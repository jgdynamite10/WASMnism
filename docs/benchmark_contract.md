# WASMnism Benchmark Contract

**Version:** 3.1  
**Date:** March 26, 2026  
**Status:** Active

---

## 1. Purpose

This document defines the measurement contract for the WASMnism benchmark.
Any compliant gateway implementation — on any platform — MUST conform to these
schemas, SLOs, and fairness rules so results are directly comparable.

A third party should be able to implement a gateway from this contract alone,
deploy it on any of the target platforms, and produce results that are
apples-to-apples comparable with every other implementation.

v3.0 replaces the v2.0 three-mode benchmark with a **two-tier suite**:

- **Primary suite** — benchmarks the rule-based content moderation pipeline
  (the real customer value prop): normalization, hashing, prohibited scan,
  PII detection, injection detection, and verdict composition. These tests
  use `ml: false` in the request body to isolate platform performance.
- **Stretch suite** — benchmarks embedded ML inference (MiniLMv2, 22.7M
  params, 53 MB) running entirely inside the WASM sandbox. This tests the
  limits of WASM compute; it is NOT the typical edge deployment pattern.

The `ml` boolean field in the request controls whether ML inference runs.
Default is `true` for backward compatibility.

---

## 2. Architecture Overview

```
┌──────────────┐      ┌─────────────────────────────────────┐
│  k6 runner   │─────▶│  Edge Moderation Gateway (WASM)     │
│              │◀─────│                                      │
└──────────────┘      │  1. Unicode NFC normalize            │
                      │  2. SHA-256 content hash             │
                      │  3. Leetspeak expansion              │
                      │  4. Prohibited content scan          │
                      │  5. PII detection (regex)            │
                      │  6. Injection detection              │
                      │  7. ML toxicity classifier           │
                      │     (MiniLMv2, Tract NNEF, in-WASM)  │
                      │  8. Policy verdict composition       │
                      └─────────────────────────────────────┘
```

### Primary Suite — Rule-Based Pipeline

| Test | Script | What It Measures |
|------|--------|-----------------|
| **Warm Light** | `warm-light.js` | Minimal-work latency (`GET /gateway/health`) |
| **Warm Policy** | `warm-policy.js` | Full 6-step rule pipeline with text, `ml: false` |
| **Concurrency Ladder (rules)** | `concurrency-ladder.js` | Scaling 1→50 VUs, rules only (`SKIP_ML=true`) |
| **Cold Start (rules)** | `cold-start.js` | WASM instantiation, no ML model load (`USE_ML=false`) |

### Stretch Suite — Embedded ML

| Test | Script | What It Measures |
|------|--------|-----------------|
| **Warm Heavy** | `warm-heavy.js` | Full moderation + ML inference (`ml: true`) |
| **Consistency (ML)** | `consistency.js` | ML latency jitter over 120s |
| **Cold Start (ML)** | `cold-start.js` | WASM instantiation + 53 MB model deserialization (`USE_ML=true`) |

All computation runs inside the WASM sandbox. The stretch suite demonstrates
that in-WASM neural network inference is feasible but has significant latency
implications (significantly higher latency than the rules-only pipeline).

---

## 3. Moderation Request / Response Schemas

### 3.1 Moderation Request

`POST /gateway/moderate` — `application/json`

```json
{
  "labels": ["safe", "unsafe"],
  "nonce": "<string>",
  "text": "The prompt text to evaluate",
  "ml": false
}
```

| Field | Type | Required | Default | Constraints |
|-------|------|----------|---------|-------------|
| `labels` | array of strings | yes | — | 1–1000 items |
| `nonce` | string | yes | — | max 256 chars |
| `text` | string | no | null | Text for rule-based + ML analysis |
| `ml` | boolean | no | `true` | Set `false` to skip ML inference |

When `ml` is `true` (or omitted) AND `text` is provided, the ML toxicity
classifier runs. When `ml` is `false`, only rule-based policy checks
execute — regardless of whether `text` is present.

### 3.2 Moderation Response

