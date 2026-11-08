"""Database access layer.

Replaces ``include/DBC.php``, ``include/db.php`` and ``include/db_functions.php``
from the PHP original.

Differences from the original, on purpose:

* No credentials in source code.  The PHP version shipped a host, user and
  password in ``DBC.php`` and fell back to them when ``dbc.ini`` was absent.
  Here the connection comes from, in order of precedence:

    1. an explicit SQLAlchemy URL passed to :class:`Database`
    2. the ``MATE_DB_URL`` environment variable
    3. ``MATE_DB_HOST`` / ``MATE_DB_NAME`` / ``MATE_DB_USER`` /
       ``MATE_DB_PASSWORD`` environment variables (MySQL)
    4. a ``dbc.ini`` file (same ``host/db/user/password`` keys as the PHP one)
    5. a local SQLite file ``mate_demo.db`` so the demo runs out of the box

* Queries use named bind parameters (``:name``) exactly like the PDO code, via
  SQLAlchemy ``text()``, so the SQL that ``AjaxTableEditor`` builds is the same
  string in both languages.
"""
from __future__ import annotations

import configparser
import datetime as _dt
import os
import re
from typing import Any, Iterable, Mapping

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL

DEFAULT_SQLITE_URL = "sqlite:///mate_demo.db"


