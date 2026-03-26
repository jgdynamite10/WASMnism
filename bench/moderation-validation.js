import http from "k6/http";
import { check, group, sleep } from "k6";
import { Counter } from "k6/metrics";

const BASE_URL =
  __ENV.GATEWAY_URL ||
  "https://wasm-prompt-firewall-imjy4pe0.fermyon.app";
const IMAGE_PATH = __ENV.IMAGE_PATH || "fixtures/benchmark.jpg";

const scenariosPassed = new Counter("scenarios_passed");
const scenariosFailed = new Counter("scenarios_failed");

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    scenarios_failed: ["count==0"],
  },
};

const imageData = open(IMAGE_PATH, "b");

function moderate(labels, text) {
  const formData = {
    image: http.file(imageData, "benchmark.jpg", "image/jpeg"),
    labels: JSON.stringify(labels),
  };
  if (text) {
    formData.text = text;
  }
  return http.post(`${BASE_URL}/api/clip/moderate`, formData);
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

  // ---------------------------------------------------------------
  // Scenario 1: Clean input → allow
  // Use a timestamped label to avoid stale KV cache hits from prior runs
  // ---------------------------------------------------------------
  const uniqueLabel = `bench_${Date.now()}`;
  group("S1: Clean input (allow)", function () {
    const res = moderate(["cat", "dog", uniqueLabel]);
    const body = parseBody(res);

    const passed = check(res, {
      "status 200": (r) => r.status === 200,
    }) && check(body, {
      "verdict is allow": (b) => b && b.verdict === "allow",
      "no policy flags": (b) => b && Array.isArray(b.moderation.policy_flags) && b.moderation.policy_flags.length === 0,
      "safety_scores present": (b) => b && Array.isArray(b.moderation.safety_scores) && b.moderation.safety_scores.length > 0,
      "all safety scores below 0.50": (b) => {
        if (!b || !b.moderation.safety_scores) return false;
        return b.moderation.safety_scores.every((s) => s.score < 0.5);
      },
      "classification has results": (b) => b && b.classification && b.classification.results.length > 0,
      "hash starts with sha256:": (b) => b && b.cache.hash.startsWith("sha256:"),
    });

    logResult("S1: Clean input → allow", passed);
  });

  sleep(0.5);

  // ---------------------------------------------------------------
  // Scenario 2: XSS injection → block
  // ---------------------------------------------------------------
  group("S2: Injection (block)", function () {
    const res = moderate(["<script>alert(1)</script>"]);
    const body = parseBody(res);

    const passed = check(res, {
      "status 200": (r) => r.status === 200,
    }) && check(body, {
      "verdict is block": (b) => b && b.verdict === "block",
      "has injection_attempt flag": (b) =>
        b && b.moderation.policy_flags.includes("injection_attempt"),
      "classification absent (pre-check block)": (b) =>
        b && b.classification == null,
    });

    logResult("S2: XSS injection → block", passed);
  });

  sleep(0.5);

  // ---------------------------------------------------------------
  // Scenario 3: Prohibited terms → block
  // ---------------------------------------------------------------
  group("S3: Prohibited terms (block)", function () {
    const res = moderate(["kill", "bomb", "cat"]);
    const body = parseBody(res);

    const passed = check(res, {
      "status 200": (r) => r.status === 200,
    }) && check(body, {
      "verdict is block": (b) => b && b.verdict === "block",
      "has prohibited_term flag": (b) =>
        b && b.moderation.policy_flags.includes("prohibited_term"),
      "blocked_terms not empty": (b) =>
        b && b.moderation.blocked_terms.length > 0,
    });

    logResult("S3: Prohibited terms → block", passed);
  });

  sleep(0.5);

  // ---------------------------------------------------------------
  // Scenario 4: PII email → review
  // ---------------------------------------------------------------
  group("S4: PII email (review)", function () {
    const res = moderate(["cat", "dog"], "contact user@example.com");
    const body = parseBody(res);

    const passed = check(res, {
      "status 200": (r) => r.status === 200,
    }) && check(body, {
      "verdict is review": (b) => b && b.verdict === "review",
      "has pii_detected flag": (b) =>
        b && b.moderation.policy_flags.includes("pii_detected"),
    });

    logResult("S4: PII email → review", passed);
  });

  sleep(0.5);

  // ---------------------------------------------------------------
  // Scenario 5: PII phone → review
  // ---------------------------------------------------------------
  group("S5: PII phone (review)", function () {
    const res = moderate(["cat"], "call 555-123-4567");
    const body = parseBody(res);

    const passed = check(res, {
      "status 200": (r) => r.status === 200,
    }) && check(body, {
      "verdict is review": (b) => b && b.verdict === "review",
      "has pii_detected flag": (b) =>
        b && b.moderation.policy_flags.includes("pii_detected"),
    });

    logResult("S5: PII phone → review", passed);
  });

  sleep(0.5);

  // ---------------------------------------------------------------
  // Scenario 6: Leetspeak evasion → block
  // ---------------------------------------------------------------
  group("S6: Leetspeak evasion (block)", function () {
    const res = moderate(["h@t3", "k1ll"]);
    const body = parseBody(res);

    const passed = check(res, {
      "status 200": (r) => r.status === 200,
    }) && check(body, {
      "verdict is block": (b) => b && b.verdict === "block",
      "has prohibited_term flag": (b) =>
        b && b.moderation.policy_flags.includes("prohibited_term"),
    });

    logResult("S6: Leetspeak evasion → block", passed);
  });

  sleep(0.5);

  // ---------------------------------------------------------------
  // Scenario 7: SQL injection → block
  // ---------------------------------------------------------------
  group("S7: SQL injection (block)", function () {
    const res = moderate(["cat'; DROP TABLE users;--"]);
    const body = parseBody(res);

    const passed = check(res, {
      "status 200": (r) => r.status === 200,
    }) && check(body, {
      "verdict is block": (b) => b && b.verdict === "block",
      "has injection_attempt flag": (b) =>
        b && b.moderation.policy_flags.includes("injection_attempt"),
    });

    logResult("S7: SQL injection → block", passed);
  });

  sleep(0.5);

  // ---------------------------------------------------------------
  // Scenario 8: Cache hit (repeat of S1 with same unique label)
  // ---------------------------------------------------------------
  group("S8: Cache hit (allow)", function () {
    const res = moderate(["cat", "dog", uniqueLabel]);
    const body = parseBody(res);

    const passed = check(res, {
      "status 200": (r) => r.status === 200,
    }) && check(body, {
      "verdict is allow": (b) => b && b.verdict === "allow",
      "cache hit is true": (b) => b && b.cache.hit === true,
    });

    logResult("S8: Cache hit → allow", passed);
  });

  sleep(0.5);

  // ---------------------------------------------------------------
  // Scenario 9: Image NOT blocklisted after pre-check block
  //
  // S2 blocked at pre-check (injection), so the image hash should
  // NOT have been added to the blocklist. Re-uploading with clean
  // labels should succeed.
  // ---------------------------------------------------------------
  group("S9: Image not blocklisted after pre-check block", function () {
    const res = moderate(["sunrise", "mountain", "river"]);
    const body = parseBody(res);

    const passed = check(res, {
      "status 200": (r) => r.status === 200,
    }) && check(body, {
      "verdict is allow": (b) => b && b.verdict === "allow",
      "image_blocklisted is absent or false": (b) =>
        b && (!b.cache.image_blocklisted || b.cache.image_blocklisted === false),
    });

    logResult("S9: Image not blocklisted after pre-check block", passed);
  });

  console.log("\n=== Validation complete ===\n");
}
