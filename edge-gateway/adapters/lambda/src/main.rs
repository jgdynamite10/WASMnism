use aws_sdk_dynamodb::Client as DynamoClient;
use aws_sdk_dynamodb::types::AttributeValue;
use include_dir::{include_dir, Dir};
use lambda_http::{
    http::StatusCode, run, service_fn, Body, Error, Request, Response,
};
use std::env;
use std::sync::OnceLock;
use uuid::Uuid;

use clipclap_gateway_core::{
    cache::CachedVerdict,
    error::GatewayError,
    handlers,
    pipeline::{self, ModerationRequest},
    toxicity::ToxicityClassifier,
    types::{EchoRequest, ErrorBody, ErrorDetail, GatewayConfig},
};

static STATIC_DIR: Dir = include_dir!("$CARGO_MANIFEST_DIR/static");

const DYNAMO_TABLE: &str = "moderation-cache";

// ---------------------------------------------------------------------------
// ML model loading (lazy, survives across warm-start invocations)
// ---------------------------------------------------------------------------

static CLASSIFIER: OnceLock<Option<ToxicityClassifier>> = OnceLock::new();
static CLASSIFIER_ERROR: OnceLock<Option<String>> = OnceLock::new();

fn get_classifier() -> Option<&'static ToxicityClassifier> {
    CLASSIFIER
        .get_or_init(|| {
            let model_dir = env::var("ML_MODEL_PATH")
                .unwrap_or_else(|_| "/var/task/models/toxicity".into());

            let model_path = format!("{}/model.nnef.tar", model_dir);
            let vocab_path = format!("{}/vocab.txt", model_dir);

            let model_bytes = match std::fs::read(&model_path) {
                Ok(b) => b,
                Err(e) => {
                    let msg = format!("model read {model_path}: {e}");
                    let _ = CLASSIFIER_ERROR.set(Some(msg));
                    return None;
                }
            };
            let vocab = match std::fs::read_to_string(&vocab_path) {
                Ok(v) => v,
                Err(e) => {
                    let msg = format!("vocab read {vocab_path}: {e}");
                    let _ = CLASSIFIER_ERROR.set(Some(msg));
                    return None;
                }
            };
            let info = format!(
                "model={} bytes, vocab={} lines",
                model_bytes.len(),
                vocab.lines().count()
            );
            match ToxicityClassifier::from_nnef_tar(&model_bytes, &vocab) {
                Ok(c) => {
                    let _ = CLASSIFIER_ERROR.set(Some(format!("ok: {info}")));
                    Some(c)
                }
                Err(e) => {
                    let _ = CLASSIFIER_ERROR.set(Some(format!("init failed ({info}): {e}")));
                    None
                }
            }
        })
        .as_ref()
}

