# WASMnism Tier 2 Benchmark Contract

**Version:** 1.0
**Status:** Active
**Last revised:** 2026-04-28
**Companion to:** `docs/benchmark_contract.md` (Tier 1, v3.4)

---

## 1. Purpose

This contract defines the methodology for benchmarking **Tier 2** of WASMnism — ML-inference content moderation deployed on **two fundamentally different platforms**:

| Platform | Branch | Runtime | Execution model |
|----------|--------|---------|-----------------|
| Akamai Functions | `ml-inference` | Spin (WASM) | **Per-request WASM instance** — every request spawns a fresh component, executes, tears down |
| AWS Lambda | `ml-inference` | Native ARM64 | **Warm execution context** — function instance reused across many invocations until idle/replaced |

These two runtime models have **fundamentally different ML cost curves**, and any Tier 2 measurement that does not separately characterise cold-ML, warm-ML, and cache-hit behaviour is misleading. This contract makes the differences measurable, comparable, and disclosable.

The Tier 1 contract (v3.4) explicitly excludes ML content. Tier 2 picks up where Tier 1 stops.

---

## 2. Architecture

### 2.1 Per-platform execution model

```
Akamai Functions (Spin/WASM)                    AWS Lambda (native ARM64)
┌─────────────────────────┐                     ┌─────────────────────────┐
│ Request 1 arrives       │                     │ Request 1 arrives       │
│ ↓                       │                     │ ↓                       │
│ Spawn fresh WASM inst.  │                     │ Cold start container?   │
│ ↓                       │                     │ ↓ (if cold)             │
│ OnceLock init           │                     │ OnceLock init           │
│ → load /models/...nnef  │                     │ → load .../model.nnef   │
│ → ~600 ms               │                     │ → ~200 ms               │
│ Tract inference ~10 ms  │                     │ Tract inference ~10 ms  │
│ Return response         │                     │ Return response         │
│ Discard WASM instance   │                     │ Container stays warm    │
│                         │                     │                         │
│ Request 2 arrives       │                     │ Request 2 arrives       │
│ ↓                       │                     │ ↓                       │
│ Spawn fresh WASM inst.  │                     │ Reuse warm container    │
│ ↓                       │                     │ ↓                       │
│ OnceLock init AGAIN     │                     │ OnceLock returns cached │
│ → reload model ~600 ms  │                     │ → no model reload       │
│ Tract inference ~10 ms  │                     │ Tract inference ~10 ms  │
│ Return response         │                     │ Return response         │
└─────────────────────────┘                     └─────────────────────────┘
```

This asymmetry is **a feature of the comparison, not a bug**. Reporting only "average ML latency" hides both platforms' true cost profiles. Reporting cold/warm/cache as three named scenarios surfaces them.

### 2.2 Code-level conditional ML

Both adapters implement two layers of conditional model loading:

**Per-request opt-in** (caller-controlled, both platforms):

```rust
let classifier = if mod_req.ml { get_classifier() } else { None };
```

Caller sets `"ml": true` in the request body to opt into model loading. `false` short-circuits before `OnceLock::get_or_init()` ever runs, paying zero ML cost.

**Deploy-level opt-out** (operator-controlled, Akamai only):

```rust
fn local_ml_enabled() -> bool {
    variables::get("local_ml")
        .map(|v| v.eq_ignore_ascii_case("true") || v.trim() == "1")
        .unwrap_or(false)
}
```

`local_ml` Spin variable. When `false`, `get_classifier()` returns `None` regardless of request. Used to ship the same WASM binary as a Tier 1 (rules-only) deployment without recompiling.

### 2.3 Cache backends

| Platform | Backend | Used by |
|----------|---------|---------|
| Akamai Functions | Spin Key-Value (regional storage) | `kv_get`, `kv_put`, `kv_blocklist_image` |
| AWS Lambda | DynamoDB (`moderation-cache` table, us-east-1) | `dynamo_get`, `dynamo_put` |

Both are integral parts of the Tier 2 cost and latency story — must be exercised in benchmarks (see Section 7) and disclosed in the scorecard (Section 9).

---

## 3. Endpoint Matrix

