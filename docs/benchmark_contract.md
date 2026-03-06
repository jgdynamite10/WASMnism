# WASMnism Benchmark Contract

**Version:** 1.0  
**Date:** March 5, 2026  
**Status:** Draft

---

## 1. Purpose

This document defines the measurement contract for the WASMnism benchmark.
Any compliant gateway implementation — on any platform — MUST conform to these
schemas, SLOs, and fairness rules so results are directly comparable.

A third party should be able to implement a gateway from this contract alone,
deploy it on any of the target platforms, and produce results that are
apples-to-apples comparable with every other implementation.

---

## 2. Architecture Overview

```
┌──────────┐       ┌─────────────────┐       ┌─────────────────────┐
│  k6 / ── │──────▶│  Edge Gateway   │──────▶│  Inference Service  │
│  client   │◀──────│  (WASM / Lambda)│◀──────│  (FastAPI + CLIP/   │
└──────────┘       └─────────────────┘       │   CLAP models)      │
                                             └─────────────────────┘
```

Two benchmark modes:

| Mode | Path | What It Measures |
|------|------|-----------------|
| **Gateway-only** | `/gateway/health`, `/gateway/echo` | Pure edge overhead: routing, serialization, cold start |
| **Full proxy** | `/api/clip/classify`, `/api/clap/classify` | End-to-end: edge overhead + network hop + inference |

---

## 3. Gateway Request / Response Schemas

### 3.1 Classification Endpoints (Full Proxy)

#### POST /api/clip/classify

**Request:** `multipart/form-data`

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `image` | file | yes | JPEG or PNG, max 10 MB |
| `labels` | string | yes | JSON array of strings, max 1000 items |

#### POST /api/clap/classify

**Request:** `multipart/form-data`

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `audio` | file | yes | WAV or MP3, max 25 MB |
| `labels` | string | yes | JSON array of strings, max 1000 items |

#### Classification Response (both endpoints)

All gateways MUST return this exact JSON schema. Field order MAY vary;
field names, types, and nesting MUST NOT.

```json
{
  "results": [
    {
      "label": "<string>",
      "score": "<float, 0.0–1.0, softmax>",
      "similarity": "<float, -1.0–1.0, cosine>"
    }
  ],
  "metrics": {
    "model_load_ms": "<float>",
    "input_encoding_ms": "<float>",
    "text_encoding_ms": "<float>",
    "similarity_ms": "<float>",
    "total_inference_ms": "<float>",
    "num_candidates": "<int>"
  }
}
```

**Validation rules:**

- `results` MUST be a non-empty array, sorted by `score` descending.
- `score` values MUST sum to 1.0 (±0.01 tolerance for floating-point).
- `metrics` MUST be present even if all values are 0.0.
- HTTP status MUST be `200` on success.

### 3.2 Gateway Metadata Envelope (optional)

Gateways MAY wrap the upstream response in a metadata envelope for
observability. If used, the envelope MUST follow this schema:

```json
{
  "gateway": {
    "platform": "<string: spin | fastly | workers | lambda>",
    "region": "<string>",
    "cold_start": "<bool>",
    "gateway_latency_ms": "<float>",
    "upstream_latency_ms": "<float>"
  },
  "upstream": {
    "results": [ "..." ],
    "metrics": { "..." }
  }
}
```

For **benchmark scoring**, only the `upstream` block is compared across
platforms. The `gateway` block is informational.

---

## 4. Gateway ↔ Inference Service Contract

### 4.1 Upstream Endpoints

The gateway proxies to the inference service at `INFERENCE_URL` (env var).

| Gateway Path | Upstream Path | Method |
|-------------|---------------|--------|
| `POST /api/clip/classify` | `${INFERENCE_URL}/api/clip/classify` | POST |
| `POST /api/clap/classify` | `${INFERENCE_URL}/api/clap/classify` | POST |

The gateway MUST forward the multipart body unchanged.
The gateway MUST NOT modify, re-encode, or reorder form fields.

### 4.2 Timeouts

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Connect timeout** | 5 s | Inference service should be warm |
| **Read timeout** | 30 s | Large audio files; model may be loading |
| **Total request timeout** | 35 s | Connect + read + margin |
| **Gateway processing budget** | 50 ms | Gateway overhead must be negligible |

Timeouts are NOT configurable per-platform for benchmark runs. All
platforms use the same values to ensure fairness.

