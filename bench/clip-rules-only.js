// Tier 2 — Handler-weight isolation (per benchmark_contract_tier2.md Section 6.5)
//
// Methodology:
//   POST /api/clip/moderate with ml:false
//   Sustained load for 60s at 10 VUs
//   Reports the same shape as bench/warm-policy.js, enabling direct
//   side-by-side comparison: same handler endpoint, ml off, no cache pre-seed.
//
// Why this script exists:
//   /api/clip/moderate has heavier handler logic than /gateway/moderate
//   (multipart-aware body parsing, image blocklist check, KV cache lookup,
//   KV cache write). Even with ml:false, this overhead is real. Empirical
//   single-curl data showed ~13 ms extra vs /gateway/moderate ml:false.
//   This script measures it under sustained load.
//
// Use this number to:
//   1. Quantify the cost of /api/clip/moderate's full-pipeline handler
//   2. Compare Tier 2 platforms running the SAME handler with no ML
//   3. Establish a baseline that the cache-hit and warm-ml scenarios build on
//
// Env vars:
//   GATEWAY_URL    — required; base URL of platform under test
//   CLIP_VUS       — default 10
//   CLIP_DURATION  — default "60s"
//   PLATFORM       — optional label ("akamai-ml" | "lambda-ml")

import http from "k6/http";
import { check } from "k6";
import { Rate, Trend } from "k6/metrics";

const errorRate = new Rate("errors");
const clipRulesLatency = new Trend("clip_rules_only_latency_ms", true);
const processingMs = new Trend("server_processing_ms", true);

const BASE_URL =
  __ENV.GATEWAY_URL ||
  "https://f9318a6c-01e4-4f5b-995e-51894dfaf817.fwf.app";

const CLIP_VUS = parseInt(__ENV.CLIP_VUS || "10", 10);
const CLIP_DURATION = __ENV.CLIP_DURATION || "60s";
const PLATFORM = __ENV.PLATFORM || "tier2";

const PROMPTS = [
  "What is the weather like today?",
  "Can you help me write a cover letter?",
  "Explain quantum computing in simple terms",
  "Tell me how to write a good resume",
  "What are the best practices for code reviews?",
];

const headers = { "Content-Type": "application/json" };

export const options = {
  scenarios: {
    clipRulesOnly: {
      executor: "constant-vus",
      vus: CLIP_VUS,
      duration: CLIP_DURATION,
    },
  },
  thresholds: {
    errors: ["rate<0.01"],
  },
};

export default function () {
  const text = PROMPTS[Math.floor(Math.random() * PROMPTS.length)];
  const payload = JSON.stringify({
    labels: ["safe", "unsafe"],
    nonce: `clip-rules-${PLATFORM}-${__VU}-${__ITER}`,
    text,
    ml: false,
  });

  const res = http.post(`${BASE_URL}/api/clip/moderate`, payload, {
    headers,
    tags: { scenario: "clip-rules-only", platform: PLATFORM },
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
  clipRulesLatency.add(res.timings.duration);

  try {
    const body = res.json();
    if (body && body.moderation) {
      processingMs.add(body.moderation.processing_ms);
    }
  } catch {}
}
