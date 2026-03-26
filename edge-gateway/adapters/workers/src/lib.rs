use worker::*;

use clipclap_gateway_core::{
    cache::CachedVerdict,
    error::{map_upstream_status, GatewayError},
    handlers,
    pipeline::{self, ModerationRequest},
    types::{ClassificationResponse, EchoRequest, ErrorBody, ErrorDetail, GatewayConfig},
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn get_config(env: &Env) -> GatewayConfig {
    GatewayConfig {
        platform: "workers".into(),
        region: env.var("GATEWAY_REGION").map(|v| v.to_string()).unwrap_or_else(|_| "unknown".into()),
    }
}

fn get_inference_url(env: &Env) -> Result<String> {
    env.var("INFERENCE_URL")
        .map(|v| v.to_string())
        .map_err(|_| Error::RustError("INFERENCE_URL not configured".into()))
}

fn request_id() -> String {
    uuid::Uuid::new_v4().to_string()
}

fn json_ok(body: &impl serde::Serialize, rid: &str, cfg: &GatewayConfig) -> Result<Response> {
    json_resp(200, body, rid, cfg)
}

fn json_resp(status: u16, body: &impl serde::Serialize, rid: &str, cfg: &GatewayConfig) -> Result<Response> {
    let bytes = serde_json::to_vec(body).unwrap_or_default();
    let mut resp = Response::from_bytes(bytes)?;
    let headers = resp.headers_mut();
    headers.set("content-type", "application/json")?;
    headers.set("x-gateway-platform", &cfg.platform)?;
    headers.set("x-gateway-region", &cfg.region)?;
    headers.set("x-gateway-request-id", rid)?;

    Ok(resp.with_status(status))
}

fn error_json(err: &GatewayError, rid: &str, cfg: &GatewayConfig) -> Result<Response> {
    json_resp(err.status_code(), &err.to_error_body(), rid, cfg)
}

fn parse_moderation_request(body: &[u8]) -> std::result::Result<ModerationRequest, GatewayError> {
    let req: ModerationRequest = serde_json::from_slice(body)
        .map_err(|e| GatewayError::BadRequest(format!("Invalid JSON: {e}")))?;

    if req.labels.is_empty() || req.labels.len() > 1000 {
        return Err(GatewayError::BadRequest("labels must contain 1-1000 items".into()));
    }
    if req.nonce.len() > 256 {
        return Err(GatewayError::BadRequest("nonce must be <=256 characters".into()));
    }
    Ok(req)
}

// ---------------------------------------------------------------------------
// KV cache helpers
// ---------------------------------------------------------------------------

async fn kv_get(env: &Env, hash: &str) -> Option<CachedVerdict> {
    let kv = env.kv("MODERATION_CACHE").ok()?;
    let bytes = kv.get(hash).bytes().await.ok()??;
    CachedVerdict::from_bytes(&bytes)
}

async fn kv_put(env: &Env, hash: &str, verdict: &CachedVerdict) {
    if let Ok(kv) = env.kv("MODERATION_CACHE") {
        let _ = kv.put_bytes(hash, &verdict.to_bytes())
            .map(|builder| builder.execute());
    }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

#[event(fetch)]
async fn main(req: Request, env: Env, _ctx: Context) -> Result<Response> {
    let path = req.path();
    let method = req.method().to_string();

    match (method.as_str(), path.as_str()) {
        ("GET", "/gateway/health") => handle_health(&env),
        ("POST", "/gateway/echo") => handle_echo(req, &env).await,
        ("POST", "/gateway/mock-classify") => handle_mock_classify(req, &env).await,
        ("POST", "/gateway/moderate") => handle_moderate(req, &env).await,
        ("POST", "/gateway/moderate-cached") => handle_moderate_cached(req, &env).await,
        ("POST", "/api/clip/moderate") => handle_full_moderate(req, &env).await,
        ("POST", "/api/clip/classify") | ("POST", "/api/clap/classify") => {
            handle_proxy(req, &env).await
        }
        _ => handle_not_found(&env),
    }
}

// ---------------------------------------------------------------------------
// Gateway-only handlers
// ---------------------------------------------------------------------------

fn handle_health(env: &Env) -> Result<Response> {
    let cfg = get_config(env);
    let rid = request_id();
    json_ok(&handlers::health(&cfg), &rid, &cfg)
}

async fn handle_echo(mut req: Request, env: &Env) -> Result<Response> {
    let cfg = get_config(env);
    let rid = request_id();

    let body = req.bytes().await?;
    let echo_req: EchoRequest = match serde_json::from_slice(&body) {
        Ok(r) => r,
        Err(e) => {
            let err = GatewayError::BadRequest(format!("Invalid JSON: {e}"));
            return error_json(&err, &rid, &cfg);
        }
    };

    if echo_req.labels.is_empty() || echo_req.labels.len() > 1000 {
        let err = GatewayError::BadRequest("labels must contain 1-1000 items".into());
        return error_json(&err, &rid, &cfg);
    }
    if echo_req.nonce.len() > 256 {
        let err = GatewayError::BadRequest("nonce must be <=256 characters".into());
        return error_json(&err, &rid, &cfg);
    }

    json_ok(&handlers::echo(&echo_req, &cfg, &rid), &rid, &cfg)
}

async fn handle_mock_classify(mut req: Request, env: &Env) -> Result<Response> {
    let cfg = get_config(env);
    let rid = request_id();

    let body = req.bytes().await?;
    let parsed: EchoRequest = match serde_json::from_slice(&body) {
        Ok(r) => r,
        Err(e) => {
            let err = GatewayError::BadRequest(format!("Invalid JSON: {e}"));
            return error_json(&err, &rid, &cfg);
        }
    };

    if parsed.labels.is_empty() || parsed.labels.len() > 1000 {
        let err = GatewayError::BadRequest("labels must contain 1-1000 items".into());
        return error_json(&err, &rid, &cfg);
    }

    json_ok(&handlers::mock_classify(&parsed.labels), &rid, &cfg)
}

// ---------------------------------------------------------------------------
// Mode 1: Policy-Only (POST /gateway/moderate)
// ---------------------------------------------------------------------------

async fn handle_moderate(mut req: Request, env: &Env) -> Result<Response> {
    let cfg = get_config(env);
    let rid = request_id();

    let body = req.bytes().await?;
    let mod_req = match parse_moderation_request(&body) {
        Ok(r) => r,
        Err(err) => return error_json(&err, &rid, &cfg),
    };

    let resp = pipeline::moderate_policy_only(&mod_req, &cfg, &rid, None);
    json_ok(&resp, &rid, &cfg)
}

// ---------------------------------------------------------------------------
// Mode 2: Cached Hit (POST /gateway/moderate-cached)
// ---------------------------------------------------------------------------

async fn handle_moderate_cached(mut req: Request, env: &Env) -> Result<Response> {
    let cfg = get_config(env);
    let rid = request_id();

    let body = req.bytes().await?;
    let mod_req = match parse_moderation_request(&body) {
        Ok(r) => r,
        Err(err) => return error_json(&err, &rid, &cfg),
    };

    let normalized = clipclap_gateway_core::normalize::normalize_labels(&mod_req.labels);
    let hash = clipclap_gateway_core::hash::content_hash(&normalized, None);
    let cached = kv_get(env, &hash).await;

    let resp = pipeline::moderate_cached(&mod_req, cached.as_ref(), &cfg, &rid, None);
    json_ok(&resp, &rid, &cfg)
}

// ---------------------------------------------------------------------------
// Mode 3: Full Pipeline (POST /api/clip/moderate)
// ---------------------------------------------------------------------------

async fn handle_full_moderate(mut req: Request, env: &Env) -> Result<Response> {
    let cfg = get_config(env);
    let rid = request_id();

    let content_type = req
        .headers()
        .get("content-type")
        .ok()
        .flatten()
        .unwrap_or_default();

    let raw_body = req.bytes().await?;

    let labels = match extract_labels_from_body(&content_type, &raw_body) {
        Ok(l) => l,
        Err(msg) => {
            let err = GatewayError::BadRequest(msg);
            return error_json(&err, &rid, &cfg);
        }
    };

    if labels.is_empty() || labels.len() > 1000 {
        let err = GatewayError::BadRequest("labels must contain 1-1000 items".into());
        return error_json(&err, &rid, &cfg);
    }

    let mod_req = ModerationRequest {
        labels,
        nonce: rid.clone(),
        text: None,
    };

    let pre = pipeline::pre_moderate(&mod_req, None);

    if let Some(cached) = kv_get(env, &pre.hash).await {
        let resp = pipeline::moderate_cached(&mod_req, Some(&cached), &cfg, &rid, None);
        return json_ok(&resp, &rid, &cfg);
    }

    if pre.is_blocked() {
        let resp = pipeline::blocked_response(&pre, &cfg, &rid);
        return json_ok(&resp, &rid, &cfg);
    }

    let base_url = match get_inference_url(env) {
        Ok(url) => url,
        Err(_) => {
            let err = GatewayError::InternalError("INFERENCE_URL not configured".into());
            return error_json(&err, &rid, &cfg);
        }
    };

    let upstream_uri = format!("{}/api/clip/classify", base_url.trim_end_matches('/'));

    let init = RequestInit::new();
    init.with_method(Method::Post);

    let headers = Headers::new();
    headers.set("content-type", &content_type)?;
    headers.set("x-request-id", &rid)?;
    init.with_headers(headers);
    init.with_body(Some(raw_body.into()));

    let upstream_req = Request::new_with_init(&upstream_uri, &init)?;
    let mut upstream_resp = Fetch::Request(upstream_req).send().await?;
    let status = upstream_resp.status_code();
    let resp_body = upstream_resp.bytes().await?;

    let body_preview = String::from_utf8_lossy(&resp_body[..resp_body.len().min(256)]);
    if let Err(err) = map_upstream_status(status, &body_preview) {
        return error_json(&err, &rid, &cfg);
    }

    let classification: ClassificationResponse = match serde_json::from_slice(&resp_body) {
        Ok(c) => c,
        Err(e) => {
            let err = GatewayError::UpstreamError(Some(status), format!("Bad upstream JSON: {e}"));
            return error_json(&err, &rid, &cfg);
        }
    };

    let (resp, cached_verdict) = pipeline::post_moderate(&pre, &classification, &cfg, &rid);
    kv_put(env, &pre.hash, &cached_verdict).await;

    json_ok(&resp, &rid, &cfg)
}

// ---------------------------------------------------------------------------
// Legacy proxy handler
// ---------------------------------------------------------------------------

async fn handle_proxy(mut req: Request, env: &Env) -> Result<Response> {
    let cfg = get_config(env);
    let rid = request_id();

    let base_url = match get_inference_url(env) {
        Ok(url) => url,
        Err(_) => {
            let err = GatewayError::InternalError("INFERENCE_URL not configured".into());
            return error_json(&err, &rid, &cfg);
        }
    };

    let path = req.path();
    let upstream_uri = format!("{}{}", base_url.trim_end_matches('/'), path);

    let content_type = req
        .headers()
        .get("content-type")
        .ok()
        .flatten()
        .unwrap_or_else(|| "application/octet-stream".into());

    let fwd_rid = req
        .headers()
        .get("x-request-id")
        .ok()
        .flatten()
        .unwrap_or_else(|| rid.clone());

    let body = req.bytes().await?;

    let init = RequestInit::new();
    init.with_method(Method::Post);

    let headers = Headers::new();
    headers.set("content-type", &content_type)?;
    headers.set("x-request-id", &fwd_rid)?;
    init.with_headers(headers);
    init.with_body(Some(body.into()));

    let upstream_req = Request::new_with_init(&upstream_uri, &init)?;
    let mut upstream_resp = Fetch::Request(upstream_req).send().await?;
    let status = upstream_resp.status_code();
    let resp_body = upstream_resp.bytes().await?;

    let body_preview = String::from_utf8_lossy(&resp_body[..resp_body.len().min(256)]);
    if let Err(err) = map_upstream_status(status, &body_preview) {
        return error_json(&err, &rid, &cfg);
    }

    let mut resp = Response::from_bytes(resp_body)?;
    let h = resp.headers_mut();
    h.set("content-type", "application/json")?;
    h.set("x-gateway-platform", &cfg.platform)?;
    h.set("x-gateway-region", &cfg.region)?;
    h.set("x-gateway-request-id", &rid)?;
    Ok(resp.with_status(200))
}

// ---------------------------------------------------------------------------
// Catch-all
// ---------------------------------------------------------------------------

fn handle_not_found(env: &Env) -> Result<Response> {
    let cfg = get_config(env);
    let rid = request_id();
    json_resp(
        404,
        &ErrorBody {
            error: ErrorDetail {
                code: "NOT_FOUND".into(),
                message: "Unknown endpoint".into(),
                upstream_status: None,
            },
        },
        &rid,
        &cfg,
    )
}

// ---------------------------------------------------------------------------
// Multipart/JSON label extraction
// ---------------------------------------------------------------------------

fn extract_labels_from_body(content_type: &str, body: &[u8]) -> std::result::Result<Vec<String>, String> {
    if content_type.contains("application/json") {
        let parsed: serde_json::Value =
            serde_json::from_slice(body).map_err(|e| format!("Invalid JSON: {e}"))?;
        let labels = parsed.get("labels").ok_or("Missing 'labels' field")?;
        if let Some(arr) = labels.as_array() {
            Ok(arr
                .iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect())
        } else if let Some(s) = labels.as_str() {
            parse_labels_string(s)
        } else {
            Err("'labels' must be an array or string".into())
        }
    } else if content_type.contains("multipart/form-data") {
        extract_labels_from_multipart(content_type, body)
    } else {
        Err(format!("Unsupported Content-Type: {content_type}"))
    }
}

fn extract_labels_from_multipart(
    content_type: &str,
    body: &[u8],
) -> std::result::Result<Vec<String>, String> {
    let boundary = content_type
        .split("boundary=")
        .nth(1)
        .ok_or("Missing multipart boundary")?
        .trim_matches('"')
        .to_string();

    let body_str = String::from_utf8_lossy(body);
    let delimiter = format!("--{boundary}");

    for part in body_str.split(&delimiter) {
        if !part.contains("name=\"labels\"") && !part.contains("name=labels") {
            continue;
        }
        if let Some(idx) = part.find("\r\n\r\n") {
            let value = part[idx + 4..].trim_end_matches("\r\n").trim();
            return parse_labels_string(value);
        }
        if let Some(idx) = part.find("\n\n") {
            let value = part[idx + 2..].trim_end_matches('\n').trim();
            return parse_labels_string(value);
        }
    }
    Err("No 'labels' field found in multipart body".into())
}

fn parse_labels_string(s: &str) -> std::result::Result<Vec<String>, String> {
    if let Ok(arr) = serde_json::from_str::<Vec<String>>(s) {
        return Ok(arr);
    }
    Ok(s.split(',')
        .map(|l| l.trim().to_string())
        .filter(|l| !l.is_empty())
        .collect())
}
