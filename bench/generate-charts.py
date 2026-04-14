#!/usr/bin/env python3
"""Generate scorecard charts as base64-encoded SVGs for HTML embedding.

Usage:
    python3 bench/generate-charts.py --out results/charts/
    python3 bench/generate-charts.py --out results/charts-gcp/ --origin gcp

Reads benchmark data for the specified origin (linode or gcp) and produces
SVG files + a combined base64 snippet file for HTML injection.
"""
import argparse
import base64
import io
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

AKAMAI_COLOR = "#0072CE"
FASTLY_COLOR = "#FF282D"
WORKERS_COLOR = "#F6821F"
GRID_COLOR = "#e5e7eb"
BG_COLOR = "#ffffff"
TEXT_COLOR = "#1a1a2e"
MUTED_COLOR = "#6b7280"

PLATFORMS = ["Akamai", "Fastly", "Workers"]
COLORS = [AKAMAI_COLOR, FASTLY_COLOR, WORKERS_COLOR]

# --- Per-origin benchmark data ---

DATA = {
    "linode": {
        "region_label": "Chicago",
        "exec_summary": {
            "akamai": [6.2, 8.8, 10.1],
            "fastly": [2.4, 6.1, 6.8],
            "workers": [6.0, 5.8, 7.2],
        },
        "cold_start": {
            "regions": ["Singapore", "Frankfurt", "Chicago"],
            "akamai": [48.4, 132.3, 45.2],
            "fastly": [4.9, 7.1, 6.6],
            "workers": [11.9, 11.5, 10.4],
        },
        "concurrency": {
            "x_pos": [10, 25, 300, 500, 2000],
            "x_labels": ["10", "25", "300", "500", "2,000"],
            "akamai": [8.8, 10.1, 33.2, 52.4, 66.2],
            "fastly": [6.1, 6.8, 46.4, 114.9, 150.7],
            "workers": [5.8, 6.6, 33.7, 58.2, 80.5],
            "crossover_low_color": WORKERS_COLOR,
            "crossover_high_color": AKAMAI_COLOR,
            "crossover_low_label": "Workers\nleads",
            "crossover_high_label": "Akamai leads",
            "crossover_x": 60,
        },
        "throughput": {
            "akamai": [2132, 3029, 2824],
            "fastly": [1579, 1918, 1834],
            "workers": [2153, 2856, 2663],
        },
    },
    "gcp": {
        "region_label": "Cross-region",
        "exec_summary": {
            "akamai": [9.0, 11.5, 11.9],
            "fastly": [3.1, 7.0, 7.2],
            "workers": [10.4, 11.0, 10.7],
        },
        "cold_start": {
            "regions": ["Singapore", "Belgium", "N. Virginia"],
            "akamai": [144.2, 65.6, 90.9],
            "fastly": [5.8, 7.6, 10.8],
            "workers": [8.8, 10.5, 21.6],
        },
        "concurrency": {
            "x_pos": [10, 25, 300, 500, 2000],
            "x_labels": ["10", "25", "300", "500", "2,000"],
            "akamai": [11.5, 11.9, 40.8, 85.4, 91.6],
            "fastly": [7.0, 7.2, 34.4, 60.2, 69.7],
            "workers": [11.0, 10.7, 38.0, 163.2, 193.3],
            "crossover_low_color": FASTLY_COLOR,
            "crossover_high_color": FASTLY_COLOR,
            "crossover_low_label": "Fastly\nleads",
            "crossover_high_label": "Fastly leads",
            "crossover_x": 60,
        },
        "throughput": {
            "akamai": [2859, 4690, 4638],
            "fastly": [3198, 4967, 4494],
            "workers": [854, 1196, 1067],
        },
    },
}


def style_ax(ax, title, ylabel, xlabel=None):
    ax.set_title(title, fontsize=13, fontweight="600", color=TEXT_COLOR, pad=12)
    ax.set_ylabel(ylabel, fontsize=10, color=MUTED_COLOR)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=10, color=MUTED_COLOR)
    ax.tick_params(colors=MUTED_COLOR, labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID_COLOR)
    ax.spines["bottom"].set_color(GRID_COLOR)
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_facecolor(BG_COLOR)


