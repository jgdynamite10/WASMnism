# WASMnism Architecture

Comprehensive architecture reference for the WASM-powered AI Prompt Firewall,
covering system design, deployment topology, and benchmark infrastructure.

---

## 1. System Overview

```
                               ┌─────────────────────────────────────────────────────┐
                               │              WASMnism Project                        │
                               │                                                      │
  ┌──────────┐                 │  ┌──────────────────────────────────────────────┐    │
  │  Browser  │─── HTTPS ─────▶│  │         Edge Gateway (WASM binary)           │    │
  │  Dashboard│◀───────────────│  │                                              │    │
  └──────────┘                 │  │  ┌─────────────┐   ┌───────────────────┐    │    │
                               │  │  │ Platform     │   │  Core Library      │    │    │
  ┌──────────┐                 │  │  │ Adapter      │──▶│  (shared Rust)     │    │    │
  │  k6 Load │─── HTTPS ─────▶│  │  │ (spin/       │   │                   │    │    │
  │  Runner  │◀───────────────│  │  │  fastly/     │   │  pipeline.rs      │    │    │
  └──────────┘                 │  │  │  workers/    │   │  policy.rs        │    │    │
                               │  │  │  lambda)     │   │  toxicity.rs      │    │    │
                               │  │  └─────────────┘   │  tokenizer        │    │    │
                               │  │                     │  normalize.rs     │    │    │
                               │  │                     │  hash.rs          │    │    │
                               │  │                     │  cache.rs         │    │    │
                               │  │                     └───────────────────┘    │    │
                               │  └──────────────────────────────────────────────┘    │
                               │                                                      │
                               │  ┌──────────────────┐  ┌────────────────────────┐   │
                               │  │  Svelte Frontend  │  │  Benchmark Suite (k6)  │   │
                               │  │  (static files)   │  │  + Automation (bash)   │   │
                               │  └──────────────────┘  └────────────────────────┘   │
                               └─────────────────────────────────────────────────────┘
```

The project has three major components:

1. **Edge Gateway** — A Rust codebase compiled to `wasm32-wasip1`, running an 8-step
   content moderation pipeline with an embedded ML toxicity classifier
2. **Frontend Dashboard** — A Svelte SaaS-style UI for interactive prompt evaluation
3. **Benchmark Infrastructure** — k6 scripts, automation pipelines, and multi-region
   runner infrastructure for reproducible cross-platform performance measurement

---

## 2. Edge Gateway Architecture

### Core + Adapter Split

The gateway uses a shared-core / thin-adapter pattern. All business logic lives in the
`core` crate. Each platform gets a thin adapter that wires HTTP routing and KV storage
to the core functions.

```
edge-gateway/
├── core/                      # Shared library (platform-agnostic)
│   ├── pipeline.rs            #   Request → 8-step moderation → response
│   ├── policy.rs              #   Rule engine: prohibited terms, PII, injection
│   ├── toxicity.rs            #   ML model: ToxicityClassifier (Tract NNEF)
│   ├── normalize.rs           #   Unicode NFC + leetspeak expansion
│   ├── hash.rs                #   SHA-256 content hashing
│   ├── cache.rs               #   CachedVerdict serialization
│   ├── handlers.rs            #   Mock classification (CLIP placeholder)
│   ├── error.rs               #   Error types
│   └── types.rs               #   Shared type definitions
│
├── adapters/
│   ├── spin/                  # Fermyon Cloud + Akamai Functions
│   │   ├── src/lib.rs         #   Spin SDK HTTP router, KV store integration
│   │   ├── spin.toml          #   App manifest (routes, variables, files)
│   │   └── static/            #   Built frontend files (gitignored)
│   ├── fastly/                # Fastly Compute (scaffolded)
│   ├── workers/               # Cloudflare Workers (scaffolded)
│   └── lambda/                # AWS Lambda (scaffolded)
│
└── models/toxicity/           # ML model artifacts
    ├── model.nnef.tar         #   53 MB Tract NNEF model (gitignored)
    └── vocab.txt              #   8,000-token WordPiece vocabulary
```

