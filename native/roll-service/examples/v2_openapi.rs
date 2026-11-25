#![allow(clippy::unwrap_used, clippy::expect_used)]
use comicpile_roll_service::openapi::canonical_openapi;
fn main() {
    println!("{}", canonical_openapi().to_pretty_json().expect("serializable OpenAPI document"));
}
