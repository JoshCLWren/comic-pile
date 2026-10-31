//! Shared bounding for the Option E Roll pool.
//!
//! Bootstrap and the Roll offer must rank the same validated frontiers and
//! apply the same top-`die` bound. Temporary exclusions (browser cookie
//! snoozes and the previous pending offer) belong to the offer only; bootstrap
//! has no authority over them and must never apply legacy session skip/snooze
//! arrays or the durable Fibonacci backoff to the in-play pool.
use crate::reading_constraints::EligibleFrontier;
use std::collections::HashSet;

/// Take the highest-ranked `die` candidates. Callers apply any temporary
/// exclusions after this bound, so a hidden face is never backfilled from
/// below the die.
pub(crate) fn bounded_pool<T>(
    candidates: impl IntoIterator<Item = T>,
    is_excluded: impl Fn(&T) -> bool,
    die: i32,
) -> Vec<T> {
    candidates
        .into_iter()
        .take(die.max(0) as usize)
        .filter(|candidate| !is_excluded(candidate))
        .collect()
}

/// The in-play pool displayed by bootstrap: the Option E top-`die` frontiers
/// with no session, durable, or cookie authority.
pub(crate) fn in_play_frontiers(
    candidates: &[EligibleFrontier],
    die: i32,
) -> Vec<EligibleFrontier> {
    bounded_pool(candidates.iter().copied(), |_| false, die)
}

/// The offer pool: the same top-`die` bound, then only temporary exclusions.
pub(crate) fn offer_frontiers(
    candidates: &[EligibleFrontier],
    excluded: &HashSet<i32>,
    die: i32,
) -> Vec<EligibleFrontier> {
    bounded_pool(
        candidates.iter().copied(),
        |candidate| excluded.contains(&candidate.thread_id),
        die,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frontier(thread_id: i32) -> EligibleFrontier {
        EligibleFrontier {
            thread_id,
            issue_id: thread_id * 100,
            queue_position: thread_id,
        }
    }

    #[test]
    fn top_die_bound_is_applied_before_exclusions() {
        let candidates: Vec<_> = (1..=12).map(frontier).collect();
        let excluded = HashSet::from([2, 3]);

        let offer = offer_frontiers(&candidates, &excluded, 10);
        let ids: Vec<_> = offer.iter().map(|candidate| candidate.thread_id).collect();
        assert_eq!(ids, vec![1, 4, 5, 6, 7, 8, 9, 10]);

        let in_play = in_play_frontiers(&candidates, 10);
        assert_eq!(
            in_play
                .iter()
                .map(|candidate| candidate.thread_id)
                .collect::<Vec<_>>(),
            (1..=10).collect::<Vec<_>>(),
            "bootstrap must not apply temporary or legacy exclusions"
        );
        assert_eq!(
            in_play,
            offer_frontiers(&candidates, &HashSet::new(), 10),
            "empty-exclusion offer and bootstrap must expose the same faces"
        );
    }

    #[test]
    fn selecting_more_faces_than_candidates_is_bounded_by_the_pool() {
        let candidates: Vec<_> = (1..=3).map(frontier).collect();
        assert_eq!(in_play_frontiers(&candidates, 10), candidates);
        assert!(in_play_frontiers(&candidates, 0).is_empty());
        assert!(in_play_frontiers(&[], 10).is_empty());
    }
}
