// Tier 2 — Cold ML latency (per benchmark_contract_tier2.md Section 7.1)
//
// Methodology:
//   1. Send single POST /gateway/moderate with ml:true
//   2. Record k6 http_req_duration
//   3. Sleep COLD_IDLE_SECONDS between iterations
//   4. Repeat for COLD_ITERATIONS
//
// Per-platform behaviour:
//   - Akamai Functions: every request reloads the model (~600 ms). Idle gap is
//     parity-only — Spin spawns a fresh WASM instance every request anyway.
//   - AWS Lambda: 60s idle is NOT sufficient to guarantee container retirement.
//     For a true cold path on Lambda, set COLD_IDLE_SECONDS=1200 (20 min) OR
//     redeploy the function immediately before the run. Document the choice in
//     the result manifest.
//
// Reporting: cold-ML scorecard cells MUST show all 10 individual values, not
// just the median. Variance is part of the answer.
//
// Env vars:
//   GATEWAY_URL          — required; base URL of platform under test
//   COLD_ITERATIONS      — default 10
//   COLD_IDLE_SECONDS    — default 60
//   PLATFORM             — optional label ("akamai-ml" | "lambda-ml") for tagging

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const errorRate = new Rate("errors");
const coldMlLatency = new Trend("cold_ml_latency_ms", true);
const totalInferenceMs = new Trend("server_total_inference_ms", true);

const BASE_URL =
  __ENV.GATEWAY_URL ||
  "https://f9318a6c-01e4-4f5b-995e-51894dfaf817.fwf.app";

const ITERATIONS = parseInt(__ENV.COLD_ITERATIONS || "10", 10);
const IDLE_SECONDS = parseInt(__ENV.COLD_IDLE_SECONDS || "60", 10);
const PLATFORM = __ENV.PLATFORM || "tier2";

const PROMPTS = [
  "I genuinely think you should reconsider this approach",
  "what an interesting take, very thought-provoking",
  "your work has consistently exceeded expectations",
  "this proposal needs more careful examination",
  "the data suggests a different conclusion entirely",
  "I appreciate your perspective on this matter",
  "let's discuss this further at the next meeting",
  "the analysis reveals a complex situation",
  "consider all the implications before deciding",
  "this approach has merit but needs refinement",
];

export const options = {
  scenarios: {
    coldMl: {
      executor: "per-vu-iterations",
      vus: 1,
      iterations: ITERATIONS,
      maxDuration: `${(IDLE_SECONDS + 30) * ITERATIONS}s`,
    },
  },
  thresholds: {
    errors: ["rate<0.10"], // cold ML may fail occasionally on platform variance
  },
};

const headers = { "Content-Type": "application/json" };

export default function () {
  // Idle gap between iterations (Section 7.1 protocol)
  if (__ITER > 0 && IDLE_SECONDS > 0) {
    sleep(IDLE_SECONDS);
  }

  const text = PROMPTS[__ITER % PROMPTS.length];
  const payload = JSON.stringify({
    labels: ["safe", "unsafe"],
    nonce: `cold-ml-${PLATFORM}-${__VU}-${__ITER}`,
    text,
    ml: true,
  });

  const res = http.post(`${BASE_URL}/gateway/moderate`, payload, {
    headers,
    tags: {
      scenario: "cold-ml",
      iteration: String(__ITER),
      platform: PLATFORM,
    },
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

  errorRate.add(!passed);
  coldMlLatency.add(res.timings.duration);

  // Log each iteration explicitly — contract requires all 10 individual values
  // in the scorecard. console.log goes to stdout/stderr; k6 JSON output captures
  // them into the per-iteration metric stream as well.
  let inferenceMs = "n/a";
  try {
    const body = res.json();
    if (body && body.classification && body.classification.metrics) {
      inferenceMs = body.classification.metrics.total_inference_ms;
      if (typeof inferenceMs === "number") {
        totalInferenceMs.add(inferenceMs);
      }
    }
  } catch {}

  console.log(
    `[cold-ml iter=${__ITER} platform=${PLATFORM}] ` +
      `duration_ms=${res.timings.duration.toFixed(2)} ` +
      `server_inference_ms=${inferenceMs} ` +
      `status=${res.status}`
  );
}
