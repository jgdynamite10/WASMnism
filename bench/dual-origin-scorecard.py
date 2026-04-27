#!/usr/bin/env python3
"""Generate a dual-origin (Linode vs GCP) comparison scorecard.

Reads 7-run median base-suite data and extended-suite data from both
Linode and GCP runner origins, then produces a markdown scorecard
highlighting backbone bias between the two origins.

Usage:
    python3 bench/dual-origin-scorecard.py
"""

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "results"
OUTPUT = ROOT / "April_13th_dual_origin_comparison.md"

# ---------------------------------------------------------------------------
# Data path configuration
# ---------------------------------------------------------------------------

PLATFORMS = ["akamai", "fastly", "workers"]
PLATFORM_LABELS = {"akamai": "Akamai", "fastly": "Fastly", "workers": "Workers"}

LINODE_BASE = {
    "akamai":  ROOT / "akamai"  / "multiregion_20260413_062524",
    "fastly":  ROOT / "fastly"  / "multiregion_20260413_062524",
    "workers": ROOT / "workers" / "multiregion_20260413_062525",
}
LINODE_REGIONS = ["us-ord", "eu-central", "ap-south"]

GCP_BASE = {
    "akamai":  ROOT / "akamai"  / "multiregion_20260413_115156",
    "fastly":  ROOT / "fastly"  / "multiregion_20260413_125240",
    "workers": ROOT / "workers" / "multiregion_20260413_134725",
}
GCP_REGIONS = ["gcp-us-east", "gcp-eu-west", "gcp-ap-southeast"]

LINODE_EXT = {
    "akamai":  ROOT / "akamai"  / "multiregion_20260413_072415",
    "fastly":  ROOT / "fastly"  / "multiregion_20260413_072415",
    "workers": ROOT / "workers" / "multiregion_20260413_072416",
}

GCP_EXT = {
    "akamai":  ROOT / "akamai"  / "multiregion_20260413_144433",
    "fastly":  ROOT / "fastly"  / "multiregion_20260413_152159",
    "workers": ROOT / "workers" / "multiregion_20260413_155748",
}

REGION_LABELS = {
    "us-ord":             "Chicago (US)",
    "eu-central":         "Frankfurt (EU)",
    "ap-south":           "Singapore (APAC)",
    "gcp-us-east":        "N. Virginia (US)",
    "gcp-eu-west":        "Belgium (EU)",
    "gcp-ap-southeast":   "Singapore (APAC)",
}

REGION_PAIRS = [
    ("us-ord",      "gcp-us-east"),
    ("eu-central",  "gcp-eu-west"),
    ("ap-south",    "gcp-ap-southeast"),
]

