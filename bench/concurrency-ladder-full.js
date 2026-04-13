import http from "k6/http";
import { check } from "k6";
import { Rate, Trend } from "k6/metrics";

const errorRate = new Rate("errors");
const latency = new Trend("ladder_latency", true);
const processingMs = new Trend("server_processing_ms", true);

const BASE_URL =
  __ENV.GATEWAY_URL ||
  "https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app";

// Extended concurrency ladder: 1 → 10 → 50 → 100 → 250 → 500 → 1,000 VUs.
// 60s per step = 420s total (7 minutes).
// Requires a runner with ≥4 vCPU / 16 GB (e.g. GCP e2-standard-4).
export const options = {
  stages: [
    { duration: "60s", target: 1 },
    { duration: "60s", target: 10 },
    { duration: "60s", target: 50 },
    { duration: "60s", target: 100 },
    { duration: "60s", target: 250 },
    { duration: "60s", target: 500 },
    { duration: "60s", target: 1000 },
  ],
  thresholds: {
    errors: ["rate<0.10"],
  },
};

const headers = { "Content-Type": "application/json" };

const PROMPTS = [
  "What is the weather like today?",
  "Can you help me write a cover letter?",
  "Explain quantum computing in simple terms",
  "Tell me how to write a good resume",
  "What are the best practices for code reviews?",
];

export default function () {
  const text = PROMPTS[Math.floor(Math.random() * PROMPTS.length)];
  const payload = JSON.stringify({
    labels: ["safe", "unsafe"],
    nonce: `ladder-full-${__VU}-${__ITER}`,
    text: text,
  });

  const res = http.post(`${BASE_URL}/gateway/moderate`, payload, {
    headers,
    tags: { endpoint: "moderate-ladder-full" },
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
  latency.add(res.timings.duration);

  try {
    const body = res.json();
    if (body.moderation) {
      processingMs.add(body.moderation.processing_ms);
    }
  } catch {}
}
