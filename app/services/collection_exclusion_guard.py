"""Identity-based collection exclusions shared by import preview and commit."""

from collections.abc import Sequence
from dataclasses import dataclass, field
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import collection_exclusion_repository as exclusions
from app.repositories import collection_guard_repository as repository


@dataclass(frozen=True)
class CollectionGuardDecision:
    """An exclusion or missing identity that cannot be overridden by an include."""

    reason: str
    exclusion_ids: tuple[int, ...] = ()


@dataclass
class CollectionGuard:
    """One owner's explicit decisions and batched identity evidence."""

    volumes: dict[tuple[str, str], int] = field(default_factory=dict)
    threads: dict[int, int] = field(default_factory=dict)
    issues: dict[int, int] = field(default_factory=dict)
    issue_threads: dict[int, int] = field(default_factory=dict)
    identity_volumes: dict[int, set[tuple[str, str]]] = field(default_factory=dict)
    thread_identities: dict[int, set[tuple[str, str]]] = field(default_factory=dict)
    issue_volumes: dict[int, set[tuple[str, str]]] = field(default_factory=dict)
    series_threads: dict[int, set[int]] = field(default_factory=dict)
    issue_targets: dict[int, set[int]] = field(default_factory=dict)

    def _local_decision(self, fact: dict[str, object]) -> CollectionGuardDecision | None:
        """Resolve owned Issue and Thread targets the source entry would land in."""
        issue_id = fact.get("resolved_issue_id")
        thread_id = fact.get("thread_id")
        if isinstance(issue_id, int):
            if issue_id in self.issues:
                return CollectionGuardDecision(
                    "collection_issue_excluded", (self.issues[issue_id],)
                )
            thread_id = self.issue_threads.get(issue_id, thread_id)
        if isinstance(thread_id, int) and thread_id in self.threads:
            return CollectionGuardDecision("collection_thread_excluded", (self.threads[thread_id],))
        issue_identity_id = fact.get("external_issue_identity_id")
        if isinstance(issue_identity_id, int):
            for target in self.issue_targets.get(issue_identity_id, ()):
                if target in self.issues:
                    return CollectionGuardDecision(
                        "collection_issue_excluded", (self.issues[target],)
                    )
                target_thread = self.issue_threads.get(target)
                if target_thread is not None and target_thread in self.threads:
                    return CollectionGuardDecision(
                        "collection_thread_excluded", (self.threads[target_thread],)
                    )
        series_identity_id = fact.get("external_series_identity_id")
        if isinstance(series_identity_id, int):
            for target in self.series_threads.get(series_identity_id, ()):
                if target in self.threads:
                    return CollectionGuardDecision(
                        "collection_thread_excluded", (self.threads[target],)
                    )
        return None

    def check(self, fact: dict[str, object]) -> CollectionGuardDecision | None:
        """Fail closed on excluded or ambiguous material without using its title."""
        if not (self.volumes or self.threads or self.issues):
            return None
        if local := self._local_decision(fact):
            return local
        issue_id = fact.get("resolved_issue_id")
        thread_id = fact.get("thread_id")
        candidates: set[tuple[str, str]] = set()
        for key in ("external_series_identity_id", "external_issue_identity_id"):
            identity_id = fact.get(key)
            if isinstance(identity_id, int):
                candidates.update(self.identity_volumes.get(identity_id, ()))
        for key in ("comicvine_series_id", "volume_id"):
            value = fact.get(key)
            if isinstance(value, (str, int)):
                candidates.add(normalize_volume("comicvine", str(value)))
        provider = fact.get("series_provider")
        external_id = fact.get("series_external_id")
        if isinstance(provider, str) and isinstance(external_id, (str, int)):
            candidates.add(normalize_volume(provider, str(external_id)))
        if isinstance(thread_id, int):
            candidates.update(self.thread_identities.get(thread_id, ()))
        if isinstance(issue_id, int):
            candidates.update(self.issue_volumes.get(issue_id, ()))
        matched = tuple(sorted({self.volumes[key] for key in candidates if key in self.volumes}))
        if matched:
            return CollectionGuardDecision("collection_volume_excluded", matched)
        # If an owner excludes external volumes, missing or conflicting volume
        # identity is not evidence that prospective material is safe to adopt.
        missing_provider = {provider for provider, _ in self.volumes} - {
            provider for provider, _ in candidates
        }
        malformed = any(
            provider == "comicvine" and not value.isdecimal() for provider, value in candidates
        )
        if self.volumes and (
            not candidates or len(candidates) > 1 or missing_provider or malformed
        ):
            return CollectionGuardDecision("collection_identity_requires_review")
        return None


