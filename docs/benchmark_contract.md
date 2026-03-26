# WASMnism Benchmark Contract

**Version:** 2.0  
**Date:** March 10, 2026  
**Status:** Active

---

## 1. Purpose

This document defines the measurement contract for the WASMnism benchmark.
Any compliant gateway implementation — on any platform — MUST conform to these
schemas, SLOs, and fairness rules so results are directly comparable.

A third party should be able to implement a gateway from this contract alone,
deploy it on any of the target platforms, and produce results that are
apples-to-apples comparable with every other implementation.

v2.0 replaces the thin-proxy architecture with a **content moderation and
policy gateway** that performs real computational work at the edge: text
normalization, SHA-256 hashing, multi-pattern matching, regex PII scanning,
policy evaluation, and KV store caching.

---

## 2. Architecture Overview

```
┌──────────────┐      ┌──────────────────────────────┐      ┌───────────────────┐
│  k6 runner   │─────▶│  Edge Moderation Gateway      │─────▶│ ClipClap Inference│
│  (3 regions) │◀─────│  (WASM / Lambda)              │◀─────│ (Linode us-ord)   │
└──────────────┘      │                                │      └───────────────────┘
                      │  Pre-inference:                │
                      │   · Unicode NFC normalize      │
                      │   · SHA-256 content hash       │
                      │   · KV cache lookup            │
                      │   · Policy pre-check           │
                      │     (prohibited terms, PII,    │
                      │      injection detection)      │
                      │                                │
                      │  Post-inference:               │
                      │   · Policy post-check          │
                      │     (high-risk score threshold) │
                      │   · KV cache write             │
                      │   · Verdict composition        │
                      └──────────────────────────────┘
```

Three benchmark modes:

| Mode | Endpoint | What It Measures |
|------|----------|-----------------|
| **Policy-Only** | `POST /gateway/moderate` | Pure edge compute: normalization, hashing, multi-pattern matching, regex, policy evaluation, mock classification |
| **Cached Hit** | `POST /gateway/moderate-cached` | Edge compute + platform KV store read latency |
| **Full Pipeline** | `POST /api/clip/moderate` | End-to-end: edge compute + network hop + inference + post-processing + KV write |

Legacy endpoints (`/gateway/health`, `/gateway/echo`, `/gateway/mock-classify`,
`/api/clip/classify`, `/api/clap/classify`) remain available but are not
part of the v2.0 scorecard.

---

## 3. Moderation Request / Response Schemas

### 3.1 Moderation Request

Used by all three benchmark modes.

**Mode 1 and 2:** `application/json`