Both Tier 2 deployments expose the same endpoints. The choice of endpoint × `ml` flag combination determines what is being measured.

| Endpoint | `ml` flag | What it measures | Used by k6 script |
|----------|-----------|------------------|-------------------|
| `POST /gateway/moderate` | `false` | Rules-only baseline on Tier 2 binary (handler-weight isolation vs Tier 1) | `bench/clip-rules-only.js` (variant) |
| `POST /gateway/moderate` | `true`  | Clean ML path: rules + ML, no cache, no multipart, no image blocklist | `bench/cold-ml.js`, `bench/warm-ml.js` |
| `POST /api/clip/moderate` | `false` | Full handler weight without ML (cache + multipart + blocklist + rules) | `bench/clip-rules-only.js` |
| `POST /api/clip/moderate` | `true`  | Full production-shape: rules + cache + ML + image blocklist | `bench/cache-hit.js`, `bench/mixed-load.js` |

**Default endpoint for ML benchmarks:** `/gateway/moderate` with `ml: true`. `/api/clip/moderate` is reserved for cache-hit and mixed-load scenarios where cache + image blocklist behaviour is part of the test surface.

---

## 4. Moderation Request / Response Schemas

### 4.1 Request — JSON body (`Content-Type: application/json`)

```json
{
  "labels": ["safe", "unsafe"],
  "nonce": "tier2-<test>-<vu>-<iter>",
  "text": "candidate text to moderate",
  "ml": true
}
```

| Field | Type | Required | Tier 2 semantics |
|-------|------|----------|------------------|
| `labels` | `string[]` (1–1000) | yes | Candidate category labels |
| `nonce` | `string` (≤256 chars) | yes | Trace identifier; mirrored into response `gateway.request_id` |
| `text` | `string?` | no | The content to moderate (with rules + ML) |
| `ml` | `bool` | no — default `true` | Opt-in/out of ML inference. Critical for Tier 2: **always set explicitly** in benchmarks |

**Note on default:** The `ModerationRequest` struct in `core/` defaults `ml` to `true` if absent. Benchmarks MUST set `ml` explicitly — never rely on the default — so that scripts are self-documenting and a future schema change can't silently flip ML behaviour.

### 4.2 Response — JSON

```json
{
  "verdict": "allow" | "block",
  "moderation": {
    "policy_flags": [...],
    "blocked_terms": [...],
    "confidence": 0.0,
    "processing_ms": 0.04,
    "ml_used": true
  },
  "classification": {
    "results": [{"label": "...", "score": 0.0, "similarity": 0.0}],
    "metrics": {
      "model_load_ms": 0.0,
      "input_encoding_ms": 0.0,
      "text_encoding_ms": 0.0,
      "similarity_ms": 0.0,
      "total_inference_ms": 0.0,
      "num_candidates": 1
    }
  },
  "cache": {"hit": false, "hash": "sha256:..."},
  "gateway": {"platform": "...", "region": "...", "request_id": "..."}
}
```

**Tier 2-specific fields the scorecard tracks:**

| Field | Source | Notes |
|-------|--------|-------|
| `classification.metrics.total_inference_ms` | Tract self-reported | Pure inference time, **excludes** model load |
| `classification.metrics.model_load_ms` | Tract self-reported | **Beware:** on Spin/WASM this is reported as `0.0` even when model loaded — see Section 6.5 |
| `cache.hit` | Server | Whether the response came from KV/DynamoDB cache short-circuit |
| `moderation.processing_ms` | Server | Rules pipeline only |

**Authoritative latency source:** k6's `http_req_duration` (client wall-clock). Server-side metrics are recorded for analysis but do not determine scorecard values.

### 4.3 Health response (Tier 2-specific fields)

`GET /gateway/health` on Tier 2 deployments returns Tier 1 fields plus:

| Field | Type | Notes |
|-------|------|-------|
| `ml_model_file` | `bool` | `model.nnef.tar` exists in the expected mount path |
| `ml_vocab_file` | `bool` | `vocab.txt` exists |
| `ml_classifier_ready` | `bool` | `OnceLock` is populated. **On Akamai always `false` for fresh requests** — health is a separate component invocation. |
| `ml_status` | `string` | Free-form status from `CLASSIFIER_ERROR`: `"ok: model=…"`, `"disabled (local_ml != true)"`, or error detail |

