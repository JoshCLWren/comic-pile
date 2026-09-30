"""API route handlers."""

from types import ModuleType

__all__ = [
    "analytics",
    "cbl_sources",
    "continuity_plan",
    "continuity_rule",
    "continuity_template",
    "custom_cbl",
    "dependency",
    "dependency_group",
    "dependency_group_batch",
    "health",
    "issue_dependency_batch",
    "reading_order_projection",
    "recommendation_diagnostics",
    "releases",
    "roll_recovery_switch",
    "taste_signal",
]


def __getattr__(name: str) -> ModuleType:
    """Lazily import an API submodule on first attribute access.

    Keeps ``app.api`` free of eager router-surface imports so cold-start
    entry points such as ``from app.api import ping`` stay cheap (issue #2978).

    Args:
        name: Submodule name to import.

    Returns:
        The imported submodule.

    Raises:
        AttributeError: If ``name`` is not a known API submodule.
    """
    if name in __all__:
        import importlib

        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
