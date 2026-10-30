//! Local parity runner. Never mounted on the service's public router.
use comicpile_roll_service::{auth, config::Config, reading_inputs, AppState};
#[tokio::main]
async fn main() {
    let state = AppState::new(Config::from_env().expect("local configuration required")).unwrap();
    let token = std::env::var("RUST_ROLL_TEST_TOKEN").expect("synthetic token required");
    let user = auth::authenticate(&state, &token)
        .await
        .ok()
        .expect("fixture authentication");
    match reading_inputs::load_core_inputs(&state, user).await {
        Ok(inputs) => println!("{}", serde_json::to_string(&inputs).unwrap()),
        Err(error) => {
            eprintln!("snapshot failed: {} {}", error.0, error.1);
            std::process::exit(1);
        }
    }
}
