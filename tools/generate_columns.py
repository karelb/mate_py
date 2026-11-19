#!/usr/bin/env python3
"""Generate MATE column settings from database tables.

Reads the structure of one or more tables and writes ready-to-edit Python
settings into the generated block of ``web.py`` (between the
``# BEGIN GENERATED PAGES`` / ``# END GENERATED PAGES`` markers).  Every table
becomes a page: ``PAGES[key]`` names the database (a key of ``DATABASES`` in
``web.py``) and the table, so each page in the menu can use its own database.

Examples
--------
    # read-only editor for two tables of the database in $MATE_DB_URL
    python tools/generate_columns.py --tables customers,orders

    # every table, with orders and products editable (add/edit/copy/delete)
    python tools/generate_columns.py --all --editable orders products

    # make every generated table editable and show the primary key column
    python tools/generate_columns.py --all --editable --show-id

    # tables of another database: add DATABASES["crm"] = "mysql+pymysql://..." to
    # web.py first; the pages are called crm_customers, crm_orders (or use --page)
    python tools/generate_columns.py --db crm --tables customers,orders
    python tools/generate_columns.py --db crm --tables customers --page clients

    # just print the code, do not touch web.py
    python tools/generate_columns.py --tables orders --print

Connection: ``--url`` (SQLAlchemy URL), else ``DATABASES[--db]`` from the target
file (web.py); for the "default" database without an entry: ``MATE_DB_URL``, the
``MATE_DB_*`` variables or ``dbc.ini`` (see mate/db.py).

Pages already present in the block are kept (unless ``--replace``), so you can
add one table at a time; a page generated again is refreshed.
Hand-made changes belong in ``OVERRIDES`` in ``web.py``: they survive regeneration.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from mate import introspect as I  # noqa: E402
from mate.db import Database  # noqa: E402
from mate.editor import ConfigError  # noqa: E402

DEFAULT_TARGET = os.path.join(ROOT, "web.py")


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="default", metavar="NAME",
                    help="database name, a key of DATABASES in web.py (default: 'default')")
    ap.add_argument("--url", help="SQLAlchemy URL to read the tables from (default: DATABASES[--db] in web.py)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--tables", help="comma separated list of tables")
    g.add_argument("--all", action="store_true", help="all tables in the database")
    ap.add_argument("--editable", nargs="*", metavar="TABLE", default=None,
                    help="allow add/edit/copy/delete; without names: for every generated table")
    ap.add_argument("--show-id", action="store_true", help="show the primary key column in the table")
    ap.add_argument("--primary-col", help="primary key column (one table only; for tables without a primary key)")
    ap.add_argument("--page", help="page key / URL name (one table only; default: table, or <db>_<table>)")
    ap.add_argument("--target", default=DEFAULT_TARGET, help="file holding the generated block (default: web.py)")
    ap.add_argument("--replace", action="store_true", help="drop pages already in the block first")
    ap.add_argument("--print", dest="print_only", action="store_true", help="print instead of writing")
    return ap.parse_args(argv)


def configured_url(target: str, name: str) -> str | None:
    """URL of database *name* from the ``DATABASES`` setting in *target* (web.py)."""
    databases: dict = {}
    if os.path.exists(target):
        spec = importlib.util.spec_from_file_location("_mate_target", target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)          # web.py builds its app lazily: no side effects
        databases = getattr(module, "DATABASES", None) or {}
    if name in databases:
        return databases[name]
    if name == "default":
        return None                              # MATE_DB_URL / MATE_DB_* / dbc.ini
    raise ConfigError(f"database {name!r} is not in DATABASES of {target} "
                      f"(known: {', '.join(databases) or 'none'}); add it there or pass --url")


def main(argv=None) -> int:
    args = parse_args(argv)
    if not I.SAFE_IDENT.match(args.db):
        print(f"unsupported database name {args.db!r} (letters, digits and _ only)", file=sys.stderr)
        return 2
    try:
        url = args.url or configured_url(os.path.abspath(args.target), args.db)
    except ConfigError as exc:
        print(f"! {exc}", file=sys.stderr)
        return 2
    db = Database(url)
    tables = I.list_tables(db) if args.all else [t.strip() for t in args.tables.split(",") if t.strip()]
    if not tables:
        print("no tables found", file=sys.stderr)
        return 1
    for opt in ("primary_col", "page"):
        if getattr(args, opt) and len(tables) != 1:
            print(f"--{opt.replace('_', '-')} only works with exactly one table", file=sys.stderr)
            return 2

    def is_editable(t: str) -> bool:
        return args.editable is not None and (args.editable == [] or t in args.editable)

    segments: dict[str, str] = {}
    for t in tables:
        try:
            info = I.reflect_table(db, t, args.primary_col)
        except ConfigError as exc:
            print(f"! {t}: {exc}", file=sys.stderr)
            if not args.all:
                return 1
            continue
        ed = is_editable(t)
        plan = I.plan_columns(info, editable=ed, show_id=args.show_id)
        key = args.page or I.page_key(t, args.db)
        try:
            segments[key] = I.render_table(info, plan, permissions=I.table_permissions(ed), title=I.label(t),
                                           database=args.db, page=key)
        except ConfigError as exc:
            print(f"! {t}: {exc}", file=sys.stderr)
            return 2
        skipped = f", skipped {len(info.skipped)}" if info.skipped else ""
        print(f"  page {key}: {args.db}.{t}, {len(plan)} columns, pk={info.pk}, {'editable' if ed else 'read-only'}{skipped}",
              file=sys.stderr)
        if ed and info.pk_kind != "int":
            print(f"  ! {t}: primary key {info.pk!r} is not an integer; adding rows needs the database "
                  "to generate it", file=sys.stderr)

    if not segments:
        return 1
    if args.print_only:
        print(I.render_block(segments))
        return 0
    present = I.update_file(os.path.abspath(args.target), segments, replace=args.replace)
    print(f"wrote {os.path.abspath(args.target)} ({len(present)} page(s): {', '.join(present)})",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
