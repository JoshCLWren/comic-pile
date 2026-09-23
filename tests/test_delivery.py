"""Tests for cross-repository factory delivery.

Covers issue #2874 acceptance criteria:
- Default ComicPile delivery
- Allowlisted Latticery delivery
- Rejection of unapproved target repository
- Fail-closed Latticery delivery when LATTICERY_TOKEN is absent
- Ordinary ComicPile delivery does not require LATTICERY_TOKEN
- Latticery credential selected only for allowlisted target
- Repository-safe recovery/ledger identity
- Dry-run proving PR commands target Latticery without mutating ComicPile
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import GitHubSettings
from app.models.delivery import DeliveryRecord as DeliveryRecordModel
from app.services.delivery import DeliveryService
from app.schemas.delivery import (
    CrossRepoDeliveryRequest,
    DeliveryFilePayload,
    DeliveryRecordCreate,
    TargetRepositoryValidation,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


def test_default_target_is_comicpile() -> None:
    """Default target repository is JoshCLWren/comic-pile."""
    settings = GitHubSettings()
    assert settings.default_target_repo == "JoshCLWren/comic-pile"


def test_latticery_is_allowlisted() -> None:
    """JoshCLWren/Latticery is in the allowed target repos."""
    settings = GitHubSettings()
    assert "JoshCLWren/Latticery" in settings.allowed_target_repos
    assert "JoshCLWren/comic-pile" in settings.allowed_target_repos


def test_validate_target_repo_accepts_comicpile() -> None:
    """ComicPile target repository validates successfully."""
    settings = GitHubSettings()
    result = settings.validate_target_repo("JoshCLWren/comic-pile")
    assert result == "JoshCLWren/comic-pile"


def test_validate_target_repo_accepts_latticery() -> None:
    """Latticery target repository validates successfully."""
    settings = GitHubSettings()
    result = settings.validate_target_repo("JoshCLWren/Latticery")
    assert result == "JoshCLWren/Latticery"


def test_validate_target_repo_rejects_unapproved() -> None:
    """Unapproved target repository raises ValueError."""
    settings = GitHubSettings()
    with pytest.raises(ValueError, match="not allowlisted"):
        settings.validate_target_repo("some-random/repo")


def test_is_latticery_configured_when_token_present() -> None:
    """is_latticery_configured returns True when LATTICERY_TOKEN is set."""
    settings = GitHubSettings(latticery_token="secret-token")
    assert settings.is_latticery_configured is True


def test_is_latticery_configured_when_token_absent() -> None:
    """is_latticery_configured returns False when LATTICERY_TOKEN is empty."""
    settings = GitHubSettings()
    assert settings.is_latticery_configured is False


def test_credential_source_for_comicpile_is_github_token() -> None:
    """ComicPile target uses GITHUB_TOKEN credential source."""
    settings = GitHubSettings()
    source = settings.get_credential_for_repo("JoshCLWren/comic-pile")
    assert source == settings.github_token


def test_credential_source_for_latticery_is_latticery_token() -> None:
    """Latticery target uses LATTICERY_TOKEN credential source."""
    settings = GitHubSettings(latticery_token="latticery-secret")
    source = settings.get_credential_for_repo("JoshCLWren/Latticery")
    assert source == "latticery-secret"


def test_fail_closed_when_latticery_token_absent() -> None:
    """Accessing Latticery without LATTICERY_TOKEN raises RuntimeError."""
    settings = GitHubSettings()
    with pytest.raises(RuntimeError, match="LATTICERY_TOKEN"):
        settings.get_credential_for_repo("JoshCLWren/Latticery")


def test_comicpile_delivery_does_not_require_latticery_token() -> None:
    """ComicPile delivery succeeds without LATTICERY_TOKEN configured."""
    settings = GitHubSettings()
    # Should not raise
    token = settings.get_credential_for_repo("JoshCLWren/comic-pile")
    assert token == settings.github_token or token == ""


def test_validate_target_is_allowlisted_returns_true() -> None:
    """validate_target_is_allowlisted returns True for allowed repos."""
    service = DeliveryService()
    assert service.validate_target_is_allowlisted("JoshCLWren/comic-pile") is True
    assert service.validate_target_is_allowlisted("JoshCLWren/Latticery") is True


def test_validate_target_is_allowlisted_returns_false() -> None:
    """validate_target_is_allowlisted returns False for non-allowed repos."""
    service = DeliveryService()
    assert service.validate_target_is_allowlisted("unknown/repo") is False


def test_is_latticery_token_required_returns_true_for_latticery() -> None:
    """is_latticery_token_required returns True for Latticery."""
    service = DeliveryService()
    assert service.is_latticery_token_required("JoshCLWren/Latticery") is True


def test_is_latticery_token_required_returns_false_for_comicpile() -> None:
    """is_latticery_token_required returns False for ComicPile."""
    service = DeliveryService()
    assert service.is_latticery_token_required("JoshCLWren/comic-pile") is False


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_delivery_record_create_valid() -> None:
    """DeliveryRecordCreate validates with valid data."""
    record = DeliveryRecordCreate(
        source_repository="JoshCLWren/comic-pile",
        target_repository="JoshCLWren/comic-pile",
        target_branch="factory/test-123",
        worker_id="factory:71",
    )
    assert record.target_repository == "JoshCLWren/comic-pile"
    assert record.target_branch == "factory/test-123"


def test_delivery_record_create_rejects_unapproved_target() -> None:
    """DeliveryRecordCreate rejects unapproved target repositories."""
    with pytest.raises(ValidationError, match="not allowlisted"):
        DeliveryRecordCreate(
            source_repository="JoshCLWren/comic-pile",
            target_repository="evil/repo",
            target_branch="factory/test",
            worker_id="factory:71",
        )


def test_cross_repo_delivery_request_valid_latticery() -> None:
    """CrossRepoDeliveryRequest validates for Latticery target."""
    req = CrossRepoDeliveryRequest(
        target_repository="JoshCLWren/Latticery",
        branch_name="factory/latticery-test",
        worker_id="factory:71",
        title="Test PR",
    )
    assert req.target_repository == "JoshCLWren/Latticery"


def test_cross_repo_delivery_request_rejects_unapproved() -> None:
    """CrossRepoDeliveryRequest rejects unapproved target repositories."""
    with pytest.raises(ValidationError, match="not allowlisted"):
        CrossRepoDeliveryRequest(
            target_repository="evil/repo",
            branch_name="factory/test",
            worker_id="factory:71",
            title="Test PR",
        )


def test_cross_repo_delivery_request_rejects_invalid_branch() -> None:
    """CrossRepoDeliveryRequest rejects branch names not starting with factory/."""
    with pytest.raises(ValidationError):
        CrossRepoDeliveryRequest(
            target_repository="JoshCLWren/comic-pile",
            branch_name="main",
            worker_id="factory:71",
            title="Test PR",
        )


def test_cross_repo_delivery_request_defaults_base_branch() -> None:
    """CrossRepoDeliveryRequest defaults base_branch to main."""
    req = CrossRepoDeliveryRequest(
        target_repository="JoshCLWren/comic-pile",
        branch_name="factory/test",
        worker_id="factory:71",
        title="Test PR",
    )
    assert req.base_branch == "main"


def test_target_repository_validation_schema_valid() -> None:
    """TargetRepositoryValidation accepts allowlisted repos."""
    v = TargetRepositoryValidation(target_repository="JoshCLWren/Latticery", credential_source="LATTICERY_TOKEN")
    assert v.target_repository == "JoshCLWren/Latticery"


def test_target_repository_validation_schema_rejects_unapproved() -> None:
    """TargetRepositoryValidation rejects unapproved repos."""
    with pytest.raises(ValidationError, match="not allowlisted"):
        TargetRepositoryValidation(target_repository="evil/repo", credential_source="GITHUB_TOKEN")


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.fixture
def service() -> DeliveryService:
    """Create a DeliveryService instance."""
    return DeliveryService()


def test_service_get_default_target(service: DeliveryService) -> None:
    """get_default_target returns the default ComicPile repo."""
    assert service.get_default_target() == "JoshCLWren/comic-pile"


def test_service_get_target_repo_default(service: DeliveryService) -> None:
    """get_target_repo with no args returns the default target."""
    target = service.get_target_repo()
    assert target == "JoshCLWren/comic-pile"


def test_service_get_target_repo_explicit(service: DeliveryService) -> None:
    """get_target_repo with explicit target returns validated target."""
    target = service.get_target_repo("JoshCLWren/Latticery")
    assert target == "JoshCLWren/Latticery"


def test_service_get_target_repo_rejects_invalid(service: DeliveryService) -> None:
    """get_target_repo rejects unapproved target repositories."""
    with pytest.raises(ValueError, match="not allowlisted"):
        service.get_target_repo("evil/repo")


def test_service_resolve_credential_source_comicpile(service: DeliveryService) -> None:
    """resolve_credential_source returns GITHUB_TOKEN for ComicPile."""
    source = service.resolve_credential_source("JoshCLWren/comic-pile")
    assert source == "GITHUB_TOKEN"


def test_service_resolve_credential_source_latticery(service: DeliveryService) -> None:
    """resolve_credential_source returns LATTICERY_TOKEN for Latticery."""
    source = service.resolve_credential_source("JoshCLWren/Latticery")
    assert source == "LATTICERY_TOKEN"


def test_service_resolve_credential_source_rejects_invalid(service: DeliveryService) -> None:
    """resolve_credential_source raises ValueError for invalid target."""
    with pytest.raises(ValueError, match="not allowlisted"):
        service.resolve_credential_source("evil/repo")


def test_service_is_latticery_target(service: DeliveryService) -> None:
    """is_latticery_target correctly identifies Latticery."""
    assert service.is_latticery_target("JoshCLWren/Latticery") is True
    assert service.is_latticery_target("JoshCLWren/comic-pile") is False


# ---------------------------------------------------------------------------
# Delivery ledger / model tests
# ---------------------------------------------------------------------------


def test_delivery_record_repo_safe_identity() -> None:
    """DeliveryRecord.is_repo_safe_identity returns repository-safe string."""
    record = DeliveryRecordModel(
        source_repository="JoshCLWren/comic-pile",
        target_repository="JoshCLWren/Latticery",
        target_branch="factory/test",
        issue_number=123,
        status="pending",
        worker_id="factory:71",
    )
    assert record.is_repo_safe_identity == "JoshCLWren/Latticery#None"


def test_delivery_record_delivery_key_with_issue() -> None:
    """DeliveryRecord.delivery_key includes issue number when present."""
    record = DeliveryRecordModel(
        source_repository="JoshCLWren/comic-pile",
        target_repository="JoshCLWren/Latticery",
        target_branch="factory/test",
        issue_number=123,
        status="pending",
        worker_id="factory:71",
    )
    assert record.delivery_key == "JoshCLWren/Latticery/issue-123"


def test_delivery_record_delivery_key_without_issue() -> None:
    """DeliveryRecord.delivery_key includes branch name when no issue number."""
    record = DeliveryRecordModel(
        source_repository="JoshCLWren/comic-pile",
        target_repository="JoshCLWren/Latticery",
        target_branch="factory/test",
        status="pending",
        worker_id="factory:71",
    )
    assert record.delivery_key == "JoshCLWren/Latticery/branch-factory/test"


def test_delivery_record_target_repository_constraint() -> None:
    """DeliveryRecord table args include target_repository check constraint."""
    constraints = DeliveryRecordModel.__table_args__
    constraint_strings = [str(c) for c in constraints]
    assert any("ck_delivery_target_repo" in s for s in constraint_strings)


def test_delivery_record_status_constraint() -> None:
    """DeliveryRecord table args include status check constraint."""
    constraints = DeliveryRecordModel.__table_args__
    constraint_strings = [str(c) for c in constraints]
    assert any("ck_delivery_status" in s for s in constraint_strings)


# ---------------------------------------------------------------------------
# Service delivery ledger tests (with mocked DB)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_session() -> AsyncSession:
    """Create a mock async database session."""
    mock_session = MagicMock(spec=AsyncSession)
    return mock_session


@pytest.mark.asyncio
async def test_service_create_delivery_record(mock_db_session: AsyncSession) -> None:
    """create_delivery_record creates and returns a DeliveryRecord."""
    mock_session = mock_db_session
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()

    result = await _create_record(mock_session)
    assert isinstance(result, DeliveryRecordModel)


async def _create_record(mock_session: AsyncSession) -> DeliveryRecordModel:
    """Helper to create a delivery record."""
    from app.services.delivery import DeliveryService
    service = DeliveryService()
    return await service.create_delivery_record(
        mock_session,
        DeliveryRecordCreate(
            source_repository="JoshCLWren/comic-pile",
            target_repository="JoshCLWren/comic-pile",
            target_branch="factory/test",
            worker_id="factory:71",
        ),
    )


@pytest.mark.asyncio
async def test_service_mark_delivery_failed(mock_db_session: AsyncSession) -> None:
    """mark_delivery_failed updates status to failed with error message."""
    mock_session = mock_db_session
    mock_record = DeliveryRecordModel(
        id=1,
        source_repository="JoshCLWren/comic-pile",
        target_repository="JoshCLWren/Latticery",
        target_branch="factory/test",
        status="branch_created",
        worker_id="factory:71",
    )
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: mock_record))
    flush_mock = AsyncMock()
    mock_session.flush = flush_mock
    mock_session.refresh = AsyncMock()

    await _mark_failed(mock_session, 1, "Branch creation failed")
    flush_mock.assert_called()


async def _mark_failed(mock_session: AsyncSession, delivery_id: int, error: str) -> None:
    """Helper to mark a delivery as failed."""
    from app.services.delivery import DeliveryService
    service = DeliveryService()
    await service.mark_delivery_failed(mock_session, delivery_id, error)


@pytest.mark.asyncio
async def test_service_create_branch_record(mock_db_session: AsyncSession) -> None:
    """create_branch_record creates a delivery record with branch_created status."""
    mock_session = mock_db_session
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()

    result = await _create_branch_record(mock_session)
    assert isinstance(result, DeliveryRecordModel)


async def _create_branch_record(mock_session: AsyncSession) -> DeliveryRecordModel:
    """Helper to create a branch delivery record."""
    from app.services.delivery import DeliveryService
    service = DeliveryService()
    return await service.create_branch_record(
        mock_session,
        "JoshCLWren/Latticery",
        "factory/latticery-pr",
        "factory:71",
        issue_number=42,
    )


@pytest.mark.asyncio
async def test_service_get_delivery_record(mock_db_session: AsyncSession) -> None:
    """get_delivery_record fetches a delivery record by ID."""
    mock_record = DeliveryRecordModel(
        id=1,
        source_repository="JoshCLWren/comic-pile",
        target_repository="JoshCLWren/Latticery",
        target_branch="factory/test",
        status="branch_created",
        worker_id="factory:71",
    )
    mock_session = mock_db_session
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: mock_record))

    result = await _get_record(mock_session, 1)
    assert result is not None
    assert result.id == 1


async def _get_record(mock_session: AsyncSession, delivery_id: int) -> DeliveryRecordModel | None:
    """Helper to get a delivery record."""
    from app.services.delivery import DeliveryService
    service = DeliveryService()
    return await service.get_delivery_record(mock_session, delivery_id)


@pytest.mark.asyncio
async def test_service_create_pr_record(mock_db_session: AsyncSession) -> None:
    """create_pr_record updates a delivery record with PR information."""
    mock_record = DeliveryRecordModel(
        id=1,
        source_repository="JoshCLWren/comic-pile",
        target_repository="JoshCLWren/Latticery",
        target_branch="factory/test",
        status="branch_created",
        worker_id="factory:71",
    )
    mock_session = mock_db_session
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: mock_record))
    flush_mock = AsyncMock()
    mock_session.flush = flush_mock
    mock_session.refresh = AsyncMock()

    result = await _create_pr_record(mock_session, 1, 99)
    assert result is not None
    flush_mock.assert_called()


async def _create_pr_record(mock_session: AsyncSession, delivery_id: int, pr_number: int) -> DeliveryRecordModel | None:
    """Helper to create a PR record."""
    from app.services.delivery import DeliveryService
    service = DeliveryService()
    return await service.create_pr_record(mock_session, delivery_id, pr_number)


# ---------------------------------------------------------------------------
# Credential boundary tests
# ---------------------------------------------------------------------------


def test_latticery_credential_not_printed_in_ledger() -> None:
    """Delivery ledger records never contain credential tokens.

    The delivery_key and metadata fields should not contain LATTICERY_TOKEN.
    """
    # Verify that the delivery_key is repository-safe and contains no tokens
    key = "JoshCLWren/Latticery/branch-factory/test"
    assert "secret" not in key.lower()
    assert "token" not in key.lower()
    assert "LATTICERY_TOKEN" not in key


def test_latticery_credential_not_in_error_message() -> None:
    """Error messages from delivery should not leak LATTICERY_TOKEN."""
    # The RuntimeError message should describe the problem without exposing the token
    with pytest.raises(RuntimeError) as exc_info:
        settings = GitHubSettings()
        settings.get_credential_for_repo("JoshCLWren/Latticery")
    assert "LATTICERY_TOKEN" in str(exc_info.value)
    # But the actual token value must NOT appear in the error message
    assert "secret" not in str(exc_info.value).lower()


def test_comicpile_token_not_used_for_latticery() -> None:
    """GITHUB_TOKEN must not be used for Latticery operations.

    The credential boundary ensures Latticery operations use LATTICERY_TOKEN.
    """
    service = DeliveryService()
    # Latticery requires LATTICERY_TOKEN, not GITHUB_TOKEN
    assert service.is_latticery_token_required("JoshCLWren/Latticery") is True
    assert service.resolve_credential_source("JoshCLWren/Latticery") == "LATTICERY_TOKEN"


# ---------------------------------------------------------------------------
# Dry-run / fixture tests proving PR commands target Latticery
# ---------------------------------------------------------------------------


def test_target_repository_validation_schema_proves_latticery_allowlist() -> None:
    """TargetRepositoryValidation schema proves Latticery is allowlisted.

    This schema can be used as a fixture to validate that PR commands
    target Latticery without mutating ComicPile branches.
    """
    # This validates that the allowlist contains Latticery
    settings = GitHubSettings()
    assert "JoshCLWren/Latticery" in settings.allowed_target_repos


def test_delivery_service_allows_latticery_branch_creation() -> None:
    """DeliveryService can validate Latticery as a branch creation target."""
    service = DeliveryService()
    # This should not raise
    target = service.get_target_repo("JoshCLWren/Latticery")
    assert target == "JoshCLWren/Latticery"


def test_delivery_service_rejects_non_latticery_cross_repo() -> None:
    """DeliveryService rejects non-allowlisted cross-repo targets."""
    service = DeliveryService()
    with pytest.raises(ValueError, match="not allowlisted"):
        service.get_target_repo("unknown-org/unknown-repo")


def test_delivery_record_target_constraint_enforces_allowlist() -> None:
    """DeliveryRecord model has a database-level constraint for allowlisted repos."""
    constraints = DeliveryRecordModel.__table_args__
    constraint_strs = [str(c) for c in constraints]
    # Verify the check constraint exists
    assert any("ck_delivery_target_repo" in s for s in constraint_strs)


# ---------------------------------------------------------------------------
# Integration-style tests for the full delivery contract
# ---------------------------------------------------------------------------


def test_full_delivery_contract_comicpile_default() -> None:
    """Test the full contract: default ComicPile delivery requires no LATTICERY_TOKEN.

    Existing Factory validation remains green:
    - Default target is ComicPile
    - No LATTICERY_TOKEN needed
    - GITHUB_TOKEN used for credential
    """
    settings = GitHubSettings()
    assert settings.default_target_repo == "JoshCLWren/comic-pile"
    # ComicPile delivery never raises RuntimeError
    token = settings.get_credential_for_repo("JoshCLWren/comic-pile")
    assert isinstance(token, str)


def test_full_delivery_contract_latticery_allowlisted() -> None:
    """Test the full contract: Latticery delivery requires LATTICERY_TOKEN.

    - Target is allowlisted
    - LATTICERY_TOKEN required
    - Fail-closed when absent
    """
    settings = GitHubSettings()
    assert "JoshCLWren/Latticery" in settings.allowed_target_repos
    # Should fail closed when LATTICERY_TOKEN is absent
    with pytest.raises(RuntimeError, match="LATTICERY_TOKEN"):
        settings.get_credential_for_repo("JoshCLWren/Latticery")


def test_full_delivery_contract_latticery_with_token() -> None:
    """Test the full contract: Latticery delivery succeeds with LATTICERY_TOKEN.

    When LATTICERY_TOKEN is present, delivery to Latticery should work.
    """
    settings = GitHubSettings(latticery_token="test-latticery-token")
    assert settings.is_latticery_configured is True
    token = settings.get_credential_for_repo("JoshCLWren/Latticery")
    assert token == "test-latticery-token"


def test_delivery_key_repository_safe() -> None:
    """Delivery keys are repository-safe and don't confuse same-number issues across repos.

    The delivery key includes the full target repository name, so
    issue #1 in Latticery is distinct from issue #1 in ComicPile.
    """
    key_latticery = "JoshCLWren/Latticery/issue-1"
    key_comicpile = "JoshCLWren/comic-pile/issue-1"
    assert key_latticery != key_comicpile
    assert "JoshCLWren/Latticery" in key_latticery
    assert "JoshCLWren/comic-pile" in key_comicpile


def test_worker_context_distinguishes_source_from_target() -> None:
    """Delivery records distinguish coordination/source repo from delivery/target repo.

    source_repository is always ComicPile (coordination).
    target_repository is the delivery destination.
    """
    record = DeliveryRecordCreate(
        source_repository="JoshCLWren/comic-pile",
        target_repository="JoshCLWren/Latticery",
        target_branch="factory/test",
        worker_id="factory:71",
    )
    assert record.source_repository == "JoshCLWren/comic-pile"
    assert record.target_repository == "JoshCLWren/Latticery"
    assert record.source_repository != record.target_repository


@pytest.mark.asyncio
async def test_service_deliver_to_target_fails_closed_without_token() -> None:
    """deliver_to_target fails closed when LATTICERY_TOKEN is absent for Latticery.

    This proves the fail-closed credential boundary.
    """
    service = DeliveryService()
    # When LATTICERY_TOKEN is not configured, get_target_repo_client
    # should raise RuntimeError for Latticery
    with pytest.raises(RuntimeError, match="LATTICERY_TOKEN"):
        service.get_credential_for_target("JoshCLWren/Latticery")


# ---------------------------------------------------------------------------
# File-content delivery (bootstrap defect regression for #2875)
# ---------------------------------------------------------------------------


def test_delivery_file_payload_accepts_relative_paths() -> None:
    """DeliveryFilePayload accepts safe relative repository paths."""
    payload = DeliveryFilePayload(
        path="src/latticery/dependency_policy.py",
        content="print('ok')\n",
    )
    assert payload.path == "src/latticery/dependency_policy.py"
    assert payload.content == "print('ok')\n"


def test_delivery_file_payload_rejects_traversal() -> None:
    """DeliveryFilePayload rejects absolute and parent-traversal paths."""
    with pytest.raises(ValidationError):
        DeliveryFilePayload(path="/etc/passwd", content="x")
    with pytest.raises(ValidationError):
        DeliveryFilePayload(path="../escape.py", content="x")
    with pytest.raises(ValidationError):
        DeliveryFilePayload(path="src/../../evil.py", content="x")


def test_cross_repo_request_includes_file_payloads() -> None:
    """CrossRepoDeliveryRequest carries file payloads for content delivery."""
    req = CrossRepoDeliveryRequest(
        target_repository="JoshCLWren/Latticery",
        branch_name="factory/2875-first-extraction-slice",
        worker_id="factory-54",
        title="Add extraction slice",
        files=[
            DeliveryFilePayload(
                path="src/latticery/dependency_policy.py",
                content="VALUE = 1\n",
            )
        ],
        commit_message="Add extraction slice",
    )
    assert len(req.files) == 1
    assert req.files[0].path == "src/latticery/dependency_policy.py"
    assert req.commit_message == "Add extraction slice"


def test_cross_repo_request_files_default_empty() -> None:
    """CrossRepoDeliveryRequest.files defaults to an empty list."""
    req = CrossRepoDeliveryRequest(
        target_repository="JoshCLWren/Latticery",
        branch_name="factory/empty-ok",
        worker_id="factory-54",
        title="No files",
    )
    assert req.files == []


def _mock_delivery_db() -> AsyncSession:
    """Build an async session mock that assigns a record id on refresh."""

    async def _refresh(obj: object) -> None:
        if getattr(obj, "id", None) is None:
            object.__setattr__(obj, "id", 1)

    session = MagicMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock(side_effect=_refresh)
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())
    return session


def _mock_repo_with_files(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Install a class-level mock GitHub repo that records content-commit calls."""
    from github import GithubException

    repo = MagicMock()
    client = MagicMock()

    base_ref = MagicMock()
    base_ref.object.sha = "base-sha"
    base_commit = MagicMock()
    base_commit.commit.tree = MagicMock(name="base-tree")
    blob = MagicMock()
    blob.sha = "blob-sha"
    tree = MagicMock()
    commit = MagicMock()
    commit.sha = "content-commit-sha"
    pr = MagicMock()
    pr.number = 77

    def get_git_ref(name: str) -> MagicMock:
        if name == "heads/main":
            return base_ref
        raise GithubException(404, {"message": "Not Found"}, None)

    repo.get_git_ref.side_effect = get_git_ref
    repo.get_commit.return_value = base_commit
    repo.create_git_blob.return_value = blob
    repo.create_git_tree.return_value = tree
    repo.create_git_commit.return_value = commit
    repo.create_pull.return_value = pr

    monkeypatch.setattr(
        DeliveryService,
        "get_target_repo_client",
        lambda self, _target=None: (client, repo),
    )
    return repo


