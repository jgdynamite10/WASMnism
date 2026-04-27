# Reproducing the WASMnism Benchmark

Step-by-step guide for reproducing the WASM edge gateway benchmark from scratch.

## Prerequisites

### Build tools

```bash
# Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup target add wasm32-wasip1

# Spin CLI
curl -fsSL https://developer.fermyon.com/downloads/install.sh | bash
sudo mv spin /usr/local/bin/

# Spin aka plugin (for Akamai Functions deployment)
spin plugins install aka

# Fastly CLI (for Fastly Compute deployment)
brew install fastly/tap/fastly

# Wrangler CLI (for Cloudflare Workers deployment — installed via npx, no global install needed)
# npx wrangler login

# Node.js (for frontend)
# macOS:
brew install node
# Ubuntu:
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs
```

### Benchmark tools

```bash
# k6
# macOS:
brew install k6
# Ubuntu:
curl -fsSL https://dl.k6.io/key.gpg | gpg --dearmor -o /usr/share/keyrings/k6.gpg
echo 'deb [signed-by=/usr/share/keyrings/k6.gpg] https://dl.k6.io/deb stable main' | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update && sudo apt-get install -y k6

# Python 3 (stdlib only — no pip packages needed)
# macOS: pre-installed or `brew install python3`
# Ubuntu: pre-installed or `sudo apt-get install -y python3`
```

### Multi-region tools (optional, for full reproduce)

```bash
# Linode CLI (Akamai-owned origin)
pip install linode-cli
linode-cli configure   # Provide your Linode API token

# GCP CLI (neutral origin — recommended for unbiased results)
# Install: https://cloud.google.com/sdk/docs/install
gcloud auth login
gcloud config set project <your-project-id>

# SSH key (runners are provisioned with your ~/.ssh/id_ed25519.pub)
```

### Verify all prerequisites

```bash
make prereqs
```

## Quick Reproduce (single region, from your machine)

> **Note:** ML model files are only needed on the `ml-inference` branch (Tier 2). This branch runs rules-only.

### 1. Build and deploy

```bash
# Build WASM gateway + frontend
make build

# Deploy to Akamai Functions (requires `spin aka login` first)
make deploy-akamai

# Or deploy to Fastly Compute (requires `fastly auth login` first)
make deploy-fastly

# Or deploy to Cloudflare Workers (requires `npx wrangler login` first)
make deploy-workers
```

### 2. Run the full pipeline

```bash
# Primary suite only (~40 min: validate + 7 runs)
make benchmark PLATFORM=akamai  URL=https://your-gateway.fwf.app
make benchmark PLATFORM=fastly  URL=https://your-gateway.edgecompute.app
make benchmark PLATFORM=workers URL=https://your-worker.your-subdomain.workers.dev

# With cold start tests (~60 min)
make benchmark PLATFORM=akamai URL=https://your-gateway.fwf.app BENCH_FLAGS="--cold"
```

This runs: prerequisite check -> validation (8/8 must pass) -> 7-run suite -> median computation -> results document.

Results are saved to `results/<platform>/`.

## Full Reproduce (multi-region)

### Option A: Linode Runners (Akamai-owned origin)

> **Bias note:** Linode is owned by Akamai. Traffic to Akamai edge PoPs
> may use Akamai's private backbone, giving Akamai a network advantage.
> For unbiased results, use GCP runners (Option B) or run both.

```bash
# 1. Provision 3 Linode Nanodes ($5/mo each) in Chicago, Frankfurt, Singapore
make runners-up          # ~5 min; IPs saved to deploy/runners.env

# 2. Verify
make runners-status

# 3. Run base suite from all 3 regions
make bench-multiregion PLATFORM=akamai  URL=https://your-gateway.fwf.app BENCH_FLAGS="--cold"
make bench-multiregion PLATFORM=fastly  URL=https://your-gateway.edgecompute.app
make bench-multiregion PLATFORM=workers URL=https://your-worker.your-subdomain.workers.dev

# 4. Teardown
make runners-down
```

### Option B: GCP Runners (Neutral origin — recommended)

GCP is not owned by any CDN vendor, eliminating backbone bias.
Uses `e2-standard-4` (4 vCPU, 16 GB) in Iowa, Belgium, Singapore.

