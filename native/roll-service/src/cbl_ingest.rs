//! Offline, idempotent ingestion of a pinned `CBL-ReadingLists` mirror.
//!
//! The application never fetches GitHub during a request. An operator checks out
//! an exact mirror revision, runs the inventory and dry-run reports from this
//! module, and only then applies the same pinned local tree through the trusted
//! operational workflow that already owns the database credentials (#4171).
//!
//! Writes are set-based and bounded: lists, identities and entries are upserted
//! with `unnest` batches inside one transaction. Files missing from a newer
//! revision are marked inactive rather than deleted, so reader references and
//! adoption provenance survive. A file that is present but fails to parse is
//! protected from deactivation, preserving its last known-good rows.

use chrono::{DateTime, Utc};
use native_tls::TlsConnector;
use postgres_native_tls::MakeTlsConnector;
use quick_xml::{escape::unescape, events::Event, Reader, XmlVersion};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet, HashMap},
    fmt, fs,
    path::{Path, PathBuf},
    process::Command,
    sync::atomic::{AtomicUsize, Ordering},
};
use tokio_postgres::{Client, Config as PostgresConfig, GenericClient};

const DEFAULT_REPOSITORY: &str = "JoshCLWren/CBL-ReadingLists";
const MAX_MIRROR_FILES: usize = 50_000;
const MAX_CBL_FILE_BYTES: usize = 64 * 1024 * 1024;
const MAX_BOOKS_PER_LIST: usize = 20_000;
const MAX_SOURCE_PATH_LENGTH: usize = 1000;
const MAX_LIST_NAME_LENGTH: usize = 500;
const MAX_SERIES_NAME_LENGTH: usize = 500;
const MAX_ISSUE_NUMBER_LENGTH: usize = 100;
const MAX_EXTERNAL_ID_LENGTH: usize = 100;
const BATCH_SIZE: usize = 500;
const CBL_INGEST_LOCK_ID: i64 = 0x4342_4c5f_494e_4745;

/// A path-specific or argument-level ingestion failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IngestError(String);

impl IngestError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl fmt::Display for IngestError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for IngestError {}

/// One ordered comic reference declared by a CBL list.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CBLBook {
    pub position: i32,
    pub series: String,
    pub issue_number: String,
    pub volume_year: Option<i32>,
    pub publication_year: Option<i32>,
    pub comicvine_series_id: Option<String>,
    pub comicvine_issue_id: Option<String>,
}

/// One parsed `.cbl` file plus the provenance needed for idempotent sync.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CBLList {
    pub source_path: String,
    pub content_hash: String,
    pub name: String,
    pub declared_issue_count: Option<i32>,
    pub books: Vec<CBLBook>,
}

/// A file that was discovered but could not be parsed.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CBLParseFailure {
    pub source_path: String,
    pub message: String,
}

/// One deterministic inventory row for a discovered file.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CBLInventoryFile {
    pub source_path: String,
    pub content_hash: String,
    pub publisher: String,
    pub entry_count: usize,
    pub comicvine_series_id_count: usize,
    pub comicvine_issue_id_count: usize,
    pub comicvine_pair_count: usize,
}

/// File and parse counts for one top-level mirror directory.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CBLInventoryPublisher {
    pub name: String,
    pub files: usize,
    pub parsed: usize,
    pub failed: usize,
}

/// Database-free, deterministic inventory of one complete mirror revision.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CBLInventory {
    pub total_files: usize,
    pub parsed_files: usize,
    pub failed_files: usize,
    pub total_entries: usize,
    pub entries_with_comicvine_series_id: usize,
    pub entries_with_comicvine_issue_id: usize,
    pub entries_with_comicvine_pair: usize,
    pub distinct_comicvine_series_ids: usize,
    pub distinct_comicvine_issue_ids: usize,
    pub duplicate_content_hash_groups: usize,
    pub duplicate_source_paths: usize,
    pub declared_count_mismatches: usize,
    pub files: Vec<CBLInventoryFile>,
    pub publishers: Vec<CBLInventoryPublisher>,
}

/// Machine-readable outcome of one reconcile (or dry-run reconcile).
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SyncSummary {
    pub source_created: bool,
    pub inserted_lists: usize,
    pub updated_lists: usize,
    pub deactivated_lists: usize,
    pub protected_lists: usize,
    pub unchanged_lists: usize,
    pub entries_written: usize,
    pub identities_upserted: usize,
    pub dry_run: bool,
    pub changed: bool,
    pub repository_reconciled: bool,
}

/// Command-line contract shared by the binary and its integration tests.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IngestOptions {
    pub mirror_path: PathBuf,
    pub revision_sha: String,
    pub repository: String,
    pub repository_aliases: Vec<String>,
    pub dry_run: bool,
    pub inventory_only: bool,
}

/// Parse CLI arguments without pulling a framework into the deployment binary.
pub fn parse_options(arguments: &[String]) -> Result<IngestOptions, IngestError> {
    let mut mirror_path = None;
    let mut revision_sha = None;
    let mut repository = DEFAULT_REPOSITORY.to_string();
    let mut repository_aliases = Vec::new();
    let mut dry_run = false;
    let mut inventory_only = false;
    let mut index = 0;
    while index < arguments.len() {
        let argument = &arguments[index];
        match argument.as_str() {
            "--dry-run" => dry_run = true,
            "--inventory-only" => inventory_only = true,
            "--revision-sha" | "--repository" | "--reconcile-repository" => {
                index += 1;
                let value = arguments
                    .get(index)
                    .ok_or_else(|| IngestError::new(format!("{argument} requires a value")))?;
                match argument.as_str() {
                    "--revision-sha" => revision_sha = Some(value.clone()),
                    "--repository" => repository = value.clone(),
                    _ => repository_aliases.push(value.clone()),
                }
            }
            other if other.starts_with('-') => {
                return Err(IngestError::new(format!("unknown option: {other}")));
            }
            other => {
                if mirror_path.is_some() {
                    return Err(IngestError::new("only one mirror path is accepted"));
                }
                mirror_path = Some(PathBuf::from(other));
            }
        }
        index += 1;
    }
    let mirror_path = mirror_path.ok_or_else(|| IngestError::new("mirror_path is required"))?;
    let revision_sha =
        revision_sha.ok_or_else(|| IngestError::new("--revision-sha is required"))?;
    validate_repository(&repository)?;
    validate_revision(&revision_sha)?;
    for alias in &repository_aliases {
        validate_repository(alias)?;
        if alias == &repository {
            return Err(IngestError::new(
                "repository must not also be listed as an alias",
            ));
        }
    }
    Ok(IngestOptions {
        mirror_path,
        revision_sha,
        repository,
        repository_aliases,
        dry_run,
        inventory_only,
    })
}

fn validate_repository(value: &str) -> Result<(), IngestError> {
    if value.trim().is_empty() || value.chars().count() > 255 {
        Err(IngestError::new(
            "repository must be non-empty and at most 255 characters",
        ))
    } else {
        Ok(())
    }
}

fn validate_revision(value: &str) -> Result<(), IngestError> {
    if !matches!(value.len(), 40 | 64) || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        Err(IngestError::new(
            "--revision-sha must be a full 40- or 64-character hexadecimal Git SHA",
        ))
    } else {
        Ok(())
    }
}

