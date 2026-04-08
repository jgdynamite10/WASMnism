use crate::timing::epoch_ms;
use crate::types::*;

fn round3(v: f64) -> f64 {
    (v * 1_000.0).round() / 1_000.0
}

fn round6(v: f64) -> f64 {
    (v * 1_000_000.0).round() / 1_000_000.0
}

// ---------------------------------------------------------------------------
// GET /gateway/health
// ---------------------------------------------------------------------------

pub fn health(config: &GatewayConfig) -> HealthResponse {
    HealthResponse {
        status: "healthy".into(),
        platform: config.platform.clone(),
        region: config.region.clone(),
        timestamp_ms: epoch_ms(),
    }
}

// ---------------------------------------------------------------------------
// POST /gateway/echo
// ---------------------------------------------------------------------------

pub fn echo(req: &EchoRequest, config: &GatewayConfig, request_id: &str) -> EchoResponse {
    EchoResponse {
        echo: EchoContent {
            labels: req.labels.clone(),
            nonce: req.nonce.clone(),
        },
        gateway: GatewayInfo {
            platform: config.platform.clone(),
            region: config.region.clone(),
            timestamp_ms: epoch_ms(),
            request_id: request_id.to_string(),
        },
    }
}

// ---------------------------------------------------------------------------
// POST /gateway/mock-classify
//
// Deterministic score distribution per benchmark_contract.md §5.3:
//   1 label  → [1.00]
//   2 labels → [0.70, 0.30]
//   3 labels → [0.70, 0.20, 0.10]
//   N > 3    → [0.70, 0.20] + remaining 0.10/(N-2) each
//
// similarity = score × 0.41, rounded to 3 dp
// ---------------------------------------------------------------------------

pub fn mock_classify(labels: &[String]) -> ClassificationResponse {
    let scores = compute_mock_scores(labels.len());

    let results: Vec<ClassificationResult> = labels
        .iter()
        .zip(scores.iter())
        .map(|(label, &score)| ClassificationResult {
            label: label.clone(),
            score,
            similarity: round3(score * 0.41),
        })
        .collect();

    ClassificationResponse {
        results,
        metrics: InferenceMetrics {
            model_load_ms: 0.0,
            input_encoding_ms: 0.0,
            text_encoding_ms: 0.0,
            similarity_ms: 0.0,
            total_inference_ms: 0.0,
            num_candidates: labels.len(),
        },
    }
}

fn compute_mock_scores(n: usize) -> Vec<f64> {
    match n {
        0 => vec![],
        1 => vec![1.0],
        2 => vec![0.70, 0.30],
        3 => vec![0.70, 0.20, 0.10],
        _ => {
            let tail = round6(0.10 / (n as f64 - 2.0));
            let mut scores = vec![0.70, 0.20];
            scores.extend(std::iter::repeat(tail).take(n - 2));
            scores
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mock_scores_1_label() {
        let resp = mock_classify(&["cat".into()]);
        assert_eq!(resp.results.len(), 1);
        assert!((resp.results[0].score - 1.0).abs() < 1e-9);
    }

    #[test]
    fn mock_scores_3_labels() {
        let resp = mock_classify(&["cat".into(), "dog".into(), "bird".into()]);
        assert_eq!(resp.results.len(), 3);
        assert!((resp.results[0].score - 0.70).abs() < 1e-9);
        assert!((resp.results[1].score - 0.20).abs() < 1e-9);
        assert!((resp.results[2].score - 0.10).abs() < 1e-9);
        let sum: f64 = resp.results.iter().map(|r| r.score).sum();
        assert!((sum - 1.0).abs() < 0.01);
    }

    #[test]
    fn mock_scores_5_labels() {
        let labels: Vec<String> = vec!["a", "b", "c", "d", "e"]
            .into_iter()
            .map(String::from)
            .collect();
        let resp = mock_classify(&labels);
        assert_eq!(resp.results.len(), 5);
        assert!((resp.results[0].score - 0.70).abs() < 1e-9);
        assert!((resp.results[1].score - 0.20).abs() < 1e-9);
        let tail = round6(0.10 / 3.0);
        for r in &resp.results[2..] {
            assert!((r.score - tail).abs() < 1e-6);
        }
    }

    #[test]
    fn mock_similarity_matches_contract() {
        let resp = mock_classify(&["cat".into(), "dog".into(), "bird".into()]);
        assert!((resp.results[0].similarity - round3(0.70 * 0.41)).abs() < 1e-9);
        assert!((resp.results[1].similarity - round3(0.20 * 0.41)).abs() < 1e-9);
    }

    #[test]
    fn mock_metrics_zeroed() {
        let resp = mock_classify(&["cat".into()]);
        assert_eq!(resp.metrics.model_load_ms, 0.0);
        assert_eq!(resp.metrics.total_inference_ms, 0.0);
        assert_eq!(resp.metrics.num_candidates, 1);
    }
}
