//! Python access-token semantics and opaque, verified owner identity.
use crate::{ApiError, AppState};
use axum::{
    extract::FromRequestParts,
    http::{request::Parts, StatusCode},
};
use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation};
use serde_json::Value;
use std::sync::Arc;

/// Can only be constructed after signature, revocation and password epoch checks.
#[derive(Clone, Copy)]
pub struct AuthenticatedUser {
    id: i32,
}
impl AuthenticatedUser {
    pub fn id(&self) -> i32 {
        self.id
    }

    #[cfg(test)]
    pub(crate) fn for_test(id: i32) -> Self {
        Self { id }
    }
}

fn unauthorized(detail: &'static str) -> ApiError {
    ApiError(StatusCode::UNAUTHORIZED, detail.to_string())
}

fn bearer(parts: &Parts) -> Result<&str, ApiError> {
    let value = parts
        .headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .ok_or_else(|| unauthorized("Not authenticated"))?;
    let (scheme, token) = value.split_once(' ').unwrap_or((value, ""));
    if !scheme.eq_ignore_ascii_case("bearer") || token.is_empty() {
        return Err(unauthorized("Not authenticated"));
    }
    Ok(token)
}

struct AccessClaims {
    username: String,
    jti: String,
    password_epoch: Value,
}
fn claims(token: &str, secret: &[u8]) -> Result<AccessClaims, ApiError> {
    let invalid = || unauthorized("Invalid or expired token");
    let mut validation = Validation::new(Algorithm::HS256);
    // Verify the HS256 signature with the library, then reproduce python-jose's
    // optional claim rules explicitly (its int() accepts string NumericDates).
    validation.required_spec_claims.clear();
    validation.validate_exp = false;
    validation.validate_nbf = false;
    validation.validate_aud = false;
    let payload = decode::<Value>(token, &DecodingKey::from_secret(secret), &validation)
        .map_err(|_| invalid())?
        .claims;
    let now = jsonwebtoken::get_current_timestamp() as i64;
    for field in ["iat", "nbf", "exp"] {
        if let Some(value) = payload.get(field) {
            let numeric = integer(value).ok_or_else(|| match value {
                Value::Null | Value::Array(_) | Value::Object(_) => {
                    unauthorized("Invalid token format")
                }
                _ => invalid(),
            })?;
            if (field == "exp" && numeric < now) || (field == "nbf" && numeric > now) {
                return Err(invalid());
            }
        }
    }
    if payload.get("aud").is_some()
        || payload.get("at_hash").is_some()
        || ["sub", "jti"]
            .iter()
            .any(|field| payload.get(field).is_some_and(|v| !v.is_string()))
    {
        return Err(invalid());
    }
    let username = payload
        .get("sub")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty());
    if username.is_none() || payload.get("type").and_then(Value::as_str) != Some("access") {
        return Err(unauthorized("Invalid authentication credentials"));
    }
    let jti = payload
        .get("jti")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| unauthorized("Token has been revoked"))?;
    let password_epoch = payload.get("pc").cloned().unwrap_or(Value::Null);
    Ok(AccessClaims {
        username: username.unwrap().into(),
        jti: jti.into(),
        password_epoch,
    })
}

// Match int() on the scalar epochs emitted by Python (including numeric strings).
fn integer(value: &Value) -> Option<i64> {
    match value {
        Value::Number(n) => n.as_i64().or_else(|| {
            n.as_f64()
                .filter(|v| v.is_finite() && *v >= i64::MIN as f64 && *v < i64::MAX as f64)
                .map(|v| v as i64)
        }),
        Value::String(s) => s.trim().parse().ok(),
        Value::Bool(v) => Some(i64::from(*v)),
        _ => None,
    }
}

/// Authentication performs no reading writes and never rotates refresh credentials.
pub async fn authenticate(state: &AppState, token: &str) -> Result<AuthenticatedUser, ApiError> {
    let claims = claims(token, state.jwt_secret.as_bytes())?;
    let connection = crate::db::checkout(state).await?;
    let row = crate::db::query_one_optional(state, connection,
        "SELECT u.id, COALESCE(trunc(extract(epoch FROM u.password_changed_at))::bigint, 0), EXISTS(SELECT 1 FROM revoked_tokens r WHERE r.jti = $2) FROM users u WHERE u.username = $1 LIMIT 1",
        &[&claims.username, &claims.jti]).await?
        .ok_or_else(|| unauthorized("User not found"))?;
    if row.get::<_, bool>(2) {
        return Err(unauthorized("Token has been revoked"));
    }
    let password_epoch = if claims.password_epoch.is_null() {
        0
} else {
        integer(&claims.password_epoch).ok_or(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Internal Server Error".to_string(),
        ))?;
    };
    if password_epoch < row.get::<_, i64>(1) {
        return Err(unauthorized("Password changed; please sign in again."));
    }
    Ok(AuthenticatedUser { id: row.get(0) })
}

impl FromRequestParts<Arc<AppState>> for AuthenticatedUser {
    type Rejection = ApiError;
    async fn from_request_parts(
        parts: &mut Parts,
        state: &Arc<AppState>,
    ) -> Result<Self, Self::Rejection> {
        authenticate(state, bearer(parts)?).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use jsonwebtoken::{encode, EncodingKey, Header};
    use serde_json::json;

    #[test]
    fn reject_wrong_algorithm_wrong_signature_and_unsigned_credentials() {
        let payload = json!({"sub":"reader", "jti":"test-jti", "type":"access"});
        let key = EncodingKey::from_secret(b"synthetic-test-key");
        let hs256 = encode(&Header::new(Algorithm::HS256), &payload, &key).unwrap();
        assert!(claims(&hs256, b"synthetic-test-key").is_ok());
        let wrong_key = claims(&hs256, b"other-key").err().unwrap();
        assert_eq!(wrong_key.0, StatusCode::UNAUTHORIZED);
        let hs384 = encode(&Header::new(Algorithm::HS384), &payload, &key).unwrap();
        assert!(claims(&hs384, b"synthetic-test-key").is_err());
        assert!(claims("eyJhbGciOiJub25lIn0.e30.", b"synthetic-test-key").is_err());
    }
}
