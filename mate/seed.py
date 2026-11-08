"""Load the demo ``test_data`` table (from ``sql/test_data.sql``) into a database."""
from __future__ import annotations

import os

from .db import Database, split_sql

SQL_FILE = os.path.join(os.path.dirname(__file__), "..", "sql", "test_data.sql")

SQLITE_DDL = """
create table if not exists test_data (
  id integer primary key,
  ow_project varchar(255) not null,
  work_set_id integer not null,
  work_set_name varchar(100) not null,
  nr_bh integer,
  create_date date not null,
  create_user_id varchar(25) not null,
  to_delete integer not null default 0,
  first_date date not null,
  last_date date not null
)
"""


def seed_demo(db: Database, sql_file: str = SQL_FILE, force: bool = False) -> int:
    """Create + fill ``test_data`` if missing/empty.  Returns the row count."""
    if db.table_exists("test_data") and not force:
        n = db.scalar("select count(*) from test_data") or 0
        if n:
            return int(n)
    with open(sql_file, encoding="utf-8") as fh:
        script = fh.read()
    if db.dialect == "sqlite":
        db.execute("drop table if exists test_data")
        db.execute(SQLITE_DDL)
        inserts = [s for s in split_sql(script) if s.lstrip().upper().startswith("INSERT")]
        with db.engine.begin() as conn:
            for stmt in inserts:
                conn.exec_driver_sql(stmt)
    else:
        db.run_script(script)
    return int(db.scalar("select count(*) from test_data") or 0)
