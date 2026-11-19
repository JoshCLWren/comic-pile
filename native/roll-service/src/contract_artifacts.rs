//! Single registry of every Rust-generated OpenAPI contract artifact.
//!
//! These documents are build outputs, not checked-in sources (owner directive
//! 2026-11-19: feature PRs must not edit generated files). `cargo run --example
//! api_contracts -- <dir>` writes each one as `<dir>/<file name>`; the
//! repository wrapper `node scripts/generate_api_artifacts.mjs` writes them into
//! the gitignored `native/contracts/` paths that the frontend generators read.
//!
//! Strictness that used to come from byte-comparing a checked-in copy is kept
//! by [`validate_contract`], which every generated document must pass in the
//! unit tests below and again in the example before anything is written.

use std::collections::{BTreeMap, BTreeSet};

use serde_json::Value;
use utoipa::OpenApi;

/// One generated contract: its artifact file name and the Rust declaration it
/// is derived from.
pub struct ContractArtifact {
    pub file_name: &'static str,
    pub build: fn() -> utoipa::openapi::OpenApi,
}

/// Every Rust-generated contract under `native/contracts/`, sorted by file name.
///
/// The frozen inputs `python-legacy.openapi.json` and
/// `roll-bootstrap-v1.openapi.json` are not generated and stay tracked.
pub const CONTRACT_ARTIFACTS: &[ContractArtifact] = &[
    ContractArtifact {
        file_name: "bug-reports-v1.openapi.json",
        build: crate::bug_reports::BugReportsApi::openapi,
    },
    ContractArtifact {
        file_name: "issue-read-state-v1.openapi.json",
        build: crate::issue_read_state::issue_read_state_openapi,
    },
    ContractArtifact {
        file_name: "issue-v2.openapi.json",
        build: crate::issue_service::IssueApi::openapi,
    },
    ContractArtifact {
        file_name: "preferences-v1.openapi.json",
        build: crate::preferences::PreferencesApi::openapi,
    },
    ContractArtifact {
        file_name: "reading-order-groups-v1.openapi.json",
        build: crate::dependency_groups::dependency_groups_openapi,
    },
    ContractArtifact {
        file_name: "roll-v1.openapi.json",
        build: crate::roll_v1_openapi::roll_v1_openapi,
    },
    ContractArtifact {
        file_name: "same-path-runtime.openapi.json",
        build: crate::same_path_openapi::same_path_openapi,
    },
    ContractArtifact {
        file_name: "thread-issues-v1.openapi.json",
        build: crate::thread_issues::thread_issues_openapi,
    },
    ContractArtifact {
        file_name: "thread-ordering-v1.openapi.json",
        build: crate::thread_ordering::thread_ordering_openapi,
    },
    ContractArtifact {
        file_name: "threads-v1.openapi.json",
        build: crate::threads_v1_openapi::threads_v1_openapi,
    },
    ContractArtifact {
        file_name: "threads-v2.openapi.json",
        build: crate::threads::ThreadsApi::openapi,
    },
    ContractArtifact {
        file_name: "v2-runtime.openapi.json",
        build: crate::openapi::canonical_openapi,
    },
];

const HTTP_METHODS: &[&str] = &[
    "get", "put", "post", "patch", "delete", "head", "options", "trace",
];

/// Render a contract exactly as the artifact file is written (pretty JSON plus
/// a trailing newline, matching the historical `println!` examples).
pub fn render_contract(artifact: &ContractArtifact) -> Result<String, String> {
    (artifact.build)()
        .to_pretty_json()
        .map(|json| json + "\n")
        .map_err(|error| format!("{}: not serializable: {error}", artifact.file_name))
}

/// Validate one generated OpenAPI document.
///
/// Requirements: OpenAPI 3.1 with a titled, versioned `info`; at least one
/// path; every path starts with `/api/`; every operation declares a non-empty
/// `operationId` that is unique within the document and at least one response;
/// and every `#/components/schemas/<name>` reference resolves.
pub fn validate_contract(file_name: &str, document: &Value) -> Result<(), String> {
    let fail = |message: String| Err(format!("{file_name}: {message}"));
    let version = document["openapi"].as_str().unwrap_or_default();
    if !version.starts_with("3.1") {
        return fail(format!("openapi version must be 3.1.x, got {version:?}"));
    }
    if document["info"]["title"]
        .as_str()
        .unwrap_or_default()
        .is_empty()
        || document["info"]["version"]
            .as_str()
            .unwrap_or_default()
            .is_empty()
    {
        return fail("info.title and info.version are required".to_owned());
    }
    let Some(paths) = document["paths"].as_object() else {
        return fail("paths must be an object".to_owned());
    };
    if paths.is_empty() {
        return fail("paths must not be empty".to_owned());
    }
    let mut operation_ids: BTreeMap<&str, String> = BTreeMap::new();
    for (path, item) in paths {
        if !path.starts_with("/api/") {
            return fail(format!("path {path} must live under /api/"));
        }
        let Some(item) = item.as_object() else {
            return fail(format!("path item {path} must be an object"));
        };
        for (method, operation) in item {
            if !HTTP_METHODS.contains(&method.as_str()) {
                continue;
            }
            let label = format!("{} {path}", method.to_uppercase());
            let operation_id = operation["operationId"].as_str().unwrap_or_default();
            if operation_id.is_empty() {
                return fail(format!("{label} has no operationId"));
            }
            if let Some(previous) = operation_ids.insert(operation_id, label.clone()) {
                return fail(format!(
                    "operationId {operation_id} is declared by both {previous} and {label}"
                ));
            }
            if operation["responses"]
                .as_object()
                .is_none_or(serde_json::Map::is_empty)
            {
                return fail(format!("{label} declares no responses"));
            }
        }
    }
    if operation_ids.is_empty() {
        return fail("document declares no operations".to_owned());
    }
    let schemas: BTreeSet<&str> = document["components"]["schemas"]
        .as_object()
        .map(|schemas| schemas.keys().map(String::as_str).collect())
        .unwrap_or_default();
    let mut unresolved = BTreeSet::new();
    collect_unresolved_refs(document, &schemas, &mut unresolved);
    if !unresolved.is_empty() {
        return fail(format!("unresolved schema references: {unresolved:?}"));
    }
    Ok(())
}

