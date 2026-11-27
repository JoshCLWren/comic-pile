//! Single typed accessor for the approved Reading List engine runtime setting (#4747).
//!
//! Reading List engine (evaluated reading eligibility) is an owner-approved rollout
//! setting, not a cutover feature flag. It is effective only when
//! `READING_LISTS_ENABLED` is truthy AND `READING_LISTS_APPROVED_PREVIEW` carries a
//! non-blank owner-approval reference. Every handler (Queue, thread list and
//! detail, Roll offer, bootstrap, thread issues, ordering, lifecycle) resolves
//! the setting through `AppState::reading_lists`, parsed exactly once at startup by
//! [`reading_lists_from_lookup`] (via `Config`); no other module reads these
//! variables and tests inject the value instead of mutating the environment. When the setting is not effective, production runs the legacy
//! stored `threads.is_blocked` authority with no extra statement.

const ENABLED_VAR: &str = "READING_LISTS_ENABLED";
const APPROVAL_VAR: &str = "READING_LISTS_APPROVED_PREVIEW";

/// Parse the activation switch with the same truthy set Python's pydantic bool uses.
fn truthy(value: &str) -> bool {
    matches!(
        value.trim().to_ascii_lowercase().as_str(),
        "1" | "true" | "t" | "yes" | "y" | "on"
    )
}

/// Resolve the effective setting from raw variable values (pure, testable).
pub(crate) fn reading_lists_effective(enabled: Option<&str>, approval: Option<&str>) -> bool {
    enabled.is_some_and(truthy) && approval.is_some_and(|value| !value.trim().is_empty())
}

/// Resolve the setting once from an injectable lookup (startup parses the
/// process environment; tests pass an explicit closure, never mutate env).
pub(crate) fn reading_lists_from_lookup(get: impl Fn(&str) -> Option<String>) -> bool {
    reading_lists_effective(get(ENABLED_VAR).as_deref(), get(APPROVAL_VAR).as_deref())
}

#[cfg(test)]
mod tests {
    use super::reading_lists_effective;

    #[test]
    fn effective_only_with_truthy_switch_and_nonblank_approval() {
        for truthy in ["1", "true", "TRUE", " yes ", "on", "t", "y"] {
            assert!(reading_lists_effective(Some(truthy), Some("ref-1")), "{truthy}");
        }
        for falsy in ["", "0", "false", "no", "off", "enabled", "2"] {
            assert!(!reading_lists_effective(Some(falsy), Some("ref-1")), "{falsy}");
        }
        assert!(!reading_lists_effective(None, Some("ref-1")));
        assert!(!reading_lists_effective(Some("true"), None));
        assert!(!reading_lists_effective(Some("true"), Some("   ")));
        assert!(!reading_lists_effective(None, None));
    }
}
