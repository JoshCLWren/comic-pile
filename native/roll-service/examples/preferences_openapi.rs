//! Emit the native same-path preferences OpenAPI contract.
use comicpile_roll_service::preferences::PreferencesApi;
use utoipa::OpenApi;

fn main() {
    println!(
        "{}",
        PreferencesApi::openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document")
    );
}