### Why this pattern works

- **One codebase, many platforms**: The core compiles once to `wasm32-wasip1`. Each
  adapter is ~200-400 lines that adapts the platform's HTTP/KV APIs to core functions.
- **Identical behavior**: Both Fermyon Cloud and Akamai Functions use the exact same
  Spin adapter and WASM binary. The only difference is the platform runtime.
- **Testable in isolation**: The core has unit tests that run without any platform SDK.

### The 8-Step Moderation Pipeline

Every `POST /gateway/moderate` request flows through these steps:

```
Request JSON
    │
    ▼
┌─ Step 1: Parse & validate ─────────────────────────────────────────────┐
│  Extract labels[], text, nonce, ml flag                                 │
└─────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Step 2: Pre-check (rules) ────────────────────────────────────────────┐
│  • Unicode NFC normalization                                            │
│  • Leetspeak expansion (h@t3 → hate, k1ll → kill)                      │
│  • Prohibited term scan (Aho-Corasick, 60+ patterns)                   │
│  • Prompt injection detection ("ignore previous", "jailbreak", etc.)    │
│  • Code injection detection (XSS, SQL injection)                        │
│  • PII detection (email, phone, SSN regex)                              │
│                                                                         │
│  If BLOCK detected → return immediately (no cache, no ML)               │
└─────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Step 3: Cache lookup ─────────────────────────────────────────────────┐
│  SHA-256(normalized labels) → KV store lookup                           │
│  HIT → return cached verdict immediately                                │
│  MISS → continue to classification                                      │
└─────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Step 4: Classification ───────────────────────────────────────────────┐
│  Mock CLIP classification (placeholder for future image support)        │
└─────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Step 5: ML toxicity (if ml:true AND text present) ────────────────────┐
│  • WordPiece tokenization (custom Rust tokenizer, 8k vocab)            │
│  • Tensor construction (input_ids, attention_mask, token_type_ids)      │
│  • Forward pass through MiniLMv2 (22.7M params, Tract NNEF)            │
│  • Sigmoid → per-category probabilities (toxic, severe_toxic)           │
│                                                                         │
│  Performance: varies significantly by platform (see private results)   │
│  When ml:false → this entire step is skipped                            │
└─────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Step 6: Post-check ──────────────────────────────────────────────────┐
│  Evaluate classification scores against thresholds                      │
└─────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Step 7: Verdict merge ───────────────────────────────────────────────┐
│  Combine pre-check + post-check + ML results                           │
│  Strictest wins: block > review > allow                                │
└─────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Step 8: Response ─────────────────────────────────────────────────────┐
│  JSON response with verdict, moderation details, timing, cache info     │
│  Cache MISS → write verdict to KV store for future requests             │
└─────────────────────────────────────────────────────────────────────────┘
```

### ML Model Architecture

```
Input text
    │
    ▼
┌─ WordPiece Tokenizer ──────┐
│  Custom Rust implementation  │
│  8,000-token vocabulary      │
│  Max sequence length: 128    │
└─────────────────────────────┘
    │
    ▼  [input_ids, attention_mask, token_type_ids]
    │
┌─ MiniLMv2 Transformer ─────┐
│  22.7M parameters            │
│  Fine-tuned on Jigsaw data   │
│  Runs in Tract NNEF engine   │
│  Inside WASM sandbox         │
└─────────────────────────────┘
    │
    ▼  Raw logits
    │
┌─ Sigmoid Activation ───────┐      ┌──────────────┐
│  toxic: 0.0 → 1.0           │─────▶│  ≥ 0.80: BLOCK│
│  severe_toxic: 0.0 → 1.0    │      │  ≥ 0.50: REVIEW│
└─────────────────────────────┘      │  < 0.50: (none)│
                                      └──────────────┘
```

**Model provenance:** PyTorch → ONNX (opset 14, fixed shapes) → vocabulary-trimmed
(30k → 8k tokens) → Tract NNEF. NNEF avoids expensive protobuf parsing in the WASM
runtime. Full details in `edge-gateway/models/README.md`.

---

## 3. Platform Deployment Topology

