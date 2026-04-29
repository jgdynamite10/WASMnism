// Tier 2 — Mixed load (per benchmark_contract_tier2.md Section 7.4)
//
// Methodology:
//   1. Build payload pool:
//      - 50 unique rules-only payloads (text without prohibited terms or PII)
//      - 5 unique ML-trigger payloads (text needing classifier judgement)
//   2. Pre-seed cache for 4 of 5 ML payloads (N_PRIME=2 each, in setup())
//   3. Run for MIXED_DURATION at MIXED_VUS, each iteration:
//      - 95% chance: pick rules-only payload → ml:false
//      - 5% chance: pick ML payload — 80% from pre-seeded set (cache-eligible),
//                                     20% from uncached set (forces ML)
//   4. Report:
//      - Overall p50, p95, p99
//      - Per-bucket p50 (rules-only / ml-cache-hit / ml-cold)
//      - Cache hit rate among ML calls
//
// This is the closest the suite gets to realistic production traffic shape.
// The headline mixed-tier number for the scorecard.
//
// Env vars:
//   GATEWAY_URL     — required; base URL of platform under test
//   MIXED_VUS       — default 10
//   MIXED_DURATION  — default "5m"
//   PLATFORM        — optional label ("akamai-ml" | "lambda-ml")

import http from "k6/http";
import { check } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";

const errorRate = new Rate("errors");
const overallLatency = new Trend("mixed_overall_latency_ms", true);
const rulesLatency = new Trend("mixed_rules_latency_ms", true);
const mlCacheHitLatency = new Trend("mixed_ml_cache_hit_latency_ms", true);
const mlColdLatency = new Trend("mixed_ml_cold_latency_ms", true);
const mlCacheHitRate = new Rate("mixed_ml_cache_hit_rate");
const requestBucket = new Counter("mixed_request_bucket");

const BASE_URL =
  __ENV.GATEWAY_URL ||
  "https://f9318a6c-01e4-4f5b-995e-51894dfaf817.fwf.app";

const MIXED_VUS = parseInt(__ENV.MIXED_VUS || "10", 10);
const MIXED_DURATION = __ENV.MIXED_DURATION || "5m";
const PLATFORM = __ENV.PLATFORM || "tier2";

// 50 rules-only payloads — generic conversational text
const RULES_PROMPTS = Array.from({ length: 50 }, (_, i) => ({
  text: `safe production message number ${i} discussing routine business operations`,
  ml: false,
}));

// 5 ML-trigger payloads — ambiguous text the rules pipeline can't decide on
const ML_PROMPTS = [
  { text: "I'm extremely frustrated with this entire situation and the people involved", id: "ml0" },
  { text: "this strategy seems aggressive but might actually work in our favour", id: "ml1" },
  { text: "the team's recent decisions feel deeply problematic to me", id: "ml2" },
  { text: "your reasoning here is flawed and shows a lack of understanding", id: "ml3" },
  { text: "the customer's complaint deserves immediate and serious attention", id: "ml4" },
];

// Seed 4 of 5 (indexes 0..3); index 4 stays uncached → forces cold ML on hit
const SEEDED_INDEXES = [0, 1, 2, 3];

const headers = { "Content-Type": "application/json" };

export const options = {
  scenarios: {
    mixedLoad: {
      executor: "constant-vus",
      vus: MIXED_VUS,
      duration: MIXED_DURATION,
      gracefulStop: "10s",
    },
  },
  thresholds: {
    errors: ["rate<0.01"],
    mixed_overall_latency_ms: ["p(95)<500"], // sanity check; scorecard reports actuals
  },
};

export function setup() {
  // Pre-seed cache for the 4 indexed ML payloads (2 calls each)
  for (const idx of SEEDED_INDEXES) {
    const prompt = ML_PROMPTS[idx];
    const payload = JSON.stringify({
      labels: ["safe", "unsafe"],
      nonce: `mixed-seed-${PLATFORM}-${prompt.id}`,
      text: prompt.text,
      ml: true,
    });
    for (let i = 0; i < 2; i++) {
      const res = http.post(`${BASE_URL}/api/clip/moderate`, payload, {
        headers,
        tags: { scenario: "mixed-load", phase: "seed" },
      });
      console.log(
        `[mixed-load seed] idx=${idx} iter=${i} status=${res.status} duration_ms=${res.timings.duration.toFixed(2)}`
      );
    }
  }
  return { seededIndexes: SEEDED_INDEXES };
}

export default function () {
  const isMl = Math.random() < 0.05; // 5% ML traffic

  if (!isMl) {
    // 95% rules-only path — short-circuits before ML, hits /api/clip/moderate ml:false
    const prompt = RULES_PROMPTS[Math.floor(Math.random() * RULES_PROMPTS.length)];
    const payload = JSON.stringify({
      labels: ["safe", "unsafe"],
      nonce: `mixed-rules-${PLATFORM}-${__VU}-${__ITER}`,
      text: prompt.text,
      ml: false,
    });

    const res = http.post(`${BASE_URL}/api/clip/moderate`, payload, {
      headers,
      tags: { scenario: "mixed-load", bucket: "rules", platform: PLATFORM },
    });

    errorRate.add(res.status !== 200);
    overallLatency.add(res.timings.duration);
    rulesLatency.add(res.timings.duration);
    requestBucket.add(1, { bucket: "rules" });
    return;
  }

  // 5% ML path — 80% from seeded set (should cache-hit), 20% from uncached
  const useSeeded = Math.random() < 0.80;
  const idx = useSeeded
    ? SEEDED_INDEXES[Math.floor(Math.random() * SEEDED_INDEXES.length)]
    : 4; // unseeded
  const prompt = ML_PROMPTS[idx];

  const payload = JSON.stringify({
    labels: ["safe", "unsafe"],
    nonce: `mixed-ml-${PLATFORM}-${__VU}-${__ITER}`,
    text: prompt.text,
    ml: true,
  });

  const res = http.post(`${BASE_URL}/api/clip/moderate`, payload, {
    headers,
    tags: {
      scenario: "mixed-load",
      bucket: useSeeded ? "ml-cache-hit-target" : "ml-cold-target",
      platform: PLATFORM,
    },
  });

  errorRate.add(res.status !== 200);
  overallLatency.add(res.timings.duration);

  let cacheHit = false;
  try {
    const body = res.json();
    cacheHit = body && body.cache && body.cache.hit === true;
  } catch {}

  if (cacheHit) {
    mlCacheHitLatency.add(res.timings.duration);
    requestBucket.add(1, { bucket: "ml-cache-hit" });
  } else {
    mlColdLatency.add(res.timings.duration);
    requestBucket.add(1, { bucket: "ml-cold" });
  }
  mlCacheHitRate.add(cacheHit);
}
