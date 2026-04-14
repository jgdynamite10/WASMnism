#!/usr/bin/env python3
"""
Tier 1 Cost Analysis — Fastly, Cloudflare Workers, Akamai Functions
Parses actual platform usage data and calculates costs against published pricing.
"""
import json
import sys
from datetime import datetime, timezone

# Published pricing (April 2026) — from cost-config.example.yaml
FASTLY_PRICING = {
    "compute_request_per_1m": 0.50,
    "compute_vcpu_ms_per_1m": 0.05,
    "cdn_bandwidth_per_gb": 0.12,
    "cdn_request_per_1m": 1.00,
    "free_compute_requests": 10_000_000,
    "free_vcpu_ms": 100_000_000,
    "free_cdn_bandwidth_gb": 100,
    "free_cdn_requests": 1_000_000,
}

WORKERS_PRICING = {
    "platform_monthly": 5.00,
    "request_per_1m": 0.30,
    "cpu_ms_per_1m": 0.02,
    "free_requests": 10_000_000,
    "free_cpu_ms": 30_000_000,
}


def parse_fastly_ndjson(path):
    """Parse newline-delimited JSON from fastly stats historical."""
    days = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                ts = obj.get("start_time", 0)
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                days.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "compute_requests": obj.get("compute_requests", 0),
                    "compute_request_time_billed_ms": obj.get("compute_request_time_billed_ms", 0),
                    "compute_execution_time_ms": obj.get("compute_execution_time_ms", 0),
                    "bandwidth": obj.get("bandwidth", 0),
                    "all_status_2xx": obj.get("all_status_2xx", 0),
                    "all_status_4xx": obj.get("all_status_4xx", 0),
                    "all_status_5xx": obj.get("all_status_5xx", 0),
                    "compute_resp_body_bytes": obj.get("compute_resp_body_bytes", 0),
                    "compute_req_body_bytes": obj.get("compute_req_body_bytes", 0),
                    "compute_guest_errors": obj.get("compute_guest_errors", 0),
                    "compute_ram_used": obj.get("compute_ram_used", 0),
                    "kv_class_a": obj.get("kv_store_class_a_operations", 0) or obj.get("object_store_class_a_operations", 0),
                    "kv_class_b": obj.get("kv_store_class_b_operations", 0) or obj.get("object_store_class_b_operations", 0),
                })
            except json.JSONDecodeError:
                continue
    return days