Pre-flight validation (`bench/run-validation.sh`) MUST verify these fields parse correctly before any benchmark begins.

---

## 5. Platform Mapping

| Concern | Akamai Functions | AWS Lambda |
|---------|------------------|------------|
| Compute runtime | Spin (WASM) | `provided.al2023` (native ARM64) |
| Process lifetime | One request | Many requests until idle (~5–15 min) |
| `OnceLock` semantics | Per-request init | Per-warm-context init |
| Model mount | `/models/toxicity/` (Spin filesystem mount declared in `spin.toml`) | `/var/task/models/toxicity/` (Lambda layer / `--include` deploy) |
| Cache | Spin Key-Value (`Store::open_default()`) | DynamoDB table `moderation-cache` (us-east-1) |
| Region availability | Global edge PoPs (~4,200) | **us-east-1 only** (single region) |
| Cold-start latency profile | Every request reloads model | First call after idle reloads; warm calls reuse |

---

## 6. Service Level Objectives (SLO)

SLOs are reference lines on the scorecard, **not pass/fail gates**. They define what each scenario *should* look like under healthy operation.

### 6.1 Cold ML (single-shot, no prior warmup)

Definition: first ML request to a fresh execution context. On Akamai every request qualifies (per-request WASM); on Lambda only the first request after idle qualifies.

**Measurement protocol:** see Section 7.1.

| Platform | Metric | Target | Notes |
|----------|--------|--------|-------|
| Akamai Functions | p50 cold ML | ≤ 1,000 ms | ~600 ms model load + ~10 ms inference + network |
| Akamai Functions | p90 cold ML | ≤ 1,500 ms | Tail includes Tract first-pass JIT |
| AWS Lambda | p50 cold ML | ≤ 600 ms | Cold container + ~200 ms model load |
| AWS Lambda | p90 cold ML | ≤ 1,200 ms | Tail includes Lambda init |

### 6.2 Warm ML (after explicit warmup, sustained load)

Definition: ML requests after `N=10` warmup calls have been sent and discarded.

**Measurement protocol:** see Section 7.2.

| Platform | Metric | Target | Notes |
|----------|--------|--------|-------|
| Akamai Functions | p50 warm ML | ≤ 1,000 ms | **Expected to roughly equal cold ML** — per-request WASM has no warm tier |
| Akamai Functions | p90 warm ML | ≤ 1,500 ms | |
| AWS Lambda | p50 warm ML | ≤ 50 ms | Model in memory, only inference + network |
| AWS Lambda | p90 warm ML | ≤ 150 ms | |

The expected divergence between Akamai warm-ML and Lambda warm-ML (≥ 10×) is **the headline architectural finding** of Tier 2 and must be prominently displayed on the scorecard.

### 6.3 Cache hit

Definition: identical payload sent N times in succession; second through Nth request should hit KV/DynamoDB cache and short-circuit before reaching the ML pipeline.

**Measurement protocol:** see Section 7.3.

| Platform | Metric | Target | Notes |
|----------|--------|--------|-------|
| Akamai Functions | p50 cache-hit | ≤ 50 ms | Spin KV regional read + JSON serialise + network |
| Akamai Functions | p95 cache-hit | ≤ 150 ms | |
| AWS Lambda | p50 cache-hit | ≤ 30 ms | DynamoDB read in same region |
| AWS Lambda | p95 cache-hit | ≤ 100 ms | |
| Both | Cache hit rate (call 2..N) | ≥ 95% | Cache MUST short-circuit |

### 6.4 Mixed load (production-realistic)

Definition: 1,000-request sample with 95% rules-only requests + 5% ML requests, of which 90% are repeated-payload (cache-hit-eligible).

**Measurement protocol:** see Section 7.4.

| Platform | Metric | Target | Notes |
|----------|--------|--------|-------|
| Both | Overall p50 | ≤ 50 ms | Dominated by the 95% rules path |
| Both | Overall p95 | ≤ 200 ms | The 5% ML pulls the tail |
| Both | Overall p99 | ≤ 1,500 ms | Cold-ML cache misses dominate |
| Both | Error rate | ≤ 1% | |

