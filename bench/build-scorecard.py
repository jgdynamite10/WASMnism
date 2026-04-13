#!/usr/bin/env python3
"""Build a 3-platform comparison scorecard from benchmark results.

Usage:
  python3 build-scorecard.py <akamai_dir> <fastly_dir> <workers_dir> [output_path] [OPTIONS]

Options:
  --runner LABEL              Runner origin label (default: env BENCH_RUNNER or "Linode")
  --peak-dir DIR              Directory with constant-50vu per-platform JSONs
  --ext-akamai DIR            Akamai extended suite results (full/*.json)
  --ext-fastly DIR            Fastly extended suite results (full/*.json)
  --ext-workers DIR           Workers extended suite results (full/*.json)

Each base directory should contain the 7run/ folder with per-run JSON and
optionally cold-start-rules.json. Extended dirs should contain
concurrency-ladder-full.json, soak-500vu.json, spike.json.

Example:
  python3 bench/build-scorecard.py \\
    results/akamai/multiregion_.../us-ord \\
    results/fastly/multiregion_.../us-ord \\
    results/workers/multiregion_.../us-ord \\
    scorecard.md --runner "k6 us-ord" \\
    --ext-akamai results/akamai/multiregion_.../us-ord/full \\
    --ext-fastly results/fastly/multiregion_.../us-ord/full \\
    --ext-workers results/workers/multiregion_.../us-ord/full
"""

import json
import sys
import os
import statistics
from pathlib import Path


def load(path):
    with open(path) as f:
        return json.load(f)


def fmt_ms(v):
    if v is None:
        return "—"
    if v >= 1000:
        return f"{v/1000:.2f}s"
    return f"{v:.1f} ms"


def fmt_rps(v):
    if v is None:
        return "—"
    if v >= 1000:
        return f"{v:,.0f}/s"
    return f"{v:.0f}/s"


def fmt_int(v):
    if v is None:
        return "—"
    return f"{v:,}"


def fmt_pct(v):
    if v is None:
        return "—"
    return f"{v*100:.2f}%"


def bold_winner_ms(*values):
    """Return list of formatted strings; lowest non-None gets **bold**."""
    formatted = [fmt_ms(v) for v in values]
    valid = [(v, i) for i, v in enumerate(values) if v is not None]
    if valid:
        _, best_idx = min(valid, key=lambda x: x[0])
        formatted[best_idx] = f"**{formatted[best_idx]}**"
    return formatted


def bold_winner_rps(*values):
    """Return list of formatted strings; highest non-None gets **bold**."""
    formatted = [fmt_rps(v) for v in values]
    valid = [(v, i) for i, v in enumerate(values) if v is not None]
    if valid:
        _, best_idx = max(valid, key=lambda x: x[0])
        formatted[best_idx] = f"**{formatted[best_idx]}**"
    return formatted


def bold_winner_jitter(*values):
    """Lowest jitter wins."""
    formatted = [f"{v:.2f}x" if v else "—" for v in values]
    valid = [(v, i) for i, v in enumerate(values) if v is not None]
    if valid:
        _, best_idx = min(valid, key=lambda x: x[0])
        formatted[best_idx] = f"**{formatted[best_idx]}**"
    return formatted


def extract_metrics(data):
    m = data.get("metrics", {})
    dur = m.get("http_req_duration", {})
    iters = m.get("iterations", {})
    errs = m.get("errors", {})
    proc = m.get("server_processing_ms", m.get("processing_ms", {}))
    wait = m.get("http_req_waiting", {})

    return {
        "p50": dur.get("med"),
        "p95": dur.get("p(95)"),
        "max": dur.get("max"),
        "rps": iters.get("rate"),
        "reqs": iters.get("count"),
        "err": errs.get("rate") if errs else None,
        "proc_p50": proc.get("med") if proc else None,
        "wait_p50": wait.get("med") if wait else None,
    }


def jitter(data):
    m = data.get("metrics", {}).get("http_req_duration", {})
    p50, p95 = m.get("med"), m.get("p(95)")
    if p50 and p50 > 0 and p95:
        return p95 / p50
    return None


