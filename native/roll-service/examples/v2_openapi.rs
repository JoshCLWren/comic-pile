//! Emit the canonical native v2 OpenAPI contract for every deployed operation.
use comicpile_roll_service::openapi::canonical_openapi;

fn main() {
    println!(
        "{}",
        canonical_openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document")
    );
}
