"""Metrics database operations for Ralph agent tracking."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import engine
from app.models.agent_metrics import AgentMetrics

logger = logging.getLogger(__name__)


def record_metric(
    task_id: int,
    status: str,
    duration: float | None = None,
    error_type: str | None = None,
    api_calls: int = 0,
    tokens_used: int = 0,
) -> AgentMetrics:
    """Record a metric for a task execution.

    Args:
        task_id: Task ID (GitHub issue number)
        status: Task status (pending, in-progress, done, blocked, in-review)
        duration: Duration in seconds
        error_type: Error type if failed
        api_calls: Number of API calls made
        tokens_used: Number of tokens used

    Returns:
        Created AgentMetrics record
    """
    """Record a metric for a task execution.

    Args:
        task_id: Task ID (GitHub issue number)
        status: Task status (pending, in-progress, done, blocked, in-review)
        duration: Duration in seconds
        error_type: Error type if failed
        api_calls: Number of API calls made
        tokens_used: Number of tokens used

    Returns:
        Created AgentMetrics record
    """
    with Session(engine) as session:
        metric = AgentMetrics(
            task_id=task_id,
            status=status,
            duration=duration,
            error_type=error_type,
            api_calls=api_calls,
            tokens_used=tokens_used,
        )
        session.add(metric)
        session.commit()
        session.refresh(metric)
        logger.info(
            f"Recorded metric for task {task_id}: status={status}, duration={duration}s, "
            f"api_calls={api_calls}, tokens_used={tokens_used}"
        )
        return metric


def get_task_metrics(task_id: int) -> list[AgentMetrics]:
    """Get all metrics for a specific task.

    Args:
        task_id: Task ID (GitHub issue number)

    Returns:
        List of AgentMetrics records
    """
    with Session(engine) as session:
        result = session.execute(select(AgentMetrics).where(AgentMetrics.task_id == task_id))
        return list(result.scalars().all())


def get_latest_task_metric(task_id: int) -> AgentMetrics | None:
    """Get the latest metric for a specific task.

    Args:
        task_id: Task ID (GitHub issue number)

    Returns:
        Latest AgentMetrics record or None
    """
    with Session(engine) as session:
        result = session.execute(
            select(AgentMetrics)
            .where(AgentMetrics.task_id == task_id)
            .order_by(AgentMetrics.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


def get_task_summary(task_id: int) -> dict:
    """Get summary statistics for a specific task.

    Args:
        task_id: Task ID (GitHub issue number)

    Returns:
        Dictionary with summary statistics
    """
    with Session(engine) as session:
        result = session.execute(
            select(
                func.count(AgentMetrics.id).label("total_attempts"),
                func.sum(AgentMetrics.duration).label("total_duration"),
                func.avg(AgentMetrics.duration).label("avg_duration"),
                func.sum(AgentMetrics.api_calls).label("total_api_calls"),
                func.sum(AgentMetrics.tokens_used).label("total_tokens"),
            ).where(AgentMetrics.task_id == task_id)
        )
        row = result.one()

        return {
            "task_id": task_id,
            "total_attempts": row.total_attempts or 0,
            "total_duration": float(row.total_duration or 0),
            "avg_duration": float(row.avg_duration or 0),
            "total_api_calls": row.total_api_calls or 0,
            "total_tokens": row.total_tokens or 0,
        }


def get_overall_summary() -> dict:
    """Get overall summary statistics for all tasks.

    Returns:
        Dictionary with overall statistics
    """
    with Session(engine) as session:
        result = session.execute(
            select(
                func.count(AgentMetrics.id).label("total_metrics"),
                func.count(func.distinct(AgentMetrics.task_id)).label("unique_tasks"),
                func.sum(AgentMetrics.duration).label("total_duration"),
                func.avg(AgentMetrics.duration).label("avg_duration"),
                func.sum(AgentMetrics.api_calls).label("total_api_calls"),
                func.sum(AgentMetrics.tokens_used).label("total_tokens"),
            )
        )
        row = result.one()

        return {
            "total_metrics": row.total_metrics or 0,
            "unique_tasks": row.unique_tasks or 0,
            "total_duration": float(row.total_duration or 0),
            "avg_duration": float(row.avg_duration or 0),
            "total_api_calls": row.total_api_calls or 0,
            "total_tokens": row.total_tokens or 0,
        }


def get_status_breakdown() -> dict:
    """Get breakdown of metrics by status.

    Returns:
        Dictionary with status breakdown
    """
    with Session(engine) as session:
        result = session.execute(
            select(
                AgentMetrics.status,
                func.count(AgentMetrics.id).label("count"),
            )
            .group_by(AgentMetrics.status)
            .order_by(func.count(AgentMetrics.id).desc())
        )
        rows = result.all()

        status_dict = {}
        for status, count in rows:
            status_dict[status] = count
        return status_dict


def get_recent_metrics(limit: int = 100) -> list[AgentMetrics]:
    """Get recent metrics across all tasks.

    Args:
        limit: Maximum number of metrics to return

    Returns:
        List of AgentMetrics records
    """
    with Session(engine) as session:
        result = session.execute(
            select(AgentMetrics).order_by(AgentMetrics.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


def get_error_summary() -> dict:
    """Get summary of errors by type.

    Returns:
        Dictionary with error breakdown
    """
    with Session(engine) as session:
        result = session.execute(
            select(
                AgentMetrics.error_type,
                func.count(AgentMetrics.id).label("count"),
            )
            .where(AgentMetrics.error_type.isnot(None))
            .group_by(AgentMetrics.error_type)
            .order_by(func.count(AgentMetrics.id).desc())
        )
        rows = result.all()

        error_dict = {}
        for error_type, count in rows:
            error_dict[error_type] = count
        return error_dict


def update_task_metric(
    metric_id: int,
    status: str | None = None,
    duration: float | None = None,
    error_type: str | None = None,
    api_calls: int | None = None,
    tokens_used: int | None = None,
) -> AgentMetrics | None:
    """Update an existing metric record.

    Args:
        metric_id: Metric record ID
        status: New status (optional)
        duration: New duration (optional)
        error_type: New error type (optional)
        api_calls: New API calls count (optional)
        tokens_used: New tokens used count (optional)

    Returns:
        Updated AgentMetrics record or None if not found
    """
    with Session(engine) as session:
        metric = session.get(AgentMetrics, metric_id)
        if not metric:
            logger.warning(f"Metric {metric_id} not found")
            return None

        if status is not None:
            metric.status = status
        if duration is not None:
            metric.duration = duration
        if error_type is not None:
            metric.error_type = error_type
        if api_calls is not None:
            metric.api_calls = api_calls
        if tokens_used is not None:
            metric.tokens_used = tokens_used

        session.commit()
        session.refresh(metric)
        logger.info(f"Updated metric {metric_id}")
        return metric


def delete_old_metrics(days: int = 30) -> int:
    """Delete metrics older than specified days.

    Args:
        days: Number of days to keep

    Returns:
        Number of deleted records
    """
    cutoff_date = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=days
    )

    with Session(engine) as session:
        result = session.execute(
            select(func.count(AgentMetrics.id)).where(AgentMetrics.created_at < cutoff_date)
        )
        count = result.scalar() or 0

        if count > 0:
            session.query(AgentMetrics).filter(AgentMetrics.created_at < cutoff_date).delete()
            session.commit()
            logger.info(f"Deleted {count} old metrics (older than {days} days)")

        return count