All platforms MUST return this exact JSON schema. Field order MAY vary;
field names, types, and nesting MUST NOT.

```json
{
  "verdict": "allow | block | review",
  "moderation": {
    "policy_flags": ["prohibited_term", "pii_detected", "injection_attempt"],
    "confidence": 0.0,
    "blocked_terms": ["kill", "[injection]"],
    "processing_ms": 862.1,
    "ml_toxicity": {
      "toxic": 0.001,
      "severe_toxic": 0.0001,
      "inference_ms": 858.9,
      "model": "MiniLMv2-toxic-jigsaw"
    }
  },
  "classification": { ... },
  "cache": {
    "hit": false,
    "hash": "sha256:<64 hex chars>"
  },
  "gateway": {
    "platform": "<Akamai Functions | Fastly Compute | workers>",
    "region": "<string>",
    "request_id": "<uuid>"
  }
}
```

**Validation rules:**

- `verdict` MUST be one of: `allow`, `block`, `review`.
- `moderation.policy_flags` MUST be an array (may be empty).
- `moderation.confidence` MUST be a float 0.0–1.0.
- `moderation.processing_ms` MUST reflect actual gateway processing time (including ML inference).
- `moderation.ml_toxicity` MUST be present when `ml` is true and `text` is non-empty; null/absent otherwise.
- `moderation.ml_toxicity.inference_ms` MUST reflect actual ML forward pass time.
- `cache.hit` MUST be a boolean.
- `cache.hash` MUST start with `sha256:` followed by 64 hex characters.
- `gateway.platform` MUST be one of the target platforms (`Akamai Functions`, `Fastly Compute`, `workers`).
- `gateway.request_id` MUST be a UUID v4.
- HTTP status MUST be `200` on success.

### 3.3 Verdict Logic

**Pre-check (all modes):**

| Condition | Verdict | Flag |
|-----------|---------|------|
| Input contains prohibited terms | `block` | `prohibited_term` |
| Input contains PII patterns (email, phone, SSN) | `review` | `pii_detected` |
| Input contains injection patterns (XSS, SQL) | `block` | `injection_attempt` |
| No flags | `allow` | _(none)_ |

**ML toxicity check (when `ml: true` and `text` is provided):**

| Condition | Verdict | Flag |
|-----------|---------|------|
| `toxic` or `severe_toxic` ≥ 0.80 | `block` | ML toxicity score in response |
| `toxic` ≥ 0.50 | `review` | ML toxicity score in response |
| Below thresholds | `allow` | _(none)_ |

**Merge rule:** The stricter verdict wins (block > review > allow).

### 3.4 Cache Behavior

| Endpoint | Cache Read | Cache Write |
|----------|-----------|-------------|
| `POST /gateway/moderate` | No | No |
| `POST /gateway/moderate-cached` | Yes (by label hash) | No |

Cache key: SHA-256 of normalized labels (NFC + lowercase + whitespace collapsed).

---

## 4. ML Inference Contract

### 4.1 Embedded Inference

The gateway performs ML inference **locally** inside the WASM sandbox.
There is no external inference service call. The Tract NNEF runtime
loads the model from bundled files at startup.

| Component | Detail |
|-----------|--------|
| Model | MiniLMv2-toxic-jigsaw (22.7M params) |
| Format | NNEF (Tract native) |
| Vocab | 8,000 WordPiece tokens |
| Model size | ~53 MB |
| Categories | `toxic`, `severe_toxic` |

### 4.2 Inference Timing

| Phase | Typical | Notes |
|-------|---------|-------|
| Model deserialization | Varies | Cold start only; depends on platform I/O speed |
| WordPiece tokenization | <1ms | Custom Rust tokenizer |
| Forward pass | Varies by platform | Dominant cost of ML inference |
| Total gateway processing | Varies | Including all 8 pipeline steps |

### 4.3 Headers

The gateway MUST set the following response headers:

