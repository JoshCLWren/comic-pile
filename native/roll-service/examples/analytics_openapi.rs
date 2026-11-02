//! Emit the native v2 analytics metrics OpenAPI contract.
use comicpile_roll_service::analytics::AnalyticsApi;
use utoipa::OpenApi;

fn main() {
    println!(
        "{}",
        AnalyticsApi::openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document")
    );
}
