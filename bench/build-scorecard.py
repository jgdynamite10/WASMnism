#!/usr/bin/env python3
"""Build a comparison scorecard from benchmark results.

Usage: python3 build-scorecard.py <results_dir1> <results_dir2> [output_path] [--runner LABEL]

Example:
  python3 bench/build-scorecard.py results/akamai/multiregion_20260410/us-ord/7run results/fastly/multiregion_20260410/us-ord/7run
  python3 bench/build-scorecard.py results/akamai/... results/fastly/... scorecard.md --runner "k6 us-ord"
"""

import json
import sys
import os
from pathlib import Path


def load(path):
    with open(path) as f:
        return json.load(f)


def get(data, *keys, default=None):
    v = data
    for k in keys:
        if isinstance(v, dict):
            v = v.get(k, {})
        else:
            return default
    return v if v != {} else default


def fmt_ms(v):
    if v is None:
        return "—"
    if v >= 1000:
        return f"{v/1000:.2f}s"
    return f"{v:.1f}ms"


def fmt_int(v):
    if v is None:
        return "—"
    return f"{v:,}"


def fmt_pct(v):
    if v is None:
        return "—"
    return f"{v*100:.2f}%"


def ratio(a, b):
    if a is None or b is None or b == 0:
        return "—"
    return f"{a/b:.1f}x"


def extract_metrics(data):
    m = data.get("metrics", {})
    dur = m.get("http_req_duration", {})
    iters = m.get("iterations", {})
    errs = m.get("errors", {})
    proc = m.get("server_processing_ms", m.get("processing_ms", {}))

    return {
        "p50": dur.get("med"),
        "p95": dur.get("p(95)"),
        "p90": dur.get("p(90)"),
        "avg": dur.get("avg"),
        "max": dur.get("max"),
        "min": dur.get("min"),
        "reqs": iters.get("count"),
        "rps": iters.get("rate"),
        "err": errs.get("value"),
        "proc_p50": proc.get("med"),
        "proc_avg": proc.get("avg"),
    }


def jitter(data):
    m = data.get("metrics", {})
    dur = m.get("http_req_duration", {})
    p50 = dur.get("med")
    p95 = dur.get("p(95)")
    if p50 and p50 > 0 and p95:
        return p95 / p50
    return None


def section(title, fa, fb, name_a, name_b, show_proc=False):
    lines = []
    lines.append(f"\n## {title}\n")
    lines.append(f"| Metric | {name_a} | {name_b} | Ratio |")
    lines.append("|--------|---------|---------|-------|")

    def row(label, key, formatter=fmt_ms):
        va = fa.get(key)
        vb = fb.get(key)
        lines.append(f"| {label} | {formatter(va)} | {formatter(vb)} | {ratio(va, vb)} |")

    row("Round-trip p50", "p50")
    row("Round-trip p90", "p90")
    row("Round-trip p95", "p95")
    row("Round-trip avg", "avg")
    row("Max latency", "max")
    row("Total requests", "reqs", fmt_int)
    row("Requests/sec", "rps", lambda v: f"{v:.1f}/s" if v else "—")
    row("Error rate", "err", fmt_pct)

    if show_proc:
        row("Server processing p50", "proc_p50")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    args = list(sys.argv[1:])
    runner = os.environ.get("BENCH_RUNNER", "unknown")
    if "--runner" in args:
        idx = args.index("--runner")
        runner = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    dir_a = Path(args[0])
    dir_b = Path(args[1])
    output = args[2] if len(args) > 2 else None

    name_a = dir_a.parent.name.title()
    name_b = dir_b.parent.name.title()

    lines = []
    lines.append(f"# WASMnism Benchmark Scorecard (rules-only)")
    lines.append(f"")
    lines.append(f"**{name_a}** vs **{name_b}**")
    lines.append(f"")
    lines.append(f"- Date: {dir_a.name}")
    lines.append(f"- Runner: {runner}")
    lines.append(f"")

    tests = [
        ("Warm Light (Health Check, 10 VUs, 60s)", "warm-light.json", False),
        ("Warm Policy (Rules Pipeline, 10 VUs, 60s)", "warm-policy.json", True),
        ("Concurrency Ladder (1→50 VUs, 150s)", "concurrency-rules.json", False),
    ]

    lines.append("\n---\n")
    lines.append("# Rules Pipeline Suite\n")

    for title, filename, show_proc in tests:
        path_a = dir_a / filename
        path_b = dir_b / filename

        if not path_a.exists() or not path_b.exists():
            lines.append(f"\n## {title}\n")
            lines.append("*Results not available for both platforms.*\n")
            continue

        da = load(path_a)
        db = load(path_b)
        fa = extract_metrics(da)
        fb = extract_metrics(db)
        lines.append(section(title, fa, fb, name_a, name_b, show_proc))

    # Cold start — rules
    lines.append("\n---\n")
    lines.append("# Cold Start\n")

    path_a = dir_a / "cold-start-rules.json"
    path_b = dir_b / "cold-start-rules.json"
    if path_a.exists() and path_b.exists():
        da = load(path_a)
        db = load(path_b)
        fa = extract_metrics(da)
        fb = extract_metrics(db)
        lines.append(section("Cold Start — Rules", fa, fb, name_a, name_b))
    else:
        lines.append("\n## Cold Start — Rules\n")
        lines.append("*Results not available for both platforms.*\n")

    output_text = "\n".join(lines) + "\n"

    if output:
        with open(output, "w") as f:
            f.write(output_text)
        print(f"Scorecard written to {output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