class QueryError(Exception):
    """Raised when a query fails.  Carries the SQL and params for diagnostics."""

    def __init__(self, message: str, sql: str = "", params: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.sql = sql
        self.params = dict(params or {})


def _url_from_ini(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    cp = configparser.ConfigParser()
    # PHP's parse_ini_file tolerates files without a section header
    with open(path, encoding="utf-8") as fh:
        cp.read_string("[dbc]\n" + fh.read())
    sec = cp["dbc"]
    return str(
        URL.create(
            "mysql+pymysql",
            username=sec.get("user"),
            password=sec.get("password"),
            host=sec.get("host"),
            database=sec.get("db"),
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)
    )


def resolve_url(url: str | None = None, ini_file: str = "dbc.ini") -> str:
    if url:
        return url
    if os.environ.get("MATE_DB_URL"):
        return os.environ["MATE_DB_URL"]
    if os.environ.get("MATE_DB_HOST"):
        return str(
            URL.create(
                "mysql+pymysql",
                username=os.environ.get("MATE_DB_USER"),
                password=os.environ.get("MATE_DB_PASSWORD"),
                host=os.environ["MATE_DB_HOST"],
                database=os.environ.get("MATE_DB_NAME"),
                query={"charset": "utf8mb4"},
            ).render_as_string(hide_password=False)
        )
    return _url_from_ini(ini_file) or DEFAULT_SQLITE_URL


# --------------------------------------------------------------------------
# MySQL function shims so that display masks such as ``if(x='0','No','Yes')``,
# ``date_format(d,'%d %M %Y')`` or ``concat(a,b)`` also run on SQLite (used for
# the demo and the test-suite).  On MySQL/MariaDB these are native.
# --------------------------------------------------------------------------
_MYSQL_TO_STRFTIME = {
    "%d": "%d", "%e": "%-d", "%m": "%m", "%c": "%-m", "%Y": "%Y", "%y": "%y",
    "%M": "%B", "%b": "%b", "%H": "%H", "%i": "%M", "%s": "%S", "%S": "%S",
    "%T": "%H:%M:%S", "%W": "%A", "%a": "%a", "%j": "%j", "%%": "%%",
}


def _sqlite_date_format(value: Any, fmt: str) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        parsed = None
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = _dt.datetime.strptime(value[:19], pattern)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
        value = parsed
    out = re.sub(r"%.", lambda m: _MYSQL_TO_STRFTIME.get(m.group(0), m.group(0)), fmt)
    return value.strftime(out)


def _sqlite_truncate(value: Any, digits: Any) -> float | None:
    if value is None:
        return None
    factor = 10 ** int(digits)
    return int(float(value) * factor) / factor


def _sqlite_if(cond: Any, a: Any, b: Any) -> Any:
    return a if cond not in (None, 0, "0", "", False) else b


def _sqlite_concat(*args: Any) -> str | None:
    if any(a is None for a in args):
        return None
    return "".join(str(a) for a in args)


def _register_sqlite_functions(dbapi_conn, _record) -> None:
    dbapi_conn.create_function("date_format", 2, _sqlite_date_format)
    dbapi_conn.create_function("truncate", 2, _sqlite_truncate)
    dbapi_conn.create_function("if", 3, _sqlite_if)
    dbapi_conn.create_function("ifnull", 2, lambda a, b: b if a is None else a)
    dbapi_conn.create_function("concat", -1, _sqlite_concat)


class Database:
    """Thin wrapper that mirrors the helpers the PHP code relied on."""

    def __init__(self, url: str | None = None, engine: Engine | None = None):
        if engine is not None:
            self.engine = engine
        else:
            self.engine = create_engine(resolve_url(url), future=True, pool_pre_ping=True)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", _register_sqlite_functions)

    # -- dialect helpers ---------------------------------------------------
    @property
    def dialect(self) -> str:
        return self.engine.dialect.name

    # -- core --------------------------------------------------------------
    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Run a SELECT and return a list of dict rows (``PDO::FETCH_ASSOC``)."""
        params = dict(params or {})
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql), params)
                return [dict(r._mapping) for r in result]
        except Exception as exc:  # noqa: BLE001 - re-raised with context
            raise QueryError(f"{exc.__class__.__name__}: {exc}", sql, params) from exc

    def scalar(self, sql: str, params: Mapping[str, Any] | None = None) -> Any:
        rows = self.query(sql, params)
        if not rows:
            return None
        return next(iter(rows[0].values()))

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> tuple[int, Any]:
        """Run INSERT/UPDATE/DELETE in its own transaction.

        Returns ``(rowcount, lastrowid)``.
        """
        params = dict(params or {})
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text(sql), params)
                last_id = getattr(result, "lastrowid", None)
                return result.rowcount, last_id
        except Exception as exc:  # noqa: BLE001
            raise QueryError(f"{exc.__class__.__name__}: {exc}", sql, params) from exc

    def run_script(self, script: str) -> None:
        """Execute a multi-statement SQL script (used for seeding demo data)."""
        with self.engine.begin() as conn:
            raw = conn.connection  # DBAPI connection
            if self.dialect == "sqlite":
                raw.executescript(script)
            else:
                for stmt in split_sql(script):
                    conn.exec_driver_sql(stmt)

    # -- PHP helper equivalents (db_functions.php) -------------------------
    def table_fieldnames(self, table: str) -> list[str]:
        """``SHOW COLUMNS FROM <table>`` -> list of column names."""
        insp = inspect(self.engine)
        return [c["name"] for c in insp.get_columns(table)]

    def table_exists(self, table: str) -> bool:
        return inspect(self.engine).has_table(table)

    def table_distinct_values(self, table: str) -> dict[str, str]:
        """Config lookup used by the original for per-column dropdown values."""
        rows = self.query(
            "select column_name, list_distinct_values from distinct_values "
            "where table_name = :t",
            {"t": table},
        )
        return {r["column_name"]: r["list_distinct_values"] for r in rows}


def split_sql(script: str) -> Iterable[str]:
    """Very small statement splitter good enough for phpMyAdmin style dumps."""
    buf: list[str] = []
    in_str = False
    quote = ""
    i = 0
    while i < len(script):
        ch = script[i]
        nxt = script[i + 1] if i + 1 < len(script) else ""
        if not in_str:
            if ch == "-" and nxt == "-":
                j = script.find("\n", i)
                i = len(script) if j == -1 else j
                continue
            if ch == "/" and nxt == "*":
                j = script.find("*/", i + 2)
                i = len(script) if j == -1 else j + 2
                continue
            if ch in ("'", '"'):
                in_str, quote = True, ch
            elif ch == ";":
                stmt = "".join(buf).strip()
                if stmt:
                    yield stmt
                buf = []
                i += 1
                continue
        else:
            if ch == "\\":
                buf.append(ch + nxt)
                i += 2
                continue
            if ch == quote:
                if nxt == quote:
                    buf.append(ch + nxt)
                    i += 2
                    continue
                in_str = False
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        yield tail
