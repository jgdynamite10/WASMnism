import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const errorRate = new Rate("errors");
const gatewayLatency = new Trend("gateway_latency", true);

const BASE_URL = __ENV.GATEWAY_URL || "https://wasm-prompt-firewall-imjy4pe0.fermyon.app";
const LABELS = JSON.stringify(["cat", "dog", "bird", "car", "music"]);
const NONCE = "wasmnism-bench-v1";

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
    http_req_duration: ["p(50)<15", "p(95)<50", "p(99)<150"],
    errors: ["rate<0.001"],
  },
};

const payload = JSON.stringify({ labels: JSON.parse(LABELS), nonce: NONCE });
const headers = { "Content-Type": "application/json" };

export default function () {
  const res = http.post(`${BASE_URL}/gateway/mock-classify`, payload, {
    headers,
    tags: { endpoint: "mock-classify" },
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
    "has correct headers": (r) =>
      r.headers["X-Gateway-Platform"] !== undefined &&
      r.headers["X-Gateway-Request-Id"] !== undefined,
  });

  errorRate.add(!passed);
  gatewayLatency.add(res.timings.duration);
}
