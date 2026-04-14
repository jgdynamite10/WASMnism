# I Benchmarked a WASM Content Moderation Gateway Across Three Edge Platforms. Here's What I Found.

*Akamai Functions vs Fastly Compute vs Cloudflare Workers — a decision-grade price-per-performance comparison, April 2026*

---

## TL;DR

I wrote a content moderation gateway in Rust, compiled it to WebAssembly, and deployed identical binaries across three edge platforms: **Akamai Functions**, **Fastly Compute**, and **Cloudflare Workers**. Then I hammered all three from two independent cloud origins, across three continents, at concurrency levels from 1 to 2,000 simultaneous users.

The results surprised me:

- **Fastly** is the fastest platform at idle — 2.4 ms median round-trip for a health check, 6.1 ms for the full moderation pipeline.
- **Cloudflare Workers** wins at moderate concurrency — 5.8 ms policy p50 at 10 VUs, lowest tail latency under load.
- **Akamai** dominates at scale — 66 ms p50 at 2,000 concurrent users vs Workers' 81 ms and Fastly's 151 ms.
- **All three platforms: zero errors** from 10 VUs through 2,000 VUs. Not a single dropped request.

There is no single "fastest" platform. The right choice depends entirely on your traffic pattern.

---

## Why This Benchmark Exists

Every major AI provider needs a content moderation layer. Most deploy it as a centralized service — a single region, a single runtime, a single bottleneck. When inference latency already eats 500 ms–2 s per request, does it matter if your safety check adds another 10 ms or 100 ms?

It matters when you're running that check at the edge, before the prompt ever reaches your model. An edge-deployed firewall can reject bad input in under 10 ms — before it consumes GPU time, before it crosses a region boundary, before it racks up inference costs. But only if the edge platform itself doesn't add overhead that eats the advantage.

I wanted to find out: **which WASM-first edge platform gives the best price-per-performance for a real moderation workload?**

Not a synthetic "Hello World." Not a proxy pass-through. A real 7-step pipeline: normalize input, compute content hash, expand leetspeak, scan for prohibited terms, detect PII, check for injection attacks, and issue a verdict. All in Rust, compiled to WASM, running at the edge.

---

## Disclosure

**I work at Akamai.** One of the three platforms being tested is my employer's product.

To address this directly:

1. **Identical code.** The core moderation library (`clipclap-gateway-core`) is shared across all three platforms. Only the thin adapter layer differs — Spin SDK for Akamai, Fastly SDK for Fastly, `worker` crate for Cloudflare. The Rust code that actually processes prompts is byte-for-byte identical.

2. **Dual-origin testing.** All initial benchmarks used Linode runners. Akamai acquired Linode in 2022, so traffic from Linode to Akamai likely traverses a private backbone. To control for this, I provisioned a second set of runners on GCP (Google Cloud Platform) — a neutral origin with no ownership relationship to any of the three platforms. All results are reported from both origins.

3. **Paid tiers.** All platforms use paid tiers: Cloudflare Workers Paid ($5/mo), Fastly usage-based billing, Akamai Functions (preview/beta with production-grade infrastructure).

