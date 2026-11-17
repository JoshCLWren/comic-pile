//! Shared `CRON_SECRET` usability gate for native cron routes.
//!
//! Mirrors Python `app.config._usable_secret` /
//! `Settings.usable_cron_secret` and `app.access_control.require_cron_secret`:
//! a missing, empty, or placeholder value means the deployment has not
//! configured a usable secret, so the route must fail closed. Keeping the
//! check here makes every native cron route reject the same values.

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

#[cfg(test)]
mod tests {
    use super::*;

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
}