/// Verify that the supplied directory is the clean, exact Git checkout it claims to be.
///
/// The ingester never fetches or mutates the mirror. This preflight prevents a dirty,
/// untracked-contaminated, wrong-revision, or wrong-repository tree from being recorded as
/// trusted provenance and from deactivating paths that are absent only because of local state.
pub fn verify_pinned_checkout(
    mirror_path: &Path,
    revision_sha: &str,
    repository: &str,
) -> Result<(), IngestError> {
    validate_revision(revision_sha)?;
    validate_repository(repository)?;
    let mirror = fs::canonicalize(mirror_path)
        .map_err(|error| IngestError::new(format!("cannot resolve mirror path: {error}")))?;
    let top_level = git_output(&mirror, &["rev-parse", "--show-toplevel"])?;
    let top_level = fs::canonicalize(Path::new(top_level.trim()))
        .map_err(|error| IngestError::new(format!("cannot resolve Git worktree: {error}")))?;
    if top_level != mirror {
        return Err(IngestError::new(
            "mirror_path must be the root of the pinned Git worktree",
        ));
    }
    let head = git_output(&mirror, &["rev-parse", "HEAD"])?;
    if !head.trim().eq_ignore_ascii_case(revision_sha) {
        return Err(IngestError::new(
            "mirror worktree HEAD does not match --revision-sha",
        ));
    }
    let status = git_output(&mirror, &["status", "--porcelain", "--untracked-files=all"])?;
    if !status.trim().is_empty() {
        return Err(IngestError::new(
            "mirror worktree must be clean with no untracked files",
        ));
    }
    let origin = git_output(&mirror, &["remote", "get-url", "origin"])?;
    if normalize_git_remote(origin.trim()).as_deref() != Some(repository.trim()) {
        return Err(IngestError::new(
            "mirror origin must match the canonical GitHub repository",
        ));
    }
    Ok(())
}

fn git_output(mirror_path: &Path, arguments: &[&str]) -> Result<String, IngestError> {
    let output = Command::new("git")
        .arg("-C")
        .arg(mirror_path)
        .args(arguments)
        .output()
        .map_err(|error| IngestError::new(format!("cannot run local Git: {error}")))?;
    if !output.status.success() {
        return Err(IngestError::new(format!(
            "local Git {} failed",
            arguments.first().copied().unwrap_or("command")
        )));
    }
    String::from_utf8(output.stdout)
        .map_err(|_| IngestError::new("local Git returned non-UTF-8 output"))
}

fn normalize_git_remote(remote: &str) -> Option<String> {
    let remote = remote.trim().trim_end_matches('/');
    let remote = remote.strip_suffix(".git").unwrap_or(remote);
    let path = remote
        .strip_prefix("https://github.com/")
        .or_else(|| remote.strip_prefix("http://github.com/"))
        .or_else(|| remote.strip_prefix("ssh://git@github.com/"))
        .or_else(|| remote.strip_prefix("git@github.com:"))?;
    Some(path.to_string())
}

/// Return every `.cbl` file beneath a mirror in deterministic relative-path order.
pub fn discover_cbl_files(mirror_path: &Path) -> Result<Vec<PathBuf>, IngestError> {
    if !mirror_path.is_dir() {
        return Err(IngestError::new(
            "mirror_path must be an existing directory",
        ));
    }
    let mut pending = vec![mirror_path.to_path_buf()];
    let mut discovered = Vec::new();
    while let Some(directory) = pending.pop() {
        let entries = fs::read_dir(&directory)
            .map_err(|error| IngestError::new(format!("cannot read mirror directory: {error}")))?;
        for entry in entries {
            let entry = entry
                .map_err(|error| IngestError::new(format!("cannot read mirror entry: {error}")))?;
            let path = entry.path();
            let file_type = entry
                .file_type()
                .map_err(|error| IngestError::new(format!("cannot stat mirror entry: {error}")))?;
            if file_type.is_dir() {
                pending.push(path);
            } else if file_type.is_file()
                && path
                    .extension()
                    .and_then(|extension| extension.to_str())
                    .is_some_and(|extension| extension.eq_ignore_ascii_case("cbl"))
            {
                discovered.push(path);
            }
        }
    }
    if discovered.len() > MAX_MIRROR_FILES {
        return Err(IngestError::new("mirror exceeds the supported file limit"));
    }
    discovered.sort_by(|left, right| {
        let left = relative_source_path(left, mirror_path);
        let right = relative_source_path(right, mirror_path);
        (left.to_lowercase(), left).cmp(&(right.to_lowercase(), right))
    });
    Ok(discovered)
}