| Header | Value |
|--------|-------|
| `Content-Type` | `application/json` |
| `X-Gateway-Platform` | `Akamai Functions`, `Fastly Compute`, or `workers` |
| `X-Gateway-Region` | Deployment region (e.g., `us-ord`) |
| `X-Gateway-Request-Id` | UUID v4, generated per request |

---

## 5. Platform KV Store Mapping

Each platform uses its native KV store:

| Platform | KV Implementation | Store Name |
|----------|------------------|------------|
| Akamai Functions (Spin) | `spin_sdk::key_value::Store` | `default` |
| Fastly Compute | `fastly::KVStore` | `moderation_cache` |
| Cloudflare Workers | `worker::kv` | `MODERATION_CACHE` |

---

## 6. Service Level Objectives (SLO)

SLOs define the performance bar. They are NOT pass/fail gates for the
benchmark; they are the reference lines on the scorecard.

### 6.1 Primary Suite SLOs

**6.1.1 Cold Start — Rules Only**

| Metric | Target | Notes |
|--------|--------|-------|
| p50 cold start | ≤ 100 ms | WASM instantiation only, no model load |
| p90 cold start | ≤ 300 ms | Includes platform scheduling variance |
| Error rate | 0% | Cold starts must not fail |

**6.1.2 Warm Light** (GET /gateway/health)

| Metric | Target | Notes |
|--------|--------|-------|
| p50 latency | ≤ 20 ms | Minimal-work, no ML |
| p95 latency | ≤ 60 ms | Includes platform overhead |
| Error rate | ≤ 0.1% | Over full benchmark run |
| Throughput | ≥ 400 RPS | At 10 concurrent connections |

**6.1.3 Warm Policy** (POST /gateway/moderate, ml: false)

| Metric | Target | Notes |
|--------|--------|-------|
| p50 latency | ≤ 30 ms | Full 6-step rule pipeline with text |
| p95 latency | ≤ 100 ms | Includes regex PII and injection scan |
| Error rate | ≤ 0.1% | Over full benchmark run |
| Throughput | ≥ 100 RPS | At 10 concurrent connections |

**6.1.4 Concurrency Ladder — Rules**

| Metric | Target | Notes |
|--------|--------|-------|
| Error rate | ≤ 5% | At peak 50 VUs, rules only |
| Latency degradation | ≤ 3x baseline | p50 at 50 VUs vs p50 at 1 VU |

### 6.2 Stretch Suite SLOs

**6.2.1 Cold Start — ML**

| Metric | Target | Notes |
|--------|--------|-------|
| p50 cold start | ≤ 3000 ms | WASM instantiation + 53 MB model deserialization |
| p90 cold start | ≤ 5000 ms | Includes platform scheduling variance |
| Error rate | 0% | Cold starts must not fail |

**6.2.2 Warm Heavy** (POST /gateway/moderate, ml: true)

| Metric | Target | Notes |
|--------|--------|-------|
| p50 latency | ≤ 1500 ms | Dominated by ML inference |
| p95 latency | ≤ 3000 ms | Includes model reload or scheduling |
| Error rate | ≤ 1% | ML inference may occasionally time out |
| Throughput | ≥ 1 RPS | At 5 concurrent connections |

**6.2.3 Consistency — ML**

| Metric | Target | Notes |
|--------|--------|-------|
| Jitter (p95/p50) | ≤ 3.0x | Predictable ML latency over 120s |
| Error rate | ≤ 5% | Over sustained run |

### 6.6 Measurement Method

- **Timing source:** Client-side (k6 `http_req_duration`). This is the
  source of truth for the scorecard.
- **Server-side timing** (`moderation.processing_ms`, `ml_toxicity.inference_ms`)
  is recorded for analysis but does not determine scorecard values.
- **Suite runner:** `bench/run-suite.sh` orchestrates all tests with a
  pre-flight health check and warm-up request. Pass `--ml` for stretch
  tests, `--cold` for cold start tests.
- **Warm-up:** The suite sends one `POST /gateway/moderate` with `ml: false`
  before starting any test.
