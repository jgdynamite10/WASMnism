import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const errorRate = new Rate("errors");
const proxyLatency = new Trend("proxy_latency", true);

const BASE_URL = __ENV.GATEWAY_URL || "https://wasm-prompt-firewall-imjy4pe0.fermyon.app";
const LABELS = JSON.stringify(["cat", "dog", "bird", "car", "music"]);

// Concurrency ladder per benchmark_contract.md §7.2
export const options = {
  stages: [
    { duration: "10s", target: 1 },    // warm-up
    { duration: "15s", target: 10 },   // ramp 1
    { duration: "15s", target: 10 },   // hold 1
    { duration: "15s", target: 50 },   // ramp 2
    { duration: "15s", target: 50 },   // hold 2
    { duration: "15s", target: 100 },  // ramp 3
    { duration: "15s", target: 100 },  // hold 3
    { duration: "10s", target: 1 },    // cool-down
  ],
  thresholds: {
    http_req_duration: ["p(50)<500", "p(95)<1500", "p(99)<3000"],
    errors: ["rate<0.005"],
  },
};

const imageFile = open("fixtures/benchmark.jpg", "b");

export default function () {
  const res = http.post(`${BASE_URL}/api/clip/classify`, {
    image: http.file(imageFile, "benchmark.jpg", "image/jpeg"),
    labels: LABELS,
  }, {
    tags: { endpoint: "clip-classify" },
  });

  const passed = check(res, {
    "status is 200": (r) => r.status === 200,
    "has results array": (r) => {
      try {
        return JSON.parse(r.body).results.length === 5;
      } catch {
        return false;
      }
    },
    "scores sum to ~1.0": (r) => {
      try {
        const results = JSON.parse(r.body).results;
        const sum = results.reduce((acc, r) => acc + r.score, 0);
        return Math.abs(sum - 1.0) < 0.01;
      } catch {
        return false;
      }
    },
    "has correct headers": (r) =>
      r.headers["X-Gateway-Platform"] !== undefined &&
      r.headers["X-Gateway-Request-Id"] !== undefined,
  });

  errorRate.add(!passed);
  proxyLatency.add(res.timings.duration);
}