```json
{
  "labels": ["cat", "dog", "bird"],
  "nonce": "<string>",
  "text": "<optional string, free text for PII/content scanning>"
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `labels` | array of strings | yes | 1–1000 items |
| `nonce` | string | yes | max 256 chars |
| `text` | string | no | Optional free text for content scanning |

**Mode 3:** `multipart/form-data` (same format as `/api/clip/classify`)

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `image` | file | yes | JPEG or PNG, max 10 MB |
| `labels` | string | yes | JSON array of strings, max 1000 items |

### 3.2 Moderation Response

All platforms MUST return this exact JSON schema. Field order MAY vary;
field names, types, and nesting MUST NOT.

```json
{
  "verdict": "allow | block | review",
  "moderation": {
    "policy_flags": ["prohibited_term", "pii_detected", "injection_attempt", "high_risk_score"],
    "confidence": 0.95,
    "blocked_terms": ["kill", "[injection]"],
    "processing_ms": 2.3
  },
  "classification": {
    "results": [
      { "label": "<string>", "score": "<float>", "similarity": "<float>" }
    ],
    "metrics": {
      "model_load_ms": "<float>",
      "input_encoding_ms": "<float>",
      "text_encoding_ms": "<float>",
      "similarity_ms": "<float>",
      "total_inference_ms": "<float>",
      "num_candidates": "<int>"
    }
  },
  "cache": {
    "hit": false,
    "hash": "sha256:<64 hex chars>"
  },
  "gateway": {
    "platform": "<spin | fastly | workers | lambda>",
    "region": "<string>",
    "request_id": "<uuid>"
  }
}
```

**Validation rules:**

- `verdict` MUST be one of: `allow`, `block`, `review`.
- `moderation.policy_flags` MUST be an array (may be empty).
- `moderation.confidence` MUST be a float 0.0–1.0.
- `moderation.processing_ms` MUST reflect actual gateway processing time.
- `classification` MUST be present (null for blocked requests in Mode 3).
- `cache.hit` MUST be a boolean.
- `cache.hash` MUST start with `sha256:` followed by 64 hex characters.
- `gateway.platform` MUST be one of the four target platforms.
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

**Post-check (Modes 1 and 3 only):**

| Condition | Verdict | Flag |
|-----------|---------|------|
| High-risk label score ≥ 0.80 | `block` | `high_risk_score` |
| High-risk label score ≥ 0.50 | `review` | _(none)_ |
| No high-risk labels | `allow` | _(none)_ |

High-risk labels: `violence`, `gore`, `explicit`, `hate`, `weapons`.

**Merge rule:** The stricter verdict wins (block > review > allow).

### 3.4 Cache Behavior

| Mode | Cache Read | Cache Write |
|------|-----------|-------------|
| Policy-Only | No | No |
| Cached Hit | Yes (by label hash) | No |
| Full Pipeline | Yes (by label hash) | Yes (after inference) |

Cache key: SHA-256 of normalized labels (NFC + lowercase + whitespace collapsed).

---

## 4. Gateway ↔ Inference Service Contract

### 4.1 Upstream Endpoint

The gateway proxies to the inference service at `INFERENCE_URL` (env var)
only in Full Pipeline mode when the pre-check verdict is `allow` and the
cache does not contain a result for the label hash.

| Gateway Path | Upstream Path | Method |
|-------------|---------------|--------|
| `POST /api/clip/moderate` | `${INFERENCE_URL}/api/clip/classify` | POST |

The gateway MUST forward the multipart body unchanged to the inference service.

### 4.2 Timeouts

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Connect timeout** | 5 s | Inference service should be warm |
| **Read timeout** | 30 s | Large files; model may be loading |
| **Total request timeout** | 35 s | Connect + read + margin |
| **Gateway processing budget** | 50 ms | Gateway overhead (excluding inference) |

### 4.3 Error Mapping

Same as v1.0. See `edge-gateway/core/src/error.rs` for implementation.

### 4.4 Headers

The gateway MUST set the following response headers:

| Header | Value |
|--------|-------|
| `Content-Type` | `application/json` |
| `X-Gateway-Platform` | `spin`, `fastly`, `workers`, or `lambda` |
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
| AWS Lambda | DynamoDB | `moderation-cache` |

---

## 6. Service Level Objectives (SLO)

SLOs define the performance bar. They are NOT pass/fail gates for the
benchmark; they are the reference lines on the scorecard.

### 6.1 Policy-Only SLO (POST /gateway/moderate)

| Metric | Target | Notes |
|--------|--------|-------|
| p50 latency | ≤ 20 ms | Warm requests |
| p95 latency | ≤ 60 ms | Includes occasional cold starts |
| p99 latency | ≤ 200 ms | Hard ceiling |
| Error rate | ≤ 0.1% | Over full benchmark run |
| Throughput | ≥ 400 RPS | At 50 concurrent connections |

### 6.2 Cached Hit SLO (POST /gateway/moderate-cached)

| Metric | Target | Notes |
|--------|--------|-------|
| p50 latency | ≤ 25 ms | Normalize + hash + KV read |
| p95 latency | ≤ 75 ms | Includes KV store variance |
| p99 latency | ≤ 250 ms | Hard ceiling |
| Error rate | ≤ 0.1% | Over full benchmark run |
| Throughput | ≥ 300 RPS | At 50 concurrent connections |

### 6.3 Full Pipeline SLO (POST /api/clip/moderate)

| Metric | Target | Notes |
|--------|--------|-------|
| p50 latency | ≤ 600 ms | Dominated by inference time |
| p95 latency | ≤ 1500 ms | Model load or cold start |
| p99 latency | ≤ 3000 ms | Hard ceiling |
| Error rate | ≤ 0.5% | Inference may be less reliable |
| Throughput | ≥ 40 RPS | At 10 concurrent connections |

### 6.4 Measurement Method

- **Timing source:** Client-side (k6 `http_req_duration`). This is the
  source of truth for the scorecard.
- **Server-side timing** (`moderation.processing_ms`) is recorded for
  analysis but does not determine scorecard values.
- **Runs:** 7 runs per configuration. Report the **median** of each metric.
- **Warm-up:** Each run begins with a 10-second warm-up phase (not scored).
- **Duration:** Each scored run lasts 60 seconds.

---

## 7. Fairness Rules

Every platform is benchmarked under identical conditions. Any deviation
invalidates the comparison.

### 7.1 Payload Invariance

| Rule | Detail |
|------|--------|
| Same image file | `bench/fixtures/benchmark.jpg` — a 640×480 JPEG, ~68 KB |
| Same labels | `["cat", "dog", "bird", "car", "music"]` — 5 labels for all runs |
| Same nonce | `"wasmnism-bench-v2"` |

Fixture files are checked into the repo. Changing them invalidates all
prior results.

### 7.2 Concurrency Ladder

All benchmark modes use the same concurrency progression:

| Stage | Duration | Virtual Users (VUs) |
|-------|----------|---------------------|
| Warm-up | 10 s | 1 |
| Ramp 1 | 15 s | 1 → 10 |
| Hold 1 | 15 s | 10 |
| Ramp 2 | 15 s | 10 → 50 |
| Hold 2 | 15 s | 50 |
| Ramp 3 | 15 s | 50 → 100 |
| Hold 3 | 15 s | 100 |
| Cool-down | 10 s | 100 → 1 |

**Total:** ~110 seconds per run (10 s warm-up + 90 s scored + 10 s cooldown).

### 7.3 Multi-Region Testing

Tests are run from **3 geographic locations** to capture regional variance:

| Region | Runner Location | Purpose |
|--------|----------------|---------|
| US Central | Linode us-ord (Chicago) | Near inference service |
| Europe | Linode eu-west (London) | Transatlantic latency |
| Asia-Pacific | Linode ap-south (Singapore) | Maximum distance |

Each region runs the full benchmark suite independently.

### 7.4 Cold Start Protocol

Cold start latency is measured separately:

1. Deploy/restart the gateway.
2. Wait 5 minutes (ensure instance is idle/cold).
3. Send a single request and record the full response time.
4. Repeat steps 1-3 for 20 measurements.
5. Report p50 and p99 cold start latency.

### 7.5 Deployment Configuration

| Parameter | Requirement |
|-----------|-------------|
| Memory | Platform default (document actual value) |
| CPU | Platform default (document actual value) |
| Scaling | Single instance, no auto-scale during run |
| KV Store | Platform-native (see §5) |
| Caching | No CDN or response caching; bypass if platform enables by default |
| TLS | Required (HTTPS). All platforms use TLS. |

### 7.6 Inference Service (Full Pipeline Only)

- Single inference service instance at Linode us-ord.
- Inference service must be warm (health-checked) before each run.
- Same `INFERENCE_URL` for all platforms.

### 7.7 Result Integrity

- Raw k6 JSON output is saved to `results/<platform>/<region>/<run_N>.json`.
- Raw results are **gitignored** (may contain IPs).
- Aggregated scorecard (`bench/scorecard.md`) contains only medians.
- All results from a benchmark session use the same k6 version,
  same runners, same inference service state.

---

## 8. Scorecard Format

The final scorecard (`bench/scorecard.md`) reports the median of 7 runs,
from each of the 3 test regions:

### 8.1 Per-Region Table

```
| Platform | Mode           | p50 (ms) | p95 (ms) | p99 (ms) | RPS   | Error % |
|----------|----------------|----------|----------|----------|-------|---------|
| Spin     | policy-only    |          |          |          |       |         |
| Spin     | cached-hit     |          |          |          |       |         |
| Spin     | full-pipeline  |          |          |          |       |         |
| Fastly   | policy-only    |          |          |          |       |         |
| Fastly   | cached-hit     |          |          |          |       |         |
| Fastly   | full-pipeline  |          |          |          |       |         |
| Workers  | policy-only    |          |          |          |       |         |
| Workers  | cached-hit     |          |          |          |       |         |
| Workers  | full-pipeline  |          |          |          |       |         |
| Lambda   | policy-only    |          |          |          |       |         |
| Lambda   | cached-hit     |          |          |          |       |         |
| Lambda   | full-pipeline  |          |          |          |       |         |
```

### 8.2 Cold Start Table

```
| Platform | p50 Cold Start (ms) | p99 Cold Start (ms) |
|----------|--------------------|--------------------|
| Spin     |                    |                    |
| Fastly   |                    |                    |
| Workers  |                    |                    |
| Lambda   |                    |                    |
```

### 8.3 Cost Table

```
| Platform | $/1M Policy-Only | $/1M Cached-Hit | $/1M Full-Pipeline |
|----------|-----------------|-----------------|-------------------|
| Spin     |                 |                 |                   |
| Fastly   |                 |                 |                   |
| Workers  |                 |                 |                   |
| Lambda   |                 |                 |                   |
```

---

## 9. Moderation Validation

Before running performance benchmarks, each platform MUST pass the moderation
validation suite to prove correctness. The suite sends the same safe image
(`bench/fixtures/benchmark.jpg`) with different label/text payloads and
asserts identical verdicts across all platforms.

### 9.1 Validation Scenarios

| # | Name | Labels | Text | Expected Verdict | Expected Flag |
|---|------|--------|------|-----------------|---------------|
| S1 | Clean input | `["cat","dog","<unique>"]` | — | `allow` | _(none)_ |
| S2 | XSS injection | `["<script>alert(1)</script>"]` | — | `block` | `injection_attempt` |
| S3 | Prohibited terms | `["kill","bomb","cat"]` | — | `block` | `prohibited_term` |
| S4 | PII email | `["cat","dog"]` | `"contact user@example.com"` | `review` | `pii_detected` |
| S5 | PII phone | `["cat"]` | `"call 555-123-4567"` | `review` | `pii_detected` |
| S6 | Leetspeak evasion | `["h@t3","k1ll"]` | — | `block` | `prohibited_term` |
| S7 | SQL injection | `["cat'; DROP TABLE users;--"]` | — | `block` | `injection_attempt` |
| S8 | Cache hit | _(repeat S1 labels)_ | — | `allow` | `cache.hit: true` |
| S9 | Image not blocklisted | `["sunrise","mountain","river"]` | — | `allow` | `image_blocklisted: false` |

S1 uses a timestamped label to guarantee a cache miss and fresh inference.

### 9.2 Additional Assertions (S1 only)

- `moderation.safety_scores` MUST be present (array of 10 safety labels).
- All safety scores MUST be below 0.50 (safe image).
- `classification.results` MUST contain only user-supplied labels (safety labels stripped).

### 9.3 Running Validation

```bash
./bench/run-validation.sh <platform> <gateway_url>
```

Exit code 0 = all 9 scenarios passed. Any non-zero exit = at least one check failed.

All four platforms must produce 9/9 pass before performance benchmarks are run.

---

## 10. Versioning

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-03-05 | Initial contract (thin proxy architecture) |
| 2.0 | 2026-03-10 | Moderation gateway: 3 benchmark modes, multi-region, cold start protocol, KV store caching, updated scorecard |
| 2.1 | 2026-03-25 | Safety labels, image blocklist, moderation validation suite (9 scenarios), text field extraction |
