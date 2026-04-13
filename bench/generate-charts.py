#!/usr/bin/env python3
"""Generate scorecard charts as base64-encoded SVGs for HTML embedding.

Usage:
    python3 bench/generate-charts.py --out results/charts/

Reads hardcoded benchmark data (cross-region medians or per-region values)
and produces SVG files + a combined base64 snippet file for HTML injection.
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


def chart_executive_summary(outdir):
    """Grouped bar: p50 latency across base suite tests (cross-region medians)."""
    tests = ["Warm Light\n(10 VUs)", "Warm Policy\n(10 VUs)", "Concurrency\nLadder (1-50)"]
    akamai = [6.2, 8.8, 10.1]
    fastly = [2.4, 6.1, 6.8]
    workers = [6.0, 5.8, 7.2]

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
    style_ax(ax, "Base Suite — Median Latency (p50)", "Latency (ms)")
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    ax.set_ylim(0, max(max(akamai), max(fastly), max(workers)) * 1.25)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_executive_summary.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


def chart_concurrency_scaling(outdir):
    """Line chart: p50 latency vs VU count showing the crossover point."""
    vus =     [10,   25,    500,   500,   2000]
    labels =  ["Policy\n10 VU", "Ladder\n1-50", "Ladder\n1-1K", "Soak\n500 VU", "Spike\n2K VU"]
    x_pos =   [10,   25,    300,   500,   2000]

    akamai =  [8.8,  10.1,  33.2,  52.4,  66.2]
    fastly =  [6.1,  6.8,   46.4,  114.9, 150.7]
    workers = [5.8,  6.6,   33.7,  58.2,  80.5]

    fig, ax = plt.subplots(figsize=(9, 5))

    ax.plot(x_pos, akamai, "o-", color=AKAMAI_COLOR, linewidth=2.5, markersize=7, label="Akamai", zorder=4)
    ax.plot(x_pos, fastly, "s-", color=FASTLY_COLOR, linewidth=2.5, markersize=7, label="Fastly", zorder=4)
    ax.plot(x_pos, workers, "^-", color=WORKERS_COLOR, linewidth=2.5, markersize=7, label="Workers", zorder=4)

    for i, (a, f, w) in enumerate(zip(akamai, fastly, workers)):
        xp = x_pos[i]
        offset = 4
        ax.annotate(f"{a:.0f}", (xp, a), textcoords="offset points", xytext=(0, offset),
                    fontsize=7.5, color=AKAMAI_COLOR, ha="center", fontweight="600")
        ax.annotate(f"{f:.0f}", (xp, f), textcoords="offset points", xytext=(0, offset),
                    fontsize=7.5, color=FASTLY_COLOR, ha="center", fontweight="600")
        ax.annotate(f"{w:.0f}", (xp, w), textcoords="offset points", xytext=(0, -12),
                    fontsize=7.5, color=WORKERS_COLOR, ha="center", fontweight="600")

    ax.axvspan(0, 60, alpha=0.04, color=WORKERS_COLOR, zorder=1)
    ax.axvspan(60, 2200, alpha=0.04, color=AKAMAI_COLOR, zorder=1)
    ax.text(30, 145, "Workers\nleads", fontsize=8, color=WORKERS_COLOR, ha="center", alpha=0.7, fontstyle="italic")
    ax.text(800, 145, "Akamai leads", fontsize=8, color=AKAMAI_COLOR, ha="center", alpha=0.7, fontstyle="italic")

    ax.set_xscale("log")
    ax.set_xticks(x_pos)
    ax.set_xticklabels(["10", "25", "300", "500", "2,000"])
    ax.xaxis.set_minor_formatter(ticker.NullFormatter())
    style_ax(ax, "Latency vs Concurrency — The Crossover (Chicago, p50)", "Latency (ms)", "Virtual Users (log scale)")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.set_ylim(0, 170)
    ax.set_xlim(7, 2500)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_concurrency_scaling.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


def chart_throughput_at_scale(outdir):
    """Grouped bar: RPS across extended suite tests (Chicago)."""
    tests = ["Full Ladder\n(1-1K VUs)", "Soak\n(500 VUs, 10m)", "Spike\n(0-2K VUs)"]
    akamai = [2132, 3029, 2824]
    fastly = [1579, 1918, 1834]
    workers = [2153, 2856, 2663]

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
    style_ax(ax, "Extended Suite — Throughput at Scale (Chicago)", "Requests / sec")
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    ax.set_ylim(0, max(max(akamai), max(fastly), max(workers)) * 1.2)
    fig.tight_layout()
    path = os.path.join(outdir, "chart_throughput_at_scale.svg")
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


def chart_cold_start(outdir):
    """Horizontal bar: cold start p50 by region."""
    regions = ["Singapore", "Frankfurt", "Chicago"]
    akamai = [48.4, 132.3, 45.2]
    fastly = [4.9, 7.1, 6.6]
    workers = [11.9, 11.5, 10.4]

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


def svg_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def main():
    parser = argparse.ArgumentParser(description="Generate scorecard charts")
    parser.add_argument("--out", default="results/charts/", help="Output directory")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    charts = [
        ("executive_summary", chart_executive_summary(args.out)),
        ("concurrency_scaling", chart_concurrency_scaling(args.out)),
        ("throughput_at_scale", chart_throughput_at_scale(args.out)),
        ("cold_start", chart_cold_start(args.out)),
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
