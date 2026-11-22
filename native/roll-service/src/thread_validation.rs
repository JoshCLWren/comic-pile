//! FastAPI/Pydantic-compatible request validation for the native thread
//! lifecycle routes.
//!
//! The frozen Python app turns every request-validation failure into HTTP 422.
//! In production the body is `{"detail": "Validation failed"}`; elsewhere it
//! also carries the per-field `errors` list (`field`, `message`, `type`) and
//! the offending `body` (`app/exception_handlers.py`). This module reproduces
//! both shapes and the Pydantic v2 messages the handlers rely on.
#![forbid(unsafe_code)]
use crate::ApiError;
use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::{json, Map, Value};

/// A handler failure: either an ordinary API error or request validation.
#[derive(Debug)]
pub enum LifecycleError {
    /// Any non-validation API error.
    Api(ApiError),
    /// Request validation failed (HTTP 422).
    Validation {
        /// Collected field errors in field order.
        errors: Vec<Value>,
        /// The parsed request body (or `null`).
        body: Value,
    },
}

impl From<ApiError> for LifecycleError {
    fn from(error: ApiError) -> Self {
        Self::Api(error)
    }
}

fn is_production() -> bool {
    std::env::var("ENVIRONMENT").is_ok_and(|value| value == "production")
}

/// The 422 body: plain in production, detailed elsewhere (Python parity).
pub fn validation_payload(production: bool, errors: &[Value], body: &Value) -> Value {
    if production {
        json!({"detail": "Validation failed"})
    } else {
        json!({"detail": "Validation failed", "errors": errors, "body": body})
    }
}

impl IntoResponse for LifecycleError {
    fn into_response(self) -> Response {
        match self {
            Self::Api(error) => error.into_response(),
            Self::Validation { errors, body } => (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(validation_payload(is_production(), &errors, &body)),
            )
                .into_response(),
        }
    }
}

/// Accumulates Pydantic-style field errors for one request.
#[derive(Default)]
pub struct Check {
    errors: Vec<Value>,
}

impl Check {
    /// Record one error at `loc` (for example `["body", "title"]`).
    pub fn push(&mut self, loc: &[&str], kind: &str, message: impl Into<String>) {
        self.errors.push(json!({
            "field": loc.join("."),
            "message": message.into(),
            "type": kind,
        }));
    }

    /// Record one error whose location ends with a list index.
    pub fn push_indexed(&mut self, loc: &[&str], index: usize, kind: &str, message: &str) {
        let mut field = loc.join(".");
        field.push('.');
        field.push_str(&index.to_string());
        self.errors
            .push(json!({"field": field, "message": message, "type": kind}));
    }

    /// Copy of the errors recorded so far.
    pub fn errors_snapshot(&self) -> Vec<Value> {
        self.errors.clone()
    }

    /// True when no error was recorded.
    pub fn is_clean(&self) -> bool {
        self.errors.is_empty()
    }

    /// Finish: `Ok(())` when clean, otherwise the 422 error.
    pub fn finish(self, body: Value) -> Result<(), LifecycleError> {
        if self.errors.is_empty() {
            Ok(())
        } else {
            Err(LifecycleError::Validation {
                errors: self.errors,
                body,
            })
        }
    }
}

/// Pydantic text for a minimum string length.
pub fn too_short(min: usize) -> String {
    format!(
        "String should have at least {min} character{}",
        if min == 1 { "" } else { "s" }
    )
}

/// Pydantic text for a maximum string length.
pub fn too_long(max: usize) -> String {
    format!(
        "String should have at most {max} character{}",
        if max == 1 { "" } else { "s" }
    )
}

/// Parse a JSON request body. A missing body is `Ok(None)`.
pub fn parse_body(bytes: &[u8]) -> Result<Option<Value>, LifecycleError> {
    if bytes.iter().all(u8::is_ascii_whitespace) {
        return Ok(None);
    }
    serde_json::from_slice::<Value>(bytes)
        .map(Some)
        .map_err(|_| LifecycleError::Validation {
            errors: vec![json!({
                "field": "body.0",
                "message": "JSON decode error",
                "type": "json_invalid",
            })],
            body: Value::String(String::from_utf8_lossy(bytes).into_owned()),
        })
}

/// Require a body object for a model-typed parameter.
pub fn require_object(body: Option<Value>) -> Result<Map<String, Value>, LifecycleError> {
    match body {
        None => Err(LifecycleError::Validation {
            errors: vec![json!({
                "field": "body",
                "message": "Field required",
                "type": "missing",
            })],
            body: Value::Null,
        }),
        Some(Value::Object(map)) => Ok(map),
        Some(other) => Err(LifecycleError::Validation {
            errors: vec![json!({
                "field": "body",
                "message": "Input should be a valid dictionary or object to extract fields from",
                "type": "model_attributes_type",
            })],
            body: other,
        }),
    }
}