fn relative_source_path(path: &Path, mirror_path: &Path) -> String {
    path.strip_prefix(mirror_path)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

/// Parse one file from disk, isolating read and XML failures for the inventory.
pub fn parse_cbl_file(path: &Path, mirror_path: &Path) -> Result<CBLList, IngestError> {
    let size = fs::metadata(path)
        .map_err(|error| IngestError::new(format!("cannot stat CBL: {error}")))?
        .len();
    if size > MAX_CBL_FILE_BYTES as u64 {
        return Err(IngestError::new("CBL file exceeds the 64 MiB size limit"));
    }
    let raw =
        fs::read(path).map_err(|error| IngestError::new(format!("cannot read CBL: {error}")))?;
    parse_cbl_bytes(&raw, &relative_source_path(path, mirror_path))
}

/// Parse one `.cbl` document without any filesystem, network or database I/O.
pub fn parse_cbl_bytes(raw: &[u8], source_path: &str) -> Result<CBLList, IngestError> {
    if source_path.trim().is_empty() || source_path.chars().count() > MAX_SOURCE_PATH_LENGTH {
        return Err(IngestError::new(
            "CBL source path must be non-empty and at most 1000 characters",
        ));
    }
    if raw.len() > MAX_CBL_FILE_BYTES {
        return Err(IngestError::new("CBL file exceeds the 64 MiB size limit"));
    }
    let mut reader = Reader::from_reader(raw);
    let mut buffer = Vec::new();
    let mut depth = 0usize;
    let mut root_seen = false;
    let mut books_seen = false;
    let mut books_depth = None;
    let mut capture = None;
    let mut captured_text = String::new();
    let mut name = None;
    let mut declared_issue_count = None;
    let mut current_book = None;
    let mut books = Vec::new();

    loop {
        let event = reader
            .read_event_into(&mut buffer)
            .map_err(|error| IngestError::new(format!("malformed CBL XML: {error}")))?;
        match event {
            Event::Start(ref element) => {
                if !root_seen {
                    if element.name().as_ref() != b"ReadingList" {
                        return Err(IngestError::new("CBL root element must be ReadingList"));
                    }
                    root_seen = true;
                } else if depth == 0 {
                    return Err(IngestError::new("CBL document has multiple root elements"));
                }
                let element_depth = depth;
                depth += 1;
                match element.name().as_ref() {
                    "Books" if element_depth == 1 => {
                        books_seen = true;
                        books_depth = Some(depth);
                    }
                    "Name" if current_book.is_none() && element_depth == 1 => {
                        capture = Some(CapturedField::Name);
                        captured_text.clear();
                    }
                    "NumIssues" if current_book.is_none() && element_depth == 1 => {
                        capture = Some(CapturedField::NumIssues);
                        captured_text.clear();
                    }
                    "Book" => {
                        if books_depth != Some(element_depth) {
                            return Err(IngestError::new("Book element must be inside Books"));
                        }
                        ensure_book_capacity(books.len())?;
                        let mut book = parse_book(element)?;
                        book.position = i32::try_from(books.len() + 1)
                            .map_err(|_| IngestError::new("too many ordered book entries"))?;
                        current_book = Some(book);
                    }
                    "Database" => {
                        if let Some(book) = current_book.as_mut() {
                            apply_database(book, element)?;
                        }
                    }
                    _ => {}
                }
            }
            Event::Empty(ref element) => {
                if !root_seen {
                    if element.name().as_ref() != b"ReadingList" {
                        return Err(IngestError::new("CBL root element must be ReadingList"));
                    }
                    root_seen = true;
                } else if depth == 0 {
                    return Err(IngestError::new("CBL document has multiple root elements"));
                }
                let element_depth = depth;
                match element.name().as_ref() {
                    "Books" if element_depth == 1 => books_seen = true,
                    "Book" => {
                        if books_depth != Some(element_depth) {
                            return Err(IngestError::new("Book element must be inside Books"));
                        }
                        ensure_book_capacity(books.len())?;
                        let mut book = parse_book(element)?;
                        book.position = i32::try_from(books.len() + 1)
                            .map_err(|_| IngestError::new("too many ordered book entries"))?;
                        books.push(book);
                    }
                    "Database" => {
                        if let Some(book) = current_book.as_mut() {
                            apply_database(book, element)?;
                        }
                    }
                    _ => {}
                }
            }
            Event::Text(ref text) => {
                if capture.is_some() {
                    let value = unescape(text.as_ref()).map_err(|error| {
                        IngestError::new(format!("invalid XML entity: {error}"))
                    })?;
                    captured_text.push_str(&value);
                }
            }
            Event::CData(ref text) => {
                if capture.is_some() {
                    captured_text.push_str(text.as_ref());
                }
            }
            Event::GeneralRef(reference) => {
                if capture.is_some() {
                    captured_text.push_str(&decode_reference(reference.as_ref()));
                }
            }
            Event::End(ref element) => {
                match element.name().as_ref() {
                    "Name" if capture == Some(CapturedField::Name) => {
                        capture = None;
                        name = Some(captured_text.trim().to_string());
                    }
                    "NumIssues" if capture == Some(CapturedField::NumIssues) => {
                        capture = None;
                        declared_issue_count = if captured_text.trim().is_empty() {
                            None
                        } else {
                            Some(parse_optional_int(&captured_text)?)
                        };
                    }
                    "Book" => {
                        ensure_book_capacity(books.len())?;
                        let book = current_book
                            .take()
                            .ok_or_else(|| IngestError::new("unexpected closing Book tag"))?;
                        books.push(book);
                    }
                    "Books" if books_depth == Some(depth) => books_depth = None,
                    _ => {}
                }
                depth = depth.saturating_sub(1);
            }
            Event::Eof => break,
            _ => {}
        }
        buffer.clear();
    }
    if !root_seen {
        return Err(IngestError::new("CBL document has no root element"));
    }
    if depth != 0 {
        return Err(IngestError::new("CBL document has an unclosed element"));
    }
    if !books_seen {
        return Err(IngestError::new(
            "CBL ReadingList is missing its Books element",
        ));
    }
    let name = name.filter(|value| !value.is_empty()).unwrap_or_else(|| {
        Path::new(source_path).file_stem().map_or_else(
            || source_path.to_string(),
            |stem| stem.to_string_lossy().into_owned(),
        )
    });
    if name.chars().count() > MAX_LIST_NAME_LENGTH {
        return Err(IngestError::new("CBL name exceeds 500 characters"));
    }
    let mut hasher = Sha256::new();
    hasher.update(raw);
    let content_hash = hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    Ok(CBLList {
        source_path: source_path.to_string(),
        content_hash,
        name,
        declared_issue_count,
        books,
    })
}

fn ensure_book_capacity(current: usize) -> Result<(), IngestError> {
    if current >= MAX_BOOKS_PER_LIST {
        Err(IngestError::new(
            "CBL list exceeds the supported entry limit",
        ))
    } else {
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CapturedField {
    Name,
    NumIssues,
}

fn decode_reference(raw: &str) -> String {
    let entity = raw.strip_prefix('&').unwrap_or(raw);
    let entity = entity.strip_suffix(';').unwrap_or(entity);
    match entity {
        "amp" => "&".to_string(),
        "lt" => "<".to_string(),
        "gt" => ">".to_string(),
        "quot" => "\"".to_string(),
        "apos" => "'".to_string(),
        numeric if numeric.starts_with("#x") || numeric.starts_with("#X") => {
            u32::from_str_radix(&numeric[2..], 16)
                .ok()
                .and_then(char::from_u32)
                .map_or_else(|| format!("&{entity};"), |value| value.to_string())
        }
        numeric if numeric.starts_with('#') => numeric[1..]
            .parse::<u32>()
            .ok()
            .and_then(char::from_u32)
            .map_or_else(|| format!("&{entity};"), |value| value.to_string()),
        other => format!("&{other};"),
    }
}

fn attribute(
    element: &quick_xml::events::BytesStart<'_>,
    key: &[u8],
) -> Result<Option<String>, IngestError> {
    for candidate in element.attributes() {
        let attribute = candidate
            .map_err(|error| IngestError::new(format!("invalid CBL attribute: {error}")))?;
        if attribute.key.as_ref().as_bytes() != key {
            continue;
        }
        let value = attribute
            .normalized_value(XmlVersion::Implicit1_0)
            .map_err(|error| IngestError::new(format!("invalid CBL attribute: {error}")))?;
        let value = value.trim();
        return Ok(if value.is_empty() {
            None
        } else {
            Some(value.to_string())
        });
    }
    Ok(None)
}

fn first_attribute(
    element: &quick_xml::events::BytesStart<'_>,
    keys: &[&[u8]],
) -> Result<Option<String>, IngestError> {
    for key in keys {
        let value = attribute(element, key)?;
        if value.is_some() {
            return Ok(value);
        }
    }
    Ok(None)
}

fn parse_optional_int(raw: &str) -> Result<i32, IngestError> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err(IngestError::new("expected an integer value"));
    }
    trimmed
        .parse::<i32>()
        .map_err(|_| IngestError::new(format!("expected an integer value, got {trimmed:?}")))
}

fn parse_optional_year(raw: Option<String>) -> Result<Option<i32>, IngestError> {
    match raw {
        Some(value) if value.trim().eq_ignore_ascii_case("None") => Ok(None),
        Some(value) => parse_optional_int(&value).map(Some),
        None => Ok(None),
    }
}

fn parse_book(element: &quick_xml::events::BytesStart<'_>) -> Result<CBLBook, IngestError> {
    let series = attribute(element, b"Series")?
        .filter(|value| !value.is_empty())
        .ok_or_else(|| IngestError::new("book is missing required Series"))?;
    let issue_number = attribute(element, b"Number")?
        .filter(|value| !value.is_empty())
        .ok_or_else(|| IngestError::new("book is missing required Number"))?;
    if series.chars().count() > MAX_SERIES_NAME_LENGTH {
        return Err(IngestError::new("book Series exceeds 500 characters"));
    }
    if issue_number.chars().count() > MAX_ISSUE_NUMBER_LENGTH {
        return Err(IngestError::new("book Number exceeds 100 characters"));
    }
    let volume_year = parse_optional_year(attribute(element, b"Volume")?)?;
    let publication_year = parse_optional_year(attribute(element, b"Year")?)?;
    let comicvine_series_id = first_attribute(
        element,
        &[b"SeriesID", b"SeriesId", b"VolumeID", b"VolumeId"],
    )?;
    let comicvine_issue_id = first_attribute(element, &[b"IssueID", b"IssueId"])?;
    validate_external_ids(&comicvine_series_id, &comicvine_issue_id)?;
    Ok(CBLBook {
        position: 0,
        series,
        issue_number,
        volume_year,
        publication_year,
        comicvine_series_id,
        comicvine_issue_id,
    })
}

fn apply_database(
    book: &mut CBLBook,
    element: &quick_xml::events::BytesStart<'_>,
) -> Result<(), IngestError> {
    let database_name = attribute(element, b"Name")?;
    if !database_name.as_deref().is_some_and(|value| {
        value.eq_ignore_ascii_case("comicvine") || value.eq_ignore_ascii_case("cv")
    }) {
        return Ok(());
    }
    if book.comicvine_series_id.is_none() {
        book.comicvine_series_id =
            first_attribute(element, &[b"Series", b"SeriesID", b"Volume", b"VolumeID"])?;
    }
    if book.comicvine_issue_id.is_none() {
        book.comicvine_issue_id = first_attribute(element, &[b"Issue", b"IssueID"])?;
    }
    validate_external_ids(&book.comicvine_series_id, &book.comicvine_issue_id)
}

fn validate_external_ids(
    series_id: &Option<String>,
    issue_id: &Option<String>,
) -> Result<(), IngestError> {
    if series_id
        .iter()
        .chain(issue_id)
        .any(|id| id.chars().count() > MAX_EXTERNAL_ID_LENGTH)
    {
        return Err(IngestError::new(
            "Comic Vine external id exceeds 100 characters",
        ));
    }
    Ok(())
}

/// Build a deterministic, database-free inventory from parsed mirror results.
pub fn build_inventory(
    parsed_lists: &[CBLList],
    failures: &[CBLParseFailure],
) -> Result<CBLInventory, IngestError> {
    if parsed_lists
        .iter()
        .any(|item| item.source_path.trim().is_empty())
        || failures
            .iter()
            .any(|item| item.source_path.trim().is_empty())
    {
        return Err(IngestError::new(
            "CBL inventory source paths must be non-empty",
        ));
    }
    let mut files: Vec<CBLInventoryFile> = parsed_lists.iter().map(inventory_file).collect();
    files.sort_by(|left, right| {
        (left.source_path.to_lowercase(), &left.source_path)
            .cmp(&(right.source_path.to_lowercase(), &right.source_path))
    });

    let mut hash_paths: BTreeMap<&str, BTreeSet<&str>> = BTreeMap::new();
    for item in parsed_lists {
        hash_paths
            .entry(&item.content_hash)
            .or_default()
            .insert(&item.source_path);
    }
    let series_ids: BTreeSet<&str> = parsed_lists
        .iter()
        .flat_map(|item| item.books.iter())
        .filter_map(|book| book.comicvine_series_id.as_deref())
        .collect();
    let issue_ids: BTreeSet<&str> = parsed_lists
        .iter()
        .flat_map(|item| item.books.iter())
        .filter_map(|book| book.comicvine_issue_id.as_deref())
        .collect();

    let mut publisher_flags: BTreeMap<String, Vec<bool>> = BTreeMap::new();
    for item in parsed_lists {
        publisher_flags
            .entry(publisher_for_path(&item.source_path))
            .or_default()
            .push(true);
    }
    for failure in failures {
        publisher_flags
            .entry(publisher_for_path(&failure.source_path))
            .or_default()
            .push(false);
    }
    let publishers = publisher_flags
        .into_iter()
        .map(|(name, flags)| CBLInventoryPublisher {
            name,
            files: flags.len(),
            parsed: flags.iter().filter(|parsed| **parsed).count(),
            failed: flags.iter().filter(|parsed| !**parsed).count(),
        })
        .collect();

    let mut all_paths: Vec<&str> = parsed_lists
        .iter()
        .map(|item| item.source_path.as_str())
        .chain(failures.iter().map(|item| item.source_path.as_str()))
        .collect();
    let distinct_paths = all_paths.iter().copied().collect::<BTreeSet<_>>().len();
    all_paths.sort_unstable();

    Ok(CBLInventory {
        total_files: all_paths.len(),
        parsed_files: parsed_lists.len(),
        failed_files: failures.len(),
        total_entries: parsed_lists.iter().map(|item| item.books.len()).sum(),
        entries_with_comicvine_series_id: count_books(parsed_lists, |book| {
            book.comicvine_series_id.is_some()
        }),
        entries_with_comicvine_issue_id: count_books(parsed_lists, |book| {
            book.comicvine_issue_id.is_some()
        }),
        entries_with_comicvine_pair: count_books(parsed_lists, |book| {
            book.comicvine_series_id.is_some() && book.comicvine_issue_id.is_some()
        }),
        distinct_comicvine_series_ids: series_ids.len(),
        distinct_comicvine_issue_ids: issue_ids.len(),
        duplicate_content_hash_groups: hash_paths.values().filter(|paths| paths.len() > 1).count(),
        duplicate_source_paths: all_paths.len() - distinct_paths,
        declared_count_mismatches: parsed_lists
            .iter()
            .filter(|item| {
                item.declared_issue_count
                    .is_some_and(|count| usize::try_from(count).ok() != Some(item.books.len()))
            })
            .count(),
        files,
        publishers,
    })
}

fn count_books(lists: &[CBLList], predicate: impl Fn(&CBLBook) -> bool) -> usize {
    lists
        .iter()
        .flat_map(|item| item.books.iter())
        .filter(|book| predicate(book))
        .count()
}

fn inventory_file(item: &CBLList) -> CBLInventoryFile {
    CBLInventoryFile {
        source_path: item.source_path.clone(),
        content_hash: item.content_hash.clone(),
        publisher: publisher_for_path(&item.source_path),
        entry_count: item.books.len(),
        comicvine_series_id_count: count_books(std::slice::from_ref(item), |book| {
            book.comicvine_series_id.is_some()
        }),
        comicvine_issue_id_count: count_books(std::slice::from_ref(item), |book| {
            book.comicvine_issue_id.is_some()
        }),
        comicvine_pair_count: count_books(std::slice::from_ref(item), |book| {
            book.comicvine_series_id.is_some() && book.comicvine_issue_id.is_some()
        }),
    }
}

fn publisher_for_path(source_path: &str) -> String {
    source_path.split_once('/').map_or_else(
        || "(root)".to_string(),
        |(publisher, _)| publisher.to_string(),
    )
}

/// Connect with the same credential source as the trusted migration runner.
pub async fn connect(database_url: &str) -> Result<Client, IngestError> {
    let raw = database_url.trim();
    let url = [
        "postgresql+asyncpg://",
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
    ]
    .iter()
    .find_map(|prefix| raw.strip_prefix(prefix))
    .map_or_else(|| raw.to_string(), |rest| format!("postgresql://{rest}"));
    let config: PostgresConfig = url
        .parse()
        .map_err(|error| IngestError::new(format!("invalid database URL: {error}")))?;
    let tls = TlsConnector::new()
        .map_err(|error| IngestError::new(format!("TLS initialization failed: {error}")))?;
    let (client, connection) = config
        .connect(MakeTlsConnector::new(tls))
        .await
        .map_err(|_error| IngestError::new("database connection failed"))?;
    tokio::spawn(connection);
    Ok(client)
}

#[derive(Debug)]
struct ExistingList {
    active: bool,
    content_hash: String,
}

/// Reconcile parsed lists into the shared CBL reference tables.
///
/// The caller owns the transaction; a dry run performs reads only. No row is
/// ever hard-deleted, and paths that failed to parse are protected from
/// deactivation so a malformed source cannot erase last known-good data.
// The CLI and DB-backed tests both call this single entry point; bundling the
// inputs in a struct would only duplicate the argument list at both edges.
#[allow(clippy::too_many_arguments)]
pub async fn sync_cbl_lists<C: GenericClient>(
    client: &C,
    repository: &str,
    revision_sha: &str,
    parsed_lists: &[CBLList],
    protected_paths: &BTreeSet<String>,
    repository_aliases: &[String],
    dry_run: bool,
    synced_at: DateTime<Utc>,
) -> Result<SyncSummary, IngestError> {
    validate_repository(repository)?;
    validate_revision(revision_sha)?;
    let repository = repository.trim().to_string();
    let revision_sha = revision_sha.trim().to_string();
    let paths: BTreeSet<&str> = parsed_lists
        .iter()
        .map(|item| item.source_path.as_str())
        .collect();
    if paths.len() != parsed_lists.len() {
        return Err(IngestError::new(
            "CBL source paths must be unique within one sync",
        ));
    }
    if parsed_lists.iter().any(|item| {
        item.content_hash.len() != 64
            || !item
                .content_hash
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit())
    }) {
        return Err(IngestError::new(
            "CBL content hashes must be 64 hex characters",
        ));
    }
    if protected_paths.iter().any(|path| path.trim().is_empty()) {
        return Err(IngestError::new(
            "protected CBL source paths must be non-empty",
        ));
    }
    let mut aliases = Vec::new();
    for alias in repository_aliases {
        validate_repository(alias)?;
        let alias = alias.trim().to_string();
        if alias != repository && !aliases.contains(&alias) {
            aliases.push(alias);
        }
    }

    if !dry_run {
        client
            .execute(
                "SELECT pg_advisory_xact_lock($1::bigint)",
                &[&CBL_INGEST_LOCK_ID],
            )
            .await
            .map_err(|error| IngestError::new(format!("cbl ingest lock failed: {error}")))?;
    }
    let (mut source_id, existing_revision) = lookup_source(client, &repository, dry_run).await?;
    let source_created = source_id.is_none();
    let mut repository_reconciled = false;
    if source_id.is_some() && !aliases.is_empty() {
        reject_active_alias_conflict(client, &aliases).await?;
    }
    if source_id.is_none() && !aliases.is_empty() {
        let alias_rows = source_query(
            client,
            "SELECT id, revision_sha FROM cbl_sources WHERE repository = ANY($1::text[])",
            &[&aliases],
            dry_run,
        )
        .await?;
        if alias_rows.len() > 1 {
            return Err(IngestError::new(
                "multiple repository aliases match existing CBL sources",
            ));
        }
        if let Some(row) = alias_rows.first() {
            source_id = Some(row.get::<_, i32>(0));
            repository_reconciled = true;
        }
    }

    let existing_lists = match source_id {
        Some(id) => {
            let rows = source_query(
                client,
                "SELECT id, source_path, active, content_hash FROM cbl_source_lists WHERE source_id = $1",
                &[&id],
                dry_run,
            )
            .await?;
            rows.into_iter()
                .map(|row| {
                    (
                        row.get::<_, String>(1),
                        ExistingList {
                            active: row.get::<_, bool>(2),
                            content_hash: row.get::<_, String>(3),
                        },
                    )
                })
                .collect::<HashMap<_, _>>()
        }
        None => HashMap::new(),
    };

    let mut pending = Vec::new();
    let mut inserted = 0;
    let mut updated = 0;
    let mut unchanged = 0;
    for parsed in parsed_lists {
        match existing_lists.get(parsed.source_path.as_str()) {
            Some(existing) if existing.active && existing.content_hash == parsed.content_hash => {
                unchanged += 1;
            }
            Some(_) => {
                updated += 1;
                pending.push(parsed);
            }
            None => {
                inserted += 1;
                pending.push(parsed);
            }
        }
    }
    let mut keep_paths: BTreeSet<&str> = paths.clone();
    keep_paths.extend(protected_paths.iter().map(String::as_str));
    let deactivated = existing_lists
        .iter()
        .filter(|(path, existing)| existing.active && !keep_paths.contains(path.as_str()))
        .count();
    let protected_lists = existing_lists
        .iter()
        .filter(|(path, existing)| existing.active && protected_paths.contains(path.as_str()))
        .count();
    let source_changed = source_created
        || existing_revision.as_deref() != Some(revision_sha.as_str())
        || repository_reconciled;
    let changed = inserted > 0 || updated > 0 || deactivated > 0 || source_changed;

    if dry_run || !changed {
        let identities_upserted = if dry_run {
            count_missing_identities(client, &pending).await?
        } else {
            0
        };
        return Ok(SyncSummary {
            source_created,
            inserted_lists: if dry_run { inserted } else { 0 },
            updated_lists: if dry_run { updated } else { 0 },
            deactivated_lists: if dry_run { deactivated } else { 0 },
            protected_lists,
            unchanged_lists: unchanged,
            entries_written: if dry_run {
                pending.iter().map(|item| item.books.len()).sum()
            } else {
                0
            },
            identities_upserted,
            dry_run,
            changed,
            repository_reconciled: dry_run && repository_reconciled,
        });
    }

    let source_id = upsert_source(client, source_id, &repository, &revision_sha, synced_at).await?;
    let list_ids = upsert_lists(client, source_id, &pending, &revision_sha, synced_at).await?;
    let changed_ids: Vec<i32> = list_ids.values().copied().collect();
    delete_entries(client, &changed_ids).await?;
    let identities_upserted = upsert_identities(client, &pending, synced_at).await?;
    let identity_ids = resolve_identity_ids(client, &pending).await?;
    let entries_written =
        insert_entries(client, &pending, &list_ids, &identity_ids, synced_at).await?;
    let keep_paths: Vec<&str> = keep_paths.into_iter().collect();
    let deactivated_applied = client
        .execute(
            "UPDATE cbl_source_lists
             SET active = FALSE, revision_sha = $1, updated_at = $2
             WHERE source_id = $3 AND active IS TRUE AND NOT (source_path = ANY($4::text[]))",
            &[&revision_sha, &synced_at, &source_id, &keep_paths],
        )
        .await
        .map_err(|error| IngestError::new(format!("cbl list deactivation failed: {error}")))?;

    Ok(SyncSummary {
        source_created,
        inserted_lists: inserted,
        updated_lists: updated,
        deactivated_lists: usize::try_from(deactivated_applied).unwrap_or(deactivated),
        protected_lists,
        unchanged_lists: unchanged,
        entries_written,
        identities_upserted,
        dry_run: false,
        changed: true,
        repository_reconciled,
    })
}

