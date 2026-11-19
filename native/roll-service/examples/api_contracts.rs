//! Write every Rust-generated OpenAPI contract into one directory.
//!
//! Usage: `cargo run -p comicpile-roll-service --example api_contracts -- <dir>`.
//! The repository entry point is `node scripts/generate_api_artifacts.mjs`,
//! which writes into the gitignored `native/contracts/` artifact paths.
//! Each document is validated before anything is written.
#![allow(clippy::unwrap_used, clippy::expect_used)]
use comicpile_roll_service::contract_artifacts::{
    render_contract, validate_contract, CONTRACT_ARTIFACTS,
};

fn main() {
    let dir = std::env::args()
        .nth(1)
        .expect("usage: api_contracts <output directory>");
    let dir = std::path::PathBuf::from(dir);
    std::fs::create_dir_all(&dir).expect("create output directory");
    let mut rendered = Vec::with_capacity(CONTRACT_ARTIFACTS.len());
    for artifact in CONTRACT_ARTIFACTS {
        let text = render_contract(artifact).unwrap_or_else(|error| panic!("{error}"));
        let document: serde_json::Value =
            serde_json::from_str(&text).expect("generated JSON parses");
        validate_contract(artifact.file_name, &document).unwrap_or_else(|error| panic!("{error}"));
        rendered.push((artifact.file_name, text));
    }
    for (file_name, text) in rendered {
        std::fs::write(dir.join(file_name), text).expect("write contract");
        println!("wrote {}", dir.join(file_name).display());
    }
}