fn collect_unresolved_refs(value: &Value, schemas: &BTreeSet<&str>, out: &mut BTreeSet<String>) {
    match value {
        Value::Object(map) => {
            for (key, child) in map {
                if key == "$ref" {
                    if let Some(reference) = child.as_str() {
                        let resolved = reference
                            .strip_prefix("#/components/schemas/")
                            .is_some_and(|name| schemas.contains(name));
                        if !resolved {
                            out.insert(reference.to_owned());
                        }
                    }
                } else {
                    collect_unresolved_refs(child, schemas, out);
                }
            }
        }
        Value::Array(items) => {
            for item in items {
                collect_unresolved_refs(item, schemas, out);
            }
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_generated_contract_is_valid_and_deterministic() {
        for artifact in CONTRACT_ARTIFACTS {
            let first = render_contract(artifact).expect("renderable contract");
            let second = render_contract(artifact).expect("renderable contract");
            assert_eq!(
                first, second,
                "{} must render byte-identically on every run",
                artifact.file_name
            );
            let document: Value = serde_json::from_str(&first).expect("generated JSON parses");
            validate_contract(artifact.file_name, &document).expect("valid generated contract");
        }
    }

    #[test]
    fn artifact_file_names_are_unique_sorted_and_generated_only() {
        let names: Vec<&str> = CONTRACT_ARTIFACTS.iter().map(|a| a.file_name).collect();
        let mut sorted = names.clone();
        sorted.sort_unstable();
        sorted.dedup();
        assert_eq!(names, sorted, "file names must be unique and sorted");
        for name in names {
            assert!(name.ends_with(".openapi.json"), "{name}");
            assert!(
                name != "python-legacy.openapi.json" && name != "roll-bootstrap-v1.openapi.json",
                "{name} is a frozen tracked input, not a generated artifact"
            );
        }
    }

    type Mutation = fn(&mut Value);

    fn minimal() -> Value {
        serde_json::json!({
            "openapi": "3.1.0",
            "info": {"title": "t", "version": "1"},
            "paths": {
                "/api/v2/a": {"get": {"operationId": "a", "responses": {"200": {
                    "description": "ok",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/A"}}}
                }}}}
            },
            "components": {"schemas": {"A": {"type": "object"}}}
        })
    }

    #[test]
    fn validator_accepts_a_minimal_contract() {
        assert_eq!(validate_contract("m", &minimal()), Ok(()));
    }

    #[test]
    fn validator_rejects_each_broken_invariant() {
        let cases: Vec<(&str, Mutation)> = vec![
            ("openapi version", |d| d["openapi"] = "3.0.3".into()),
            ("info.title", |d| d["info"]["title"] = "".into()),
            ("paths must not be empty", |d| {
                d["paths"] = serde_json::json!({})
            }),
            ("must live under /api/", |d| {
                let item = d["paths"]["/api/v2/a"].take();
                d["paths"] = serde_json::json!({"/other": item});
            }),
            ("has no operationId", |d| {
                d["paths"]["/api/v2/a"]["get"]["operationId"] = Value::Null
            }),
            ("declared by both", |d| {
                let op = d["paths"]["/api/v2/a"]["get"].clone();
                d["paths"]["/api/v2/a"]["post"] = op;
            }),
            ("declares no responses", |d| {
                d["paths"]["/api/v2/a"]["get"]["responses"] = serde_json::json!({})
            }),
            ("unresolved schema references", |d| {
                d["components"]["schemas"] = serde_json::json!({})
            }),
        ];
        for (expected, mutate) in cases {
            let mut document = minimal();
            mutate(&mut document);
            let error = validate_contract("m", &document).expect_err(expected);
            assert!(error.contains(expected), "{expected}: {error}");
        }
    }
}
