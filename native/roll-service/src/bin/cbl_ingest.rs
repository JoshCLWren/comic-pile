//! Operator-facing offline CBL mirror inventory/dry-run/apply command.
//!
//! Usage: cargo run -p comicpile-roll-service --bin cbl_ingest -- \
//!   /path/to/CBL-ReadingLists --revision-sha <sha> [--inventory-only|--dry-run]
//!
//! The mirror is a pinned local checkout; this binary never fetches GitHub.
//! Database credentials come from `CBL_INGEST_DATABASE_URL`, then
//! `RUST_ROLL_DATABASE_URL`, then the existing deployment `DATABASE_URL`.

use chrono::Utc;
use comicpile_roll_service::cbl_ingest::{
    build_inventory, connect, discover_cbl_files, parse_cbl_file, parse_options, sync_cbl_lists,
    CBLParseFailure,
};
use std::process::ExitCode;

fn database_url() -> Option<String> {
    [
        "CBL_INGEST_DATABASE_URL",
        "RUST_ROLL_DATABASE_URL",
        "DATABASE_URL",
    ]
    .iter()
    .find_map(|name| {
        std::env::var(name)
            .ok()
            .filter(|value| !value.trim().is_empty())
    })
}

fn print_payload(payload: &serde_json::Value) {
    println!(
        "{}",
        serde_json::to_string(payload).unwrap_or_else(|_| "{}".to_string())
    );
}

async fn run() -> Result<(bool, serde_json::Value), String> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let options = parse_options(&arguments).map_err(|error| error.to_string())?;

    let files = discover_cbl_files(&options.mirror_path).map_err(|error| error.to_string())?;
    let mut parsed_lists = Vec::with_capacity(files.len());
    let mut failures: Vec<CBLParseFailure> = Vec::new();
    for path in &files {
        match parse_cbl_file(path, &options.mirror_path) {
            Ok(list) => parsed_lists.push(list),
            Err(error) => failures.push(CBLParseFailure {
                source_path: path
                    .strip_prefix(&options.mirror_path)
                    .unwrap_or(path)
                    .to_string_lossy()
                    .replace('\\', "/"),
                message: error.to_string(),
            }),
        }
    }
    let inventory = build_inventory(&parsed_lists, &failures).map_err(|error| error.to_string())?;
    let inventory_value = serde_json::to_value(&inventory)
        .map_err(|error| format!("inventory serialization failed: {error}"))?;
    let parse_failures = serde_json::to_value(&failures)
        .map_err(|error| format!("failure serialization failed: {error}"))?;
    let revision = options.revision_sha.clone();
    let repository = options.repository.clone();
    let aliases = options.repository_aliases.clone();
    let mode = if options.inventory_only {
        "inventory"
    } else if options.dry_run {
        "dry_run"
    } else {
        "sync"
    };

    if options.inventory_only {
        return Ok((
            failures.is_empty(),
            serde_json::json!({
                "mode": mode,
                "repository": repository,
                "revision_sha": revision,
                "inventory": inventory_value,
                "parsed_lists": parsed_lists.len(),
                "parse_failures": parse_failures,
            }),
        ));
    }

    let url = database_url().ok_or_else(|| {
        "set CBL_INGEST_DATABASE_URL (or RUST_ROLL_DATABASE_URL / DATABASE_URL)".to_string()
    })?;
    let mut client = connect(&url).await.map_err(|error| error.to_string())?;
    let synced_at = Utc::now();
    let protected: std::collections::BTreeSet<String> = failures
        .iter()
        .map(|failure| failure.source_path.clone())
        .collect();
    let summary = if options.dry_run {
        sync_cbl_lists(
            &client,
            &repository,
            &revision,
            &parsed_lists,
            &protected,
            &aliases,
            true,
            synced_at,
        )
        .await
        .map_err(|error| error.to_string())?
    } else {
        let transaction = client
            .transaction()
            .await
            .map_err(|error| format!("transaction start failed: {error}"))?;
        let summary = sync_cbl_lists(
            &transaction,
            &repository,
            &revision,
            &parsed_lists,
            &protected,
            &aliases,
            false,
            synced_at,
        )
        .await
        .map_err(|error| error.to_string())?;
        transaction
            .commit()
            .await
            .map_err(|error| format!("transaction commit failed: {error}"))?;
        summary
    };
    let summary_value = serde_json::to_value(&summary)
        .map_err(|error| format!("summary serialization failed: {error}"))?;
    let mut payload = serde_json::json!({
        "mode": mode,
        "repository": repository,
        "repository_aliases": aliases,
        "revision_sha": revision,
        "inventory": inventory_value,
        "parsed_lists": parsed_lists.len(),
        "parse_failures": parse_failures,
    });
    if let (Some(object), Some(summary_object)) =
        (payload.as_object_mut(), summary_value.as_object())
    {
        for (key, value) in summary_object {
            object.insert(key.clone(), value.clone());
        }
    }
    Ok((true, payload))
}

#[tokio::main]
async fn main() -> ExitCode {
    match run().await {
        Ok((success, payload)) => {
            print_payload(&payload);
            if success {
                ExitCode::SUCCESS
            } else {
                ExitCode::FAILURE
            }
        }
        Err(message) => {
            eprintln!("cbl_ingest failed: {message}");
            ExitCode::FAILURE
        }
    }
}