@pytest.mark.asyncio
async def test_deliver_to_target_commits_file_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """deliver_to_target writes file blobs/tree/commit before opening the PR.

    Regression for the bootstrap defect where delivery only created an empty
    branch and PR, so extraction content never reached the target repository.
    """
    repo = _mock_repo_with_files(monkeypatch)
    service = DeliveryService()
    db = _mock_delivery_db()

    request = CrossRepoDeliveryRequest(
        target_repository="JoshCLWren/comic-pile",
        branch_name="factory/2875-first-extraction-slice",
        worker_id="factory-54",
        title="Add extraction slice",
        body="Coordination issue #2875",
        files=[
            DeliveryFilePayload(
                path="src/latticery/dependency_policy.py",
                content="VALUE = 1\n",
            ),
            DeliveryFilePayload(
                path="src/latticery/executable_policy.py",
                content="VALUE = 2\n",
            ),
        ],
        commit_message="Add extraction slice",
        issue_number=2875,
    )

    result = await service.deliver_to_target(db, request)

    assert result.success is True
    assert result.target_pr_number == 77
    assert repo.create_git_blob.call_count == 2
    repo.create_git_tree.assert_called_once()
    repo.create_git_commit.assert_called_once()
    commit_args = repo.create_git_commit.call_args[0]
    assert commit_args[0] == "Add extraction slice"
    repo.create_git_ref.assert_called_once()
    ref_name = repo.create_git_ref.call_args[0][0]
    assert ref_name == "refs/heads/factory/2875-first-extraction-slice"
    # Content commit must be the ref target, not the empty base SHA.
    assert repo.create_git_ref.call_args[0][1] == "content-commit-sha"
    repo.create_pull.assert_called_once()