async fn source_query<C: GenericClient>(
    client: &C,
    sql: &str,
    parameters: &[&(dyn tokio_postgres::types::ToSql + Sync)],
    dry_run: bool,
) -> Result<Vec<tokio_postgres::Row>, IngestError> {
    let sql = if dry_run {
        sql.to_string()
    } else {
        format!("{sql} FOR UPDATE")
    };
    client
        .query(&sql, parameters)
        .await
        .map_err(|error| IngestError::new(format!("cbl source lookup failed: {error}")))
}

async fn lookup_source<C: GenericClient>(
    client: &C,
    repository: &str,
    dry_run: bool,
) -> Result<(Option<i32>, Option<String>), IngestError> {
    let rows = source_query(
        client,
        "SELECT id, revision_sha FROM cbl_sources WHERE repository = $1",
        &[&repository],
        dry_run,
    )
    .await?;
    if rows.len() > 1 {
        return Err(IngestError::new(
            "multiple CBL sources share one repository",
        ));
    }
    Ok(rows.first().map_or((None, None), |row| {
        (Some(row.get::<_, i32>(0)), Some(row.get::<_, String>(1)))
    }))
}

async fn reject_active_alias_conflict<C: GenericClient>(
    client: &C,
    aliases: &[String],
) -> Result<(), IngestError> {
    let row = client
        .query_one(
            "SELECT COUNT(*)::bigint
             FROM cbl_sources s
             JOIN cbl_source_lists l ON l.source_id = s.id
             WHERE s.repository = ANY($1::text[]) AND l.active IS TRUE",
            &[&aliases],
        )
        .await
        .map_err(|error| IngestError::new(format!("cbl alias lookup failed: {error}")))?;
    if row.get::<_, i64>(0) > 0 {
        return Err(IngestError::new(
            "canonical repository and an active repository alias both exist; reconcile the ambiguous source identities before ingestion",
        ));
    }
    Ok(())
}

