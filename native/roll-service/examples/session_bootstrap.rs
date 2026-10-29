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
        .ok()
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
    let result = if let Ok(id) = std::env::var("RUST_ROLL_TEST_SESSION_ID") {
        db::require_owned_reading_session(&state, user, id.parse().unwrap())
            .await
            .map(|_| serde_json::json!({"owned":true}))
    } else if std::env::var("RUST_ROLL_TEST_RESOLVE_ONLY").is_ok() {
        let mut c = db::checkout(&state).await.ok().unwrap();
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
