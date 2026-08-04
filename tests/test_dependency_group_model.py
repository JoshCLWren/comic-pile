"""Regression tests for named dependency-group persistence."""

from typing import cast

from sqlalchemy import CheckConstraint, Table, UniqueConstraint

from app.models.dependency_group import DependencyGroup, DependencyGroupMembership


def _model_table(model_table: object) -> Table:
    """Narrow SQLAlchemy's declarative table attribute for static analysis."""
    return cast(Table, model_table)


def test_dependency_group_names_are_unique_per_user() -> None:
    """Prevent duplicate group names inside one user's namespace."""
    constraints = {
        constraint.name
        for constraint in _model_table(DependencyGroup.__table__).constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "uq_dependency_groups_user_name" in constraints


def test_dependency_group_membership_requires_exactly_one_target() -> None:
    """A membership must point to one thread or one issue, never both or neither."""
    constraints = {
        constraint.name
        for constraint in _model_table(DependencyGroupMembership.__table__).constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_dependency_group_membership_one_target" in constraints


def test_dependency_group_memberships_are_unique_by_target() -> None:
    """Do not allow the same thread or issue to be added twice to one group."""
    constraints = {
        constraint.name
        for constraint in _model_table(DependencyGroupMembership.__table__).constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert constraints >= {
        "uq_dependency_group_thread",
        "uq_dependency_group_issue",
    }
