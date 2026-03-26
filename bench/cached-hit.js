import http from "k6/http";
import { check } from "k6";
import { Rate, Trend } from "k6/metrics";

const errorRate = new Rate("errors");
const gatewayLatency = new Trend("gateway_latency", true);
const processingMs = new Trend("processing_ms", true);
const cacheHitRate = new Rate("cache_hit_rate");

const BASE_URL = __ENV.GATEWAY_URL || "https://wasm-prompt-firewall-imjy4pe0.fermyon.app";
const LABELS = ["cat", "dog", "bird", "car", "music"];
const NONCE = "wasmnism-bench-v2";

export const options = {
  stages: [
    { duration: "10s", target: 1 },
    { duration: "15s", target: 10 },
    { duration: "15s", target: 10 },
    { duration: "15s", target: 50 },
    { duration: "15s", target: 50 },
    { duration: "15s", target: 100 },
    { duration: "15s", target: 100 },
    { duration: "10s", target: 1 },
  ],
  thresholds: {
    http_req_duration: ["p(50)<25", "p(95)<75", "p(99)<250"],
    errors: ["rate<0.001"],
  },
};

const payload = JSON.stringify({ labels: LABELS, nonce: NONCE });
const headers = { "Content-Type": "application/json" };

// Populate cache before the main benchmark via Mode 3 (full pipeline).
// The setup function runs once before the main test.
export function setup() {
  const imgPath = __ENV.IMAGE_PATH || "bench/fixtures/benchmark.jpg";
  const labelsStr = JSON.stringify(LABELS);

  // First, populate via full pipeline to seed the KV cache
  const formData = {
    image: http.file(open(imgPath, "b"), "benchmark.jpg", "image/jpeg"),
    labels: labelsStr,
  };
  const seedRes = http.post(`${BASE_URL}/api/clip/moderate`, formData, {
    tags: { endpoint: "cache-seed" },
  });

  check(seedRes, {
    "cache seed succeeded": (r) => r.status === 200,
  });

  return {};
}

export default function () {
  const res = http.post(`${BASE_URL}/gateway/moderate-cached`, payload, {
    headers,
    tags: { endpoint: "cached-hit" },
  });

  const passed = check(res, {
    "status is 200": (r) => r.status === 200,
    "has verdict": (r) => {
      try {
        const body = JSON.parse(r.body);
        return ["allow", "block", "review"].includes(body.verdict);
      } catch {
        return false;
      }
    },
    "has cache hash": (r) => {
      try {
        return JSON.parse(r.body).cache.hash.startsWith("sha256:");
      } catch {
        return false;
      }
    },
  });

  errorRate.add(!passed);
  gatewayLatency.add(res.timings.duration);

  try {
    const body = JSON.parse(res.body);
    cacheHitRate.add(body.cache && body.cache.hit === true);
    if (body.moderation && body.moderation.processing_ms) {
      processingMs.add(body.moderation.processing_ms);
    }
  } catch {}
}
