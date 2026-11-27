#![allow(clippy::unwrap_used, clippy::expect_used)]
fn main() {
    println!("{}", comicpile_roll_service::openapi::canonical_openapi().to_pretty_json().expect("json"));
}
