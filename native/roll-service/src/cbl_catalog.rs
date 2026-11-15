//! Read-only browsing of the shared CBL catalog folder tree and search.
//!
//! These endpoints are deliberately ownership-free: they read the shared
//! `cbl_sources` / `cbl_source_lists` catalog and never join reader-owned
//! Issues, Threads, Reading Lists, or adoption receipts. Folder navigation, search,
//! and pagination therefore produce identical results for every authenticated
//! account, including a brand-new one with no comics.
//!
//! Folder paths are source-relative and `/`-separated. A folder is not stored as
//! a row: it is derived from the path prefixes of active lists. The SQL below uses
//! `split_part`/`strpos` so folder listing stays a single aggregate query even
//! when the catalog contains thousands of paths.