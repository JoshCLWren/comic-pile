//! Native process entry point: bind once, drain on SIGINT/SIGTERM, close the pool.
use comicpile_roll_service::{config::Config, router, AppState};
use std::{future::IntoFuture, process::ExitCode, sync::Arc, time::Duration};

#[tokio::main]
async fn main() -> ExitCode {
    match run().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("native Roll startup failed: {message}");
            ExitCode::FAILURE
        }
    }
}
async fn run() -> Result<(), &'static str> {
    let config = Config::from_env().map_err(|error| error.0)?;
    let bind = config.bind;
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(config.log_filter.clone())
        .try_init()
        .map_err(|_| "log initialization failed")?;
    let state = Arc::new(AppState::new(config).map_err(|error| error.0)?);
    let listener = tokio::net::TcpListener::bind(bind)
        .await
        .map_err(|_| "listener bind failed")?;
    tracing::info!(address = %bind, "native Roll listener started");
    let drain_timeout = state.request_timeout + Duration::from_secs(1);
    let (shutdown_send, mut shutdown_receive) = tokio::sync::watch::channel(false);
    let signal_task = tokio::spawn(async move {
        shutdown_signal().await;
        let _ = shutdown_send.send(true);
    });
    let mut graceful_receive = shutdown_receive.clone();
    let server = axum::serve(listener, router(state.clone()))
        .with_graceful_shutdown(async move {
            let _ = graceful_receive.changed().await;
        })
        .into_future();
    tokio::pin!(server);
    let result = tokio::select! {
        result = &mut server => result.map_err(|_| "HTTP server failed"),
        _ = shutdown_receive.changed() => {
            match tokio::time::timeout(drain_timeout, &mut server).await {
                Ok(result) => result.map_err(|_| "HTTP server failed"),
                Err(_) => Err("shutdown drain deadline exceeded"),
            }
        }
    };
    signal_task.abort();
    state.pool.close();
    result
}
async fn shutdown_signal() {
    let interrupt = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut signal) => {
                signal.recv().await;
            }
            Err(_) => {
                std::future::pending::<()>().await;
            }
        }
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();
    tokio::select! { _ = interrupt => {}, _ = terminate => {} }
    tracing::info!("draining native Roll requests");
}
