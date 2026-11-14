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


def test_normalize_discards_only_internal_attribute_version_assignments() -> None:
    """Catalog versions vary between dumps; actual column options remain visible."""
    schema = "CREATE TABLE public.demo (label text);\n"
    first = (
        schema
        + "ALTER TABLE ONLY public.demo ALTER COLUMN label SET (pg_attver=123);\n"
        + 'ALTER TABLE ONLY "public"."demo" ALTER COLUMN "label" SET (pg_attver=456);\n'
    )
    second = first.replace("123", "789").replace("456", "987")
    assert _normalize(first) == _normalize(second) == schema
    assert _normalize(_normalize(first)) == schema

    meaningful = (
        "ALTER TABLE ONLY public.demo ALTER COLUMN label SET (n_distinct=123);\n"
        "ALTER TABLE ONLY public.demo ALTER COLUMN label SET (pg_attver=123, n_distinct=2);\n"
        "ALTER TABLE ONLY public.demo ALTER COLUMN label SET DEFAULT 'pg_attver=123';\n"
        "COMMENT ON COLUMN public.demo.label IS 'pg_attver=123';\n"
    )
    assert _normalize(meaningful) == meaningful


def test_normalize_preserves_attribute_version_text_inside_quoted_sql() -> None:
    """Returned SQL and multiline literals remain meaningful schema content."""
    body = (
        "CREATE FUNCTION public.example() RETURNS text LANGUAGE sql AS $body$\n"
        "SELECT $query$\n"
        "ALTER TABLE ONLY public.demo ALTER COLUMN label SET (pg_attver=123);\n"
        "$query$;\n"
        "$body$;\n"
        "COMMENT ON TABLE public.demo IS 'example:\n"
        "ALTER TABLE ONLY public.demo ALTER COLUMN label SET (pg_attver=123);\n"
        "end';\n"
    )
    metadata = "ALTER TABLE ONLY public.demo ALTER COLUMN label SET (pg_attver=123);\n"
    assert _normalize(body) == body
    assert _normalize(metadata + body) == body
    assert _normalize(body + metadata) == body
    assert _normalize(body.replace("123", "456")) != _normalize(body)
