"""Read a database table and derive MATE column settings from it.

Used by the generator script (``tools/generate_columns.py``), which writes the
settings as Python code into the generated block of ``web.py``: one ``PAGES[key]``
entry per page, naming the database (a key of ``DATABASES``) and the table it shows.

Mapping of SQL types to field helpers (see :mod:`mate.fields`):

===========================  ==================  =================================
SQL type                     helper              notes
===========================  ==================  =================================
integer / numeric / float    ``num_field``       right aligned
varchar/char (<= 255)        ``txt_field``
text / long varchar / JSON   ``txtarea_field``   textarea input, not shown in table
                                                 (SQLite/PostgreSQL ``TEXT`` is ordinary text)
date / datetime / timestamp  ``date_field``      calendar input, formatted display
boolean / tinyint(1)         ``yn_field``        Yes/No dropdown
binary / blob                (skipped)
===========================  ==================  =================================
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.sql import sqltypes as T

from .db import Database
from .editor import ConfigError

# Table/column names must be plain identifiers: they end up in SQL, URLs, DOM ids
# and generated source code.
SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

READ_ONLY_PERMS = "VQSXOHUIF"
EDIT_TABLE_PERMS = "AEDC"


@dataclass
class ColInfo:
    name: str
    kind: str                 # int float text longtext date bool
    nullable: bool = True
    has_default: bool = False
    sql_type: str = ""


@dataclass
class TableInfo:
    name: str
    pk: str
    columns: list[ColInfo]
    pk_kind: str = "int"
    skipped: list[tuple[str, str]] = dc_field(default_factory=list)   # (column, reason)


# Dialects where an unsized TEXT column is the ordinary string type (SQLite has no
# VARCHAR limit, PostgreSQL recommends TEXT); in MySQL TEXT is a 64 KB long-text type.
PLAIN_TEXT_DIALECTS = {"sqlite", "postgresql"}


def classify(t: Any, dialect: str = "") -> str:
    if isinstance(t, T.Boolean):
        return "bool"
    if isinstance(t, T.Integer):
        if type(t).__name__ == "TINYINT" and getattr(t, "display_width", None) == 1:
            return "bool"
        return "int"
    if isinstance(t, (T.Numeric, T.Float)):
        return "float"
    if isinstance(t, (T.DateTime, T.Date)):
        return "date"
    if isinstance(t, (T.LargeBinary, T._Binary)):
        return "binary"
    if isinstance(t, T.JSON):
        return "longtext"
    if isinstance(t, T.Text):
        length = getattr(t, "length", None)
        if dialect in PLAIN_TEXT_DIALECTS and not length:
            return "text"
        return "longtext"
    if isinstance(t, T.String):               # includes Enum
        length = getattr(t, "length", None)
        return "longtext" if length and length > 255 else "text"
    name = str(t).lower()
    if "blob" in name or "binary" in name:
        return "binary"
    return "text"


def reflect_table(db: Database, table: str, primary_col: str | None = None) -> TableInfo:
    if not SAFE_IDENT.match(table):
        raise ConfigError(f"unsupported table name {table!r} (letters, digits and _ only)")
    insp = inspect(db.engine)
    if not insp.has_table(table):
        raise ConfigError(f"table {table!r} does not exist in this database")
    cols: list[ColInfo] = []
    skipped: list[tuple[str, str]] = []
    for c in insp.get_columns(table):
        name = c["name"]
        if not SAFE_IDENT.match(name):
            skipped.append((name, "unsupported characters in column name"))
            continue
        kind = classify(c["type"], db.dialect)
        if kind == "binary":
            skipped.append((name, "binary column"))
            continue
        cols.append(ColInfo(name=name, kind=kind, nullable=bool(c.get("nullable", True)),
                            has_default=c.get("default") is not None, sql_type=str(c["type"])))
    names = [c.name for c in cols]
    pk = primary_col
    if not pk:
        pks = insp.get_pk_constraint(table).get("constrained_columns") or []
        if len(pks) == 1:
            pk = pks[0]
        elif "id" in names:
            pk = "id"
        else:
            raise ConfigError(
                f"table {table!r} has no single-column primary key; use --primary-col")
    if pk not in names:
        raise ConfigError(f"primary key column {pk!r} not found (or unsupported) in {table!r}")
    pk_kind = next(c.kind for c in cols if c.name == pk)
    return TableInfo(table, pk, cols, pk_kind, skipped)


def list_tables(db: Database) -> list[str]:
    return [t for t in inspect(db.engine).get_table_names()
            if SAFE_IDENT.match(t) and not t.startswith("sqlite_")]


# --------------------------------------------------------------------------
HELPERS = {"int": "num_field", "float": "num_field", "text": "txt_field", "longtext": "txtarea_field",
           "date": "date_field", "bool": "yn_field"}


def label(name: str) -> str:
    """``ow_project`` -> ``Ow Project``, ``CategoryName`` -> ``Category Name``, ``CustomerID`` -> ``Customer ID``."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name.replace("_", " "))
    return " ".join(w[:1].upper() + w[1:] for w in spaced.split())