### 6.5 Server-reported metrics caveat (do not use for scorecard latency)

`classification.metrics.model_load_ms` and `total_inference_ms` are reported by Tract from inside the inference pipeline. They have known issues:

- On **Spin/WASM** the model load happens inside `OnceLock::get_or_init()` *before* Tract starts timing. As a result `model_load_ms` is reported as `0.0` even when ~600 ms was just spent loading the NNEF file. **Do not use this field as evidence the model loaded or did not load.** Use k6 wall-clock duration as the authoritative source.
- On **Lambda** the same caveat applies, but it matters less because the model only loads once per warm container — most `model_load_ms` reads are genuine zero.

The scorecard MUST cite k6 `http_req_duration` for all latency claims and treat server-reported timing as secondary evidence only.

---

## 7. Measurement Methodology

### 7.1 Cold ML protocol

**Script:** `bench/cold-ml.js`

```
1. Send single POST /gateway/moderate with body {"labels":[...],"text":"...","ml":true}
2. Record k6 http_req_duration
3. Wait 60 seconds (or longer — see per-platform notes)
4. Repeat for N=10 iterations
5. Report each iteration value individually + p50/p90 across iterations
```

**Per-platform notes:**

- **Akamai:** Every request is cold by definition. The 60-second idle is unnecessary on Akamai but kept for parity. Spin spawns a fresh WASM instance every time regardless.
- **Lambda:** 60-second idle is **not sufficient** to guarantee container retirement. AWS keeps containers warm for ~5–15 minutes typically. To force a true cold start: redeploy the function immediately before the run, OR wait ≥ 20 minutes between iterations, OR use Lambda Invocation Type: `Event` to avoid warm reuse. Document which method was used in the result manifest.
- **Reporting:** Cold-ML scorecard cells MUST show **all 10 individual values**, not just the median, because the variance is informative.

### 7.2 Warm ML protocol

**Script:** `bench/warm-ml.js`

```
1. Send N_WARMUP=10 POST /gateway/moderate with ml:true
   → discard these from results
2. Sustained load for 60 seconds at constant 5 VUs, ml:true throughout
3. Report p50, p90, p95, p99 of http_req_duration across the 60-second window
4. Verify: at least one ML inference per VU (otherwise increase iterations)
```

**Why N=10 warmup, not lower:** Lambda's first 1–3 invocations may include init.go() overhead beyond model loading. Discarding 10 ensures any per-instance JIT or library init has settled. On Akamai N is irrelevant (every request reloads), but parity matters for cross-platform comparison.

**5 VUs, not higher:** Tier 2 ML throughput is intentionally low (each ML call costs hundreds of ms on Akamai). Higher VU counts would push latency through queue saturation rather than reflecting platform compute speed. The 50–100 RPS target captures realistic small-team production load.

### 7.3 Cache-hit protocol

**Script:** `bench/cache-hit.js`

```
1. Generate 1 unique payload P with ml:true
2. Send N_PRIME=2 POST /api/clip/moderate with P → primes the cache
3. Send N_HIT=20 identical POSTs with P → should all hit cache
4. Verify: response.cache.hit == true for ≥ 19 of the 20 hits
5. Report p50, p95, p99 of http_req_duration across the 20 hits
6. Bonus: send 1 fresh unique payload to verify cache is bounded (not measured)
```

**Why N_PRIME=2:** First call always misses (computes verdict, writes to cache). Second call MAY miss if cache write hasn't propagated (Spin KV is eventually-consistent). Two primes guarantee the third+ call sees the cache.

### 7.4 Mixed-load protocol

**Script:** `bench/mixed-load.js`

```
1. Build a payload pool:
   - 50 unique rules-only payloads (text without prohibited terms or PII)
   - 5 unique ML-trigger payloads (text needing classifier judgement)
2. Pre-seed cache for 4 of the 5 ML payloads (N_PRIME=2 each)
3. Run for 5 minutes at constant 10 VUs, each iteration:
   - 95% chance: pick rules-only payload, send with ml:false
   - 5% chance: pick ML payload — 80% from pre-seeded set (cache-eligible),
                                  20% from uncached set (forces ML)
4. Report:
   - Overall p50, p95, p99
   - Per-bucket p50 (rules-only / ML-cache-hit / ML-cold)
   - Cache hit rate among ML calls
```

