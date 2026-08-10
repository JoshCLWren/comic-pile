"""Read-only access to a developer-local ComicVine SQLite snapshot."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

LOCAL_COMICVINE_DB_ENV = "COMICPILE_COMICVINE_SQLITE_PATH"


@dataclass(frozen=True)
class LocalComicVineResult:
    """Normalized result from the local ComicVine snapshot."""

    data: dict[str, object]
    provenance: str = "comicvine-local-sqlite"
    complete: bool = True


class LocalComicVineSnapshot:
    """Read a local ComicVine SQLite cache without mutating it."""

    def __init__(self, path: str | Path | None = None) -> None:
        """Configure the optional local snapshot path."""
        configured = path or os.getenv(LOCAL_COMICVINE_DB_ENV)
        self.path = Path(configured).expanduser() if configured else None

    @property
    def available(self) -> bool:
        """Return whether the configured snapshot exists."""
        return self.path is not None and self.path.is_file()

    def _connect(self) -> sqlite3.Connection:
        if not self.available or self.path is None:
            raise FileNotFoundError("Local ComicVine snapshot is not configured or does not exist")
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _decode_value(value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped or stripped[0] not in "[{":
            return value
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return value

    @classmethod
    def _normalize_row(cls, row: sqlite3.Row) -> dict[str, object]:
        return {key: cls._decode_value(row[key]) for key in row.keys()}

    def _lookup(
        self,
        table: str,
        external_id: int,
        required: tuple[str, ...],
    ) -> LocalComicVineResult | None:
        if not self.available:
            return None
        with self._connect() as connection:
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            id_candidates = (
                "id",
                "comicvine_id",
                f"{table.removeprefix('cv_')}_id",
            )
            id_column = next(
                (candidate for candidate in id_candidates if candidate in columns),
                None,
            )
            if id_column is None:
                return None
            row = connection.execute(
                f"SELECT * FROM {table} WHERE {id_column} = ? LIMIT 1",
                (external_id,),
            ).fetchone()
        if row is None:
            return None
        data = self._normalize_row(row)
        complete = all(data.get(field) not in (None, "") for field in required)
        return LocalComicVineResult(data=data, complete=complete)

    def get_volume(self, volume_id: int) -> LocalComicVineResult | None:
        """Look up one volume by ComicVine ID."""
        return self._lookup("cv_volume", volume_id, ("name",))

    def get_issue(self, issue_id: int) -> LocalComicVineResult | None:
        """Look up one issue by ComicVine ID, including decoded relationship JSON."""
        return self._lookup("cv_issue", issue_id, ("volume_id", "issue_number"))

    def get_volume_issues(self, volume_id: int) -> list[LocalComicVineResult]:
        """Return every locally cached issue in one ComicVine volume.

        Args:
            volume_id: ComicVine volume identity.

        Returns:
            Issue rows in stable numeric-ID order, or an empty list when unavailable.
        """
        if not self.available:
            return []
        with self._connect() as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(cv_issue)")}
            if "volume_id" not in columns:
                return []
            order_column = "id" if "id" in columns else "issue_number"
            rows = connection.execute(
                f"SELECT * FROM cv_issue WHERE volume_id = ? ORDER BY {order_column}",
                (volume_id,),
            ).fetchall()
        return [
            LocalComicVineResult(data=self._normalize_row(row), complete=True)
            for row in rows
        ]

    def search_volumes(self, query: str, *, limit: int = 10) -> list[LocalComicVineResult]:
        """Return ranked local candidates without treating rank as identity confirmation."""
        if not self.available or not query.strip() or limit <= 0:
            return []
        with self._connect() as connection:
            fts_tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name LIKE 'cv_volume%fts%'"
                )
            ]
            if not fts_tables:
                return []
            table = fts_tables[0]
            rows = connection.execute(
                f"SELECT rowid AS id, *, bm25({table}) AS rank FROM {table} "
                f"WHERE {table} MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
        return [
            LocalComicVineResult(data=self._normalize_row(row), complete=False)
            for row in rows
        ]

    def sync_metadata(self) -> dict[str, object]:
        """Expose snapshot freshness metadata when the snapshot provides it."""
        if not self.available:
            return {}
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='cv_sync_metadata'"
            ).fetchone()
            if exists is None:
                return {}
            rows = connection.execute("SELECT * FROM cv_sync_metadata").fetchall()
        return {str(index): self._normalize_row(row) for index, row in enumerate(rows)}

    def get_issue_or_fallback(
        self,
        issue_id: int,
        fallback: Callable[[int], Mapping[str, object]],
    ) -> LocalComicVineResult:
        """Prefer a complete local issue; use the live provider only for a miss/incomplete row."""
        local = self.get_issue(issue_id)
        if local is not None and local.complete:
            return local
        return LocalComicVineResult(data=dict(fallback(issue_id)), provenance="comicvine-live")
