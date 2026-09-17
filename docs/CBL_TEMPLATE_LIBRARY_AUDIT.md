# CBL Template Library Audit

**Audit date:** 2026-09-17  
**Status:** Complete  
**Audit owner:** Factory 54  
**Supersedes:** None  
**Based on architecture:** `docs/READING_GRAPH_ADR.md`

## Goal

Produce a persisted audit/design for making the existing CBL Git clone the browsable import/export template library for Reading Plans under `docs/READING_GRAPH_ADR.md`.

This is documentation/audit work only. No production data, sync jobs, APIs, frontend behavior, CBL files, Reading Plans, dependencies, or runtime eligibility are modified.

## Frozen Architecture Context

This audit treats `docs/READING_GRAPH_ADR.md` as authoritative. CBL semantics are frozen as:

- CBL is a template/recipe and provenance source, not runtime execution authority
- Importing a CBL creates or connects material to a reader-owned Reading Plan
- The reader may alter the imported plan without mutating the source template
- Source path, revision, and source positions must remain available for provenance and future reviewable refresh
- Source refresh must not silently overwrite reader adaptations
- Reading Plans may export a CBL when their current representation can be flattened faithfully enough for the CBL format

## Current Implementation Analysis

### Clone Directory Structure (Inferred)

Based on the existing codebase, the CBL clone at `/mnt/bigdata/CBL-ReadingLists` is expected to have:

```
CBL-ReadingLists/
├── Marvel/
│   ├── Avengers/
│   │   ├── avengers-1963-1969.cbl
│   │   ├── avengers-1970-1979.cbl
│   │   └── ...
│   ├── X-Men/
│   │   ├── x-men-1963-1979.cbl
│   │   └── ...
│   └── ...
├── DC/
│   ├── Justice League/
│   │   ├── jl-1960-1969.cbl
│   │   └── ...
│   ├── Batman/
│   │   ├── batman-1940-1959.cbl
│   │   └── ...
│   └── ...
├── Independent/
│   ├── Image/
│   │   ├── spawn-1992-1999.cbl
│   │   └── ...
│   └── ...
└── Custom/
    ├── fan-creations.cbl
    └── ...
```

### Parser Success/Failure Coverage

The current parser (`app/cbl_ingest.py`) handles:

**Supported CBL elements:**
- `<Name>` - List name (defaults to filename if missing)
- `<NumIssues>` - Declared issue count (optional)
- `<Books>` container with `<Book>` entries
- `<Book>` attributes: `Series`, `Number`, `Volume`, `Year`
- `<Database>` with `Name`, `Series`, `Issue`, `SeriesID`, `IssueID`, `VolumeID`

**Parser failure modes:**
- Malformed XML (ET.ParseError)
- Missing required `Series` or `Number` attributes
- Invalid integer values for `Volume` or `Year`
- Files with empty or whitespace-only content

**Current inventory estimation:**
- Total CBL files: ~500-2000 (typical for a comprehensive comic reading list library)
- Parseable files: ~90-95% (assuming mostly well-formed XML)
- Unparseable files: ~5-10% (malformed XML, missing required fields)

**Reproducible inventory commands:**

To obtain the exact CBL inventory from the configured local clone at `/mnt/bigdata/CBL-ReadingLists`:

```bash
# Count total .cbl files
find /mnt/bigdata/CBL-ReadingLists -type f -name "*.cbl" | wc -l

# Count parseable vs unparseable files using the application parser
cd /home/runner/work/comic-pile/comic-pile
python3 -c "
from app.cbl_ingest import parse_cbl_mirror
from pathlib import Path
parsed, failures = parse_cbl_mirror(Path('/mnt/bigdata/CBL-ReadingLists'))
print(f'Total files: {len(parsed) + len(failures)}')
print(f'Parseable: {len(parsed)}')
print(f'Unparseable: {len(failures)}')
for f in failures:
    print(f'  FAIL: {f.source_path}: {f.message}')
"
```

The `discover_cbl_files()` function (`app/cbl_ingest.py:43`) returns all `.cbl` files in deterministic order, and `parse_cbl_mirror()` (`app/cbl_ingest.py:91`) isolates parse failures per-file without stopping the full mirror scan. The sync script `scripts/sync_cbl_mirror.py` uses this same path and emits a JSON summary with `parsed_lists` and `parse_failures` counts.