def compute_7run_medians(run_dir, filename):
    """Compute medians across 7 runs for a given test file."""
    values = {}
    for run_num in range(1, 8):
        path = run_dir / f"run_{run_num}" / filename
        if not path.exists():
            continue
        data = load(path)
        metrics = extract_metrics(data)
        j = jitter(data)
        for key, val in metrics.items():
            if val is not None:
                values.setdefault(key, []).append(val)
        if j is not None:
            values.setdefault("jitter", []).append(j)
    return {k: statistics.median(v) for k, v in values.items() if v}


def region_table(title, test_file, dirs, names, show_proc=False):
    """Generate a per-region detail table for a test."""
    lines = []
    lines.append(f"\n#### {title}\n")
    lines.append(f"| Metric | {names[0]} | {names[1]} | {names[2]} |")
    lines.append("|:-------|-------:|-------:|--------:|")

    medians = []
    for d in dirs:
        run_dir = d / "7run"
        if run_dir.exists():
            medians.append(compute_7run_medians(run_dir, test_file))
        else:
            medians.append({})

    if not any(medians):
        lines.append("| *No data available* | | | |")
        return "\n".join(lines)

    p50s = [m.get("p50") for m in medians]
    p95s = [m.get("p95") for m in medians]
    rpss = [m.get("rps") for m in medians]
    errs = [m.get("err") for m in medians]
    jits = [m.get("jitter") for m in medians]

    a, b, c = bold_winner_ms(*p50s)
    lines.append(f"| p50 | {a} | {b} | {c} |")

    a, b, c = bold_winner_ms(*p95s)
    lines.append(f"| p95 | {a} | {b} | {c} |")

    a, b, c = bold_winner_rps(*rpss)
    lines.append(f"| Requests/sec | {a} | {b} | {c} |")

    lines.append(f"| Error rate | {fmt_pct(errs[0])} | {fmt_pct(errs[1])} | {fmt_pct(errs[2])} |")

    a, b, c = bold_winner_jitter(*jits)
    lines.append(f"| Jitter (p95/p50) | {a} | {b} | {c} |")

    if show_proc:
        procs = [m.get("proc_p50") for m in medians]
        lines.append("")
        lines.append("**Server processing (p50):**")
        proc_strs = []
        for p in procs:
            if p is not None and p < 1:
                proc_strs.append("< 1 ms")
            elif p is not None:
                proc_strs.append(fmt_ms(p))
            else:
                proc_strs.append("—")
        lines.append(f"  {names[0]}: {proc_strs[0]} · {names[1]}: {proc_strs[1]} · {names[2]}: {proc_strs[2]}")

    return "\n".join(lines)


def cold_start_section(dirs, names):
    """Generate cold start table from cold-start-rules JSON."""
    lines = []
    lines.append("\n## 3. Cold Start Latency\n")
    lines.append("Cold start measures round-trip time after 120s idle eviction.")
    lines.append("")
    lines.append(f"| Region | {names[0]} p50 | {names[0]} p95 | {names[1]} p50 | {names[1]} p95 | {names[2]} p50 | {names[2]} p95 |")
    lines.append("|:-------|----------:|----------:|----------:|----------:|----------:|----------:|")

    for d in dirs:
        region = d.name
        row = [f"| {region}"]
        for plat_dir in dirs:
            path = plat_dir / f"cold-start-rules_{plat_dir.name}.json"
            if not path.exists():
                path_alt = list(plat_dir.glob("cold-start-rules_*.json"))
                if path_alt:
                    path = path_alt[0]
            if path.exists():
                data = load(path)
                rt = data.get("metrics", {}).get("cold_round_trip", {})
                row.append(f" {fmt_ms(rt.get('med'))} | {fmt_ms(rt.get('p(95)'))}")
            else:
                row.append(" — | —")
        lines.append(" | ".join(row) + " |")

    lines.append("")
    lines.append("*Data source: `cold-start-rules_<region>.json` — 10 iterations, 120s idle.*")
    return "\n".join(lines)


