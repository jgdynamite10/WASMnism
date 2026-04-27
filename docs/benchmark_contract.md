# WASMnism Benchmark Contract

**Version:** 3.4  
**Date:** April 14, 2026  
**Status:** Active

---

## 1. Purpose

This document defines the measurement contract for the WASMnism benchmark.
Any compliant gateway implementation — on any platform — MUST conform to these
schemas, SLOs, and fairness rules so results are directly comparable.

A third party should be able to implement a gateway from this contract alone,
deploy it on any of the target platforms, and produce results that are
apples-to-apples comparable with every other implementation.

v3.0 replaces the v2.0 three-mode benchmark with a **rules-only suite** on
this branch: benchmarks the rule-based content moderation pipeline (the
real customer value prop): normalization, hashing, leetspeak expansion,
prohibited scan, PII detection, injection detection, and verdict composition.

The `ml` boolean field remains in the request schema for schema stability
across branches; on Tier 1 (rules-only) it defaults to `false` and ML
inference is not available. ML benchmarking and embedded inference are
defined on the `ml-inference` branch.

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
                      │  7. Policy verdict composition       │
                      └─────────────────────────────────────┘
```

### Primary Suite — Rule-Based Pipeline

| Test | Script | What It Measures |
|------|--------|-----------------|
| **Warm Light** | `warm-light.js` | Minimal-work latency (`GET /gateway/health`) |
| **Warm Policy** | `warm-policy.js` | Full 7-step rule pipeline with text, `ml: false` |
| **Concurrency Ladder (rules)** | `concurrency-ladder.js` | Scaling 1→50 VUs, rules-only ladder |
| **Sustained Peak** | `constant-50vu.js` | 50 VUs constant for 60s |
| **Cold Start (rules)** | `cold-start.js` | Post-idle round-trip overhead (CDN connection warmth + compute) |

### Extended Suite — High Concurrency & Stress

| Test | Script | What It Measures |
|------|--------|-----------------|
| **Full Concurrency Ladder** | `concurrency-ladder-full.js` | Scaling 1→1,000 VUs (60s per step, 7 min total) |
| **Soak** | `soak-500vu.js` | 500 VUs sustained for 10 min; reveals GC, leaks, throttling |
| **Spike** | `spike-2000vu.js` | Ramp 0→2,000 in 10s, hold 60s; finds breaking point |

The extended suite requires runners with ≥4 vCPU / 16 GB (e.g., GCP
`e2-standard-4`). For spike tests above 1,000 VUs, distribute load
across multiple runners (each handles `SPIKE_VUS / N` where N = runner count).

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
| `text` | string | no | null | Text for rule-based analysis |
| `ml` | boolean | no | `false` | ML inference is not available on Tier 1; keep `false` |

On this branch, only rule-based policy checks run. The `ml` field is
reserved for schema compatibility with the `ml-inference` branch and MUST
be `false` for benchmark requests.

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
    "processing_ms": 862.1
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
- `moderation.processing_ms` MUST reflect actual gateway processing time for the rules pipeline.
- `cache.hit` MUST be a boolean.
- `cache.hash` MUST start with `sha256:` followed by 64 hex characters.
- `gateway.platform` MUST be one of the target platforms (`Akamai Functions`, `Fastly Compute`, `workers`).
- `gateway.request_id` MUST be a UUID v4.
- HTTP status MUST be `200` on success.

### 3.3 Verdict Logic

**Pre-check:**

| Condition | Verdict | Flag |
|-----------|---------|------|
| Input contains prohibited terms | `block` | `prohibited_term` |
| Input contains PII patterns (email, phone, SSN) | `review` | `pii_detected` |
| Input contains injection patterns (XSS, SQL) | `block` | `injection_attempt` |
| No flags | `allow` | _(none)_ |

**Merge rule:** When multiple policy conditions apply, the stricter verdict
wins (block > review > allow).

### 3.4 Cache Behavior

| Endpoint | Cache Read | Cache Write |
|----------|-----------|-------------|
| `POST /gateway/moderate` | No | No |
| `POST /gateway/moderate-cached` | Yes (by label hash) | No |

Cache key: SHA-256 of normalized labels (NFC + lowercase + whitespace collapsed).

---

## 4. Response Headers

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

Scorecards report this as **post-idle round-trip overhead**; measurement protocol and semantics are defined in **§7.4** (not “WASM cold start” or instance eviction alone).

| Metric | Target | Notes |
|--------|--------|-------|
| p50 cold start | ≤ 100 ms | Rules only (`ml: false`, no model). End-to-end RTT after 120s idle: **connection re-establishment (e.g. TCP/TLS, CDN path) plus compute** — see §7.4 per platform. |
| p90 cold start | ≤ 300 ms | Includes tail latency on the client–edge path and platform variance. |
| Error rate | 0% | Post-idle requests must not fail |

**6.1.2 Warm Light** (GET /gateway/health)

| Metric | Target | Notes |
|--------|--------|-------|
| p50 latency | ≤ 20 ms | Minimal-work health check |
| p95 latency | ≤ 60 ms | Includes platform overhead |
| Error rate | ≤ 0.1% | Over full benchmark run |
| Throughput | ≥ 400 RPS | At 10 concurrent connections |

**6.1.3 Warm Policy** (POST /gateway/moderate, ml: false)

| Metric | Target | Notes |
|--------|--------|-------|
| p50 latency | ≤ 30 ms | Full 7-step rule pipeline with text |
| p95 latency | ≤ 100 ms | Includes regex PII and injection scan |
| Error rate | ≤ 0.1% | Over full benchmark run |
| Throughput | ≥ 100 RPS | At 10 concurrent connections |

**6.1.4 Concurrency Ladder — Rules**

| Metric | Target | Notes |
|--------|--------|-------|
| Error rate | ≤ 5% | At peak 50 VUs, rules only |
| Latency degradation | ≤ 3x baseline | p50 at 50 VUs vs p50 at 1 VU |

### 6.1.5 Extended Suite SLOs

**Full Concurrency Ladder (1→1,000 VUs)**

| Metric | Target | Notes |
|--------|--------|-------|
| Error rate at 500 VUs | ≤ 5% | Platform should handle 500 concurrent without failures |
| Error rate at 1,000 VUs | ≤ 10% | Some degradation acceptable at extreme concurrency |
| Latency degradation | ≤ 5x baseline | p50 at 1,000 VUs vs p50 at 1 VU |

**Soak (500 VUs, 10 min)**

| Metric | Target | Notes |
|--------|--------|-------|
| Error rate | ≤ 5% | Sustained load must remain stable |
| p95 latency | ≤ 2,000 ms | No runaway latency growth over time |
| Latency drift | ≤ 20% | p50 in last minute vs first minute |

**Spike (0→2,000 VUs)**

| Metric | Target | Notes |
|--------|--------|-------|
| Error rate | ≤ 20% | High concurrency; some rejection expected |
| Recovery time | ≤ 10s | After ramp-down, latency returns to baseline |

### 6.2 Measurement Method

- **Timing source:** Client-side (k6 `http_req_duration`). This is the
  source of truth for the scorecard.
- **Server-side timing** (`moderation.processing_ms`) is recorded for
  analysis but does not determine scorecard values.
- **Suite runner:** `bench/run-suite.sh` orchestrates all tests with a
  pre-flight health check and warm-up request. Pass `--cold` for cold start
  tests.
- **Warm-up:** The suite sends one `POST /gateway/moderate` with `ml: false`
  before starting any test.
- **Scorecard:** Generated by `bench/build-scorecard.py` comparing any two
  results directories.

### 6.3 DNS Resolution Behavior

k6 uses its own DNS resolver with the following defaults:

| Setting | Default | Implication |
|---------|---------|-------------|
| `ttl` | `5m` | DNS records are cached for 5 minutes regardless of the actual record TTL |
| `select` | `random` | When multiple A/AAAA records are returned, k6 picks one at random |
| `policy` | `preferIPv4` | IPv4 addresses are preferred over IPv6 |

**Implications for CDN-fronted platforms:** Anycast platforms (Akamai, Fastly,
Cloudflare) typically return a single anycast IP, so DNS TTL handling has
minimal impact — network-layer anycast routing determines which PoP handles the
request. However, platforms using DNS-based load balancing (multiple A records
with short TTLs) will not see k6 rotate targets within a 5-minute window.

k6 does **not** re-resolve DNS per request. DNS resolution occurs at connection
creation time. With HTTP keep-alive enabled (the default), connections are
reused across multiple requests, so DNS resolution is infrequent during
steady-state testing.

### 6.4 Connection Reuse

k6 enables HTTP keep-alive by default. During steady-state and ladder tests,
TCP/TLS connections are reused across requests. This means:

- DNS resolution happens once per connection, not per request.
- TLS handshake overhead is amortized across many requests.
- Results reflect **warm connection** performance for most of the test duration.
- The cold start test (§7.4) is the only test designed to measure post-idle
  connection re-establishment.

### 6.5 Single-Source-IP Limitation

Each geographic region runs from a **single runner machine** (1 public IP).
All virtual users (VUs) share that IP. This means:

- All load from a region hits the nearest PoP as determined by anycast or
  geo-DNS for that single IP address.
- Intra-PoP load balancing across multiple edge servers is not exercised the
  way it would be with distributed real-user traffic from many IPs.
- Results represent **best-case single-PoP performance**, not a full CDN mesh
  exercise.
- This is disclosed in each scorecard under "Methodology Notes."

### 6.6 Ramp-Up and CDN Mapping

CDN platforms dynamically adjust mapping and capacity based on traffic patterns.
Rapid ramp-ups can produce misleading results if the CDN has not had time to
distribute load.

| Test | Ramp Profile | CDN Impact |
|------|-------------|------------|
| Concurrency ladder | 60s per step (1→50 VUs) | CDN-friendly — gradual increase |
| Sustained peak | 30s ramp to 50 VUs | Moderate — short ramp but stable hold |
| Spike test | 0→2,000 VUs in 10s | Aggressive — may expose single-server limits before CDN redistributes |

The spike test intentionally stresses sudden-burst handling, but results should
be interpreted with the understanding that CDN mapping may not have fully
adjusted during the initial surge. The ladder and sustained tests are more
representative of production traffic patterns.

---

## 7. Fairness Rules

Every platform is benchmarked under identical conditions. Any deviation
invalidates the comparison.

### 7.1 Payload Invariance

| Rule | Detail |
|------|--------|
| Same labels | `["safe", "unsafe"]` — consistent across all tests |
| Same prompt pool | 5 rotating prompts (see `warm-policy.js`) |
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

The extended `concurrency-ladder-full.js` uses this progression:

| Stage | Duration | Virtual Users (VUs) |
|-------|----------|---------------------|
| Hold 1 | 60 s | 1 |
| Hold 2 | 60 s | 10 |
| Hold 3 | 60 s | 50 |
| Hold 4 | 60 s | 100 |
| Hold 5 | 60 s | 250 |
| Hold 6 | 60 s | 500 |
| Hold 7 | 60 s | 1,000 |

**Total:** 420 seconds (7 minutes).

### 7.3 Multi-Region Testing

Tests are run from **3 geographic locations** to capture regional variance.

#### 7.3.1 Runner Origins

Two runner infrastructures are available. Using both eliminates
backbone bias (see §7.3.2):

| Region | Linode (Akamai-owned) | GCP (Neutral) |
|--------|----------------------|----------------|
| US Central | us-ord (Chicago) | us-central1 (Iowa) |
| Europe | eu-central (Frankfurt) | europe-west1 (Belgium) |
| Asia-Pacific | ap-south (Singapore) | asia-southeast1 (Singapore) |

Each region runs the full benchmark suite independently.

#### 7.3.2 Origin Bias Disclosure

Linode is owned by Akamai. Traffic from Linode DCs to Akamai edge
PoPs may traverse Akamai's private backbone, giving Akamai lower
network latency and less jitter than competitors whose traffic must
cross the public internet.

To control for this bias, the benchmark SHOULD be run from both
Linode and GCP origins. If results are materially similar, backbone
bias is negligible. If Akamai's numbers improve significantly from
Linode vs. GCP, the GCP results are the primary scorecard and Linode
results are disclosed as a supplementary "Akamai-hosted origin"
perspective.

The scorecard MUST disclose which runner origin produced the data.

### 7.4 Cold Start Protocol

Cold start latency is measured by `cold-start.js` (rules only).

1. Send `POST /gateway/moderate` with text and `ml: false`.
2. Record round-trip time.
3. Wait 120 seconds of idle time.
4. Repeat for 10 iterations.

The `--cold` flag on `run-suite.sh` runs the cold start test.

**What "cold start" actually measures:** The 120-second idle period allows
CDN/networking connections (TCP, TLS, inter-PoP tunnels) to go idle or close.
The subsequent request measures the full round-trip overhead of re-establishing
those connections plus compute execution. This overhead varies by platform:

- **Akamai Functions:** Every invocation creates a new WASM instance, so there
  is no "warm instance" to evict. What appears as cold start is predominantly
  CDN/networking connection overhead (TCP/TLS between edge PoPs and compute
  backends). As Functions traffic grows, shared connections from other customers
  reduce the probability of hitting a fully cold path.
- **Fastly Compute:** Similar model — each request gets a fresh WASM instance.
  Cold start reflects connection-layer overhead.
- **Cloudflare Workers:** Uses an isolate model with possible instance reuse.
  Cold start may include both connection overhead and isolate spin-up.

The scorecard reports this metric as **"Post-idle round-trip overhead"** rather
than "WASM cold start" to avoid implying that WASM instance eviction is the
sole or primary factor.

### 7.5 Deployment Configuration

| Parameter | Requirement |
|-----------|-------------|
| Memory | Platform default (document actual value) |
| CPU | Platform default (document actual value) |
| Scaling | Single instance, no auto-scale during run |
| KV Store | Platform-native (see §5) |
| Caching | No CDN or response caching; bypass if platform enables by default |
| TLS | Required (HTTPS). All platforms use TLS. |

### 7.6 Result Integrity

- Raw k6 JSON output is saved to `results/<platform>/<timestamp>/`.
- Primary suite files: `warm-light.json`, `warm-policy.json`, `concurrency-ladder.json`, `constant-50vu.json`.
- Extended suite files: `concurrency-ladder-full.json`, `soak-500vu.json`, `spike.json`.
- Cold start files: `cold-start-rules.json`.
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

### 8.2 Cost Table

```
| Platform | $/1M (rules) |
|----------|-------------|
| Akamai   |             |
| Fastly   |             |
| Workers  |             |
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
| S1 | Clean input | `["cat","dog","<unique>"]` | `"A peaceful sunset over the mountains"` | `allow` | _(none)_ |
| S2 | XSS injection | `["<script>alert(1)</script>"]` | — | `block` | `injection_attempt` |
| S3 | Prohibited terms | `["kill","bomb","cat"]` | — | `block` | `prohibited_term` |
| S4 | PII email | `["cat","dog"]` | `"contact user@example.com"` | `review` | `pii_detected` |
| S5 | PII phone | `["cat"]` | `"call 555-123-4567"` | `review` | `pii_detected` |
| S6 | Leetspeak evasion | `["h@t3","k1ll"]` | — | `block` | `prohibited_term` |
| S7 | SQL injection | `["cat'; DROP TABLE users;--"]` | — | `block` | `injection_attempt` |
| S8 | Cache hit | _(repeat S1 labels, no text)_ | — | `allow` | `cache.hit: true` |

