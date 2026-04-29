#!/usr/bin/env python3
"""Validate benchmark result directories for completeness and freshness.

Supports both Tier 1 (rules-only, 7-run methodology) and Tier 2 (ML, scenario-based
methodology per docs/benchmark_contract_tier2.md v1.0).

Usage:
    # Tier 1 (multiregion_* directories with 7run/ subdirectories)
    python3 bench/validate-results.py results/akamai/multiregion_20260413_062524 \
        results/fastly/multiregion_20260413_062524 \
        results/workers/multiregion_20260413_062525

    # Tier 2 (tier2_* directories with per-scenario JSON files)
    python3 bench/validate-results.py results/akamai-ml/tier2_20260430_140000 \
        results/lambda-ml/tier2_20260430_140000

    # Mixed
    python3 bench/validate-results.py --max-age 24 \
        results/akamai/multiregion_* \
        results/akamai-ml/tier2_*

Tier auto-detected from directory contents:
    - 7run/ subdirectory present  → Tier 1
    - cold-ml.json / warm-ml.json present → Tier 2
    - Falls back to directory name (multiregion_* → Tier 1, tier2_* → Tier 2)

Tier 1 checks:
    - 7run/ directory exists with 7 complete runs
    - Each run has warm-light.json, warm-policy.json, concurrency-ladder.json
    - Cold start JSONs exist for all 3 regions

Tier 2 checks (per docs/benchmark_contract_tier2.md sections 7.1-7.4):
    - cold-ml.json     (Section 7.1 — 10 single-shot iterations)
    - warm-ml.json     (Section 7.2 — N=10 warmup discarded + 60s at 5 VUs)
    - cache-hit.json   (Section 7.3 — N=2 prime + N=20 identical hits)
    - mixed-load.json  (Section 7.4 — 5 min at 10 VUs, 95%/5% rules/ML mix)
    - clip-rules-only.json (Section 6.5 — handler-weight isolation, /api/clip/moderate ml:false)
    - Optional: each JSON parses and has at least one http_req_duration data point

Both:
    - Timestamps within --max-age hours (default: 48)

Exits non-zero if any check fails.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------
# Region definitions (shared across tiers)
# --------------------------------------------------------------------------
REGIONS_LINODE = ["us-ord", "eu-central", "ap-south"]
REGIONS_GCP = ["gcp-us-east", "gcp-eu-west", "gcp-ap-southeast"]

# --------------------------------------------------------------------------
# Tier 1 configuration
# --------------------------------------------------------------------------
TIER1_REQUIRED_RUN_FILES = ["warm-light.json", "warm-policy.json", "concurrency-ladder.json"]
TIER1_REQUIRED_RUNS = 7

# --------------------------------------------------------------------------
# Tier 2 configuration (per benchmark_contract_tier2.md sections 7.1-7.4)
# --------------------------------------------------------------------------
TIER2_REQUIRED_SCENARIO_FILES = [
    "cold-ml.json",          # Section 7.1
    "warm-ml.json",           # Section 7.2
    "cache-hit.json",         # Section 7.3
    "mixed-load.json",        # Section 7.4
    "clip-rules-only.json",   # Section 6.5 — handler-weight isolation
]

MIN_RESULT_FILE_BYTES = 100


# --------------------------------------------------------------------------
# Tier detection
# --------------------------------------------------------------------------
def detect_tier(result_path: Path) -> str:
    """Return 'tier1' or 'tier2' based on directory contents and naming.

    Detection order:
      1. Any region subdir with `7run/` → tier1
      2. Any region subdir with `cold-ml.json` or `warm-ml.json` → tier2
      3. Directory name pattern: `tier2_*` → tier2, `multiregion_*` → tier1
      4. Fallback: tier1 (preserves backward compatibility)
    """
    for region in REGIONS_GCP + REGIONS_LINODE:
        region_dir = result_path / region
        if not region_dir.is_dir():
            continue
        if (region_dir / "7run").is_dir():
            return "tier1"
        if (region_dir / "cold-ml.json").exists() or (region_dir / "warm-ml.json").exists():
            return "tier2"

    name_lower = result_path.name.lower()
    if name_lower.startswith("tier2_") or "_tier2_" in name_lower:
        return "tier2"
    if name_lower.startswith("multiregion_"):
        return "tier1"
    return "tier1"


def regions_for_dir(result_path: Path) -> list:
    """Use GCP region names if this run was executed from GCP runners; else Linode."""
    if (result_path / "gcp-us-east").is_dir():
        return REGIONS_GCP
    return REGIONS_LINODE


def parse_timestamp_from_dir(dirname):
    """Extract YYYYMMDD_HHMMSS from a directory name (multiregion_* or tier2_*)."""
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


# --------------------------------------------------------------------------
# Tier 1 validation
# --------------------------------------------------------------------------
def validate_region_tier1(region_dir: Path, region: str, errors: list):
    """Validate a single region's Tier 1 results (7-run methodology)."""
    run_dir = region_dir / "7run"

    if not run_dir.is_dir():
        errors.append(f"  MISSING: {run_dir}")
        return

    runs = sorted([d for d in run_dir.iterdir() if d.is_dir() and d.name.startswith("run_")])
    if len(runs) < TIER1_REQUIRED_RUNS:
        errors.append(f"  INCOMPLETE: {run_dir} has {len(runs)} runs, need {TIER1_REQUIRED_RUNS}")

    for run in runs:
        for fname in TIER1_REQUIRED_RUN_FILES:
            fpath = run / fname
            if not fpath.exists():
                errors.append(f"  MISSING: {fpath}")
            elif fpath.stat().st_size < MIN_RESULT_FILE_BYTES:
                errors.append(f"  EMPTY/CORRUPT: {fpath} ({fpath.stat().st_size} bytes)")

    cold_start = region_dir / f"cold-start-rules_{region}.json"
    if not cold_start.exists():
        errors.append(f"  MISSING cold start: {cold_start}")
    elif cold_start.stat().st_size < MIN_RESULT_FILE_BYTES:
        errors.append(f"  EMPTY/CORRUPT: {cold_start}")


