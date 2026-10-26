"""Checked schemas for deterministic production reading graph and reviewed intent.

Every compact row is validated on load, including nullable catalog foreign
keys. A missing or malformed fixture field must fail before replay can run.
"""

from typing import NotRequired, TypedDict

type RowValue = str | int | bool | None | list[int]
type ThreadRow = tuple[int, str, str, int, int | None, int | None, int, str, bool, bool, int | None, int | None]
type IssueRow = tuple[int, int, str, int, str, int | None]
type ListRow = tuple[int, str, str]
type EntryRow = tuple[int, int, int, int, str, bool, bool, list[int]]
type DependencyRow = tuple[int, int, int, str | None, str | None, str]
type ExclusionRow = tuple[int, str, str, int | None, int | None]
type OverlapRow = tuple[int, int, int, int]
type IdentityRow = tuple[int, str, str, str]
type ThreadMappingRow = tuple[int, int, int, str]
type CatalogSeriesRow = tuple[int, int]
type CatalogIssueRow = tuple[int, int, int | None]


class GeneratedDependencyCensus(TypedDict):
    """Fingerprint of historical generated evidence, not active constraints."""

    count: int
    fingerprint: str


class ProductionGraphFixture(TypedDict):
    """All reader-derived rows used by the real Option E SQL replay."""

    schema_version: int
    reader: str
    threads: list[ThreadRow]
    issues: list[IssueRow]
    lists: list[ListRow]
    entries: list[EntryRow]
    dependencies: list[DependencyRow]
    exclusions: list[ExclusionRow]
    overlaps: list[OverlapRow]
    identities: list[IdentityRow]
    thread_identity_mappings: list[ThreadMappingRow]
    catalog_series: list[CatalogSeriesRow]
    catalog_issues: list[CatalogIssueRow]
    inert_generated_dependencies: GeneratedDependencyCensus


class XmenStep(TypedDict):
    """Specific reader-approved X-Men progression and forbidden offers."""

    read: int
    blocked: NotRequired[list[int]]
    unblocks: list[int]
    still_blocked: list[int]


class XmenSequence(TypedDict):
    """Approved successive Uncanny/X-Men crossover handoffs."""

    source: str
    steps: list[XmenStep]


class UltimateSequence(TypedDict):
    """Approved loose-list handoff after sequential Black Panther issues."""

    source: str
    read: int
    target: int
    progress_to_handoff: list[int]


class FantasticFourStep(TypedDict):
    """Approved FF/Fantastic Four interleaving step."""

    read: int
    before_blocked: list[int]
    unblocks: list[int]
    after_blocked: list[int]


class FantasticFourSequence(TypedDict):
    """Approved FF/Fantastic Four progression."""

    source: str
    steps: list[FantasticFourStep]


class ApprovedSequences(TypedDict):
    """Sequences authored independently from the runtime eligibility engine."""

    xmen_1998: XmenSequence
    ultimate_2025: UltimateSequence
    fantastic_four: FantasticFourSequence


class UnresolvedReaderIntent(TypedDict):
    """Required reconciliation census; historical contradiction text blocks signoff."""

    strict_partial_membership_needing_classification: int
    reading_list_vs_reading_plan_discrepancies_needing_classification: int
    historical_contradictions: int | str


class SourceDecision(TypedDict):
    """Independent reconciliation receipt for a disputed source decision."""

    source: str
    discrepancy: str
    decision: str
    reviewed_by: str


class ProductionReadingContract(TypedDict):
    """Reader-intent oracle, fingerprint, and explicit unresolved census."""

    version: int
    authority: str
    approved_sequences: ApprovedSequences
    unresolved_reader_intent: UnresolvedReaderIntent
    fixture_git_blob_sha: str
    reader_intent_signoff: str
    reviewed_source_decisions: list[SourceDecision]
