//! Emit the native v2 queue OpenAPI document for contract review and drift checks.
use comicpile_roll_service::queue::QueueApi;
use utoipa::OpenApi;

fn main() {
    println!(
        "{}",
        QueueApi::openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document")
    );
}
