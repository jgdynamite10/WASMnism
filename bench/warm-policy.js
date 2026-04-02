import http from "k6/http";
import { check } from "k6";
import { Rate, Trend } from "k6/metrics";

const errorRate = new Rate("errors");
const latency = new Trend("warm_policy_latency", true);
const processingMs = new Trend("server_processing_ms", true);

const BASE_URL =
  __ENV.GATEWAY_URL ||
  "https://wasm-prompt-firewall-imjy4pe0.fermyon.app";

const PROMPTS = [
  "What is the weather like today?",
  "Can you help me write a cover letter?",
  "Explain quantum computing in simple terms",
  "Tell me how to write a good resume",
  "What are the best practices for code reviews?",
];

export const options = {
  scenarios: {
    warmPolicy: {
      executor: "constant-vus",
      vus: 10,
      duration: "60s",
    },
  },
  thresholds: {
    errors: ["rate<0.01"],
  },
};

const headers = { "Content-Type": "application/json" };

export default function () {
  const text = PROMPTS[Math.floor(Math.random() * PROMPTS.length)];
  const payload = JSON.stringify({
    labels: ["safe", "unsafe"],
    nonce: `policy-${__VU}-${__ITER}`,
    text: text,
    ml: false,
  });

  const res = http.post(`${BASE_URL}/gateway/moderate`, payload, {
    headers,
    tags: { endpoint: "moderate-policy" },
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
    "ml_toxicity is null": (r) => {
      try {
        return r.json().moderation.ml_toxicity === null || r.json().moderation.ml_toxicity === undefined;
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