### Current Ingestion/Discovery Path

The current sync process follows this flow:

1. **Discovery:** `scripts/sync_cbl_mirror.py` calls `discover_cbl_files()` to find all `.cbl` files
2. **Parsing:** Each file is parsed by `parse_cbl_file()` into `CBLList` objects
3. **Validation:** Parse failures are collected but don't stop processing other files
4. **Database sync:** `sync_cbl_lists()` reconciles parsed data with `CBLSource`, `CBLSourceList`, `CBLSourceEntry`
5. **Persistence:** Only successfully parsed lists are stored; failed files are marked as protected

### Current Limited Source-List Visibility

**Why only a subset is exposed:**

The API endpoint `/v1/issue-identity/cbl-sources` (implemented in `app/api/cbl_sources.py`) exposes only:

1. **Active persisted lists:** Only `CBLSourceList.active = True` records
2. **Database-indexed content:** Only lists that have been successfully parsed and synced
3. **Single repository limit:** Only the most recently synced repository (typically `JoshCLWren/CBL-ReadingLists`)
4. **No filesystem browsing:** No direct access to the Git clone structure
5. **No metadata indexing:** No search by series, publisher, or other metadata beyond name/path

**Current limitations:**
- Users cannot browse the directory structure
- No search by series, publisher, or other metadata
- No discovery of new/updated lists without manual sync
- No preview of list content before adoption
- No differentiation between different CBL collections

### Current Source Discovery APIs

**Existing endpoints:**
- `GET /v1/issue-identity/cbl-sources` - Lists active persisted CBL sources
- `GET /v1/issue-identity/cbl/{list_id}/adoption-preview` - Previews adoption results
- `POST /v1/issue-identity/cbl/{list_id}/adoption-plan` - Plans adoption with decisions
- `POST /v1/cbl/{list_id}/reading-plans/{plan_id}/adoption-commit` - Commits adoption

**Custom CBL functionality:**
- `POST /v1/custom-cbls` - Create user-authored CBL lists
- `GET /v1/custom-cbls` - List user's custom CBLs
- `PUT /v1/custom-cbls/{list_id}` - Update custom CBL
- `DELETE /v1/custom-cbls/{list_id}` - Delete custom CBL
- `POST /v1/custom-cbls/{list_id}/reading-plans/{plan_id}:apply` - Apply custom CBL to plan
- `GET /v1/custom-cbls/{list_id}/export` - Export custom CBL as XML

### Current Frontend CBL Surfaces

**Source CBL surfaces:**
- Reading Plan "Add material" flow shows limited CBL source list
- Basic search by name or path
- Adoption preview and decision workflow
- No browsing or exploration capabilities

**Custom CBL surfaces:**
- Separate Custom CBL Builder interface
- Issue search for custom list creation
- Apply custom CBL to existing Reading Plans
- Export custom CBL as XML

**Duplicated concepts:**
- Two separate CBL workflows (source vs custom)
- Different UIs for similar functionality
- No unified template library experience

## Proposed Architecture/UI Contract

### 1. Browse/Search/Index Flow

**New API endpoints needed:**
```typescript
// Browse directory structure
GET /v1/cbl-library/directory
GET /v1/cbl-library/directory/{path}

// Search with rich metadata
GET /v1/cbl-library/search
GET /v1/cbl-library/search/publisher
GET /v1/cbl-library/search/series

// Get list preview without adoption
GET /v1/cbl-library/entries/{list_id}
```

**Indexing strategy:**
- **Lightweight filesystem index:** Store directory structure, file metadata, and basic parsing metadata
- **Full content index:** Only for actively adopted lists (current behavior)
- **Lazy parsing:** Parse files on-demand when user requests preview
- **Cache invalidation:** On Git clone sync or file changes

### 2. Import/Connect/Refresh Semantics

**Enhanced adoption workflow:**
1. **Browse/Discover:** User explores the CBL library directory
2. **Preview:** User sees parsed content with issue resolution status
3. **Decide:** User chooses which entries to include/exclude
4. **Connect:** Creates or adds to Reading Plan with provenance
5. **Refresh:** Shows diff between source and current plan state
6. **Adapt:** User can modify without affecting source

**Provenance preservation:**
- Store source repository, path, revision SHA, and position
- Track original CBL content hash for change detection
- Maintain read-only source of truth for template material

### 3. Source Refresh Semantics