async fn upsert_source<C: GenericClient>(
    client: &C,
    source_id: Option<i32>,
    repository: &str,
    revision: &str,
    synced_at: DateTime<Utc>,
) -> Result<i32, IngestError> {
    match source_id {
        Some(id) => {
            client
                .execute(
                    "UPDATE cbl_sources
                     SET repository = $1, revision_sha = $2, synced_at = $3, updated_at = $3
                     WHERE id = $4",
                    &[&repository, &revision, &synced_at, &id],
                )
                .await
                .map_err(|error| IngestError::new(format!("cbl source update failed: {error}")))?;
            Ok(id)
        }
        None => {
            let row = client
                .query_one(
                    "INSERT INTO cbl_sources
                        (repository, revision_sha, synced_at, created_at, updated_at)
                     VALUES ($1, $2, $3, $3, $3)
                     ON CONFLICT (repository) DO UPDATE
                        SET revision_sha = EXCLUDED.revision_sha,
                            synced_at = EXCLUDED.synced_at,
                            updated_at = EXCLUDED.updated_at
                     RETURNING id",
                    &[&repository, &revision, &synced_at],
                )
                .await
                .map_err(|error| IngestError::new(format!("cbl source insert failed: {error}")))?;
            Ok(row.get::<_, i32>(0))
        }
    }
}