def calc_fastly_costs(days, include_free_tier=True):
    """Calculate Fastly costs from usage data.

    IMPORTANT: vCPU billing uses compute_execution_time_ms (actual CPU work time),
    NOT compute_request_time_billed_ms (Compute Duration with 50ms floor).
    Fastly's Compute Duration metric only applies to pre-March 2026 customers.
    Verified against Fastly billing console April 2026.
    """
    total_requests = sum(d["compute_requests"] for d in days)
    total_duration_ms = sum(d["compute_request_time_billed_ms"] for d in days)
    total_exec_ms = sum(d["compute_execution_time_ms"] for d in days)
    total_bandwidth_bytes = sum(d["bandwidth"] for d in days)
    total_bandwidth_gb = total_bandwidth_bytes / (1024**3)
    total_resp_bytes = sum(d["compute_resp_body_bytes"] for d in days)
    total_req_bytes = sum(d["compute_req_body_bytes"] for d in days)

    avg_exec_ms_per_req = total_exec_ms / total_requests if total_requests > 0 else 0

    if include_free_tier:
        billable_requests = max(0, total_requests - FASTLY_PRICING["free_compute_requests"])
        billable_vcpu_ms = max(0, total_exec_ms - FASTLY_PRICING["free_vcpu_ms"])
        billable_bw_gb = max(0, total_bandwidth_gb - FASTLY_PRICING["free_cdn_bandwidth_gb"])
        billable_cdn_requests = max(0, total_requests - FASTLY_PRICING["free_cdn_requests"])
    else:
        billable_requests = total_requests
        billable_vcpu_ms = total_exec_ms
        billable_bw_gb = total_bandwidth_gb
        billable_cdn_requests = total_requests

    cost_compute_req = (billable_requests / 1_000_000) * FASTLY_PRICING["compute_request_per_1m"]
    cost_vcpu = (billable_vcpu_ms / 1_000_000) * FASTLY_PRICING["compute_vcpu_ms_per_1m"]
    cost_bandwidth = billable_bw_gb * FASTLY_PRICING["cdn_bandwidth_per_gb"]
    cost_cdn_req = (billable_cdn_requests / 1_000_000) * FASTLY_PRICING["cdn_request_per_1m"]
    total_cost = cost_compute_req + cost_vcpu + cost_bandwidth + cost_cdn_req

    return {
        "total_requests": total_requests,
        "total_duration_ms": total_duration_ms,
        "total_exec_ms": total_exec_ms,
        "total_bandwidth_gb": total_bandwidth_gb,
        "total_resp_bytes": total_resp_bytes,
        "total_req_bytes": total_req_bytes,
        "avg_exec_ms_per_req": avg_exec_ms_per_req,
        "cost_compute_req": cost_compute_req,
        "cost_vcpu": cost_vcpu,
        "cost_bandwidth": cost_bandwidth,
        "cost_cdn_req": cost_cdn_req,
        "total_cost": total_cost,
        "include_free_tier": include_free_tier,
    }


def calc_workers_costs(days_data, include_free_tier=True):
    """Calculate Workers costs from GraphQL analytics data."""
    total_requests = sum(d["requests"] for d in days_data)
    total_duration_ms = sum(d["duration_ms"] for d in days_data)
    total_wall_time_ms = sum(d["wall_time_ms"] for d in days_data)
    total_resp_bytes = sum(d["response_body_size"] for d in days_data)

    avg_cpu_ms_per_req = total_duration_ms / total_requests if total_requests > 0 else 0
    avg_wall_ms_per_req = total_wall_time_ms / total_requests if total_requests > 0 else 0

    if include_free_tier:
        billable_requests = max(0, total_requests - WORKERS_PRICING["free_requests"])
        billable_cpu_ms = max(0, total_duration_ms - WORKERS_PRICING["free_cpu_ms"])
    else:
        billable_requests = total_requests
        billable_cpu_ms = total_duration_ms

    cost_platform = WORKERS_PRICING["platform_monthly"]
    cost_requests = (billable_requests / 1_000_000) * WORKERS_PRICING["request_per_1m"]
    cost_cpu = (billable_cpu_ms / 1_000_000) * WORKERS_PRICING["cpu_ms_per_1m"]
    total_cost = cost_platform + cost_requests + cost_cpu

    return {
        "total_requests": total_requests,
        "total_cpu_ms": total_duration_ms,
        "total_wall_time_ms": total_wall_time_ms,
        "total_resp_bytes": total_resp_bytes,
        "avg_cpu_ms_per_req": avg_cpu_ms_per_req,
        "avg_wall_ms_per_req": avg_wall_ms_per_req,
        "cost_platform": cost_platform,
        "cost_requests": cost_requests,
        "cost_cpu": cost_cpu,
        "total_cost": total_cost,
        "include_free_tier": include_free_tier,
    }