def chart_executive_summary(outdir, origin):
    """Grouped bar: p50 latency across base suite tests (cross-region medians)."""
    d = DATA[origin]["exec_summary"]
    region = DATA[origin]["region_label"]
    tests = ["Warm Light\n(10 VUs)", "Warm Policy\n(10 VUs)", "Concurrency\nLadder (1-50)"]
    akamai, fastly, workers = d["akamai"], d["fastly"], d["workers"]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = range(len(tests))
    w = 0.25
    bars_a = ax.bar([i - w for i in x], akamai, w, color=AKAMAI_COLOR, label="Akamai", zorder=3)
    bars_f = ax.bar(x, fastly, w, color=FASTLY_COLOR, label="Fastly", zorder=3)
    bars_w = ax.bar([i + w for i in x], workers, w, color=WORKERS_COLOR, label="Workers", zorder=3)

    for bars in [bars_a, bars_f, bars_w]:
        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h + 0.2, f"{h:.1f}",
                    ha="center", va="bottom", fontsize=8, color=TEXT_COLOR, fontweight="500")

    ax.set_xticks(x)
    ax.set_xticklabels(tests)
    style_ax(ax, f"Base Suite — Median Latency (p50, {region})", "Latency (ms)")
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    ax.set_ylim(0, max(max(akamai), max(fastly), max(workers)) * 1.25)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_executive_summary.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


def chart_concurrency_scaling(outdir, origin):
    """Line chart: p50 latency vs VU count showing the crossover point."""
    d = DATA[origin]["concurrency"]
    region = DATA[origin]["region_label"]
    x_pos = d["x_pos"]
    akamai, fastly, workers = d["akamai"], d["fastly"], d["workers"]

    fig, ax = plt.subplots(figsize=(9, 5))

    ax.plot(x_pos, akamai, "o-", color=AKAMAI_COLOR, linewidth=2.5, markersize=7, label="Akamai", zorder=4)
    ax.plot(x_pos, fastly, "s-", color=FASTLY_COLOR, linewidth=2.5, markersize=7, label="Fastly", zorder=4)
    ax.plot(x_pos, workers, "^-", color=WORKERS_COLOR, linewidth=2.5, markersize=7, label="Workers", zorder=4)

    y_max = max(max(akamai), max(fastly), max(workers)) * 1.15
    for i, (a, f, w_val) in enumerate(zip(akamai, fastly, workers)):
        xp = x_pos[i]
        offset = 4
        ax.annotate(f"{a:.0f}", (xp, a), textcoords="offset points", xytext=(0, offset),
                    fontsize=7.5, color=AKAMAI_COLOR, ha="center", fontweight="600")
        ax.annotate(f"{f:.0f}", (xp, f), textcoords="offset points", xytext=(0, offset),
                    fontsize=7.5, color=FASTLY_COLOR, ha="center", fontweight="600")
        ax.annotate(f"{w_val:.0f}", (xp, w_val), textcoords="offset points", xytext=(0, -12),
                    fontsize=7.5, color=WORKERS_COLOR, ha="center", fontweight="600")

    cx = d["crossover_x"]
    ax.axvspan(0, cx, alpha=0.04, color=d["crossover_low_color"], zorder=1)
    ax.axvspan(cx, 2200, alpha=0.04, color=d["crossover_high_color"], zorder=1)
    ax.text(30, y_max * 0.88, d["crossover_low_label"], fontsize=8,
            color=d["crossover_low_color"], ha="center", alpha=0.7, fontstyle="italic")
    ax.text(800, y_max * 0.88, d["crossover_high_label"], fontsize=8,
            color=d["crossover_high_color"], ha="center", alpha=0.7, fontstyle="italic")

    ax.set_xscale("log")
    ax.set_xticks(x_pos)
    ax.set_xticklabels(d["x_labels"])
    ax.xaxis.set_minor_formatter(ticker.NullFormatter())
    style_ax(ax, f"Latency vs Concurrency — The Crossover ({region}, p50)", "Latency (ms)", "Virtual Users (log scale)")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.set_ylim(0, y_max)
    ax.set_xlim(7, 2500)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_concurrency_scaling.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


