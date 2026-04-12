import http from "k6/http";
import { check, group, sleep } from "k6";
import { Counter } from "k6/metrics";

const BASE_URL =
  __ENV.GATEWAY_URL ||
  "https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app";

const scenariosPassed = new Counter("scenarios_passed");
const scenariosFailed = new Counter("scenarios_failed");

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    scenarios_failed: ["count==0"],
  },
};

const headers = { "Content-Type": "application/json" };

function moderate(labels, text) {
  const body = { labels, nonce: `validation-${Date.now()}` };
  if (text) {
    body.text = text;
  }
  return http.post(`${BASE_URL}/gateway/moderate`, JSON.stringify(body), {
    headers,
  });
}

function parseBody(res) {
  try {
    return JSON.parse(res.body);
  } catch {
    return null;
  }
}

function logResult(name, passed) {
  const icon = passed ? "PASS" : "FAIL";
  console.log(`  [${icon}] ${name}`);
  if (passed) {
    scenariosPassed.add(1);
  } else {
    scenariosFailed.add(1);
  }
}

export default function () {
  console.log(`\n=== Moderation Validation: ${BASE_URL} ===\n`);

  // S1: Clean input with text → allow
  const uniqueLabel = `bench_${Date.now()}`;
  group("S1: Clean input (allow)", function () {
    const res = moderate(
      ["cat", "dog", uniqueLabel],
      "A peaceful sunset over the mountains"
    );
    const body = parseBody(res);

    const passed =
      check(res, {
        "status 200": (r) => r.status === 200,
      }) &&
      check(body, {
        "verdict is allow": (b) => b && b.verdict === "allow",
        "no policy flags": (b) =>
          b &&
          Array.isArray(b.moderation.policy_flags) &&
          b.moderation.policy_flags.length === 0,
        "hash starts with sha256:": (b) =>
          b && b.cache.hash.startsWith("sha256:"),
        "processing_ms is non-negative": (b) =>
          b && b.moderation.processing_ms >= 0,
      });

    logResult("S1: Clean input → allow", passed);
  });

  sleep(0.5);

  // S2: XSS injection → block
  group("S2: Injection (block)", function () {
    const res = moderate(["<script>alert(1)</script>"]);
    const body = parseBody(res);

    const passed =
      check(res, {
        "status 200": (r) => r.status === 200,
      }) &&
      check(body, {
        "verdict is block": (b) => b && b.verdict === "block",
        "has injection_attempt flag": (b) =>
          b && b.moderation.policy_flags.includes("injection_attempt"),
      });

    logResult("S2: XSS injection → block", passed);
  });

  sleep(0.5);

  // S3: Prohibited terms → block
  group("S3: Prohibited terms (block)", function () {
    const res = moderate(["kill", "bomb", "cat"]);
    const body = parseBody(res);

    const passed =
      check(res, {
        "status 200": (r) => r.status === 200,
      }) &&
      check(body, {
        "verdict is block": (b) => b && b.verdict === "block",
        "has prohibited_term flag": (b) =>
          b && b.moderation.policy_flags.includes("prohibited_term"),
        "blocked_terms not empty": (b) =>
          b && b.moderation.blocked_terms.length > 0,
      });

    logResult("S3: Prohibited terms → block", passed);
  });

  sleep(0.5);

  // S4: PII email → review
  group("S4: PII email (review)", function () {
    const res = moderate(["cat", "dog"], "contact user@example.com");
    const body = parseBody(res);

    const passed =
      check(res, {
        "status 200": (r) => r.status === 200,
      }) &&
      check(body, {
        "verdict is review": (b) => b && b.verdict === "review",
        "has pii_detected flag": (b) =>
          b && b.moderation.policy_flags.includes("pii_detected"),
      });

    logResult("S4: PII email → review", passed);
  });

  sleep(0.5);

  // S5: PII phone → review
  group("S5: PII phone (review)", function () {
    const res = moderate(["cat"], "call 555-123-4567");
    const body = parseBody(res);

    const passed =
      check(res, {
        "status 200": (r) => r.status === 200,
      }) &&
      check(body, {
        "verdict is review": (b) => b && b.verdict === "review",
        "has pii_detected flag": (b) =>
          b && b.moderation.policy_flags.includes("pii_detected"),
      });

    logResult("S5: PII phone → review", passed);
  });

  sleep(0.5);

  // S6: Leetspeak evasion → block
  group("S6: Leetspeak evasion (block)", function () {
    const res = moderate(["h@t3", "k1ll"]);
    const body = parseBody(res);

    const passed =
      check(res, {
        "status 200": (r) => r.status === 200,
      }) &&
      check(body, {
        "verdict is block": (b) => b && b.verdict === "block",
        "has prohibited_term flag": (b) =>
          b && b.moderation.policy_flags.includes("prohibited_term"),
      });

    logResult("S6: Leetspeak evasion → block", passed);
  });

  sleep(0.5);

  // S7: SQL injection → block
  group("S7: SQL injection (block)", function () {
    const res = moderate(["cat'; DROP TABLE users;--"]);
    const body = parseBody(res);

    const passed =
      check(res, {
        "status 200": (r) => r.status === 200,
      }) &&
      check(body, {
        "verdict is block": (b) => b && b.verdict === "block",
        "has injection_attempt flag": (b) =>
          b && b.moderation.policy_flags.includes("injection_attempt"),
      });

    logResult("S7: SQL injection → block", passed);
  });

  sleep(0.5);

  // S8: Cache hit via /gateway/moderate-cached
  group("S8: Cache hit (allow)", function () {
    const cacheLabels = ["cat", "dog", uniqueLabel];
    const cacheBody = JSON.stringify({
      labels: cacheLabels,
      nonce: `cache-prime-${Date.now()}`,
    });

    http.post(`${BASE_URL}/gateway/moderate-cached`, cacheBody, { headers });
    sleep(1.0);

    const res = http.post(
      `${BASE_URL}/gateway/moderate-cached`,
      JSON.stringify({
        labels: cacheLabels,
        nonce: `cache-hit-${Date.now()}`,
      }),
      { headers }
    );
    const body = parseBody(res);

    const passed =
      check(res, {
        "status 200": (r) => r.status === 200,
      }) &&
      check(body, {
        "verdict is allow": (b) => b && b.verdict === "allow",
        "cache hit is true": (b) => b && b.cache.hit === true,
      });

    logResult("S8: Cache hit → allow", passed);
  });

  console.log("\n=== Validation complete (8 rule scenarios) ===\n");
}
