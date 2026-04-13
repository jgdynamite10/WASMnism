#!/usr/bin/env python3
"""Inject base64-encoded SVG charts into the HTML scorecard.

Usage:
    python3 bench/inject-charts.py \
        --html results/April_13th_scorecard_origin_Linode_Base_extended.html \
        --charts results/charts/
"""
import argparse
import base64
import os
import re


def svg_to_img_tag(svg_path, alt, max_width="900px"):
    with open(svg_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return (
        f'<img src="data:image/svg+xml;base64,{b64}" '
        f'alt="{alt}" '
        f'style="width:100%;max-width:{max_width};margin:1.5rem auto;display:block;">'
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True)
    parser.add_argument("--charts", default="results/charts/")
    args = parser.parse_args()

    with open(args.html, "r") as f:
        html = f.read()

    chart_dir = args.charts

    exec_chart = svg_to_img_tag(
        os.path.join(chart_dir, "chart_executive_summary.svg"),
        "Base Suite Latency Comparison"
    )
    scaling_chart = svg_to_img_tag(
        os.path.join(chart_dir, "chart_concurrency_scaling.svg"),
        "Concurrency Scaling Crossover"
    )
    throughput_chart = svg_to_img_tag(
        os.path.join(chart_dir, "chart_throughput_at_scale.svg"),
        "Extended Suite Throughput"
    )
    cold_chart = svg_to_img_tag(
        os.path.join(chart_dir, "chart_cold_start.svg"),
        "Cold Start Latency"
    )

    # Inject after the Executive Summary heading, before the table
    html = html.replace(
        '<h2>2. Executive Summary</h2>\n<p class="section-note">',
        f'<h2>2. Executive Summary</h2>\n{exec_chart}\n<p class="section-note">',
    )

    # Inject scaling chart after the extended suite heading
    html = html.replace(
        '<h2>7. Extended Suite',
        f'{scaling_chart}\n<h2>7. Extended Suite',
    )

    # Inject throughput chart after 7c spike section header
    html = html.replace(
        '<h3>7c. Spike Test',
        f'{throughput_chart}\n<h3>7c. Spike Test',
    )

    # Inject cold start chart after the cold start heading
    html = html.replace(
        '<h2>3. Cold Start Latency</h2>\n<p>Cold start measures',
        f'<h2>3. Cold Start Latency</h2>\n{cold_chart}\n<p>Cold start measures',
    )

    with open(args.html, "w") as f:
        f.write(html)

    print(f"Injected 4 charts into {args.html}")


if __name__ == "__main__":
    main()