This is the closest the suite gets to realistic production traffic shape. It is the headline mixed-tier number for the scorecard.

### 7.5 Suite warm-up and pre-flight

The suite runner (`bench/run-suite.sh` Tier 2 mode, T2R4) MUST:

1. Run `bench/run-validation.sh` against both Tier 2 endpoints first — verify health endpoint shape, basic moderate request, ML response schema.
2. For each platform, send 1 warm-up `POST /gateway/moderate` with `ml:false` before any test starts (network warmup, not ML warmup).
3. Each individual ML test (cold-ml, warm-ml) implements its own ML-specific warmup as defined above.

### 7.6 Multi-region testing

Tests run from **3 GCP regions** (per Tier 1 contract Section 7.3.1):

- `gcp-us-east` (us-east4-c, Virginia)
- `gcp-eu-west` (europe-west1-b, Belgium)
- `gcp-ap-southeast` (asia-southeast1-b, Singapore)

**Regional interpretation per platform:**

| Platform | Multi-region significance |
|----------|---------------------------|
| Akamai Functions | Genuine — global edge PoPs; us-east → US PoPs, eu-west → EU PoPs, ap-southeast → APAC PoPs |
| AWS Lambda | **Latency-only — Lambda is single-region (us-east-1)**. EU and APAC runners measure cross-Atlantic / cross-Pacific network latency to us-east-1. This is a known Lambda fairness limitation; see Section 8.2. |

---

## 8. Fairness Rules

### 8.1 Payload Invariance

Same labels and prompt patterns across both Tier 2 platforms (per Tier 1 contract Section 7.1):

- Labels: `["safe", "unsafe"]`
- Prompt pool: shared with Tier 1 (`bench/warm-policy.js` source) extended with 5 ML-trigger prompts
- Nonce pattern: `tier2-<test>-<vu>-<iter>`

### 8.2 Single-region Lambda disclosure (mandatory)

The Tier 2 scorecard MUST disclose, prominently:

> AWS Lambda is benchmarked in **us-east-1 only**. Latency from European and Asia-Pacific GCP runners to us-east-1 reflects **transcontinental network distance**, not Lambda's compute performance. To compare regional latency fairly, Akamai Functions (multi-PoP) and Lambda (single-region) numbers should be read together with the network distance contribution called out separately. Multi-region Lambda deployments would close some of this gap but are out of scope for this benchmark — the question being answered is "what does Tier 2 ML cost on each platform with a single deployment", not "what is the theoretical minimum after multi-region engineering work."

### 8.3 OnceLock asymmetry disclosure (mandatory)

The Tier 2 scorecard MUST disclose, prominently:

> Akamai Functions runs each request in a fresh WASM instance — the model loads from disk every time, costing ~600 ms on every ML invocation. AWS Lambda holds the model in memory across warm container invocations — the model loads once per container (~200 ms), then subsequent ML calls cost ~10 ms each. **This is a real architectural difference**, not a benchmark artefact. Whether it is good or bad depends on workload: low-volume ML (occasional calls, long idle gaps) penalises Akamai's per-request reload but minimises Lambda's cost per call too; high-volume ML (sustained traffic) lets Lambda amortise the model load across thousands of warm invocations while Akamai keeps paying the reload tax forever.

### 8.4 Cache backend disclosure

DynamoDB (Lambda) and Spin KV (Akamai) have different latency characteristics. Cache-hit numbers reflect both the platform compute path AND the cache read latency. Disclose this in the scorecard:

> Cache-hit latency on Lambda includes a DynamoDB read round-trip in us-east-1 (typically 5–15 ms). Cache-hit latency on Akamai includes a Spin KV read (regional, usually < 5 ms). The cache backend is part of each platform's surface area and is not equalised.

### 8.5 Pre-warmup honesty

Every ML test MUST document its warmup protocol (N, idle gap, force-cold method) in the result manifest. Cold-ML and warm-ML scorecard cells MUST be clearly labelled — never report a single number for "ML latency" without specifying the scenario.