def chart_throughput_at_scale(outdir, origin):
    """Grouped bar: RPS across extended suite tests."""
    d = DATA[origin]["throughput"]
    region = DATA[origin]["region_label"]
    tests = ["Full Ladder\n(1-1K VUs)", "Soak\n(500 VUs, 10m)", "Spike\n(0-2K VUs)"]
    akamai, fastly, workers = d["akamai"], d["fastly"], d["workers"]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = range(len(tests))
    w = 0.25
    bars_a = ax.bar([i - w for i in x], akamai, w, color=AKAMAI_COLOR, label="Akamai", zorder=3)
    bars_f = ax.bar(x, fastly, w, color=FASTLY_COLOR, label="Fastly", zorder=3)
    bars_w = ax.bar([i + w for i in x], workers, w, color=WORKERS_COLOR, label="Workers", zorder=3)

    for bars in [bars_a, bars_f, bars_w]:
        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h + 30, f"{h:,.0f}",
                    ha="center", va="bottom", fontsize=8, color=TEXT_COLOR, fontweight="500")

    ax.set_xticks(x)
    ax.set_xticklabels(tests)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    style_ax(ax, f"Extended Suite — Throughput at Scale ({region})", "Requests / sec")
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    ax.set_ylim(0, max(max(akamai), max(fastly), max(workers)) * 1.2)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_throughput_at_scale.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


def chart_cold_start(outdir, origin):
    """Horizontal bar: cold start p50 by region."""
    d = DATA[origin]["cold_start"]
    regions = d["regions"]
    akamai, fastly, workers = d["akamai"], d["fastly"], d["workers"]

    fig, ax = plt.subplots(figsize=(8, 3.5))
    y = range(len(regions))
    h = 0.25
    ax.barh([i + h for i in y], akamai, h, color=AKAMAI_COLOR, label="Akamai", zorder=3)
    ax.barh(y, fastly, h, color=FASTLY_COLOR, label="Fastly", zorder=3)
    ax.barh([i - h for i in y], workers, h, color=WORKERS_COLOR, label="Workers", zorder=3)

    for i in y:
        ax.text(akamai[i] + 2, i + h, f"{akamai[i]:.0f} ms", va="center", fontsize=8, color=AKAMAI_COLOR, fontweight="500")
        ax.text(fastly[i] + 2, i, f"{fastly[i]:.0f} ms", va="center", fontsize=8, color=FASTLY_COLOR, fontweight="500")
        ax.text(workers[i] + 2, i - h, f"{workers[i]:.0f} ms", va="center", fontsize=8, color=WORKERS_COLOR, fontweight="500")

    ax.set_yticks(y)
    ax.set_yticklabels(regions)
    ax.invert_yaxis()
    style_ax(ax, "Cold Start Latency (p50)", "")
    ax.set_xlabel("Latency (ms)", fontsize=10, color=MUTED_COLOR)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.xaxis.grid(True, color=GRID_COLOR, linewidth=0.7)
    ax.yaxis.grid(False)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_cold_start.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


# --- Comparison charts (Linode vs GCP side-by-side) ---