### Fermyon Cloud — Single Region

```
┌──────────────────────────────────────────────────────────────────────┐
│                        FERMYON CLOUD                                  │
│                                                                      │
│                    ┌──────────────────┐                               │
│                    │  us-ord (Chicago) │                               │
│                    │                  │                               │
│  User (Chicago) ──▶│  WASM Gateway    │  ◀── User (Frankfurt)         │
│                    │  + KV Store      │                               │
│                    │  + Frontend      │                               │
│                    └──────────────────┘  ◀── User (Singapore)         │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

- **One compute region** (us-ord / Chicago)
- No edge layer — TLS terminates at the compute region
- All users worldwide talk to Chicago
- Latency scales linearly with geographic distance
- Deployed via `spin cloud deploy`

### Akamai Functions — Global Edge + Multi-Region Compute

```
┌──────────────────────────────────────────────────────────────────────┐
│                     AKAMAI FUNCTIONS                                  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                  Akamai Edge Network                          │    │
│  │                  4,200+ PoPs globally                         │    │
│  │                                                              │    │
│  │  User (Chicago) ──▶ [Chicago PoP] ──┐                        │    │
│  │                       TLS + route    │                        │    │
│  │                                      ▼                        │    │
│  │                              ┌──────────────┐                 │    │
│  │                              │ fwf-dev-     │                 │    │
│  │                              │  us-ord      │                 │    │
│  │                              │ WASM Gateway │                 │    │
│  │                              └──────────────┘                 │    │
│  │                                                              │    │
│  │  User (Frankfurt) ▶ [Frankfurt PoP] ┐                        │    │
│  │                        TLS + route   │                        │    │
│  │                                      ▼                        │    │
│  │                              ┌──────────────┐                 │    │
│  │                              │ fwf-dev-     │                 │    │
│  │                              │  de-fra-2    │                 │    │
│  │                              │ WASM Gateway │                 │    │
│  │                              └──────────────┘                 │    │
│  │                                                              │    │
│  │  User (Singapore) ▶ [Singapore PoP] ┐                        │    │
│  │                        TLS + route   │                        │    │
│  │                                      ▼                        │    │
│  │                              ┌──────────────┐                 │    │
│  │                              │ fwf-dev-     │                 │    │
│  │                              │  sg-sin-2    │                 │    │
│  │                              │ WASM Gateway │                 │    │
│  │                              └──────────────┘                 │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

- **Two-tier architecture**: Edge PoPs (TLS, routing) + Compute Regions (WASM execution)
- On `spin aka deploy`, Akamai auto-replicates the WASM binary to multiple compute regions
- Verified compute regions: `us-ord` (Chicago), `de-fra-2` (Frankfurt), `sg-sin-2` (Singapore)
- Edge PoPs route each request to the nearest compute region via the `akaalb` load balancer cookie
- No request crosses an ocean — compute is always local to the user
- The 1ms vs 12ms edge-to-compute hop is intra-city networking, not geographic latency
- Deployed via `spin aka deploy` (one command, auto-replication is invisible)

### How We Verified This

Akamai injects headers on every response that reveal the infrastructure path:

| Header | What it reveals |
|--------|----------------|
| `Akamai-Request-BC` (`n=` field) | Edge PoP city (e.g., `US_IL_CHICAGO`, `DE_HE_FRANKFURT`) |
| `Set-Cookie: akaalb_fwf-prod-apps` (`m=` field) | Compute backend (e.g., `fwf-dev-de-fra-2`) |
| `x-envoy-upstream-service-time` | Edge-to-compute hop in milliseconds |

See `results/akamai/edge_verification.md` (private) for full header dumps from all regions.

### Fastly Compute — Single-Tier (WASM at the PoP)

```
Client --> [Fastly PoP: TLS + WASM execution] --> Response
```