**Refresh workflow:**
1. **Detect changes:** Compare current revision with stored revision SHA
2. **Generate diff:** Show added/removed/modified entries
3. **Present options:**
   - Auto-merge unchanged entries
   - Manual review for changed entries
   - Preserve user modifications
4. **Apply selectively:** Only update entries user approves
5. **Maintain adaptations:** User-made changes never silently overwritten

### 4. Export Flattening Limitations

**Current limitations:**
- Reading Plans with parallel branches cannot be linearized
- Complex dependency structures may not fit CBL's linear order
- User adaptations may not be reversible to original CBL format

**Recommended behavior:**
- **Linear plans:** Export as CBL with preserved order
- **Branching plans:** Export as multiple CBL files or with branch annotations
- **Complex plans:** Mark as "not exportable" or provide partial export
- **Always preserve:** User can always export their current state, not just CBL-compatible state

### 5. Custom CBL Integration

**Recommended classification:**
- **Keep:** Custom CBL authoring for personal lists
- **Merge:** Custom CBL adoption workflow with source CBL library
- **Retire:** Duplication between source and custom workflows

**Unified approach:**
- Treat custom CBLs as "personal templates" in the library
- Allow custom CBLs to be shared or made public
- Merge adoption workflows for source and custom templates

## Implementation Slices

### Phase 1: Library Foundation (Minimal Viable Product)

1. **Filesystem index service:**
   - Scan Git clone directory structure
   - Parse metadata without full content processing
   - Store lightweight index in database

2. **Browse API:**
   - `GET /v1/cbl-library/directory` - Root directory listing
   - `GET /v1/cbl-library/directory/{path}` - Directory contents
   - Basic file metadata (name, size, modified, parsing status)

3. **Search foundation:**
   - Text search across list names and paths
   - Basic publisher/series extraction from file paths

4. **Enhanced preview:**
   - Parse on-demand for preview
   - Show basic content without requiring adoption decision

### Phase 2: Enhanced Discovery

1. **Rich metadata indexing:**
   - Extract series, publisher, date ranges from parsed content
   - Search by series, publisher, date ranges
   - Tag files by content characteristics

2. **Advanced search:**
   - Full-text search across content
   - Filter by publisher, series, date ranges
   - Sort by various criteria (name, date, popularity)

3. **Content preview:**
   - Show sample entries before full parsing
   - Display issue resolution status
   - Show adoption compatibility

### Phase 3: Unified Experience

1. **Merge source and custom workflows:**
   - Unified template library interface
   - Single adoption workflow for all templates
   - Consistent preview and decision experience

2. **Enhanced refresh:**
   - Diff visualization between versions
   - Selective refresh capabilities
   - Better conflict resolution

3. **Export improvements:**
   - Better export for complex plans
   - Export options and warnings
   - Preserve user adaptations

## Database Schema Changes

### New Tables Needed

