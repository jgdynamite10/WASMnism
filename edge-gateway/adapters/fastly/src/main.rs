use fastly::http::StatusCode;
use fastly::{ConfigStore, Error, KVStore, Request, Response};
use include_dir::{include_dir, Dir};
use uuid::Uuid;

use clipclap_gateway_core::{
    cache::CachedVerdict,
    error::{map_upstream_status, GatewayError},
    handlers,
    pipeline::{self, ModerationRequest},
    types::{ClassificationResponse, EchoRequest, ErrorBody, ErrorDetail, GatewayConfig},
};

static STATIC_DIR: Dir = include_dir!("$CARGO_MANIFEST_DIR/static");

const BACKEND_NAME: &str = "inference";
const CONFIG_STORE: &str = "gateway_config";
const KV_STORE: &str = "moderation_cache";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn config() -> GatewayConfig {
    let store = ConfigStore::open(CONFIG_STORE);
    GatewayConfig {
        platform: store
            .get("gateway_platform")
            .unwrap_or_else(|| "Fastly Compute".into()),
        region: store.get("gateway_region").unwrap_or_else(|| "unknown".into()),
    }
}

fn inference_url() -> Result<String, GatewayError> {
    let store = ConfigStore::open(CONFIG_STORE);
    store
        .get("inference_url")
        .ok_or_else(|| GatewayError::InternalError("INFERENCE_URL not configured".into()))
}

fn request_id() -> String {
    Uuid::new_v4().to_string()
}

fn json_ok(body: &impl serde::Serialize, rid: &str, cfg: &GatewayConfig) -> Response {
    json_resp(200, body, rid, cfg)
}

fn json_resp(status: u16, body: &impl serde::Serialize, rid: &str, cfg: &GatewayConfig) -> Response {
    let bytes = serde_json::to_vec(body).unwrap_or_default();
    Response::from_status(StatusCode::from_u16(status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR))
        .with_header("content-type", "application/json")
        .with_header("x-gateway-platform", &cfg.platform)
        .with_header("x-gateway-region", &cfg.region)
        .with_header("x-gateway-request-id", rid)
        .with_body(bytes)
}

fn error_resp(err: &GatewayError, rid: &str, cfg: &GatewayConfig) -> Response {
    json_resp(err.status_code(), &err.to_error_body(), rid, cfg)
}

