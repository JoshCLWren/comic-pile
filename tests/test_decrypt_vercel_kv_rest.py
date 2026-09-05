"""Unit tests for production Vercel KV REST decrypt helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.benchmark_cache_latency import load_dotenv_values
from scripts.decrypt_vercel_kv_rest import (
    KV_READ_ONLY_TOKEN_KEY,
    KV_TOKEN_KEY,
    KV_URL_KEY,
    choose_kv_credentials,
    collect_usable_values,
    coverage_payload,
    decrypt_production_kv_rest,
    env_targets_production,
    is_usable_secret,
    select_production_env_ids,
    write_kv_dotenv,
)


def test_is_usable_secret_rejects_placeholders() -> None:
    """CLI pull placeholders must not be treated as credentials."""
    assert is_usable_secret(None) is False
    assert is_usable_secret("") is False
    assert is_usable_secret("   ") is False
    assert is_usable_secret("[SENSITIVE]") is False
    assert is_usable_secret("https://example.upstash.io") is True


def test_env_targets_production_accepts_list_and_legacy_unset() -> None:
    """Production-targeted records are selected; preview-only records are not."""
    assert env_targets_production({}) is True
    assert env_targets_production({"target": ["production", "preview"]}) is True
    assert env_targets_production({"target": "production"}) is True
    assert env_targets_production({"target": ["preview"]}) is False


def test_select_production_env_ids_ignores_redis_url() -> None:
    """``REDIS_URL`` is the RESP path and must never be selected."""
    envs: list[dict[str, object]] = [
        {"key": KV_URL_KEY, "id": "env_url", "target": ["production"]},
        {"key": KV_TOKEN_KEY, "id": "env_token", "target": ["production"]},
        {"key": "REDIS_URL", "id": "env_redis", "target": ["production"]},
        {"key": KV_READ_ONLY_TOKEN_KEY, "id": "env_ro", "target": ["preview"]},
    ]

    selected = select_production_env_ids(envs)

    assert selected == {KV_URL_KEY: "env_url", KV_TOKEN_KEY: "env_token"}


def test_collect_usable_values_skips_sensitive_placeholders() -> None:
    """List-decrypt payloads that still redact must yield no usable token."""
    envs: list[dict[str, object]] = [
        {
            "key": KV_URL_KEY,
            "value": "https://example.upstash.io",
            "target": ["production"],
        },
        {"key": KV_TOKEN_KEY, "value": "[SENSITIVE]", "target": ["production"]},
        {"key": "REDIS_URL", "value": "redis://localhost:6379", "target": ["production"]},
    ]

    values = collect_usable_values(envs)

    assert values == {KV_URL_KEY: "https://example.upstash.io"}


def test_choose_kv_credentials_prefers_read_write_token() -> None:
    """Read-write ``KV_REST_API_TOKEN`` wins over the GET-only fallback."""
    url, token, source = choose_kv_credentials(
        {
            KV_URL_KEY: "https://example.upstash.io",
            KV_TOKEN_KEY: "write-token",
            KV_READ_ONLY_TOKEN_KEY: "readonly-token",
        }
    )

    assert url == "https://example.upstash.io"
    assert token == "write-token"
    assert source == KV_TOKEN_KEY


def test_choose_kv_credentials_falls_back_to_read_only_token() -> None:
    """GET-only latency can use ``KV_REST_API_READ_ONLY_TOKEN``."""
    url, token, source = choose_kv_credentials(
        {
            KV_URL_KEY: "https://example.upstash.io",
            KV_READ_ONLY_TOKEN_KEY: "readonly-token",
        }
    )

    assert url == "https://example.upstash.io"
    assert token == "readonly-token"
    assert source == KV_READ_ONLY_TOKEN_KEY


def test_write_kv_dotenv_round_trips_through_benchmark_loader(tmp_path: Path) -> None:
    """The runner-local file must reload as the KV aliases the benchmark maps."""
    path = tmp_path / "vercel-kv-rest.env"
    write_kv_dotenv(path, "https://example.upstash.io", "write-token")

    values = load_dotenv_values(str(path))

    assert values[KV_URL_KEY] == "https://example.upstash.io"
    assert values[KV_TOKEN_KEY] == "write-token"
    assert "REDIS_URL" not in values
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_coverage_payload_never_includes_secret_values() -> None:
    """Coverage JSON is safe to log and attach as an artifact."""
    payload = coverage_payload(
        ["DATABASE_URL", KV_TOKEN_KEY, KV_URL_KEY, "REDIS_URL"],
        "https://secret.upstash.io",
        "super-secret-token",
        KV_TOKEN_KEY,
        "project_env_by_id",
    )

    rendered = str(payload)
    assert "super-secret-token" not in rendered
    assert "secret.upstash.io" not in rendered
    assert payload["kv_rest_api_url_present"] is True
    assert payload["kv_rest_api_token_present"] is True
    assert payload["kv_token_source"] == KV_TOKEN_KEY
    assert payload["redis_url_ignored"] is True


def test_decrypt_production_kv_rest_uses_per_id_when_list_is_redacted() -> None:
    """Per-id decrypt supplies real values after a redacted list-decrypt."""
    listed: list[dict[str, object]] = [
        {"key": KV_URL_KEY, "id": "env_url", "target": ["production"]},
        {"key": KV_TOKEN_KEY, "id": "env_token", "target": ["production"]},
        {"key": "REDIS_URL", "id": "env_redis", "target": ["production"]},
    ]
    redacted: list[dict[str, object]] = [
        {**listed[0], "value": "[SENSITIVE]"},
        {**listed[1], "value": "[SENSITIVE]"},
        {**listed[2], "value": "redis://localhost:6379"},
    ]
    by_id = {
        "env_url": "https://example.upstash.io",
        "env_token": "write-token",
    }

    def fake_list(
        _token: str,
        _project_id: str,
        _team_id: str,
        *,
        decrypt: bool,
    ) -> list[dict[str, object]]:
        return redacted if decrypt else listed

    def fake_by_id(
        _token: str,
        _project_id: str,
        _team_id: str,
        env_id: str,
    ) -> str | None:
        return by_id.get(env_id)

    with (
        patch("scripts.decrypt_vercel_kv_rest.list_project_envs", side_effect=fake_list),
        patch("scripts.decrypt_vercel_kv_rest.decrypt_env_by_id", side_effect=fake_by_id),
    ):
        url, token, source, method, keys = decrypt_production_kv_rest(
            "vercel-token",
            "prj_test",
            "team_test",
        )

    assert url == "https://example.upstash.io"
    assert token == "write-token"
    assert source == KV_TOKEN_KEY
    assert method == "project_env_by_id"
    assert KV_URL_KEY in keys
    assert "REDIS_URL" in keys


def test_decrypt_production_kv_rest_uses_list_decrypt_when_values_are_real() -> None:
    """A decrypted list payload should not make extra per-id calls."""
    records = [
        {
            "key": KV_URL_KEY,
            "id": "env_url",
            "value": "https://example.upstash.io",
            "target": ["production"],
        },
        {
            "key": KV_TOKEN_KEY,
            "id": "env_token",
            "value": "write-token",
            "target": ["production"],
        },
    ]

    with (
        patch(
            "scripts.decrypt_vercel_kv_rest.list_project_envs",
            return_value=records,
        ) as list_mock,
        patch("scripts.decrypt_vercel_kv_rest.decrypt_env_by_id") as by_id_mock,
    ):
        url, token, source, method, _keys = decrypt_production_kv_rest(
            "vercel-token",
            "prj_test",
            "team_test",
        )

    assert url == "https://example.upstash.io"
    assert token == "write-token"
    assert source == KV_TOKEN_KEY
    assert method == "list_decrypt"
    assert list_mock.call_count == 2
    by_id_mock.assert_not_called()


def test_choose_kv_credentials_rejects_sensitive_write_token() -> None:
    """A redacted write token must not hide a usable read-only token."""
    url, token, source = choose_kv_credentials(
        {
            KV_URL_KEY: "https://example.upstash.io",
            KV_TOKEN_KEY: "[SENSITIVE]",
            KV_READ_ONLY_TOKEN_KEY: "readonly-token",
        }
    )

    assert url == "https://example.upstash.io"
    assert token == "readonly-token"
    assert source == KV_READ_ONLY_TOKEN_KEY
