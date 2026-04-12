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
# Linode CLI
pip install linode-cli
linode-cli configure   # Provide your Linode API token

# SSH key (runners are provisioned with your ~/.ssh/id_ed25519.pub)
```

### Verify all prerequisites

```bash
make prereqs
```

## Quick Reproduce (single region, from your machine)

### 1. Download ML model files (optional — needed only for `ml: true` tests)

```bash
cd edge-gateway/models/toxicity/
gh release download v0.2.0-models --repo jgdynamite/WASMnism

# Verify checksums
shasum -a 256 -c << 'CHECKSUMS'
aaf95fcf4aef8e7636a7bf40e2cb3f4ed03eb039b8bd32e96c348224bca99377  model.nnef.tar
04332de50cb467423bfd623703c8c05e830a57a2f325cda835a29bef7626655f  vocab.txt
CHECKSUMS
cd ../../..
```

The rules-only pipeline (`ml: false`) — which is the primary benchmark suite — builds and runs without the model files.

### 2. Build and deploy

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

### 3. Run the full pipeline

```bash
# Primary suite only (~40 min: validate + 7 runs)
make benchmark PLATFORM=akamai  URL=https://your-gateway.fwf.app
make benchmark PLATFORM=fastly  URL=https://your-gateway.edgecompute.app
make benchmark PLATFORM=workers URL=https://your-worker.your-subdomain.workers.dev

# Primary + stretch (ML) suite (~60 min) — not available on Fastly or Workers
make benchmark PLATFORM=akamai URL=https://your-gateway.fwf.app BENCH_FLAGS="--ml"

# Everything including cold start (~100 min) — not available on Fastly
make benchmark PLATFORM=akamai URL=https://your-gateway.fwf.app BENCH_FLAGS="--ml --cold"
```

This runs: prerequisite check -> validation (9/9 must pass) -> 7-run suite -> median computation -> results document.

Results are saved to `results/<platform>/`.

## Full Reproduce (multi-region)

### 1. Provision k6 runners

This creates 3 Linode Nanodes ($5/mo each) in Chicago, Frankfurt, and Singapore:

```bash
make runners-up
```

This takes ~5 minutes. Runner IPs are saved to `deploy/runners.env` (gitignored).

### 2. Verify runners

```bash
make runners-status
```

### 3. Run multi-region benchmark

```bash
# From all 3 regions in parallel
make bench-multiregion PLATFORM=akamai  URL=https://your-gateway.fwf.app BENCH_FLAGS="--ml --cold"
make bench-multiregion PLATFORM=fastly  URL=https://your-gateway.edgecompute.app
make bench-multiregion PLATFORM=workers URL=https://your-worker.your-subdomain.workers.dev
```

This SSHs into each runner, executes the full reproduce pipeline, and
collects results back to `results/<platform>/multiregion_<timestamp>/`.

### 4. Teardown runners (when done)

```bash
make runners-down
```

## Comparing Platforms

Once you have results for two or more platforms:

```bash
make scorecard \
  A=results/akamai/multiregion_20260404/us-ord/7run \
  B=results/fastly/multiregion_20260404/us-ord/7run \
  OUT=results/scorecard_akamai_vs_fastly.md
```

## Adding a New Platform

1. Implement the adapter in `edge-gateway/adapters/<platform>/`
   (see [MODERATION_GUIDE.md](MODERATION_GUIDE.md) for the adapter checklist)
2. Add `make deploy-<platform>` target to `edge-gateway/Makefile`
3. Deploy to the platform
4. Run: `make benchmark PLATFORM=<name> URL=<url> BENCH_FLAGS="--ml"`
5. Or multi-region: `make bench-multiregion PLATFORM=<name> URL=<url>`
6. Compare: `make scorecard A=results/akamai/... B=results/<platform>/...`

No new benchmark scripts, runners, or documentation needed.

## ML Model

The 53MB ML model (`model.nnef.tar`) is gitignored due to size. Download it from the GitHub Release:

```bash
cd edge-gateway/models/toxicity/
gh release download v0.2.0-models --repo jgdynamite/WASMnism
```

Or download manually from: https://github.com/jgdynamite/WASMnism/releases/tag/v0.2.0-models

The model must be at `edge-gateway/models/toxicity/model.nnef.tar` before building with ML support.

See [edge-gateway/models/README.md](../edge-gateway/models/README.md) for:
- Base model source (HuggingFace) and fine-tuning dataset (Jigsaw/Kaggle)
- Full conversion pipeline (PyTorch → ONNX → vocabulary trim → Tract NNEF)
- How to regenerate from scratch
- SHA-256 checksums

Verify model integrity:

```bash
cd edge-gateway/models
shasum -a 256 -c << 'CHECKSUMS'
aaf95fcf4aef8e7636a7bf40e2cb3f4ed03eb039b8bd32e96c348224bca99377  toxicity/model.nnef.tar
04332de50cb467423bfd623703c8c05e830a57a2f325cda835a29bef7626655f  toxicity/vocab.txt
CHECKSUMS
```

## Interpreting Results

### Key metrics

| Metric | What it means |
|--------|--------------|
| **Server processing p50** | Time the gateway spends on your request (rules only). Isolates compute from network. |
| **Round-trip p50** | Total client-to-server-to-client time. Includes network latency. |
| **ML inference p50** | Time for the neural network forward pass. Only on platforms with ML support. |
| **Jitter (p95/p50)** | Latency consistency — lower is better. |
| **Error rate** | Percentage of failed requests. |

Platform-specific benchmark results are in `results/` (gitignored — not in this repository). Run the benchmark yourself to generate them.

### Network latency caveat

Round-trip latency includes network time between the k6 runner and the
gateway. The server processing time (`proc_p50`) isolates actual gateway
computation. When comparing platforms, use server-side metrics to compare
compute performance and round-trip metrics to compare end-user experience.

### Cold start

Rules-only cold start measures WASM module instantiation overhead.
ML cold start adds model deserialization overhead for the 53MB NNEF model.
These are separate concerns — most production deployments would use
`ml: false` and never hit the model loading path.

## Known Caveats

- **k6 maxDuration**: Cold start tests need high `maxDuration` (10 iterations x 120s gaps). The script sets this dynamically.
- **Paid tiers**: All platforms must use paid tiers for benchmark accuracy. See `.cursorrules` for tier details.
- **Runner location matters**: Multi-region results isolate network latency. Single-region results from your laptop include your ISP latency.
- **Model consistency**: All platforms must use the same `model.nnef.tar` and `vocab.txt`. Verify with checksums above.
