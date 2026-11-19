//! Shared request validation for the review-preview routes (#4842).
//!
//! Production FastAPI replaces every `RequestValidationError` with the house
//! body `{"detail": "Validation failed"}` (`app/exception_handlers.py`), so a
//! malformed path id or body never carries per-field detail. These helpers
//! reproduce pydantic's lax coercions and that wire body, following the
//! `thread_ordering.rs` precedent.

use crate::{thread_ordering::coerce_json_int, ApiError};
use axum::extract::{rejection::PathRejection, Path};
use serde_json::{Map, Value};

/// The production 422 body for any request-validation failure.
pub(crate) fn validation_failed() -> ApiError {
    ApiError::Unprocessable("Validation failed".into())
}

/// Parse an `int` path parameter the way FastAPI does (signed decimal text).
pub(crate) fn parse_path_int(raw: Result<Path<String>, PathRejection>) -> Result<i64, ApiError> {
    let Path(raw) = raw.map_err(|_| validation_failed())?;
    let trimmed = raw.trim();
    let digits = trimmed.strip_prefix(['+', '-']).unwrap_or(trimmed);
    if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(validation_failed());
    }
    trimmed.parse().map_err(|_| validation_failed())
}

/// Parse a request body that must be a JSON object.
pub(crate) fn parse_body_object(body: &[u8]) -> Result<Map<String, Value>, ApiError> {
    match serde_json::from_slice::<Value>(body) {
        Ok(Value::Object(map)) => Ok(map),
        _ => Err(validation_failed()),
    }
}

/// A required lax-`int` body field.
pub(crate) fn required_int(map: &Map<String, Value>, field: &str) -> Result<i64, ApiError> {
    map.get(field)
        .and_then(coerce_json_int)
        .ok_or_else(validation_failed)
}

/// A required `str` body field (pydantic strict-ish: JSON strings only).
pub(crate) fn required_str<'a>(
    map: &'a Map<String, Value>,
    field: &str,
) -> Result<&'a str, ApiError> {
    map.get(field)
        .and_then(Value::as_str)
        .ok_or_else(validation_failed)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn path_int_matches_fastapi_int() {
        assert_eq!(parse_path_int(Ok(Path("12".into()))).unwrap(), 12);
        assert_eq!(parse_path_int(Ok(Path(" +7 ".into()))).unwrap(), 7);
        for bad in ["abc", "", "1.5", "-", "1e3", "99999999999999999999"] {
            let error = parse_path_int(Ok(Path(bad.into()))).unwrap_err();
            assert_eq!(error.detail(), "Validation failed", "{bad}");
        }
    }

    #[test]
    fn body_must_be_an_object_with_typed_fields() {
        assert!(parse_body_object(b"[]").is_err());
        assert!(parse_body_object(b"").is_err());
        assert!(parse_body_object(b"{bad").is_err());
        let map = parse_body_object(br#"{"a": "3", "b": 2.0, "c": "x"}"#).unwrap();
        assert_eq!(required_int(&map, "a").unwrap(), 3);
        assert_eq!(required_int(&map, "b").unwrap(), 2);
        assert!(required_int(&map, "c").is_err());
        assert!(required_int(&map, "missing").is_err());
        assert_eq!(required_str(&map, "c").unwrap(), "x");
        assert!(required_str(&map, "a").is_ok());
        assert!(required_str(&json!({"a": 1}).as_object().unwrap().clone(), "a").is_err());
    }
}
