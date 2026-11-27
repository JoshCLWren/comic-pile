#![allow(clippy::unwrap_used, clippy::expect_used)]
use utoipa::OpenApi;
fn main() {
    println!("{}", comicpile_roll_service::threads::ThreadsApi::openapi().to_pretty_json().expect("json"));
}
