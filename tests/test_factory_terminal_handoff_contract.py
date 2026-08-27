"""Regression contracts for trusted fixed-model terminal handoffs."""

from pathlib import Path


WORKER = Path('.github/scripts/free-model-factory-worker.sh')


def _worker_text() -> str:
    """Return the trusted fixed-model worker source."""
    return WORKER.read_text(encoding='utf-8')


def test_fixed_model_prompt_reserves_merge_and_close_for_controller() -> None:
    """Review agents must not race the trusted controller by merging directly."""
    text = _worker_text()

    assert 'Do not merge or close the assigned pull request' in text
    assert 'the trusted wrapper and review controller own the final lifecycle transition' in text


def test_already_merged_reviewed_head_is_a_successful_terminal_result() -> None:
    """A PR merged during agent execution must not crash review-controller handoff."""
    text = _worker_text()

    assert 'if [[ -n "$merged_at" ]]' in text
    assert '[[ "$observed_head" == "$EXPECTED_HEAD" ]]' in text
    assert 'factory_work_result_merged:' in text
    assert 'record_terminal_outcome success "PR #${NUMBER} merged at the reviewed head during worker execution"' in text
    assert 'skipping review controller' in text


def test_worker_emits_only_canonical_terminal_outcomes() -> None:
    """Trusted synchronous evidence must use the incident taxonomy."""
    text = _worker_text()

    assert (
        'success|no_work|work_failure|provider_failure|provider_throttle|model_unavailable|'
        'model_policy_violation|environment_failure|control_plane_failure|unknown_failure'
    ) in text
    assert 'TERMINAL_OUTCOME_FILE="${RUNNER_TEMP:-/tmp}/factory-discovery-outcome"' in text


def test_timed_pinned_session_is_provider_failure_after_smoke() -> None:
    """A Kilo/OpenCode session timeout must not collapse to unknown_failure."""
    text = _worker_text()

    assert 'status == 124 || status == 137 || status == 143' in text
    assert (
        'record_terminal_outcome provider_failure '
        '"pinned provider/model session timed out or was interrupted after smoke succeeded'
    ) in text


def test_throttle_and_model_missing_remain_distinct() -> None:
    """Rate limiting and model retirement have different health scopes."""
    text = _worker_text()

    assert 'record_terminal_outcome provider_throttle' in text
    assert 'record_terminal_outcome model_unavailable' in text
    assert 'HTTP[^0-9]*(404|410)' in text


def test_review_controller_failure_is_control_plane_failure() -> None:
    """A trusted controller exception must not be attributed to the model/provider."""
    text = _worker_text()

    assert 'controller_status=$?' in text
    assert (
        'record_terminal_outcome control_plane_failure '
        '"trusted review controller failed for PR #${NUMBER} with exit status ${controller_status}"'
    ) in text
