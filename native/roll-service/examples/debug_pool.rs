use comicpile_roll_service::{config::Config, AppState};
#[tokio::main]
async fn main() {
    let config = Config::from_env().unwrap();
    let state = AppState::new(config).unwrap();
    match state.pool.get().await {
        Ok(_) => println!("pool ok"),
        Err(e) => println!("pool err: {:?}", e),
    }
    state.pool.close();
}
