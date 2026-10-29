//! Exercise the production server lifecycle with controlled in-flight handlers.
use axum::{routing::get, Router};
use comicpile_roll_service::{config::Config, serve, AppState};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::{oneshot, Notify},
};

fn state() -> Arc<AppState> {
    let mut config = Config::from_lookup(|key| match key {
        "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
        "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
        _ => None,
    })
    .unwrap();
    config.request_timeout = Duration::from_millis(20);
    Arc::new(AppState::new(config).unwrap())
}

#[tokio::test]
async fn active_request_finishes_before_shutdown_closes_pool() {
    let state = state();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let started = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let app = Router::new().route(
        "/work",
        get({
            let started = started.clone();
            let release = release.clone();
            move || {
                let started = started.clone();
                let release = release.clone();
                async move {
                    started.notify_one();
                    release.notified().await;
                    "finished work"
                }
            }
        }),
    );
    let (stop, stopped) = oneshot::channel();
    let server = tokio::spawn(serve(listener, app, state.clone(), async {
        let _ = stopped.await;
    }));
    let mut socket = TcpStream::connect(address).await.unwrap();
    socket
        .write_all(b"GET /work HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        .await
        .unwrap();
    tokio::time::timeout(Duration::from_secs(1), started.notified())
        .await
        .unwrap();
    stop.send(()).unwrap();
    tokio::time::sleep(Duration::from_millis(10)).await;
    assert!(
        !server.is_finished(),
        "active work was dropped during drain"
    );
    assert!(!state.pool.is_closed());
    release.notify_one();
    let mut response = String::new();
    tokio::time::timeout(Duration::from_secs(1), socket.read_to_string(&mut response))
        .await
        .unwrap()
        .unwrap();
    assert!(response.contains("finished work"));
    assert!(tokio::time::timeout(Duration::from_secs(1), server)
        .await
        .unwrap()
        .unwrap()
        .is_ok());
    assert!(state.pool.is_closed());
}

#[tokio::test]
async fn hard_deadline_stops_work_that_never_finishes() {
    let state = state();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let started = Arc::new(Notify::new());
    let app = Router::new().route(
        "/stalled",
        get({
            let started = started.clone();
            move || {
                let started = started.clone();
                async move {
                    started.notify_one();
                    std::future::pending::<&'static str>().await
                }
            }
        }),
    );
    let (stop, stopped) = oneshot::channel();
    let server = tokio::spawn(serve(listener, app, state.clone(), async {
        let _ = stopped.await;
    }));
    let mut socket = TcpStream::connect(address).await.unwrap();
    socket
        .write_all(b"GET /stalled HTTP/1.1\r\nHost: localhost\r\n\r\n")
        .await
        .unwrap();
    tokio::time::timeout(Duration::from_secs(1), started.notified())
        .await
        .unwrap();
    let since = Instant::now();
    stop.send(()).unwrap();
    let result = tokio::time::timeout(Duration::from_secs(2), server)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(result, Err("shutdown drain deadline exceeded"));
    assert!(since.elapsed() >= Duration::from_secs(1));
    assert!(state.pool.is_closed());
    drop(socket);
}
