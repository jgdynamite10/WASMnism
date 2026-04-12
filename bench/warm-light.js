import http from "k6/http";
import { check } from "k6";
import { Rate, Trend } from "k6/metrics";

const errorRate = new Rate("errors");
const latency = new Trend("warm_light_latency", true);

const BASE_URL = __ENV.GATEWAY_URL || "https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app";

export const options = {
  scenarios: {
    warmLight: {
      executor: "constant-vus",
      vus: 10,
      duration: "60s",
    },
  },
  thresholds: {
    errors: ["rate<0.01"],
  },
};

export default function () {
  const res = http.get(`${BASE_URL}/gateway/health`, {
    tags: { endpoint: "health" },
  });

  const passed = check(res, {
    "status is 200": (r) => r.status === 200,
    "has valid JSON": (r) => {
      try { return r.json().status === "healthy"; } catch { return false; }
    },
  });

  errorRate.add(!passed);
  latency.add(res.timings.duration);
}