async fn upsert_lists<C: GenericClient>(
    client: &C,
    source_id: i32,
    pending: &[&CBLList],
    revision: &str,
    synced_at: DateTime<Utc>,
) -> Result<HashMap<String, i32>, IngestError> {
    let mut ids = HashMap::new();
    for chunk in pending.chunks(BATCH_SIZE) {
        let paths: Vec<&str> = chunk.iter().map(|item| item.source_path.as_str()).collect();
        let names: Vec<&str> = chunk.iter().map(|item| item.name.as_str()).collect();
        let declared: Vec<Option<i32>> =
            chunk.iter().map(|item| item.declared_issue_count).collect();
        let hashes: Vec<&str> = chunk
            .iter()
            .map(|item| item.content_hash.as_str())
            .collect();
        let rows = client
            .query(
                "INSERT INTO cbl_source_lists
                    (source_id, source_path, name, declared_issue_count, content_hash,
                     revision_sha, active, created_at, updated_at)
                 SELECT $1::int, input.path, input.name, input.declared, input.hash,
                        $2::text, TRUE, $3::timestamptz, $3::timestamptz
                 FROM unnest($4::text[], $5::text[], $6::int[], $7::text[])
                      AS input(path, name, declared, hash)
                 ON CONFLICT (source_id, source_path) DO UPDATE
                    SET name = EXCLUDED.name,
                        declared_issue_count = EXCLUDED.declared_issue_count,
                        content_hash = EXCLUDED.content_hash,
                        revision_sha = EXCLUDED.revision_sha,
                        active = TRUE,
                        updated_at = EXCLUDED.updated_at
                 RETURNING id, source_path",
                &[
                    &source_id, &revision, &synced_at, &paths, &names, &declared, &hashes,
                ],
            )
            .await
            .map_err(|error| IngestError::new(format!("cbl list upsert failed: {error}")))?;
        for row in &rows {
            ids.insert(row.get::<_, String>(1), row.get::<_, i32>(0));
        }
    }
    Ok(ids)
}

async fn delete_entries<C: GenericClient>(client: &C, list_ids: &[i32]) -> Result<(), IngestError> {
    for chunk in list_ids.chunks(BATCH_SIZE) {
        client
            .execute(
                "DELETE FROM cbl_source_entries WHERE list_id = ANY($1::int[])",
                &[&chunk],
            )
            .await
            .map_err(|error| IngestError::new(format!("cbl entry replacement failed: {error}")))?;
    }
    Ok(())
}

fn collect_identity_ids(pending: &[&CBLList]) -> (Vec<String>, Vec<String>) {
    let mut series_ids = BTreeSet::new();
    let mut issue_ids = BTreeSet::new();
    for list in pending {
        for book in &list.books {
            if let Some(id) = &book.comicvine_series_id {
                series_ids.insert(id.clone());
            }
            if let Some(id) = &book.comicvine_issue_id {
                issue_ids.insert(id.clone());
            }
        }
    }
    (
        series_ids.into_iter().collect(),
        issue_ids.into_iter().collect(),
    )
}

async fn count_missing_identities<C: GenericClient>(
    client: &C,
    pending: &[&CBLList],
) -> Result<usize, IngestError> {
    let (series_ids, issue_ids) = collect_identity_ids(pending);
    let mut existing = 0usize;
    for (entity_type, ids) in [("series", &series_ids), ("issue", &issue_ids)] {
        for chunk in ids.chunks(BATCH_SIZE) {
            let row = client
                .query_one(
                    "SELECT COUNT(*)::bigint FROM external_identities
                     WHERE provider = 'comicvine' AND entity_type = $1::text
                       AND external_id = ANY($2::text[])",
                    &[&entity_type, &chunk],
                )
                .await
                .map_err(|error| {
                    IngestError::new(format!("cbl identity lookup failed: {error}"))
                })?;
            existing += usize::try_from(row.get::<_, i64>(0)).unwrap_or(0);
        }
    }
    Ok((series_ids.len() + issue_ids.len()).saturating_sub(existing))
}

/// Insert missing (provider, entity type, external id) identities in batches.
async fn upsert_identities<C: GenericClient>(
    client: &C,
    pending: &[&CBLList],
    synced_at: DateTime<Utc>,
) -> Result<usize, IngestError> {
    let (series_ids, issue_ids) = collect_identity_ids(pending);
    let mut inserted = 0;
    for (entity_type, ids) in [("series", &series_ids), ("issue", &issue_ids)] {
        for chunk in ids.chunks(BATCH_SIZE) {
            let count = client
                .execute(
                    "INSERT INTO external_identities
                        (provider, entity_type, external_id, metadata_json, created_at, updated_at)
                     SELECT 'comicvine', $1::text, input.external_id,
                            '{}'::json, $2::timestamptz, $2::timestamptz
                     FROM unnest($3::text[]) AS input(external_id)
                     ON CONFLICT (provider, entity_type, external_id) DO NOTHING",
                    &[&entity_type, &synced_at, &chunk],
                )
                .await
                .map_err(|error| {
                    IngestError::new(format!("cbl identity upsert failed: {error}"))
                })?;
            inserted += usize::try_from(count).unwrap_or(0);
        }
    }
    Ok(inserted)
}

