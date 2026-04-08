# Cost Model: Price per 1M Requests at SLO

**Date:** April 5, 2026
**Workload:** Rules-only moderation (`ml: false`) — the production-recommended mode
**Sources:** Official pricing pages, verified April 2026

---

## 1. Platform Pricing (Pay-As-You-Go Rates)

### Fastly Compute

Source: [fastly.com/pricing](https://www.fastly.com/pricing)

| Component | Free Tier | Rate (after free) |
|-----------|-----------|-------------------|
| Compute requests | 10M/mo | $0.50 per 1M |
| Compute vCPU-ms | 100M/mo | $0.05 per 1M vCPU-ms |
| CDN bandwidth (NA/EU) | 100 GB/mo | $0.12/GB |
| CDN requests | 1M/mo | $1.00 per 1M ($0.01/10K) |
| KV Store reads (Class B) | 1M/mo | $0.55 per 1M |
| KV Store writes (Class A) | 100K/mo | $6.50 per 1M ($0.65/100K) |
| Minimum monthly | $0 | — |

Note: Compute services also incur CDN delivery charges (bandwidth + requests).

### Fermyon Cloud

Source: [fermyon.com/pricing](https://www.fermyon.com/pricing)

| Component | Starter (free) | Growth |
|-----------|---------------|--------|
| Monthly fee | $0 | $19.38 |
| Requests included | 100K/mo | 1M/mo |
| Bandwidth included | 5 GB | 50 GB |
| Apps | 5 | 100 |
| Compute billing | Included (no per-ms charge) | Included |
| Beyond quota | Throttled | Enterprise contact |

No per-request overage pricing is published. The plan fee IS the cost.

### Akamai Functions (EdgeWorkers)

Source: [techdocs.akamai.com/edgeworkers](https://techdocs.akamai.com/edgeworkers/docs/reporting-and-billing)

| Component | Rate |
|-----------|------|
| Per-event pricing | **Not publicly listed** — contract-based |
| Resource tiers | Basic, Dynamic, Enterprise Compute |
| Bandwidth | Part of Akamai delivery contract |
| Minimum | Contract-dependent |

Akamai does not publish self-serve pricing for Functions. Costs require a sales quote.

### Cloudflare Workers

Source: [developers.cloudflare.com/workers/platform/pricing](https://developers.cloudflare.com/workers/platform/pricing/)

| Component | Free | Paid ($5/mo) |
|-----------|------|-------------|
| Requests | 100K/day | 10M/mo included, then $0.30/1M |
| CPU time | 10ms/invocation limit | 30M CPU-ms/mo included, then $0.02/1M CPU-ms |
| Bandwidth | Free | Free |
| KV reads | 100K/day | 10M/mo, then $0.50/1M |
| KV writes | 1K/day | 1M/mo, then $5.00/1M |
| Minimum monthly | $0 | $5 |

### AWS Lambda (ARM64, 128MB)

Source: [aws.amazon.com/lambda/pricing](https://aws.amazon.com/lambda/pricing/)

| Component | Free Tier | Rate (after free) |
|-----------|-----------|-------------------|
| Requests | 1M/mo | $0.20 per 1M |
| Compute (ARM) | 400K GB-s/mo | $0.0000133334/GB-second |
| Data transfer out | 100 GB/mo (AWS free tier) | $0.09/GB |
| Minimum monthly | $0 | — |

---

## 2. Workload Profile (from benchmarks)

Our rules-only moderation request:

| Parameter | Value | Source |
|-----------|-------|--------|
| Server processing time | ~4ms (Fastly), ~2.3ms (Akamai), ~5.5ms (Fermyon) | Benchmark medians |
| Response size | ~700 bytes (0.7 KB) | Measured from `/gateway/moderate` |
| Request size | ~200 bytes | POST body with labels + text |
| KV operations | 0 (basic test), 1 read + maybe 1 write (cached mode) | Benchmark contract |
| External calls | 0 (self-contained gateway) | Architecture design |

---

## 3. Cost per 1M Requests (Rules-Only Moderation)

Assumptions:
- Using measured ~4ms vCPU per request (conservative, Fastly's actual)
- Response size 0.7 KB = 0.7 GB per 1M requests
- No KV operations (basic moderation mode)
- Free tier allocations **excluded** (production-scale comparison)

### Fastly Compute

| Component | Calculation | Cost |
|-----------|-------------|------|
| Compute requests | 1M × $0.50/1M | $0.50 |
| Compute vCPU-ms | 4ms × 1M = 4M vCPU-ms × $0.05/1M | $0.20 |
| CDN bandwidth | 0.7 GB × $0.12/GB | $0.08 |
| CDN requests | 1M × $1.00/1M | $1.00 |
| **Total per 1M** | | **$1.78** |

### Fermyon Cloud (Growth Plan)

| Component | Calculation | Cost |
|-----------|-------------|------|
| Plan fee | $19.38/mo (covers 1M requests) | $19.38 |
| Compute | Included | $0.00 |
| Bandwidth | 0.7 GB (within 50 GB included) | $0.00 |
| **Total per 1M** | | **$19.38** |

At the Starter plan (free), cost is $0 for up to 100K requests/month.

### Cloudflare Workers (Paid Plan)

| Component | Calculation | Cost |
|-----------|-------------|------|
| Platform fee | $5/mo minimum | $5.00 |
| Requests | 1M (within 10M included) | $0.00 |
| CPU time | 4ms × 1M = 4M CPU-ms (within 30M included) | $0.00 |
| Bandwidth | Free | $0.00 |
| **Total per 1M** | | **$5.00** |

### AWS Lambda (128MB ARM64)

| Component | Calculation | Cost |
|-----------|-------------|------|
| Requests | 1M × $0.20/1M | $0.20 |
| Compute | 0.125 GB × 0.005s × 1M = 625 GB-s × $0.0000133 | $0.01 |
| Data transfer | 0.7 GB × $0.09/GB | $0.06 |
| **Total per 1M** | | **$0.27** |

### Akamai Functions

| Component | Cost |
|-----------|------|
| Contract-based | **Quote required** |

---

## 4. Cost at Scale

### Monthly cost by request volume (free tiers INCLUDED)

| Monthly Volume | Fastly Compute | Fermyon Cloud | Cloudflare Workers | AWS Lambda |
|---------------|---------------|--------------|-------------------|------------|
| **100K** | **$0.00** | **$0.00** (Starter) | **$0.00** (Free) | **$0.00** |
| **1M** | **$0.00** | $19.38 (Growth) | $5.00 | **~$0.06** |
| **10M** | **$0.00** | Enterprise (?) | $5.20 | **$2.43** |
| **100M** | $159.00 | Enterprise (?) | $39.40 | $26.10 |
| **1B** | $1,517.00 | Enterprise (?) | $381.40 | $265.79 |

### Monthly cost by request volume (free tiers EXCLUDED — true unit economics)

| Monthly Volume | Fastly Compute | Fermyon Cloud | Cloudflare Workers | AWS Lambda |
|---------------|---------------|--------------|-------------------|------------|
| **1M** | **$1.78** | $19.38 | $5.32 | **$0.27** |
| **10M** | $17.80 | Enterprise (?) | $8.20 | $2.70 |
| **100M** | $178.00 | Enterprise (?) | $37.00 | $27.00 |
| **1B** | $1,780.00 | Enterprise (?) | $370.00 | $270.00 |

### Detailed calculation at 100M/month (with free tiers)

**Fastly Compute:**
- Compute requests: 10M free + 90M × $0.50/1M = $45.00
- Compute vCPU-ms: 100M free + 300M × $0.05/1M = $15.00 (400M total at 4ms/req)
- CDN bandwidth: 70 GB (within 100 GB free) = $0.00
- CDN requests: 1M free + 99M × $1.00/1M = $99.00
- **Total: $159.00**

**Cloudflare Workers:**
- Platform: $5.00
- Requests: 10M free + 90M × $0.30/1M = $27.00
- CPU-ms: 30M free + 370M × $0.02/1M = $7.40 (400M total)
- Bandwidth: $0.00
- **Total: $39.40**

**AWS Lambda (128MB ARM64):**
- Requests: 1M free + 99M × $0.20/1M = $19.80
- Compute: 400K GB-s free + 62,100 GB-s × $0.0000133 = $0.83 (62,500 total)
- Data transfer: 70 GB × $0.09/GB = $6.30 (past 100 GB AWS free tier if on 12-mo trial, otherwise full cost)
- **Total: ~$26.93**

---

## 5. Cost-Performance Matrix

The real question: what do you get for your dollar?

### At 1M requests/month (with free tiers)

| Platform | Monthly Cost | Policy p50 | Cost per 1M | Effective $/request |
|----------|-------------|-----------|-------------|---------------------|
| **Fastly Compute** | **$0.00** | **8.6ms** | **$0.00** | **$0.00** |
| AWS Lambda | ~$0.06 | 30.9ms | ~$0.06 | $0.00000006 |
| Cloudflare Workers | $5.00 | **6.6ms** | $5.00 | $0.000005 |
| Fermyon Cloud | $19.38 | 1,100ms | $19.38 | $0.00001938 |

### At 100M requests/month

| Platform | Monthly Cost | Policy p50 | Cost per req | Latency × Cost Score |
|----------|-------------|-----------|-------------|---------------------|
| **Cloudflare Workers** | ~$39 | **6.6ms** | $0.00000039 | **Best** (fastest + mid-cost) |
| **Fastly Compute** | $159 | 8.6ms | $0.0000016 | Fast but 4x pricier than Workers |
| AWS Lambda | ~$27 | 30.9ms | $0.00000027 | Cheapest but single-region |
| Fermyon Cloud | Enterprise | 1,100ms | Unknown | Slow + unknown price |

---

## 6. Key Insights for the Blog Post

### Free tier comparison

| Platform | Free requests/mo | Free compute | Free bandwidth |
|----------|-----------------|-------------|---------------|
| **Fastly Compute** | **10M** | **100M vCPU-ms** | **100 GB** |
| Cloudflare Workers | ~3M (100K/day) | 10ms/req cap | Unlimited |
| AWS Lambda | 1M | 400K GB-s | 100 GB (AWS trial) |
| Fermyon Cloud | 100K | Included | 5 GB |

Fastly's free tier is the most generous — **10M requests/month for free** with 100M vCPU-ms. For our 4ms/request workload, that's 25M requests before hitting compute limits.

### Cost structure differences

1. **Fermyon Cloud**: Plan-based. Simple, but expensive per-request. No compute metering is great for ML-heavy workloads (890ms CPU for free) but the $19.38/1M floor hurts for rules-only.

2. **Fastly Compute**: Usage-based with generous free tier. Most cost-effective at low-to-mid volume. CDN request charges ($1/1M) add up at scale.

3. **Cloudflare Workers**: Usage-based with $5/mo floor. No bandwidth charges is a unique advantage. Most cost-effective at high volume.

4. **AWS Lambda**: Pure usage-based, cheapest per-request at scale. No platform fee. But add API Gateway ($1/1M) or ALB ($0.008/LCU-hour) to get HTTP endpoints.

### The price-performance winner

At every scale tested, **Fastly Compute** delivers the best price-performance ratio for rules-only moderation:

| Scale | Cheapest | Fastest | Best price-performance |
|-------|----------|---------|----------------------|
| 1M/mo | Fastly ($0) | Workers (6.6ms) | **Fastly** (free tier) |
| 10M/mo | Fastly ($0) | Workers (6.6ms) | **Fastly** (free tier) |
| 100M/mo | Lambda ($27) | Workers (6.6ms) | **Workers** ($39, 6.6ms global) |
| 1B/mo | Lambda ($270) | Workers (6.6ms) | **Workers if latency matters, Lambda if cost-first** |

At massive scale (1B+), AWS Lambda is cheapest ($270/mo) but serves a single region (31ms from Chicago, 246ms from Singapore). Workers costs $370/mo — 37% more — but delivers 6.6ms globally. Fastly at $1,780/mo is 4.8x more expensive than Workers with comparable latency.

---

## 7. Disclaimers

- Pricing is from public rate cards as of April 2026; enterprise/negotiated rates may differ significantly.
- Akamai Functions pricing requires a sales quote and is excluded from comparisons.
- AWS Lambda costs do not include API Gateway/ALB charges needed for HTTP endpoints.
- Fermyon Cloud beyond Growth tier (>1M/mo) requires enterprise contact.
- All five platforms have been benchmarked. See `results/five_platform_scorecard.md` for full data.
- Free tier calculations assume these are the only workloads on the account.
- All costs are USD, pay-as-you-go, no reserved capacity or committed use discounts.