- **Single-tier architecture**: WASM executes directly on the PoP — no separate compute layer
- The `x-served-by` header reveals the exact PoP: `cache-chi-...-CHI`, `cache-fra-...-FRA`, etc.
- No "upstream service time" header because there is no upstream — everything runs on one node
- Pre-warmed isolate model: WASM instance is already loaded when the request arrives
- Verified PoPs: `DFW` (Dallas), `CHI` (Chicago), `FRA` (Frankfurt), `SIN` (Singapore)
- Deployed via `fastly compute publish` (one command)

#### How We Verified This

```bash
curl -si https://morally-civil-urchin.edgecompute.app/gateway/health | grep x-served-by
# x-served-by: cache-chi-klot8100056-CHI    ← WASM ran on Chicago PoP
# x-served-by: cache-fra-etou8220069-FRA    ← WASM ran on Frankfurt PoP
# x-served-by: cache-sin-wsap440030-SIN     ← WASM ran on Singapore PoP
```

See `results/fastly/edge_verification.md` (private) for full header dumps from all regions.

### AWS Lambda — Single-Region Native ARM64 (Regional Baseline)

```
Client --> [Lambda Function URL] --> Lambda ARM64 --> DynamoDB (cache)
```

- **Not WASM**: Lambda runs a native ARM64 binary compiled from the same Rust codebase
- **Single region**: Deployed to us-east-1 (N. Virginia)
- **Zero scheduling overhead**: Lambda environments stay warm for ~15 minutes
- **Sub-millisecond processing**: Native ARM64 processes faster than WASM platforms
- **DynamoDB caching**: Uses DynamoDB on-demand for verdict caching (instead of KV stores)
- **Function URL**: Direct HTTPS endpoint, no API Gateway (for fair benchmarking)
- **Embedded ML**: ToxicityClassifier loaded from `/var/task/models/toxicity/` via `OnceLock` (same lazy-init pattern as Spin)
- **Frontend dashboard**: Svelte UI embedded via `include_dir` (same approach as Fastly)
- **ML inference**: runs on native ARM64 (significantly faster than WASM)
- Remote clients pay full network RTT: ~70ms from EU, ~210ms from AP
- Deployed via `cargo lambda deploy` with `--include models/toxicity` and `--s3-bucket` for the 53MB+ package

### Why Architecture Matters for Performance

| Step | Fastly (single-tier) | Akamai (two-tier) | Fermyon (single-region) | AWS Lambda (regional) |
|------|---------------------|-------------------|------------------------|----------------------|
| TLS termination | At PoP | At edge PoP | At compute | At Lambda URL |
| Route to compute | **N/A (same node)** | Internal hop | N/A (single region) | N/A (single region) |
| Schedule WASM/runtime | **Pre-warmed** | On-demand | On-demand | **Warm Lambda** |
| Execute logic | WASM | WASM | WASM | **Native ARM64** |

Server processing time is similar across WASM platforms. The dominant performance differentiator is **platform scheduling overhead** — the cost of on-demand dispatch vs pre-warmed isolates. Benchmark results (private) quantify this gap. See `results/` (gitignored).

### Platform Comparison

| Aspect | Fermyon Cloud | Akamai Functions | Fastly Compute | AWS Lambda |
|--------|--------------|-----------------|---------------|------------|
| Architecture | Single-region | Two-tier (edge + compute) | **Single-tier (PoP = compute)** | Single-region |
| Runtime | WASM (`wasm32-wasip1`) | WASM (`wasm32-wasip1`) | WASM (`wasm32-wasip1`) | **Native ARM64** |
| Execution location | US-ORD only | Compute regions (3+) | **Directly at PoP** | us-east-1 only |
| Scheduling model | On-demand | On-demand | **Pre-warmed** | **Warm** |
| Compute regions | 1 (us-ord) | 3+ (us-ord, de-fra-2, sg-sin-2) | 4+ PoPs (DFW, CHI, FRA, SIN) | 1 (us-east-1) |
| Edge layer | None | 4,200+ Akamai CDN PoPs | Fastly PoP network | None |
| Auto-replication | No | Yes | Yes | No |
| Nearest-region routing | No | Yes (akaalb cookie) | Yes (anycast DNS) | No |
| TLS termination | At compute | At edge PoP | At PoP | At Function URL |
| Filesystem access | Yes | Yes | No | Yes |
| Caching backend | Spin KV | Spin KV | Fastly KV Store | DynamoDB |
| Frontend dashboard | Spin static fileserver | Spin static fileserver | `include_dir` embedded | `include_dir` embedded |
| Deploy command | `spin cloud deploy` | `spin aka deploy` | `fastly compute publish` | `cargo lambda deploy` |

