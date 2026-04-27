# WASMnism

**WASM-Powered Content Moderation at the Edge**

A portable WASM-powered content moderation gateway deployed as WebAssembly across three WASM-first edge platforms. Built to compare edge compute providers for a real-world workload.

> **Status**: All three Tier 1 platforms are live and deployed.

> For ML inference benchmarks (Tier 2: Akamai Functions vs AWS Lambda), see the `ml-inference` branch.

**Live demos**:
- Akamai Functions: [0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app](https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app/)
- Fastly Compute: [morally-civil-urchin.edgecompute.app](https://morally-civil-urchin.edgecompute.app/)
- Cloudflare Workers: [wasm-prompt-firewall.jgdynamite2000qx.workers.dev](https://wasm-prompt-firewall.jgdynamite2000qx.workers.dev/)

---

## What's Been Built

### Edge Gateway (Rust → WASM)

A single Rust codebase compiled to WASM that runs a 7-step moderation pipeline entirely at the edge:

1. **Unicode NFC normalization** — canonical text form
2. **SHA-256 content hashing** — cache key + deduplication
3. **Leetspeak expansion** — `h@t3` → `hate`, `k1ll` → `kill`
4. **Prohibited content scan** — multi-pattern matching on expanded text
5. **PII detection** — email, phone, SSN regex
6. **Injection detection** — XSS, SQL injection patterns
7. **Policy verdict** — merge all signals into `allow`, `review`, or `block`

### Frontend Dashboard

A Svelte SaaS-style dashboard with:
- Real-time prompt evaluation against the live edge gateway
- Pipeline visualization with color-coded status
- Timing breakdown (client round-trip, gateway processing)
- Pre-built example prompts spanning safe text, injection attacks, PII, and leetspeak evasion

### Deployments

| Platform | Adapter | WASM Target | Status |
|----------|---------|-------------|--------|
| **Akamai Functions** (Spin) | `edge-gateway/adapters/spin/` | `wasm32-wasip1` | Deployed |
| **Fastly Compute** | `edge-gateway/adapters/fastly/` | `wasm32-wasip1` | Deployed |
| **Cloudflare Workers** | `edge-gateway/adapters/workers/` | `wasm32-unknown-unknown` | Deployed |

### Benchmark Infrastructure

- **Primary suite**: warm light, warm policy, concurrency ladder (1→50 VUs), sustained 50 VU, cold start
- **Extended suite**: full ladder (1→1,000 VUs), soak (500 VUs / 10 min), spike (0→2,000 VUs)
- Suite runner, 7-run median calculator, scorecard generator, and multi-region orchestrator
- Automated reproduce pipeline: `make benchmark` (single region) or `make bench-multiregion` (3 regions)
- **Dual-origin runners**: Linode (Akamai-owned) and GCP (neutral) for bias-controlled comparisons
- Multi-region k6 infrastructure: Linode Nanodes or GCP e2-standard-4 in US, EU, and APAC
- Measurement contract v3.4 with 8-scenario validation suite for correctness

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
                        │  │   workers/)  │    │  3. Verdict merge      │  │
                         │  └─────────────┘    └────────────────────────┘  │
                         └─────────────────────────────────────────────────┘
```

The gateway is a single Rust codebase with thin platform adapters. The core library compiles to `wasm32-wasip1` (Akamai, Fastly) and `wasm32-unknown-unknown` (Cloudflare Workers).

## Project Structure

```
WASMnism/
├── Makefile                # Root automation: make build, make benchmark, make runners-up, etc.
├── edge-gateway/           # Rust workspace
│   ├── core/               #   Shared logic: pipeline, policy, normalize, hash, cache, timing
│   ├── adapters/           #   Platform-specific HTTP adapters
│   │   ├── spin/           #     Akamai Functions
│   │   ├── fastly/         #     Fastly Compute
│   │   └── workers/        #     Cloudflare Workers
├── frontend/               # Svelte dashboard (built → embedded in each adapter)
├── bench/                  # k6 benchmark scripts + automation
│   ├── reproduce.sh        #   End-to-end pipeline: validate → 7-run → medians
│   ├── run-multiregion.sh  #   Distribute to 3 k6 runners in parallel
│   ├── run-suite.sh        #   Single benchmark suite run
│   └── run-7x.sh           #   7-run median calculator
├── deploy/                 # Deployment + infrastructure
│   ├── k6-runner-setup.sh  #   Provision/teardown 3 Linode k6 runners
│   ├── gcp-runner-setup.sh #   Provision/teardown 3 GCP k6 runners (neutral origin)
│   └── runners.env         #   Runner IPs (gitignored)
├── cost/                   # Cost model per 1M requests
├── docs/                   # Benchmark contract, moderation guide, reproduce guide
│   ├── ARCHITECTURE.md     #   Full system architecture reference
│   ├── benchmark_rollout_plan_public_stub.md  #  Pointer: full plan is local (gitignored)
│   └── REPRODUCE.md        #   Step-by-step reproduction guide
└── results/                # Benchmark data (gitignored — not in this repository)
```

## Quick Start

### Prerequisites

| Tool | Needed for | Install |
|------|-----------|---------|
| [Rust](https://rustup.rs/) + `wasm32-wasip1` | Build gateway | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh && rustup target add wasm32-wasip1` |
| [Spin CLI](https://developer.fermyon.com/spin/install) | Akamai deploy | `curl -fsSL https://developer.fermyon.com/downloads/install.sh \| bash` |
| Spin aka plugin | Akamai Functions | `spin plugins install aka` |
| [Fastly CLI](https://www.fastly.com/documentation/reference/cli/) | Fastly Compute deploy | `brew install fastly/tap/fastly` |
| [Wrangler CLI](https://developers.cloudflare.com/workers/wrangler/) | Cloudflare Workers deploy | `npx wrangler login` (via npx, no global install) |
| [Node.js](https://nodejs.org/) 18+ | Frontend build | `brew install node` or [nodejs.org](https://nodejs.org) |
| [k6](https://k6.io) | Benchmarks | `brew install k6` |
| Python 3 | Medians + scorecard | Pre-installed on macOS/Ubuntu |

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
# Akamai Functions
make deploy-akamai

# Fastly Compute
make deploy-fastly

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

Set `"ml": false` (ML is not available on this branch).

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

Returns gateway status, platform, and region.

## Benchmark

See the full [measurement contract](docs/benchmark_contract.md) (v3.4) for schemas, SLOs, and fairness rules.

### Running Benchmarks

```bash
# Single platform, base suite (~40 min)
make benchmark PLATFORM=akamai URL=<endpoint-url>

# Multi-region from Linode runners (~90 min per platform)
make bench-multiregion PLATFORM=fastly URL=<endpoint-url>

# Multi-region from GCP runners — neutral origin, recommended (~90 min per platform)
make bench-multiregion-gcp PLATFORM=akamai URL=<endpoint-url>

# Extended suite: 1K ladder + soak + spike (~32 min per platform)
make bench-full-gcp PLATFORM=akamai URL=<endpoint-url>
```

See [docs/REPRODUCE.md](docs/REPRODUCE.md) for the full reproduction guide.

## License

See [LICENSE](LICENSE).
