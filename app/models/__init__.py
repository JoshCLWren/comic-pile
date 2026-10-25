"""SQLAlchemy database models."""


from app.models.cbl_adoption_receipt import CblAdoptionReceipt
from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.catalog import CatalogIssue, CatalogSeries
from app.models.catalog_commit_receipt import CatalogCommitReceipt
from app.models.collection_exclusion import CollectionExclusion
from app.models.comicvine_metadata_refresh import ComicVineMetadataRefreshRequest
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule, ContinuityRuleSelectedMember
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList, CustomCBLOverlapDecision
from app.models.custom_cbl_source_link import CustomCBLSourceLink
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.delivery import DeliveryRecord
from app.models.event import Event
from app.models.recommendation_context import RecommendationContext
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.failed_login_attempt import FailedLoginAttempt
from app.models.github_issue_submission_limit import GithubIssueSubmissionLimit
from app.models.issue import Issue
from app.models.metadata_correction import IssueMetadataCorrection
from app.models.password_reset_token import PasswordResetToken
from app.models.perf_alarm import PerfAlarmCounter, PerfAlarmIncident
from app.models.performance_metric import PerformanceMetric
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.models.reading_plan_membership import (
    ReadingPlanDependency,
    ReadingPlanIssue,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
)
from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.models.release import Release
from app.models.revoked_token import RevokedToken
from app.models.reading_session import ReadingSession
from app.models.snapshot import Snapshot
from app.models.tag import Tag, TagAssignment
from app.models.taste_signal import TasteSignal
from app.models.thread import Thread
from app.models.user import User
from app.models.user_preferences import UserPreferences

__all__ = [
    "CblAdoptionReceipt",
    "CBLSource",
    "CBLSourceEntry",
    "CBLSourceList",
    "CatalogCommitReceipt",
    "CatalogIssue",
    "CatalogSeries",
    "CollectionExclusion",
    "ComicVineMetadataRefreshRequest",
    "ContinuityPlan",
    "ContinuityRule",
    "ContinuityRuleSelectedMember",
    "CustomCBLEntry",
    "CustomCBLList",
    "CustomCBLOverlapDecision",
    "CustomCBLSourceLink",
    "Dependency",
    "DependencyGroup",
    "DependencyGroupMembership",
    "DeliveryRecord",
    "Event",
    "ExternalIdentity",
    "RecommendationContext",
    "FailedLoginAttempt",
    "GithubIssueSubmissionLimit",
    "Issue",
    "IssueExternalIdentityMapping",
    "IssueMetadataCorrection",
    "PasswordResetToken",
    "PerfAlarmCounter",
    "PerfAlarmIncident",
    "PerformanceMetric",
    "ReadingOrder",
    "ReadingOrderItem",
    "ReadingPlanDependency",
    "ReadingPlanIssue",
    "ReadingPlanReleaseSource",
    "ReadingPlanSource",
    "ReadingPlanSourcePlacement",
    "Release",
    "RevokedToken",
    "ReadingSession",
    "Snapshot",
    "TasteSignal",
    "Tag",
    "TagAssignment",
    "Thread",
    "ThreadExternalSeriesMapping",
    "User",
    "UserPreferences",
]
