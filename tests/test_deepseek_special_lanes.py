"""Pin invariants for the DeepSeek Free anonymous/authenticated factory experiment."""
from pathlib import Path
import json

def test_deepseek_special_lane_pins() -> None:
    """Verify all four workers retain their intended free model and auth grouping."""
    lines = Path(".github/free-model-factories.tsv").read_text().splitlines()
    rows = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if parts[0] in {"87", "88", "89", "90"}:
            rows[int(parts[0])] = parts
    assert set(rows) == {87, 88, 89, 90}
    assert {87, 89} == {n for n, row in rows.items() if "Anonymous" in row[5]}
    assert {88, 90} == {n for n, row in rows.items() if "Authenticated" in row[5]}
    assert all(row[1:3] == ["opencode-free", "deepseek-v4.1-flash-free"] for row in rows.values())
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    assert set(rows).issubset(set(lock["expected_workers"]))

def test_special_pins_bypass_dynamic_rotation_and_are_strict() -> None:
    """Require exact-model selection, credential handling, and tool probing."""
    run = Path(".github/workflows/free-model-factory-run.yml").read_text()
    assert "87|89) deepseek_mode=anonymous" in run
    assert "88|90) deepseek_mode=authenticated" in run
    assert 'missing-OpenCode-credential' in run
    assert 'EXISTING_OPENCODE_KEY: ${{ secrets.OPENCODE_API_KEY || secrets.OPENCODE_ZEN_API_KEY }}' in run
    assert 'OPENCODE_API_KEY=%s' in run
    assert 'steps.lane.outputs.deepseek_mode == \'authenticated\'' in run
    assert '"$source" == opencode-free && "$model" == deepseek-v4.1-flash-free' in run
    assert "rotation disabled" in run
    assert "Pinned free DeepSeek absent from OpenCode catalog" in run
    assert "DEEPSEEK_LANE_TOOL_OK" in run
    assert "if [[ \"$DEEPSEEK_MODE\" != normal && \"$status\" -ne 0 ]]" in run
