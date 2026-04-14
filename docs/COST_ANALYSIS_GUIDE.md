# Cost Analysis Guide

Operational guide for producing Tier 1 cost analysis reports for WASMnism.

## Data Collection

### Fastly Compute

```bash
fastly stats historical \
  --service-id P6OGBpYSN19w9UxuaAfbdi \
  --from 2026-04-07 \
  --to 2026-04-14 \
  --by day > /tmp/fastly_benchmark_stats.json
```

Output: newline-delimited JSON, one object per day. Key fields:

| API Field | Meaning | Billing Use |
|:----------|:--------|:------------|
| `compute_requests` | Invocations | Billed at $0.50/1M |
| `compute_execution_time_ms` | **Actual CPU work time** | **Billed for vCPU at $0.05/1M ms** |
| `compute_request_time_billed_ms` | Wall clock w/ 50ms floor | **NOT billed for vCPU** (Compute Duration, pre-March 2026 customers only) |
| `bandwidth` | Total bandwidth in bytes | Billed at $0.12/GB (CDN bandwidth) |
| `all_status_2xx` / `4xx` / `5xx` | Status code counts | Not billed directly |
| `compute_resp_body_bytes` | Response body bytes | Informational |
| `compute_req_body_bytes` | Request body bytes | Informational |

**CRITICAL**: Use `compute_execution_time_ms` for vCPU cost, NOT `compute_request_time_billed_ms`. The 50ms-floor Duration metric is a legacy billing model for pre-March 2026 customers. Verified against Fastly billing console April 2026.

CDN requests are billed separately at $1.00/1M. They equal `compute_requests` (every compute invocation also counts as a CDN request).

### Cloudflare Workers

Use the GraphQL Analytics API:

```bash
curl -s https://api.cloudflare.com/client/v4/graphql \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -d '{"query": "{ viewer { accounts(filter: {accountTag: \"$ACCOUNT_ID\"}) { workersInvocationsAdaptive(limit: 100, filter: {scriptName: \"wasm-prompt-firewall\", datetimeHour_geq: \"2026-04-07T00:00:00Z\", datetimeHour_lt: \"2026-04-14T00:00:00Z\"}, orderBy: [datetimeHour_ASC]) { dimensions { datetimeHour scriptName } sum { requests duration wallTime responseBodySize errors } } } } }"}'
```

Key fields from `sum`:

| Field | Meaning | Billing Use |
|:------|:--------|:------------|
| `requests` | Invocations | Billed at $0.30/1M |
| `duration` | CPU time (ms) | Billed at $0.02/1M ms |
| `wallTime` | Wall clock (ms) | Not billed |
| `responseBodySize` | Response bytes | Not billed (bandwidth is free) |

### Akamai Functions

```bash
spin aka app status --usage-since "2026-04-07T00:00:00Z"
```

Returns total invocations since the given timestamp. To get per-day data, run consecutive queries and compute deltas:

```bash
spin aka app status --usage-since "2026-04-12T00:00:00Z"
spin aka app status --usage-since "2026-04-13T00:00:00Z"
```

Constraint: `usage-since` only works within a 7-day window.

During preview, Akamai Functions has no billing. Total cost is $0.

## Pricing Constants (April 2026)

### Fastly Compute

| Item | Rate | Free Tier |
|:-----|:-----|:----------|
| Compute requests | $0.50/1M | 10M/month |
| Compute vCPU | $0.05/1M ms | 100M ms/month |
| CDN requests | $1.00/1M | 1M/month |
| CDN bandwidth | $0.12/GB | 100 GB/month |

### Cloudflare Workers

| Item | Rate | Free Tier |
|:-----|:-----|:----------|
| Platform fee | $5.00/month | — |
| Requests | $0.30/1M | 10M/month |
| CPU time | $0.02/1M ms | 30M ms/month |
| Bandwidth | Free | — |

### Akamai Functions

Preview/beta — $0 during preview phase.

## Calculation Methodology

### Cost Formula (without free tier)

```
Fastly total = (requests/1M × $0.50) + (exec_ms/1M × $0.05) + (gb × $0.12) + (requests/1M × $1.00)
Workers total = $5.00 + (requests/1M × $0.30) + (cpu_ms/1M × $0.02)
Akamai total = $0.00 (preview)
```

### Cost Formula (with free tier)

```
Fastly total = (max(0, requests - 10M)/1M × $0.50) + (max(0, exec_ms - 100M)/1M × $0.05) + (max(0, gb - 100) × $0.12) + (max(0, requests - 1M)/1M × $1.00)
Workers total = $5.00 + (max(0, requests - 10M)/1M × $0.30) + (max(0, cpu_ms - 30M)/1M × $0.02)
```

### Unit Economics ($/1M requests)

```
$/1M = total_cost_no_free / (total_requests / 1M)
```

### Monthly Extrapolation

```
monthly_requests = 7_day_requests × (30/7)
monthly_cost = per_1m_cost × (monthly_requests / 1M)
```

## Chart Generation

```bash
python3 bench/generate-charts.py --origin cost --out results/charts-cost/
```

Generates 4 SVGs:
- `chart_executive_summary.svg` — Total cost and $/1M bars
- `chart_concurrency_scaling.svg` — Daily request volume lines
- `chart_cold_start.svg` — Fastly cost decomposition stacked bar
- `chart_throughput_at_scale.svg` — Monthly extrapolation grouped bars

Update `COST_DATA` in `bench/generate-charts.py` with fresh numbers before regenerating.

## Report Generation Workflow

1. **Collect data**: Run CLI commands above for all 3 platforms.
2. **Calculate costs**: Run `python3 cost/analyze-tier1-costs.py` (update data sources in the script first).
3. **Update chart data**: Edit `COST_DATA` in `bench/generate-charts.py` with the script output.
4. **Write .md**: Copy `templates/cost_analysis_template.md`, fill all `{{PLACEHOLDER}}` values.
5. **Write .html**: Hand-craft HTML using canonical CSS from template. Match section structure of .md.
6. **Generate charts**: `python3 bench/generate-charts.py --origin cost --out results/charts-cost/`
7. **Inject charts**: `python3 bench/inject-charts.py --html <file>.html --charts results/charts-cost/`
8. **Generate PDF**: `python3 -m weasyprint <file>.html <file>.pdf`

## Naming Convention

```
results/{Month}_{Day}_Tier1_Cost_Analysis.{md,html,pdf}
```

Example: `results/April_13_Tier1_Cost_Analysis.md`

## Critical Rules

1. **Never use `compute_request_time_billed_ms` for vCPU cost.** Use `compute_execution_time_ms`.
2. **Always query all 3 platforms for the same measurement period.** Normalize dates.
3. **Always include both "with free tier" and "without free tier" calculations.** The "without free tier" number is the true unit economics.
4. **State if any number is an estimate.** If you can't query live data, say so explicitly.
5. **Include the About/Live demos/Source block** in every report (see template).
6. **Run `make security-check` before committing.** Cost data files may contain IPs.