4. **Open methodology.** The benchmark contract, k6 scripts, validation suite, and Rust source are all in the [WASMnism repository](https://github.com/jgdynamite/WASMnism). You can reproduce every number in this post.

---

## The Architecture

### The Moderation Pipeline

The gateway implements a 7-step rules-only pipeline:

```
Input → Normalize → Hash → Leetspeak Expand → Prohibited Scan → PII Check → Injection Check → Verdict
```

Every request hits all seven steps. There are no shortcuts, no early exits (except for cache hits). This ensures the benchmark measures the full computational cost of real moderation.

The pipeline is implemented as a Rust workspace:

```
edge-gateway/
├── core/          # Shared library — pipeline, policy, hash, normalize
├── adapters/
│   ├── spin/      # Akamai Functions (via Fermyon Spin SDK)
│   ├── fastly/    # Fastly Compute (via Fastly SDK)
│   └── workers/   # Cloudflare Workers (via worker crate)
```

The `core/` crate is a dependency of every adapter. When you `cargo build` any adapter, you get the same pipeline logic compiled to the adapter's WASM target.

### Three Platforms, Two Architecture Models

| Aspect | Akamai Functions | Fastly Compute | Cloudflare Workers |
|:-------|:-----------------|:---------------|:-------------------|
| **Architecture** | Two-tier (edge PoPs + compute regions) | Single-tier (WASM executes at PoP) | Single-tier (V8 isolate at PoP) |
| **WASM target** | `wasm32-wasip1` | `wasm32-wasip1` | `wasm32-unknown-unknown` |
| **Scheduling** | On-demand | Pre-warmed | Pre-warmed |
| **Global PoPs** | 4,400+ edge locations | 130+ PoPs | 330+ cities |
| **WASM runtime** | Wasmtime (via Spin) | Wasmtime | V8 |

The architectural difference that matters most: **Akamai uses a two-tier model** where edge PoPs handle routing and TLS, but compute happens in separate regional compute clusters. Fastly and Workers both use a **single-tier model** where your WASM code executes directly at the Point of Presence that received the request.

This has a direct, measurable effect on performance — and it flips depending on concurrency.

---

## The Measurement Contract

Before running a single benchmark, I locked down the methodology:

**Contract version 3.3** — [full spec in the repo](https://github.com/jgdynamite/WASMnism/blob/main/docs/benchmark-contract.md).

### Test Suite

| Test | VUs | Duration | What It Measures |
|:-----|----:|:---------|:-----------------|
| Cold Start | 1 | 10 × 120s idle | Startup overhead after eviction |
| Warm Light | 10 | 60s | Raw platform overhead (health check) |
| Warm Policy | 10 | 60s | Full moderation pipeline (7-step) |
| Concurrency Ladder | 1→50 | 150s (5 stages) | Behaviour under increasing load |
| Full Ladder | 1→1,000 | 7 min (7 stages) | High-concurrency ceiling |
| Soak | 500 | 10 min | Sustained load stability |
| Spike | 0→2,000 | 80s (flash ramp) | Breaking point under burst traffic |

### Methodology

- **7-run medians** for the base suite. Single run for extended tests (ladder/soak/spike are expensive).
- **Client-side timing** via k6's `http_req_duration` — this includes TLS, network, processing, everything. It's what the end user experiences.
- **Three regions per origin**: US (Chicago / N. Virginia), EU (Frankfurt / Belgium), APAC (Singapore).
- **Dedicated-CPU runners**: Linode Dedicated 4 vCPU (8 GB) and GCP `e2-standard-4` (4 vCPU, 16 GB). I learned the hard way that shared-CPU runners bottleneck k6 before they bottleneck the platform.

### A Lesson About Runner Sizing

On April 12, I ran the full benchmark suite on Linode `g6-nanode-1` instances — 1 shared vCPU, 1 GB RAM. The results showed Fastly at 7.7 ms for a health check. Good, but nothing spectacular.

The next day, I upgraded to `g6-dedicated-4` — 4 dedicated vCPUs, 8 GB RAM. Same code, same platforms, same endpoints.

Fastly dropped from 7.7 ms to **2.4 ms**. A 3x improvement that had nothing to do with Fastly — I'd been measuring k6's CPU contention, not platform latency.

If you're benchmarking edge platforms, use dedicated-CPU runners. Shared instances lie to you.

---

## The Results

### Executive Summary — Base Suite

Cross-region median of 7-run medians, from Linode runners (Akamai-owned origin). Lower latency and higher RPS are better.

| Metric | Akamai | Fastly | Workers |
|:-------|-------:|-------:|--------:|
| Health check p50 | 6.2 ms | **2.4 ms** | 6.0 ms |
| Health check RPS | 1,304/s | **3,468/s** | 1,461/s |
| Policy p50 | 8.8 ms | 6.1 ms | **5.8 ms** |
| Policy RPS | 968/s | **1,506/s** | 1,443/s |
| Ladder p50 (1→50 VUs) | 10.1 ms | **6.8 ms** | 7.2 ms |
| Ladder RPS | 1,031/s | 1,316/s | **1,394/s** |
| Errors (all tests) | 0.00% | 0.00% | 0.00% |

At low concurrency, Fastly is the clear speed leader — roughly 2.5x faster than Akamai and Workers for raw request handling. For the full moderation pipeline, Workers edges out Fastly on p50 (5.8 vs 6.1 ms) thanks to V8's optimized WASM runtime reporting sub-millisecond server processing time.

### Cold Start

Cold start measures the first request after 120 seconds of idle eviction — the worst case for bursty serverless traffic.

| Region | Akamai | Fastly | Workers |
|:-------|-------:|-------:|--------:|
| US (Chicago) | 45 ms | **7 ms** | 10 ms |
| EU (Frankfurt) | 132 ms | **7 ms** | 12 ms |
| APAC (Singapore) | 48 ms | **5 ms** | 12 ms |

Akamai's two-tier architecture shows up here: cold requests must be routed from the edge PoP to a compute region, adding 45–132 ms depending on geographic proximity to the nearest compute cluster. Fastly's single-tier model keeps cold starts under 7 ms globally — the WASM instance is instantiated at the PoP that received the request.

### Where It Gets Interesting: The Crossover

The base suite caps out at 50 VUs. For a real production workload — think a viral tweet triggering a moderation storm — you need to know what happens at 500, 1,000, or 2,000 concurrent users.

**Full Concurrency Ladder (1→1,000 VUs, from Linode):**

| Metric | Akamai | Fastly | Workers |
|:-------|-------:|-------:|--------:|
| Chicago p50 | **33 ms** | 46 ms | 34 ms |
| Frankfurt p50 | **34 ms** | 54 ms | 36 ms |
| Singapore p50 | **37 ms** | 48 ms | 38 ms |
| Total requests (Chicago) | 895K | 664K | **904K** |

At 1,000 VUs, the rankings flip. Akamai's two-tier architecture — the same design that adds cold-start latency — now *absorbs* load better than PoP-level execution. The compute regions scale independently of edge routing, preventing the congestion that Fastly's single-tier PoPs experience under high fan-in.

**Soak Test (500 VUs sustained, 10 minutes):**

| Metric | Akamai | Fastly | Workers |
|:-------|-------:|-------:|--------:|
| Chicago p50 | **52 ms** | 115 ms | 58 ms |
| Chicago RPS | **3,029/s** | 1,918/s | 2,856/s |
| Total requests (Chicago) | **1.8M** | 1.2M | 1.7M |

Over 10 minutes at 500 VUs, Akamai sustains the highest throughput globally (2,929–3,102 RPS) while maintaining the lowest median latency. Fastly falls to roughly half Akamai's throughput under sustained load.

**Spike Test (0→2,000 VUs, flash ramp):**

| Metric | Akamai | Fastly | Workers |
|:-------|-------:|-------:|--------:|
| Chicago p50 | **66 ms** | 151 ms | 81 ms |
| Chicago RPS | **2,824/s** | 1,834/s | 2,663/s |
| Frankfurt p50 | **65 ms** | 158 ms | 77 ms |
| Singapore p50 | **69 ms** | 167 ms | 82 ms |
| Errors (all regions) | 0.00% | 0.00% | 0.00% |

At 2,000 concurrent users, Akamai's advantage is definitive: lowest p50 and highest throughput in every region. Fastly's single-tier PoPs experience 2x the latency of Akamai's compute regions under spike conditions.

And the most remarkable finding: **all three platforms handle 2,000 simultaneous users with zero errors**. Not a single dropped request across any region or any platform.

---

## The Backbone Bias Question

Here's the elephant in the room: Akamai owns Linode. When I fire requests from a Linode datacenter to an Akamai edge PoP, that traffic probably traverses Akamai's private backbone — fewer hops, lower jitter, better peering. Am I measuring platform performance or network advantage?

To answer this, I provisioned identical runners on Google Cloud Platform — a neutral origin with no ownership relationship to any of the three platforms — and ran the full suite again.

### Base Suite: Linode vs GCP Origin (US Region, Warm Policy)

| Platform | Linode p50 | GCP p50 | Delta |
|:---------|----------:|-------:|------:|
| Akamai | **8.8 ms** | 11.5 ms | +2.7 ms (+31%) |
| Fastly | **6.1 ms** | 8.3 ms | +2.2 ms (+36%) |
| Workers | **5.8 ms** | 13.7 ms | +7.9 ms (+136%) |

Every platform is faster from Linode. But the interesting finding is the *differential*: Akamai's advantage from Linode (+2.7 ms) is actually smaller than Fastly's (+2.2 ms is proportionally larger at 36%). Workers shows the biggest swing at +136%, suggesting that Linode's US datacenter (Chicago) has better peering to Cloudflare's Chicago PoP than GCP's Virginia datacenter does.

**Average origin delta across the base suite:**

| Platform | Avg Δ (GCP − Linode) |
|:---------|--------------------:|
| Akamai | +2.4 ms |
| Fastly | +1.6 ms |
| Workers | +7.3 ms |

Akamai's backbone bias exists but is modest — about 2.4 ms. The bigger story is that **Workers is by far the most sensitive to runner origin** (+7.3 ms average), which likely reflects geographic routing differences rather than any backbone relationship.

### The Real Surprise: GCP Results at Scale

When I looked at the extended suite from GCP, the high-concurrency rankings shifted dramatically:

**Soak Test (500 VUs, 10 min) — GCP origin, US region:**

| Platform | Linode p50 | GCP p50 | Linode RPS | GCP RPS |
|:---------|----------:|-------:|----------:|-------:|
| Akamai | **52 ms** | 85 ms | 3,029/s | **4,690/s** |
| Fastly | 115 ms | **67 ms** | 1,918/s | **4,967/s** |
| Workers | **58 ms** | 178 ms | **2,856/s** | 1,196/s |

From the GCP origin, **Fastly leapfrogs Akamai** in the extended suite — lower p50 and higher RPS in every soak and spike test. This is the opposite of the Linode results.

Why? Two likely explanations:

1. **GCP's Virginia datacenter has excellent peering to Fastly's Ashburn PoP** — possibly better than the Linode-to-Fastly path in Chicago.
2. **Workers' performance degrades significantly from GCP** (-56% RPS in the soak test), suggesting Cloudflare's routing from GCP is suboptimal for sustained load.

The takeaway: **the "best" platform depends not just on concurrency level, but on where your users are coming from.** If your traffic originates from a major cloud provider, Fastly's single-tier architecture has an edge even at high scale. If your traffic comes from a CDN-adjacent network, Akamai's two-tier model wins.

---

## Why the Platforms Differ

The latency breakdown from Warm Policy (Chicago, p50) tells the story:

| Component | Akamai | Fastly | Workers |
|:----------|-------:|-------:|--------:|
| Server processing (WASM pipeline) | 2.8 ms | 3.3 ms | < 1 ms |
| HTTP framing overhead | 0.1 ms | 0.5 ms | 0.3 ms |
| Server-side waiting | 8.7 ms | 5.6 ms | 5.5 ms |
| **Total round-trip** | **8.8 ms** | **6.1 ms** | **5.8 ms** |

Three things jump out:

**Workers' sub-millisecond processing time** isn't a measurement artifact. V8's WASM runtime (used by Workers) is more aggressively optimized for short-lived isolates than Wasmtime (used by Akamai and Fastly). The same Rust code, compiled to `wasm32-unknown-unknown` for Workers vs `wasm32-wasip1` for the others, runs measurably faster in V8.

**Akamai's 0.1 ms HTTP framing** is the lowest across all platforms and regions. The two-tier architecture adds routing latency (visible in server-side waiting) but the actual HTTP send/receive is extremely efficient — likely because the compute regions have optimized connection pooling to the edge.

**The 3 ms gap** between Akamai's total (8.8 ms) and Workers' (5.8 ms) at 10 VUs is almost entirely routing overhead from Akamai's two-tier model. At 2,000 VUs, that overhead is amortized across a compute region with much higher capacity than a single PoP, which is why Akamai wins at scale.

---

## What About Errors?

Zero. Across every test, every region, every concurrency level, every platform.

| Test | Max VUs | Akamai Errors | Fastly Errors | Workers Errors |
|:-----|--------:|:--------------|:--------------|:---------------|
| Cold Start | 1 | 0% | 0% | 0% |
| Warm Light | 10 | 0% | 0% | 0% |
| Warm Policy | 10 | 0% | 0% | 0% |
| Concurrency Ladder | 50 | 0% | 0% | 0% |
| Full Ladder | 1,000 | 0% | 0% | 0% |
| Soak (10 min) | 500 | 0% | 0% | 0% |
| Spike | 2,000 | 0% | 0% | 0% |

This is remarkable. At 2,000 concurrent users hammering a moderation pipeline from three continents, all three platforms returned valid responses to every single request. The WASM edge ecosystem has matured to a point where reliability is table stakes, not a differentiator.

---

## The Cost Dimension

Performance without pricing is a half-story. Here's the pricing model for each platform at the time of testing:

| Platform | Model | Base Cost | Per-Request Cost | Notes |
|:---------|:------|:----------|:-----------------|:------|
| Akamai Functions | Preview / beta | Free during preview | Free during preview | Production infrastructure; pricing TBD |
| Fastly Compute | Usage-based | No base fee | ~$0.50/M requests + compute time | Billed per request + CPU ms |
| Cloudflare Workers | Subscription + usage | $5/mo | $0.30/M requests (first 10M included) | Paid plan eliminates free-tier rate limiting |

Akamai's preview status makes direct cost comparison impossible right now. Between Fastly and Workers: Workers' $5/mo subscription includes 10M requests, making it cheaper at low volume. Fastly's usage-based model is more predictable at scale (no subscription, pay exactly for what you use).

For a moderation firewall handling 100M requests/month, the compute cost would be roughly:
- **Fastly**: ~$50/mo (requests) + compute-time billing
- **Workers**: $5/mo + ~$27/mo (90M excess requests × $0.30/M) = ~$32/mo

But these numbers shift with CPU time billing, and a moderation pipeline is more compute-intensive than a simple proxy. The only way to get a real cost answer is to run a production-representative load and read your invoice.

---

## The Verdict

**Choose based on your traffic pattern:**

| If your workload looks like... | Choose | Why |
|:-------------------------------|:-------|:----|
| Low/moderate traffic, latency-sensitive | **Fastly Compute** | 2.4 ms health check, 6.1 ms policy — nothing touches it at idle |
| Bursty traffic with cold starts | **Fastly Compute** | 5–7 ms cold start globally vs Akamai's 45–132 ms |
| Sustained high concurrency (500+ VUs) | **Akamai Functions** | Lowest p50 and highest throughput at 500–2,000 VUs from CDN-adjacent origins |
| High concurrency from major cloud origins | **Fastly Compute** | GCP-origin data shows Fastly leading even at 2,000 VUs |
| Lowest tail latency under stress | **Cloudflare Workers** | Best worst-case max latency in soak tests (641 ms vs 1,694 ms) |
| Cheapest at moderate volume | **Cloudflare Workers** | $5/mo covers 10M requests; predictable pricing |
| All-around balance | Any of the three | 0% errors everywhere; all are production-ready |

The narrative is simple: **Fastly is fastest at idle. Workers is fastest at moderate load with the best worst-case guarantees. Akamai is fastest at scale — but the advantage depends on your origin network.**

---

## How to Reproduce

Everything you need is in the [WASMnism repository](https://github.com/jgdynamite/WASMnism).

### Prerequisites

- Rust toolchain with `wasm32-wasip1` and `wasm32-unknown-unknown` targets
- [Spin CLI](https://developer.fermyon.com/spin/install) (for Akamai Functions)
- [Fastly CLI](https://developer.fastly.com/reference/cli/)
- [Wrangler](https://developers.cloudflare.com/workers/wrangler/) (for Cloudflare Workers)
- [k6](https://k6.io/) v1.7+ for benchmarking
- Accounts on all three platforms (paid tiers for fair comparison)

### Build

```bash
cd edge-gateway

# Build all adapters
cargo build --release -p clipclap-gateway-spin --target wasm32-wasip1
cargo build --release -p clipclap-gateway-fastly --target wasm32-wasip1
cargo build --release -p clipclap-gateway-workers --target wasm32-unknown-unknown
```

### Deploy

```bash
# Akamai Functions (via Spin)
cd adapters/spin && spin aka deploy

# Fastly Compute
cd adapters/fastly && fastly compute publish

# Cloudflare Workers
cd adapters/workers && npx wrangler deploy
```

### Benchmark

```bash
# Provision runners (Linode or GCP)
make runners-up          # Linode
make gcp-runners-up      # GCP

# Run base suite (7 runs, 3 regions)
make bench-multiregion PLATFORM=akamai URL=https://your-endpoint.fwf.app
make bench-multiregion PLATFORM=fastly URL=https://your-endpoint.edgecompute.app
make bench-multiregion PLATFORM=workers URL=https://your-endpoint.workers.dev

# Run extended suite
make bench-full PLATFORM=akamai URL=https://your-endpoint.fwf.app

# Validate results
python3 bench/validate-results.py results/

# Generate scorecard
make report PLATFORMS="akamai fastly workers" NAME="my_scorecard"
```

### Benchmark Contract

The full measurement contract (v3.3) is at `docs/benchmark-contract.md`. Key rules:

- 7-run medians for the base suite; report the median of medians across regions
- Client-side timing (`http_req_duration`) is the source of truth
- Dedicated-CPU runners only (4+ vCPU minimum)
- Disclose runner origin (cloud provider and region)
- All platforms on paid tiers

---

## What's Next

This benchmark covers the **rules-only pipeline** — the Tier 1 comparison of pure WASM execution across edge platforms. The `ml-inference` branch adds a Tier 2 comparison: **ML inference at the edge** using an embedded MiniLMv2 toxicity classifier (via Tract NNEF), comparing Akamai Functions (WASM) against AWS Lambda (native ARM64).

The question that branch aims to answer: can you run a real ML model inside a WASM sandbox at the edge, and how does it compare to a traditional serverless function with native hardware access? Early architecture is in place — stay tuned for the Tier 2 results.

---

*All benchmark data collected April 13, 2026. Benchmark contract v3.3. Full data, k6 scripts, Rust source, and deployment configs available at [github.com/jgdynamite/WASMnism](https://github.com/jgdynamite/WASMnism).*

*Runner origins: Linode Dedicated 4 vCPU (Chicago, Frankfurt, Singapore) and GCP e2-standard-4 (N. Virginia, Belgium, Singapore). Linode is owned by Akamai — see Disclosure section.*
