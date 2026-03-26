use serde::{Deserialize, Serialize};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use crate::cache::CachedVerdict;
use crate::handlers::mock_classify;
use crate::hash::content_hash;
use crate::normalize::normalize_labels;
use crate::policy::{self, merge_results, PolicyConfig, PolicyFlag, PolicyResult, Verdict};
use crate::toxicity::ToxicityClassifier;
use crate::types::{ClassificationResponse, GatewayConfig};

// ---------------------------------------------------------------------------
// Request / Response types for the moderation pipeline
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
pub struct ModerationRequest {
    pub labels: Vec<String>,
    pub nonce: String,
    #[serde(default)]
    pub text: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ModerationResponse {
    pub verdict: Verdict,
    pub moderation: ModerationInfo,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub classification: Option<ClassificationResponse>,
    pub cache: CacheInfo,
    pub gateway: GatewayResponseInfo,
}

#[derive(Debug, Clone, Serialize)]
pub struct ModerationInfo {
    pub policy_flags: Vec<String>,
    pub confidence: f64,
    pub blocked_terms: Vec<String>,
    pub processing_ms: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub safety_scores: Option<Vec<SafetyScore>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ml_toxicity: Option<ToxicityInfo>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ToxicityInfo {
    pub toxic: f64,
    pub severe_toxic: f64,
    pub inference_ms: f64,
    pub model: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct SafetyScore {
    pub label: String,
    pub score: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct CacheInfo {
    pub hit: bool,
    pub hash: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub image_blocklisted: Option<bool>,
}

#[derive(Debug, Clone, Serialize)]
pub struct GatewayResponseInfo {
    pub platform: String,
    pub region: String,
    pub request_id: String,
}

// ---------------------------------------------------------------------------
// Pre-moderation result (used by adapters for Mode 3 split)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct PreModerationResult {
    pub normalized_labels: Vec<String>,
    pub hash: String,
    pub pre_policy: PolicyResult,
    pub start_time: Instant,
    pub user_label_count: usize,
}

impl PreModerationResult {
    pub fn is_blocked(&self) -> bool {
        self.pre_policy.verdict == Verdict::Block
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn gateway_info(config: &GatewayConfig, request_id: &str) -> GatewayResponseInfo {
    GatewayResponseInfo {
        platform: config.platform.clone(),
        region: config.region.clone(),
        request_id: request_id.to_string(),
    }
}

fn policy_flag_strings(result: &PolicyResult) -> Vec<String> {
    result.flags.iter().map(|f| {
        serde_json::to_value(f)
            .ok()
            .and_then(|v| v.as_str().map(String::from))
            .unwrap_or_else(|| format!("{f:?}"))
    }).collect()
}

// ---------------------------------------------------------------------------
// Mode 1: Policy-Only (POST /gateway/moderate)
//
// Full pipeline with mock classification. No backend call.
// ---------------------------------------------------------------------------

pub fn moderate_policy_only(
    req: &ModerationRequest,
    config: &GatewayConfig,
    request_id: &str,
    content: Option<&[u8]>,
    classifier: Option<&ToxicityClassifier>,
) -> ModerationResponse {
    let start = Instant::now();
    let normalized = normalize_labels(&req.labels);
    let hash = content_hash(&normalized, content);

    let pre = policy::pre_check(&normalized, req.text.as_deref());

    // If rule-based check already blocks, skip ML inference to save compute
    let (ml_policy, ml_info) = if pre.verdict == Verdict::Block {
        (None, None)
    } else {
        run_ml_toxicity(classifier, req.text.as_deref(), &req.labels)
    };

    let mock_classification = mock_classify(&normalized);
    let policy_config = PolicyConfig::default();
    let post = policy::post_check(&mock_classification, &policy_config);

    let mut merged = merge_results(&pre, &post);
    if let Some(ref ml) = ml_policy {
        merged = merge_results(&merged, ml);
    }

    let total_ms = start.elapsed().as_secs_f64() * 1000.0;

    ModerationResponse {
        verdict: merged.verdict.clone(),
        moderation: ModerationInfo {
            policy_flags: policy_flag_strings(&merged),
            confidence: merged.confidence,
            blocked_terms: merged.blocked_terms.clone(),
            processing_ms: total_ms,
            safety_scores: None,
            ml_toxicity: ml_info,
        },
        classification: Some(mock_classification),
        cache: CacheInfo {
            hit: false,
            hash,
            image_blocklisted: None,
        },
        gateway: gateway_info(config, request_id),
    }
}

// ---------------------------------------------------------------------------
// Mode 2: Cached Hit (POST /gateway/moderate-cached)
//
// Normalize + hash + cache lookup. The adapter provides the cached data.
// ---------------------------------------------------------------------------

pub fn moderate_cached(
    req: &ModerationRequest,
    cached: Option<&CachedVerdict>,
    config: &GatewayConfig,
    request_id: &str,
    content: Option<&[u8]>,
) -> ModerationResponse {
    let start = Instant::now();
    let normalized = normalize_labels(&req.labels);
    let hash = content_hash(&normalized, content);

    if let Some(cv) = cached {
        let total_ms = start.elapsed().as_secs_f64() * 1000.0;
        return ModerationResponse {
            verdict: cv.verdict.clone(),
            moderation: ModerationInfo {
                policy_flags: policy_flag_strings(&cv.policy),
                confidence: cv.policy.confidence,
                blocked_terms: cv.policy.blocked_terms.clone(),
                processing_ms: total_ms,
                safety_scores: None,
                ml_toxicity: None,
            },
            classification: cv.classification.clone(),
            cache: CacheInfo { hit: true, hash, image_blocklisted: None },
            gateway: gateway_info(config, request_id),
        };
    }

    // Cache miss: fall back to policy-only (no ML classifier in cached mode)
    moderate_policy_only(req, config, request_id, content, None)
}

// ---------------------------------------------------------------------------
// Mode 3: Full Pipeline — split into pre + post for async proxy in between
// ---------------------------------------------------------------------------

/// Phase 1: normalize, hash, cache check, policy pre-check.
/// Returns the pre-moderation result for the adapter to decide whether to
/// proxy to the inference service.
pub fn pre_moderate(
    req: &ModerationRequest,
    content: Option<&[u8]>,
) -> PreModerationResult {
    let start = Instant::now();
    let user_label_count = req.labels.len();
    let normalized = normalize_labels(&req.labels);
    let hash = content_hash(&normalized, content);
    let pre_policy = policy::pre_check(&normalized, req.text.as_deref());

    PreModerationResult {
        normalized_labels: normalized,
        hash,
        pre_policy,
        start_time: start,
        user_label_count,
    }
}

/// Phase 2: apply post-check on classification results, build final response.
/// Called by the adapter after receiving the inference response.
///
/// Splits safety label results from user results, evaluates safety scores
/// independently, merges all policy results, and returns only user-visible
/// classification results in the response.
pub fn post_moderate(
    pre: &PreModerationResult,
    classification: &ClassificationResponse,
    config: &GatewayConfig,
    request_id: &str,
) -> (ModerationResponse, CachedVerdict) {
    let policy_config = PolicyConfig::default();

    // Separate safety label results from user label results
    let (user_classification, safety_results) =
        policy_config.split_safety_results(classification, pre.user_label_count);

    // Evaluate standard post-check on all results (catches user-supplied high-risk labels)
    let post = policy::post_check(classification, &policy_config);

    // Evaluate safety label scores independently
    let safety_policy = policy_config.check_safety_scores(&safety_results);

    // Merge all three: pre-check + post-check + safety check (strictest wins)
    let merged = merge_results(&merge_results(&pre.pre_policy, &post), &safety_policy);
    let total_ms = pre.start_time.elapsed().as_secs_f64() * 1000.0;

    let safety_scores: Vec<SafetyScore> = safety_results.iter().map(|r| SafetyScore {
        label: r.label.clone(),
        score: r.score,
    }).collect();

    let response = ModerationResponse {
        verdict: merged.verdict.clone(),
        moderation: ModerationInfo {
            policy_flags: policy_flag_strings(&merged),
            confidence: merged.confidence,
            blocked_terms: merged.blocked_terms.clone(),
            processing_ms: total_ms,
            safety_scores: if safety_scores.is_empty() { None } else { Some(safety_scores) },
            ml_toxicity: None,
        },
        classification: Some(user_classification.clone()),
        cache: CacheInfo {
            hit: false,
            hash: pre.hash.clone(),
            image_blocklisted: None,
        },
        gateway: gateway_info(config, request_id),
    };

    let cached = CachedVerdict::new(
        pre.hash.clone(),
        merged,
        Some(user_classification),
        now_ms(),
    );

    (response, cached)
}

/// Build a blocked response when pre-check blocks before inference.
pub fn blocked_response(
    pre: &PreModerationResult,
    config: &GatewayConfig,
    request_id: &str,
) -> ModerationResponse {
    let total_ms = pre.start_time.elapsed().as_secs_f64() * 1000.0;

    ModerationResponse {
        verdict: pre.pre_policy.verdict.clone(),
        moderation: ModerationInfo {
            policy_flags: policy_flag_strings(&pre.pre_policy),
            confidence: pre.pre_policy.confidence,
            blocked_terms: pre.pre_policy.blocked_terms.clone(),
            processing_ms: total_ms,
            safety_scores: None,
            ml_toxicity: None,
        },
        classification: None,
        cache: CacheInfo {
            hit: false,
            hash: pre.hash.clone(),
            image_blocklisted: None,
        },
        gateway: gateway_info(config, request_id),
    }
}

// ---------------------------------------------------------------------------
// ML toxicity scoring helper
// ---------------------------------------------------------------------------

const ML_TOXIC_THRESHOLD: f64 = 0.65;
const ML_SEVERE_THRESHOLD: f64 = 0.45;

fn run_ml_toxicity(
    classifier: Option<&ToxicityClassifier>,
    text: Option<&str>,
    labels: &[String],
) -> (Option<PolicyResult>, Option<ToxicityInfo>) {
    let classifier = match classifier {
        Some(c) => c,
        None => return (None, None),
    };

    let input = text
        .map(String::from)
        .unwrap_or_else(|| labels.join(" "));

    if input.trim().is_empty() {
        return (None, None);
    }

    match classifier.classify(&input) {
        Ok(scores) => {
            let mut flags = Vec::new();
            let mut blocked = Vec::new();
            let mut worst = scores.toxic.max(scores.severe_toxic);

            if scores.toxic >= ML_TOXIC_THRESHOLD {
                flags.push(PolicyFlag::MlToxicityDetected);
                blocked.push(format!("[ml] toxic={:.2}", scores.toxic));
            }
            if scores.severe_toxic >= ML_SEVERE_THRESHOLD {
                if !flags.contains(&PolicyFlag::MlToxicityDetected) {
                    flags.push(PolicyFlag::MlToxicityDetected);
                }
                blocked.push(format!("[ml] severe_toxic={:.2}", scores.severe_toxic));
            }

            let verdict = if !flags.is_empty() {
                Verdict::Block
            } else if worst >= 0.40 {
                Verdict::Review
            } else {
                Verdict::Allow
            };

            if verdict == Verdict::Allow {
                worst = 0.0;
            }

            let policy = PolicyResult {
                verdict,
                flags,
                blocked_terms: blocked,
                confidence: worst,
                processing_ms: scores.inference_ms,
            };

            let info = ToxicityInfo {
                toxic: scores.toxic,
                severe_toxic: scores.severe_toxic,
                inference_ms: scores.inference_ms,
                model: "MiniLMv2-toxic-jigsaw".into(),
            };

            (Some(policy), Some(info))
        }
        Err(_) => (None, None),
    }
}

/// Build a blocked response when the image hash is on the blocklist.
pub fn image_blocklisted_response(
    _image_hash: &str,
    config: &GatewayConfig,
    request_id: &str,
) -> ModerationResponse {
    ModerationResponse {
        verdict: Verdict::Block,
        moderation: ModerationInfo {
            policy_flags: vec!["image_blocklisted".into()],
            confidence: 1.0,
            blocked_terms: vec!["[image on blocklist]".into()],
            processing_ms: 0.0,
            safety_scores: None,
            ml_toxicity: None,
        },
        classification: None,
        cache: CacheInfo {
            hit: false,
            hash: String::new(),
            image_blocklisted: Some(true),
        },
        gateway: gateway_info(config, request_id),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config() -> GatewayConfig {
        GatewayConfig {
            platform: "test".into(),
            region: "us-test".into(),
        }
    }

    #[test]
    fn policy_only_clean_input() {
        let req = ModerationRequest {
            labels: vec!["cat".into(), "dog".into(), "bird".into()],
            nonce: "test".into(),
            text: None,
        };
        let resp = moderate_policy_only(&req, &test_config(), "rid-1", None, None);
        assert_eq!(resp.verdict, Verdict::Allow);
        assert!(resp.classification.is_some());
        assert!(!resp.cache.hit);
        assert!(resp.cache.hash.starts_with("sha256:"));
        assert_eq!(resp.gateway.platform, "test");
    }

    #[test]
    fn policy_only_with_prohibited_term() {
        let req = ModerationRequest {
            labels: vec!["kill".into(), "dog".into()],
            nonce: "test".into(),
            text: None,
        };
        let resp = moderate_policy_only(&req, &test_config(), "rid-2", None, None);
        assert_eq!(resp.verdict, Verdict::Block);
        assert!(!resp.moderation.policy_flags.is_empty());
    }

    #[test]
    fn policy_only_with_injection() {
        let req = ModerationRequest {
            labels: vec!["<script>alert(1)</script>".into()],
            nonce: "test".into(),
            text: None,
        };
        let resp = moderate_policy_only(&req, &test_config(), "rid-3", None, None);
        assert_eq!(resp.verdict, Verdict::Block);
    }

    #[test]
    fn cached_hit_returns_cached() {
        let req = ModerationRequest {
            labels: vec!["cat".into()],
            nonce: "test".into(),
            text: None,
        };
        let cached = CachedVerdict::new(
            "sha256:old".into(),
            PolicyResult {
                verdict: Verdict::Allow,
                flags: vec![],
                blocked_terms: vec![],
                confidence: 0.0,
                processing_ms: 1.0,
            },
            None,
            12345,
        );
        let resp = moderate_cached(&req, Some(&cached), &test_config(), "rid-4", None);
        assert!(resp.cache.hit);
        assert_eq!(resp.verdict, Verdict::Allow);
    }

    #[test]
    fn cached_miss_falls_back() {
        let req = ModerationRequest {
            labels: vec!["cat".into()],
            nonce: "test".into(),
            text: None,
        };
        let resp = moderate_cached(&req, None, &test_config(), "rid-5", None);
        assert!(!resp.cache.hit);
        assert!(resp.classification.is_some());
    }

    #[test]
    fn pre_moderate_clean_allows() {
        let req = ModerationRequest {
            labels: vec!["cat".into(), "dog".into()],
            nonce: "test".into(),
            text: None,
        };
        let pre = pre_moderate(&req, None);
        assert!(!pre.is_blocked());
        assert!(pre.hash.starts_with("sha256:"));
    }

    #[test]
    fn pre_moderate_injection_blocks() {
        let req = ModerationRequest {
            labels: vec!["<script>alert(1)</script>".into()],
            nonce: "test".into(),
            text: None,
        };
        let pre = pre_moderate(&req, None);
        assert!(pre.is_blocked());
    }

    #[test]
    fn post_moderate_builds_response() {
        let req = ModerationRequest {
            labels: vec!["cat".into(), "dog".into()],
            nonce: "test".into(),
            text: None,
        };
        let pre = pre_moderate(&req, None);
        let classification = crate::handlers::mock_classify(&pre.normalized_labels);
        let (resp, cached) = post_moderate(&pre, &classification, &test_config(), "rid-6");
        assert_eq!(resp.verdict, Verdict::Allow);
        assert!(resp.classification.is_some());
        assert!(!resp.cache.hit);
        assert_eq!(cached.hash, pre.hash);
    }

    #[test]
    fn deterministic_hash() {
        let req = ModerationRequest {
            labels: vec!["cat".into(), "dog".into()],
            nonce: "test".into(),
            text: None,
        };
        let h1 = pre_moderate(&req, None).hash;
        let h2 = pre_moderate(&req, None).hash;
        assert_eq!(h1, h2);
    }
}
