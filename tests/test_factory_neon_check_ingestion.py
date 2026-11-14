"""Guard trusted CI-to-Neon ingestion against a falsely green no-op."""
import importlib
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github/scripts"))
operations = importlib.import_module("factory_state_operations")

def test_check_ingest_requires_a_restricted_connection(monkeypatch):
    monkeypatch.delenv("FACTORY_STATE_DSN_FILE", raising=False)
    with pytest.raises(RuntimeError, match="requires restricted Neon"):
        operations.ingest_check("JoshCLWren/comic-pile", {"workflow_run": {}})

def test_workflow_resolves_both_credentials_and_fails_closed():
    workflow = (ROOT / ".github/workflows/factory-check-projection.yml").read_text()
    assert "neon-api-key: ${{ secrets.NEON_API_KEY }}" in workflow
    assert "neon-project-id: ${{ vars.NEON_PROJECT_ID }}" in workflow
    assert r"\${{" not in workflow
    assert '[[ -z "${FACTORY_STATE_DSN_FILE:-}" || ! -s "$FACTORY_STATE_DSN_FILE" ]]' in workflow
    assert "ref: main" in workflow and "persist-credentials: false" in workflow

def test_duplicate_check_delivery_does_not_rewrite_or_wake():
    import inspect
    sql_source = inspect.getsource(operations._ingest_check)
    assert "factory_check_projection.run_id<EXCLUDED.run_id" in sql_source
    assert "factory_check_projection.conclusion IS DISTINCT FROM EXCLUDED.conclusion" in sql_source
    assert "RETURNING 1" in sql_source
    assert "if changed:" in sql_source
