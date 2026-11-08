"""Regression: Alembic lock waits are bounded and failed migrations never stamp."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from tests.conftest import _looks_like_test_database, get_test_database_url

ROOT = Path(__file__).resolve().parents[1]
REVISION = "c4736locktest"


def _migration_fixture(tmp_path: Path) -> Path:
    """Use the real env.py with one isolated, lock-requiring migration."""
    scripts = tmp_path / "alembic"
    versions = scripts / "versions"
    versions.mkdir(parents=True)
    shutil.copy2(ROOT / "alembic" / "env.py", scripts / "env.py")
    (versions / "lock_test.py").write_text(
        f'''"""Disposable migration for lock-timeout testing."""

from alembic import op

revision = "{REVISION}"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE migration_lock_fixture ADD COLUMN verified BOOLEAN")


def downgrade() -> None:
    op.execute("ALTER TABLE migration_lock_fixture DROP COLUMN verified")
''',
        encoding="utf-8",
    )
    ini = tmp_path / "alembic.ini"
    original = (ROOT / "alembic.ini").read_text(encoding="utf-8")
    marker = "script_location = %(here)s/alembic"
    assert marker in original, "Alembic script-location configuration changed"
    ini.write_text(original.replace(marker, f"script_location = {scripts}"), encoding="utf-8")
    return ini


def _run_migration(ini: Path, database_url: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["ALEMBIC_LOCK_TIMEOUT_MS"] = "250"
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ini), "upgrade", "head"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )


def test_migration_lock_timeout_rolls_back_and_allows_retry(tmp_path: Path) -> None:
    """A blocked ALTER fails promptly without a stamp; retry succeeds after unlock."""
    test_database_url = get_test_database_url()
    assert _looks_like_test_database(test_database_url), (
        "Lock regression must only use a disposable database named *test*"
    )
    base_url = make_url(test_database_url).set(drivername="postgresql+psycopg")
    engine = create_engine(base_url)
    schema = f"migration_lock_{uuid4().hex}"
    migration_url = base_url.set(
        query={**dict(base_url.query), "options": f"-csearch_path={schema}"}
    ).render_as_string(hide_password=False)
    ini = _migration_fixture(tmp_path)
    lock_holder = None

    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(
                f'CREATE TABLE "{schema}".migration_lock_fixture (id INTEGER PRIMARY KEY)'
            )

        lock_holder = engine.connect()
        lock_holder.exec_driver_sql(
            f'LOCK TABLE "{schema}".migration_lock_fixture IN ACCESS EXCLUSIVE MODE'
        )

        started = time.monotonic()
        failure = _run_migration(ini, migration_url)
        elapsed = time.monotonic() - started
        details = failure.stdout + failure.stderr
        assert failure.returncode != 0, details
        assert "SQLSTATE 55P03" in details, details
        assert "lock_timeout=250ms" in details, details
        assert elapsed < 10, f"Lock timeout was not prompt: {elapsed:.2f}s"

        lock_holder.rollback()
        lock_holder.close()
        lock_holder = None

        with engine.connect() as connection:
            version_exists = connection.exec_driver_sql(
                "SELECT to_regclass(%s)", (f"{schema}.alembic_version",)
            ).scalar_one()
            if version_exists is not None:
                assert connection.exec_driver_sql(
                    f'SELECT COUNT(*) FROM "{schema}".alembic_version'
                ).scalar_one() == 0
            assert connection.exec_driver_sql(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = 'migration_lock_fixture' "
                "AND column_name = 'verified'",
                (schema,),
            ).scalar_one() == 0

        success = _run_migration(ini, migration_url)
        assert success.returncode == 0, success.stdout + success.stderr
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                f'SELECT version_num FROM "{schema}".alembic_version'
            ).scalar_one() == REVISION
            assert connection.exec_driver_sql(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = 'migration_lock_fixture' "
                "AND column_name = 'verified'",
                (schema,),
            ).scalar_one() == 1
    finally:
        if lock_holder is not None:
            lock_holder.rollback()
            lock_holder.close()
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()