### 4.3 Error Mapping

The gateway translates upstream errors to a consistent error schema:

```json
{
  "error": {
    "code": "<string>",
    "message": "<string>",
    "upstream_status": "<int | null>"
  }
}
```

| Upstream Condition | Gateway HTTP Status | Error Code |
|-------------------|---------------------|------------|
| 200 OK | 200 | _(none — success)_ |
| 400 Bad Request | 400 | `UPSTREAM_BAD_REQUEST` |
| 422 Unprocessable | 422 | `UPSTREAM_VALIDATION_ERROR` |
| 500 Internal Error | 502 | `UPSTREAM_ERROR` |
| Connection refused | 502 | `UPSTREAM_UNREACHABLE` |
| Connect timeout | 504 | `UPSTREAM_CONNECT_TIMEOUT` |
| Read timeout | 504 | `UPSTREAM_READ_TIMEOUT` |
| Gateway internal error | 500 | `GATEWAY_INTERNAL_ERROR` |

### 4.4 Headers

The gateway MUST set the following response headers:

| Header | Value |
|--------|-------|
| `Content-Type` | `application/json` |
| `X-Gateway-Platform` | `spin`, `fastly`, `workers`, or `lambda` |
| `X-Gateway-Region` | Deployment region (e.g., `us-east-1`) |
| `X-Gateway-Request-Id` | UUID v4, generated per request |

The gateway MUST forward these request headers to the inference service
if present: `X-Request-Id`, `Accept`.

---

## 5. Gateway-Only Paths

These endpoints exercise the gateway without calling the inference service.
They are used for pure edge performance benchmarking.

### 5.1 GET /gateway/health

Returns gateway liveness. No inference call.

**Response** (HTTP 200):

```json
{
  "status": "healthy",
  "platform": "<string: spin | fastly | workers | lambda>",
  "region": "<string>",
  "timestamp_ms": "<int, Unix epoch ms>"
}
```

### 5.2 POST /gateway/echo

Accepts a JSON body, echoes it back with gateway metadata. Exercises
request parsing, JSON serialization, and response writing — the same
code paths as the real proxy minus the upstream call.

**Request:**

