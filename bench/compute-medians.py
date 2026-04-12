#!/usr/bin/env python3
"""Compute median metrics from 7 benchmark runs.

Usage: python3 compute-medians.py <7run_dir> [output_path]

Reads run_1/ through run_7/ under the given directory, extracts key
metrics from each test JSON, and reports the median of each metric.
"""

import json
import sys
import os
from pathlib import Path
from statistics import median


def load(path):
    with open(path) as f:
        return json.load(f)


def extract(data):
    m = data.get("metrics", {})
    dur = m.get("http_req_duration", {})
    iters = m.get("iterations", {})
    errs = m.get("errors", {})
    proc = m.get("server_processing_ms", m.get("processing_ms", {}))

    return {
        "p50": dur.get("med"),
        "p90": dur.get("p(90)"),
        "p95": dur.get("p(95)"),
        "avg": dur.get("avg"),
        "max": dur.get("max"),
        "min": dur.get("min"),
        "reqs": iters.get("count"),
        "rps": iters.get("rate"),
        "err": errs.get("value"),
        "proc_p50": proc.get("med"),
    }


def fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        if v >= 1000:
            return f"{v/1000:.2f}s"
        return f"{v:.1f}ms"
    return str(v)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    base = Path(sys.argv[1])
    output = sys.argv[2] if len(sys.argv) > 2 else None

    tests = ["warm-light", "warm-policy", "concurrency-ladder"]
    runs = sorted(base.glob("run_*"))

    if len(runs) < 3:
        print(f"Found {len(runs)} runs, need at least 3.")
        sys.exit(1)

    lines = []
    platform = base.parent.name if base.parent.name != "results" else "Unknown"
    lines.append(f"# {platform.title()} Benchmark Medians ({len(runs)} runs)")
    lines.append(f"")
    lines.append(f"Directory: {base}")
    lines.append(f"")
    lines.append("---")
    lines.append("")
    lines.append("## Rules Pipeline Suite")
    lines.append("")

    for test in tests:
        all_metrics = {}
        valid_runs = 0
        for run_dir in runs:
            path = run_dir / f"{test}.json"
            if not path.exists():
                continue
            data = load(path)
            m = extract(data)
            valid_runs += 1
            for k, v in m.items():
                if v is not None:
                    all_metrics.setdefault(k, []).append(v)

        lines.append(f"## {test} ({valid_runs} runs)")
        lines.append(f"")
        lines.append(f"| Metric | Median | Min | Max |")
        lines.append(f"|--------|--------|-----|-----|")

        for key in ["p50", "p90", "p95", "avg", "max", "reqs", "rps", "err", "proc_p50"]:
            vals = all_metrics.get(key, [])
            if not vals:
                continue
            med = median(vals)
            lo = min(vals)
            hi = max(vals)
            label = key.replace("_", " ")
            if key == "err":
                lines.append(f"| {label} | {med*100:.2f}% | {lo*100:.2f}% | {hi*100:.2f}% |")
            elif key in ("reqs",):
                lines.append(f"| {label} | {int(med):,} | {int(lo):,} | {int(hi):,} |")
            elif key == "rps":
                lines.append(f"| {label} | {med:.1f}/s | {lo:.1f}/s | {hi:.1f}/s |")
            else:
                lines.append(f"| {label} | {fmt(med)} | {fmt(lo)} | {fmt(hi)} |")

        jitter_vals = []
        for run_dir in runs:
            path = run_dir / f"{test}.json"
            if not path.exists():
                continue
            data = load(path)
            m = data.get("metrics", {}).get("http_req_duration", {})
            p50 = m.get("med")
            p95 = m.get("p(95)")
            if p50 and p50 > 0 and p95:
                jitter_vals.append(p95 / p50)

        if jitter_vals:
            lines.append(f"| jitter (p95/p50) | {median(jitter_vals):.2f}x | {min(jitter_vals):.2f}x | {max(jitter_vals):.2f}x |")

        lines.append(f"")

    text = "\n".join(lines) + "\n"

    if output:
        with open(output, "w") as f:
            f.write(text)
        print(f"Written to {output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
