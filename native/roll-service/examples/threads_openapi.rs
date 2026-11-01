//! Emit the native v2 reader threads OpenAPI contract.
use comicpile_roll_service::threads::ThreadsApi;
use utoipa::OpenApi;

fn main() {
    println!(
        "{}",
        ThreadsApi::openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document")
    );
}
