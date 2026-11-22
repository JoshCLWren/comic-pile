//! `comicpile-migrate`: apply or inspect pending Rust migrations.
//!
//! The URL comes from `MIGRATE_DATABASE_URL`, falling back to `DATABASE_URL`;
//! a SQLAlchemy `+asyncpg`/`+psycopg` driver suffix is accepted and stripped.
use std::process::ExitCode;

#[tokio::main]
async fn main() -> ExitCode {
    let command = std::env::args().nth(1).unwrap_or_default();
    match command.as_str() {
        "up" => run_up().await,
        "plan" => run_plan().await,
        _ => {
            eprintln!("usage: comicpile-migrate <up|plan>");
            ExitCode::from(2)
        }
    }
}

fn database_url() -> Option<String> {
    let raw = std::env::var("MIGRATE_DATABASE_URL")
        .ok()
        .or_else(|| std::env::var("DATABASE_URL").ok())?;
    Some(
        raw.replacen("postgresql+asyncpg://", "postgresql://", 1)
            .replacen("postgresql+psycopg://", "postgresql://", 1),
    )
}

async fn run_up() -> ExitCode {
    let Some(url) = database_url() else {
        eprintln!("set MIGRATE_DATABASE_URL or DATABASE_URL");
        return ExitCode::from(2);
    };
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

async fn run_plan() -> ExitCode {
    let Some(url) = database_url() else {
        eprintln!("set MIGRATE_DATABASE_URL or DATABASE_URL");
        return ExitCode::from(2);
    };
    let result = async {
        let mut client = comicpile_migrate::connect(&url).await?;
        comicpile_migrate::needs_work(&mut client).await
    }
    .await;
    match result {
        Ok(false) => {
            println!("migrations pending: false");
            ExitCode::SUCCESS
        }
        Ok(true) => {
            println!("migrations pending: true");
            ExitCode::from(10)
        }
        Err(error) => {
            eprintln!("migration check failed: {error}");
            ExitCode::FAILURE
        }
    }
}
