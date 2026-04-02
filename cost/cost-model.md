# Cost Model: Price per 1M Requests

## Methodology

Cost is calculated for 1 million requests at each benchmark mode.
Pricing uses the public rate card for each platform as of March 2026.
All costs are in USD.

---

## Platform Pricing Summary

### Akamai Functions (Fermyon Cloud / Spin)

| Component | Rate |
|-----------|------|
| Requests | $0.50 per 1M requests |
| Compute | $18/mo per dedicated core (included in free tier for low volume) |
| KV Store reads | $0.50 per 1M reads |
| KV Store writes | $1.00 per 1M writes |
| Bandwidth | $0.08/GB |

### Fastly Compute

| Component | Rate |
|-----------|------|
| Requests | $0.40 per 10K requests ($40 per 1M) |
| Compute (WASM exec) | Included in request price |
| KV Store reads | $0.50 per 1M reads |
| KV Store writes | $5.00 per 1M writes |
| Bandwidth | $0.08/GB |

### Cloudflare Workers

| Component | Rate |
|-----------|------|
| Requests (Standard) | $0.30 per 1M requests |
| CPU time | $0.02 per 1M ms of CPU time |
| KV reads | $0.50 per 1M reads |
| KV writes | $5.00 per 1M writes |
| Bandwidth | Free (included) |

### AWS Lambda

| Component | Rate |
|-----------|------|
| Requests | $0.20 per 1M requests |
| Compute | $0.0000133 per GB-second (128MB ARM64) |
| DynamoDB reads | $0.25 per 1M read capacity units |
| DynamoDB writes | $1.25 per 1M write capacity units |
| NAT Gateway | $0.045/hr + $0.045/GB (for outbound to inference) |
| Bandwidth | $0.09/GB |

---

## Cost Calculation Template

### Per-Test Assumptions

| Test | Avg Response Size | KV Reads | Compute Weight | Notes |
|------|------------------|----------|----------------|-------|
| Warm Light (health) | ~0.2 KB | 0 | Minimal | No ML, no policy |
| Warm Policy (rules) | ~0.7 KB | 0 | ~3ms CPU | Full rule pipeline, `ml: false` |
| Warm Heavy (ML) | ~1 KB | 0 | ~890ms CPU | ML toxicity inference |

### Cost per 1M Requests

Fermyon Cloud costs are based on observed benchmark data (March 2026).
Other platforms to be filled after deployment and benchmarking.

**Fermyon Cloud (Spin) — observed metrics:**
- Warm-light: avg 52ms round-trip, ~0.2 KB response, ~189 RPS at 10 VUs
- Warm-policy: avg 562ms round-trip (3.2ms server), ~0.7 KB, ~17 RPS at 10 VUs
- Warm-heavy: avg 1400ms round-trip (912ms server), ~1 KB, ~3.5 RPS at 5 VUs

| Platform | Test | Requests | Compute | KV | Bandwidth | Total |
|----------|------|----------|---------|----|-----------| ------|
| Spin | warm-light | $0.50 | included | N/A | $0.16 | **~$0.66** |
| Spin | warm-policy | $0.50 | included | N/A | $0.06 | **~$0.56** |
| Spin | warm-heavy | $0.50 | included | N/A | $0.08 | **~$0.58** |
| Fastly | warm-light | | | N/A | | |
| Fastly | warm-policy | | | N/A | | |
| Fastly | warm-heavy | | | N/A | | |
| Workers | warm-light | | | N/A | | |
| Workers | warm-policy | | | N/A | | |
| Workers | warm-heavy | | | N/A | | |
| Lambda | warm-light | | | N/A | | |
| Lambda | warm-policy | | | N/A | | |
| Lambda | warm-heavy | | | N/A | | |

**Fermyon cost notes:**
- Request cost: $0.50/1M applies to all test types.
- Compute: Included in Fermyon Cloud pricing (no per-ms billing).
  This is a significant advantage for ML-heavy workloads — the ~890ms
  of CPU time per heavy request incurs no additional compute charge.
  For rules-only (warm-policy), the ~3ms processing is negligible.
- Bandwidth: 1M × 0.2 KB = 0.2 GB × $0.08 = $0.016 (light);
  1M × 0.7 KB = 0.7 GB × $0.08 = $0.056 (policy);
  1M × 1 KB = 1 GB × $0.08 = $0.08 (heavy).
- KV: Not used in warm-light, warm-policy, or warm-heavy benchmarks.

---

## Notes

- Pricing is based on public rate cards and may differ from negotiated enterprise contracts.
- Free tier allocations are NOT included in calculations (we assume production-scale volume).
- The gateway is self-contained — no external inference calls, so no NAT Gateway costs.
- Warm-policy cost is minimal (~3ms CPU per request).
- Warm-heavy cost is dominated by CPU time (ML inference ~890ms per request).
- Bandwidth costs use average response size from benchmark measurements.
- All prices are pay-as-you-go; reserved capacity or committed use discounts are excluded.