fn classifier_status() -> String {
    match CLASSIFIER_ERROR.get() {
        Some(Some(msg)) => msg.clone(),
        Some(None) => "not attempted".into(),
        None => "not loaded yet".into(),
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn config() -> GatewayConfig {
    GatewayConfig {
        platform: env::var("GATEWAY_PLATFORM").unwrap_or_else(|_| "AWS Lambda".into()),
        region: env::var("GATEWAY_REGION").unwrap_or_else(|_| "unknown".into()),
    }
}

fn request_id() -> String {
    Uuid::new_v4().to_string()
}

fn json_ok(body: &impl serde::Serialize, rid: &str, cfg: &GatewayConfig) -> Response<Body> {
    json_resp(200, body, rid, cfg)
}

fn json_resp(
    status: u16,
    body: &impl serde::Serialize,
    rid: &str,
    cfg: &GatewayConfig,
) -> Response<Body> {
    let bytes = serde_json::to_vec(body).unwrap_or_default();
    Response::builder()
        .status(StatusCode::from_u16(status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR))
        .header("content-type", "application/json")
        .header("x-gateway-platform", &cfg.platform)
        .header("x-gateway-region", &cfg.region)
        .header("x-gateway-request-id", rid)
        .body(Body::Binary(bytes))
        .unwrap_or_else(|_| {
            Response::builder()
                .status(500)
                .body(Body::Empty)
                .unwrap()
        })
}

fn error_resp(err: &GatewayError, rid: &str, cfg: &GatewayConfig) -> Response<Body> {
    json_resp(err.status_code(), &err.to_error_body(), rid, cfg)
}

fn parse_moderation_req(body: &[u8]) -> Result<ModerationRequest, GatewayError> {
    let req: ModerationRequest = serde_json::from_slice(body)
        .map_err(|e| GatewayError::BadRequest(format!("Invalid JSON: {e}")))?;
    if req.labels.is_empty() || req.labels.len() > 1000 {
        return Err(GatewayError::BadRequest(
            "labels must contain 1-1000 items".into(),
        ));
    }
    if req.nonce.len() > 256 {
        return Err(GatewayError::BadRequest(
            "nonce must be <=256 characters".into(),
        ));
    }
    Ok(req)
}

// ---------------------------------------------------------------------------
// DynamoDB cache helpers
// ---------------------------------------------------------------------------

async fn dynamo_get(client: &DynamoClient, hash: &str) -> Option<CachedVerdict> {
    let result = client
        .get_item()
        .table_name(DYNAMO_TABLE)
        .key("hash", AttributeValue::S(hash.to_string()))
        .send()
        .await
        .ok()?;

    let item = result.item()?;
    let data = item.get("data")?.as_s().ok()?;
    let bytes = data.as_bytes();
    CachedVerdict::from_bytes(bytes)
}

async fn dynamo_put(client: &DynamoClient, hash: &str, verdict: &CachedVerdict) {
    let data = String::from_utf8(verdict.to_bytes()).unwrap_or_default();
    let _ = client
        .put_item()
        .table_name(DYNAMO_TABLE)
        .item("hash", AttributeValue::S(hash.to_string()))
        .item("data", AttributeValue::S(data))
        .send()
        .await;
}

// ---------------------------------------------------------------------------
// Request handler
// ---------------------------------------------------------------------------

async fn handler(req: Request, dynamo: &DynamoClient) -> Result<Response<Body>, Error> {
    let path = req.uri().path().to_string();
    let method = req.method().as_str().to_uppercase();

    match (method.as_str(), path.as_str()) {
        ("GET", "/gateway/health") => Ok(handle_health()),
        ("POST", "/gateway/echo") => Ok(handle_echo(&req)),
        ("POST", "/gateway/mock-classify") => Ok(handle_mock_classify(&req)),
        ("POST", "/gateway/moderate") => Ok(handle_moderate(&req)),
        ("POST", "/gateway/moderate-cached") => Ok(handle_moderate_cached(&req, dynamo).await),
        ("POST", "/api/clip/moderate") => Ok(handle_full_moderate(&req, dynamo).await),
        ("POST", "/api/clip/classify") | ("POST", "/api/clap/classify") => {
            Ok(handle_clip_classify(&req))
        }
        ("GET", _) => Ok(handle_static(&path)),
        _ => Ok(handle_not_found()),
    }
}

// ---------------------------------------------------------------------------
// Gateway-only handlers
// ---------------------------------------------------------------------------

fn handle_health() -> Response<Body> {
    let cfg = config();
    let rid = request_id();

    let model_dir = env::var("ML_MODEL_PATH")
        .unwrap_or_else(|_| "/var/task/models/toxicity".into());
    let model_exists =
        std::fs::metadata(format!("{}/model.nnef.tar", model_dir)).is_ok();
    let vocab_exists =
        std::fs::metadata(format!("{}/vocab.txt", model_dir)).is_ok();
    let already_loaded = CLASSIFIER.get().map(|o| o.is_some()).unwrap_or(false);

    let mut health = serde_json::to_value(&handlers::health(&cfg)).unwrap_or_default();
    if let Some(obj) = health.as_object_mut() {
        obj.insert("ml_model_file".into(), model_exists.into());
        obj.insert("ml_vocab_file".into(), vocab_exists.into());
        obj.insert("ml_classifier_ready".into(), already_loaded.into());
        obj.insert("ml_status".into(), classifier_status().into());
    }

    json_ok(&health, &rid, &cfg)
}

fn handle_echo(req: &Request) -> Response<Body> {
    let cfg = config();
    let rid = request_id();

    let body = req.body().as_ref();
    let echo_req: EchoRequest = match serde_json::from_slice(body) {
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

fn handle_mock_classify(req: &Request) -> Response<Body> {
    let cfg = config();
    let rid = request_id();

    let body = req.body().as_ref();
    let parsed: EchoRequest = match serde_json::from_slice(body) {
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

fn handle_moderate(req: &Request) -> Response<Body> {
    let cfg = config();
    let rid = request_id();

    let body = req.body().as_ref();
    let mod_req = match parse_moderation_req(body) {
        Ok(r) => r,
        Err(err) => return error_resp(&err, &rid, &cfg),
    };

    // Only load the Tract model when the request explicitly asks for ML scoring.
    let classifier = if mod_req.ml { get_classifier() } else { None };
    let resp = pipeline::moderate_policy_only(&mod_req, &cfg, &rid, None, classifier);
    json_ok(&resp, &rid, &cfg)
}

// ---------------------------------------------------------------------------
// Mode 2: Cached Hit (POST /gateway/moderate-cached)
// ---------------------------------------------------------------------------

async fn handle_moderate_cached(req: &Request, dynamo: &DynamoClient) -> Response<Body> {
    let cfg = config();
    let rid = request_id();

    let body = req.body().as_ref();
    let mod_req = match parse_moderation_req(body) {
        Ok(r) => r,
        Err(err) => return error_resp(&err, &rid, &cfg),
    };

    let normalized = clipclap_gateway_core::normalize::normalize_labels(&mod_req.labels);
    let hash = clipclap_gateway_core::hash::content_hash(&normalized, None);
    let cached = dynamo_get(dynamo, &hash).await;
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
        dynamo_put(dynamo, &cv.hash, &cv).await;
    }

    json_ok(&resp, &rid, &cfg)
}

// ---------------------------------------------------------------------------
// Mode 3: Full Pipeline with local ML (POST /api/clip/moderate)
//
// Runs the complete rules + Tract toxicity pipeline locally on AWS Lambda.
// Standalone — no outbound inference call. Lambda is an independent Tier 2
// benchmark target; it does NOT call Akamai or any other service.
//
// Flow:
//   1. Parse body; extract labels and text
//   2. Rules pre-check; early-exit if blocked
//   3. DynamoDB cache lookup; early-exit on hit
//   4. Tract ML inference (model lazy-loads via OnceLock on first ML request)
//   5. Cache verdict to DynamoDB; return response
// ---------------------------------------------------------------------------

async fn handle_full_moderate(req: &Request, dynamo: &DynamoClient) -> Response<Body> {
    let cfg = config();
    let rid = request_id();

    let content_type = req
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();

    let raw_body = req.body().as_ref().to_vec();

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

    let text_field = extract_text_from_body(&content_type, &raw_body);

    // Read the `ml` flag from the request body.
    // JSON bodies: honour the caller's `"ml"` field; default true so existing
    // callers that omit the field still get ML inference.
    // Multipart bodies (image flows): always true.
    let ml_requested = extract_ml_flag(&content_type, &raw_body);

    let mod_req = ModerationRequest {
        labels,
        nonce: rid.clone(),
        text: text_field,
        ml: ml_requested,
    };

    // Rules pre-check: fast early-exit before touching the ML model
    let pre = pipeline::pre_moderate(&mod_req, None);

    if pre.is_blocked() {
        let resp = pipeline::blocked_response(&pre, &cfg, &rid);
        return json_ok(&resp, &rid, &cfg);
    }

    // DynamoDB cache lookup
    if let Some(cached) = dynamo_get(dynamo, &pre.hash).await {
        let resp = pipeline::moderate_cached(&mod_req, Some(&cached), &cfg, &rid, None);
        return json_ok(&resp, &rid, &cfg);
    }

    // Only load the Tract model when the request explicitly asks for ML.
    let classifier = if mod_req.ml { get_classifier() } else { None };
    let resp = pipeline::moderate_policy_only(&mod_req, &cfg, &rid, None, classifier);

    // Cache verdict to DynamoDB
    let cv = CachedVerdict::new(
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
    dynamo_put(dynamo, &pre.hash, &cv).await;

    json_ok(&resp, &rid, &cfg)
}

// ---------------------------------------------------------------------------
// POST /api/clip/classify — embedding-shaped scores for benchmarks (contract section 5.3)
// ---------------------------------------------------------------------------

/// Akamai Spin forwards multipart here for clip flows. Respond directly (no second upstream hop).
fn handle_clip_classify(req: &Request) -> Response<Body> {
    let cfg = config();
    let rid = request_id();

    let content_type = req
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();

    let raw_body = req.body().as_ref().to_vec();
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

    json_ok(&handlers::mock_classify(&labels), &rid, &cfg)
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

fn handle_static(path: &str) -> Response<Body> {
    let file_path = match path {
        "/" | "" => "index.html",
        p => p.trim_start_matches('/'),
    };

    if let Some(file) = STATIC_DIR.get_file(file_path) {
        let ct = content_type_for(file_path);
        let mut builder = Response::builder()
            .status(200)
            .header("content-type", ct);
        if file_path.starts_with("assets/") {
            builder = builder.header("cache-control", "public, max-age=31536000, immutable");
        }
        builder
            .body(Body::Binary(file.contents().to_vec()))
            .unwrap_or_else(|_| Response::builder().status(500).body(Body::Empty).unwrap())
    } else if let Some(file) = STATIC_DIR.get_file("index.html") {
        Response::builder()
            .status(200)
            .header("content-type", "text/html; charset=utf-8")
            .body(Body::Binary(file.contents().to_vec()))
            .unwrap_or_else(|_| Response::builder().status(500).body(Body::Empty).unwrap())
    } else {
        handle_not_found()
    }
}

// ---------------------------------------------------------------------------
// Catch-all
// ---------------------------------------------------------------------------

fn handle_not_found() -> Response<Body> {
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
// Multipart/JSON label extraction
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

fn extract_labels_from_multipart(
    content_type: &str,
    body: &[u8],
) -> Result<Vec<String>, String> {
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

/// Read the `ml` flag from the request body.
/// JSON: returns the value of `"ml"` if present, otherwise `true` (opt-in default).
/// Multipart bodies (image flows): always `true`.
fn extract_ml_flag(content_type: &str, body: &[u8]) -> bool {
    if content_type.contains("application/json") {
        serde_json::from_slice::<serde_json::Value>(body)
            .ok()
            .and_then(|v| v.get("ml").and_then(|m| m.as_bool()))
            .unwrap_or(true)
    } else {
        true
    }
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

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() -> Result<(), Error> {
    let aws_config = aws_config::load_from_env().await;
    let dynamo = DynamoClient::new(&aws_config);

    run(service_fn(|req: Request| {
        let dynamo_ref = &dynamo;
        async move { handler(req, dynamo_ref).await }
    }))
    .await
}
