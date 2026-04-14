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
    """Calculate Fastly costs from usage data."""
    total_requests = sum(d["compute_requests"] for d in days)
    total_billed_ms = sum(d["compute_request_time_billed_ms"] for d in days)
    total_bandwidth_bytes = sum(d["bandwidth"] for d in days)
    total_bandwidth_gb = total_bandwidth_bytes / (1024**3)
    total_resp_bytes = sum(d["compute_resp_body_bytes"] for d in days)
    total_req_bytes = sum(d["compute_req_body_bytes"] for d in days)
    total_exec_ms = sum(d["compute_execution_time_ms"] for d in days)

    avg_billed_ms_per_req = total_billed_ms / total_requests if total_requests > 0 else 0
    avg_exec_ms_per_req = total_exec_ms / total_requests if total_requests > 0 else 0

    if include_free_tier:
        billable_requests = max(0, total_requests - FASTLY_PRICING["free_compute_requests"])
        billable_vcpu_ms = max(0, total_billed_ms - FASTLY_PRICING["free_vcpu_ms"])
        billable_bw_gb = max(0, total_bandwidth_gb - FASTLY_PRICING["free_cdn_bandwidth_gb"])
        billable_cdn_requests = max(0, total_requests - FASTLY_PRICING["free_cdn_requests"])
    else:
        billable_requests = total_requests
        billable_vcpu_ms = total_billed_ms
        billable_bw_gb = total_bandwidth_gb
        billable_cdn_requests = total_requests

    cost_compute_req = (billable_requests / 1_000_000) * FASTLY_PRICING["compute_request_per_1m"]
    cost_vcpu = (billable_vcpu_ms / 1_000_000) * FASTLY_PRICING["compute_vcpu_ms_per_1m"]
    cost_bandwidth = billable_bw_gb * FASTLY_PRICING["cdn_bandwidth_per_gb"]
    cost_cdn_req = (billable_cdn_requests / 1_000_000) * FASTLY_PRICING["cdn_request_per_1m"]
    total_cost = cost_compute_req + cost_vcpu + cost_bandwidth + cost_cdn_req

    return {
        "total_requests": total_requests,
        "total_billed_ms": total_billed_ms,
        "total_exec_ms": total_exec_ms,
        "total_bandwidth_gb": total_bandwidth_gb,
        "total_resp_bytes": total_resp_bytes,
        "total_req_bytes": total_req_bytes,
        "avg_billed_ms_per_req": avg_billed_ms_per_req,
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
    # Parse Fastly data
    fastly_benchmark = parse_fastly_ndjson("/tmp/fastly_benchmark_stats.json")
    fastly_vcl = parse_fastly_ndjson("/tmp/fastly_vcl_stats.json")

    # CF Workers data (hardcoded from GraphQL response)
    cf_days = [
        {"date": "2026-04-07", "requests": 6_017_330, "duration_ms": 3384188.233, "wall_time_ms": 4512998025/1000, "response_body_size": 2_820_794_215, "errors": 8},
        {"date": "2026-04-08", "requests": 14, "duration_ms": 119.371, "wall_time_ms": 129236/1000, "response_body_size": 40_962, "errors": 0},
        {"date": "2026-04-09", "requests": 183_745, "duration_ms": 52637.280, "wall_time_ms": 90098111/1000, "response_body_size": 111_212_451, "errors": 0},
        {"date": "2026-04-10", "requests": 3_716_143, "duration_ms": 1877046.494, "wall_time_ms": 2555868558/1000, "response_body_size": 1_755_439_641, "errors": 0},
        {"date": "2026-04-11", "requests": 6, "duration_ms": 47.657, "wall_time_ms": 49792/1000, "response_body_size": 2_000, "errors": 0},
        {"date": "2026-04-12", "requests": 5_438_453, "duration_ms": 2711616.120, "wall_time_ms": 3640419551/1000, "response_body_size": 2_526_623_337, "errors": 0},
        {"date": "2026-04-13", "requests": 24_681_724, "duration_ms": 15095806.406, "wall_time_ms": 19391954896/1000, "response_body_size": 13_179_442_241, "errors": 0},
    ]

    # Akamai data (from spin aka app status)
    akamai_invocations_7d = 44_948_245

    print("=" * 80)
    print("TIER 1 COST ANALYSIS — RAW PLATFORM DATA")
    print("=" * 80)

    # --- Fastly ---
    print("\n" + "=" * 40)
    print("FASTLY COMPUTE — wasm-prompt-firewall")
    print("=" * 40)
    print(f"\nPeriod: April 1–13, 2026")
    print(f"Services: wasm-prompt-firewall (P6OG...), preferably-valid-turtle (CbRn...), ME's website (pUoj...)")
    print("\nBenchmark service (wasm-prompt-firewall) — Daily breakdown:")
    print(f"{'Date':<14} {'Requests':>12} {'Billed ms':>14} {'Exec ms':>14} {'Bandwidth':>12} {'Errors':>8}")
    print("-" * 76)
    for d in fastly_benchmark:
        if d["compute_requests"] > 0:
            print(f"{d['date']:<14} {format_number(d['compute_requests']):>12} {format_ms(d['compute_request_time_billed_ms']):>14} {format_ms(d['compute_execution_time_ms']):>14} {format_bytes(d['bandwidth']):>12} {d['all_status_5xx']:>8}")

    fastly_with_free = calc_fastly_costs(fastly_benchmark, include_free_tier=True)
    fastly_no_free = calc_fastly_costs(fastly_benchmark, include_free_tier=False)

    print(f"\nTotals (benchmark service only):")
    print(f"  Total requests:        {format_number(fastly_with_free['total_requests'])}")
    print(f"  Billed compute time:   {format_ms(fastly_with_free['total_billed_ms'])}")
    print(f"  Actual execution time: {format_ms(fastly_with_free['total_exec_ms'])}")
    print(f"  Bandwidth:             {fastly_with_free['total_bandwidth_gb']:.2f} GB")
    print(f"  Avg billed ms/req:     {fastly_with_free['avg_billed_ms_per_req']:.1f} ms")
    print(f"  Avg exec ms/req:       {fastly_with_free['avg_exec_ms_per_req']:.2f} ms")
    print(f"  Billed/Exec ratio:     {fastly_with_free['avg_billed_ms_per_req']/fastly_with_free['avg_exec_ms_per_req']:.1f}x")

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

    # --- Akamai ---
    print("\n" + "=" * 40)
    print("AKAMAI FUNCTIONS — wasm-prompt-firewall")
    print("=" * 40)
    print(f"\n  Invocations (last 7 days): {format_number(akamai_invocations_7d)}")
    print(f"  Pricing: Preview/beta — $0 (no billing during preview)")
    print(f"  TOTAL COST: $0.00")

    # --- Summary ---
    print("\n" + "=" * 80)
    print("COST COMPARISON SUMMARY")
    print("=" * 80)
    print(f"\n{'Platform':<20} {'Requests':>12} {'Period':>14} {'Cost (w/ free)':>16} {'Cost (no free)':>16} {'$/1M req':>10}")
    print("-" * 90)
    fastly_per_1m = fastly_no_free["total_cost"] / (fastly_with_free["total_requests"] / 1_000_000) if fastly_with_free["total_requests"] > 0 else 0
    cf_per_1m = cf_no_free["total_cost"] / (total_cf_requests / 1_000_000) if total_cf_requests > 0 else 0
    print(f"{'Fastly Compute':<20} {format_number(fastly_with_free['total_requests']):>12} {'Apr 1-13':>14} {format_cost(fastly_with_free['total_cost']):>16} {format_cost(fastly_no_free['total_cost']):>16} {format_cost(fastly_per_1m):>10}")
    print(f"{'CF Workers':<20} {format_number(total_cf_requests):>12} {'Apr 7-13':>14} {format_cost(cf_with_free['total_cost']):>16} {format_cost(cf_no_free['total_cost']):>16} {format_cost(cf_per_1m):>10}")
    print(f"{'Akamai Functions':<20} {format_number(akamai_invocations_7d):>12} {'Last 7 days':>14} {'$0.00':>16} {'$0.00':>16} {'$0.00':>10}")

    # Key insight: why is Fastly expensive?
    print("\n" + "=" * 80)
    print("WHY IS FASTLY EXPENSIVE? — Billing Analysis")
    print("=" * 80)
    print(f"""
The #1 cost driver on Fastly is CDN REQUEST CHARGES, not compute.

Fastly bills compute requests AND CDN requests separately:
  - Compute requests: $0.50/1M (your code execution)
  - CDN requests:     $1.00/1M (delivery — DOUBLE the compute rate)

For {format_number(fastly_with_free['total_requests'])} requests:
  Compute request charges: {format_cost(fastly_no_free['cost_compute_req'])}
  CDN request charges:     {format_cost(fastly_no_free['cost_cdn_req'])}  ← THIS IS THE CULPRIT
  Compute vCPU time:       {format_cost(fastly_no_free['cost_vcpu'])}
  CDN bandwidth:           {format_cost(fastly_no_free['cost_bandwidth'])}

CDN requests are {fastly_no_free['cost_cdn_req']/fastly_no_free['total_cost']*100:.0f}% of the total Fastly bill.

Additionally, Fastly's BILLED time is {fastly_with_free['avg_billed_ms_per_req']:.1f}ms per request,
while actual execution is only {fastly_with_free['avg_exec_ms_per_req']:.2f}ms — a {fastly_with_free['avg_billed_ms_per_req']/fastly_with_free['avg_exec_ms_per_req']:.0f}x multiplier.
This is Fastly's minimum billing granularity (50ms minimum per invocation).

Cloudflare Workers charges $0.30/1M requests (single charge, no separate CDN fee)
and has FREE bandwidth. At the same volume, Workers would cost:
  Requests: {format_cost((fastly_with_free['total_requests']/1_000_000) * 0.30)}
  CPU time:  negligible (sub-ms per request)
  Platform:  $5.00
  Bandwidth: $0.00
""")

    return {
        "fastly_with_free": fastly_with_free,
        "fastly_no_free": fastly_no_free,
        "cf_with_free": cf_with_free,
        "cf_no_free": cf_no_free,
        "akamai_invocations_7d": akamai_invocations_7d,
        "fastly_days": fastly_benchmark,
        "cf_days": cf_days,
    }


if __name__ == "__main__":
    main()