#[derive(Default)]
struct IdentityIds {
    series: HashMap<String, i32>,
    issues: HashMap<String, i32>,
}

async fn resolve_identity_ids<C: GenericClient>(
    client: &C,
    pending: &[&CBLList],
) -> Result<IdentityIds, IngestError> {
    let (series_ids, issue_ids) = collect_identity_ids(pending);
    let mut result = IdentityIds::default();
    for chunk in series_ids.chunks(BATCH_SIZE) {
        let rows = client
            .query(
                "SELECT id, external_id FROM external_identities
                 WHERE provider = 'comicvine' AND entity_type = 'series'
                   AND external_id = ANY($1::text[])",
                &[&chunk],
            )
            .await
            .map_err(|error| IngestError::new(format!("cbl identity lookup failed: {error}")))?;
        for row in &rows {
            result
                .series
                .insert(row.get::<_, String>(1), row.get::<_, i32>(0));
        }
    }
    for chunk in issue_ids.chunks(BATCH_SIZE) {
        let rows = client
            .query(
                "SELECT id, external_id FROM external_identities
                 WHERE provider = 'comicvine' AND entity_type = 'issue'
                   AND external_id = ANY($1::text[])",
                &[&chunk],
            )
            .await
            .map_err(|error| IngestError::new(format!("cbl identity lookup failed: {error}")))?;
        for row in &rows {
            result
                .issues
                .insert(row.get::<_, String>(1), row.get::<_, i32>(0));
        }
    }
    Ok(result)
}

async fn insert_entries<C: GenericClient>(
    client: &C,
    pending: &[&CBLList],
    list_ids: &HashMap<String, i32>,
    identity_ids: &IdentityIds,
    synced_at: DateTime<Utc>,
) -> Result<usize, IngestError> {
    let mut list_ids_column = Vec::with_capacity(BATCH_SIZE);
    let mut positions = Vec::with_capacity(BATCH_SIZE);
    let mut series_names = Vec::with_capacity(BATCH_SIZE);
    let mut issue_numbers = Vec::with_capacity(BATCH_SIZE);
    let mut volume_years = Vec::with_capacity(BATCH_SIZE);
    let mut publication_years = Vec::with_capacity(BATCH_SIZE);
    let mut series_identity_ids = Vec::with_capacity(BATCH_SIZE);
    let mut issue_identity_ids = Vec::with_capacity(BATCH_SIZE);
    let mut written = 0;
    for list in pending {
        let Some(list_id) = list_ids.get(&list.source_path) else {
            return Err(IngestError::new("upserted CBL list has no id"));
        };
        for book in &list.books {
            list_ids_column.push(*list_id);
            positions.push(book.position);
            series_names.push(book.series.clone());
            issue_numbers.push(book.issue_number.clone());
            volume_years.push(book.volume_year);
            publication_years.push(book.publication_year);
            series_identity_ids.push(
                book.comicvine_series_id
                    .as_ref()
                    .and_then(|id| identity_ids.series.get(id).copied()),
            );
            issue_identity_ids.push(
                book.comicvine_issue_id
                    .as_ref()
                    .and_then(|id| identity_ids.issues.get(id).copied()),
            );
            if list_ids_column.len() == BATCH_SIZE {
                written += insert_entry_batch(
                    client,
                    &list_ids_column,
                    &positions,
                    &series_names,
                    &issue_numbers,
                    &volume_years,
                    &publication_years,
                    &series_identity_ids,
                    &issue_identity_ids,
                    synced_at,
                )
                .await?;
                list_ids_column.clear();
                positions.clear();
                series_names.clear();
                issue_numbers.clear();
                volume_years.clear();
                publication_years.clear();
                series_identity_ids.clear();
                issue_identity_ids.clear();
            }
        }
    }
    if !list_ids_column.is_empty() {
        written += insert_entry_batch(
            client,
            &list_ids_column,
            &positions,
            &series_names,
            &issue_numbers,
            &volume_years,
            &publication_years,
            &series_identity_ids,
            &issue_identity_ids,
            synced_at,
        )
        .await?;
    }
    Ok(written)
}

#[allow(clippy::too_many_arguments)]
async fn insert_entry_batch<C: GenericClient>(
    client: &C,
    list_ids: &[i32],
    positions: &[i32],
    series_names: &[String],
    issue_numbers: &[String],
    volume_years: &[Option<i32>],
    publication_years: &[Option<i32>],
    series_identity_ids: &[Option<i32>],
    issue_identity_ids: &[Option<i32>],
    synced_at: DateTime<Utc>,
) -> Result<usize, IngestError> {
    let count = client
        .execute(
            "INSERT INTO cbl_source_entries
                (list_id, position, series_name, issue_number, volume_year,
                 publication_year, external_series_identity_id,
                 external_issue_identity_id, created_at)
             SELECT input.list_id, input.position, input.series_name, input.issue_number,
                    input.volume_year, input.publication_year,
                    input.series_identity_id, input.issue_identity_id, $9::timestamptz
             FROM unnest($1::int[], $2::int[], $3::text[], $4::text[], $5::int[],
                         $6::int[], $7::int[], $8::int[])
                  AS input(list_id, position, series_name, issue_number, volume_year,
                           publication_year, series_identity_id, issue_identity_id)",
            &[
                list_ids,
                positions,
                series_names,
                issue_numbers,
                volume_years,
                publication_years,
                series_identity_ids,
                issue_identity_ids,
                &synced_at,
            ],
        )
        .await
        .map_err(|error| IngestError::new(format!("cbl entry insert failed: {error}")))?;
    Ok(usize::try_from(count).unwrap_or(0))
}

#[cfg(test)]
mod tests {
    use super::*;

    static NEXT_GIT_FIXTURE: AtomicUsize = AtomicUsize::new(1);

    struct GitFixture {
        root: PathBuf,
        revision: String,
    }

    impl GitFixture {
        fn new(repository: &str) -> Self {
            let root = std::env::temp_dir().join(format!(
                "comicpile-cbl-git-{}-{}",
                std::process::id(),
                NEXT_GIT_FIXTURE.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&root).unwrap();
            git(&root, &["init", "--quiet"]);
            git(
                &root,
                &[
                    "remote",
                    "add",
                    "origin",
                    &format!("https://github.com/{repository}.git"),
                ],
            );
            fs::write(
                root.join("DC.cbl"),
                minimal_cbl("<Book Series=\"X\" Number=\"1\" />"),
            )
            .unwrap();
            git(&root, &["add", "."]);
            git(
                &root,
                &[
                    "-c",
                    "user.name=CBL Test",
                    "-c",
                    "user.email=cbl-test@example.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "fixture",
                ],
            );
            let revision = git(&root, &["rev-parse", "HEAD"]).trim().to_string();
            Self { root, revision }
        }
    }

    impl Drop for GitFixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    fn git(root: &Path, arguments: &[&str]) -> String {
        let output = Command::new("git")
            .arg("-C")
            .arg(root)
            .args(arguments)
            .output()
            .unwrap();
        assert!(output.status.success(), "git {arguments:?} failed");
        String::from_utf8(output.stdout).unwrap()
    }

