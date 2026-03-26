use aws_sdk_dynamodb::Client as DynamoClient;
use aws_sdk_dynamodb::types::AttributeValue;
use lambda_http::{
    http::StatusCode, run, service_fn, Body, Error, Request, Response,
};
use std::env;
use uuid::Uuid;

use clipclap_gateway_core::{
    cache::CachedVerdict,
    error::{map_upstream_status, GatewayError},
    handlers,
    pipeline::{self, ModerationRequest},
    types::{ClassificationResponse, EchoRequest, ErrorBody, ErrorDetail, GatewayConfig},
};

const DYNAMO_TABLE: &str = "moderation-cache";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn config() -> GatewayConfig {
    GatewayConfig {
        platform: "lambda".into(),
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
            Ok(handle_proxy(&req).await)
        }
        _ => Ok(handle_not_found()),
    }
}

// ---------------------------------------------------------------------------
// Gateway-only handlers
// ---------------------------------------------------------------------------

fn handle_health() -> Response<Body> {
    let cfg = config();
    let rid = request_id();
    json_ok(&handlers::health(&cfg), &rid, &cfg)
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

    let resp = pipeline::moderate_policy_only(&mod_req, &cfg, &rid, None);
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

    let resp = pipeline::moderate_cached(&mod_req, cached.as_ref(), &cfg, &rid, None);
    json_ok(&resp, &rid, &cfg)
}

// ---------------------------------------------------------------------------
// Mode 3: Full Pipeline (POST /api/clip/moderate)
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

    let mod_req = ModerationRequest {
        labels,
        nonce: rid.clone(),
        text: None,
    };

    let pre = pipeline::pre_moderate(&mod_req, None);

    if let Some(cached) = dynamo_get(dynamo, &pre.hash).await {
        let resp = pipeline::moderate_cached(&mod_req, Some(&cached), &cfg, &rid, None);
        return json_ok(&resp, &rid, &cfg);
    }

    if pre.is_blocked() {
        let resp = pipeline::blocked_response(&pre, &cfg, &rid);
        return json_ok(&resp, &rid, &cfg);
    }

    let inference_url =
        env::var("INFERENCE_URL").unwrap_or_else(|_| "http://localhost:8000".into());
    let upstream_uri = format!("{}/api/clip/classify", inference_url.trim_end_matches('/'));

    let client = reqwest::Client::new();
    let upstream_resp = match client
        .post(&upstream_uri)
        .header("content-type", &content_type)
        .header("x-request-id", &rid)
        .body(raw_body)
        .send()
        .await
    {
        Ok(resp) => resp,
        Err(_) => {
            let err =
                GatewayError::UpstreamUnreachable("Failed to reach inference service".into());
            return error_resp(&err, &rid, &cfg);
        }
    };

    let status = upstream_resp.status().as_u16();
    let resp_body = upstream_resp.bytes().await.unwrap_or_default();

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
    dynamo_put(dynamo, &pre.hash, &cached_verdict).await;

    json_ok(&resp, &rid, &cfg)
}

// ---------------------------------------------------------------------------
// Legacy proxy handler
// ---------------------------------------------------------------------------

async fn handle_proxy(req: &Request) -> Response<Body> {
    let cfg = config();
    let rid = request_id();

    let inference_url =
        env::var("INFERENCE_URL").unwrap_or_else(|_| "http://localhost:8000".into());
    let path = req.uri().path();
    let upstream_uri = format!("{}{}", inference_url.trim_end_matches('/'), path);

    let content_type = req
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("application/octet-stream")
        .to_string();

    let fwd_rid = req
        .headers()
        .get("x-request-id")
        .and_then(|v| v.to_str().ok())
        .unwrap_or(&rid)
        .to_string();

    let body = req.body().as_ref().to_vec();

    let client = reqwest::Client::new();
    let upstream_resp = match client
        .post(&upstream_uri)
        .header("content-type", &content_type)
        .header("x-request-id", &fwd_rid)
        .body(body)
        .send()
        .await
    {
        Ok(resp) => resp,
        Err(_) => {
            let err =
                GatewayError::UpstreamUnreachable("Failed to reach inference service".into());
            return error_resp(&err, &rid, &cfg);
        }
    };

    let status = upstream_resp.status().as_u16();
    let resp_body = upstream_resp.bytes().await.unwrap_or_default();

    let body_preview = String::from_utf8_lossy(&resp_body[..resp_body.len().min(256)]);
    if let Err(err) = map_upstream_status(status, &body_preview) {
        return error_resp(&err, &rid, &cfg);
    }

    Response::builder()
        .status(200)
        .header("content-type", "application/json")
        .header("x-gateway-platform", &cfg.platform)
        .header("x-gateway-region", &cfg.region)
        .header("x-gateway-request-id", &rid)
        .body(Body::Binary(resp_body.to_vec()))
        .unwrap_or_else(|_| {
            Response::builder()
                .status(500)
                .body(Body::Empty)
                .unwrap()
        })
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
