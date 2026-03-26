import http from "k6/http";
import { check, group, sleep } from "k6";
import { Trend, Rate, Counter } from "k6/metrics";

const BASE_URL = __ENV.GATEWAY_URL || "http://127.0.0.1:3000";
const PLATFORM = __ENV.PLATFORM || "unknown";
const IMAGE_PATH = __ENV.IMAGE_PATH || "fixtures/benchmark.jpg";

const policyLatency = new Trend("mode1_policy_latency", true);
const cachedLatency = new Trend("mode2_cached_latency", true);
const pipelineLatency = new Trend("mode3_pipeline_latency", true);
const policyProcessing = new Trend("mode1_processing_ms", true);
const cachedProcessing = new Trend("mode2_processing_ms", true);
const pipelineProcessing = new Trend("mode3_processing_ms", true);
const errorCount = new Counter("error_count");

const LABELS = ["cat", "dog", "bird", "car", "music"];
const NONCE = "bench-compare";
const payload = JSON.stringify({ labels: LABELS, nonce: NONCE });
const headers = { "Content-Type": "application/json" };

const imageData = open(IMAGE_PATH, "b");
const labelsStr = JSON.stringify(LABELS);

export const options = {
  scenarios: {
    mode1_policy: {
      executor: "ramping-vus",
      startVUs: 1,
      stages: [
        { duration: "5s", target: 10 },
        { duration: "10s", target: 50 },
        { duration: "10s", target: 50 },
        { duration: "5s", target: 1 },
      ],
      exec: "mode1",
      startTime: "0s",
    },
    mode2_cached: {
      executor: "ramping-vus",
      startVUs: 1,
      stages: [
        { duration: "5s", target: 10 },
        { duration: "10s", target: 50 },
        { duration: "10s", target: 50 },
        { duration: "5s", target: 1 },
      ],
      exec: "mode2",
      startTime: "35s",
    },
    mode3_pipeline: {
      executor: "ramping-vus",
      startVUs: 1,
      stages: [
        { duration: "5s", target: 5 },
        { duration: "10s", target: 20 },
        { duration: "10s", target: 20 },
        { duration: "5s", target: 1 },
      ],
      exec: "mode3",
      startTime: "70s",
    },
  },
  thresholds: {
    "mode1_policy_latency": ["p(50)<500", "p(95)<2000"],
    "mode2_cached_latency": ["p(50)<500", "p(95)<2000"],
    "mode3_pipeline_latency": ["p(50)<5000", "p(95)<10000"],
  },
};

export function setup() {
  console.log(`\n=== Quick Benchmark: ${PLATFORM} @ ${BASE_URL} ===\n`);

  const health = http.get(`${BASE_URL}/gateway/health`);
  check(health, { "health ok": (r) => r.status === 200 });

  const formData = {
    image: http.file(imageData, "benchmark.jpg", "image/jpeg"),
    labels: labelsStr,
  };
  const seed = http.post(`${BASE_URL}/api/clip/moderate`, formData);
  if (seed.status === 200) {
    console.log("Cache seeded for Mode 2");
  } else {
    console.log(`Cache seed status: ${seed.status} (Mode 2 may not show cache hits)`);
  }

  return {};
}

export function mode1() {
  const res = http.post(`${BASE_URL}/gateway/moderate`, payload, { headers });
  policyLatency.add(res.timings.duration);
  try {
    const b = JSON.parse(res.body);
    if (b.moderation) policyProcessing.add(b.moderation.processing_ms);
  } catch {}
  if (res.status !== 200) errorCount.add(1);
}

export function mode2() {
  const res = http.post(`${BASE_URL}/gateway/moderate-cached`, payload, { headers });
  cachedLatency.add(res.timings.duration);
  try {
    const b = JSON.parse(res.body);
    if (b.moderation) cachedProcessing.add(b.moderation.processing_ms);
  } catch {}
  if (res.status !== 200) errorCount.add(1);
}

export function mode3() {
  const formData = {
    image: http.file(imageData, "benchmark.jpg", "image/jpeg"),
    labels: labelsStr,
  };
  const res = http.post(`${BASE_URL}/api/clip/moderate`, formData);
  pipelineLatency.add(res.timings.duration);
  try {
    const b = JSON.parse(res.body);
    if (b.moderation) pipelineProcessing.add(b.moderation.processing_ms);
  } catch {}
  if (res.status !== 200) errorCount.add(1);
}