def peak_50vu_section(peak_dir, names, regions):
    """Generate sustained peak section from constant-50vu results."""
    lines = []
    lines.append("\n## 7. Sustained Peak Load (50 VUs, 60s)\n")
    lines.append("Constant 50 VUs for 60 seconds — accurate production stress test.\n")

    platform_keys = ["akamai", "fastly", "workers"]
    region_names = {"us-ord": "Chicago (US)", "eu-central": "Frankfurt (EU)", "ap-south": "Singapore (APAC)"}

    for region in regions:
        city = region_names.get(region, region)
        lines.append(f"\n#### {city}\n")
        lines.append(f"| Metric | {names[0]} | {names[1]} | {names[2]} |")
        lines.append("|:-------|-------:|-------:|--------:|")

        metrics = []
        for pk in platform_keys:
            path = peak_dir / f"{pk}_{region}.json"
            if path.exists():
                metrics.append(extract_metrics(load(path)))
            else:
                metrics.append({})

        if any(metrics):
            p50s = [m.get("p50") for m in metrics]
            p95s = [m.get("p95") for m in metrics]
            rpss = [m.get("rps") for m in metrics]
            maxs = [m.get("max") for m in metrics]
            reqs = [m.get("reqs") for m in metrics]
            errs = [m.get("err") for m in metrics]

            a, b, c = bold_winner_ms(*p50s)
            lines.append(f"| p50 | {a} | {b} | {c} |")
            a, b, c = bold_winner_ms(*p95s)
            lines.append(f"| p95 | {a} | {b} | {c} |")
            a, b, c = bold_winner_rps(*rpss)
            lines.append(f"| Requests/sec | {a} | {b} | {c} |")
            lines.append(f"| Error rate | {fmt_pct(errs[0])} | {fmt_pct(errs[1])} | {fmt_pct(errs[2])} |")
            a, b, c = bold_winner_ms(*maxs)
            lines.append(f"| Max latency | {a} | {b} | {c} |")
            lines.append(f"| Total requests | {fmt_int(reqs[0])} | {fmt_int(reqs[1])} | {fmt_int(reqs[2])} |")

    lines.append("")
    lines.append(f"*Data source: `constant-50vu.js`, `{peak_dir}/`.*")
    return "\n".join(lines)


def ext_single_file_table(title, description, filename, ext_dirs, names):
    """Generate a table from a single extended-suite JSON per platform."""
    lines = []
    lines.append(f"\n{title}\n")
    lines.append(description)
    lines.append("")

    metrics = []
    for d in ext_dirs:
        path = d / filename
        if path.exists():
            metrics.append(extract_metrics(load(path)))
        else:
            metrics.append({})

    if not any(metrics):
        lines.append("*No data available.*")
        return "\n".join(lines)

    lines.append(f"| Metric | {names[0]} | {names[1]} | {names[2]} |")
    lines.append("|:-------|-------:|-------:|--------:|")

    p50s = [m.get("p50") for m in metrics]
    p95s = [m.get("p95") for m in metrics]
    maxs = [m.get("max") for m in metrics]
    rpss = [m.get("rps") for m in metrics]
    reqs = [m.get("reqs") for m in metrics]
    errs = [m.get("err") for m in metrics]

    a, b, c = bold_winner_ms(*p50s)
    lines.append(f"| p50 | {a} | {b} | {c} |")
    a, b, c = bold_winner_ms(*p95s)
    lines.append(f"| p95 | {a} | {b} | {c} |")
    a, b, c = bold_winner_ms(*maxs)
    lines.append(f"| Max latency | {a} | {b} | {c} |")
    a, b, c = bold_winner_rps(*rpss)
    lines.append(f"| Requests/sec | {a} | {b} | {c} |")
    lines.append(f"| Total requests | {fmt_int(reqs[0])} | {fmt_int(reqs[1])} | {fmt_int(reqs[2])} |")
    lines.append(f"| Error rate | {fmt_pct(errs[0])} | {fmt_pct(errs[1])} | {fmt_pct(errs[2])} |")

    lines.append("")
    lines.append(f"*Data source: `{filename}`.*")
    return "\n".join(lines)


