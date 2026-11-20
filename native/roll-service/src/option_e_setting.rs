//! Single typed accessor for the approved Option E runtime setting (#4747).
//!
//! Option E (evaluated reading eligibility) is an owner-approved rollout
//! setting, not a cutover feature flag. It is effective only when
//! `OPTION_E_ENABLED` is truthy AND `OPTION_E_APPROVED_PREVIEW` carries a
//! non-blank owner-approval reference. Every handler (Queue, thread list and
//! detail, Roll offer, bootstrap, thread issues, ordering, lifecycle) resolves
//! the setting through `AppState::option_e`, parsed exactly once at startup by
//! [`option_e_from_lookup`] (via `Config`); no other module reads these
//! variables and tests inject the value instead of mutating the environment. When the setting is not effective, production runs the legacy
//! stored `threads.is_blocked` authority with no extra statement.

const ENABLED_VAR: &str = "OPTION_E_ENABLED";
const APPROVAL_VAR: &str = "OPTION_E_APPROVED_PREVIEW";

/// Parse the activation switch with the same truthy set Python's pydantic bool uses.
fn truthy(value: &str) -> bool {
    matches!(
        value.trim().to_ascii_lowercase().as_str(),
        "1" | "true" | "t" | "yes" | "y" | "on"
    )
}

/// Resolve the effective setting from raw variable values (pure, testable).
pub(crate) fn option_e_effective(enabled: Option<&str>, approval: Option<&str>) -> bool {
    enabled.is_some_and(truthy) && approval.is_some_and(|value| !value.trim().is_empty())
}

/// Resolve the setting once from an injectable lookup (startup parses the
/// process environment; tests pass an explicit closure, never mutate env).
pub(crate) fn option_e_from_lookup(get: impl Fn(&str) -> Option<String>) -> bool {
    option_e_effective(get(ENABLED_VAR).as_deref(), get(APPROVAL_VAR).as_deref())
}

#[cfg(test)]
mod tests {
    use super::option_e_effective;

    #[test]
    fn effective_only_with_truthy_switch_and_nonblank_approval() {
        for truthy in ["1", "true", "TRUE", " yes ", "on", "t", "y"] {
            assert!(option_e_effective(Some(truthy), Some("ref-1")), "{truthy}");
        }
        for falsy in ["", "0", "false", "no", "off", "enabled", "2"] {
            assert!(!option_e_effective(Some(falsy), Some("ref-1")), "{falsy}");
        }
        assert!(!option_e_effective(None, Some("ref-1")));
        assert!(!option_e_effective(Some("true"), None));
        assert!(!option_e_effective(Some("true"), Some("   ")));
        assert!(!option_e_effective(None, None));
    }
}
