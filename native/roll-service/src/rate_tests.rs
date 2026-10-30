//! Tests for the rate endpoint.
use super::*;
use crate::{config::Config, AppState};
use axum::body::Body;
use http::StatusCode;
use serde_json::json;
use std::sync::Arc;

#[tokio::test]
async fn test_rate_invalid_rating_range() {
    let config = Config::from_lookup(|name| match name {
        "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
        "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
        "RATING_MIN" => Some("0.5".into()),
        "RATING_MAX" => Some("5.0".into()),
        "RATING_THRESHOLD" => Some("3.5".into()),
        _ => None,
    })
    .unwrap();
    
    let state = Arc::new(AppState::new(config).unwrap());
    
    // Test rating too low
    assert_eq!(
        get_rating_limits(&state),
        (0.5, 5.0, 3.5)
    );
    
    // Test normalize format value
    assert_eq!(normalize_format_value("Comic Book"), "comic_book");
    assert_eq!(normalize_format_value("Trade Paperback"), "trade_paperback");
    assert_eq!(normalize_format_value("Graphic Novel"), "graphic_novel");
    assert_eq!(normalize_format_value("ONE-SHOT"), "one-shot");
    assert_eq!(normalize_format_value("MAGAZINE"), "magazine");
}