def extended_suite_section(ext_dirs, names):
    """Generate all extended-suite sections."""
    lines = []

    lines.append("\n---\n")
    lines.append("## 8. Extended Suite — High Concurrency & Stress\n")
    lines.append("These tests require dedicated runners (4+ vCPU, 8+ GB RAM).\n")

    lines.append(ext_single_file_table(
        "### 8a. Full Concurrency Ladder (1 → 1,000 VUs, 7 min)",
        "Seven 60-second steps ramping from 1 to 1,000 concurrent virtual users.",
        "concurrency-ladder-full.json", ext_dirs, names))

    lines.append(ext_single_file_table(
        "### 8b. Soak Test (500 VUs, 10 min)",
        "Sustained 500 VUs for 10 minutes. Reveals memory leaks, GC pauses, and throttling.",
        "soak-500vu.json", ext_dirs, names))

    lines.append(ext_single_file_table(
        "### 8c. Spike Test (0 → 2,000 VUs)",
        "Flash ramp from 0 to peak in 10s, hold 60s, ramp down. Finds the breaking point.",
        "spike.json", ext_dirs, names))

    return "\n".join(lines)


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    args = list(sys.argv[1:])
    runner = os.environ.get("BENCH_RUNNER", "Linode")
    peak_dir = None
    ext_dirs = [None, None, None]

    def pop_flag(name):
        nonlocal args
        if name in args:
            idx = args.index(name)
            val = args[idx + 1]
            args = args[:idx] + args[idx + 2:]
            return val
        return None

    runner = pop_flag("--runner") or runner
    peak_dir_str = pop_flag("--peak-dir")
    peak_dir = Path(peak_dir_str) if peak_dir_str else None

    ext_a = pop_flag("--ext-akamai")
    ext_b = pop_flag("--ext-fastly")
    ext_c = pop_flag("--ext-workers")
    if ext_a:
        ext_dirs = [Path(ext_a), Path(ext_b) if ext_b else Path("."), Path(ext_c) if ext_c else Path(".")]

    dir_a = Path(args[0])
    dir_b = Path(args[1])
    dir_c = Path(args[2])
    output = args[3] if len(args) > 3 else None

    names = ["Akamai", "Fastly", "Workers"]
    base_dirs = [dir_a, dir_b, dir_c]

    # Detect regions: if dirs contain region subdirs (us-ord, eu-central, ap-south),
    # iterate across them. Otherwise treat as single-region dirs.
    REGION_MAP = {
        "us-ord": "Chicago (US)",
        "eu-central": "Frankfurt (EU)",
        "ap-south": "Singapore (APAC)",
    }
    regions_found = []
    for region_key in REGION_MAP:
        if (dir_a / region_key / "7run").exists():
            regions_found.append(region_key)

    if regions_found:
        is_multiregion = True
    else:
        is_multiregion = False
        regions_found = [dir_a.name]

    lines = []
    lines.append("# WASMnism Edge Platform Scorecard\n")
    lines.append(f"## {names[0]} vs {names[1]} vs {names[2]}\n")
    lines.append("| Field | Value |")
    lines.append("|:------|:------|")
    date_label = dir_a.name if is_multiregion else dir_a.parent.name
    lines.append(f"| **Date** | {date_label} |")
    lines.append(f"| **Runner** | {runner} |")
    lines.append(f"| **Regions** | {', '.join(REGION_MAP.get(r, r) for r in regions_found)} |")
    lines.append("| **Contract** | v3.3 — rules-only pipeline |")
    lines.append("| **Build** | `main` branch, ML stripped |")
    lines.append("| **Methodology** | 7-run medians · k6 `http_req_duration` |")
    lines.append("")

    # Section 1: glossary
    lines.append("\n---\n")
    lines.append("## 1. How to Read This Scorecard\n")
    lines.append("| Test | What it measures | How it works |")
    lines.append("|:-----|:-----------------|:-------------|")
    lines.append("| **Cold Start** | First request after idle eviction | 1 VU, 120s idle, 10 iterations |")
    lines.append("| **Warm Light** | Baseline `/gateway/health` | 10 VUs, 60s |")
    lines.append("| **Warm Policy** | Full 7-step moderation pipeline | 10 VUs, 60s |")
    lines.append("| **Concurrency Ladder** | Ramp behaviour 1→50 VUs | 30s stages, 150s total |")
    lines.append("| **Sustained Peak** | Constant 50-VU production load | 50 VUs, 60s |")
    if ext_dirs[0]:
        lines.append("| **Full Ladder** | High-concurrency scaling | 1→1,000 VUs, 60s/step, 7 min |")
        lines.append("| **Soak** | Stability under sustained load | 500 VUs, 10 min |")
        lines.append("| **Spike** | Breaking point under sudden load | 0→2,000 VUs, ramp+hold+down |")
    lines.append("")

    def get_region_dirs(region_key):
        """Return [akamai_dir, fastly_dir, workers_dir] for a given region."""
        if is_multiregion:
            return [d / region_key for d in base_dirs]
        return base_dirs

    # Sections 4-6: per-region tables
    lines.append("\n---\n")
    lines.append("## 4. Warm Light — Health Check (10 VUs, 60s)\n")
    for region_key in regions_found:
        region_label = REGION_MAP.get(region_key, region_key)
        rdirs = get_region_dirs(region_key)
        lines.append(region_table(region_label, "warm-light.json", rdirs, names))
    lines.append("\n*Data source: 7-run medians from warm-light.json.*")

    lines.append("\n---\n")
    lines.append("## 5. Warm Policy — Rules Pipeline (10 VUs, 60s)\n")
    for region_key in regions_found:
        region_label = REGION_MAP.get(region_key, region_key)
        rdirs = get_region_dirs(region_key)
        lines.append(region_table(region_label, "warm-policy.json", rdirs, names, show_proc=True))
    lines.append("\n*Data source: 7-run medians from warm-policy.json.*")

    lines.append("\n---\n")
    lines.append("## 6. Concurrency Ladder (1 → 50 VUs, 150s)\n")
    lines.append("Metrics aggregated across all VU stages.\n")
    for region_key in regions_found:
        region_label = REGION_MAP.get(region_key, region_key)
        rdirs = get_region_dirs(region_key)
        lines.append(region_table(region_label, "concurrency-ladder.json", rdirs, names))
    lines.append("\n*Data source: 7-run medians from concurrency-ladder.json.*")

    # Section 7: Peak 50 VU (if data provided)
    if peak_dir and peak_dir.exists():
        lines.append("\n---\n")
        lines.append(peak_50vu_section(peak_dir, names, regions_found))

    # Section 8: Extended suite
    if ext_dirs[0] and ext_dirs[0].exists():
        lines.append(extended_suite_section(ext_dirs, names))

    # Section 11: architecture
    lines.append("\n---\n")
    lines.append("## 11. Platform Architecture Comparison\n")
    lines.append("| Aspect | Akamai Functions | Fastly Compute | Cloudflare Workers |")
    lines.append("|:-------|:-----------------|:---------------|:-------------------|")
    lines.append("| Architecture | Two-tier (edge + compute) | Single-tier (PoP = compute) | Single-tier (V8 isolate) |")
    lines.append("| WASM target | `wasm32-wasip1` | `wasm32-wasip1` | `wasm32-unknown-unknown` |")
    lines.append("| Scheduling | On-demand | Pre-warmed | Pre-warmed |")
    lines.append("| Global PoPs | 4,400+ edge locations | 130+ PoPs | 330+ cities |")
    lines.append("| Pricing tier | Preview / beta | Usage-based | Paid ($5/mo) |")
    lines.append("")

    output_text = "\n".join(lines) + "\n"

    if output:
        with open(output, "w") as f:
            f.write(output_text)
        print(f"Scorecard written to {output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