---

## 4. Request Lifecycle

### Rules-Only Request (`ml: false`)

```
Client                    Edge PoP (Akamai only)        Compute Region
  │                              │                           │
  │── POST /gateway/moderate ──▶│                           │
  │   { ml: false, text: ... }  │── forward ───────────────▶│
  │                              │                           │── parse JSON
  │                              │                           │── normalize + hash
  │                              │                           │── pre-check (rules)
  │                              │                           │── cache lookup
  │                              │                           │── classify (mock)
  │                              │                           │── [skip ML]
  │                              │                           │── merge verdict
  │                              │                           │── cache write
  │                              │◀── response ──────────────│
  │◀── JSON response ───────────│                           │
  │                              │                           │
```

### ML Request (`ml: true`)

```
Client                    Edge PoP (Akamai only)        Compute Region
  │                              │                           │
  │── POST /gateway/moderate ──▶│                           │
  │   { ml: true, text: ... }   │── forward ───────────────▶│
  │                              │                           │── parse JSON
  │                              │                           │── normalize + hash
  │                              │                           │── pre-check (rules)
  │                              │                           │── cache lookup
  │                              │                           │── classify (mock)
  │                              │                           │── ML: tokenize text
  │                              │                           │── ML: build tensors
  │                              │                           │── ML: Tract forward pass
  │                              │                           │── ML: sigmoid scores
  │                              │                           │── merge verdict
  │                              │                           │── cache write
  │                              │◀── response ──────────────│
  │◀── JSON response ───────────│                           │
  │                              │                           │
```

---

## 5. Benchmark Infrastructure

### Multi-Region Runner Topology

```
                        ┌──────────────────────────────────┐
                        │        Your Laptop (orchestrator)  │
                        │                                    │
                        │  make bench-multiregion            │
                        │  PLATFORM=akamai URL=<url>         │
                        └───────┬──────────┬─────────┬──────┘
                                │          │         │
                     SSH + sync │   SSH    │  SSH    │
                                │          │         │
                   ┌────────────▼──┐  ┌────▼────┐  ┌▼────────────┐
                   │ k6-us-ord     │  │ k6-eu-  │  │ k6-ap-south │
                   │ Chicago       │  │ central │  │ Singapore   │
                   │ 172.234.28.*  │  │ Frankfurt│  │ 139.162.8.* │
                   │               │  │ 139.162.*│  │             │
                   │ Linode Nanode │  │ Linode  │  │ Linode      │
                   │ $5/mo         │  │ Nanode  │  │ Nanode      │
                   └───────┬───────┘  └────┬────┘  └──────┬──────┘
                           │               │              │
                     k6 → HTTPS      k6 → HTTPS    k6 → HTTPS
                           │               │              │
                           ▼               ▼              ▼
                   ┌──────────────────────────────────────────┐
                   │         Target Platform                    │
                   │  (Fermyon Cloud / Akamai Functions / ...)  │
                   └──────────────────────────────────────────┘
```

### Automation Pipeline

