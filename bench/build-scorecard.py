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
    ml = m.get("ml_inference_ms", {})
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
        "ml_p50": ml.get("med"),
        "ml_avg": ml.get("avg"),
        "ml_p95": ml.get("p(95)"),
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


def section(title, fa, fb, name_a, name_b, show_ml=False, show_proc=False):
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

    if show_ml:
        row("ML inference p50", "ml_p50")
        row("ML inference p95", "ml_p95")
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
    lines.append(f"# WASMnism Benchmark Scorecard")
    lines.append(f"")
    lines.append(f"**{name_a}** vs **{name_b}**")
    lines.append(f"")
    lines.append(f"- Date: {dir_a.name}")
    lines.append(f"- Runner: {runner}")
    lines.append(f"")

    # Primary suite tests (filenames match run-suite.sh output)
    primary_tests = [
        ("Warm Light (Health Check, 10 VUs, 60s)", "warm-light.json", False, False),
        ("Warm Policy (Rules Pipeline, 10 VUs, 60s)", "warm-policy.json", False, True),
        ("Concurrency Ladder — Rules (1→50 VUs, 150s)", "concurrency-rules.json", False, False),
    ]

    # Stretch suite tests
    stretch_tests = [
        ("Warm Heavy (ML Inference, 5 VUs, 60s)", "warm-heavy.json", True, False),
        ("Consistency — ML (5 VUs, 120s)", "consistency-ml.json", True, False),
    ]

    lines.append("\n---\n")
    lines.append("# Primary Suite (rules, ml:false)\n")

    for title, filename, show_ml, show_proc in primary_tests:
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
        lines.append(section(title, fa, fb, name_a, name_b, show_ml, show_proc))

    lines.append("\n---\n")
    lines.append("# Stretch Suite (embedded ML, ml:true)\n")

    for title, filename, show_ml, show_proc in stretch_tests:
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
        lines.append(section(title, fa, fb, name_a, name_b, show_ml, show_proc))

        ja = jitter(da)
        jb = jitter(db)
        if ja or jb:
            ja_str = f"{ja:.2f}x" if ja else "—"
            jb_str = f"{jb:.2f}x" if jb else "—"
            lines.append(f"\n*Jitter (p95/p50): {name_a}={ja_str}, {name_b}={jb_str}*")

    # Cold start — rules
    lines.append("\n---\n")
    lines.append("# Cold Start\n")

    for label, filename in [("Cold Start — Rules", "cold-start-rules.json"), ("Cold Start — ML", "cold-start-ml.json")]:
        path_a = dir_a / filename
        path_b = dir_b / filename
        if path_a.exists() and path_b.exists():
            da = load(path_a)
            db = load(path_b)
            fa = extract_metrics(da)
            fb = extract_metrics(db)
            show_ml = "ML" in label
            lines.append(section(label, fa, fb, name_a, name_b, show_ml))
        else:
            lines.append(f"\n## {label}\n")
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
