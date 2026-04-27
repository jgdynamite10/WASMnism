use std::collections::HashMap;

/// Minimal WordPiece tokenizer for BERT-family models.
/// Loads a `vocab.txt` (one token per line) and produces input tensors
/// compatible with ONNX BertForSequenceClassification.
pub struct WordPieceTokenizer {
    vocab: HashMap<String, i64>,
    cls_id: i64,
    sep_id: i64,
    unk_id: i64,
    pad_id: i64,
    max_length: usize,
}

#[derive(Debug, Clone)]
pub struct TokenizerOutput {
    pub input_ids: Vec<i64>,
    pub attention_mask: Vec<i64>,
    pub token_type_ids: Vec<i64>,
}

impl WordPieceTokenizer {
    pub fn from_vocab(vocab_text: &str, max_length: usize) -> Self {
        let mut vocab = HashMap::with_capacity(32_000);
        for (idx, line) in vocab_text.lines().enumerate() {
            let token = line.trim_end();
            if !token.is_empty() {
                vocab.insert(token.to_string(), idx as i64);
            }
        }

        let cls_id = vocab.get("[CLS]").copied().unwrap_or(101);
        let sep_id = vocab.get("[SEP]").copied().unwrap_or(102);
        let unk_id = vocab.get("[UNK]").copied().unwrap_or(100);
        let pad_id = vocab.get("[PAD]").copied().unwrap_or(0);

        Self {
            vocab,
            cls_id,
            sep_id,
            unk_id,
            pad_id,
            max_length,
        }
    }

    pub fn encode(&self, text: &str) -> TokenizerOutput {
        let lowered = text.to_lowercase();
        let tokens = self.tokenize(&lowered);

        let max_tokens = self.max_length.saturating_sub(2);
        let token_ids: Vec<i64> = tokens
            .iter()
            .take(max_tokens)
            .map(|t| self.vocab.get(t.as_str()).copied().unwrap_or(self.unk_id))
            .collect();

        let seq_len = token_ids.len() + 2;
        let mut input_ids = Vec::with_capacity(self.max_length);
        let mut attention_mask = Vec::with_capacity(self.max_length);
        let token_type_ids = vec![0i64; self.max_length];

        input_ids.push(self.cls_id);
        input_ids.extend_from_slice(&token_ids);
        input_ids.push(self.sep_id);
        input_ids.resize(self.max_length, self.pad_id);

        attention_mask.extend(std::iter::repeat(1i64).take(seq_len));
        attention_mask.resize(self.max_length, 0);

        TokenizerOutput {
            input_ids,
            attention_mask,
            token_type_ids,
        }
    }

    fn tokenize(&self, text: &str) -> Vec<String> {
        let mut tokens = Vec::new();
        for word in basic_tokenize(text) {
            self.wordpiece(&word, &mut tokens);
        }
        tokens
    }

    fn wordpiece(&self, word: &str, output: &mut Vec<String>) {
        if self.vocab.contains_key(word) {
            output.push(word.to_string());
            return;
        }

        let chars: Vec<char> = word.chars().collect();
        let mut start = 0;
        let mut is_first = true;

        while start < chars.len() {
            let mut end = chars.len();
            let mut found = false;

            while start < end {
                let substr: String = chars[start..end].iter().collect();
                let candidate = if is_first {
                    substr.clone()
                } else {
                    format!("##{substr}")
                };

                if self.vocab.contains_key(&candidate) {
                    output.push(candidate);
                    found = true;
                    break;
                }
                end -= 1;
            }

            if !found {
                output.push("[UNK]".to_string());
                return;
            }

            start = end;
            is_first = false;
        }
    }
}

fn basic_tokenize(text: &str) -> Vec<String> {
    let mut words = Vec::new();
    let mut current = String::new();

    for c in text.chars() {
        if c.is_whitespace() {
            if !current.is_empty() {
                words.push(std::mem::take(&mut current));
            }
        } else if c.is_ascii_punctuation() || is_cjk(c) {
            if !current.is_empty() {
                words.push(std::mem::take(&mut current));
            }
            words.push(c.to_string());
        } else {
            current.push(c);
        }
    }

    if !current.is_empty() {
        words.push(current);
    }

    words
}

fn is_cjk(c: char) -> bool {
    let cp = c as u32;
    (0x4E00..=0x9FFF).contains(&cp)
        || (0x3400..=0x4DBF).contains(&cp)
        || (0x20000..=0x2A6DF).contains(&cp)
        || (0xF900..=0xFAFF).contains(&cp)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_tokenizer() -> WordPieceTokenizer {
        let vocab_path =
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../models/toxicity/vocab.txt");
        let vocab = std::fs::read_to_string(&vocab_path)
            .unwrap_or_else(|_| panic!("vocab.txt not found at {}", vocab_path.display()));
        WordPieceTokenizer::from_vocab(&vocab, 128)
    }

    #[test]
    fn output_lengths_match_max() {
        let tok = make_tokenizer();
        let out = tok.encode("hello world");
        assert_eq!(out.input_ids.len(), 128);
        assert_eq!(out.attention_mask.len(), 128);
        assert_eq!(out.token_type_ids.len(), 128);
    }

    #[test]
    fn cls_sep_tokens_present() {
        let tok = make_tokenizer();
        let out = tok.encode("test");
        assert_eq!(out.input_ids[0], 101); // [CLS]
        let first_pad = out.attention_mask.iter().position(|&m| m == 0).unwrap();
        assert_eq!(out.input_ids[first_pad - 1], 102); // [SEP]
    }

    #[test]
    fn padding_is_zero() {
        let tok = make_tokenizer();
        let out = tok.encode("hi");
        let first_pad = out.attention_mask.iter().position(|&m| m == 0).unwrap();
        for i in first_pad..128 {
            assert_eq!(out.input_ids[i], 0);
            assert_eq!(out.attention_mask[i], 0);
        }
    }

    #[test]
    fn known_word_tokenizes_correctly() {
        let tok = make_tokenizer();
        let out = tok.encode("hello");
        assert_eq!(out.input_ids[0], 101);
        assert_ne!(out.input_ids[1], tok.unk_id);
    }
}