def normalize_volume(provider: str, external_id: str) -> tuple[str, str]:
    """Normalize ComicVine's numeric and 4050-prefixed forms, never series names."""
    provider = provider.strip().casefold()
    value = external_id.strip()
    match = re.fullmatch(r"(?:4050-)?([0-9]+)", value) if provider == "comicvine" else None
    return provider, str(int(match.group(1))) if match else value


def _metadata_volumes(provider: str, metadata: object) -> set[tuple[str, str]]:
    """Read stable volume identity in supported provider metadata shapes."""
    if not isinstance(metadata, dict):
        return set()
    values = [metadata.get("volume_id")]
    volume = metadata.get("volume")
    if isinstance(volume, dict):
        values.append(volume.get("id"))
    return {
        normalize_volume(provider, str(value))
        for value in values
        if isinstance(value, (str, int)) and str(value).strip()
    }


async def load_collection_guard(
    db: AsyncSession,
    user_id: int,
    facts: Sequence[dict[str, object]],
) -> CollectionGuard:
    """Load exclusions and relevant identities once for a prospective import batch.

    Callers hold the reader lock for writes; preview does not acquire a lock.
    Evidence comes from provider IDs and confirmed/catalog mappings, never names.
    """
    guard = CollectionGuard()
    for row in await exclusions.list_for_owner(db, user_id):
        if row.provider is not None and row.external_volume_id is not None:
            guard.volumes[normalize_volume(row.provider, row.external_volume_id)] = row.id
        if row.thread_id is not None:
            guard.threads[row.thread_id] = row.id
        if row.issue_id is not None:
            guard.issues[row.issue_id] = row.id
    if not (guard.volumes or guard.threads or guard.issues):
        return guard
    identity_ids = {
        value
        for fact in facts
        for key in ("external_series_identity_id", "external_issue_identity_id")
        if isinstance(value := fact.get(key), int)
    }
    guard.series_threads = await repository.series_threads(db, user_id, identity_ids)
    guard.issue_targets = await repository.confirmed_issues(db, user_id, identity_ids)
    for identity in await repository.identities(db, identity_ids):
        values = (
            _metadata_volumes(identity.provider, identity.metadata_json)
            if identity.entity_type == "issue"
            else {normalize_volume(identity.provider, identity.external_id)}
        )
        guard.identity_volumes[identity.id] = values
    issue_ids = {value for fact in facts if isinstance(value := fact.get("resolved_issue_id"), int)}
    reused_issue_ids = {
        issue_id for targets in guard.issue_targets.values() for issue_id in targets
    }
    guard.issue_threads = await repository.owned_issue_threads(
        db, user_id, issue_ids | reused_issue_ids
    )
    thread_ids = {value for fact in facts if isinstance(value := fact.get("thread_id"), int)}
    thread_ids.update(guard.issue_threads.values())
    for thread_id, provider, external_id in await repository.thread_volumes(
        db, user_id, thread_ids
    ):
        guard.thread_identities.setdefault(thread_id, set()).add(
            normalize_volume(provider, external_id)
        )
    for issue_id, identity in await repository.issue_identities(db, user_id, issue_ids):
        guard.issue_volumes.setdefault(issue_id, set()).update(
            _metadata_volumes(identity.provider, identity.metadata_json)
        )
    for issue_id, provider, external_id in await repository.catalog_issue_volumes(
        db, user_id, issue_ids
    ):
        guard.issue_volumes.setdefault(issue_id, set()).add(normalize_volume(provider, external_id))
    return guard


async def annotate_collection_exclusions(
    db: AsyncSession,
    user_id: int,
    facts: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    """Preserve every source position while marking material unavailable for adoption."""
    guard = await load_collection_guard(db, user_id, facts)
    result = []
    for fact in facts:
        entry = dict(fact)
        decision = guard.check(entry)
        entry["collection_excluded"] = decision is not None
        entry["collection_exclusion_reason"] = decision.reason if decision else None
        entry["collection_exclusion_ids"] = list(decision.exclusion_ids) if decision else []
        result.append(entry)
    return result
