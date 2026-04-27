#!/usr/bin/env python3
"""Validate benchmark result directories for completeness and freshness.

Usage:
    python3 bench/validate-results.py <result_dir> [<result_dir> ...]
    python3 bench/validate-results.py --max-age 24 results/akamai/multiregion_* results/fastly/multiregion_*

Checks:
    - 7run/ directory exists with 7 complete runs
    - Each run has warm-light.json, warm-policy.json, concurrency-ladder.json
    - Cold start JSONs exist for all 3 regions
      (Linode: us-ord, eu-central, ap-south — or GCP: gcp-us-east, gcp-eu-west, gcp-ap-southeast)
    - Timestamps are within --max-age hours (default: 48)

Exits non-zero if any check fails.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

REGIONS_LINODE = ["us-ord", "eu-central", "ap-south"]
REGIONS_GCP = ["gcp-us-east", "gcp-eu-west", "gcp-ap-southeast"]
REQUIRED_RUN_FILES = ["warm-light.json", "warm-policy.json", "concurrency-ladder.json"]
REQUIRED_RUNS = 7


def regions_for_dir(result_path: Path) -> list:
    """Use GCP region names if this multiregion run was executed from GCP runners; else Linode."""
    if (result_path / "gcp-us-east").is_dir():
        return REGIONS_GCP
    return REGIONS_LINODE


def parse_timestamp_from_dir(dirname):
    """Extract YYYYMMDD_HHMMSS from a directory name like multiregion_20260410_170732."""
    parts = dirname.split("_")
    for i, part in enumerate(parts):
        if len(part) == 8 and part.isdigit():
            try:
                date_str = part
                time_str = parts[i + 1] if i + 1 < len(parts) else "000000"
                if len(time_str) == 6 and time_str.isdigit():
                    return datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
            except (ValueError, IndexError):
                continue
    return None


def validate_region(region_dir, region, errors):
    """Validate a single region's results."""
    run_dir = region_dir / "7run"

    if not run_dir.is_dir():
        errors.append(f"  MISSING: {run_dir}")
        return

    runs = sorted([d for d in run_dir.iterdir() if d.is_dir() and d.name.startswith("run_")])
    if len(runs) < REQUIRED_RUNS:
        errors.append(f"  INCOMPLETE: {run_dir} has {len(runs)} runs, need {REQUIRED_RUNS}")

    for run in runs:
        for fname in REQUIRED_RUN_FILES:
            fpath = run / fname
            if not fpath.exists():
                errors.append(f"  MISSING: {fpath}")
            elif fpath.stat().st_size < 100:
                errors.append(f"  EMPTY/CORRUPT: {fpath} ({fpath.stat().st_size} bytes)")

    cold_start = region_dir / f"cold-start-rules_{region}.json"
    if not cold_start.exists():
        errors.append(f"  MISSING cold start: {cold_start}")
    elif cold_start.stat().st_size < 100:
        errors.append(f"  EMPTY/CORRUPT: {cold_start}")


def validate_result_dir(result_dir, max_age_hours):
    """Validate a single multiregion result directory."""
    result_path = Path(result_dir)
    errors = []
    warnings = []

    if not result_path.is_dir():
        return [f"NOT FOUND: {result_dir}"], []

    ts = parse_timestamp_from_dir(result_path.name)
    if ts:
        age = datetime.now() - ts
        age_hours = age.total_seconds() / 3600
        if age_hours > max_age_hours:
            warnings.append(
                f"  STALE: {result_path.name} is {age_hours:.0f}h old (max: {max_age_hours}h)"
            )
    else:
        warnings.append(f"  Cannot parse timestamp from: {result_path.name}")

    regions = regions_for_dir(result_path)
    for region in regions:
        region_dir = result_path / region
        if not region_dir.is_dir():
            errors.append(f"  MISSING region dir: {region_dir}")
            continue
        validate_region(region_dir, region, errors)

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Validate benchmark result completeness")
    parser.add_argument("dirs", nargs="+", help="Result directories to validate")
    parser.add_argument(
        "--max-age", type=int, default=48, help="Max age in hours before flagging as stale"
    )
    args = parser.parse_args()

    total_errors = 0
    total_warnings = 0

    for d in args.dirs:
        print(f"=== Validating: {d} ===")
        errors, warnings = validate_result_dir(d, args.max_age)

        for w in warnings:
            print(f"  WARN: {w}")
            total_warnings += 1

        if errors:
            for e in errors:
                print(f"  FAIL: {e}")
            total_errors += len(errors)
        else:
            print("  OK: All checks passed")

        print()

    print(f"Summary: {total_errors} errors, {total_warnings} warnings")

    if total_errors > 0:
        print("FAIL: Fix errors before generating scorecard.")
        sys.exit(1)

    if total_warnings > 0:
        print("WARN: Review warnings above.")

    sys.exit(0)


if __name__ == "__main__":
    main()
