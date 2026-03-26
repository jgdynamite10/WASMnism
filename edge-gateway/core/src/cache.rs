use serde::{Deserialize, Serialize};

use crate::policy::{PolicyResult, Verdict};
use crate::types::ClassificationResponse;

/// A cached moderation verdict stored in platform KV.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CachedVerdict {
    pub hash: String,
    pub verdict: Verdict,
    pub policy: PolicyResult,
    pub classification: Option<ClassificationResponse>,
    pub cached_at_ms: u64,
}

impl CachedVerdict {
    pub fn new(
        hash: String,
        policy: PolicyResult,
        classification: Option<ClassificationResponse>,
        timestamp_ms: u64,
    ) -> Self {
        Self {
            verdict: policy.verdict.clone(),
            hash,
            policy,
            classification,
            cached_at_ms: timestamp_ms,
        }
    }

    pub fn to_bytes(&self) -> Vec<u8> {
        serde_json::to_vec(self).unwrap_or_default()
    }

    pub fn from_bytes(data: &[u8]) -> Option<Self> {
        serde_json::from_slice(data).ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::policy::PolicyFlag;

    #[test]
    fn round_trip_serialization() {
        let verdict = CachedVerdict::new(
            "sha256:abc123".into(),
            PolicyResult {
                verdict: Verdict::Allow,
                flags: vec![],
                blocked_terms: vec![],
                confidence: 0.0,
                processing_ms: 1.5,
            },
            None,
            1234567890,
        );

        let bytes = verdict.to_bytes();
        let restored = CachedVerdict::from_bytes(&bytes).unwrap();
        assert_eq!(restored.hash, "sha256:abc123");
        assert_eq!(restored.verdict, Verdict::Allow);
    }

    #[test]
    fn round_trip_with_classification() {
        let verdict = CachedVerdict::new(
            "sha256:def456".into(),
            PolicyResult {
                verdict: Verdict::Review,
                flags: vec![PolicyFlag::PiiDetected],
                blocked_terms: vec![],
                confidence: 0.9,
                processing_ms: 2.0,
            },
            Some(ClassificationResponse {
                results: vec![],
                metrics: crate::types::InferenceMetrics {
                    model_load_ms: 0.0,
                    input_encoding_ms: 0.0,
                    text_encoding_ms: 0.0,
                    similarity_ms: 0.0,
                    total_inference_ms: 0.0,
                    num_candidates: 0,
                },
            }),
            9999999999,
        );

        let bytes = verdict.to_bytes();
        let restored = CachedVerdict::from_bytes(&bytes).unwrap();
        assert_eq!(restored.verdict, Verdict::Review);
        assert!(restored.classification.is_some());
    }
}
