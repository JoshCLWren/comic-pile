# Reader-facing CBL source labels

Source titles identify reading material. Repository paths, revision hashes, and storage references are provenance, not primary names.

Reading Plan index cards, reader issue rows, and source summaries use a readable source filename/title. A retained `custom-cbl:<id>` reference resolves to that reader's current Reading List name through an owner-scoped, batched repository read. Missing or foreign references use a generic Reading List label without exposing another reader's name. The API retains the original reference for compatibility and adds `source_names` to index items and `display_name` to source snapshots. Reading these labels does not modify lists, progress, or history.

CBL candidate cards use the declared title with metadata tags removed. The Source details disclosure preserves safe source-relative paths and repository attribution; a selected source's existing disclosure retains its revision. Host filesystem prefixes and opaque custom-list references are never displayed, including behind disclosures. Windows drive paths receive the same protection as absolute Unix paths.

Disclosures are separate from navigation/selection buttons, so opening provenance does not select a candidate or navigate away. Existing semantic typography, surfaces, spacing, and native disclosure behavior are retained under the frontend visual grammar.

Focused tests cover index cards, candidates, reader summaries/rows, ownership isolation, source renames, malformed/overflow references, and read-only behavior. `frontend/src/test/cbl-source-labels.spec.ts` walks the real local API-to-browser flow at desktop and phone widths and checks provenance disclosure, hidden identifiers, and horizontal containment.
