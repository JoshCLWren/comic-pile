//! Emit the native skip OpenAPI operation for contract comparison.
use comicpile_roll_service::skip::SkipApi;
use utoipa::OpenApi;

fn main() {
    println!(
        "{}",
        SkipApi::openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document")
    );
}
