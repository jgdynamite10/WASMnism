use sha2::{Digest, Sha256};

/// Compute SHA-256 hash and return as a hex string.
pub fn sha256_hex(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    let result = hasher.finalize();
    hex_encode(&result)
}

/// Build a cache key from normalized labels and optional content bytes.
/// Format: "sha256:<hex>"
pub fn content_hash(labels: &[String], content: Option<&[u8]>) -> String {
    let mut hasher = Sha256::new();
    for label in labels {
        hasher.update(label.as_bytes());
        hasher.update(b"|");
    }
    if let Some(bytes) = content {
        hasher.update(bytes);
    }
    let result = hasher.finalize();
    format!("sha256:{}", hex_encode(&result))
}

/// Hash raw image bytes for the blocklist.
/// Format: "img:sha256:<hex>"
pub fn image_hash(image_bytes: &[u8]) -> String {
    format!("img:sha256:{}", sha256_hex(image_bytes))
}

fn hex_encode(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{b:02x}"));
    }
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sha256_deterministic() {
        let h1 = sha256_hex(b"hello world");
        let h2 = sha256_hex(b"hello world");
        assert_eq!(h1, h2);
        assert_eq!(h1.len(), 64);
    }

    #[test]
    fn sha256_different_inputs() {
        let h1 = sha256_hex(b"hello");
        let h2 = sha256_hex(b"world");
        assert_ne!(h1, h2);
    }

    #[test]
    fn content_hash_with_labels_only() {
        let labels = vec!["cat".into(), "dog".into()];
        let h = content_hash(&labels, None);
        assert!(h.starts_with("sha256:"));
        assert_eq!(h.len(), 7 + 64); // "sha256:" + 64 hex chars
    }

    #[test]
    fn content_hash_with_content() {
        let labels = vec!["cat".into()];
        let h1 = content_hash(&labels, None);
        let h2 = content_hash(&labels, Some(b"image-bytes"));
        assert_ne!(h1, h2);
    }

    #[test]
    fn content_hash_label_order_matters() {
        let h1 = content_hash(&["a".into(), "b".into()], None);
        let h2 = content_hash(&["b".into(), "a".into()], None);
        assert_ne!(h1, h2);
    }

    #[test]
    fn image_hash_format() {
        let h = image_hash(b"fake-image-bytes");
        assert!(h.starts_with("img:sha256:"));
        assert_eq!(h.len(), 11 + 64);
    }

    #[test]
    fn image_hash_deterministic() {
        let h1 = image_hash(b"same-content");
        let h2 = image_hash(b"same-content");
        assert_eq!(h1, h2);
    }
}
