//! Shared `CRON_SECRET` authorization for native cron routes.
//!
//! Mirrors Python `app.config._usable_secret` /
//! `Settings.usable_cron_secret` and `app.access_control.require_cron_secret`:
//! a missing, empty, or placeholder value means the deployment has not
//! configured a usable secret, so the route must fail closed. The `Bearer`
//! scheme is matched case-insensitively (RFC 6750, Python's `scheme.lower()`)
//! and the presented secret is compared in constant time. Keeping the whole
//! gate here means every native cron route authorizes through exactly one
//! path instead of each carrying its own subtly different copy.

use crate::ApiError;
use axum::http::HeaderMap;

/// Values Python's `usable_cron_secret` treats as an unconfigured secret.
/// Keep in sync with `_PLACEHOLDER_SECRET_VALUES` in `app/config.py`.
const PLACEHOLDER_SECRET_VALUES: &[&str] = &[
    "",
    "[SENSITIVE]",
    "<redacted>",
    "redacted",
    "undefined",
    "null",
];

/// Return the trimmed secret, or `None` when it is missing, empty, or a
/// placeholder. Mirrors Python `_usable_secret` exactly, including the
/// uppercase-only `[SENSITIVE]` comparison: `stripped.lower()` can never match
/// the mixed-case literal in the set, so that explicit check is intentional
/// parity rather than a redundant branch.
pub(crate) fn usable_cron_secret(value: Option<&str>) -> Option<&str> {
    let value = value?;
    let stripped = value.trim();
    if stripped.is_empty() {
        return None;
    }
    if PLACEHOLDER_SECRET_VALUES.contains(&stripped.to_lowercase().as_str()) {
        return None;
    }
    if stripped == "[SENSITIVE]" {
        return None;
    }
    Some(stripped)
}

/// Why a native cron request was rejected, so each route can map the shared
/// result onto its own HTTP error type without reimplementing the check.
#[derive(Debug, PartialEq, Eq)]
pub(crate) enum CronAuthError {
    /// No usable `CRON_SECRET` is configured (fail closed, HTTP 503).
    NotConfigured,
    /// The bearer is missing, malformed, or does not match (HTTP 401).
    Unauthorized,
}

/// Compare bearer material without short-circuiting on the first difference.
fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right)
        .fold(0_u8, |acc, (a, b)| acc | (a ^ b))
        == 0
}

/// Authorize a native cron request through the one shared path.
///
/// Fails closed as [`CronAuthError::NotConfigured`] when the configured secret
/// is missing/empty/placeholder, then requires a case-insensitive `Bearer`
/// scheme and a constant-time match of the presented secret. Credentials are
/// never logged.
pub(crate) fn authorize_cron(
    headers: &HeaderMap,
    expected: Option<&str>,
) -> Result<(), CronAuthError> {
    let secret = usable_cron_secret(expected).ok_or(CronAuthError::NotConfigured)?;
    let presented = headers
        .get("authorization")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| {
            let (scheme, presented) = value.split_once(' ')?;
            (scheme.eq_ignore_ascii_case("bearer") && !presented.is_empty()).then_some(presented)
        });
    match presented {
        Some(value) if constant_time_eq(value.as_bytes(), secret.as_bytes()) => Ok(()),
        _ => Err(CronAuthError::Unauthorized),
    }
}