def chart_comparison_executive_summary(outdir):
    """Side-by-side grouped bar: Linode vs GCP p50 per platform across base suite."""
    li = DATA["linode"]["exec_summary"]
    gc = DATA["gcp"]["exec_summary"]
    tests = ["Warm Light", "Warm Policy", "Conc. Ladder"]
    platforms = PLATFORMS
    colors = COLORS

    fig, axes = plt.subplots(1, 3, figsize=(12, 4.5), sharey=True)
    for col, (plat, color) in enumerate(zip(platforms, colors)):
        ax = axes[col]
        li_vals = [li[plat.lower()][i] for i in range(3)]
        gc_vals = [gc[plat.lower()][i] for i in range(3)]
        x = range(len(tests))
        w = 0.32
        bars_l = ax.bar([i - w/2 for i in x], li_vals, w, color=color, alpha=0.85, label="Linode", zorder=3)
        bars_g = ax.bar([i + w/2 for i in x], gc_vals, w, color=color, alpha=0.45, label="GCP", zorder=3)
        for bars in [bars_l, bars_g]:
            for bar in bars:
                h = bar.get_height()
                ax.text(bar.get_x() + bar.get_width() / 2, h + 0.15, f"{h:.1f}",
                        ha="center", va="bottom", fontsize=7, color=TEXT_COLOR, fontweight="500")
        ax.set_xticks(x)
        ax.set_xticklabels(tests, fontsize=8)
        ax.set_title(plat, fontsize=11, fontweight="600", color=color)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(GRID_COLOR)
        ax.spines["bottom"].set_color(GRID_COLOR)
        ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.7)
        ax.set_axisbelow(True)
        ax.set_facecolor(BG_COLOR)
        ax.tick_params(colors=MUTED_COLOR, labelsize=8)
        if col == 0:
            ax.set_ylabel("Latency (ms)", fontsize=9, color=MUTED_COLOR)
            ax.legend(frameon=False, fontsize=8, loc="upper left")

    fig.suptitle("Base Suite p50 — Linode (solid) vs GCP (light)", fontsize=13,
                 fontweight="600", color=TEXT_COLOR, y=1.02)
    all_vals = [v for d in [li, gc] for k in d for v in d[k]]
    for ax in axes:
        ax.set_ylim(0, max(all_vals) * 1.25)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_executive_summary.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


def chart_comparison_cold_start(outdir):
    """Grouped horizontal bar: cold start p50 from both origins, per platform."""
    li = DATA["linode"]["cold_start"]
    gc = DATA["gcp"]["cold_start"]
    region_pairs = ["US", "EU", "APAC"]

    li_akamai = [li["akamai"][2], li["akamai"][1], li["akamai"][0]]
    gc_akamai = [gc["akamai"][2], gc["akamai"][1], gc["akamai"][0]]
    li_fastly = [li["fastly"][2], li["fastly"][1], li["fastly"][0]]
    gc_fastly = [gc["fastly"][2], gc["fastly"][1], gc["fastly"][0]]
    li_workers = [li["workers"][2], li["workers"][1], li["workers"][0]]
    gc_workers = [gc["workers"][2], gc["workers"][1], gc["workers"][0]]

    fig, axes = plt.subplots(1, 3, figsize=(14, 3.5), sharey=True)
    h = 0.3
    for col, (plat, color, li_d, gc_d) in enumerate([
        ("Akamai", AKAMAI_COLOR, li_akamai, gc_akamai),
        ("Fastly", FASTLY_COLOR, li_fastly, gc_fastly),
        ("Workers", WORKERS_COLOR, li_workers, gc_workers),
    ]):
        ax = axes[col]
        y = range(len(region_pairs))
        ax.barh([i - h/2 for i in y], li_d, h, color=color, alpha=0.85, label="Linode", zorder=3)
        ax.barh([i + h/2 for i in y], gc_d, h, color=color, alpha=0.45, label="GCP", zorder=3)
        for i in y:
            ax.text(li_d[i] + 1, i - h/2, f"{li_d[i]:.0f}", va="center", fontsize=7, color=color, fontweight="600")
            ax.text(gc_d[i] + 1, i + h/2, f"{gc_d[i]:.0f}", va="center", fontsize=7, color=color, fontweight="500", alpha=0.9)
        ax.set_yticks(y)
        ax.set_yticklabels(region_pairs, fontsize=9)
        ax.invert_yaxis()
        ax.set_title(plat, fontsize=11, fontweight="600", color=color)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(GRID_COLOR)
        ax.spines["bottom"].set_color(GRID_COLOR)
        ax.xaxis.grid(True, color=GRID_COLOR, linewidth=0.7)
        ax.yaxis.grid(False)
        ax.set_axisbelow(True)
        ax.set_facecolor(BG_COLOR)
        ax.tick_params(colors=MUTED_COLOR, labelsize=8)
        if col == 0:
            ax.legend(frameon=False, fontsize=8, loc="lower right")
        if col == 1:
            ax.set_xlabel("Latency (ms)", fontsize=9, color=MUTED_COLOR)

    fig.suptitle("Cold Start p50 — Linode (solid) vs GCP (light)", fontsize=13,
                 fontweight="600", color=TEXT_COLOR, y=1.02)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_cold_start.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


