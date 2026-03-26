# WASMnism

**WASM-Powered Content Moderation at the Edge**

A portable AI Prompt Firewall deployed as WebAssembly across multiple edge platforms, with an embedded ML toxicity classifier running entirely inside the WASM runtime. Built to produce a decision-grade price-per-performance scorecard comparing WASM edge compute providers.

> **Status**: Work in progress. Fermyon Cloud is live. Akamai Functions, Fastly, Cloudflare, and Lambda deployments are next.

**Live demo**: [wasm-prompt-firewall-imjy4pe0.fermyon.app](https://wasm-prompt-firewall-imjy4pe0.fermyon.app/)

---

## What's Been Built

### Edge Gateway (Rust → WASM)

A single Rust codebase compiled to `wasm32-wasip1` that runs an 8-step moderation pipeline entirely at the edge:

1. **Unicode NFC normalization** — canonical text form
2. **SHA-256 content hashing** — cache key + deduplication
3. **Leetspeak expansion** — `h@t3` → `hate`, `k1ll` → `kill`
4. **Prohibited content scan** — multi-pattern matching on expanded text
5. **PII detection** — email, phone, SSN regex
6. **Injection detection** — XSS, SQL injection patterns
7. **ML toxicity classifier** — MiniLMv2 neural network (22.7M params), running inside the WASM sandbox via Tract NNEF
8. **Policy verdict** — merge all signals into `allow`, `review`, or `block`

The ML model catches semantically toxic content that keyword rules miss. "You are pathetic and disgusting" contains no prohibited terms, but the model scores it at 0.86 toxicity and blocks it.

### Frontend Dashboard

A Svelte SaaS-style dashboard with:
- Real-time prompt evaluation against the live edge gateway
- Pipeline visualization with color-coded status
- ML toxicity gauges with threshold markers
- Timing breakdown (client round-trip, gateway processing, ML inference)
- Pre-built example prompts spanning safe text, semantic toxicity, injection attacks, PII, and leetspeak evasion

### Deployments

| Platform | Status |
|----------|--------|
| **Fermyon Cloud** (Spin) | Live |
| **Akamai Functions** (Spin) | Access requested |
| **Fastly Compute** | Scaffolded |
| **Cloudflare Workers** | Scaffolded |
| **AWS Lambda** | Scaffolded |

### ML Model Pipeline

- **Model**: MiniLMv2 fine-tuned on Jigsaw toxic-comment data (22.7M parameters)
- **Export**: PyTorch → ONNX (opset 14, fixed shapes) → vocabulary-trimmed (30k → 8k tokens) → Tract NNEF
- **Runtime**: Pure-Rust inference via Tract, with a custom WordPiece tokenizer — no Python, no external service calls
- **Size**: ~53 MB model + 56 KB vocabulary, fitting within Fermyon's 100 MB limit

### Benchmark Infrastructure

- k6 scripts for three benchmark modes (policy-only, cached-hit, full-pipeline)
- Measurement contract defining schemas, SLOs, and fairness rules
- Multi-region testing from 3 geographic locations

---

## What's Planned

### Platform Deployments

- [ ] **Akamai Functions (Spin)** — access requested, same Spin adapter applies
- [ ] **Fastly Compute** — adapter scaffolded, needs deployment and testing
- [ ] **Cloudflare Workers** — adapter scaffolded, needs deployment and testing
- [ ] **AWS Lambda** — adapter scaffolded, needs deployment and testing

### Benchmarking

- [ ] Multi-region k6 runs (median of 7, client-side timing as source of truth)
- [ ] Cross-platform scorecard: latency percentiles (p50, p95, p99) per mode
- [ ] Cold start vs warm request analysis
- [ ] ML inference timing comparison across WASM platforms

### Cost Analysis

- [ ] Cost per 1M requests at SLO for each platform
- [ ] Price-per-performance scorecard

### Blog Post

- [ ] Executive summary and narrative hook
- [ ] Architecture deep-dive with diagrams
- [ ] Benchmark results with reproducible methodology
- [ ] Reproduce instructions for all platforms

### Potential Improvements

- [ ] Warm-start ML inference optimization (currently ~850ms cold on Fermyon)
- [ ] Additional toxicity categories beyond `toxic` and `severe_toxic`
- [ ] Raw JSON response toggle in the dashboard
- [ ] Persistent evaluation history (localStorage)

---

## Architecture

```
┌──────────┐     ┌──────────────────────────────────┐
│  Browser  │────▶│  Edge Gateway (WASM)              │
│  / k6     │◀────│                                    │
└──────────┘     │  1. Text normalization + hashing   │
                 │  2. Rule-based policy checks       │
                 │  3. ML toxicity inference (Tract)   │
                 │  4. Verdict composition             │
                 └──────────────────────────────────┘
```

The gateway is a single Rust codebase compiled to `wasm32-wasip1`, with thin platform adapters:

| Platform | Adapter | Status |
|----------|---------|--------|
| **Fermyon Cloud** (Spin) | `edge-gateway/adapters/spin/` | Deployed |
| **Akamai Functions** (Spin) | `edge-gateway/adapters/spin/` | Access requested |
| **Fastly Compute** | `edge-gateway/adapters/fastly/` | Scaffolded |
| **Cloudflare Workers** | `edge-gateway/adapters/workers/` | Scaffolded |
| **AWS Lambda** | `edge-gateway/adapters/lambda/` | Scaffolded |

## Project Structure

```
WASMnism/
├── edge-gateway/           # Rust workspace
│   ├── core/               #   Shared logic: pipeline, policy, toxicity, tokenizer
│   ├── adapters/           #   Platform-specific HTTP adapters
│   │   ├── spin/           #     Fermyon Cloud + Akamai Functions
│   │   ├── fastly/         #     Fastly Compute
│   │   ├── workers/        #     Cloudflare Workers
│   │   └── lambda/         #     AWS Lambda
│   ├── models/toxicity/    #   ML model files (gitignored, built locally)
│   └── tools/              #   ONNX → NNEF conversion tool
├── frontend/               # Svelte dashboard (built → Spin static files)
├── bench/                  # k6 benchmark scripts
├── deploy/                 # Deployment scaffolding
├── cost/                   # Cost model per 1M requests
└── docs/                   # Benchmark contract, moderation guide
```

## Quick Start

### Prerequisites

- [Rust](https://rustup.rs/) with `wasm32-wasip1` target: `rustup target add wasm32-wasip1`
- [Spin CLI](https://developer.fermyon.com/spin/v3/install): `curl -fsSL https://developer.fermyon.com/downloads/install.sh | bash`
- [Node.js](https://nodejs.org/) 18+ (for frontend build)

### Build & Run Locally

```bash
# Build the WASM gateway
cd edge-gateway
cargo build --target wasm32-wasip1 --release -p clipclap-gateway-spin

# Build the frontend
cd ../frontend
npm install && npm run build

# Copy frontend to Spin static dir
cp -r dist/* ../edge-gateway/adapters/spin/static/

# Run locally
cd ../edge-gateway/adapters/spin
spin up
```

### Deploy to Fermyon Cloud

```bash
cd edge-gateway/adapters/spin
spin cloud deploy
```

## ML Model

| Property | Value |
|----------|-------|
| Model | MiniLMv2-toxic-jigsaw |
| Parameters | 22.7M |
| Format | NNEF (Tract native) |
| Vocab size | 8,000 tokens |
| Model file | ~53 MB |
| Inference | ~850ms (Fermyon Cloud, cold) |
| Categories | `toxic`, `severe_toxic` |

The model runs entirely inside the WASM sandbox — no external ML service calls. It was exported from PyTorch to ONNX, vocabulary-trimmed from 30k to 8k tokens to fit deployment size limits, then converted to Tract's NNEF format to avoid expensive protobuf parsing in the WASM runtime.

## Benchmark

Three modes per the [measurement contract](docs/benchmark_contract.md):

| Mode | Endpoint | What It Measures |
|------|----------|-----------------|
| Policy-Only | `POST /gateway/moderate` | Edge compute + ML inference |
| Cached Hit | `POST /gateway/moderate-cached` | Edge compute + KV read |
| Full Pipeline | `POST /api/clip/moderate` | End-to-end with inference proxy |

```bash
cd bench
k6 run gateway-only.js
```

## API

### `POST /gateway/moderate`

```json
{
  "labels": ["safe", "unsafe"],
  "nonce": "unique-request-id",
  "text": "The prompt to evaluate"
}
```

Response:

```json
{
  "verdict": "allow",
  "moderation": {
    "policy_flags": [],
    "confidence": 0.0,
    "blocked_terms": [],
    "processing_ms": 862.1,
    "ml_toxicity": {
      "toxic": 0.001,
      "severe_toxic": 0.0001,
      "inference_ms": 858.9,
      "model": "MiniLMv2-toxic-jigsaw"
    }
  },
  "cache": { "hit": false, "hash": "sha256:..." },
  "gateway": { "platform": "spin", "region": "us-ord", "request_id": "..." }
}
```

### `GET /gateway/health`

Returns gateway status, platform, region, and ML model readiness.

## License

See [LICENSE](LICENSE).
