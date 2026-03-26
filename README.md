# WASMnism

**WASM-Powered Content Moderation at the Edge**

A portable AI Prompt Firewall deployed as WebAssembly across multiple edge platforms, with an embedded ML toxicity classifier running entirely inside the WASM runtime. Built to produce a decision-grade price-per-performance scorecard comparing edge compute providers.

**Live demo**: [wasm-prompt-firewall-imjy4pe0.fermyon.app](https://wasm-prompt-firewall-imjy4pe0.fermyon.app/)

---

## What It Does

Every prompt passes through an 8-step moderation pipeline at the edge — before reaching any downstream AI model:

1. **Unicode NFC normalization** — canonical text form
2. **SHA-256 content hashing** — cache key + deduplication
3. **Leetspeak expansion** — `h@t3` → `hate`, `k1ll` → `kill`
4. **Prohibited content scan** — multi-pattern matching on expanded text
5. **PII detection** — email, phone, SSN regex
6. **Injection detection** — XSS, SQL injection patterns
7. **ML toxicity classifier** — MiniLMv2 neural network (22.7M params) via Tract NNEF, running inside WASM
8. **Policy verdict** — merge all signals into `allow`, `review`, or `block`

The ML step catches semantically toxic content that keyword rules miss — "you are pathetic and disgusting" contains no prohibited terms, but the model scores it at 0.86 toxicity and blocks it.

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

The gateway is a single Rust codebase compiled to `wasm32-wasip1`, with thin platform adapters for each target:

| Platform | Adapter | Status |
|----------|---------|--------|
| **Fermyon Cloud** (Spin) | `edge-gateway/adapters/spin/` | Deployed |
| **Fastly Compute** | `edge-gateway/adapters/fastly/` | Scaffolded |
| **Cloudflare Workers** | `edge-gateway/adapters/workers/` | Scaffolded |
| **AWS Lambda** | `edge-gateway/adapters/lambda/` | Scaffolded |
| **Native** (baseline) | `edge-gateway/adapters/native/` | Deployed |

## Project Structure

```
WASMnism/
├── edge-gateway/           # Rust workspace
│   ├── core/               #   Shared logic: pipeline, policy, toxicity, tokenizer
│   ├── adapters/           #   Platform-specific HTTP adapters
│   │   ├── spin/           #     Fermyon Cloud (primary)
│   │   ├── fastly/         #     Fastly Compute
│   │   ├── workers/        #     Cloudflare Workers
│   │   ├── lambda/         #     AWS Lambda
│   │   └── native/         #     Native binary (benchmark baseline)
│   ├── models/toxicity/    #   ML model files (gitignored, built locally)
│   └── tools/              #   ONNX → NNEF conversion tool
├── frontend/               # Svelte dashboard (built → Spin static files)
├── bench/                  # k6 benchmark scripts
├── deploy/                 # Deployment scripts (Linode, k6 runner)
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
SPIN_VARIABLE_INFERENCE_URL="http://your-inference-host:8000" spin up
```

### Deploy to Fermyon Cloud

```bash
cd edge-gateway/adapters/spin
spin cloud deploy \
  --variable inference_url="http://your-inference-host:8000" \
  --variable gateway_region="us-ord"
```

## ML Model

The toxicity classifier uses **MiniLMv2** (fine-tuned on Jigsaw toxic-comment data), exported to ONNX, vocabulary-trimmed to 8000 tokens, then converted to Tract's NNEF format for efficient WASM loading.

| Property | Value |
|----------|-------|
| Model | MiniLMv2-toxic-jigsaw |
| Parameters | 22.7M |
| Format | NNEF (Tract native) |
| Vocab size | 8,000 tokens |
| Model file | ~53 MB |
| Inference | ~850ms (Fermyon Cloud, cold) |
| Categories | `toxic`, `severe_toxic` |

The model runs entirely inside the WASM sandbox — no external ML service calls.

## Benchmark

Three modes are benchmarked per the [measurement contract](docs/benchmark_contract.md):

| Mode | Endpoint | What It Measures |
|------|----------|-----------------|
| Policy-Only | `POST /gateway/moderate` | Edge compute + ML inference |
| Cached Hit | `POST /gateway/moderate-cached` | Edge compute + KV read |
| Full Pipeline | `POST /api/clip/moderate` | End-to-end with inference proxy |

Run with k6:

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