S1 uses a timestamped label to guarantee a cache miss.

### 9.2 Running Validation

```bash
./bench/run-validation.sh <platform> <gateway_url>
```

Exit code 0 = all 8 scenarios passed. Any non-zero exit = at least one check failed.

All three platforms must produce 8/8 pass before performance benchmarks are run.

---

## 10. Versioning

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-03-05 | Initial contract (thin proxy architecture) |
| 2.0 | 2026-03-10 | Moderation gateway: 3 benchmark modes, multi-region, cold start protocol, KV store caching, updated scorecard |
| 2.1 | 2026-03-25 | Safety labels, image blocklist, moderation validation suite (9 scenarios with ML), text field extraction |
| 3.0 | 2026-03-26 | Embedded ML toxicity classifier; 5-test benchmark suite (cold start, warm light, warm heavy, concurrency ladder, consistency); removed external inference proxy; updated SLOs for ML workload |
| 3.1 | 2026-03-26 | Two-tier benchmark: primary (rules, `ml: false`) and stretch (ML). Added `ml` request field, `warm-policy.js`, rules-only cold start. Updated SLOs and scorecard format. |
| 3.2 | 2026-04-12 | Tier 1 (rules-only) contract: removed ML/stretch content; response headers moved to §4; validation is 8 scenarios; `ml` defaults `false`; ML contract and benchmarks on `ml-inference` branch. |
| 3.3 | 2026-04-13 | Extended suite (1K ladder, 500-VU soak, 2K spike); GCP neutral-origin runners; dual-origin bias methodology; fixed `concurrency-rules` → `concurrency-ladder` naming. |
| 3.4 | 2026-04-14 | Methodology: **§6.3–§6.6** (k6 DNS cache, connection reuse, single runner IP, spike/CDN mapping). **§7.4** rewrites cold-start semantics (post-idle / CDN+TLS + compute, not WASM eviction as sole story). **§6.1.1** SLO notes aligned. Engineering review (Akamai). |
