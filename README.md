# WASMnism

**WASM-Powered Content Moderation at the Edge**

A portable AI Prompt Firewall deployed as WebAssembly across multiple edge platforms, with an embedded ML toxicity classifier running entirely inside the WASM runtime. Built to produce a decision-grade price-per-performance scorecard comparing WASM edge compute providers.

> **Status**: Work in progress. Fermyon Cloud, Akamai Functions, and Fastly Compute are live and benchmarked. Cloudflare and Lambda deployments are next.

**Live demos**:
- Fermyon Cloud: [wasm-prompt-firewall-imjy4pe0.fermyon.app](https://wasm-prompt-firewall-imjy4pe0.fermyon.app/)
- Akamai Functions: [0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app](https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app/)
- Fastly Compute: [morally-civil-urchin.edgecompute.app](https://morally-civil-urchin.edgecompute.app/)

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

| Platform | Status | Endpoint |
|----------|--------|----------|
| **Fermyon Cloud** (Spin) | Live + benchmarked | [fermyon.app](https://wasm-prompt-firewall-imjy4pe0.fermyon.app/) |
| **Akamai Functions** (Spin) | Live + benchmarked | [fwf.app](https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app/) |
| **Fastly Compute** | Live + benchmarked | [edgecompute.app](https://morally-civil-urchin.edgecompute.app/) |
| **Cloudflare Workers** | Scaffolded | — |
| **AWS Lambda** | Scaffolded | — |

### ML Model Pipeline

- **Model**: MiniLMv2 fine-tuned on Jigsaw toxic-comment data (22.7M parameters)
- **Export**: PyTorch → ONNX (opset 14, fixed shapes) → vocabulary-trimmed (30k → 8k tokens) → Tract NNEF
- **Runtime**: Pure-Rust inference via Tract, with a custom WordPiece tokenizer — no Python, no external service calls
- **Size**: ~53 MB model + 56 KB vocabulary, fitting within Fermyon's 100 MB limit

### Benchmark Infrastructure

- **Primary suite**: rule-based pipeline benchmarks (what customers deploy) — warm light, warm policy, concurrency ladder
- **Stretch suite**: embedded ML inference benchmarks (demonstrates limits) — warm heavy, consistency
- Cold start tests for both modes
- Suite runner, 7-run median calculator, scorecard generator, and multi-region runner
- Automated reproduce pipeline: `make benchmark` (single region) or `make bench-multiregion` (3 regions)
- Multi-region k6 infrastructure: automated provisioning of Linode VMs in us-ord, eu-central, ap-south
- Measurement contract v3.1 with 9-scenario validation suite for correctness

---

## What's Planned

### Platform Deployments

- [x] **Fermyon Cloud (Spin)** — deployed, validated, multi-region benchmarked
- [x] **Akamai Functions (Spin)** — deployed, validated, multi-region benchmarked
- [x] **Fastly Compute** — deployed, validated, multi-region benchmarked (rules-only; no ML due to filesystem constraint)
- [ ] **Cloudflare Workers** — adapter scaffolded, needs deployment and testing
- [ ] **AWS Lambda** — adapter scaffolded, needs deployment and testing

### Benchmarking

- [x] Primary benchmark suite (rules-only: warm light, warm policy, concurrency ladder)
- [x] Stretch benchmark suite (embedded ML: warm heavy, consistency)
- [x] Cold start tests (rules-only and ML modes)
- [x] Suite runner, scorecard generator, and 7-run median calculator
- [x] Fermyon Cloud: validation 9/9, 7-run medians, cold start data
- [x] End-to-end reproduce pipeline (`bench/reproduce.sh`)
- [x] Multi-region k6 runner infrastructure (`deploy/k6-runner-setup.sh`)
- [x] Multi-region orchestrator (`bench/run-multiregion.sh`)
- [x] Root Makefile with all automation targets
- [x] Multi-region benchmark data (3 geographic locations: us-ord, eu-central, ap-south)
- [x] Cross-platform scorecard: Fermyon vs Akamai ([results/fermyon_vs_akamai_scorecard.md](results/fermyon_vs_akamai_scorecard.md))
- [x] Three-platform scorecard: Fermyon vs Akamai vs Fastly ([results/three_platform_scorecard.md](results/three_platform_scorecard.md))

### Cost Analysis

- [ ] Cost per 1M requests at SLO for each platform
- [ ] Price-per-performance scorecard

### Blog Post

- [ ] Executive summary and narrative hook
- [x] Architecture deep-dive with diagrams ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))
- [ ] Benchmark results with reproducible methodology
- [x] Reproduce instructions ([docs/REPRODUCE.md](docs/REPRODUCE.md))

### Potential Improvements

- [ ] ML inference optimization (779ms on Akamai, 1,760ms on Fermyon — platform runtime is dominant factor; not available on Fastly)
- [ ] Additional toxicity categories beyond `toxic` and `severe_toxic`
- [ ] Quantized model variant for lower-latency ML inference
- [ ] Raw JSON response toggle in the dashboard
- [ ] Persistent evaluation history (localStorage)

---

## Architecture

> Full architecture reference: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

```
  ┌──────────┐          ┌─────────────────────────────────────────────────┐
  │  Browser  │── HTTPS ▶│  Edge Gateway (WASM binary)                     │
  │  / k6     │◀─────────│                                                 │
  └──────────┘          │  ┌─────────────┐    ┌────────────────────────┐  │
                         │  │  Platform    │    │  Core Library (Rust)   │  │
                         │  │  Adapter     │───▶│                        │  │
                         │  │  (spin/      │    │  1. Normalize + hash   │  │
                         │  │   fastly/    │    │  2. Rule-based checks  │  │
                         │  │   workers/   │    │  3. ML toxicity (Tract)│  │
                         │  │   lambda)    │    │  4. Verdict merge      │  │
                         │  └─────────────┘    └────────────────────────┘  │
                         └─────────────────────────────────────────────────┘
```

The gateway is a single Rust codebase compiled to `wasm32-wasip1`, with thin platform adapters:

| Platform | Adapter | Status |
|----------|---------|--------|
| **Fermyon Cloud** (Spin) | `edge-gateway/adapters/spin/` | Deployed + benchmarked |
| **Akamai Functions** (Spin) | `edge-gateway/adapters/spin/` | Deployed + benchmarked |
| **Fastly Compute** | `edge-gateway/adapters/fastly/` | Deployed + benchmarked (rules only) |
| **Cloudflare Workers** | `edge-gateway/adapters/workers/` | Scaffolded |
| **AWS Lambda** | `edge-gateway/adapters/lambda/` | Scaffolded |

## Project Structure

```
WASMnism/
├── Makefile                # Root automation: make build, make benchmark, make runners-up, etc.
├── edge-gateway/           # Rust workspace
│   ├── core/               #   Shared logic: pipeline, policy, toxicity, tokenizer
│   ├── adapters/           #   Platform-specific HTTP adapters
│   │   ├── spin/           #     Fermyon Cloud + Akamai Functions
│   │   ├── fastly/         #     Fastly Compute
│   │   ├── workers/        #     Cloudflare Workers
│   │   └── lambda/         #     AWS Lambda
│   ├── models/toxicity/    #   ML model + vocab (see models/README.md for provenance)
│   └── tools/              #   ONNX → NNEF conversion tool
├── frontend/               # Svelte dashboard (built → Spin static files)
├── bench/                  # k6 benchmark scripts + automation
│   ├── reproduce.sh        #   End-to-end pipeline: validate → 7-run → medians
│   ├── run-multiregion.sh  #   Distribute to 3 k6 runners in parallel
│   ├── run-suite.sh        #   Single benchmark suite run
│   └── run-7x.sh           #   7-run median calculator
├── deploy/                 # Deployment + infrastructure
│   ├── k6-runner-setup.sh  #   Provision/teardown 3 Linode k6 runners
│   └── runners.env         #   Runner IPs (gitignored)
├── cost/                   # Cost model per 1M requests
├── docs/                   # Benchmark contract, moderation guide, reproduce guide
│   ├── ARCHITECTURE.md     #   Full system architecture reference
│   └── REPRODUCE.md        #   Step-by-step stranger reproduction guide
└── results/                # Benchmark data (gitignored)
```

## Quick Start

### Prerequisites

| Tool | Needed for | Install |
|------|-----------|---------|
| [Rust](https://rustup.rs/) + `wasm32-wasip1` | Build gateway | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh && rustup target add wasm32-wasip1` |
| [Spin CLI](https://developer.fermyon.com/spin/install) | Build + deploy | `curl -fsSL https://developer.fermyon.com/downloads/install.sh \| bash` |
| Spin aka plugin | Akamai Functions | `spin plugins install aka` |
| [Fastly CLI](https://www.fastly.com/documentation/reference/cli/) | Fastly Compute deploy | `brew install fastly/tap/fastly` |
| [Node.js](https://nodejs.org/) 18+ | Frontend build | `brew install node` or [nodejs.org](https://nodejs.org) |
| [k6](https://k6.io) | Benchmarks | `brew install k6` |
| Python 3 | Medians + scorecard | Pre-installed on macOS/Ubuntu |
| [linode-cli](https://www.linode.com/docs/products/tools/cli/) | Multi-region runners | `pip install linode-cli` (optional) |

Check all at once: `make prereqs`

### Build & Run Locally

```bash
# Build everything (gateway + frontend)
make build

# Or step by step:
cd edge-gateway
cargo build --target wasm32-wasip1 --release -p clipclap-gateway-spin
cd ../frontend && npm install && npm run build
cp -r dist/* ../edge-gateway/adapters/spin/static/

# Run locally
cd ../edge-gateway/adapters/spin
spin up
```

### Deploy to Fermyon Cloud

```bash
make deploy-fermyon
# or: cd edge-gateway/adapters/spin && spin cloud deploy
```

### Deploy to Akamai Functions

```bash
spin aka login    # one-time auth
make deploy-akamai
# or: cd edge-gateway/adapters/spin && spin aka deploy --no-confirm
```

### Deploy to Fastly Compute

```bash
fastly auth login    # one-time auth
make deploy-fastly
# or: cd edge-gateway/adapters/fastly && fastly compute publish
```

## ML Model

| Property | Value |
|----------|-------|
| Model | MiniLMv2-toxic-jigsaw |
| Parameters | 22.7M |
| Format | NNEF (Tract native) |
| Vocab size | 8,000 tokens |
| Model file | ~53 MB |
| Inference | ~779ms (Akamai Functions) / ~1,760ms (Fermyon Cloud) / N/A (Fastly — no FS) |
| Categories | `toxic`, `severe_toxic` |

The model runs entirely inside the WASM sandbox — no external ML service calls. It was exported from PyTorch to ONNX, vocabulary-trimmed from 30k to 8k tokens to fit deployment size limits, then converted to Tract's NNEF format to avoid expensive protobuf parsing in the WASM runtime.

## Benchmark

See the full [measurement contract](docs/benchmark_contract.md) (v3.1) for schemas, SLOs, and fairness rules.

### Primary Suite — Rule-Based Pipeline (what customers deploy)

| Test | Script | What It Measures |
|------|--------|-----------------|
| Warm Light | `warm-light.js` | Minimal-work latency (`GET /health`) |
| Warm Policy | `warm-policy.js` | Full 6-step rule pipeline with text (`ml: false`) |
| Concurrency Ladder | `concurrency-ladder.js` | Scaling under 1→50 VUs, rules only |
| Cold Start (rules) | `cold-start.js` | WASM instantiation, no ML model load |

### Stretch Suite — Embedded ML (demonstrates limits)

| Test | Script | What It Measures |
|------|--------|-----------------|
| Warm Heavy | `warm-heavy.js` | Full moderation + ML inference |
| Consistency (ML) | `consistency.js` | ML latency jitter over 120s |
| Cold Start (ML) | `cold-start.js` | WASM instantiation + 53MB model deserialization |

The `ml` field in the request body controls whether ML inference runs. Default is `true` for backward compatibility; benchmarks use `ml: false` for the primary suite.

```bash
# Fermyon Cloud
make benchmark PLATFORM=fermyon URL=https://wasm-prompt-firewall-imjy4pe0.fermyon.app

# Akamai Functions
make benchmark PLATFORM=akamai URL=https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app

# Fastly Compute (rules-only, no ML)
make benchmark PLATFORM=fastly URL=https://morally-civil-urchin.edgecompute.app

# With ML + cold start (~100 min)
make benchmark PLATFORM=akamai URL=https://your-gateway.fwf.app BENCH_FLAGS="--ml --cold"

# Multi-region (from 3 k6 runners)
make bench-multiregion PLATFORM=akamai URL=https://your-gateway.fwf.app BENCH_FLAGS="--ml --cold"
```

## API

### `POST /gateway/moderate`

```json
{
  "labels": ["safe", "unsafe"],
  "nonce": "unique-request-id",
  "text": "The prompt to evaluate",
  "ml": false
}
```

Set `ml: false` for rules-only (recommended for production). Omit or set `ml: true` to include ML toxicity inference.

**Rules-only response** (`ml: false`) — ~3ms (Fastly Compute) / ~2.3ms (Akamai Functions) / ~5.5ms (Fermyon Cloud):

```json
{
  "verdict": "allow",
  "moderation": {
    "policy_flags": [],
    "confidence": 0.0,
    "blocked_terms": [],
    "processing_ms": 2.3
  },
  "cache": { "hit": false, "hash": "sha256:..." },
  "gateway": { "platform": "Akamai Functions", "region": "us-ord", "request_id": "..." }
}
```

**With ML response** (`ml: true`) — ~779ms (Akamai Functions) / ~1,760ms (Fermyon Cloud):

```json
{
  "verdict": "allow",
  "moderation": {
    "policy_flags": [],
    "confidence": 0.0,
    "blocked_terms": [],
    "processing_ms": 781.7,
    "ml_toxicity": {
      "toxic": 0.001,
      "severe_toxic": 0.0001,
      "inference_ms": 779.3,
      "model": "MiniLMv2-toxic-jigsaw"
    }
  },
  "cache": { "hit": false, "hash": "sha256:..." },
  "gateway": { "platform": "Akamai Functions", "region": "us-ord", "request_id": "..." }
}
```

### `GET /gateway/health`

Returns gateway status, platform, region, and ML model readiness.

## License

See [LICENSE](LICENSE).