fn parse_moderation_request(body: &[u8]) -> Result<ModerationRequest, GatewayError> {
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

fn kv_get(hash: &str) -> Option<CachedVerdict> {
    let store = KVStore::open(KV_STORE).ok()??;
    let mut lookup = store.lookup(hash).ok()?;
    let body = lookup.take_body();
    let bytes = body.into_bytes();
    CachedVerdict::from_bytes(&bytes)
}

fn kv_put(hash: &str, verdict: &CachedVerdict) {
    if let Ok(Some(store)) = KVStore::open(KV_STORE) {
        let _ = store.insert(hash, verdict.to_bytes());
    }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

#[fastly::main]
fn main(req: Request) -> Result<Response, Error> {
    let path = req.get_path().to_string();
    let method = req.get_method_str().to_uppercase();

    match (method.as_str(), path.as_str()) {
        ("GET", "/gateway/health") => Ok(handle_health()),
        ("POST", "/gateway/echo") => Ok(handle_echo(req)),
        ("POST", "/gateway/mock-classify") => Ok(handle_mock_classify(req)),
        ("POST", "/gateway/moderate") => Ok(handle_moderate(req)),
        ("POST", "/gateway/moderate-cached") => Ok(handle_moderate_cached(req)),
        ("POST", "/api/clip/moderate") => Ok(handle_full_moderate(req)),
        ("POST", "/api/clip/classify") | ("POST", "/api/clap/classify") => Ok(handle_proxy(req)),
        ("GET", _) => Ok(handle_static(&path)),
        _ => Ok(handle_not_found()),
    }
}

// ---------------------------------------------------------------------------
// Gateway-only handlers
// ---------------------------------------------------------------------------

fn handle_health() -> Response {
    let cfg = config();
    let rid = request_id();
    json_ok(&handlers::health(&cfg), &rid, &cfg)
}

fn handle_echo(mut req: Request) -> Response {
    let cfg = config();
    let rid = request_id();

    let body = req.take_body().into_bytes();
    let echo_req: EchoRequest = match serde_json::from_slice(&body) {
        Ok(r) => r,
        Err(e) => {
            let err = GatewayError::BadRequest(format!("Invalid JSON: {e}"));
            return error_resp(&err, &rid, &cfg);
        }
    };

    if echo_req.labels.is_empty() || echo_req.labels.len() > 1000 {
        let err = GatewayError::BadRequest("labels must contain 1-1000 items".into());
        return error_resp(&err, &rid, &cfg);
    }
    if echo_req.nonce.len() > 256 {
        let err = GatewayError::BadRequest("nonce must be <=256 characters".into());
        return error_resp(&err, &rid, &cfg);
    }

    json_ok(&handlers::echo(&echo_req, &cfg, &rid), &rid, &cfg)
}

fn handle_mock_classify(mut req: Request) -> Response {
    let cfg = config();
    let rid = request_id();

    let body = req.take_body().into_bytes();
    let parsed: EchoRequest = match serde_json::from_slice(&body) {
        Ok(r) => r,
        Err(e) => {
            let err = GatewayError::BadRequest(format!("Invalid JSON: {e}"));
            return error_resp(&err, &rid, &cfg);
        }
    };

    if parsed.labels.is_empty() || parsed.labels.len() > 1000 {
        let err = GatewayError::BadRequest("labels must contain 1-1000 items".into());
        return error_resp(&err, &rid, &cfg);
    }

    json_ok(&handlers::mock_classify(&parsed.labels), &rid, &cfg)
}

// ---------------------------------------------------------------------------
// Mode 1: Policy-Only (POST /gateway/moderate)
// ---------------------------------------------------------------------------

fn handle_moderate(mut req: Request) -> Response {
    let cfg = config();
    let rid = request_id();

    let body = req.take_body().into_bytes();
    let mod_req = match parse_moderation_request(&body) {
        Ok(r) => r,
        Err(err) => return error_resp(&err, &rid, &cfg),
    };

    let resp = pipeline::moderate_policy_only(&mod_req, &cfg, &rid, None, None);
    json_ok(&resp, &rid, &cfg)
}

// ---------------------------------------------------------------------------
// Mode 2: Cached Hit (POST /gateway/moderate-cached)
// ---------------------------------------------------------------------------

fn handle_moderate_cached(mut req: Request) -> Response {
    let cfg = config();
    let rid = request_id();

    let body = req.take_body().into_bytes();
    let mod_req = match parse_moderation_request(&body) {
        Ok(r) => r,
        Err(err) => return error_resp(&err, &rid, &cfg),
    };

    let normalized = clipclap_gateway_core::normalize::normalize_labels(&mod_req.labels);
    let hash = clipclap_gateway_core::hash::content_hash(&normalized, None);
    let cached = kv_get(&hash);
    let was_miss = cached.is_none();

    let resp = pipeline::moderate_cached(&mod_req, cached.as_ref(), &cfg, &rid, None);

    if was_miss {
        let cv = CachedVerdict::new(
            hash,
            clipclap_gateway_core::policy::PolicyResult {
                verdict: resp.verdict.clone(),
                flags: vec![],
                blocked_terms: resp.moderation.blocked_terms.clone(),
                confidence: resp.moderation.confidence,
                processing_ms: resp.moderation.processing_ms,
            },
            resp.classification.clone(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64,
        );
        kv_put(&cv.hash, &cv);
    }

    json_ok(&resp, &rid, &cfg)
}

// ---------------------------------------------------------------------------
// Mode 3: Full Pipeline (POST /api/clip/moderate)
// ---------------------------------------------------------------------------

fn handle_full_moderate(mut req: Request) -> Response {
    let cfg = config();
    let rid = request_id();

    let content_type = req
        .get_header_str("content-type")
        .unwrap_or("")
        .to_string();

    let raw_body = req.take_body().into_bytes();

    let labels = match extract_labels_from_body(&content_type, &raw_body) {
        Ok(l) => l,
        Err(msg) => {
            let err = GatewayError::BadRequest(msg);
            return error_resp(&err, &rid, &cfg);
        }
    };

    if labels.is_empty() || labels.len() > 1000 {
        let err = GatewayError::BadRequest("labels must contain 1-1000 items".into());
        return error_resp(&err, &rid, &cfg);
    }

    let mod_req = ModerationRequest {
        labels,
        nonce: rid.clone(),
        text: None,
        ml: false,
    };

    let pre = pipeline::pre_moderate(&mod_req, None);

    if let Some(cached) = kv_get(&pre.hash) {
        let resp = pipeline::moderate_cached(&mod_req, Some(&cached), &cfg, &rid, None);
        return json_ok(&resp, &rid, &cfg);
    }

    if pre.is_blocked() {
        let resp = pipeline::blocked_response(&pre, &cfg, &rid);
        return json_ok(&resp, &rid, &cfg);
    }

    let base_url = match inference_url() {
        Ok(url) => url,
        Err(err) => return error_resp(&err, &rid, &cfg),
    };

    let upstream_uri = format!("{}/api/clip/classify", base_url.trim_end_matches('/'));

    let outbound = Request::post(&upstream_uri)
        .with_header("content-type", &content_type)
        .with_header("x-request-id", &rid)
        .with_body(raw_body);

    let mut upstream_resp = match outbound.send(BACKEND_NAME) {
        Ok(resp) => resp,
        Err(_) => {
            let err = GatewayError::UpstreamUnreachable("Failed to reach inference service".into());
            return error_resp(&err, &rid, &cfg);
        }
    };

    let status = upstream_resp.get_status().as_u16();
    let resp_body = upstream_resp.take_body().into_bytes();

    let body_preview = String::from_utf8_lossy(&resp_body[..resp_body.len().min(256)]);
    if let Err(err) = map_upstream_status(status, &body_preview) {
        return error_resp(&err, &rid, &cfg);
    }

    let classification: ClassificationResponse = match serde_json::from_slice(&resp_body) {
        Ok(c) => c,
        Err(e) => {
            let err = GatewayError::UpstreamError(Some(status), format!("Bad upstream JSON: {e}"));
            return error_resp(&err, &rid, &cfg);
        }
    };

    let (resp, cached_verdict) = pipeline::post_moderate(&pre, &classification, &cfg, &rid);
    kv_put(&pre.hash, &cached_verdict);

    json_ok(&resp, &rid, &cfg)
}

// ---------------------------------------------------------------------------
// Legacy proxy handler
// ---------------------------------------------------------------------------

fn handle_proxy(mut req: Request) -> Response {
    let cfg = config();
    let rid = request_id();

    let base_url = match inference_url() {
        Ok(url) => url,
        Err(err) => return error_resp(&err, &rid, &cfg),
    };

    let path = req.get_path().to_string();
    let upstream_uri = format!("{}{}", base_url.trim_end_matches('/'), path);

    let content_type = req
        .get_header_str("content-type")
        .unwrap_or("application/octet-stream")
        .to_string();

    let fwd_rid = req
        .get_header_str("x-request-id")
        .unwrap_or(&rid)
        .to_string();

    let body = req.take_body().into_bytes();

    let outbound = Request::post(&upstream_uri)
        .with_header("content-type", &content_type)
        .with_header("x-request-id", &fwd_rid)
        .with_body(body);

    let mut upstream_resp = match outbound.send(BACKEND_NAME) {
        Ok(resp) => resp,
        Err(_) => {
            let err = GatewayError::UpstreamUnreachable("Failed to reach inference service".into());
            return error_resp(&err, &rid, &cfg);
        }
    };

    let status = upstream_resp.get_status().as_u16();
    let resp_body = upstream_resp.take_body().into_bytes();

    let body_preview = String::from_utf8_lossy(&resp_body[..resp_body.len().min(256)]);
    if let Err(err) = map_upstream_status(status, &body_preview) {
        return error_resp(&err, &rid, &cfg);
    }

    Response::from_status(StatusCode::OK)
        .with_header("content-type", "application/json")
        .with_header("x-gateway-platform", &cfg.platform)
        .with_header("x-gateway-region", &cfg.region)
        .with_header("x-gateway-request-id", &rid)
        .with_body(resp_body)
}

// ---------------------------------------------------------------------------
// Static file serving (embedded frontend)
// ---------------------------------------------------------------------------

fn content_type_for(path: &str) -> &'static str {
    match path.rsplit('.').next().unwrap_or("") {
        "html" => "text/html; charset=utf-8",
        "js" => "application/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "ico" => "image/x-icon",
        "json" => "application/json",
        "woff2" => "font/woff2",
        "woff" => "font/woff",
        _ => "application/octet-stream",
    }
}

fn handle_static(path: &str) -> Response {
    let file_path = match path {
        "/" | "" => "index.html",
        p => p.trim_start_matches('/'),
    };

    if let Some(file) = STATIC_DIR.get_file(file_path) {
        let ct = content_type_for(file_path);
        let mut resp = Response::from_status(StatusCode::OK)
            .with_header("content-type", ct)
            .with_body(file.contents());
        if file_path.starts_with("assets/") {
            resp.set_header("cache-control", "public, max-age=31536000, immutable");
        }
        resp
    } else if let Some(file) = STATIC_DIR.get_file("index.html") {
        // SPA fallback: serve index.html for unmatched paths
        Response::from_status(StatusCode::OK)
            .with_header("content-type", "text/html; charset=utf-8")
            .with_body(file.contents())
    } else {
        handle_not_found()
    }
}

// ---------------------------------------------------------------------------
// Catch-all
// ---------------------------------------------------------------------------

fn handle_not_found() -> Response {
    let cfg = config();
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
// Multipart/JSON label extraction (shared with Spin adapter)
// ---------------------------------------------------------------------------

fn extract_labels_from_body(content_type: &str, body: &[u8]) -> Result<Vec<String>, String> {
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

fn extract_labels_from_multipart(content_type: &str, body: &[u8]) -> Result<Vec<String>, String> {
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

fn parse_labels_string(s: &str) -> Result<Vec<String>, String> {
    if let Ok(arr) = serde_json::from_str::<Vec<String>>(s) {
        return Ok(arr);
    }
    Ok(s.split(',')
        .map(|l| l.trim().to_string())
        .filter(|l| !l.is_empty())
        .collect())
}
