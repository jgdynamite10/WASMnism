import http from "k6/http";
import { check } from "k6";
import { Rate, Trend } from "k6/metrics";

const errorRate = new Rate("errors");
const gatewayLatency = new Trend("gateway_latency", true);
const processingMs = new Trend("processing_ms", true);
const cacheHitRate = new Rate("cache_hit_rate");

const BASE_URL = __ENV.GATEWAY_URL || "https://wasm-prompt-firewall-imjy4pe0.fermyon.app";
const LABELS = ["cat", "dog", "bird", "car", "music"];
const IMAGE_PATH = __ENV.IMAGE_PATH || "bench/fixtures/benchmark.jpg";

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
    http_req_duration: ["p(50)<600", "p(95)<1500", "p(99)<3000"],
    errors: ["rate<0.005"],
  },
};

const imageData = open(IMAGE_PATH, "b");
const labelsStr = JSON.stringify(LABELS);

export default function () {
  const formData = {
    image: http.file(imageData, "benchmark.jpg", "image/jpeg"),
    labels: labelsStr,
  };

  const res = http.post(`${BASE_URL}/api/clip/moderate`, formData, {
    tags: { endpoint: "full-pipeline" },
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
    "has classification results": (r) => {
      try {
        return JSON.parse(r.body).classification.results.length > 0;
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
