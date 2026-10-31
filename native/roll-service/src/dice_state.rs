//! Session-independent, owner-scoped logical dice projection for Roll #4405.
//! New mutations will record an explicit die_after; existing session-based
//! mutations remain on their current contracts until the coordinated cutover.
use crate::{auth::AuthenticatedUser, db, ApiError};
use tokio_postgres::Transaction;

pub const DEFAULT_DIE: i32 = 6;
pub const DICE_LADDER: [i32; 7] = [2, 4, 6, 8, 10, 12, 20];

/// Latest stored outcome, not a replay of events or a session-start clock.
/// Legacy 30/50/100 events remain stored unchanged; only their projection is
/// capped at d20. Roll offers without outcomes and direct reads do not change
/// dice state. Both timestamp and ID are needed for deterministic ordering.
const LATEST_DIE_SQL: &str = "
SELECT die_after
FROM events
WHERE user_id = $1
  AND type IN ('rate', 'snooze', 'undo', 'manual_die', 'reset_dice')
  AND die_after IN (2, 4, 6, 8, 10, 12, 20, 30, 50, 100)
ORDER BY timestamp DESC, id DESC
LIMIT 1";

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum DiceAction {
    RollRating(f64),
    Reroll,
    ManualSelect(i32),
    Reset,
    DirectMarkRead,
}

/// Historic d30/d50/d100 outcomes become a *current* d20, without rewriting
/// the original event or treating past ratings as if they were new ratings.
pub fn projected_die(stored: Option<i32>) -> i32 {
    match stored {
        Some(30 | 50 | 100) => 20,
        Some(die) if DICE_LADDER.contains(&die) => die,
        _ => DEFAULT_DIE,
    }
}

/// Compute the outcome for one command. Callers persist the resulting
/// die_after once in the same transaction as the action, never pin a manual
/// selection, and use the returned value for the next logical command.
pub fn apply_action(current: i32, action: DiceAction) -> Result<i32, &'static str> {
    let position = DICE_LADDER
        .iter()
        .position(|&die| die == current)
        .ok_or("invalid current die")?;
    match action {
        DiceAction::Reset => Ok(DEFAULT_DIE),
        DiceAction::ManualSelect(die) => DICE_LADDER
            .contains(&die)
            .then_some(die)
            .ok_or("invalid manual die"),
        DiceAction::DirectMarkRead => Ok(current),
        DiceAction::Reroll => Ok(DICE_LADDER[(position + 1).min(DICE_LADDER.len() - 1)]),
        DiceAction::RollRating(rating) if rating.is_finite() && (0.0..=5.0).contains(&rating) => {
            if rating >= 4.0 {
                Ok(DICE_LADDER[position.saturating_sub(1)])
            } else {
                Ok(DICE_LADDER[(position + 1).min(DICE_LADDER.len() - 1)])
            }
        }
        DiceAction::RollRating(_) => Err("invalid rating"),
    }
}

/// Query just the newest effective event belonging to the authenticated user.
/// No session id, session expiration, snapshot, write, or unbounded replay.
pub async fn current_die(tx: &Transaction<'_>, user: AuthenticatedUser) -> Result<i32, ApiError> {
    let row = tx
        .query_opt(LATEST_DIE_SQL, &[&user.id()])
        .await
        .map_err(db::query_error)?;
    Ok(projected_die(row.map(|row| row.get::<_, i32>(0))))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_reset_and_legacy_values() {
        assert_eq!(projected_die(None), 6);
        for old in [30, 50, 100] {
            assert_eq!(projected_die(Some(old)), 20);
        }
        for new in DICE_LADDER {
            assert_eq!(projected_die(Some(new)), new);
        }
        assert_eq!(projected_die(Some(5)), 6);
        assert_eq!(apply_action(20, DiceAction::Reset), Ok(6));
    }

    #[test]
    fn ratings_use_four_point_zero_and_both_boundaries() {
        assert_eq!(apply_action(6, DiceAction::RollRating(4.0)), Ok(4));
        assert_eq!(apply_action(6, DiceAction::RollRating(3.999)), Ok(8));
        assert_eq!(apply_action(6, DiceAction::RollRating(5.0)), Ok(4));
        assert_eq!(apply_action(2, DiceAction::RollRating(4.5)), Ok(2));
        assert_eq!(apply_action(20, DiceAction::RollRating(1.0)), Ok(20));
        assert_eq!(apply_action(20, DiceAction::Reroll), Ok(20));
        assert!(apply_action(6, DiceAction::RollRating(f64::NAN)).is_err());
        assert!(apply_action(6, DiceAction::RollRating(-1.0)).is_err());
    }

    #[test]
    fn manual_choice_is_not_pinned_direct_read_does_not_move() {
        let chosen = apply_action(6, DiceAction::ManualSelect(12)).unwrap();
        assert_eq!(chosen, 12);
        assert_eq!(apply_action(chosen, DiceAction::RollRating(4.5)), Ok(10));
        assert_eq!(apply_action(chosen, DiceAction::Reroll), Ok(20));
        assert_eq!(apply_action(chosen, DiceAction::DirectMarkRead), Ok(12));
        assert_eq!(
            apply_action(6, DiceAction::ManualSelect(30)),
            Err("invalid manual die")
        );
    }

    #[tokio::test]
    async fn newest_event_is_owner_scoped_and_ties_break_by_id() {
        // CI can run this with the same disposable local PostgreSQL as other
        // Rust database tests. Do not connect to a production database.
        let Ok(url) = std::env::var("RUST_ROLL_TEST_DATABASE_URL") else {
            return;
        };
        let (mut client, connection) = tokio_postgres::connect(&url, tokio_postgres::NoTls)
            .await
            .expect("disposable PostgreSQL");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        let tx = client.transaction().await.unwrap();
        tx.batch_execute(
            "
            CREATE TEMP TABLE events (
                id integer NOT NULL, user_id integer NOT NULL,
                type text NOT NULL, die_after integer,
                timestamp timestamptz NOT NULL
            );
            INSERT INTO events VALUES
                (1, 10, 'rate', 8, '2026-10-29 10:00+00'),
                (2, 10, 'rate', 50, '2026-10-29 11:00+00'),
                (3, 20, 'reset_dice', 2, '2026-10-30 12:00+00'),
                (4, 10, 'direct_mark_read', NULL, '2026-10-30 12:00+00'),
                (5, 10, 'snooze', 12, '2026-10-29 11:00+00');
        ",
        )
        .await
        .unwrap();
        let read =
            |row: Option<tokio_postgres::Row>| projected_die(row.map(|row| row.get::<_, i32>(0)));
        assert_eq!(
            read(tx.query_opt(LATEST_DIE_SQL, &[&10_i32]).await.unwrap()),
            12
        );
        assert_eq!(
            read(tx.query_opt(LATEST_DIE_SQL, &[&20_i32]).await.unwrap()),
            2
        );
        assert_eq!(
            read(tx.query_opt(LATEST_DIE_SQL, &[&30_i32]).await.unwrap()),
            6
        );
        tx.rollback().await.unwrap();
    }
}