- **Scorecard:** Generated by `bench/build-scorecard.py` comparing any two
  results directories.

---

## 7. Fairness Rules

Every platform is benchmarked under identical conditions. Any deviation
invalidates the comparison.

### 7.1 Payload Invariance

| Rule | Detail |
|------|--------|
| Same labels | `["safe", "unsafe"]` — consistent across all ML tests |
| Same prompt pool | 5 rotating prompts (see `warm-heavy.js`) |
| Same nonce pattern | `<test>-<vu>-<iter>` for traceability |

Changing the prompt pool or labels invalidates all prior results.

### 7.2 Concurrency Ladder

The `concurrency-ladder.js` test uses this progression:

| Stage | Duration | Virtual Users (VUs) |
|-------|----------|---------------------|
| Hold 1 | 30 s | 1 |
| Hold 2 | 30 s | 5 |
| Hold 3 | 30 s | 10 |
| Hold 4 | 30 s | 25 |
| Hold 5 | 30 s | 50 |

**Total:** 150 seconds. No explicit warm-up stage — the suite runner
sends a warm-up request before starting any test.

### 7.3 Multi-Region Testing

Tests are run from **3 geographic locations** to capture regional variance:

| Region | Runner Location | Purpose |
|--------|----------------|---------|
| US Central | Linode us-ord (Chicago) | Near inference service |
| Europe | Linode eu-west (London) | Transatlantic latency |
| Asia-Pacific | Linode ap-south (Singapore) | Maximum distance |

Each region runs the full benchmark suite independently.

### 7.4 Cold Start Protocol

Cold start latency is measured by `cold-start.js`. The `USE_ML` env var
controls whether ML inference runs (default: `false`).

**Rules-only cold start** (`USE_ML=false`):
1. Send `POST /gateway/moderate` with text and `ml: false`.
2. Record round-trip time (measures WASM instantiation only).
3. Wait 120 seconds for instance eviction.
4. Repeat for 10 iterations.

**ML cold start** (`USE_ML=true`):
1. Send `POST /gateway/moderate` with text and `ml: true`.
2. Record round-trip time (WASM instantiation + model deserialization).
3. Wait 120 seconds. Repeat 10 iterations.

The `--cold` flag on `run-suite.sh` runs both variants when combined with
`--ml`. Takes ~40 minutes total.

### 7.5 Deployment Configuration

| Parameter | Requirement |
|-----------|-------------|
| Memory | Platform default (document actual value) |
| CPU | Platform default (document actual value) |
| Scaling | Single instance, no auto-scale during run |
| KV Store | Platform-native (see §5) |
| Caching | No CDN or response caching; bypass if platform enables by default |
| TLS | Required (HTTPS). All platforms use TLS. |

### 7.6 ML Model Consistency

- All platforms MUST use the same model file (`model.nnef.tar`) and
  vocabulary (`vocab.txt`).
- Model files are bundled into the WASM component at build time.
- No external inference service is called.

### 7.7 Result Integrity

- Raw k6 JSON output is saved to `results/<platform>/<timestamp>/`.
- Primary suite files: `warm-light.json`, `warm-policy.json`, `concurrency-rules.json`.
- Stretch suite files: `warm-heavy.json`, `consistency-ml.json`.
- Cold start files: `cold-start-rules.json`, `cold-start-ml.json`.
- Raw results are **gitignored** (may contain IPs/hostnames).
- Scorecards are generated by `bench/build-scorecard.py` and also gitignored.
- All results from a benchmark session use the same k6 version and runner.

---

## 8. Scorecard Format

The scorecard is generated by `bench/build-scorecard.py` from the k6
JSON exports. For cross-platform comparison, run the suite against each
platform and compare any two results directories.

### 8.1 Primary Suite Table (per platform pair)