/// Outcome of coercing one JSON value to an integer the way Pydantic lax mode does.
pub enum IntOutcome {
    /// A valid integer.
    Value(i64),
    /// Rejected, with the Pydantic error type and message.
    Invalid(&'static str, String),
}

/// Coerce a JSON value to an integer (ints, integral floats, numeric strings).
pub fn coerce_int(value: &Value) -> IntOutcome {
    match value {
        Value::Number(number) => {
            if let Some(int) = number.as_i64() {
                IntOutcome::Value(int)
            } else if let Some(float) = number.as_f64() {
                if float.fract() == 0.0 && float.abs() < 9.0e18 {
                    IntOutcome::Value(float as i64)
                } else {
                    IntOutcome::Invalid(
                        "int_from_float",
                        "Input should be a valid integer, got a number with a fractional part"
                            .into(),
                    )
                }
            } else {
                IntOutcome::Invalid("int_type", "Input should be a valid integer".into())
            }
        }
        Value::String(text) => match text.trim().parse::<i64>() {
            Ok(int) => IntOutcome::Value(int),
            Err(_) => IntOutcome::Invalid(
                "int_parsing",
                "Input should be a valid integer, unable to parse string as an integer".into(),
            ),
        },
        _ => IntOutcome::Invalid("int_type", "Input should be a valid integer".into()),
    }
}

/// Coerce a JSON value to a boolean the way Pydantic lax mode does.
pub fn coerce_bool(value: &Value) -> Option<bool> {
    match value {
        Value::Bool(flag) => Some(*flag),
        Value::Number(number) => match number.as_i64() {
            Some(0) => Some(false),
            Some(1) => Some(true),
            _ => None,
        },
        Value::String(text) => match text.trim().to_lowercase().as_str() {
            "0" | "off" | "f" | "false" | "n" | "no" => Some(false),
            "1" | "on" | "t" | "true" | "y" | "yes" => Some(true),
            _ => None,
        },
        _ => None,
    }
}

/// Integer bounds applied after coercion.
#[derive(Clone, Copy, Default)]
pub struct Bounds {
    /// Inclusive minimum (`ge`).
    pub ge: Option<i64>,
    /// Exclusive minimum (`gt`).
    pub gt: Option<i64>,
    /// Inclusive maximum (`le`).
    pub le: Option<i64>,
}

/// Validate an optional/required integer field, recording any error.
///
/// Returns `Some(value)` only when the value is present, non-null and valid.
pub fn int_field(
    check: &mut Check,
    loc: &[&str],
    value: Option<&Value>,
    bounds: Bounds,
    nullable: bool,
    required: bool,
) -> Option<i64> {
    let Some(value) = value else {
        if required {
            check.push(loc, "missing", "Field required");
        }
        return None;
    };
    if value.is_null() {
        if !nullable {
            check.push(loc, "int_type", "Input should be a valid integer");
        }
        return None;
    }
    match coerce_int(value) {
        IntOutcome::Invalid(kind, message) => {
            check.push(loc, kind, message);
            None
        }
        IntOutcome::Value(int) => {
            if let Some(ge) = bounds.ge {
                if int < ge {
                    check.push(
                        loc,
                        "greater_than_equal",
                        format!("Input should be greater than or equal to {ge}"),
                    );
                    return None;
                }
            }
            if let Some(gt) = bounds.gt {
                if int <= gt {
                    check.push(
                        loc,
                        "greater_than",
                        format!("Input should be greater than {gt}"),
                    );
                    return None;
                }
            }
            if let Some(le) = bounds.le {
                if int > le {
                    check.push(
                        loc,
                        "less_than_equal",
                        format!("Input should be less than or equal to {le}"),
                    );
                    return None;
                }
            }
            Some(int)
        }
    }
}

/// String constraints applied to a field.
#[derive(Clone, Copy, Default)]
pub struct StrRules {
    /// Minimum length in characters.
    pub min: Option<usize>,
    /// Maximum length in characters.
    pub max: Option<usize>,
}

/// Validate a string field, recording any error.
pub fn str_field(
    check: &mut Check,
    loc: &[&str],
    value: Option<&Value>,
    rules: StrRules,
    nullable: bool,
    required: bool,
) -> Option<String> {
    let Some(value) = value else {
        if required {
            check.push(loc, "missing", "Field required");
        }
        return None;
    };
    if value.is_null() {
        if !nullable {
            check.push(loc, "string_type", "Input should be a valid string");
        }
        return None;
    }
    let Some(text) = value.as_str() else {
        check.push(loc, "string_type", "Input should be a valid string");
        return None;
    };
    let length = text.chars().count();
    if let Some(min) = rules.min {
        if length < min {
            check.push(loc, "string_too_short", too_short(min));
            return None;
        }
    }
    if let Some(max) = rules.max {
        if length > max {
            check.push(loc, "string_too_long", too_long(max));
            return None;
        }
    }
    Some(text.to_string())
}

/// Parse an integer path parameter the way FastAPI does.
pub fn path_int(check: &mut Check, name: &str, raw: &str) -> Option<i64> {
    match raw.trim().parse::<i64>() {
        Ok(value) => Some(value),
        Err(_) => {
            check.push(
                &["path", name],
                "int_parsing",
                "Input should be a valid integer, unable to parse string as an integer",
            );
            None
        }
    }
}

/// Last value of a query parameter (Starlette `query_params.get`).
pub fn query_value(pairs: &[(String, String)], name: &str) -> Option<String> {
    pairs
        .iter()
        .rev()
        .find(|(key, _)| key == name)
        .map(|(_, value)| value.clone())
}

/// Decode a raw query string into key/value pairs.
pub fn query_pairs(raw: Option<&str>) -> Vec<(String, String)> {
    raw.map(|query| {
        form_urlencoded::parse(query.as_bytes())
            .map(|(key, value)| (key.into_owned(), value.into_owned()))
            .collect()
    })
    .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn integer_coercion_matches_pydantic_lax_mode() {
        assert!(matches!(coerce_int(&json!(3)), IntOutcome::Value(3)));
        assert!(matches!(coerce_int(&json!(3.0)), IntOutcome::Value(3)));
        assert!(matches!(coerce_int(&json!("7")), IntOutcome::Value(7)));
        assert!(matches!(
            coerce_int(&json!(3.5)),
            IntOutcome::Invalid("int_from_float", _)
        ));
        assert!(matches!(
            coerce_int(&json!("x")),
            IntOutcome::Invalid("int_parsing", _)
        ));
        assert!(matches!(
            coerce_int(&json!(true)),
            IntOutcome::Invalid("int_type", _)
        ));
    }

    #[test]
    fn bounds_report_pydantic_messages() {
        let mut check = Check::default();
        let value = json!(-1);
        int_field(
            &mut check,
            &["body", "issues_remaining"],
            Some(&value),
            Bounds {
                ge: Some(0),
                ..Bounds::default()
            },
            false,
            true,
        );
        let error = check.finish(Value::Null).unwrap_err();
        let LifecycleError::Validation { errors, .. } = error else {
            panic!("expected validation error");
        };
        assert_eq!(errors[0]["field"], "body.issues_remaining");
        assert_eq!(
            errors[0]["message"],
            "Input should be greater than or equal to 0"
        );
        assert_eq!(errors[0]["type"], "greater_than_equal");
    }

    #[test]
    fn string_rules_use_character_counts() {
        let mut check = Check::default();
        let value = json!("é".repeat(201));
        let result = str_field(
            &mut check,
            &["body", "title"],
            Some(&value),
            StrRules {
                min: Some(1),
                max: Some(200),
            },
            false,
            true,
        );
        assert!(result.is_none());
        assert!(!check.is_clean());
        assert_eq!(too_short(1), "String should have at least 1 character");
        assert_eq!(too_short(2), "String should have at least 2 characters");
        assert_eq!(too_long(200), "String should have at most 200 characters");
    }

    #[test]
    fn missing_body_and_bad_json_are_422() {
        assert!(matches!(
            require_object(None),
            Err(LifecycleError::Validation { .. })
        ));
        assert!(matches!(
            parse_body(b"{nope"),
            Err(LifecycleError::Validation { .. })
        ));
        assert!(parse_body(b"  ").unwrap().is_none());
    }

    #[test]
    fn query_pairs_take_the_last_value() {
        let pairs = query_pairs(Some("days=5&days=9&x=%20y"));
        assert_eq!(query_value(&pairs, "days").as_deref(), Some("9"));
        assert_eq!(query_value(&pairs, "x").as_deref(), Some(" y"));
        assert_eq!(query_value(&pairs, "none"), None);
    }

    #[test]
    fn production_validation_body_hides_field_details() {
        let errors = vec![json!({"field": "body.title", "message": "m", "type": "t"})];
        let body = json!({"title": 5});
        assert_eq!(
            validation_payload(true, &errors, &body),
            json!({"detail": "Validation failed"})
        );
        let detailed = validation_payload(false, &errors, &body);
        assert_eq!(detailed["errors"], json!(errors));
        assert_eq!(detailed["body"], body);
    }

    #[test]
    fn bool_coercion_matches_pydantic() {
        assert_eq!(coerce_bool(&json!(true)), Some(true));
        assert_eq!(coerce_bool(&json!("no")), Some(false));
        assert_eq!(coerce_bool(&json!(1)), Some(true));
        assert_eq!(coerce_bool(&json!(2)), None);
        assert_eq!(coerce_bool(&json!("maybe")), None);
    }
}