/// Authorize a native cron request and map the typed rejection onto the HTTP
/// error shared by every native route: an unconfigured/placeholder `CRON_SECRET`
/// is a fail-closed 503, while a missing or incorrect bearer is a 401. Both
/// native cron routes (release sync and ComicVine repair) call this one helper,
/// so the status split against Python's `require_cron_secret` cannot drift
/// between them. Credentials are never logged.
pub(crate) fn authorize_cron_http(
    headers: &HeaderMap,
    expected: Option<&str>,
) -> Result<(), ApiError> {
    authorize_cron(headers, expected).map_err(|reason| match reason {
        CronAuthError::NotConfigured => {
            ApiError::ServiceUnavailable("Cron endpoint is not configured".to_string())
        }
        CronAuthError::Unauthorized => ApiError::Unauthorized("Unauthorized".to_string()),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::StatusCode;

    #[test]
    fn rejects_placeholder_values_with_python_case_rules() {
        for value in [
            "",
            "   ",
            "[SENSITIVE]",
            "  [SENSITIVE]  ",
            "<redacted>",
            "<REDACTED>",
            "redacted",
            "REDACTED",
            "undefined",
            "UNDEFINED",
            "null",
            "NULL",
        ] {
            assert!(
                usable_cron_secret(Some(value)).is_none(),
                "value: {value:?}"
            );
        }
        assert!(usable_cron_secret(None).is_none());
    }

    #[test]
    fn accepts_real_secrets_and_trims_surrounding_whitespace() {
        assert_eq!(
            usable_cron_secret(Some("  a-very-secret-value  ")),
            Some("a-very-secret-value")
        );
        // Python's `.lower()` quirk: lowercase `[sensitive]` remains usable.
        assert_eq!(usable_cron_secret(Some("[sensitive]")), Some("[sensitive]"));
    }

    #[test]
    fn authorize_cron_accepts_case_insensitive_bearer_and_rejects_wrong_secret() {
        for scheme in ["bearer", "BEARER", "Bearer"] {
            let mut headers = HeaderMap::new();
            headers.insert(
                "authorization",
                format!("{scheme} a-very-secret-value")
                    .parse()
                    .expect("valid header"),
            );
            assert_eq!(
                authorize_cron(&headers, Some("a-very-secret-value")),
                Ok(()),
                "scheme: {scheme}"
            );
        }
        let mut wrong = HeaderMap::new();
        wrong.insert(
            "authorization",
            "Bearer not-the-secret".parse().expect("valid header"),
        );
        assert_eq!(
            authorize_cron(&wrong, Some("a-very-secret-value")),
            Err(CronAuthError::Unauthorized)
        );
    }

    #[test]
    fn authorize_cron_rejects_placeholders_as_not_configured() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            "Bearer a-very-secret-value".parse().expect("valid header"),
        );
        for placeholder in [
            "",
            "[SENSITIVE]",
            "<redacted>",
            "redacted",
            "undefined",
            "null",
        ] {
            assert_eq!(
                authorize_cron(&headers, Some(placeholder)),
                Err(CronAuthError::NotConfigured),
                "placeholder: {placeholder:?}"
            );
        }
    }

    #[test]
    fn authorize_cron_http_maps_not_configured_to_503_and_bad_bearer_to_401() {
        let headers = {
            let mut headers = HeaderMap::new();
            headers.insert(
                "authorization",
                "Bearer a-very-secret-value".parse().expect("valid header"),
            );
            headers
        };
        // Missing and placeholder secrets are fail-closed 503s, not 401s.
        for expected in [None, Some("<redacted>"), Some("null")] {
            assert_eq!(
                authorize_cron_http(&headers, expected)
                    .expect_err("unconfigured secret")
                    .status(),
                StatusCode::SERVICE_UNAVAILABLE,
                "expected: {expected:?}"
            );
        }
        let mut wrong = HeaderMap::new();
        wrong.insert(
            "authorization",
            "Bearer not-the-secret".parse().expect("valid header"),
        );
        assert_eq!(
            authorize_cron_http(&wrong, Some("a-very-secret-value"))
                .expect_err("wrong bearer")
                .status(),
            StatusCode::UNAUTHORIZED
        );
        let missing_bearer = HeaderMap::new();
        assert_eq!(
            authorize_cron_http(&missing_bearer, Some("a-very-secret-value"))
                .expect_err("missing bearer")
                .status(),
            StatusCode::UNAUTHORIZED
        );
    }
}
