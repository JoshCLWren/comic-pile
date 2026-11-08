"""Alembic environment configuration."""

import os
import sys
from logging.config import fileConfig

from dotenv import load_dotenv

from sqlalchemy import engine_from_config, pool
from sqlalchemy.exc import SQLAlchemyError
from greenlet import greenlet

# Initialize greenlet
if not greenlet.getcurrent():
    greenlet.greenlet_spawn(lambda: None).switch()

# Ensure greenlet is initialized
if not greenlet.getcurrent():
    greenlet.greenlet_spawn(lambda: None).switch()

# Ensure greenlet is initialized
if not greenlet.getcurrent():
    greenlet.greenlet_spawn(lambda: None).switch()

from alembic import context

import app.models
from app.database import Base

# Load environment variables from .env file
load_dotenv()

config = context.config

database_url = os.getenv("DATABASE_URL")
if database_url:
    # Convert to sync driver for alembic migrations
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _migration_lock_timeout_ms() -> int:
    """Bound PostgreSQL lock waits during schema migrations (default: 5 seconds).

    Use ALEMBIC_LOCK_TIMEOUT_MS only for a deployment-specific ceiling.
    A 0/negative or unbounded timeout is unsafe. This limits time *waiting
    for locks*, not the duration of running DDL.
    """
    raw = os.getenv("ALEMBIC_LOCK_TIMEOUT_MS", "5000")
    try:
        milliseconds = int(raw)
    except ValueError as error:
        raise ValueError(
            "ALEMBIC_LOCK_TIMEOUT_MS must be an integer number of milliseconds"
        ) from error
    if not 1 <= milliseconds <= 60000:
        raise ValueError("ALEMBIC_LOCK_TIMEOUT_MS must be between 1 and 60000")
    return milliseconds

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    lock_timeout_ms = _migration_lock_timeout_ms()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        with connectable.connect() as connection:
            # Commit the session setting *before* Alembic's migration transaction.
            # Leaving SQLAlchemy's implicit SET transaction open would prevent
            # context.begin_transaction() from owning the migration/DDL and stamp
            # atomically. NullPool closes the dedicated session after the run,
            # restoring the database's normal settings for other connections.
            connection.exec_driver_sql(
                f"SET SESSION lock_timeout = '{lock_timeout_ms}ms'"
            )
            connection.commit()

            context.configure(
                connection=connection, target_metadata=target_metadata, render_as_batch=True
            )
            try:
                with context.begin_transaction():
                    context.run_migrations()
            except SQLAlchemyError as error:
                # 55P03 is PostgreSQL's lock_not_available condition, also
                # raised when lock_timeout expires. Preserve the original error
                # and rollback while making production CI logs actionable.
                if getattr(getattr(error, "orig", None), "sqlstate", None) == "55P03":
                    print(
                        "Alembic migration blocked by a PostgreSQL lock "
                        f"(SQLSTATE 55P03; lock_timeout={lock_timeout_ms}ms). "
                        "No migration version stamp was committed.",
                        file=sys.stderr,
                    )
                raise
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
