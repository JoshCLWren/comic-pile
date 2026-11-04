//! Shared bounding for the Option E Roll pool.
//!
//! Bootstrap and the Roll offer must rank the same validated frontiers and
//! exclude temporary browser snoozes before applying the top-`die` bound.
//! Legacy session skips and durable backoff remain outside this pool.
use crate::reading_constraints::EligibleFrontier;
use std::collections::HashSet;

/// Maximum number of browser-supplied temporary snoozes one Roll request
/// accepts, whether they arrive in a request body or in a query parameter.
pub(crate) const MAX_TEMPORARY_SNOOZES: usize = 200;

/// Take the highest-ranked `die` candidates remaining after temporary exclusions.
pub(crate) fn bounded_pool<T>(
    candidates: impl IntoIterator<Item = T>,
    is_excluded: impl Fn(&T) -> bool,
    die: i32,
) -> Vec<T> {
    candidates
        .into_iter()
        .filter(|candidate| !is_excluded(candidate))
        .take(die.max(0) as usize)
        .collect()
}

/// Unexcluded reference pool used to verify legacy state has no authority.
#[cfg(test)]
pub(crate) fn in_play_frontiers(
    candidates: &[EligibleFrontier],
    die: i32,
) -> Vec<EligibleFrontier> {
    bounded_pool(candidates.iter().copied(), |_| false, die)
}

/// The offer pool: exclude snoozes across the library, then bound by the die.
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

/// Read only the existing browser snooze cookie. Malformed or oversized hints
/// cannot change the authoritative owner-scoped eligibility constraints.
pub(crate) fn browser_snoozes(headers: &axum::http::HeaderMap) -> HashSet<i32> {
    headers
        .get_all(axum::http::header::COOKIE)
        .iter()
        .filter_map(|header| header.to_str().ok())
        .flat_map(|header| header.split(';'))
        .find_map(|entry| entry.trim().strip_prefix("comicpile_roll_snoozes="))
        .and_then(|raw| {
            if raw.len() > 4096 {
                return None;
            }
            // encodeURIComponent encodes JSON brackets and commas. No other
            // escapes occur in the positive integer array written by the client.
            let decoded = raw
                .replace("%5B", "[")
                .replace("%5b", "[")
                .replace("%5D", "]")
                .replace("%5d", "]")
                .replace("%2C", ",")
                .replace("%2c", ",");
            let ids: Vec<i32> = serde_json::from_str(&decoded).ok()?;
            (ids.len() <= MAX_TEMPORARY_SNOOZES && ids.iter().all(|id| *id > 0))
                .then(|| ids.into_iter().collect())
        })
        .unwrap_or_default()
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
    fn exclusions_backfill_from_beyond_the_die() {
        let candidates: Vec<_> = (1..=12).map(frontier).collect();
        let excluded = HashSet::from([2, 3]);

        let offer = offer_frontiers(&candidates, &excluded, 10);
        let ids: Vec<_> = offer.iter().map(|candidate| candidate.thread_id).collect();
        assert_eq!(ids, vec![1, 4, 5, 6, 7, 8, 9, 10, 11, 12]);

        let in_play = in_play_frontiers(&candidates, 10);
        assert_eq!(
            in_play
                .iter()
                .map(|candidate| candidate.thread_id)
                .collect::<Vec<_>>(),
            (1..=10).collect::<Vec<_>>(),
            "the unexcluded reference ignores temporary and legacy exclusions"
        );
        assert_eq!(
            in_play,
            offer_frontiers(&candidates, &HashSet::new(), 10),
            "empty-exclusion offer and bootstrap must expose the same faces"
        );
    }

    #[test]
    fn snoozing_twenty_faces_reaches_the_rest_of_the_library() {
        let candidates: Vec<_> = (1..=45).map(frontier).collect();
        let excluded = (1..=20).collect();
        let pool = offer_frontiers(&candidates, &excluded, 20);
        assert_eq!(
            pool.iter().map(|c| c.thread_id).collect::<Vec<_>>(),
            (21..=40).collect::<Vec<_>>()
        );
    }

    #[test]
    fn browser_cookie_is_bounded_and_malformed_hints_are_ignored() {
        let mut headers = axum::http::HeaderMap::new();
        headers.insert(
            axum::http::header::COOKIE,
            "other=value; comicpile_roll_snoozes=%5B2%2C7%5D"
                .parse()
                .unwrap(),
        );
        assert_eq!(browser_snoozes(&headers), HashSet::from([2, 7]));
        for raw in ["[0]", "[-1]", "null", "[2,", "[2147483648]"] {
            headers.insert(
                axum::http::header::COOKIE,
                format!("comicpile_roll_snoozes={raw}").parse().unwrap(),
            );
            assert!(browser_snoozes(&headers).is_empty());
        }
        headers.insert(
            axum::http::header::COOKIE,
            format!(
                "comicpile_roll_snoozes={}",
                serde_json::to_string(&vec![1; 201]).unwrap()
            )
            .parse()
            .unwrap(),
        );
        assert!(browser_snoozes(&headers).is_empty());
        headers.remove(axum::http::header::COOKIE);
        assert!(browser_snoozes(&headers).is_empty());
    }

    #[test]
    fn exhausted_library_stays_empty_until_snoozes_are_cleared() {
        let candidates: Vec<_> = (1..=45).map(frontier).collect();
        let excluded = (1..=45).collect();
        assert!(offer_frontiers(&candidates, &excluded, 20).is_empty());
        assert_eq!(offer_frontiers(&candidates, &HashSet::new(), 20).len(), 20);
    }

    #[test]
    fn selecting_more_faces_than_candidates_is_bounded_by_the_pool() {
        let candidates: Vec<_> = (1..=3).map(frontier).collect();
        assert_eq!(in_play_frontiers(&candidates, 10), candidates);
        assert!(in_play_frontiers(&candidates, 0).is_empty());
        assert!(in_play_frontiers(&[], 10).is_empty());
    }
}