### 8.6 Origin Bias

Tier 2 benchmarks run from **GCP only** (no Linode-from-Akamai concern, since neither Tier 2 platform is owned by Linode). The Tier 1 origin bias discussion (Tier 1 contract Section 7.3.2) does not apply to Tier 2.

---

## 9. Scorecard Format

The Tier 2 scorecard MUST contain, at minimum:

1. **Executive summary** — three-row verdict (cold ML, warm ML, mixed load) with platform winners
2. **Architecture asymmetry disclosure** (Section 8.3 verbatim)
3. **Single-region Lambda disclosure** (Section 8.2 verbatim)
4. **Cold ML latency** — per region, per platform, **all 10 individual values** + p50/p90
5. **Warm ML latency** — per region, per platform, p50/p90/p95/p99 + warmup protocol used
6. **Cache-hit latency** — per region, per platform, p50/p95 + cache hit rate
7. **Mixed-load latency** — per region, per platform, overall p50/p95/p99 + per-bucket breakdown
8. **Cost analysis** — cost per 1M ML inferences under each scenario (cold / warm / cache-hit / mixed). See companion file `templates/cost_analysis_tier2_template.md` (T2R6).
9. **Reproduce instructions** — `make bench-tier2-gcp` invocation with exact env vars
10. **Methodology notes** — cite this contract version (1.0); inherit applicable Tier 1 notes (DNS, connection reuse, single-source-IP)

The Tier 2 scorecard is **separate from** the Tier 1 scorecard. They serve different audiences and answer different questions. Cross-reference where appropriate but do not merge.

---

## 10. ML Validation

`bench/run-validation.sh` Tier 2 mode (T2R3 extends `validate-results.py`) MUST verify:

| Scenario | Endpoint | `ml` | Expected |
|----------|----------|------|----------|
| S1 Health | `GET /gateway/health` | n/a | 200 OK; `ml_model_file: true`; `ml_vocab_file: true`; `ml_status` non-empty |
| S2 Echo | `POST /gateway/echo` | n/a | 200 OK |
| S3 Mock-classify | `POST /gateway/mock-classify` | n/a | 200 OK |
| S4 Rules clean | `POST /gateway/moderate` | `false` | `verdict: "allow"` |
| S5 Rules block | `POST /gateway/moderate` (with prohibited term) | `false` | `verdict: "block"`, `blocked_terms` non-empty |
| S6 Rules cached | `POST /gateway/moderate-cached` | `false` | 200 OK; `cache.hit` reflects state |
| S7 Full pipeline rules-only | `POST /api/clip/moderate` | `false` | 200 OK; `classification.metrics.total_inference_ms == 0.0` |
| S8 Full pipeline ML clean | `POST /api/clip/moderate` | `true` | 200 OK; `verdict: "allow"`; non-zero confidence |
| **S9 Full pipeline ML toxic** | `POST /api/clip/moderate` (with toxic text) | `true` | 200 OK; `verdict: "block"` (rules) OR non-trivial ML confidence (Tract) |

**S9 is the new Tier 2 scenario.** `validate-results.py` (T2R3) treats S9 absence as Tier-2 invalid.

---

## 11. Versioning

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-04-28 | Initial Tier 2 contract. Authored after Tier 2 deploy + architecture fix (commits `0f5be3f`, `1f31948`). |

Future versions will track:
- Changes to `OnceLock` semantics on either platform
- Changes to the toxicity model (size, version, vocab)
- Addition or removal of cache backends
- Changes to the cold/warm/cache-hit/mixed-load scenario definitions

Bumps follow semver: major for incompatible scorecard changes, minor for new scenarios, patch for clarifications.

---

## Cross-references

- Tier 1 contract: `docs/benchmark_contract.md` v3.4
- Architecture review: `~/.cursor/plans/tier2_akamai_architecture_review_a8f3c102.plan.md` (private)
- Rollout plan: `~/.cursor/plans/benchmark_rollout_coordination_b2f3a91d.plan.md` (private)
- Tier 2 scorecard template: `templates/scorecard_template_tier2.md` (T2R6, pending)
- Tier 2 cost model: `cost/analyze-tier2-costs.py` (T2R5, pending)