    fn minimal_cbl(extra: &str) -> Vec<u8> {
        format!(
            "<ReadingList><Name>Batman &amp; Robin</Name><NumIssues>2</NumIssues><Books>{extra}</Books></ReadingList>"
        )
        .into_bytes()
    }

    #[test]
    fn parses_ordered_entries_and_comicvine_identities() {
        let xml = minimal_cbl(
            "<Book Series=\"Batman\" Number=\"1\" Volume=\"2016\" Year=\"None\" SeriesID=\"4059\">\
                <Database Name=\"ComicVine\" Issue=\"1001\" /></Book>\
             <Book Series=\"Robin\" Number=\"2\" Volume=\"None\" IssueID=\"2002\" Year=\"2011\" />",
        );
        let list = parse_cbl_bytes(&xml, "DC/Batman.cbl").expect("parse");
        assert_eq!(list.name, "Batman & Robin");
        assert_eq!(list.declared_issue_count, Some(2));
        assert_eq!(list.books.len(), 2);
        assert_eq!(list.books[0].position, 1);
        assert_eq!(list.books[0].volume_year, Some(2016));
        assert_eq!(list.books[0].publication_year, None);
        assert_eq!(list.books[0].comicvine_series_id.as_deref(), Some("4059"));
        assert_eq!(list.books[0].comicvine_issue_id.as_deref(), Some("1001"));
        assert_eq!(list.books[1].volume_year, None);
        assert_eq!(list.books[1].comicvine_issue_id.as_deref(), Some("2002"));
        assert_eq!(list.content_hash.len(), 64);
    }

    #[test]
    fn decodes_numeric_and_named_entities_in_list_names() {
        let xml =
            b"<ReadingList><Name>Batman &#39; Robin &amp; Friends</Name><Books /></ReadingList>";
        let list = parse_cbl_bytes(xml, "DC/Batman.cbl").expect("parse");
        assert_eq!(list.name, "Batman ' Robin & Friends");
    }

    #[test]
    fn malformed_documents_and_missing_required_fields_fail_with_path_context() {
        let broken = b"<ReadingList><Books><Book Series=\"X\"></Books></ReadingList>";
        assert!(parse_cbl_bytes(broken, "DC/Broken.cbl").is_err());
        let missing = minimal_cbl("<Book Number=\"1\" />");
        assert!(parse_cbl_bytes(&missing, "DC/Missing.cbl").is_err());
    }

    #[test]
    fn rejects_wrong_roots_and_database_bound_violations() {
        let wrong_root = b"<Foo><Books><Book Series=\"X\" Number=\"1\" /></Books></Foo>";
        let error = parse_cbl_bytes(wrong_root, "DC/Wrong.cbl").expect_err("wrong root");
        assert!(error.to_string().contains("ReadingList"));

        let missing_books = b"<ReadingList><Name>Empty</Name></ReadingList>";
        assert!(parse_cbl_bytes(missing_books, "DC/MissingBooks.cbl").is_err());

        let long_series = format!(
            "<ReadingList><Books><Book Series=\"{}\" Number=\"1\" /></Books></ReadingList>",
            "S".repeat(MAX_SERIES_NAME_LENGTH + 1)
        );
        assert!(parse_cbl_bytes(long_series.as_bytes(), "DC/Series.cbl").is_err());

        let long_issue = format!(
            "<ReadingList><Books><Book Series=\"X\" Number=\"{}\" /></Books></ReadingList>",
            "1".repeat(MAX_ISSUE_NUMBER_LENGTH + 1)
        );
        assert!(parse_cbl_bytes(long_issue.as_bytes(), "DC/Issue.cbl").is_err());

        let nested_id = format!(
            "<ReadingList><Books><Book Series=\"X\" Number=\"1\"><Database Name=\"ComicVine\" Issue=\"{}\" /></Book></Books></ReadingList>",
            "9".repeat(MAX_EXTERNAL_ID_LENGTH + 1)
        );
        assert!(parse_cbl_bytes(nested_id.as_bytes(), "DC/Identity.cbl").is_err());
    }

    #[test]
    fn pinned_checkout_requires_exact_clean_origin_and_head() {
        let fixture = GitFixture::new(DEFAULT_REPOSITORY);
        verify_pinned_checkout(&fixture.root, &fixture.revision, DEFAULT_REPOSITORY)
            .expect("clean pinned checkout");
        assert!(
            verify_pinned_checkout(&fixture.root, &"0".repeat(40), DEFAULT_REPOSITORY).is_err()
        );

        fs::write(
            fixture.root.join("DC.cbl"),
            "<ReadingList><Books /></ReadingList>",
        )
        .unwrap();
        assert!(
            verify_pinned_checkout(&fixture.root, &fixture.revision, DEFAULT_REPOSITORY)
                .expect_err("dirty checkout")
                .to_string()
                .contains("clean")
        );
        git(&fixture.root, &["checkout", "--", "DC.cbl"]);
        fs::write(
            fixture.root.join("untracked.cbl"),
            "<ReadingList><Books /></ReadingList>",
        )
        .unwrap();
        assert!(
            verify_pinned_checkout(&fixture.root, &fixture.revision, DEFAULT_REPOSITORY).is_err()
        );
        fs::remove_file(fixture.root.join("untracked.cbl")).unwrap();
        git(
            &fixture.root,
            &[
                "remote",
                "set-url",
                "origin",
                "https://github.com/other/fork.git",
            ],
        );
        assert!(
            verify_pinned_checkout(&fixture.root, &fixture.revision, DEFAULT_REPOSITORY).is_err()
        );
    }

    #[test]
    fn inventory_counts_publishers_duplicates_and_failures() {
        let good = parse_cbl_bytes(
            &minimal_cbl("<Book Series=\"X\" Number=\"1\" />"),
            "DC/One.cbl",
        )
        .expect("parse");
        let duplicate = CBLList {
            source_path: "DC/Two.cbl".to_string(),
            ..good.clone()
        };
        let failure = CBLParseFailure {
            source_path: "Marvel/Bad.cbl".to_string(),
            message: "malformed".to_string(),
        };
        let inventory = build_inventory(&[good, duplicate], &[failure]).expect("inventory");
        assert_eq!(inventory.total_files, 3);
        assert_eq!(inventory.parsed_files, 2);
        assert_eq!(inventory.failed_files, 1);
        assert_eq!(inventory.duplicate_content_hash_groups, 1);
        assert_eq!(inventory.publishers[0].name, "DC");
        assert_eq!(inventory.publishers[0].parsed, 2);
        assert_eq!(inventory.publishers[1].name, "Marvel");
        assert_eq!(inventory.publishers[1].failed, 1);
    }

    #[test]
    fn cli_requires_revision_and_rejects_alias_equal_to_repository() {
        let arguments = vec!["/mirror".to_string()];
        assert!(parse_options(&arguments).is_err());
        let arguments = vec![
            "/mirror".to_string(),
            "--revision-sha".to_string(),
            "a".repeat(40),
            "--reconcile-repository".to_string(),
            DEFAULT_REPOSITORY.to_string(),
        ];
        assert!(parse_options(&arguments).is_err());
        let options = parse_options(&[
            "/mirror".to_string(),
            "--revision-sha".to_string(),
            "a".repeat(40),
            "--dry-run".to_string(),
        ])
        .expect("options");
        assert!(options.dry_run);
        assert_eq!(options.repository, DEFAULT_REPOSITORY);
    }
}
