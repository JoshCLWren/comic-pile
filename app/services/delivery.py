"""Cross-repository delivery service for factory work.

This service provides bounded cross-repository delivery capability:
- Default target is JoshCLWren/comic-pile (coordination repo)
- Allowlisted target JoshCLWren/Latticery uses LATTICERY_TOKEN
- Credential boundary ensures tokens are never leaked or misused
- Delivery records track target-repository identity for recovery
"""

from __future__ import annotations

import logging
from sqlalchemy import select
from github import Github, GithubException
from github.Repository import Repository

from app.config import get_github_settings
from app.database import AsyncSession
from app.models.delivery import DeliveryRecord as DeliveryRecordModel
from app.schemas.delivery import (
    CrossRepoDeliveryRequest,
    DeliveryRecordCreate,
    DeliveryRecordUpdate,
    DeliveryResult,
)

logger = logging.getLogger(__name__)


class DeliveryService:
    """Service for cross-repository factory delivery operations.

    The coordination/source repository is always ComicPile. The delivery/target
    repository is the allowlisted destination (default: JoshCLWren/comic-pile,
    allowlisted: JoshCLWren/Latticery).
    """

    ALLOWED_TARGET_REPOS = {"JoshCLWren/comic-pile", "JoshCLWren/Latticery"}
    DEFAULT_TARGET_REPO = "JoshCLWren/comic-pile"
    LATTICERY_REPO = "JoshCLWren/Latticery"

    def __init__(self) -> None:
        """Initialize the delivery service with configuration."""
        self._settings = get_github_settings()

    def get_target_repo(self, target_repository: str | None = None) -> str:
        """Get the validated target repository.

        Args:
            target_repository: Optional target repository. Defaults to ComicPile.

        Returns:
            The validated target repository string.

        Raises:
            ValueError: If the target repository is not allowlisted.
        """
        target = target_repository or self.DEFAULT_TARGET_REPO
        self._settings.validate_target_repo(target)
        return target

    def get_credential_for_target(self, target_repository: str) -> str:
        """Get the appropriate GitHub credential for a target repository.

        Args:
            target_repository: The target repository string.

        Returns:
            The GitHub token string for the target repository.

        Raises:
            ValueError: If the target repository is not allowlisted.
            RuntimeError: If LATTICERY_TOKEN is required but unavailable.
        """
        return self._settings.get_credential_for_repo(target_repository)

    def resolve_credential_source(self, target_repository: str) -> str:
        """Determine which credential source a target repository requires.

        Args:
            target_repository: The target repository string.

        Returns:
            "GITHUB_TOKEN" for ComicPile, "LATTICERY_TOKEN" for Latticery.
        """
        self._settings.validate_target_repo(target_repository)
        if target_repository == self.LATTICERY_REPO:
            return "LATTICERY_TOKEN"
        return "GITHUB_TOKEN"

    async def create_delivery_record(
        self,
        db: AsyncSession,
        record_data: DeliveryRecordCreate,
    ) -> DeliveryRecordModel:
        """Create a delivery ledger record.

        Args:
            db: Async database session.
            record_data: Delivery record creation data.

        Returns:
            The created DeliveryRecord model.
        """
        record = DeliveryRecordModel(**record_data.model_dump())
        db.add(record)
        await db.flush()
        await db.refresh(record)
        return record

    async def update_delivery_record(
        self,
        db: AsyncSession,
        delivery_id: int,
        update_data: DeliveryRecordUpdate,
    ) -> DeliveryRecordModel | None:
        """Update a delivery ledger record.

        Args:
            db: Async database session.
            delivery_id: Delivery record ID.
            update_data: Fields to update.

        Returns:
            The updated DeliveryRecord model, or None if not found.
        """
        result = await db.execute(
            select(DeliveryRecordModel).where(DeliveryRecordModel.id == delivery_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        for key, value in update_data.model_dump(exclude_unset=True).items():
            setattr(record, key, value)
        await db.flush()
        await db.refresh(record)
        return record

    async def get_delivery_record(
        self, db: AsyncSession, delivery_id: int
    ) -> DeliveryRecordModel | None:
        """Fetch a delivery record by ID.

        Args:
            db: Async database session.
            delivery_id: Delivery record ID.

        Returns:
            The DeliveryRecord model, or None if not found.
        """
        result = await db.execute(
            select(DeliveryRecordModel).where(DeliveryRecordModel.id == delivery_id)
        )
        return result.scalar_one_or_none()

    async def find_delivery_by_target_branch(
        self, db: AsyncSession, target_repository: str, target_branch: str
    ) -> DeliveryRecordModel | None:
        """Find a delivery record by target repository and branch.

        Args:
            db: Async database session.
            target_repository: The target repository.
            target_branch: The target branch name.

        Returns:
            The DeliveryRecord model, or None if not found.
        """
        result = await db.execute(
            select(DeliveryRecordModel).where(
                DeliveryRecordModel.target_repository == target_repository,
                DeliveryRecordModel.target_branch == target_branch,
            )
        )
        return result.scalar_one_or_none()

    async def create_branch_record(
        self,
        db: AsyncSession,
        target_repository: str,
        branch_name: str,
        worker_id: str,
        issue_number: int | None = None,
    ) -> DeliveryRecordModel:
        """Create a delivery record for a branch creation operation.

        Args:
            db: Async database session.
            target_repository: The target repository.
            branch_name: Name of the branch to create.
            worker_id: The worker ID performing the operation.
            issue_number: Optional linked issue number.

        Returns:
            The created DeliveryRecord model.
        """
        record = DeliveryRecordModel(
            source_repository=self.DEFAULT_TARGET_REPO,
            target_repository=target_repository,
            target_branch=branch_name,
            issue_number=issue_number,
            status="branch_created",
            worker_id=worker_id,
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)
        return record

    async def create_pr_record(
        self,
        db: AsyncSession,
        delivery_id: int,
        pr_number: int,
    ) -> DeliveryRecordModel | None:
        """Update a delivery record with PR information.

        Args:
            db: Async database session.
            delivery_id: Delivery record ID.
            pr_number: The PR number created.

        Returns:
            The updated DeliveryRecord model, or None if not found.
        """
        record = await self.get_delivery_record(db, delivery_id)
        if record is None:
            return None
        record.target_pr_number = pr_number
        record.status = "pr_opened"
        await db.flush()
        await db.refresh(record)
        return record

    async def create_merge_record(
        self,
        db: AsyncSession,
        delivery_id: int,
        merge_sha: str,
    ) -> DeliveryRecordModel | None:
        """Update a delivery record with merge information.

        Args:
            db: Async database session.
            delivery_id: Delivery record ID.
            merge_sha: The merge commit SHA.

        Returns:
            The updated DeliveryRecord model, or None if not found.
        """
        record = await self.get_delivery_record(db, delivery_id)
        if record is None:
            return None
        record.target_merge_sha = merge_sha
        record.status = "merged"
        await db.flush()
        await db.refresh(record)
        return record

    async def mark_delivery_failed(
        self,
        db: AsyncSession,
        delivery_id: int,
        error_message: str,
    ) -> DeliveryRecordModel | None:
        """Mark a delivery record as failed.

        Args:
            db: Async database session.
            delivery_id: Delivery record ID.
            error_message: The error message describing the failure.

        Returns:
            The updated DeliveryRecord model, or None if not found.
        """
        record = await self.get_delivery_record(db, delivery_id)
        if record is None:
            return None
        record.status = "failed"
        record.error_message = error_message
        await db.flush()
        await db.refresh(record)
        return record

    async def release_delivery(
        self,
        db: AsyncSession,
        delivery_id: int,
    ) -> DeliveryRecordModel | None:
        """Mark a delivery as released (cross-repo failure release).

        Args:
            db: Async database session.
            delivery_id: Delivery record ID.

        Returns:
            The updated DeliveryRecord model, or None if not found.
        """
        record = await self.get_delivery_record(db, delivery_id)
        if record is None:
            return None
        record.status = "released"
        await db.flush()
        await db.refresh(record)
        return record

    def create_github_client(self, target_repository: str) -> Github:
        """Create a GitHub client with the appropriate credential for the target repo.

        Args:
            target_repository: The target repository string.

        Returns:
            A PyGithub Github client instance.

        Raises:
            ValueError: If the target repository is not allowlisted.
            RuntimeError: If LATTICERY_TOKEN is required but unavailable.
        """
        token = self.get_credential_for_target(target_repository)
        return Github(token)

    def get_target_repo_client(
        self, target_repository: str | None = None
    ) -> tuple[Github, Repository]:
        """Get a GitHub client and repository for the target.

        Args:
            target_repository: Optional target repository. Defaults to ComicPile.

        Returns:
            A tuple of (Github client, Repository).

        Raises:
            ValueError: If the target repository is not allowlisted.
            RuntimeError: If LATTICERY_TOKEN is required but unavailable.
        """
        target = self.get_target_repo(target_repository)
        client = self.create_github_client(target)
        repo_name = target.split("/")[-1]
        repo_owner = target.split("/")[0]
        try:
            repo = client.get_repo(f"{repo_owner}/{repo_name}")
        except GithubException as e:
            raise RuntimeError(f"Failed to access target repository {target}: {e.data}") from e
        return client, repo

    async def deliver_to_target(
        self,
        db: AsyncSession,
        request: CrossRepoDeliveryRequest,
    ) -> DeliveryResult:
        """Execute a cross-repository delivery operation.

        This method:
        1. Validates the target repository against the allowlist
        2. Selects the correct credential (GITHUB_TOKEN vs LATTICERY_TOKEN)
        3. Creates a branch on the target repository
        4. Creates a PR on the target repository
        5. Records all state in the delivery ledger

        Args:
            db: Async database session.
            request: The cross-repo delivery request.

        Returns:
            The DeliveryResult with operation outcome.

        Raises:
            ValueError: If target repository is not allowlisted.
            RuntimeError: If LATTICERY_TOKEN is required but unavailable.
        """
        target = self.get_target_repo(request.target_repository)
        credential_source = self.resolve_credential_source(target)
        delivery_key = f"{target}/branch-{request.branch_name}"

        # Create the delivery ledger record
        record_data = DeliveryRecordCreate(
            source_repository=self.DEFAULT_TARGET_REPO,
            target_repository=target,
            target_branch=request.branch_name,
            issue_number=request.issue_number,
            worker_id=request.worker_id,
        )
        record = await self.create_delivery_record(db, record_data)

        try:
            client, repo = self.get_target_repo_client(target)

            # Create branch on target repo
            ref_name = f"refs/heads/{request.branch_name}"
            base_ref = repo.get_git_ref(f"heads/{request.base_branch}")
            try:
                repo.create_git_ref(ref_name, base_ref.object.sha)
            except GithubException:
                # Branch may already exist
                pass

            # Create PR on target repo
            pr = repo.create_pull(
                title=request.title,
                body=request.body or "",
                head=request.branch_name,
                base=request.base_branch,
            )

            # Update delivery record with PR info
            await self.create_pr_record(db, record.id, pr.number)
            await db.commit()
            await db.refresh(record)

            return DeliveryResult(
                success=True,
                target_repository=target,
                target_branch=request.branch_name,
                target_pr_number=pr.number,
                credential_source=credential_source,
                delivery_key=delivery_key,
            )

        except Exception as e:
            logger.exception("Cross-repo delivery failed for %s", target)
            await self.mark_delivery_failed(db, record.id, str(e))
            await db.commit()
            await db.refresh(record)
            return DeliveryResult(
                success=False,
                target_repository=target,
                target_branch=request.branch_name,
                credential_source=credential_source,
                error_message=str(e),
                delivery_key=delivery_key,
            )

    def validate_target_is_allowlisted(self, target_repository: str) -> bool:
        """Check if a target repository is allowlisted.

        Args:
            target_repository: The target repository string.

        Returns:
            True if allowlisted, False otherwise.
        """
        return target_repository in self.ALLOWED_TARGET_REPOS

    def get_default_target(self) -> str:
        """Return the default target repository (ComicPile itself)."""
        return self.DEFAULT_TARGET_REPO

    def is_latticery_target(self, target_repository: str) -> bool:
        """Check if a target repository is Latticery.

        Args:
            target_repository: The target repository string.

        Returns:
            True if the target is JoshCLWren/Latticery.
        """
        return target_repository == self.LATTICERY_REPO

    def is_latticery_token_required(self, target_repository: str) -> bool:
        """Check if LATTICERY_TOKEN is required for a target.

        Args:
            target_repository: The target repository string.

        Returns:
            True if LATTICERY_TOKEN is needed.
        """
        return self.is_latticery_target(target_repository)
