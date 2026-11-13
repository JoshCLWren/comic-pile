"""Normalization for the native Roll Alembic schema fixture."""

from scripts.export_roll_test_schema import (
    _normalize,
    _qualify_extension_operator_classes,
)


def test_qualify_extension_operator_classes_is_idempotent() -> None:
    """Bare gin_trgm_ops becomes public.gin_trgm_ops; already-qualified names stay."""
    unqualified = (
        "CREATE INDEX ix_cbl_source_list_source_path_trgm "
        "ON public.cbl_source_lists USING gin (source_path gin_trgm_ops);\n"
    )
    qualified = (
        "CREATE INDEX ix_cbl_source_list_source_path_trgm "
        "ON public.cbl_source_lists USING gin (source_path public.gin_trgm_ops);\n"
    )

    assert _qualify_extension_operator_classes(unqualified) == qualified
    assert _qualify_extension_operator_classes(qualified) == qualified


def test_normalize_qualifies_trigram_ops_and_strips_dump_banners() -> None:
    """Replayable fixture: empty search_path plus a public-qualified opclass."""
    raw = (
        "-- Dumped from database version 16.4\n"
        "-- Dumped by pg_dump version 16.4\n"
        "\\restrict abc\n"
        "SET transaction_timeout = 0;\n"
        "CREATE SCHEMA public;\n"
        "SELECT pg_catalog.set_config('search_path', '', false);\n"
        "CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;\n"
        "CREATE INDEX ix_cbl_source_list_name_trgm "
        "ON public.cbl_source_lists USING gin (name gin_trgm_ops);\n"
        "CREATE INDEX ix_cbl_source_list_source_path_trgm "
        "ON public.cbl_source_lists USING gin (source_path public.gin_trgm_ops);\n"
        "\\unrestrict abc\n"
    )

    normalized = _normalize(raw)

    assert "-- Dumped from database version" not in normalized
    assert "\\restrict" not in normalized
    assert "SET transaction_timeout" not in normalized
    assert "CREATE SCHEMA public;" not in normalized
    assert "SELECT pg_catalog.set_config('search_path', '', false);" in normalized
    assert "USING gin (name public.gin_trgm_ops)" in normalized
    assert "USING gin (source_path public.gin_trgm_ops)" in normalized
    assert " gin_trgm_ops)" not in normalized.replace("public.gin_trgm_ops)", "")
    assert normalized.endswith("\n")
    assert not normalized.endswith("\n\n")


def test_normalize_drops_client_version_column_markers() -> None:
    """Newer pg_dump `pg_attver` markers are metadata, not schema drift."""
    raw = (
        "CREATE TABLE public.alembic_version (\n"
        "    version_num character varying(32) NOT NULL\n"
        ");\n"
        "ALTER TABLE ONLY public.alembic_version "
        "ALTER COLUMN version_num SET (pg_attver=26796624);\n"
        "ALTER TABLE public.events "
        "ALTER COLUMN die SET (n_distinct=5);\n"
    )

    normalized = _normalize(raw)

    assert "pg_attver" not in normalized
    # Real column options still survive normalization.
    assert "ALTER COLUMN die SET (n_distinct=5);" in normalized