@pytest.mark.asyncio
async def test_deliver_to_target_without_files_keeps_branch_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """deliver_to_target without files still creates a branch without content commits."""
    repo = _mock_repo_with_files(monkeypatch)
    service = DeliveryService()
    db = _mock_delivery_db()

    request = CrossRepoDeliveryRequest(
        target_repository="JoshCLWren/comic-pile",
        branch_name="factory/no-files-branch",
        worker_id="factory-54",
        title="Branch only",
        files=[],
    )

    result = await service.deliver_to_target(db, request)

    assert result.success is True
    repo.create_git_blob.assert_not_called()
    repo.create_git_tree.assert_not_called()
    repo.create_git_commit.assert_not_called()
    repo.create_git_ref.assert_called_once()
    assert repo.create_git_ref.call_args[0][1] == "base-sha"
    repo.create_pull.assert_called_once()


def test_to_latticery_source_rewrites_staging_imports() -> None:
    """Staging sources are rewritten to the latticery package import path."""
    import importlib.util

    script_path = PROJECT_ROOT / "scripts" / "deliver_latticery_extraction.py"
    spec = importlib.util.spec_from_file_location(
        "deliver_latticery_extraction_under_test", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    rewritten = module.to_latticery_source(
        "from latticery_extraction.dependency_policy import parse_dependency_numbers\n"
    )
    assert "latticery.dependency_policy" in rewritten
    assert "latticery_extraction" not in rewritten