def chart_comparison_concurrency_scaling(outdir):
    """Dual-line: p50 vs VU count from both origins, showing leader reversal."""
    li = DATA["linode"]["concurrency"]
    gc = DATA["gcp"]["concurrency"]
    x_pos = li["x_pos"]

    fig, ax = plt.subplots(figsize=(10, 5.5))

    for plat, color, marker in [("akamai", AKAMAI_COLOR, "o"), ("fastly", FASTLY_COLOR, "s"), ("workers", WORKERS_COLOR, "^")]:
        label = plat.capitalize()
        ax.plot(x_pos, li[plat], f"{marker}-", color=color, linewidth=2.5, markersize=7,
                label=f"{label} (Linode)", zorder=4)
        ax.plot(x_pos, gc[plat], f"{marker}--", color=color, linewidth=2, markersize=6,
                alpha=0.7, label=f"{label} (GCP)", zorder=3)

    for plat, color in [("akamai", AKAMAI_COLOR), ("fastly", FASTLY_COLOR), ("workers", WORKERS_COLOR)]:
        for i, xp in enumerate(x_pos):
            ax.annotate(f"{li[plat][i]:.0f}", (xp, li[plat][i]), textcoords="offset points",
                        xytext=(0, 5), fontsize=6.5, color=color, ha="center", fontweight="600")
            ax.annotate(f"{gc[plat][i]:.0f}", (xp, gc[plat][i]), textcoords="offset points",
                        xytext=(0, -10), fontsize=6.5, color=color, ha="center", fontweight="500", alpha=0.8)

    ax.set_xscale("log")
    ax.set_xticks(x_pos)
    ax.set_xticklabels(li["x_labels"])
    ax.xaxis.set_minor_formatter(ticker.NullFormatter())
    y_max = max(max(gc["workers"]), max(gc["akamai"]), max(gc["fastly"])) * 1.15
    style_ax(ax, "Latency vs Concurrency — Linode (solid) vs GCP (dashed)", "Latency (ms)", "Virtual Users (log scale)")
    ax.legend(frameon=False, fontsize=8, loc="upper left", ncol=2)
    ax.set_ylim(0, y_max)
    ax.set_xlim(7, 2500)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_concurrency_scaling.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


def chart_comparison_throughput(outdir):
    """Grouped bar: RPS from both origins per extended suite test (US region)."""
    li = DATA["linode"]["throughput"]
    gc = DATA["gcp"]["throughput"]
    tests = ["Full Ladder\n(1-1K VUs)", "Soak\n(500 VUs, 10m)", "Spike\n(0-2K VUs)"]

    fig, ax = plt.subplots(figsize=(10, 5))
    n_groups = len(tests)
    n_bars = 6
    w = 0.12
    offsets = [-2.5*w, -1.5*w, -0.5*w, 0.5*w, 1.5*w, 2.5*w]
    bar_data = [
        (li["akamai"], AKAMAI_COLOR, 0.85, "", "Akamai (Linode)"),
        (gc["akamai"], AKAMAI_COLOR, 0.45, "", "Akamai (GCP)"),
        (li["fastly"], FASTLY_COLOR, 0.85, "", "Fastly (Linode)"),
        (gc["fastly"], FASTLY_COLOR, 0.45, "", "Fastly (GCP)"),
        (li["workers"], WORKERS_COLOR, 0.85, "", "Workers (Linode)"),
        (gc["workers"], WORKERS_COLOR, 0.45, "", "Workers (GCP)"),
    ]

    for idx, (vals, color, alpha, _unused, label) in enumerate(bar_data):
        positions = [i + offsets[idx] for i in range(n_groups)]
        bars = ax.bar(positions, vals, w, color=color, alpha=alpha,
                      label=label, zorder=3)
        for bar in bars:
            h_val = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h_val + 40,
                    f"{h_val:,.0f}", ha="center", va="bottom", fontsize=6,
                    color=TEXT_COLOR, fontweight="500", rotation=45)

    ax.set_xticks(range(n_groups))
    ax.set_xticklabels(tests, fontsize=9)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    style_ax(ax, "Extended Suite Throughput — Linode (solid) vs GCP (light)", "Requests / sec")
    ax.legend(frameon=False, fontsize=7.5, loc="upper right", ncol=3)
    all_vals = [v for d in [li, gc] for k in d for v in d[k]]
    ax.set_ylim(0, max(all_vals) * 1.25)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_throughput_at_scale.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


