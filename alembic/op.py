"""Stub module for Alembic operations used in migrations during tests.
Provides no-op implementations of the functions accessed by migration scripts.
This allows the migration modules to be imported without requiring a full Alembic
environment.
"""

from typing import Any

def add_column(table_name: str, column: Any, *args, **kwargs) -> None:
    """Placeholder for alembic.op.add_column – does nothing in test context."""
    return None

def create_foreign_key(constraint_name: str, source_table: str, referent_table: str,
                        local_cols: list[str], remote_cols: list[str], **kwargs) -> None:
    return None

def create_unique_constraint(constraint_name: str, table_name: str, column_names: list[str], **kwargs) -> None:
    return None

def execute(sql: Any, *args, **kwargs) -> None:
    return None

def drop_constraint(constraint_name: str, table_name: str, type_: str = "foreignkey", **kwargs) -> None:
    return None

def drop_column(table_name: str, column_name: str, *args, **kwargs) -> None:
    return None
