import http from "k6/http";
import { check } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";

const errorRate = new Rate("errors");
const latency = new Trend("soak_latency", true);
const processingMs = new Trend("server_processing_ms", true);
const totalRequests = new Counter("total_requests");

const BASE_URL =
  __ENV.GATEWAY_URL ||
  "https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app";

// Soak test: 500 VUs sustained for 10 minutes.
// Reveals memory leaks, GC pauses, connection pool exhaustion, and
// platform-side throttling that shorter tests miss.
// Requires a runner with ≥4 vCPU / 16 GB (e.g. GCP e2-standard-4).
export const options = {
  scenarios: {
    soak: {
      executor: "constant-vus",
      vus: 500,
      duration: "10m",
    },
  },
  thresholds: {
    errors: ["rate<0.05"],
    soak_latency: ["p(95)<2000"],
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
    nonce: `soak-${__VU}-${__ITER}`,
    text: text,
  });

  const res = http.post(`${BASE_URL}/gateway/moderate`, payload, {
    headers,
    tags: { endpoint: "moderate-soak" },
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
  totalRequests.add(1);
  latency.add(res.timings.duration);

  try {
    const body = res.json();
    if (body.moderation) {
      processingMs.add(body.moderation.processing_ms);
    }
  } catch {}
}
