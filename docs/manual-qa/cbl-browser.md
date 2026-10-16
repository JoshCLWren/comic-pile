# CBL browser

**Route:** `/cbl-sources`. Discover, preview and adopt external Comic Book Reading List sources into reader-owned lists.

## MQA-CBL-001: Browse/search truthfully

**Test:** Browse available sources and search a recognizable source, inspecting suggestion and result relevance.

**Expected:** Matching lists can be found where available, suggestions correspond to the query, and missing sources are not claimed to exist.

## MQA-CBL-002: Preview is non-mutating

**Test:** Open a source preview and compare entry sequence and proposed changes with an existing QA list.

**Expected:** Issues, order, unmapped entries and proposed changes are clear; preview alone does not alter owned lists or reading state.

## MQA-CBL-003: Adoption preserves curated intent

**Setup:** QA-owned list with deliberately curated issue order.

**Test:** Approve an import/update and revisit this and unrelated lists.

**Expected:** Only the approved changes occur; no unrelated order, excluded comic or list is silently regenerated, replaced or added.

## MQA-CBL-004: Imported lists agree with Roll rules

**Test:** Inspect a QA list with known strict/loose gates after the Reading List model is active and compare Roll offers.

**Expected:** Result honors the list's actual gates and prerequisites; ordinary loose-list adjacency is never silently compiled into hard blocks.