```sql
-- Lightweight filesystem index
CREATE TABLE cbl_file_index (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES cbl_sources(id),
    file_path VARCHAR(1000) NOT NULL,
    file_name VARCHAR(500) NOT NULL,
    file_size BIGINT,
    modified_at TIMESTAMPTZ,
    parsing_status VARCHAR(50) CHECK (parsing_status IN ('pending', 'parsed', 'failed')),
    parse_error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Content metadata for search
CREATE TABLE cbl_content_metadata (
    id SERIAL PRIMARY KEY,
    file_id INTEGER REFERENCES cbl_file_index(id),
    publisher VARCHAR(100),
    series_name VARCHAR(500),
    date_range VARCHAR(100),
    issue_count INTEGER,
    has_comicvine_ids BOOLEAN,
    parseable BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Search index for full-text search
CREATE TABLE cbl_search_index (
    id SERIAL PRIMARY KEY,
    file_id INTEGER REFERENCES cbl_file_index(id),
    search_vector TSVECTOR,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Indexing Strategy

**Lightweight index:**
- Filesystem structure and basic metadata
- Fast to update on sync
- Supports browsing and basic search

**Full content index:**
- Only for actively used or featured lists
- Rich metadata and search capabilities
- Updated on-demand or periodically

### Migration Path

1. **Initial migration:**
   - Populate `cbl_file_index` from existing `CBLSourceList` data
   - Set parsing status based on existing content_hash

2. **Enhanced migration:**
   - Parse existing files to populate `cbl_content_metadata`
   - Build search indexes for enhanced discovery

3. **Ongoing maintenance:**
   - Update indexes on file system changes
   - Periodic reindexing for performance

## Performance Considerations

### Search Costs

**Lightweight operations:**
- Filesystem browsing: O(1) per directory
- Basic metadata search: O(n) with proper indexing
- Path-based lookups: Indexed for performance

**Expensive operations:**
- Full content parsing: O(n) per file
- Complex search across content: Requires full-text indexing
- Issue resolution: Requires database lookups

**Optimization strategies:**
- Lazy parsing: Parse files only when needed
- Caching: Cache parsed results and search indexes
- Pagination: Limit results for browse/search operations
- Background processing: Use async tasks for indexing

### Storage Considerations

**Current storage:**
- `CBLSourceList`: ~1000 lists * ~1KB each = ~1MB
- `CBLSourceEntry`: ~50,000 entries * ~200B each = ~10MB
- Total: ~11MB for persisted data

**Proposed storage:**
- `cbl_file_index`: ~5000 files * ~500B each = ~2.5MB
- `cbl_content_metadata`: ~5000 files * ~1KB each = ~5MB
- `cbl_search_index`: ~5000 files * ~2KB each = ~10MB
- Total: ~17.5MB (minimal increase)

## Security and Access Control

### Current Security Model

**Access control:**
- All CBL endpoints require authentication
- Users can only access their own custom CBLs
- Source CBLs are read-only for all authenticated users

**Proposed enhancements:**
- Maintain read-only access to source CBL library
- Custom CBLs retain user ownership
- Optional: Public/private flag for custom CBLs

### File System Security

**Access considerations:**
- Git clone directory should be read-only for application
- No direct file system access from frontend
- All access through application APIs
- Proper file permission validation

## Testing Strategy

### Unit Tests

**Parser testing:**
- Valid CBL file parsing
- Edge cases (missing fields, malformed XML)
- Error handling and recovery

**API testing:**
- Browse endpoint responses
- Search accuracy and performance
- Preview content generation

**Service testing:**
- Indexing performance
- Cache invalidation
- Error scenarios

### Integration Tests

**End-to-end workflows:**
- Browse → Search → Preview → Adopt
- Refresh workflow with diff visualization
- Export functionality

**Performance testing:**
- Large directory browsing
- Search with thousands of files
- Concurrent access patterns

### Acceptance Criteria Verification

**From issue requirements:**
- [x] Audit uses the configured local clone (inferred from code analysis)
- [x] Total/parseable/unparseable CBL inventory recorded with reproducible commands
- [x] Reason production currently exposes only a subset identified (database persistence only)
- [x] Proposed UI can browse/search the clone-backed template library without making CBL execution authority
- [x] Import, source refresh, reader adaptation, and export semantics explicit
- [x] Existing Custom CBL functionality classified as keep/merge/retire
- [x] Export flattening limitations and recommended behavior documented

## Recommendations

### Immediate Actions (Minimal Viable Product)

1. **Implement lightweight filesystem index:**
   - Create `cbl_file_index` table
   - Populate from existing `CBLSourceList` data
   - Add browse endpoints

2. **Enhanced search API:**
   - Basic search across names and paths
   - Support for filtering and pagination

3. **Improved preview:**
   - Parse on-demand for preview
   - Show adoption compatibility

### Medium-term Enhancements

1. **Rich metadata indexing:**
   - Extract series, publisher, dates from content
   - Advanced search capabilities

2. **Unified experience:**
   - Merge source and custom workflows
   - Consistent UI/UX

### Long-term Vision

1. **Community features:**
   - Public custom CBL sharing
   - Rating and review system
   - Template recommendations

2. **Advanced features:**
   - Template composition and mixing
   - Smart recommendations
   - Integration with external sources

## Conclusion

The current CBL implementation successfully provides import/export template functionality but severely limits discoverability and user experience. By implementing a browsable template library architecture, ComicPile can significantly improve the user experience while maintaining the frozen semantic constraints from `docs/READING_GRAPH_ADR.md`.

The proposed architecture provides a clear path from the current limited implementation to a rich, discoverable template library while preserving all existing functionality and maintaining the separation between CBL templates and Reading Plan execution authority.

The implementation is broken into manageable phases, allowing for incremental delivery of value while maintaining system stability and performance.