```
| Metric               | Platform A | Platform B | Ratio |
|----------------------|-----------|-----------|-------|
| Light p50            |           |           |       |
| Light p95            |           |           |       |
| Policy p50           |           |           |       |
| Policy p95           |           |           |       |
| Policy server_ms p50 |           |           |       |
| Policy RPS           |           |           |       |
| Ladder p50 (rules)   |           |           |       |
| Ladder errors        |           |           |       |
| Cold (rules) p50     |           |           |       |
```

### 8.2 Stretch Suite Table (per platform pair)

```
| Metric               | Platform A | Platform B | Ratio |
|----------------------|-----------|-----------|-------|
| Heavy p50            |           |           |       |
| Heavy p95            |           |           |       |
| ML infer p50         |           |           |       |
| Heavy RPS            |           |           |       |
| Consistency p50 (ML) |           |           |       |
| Jitter (p95/p50)     |           |           |       |
| Cold (ML) p50        |           |           |       |
```

### 8.3 Cost Table

```
| Platform | $/1M (rules) | $/1M (ML) |
|----------|-------------|-----------|
| Akamai   |             |           |
| Fastly   |             |           |
| Workers  |             |           |
```

---

## 9. Moderation Validation

Before running performance benchmarks, each platform MUST pass the moderation
validation suite to prove correctness. The suite sends JSON payloads to
`POST /gateway/moderate` with various label/text combinations and asserts
identical verdicts across all platforms.

### 9.1 Validation Scenarios

| # | Name | Labels | Text | Expected Verdict | Expected Flag |
|---|------|--------|------|-----------------|---------------|
| S1 | Clean input + ML | `["cat","dog","<unique>"]` | `"A peaceful sunset over the mountains"` | `allow` | `ml_toxicity.toxic < 0.50` |
| S2 | XSS injection | `["<script>alert(1)</script>"]` | — | `block` | `injection_attempt` |
| S3 | Prohibited terms | `["kill","bomb","cat"]` | — | `block` | `prohibited_term` |
| S4 | PII email | `["cat","dog"]` | `"contact user@example.com"` | `review` | `pii_detected` |
| S5 | PII phone | `["cat"]` | `"call 555-123-4567"` | `review` | `pii_detected` |
| S6 | Leetspeak evasion | `["h@t3","k1ll"]` | — | `block` | `prohibited_term` |
| S7 | SQL injection | `["cat'; DROP TABLE users;--"]` | — | `block` | `injection_attempt` |
| S8 | Cache hit | _(repeat S1 labels, no text)_ | — | `allow` | `cache.hit: true` |
| S9 | ML toxicity | `["safe","unsafe"]` | `"You are pathetic and disgusting..."` | `block` or `review` | `ml_toxicity.toxic ≥ 0.50` |

S1 uses a timestamped label to guarantee a cache miss.

### 9.2 Additional Assertions (S1 only)

- `moderation.ml_toxicity` MUST be present (text was provided).
- `moderation.ml_toxicity.toxic` MUST be below 0.50 (safe text).
- `moderation.ml_toxicity.inference_ms` MUST be positive.
- `moderation.processing_ms` MUST be positive.

### 9.3 Running Validation

```bash
./bench/run-validation.sh <platform> <gateway_url>
```

Exit code 0 = all 9 scenarios passed. Any non-zero exit = at least one check failed.

All three platforms must produce 9/9 pass before performance benchmarks are run.

---

## 10. Versioning

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-03-05 | Initial contract (thin proxy architecture) |
| 2.0 | 2026-03-10 | Moderation gateway: 3 benchmark modes, multi-region, cold start protocol, KV store caching, updated scorecard |
| 2.1 | 2026-03-25 | Safety labels, image blocklist, moderation validation suite (9 scenarios), text field extraction |
| 3.0 | 2026-03-26 | Embedded ML toxicity classifier; 5-test benchmark suite (cold start, warm light, warm heavy, concurrency ladder, consistency); removed external inference proxy; updated SLOs for ML workload |
| 3.1 | 2026-03-26 | Two-tier benchmark: primary (rules, `ml:false`) and stretch (ML). Added `ml` request field, `warm-policy.js`, rules-only cold start. Updated SLOs and scorecard format. |
