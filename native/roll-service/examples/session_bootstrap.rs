//! Disposable parity runner, never mounted on a public router.
use comicpile_roll_service::{
    auth,
    config::Config,
    db,
    reading_session::{self, SessionPolicy},
    AppState,
};
#[tokio::main]
async fn main() {
    let state = AppState::new(Config::from_env().expect("local configuration")).unwrap();
    let token = std::env::var("RUST_ROLL_TEST_TOKEN").expect("synthetic token");
    let now = std::env::var("RUST_ROLL_TEST_NOW")
        .expect("fixed clock")
        .parse()
        .unwrap();
    let user = auth::authenticate(&state, &token)
        .await
        .expect("fixture authentication");
    let timezone = std::env::var("RUST_ROLL_TEST_TIMEZONE").ok();
    let policy = SessionPolicy::new(
        std::env::var("SESSION_GAP_HOURS")
            .unwrap_or_else(|_| "6".into())
            .parse()
            .unwrap(),
        std::env::var("START_DIE")
            .unwrap_or_else(|_| "6".into())
            .parse()
            .unwrap(),
    )
    .unwrap();
    // Parity cancellation mode: the process and its single-connection pool
    // outlive the abandoned bootstrap future. A byte on stdin cancels Rust work
    // while the database is still blocked on the fixture's advisory lock.
    if std::env::var_os("RUST_ROLL_TEST_CANCEL_ON_STDIN").is_some() {
        let cancellation = tokio::task::spawn_blocking(|| {
            use std::io::Read;
            let mut command = [0u8; 1];
            std::io::stdin().read_exact(&mut command)
        });
        let completed = tokio::select! {
            result = reading_session::bootstrap_at(
                &state, user, timezone.as_deref(), policy, now
            ) => Some(result),
            input = cancellation => {
                input.expect("cancellation reader panicked").expect("cancellation input");
                None
            }
        };
        if completed.is_some() {
            eprintln!("bootstrap completed before the cancellation signal");
            std::process::exit(1);
        }
        // Run a query through the SAME pool before releasing the SQL blocker.
        // Returning a still-busy connection would hang here instead of passing.
        let checkout = tokio::time::timeout(std::time::Duration::from_secs(3), async {
            let connection = db::checkout(&state).await.expect("post-cancel checkout");
            let row = connection
                .query_one("SELECT 1::int4", &[])
                .await
                .expect("post-cancel query");
            assert_eq!(row.get::<_, i32>(0), 1);
        })
        .await;
        if checkout.is_err() {
            eprintln!("post-cancel checkout or query timed out");
            std::process::exit(1);
        }
        println!(
            "{}",
            serde_json::json!({"cancelled":true,"checkout_usable":true})
        );
        return;
    }
    let result = if let Ok(id) = std::env::var("RUST_ROLL_TEST_SESSION_ID") {
        db::require_owned_reading_session(&state, user, id.parse().unwrap())
            .await
            .map(|_| serde_json::json!({"owned":true}))
    } else if std::env::var("RUST_ROLL_TEST_RESOLVE_ONLY").is_ok() {
        let mut c = db::checkout(&state).await.expect("session checkout");
        let tx = c.build_transaction().read_only(true).start().await.unwrap();
        let s = reading_session::resolve_current_session(&tx, user, now, policy).await;
        tx.rollback().await.unwrap();
        s.map(|s| serde_json::to_value(s).unwrap())
    } else {
        reading_session::bootstrap_at(&state, user, timezone.as_deref(), policy, now)
            .await
            .map(|s| serde_json::to_value(s).unwrap())
    };
    match result {
        Ok(s) => println!("{s}"),
        Err(e) => {
            eprintln!("session failed: {} {}", e.0, e.1);
            std::process::exit(1);
        }
    }
}
