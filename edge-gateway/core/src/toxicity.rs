use serde::Serialize;
use tract_onnx::prelude::*;
use tract_onnx_opl::WithOnnx;

use crate::tokenizer::WordPieceTokenizer;

const DEFAULT_MAX_LENGTH: usize = 128;

/// Toxicity classifier using a MiniLMv2 model fine-tuned on Jigsaw
/// toxic-comment data. Supports loading from ONNX (native) or NNEF tar
/// (preferred in WASM — avoids heavy protobuf parsing at runtime).
pub struct ToxicityClassifier {
    model: TypedRunnableModel<TypedModel>,
    tokenizer: WordPieceTokenizer,
    max_length: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct ToxicityScores {
    pub toxic: f64,
    pub severe_toxic: f64,
    pub inference_ms: f64,
}

impl ToxicityClassifier {
    /// Load from a pre-converted NNEF tar archive (produced by convert-to-nnef).
    /// This is the preferred path for WASM deployment since it skips the
    /// expensive ONNX protobuf parse.
    pub fn from_nnef_tar(tar_bytes: &[u8], vocab: &str) -> Result<Self, String> {
        let max_length = DEFAULT_MAX_LENGTH;
        let tokenizer = WordPieceTokenizer::from_vocab(vocab, max_length);

        let nnef = tract_nnef::framework::Nnef::default()
            .with_tract_core()
            .with_onnx();

        let mut reader = std::io::Cursor::new(tar_bytes);
        let model = nnef
            .model_for_read(&mut reader)
            .map_err(|e| format!("NNEF parse: {e}"))?
            .into_optimized()
            .map_err(|e| format!("optimize: {e}"))?
            .into_runnable()
            .map_err(|e| format!("runnable: {e}"))?;

        Ok(Self {
            model,
            tokenizer,
            max_length,
        })
    }

    /// Build the classifier from raw ONNX model bytes and a vocab.txt string.
    /// Parses the ONNX protobuf and optimizes the graph — works well natively
    /// but may exceed WASM memory limits for large models.
    pub fn from_onnx_bytes(model_bytes: &[u8], vocab: &str) -> Result<Self, String> {
        let max_length = DEFAULT_MAX_LENGTH;
        let tokenizer = WordPieceTokenizer::from_vocab(vocab, max_length);

        let ml = max_length as i64;

        let model = tract_onnx::onnx()
            .model_for_read(&mut std::io::Cursor::new(model_bytes))
            .map_err(|e| format!("ONNX parse: {e}"))?
            .with_input_fact(
                0,
                InferenceFact::dt_shape(i64::datum_type(), tvec![1, ml]),
            )
            .map_err(|e| format!("input_ids shape: {e}"))?
            .with_input_fact(
                1,
                InferenceFact::dt_shape(i64::datum_type(), tvec![1, ml]),
            )
            .map_err(|e| format!("attention_mask shape: {e}"))?
            .with_input_fact(
                2,
                InferenceFact::dt_shape(i64::datum_type(), tvec![1, ml]),
            )
            .map_err(|e| format!("token_type_ids shape: {e}"))?
            .into_typed()
            .map_err(|e| format!("typed: {e}"))?
            .into_optimized()
            .map_err(|e| format!("optimize: {e}"))?
            .into_runnable()
            .map_err(|e| format!("runnable: {e}"))?;

        Ok(Self {
            model,
            tokenizer,
            max_length,
        })
    }

    /// Backwards-compatible alias (uses ONNX path).
    pub fn from_bytes(model_bytes: &[u8], vocab: &str) -> Result<Self, String> {
        Self::from_onnx_bytes(model_bytes, vocab)
    }

    /// Score a text prompt for toxicity. Returns probabilities (0.0–1.0) for
    /// each category after applying sigmoid to raw logits.
    pub fn classify(&self, text: &str) -> Result<ToxicityScores, String> {
        let start = crate::timing::Timer::now();

        let enc = self.tokenizer.encode(text);

        let input_ids = tract_ndarray::Array2::from_shape_vec(
            (1, self.max_length),
            enc.input_ids,
        )
        .map_err(|e| format!("input_ids tensor: {e}"))?;

        let attention_mask = tract_ndarray::Array2::from_shape_vec(
            (1, self.max_length),
            enc.attention_mask,
        )
        .map_err(|e| format!("attention_mask tensor: {e}"))?;

        let token_type_ids = tract_ndarray::Array2::from_shape_vec(
            (1, self.max_length),
            enc.token_type_ids,
        )
        .map_err(|e| format!("token_type_ids tensor: {e}"))?;

        let result = self
            .model
            .run(tvec![
                input_ids.into_tvalue(),
                attention_mask.into_tvalue(),
                token_type_ids.into_tvalue(),
            ])
            .map_err(|e| format!("inference: {e}"))?;

        let logits = result[0]
            .to_array_view::<f32>()
            .map_err(|e| format!("read output: {e}"))?;

        let inference_ms = start.elapsed_ms();

        Ok(ToxicityScores {
            toxic: sigmoid(logits[[0, 0]] as f64),
            severe_toxic: sigmoid(logits[[0, 1]] as f64),
            inference_ms,
        })
    }
}

fn sigmoid(x: f64) -> f64 {
    1.0 / (1.0 + (-x).exp())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn load_classifier() -> ToxicityClassifier {
        let base = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../models/toxicity");
        let model = std::fs::read(base.join("model.onnx")).expect("model.onnx");
        let vocab = std::fs::read_to_string(base.join("vocab.txt")).expect("vocab.txt");
        ToxicityClassifier::from_bytes(&model, &vocab).expect("classifier init")
    }

    #[test]
    fn safe_text_low_toxicity() {
        let cls = load_classifier();
        let scores = cls.classify("I love sunny days and cute puppies").unwrap();
        assert!(scores.toxic < 0.3, "expected low toxic, got {}", scores.toxic);
        assert!(scores.severe_toxic < 0.1);
    }

    #[test]
    fn toxic_text_high_score() {
        let cls = load_classifier();
        let scores = cls.classify("I will kill you, you stupid worthless piece of trash").unwrap();
        assert!(scores.toxic > 0.7, "expected high toxic, got {}", scores.toxic);
    }

    #[test]
    fn severe_toxic_text() {
        let cls = load_classifier();
        let scores = cls
            .classify("I am going to murder you and your entire family you worthless scum")
            .unwrap();
        assert!(scores.toxic > 0.7);
        assert!(scores.severe_toxic > 0.3);
    }

    #[test]
    fn scores_in_valid_range() {
        let cls = load_classifier();
        let scores = cls.classify("some random test text here").unwrap();
        assert!((0.0..=1.0).contains(&scores.toxic));
        assert!((0.0..=1.0).contains(&scores.severe_toxic));
        assert!(scores.inference_ms > 0.0);
    }
}
