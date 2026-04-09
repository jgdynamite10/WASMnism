# TODO: Dynamic Region Detection

**Status:** Planned
**Priority:** Medium
**Context:** Currently `gateway_region` is a static label set at deploy time. All three edge platforms report "global (edge)" — accurate but not useful for debugging or per-request observability.

---

## Goal

Each platform adapter should detect and return the actual compute location that handled the request, without exposing sensitive infrastructure details.

## Per-Platform Implementation

### Cloudflare Workers

Workers exposes `request.cf.colo` — the IATA airport code of the PoP (e.g., `ORD`, `FRA`, `SIN`).

```rust
// In lib.rs, extract from the incoming Request
let colo = req.cf().map(|cf| cf.colo()).unwrap_or("unknown".into());
```

### Fastly Compute

Fastly provides geolocation via `fastly::geo::geo_lookup()` on the client IP, or the `server.datacenter` variable. The `x-served-by` response header also contains the PoP identifier.

```rust
// Fastly geo lookup on client IP
let geo = fastly::geo::geo_lookup(client_ip);
let datacenter = geo.map(|g| g.as_name().to_string()).unwrap_or("unknown".into());
```

Or parse from `x-served-by` header which Fastly auto-injects (e.g., `cache-chi-klot8100056-CHI` → `CHI`).

### Akamai Functions (Spin)

Akamai injects headers that reveal the compute region:
- `Akamai-Request-BC` → edge PoP city
- `Set-Cookie: akaalb_*` → compute backend (e.g., `fwf-dev-de-fra-2`)

These are on the *response* side. On the *request* side inside the WASM handler, Spin doesn't currently expose the compute region to the application. Options:
1. Parse the `akaalb` cookie from the incoming request (if Akamai sets it on the inbound path)
2. Request a Spin SDK feature to expose the compute region as a variable
3. Use the `x-envoy-upstream-service-time` header if available on inbound

### AWS Lambda

Lambda provides the `AWS_REGION` environment variable, which is already used:

```rust
let region = std::env::var("AWS_REGION").unwrap_or_else(|_| "unknown".into());
```

This is already dynamic (set by Lambda runtime), but Lambda is single-region so it always returns the deploy region (e.g., `us-east-1`).

### Fermyon Cloud

Fermyon Cloud is single-region (us-ord). No dynamic detection needed — the static label is accurate.

## Output Format

Return a consistent, non-sensitive region identifier:

```json
{
  "gateway": {
    "region": "ORD"       // IATA code for edge platforms
    "region": "us-east-1" // AWS region for Lambda
  }
}
```

## Security Considerations

- Do NOT expose internal infrastructure identifiers (e.g., `fwf-dev-de-fra-2`, `cache-chi-klot8100056-CHI`)
- Use standardized location codes (IATA airport codes or cloud region names)
- Do NOT expose client IP geolocation data