def format_number(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(int(n))


def format_ms(ms):
    if ms >= 1_000_000_000:
        return f"{ms/1_000_000_000:.2f}B ms"
    elif ms >= 1_000_000:
        return f"{ms/1_000_000:.1f}M ms"
    elif ms >= 1_000:
        return f"{ms/1_000:.1f}K ms"
    return f"{ms:.1f} ms"


def format_bytes(b):
    if b >= 1024**3:
        return f"{b/(1024**3):.2f} GB"
    elif b >= 1024**2:
        return f"{b/(1024**2):.1f} MB"
    elif b >= 1024:
        return f"{b/1024:.1f} KB"
    return f"{b} B"


def format_cost(c):
    if c < 0.01:
        return f"${c:.4f}"
    return f"${c:.2f}"


def main():
    # Parse Fastly data — scoped to Apr 7-13 only
    fastly_benchmark = parse_fastly_ndjson("/tmp/fastly_benchmark_stats_apr7_13.json")

    # CF Workers data (verified via GraphQL Analytics API, Apr 7-13 2026)
    cf_days = [
        {"date": "2026-04-07", "requests": 6_017_330, "duration_ms": 3_384_188.233, "wall_time_ms": 4_512_998_025/1000, "response_body_size": 2_820_794_215, "errors": 8},
        {"date": "2026-04-08", "requests": 14, "duration_ms": 119.371, "wall_time_ms": 129_236/1000, "response_body_size": 40_962, "errors": 0},
        {"date": "2026-04-09", "requests": 183_745, "duration_ms": 52_637.280, "wall_time_ms": 90_098_111/1000, "response_body_size": 111_212_451, "errors": 0},
        {"date": "2026-04-10", "requests": 3_716_143, "duration_ms": 1_877_046.494, "wall_time_ms": 2_555_868_558/1000, "response_body_size": 1_755_439_641, "errors": 0},
        {"date": "2026-04-11", "requests": 6, "duration_ms": 47.657, "wall_time_ms": 49_792/1000, "response_body_size": 2_000, "errors": 0},
        {"date": "2026-04-12", "requests": 5_438_453, "duration_ms": 2_711_616.120, "wall_time_ms": 3_640_419_551/1000, "response_body_size": 2_526_623_337, "errors": 0},
        {"date": "2026-04-13", "requests": 24_681_733, "duration_ms": 15_095_845.000, "wall_time_ms": 19_392_006_483/1000, "response_body_size": 13_179_474_607, "errors": 0},
    ]

    # Akamai data — per-day derived via spin aka app status --usage-since <RFC3339> deltas
    akamai_days = [
        {"date": "2026-04-07", "requests": 1},
        {"date": "2026-04-08", "requests": 0},
        {"date": "2026-04-09", "requests": 119},
        {"date": "2026-04-10", "requests": 5_877_657},
        {"date": "2026-04-11", "requests": 0},
        {"date": "2026-04-12", "requests": 4_368_106},
        {"date": "2026-04-13", "requests": 34_702_362},
    ]
    akamai_total = sum(d["requests"] for d in akamai_days)  # 44,948,245

    print("=" * 80)
    print("TIER 1 COST ANALYSIS — RAW PLATFORM DATA")
    print("=" * 80)

    # --- Fastly ---
    print("\n" + "=" * 40)
    print("FASTLY COMPUTE — wasm-prompt-firewall")
    print("=" * 40)
    print(f"\nPeriod: April 7–13, 2026")
    print(f"Service: wasm-prompt-firewall (P6OG...)")
    print("\nDaily breakdown:")
    print(f"{'Date':<14} {'Requests':>12} {'Billed ms':>14} {'Exec ms':>14} {'Bandwidth':>12} {'Errors':>8}")
    print("-" * 76)
    for d in fastly_benchmark:
        if d["compute_requests"] > 0:
            print(f"{d['date']:<14} {format_number(d['compute_requests']):>12} {format_ms(d['compute_request_time_billed_ms']):>14} {format_ms(d['compute_execution_time_ms']):>14} {format_bytes(d['bandwidth']):>12} {d['all_status_5xx']:>8}")

    fastly_with_free = calc_fastly_costs(fastly_benchmark, include_free_tier=True)
    fastly_no_free = calc_fastly_costs(fastly_benchmark, include_free_tier=False)

    print(f"\nTotals (benchmark service only):")
    print(f"  Total requests:        {format_number(fastly_with_free['total_requests'])}")
    print(f"  Compute vCPU time:     {format_ms(fastly_with_free['total_exec_ms'])} (actual CPU work — this is what Fastly bills)")
    print(f"  Compute duration:      {format_ms(fastly_with_free['total_duration_ms'])} (wall clock w/ 50ms floor — NOT billed for vCPU)")
    print(f"  Bandwidth:             {fastly_with_free['total_bandwidth_gb']:.2f} GB")
    print(f"  Avg vCPU ms/req:       {fastly_with_free['avg_exec_ms_per_req']:.2f} ms")

    print(f"\nCost breakdown (WITH free tier):")
    print(f"  Compute requests:  {format_cost(fastly_with_free['cost_compute_req'])}")
    print(f"  Compute vCPU-ms:   {format_cost(fastly_with_free['cost_vcpu'])}")
    print(f"  CDN bandwidth:     {format_cost(fastly_with_free['cost_bandwidth'])}")
    print(f"  CDN requests:      {format_cost(fastly_with_free['cost_cdn_req'])}")
    print(f"  TOTAL:             {format_cost(fastly_with_free['total_cost'])}")

    print(f"\nCost breakdown (WITHOUT free tier — true unit economics):")
    print(f"  Compute requests:  {format_cost(fastly_no_free['cost_compute_req'])}")
    print(f"  Compute vCPU-ms:   {format_cost(fastly_no_free['cost_vcpu'])}")
    print(f"  CDN bandwidth:     {format_cost(fastly_no_free['cost_bandwidth'])}")
    print(f"  CDN requests:      {format_cost(fastly_no_free['cost_cdn_req'])}")
    print(f"  TOTAL:             {format_cost(fastly_no_free['total_cost'])}")

    # --- Workers ---
    print("\n" + "=" * 40)
    print("CLOUDFLARE WORKERS — wasm-prompt-firewall")
    print("=" * 40)
    print(f"\nPeriod: April 7–13, 2026")
    print("\nDaily breakdown:")
    print(f"{'Date':<14} {'Requests':>12} {'CPU ms':>14} {'Resp Size':>12} {'Errors':>8}")
    print("-" * 62)
    for d in cf_days:
        if d["requests"] > 0:
            print(f"{d['date']:<14} {format_number(d['requests']):>12} {format_ms(d['duration_ms']):>14} {format_bytes(d['response_body_size']):>12} {d['errors']:>8}")

    cf_with_free = calc_workers_costs(cf_days, include_free_tier=True)
    cf_no_free = calc_workers_costs(cf_days, include_free_tier=False)

    total_cf_requests = sum(d["requests"] for d in cf_days)
    total_cf_cpu = sum(d["duration_ms"] for d in cf_days)
    total_cf_errors = sum(d["errors"] for d in cf_days)
    total_cf_resp = sum(d["response_body_size"] for d in cf_days)

    print(f"\nTotals:")
    print(f"  Total requests:    {format_number(total_cf_requests)}")
    print(f"  Total CPU time:    {format_ms(total_cf_cpu)}")
    print(f"  Total response:    {format_bytes(total_cf_resp)}")
    print(f"  Total errors:      {total_cf_errors}")
    print(f"  Avg CPU ms/req:    {cf_with_free['avg_cpu_ms_per_req']:.4f} ms")

    print(f"\nCost breakdown (WITH free tier):")
    print(f"  Platform fee:      {format_cost(cf_with_free['cost_platform'])}")
    print(f"  Requests:          {format_cost(cf_with_free['cost_requests'])}")
    print(f"  CPU time:          {format_cost(cf_with_free['cost_cpu'])}")
    print(f"  Bandwidth:         $0.00 (free)")
    print(f"  TOTAL:             {format_cost(cf_with_free['total_cost'])}")

    print(f"\nCost breakdown (WITHOUT free tier):")
    print(f"  Platform fee:      {format_cost(cf_no_free['cost_platform'])}")
    print(f"  Requests:          {format_cost(cf_no_free['cost_requests'])}")
    print(f"  CPU time:          {format_cost(cf_no_free['cost_cpu'])}")
    print(f"  Bandwidth:         $0.00 (free)")
    print(f"  TOTAL:             {format_cost(cf_no_free['total_cost'])}")

    print(f"\n  *** ESTIMATE vs ACTUAL BILLING ***")
    print(f"  The above are CALCULATED ESTIMATES from GraphQL API data (40M requests, Apr 7-13).")
    print(f"  Actual CF billing console (current cycle, Apr 9-14):")
    print(f"    Requests counted:  24.68M (vs our 40.04M)")
    print(f"    Usage cost:        $4.50  (14.68M billable × $0.30/1M)")
    print(f"    Platform fee:      $5.00/mo")
    print(f"    CPU cost:          $0.00  (15.08M ms within 30M free tier)")
    print(f"    ACTUAL TOTAL:      $9.50")
    print(f"  Difference: billing cycle does not align with benchmark window.")

    # --- Akamai ---
    print("\n" + "=" * 40)
    print("AKAMAI FUNCTIONS — wasm-prompt-firewall")
    print("=" * 40)
    print(f"\nPeriod: April 7–13, 2026")
    print(f"\nDaily breakdown:")
    print(f"{'Date':<14} {'Requests':>12}")
    print("-" * 28)
    for d in akamai_days:
        if d["requests"] > 0:
            print(f"{d['date']:<14} {format_number(d['requests']):>12}")
    print(f"\n  Total invocations (Apr 7-13): {format_number(akamai_total)}")
    print(f"  Pricing: Preview/beta — $0 (no billing during preview)")
    print(f"  TOTAL COST: $0.00")

    # --- Summary ---
    print("\n" + "=" * 80)
    print("COST COMPARISON SUMMARY — April 7–13, 2026 (all platforms)")
    print("=" * 80)
    print(f"\n{'Platform':<20} {'Requests':>12} {'Period':>14} {'Cost (w/ free)':>16} {'Cost (no free)':>16} {'$/1M req':>10}")
    print("-" * 90)
    fastly_per_1m = fastly_no_free["total_cost"] / (fastly_with_free["total_requests"] / 1_000_000) if fastly_with_free["total_requests"] > 0 else 0
    cf_per_1m = cf_no_free["total_cost"] / (total_cf_requests / 1_000_000) if total_cf_requests > 0 else 0
    print(f"{'Fastly Compute':<20} {format_number(fastly_with_free['total_requests']):>12} {'Apr 7-13':>14} {format_cost(fastly_with_free['total_cost']):>16} {format_cost(fastly_no_free['total_cost']):>16} {format_cost(fastly_per_1m):>10}")
    print(f"{'CF Workers (est.)':<20} {format_number(total_cf_requests):>12} {'Apr 7-13':>14} {format_cost(cf_with_free['total_cost']):>16} {format_cost(cf_no_free['total_cost']):>16} {format_cost(cf_per_1m):>10}")
    print(f"{'CF Workers (actual)':<20} {'24.68M':>12} {'billing cycle':>14} {'$9.50':>16} {'n/a':>16} {'n/a':>10}")
    print(f"{'Akamai Functions':<20} {format_number(akamai_total):>12} {'Apr 7-13':>14} {'$0.00':>16} {'$0.00':>16} {'$0.00':>10}")

    # Key insight: why is Fastly expensive?
    print("\n" + "=" * 80)
    print("WHY IS FASTLY EXPENSIVE? — Billing Analysis")
    print("=" * 80)
    print(f"""
The #1 cost driver on Fastly is CDN REQUEST DOUBLE-BILLING.

Every compute invocation triggers TWO separate request charges:
  - Compute requests: $0.50/1M (function invocation)
  - CDN requests:     $1.00/1M (delivery — charged ON TOP of compute)
  Combined:           $1.50/1M per-request fees

For {format_number(fastly_with_free['total_requests'])} requests:
  CDN request charges:     {format_cost(fastly_no_free['cost_cdn_req'])}  ({fastly_no_free['cost_cdn_req']/fastly_no_free['total_cost']*100:.0f}%)  ← PRIMARY DRIVER
  Compute request charges: {format_cost(fastly_no_free['cost_compute_req'])}  ({fastly_no_free['cost_compute_req']/fastly_no_free['total_cost']*100:.0f}%)
  Compute vCPU time:       {format_cost(fastly_no_free['cost_vcpu'])}  ({fastly_no_free['cost_vcpu']/fastly_no_free['total_cost']*100:.0f}%)
  CDN bandwidth:           {format_cost(fastly_no_free['cost_bandwidth'])}  ({fastly_no_free['cost_bandwidth']/fastly_no_free['total_cost']*100:.0f}%)

Per-request fees (compute + CDN) are {(fastly_no_free['cost_compute_req']+fastly_no_free['cost_cdn_req'])/fastly_no_free['total_cost']*100:.0f}% of the total Fastly bill.
Actual compute vCPU is only {fastly_no_free['cost_vcpu']/fastly_no_free['total_cost']*100:.0f}% — the WASM execution is very efficient.

NOTE: Fastly vCPU billing uses compute_execution_time_ms (actual CPU work, avg
{fastly_with_free['avg_exec_ms_per_req']:.2f} ms/req). The compute_request_time_billed_ms field
(50ms floor) is Compute Duration — only charged to pre-March 2026 customers.
Verified against Fastly billing console April 2026.

Workers comparison: $0.30/1M (single charge, no CDN surcharge, free bandwidth).
At the same volume, Workers would cost:
  Requests: {format_cost((fastly_with_free['total_requests']/1_000_000) * 0.30)}
  CPU time:  negligible (sub-ms per request)
  Platform:  $5.00
  Bandwidth: $0.00
""")

    # --- Monthly Extrapolation (7-day → 30-day) ---
    scale = 30 / 7
    print("\n" + "=" * 80)
    print("MONTHLY EXTRAPOLATION — 7-day actuals × (30/7)")
    print("=" * 80)
    fastly_monthly_req = fastly_with_free["total_requests"] * scale
    workers_monthly_req = total_cf_requests * scale
    akamai_monthly_req = akamai_total * scale
    fastly_monthly_cost = fastly_per_1m * (fastly_monthly_req / 1_000_000)
    workers_monthly_cost = cf_per_1m * (workers_monthly_req / 1_000_000)
    print(f"\n{'Platform':<20} {'7-day Requests':>16} {'30-day Projected':>18} {'Projected Cost':>16}")
    print("-" * 72)
    print(f"{'Fastly Compute':<20} {format_number(fastly_with_free['total_requests']):>16} {format_number(fastly_monthly_req):>18} {format_cost(fastly_monthly_cost):>16}")
    print(f"{'CF Workers':<20} {format_number(total_cf_requests):>16} {format_number(workers_monthly_req):>18} {format_cost(workers_monthly_cost):>16}")
    print(f"{'Akamai Functions':<20} {format_number(akamai_total):>16} {format_number(akamai_monthly_req):>18} {'$0.00 (preview)':>16}")

    return {
        "fastly_with_free": fastly_with_free,
        "fastly_no_free": fastly_no_free,
        "cf_with_free": cf_with_free,
        "cf_no_free": cf_no_free,
        "akamai_total": akamai_total,
        "akamai_days": akamai_days,
        "fastly_days": fastly_benchmark,
        "cf_days": cf_days,
        "fastly_per_1m": fastly_per_1m,
        "cf_per_1m": cf_per_1m,
    }


if __name__ == "__main__":
    main()
