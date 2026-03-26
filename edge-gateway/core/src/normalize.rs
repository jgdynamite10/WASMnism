use unicode_normalization::UnicodeNormalization;

/// Apply unicode NFC normalization, lowercase, and whitespace collapse.
pub fn normalize_text(input: &str) -> String {
    let nfc: String = input.nfc().collect();
    let lowered = nfc.to_lowercase();
    collapse_whitespace(&lowered)
}

/// Normalize each label in a list.
pub fn normalize_labels(labels: &[String]) -> Vec<String> {
    labels.iter().map(|l| normalize_text(l)).collect()
}

fn collapse_whitespace(s: &str) -> String {
    let mut result = String::with_capacity(s.len());
    let mut prev_space = false;
    for ch in s.trim().chars() {
        if ch.is_whitespace() {
            if !prev_space {
                result.push(' ');
            }
            prev_space = true;
        } else {
            result.push(ch);
            prev_space = false;
        }
    }
    result
}

/// Expand common leetspeak substitutions for evasion detection.
pub fn expand_leetspeak(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    for ch in input.chars() {
        match ch {
            '@' => out.push('a'),
            '3' => out.push('e'),
            '1' | '!' => out.push('i'),
            '0' => out.push('o'),
            '$' => out.push('s'),
            '7' => out.push('t'),
            '5' => out.push('s'),
            '+' => out.push('t'),
            _ => out.push(ch),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_basic() {
        assert_eq!(normalize_text("  Hello   World  "), "hello world");
    }

    #[test]
    fn normalize_unicode() {
        // e + combining acute should normalize to é (NFC)
        let input = "caf\u{0065}\u{0301}";
        let result = normalize_text(input);
        assert!(result.contains("café"));
    }

    #[test]
    fn normalize_labels_works() {
        let labels = vec!["Cat".into(), "  DOG ".into(), "BiRd".into()];
        let norm = normalize_labels(&labels);
        assert_eq!(norm, vec!["cat", "dog", "bird"]);
    }

    #[test]
    fn leetspeak_expansion() {
        assert_eq!(expand_leetspeak("h@t3"), "hate");
        assert_eq!(expand_leetspeak("$h!t"), "shit");
    }
}