# --- Cost analysis charts ---

COST_DATA = {
    "platforms": ["Fastly", "Workers", "Akamai"],
    "colors": [FASTLY_COLOR, WORKERS_COLOR, AKAMAI_COLOR],
    "requests": [54_845_054, 40_037_424, 44_948_245],
    "period": "Apr 7-13",
    # Workers costs are ESTIMATES from GraphQL API (40M req).
    # Actual CF billing (current cycle, 24.68M req): $9.50 total.
    "cost_with_free": [80.89, 14.01, 0.00],
    "cost_no_free": [96.40, 17.47, 0.00],
    "per_1m_req": [1.76, 0.44, 0.00],
    "workers_actual_billing": {"requests": 24_680_000, "total": 9.50},
    "fastly_breakdown": {
        "labels": ["CDN Requests\n($1.00/1M)", "Compute Requests\n($0.50/1M)",
                   "Compute vCPU\n($0.05/1M ms)", "CDN Bandwidth\n($0.12/GB)"],
        "values": [54.85, 27.42, 9.63, 4.50],
        "colors": ["#c0392b", "#e74c3c", "#f39c12", "#3498db"],
    },
    "daily_requests": {
        "dates": ["Apr 7", "Apr 8", "Apr 9", "Apr 10", "Apr 11", "Apr 12", "Apr 13"],
        "fastly": [0, 1, 171_931, 6_077_872, 17, 4_101_088, 44_494_145],
        "workers": [6_017_330, 14, 183_745, 3_716_143, 6, 5_438_453, 24_681_733],
        "akamai": [1, 0, 119, 5_877_657, 0, 4_368_106, 34_702_362],
    },
    "monthly_extrapolation": {
        "scale": 30 / 7,
        "projected_requests": [235_050_231, 171_589_246, 192_635_336],
        "projected_cost": [413.13, 74.89, 0.00],
    },
}


def chart_cost_comparison(outdir):
    """Side-by-side bars: total cost and $/1M requests for each platform."""
    d = COST_DATA
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))

    x = range(len(d["platforms"]))
    w = 0.5
    bars1 = ax1.bar(x, d["cost_no_free"], w, color=d["colors"], alpha=0.85, zorder=3)
    for i, (bar, val) in enumerate(zip(bars1, d["cost_no_free"])):
        label = f"${val:.2f}" if val > 0 else "$0 (preview)"
        suffix = " (est.)" if d["platforms"][i] == "Workers" else ""
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                 label + suffix, ha="center", va="bottom", fontsize=9, color=TEXT_COLOR, fontweight="600")
    ax1.set_xticks(x)
    ax1.set_xticklabels(d["platforms"])
    style_ax(ax1, "Total Cost (without free tier)", "USD")
    ax1.set_ylim(0, max(d["cost_no_free"]) * 1.3)

    bars2 = ax2.bar(x, d["per_1m_req"], w, color=d["colors"], alpha=0.85, zorder=3)
    for bar, val in zip(bars2, d["per_1m_req"]):
        label = f"${val:.2f}" if val > 0 else "$0"
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                 label, ha="center", va="bottom", fontsize=9, color=TEXT_COLOR, fontweight="600")
    ax2.set_xticks(x)
    ax2.set_xticklabels(d["platforms"])
    style_ax(ax2, "Unit Cost ($/1M requests)", "USD per 1M requests")
    ax2.set_ylim(0, max(d["per_1m_req"]) * 1.3)

    fig.suptitle(f"Tier 1 Cost Comparison — {d['period']} (all platforms)", fontsize=13,
                 fontweight="600", color=TEXT_COLOR, y=1.02)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_executive_summary.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


