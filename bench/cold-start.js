import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";

const roundTrip = new Trend("cold_round_trip", true);
const serverProcessing = new Trend("cold_server_processing", true);
const mlInference = new Trend("cold_ml_inference", true);

const BASE_URL = __ENV.GATEWAY_URL || "https://wasm-prompt-firewall-imjy4pe0.fermyon.app";
const COLD_WAIT = parseInt(__ENV.COLD_WAIT || "120");
const ITERATIONS = parseInt(__ENV.COLD_ITERATIONS || "10");
const USE_ML = (__ENV.USE_ML || "false") === "true";

export const options = {
  scenarios: {
    coldStart: {
      executor: "per-vu-iterations",
      vus: 1,
      iterations: ITERATIONS,
      maxDuration: `${ITERATIONS * (COLD_WAIT + 30)}s`,
    },
  },
  thresholds: {},
};

const mode = USE_ML ? "rules+ML" : "rules-only";

const payload = JSON.stringify({
  labels: ["safe", "unsafe"],
  nonce: "cold-start-bench",
  text: "What is the weather like today?",
  ml: USE_ML,
});
const headers = { "Content-Type": "application/json" };

export default function () {
  const res = http.post(`${BASE_URL}/gateway/moderate`, payload, {
    headers,
    tags: { endpoint: "cold-moderate" },
  });

  check(res, {
    "status is 200": (r) => r.status === 200,
  });

  roundTrip.add(res.timings.duration);

  try {
    const body = res.json();
    if (body.moderation) {
      serverProcessing.add(body.moderation.processing_ms);
    }
    if (body.moderation && body.moderation.ml_toxicity) {
      mlInference.add(body.moderation.ml_toxicity.inference_ms);
    }
  } catch {}

  if (__ITER < ITERATIONS - 1) {
    console.log(`  [${mode}] Iteration ${__ITER + 1}/${ITERATIONS}: ${res.timings.duration.toFixed(0)}ms round-trip. Waiting ${COLD_WAIT}s for cold eviction...`);
    sleep(COLD_WAIT);
  } else {
    console.log(`  [${mode}] Iteration ${__ITER + 1}/${ITERATIONS}: ${res.timings.duration.toFixed(0)}ms round-trip. Done.`);
  }
}