```json
{
  "labels": ["cat", "dog", "bird"],
  "nonce": "<string, any>"
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `labels` | array of strings | yes | 1–1000 items |
| `nonce` | string | yes | max 256 chars |

**Response** (HTTP 200):

```json
{
  "echo": {
    "labels": ["cat", "dog", "bird"],
    "nonce": "<echoed>"
  },
  "gateway": {
    "platform": "<string>",
    "region": "<string>",
    "timestamp_ms": "<int>",
    "request_id": "<uuid>"
  }
}
```

### 5.3 POST /gateway/mock-classify

Returns a **deterministic** classification response using the same schema
as the real inference endpoints. This validates JSON serialization parity
across platforms without requiring the inference service.

**Request:** same as `/gateway/echo`.

**Response** (HTTP 200):

```json
{
  "results": [
    { "label": "<first label from input>", "score": 0.70, "similarity": 0.290 },
    { "label": "<second label from input>", "score": 0.20, "similarity": 0.210 },
    { "label": "<third label from input>", "score": 0.10, "similarity": 0.130 }
  ],
  "metrics": {
    "model_load_ms": 0.0,
    "input_encoding_ms": 0.0,
    "text_encoding_ms": 0.0,
    "similarity_ms": 0.0,
    "total_inference_ms": 0.0,
    "num_candidates": 3
  }
}
```

**Determinism rules:**

- Scores are fixed: first label gets 0.70, second 0.20, remaining labels
  split the residual (0.10) equally (rounded to 6 decimal places).
- If fewer than 3 labels, redistribute proportionally (see table below).
- `similarity` values are derived: `similarity = score * 0.41` (rounded to
  3 decimal places).
- `metrics` fields are all 0.0; `num_candidates` equals the label count.

| Labels | Score Distribution |
|--------|-------------------|
| 1 | `[1.00]` |
| 2 | `[0.70, 0.30]` |
| 3 | `[0.70, 0.20, 0.10]` |
| N > 3 | `[0.70, 0.20]` + remaining `0.10 / (N-2)` each |

This endpoint is the **primary gateway-only benchmark target** because it
exercises the full serialization path.

---

## 6. Service Level Objectives (SLO)

SLOs define the performance bar. They are NOT pass/fail gates for the
benchmark; they are the reference lines on the scorecard.

### 6.1 Gateway-Only SLO (POST /gateway/mock-classify)

| Metric | Target | Notes |
|--------|--------|-------|
| p50 latency | ≤ 15 ms | Warm requests |
| p95 latency | ≤ 50 ms | Includes occasional cold starts |
| p99 latency | ≤ 150 ms | Hard ceiling |
| Error rate | ≤ 0.1% | Over full benchmark run |
| Throughput | ≥ 500 RPS | At 50 concurrent connections |

### 6.2 Full Proxy SLO (POST /api/clip/classify)

| Metric | Target | Notes |
|--------|--------|-------|
| p50 latency | ≤ 500 ms | Dominated by inference time |
| p95 latency | ≤ 1500 ms | Model load or cold start |
| p99 latency | ≤ 3000 ms | Hard ceiling |
| Error rate | ≤ 0.5% | Inference may be less reliable |
| Throughput | ≥ 50 RPS | At 10 concurrent connections |

### 6.3 Measurement Method

- **Timing source:** Client-side (k6 `http_req_duration`). This is the
  source of truth for the scorecard.
- **Server-side timing** (via `X-Gateway-*` headers or `gateway.gateway_latency_ms`)
  is informational only.
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
| Same image file | `bench/fixtures/benchmark.jpg` — a 640×480 JPEG, ~80 KB |
| Same audio file | `bench/fixtures/benchmark.wav` — 5 s, 16 kHz, mono, ~160 KB |
| Same labels | `["cat", "dog", "bird", "car", "music"]` — 5 labels for all runs |
| Same nonce | `"wasmnism-bench-v1"` |

Fixture files are checked into the repo. Changing them invalidates all
prior results.

### 7.2 Concurrency Ladder

Both gateway-only and full-proxy benchmarks use the same concurrency
progression within each run:

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

SLO metrics are computed over the scored portion only (excluding warm-up
and cool-down).

### 7.3 Client Location

- **Primary region:** `us-east-1` (or nearest equivalent per platform).
- **k6 runner:** Same machine or cloud instance for all platforms in a
  given benchmark session.
- **Network:** Runner must be in the same region as the gateway deployment
  to minimize network variance. Document the runner location in results.

### 7.4 Deployment Configuration

| Parameter | Requirement |
|-----------|-------------|
| Memory | Platform default (document actual value) |
| CPU | Platform default (document actual value) |
| Scaling | Single instance, no auto-scale during run |
| Cold start | First request of each run triggers cold start; warm-up absorbs it |
| Caching | No CDN or response caching; bypass if platform enables by default |
| TLS | Required (HTTPS). All platforms use TLS. |

### 7.5 Inference Service (Full Proxy Only)

- Single inference service instance, same region as all gateways.
- Inference service must be warm (health-checked) before each run.
- Same `INFERENCE_URL` for all platforms (no per-platform inference).

### 7.6 Result Integrity

- Raw k6 JSON output is saved to `results/<platform>/<run_N>.json`.
- Raw results are **gitignored** (may contain IPs).
- Aggregated scorecard (`bench/scorecard.md`) contains only medians.
- All results from a benchmark session use the same k6 version,
  same runner, same inference service state.

---

## 8. Scorecard Format

The final scorecard (`bench/scorecard.md`) reports the median of 7 runs:

```
| Platform   | Mode          | p50 (ms) | p95 (ms) | p99 (ms) | RPS   | Error % | $/1M req |
|------------|---------------|----------|----------|----------|-------|---------|----------|
| Spin       | gateway-only  |          |          |          |       |         |          |
| Spin       | full-proxy    |          |          |          |       |         |          |
| Fastly     | gateway-only  |          |          |          |       |         |          |
| Fastly     | full-proxy    |          |          |          |       |         |          |
| Workers    | gateway-only  |          |          |          |       |         |          |
| Workers    | full-proxy    |          |          |          |       |         |          |
| Lambda     | gateway-only  |          |          |          |       |         |          |
| Lambda     | full-proxy    |          |          |          |       |         |          |
```

**SLO compliance** is indicated with a marker: values meeting the SLO are
unmarked; values exceeding the SLO are marked with `*`.

---

## 9. Versioning

This contract is versioned. Any change to schemas, SLOs, fairness rules,
or fixture files increments the version and invalidates prior results.

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-03-05 | Initial contract |
