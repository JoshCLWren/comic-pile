//! Batched historical effort and pure bandwidth inference, matching Python's v1 policy.
use serde_json::Value;

pub(crate) fn median(values: Option<&Vec<f64>>) -> Option<f64> {
    let mut v = values.filter(|v| v.len() >= 2)?.clone();
    v.sort_by(f64::total_cmp);
    let mid = v.len() / 2;
    Some(if v.len() % 2 == 0 {
        (v[mid - 1] + v[mid]) / 2.0
    } else {
        v[mid]
    })
}
pub(crate) fn year(metadata: &Value) -> Option<i32> {
    for key in ["cover_date", "store_date"] {
        if let Some(s) = metadata[key].as_str() {
            for b in s.as_bytes().windows(4) {
                if (b.starts_with(b"19") || b.starts_with(b"20"))
                    && b.iter().all(u8::is_ascii_digit)
                {
                    return std::str::from_utf8(b).ok()?.parse().ok();
                }
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn metadata_and_median_boundaries() {
        assert_eq!(
            year(&serde_json::json!({"cover_date":"bad","store_date":"c. 1965"})),
            Some(1965)
        );
        assert_eq!(year(&serde_json::json!({"cover_date":1990})), None);
        // A single issue observation cannot supply an issue median; its thread's
        // aggregate remains the fallback, and even-sized samples use the mean.
        assert_eq!(median(Some(&vec![25.0])), None);
        assert_eq!(median(Some(&vec![25.0, 5.0, 15.0])), Some(15.0));
        assert_eq!(median(Some(&vec![25.0, 5.0])), Some(15.0));
    }
}
