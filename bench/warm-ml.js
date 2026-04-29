// Tier 2 — Warm ML latency (per benchmark_contract_tier2.md Section 7.2)
//
// Methodology:
//   1. Run a 30s warmup phase (5 VUs, 60 RPS) — discarded from results
//   2. Run 60s measurement phase (5 VUs, sustained ml:true) — measured
//   3. Report p50, p90, p95, p99 across the measurement phase only
//
// Per-platform expectation:
//   - Lambda: warmup populates OnceLock; measurement phase shows model-cached path
//     (~10-50 ms p50). This is Lambda's "true" warm performance.
//   - Akamai Functions: every request reloads regardless. Warm-ML p50 should
//     roughly equal cold-ML p50. This divergence vs Lambda is the headline
//     architectural finding.
//
// k6 mechanics: phase separation uses scenarios with `startTime`. Warmup metrics
// are tagged `phase:warmup` and excluded from the scorecard via thresholds.
// Measurement metrics are tagged `phase:measure` and feed the scorecard.
//
// Env vars:
//   GATEWAY_URL       — required; base URL of platform under test
//   WARM_VUS          — default 5
//   WARM_DURATION     — default "60s"
//   WARMUP_DURATION   — default "30s"
//   PLATFORM          — optional label ("akamai-ml" | "lambda-ml")

import http from "k6/http";
import { check } from "k6";
import { Rate, Trend } from "k6/metrics";

const errorRate = new Rate("errors");
const warmMlLatency = new Trend("warm_ml_latency_ms", true);
const totalInferenceMs = new Trend("server_total_inference_ms", true);

const BASE_URL =
  __ENV.GATEWAY_URL ||
  "https://f9318a6c-01e4-4f5b-995e-51894dfaf817.fwf.app";

const WARM_VUS = parseInt(__ENV.WARM_VUS || "5", 10);
const WARM_DURATION = __ENV.WARM_DURATION || "60s";
const WARMUP_DURATION = __ENV.WARMUP_DURATION || "30s";
const PLATFORM = __ENV.PLATFORM || "tier2";

const PROMPTS = [
  "I genuinely think you should reconsider this approach",
  "what an interesting take, very thought-provoking",
  "your work has consistently exceeded expectations",
  "this proposal needs more careful examination",
  "the data suggests a different conclusion entirely",
];

const headers = { "Content-Type": "application/json" };

export const options = {
  scenarios: {
    warmup: {
      executor: "constant-vus",
      vus: WARM_VUS,
      duration: WARMUP_DURATION,
      tags: { phase: "warmup" },
      exec: "warmupRequest",
    },
    measure: {
      executor: "constant-vus",
      vus: WARM_VUS,
      duration: WARM_DURATION,
      startTime: WARMUP_DURATION, // begins after warmup finishes
      tags: { phase: "measure" },
      exec: "measureRequest",
    },
  },
  thresholds: {
    "errors{phase:measure}": ["rate<0.01"],
  },
};

function buildPayload(phase) {
  const text = PROMPTS[Math.floor(Math.random() * PROMPTS.length)];
  return JSON.stringify({
    labels: ["safe", "unsafe"],
    nonce: `warm-ml-${PLATFORM}-${phase}-${__VU}-${__ITER}`,
    text,
    ml: true,
  });
}

export function warmupRequest() {
  http.post(`${BASE_URL}/gateway/moderate`, buildPayload("warmup"), {
    headers,
    tags: { scenario: "warm-ml", phase: "warmup", platform: PLATFORM },
  });
}

export function measureRequest() {
  const res = http.post(`${BASE_URL}/gateway/moderate`, buildPayload("measure"), {
    headers,
    tags: { scenario: "warm-ml", phase: "measure", platform: PLATFORM },
  });

  const passed = check(res, {
    "status is 200": (r) => r.status === 200,
    "has verdict": (r) => {
      try {
        return ["allow", "block", "review"].includes(r.json().verdict);
      } catch {
        return false;
      }
    },
  });

  errorRate.add(!passed, { phase: "measure" });
  warmMlLatency.add(res.timings.duration, { phase: "measure" });

  try {
    const body = res.json();
    if (body && body.classification && body.classification.metrics) {
      const inf = body.classification.metrics.total_inference_ms;
      if (typeof inf === "number") {
        totalInferenceMs.add(inf, { phase: "measure" });
      }
    }
  } catch {}
}
