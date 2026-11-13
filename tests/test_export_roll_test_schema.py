"""Normalization for the native Roll Alembic schema fixture."""

from scripts.export_roll_test_schema import (
    _normalize,
    _normalize_catalog,
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


def test_normalize_strips_postgres18_attribute_version_markers() -> None:
    """PostgreSQL 18 pg_dump attribute-version markers never reach the fixture."""
    raw = (
        "CREATE TABLE public.alembic_version (\n"
        "    version_num character varying(32) NOT NULL\n"
        ");\n"
        "ALTER TABLE ONLY public.alembic_version "
        "ALTER COLUMN version_num SET (pg_attver=26796624);\n"
        "ALTER TABLE ONLY public.issues "
        'ALTER COLUMN "position" SET (pg_attver=28926072);\n'
        "ALTER TABLE ONLY public.threads "
        "ADD CONSTRAINT ck_threads_status CHECK ((status = ANY (ARRAY['active'])));\n"
    )

    normalized = _normalize(raw)

    assert "pg_attver" not in normalized
    assert "CREATE TABLE public.alembic_version" in normalized
    assert "ck_threads_status" in normalized
    assert normalized.endswith("\n")


def test_normalize_catalog_strips_postgres18_attribute_version_markers() -> None:
    """The order-insensitive comparison ignores attribute-version markers."""
    raw = (
        "ALTER TABLE ONLY public.alembic_version "
        "ALTER COLUMN version_num SET (pg_attver=26796624);\n"
        "CREATE TABLE public.alembic_version (\n"
        "    version_num character varying(32) NOT NULL\n"
        ");\n"
    )

    normalized = _normalize_catalog(raw)

    assert "pg_attver" not in normalized
    assert "CREATE TABLE public.alembic_version" in normalized
