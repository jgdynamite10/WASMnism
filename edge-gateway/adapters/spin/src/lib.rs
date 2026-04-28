use anyhow::Result;
use spin_sdk::{
    http::{IntoResponse, Params, Request, Response, Router},
    http_component,
    key_value::Store,
    variables,
};
use std::sync::OnceLock;
use uuid::Uuid;

use clipclap_gateway_core::{
    cache::CachedVerdict,
    error::GatewayError,
    handlers,
    hash::image_hash,
    pipeline::{self, ModerationRequest},
    toxicity::ToxicityClassifier,
    types::{EchoRequest, ErrorBody, ErrorDetail, GatewayConfig},
};

// ---------------------------------------------------------------------------
// ML model loading (lazy, gated by the `local_ml` Spin variable)
//
// Model loading is SKIPPED unless `local_ml = "true"` is explicitly set.
// Default is "false" so that the standard Tier-2 deployment (Spin → Lambda
// for inference) never pays the 50 MB disk-read + NNEF parse cost on each
// cold-start invocation. Set `local_ml = "true"` only for standalone
// deployments where Spin runs the classifier locally with no Lambda backend.
// ---------------------------------------------------------------------------

static CLASSIFIER: OnceLock<Option<ToxicityClassifier>> = OnceLock::new();
static CLASSIFIER_ERROR: OnceLock<Option<String>> = OnceLock::new();

fn local_ml_enabled() -> bool {
    variables::get("local_ml")
        .map(|v| v.eq_ignore_ascii_case("true") || v.trim() == "1")
        .unwrap_or(false)
}

fn get_classifier() -> Option<&'static ToxicityClassifier> {
    CLASSIFIER
        .get_or_init(|| {
            if !local_ml_enabled() {
                let _ = CLASSIFIER_ERROR.set(Some("disabled (local_ml != true)".into()));
                return None;
            }
            let model_bytes = match std::fs::read("/models/toxicity/model.nnef.tar") {
                Ok(b) => b,
                Err(e) => {
                    let msg = format!("model read: {e}");
                    let _ = CLASSIFIER_ERROR.set(Some(msg));
                    return None;
                }
            };
            let vocab = match std::fs::read_to_string("/models/toxicity/vocab.txt") {
                Ok(v) => v,
                Err(e) => {
                    let msg = format!("vocab read: {e}");
                    let _ = CLASSIFIER_ERROR.set(Some(msg));
                    return None;
                }
            };
            let msg = format!("model={} bytes, vocab={} lines", model_bytes.len(), vocab.lines().count());
            match ToxicityClassifier::from_nnef_tar(&model_bytes, &vocab) {
                Ok(c) => {
                    let _ = CLASSIFIER_ERROR.set(Some(format!("ok: {msg}")));
                    Some(c)
                }
                Err(e) => {
                    let _ = CLASSIFIER_ERROR.set(Some(format!("init failed ({msg}): {e}")));
                    None
                }
            }
        })
        .as_ref()
}

