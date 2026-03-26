use std::{net::SocketAddr, sync::Arc};

use axum::{
    body::Bytes,
    extract::{Path, State},
    http::{header, HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Router,
};
use dashmap::DashMap;
use tower_http::cors::{Any, CorsLayer};
use tower_http::services::{ServeDir, ServeFile};
use uuid::Uuid;

use clipclap_gateway_core::{
    cache::CachedVerdict,
    error::{map_upstream_status, GatewayError},
    handlers,
    hash::image_hash,
    pipeline::{self, ModerationRequest},
    policy::PolicyConfig,
    types::{ClassificationResponse, EchoRequest, GatewayConfig},
};

// ---------------------------------------------------------------------------
// Application state
// ---------------------------------------------------------------------------

#[derive(Clone)]
struct AppState {
    config: GatewayConfig,
    inference_url: String,
    http_client: reqwest::Client,
    kv: Arc<DashMap<String, Vec<u8>>>,
}

impl AppState {
    fn request_id(&self) -> String {
        Uuid::new_v4().to_string()
    }

    fn kv_get(&self, hash: &str) -> Option<CachedVerdict> {
        let data = self.kv.get(hash)?;
        CachedVerdict::from_bytes(data.value())
    }

    fn kv_put(&self, hash: &str, verdict: &CachedVerdict) {
        self.kv.insert(hash.to_string(), verdict.to_bytes());
    }

    fn kv_is_blocklisted(&self, img_hash: &str) -> bool {
        self.kv.contains_key(img_hash)
    }

    fn kv_blocklist_image(&self, img_hash: &str) {
        self.kv.insert(img_hash.to_string(), b"blocked".to_vec());
    }
}

// ---------------------------------------------------------------------------
// JSON response helpers
// ---------------------------------------------------------------------------

fn json_response(status: StatusCode, body: &impl serde::Serialize, rid: &str, cfg: &GatewayConfig) -> Response {
    let bytes = serde_json::to_vec(body).unwrap_or_default();
    (
        status,
        [
            (header::CONTENT_TYPE, "application/json".to_string()),
            (header::HeaderName::from_static("x-gateway-platform"), cfg.platform.clone()),
            (header::HeaderName::from_static("x-gateway-region"), cfg.region.clone()),
            (header::HeaderName::from_static("x-gateway-request-id"), rid.to_string()),
        ],
        bytes,
    )
        .into_response()
}

fn json_ok(body: &impl serde::Serialize, rid: &str, cfg: &GatewayConfig) -> Response {
    json_response(StatusCode::OK, body, rid, cfg)
}

fn error_resp(err: &GatewayError, rid: &str, cfg: &GatewayConfig) -> Response {
    let status = StatusCode::from_u16(err.status_code()).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    json_response(status, &err.to_error_body(), rid, cfg)
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
// Handlers
// ---------------------------------------------------------------------------

async fn handle_health(State(state): State<AppState>) -> Response {
    let rid = state.request_id();
    json_ok(&handlers::health(&state.config), &rid, &state.config)
}

async fn handle_echo(State(state): State<AppState>, body: Bytes) -> Response {
    let rid = state.request_id();
    let cfg = &state.config;

    let echo_req: EchoRequest = match serde_json::from_slice(&body) {
        Ok(r) => r,
        Err(e) => return error_resp(&GatewayError::BadRequest(format!("Invalid JSON: {e}")), &rid, cfg),
    };

    if echo_req.labels.is_empty() || echo_req.labels.len() > 1000 {
        return error_resp(&GatewayError::BadRequest("labels must contain 1-1000 items".into()), &rid, cfg);
    }
    if echo_req.nonce.len() > 256 {
        return error_resp(&GatewayError::BadRequest("nonce must be <=256 characters".into()), &rid, cfg);
    }

    json_ok(&handlers::echo(&echo_req, cfg, &rid), &rid, cfg)
}

async fn handle_mock_classify(State(state): State<AppState>, body: Bytes) -> Response {
    let rid = state.request_id();
    let cfg = &state.config;

    let req: EchoRequest = match serde_json::from_slice(&body) {
        Ok(r) => r,
        Err(e) => return error_resp(&GatewayError::BadRequest(format!("Invalid JSON: {e}")), &rid, cfg),
    };

    if req.labels.is_empty() || req.labels.len() > 1000 {
        return error_resp(&GatewayError::BadRequest("labels must contain 1-1000 items".into()), &rid, cfg);
    }

    json_ok(&handlers::mock_classify(&req.labels), &rid, cfg)
}

// Mode 1: Policy-Only
async fn handle_moderate(State(state): State<AppState>, body: Bytes) -> Response {
    let rid = state.request_id();
    let cfg = &state.config;

    let mod_req = match parse_moderation_request(&body) {
        Ok(r) => r,
        Err(err) => return error_resp(&err, &rid, cfg),
    };

    let resp = pipeline::moderate_policy_only(&mod_req, cfg, &rid, None);
    json_ok(&resp, &rid, cfg)
}

// Mode 2: Cached Hit
async fn handle_moderate_cached(State(state): State<AppState>, body: Bytes) -> Response {
    let rid = state.request_id();
    let cfg = &state.config;

    let mod_req = match parse_moderation_request(&body) {
        Ok(r) => r,
        Err(err) => return error_resp(&err, &rid, cfg),
    };

    let normalized = clipclap_gateway_core::normalize::normalize_labels(&mod_req.labels);
    let hash = clipclap_gateway_core::hash::content_hash(&normalized, None);
    let cached = state.kv_get(&hash);

    let resp = pipeline::moderate_cached(&mod_req, cached.as_ref(), cfg, &rid, None);
    json_ok(&resp, &rid, cfg)
}

// Mode 3: Full Pipeline
async fn handle_full_moderate(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    let rid = state.request_id();
    let cfg = &state.config;
    let policy_config = PolicyConfig::default();

    let content_type = headers
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();

    let raw_body = body.to_vec();

    let labels = match extract_labels_from_body(&content_type, &raw_body) {
        Ok(l) => l,
        Err(msg) => return error_resp(&GatewayError::BadRequest(msg), &rid, cfg),
    };

    if labels.is_empty() || labels.len() > 1000 {
        return error_resp(&GatewayError::BadRequest("labels must contain 1-1000 items".into()), &rid, cfg);
    }

    let img_bytes = extract_image_from_multipart(&content_type, &raw_body);
    let text_field = extract_text_from_body(&content_type, &raw_body);

    // Image blocklist check
    if let Some(ref bytes) = img_bytes {
        let hash = image_hash(bytes);
        if state.kv_is_blocklisted(&hash) {
            let resp = pipeline::image_blocklisted_response(&hash, cfg, &rid);
            return json_ok(&resp, &rid, cfg);
        }
    }

    let mod_req = ModerationRequest {
        labels: labels.clone(),
        nonce: rid.clone(),
        text: text_field,
    };

    // Pre-moderation runs BEFORE cache lookup
    let pre = pipeline::pre_moderate(&mod_req, None);

    if pre.is_blocked() {
        let resp = pipeline::blocked_response(&pre, cfg, &rid);
        return json_ok(&resp, &rid, cfg);
    }

    if let Some(cached) = state.kv_get(&pre.hash) {
        let resp = pipeline::moderate_cached(&mod_req, Some(&cached), cfg, &rid, None);
        return json_ok(&resp, &rid, cfg);
    }

    // Augment labels with safety probes
    let augmented_labels = policy_config.augment_labels(&labels);

    // Build request to inference
    let upstream_uri = format!("{}/api/clip/classify", state.inference_url.trim_end_matches('/'));

    let fwd_result = if img_bytes.is_some() && content_type.contains("multipart") {
        let img = img_bytes.as_deref().unwrap();
        let labels_json = serde_json::to_string(&augmented_labels).unwrap_or_default();

        let form = reqwest::multipart::Form::new()
            .part(
                "image",
                reqwest::multipart::Part::bytes(img.to_vec())
                    .file_name("image.jpg")
                    .mime_str("application/octet-stream")
                    .unwrap(),
            )
            .text("labels", labels_json);

        state.http_client
            .post(&upstream_uri)
            .multipart(form)
            .header("x-request-id", &rid)
            .send()
            .await
    } else {
        state.http_client
            .post(&upstream_uri)
            .header("content-type", &content_type)
            .header("x-request-id", &rid)
            .body(raw_body)
            .send()
            .await
    };

    let upstream_resp = match fwd_result {
        Ok(r) => r,
        Err(_) => {
            return error_resp(
                &GatewayError::UpstreamUnreachable("Failed to reach inference service".into()),
                &rid,
                cfg,
            );
        }
    };

    let status = upstream_resp.status().as_u16();
    let resp_body = match upstream_resp.bytes().await {
        Ok(b) => b,
        Err(_) => {
            return error_resp(
                &GatewayError::UpstreamError(Some(status), "Failed to read upstream body".into()),
                &rid,
                cfg,
            );
        }
    };

    let body_preview = String::from_utf8_lossy(&resp_body[..resp_body.len().min(256)]);
    if let Err(err) = map_upstream_status(status, &body_preview) {
        return error_resp(&err, &rid, cfg);
    }

    let classification: ClassificationResponse = match serde_json::from_slice(&resp_body) {
        Ok(c) => c,
        Err(e) => {
            return error_resp(
                &GatewayError::UpstreamError(Some(status), format!("Bad upstream JSON: {e}")),
                &rid,
                cfg,
            );
        }
    };

    let (resp, cached_verdict) = pipeline::post_moderate(&pre, &classification, cfg, &rid);
    state.kv_put(&pre.hash, &cached_verdict);

    if resp.verdict == clipclap_gateway_core::policy::Verdict::Block {
        if let Some(ref bytes) = img_bytes {
            state.kv_blocklist_image(&image_hash(bytes));
        }
    }

    json_ok(&resp, &rid, cfg)
}

// ---------------------------------------------------------------------------
// Proxy handlers
// ---------------------------------------------------------------------------

async fn handle_proxy(
    State(state): State<AppState>,
    headers: HeaderMap,
    axum::extract::OriginalUri(uri): axum::extract::OriginalUri,
    body: Bytes,
) -> Response {
    let rid = state.request_id();
    let cfg = &state.config;

    let upstream_uri = format!(
        "{}{}",
        state.inference_url.trim_end_matches('/'),
        uri.path()
    );

    let content_type = headers
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("application/octet-stream")
        .to_string();

    let fwd_rid = headers
        .get("x-request-id")
        .and_then(|v| v.to_str().ok())
        .unwrap_or(&rid)
        .to_string();

    let result = state.http_client
        .post(&upstream_uri)
        .header("content-type", &content_type)
        .header("x-request-id", &fwd_rid)
        .body(body.to_vec())
        .send()
        .await;

    match result {
        Ok(resp) => {
            let status = resp.status().as_u16();
            let resp_body = resp.bytes().await.unwrap_or_default();

            let body_preview = String::from_utf8_lossy(&resp_body[..resp_body.len().min(256)]);
            if let Err(err) = map_upstream_status(status, &body_preview) {
                return error_resp(&err, &rid, cfg);
            }

            json_response(StatusCode::OK, &serde_json::from_slice::<serde_json::Value>(&resp_body).unwrap_or_default(), &rid, cfg)
        }
        Err(_) => error_resp(
            &GatewayError::UpstreamUnreachable("Failed to reach inference service".into()),
            &rid,
            cfg,
        ),
    }
}

async fn handle_api_health(State(state): State<AppState>) -> Response {
    let rid = state.request_id();
    let cfg = &state.config;

    let upstream_uri = format!("{}/api/health", state.inference_url.trim_end_matches('/'));

    match state.http_client.get(&upstream_uri).send().await {
        Ok(resp) => {
            let status = StatusCode::from_u16(resp.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
            let body = resp.bytes().await.unwrap_or_default();
            (
                status,
                [
                    (header::CONTENT_TYPE, "application/json".to_string()),
                    (header::HeaderName::from_static("x-gateway-platform"), cfg.platform.clone()),
                    (header::HeaderName::from_static("x-gateway-region"), cfg.region.clone()),
                    (header::HeaderName::from_static("x-gateway-request-id"), rid.clone()),
                ],
                body.to_vec(),
            )
                .into_response()
        }
        Err(_) => json_ok(
            &serde_json::json!({
                "status": "healthy",
                "platform": cfg.platform,
                "region": cfg.region,
                "gateway_only": true
            }),
            &rid,
            cfg,
        ),
    }
}

async fn handle_samples_proxy(
    State(state): State<AppState>,
    Path(path): Path<String>,
) -> Response {
    let rid = state.request_id();
    let cfg = &state.config;

    let upstream_uri = format!("{}/samples/{}", state.inference_url.trim_end_matches('/'), path);

    match state.http_client.get(&upstream_uri).send().await {
        Ok(resp) => {
            let status = StatusCode::from_u16(resp.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
            let ct = resp
                .headers()
                .get(header::CONTENT_TYPE)
                .and_then(|v| v.to_str().ok())
                .unwrap_or("application/octet-stream")
                .to_string();
            let body = resp.bytes().await.unwrap_or_default();
            (
                status,
                [
                    (header::CONTENT_TYPE, ct),
                    (header::HeaderName::from_static("access-control-allow-origin"), "*".to_string()),
                ],
                body.to_vec(),
            )
                .into_response()
        }
        Err(_) => error_resp(
            &GatewayError::UpstreamUnreachable("Failed to reach sample server".into()),
            &rid,
            cfg,
        ),
    }
}

// ---------------------------------------------------------------------------
// Multipart parsing (mirrors Spin adapter logic)
// ---------------------------------------------------------------------------

fn extract_labels_from_body(content_type: &str, body: &[u8]) -> Result<Vec<String>, String> {
    if content_type.contains("application/json") {
        let parsed: serde_json::Value =
            serde_json::from_slice(body).map_err(|e| format!("Invalid JSON: {e}"))?;
        let labels = parsed.get("labels").ok_or("Missing 'labels' field")?;
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
        let header_end = find_bytes(part, b"\r\n\r\n").or_else(|| find_bytes(part, b"\n\n"));
        let he = header_end?;

        let h = String::from_utf8_lossy(&part[..he]);
        if !h.contains("name=\"image\"") && !h.contains("name=image") {
            continue;
        }

        let body_offset = if part[he] == b'\r' { he + 4 } else { he + 2 };
        let content = &part[body_offset..];
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

fn find_bytes(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}

fn parse_labels_string(s: &str) -> Result<Vec<String>, String> {
    if let Ok(arr) = serde_json::from_str::<Vec<String>>(s) {
        return Ok(arr);
    }
    Ok(s.split(',').map(|l| l.trim().to_string()).filter(|l| !l.is_empty()).collect())
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let inference_url = std::env::var("INFERENCE_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:8000".into());
    let region = std::env::var("GATEWAY_REGION").unwrap_or_else(|_| "us-ord".into());
    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(3000);
    let static_dir = std::env::var("STATIC_DIR")
        .unwrap_or_else(|_| "/opt/gateway-native/static".into());

    let state = AppState {
        config: GatewayConfig {
            platform: "linode".into(),
            region,
        },
        inference_url,
        http_client: reqwest::Client::new(),
        kv: Arc::new(DashMap::new()),
    };

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    let static_service = ServeDir::new(&static_dir)
        .not_found_service(ServeFile::new(format!("{}/index.html", static_dir)));

    let app = Router::new()
        .route("/gateway/health", get(handle_health))
        .route("/gateway/echo", post(handle_echo))
        .route("/gateway/mock-classify", post(handle_mock_classify))
        .route("/gateway/moderate", post(handle_moderate))
        .route("/gateway/moderate-cached", post(handle_moderate_cached))
        .route("/api/clip/moderate", post(handle_full_moderate))
        .route("/api/clip/classify", post(handle_proxy))
        .route("/api/clap/classify", post(handle_proxy))
        .route("/api/health", get(handle_api_health))
        .route("/samples/{*path}", get(handle_samples_proxy))
        .fallback_service(static_service)
        .layer(cors)
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    tracing::info!("Native gateway listening on {addr}, static dir: {static_dir}");

    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
