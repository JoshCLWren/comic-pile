//! Native process entry point: bind once, drain on SIGINT/SIGTERM, close the pool.
use comicpile_roll_service::{config::Config, router, serve, AppState};
use std::{process::ExitCode, sync::Arc};

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
    serve(listener, router(state.clone()), state, shutdown_signal()).await
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
