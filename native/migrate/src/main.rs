//! `comicpile-migrate up|status|verify`.
//!
//! * `up`: apply pending migrations (adopting an Alembic database at the baseline head).
//! * `status`: read-only; print the state, fail if the database is not at an expected baseline.
//! * `verify`: like `status`, but also fail unless nothing is pending.
//!
//! The URL comes from `MIGRATE_DATABASE_URL`, falling back to `DATABASE_URL`;
//! a SQLAlchemy `+asyncpg`/`+psycopg` driver suffix is accepted and stripped.
use std::process::ExitCode;

#[tokio::main]
async fn main() -> ExitCode {
    let command = std::env::args().nth(1).unwrap_or_default();
    if !matches!(command.as_str(), "up" | "status" | "verify") {
        eprintln!("usage: comicpile-migrate up|status|verify");
        return ExitCode::from(2);
    }
    let Some(raw) = std::env::var("MIGRATE_DATABASE_URL")
        .ok()
        .or_else(|| std::env::var("DATABASE_URL").ok())
    else {
        eprintln!("set MIGRATE_DATABASE_URL or DATABASE_URL");
        return ExitCode::from(2);
    };
    let url = raw
        .replacen("postgresql+asyncpg://", "postgresql://", 1)
        .replacen("postgresql+psycopg://", "postgresql://", 1);
    if command != "up" {
        let result = async {
            let client = comicpile_migrate::connect(&url).await?;
            comicpile_migrate::status(&client).await
        }
        .await;
        return match result {
            Ok(state) => {
                println!("database state: {state}");
                if command == "verify" && !state.is_up_to_date() {
                    eprintln!("verify failed: migrations are pending");
                    ExitCode::FAILURE
                } else {
                    ExitCode::SUCCESS
                }
            }
            Err(error) => {
                eprintln!("{command} failed: {error}");
                ExitCode::FAILURE
            }
        };
    }
    let result = async {
        let mut client = comicpile_migrate::connect(&url).await?;
        comicpile_migrate::run(&mut client).await
    }
    .await;
    match result {
        Ok(report) => {
            println!(
                "migrations applied: {:?}; adopted as already applied: {:?}",
                report.applied, report.adopted
            );
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("migration failed: {error}");
            ExitCode::FAILURE
        }
    }
}