```bash
# 1. Provision 3 GCP instances (~$0.13/hr each)
make gcp-runners-up      # ~5 min; IPs saved to deploy/gcp-runners.env

# 2. Verify
make gcp-runners-status

# 3a. Base suite (same as Linode, but from neutral origin)
make bench-multiregion-gcp PLATFORM=akamai  URL=https://your-gateway.fwf.app BENCH_FLAGS="--cold"
make bench-multiregion-gcp PLATFORM=fastly  URL=https://your-gateway.edgecompute.app
make bench-multiregion-gcp PLATFORM=workers URL=https://your-worker.your-subdomain.workers.dev

# 3b. Extended suite (full ladder to 1K VUs + soak + spike)
make bench-full-gcp PLATFORM=akamai  URL=https://your-gateway.fwf.app
make bench-full-gcp PLATFORM=fastly  URL=https://your-gateway.edgecompute.app
make bench-full-gcp PLATFORM=workers URL=https://your-worker.your-subdomain.workers.dev

# 4. Teardown
make gcp-runners-down
```

### Running the Extended Suite Locally

```bash
# Full suite on a single machine (requires enough CPU/RAM for 1K VUs)
make bench-full PLATFORM=akamai URL=https://your-gateway.fwf.app
make bench-full PLATFORM=akamai URL=https://your-gateway.fwf.app BENCH_FLAGS="--cold"
```

### Time Estimates

| Suite | Per platform | With cold start |
|-------|-------------|-----------------|
| Base (7-run reproduce) | ~40 min | ~60 min |
| Full (base + extended) | ~32 min | ~52 min |
| Extended only | ~20 min | ~40 min |

## Comparing Platforms

Once you have results for all three platforms:

```bash
make scorecard \
  A=results/akamai/multiregion_20260413/us-ord/7run \
  B=results/fastly/multiregion_20260413/us-ord/7run \
  C=results/workers/multiregion_20260413/us-ord/7run \
  OUT=results/scorecard_3way.md
```

## Adding a New Platform

1. Implement the adapter in `edge-gateway/adapters/<platform>/`
   (see [MODERATION_GUIDE.md](MODERATION_GUIDE.md) for the adapter checklist)
2. Add `make deploy-<platform>` target to `edge-gateway/Makefile`
3. Deploy to the platform
4. Run: `make benchmark PLATFORM=<name> URL=<url>`
5. Or multi-region: `make bench-multiregion PLATFORM=<name> URL=<url>`
6. Compare: `make scorecard A=results/akamai/... B=results/<platform>/...`

No new benchmark scripts, runners, or documentation needed.

> ML model files are used on the `ml-inference` branch only. See that branch for model download instructions.

## Interpreting Results

### Key metrics

| Metric | What it means |
|--------|--------------|
| **Server processing p50** | Time the gateway spends on your request (rules only). Isolates compute from network. |
| **Round-trip p50** | Total client-to-server-to-client time. Includes network latency. |
| **Jitter (p95/p50)** | Latency consistency — lower is better. |
| **Error rate** | Percentage of failed requests. |

Platform-specific benchmark results are in `results/` (gitignored — not in this repository). Run the benchmark yourself to generate them.

### Network latency caveat

Round-trip latency includes network time between the k6 runner and the
gateway. The server processing time (`proc_p50`) isolates actual gateway
computation. When comparing platforms, use server-side metrics to compare
compute performance and round-trip metrics to compare end-user experience.

### Cold start

Cold start measures WASM module instantiation overhead for the rules-only pipeline.

## Known Caveats

- **k6 maxDuration**: Cold start tests need high `maxDuration` (10 iterations x 120s gaps). The script sets this dynamically.
- **Paid tiers**: All platforms must use paid tiers for benchmark accuracy. See `.cursorrules` for tier details.
- **Runner location matters**: Multi-region results isolate network latency. Single-region results from your laptop include your ISP latency.
- **Origin bias**: Linode is Akamai-owned. For unbiased results, run from GCP or run from both and compare. See `docs/benchmark_contract.md` Section 7.3.2.
- **High VU runner sizing**: The extended suite (1,000 VUs, soak, spike) requires ≥4 vCPU / 16 GB runners. Linode Nanodes (1 vCPU) cannot run the extended suite — use GCP `e2-standard-4` instances.
- **Spike distribution**: For 2,000+ VU spike tests, the load is distributed across 3 runners (~667 VUs each). A single runner above ~1,000 VUs may bottleneck on the runner itself rather than the gateway.