PAIR_LABELS = {
    ("us-ord",      "gcp-us-east"):        "US (Chicago / N. Virginia)",
    ("eu-central",  "gcp-eu-west"):        "EU (Frankfurt / Belgium)",
    ("ap-south",    "gcp-ap-southeast"):   "APAC (Singapore)",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load(path):
    with open(path) as f:
        return json.load(f)


def fmt_ms(v):
    if v is None:
        return "—"
    if v >= 1000:
        return f"{v / 1000:.2f}s"
    return f"{v:.1f} ms"


def fmt_rps(v):
    if v is None:
        return "—"
    return f"{int(round(v)):,}/s"


def fmt_pct(v):
    if v is None:
        return "—"
    return f"{v * 100:.2f}%"


def fmt_delta(linode_v, gcp_v):
    if linode_v is None or gcp_v is None:
        return "—", "—"
    delta = gcp_v - linode_v
    sign = "+" if delta >= 0 else ""
    pct = ((gcp_v - linode_v) / linode_v * 100) if linode_v != 0 else 0
    return f"{sign}{delta:.1f} ms", f"{sign}{pct:.0f}%"


def bold_min(*vals):
    """Return list of fmt_ms strings; lowest non-None is bolded."""
    strs = [fmt_ms(v) for v in vals]
    valid = [(v, i) for i, v in enumerate(vals) if v is not None]
    if valid:
        _, best = min(valid, key=lambda x: x[0])
        strs[best] = f"**{strs[best]}**"
    return strs


def bold_max_rps(*vals):
    """Return list of fmt_rps strings; highest non-None is bolded."""
    strs = [fmt_rps(v) for v in vals]
    valid = [(v, i) for i, v in enumerate(vals) if v is not None]
    if valid:
        _, best = max(valid, key=lambda x: x[0])
        strs[best] = f"**{strs[best]}**"
    return strs


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------

def extract_metrics(data):
    m = data.get("metrics", {})
    dur = m.get("http_req_duration", {})
    iters = m.get("iterations", {})
    errs = m.get("errors", {})
    return {
        "p50": dur.get("med"),
        "p95": dur.get("p(95)"),
        "max": dur.get("max"),
        "rps": iters.get("rate"),
        "reqs": iters.get("count"),
        "err": errs.get("rate") if errs else None,
    }


def compute_7run_medians(run_dir, filename):
    """Median of each metric across run_1..run_7."""
    buckets = {}
    for n in range(1, 8):
        path = run_dir / f"run_{n}" / filename
        if not path.exists():
            continue
        metrics = extract_metrics(load(path))
        for k, v in metrics.items():
            if v is not None:
                buckets.setdefault(k, []).append(v)
    return {k: statistics.median(v) for k, v in buckets.items() if v}


def load_base_medians(base_dirs, region, filename):
    """Return {platform: {metric: value}} for a given region + test file."""
    out = {}
    for plat in PLATFORMS:
        run_dir = base_dirs[plat] / region / "7run"
        if run_dir.exists():
            out[plat] = compute_7run_medians(run_dir, filename)
        else:
            out[plat] = {}
    return out


def load_ext_single(ext_dirs, region, filename):
    """Return {platform: {metric: value}} from extended-suite single-run files."""
    out = {}
    for plat in PLATFORMS:
        path = ext_dirs[plat] / region / "full" / filename
        if path.exists():
            out[plat] = extract_metrics(load(path))
        else:
            out[plat] = {}
    return out


def load_cold_start(base_dirs, region):
    """Return {platform: {metric: value}} from cold-start-rules JSON."""
    out = {}
    for plat in PLATFORMS:
        pattern = base_dirs[plat] / region / f"cold-start-rules_{region}.json"
        if pattern.exists():
            data = load(pattern)
            dur = data.get("metrics", {}).get("http_req_duration", {})
            out[plat] = {"p50": dur.get("med"), "p95": dur.get("p(95)")}
        else:
            candidates = list((base_dirs[plat] / region).glob("cold-start-rules*.json"))
            if candidates:
                data = load(candidates[0])
                dur = data.get("metrics", {}).get("http_req_duration", {})
                out[plat] = {"p50": dur.get("med"), "p95": dur.get("p(95)")}
            else:
                out[plat] = {}
    return out


# ---------------------------------------------------------------------------
# Scorecard sections
# ---------------------------------------------------------------------------

def section_origin_bias_summary():
    lines = [
        "## 1. Origin Bias Summary — Warm Policy (p50)\n",
        "How does the runner origin change each platform's latency?\n",
        "| Platform | Linode US p50 | GCP US p50 | Delta | % Change | Verdict |",
        "|:---------|-------------:|----------:|---------:|--------:|:--------|",
    ]
    linode = load_base_medians(LINODE_BASE, "us-ord", "warm-policy.json")
    gcp = load_base_medians(GCP_BASE, "gcp-us-east", "warm-policy.json")

    for plat in PLATFORMS:
        lp50 = linode[plat].get("p50")
        gp50 = gcp[plat].get("p50")
        delta_s, pct_s = fmt_delta(lp50, gp50)

        l_str, g_str = bold_min(lp50, gp50)

        if lp50 is not None and gp50 is not None:
            if gp50 < lp50:
                verdict = "GCP faster"
            elif gp50 > lp50:
                verdict = "Linode faster"
            else:
                verdict = "Tied"
        else:
            verdict = "—"

        lines.append(
            f"| {PLATFORM_LABELS[plat]} | {l_str} | {g_str} | {delta_s} | {pct_s} | {verdict} |"
        )

    lines.append("")
    lines.append(
        "> **Key question:** Does Akamai get a private-backbone advantage from Linode "
        "(which Akamai owns) vs a neutral GCP origin?"
    )
    return "\n".join(lines)


def section_base_suite_comparison():
    lines = [
        "\n---\n",
        "## 2. Base Suite Comparison — US Regions\n",
        "Side-by-side Linode (Chicago) vs GCP (N. Virginia) for each base-suite test.\n",
    ]

    tests = [
        ("warm-light.json",         "Warm Light (10 VUs, 60s)"),
        ("warm-policy.json",        "Warm Policy (10 VUs, 60s)"),
        ("concurrency-ladder.json", "Concurrency Ladder (1→50 VUs)"),
    ]

    for filename, title in tests:
        linode = load_base_medians(LINODE_BASE, "us-ord", filename)
        gcp = load_base_medians(GCP_BASE, "gcp-us-east", filename)

        lines.append(f"### {title}\n")
        lines.append("| Platform | Linode p50 | GCP p50 | Delta | Linode RPS | GCP RPS |")
        lines.append("|:---------|----------:|-------:|---------:|----------:|-------:|")

        for plat in PLATFORMS:
            lp50 = linode[plat].get("p50")
            gp50 = gcp[plat].get("p50")
            lrps = linode[plat].get("rps")
            grps = gcp[plat].get("rps")
            delta_s, _ = fmt_delta(lp50, gp50)

            l_str, g_str = bold_min(lp50, gp50)
            lr_str, gr_str = bold_max_rps(lrps, grps)

            lines.append(
                f"| {PLATFORM_LABELS[plat]} | {l_str} | {g_str} | {delta_s} | {lr_str} | {gr_str} |"
            )
        lines.append("")

    return "\n".join(lines)


def section_extended_comparison():
    lines = [
        "\n---\n",
        "## 3. Extended Suite Comparison — US Regions\n",
        "High-concurrency and stress tests: Linode (Chicago) vs GCP (N. Virginia).\n",
    ]

    ext_tests = [
        ("concurrency-ladder-full.json", "Full Concurrency Ladder (1→1,000 VUs)"),
        ("soak-500vu.json",              "Soak Test (500 VUs, 10 min)"),
        ("spike.json",                   "Spike Test (0→2,000 VUs)"),
    ]

    for filename, title in ext_tests:
        linode = load_ext_single(LINODE_EXT, "us-ord", filename)
        gcp = load_ext_single(GCP_EXT, "gcp-us-east", filename)

        lines.append(f"### {title}\n")
        lines.append("| Platform | Linode p50 | GCP p50 | Delta | Linode RPS | GCP RPS | Linode Err | GCP Err |")
        lines.append("|:---------|----------:|-------:|---------:|----------:|-------:|----------:|-------:|")

        for plat in PLATFORMS:
            lp50 = linode[plat].get("p50")
            gp50 = gcp[plat].get("p50")
            lrps = linode[plat].get("rps")
            grps = gcp[plat].get("rps")
            lerr = linode[plat].get("err")
            gerr = gcp[plat].get("err")
            delta_s, _ = fmt_delta(lp50, gp50)

            l_str, g_str = bold_min(lp50, gp50)
            lr_str, gr_str = bold_max_rps(lrps, grps)

            lines.append(
                f"| {PLATFORM_LABELS[plat]} | {l_str} | {g_str} | {delta_s} "
                f"| {lr_str} | {gr_str} | {fmt_pct(lerr)} | {fmt_pct(gerr)} |"
            )
        lines.append("")

    return "\n".join(lines)


def section_cold_start():
    lines = [
        "\n---\n",
        "## 4. Cold Start Comparison\n",
        "Post-idle round-trip overhead (p50) from both origins, all region pairs.\n",
        "| Region | Platform | Linode p50 | GCP p50 | Delta |",
        "|:-------|:---------|----------:|-------:|---------:|",
    ]

    for li_reg, gcp_reg in REGION_PAIRS:
        label = PAIR_LABELS[(li_reg, gcp_reg)]
        linode = load_cold_start(LINODE_BASE, li_reg)
        gcp = load_cold_start(GCP_BASE, gcp_reg)

        for plat in PLATFORMS:
            lp50 = linode[plat].get("p50")
            gp50 = gcp[plat].get("p50")
            delta_s, _ = fmt_delta(lp50, gp50)
            l_str, g_str = bold_min(lp50, gp50)
            lines.append(
                f"| {label} | {PLATFORM_LABELS[plat]} | {l_str} | {g_str} | {delta_s} |"
            )

    lines.append("")
    lines.append("*Data source: `cold-start-rules_<region>.json` — 10 iterations, 120s idle.*")
    return "\n".join(lines)


def section_backbone_verdict():
    lines = [
        "\n---\n",
        "## 5. Backbone Bias Verdict\n",
    ]

    tests = [
        ("warm-light.json",         "Warm Light"),
        ("warm-policy.json",        "Warm Policy"),
        ("concurrency-ladder.json", "Concurrency Ladder"),
    ]

    akamai_deltas = []
    fastly_deltas = []
    workers_deltas = []

    lines.append("### Per-test origin delta (GCP p50 − Linode p50)\n")
    lines.append("| Test | Akamai Δ | Fastly Δ | Workers Δ |")
    lines.append("|:-----|--------:|--------:|----------:|")

    for filename, label in tests:
        linode = load_base_medians(LINODE_BASE, "us-ord", filename)
        gcp = load_base_medians(GCP_BASE, "gcp-us-east", filename)

        deltas = {}
        for plat in PLATFORMS:
            lp50 = linode[plat].get("p50")
            gp50 = gcp[plat].get("p50")
            if lp50 is not None and gp50 is not None:
                deltas[plat] = gp50 - lp50
            else:
                deltas[plat] = None

        if deltas["akamai"] is not None:
            akamai_deltas.append(deltas["akamai"])
        if deltas["fastly"] is not None:
            fastly_deltas.append(deltas["fastly"])
        if deltas["workers"] is not None:
            workers_deltas.append(deltas["workers"])

        def fmt_d(v):
            if v is None:
                return "—"
            sign = "+" if v >= 0 else ""
            return f"{sign}{v:.1f} ms"

        lines.append(f"| {label} | {fmt_d(deltas['akamai'])} | {fmt_d(deltas['fastly'])} | {fmt_d(deltas['workers'])} |")

    lines.append("")

    avg_akamai = statistics.mean(akamai_deltas) if akamai_deltas else None
    avg_fastly = statistics.mean(fastly_deltas) if fastly_deltas else None
    avg_workers = statistics.mean(workers_deltas) if workers_deltas else None

    lines.append("### Average origin delta across base suite\n")
    lines.append("| Platform | Avg Δ (GCP − Linode) | Interpretation |")
    lines.append("|:---------|--------------------:|:---------------|")

    for plat, avg in [("Akamai", avg_akamai), ("Fastly", avg_fastly), ("Workers", avg_workers)]:
        if avg is None:
            lines.append(f"| {plat} | — | No data |")
            continue
        sign = "+" if avg >= 0 else ""
        if avg > 0:
            interp = "faster from Linode"
        elif avg < 0:
            interp = "faster from GCP"
        else:
            interp = "no difference"
        lines.append(f"| {plat} | {sign}{avg:.1f} ms | {interp} |")

    lines.append("")

    # Narrative
    lines.append("### Analysis\n")

    if avg_akamai is not None and avg_fastly is not None and avg_workers is not None:
        akamai_advantage = avg_akamai - statistics.mean([avg_fastly, avg_workers])
        if avg_akamai > 0 and akamai_advantage > 1.0:
            lines.append(
                f"Akamai shows a **{avg_akamai:.1f} ms** advantage from Linode vs GCP "
                f"(avg across base suite), while Fastly and Workers average "
                f"{sign}{statistics.mean([avg_fastly, avg_workers]):.1f} ms. "
                f"The differential ({akamai_advantage:.1f} ms) suggests Akamai benefits "
                f"from private backbone routing when the origin is on Linode (Akamai-owned "
                f"infrastructure)."
            )
        elif avg_akamai > 0:
            lines.append(
                f"Akamai is {avg_akamai:.1f} ms faster from Linode, but the margin vs "
                f"other platforms ({akamai_advantage:.1f} ms) is small — backbone bias "
                f"is present but modest."
            )
        else:
            lines.append(
                f"Akamai is actually faster from GCP ({abs(avg_akamai):.1f} ms). "
                f"No backbone bias detected in this dataset."
            )

        lines.append("")
        lines.append(
            "**Why this matters:** Akamai acquired Linode in 2022. Traffic from Linode "
            "origins to Akamai Functions likely traverses Akamai's private backbone "
            "rather than the public internet, reducing hops and jitter. GCP origins "
            "must cross ISP boundaries to reach Akamai's edge, adding latency. "
            "Fastly and Cloudflare Workers have no such ownership relationship with "
            "either origin, so their delta reflects pure geographic distance differences."
        )
    else:
        lines.append("Insufficient data to compute backbone bias analysis.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    sections = []

    sections.append("# WASMnism Dual-Origin Scorecard — Backbone Bias Analysis\n")
    sections.append("| Field | Value |")
    sections.append("|:------|:------|")
    sections.append("| **Date** | 2026-04-13 |")
    sections.append("| **Linode Runner** | Chicago (Linode Dedicated 4 vCPU) |")
    sections.append("| **GCP Runner** | us-east1 (e2-standard-4) |")
    sections.append("| **Linode Regions** | Chicago (US), Frankfurt (EU), Singapore (APAC) |")
    sections.append("| **GCP Regions** | N. Virginia (US), Belgium (EU), Singapore (APAC) |")
    sections.append("| **Contract** | v3.4 — rules-only pipeline |")
    sections.append("| **Methodology** | 7-run medians · k6 `http_req_duration` |")
    sections.append("")
    sections.append(
        "> This scorecard compares identical benchmark payloads fired from two different "
        "origins — Linode (Akamai-owned) and GCP (neutral) — to quantify backbone routing bias."
    )

    sections.append("\n---\n")
    sections.append(section_origin_bias_summary())
    sections.append(section_base_suite_comparison())
    sections.append(section_extended_comparison())
    sections.append(section_cold_start())
    sections.append(section_backbone_verdict())

    # Footer
    sections.append("\n---\n")
    sections.append("## Methodology Notes\n")
    sections.append("- **Base suite**: 7 runs per test, median selected. Tests: warm-light, warm-policy, concurrency-ladder.")
    sections.append("- **Extended suite**: Single run per test. Tests: full ladder (1→1K VUs), soak (500 VUs, 10 min), spike (0→2K VUs).")
    sections.append("- **Cold start**: 10 iterations after 120s idle (measures CDN/networking connection re-establishment + compute startup).")
    sections.append("- **Client-side timing**: k6 `http_req_duration` is the source of truth (includes TLS, network, processing).")
    sections.append("- **Linode runner**: Linode Dedicated CPU (Chicago). Akamai owns Linode — traffic uses private backbone.")
    sections.append("- **GCP runner**: e2-standard-4 (us-east1). Neutral cloud — traffic traverses public internet to all platforms.")
    sections.append("")

    output_text = "\n".join(sections) + "\n"

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(output_text)
    print(f"Scorecard written to {OUTPUT}")
    print(f"  {len(output_text)} bytes, {output_text.count(chr(10))} lines")


if __name__ == "__main__":
    main()
