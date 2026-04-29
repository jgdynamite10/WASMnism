// Tier 2 — Cache-hit short-circuit (per benchmark_contract_tier2.md Section 7.3)
//
// Methodology:
//   1. Generate 1 unique payload P with ml:true
//   2. Send N_PRIME=2 POSTs of P → primes the cache (KV/DynamoDB)
//   3. Send N_HIT=20 identical POSTs of P → should all hit cache
//   4. Verify response.cache.hit == true for ≥ 19 of 20 hits (≥ 95%)
//   5. Report p50, p95, p99 of http_req_duration across the 20 hits
//
// Why N_PRIME=2:
//   First call always misses (computes verdict, writes cache). Second call MAY
//   miss if the cache write hasn't propagated (Spin KV is eventually consistent).
//   Two primes guarantee third+ call sees the cache.
//
// Endpoint: POST /api/clip/moderate (full pipeline includes cache lookup)
//
// Env vars:
//   GATEWAY_URL    — required; base URL of platform under test
//   N_PRIME        — default 2
//   N_HIT          — default 20
//   PLATFORM       — optional label ("akamai-ml" | "lambda-ml")

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";

const errorRate = new Rate("errors");
const cacheHitLatency = new Trend("cache_hit_latency_ms", true);
const cacheHitRate = new Rate("cache_hit_rate");
const cacheMissCounter = new Counter("cache_misses_during_hit_phase");

const BASE_URL =
  __ENV.GATEWAY_URL ||
  "https://f9318a6c-01e4-4f5b-995e-51894dfaf817.fwf.app";

const N_PRIME = parseInt(__ENV.N_PRIME || "2", 10);
const N_HIT = parseInt(__ENV.N_HIT || "20", 10);
const PLATFORM = __ENV.PLATFORM || "tier2";

// Unique-but-stable payload (per VU, per run). Using __VU lets multiple parallel
// runs avoid cross-contamination via cache.
const STABLE_TEXT_PER_VU = (vu) =>
  `cache-hit benchmark probe text vu=${vu} run=${Date.now() % 100000}`;

const headers = { "Content-Type": "application/json" };

export const options = {
  scenarios: {
    cacheHit: {
      executor: "per-vu-iterations",
      vus: 1,
      iterations: N_PRIME + N_HIT,
      maxDuration: "10m", // generous; usually < 1 min
    },
  },
  thresholds: {
    errors: ["rate<0.05"],
    "cache_hit_rate{phase:hit}": ["rate>=0.95"],
  },
};

export default function () {
  const text = STABLE_TEXT_PER_VU(__VU);
  const isPrime = __ITER < N_PRIME;
  const phase = isPrime ? "prime" : "hit";

  const payload = JSON.stringify({
    labels: ["safe", "unsafe"],
    nonce: `cache-hit-${PLATFORM}-${__VU}-${__ITER}`,
    text,
    ml: true,
  });

  const res = http.post(`${BASE_URL}/api/clip/moderate`, payload, {
    headers,
    tags: {
      scenario: "cache-hit",
      phase,
      platform: PLATFORM,
      iteration: String(__ITER),
    },
  });

  const passed = check(res, {
    "status is 200": (r) => r.status === 200,
  });
  errorRate.add(!passed);

  if (!isPrime) {
    cacheHitLatency.add(res.timings.duration, { phase: "hit" });

    try {
      const body = res.json();
      const hit = body && body.cache && body.cache.hit === true;
      cacheHitRate.add(hit, { phase: "hit" });
      if (!hit) {
        cacheMissCounter.add(1);
        console.warn(
          `[cache-hit iter=${__ITER}] CACHE MISS during hit phase! ` +
            `cache.hit=${body && body.cache ? body.cache.hit : "unknown"}`
        );
      }
    } catch (e) {
      cacheHitRate.add(false, { phase: "hit" });
    }
  }

  // Tiny inter-request gap so successive calls don't clobber each other on
  // platforms with eventually-consistent cache writes
  sleep(0.1);
}
