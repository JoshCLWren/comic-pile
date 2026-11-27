#![allow(clippy::unwrap_used, clippy::expect_used)]
fn main() {
    println!("{}", comicpile_roll_service::same_path_openapi::same_path_openapi().to_pretty_json().expect("json"));
}
