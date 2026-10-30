//! Local parity runner. Never mounted on the service's public router.
use comicpile_roll_service::{auth, config::Config, option_inputs, AppState};
#[tokio::main]
async fn main() {
    let state = AppState::new(Config::from_env().expect("local configuration required")).unwrap();
    let token = std::env::var("RUST_ROLL_TEST_TOKEN").expect("synthetic token required");
    let user = auth::authenticate(&state, &token)
        .await
        .ok()
        .expect("fixture authentication");
    match option_inputs::load_option_diagnostics(&state, user).await {
        Ok(inputs) => {
            println!("{}", serde_json::to_string(&inputs).unwrap());
            if inputs.require_resolved().is_err() {
                std::process::exit(2);
            }
        }
        Err(error) => {
            eprintln!("snapshot failed: {} {}", error.0, error.1);
            std::process::exit(1);
        }
    }
}