```
make bench-multiregion PLATFORM=akamai URL=<url> BENCH_FLAGS="--ml --cold"
    │
    ├─ 1. deploy/k6-runner-setup.sh sync     Copy latest bench/ scripts to all 3 runners
    │
    ├─ 2. bench/run-multiregion.sh           Launch reproduce.sh on each runner via SSH
    │      │
    │      ├─ [us-ord]     bench/reproduce.sh akamai <url> --ml --cold --region us-ord
    │      ├─ [eu-central] bench/reproduce.sh akamai <url> --ml --cold --region eu-central
    │      └─ [ap-south]   bench/reproduce.sh akamai <url> --ml --cold --region ap-south
    │                │
    │                ├─ Step 0: Prerequisite check (curl, k6, python3)
    │                ├─ Step 1: Health check (GET /gateway/health → 200)
    │                ├─ Step 2: Validation (9 scenarios, 34 checks → 9/9 PASS)
    │                ├─ Step 3: 7-run benchmark suite
    │                │    ├─ Primary: warm-light, warm-policy, concurrency-ladder
    │                │    └─ Stretch (if --ml): warm-heavy, consistency
    │                ├─ Step 4: Compute medians (python3 compute-medians.py)
    │                └─ Step 5: Cold start tests (if --cold)
    │                     ├─ 10 iterations, USE_ML=false (rules cold start)
    │                     └─ 10 iterations, USE_ML=true  (ML cold start)
    │
    ├─ 3. Collect results from all runners via SCP
    │      └─ results/<platform>/multiregion_<timestamp>/{us-ord,eu-central,ap-south}/
    │
    └─ 4. Done. Results ready for scorecard generation.
```

### Benchmark Suite Tests

| Suite | Test | VUs | Duration | What It Measures |
|-------|------|-----|----------|-----------------|
| **Primary** | Warm Light | 10 | 60s | Health endpoint latency (GET) |
| **Primary** | Warm Policy | 10 | 60s | Full rule pipeline, `ml: false` |
| **Primary** | Concurrency Ladder | 1→50 | 150s | Scaling under load, rules only |
| **Primary** | Cold Start (rules) | 1 | ~20min | WASM instantiation (90s gaps) |
| **Stretch** | Warm Heavy | 5 | 60s | Full moderation + ML inference |
| **Stretch** | Consistency | 5 | 120s | ML latency jitter over time |
| **Stretch** | Cold Start (ML) | 1 | ~20min | WASM + 53MB model deserialize |

### Statistical Method

- **7 runs** of each warm test, report **median** (resistant to outliers)
- Percentiles captured: p50, p90, p95, avg, max
- Jitter measured as p95/p50 ratio (lower = more consistent)
- Server-side `processing_ms` isolated from round-trip (network-independent)
- Cold start: 10 iterations with 90s pause between each to force instance spin-down

---

## 6. Performance Results

Benchmark results are stored in `results/` (gitignored — not in this repository).
The benchmark compares all five platforms across three geographic regions using
the primary suite (rules-only) and stretch suite (embedded ML). Results include
per-region p50/p95 latencies, throughput, cold start times, and ML inference.

To reproduce: see [docs/REPRODUCE.md](REPRODUCE.md).

---

## 7. Security Model

### What runs inside the WASM sandbox

- All text processing (normalization, hashing, pattern matching)
- ML inference (Tract NNEF forward pass)
- Verdict composition
- No outbound network calls for moderation (all computation is local)

### What the platform provides

- TLS termination
- HTTP routing
- KV store (Spin KV) for verdict caching
- Configuration variables (platform name, region)

### Secrets management

- No API keys needed for moderation (all logic is embedded)
- Platform credentials (`spin cloud login`, `spin aka login`) are session-based, not stored in code
- `gateway_platform` and `gateway_region` are set via `--variable` at deploy time
- `.env.example` and `cost-config.example.yaml` contain placeholders only
- `results/` directory is gitignored (may contain runner IPs)
- `deploy/runners.env` is gitignored (contains runner IPs)

---

## 8. Adding a New Platform

1. Create `edge-gateway/adapters/<platform>/` with HTTP router and KV adapter
2. Wire the platform's request/response types to `core::pipeline` functions
3. Add `deploy-<platform>` target to `edge-gateway/Makefile`
4. Add `deploy-<platform>` target to root `Makefile`
5. Deploy and run validation: `make validate PLATFORM=<name> URL=<url>`
6. Run benchmarks: `make bench-multiregion PLATFORM=<name> URL=<url> BENCH_FLAGS="--ml --cold"`
7. Generate scorecard: `make scorecard A=results/fermyon/... B=results/<platform>/...`

The benchmark scripts, k6 runners, and automation pipeline are all platform-agnostic.
No new benchmark code is needed — only the adapter.