def chart_cost_breakdown(outdir):
    """Horizontal stacked bar: Fastly cost components showing CDN requests dominate."""
    d = COST_DATA["fastly_breakdown"]
    fig, ax = plt.subplots(figsize=(9, 3.5))

    left = 0
    for label, val, color in zip(d["labels"], d["values"], d["colors"]):
        bar = ax.barh(0, val, left=left, color=color, height=0.5, label=label, zorder=3)
        if val > 1:
            ax.text(left + val / 2, 0, f"${val:.2f}\n({val/sum(d['values'])*100:.0f}%)",
                    ha="center", va="center", fontsize=8, color="white", fontweight="600")
        left += val

    ax.set_yticks([0])
    ax.set_yticklabels(["Fastly\nCompute"], fontsize=10, fontweight="600")
    ax.set_xlim(0, sum(d["values"]) * 1.15)
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"${v:.0f}"))
    style_ax(ax, "Fastly Cost Decomposition — The CDN Double-Billing", "")
    ax.set_xlabel("USD (without free tier)", fontsize=10, color=MUTED_COLOR)
    ax.legend(frameon=False, fontsize=8, loc="upper right", ncol=2)
    ax.yaxis.grid(False)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_cold_start.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


def chart_daily_usage(outdir):
    """Multi-line: daily request volume across all 3 platforms during benchmark period."""
    d = COST_DATA["daily_requests"]
    dates = d["dates"]
    x = range(len(dates))

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(x, [v / 1e6 for v in d["fastly"]], "s-", color=FASTLY_COLOR,
            linewidth=2.5, markersize=8, label="Fastly", zorder=5)
    ax.plot(x, [v / 1e6 for v in d["workers"]], "^-", color=WORKERS_COLOR,
            linewidth=2.5, markersize=8, label="Workers", zorder=4)
    ax.plot(x, [v / 1e6 for v in d["akamai"]], "o-", color=AKAMAI_COLOR,
            linewidth=2.5, markersize=8, label="Akamai", zorder=3)

    for i, f_val in enumerate(d["fastly"]):
        if f_val > 500_000:
            ax.annotate(f"{f_val/1e6:.1f}M", (i, f_val/1e6), textcoords="offset points",
                        xytext=(0, 10), fontsize=7, color=FASTLY_COLOR, ha="center", fontweight="600")
    for i, w_val in enumerate(d["workers"]):
        if w_val > 500_000:
            ax.annotate(f"{w_val/1e6:.1f}M", (i, w_val/1e6), textcoords="offset points",
                        xytext=(0, -14), fontsize=7, color=WORKERS_COLOR, ha="center", fontweight="600")
    for i, a_val in enumerate(d["akamai"]):
        if a_val > 500_000:
            offset_y = 10 if d["fastly"][i] < a_val * 0.8 else -14
            ax.annotate(f"{a_val/1e6:.1f}M", (i, a_val/1e6), textcoords="offset points",
                        xytext=(0, offset_y), fontsize=7, color=AKAMAI_COLOR, ha="center", fontweight="600")

    ax.set_xticks(x)
    ax.set_xticklabels(dates, fontsize=9)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"{v:.0f}M"))
    style_ax(ax, f"Daily Request Volume — {COST_DATA['period']} (all platforms)", "Requests (millions)")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    all_daily = list(d["fastly"]) + list(d["workers"]) + list(d["akamai"])
    ax.set_ylim(0, max(v / 1e6 for v in all_daily) * 1.25)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_concurrency_scaling.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


