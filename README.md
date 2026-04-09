# WASMnism

**WASM-Powered Content Moderation at the Edge**

A portable AI Prompt Firewall deployed as WebAssembly across multiple edge platforms, with an embedded ML toxicity classifier running entirely inside the WASM runtime. Built to compare WASM edge compute providers for a real-world workload.

> **Status**: All five platforms are live and deployed.

**Live demos**:
- Fermyon Cloud: [wasm-prompt-firewall-imjy4pe0.fermyon.app](https://wasm-prompt-firewall-imjy4pe0.fermyon.app/)
- Akamai Functions: [0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app](https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app/)
- Fastly Compute: [morally-civil-urchin.edgecompute.app](https://morally-civil-urchin.edgecompute.app/)
- AWS Lambda: [mktmxuqwtkv7ckfkunlyypga4a0sdwwb.lambda-url.us-east-1.on.aws](https://mktmxuqwtkv7ckfkunlyypga4a0sdwwb.lambda-url.us-east-1.on.aws/)
- Cloudflare Workers: [wasm-prompt-firewall.jgdynamite2000qx.workers.dev](https://wasm-prompt-firewall.jgdynamite2000qx.workers.dev/)

---

## What's Been Built

### Edge Gateway (Rust → WASM)

A single Rust codebase compiled to WASM that runs an 8-step moderation pipeline entirely at the edge:

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

| Platform | Adapter | WASM Target | Status |
|----------|---------|-------------|--------|
| **Fermyon Cloud** (Spin) | `edge-gateway/adapters/spin/` | `wasm32-wasip1` | Deployed |
| **Akamai Functions** (Spin) | `edge-gateway/adapters/spin/` | `wasm32-wasip1` | Deployed |
| **Fastly Compute** | `edge-gateway/adapters/fastly/` | `wasm32-wasip1` | Deployed |
| **AWS Lambda** | `edge-gateway/adapters/lambda/` | Native ARM64 | Deployed |
| **Cloudflare Workers** | `edge-gateway/adapters/workers/` | `wasm32-unknown-unknown` | Deployed |

### ML Model Pipeline

- **Model**: MiniLMv2 fine-tuned on Jigsaw toxic-comment data (22.7M parameters)
- **Export**: PyTorch → ONNX (opset 14, fixed shapes) → vocabulary-trimmed (30k → 8k tokens) → Tract NNEF
- **Runtime**: Pure-Rust inference via Tract, with a custom WordPiece tokenizer — no Python, no external service calls
- **Size**: ~53 MB model + 56 KB vocabulary
- **Download**: `cd edge-gateway/models/toxicity/ && gh release download v0.2.0-models` ([release page](https://github.com/jgdynamite/WASMnism/releases/tag/v0.2.0-models))
- **Base model**: [nreimers/MiniLMv2-L6-H384-distilled-from-RoBERTa-Large](https://huggingface.co/nreimers/MiniLMv2-L6-H384-distilled-from-RoBERTa-Large) (HuggingFace)
- **Dataset**: [Jigsaw Toxic Comment Classification](https://www.kaggle.com/c/jigsaw-toxic-comment-classification-challenge) (Kaggle)
- **ML availability**: Fermyon Cloud, Akamai Functions, AWS Lambda (native). Not available on Fastly (no filesystem) or Cloudflare Workers (no WASI).

### Benchmark Infrastructure

- **Primary suite**: rule-based pipeline benchmarks — warm light, warm policy, concurrency ladder
- **Stretch suite**: embedded ML inference benchmarks — warm heavy, consistency
- Cold start tests for both modes
- Suite runner, 7-run median calculator, scorecard generator, and multi-region runner
- Automated reproduce pipeline: `make benchmark` (single region) or `make bench-multiregion` (3 regions)
- Multi-region k6 infrastructure: automated provisioning of Linode VMs in us-ord, eu-central, ap-south
- Measurement contract v3.1 with 9-scenario validation suite for correctness

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

The gateway is a single Rust codebase with thin platform adapters. The core library compiles to `wasm32-wasip1` (Fermyon, Akamai, Fastly), `wasm32-unknown-unknown` (Cloudflare Workers), and native ARM64 (AWS Lambda).

## Project Structure

```
WASMnism/
├── Makefile                # Root automation: make build, make benchmark, make runners-up, etc.
├── edge-gateway/           # Rust workspace
│   ├── core/               #   Shared logic: pipeline, policy, toxicity, tokenizer, timing
│   ├── adapters/           #   Platform-specific HTTP adapters
│   │   ├── spin/           #     Fermyon Cloud + Akamai Functions
│   │   ├── fastly/         #     Fastly Compute
│   │   ├── workers/        #     Cloudflare Workers
│   │   └── lambda/         #     AWS Lambda
│   ├── models/toxicity/    #   ML model + vocab (see models/README.md for provenance)
│   └── tools/              #   ONNX → NNEF conversion tool
├── frontend/               # Svelte dashboard (built → embedded in each adapter)
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
│   └── REPRODUCE.md        #   Step-by-step reproduction guide
└── results/                # Benchmark data (gitignored — not in this repository)
```

## Quick Start

### Prerequisites

| Tool | Needed for | Install |
|------|-----------|---------|
| [Rust](https://rustup.rs/) + `wasm32-wasip1` | Build gateway | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh && rustup target add wasm32-wasip1` |
| [Spin CLI](https://developer.fermyon.com/spin/install) | Fermyon / Akamai deploy | `curl -fsSL https://developer.fermyon.com/downloads/install.sh \| bash` |
| Spin aka plugin | Akamai Functions | `spin plugins install aka` |
| [Fastly CLI](https://www.fastly.com/documentation/reference/cli/) | Fastly Compute deploy | `brew install fastly/tap/fastly` |
| [cargo-lambda](https://www.cargo-lambda.info/) | AWS Lambda deploy | `brew tap cargo-lambda/cargo-lambda && brew install cargo-lambda` |
| [Wrangler CLI](https://developers.cloudflare.com/workers/wrangler/) | Cloudflare Workers deploy | `npx wrangler login` (via npx, no global install) |
| [Node.js](https://nodejs.org/) 18+ | Frontend build | `brew install node` or [nodejs.org](https://nodejs.org) |
| [k6](https://k6.io) | Benchmarks | `brew install k6` |
| Python 3 | Medians + scorecard | Pre-installed on macOS/Ubuntu |
| [linode-cli](https://www.linode.com/docs/products/tools/cli/) | Multi-region runners | `pip install linode-cli` (optional) |

Check all at once: `make prereqs`

### Build & Run Locally

```bash
# Build everything (gateway + frontend)
make build

# Run locally with Spin
cd edge-gateway/adapters/spin
spin up
```

### Deploy

```bash
# Fermyon Cloud
make deploy-fermyon

# Akamai Functions
make deploy-akamai

# Fastly Compute
make deploy-fastly

# AWS Lambda
make deploy-lambda

# Cloudflare Workers
make deploy-workers
```

Each deploy target builds the frontend, copies it to the adapter's static directory, builds the adapter, and deploys. See [docs/REPRODUCE.md](docs/REPRODUCE.md) for detailed instructions.

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

**Response:**

```json
{
  "verdict": "allow",
  "moderation": {
    "policy_flags": [],
    "confidence": 0.0,
    "blocked_terms": [],
    "processing_ms": 3.2
  },
  "cache": { "hit": false, "hash": "sha256:..." },
  "gateway": { "platform": "...", "region": "...", "request_id": "..." }
}
```

### `GET /gateway/health`

Returns gateway status, platform, region, and ML model readiness.

## Benchmark

See the full [measurement contract](docs/benchmark_contract.md) (v3.1) for schemas, SLOs, and fairness rules.

### Running Benchmarks

```bash
# Single platform (rules-only, ~40 min)
make benchmark PLATFORM=<name> URL=<endpoint-url>

# With ML inference (~60 min)
make benchmark PLATFORM=<name> URL=<endpoint-url> BENCH_FLAGS="--ml"

# Multi-region (from 3 k6 runners, ~90 min)
make bench-multiregion PLATFORM=<name> URL=<endpoint-url>
```

See [docs/REPRODUCE.md](docs/REPRODUCE.md) for the full reproduction guide.

## License

See [LICENSE](LICENSE).
