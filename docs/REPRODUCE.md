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

# cargo-lambda (for AWS Lambda deployment)
brew tap cargo-lambda/cargo-lambda && brew install cargo-lambda

# AWS CLI (for Lambda infrastructure)
brew install awscli

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

### 1. Build and deploy

```bash
# Build WASM gateway + frontend
make build

# Deploy to Fermyon Cloud (requires `spin cloud login` first)
make deploy-fermyon

# Or deploy to Akamai Functions (requires `spin aka login` first)
make deploy-akamai

# Or deploy to Fastly Compute (requires `fastly auth login` first)
make deploy-fastly

# Or deploy to AWS Lambda (requires AWS CLI configured + cargo-lambda installed)
make deploy-lambda

# Or deploy to Cloudflare Workers (requires `npx wrangler login` first)
make deploy-workers
```

### 2. Run the full pipeline

```bash
# Primary suite only (~40 min: validate + 7 runs)
make benchmark PLATFORM=fermyon URL=https://your-gateway.fermyon.app
make benchmark PLATFORM=akamai  URL=https://your-gateway.fwf.app
make benchmark PLATFORM=fastly  URL=https://your-gateway.edgecompute.app
make benchmark PLATFORM=lambda  URL=https://your-lambda-function-url.lambda-url.us-east-1.on.aws
make benchmark PLATFORM=workers URL=https://your-worker.your-subdomain.workers.dev

# Primary + stretch (ML) suite (~60 min) — not available on Fastly or Workers
make benchmark PLATFORM=akamai URL=https://your-gateway.fwf.app BENCH_FLAGS="--ml"
make benchmark PLATFORM=lambda URL=https://your-lambda-function-url.lambda-url.us-east-1.on.aws BENCH_FLAGS="--ml"

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
make bench-multiregion PLATFORM=fermyon URL=https://your-gateway.fermyon.app BENCH_FLAGS="--ml --cold"
make bench-multiregion PLATFORM=akamai  URL=https://your-gateway.fwf.app BENCH_FLAGS="--ml --cold"
make bench-multiregion PLATFORM=fastly  URL=https://your-gateway.edgecompute.app
make bench-multiregion PLATFORM=lambda  URL=https://your-lambda-function-url.lambda-url.us-east-1.on.aws --cold
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
  A=results/fermyon/multiregion_20260402/us-ord/7run \
  B=results/akamai/multiregion_20260404/us-ord/7run \
  OUT=results/scorecard_fermyon_vs_akamai.md
```

## Adding a New Platform

1. Implement the adapter in `edge-gateway/adapters/<platform>/`
   (see [MODERATION_GUIDE.md](MODERATION_GUIDE.md) for the adapter checklist)
2. Add `make deploy-<platform>` target to `edge-gateway/Makefile`
3. Deploy to the platform
4. Run: `make benchmark PLATFORM=<name> URL=<url> BENCH_FLAGS="--ml"`
5. Or multi-region: `make bench-multiregion PLATFORM=<name> URL=<url>`
6. Compare: `make scorecard A=results/fermyon/... B=results/<platform>/...`

No new benchmark scripts, runners, or documentation needed.

## ML Model

The 53MB ML model (`model.nnef.tar`) is gitignored due to size. It must be
present at `edge-gateway/models/toxicity/model.nnef.tar` before building.

See [edge-gateway/models/README.md](../edge-gateway/models/README.md) for:
- Model provenance and SHA-256 checksums
- How to regenerate from scratch
- Why NNEF format was chosen over ONNX

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

| Metric | What it means | Fermyon Cloud | Akamai Functions | Fastly Compute | AWS Lambda | Cloudflare Workers |
|--------|--------------|---------------|-----------------|---------------|------------|-------------------|
| **Server processing p50** | Time the gateway spends on your request (rules only) | 5.4-5.5ms | 2.3-2.4ms | 2.6ms | 0.0ms (native) | <1ms |
| **Round-trip p50** | Total client-to-server-to-client time | Depends on distance to US-ORD | Depends on nearest compute region | Depends on nearest PoP | Depends on distance to us-east-1 | Depends on nearest PoP |
| **ML inference p50** | Time for the neural network forward pass | 887ms | 779-789ms | N/A (no FS) | 219ms (native ARM64) | N/A (no WASI) |
| **Jitter (p95/p50)** | Latency consistency — lower is better | 1.28-1.35x | 1.05-1.11x | 1.39-2.10x | 1.33x | 1.68-1.89x |
| **Error rate** | Percentage of failed requests | 0% | 0% | 0% | 0% | 0% |

### Network latency caveat

Round-trip latency includes network time between the k6 runner and the
gateway. The server processing time (`proc_p50`) isolates actual gateway
computation. When comparing platforms, use server-side metrics to compare
compute performance and round-trip metrics to compare end-user experience.

### Cold start

Rules-only cold start measures WASM module instantiation overhead.
ML cold start adds ~1s for deserializing the 53MB NNEF model.
These are separate concerns — most production deployments would use
`ml: false` and never hit the model loading path.

## Known Caveats

- **k6 maxDuration**: Cold start tests need high `maxDuration` (10 iterations x 120s gaps). The script sets this dynamically.
- **Fermyon free tier**: May have rate limits or instance caps. Use a paid plan for benchmark accuracy.
- **Runner location matters**: Multi-region results isolate network latency. Single-region results from your laptop include your ISP latency.
- **Model consistency**: All platforms must use the same `model.nnef.tar` and `vocab.txt`. Verify with checksums above.
