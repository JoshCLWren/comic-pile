//! Read-only, loopback-only, authenticated slice of the Roll v2 projection.
//! Intentionally NOT a replacement for /api/v2/roll/bootstrap.
use axum::{
    extract::{Path, State},
    http::{header::AUTHORIZATION, HeaderMap, StatusCode},
    routing::get,
    Json, Router,
};
use chrono::{DateTime, Utc};
use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation};
use serde::{Deserialize, Serialize};
use std::{env, net::Ipv4Addr, sync::Arc};
use tokio_postgres::NoTls;
use url::Url;

#[derive(Clone)]
struct AppState {
    database_url: String,
    jwt_key: Arc<String>,
}

#[derive(Debug, Deserialize)]
struct Claims {
    sub: String,
    jti: String,
    #[serde(rename = "type")]
    token_type: String,
    exp: usize,
}

#[derive(Debug, Serialize, PartialEq)]
struct LastRead {
    issue_id: Option<i32>,
    issue_number: Option<String>,
    thread_id: Option<i32>,
    thread_title: Option<String>,
    read_at: Option<DateTime<Utc>>,
}

async fn last_read(
    State(state): State<AppState>,
    Path(session_id): Path<i32>,
    headers: HeaderMap,
) -> Result<Json<Option<LastRead>>, StatusCode> {
    let token = headers
        .get(AUTHORIZATION)
        .and_then(|h| h.to_str().ok())
        .and_then(|h| h.strip_prefix("Bearer "))
        .ok_or(StatusCode::UNAUTHORIZED)?;
    let mut validation = Validation::new(Algorithm::HS256);
    validation.algorithms = vec![Algorithm::HS256];
    let claims = decode::<Claims>(
        token,
        &DecodingKey::from_secret(state.jwt_key.as_bytes()),
        &validation,
    )
    .map_err(|_| StatusCode::UNAUTHORIZED)?
    .claims;
    if claims.token_type != "access" || claims.sub.is_empty() || claims.jti.is_empty() {
        return Err(StatusCode::UNAUTHORIZED);
    }

    // One connection per request, matching a cold database-backed operation.
    // Do not connect at startup: readiness captures the native runtime floor.
    let (client, connection) = tokio_postgres::connect(&state.database_url, NoTls)
        .await
        .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    tokio::spawn(async move {
        let _ = connection.await;
    });
    let owner = client
        .query_opt(
            "SELECT u.id FROM users AS u WHERE u.username = $1
             AND NOT EXISTS (
               SELECT 1 FROM revoked_tokens AS r
               WHERE r.user_id = u.id AND r.jti = $2
             )",
            &[&claims.sub, &claims.jti],
        )
        .await
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?
        .ok_or(StatusCode::UNAUTHORIZED)?;
    let user_id: i32 = owner.get(0);
    // Scoped to the session owner, never expose another user's history.
    let owns_session = client
        .query_opt(
            "SELECT id FROM sessions WHERE id = $1 AND user_id = $2",
            &[&session_id, &user_id],
        )
        .await
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?
        .is_some();
    if !owns_session {
        return Err(StatusCode::NOT_FOUND);
    }

    // Mirrors app.repositories.roll_v2_projection.fetch_session_last_read:
    // latest rate event, descending (timestamp, id), nullable issue fields.
    let row = client
        .query_opt(
            "SELECT e.issue_id, COALESCE(i.issue_number, e.issue_number),
                    e.thread_id, t.title, e.timestamp
             FROM events AS e
             LEFT JOIN issues AS i ON i.id = e.issue_id
             LEFT JOIN threads AS t ON t.id = e.thread_id AND t.user_id = $2
             WHERE e.session_id = $1 AND e.type = 'rate'
             ORDER BY e.timestamp DESC, e.id DESC LIMIT 1",
            &[&session_id, &user_id],
        )
        .await
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(row.map(|r| LastRead {
        issue_id: r.get(0),
        issue_number: r.get(1),
        thread_id: r.get(2),
        thread_title: r.get(3),
        read_at: r.get(4),
    })))
}

fn validate_url(raw: &str) -> Result<(), String> {
    let url = Url::parse(raw).map_err(|_| "Invalid database URL")?;
    if !matches!(url.scheme(), "postgres" | "postgresql")
        || url.host_str() != Some("127.0.0.1")
        || url.port_or_known_default() != Some(55435)
    {
        return Err("Database must be postgresql://127.0.0.1:55435".into());
    }
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let database_url = env::var("LOCAL_PROFILE_DATABASE_URL")?;
    validate_url(&database_url).map_err(std::io::Error::other)?;
    let jwt_key = env::var("SECRET_KEY")?;
    if jwt_key.is_empty() {
        return Err("SECRET_KEY is required".into());
    }
    let port: u16 = env::var("RUST_SPIKE_PORT")?.parse()?;
    let state = AppState {
        database_url,
        jwt_key: Arc::new(jwt_key),
    };
    let app = Router::new()
        .route("/health", get(|| async { Json(serde_json::json!({"ok": true})) }))
        .route("/spike/sessions/:session_id/last-read", get(last_read))
        .with_state(state);
    let listener = tokio::net::TcpListener::bind((Ipv4Addr::LOCALHOST, port)).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_remote_database_urls() {
        assert!(validate_url("postgresql://127.0.0.1:55435/local").is_ok());
        for bad in [
            "postgresql://localhost:55435/local",
            "postgresql://127.0.0.1:5432/local",
            "postgresql://production.example.com:55435/db",
            "https://127.0.0.1:55435/db",
        ] {
            assert!(validate_url(bad).is_err(), "{bad}");
        }
    }
}