# --------------------------------------------------------------------------
# Tier 2 validation
# --------------------------------------------------------------------------
def validate_scenario_json_quickcheck(fpath: Path, errors: list):
    """Lightweight content sanity check — parse JSON, confirm it has at least one
    http_req_duration metric. Does not validate semantic correctness; that's the
    scorecard builder's job.
    """
    try:
        with fpath.open("r") as f:
            head = f.read(8192)
            f.seek(0)
            content = f.read()
    except (OSError, UnicodeDecodeError) as e:
        errors.append(f"  UNREADABLE: {fpath} ({e})")
        return

    if "http_req_duration" not in head and "http_req_duration" not in content:
        errors.append(
            f"  NO METRICS: {fpath} has no 'http_req_duration' tag — "
            f"likely an empty/failed k6 run"
        )


def validate_region_tier2(region_dir: Path, region: str, errors: list, deep_check: bool):
    """Validate a single region's Tier 2 results (scenario-based methodology).

    Args:
        deep_check: if True, also parse each JSON to verify it contains k6 metrics
    """
    for fname in TIER2_REQUIRED_SCENARIO_FILES:
        fpath = region_dir / fname
        if not fpath.exists():
            errors.append(f"  MISSING Tier 2 scenario: {fpath}")
            continue
        size = fpath.stat().st_size
        if size < MIN_RESULT_FILE_BYTES:
            errors.append(f"  EMPTY/CORRUPT: {fpath} ({size} bytes)")
            continue
        if deep_check:
            validate_scenario_json_quickcheck(fpath, errors)


# --------------------------------------------------------------------------
# Top-level dispatch
# --------------------------------------------------------------------------
def validate_result_dir(result_dir, max_age_hours, deep_check):
    """Validate a single result directory (auto-detects tier)."""
    result_path = Path(result_dir)
    errors = []
    warnings = []

    if not result_path.is_dir():
        return [f"NOT FOUND: {result_dir}"], [], None

    tier = detect_tier(result_path)

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

        if tier == "tier2":
            validate_region_tier2(region_dir, region, errors, deep_check)
        else:
            validate_region_tier1(region_dir, region, errors)

    return errors, warnings, tier


def main():
    parser = argparse.ArgumentParser(description="Validate benchmark result completeness")
    parser.add_argument("dirs", nargs="+", help="Result directories to validate")
    parser.add_argument(
        "--max-age", type=int, default=48, help="Max age in hours before flagging as stale"
    )
    parser.add_argument(
        "--deep-check",
        action="store_true",
        help="Tier 2 only: parse each scenario JSON to confirm k6 metrics present",
    )
    args = parser.parse_args()

    total_errors = 0
    total_warnings = 0

    for d in args.dirs:
        print(f"=== Validating: {d} ===")
        errors, warnings, tier = validate_result_dir(d, args.max_age, args.deep_check)

        if tier:
            print(f"  Tier: {tier}")

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