def plan_columns(info: TableInfo, *, editable: bool = False, show_id: bool = False) -> list[dict[str, Any]]:
    """Decide helper, permission letters and extras for every column."""
    plan = []
    for c in info.columns:
        if c.name == info.pk:
            # a text key (e.g. a customer code) means something to the user: show it
            visible = show_id or c.kind != "int"
            plan.append({"name": c.name, "helper": "id_field", "perms": "T" if visible else "",
                         "text": None if c.kind == "int" else label(c.name), "extra": {}})
            continue
        perms = "" if c.kind == "longtext" else "T"
        extra: dict[str, Any] = {}
        if editable:
            perms += "AEC"
            if not c.nullable and not c.has_default and c.kind != "bool":
                extra["req"] = True
        plan.append({"name": c.name, "helper": HELPERS[c.kind], "perms": perms,
                     "text": label(c.name), "extra": extra})
    return plan


def table_permissions(editable: bool) -> str:
    return READ_ONLY_PERMS + (EDIT_TABLE_PERMS if editable else "")


# --------------------------------------------------------------------------
# Code generation
# --------------------------------------------------------------------------
BEGIN = "# BEGIN GENERATED PAGES"
END = "# END GENERATED PAGES"
HEADER_NOTE = ("(written by tools/generate_columns.py - re-run it to refresh; "
               "put manual changes in OVERRIDES, not in this block)")
IMPORT_LINE = ("from mate.fields import (date_field, field, id_field, num_field, txt_field, "
               "txtarea_field, yn_field)")


def page_key(table: str, database: str = "default") -> str:
    """Default page key (URL slug) of *table*: the table name, prefixed for other databases."""
    return table if database == "default" else f"{database}_{table}"


def render_table(info: TableInfo, plan: list[dict[str, Any]], *, permissions: str, title: str,
                 database: str = "default", page: str | None = None) -> str:
    page = page or page_key(info.name, database)
    if not SAFE_IDENT.match(page):
        raise ConfigError(f"unsupported page name {page!r} (letters, digits and _ only)")
    out = [f"# skipped column {col!r}: {why}" for col, why in info.skipped]
    out += [f"PAGES[{page!r}] = {{",
            f"    \"database\": {database!r},",
            f"    \"table\": {info.name!r},",
            f"    \"title\": {title!r},",
            f"    \"primary_col\": {info.pk!r},",
            f"    \"permissions\": {permissions!r},",
            "    \"columns\": {"]
    for p in plan:
        args = [p["helper"], repr(p["name"]), repr(p["perms"])]
        if p["text"] is not None:
            args.append(repr(p["text"]))
        kwargs = ", ".join(f"{k}={v!r}" for k, v in p["extra"].items())
        out.append(f"        {p['name']!r}: field({', '.join(args)}{', ' + kwargs if kwargs else ''}),")
    out += ["    },", "}"]
    return "\n".join(out) + "\n"


_SEGMENT = re.compile(r"(?ms)^(?:#[^\n]*\n)*PAGES\[(?P<q>['\"])(?P<name>.+?)(?P=q)\] = \{\n.*?^\}\n")


def parse_block(text: str) -> dict[str, str]:
    """Existing per-page code segments inside a generated block (page key -> code)."""
    return {m.group("name"): m.group(0) for m in _SEGMENT.finditer(text)}


def render_block(segments: dict[str, str]) -> str:
    body = "\n".join(segments.values())
    return f"{BEGIN} {HEADER_NOTE}\n{IMPORT_LINE}\n\nPAGES: dict = {{}}\n\n{body}{END}\n"


def update_file(path: str, segments: dict[str, str], *, replace: bool = False) -> list[str]:
    """Write *segments* into the generated block of *path*.

    Pages already in the block are kept unless *replace* is set (a page that is
    generated again is always refreshed).  Returns the page keys now present.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        text = ""
    a, b = text.find(BEGIN), text.find(END)
    has_block = a != -1 and b > a
    merged: dict[str, str] = {}
    if has_block and not replace:
        merged.update(parse_block(text[a:b]))
    merged.update(segments)
    block = render_block(merged)
    if has_block:
        end = text.find("\n", b)
        end = len(text) if end == -1 else end + 1
        new = text[:a] + block + text[end:]
    else:
        new = text + ("\n" if text and not text.endswith("\n") else "") + block
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    return list(merged)