fn classifier_status() -> String {
    CLASSIFIER_ERROR
        .get()
        .and_then(|o| o.as_ref())
        .cloned()
        .unwrap_or_else(|| "not initialized".into())
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn config() -> GatewayConfig {
    GatewayConfig {
        platform: variables::get("gateway_platform").unwrap_or_else(|_| "spin".into()),
        region: variables::get("gateway_region").unwrap_or_else(|_| "unknown".into()),
    }
}

fn request_id() -> String {
    Uuid::new_v4().to_string()
}

fn json_ok(body: &impl serde::Serialize, rid: &str, cfg: &GatewayConfig) -> Response {
    json_resp(200, body, rid, cfg)
}

fn json_resp(status: u16, body: &impl serde::Serialize, rid: &str, cfg: &GatewayConfig) -> Response {
    let bytes = serde_json::to_vec(body).unwrap_or_default();
    Response::builder()
        .status(status)
        .header("content-type", "application/json")
        .header("x-gateway-platform", &cfg.platform)
        .header("x-gateway-region", &cfg.region)
        .header("x-gateway-request-id", rid)
        .body(bytes)
        .build()
}

fn error_resp(err: &GatewayError, rid: &str, cfg: &GatewayConfig) -> Response {
    json_resp(err.status_code(), &err.to_error_body(), rid, cfg)
}

fn parse_moderation_request(req: &Request) -> Result<ModerationRequest, GatewayError> {
    let body: ModerationRequest = serde_json::from_slice(req.body())
        .map_err(|e| GatewayError::BadRequest(format!("Invalid JSON: {e}")))?;

    if body.labels.is_empty() || body.labels.len() > 1000 {
        return Err(GatewayError::BadRequest("labels must contain 1-1000 items".into()));
    }
    if body.nonce.len() > 256 {
        return Err(GatewayError::BadRequest("nonce must be <=256 characters".into()));
    }
    Ok(body)
}

// ---------------------------------------------------------------------------
// Spin KV cache helpers
// ---------------------------------------------------------------------------

fn kv_get(hash: &str) -> Option<CachedVerdict> {
    let store = Store::open_default().ok()?;
    let data = store.get(hash).ok()??;
    CachedVerdict::from_bytes(&data)
}

fn kv_put(hash: &str, verdict: &CachedVerdict) {
    if let Ok(store) = Store::open_default() {
        let _ = store.set(hash, &verdict.to_bytes());
    }
}

fn kv_is_blocklisted(img_hash: &str) -> bool {
    let Ok(store) = Store::open_default() else { return false };
    store.get(img_hash).ok().flatten().is_some()
}

fn kv_blocklist_image(img_hash: &str) {
    if let Ok(store) = Store::open_default() {
        let _ = store.set(img_hash, b"blocked");
    }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

#[http_component]
async fn handle(req: Request) -> Response {
    let mut router = Router::new();
    router.get("/gateway/health", handle_health);
    router.post("/gateway/echo", handle_echo);
    router.post("/gateway/mock-classify", handle_mock_classify);

    // Moderation endpoints
    router.post("/gateway/moderate", handle_moderate);
    router.post("/gateway/moderate-cached", handle_moderate_cached);
    router.post("/api/clip/moderate", handle_full_moderate);

    // Health (local — no upstream proxy needed for standalone Tier 2)
    router.get_async("/api/health", handle_api_health);

    router.any("/*", handle_not_found);
    router.handle_async(req).await
}

// ---------------------------------------------------------------------------
// Gateway-only handlers (unchanged)
// ---------------------------------------------------------------------------

fn handle_health(_req: Request, _params: Params) -> Result<impl IntoResponse> {
    let cfg = config();
    let rid = request_id();

    let model_exists = std::fs::metadata("/models/toxicity/model.nnef.tar").is_ok();
    let vocab_exists = std::fs::metadata("/models/toxicity/vocab.txt").is_ok();
    let already_loaded = CLASSIFIER.get().map(|o| o.is_some()).unwrap_or(false);

    let mut health = serde_json::to_value(&handlers::health(&cfg)).unwrap_or_default();
    if let Some(obj) = health.as_object_mut() {
        obj.insert("ml_model_file".into(), model_exists.into());
        obj.insert("ml_vocab_file".into(), vocab_exists.into());
        obj.insert("ml_classifier_ready".into(), already_loaded.into());
        obj.insert("ml_status".into(), classifier_status().into());
    }

    Ok(json_ok(&health, &rid, &cfg))
}

fn handle_echo(req: Request, _params: Params) -> Result<impl IntoResponse> {
    let cfg = config();
    let rid = request_id();

    let echo_req: EchoRequest = match serde_json::from_slice(req.body()) {
        Ok(r) => r,
        Err(e) => {
            let err = GatewayError::BadRequest(format!("Invalid JSON: {e}"));
            return Ok(error_resp(&err, &rid, &cfg));
        }
    };

    if echo_req.labels.is_empty() || echo_req.labels.len() > 1000 {
        let err = GatewayError::BadRequest("labels must contain 1-1000 items".into());
        return Ok(error_resp(&err, &rid, &cfg));
    }
    if echo_req.nonce.len() > 256 {
        let err = GatewayError::BadRequest("nonce must be <=256 characters".into());
        return Ok(error_resp(&err, &rid, &cfg));
    }

    Ok(json_ok(&handlers::echo(&echo_req, &cfg, &rid), &rid, &cfg))
}

fn handle_mock_classify(req: Request, _params: Params) -> Result<impl IntoResponse> {
    let cfg = config();
    let rid = request_id();

    let body: EchoRequest = match serde_json::from_slice(req.body()) {
        Ok(r) => r,
        Err(e) => {
            let err = GatewayError::BadRequest(format!("Invalid JSON: {e}"));
            return Ok(error_resp(&err, &rid, &cfg));
        }
    };

    if body.labels.is_empty() || body.labels.len() > 1000 {
        let err = GatewayError::BadRequest("labels must contain 1-1000 items".into());
        return Ok(error_resp(&err, &rid, &cfg));
    }

    Ok(json_ok(&handlers::mock_classify(&body.labels), &rid, &cfg))
}

// ---------------------------------------------------------------------------
// Mode 1: Policy-Only (POST /gateway/moderate)
// ---------------------------------------------------------------------------

fn handle_moderate(req: Request, _params: Params) -> Result<impl IntoResponse> {
    let cfg = config();
    let rid = request_id();

    let mod_req = match parse_moderation_request(&req) {
        Ok(r) => r,
        Err(err) => return Ok(error_resp(&err, &rid, &cfg)),
    };

    // Only load the Tract model when the request explicitly asks for ML scoring.
    let classifier = if mod_req.ml { get_classifier() } else { None };
    let resp = pipeline::moderate_policy_only(&mod_req, &cfg, &rid, None, classifier);
    Ok(json_ok(&resp, &rid, &cfg))
}

// ---------------------------------------------------------------------------
// Mode 2: Cached Hit (POST /gateway/moderate-cached)
// ---------------------------------------------------------------------------

fn handle_moderate_cached(req: Request, _params: Params) -> Result<impl IntoResponse> {
    let cfg = config();
    let rid = request_id();

    let mod_req = match parse_moderation_request(&req) {
        Ok(r) => r,
        Err(err) => return Ok(error_resp(&err, &rid, &cfg)),
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

    Ok(json_ok(&resp, &rid, &cfg))
}

// ---------------------------------------------------------------------------
// Mode 3: Full Pipeline with local ML (POST /api/clip/moderate)
//
// Runs the complete rules + Tract toxicity pipeline locally on Akamai
// Functions. No Lambda call — this is Tier 2 standalone.
//
// Flow:
//   1. Parse body (JSON or multipart); extract labels, text, optional image
//   2. Image blocklist check (instant KV lookup)
//   3. Rules pre-check; early-exit if blocked
//   4. KV cache lookup; early-exit on hit
//   5. Tract ML inference (model lazy-loads on first ML request via OnceLock)
//   6. Cache verdict; add image to blocklist if blocked
// ---------------------------------------------------------------------------

fn handle_full_moderate(req: Request, _params: Params) -> Result<impl IntoResponse> {
    let cfg = config();
    let rid = request_id();

    let content_type = req
        .header("content-type")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    let raw_body = req.into_body();

    let labels = match extract_labels_from_body(&content_type, &raw_body) {
        Ok(l) => l,
        Err(msg) => {
            let err = GatewayError::BadRequest(msg);
            return Ok(error_resp(&err, &rid, &cfg));
        }
    };

    if labels.is_empty() || labels.len() > 1000 {
        let err = GatewayError::BadRequest("labels must contain 1-1000 items".into());
        return Ok(error_resp(&err, &rid, &cfg));
    }

    let img_bytes = extract_image_from_multipart(&content_type, &raw_body);
    let text_field = extract_text_from_body(&content_type, &raw_body);

    // Image blocklist check (SHA-256 of image bytes → KV)
    if let Some(ref bytes) = img_bytes {
        let img_hash = image_hash(bytes);
        if kv_is_blocklisted(&img_hash) {
            let resp = pipeline::image_blocklisted_response(&img_hash, &cfg, &rid);
            return Ok(json_ok(&resp, &rid, &cfg));
        }
    }

    let mod_req = ModerationRequest {
        labels,
        nonce: rid.clone(),
        text: text_field,
        ml: true,
    };

    // Rules pre-check: fast early-exit before touching the ML model
    let pre = pipeline::pre_moderate(&mod_req, None);

    if pre.is_blocked() {
        let resp = pipeline::blocked_response(&pre, &cfg, &rid);
        return Ok(json_ok(&resp, &rid, &cfg));
    }

    // KV cache lookup
    if let Some(cached) = kv_get(&pre.hash) {
        let resp = pipeline::moderate_cached(&mod_req, Some(&cached), &cfg, &rid, None);
        return Ok(json_ok(&resp, &rid, &cfg));
    }

    // Full pipeline: rules + local Tract toxicity inference.
    // get_classifier() loads the NNEF model once per warm instance (OnceLock).
    let resp = pipeline::moderate_policy_only(&mod_req, &cfg, &rid, None, get_classifier());

    // Cache verdict
    let cv = clipclap_gateway_core::cache::CachedVerdict::new(
        pre.hash.clone(),
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
    kv_put(&pre.hash, &cv);

    // Add image to blocklist if this content is being blocked
    if resp.verdict == clipclap_gateway_core::policy::Verdict::Block {
        if let Some(ref bytes) = img_bytes {
            kv_blocklist_image(&image_hash(bytes));
        }
    }

    Ok(json_ok(&resp, &rid, &cfg))
}

/// Extract raw image bytes from a multipart body (looks for the "image" field).
fn extract_image_from_multipart(content_type: &str, body: &[u8]) -> Option<Vec<u8>> {
    if !content_type.contains("multipart/form-data") {
        return None;
    }
    let boundary = content_type.split("boundary=").nth(1)?.trim_matches('"');
    let delimiter = format!("--{boundary}");
    let delimiter_bytes = delimiter.as_bytes();

    let mut start = 0;
    let mut parts: Vec<(usize, usize)> = Vec::new();
    while let Some(pos) = find_bytes(&body[start..], delimiter_bytes) {
        if !parts.is_empty() {
            parts.last_mut().unwrap().1 = start + pos;
        }
        let part_start = start + pos + delimiter_bytes.len();
        parts.push((part_start, body.len()));
        start = part_start;
    }

    for (part_start, part_end) in &parts {
        let part = &body[*part_start..*part_end];
        let header_end = find_bytes(part, b"\r\n\r\n")
            .or_else(|| find_bytes(part, b"\n\n"));
        let Some(he) = header_end else { continue };

        let header = String::from_utf8_lossy(&part[..he]);
        if !header.contains("name=\"image\"") && !header.contains("name=image") {
            continue;
        }

        let body_offset = if part[he] == b'\r' { he + 4 } else { he + 2 };
        let content = &part[body_offset..];
        // Trim trailing \r\n before next boundary
        let trimmed = if content.ends_with(b"\r\n") {
            &content[..content.len() - 2]
        } else if content.ends_with(b"\n") {
            &content[..content.len() - 1]
        } else {
            content
        };
        return Some(trimmed.to_vec());
    }
    None
}

fn find_bytes(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}


/// Extract labels from either JSON body or multipart form data.
fn extract_labels_from_body(content_type: &str, body: &[u8]) -> Result<Vec<String>, String> {
    if content_type.contains("application/json") {
        let parsed: serde_json::Value = serde_json::from_slice(body)
            .map_err(|e| format!("Invalid JSON: {e}"))?;
        let labels = parsed.get("labels")
            .ok_or("Missing 'labels' field")?;
        if let Some(arr) = labels.as_array() {
            Ok(arr.iter().filter_map(|v| v.as_str().map(String::from)).collect())
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
        // Find the blank line separating headers from content
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

/// Extract optional "text" field from multipart or JSON body.
fn extract_text_from_body(content_type: &str, body: &[u8]) -> Option<String> {
    if content_type.contains("application/json") {
        let parsed: serde_json::Value = serde_json::from_slice(body).ok()?;
        parsed.get("text").and_then(|v| v.as_str()).map(String::from)
    } else if content_type.contains("multipart/form-data") {
        let boundary = content_type.split("boundary=").nth(1)?.trim_matches('"');
        let body_str = String::from_utf8_lossy(body);
        let delimiter = format!("--{boundary}");
        for part in body_str.split(&delimiter) {
            if !part.contains("name=\"text\"") && !part.contains("name=text") {
                continue;
            }
            if let Some(idx) = part.find("\r\n\r\n") {
                let value = part[idx + 4..].trim_end_matches("\r\n").trim();
                if !value.is_empty() {
                    return Some(value.to_string());
                }
            }
            if let Some(idx) = part.find("\n\n") {
                let value = part[idx + 2..].trim_end_matches('\n').trim();
                if !value.is_empty() {
                    return Some(value.to_string());
                }
            }
        }
        None
    } else {
        None
    }
}

fn parse_labels_string(s: &str) -> Result<Vec<String>, String> {
    if let Ok(arr) = serde_json::from_str::<Vec<String>>(s) {
        return Ok(arr);
    }
    Ok(s.split(',').map(|l| l.trim().to_string()).filter(|l| !l.is_empty()).collect())
}

// ---------------------------------------------------------------------------
// /api/health — proxy to inference service health endpoint
// ---------------------------------------------------------------------------

async fn handle_api_health(_req: Request, _params: Params) -> Result<impl IntoResponse> {
    let cfg = config();
    let rid = request_id();

    let inference_url = match variables::get("inference_url") {
        Ok(url) => url,
        Err(_) => {
            return Ok(json_ok(&handlers::health(&cfg), &rid, &cfg));
        }
    };

    let upstream_uri = format!("{}/api/health", inference_url.trim_end_matches('/'));
    let outbound = Request::get(&upstream_uri).build();

    let upstream_resp: Result<Response, _> = spin_sdk::http::send(outbound).await;
    match upstream_resp {
        Ok(resp) => {
            let status = *resp.status();
            let body = resp.into_body();
            Ok(Response::builder()
                .status(status)
                .header("content-type", "application/json")
                .header("x-gateway-platform", &cfg.platform)
                .header("x-gateway-region", &cfg.region)
                .header("x-gateway-request-id", &rid)
                .body(body)
                .build())
        }
        Err(_) => {
            Ok(json_ok(
                &serde_json::json!({
                    "status": "healthy",
                    "platform": cfg.platform,
                    "region": cfg.region,
                    "gateway_only": true
                }),
                &rid,
                &cfg,
            ))
        }
    }
}


// ---------------------------------------------------------------------------
// Catch-all
// ---------------------------------------------------------------------------

fn handle_not_found(_req: Request, _params: Params) -> Result<impl IntoResponse> {
    let cfg = config();
    let rid = request_id();
    Ok(json_resp(
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
    ))
}
