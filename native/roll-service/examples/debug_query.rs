use comicpile_roll_service::{config::Config, db, AppState};
#[tokio::main]
async fn main() {
    let config = Config::from_env().unwrap();
    let state = AppState::new(config).unwrap();
    let conn = match db::checkout(&state).await {
        Ok(c) => c,
        Err(e) => {
            println!("checkout err status {}", e.0);
            return;
        }
    };
    let rows = conn
        .query(
            "SELECT current_schema(), current_setting('search_path')",
            &[],
        )
        .await
        .unwrap();
    for r in &rows {
        println!("row: {:?}", r);
    }
    let res = conn.query("SELECT count(*)::int FROM users", &[]).await;
    println!("users count: {:?}", res);
    state.pool.close();
}