def chart_monthly_extrapolation(outdir):
    """Grouped bars: 7-day actual vs 30-day projected requests and costs."""
    d = COST_DATA
    ext = d["monthly_extrapolation"]
    platforms = d["platforms"]
    colors = d["colors"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))
    x = range(len(platforms))
    w = 0.35

    actual_m = [r / 1e6 for r in d["requests"]]
    projected_m = [r / 1e6 for r in ext["projected_requests"]]
    b1 = ax1.bar([i - w/2 for i in x], actual_m, w, color=colors, alpha=0.85, label="7-day actual", zorder=3)
    b2 = ax1.bar([i + w/2 for i in x], projected_m, w, color=colors, alpha=0.45, label="30-day projected", zorder=3)
    for bar, val in zip(b1, actual_m):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                 f"{val:.0f}M", ha="center", va="bottom", fontsize=7, fontweight="600", color=TEXT_COLOR)
    for bar, val in zip(b2, projected_m):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                 f"{val:.0f}M", ha="center", va="bottom", fontsize=7, fontweight="600", color=MUTED_COLOR)
    ax1.set_xticks(x)
    ax1.set_xticklabels(platforms)
    ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"{v:.0f}M"))
    style_ax(ax1, "Request Volume", "Requests (millions)")
    ax1.set_ylim(0, max(projected_m) * 1.25)
    ax1.legend(frameon=False, fontsize=8, loc="upper left")

    actual_cost = d["cost_no_free"]
    projected_cost = ext["projected_cost"]
    b3 = ax2.bar([i - w/2 for i in x], actual_cost, w, color=colors, alpha=0.85, label="7-day actual", zorder=3)
    b4 = ax2.bar([i + w/2 for i in x], projected_cost, w, color=colors, alpha=0.45, label="30-day projected", zorder=3)
    for bar, val in zip(b3, actual_cost):
        label = f"${val:.2f}" if val > 0 else "$0"
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                 label, ha="center", va="bottom", fontsize=7, fontweight="600", color=TEXT_COLOR)
    for bar, val in zip(b4, projected_cost):
        label = f"${val:.0f}" if val > 0 else "$0"
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                 label, ha="center", va="bottom", fontsize=7, fontweight="600", color=MUTED_COLOR)
    ax2.set_xticks(x)
    ax2.set_xticklabels(platforms)
    style_ax(ax2, "Cost (without free tier)", "USD")
    ax2.set_ylim(0, max(projected_cost) * 1.25)
    ax2.legend(frameon=False, fontsize=8, loc="upper left")

    fig.suptitle("Monthly Extrapolation — 7-day actuals \u00d7 (30/7)", fontsize=13,
                 fontweight="600", color=TEXT_COLOR, y=1.02)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_throughput_at_scale.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


def svg_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def main():
    parser = argparse.ArgumentParser(description="Generate scorecard charts")
    parser.add_argument("--out", default="results/charts/", help="Output directory")
    parser.add_argument("--origin", choices=["linode", "gcp", "comparison", "cost"], default="linode",
                        help="Runner origin dataset to use (default: linode)")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    if args.origin == "cost":
        charts = [
            ("executive_summary", chart_cost_comparison(args.out)),
            ("concurrency_scaling", chart_daily_usage(args.out)),
            ("cold_start", chart_cost_breakdown(args.out)),
            ("throughput_at_scale", chart_monthly_extrapolation(args.out)),
        ]
    elif args.origin == "comparison":
        charts = [
            ("executive_summary", chart_comparison_executive_summary(args.out)),
            ("concurrency_scaling", chart_comparison_concurrency_scaling(args.out)),
            ("throughput_at_scale", chart_comparison_throughput(args.out)),
            ("cold_start", chart_comparison_cold_start(args.out)),
        ]
    else:
        charts = [
            ("executive_summary", chart_executive_summary(args.out, args.origin)),
            ("concurrency_scaling", chart_concurrency_scaling(args.out, args.origin)),
            ("throughput_at_scale", chart_throughput_at_scale(args.out, args.origin)),
            ("cold_start", chart_cold_start(args.out, args.origin)),
        ]

    b64_path = os.path.join(args.out, "charts_base64.txt")
    with open(b64_path, "w") as f:
        for name, path in charts:
            b64 = svg_to_base64(path)
            f.write(f"<!-- {name} -->\n")
            f.write(f'<img src="data:image/svg+xml;base64,{b64}" alt="{name}" style="width:100%;max-width:900px;margin:1rem auto;display:block;">\n\n')

    print(f"Generated {len(charts)} charts in {args.out}")
    for name, path in charts:
        print(f"  {name}: {path}")
    print(f"Base64 snippets: {b64_path}")


if __name__ == "__main__":
    main()
