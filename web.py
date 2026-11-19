"""MATE application: which database, which tables, and how each table behaves.

This is the one file you edit to configure the app.

1. DATABASES  every database the pages use, by name (``DATABASES`` below).
2. PAGES      the generated block holds one entry per page: the database it connects
              to, the table it shows and its column settings.  Create or refresh it
              from the database with::

                  python tools/generate_columns.py --tables customers,orders
                  python tools/generate_columns.py --all --editable orders
                  python tools/generate_columns.py --db crm --tables contacts

3. TWEAKS     ``OVERRIDES`` changes the generated settings (labels, permissions, titles,
              extra options).  It lives outside the generated block, so regenerating
              never overwrites it.
4. MENU       the start page ``/`` is static (brand bar + menu row).  Every entry in
              ``PAGES`` is a page, opened from the dropdown menu; ``MENU`` groups the
              pages into dropdowns, ``ENABLED_PAGES`` shows only some of them.

Run it with ``python run.py`` or any WSGI server: ``gunicorn web:app``.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

from mate.db import Database
from mate.editor import AjaxTableEditor, ConfigError
from mate.web import create_app

# --------------------------------------------------------------------------
# 1. Settings
# --------------------------------------------------------------------------
# The databases the pages connect to, by name.  Values are SQLAlchemy URLs, e.g.
# "mysql+pymysql://user:password@host/dbname" or "sqlite:///db/northwind.db".  None means
# $MATE_DB_URL, $MATE_DB_HOST/NAME/USER/PASSWORD, dbc.ini, or the local SQLite demo.
# Keep passwords out of this file: read them from the environment, as in the example.
# Each database gets one connection pool, shared by all pages that use it.
DATABASES: dict[str, str | None] = {
    "default": None,
    # "crm": os.environ.get("CRM_DB_URL"),
    "northwind": "sqlite:///" + os.path.join(os.path.dirname(os.path.abspath(__file__)), "db", "northwind.db"),
}

LANGUAGE = os.environ.get("MATE_LANG", "en")     # en de es fr it nl pt-br ru tr zh
BRAND = "SeisTT"                                 # navbar brand (the logo is static/images/logo.png)
PAGE_TITLE = "SeisTT 3.1"                        # appended to the browser tab title
ENABLED_PAGES: list[str] | None = None           # None = all pages in PAGES

# Start page (/): a static page with the brand bar and the menu row below it.
HOME_TITLE = "Welcome"
HOME_HTML = "<p>Choose a page from the menu to open a table.</p>"      # trusted markup

# Menu row with dropdowns.  Each entry is a page key (direct link) or a dropdown:
# {"label": "Label", "pages": [pages]}  (the short form ("Label", [pages]) works too).
# None = one dropdown called "Tables" with every enabled page.  Example:
#     MENU = [("Seismic", ["surveys", "lines"]), ("CRM", ["crm_contacts"]), "orders"]
MENU: list | None = [
    {"label": "Wells", "pages": ["test_data"]},
    {"label": "NorthWind", "pages": ["northwind_Categories", "northwind_Products", "northwind_Customers"]},
]

# Options applied to every page; per-page values in OVERRIDES win.  Names are those
# of the PHP ``setConfig`` calls (camelCase) or their snake_case equivalents.
DEFAULT_CONFIG: dict[str, Any] = {
    "filterPosition": "top-after",
    "paginationLinks": True,
    "iconColPosition": "first",
}

# --------------------------------------------------------------------------
# 2. Generated pages  (tools/generate_columns.py)
# --------------------------------------------------------------------------
# Every page names its database (a key of DATABASES) and table.  Two pages may show the
# same table, or tables with the same name in different databases.
# BEGIN GENERATED PAGES (written by tools/generate_columns.py - re-run it to refresh; put manual changes in OVERRIDES, not in this block)
from mate.fields import (date_field, field, id_field, num_field, txt_field, txtarea_field, yn_field)

PAGES: dict = {}

PAGES['test_data'] = {
    "database": 'default',
    "table": 'test_data',
    "title": 'Test Data',
    "primary_col": 'id',
    "permissions": 'VQSXOHUIF',
    "columns": {
        'id': field(id_field, 'id', ''),
        'ow_project': field(txt_field, 'ow_project', 'T', 'Ow Project'),
        'work_set_id': field(num_field, 'work_set_id', 'T', 'Work Set Id'),
        'work_set_name': field(txt_field, 'work_set_name', 'T', 'Work Set Name'),
        'nr_bh': field(num_field, 'nr_bh', 'T', 'Nr Bh'),
        'create_date': field(date_field, 'create_date', 'T', 'Create Date'),
        'create_user_id': field(txt_field, 'create_user_id', 'T', 'Create User Id'),
        'to_delete': field(num_field, 'to_delete', 'T', 'To Delete'),
        'first_date': field(date_field, 'first_date', 'T', 'First Date'),
        'last_date': field(date_field, 'last_date', 'T', 'Last Date'),
    },
}

# skipped column 'Picture': binary column
PAGES['northwind_Categories'] = {
    "database": 'northwind',
    "table": 'Categories',
    "title": 'Categories',
    "primary_col": 'CategoryID',
    "permissions": 'VQSXOHUIF',
    "columns": {
        'CategoryID': field(id_field, 'CategoryID', ''),
        'CategoryName': field(txt_field, 'CategoryName', 'T', 'Category Name'),
        'Description': field(txt_field, 'Description', 'T', 'Description'),
    },
}

PAGES['northwind_Products'] = {
    "database": 'northwind',
    "table": 'Products',
    "title": 'Products',
    "primary_col": 'ProductID',
    "permissions": 'VQSXOHUIF',
    "columns": {
        'ProductID': field(id_field, 'ProductID', ''),
        'ProductName': field(txt_field, 'ProductName', 'T', 'Product Name'),
        'SupplierID': field(num_field, 'SupplierID', 'T', 'Supplier ID'),
        'CategoryID': field(num_field, 'CategoryID', 'T', 'Category ID'),
        'QuantityPerUnit': field(txt_field, 'QuantityPerUnit', 'T', 'Quantity Per Unit'),
        'UnitPrice': field(num_field, 'UnitPrice', 'T', 'Unit Price'),
        'UnitsInStock': field(num_field, 'UnitsInStock', 'T', 'Units In Stock'),
        'UnitsOnOrder': field(num_field, 'UnitsOnOrder', 'T', 'Units On Order'),
        'ReorderLevel': field(num_field, 'ReorderLevel', 'T', 'Reorder Level'),
        'Discontinued': field(txt_field, 'Discontinued', 'T', 'Discontinued'),
    },
}

PAGES['northwind_Customers'] = {
    "database": 'northwind',
    "table": 'Customers',
    "title": 'Customers',
    "primary_col": 'CustomerID',
    "permissions": 'VQSXOHUIF',
    "columns": {
        'CustomerID': field(id_field, 'CustomerID', 'T', 'Customer ID'),
        'CompanyName': field(txt_field, 'CompanyName', 'T', 'Company Name'),
        'ContactName': field(txt_field, 'ContactName', 'T', 'Contact Name'),
        'ContactTitle': field(txt_field, 'ContactTitle', 'T', 'Contact Title'),
        'Address': field(txt_field, 'Address', 'T', 'Address'),
        'City': field(txt_field, 'City', 'T', 'City'),
        'Region': field(txt_field, 'Region', 'T', 'Region'),
        'PostalCode': field(txt_field, 'PostalCode', 'T', 'Postal Code'),
        'Country': field(txt_field, 'Country', 'T', 'Country'),
        'Phone': field(txt_field, 'Phone', 'T', 'Phone'),
        'Fax': field(txt_field, 'Fax', 'T', 'Fax'),
    },
}
# END GENERATED PAGES

# --------------------------------------------------------------------------
# 3. Overrides (kept when the block above is regenerated)
# --------------------------------------------------------------------------
HELP_HTML = """<strong>General</strong><br>
A nightly cronjob will report all available well lists for all OpenWorks projects in the NAM OW
database and list them here. All well lists created with the WCC app will be prefixed with
<strong>wcc_</strong>. Filtering, sorting and ordering are identical to the FastFileFinder tool.
<p></p>
<strong>Managing Well lists</strong><br>
Managing well lists in OW is a cumbersome process so you could manage the well lists from here.
Although currently only deleting well lists is possible. To delete a well list click on the edit
icon. You can then toggle between <strong>Yes</strong> and <strong>No</strong> for lists to be
deleted. The well list will not be immediately deleted but rather during the nightly running jobs."""


def replace(column: dict[str, Any]) -> dict[str, Any]:
    """Use *column* instead of merging it into the generated definition."""
    return {**column, "_replace": True}


OVERRIDES: dict[str, dict[str, Any]] = {
    # "page_key": {
    #     "database": "crm",                      # connect this page to another database
    #     "table": "contacts",                    # ... or another table
    #     "title": "Page title",                  # panel heading
    #     "nav_title": "Short name",              # navigation link text
    #     "permissions": "VQSXOHUIFE",            # table permission letters (see mate/editor.py)
    #     "config": {"editInPlace": True},        # any AjaxTableEditor option
    #     "columns": {
    #         "name": {"display_text": "Customer"},          # merged into the generated column
    #         "active": replace(field(yn_field, "active", "TE", "Active?")),
    #         "internal_notes": None,                         # remove the column
    #     },
    # },

    # Demo: the OpenWorks Well List Manager from the original PHP app.  Everything is
    # read-only except the Yes/No "Delete?" flag, which is edited in place.
    "test_data": {
        "title": "OpenWorks Well List Manager",
        "nav_title": "Well Lists",
        "permissions": "VQSXOHUIFE",
        "config": {
            "editInPlace": True,
            "helpHtml": HELP_HTML,
            "addRowTitle": "Add Login Info",
            "editRowTitle": "Edit Login Info",
            "viewRowTitle": "View Login Info",
        },
        "columns": {
            "ow_project": {"display_text": "OW Project"},
            "work_set_id": {"display_text": "Well List Id"},
            "work_set_name": {"display_text": "Well List Name"},
            "to_delete": replace(field(yn_field, "to_delete", "TE", "Delete?")),
        },
    },
}

# --------------------------------------------------------------------------
# Building the app (normally nothing to change below)
# --------------------------------------------------------------------------
def enabled_pages() -> list[str]:
    return list(ENABLED_PAGES) if ENABLED_PAGES is not None else list(PAGES)


def page_setting(page: str, key: str) -> Any:
    """A page setting: the override if present, else the generated value."""
    if page not in PAGES:
        raise ConfigError(f"page {page!r} is not in PAGES; run tools/generate_columns.py --tables <table>")
    ov = OVERRIDES.get(page, {})
    return ov[key] if key in ov else PAGES[page].get(key)


def open_databases(names: list[str] | None = None) -> dict[str, Database]:
    """One :class:`Database` per name in *names* (default: those the enabled pages use)."""
    if names is None:
        names = list(dict.fromkeys(page_setting(p, "database") or "default" for p in enabled_pages()))
    out: dict[str, Database] = {}
    for name in names:
        if name not in DATABASES and name != "default":
            raise ConfigError(f"database {name!r} is not in DATABASES (known: {', '.join(DATABASES) or 'none'})")
        out[name] = Database(DATABASES.get(name))
    return out


def _db_for(page: str, db: Database | Mapping[str, Database]) -> Database:
    if isinstance(db, Database):           # one database for every page (tests, simple setups)
        return db
    name = page_setting(page, "database") or "default"
    if name not in db:
        raise ConfigError(f"page {page!r} uses database {name!r}, which is not in DATABASES")
    return db[name]


def build_editor(page: str, db: Database | Mapping[str, Database] | None = None,
                 lang: str = LANGUAGE) -> AjaxTableEditor:
    """Combine the generated settings and the overrides of *page* into an editor.

    *db* is one database for every page, or a ``{name: Database}`` mapping such as
    :func:`open_databases` returns (default: open the database the page names).
    """
    table = page_setting(page, "table") or page
    if db is None:
        db = open_databases([page_setting(page, "database") or "default"])
    spec, ov = PAGES[page], OVERRIDES.get(page, {})

    columns = {name: dict(col) for name, col in spec["columns"].items()}
    for name, change in (ov.get("columns") or {}).items():
        if change is None:
            columns.pop(name, None)
        elif change.get("_replace"):
            columns[name] = {k: v for k, v in change.items() if k != "_replace"}
        elif name in columns:
            columns[name].update(change)
        else:
            columns[name] = dict(change)

    editor = AjaxTableEditor(table, ov.get("primary_col", spec["primary_col"]), None,
                             ov.get("permissions", spec["permissions"]), columns,
                             db=_db_for(page, db), lang=lang)
    options = {"tableTitle": ov.get("title", spec["title"]),
               "instanceName": f"mate_{page}_",
               **DEFAULT_CONFIG, **(ov.get("config") or {})}
    if "nav_title" in ov:
        options["navTitle"] = ov["nav_title"]
    for name, value in options.items():
        editor.set_config(name, value)
    return editor


def build_editors(db: Database | Mapping[str, Database] | None = None,
                  lang: str = LANGUAGE) -> dict[str, AjaxTableEditor]:
    """``{page: editor}`` for every enabled page, sharing one connection per database."""
    pages = enabled_pages()
    if db is None:
        db = open_databases()
    return {page: build_editor(page, db, lang) for page in pages}


def build_app(db: Database | Mapping[str, Database] | None = None, **kwargs: Any):
    """The Flask app.  *db*: one database for all pages, ``{name: Database}``, or None
    to connect every page to the database named in its settings."""
    kwargs.setdefault("brand", BRAND)
    kwargs.setdefault("page_title", PAGE_TITLE)
    kwargs.setdefault("menu", MENU)
    kwargs.setdefault("home_title", HOME_TITLE)
    kwargs.setdefault("home_html", HOME_HTML)
    return create_app(build_editors(db), **kwargs)


_app = None


def __getattr__(name: str) -> Any:
    """``web.app`` is built on first use, so importing this module has no side effects
    (the generator script reads ``DATABASES`` from it).  ``gunicorn web:app`` works as usual."""
    global _app
    if name == "app":
        if _app is None and PAGES:
            _app = build_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
