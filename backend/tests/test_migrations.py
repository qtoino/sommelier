import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]


def test_migrations_create_schema(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    env = {**os.environ, "SOMMELIER_DB": str(db), "SOMMELIER_DB_URL": ""}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True
    )
    tables = sa.inspect(sa.create_engine(f"sqlite:///{db}")).get_table_names()
    assert {"item", "attempt", "itemflag"} <= set(tables)
