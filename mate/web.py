"""Flask integration: one page per editor, with navigation between them.

Every page has its own :class:`~mate.editor.AjaxTableEditor`, and with it its own
database connection and table, so pages in one menu can show different databases.

Replaces the request handling in ``example/index.php`` (the ``$_POST['json']``
dispatcher, the ``?mate_export`` CSV download and the HTML page) and
``include/Common.php`` (page chrome).

URLs (``<page>`` is the page key; all API endpoints are JSON).  The PHP
action names are given in brackets:

===============================  ===========================================================
``GET  /``                        static start page (brand bar + dropdown menu, no database)
``GET  /t/<page>/``               the page (shell only; the table is drawn by mate.js)
``POST /t/<page>/api/table``      rows + paging + UI flags    [update_html, handle_search,
                                   page_num_changed, display_num_changed, order_by_changed,
                                   handle_filter_search, clear_filters, advanced_search ...]
``POST .../api/view``             view-row dialog data        [view_row]
``POST .../api/edit-form``        inputs for editing a row    [edit_in_place / edit_row]
``POST .../api/update``           save an edited row          [update_rows_in_place / update_row]
``POST .../api/add-form``         inputs for a new row        [add_row]
``POST .../api/insert``           create a row                [insert_row]
``POST .../api/delete``           delete rows                 [delete_rows]
``POST .../api/copy``             copy rows                   [copy_rows]
``POST .../api/columns``          show/hide + order settings  [show_hide_columns, order_columns_screen]
``POST .../api/columns/save``     persist hide/order choice   [update_hidden_columns, ...]
``POST .../api/distinct``         distinct values of a column (Bootstrap "list" icon)
``POST .../api/action``           user defined actions        [doDefault / userActions]
``GET  /t/<page>/export.csv``     CSV download                [?mate_export=1]
===============================  ===========================================================

Navigation: a brand bar on top and, underneath, a menu row with dropdowns whose entries open
the pages.  The menu layout is the ``menu`` argument of :func:`create_app`.

Security notes
--------------
* Data endpoints require the ``X-Mate-Request`` header; a cross-site form post
  cannot set it, so this doubles as CSRF protection.
* Column/row permissions are enforced in :class:`mate.editor.AjaxTableEditor`
  (``PermissionDenied`` -> HTTP 403), per page.
* Database errors return a generic message unless ``MATE_DEBUG`` is set.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import secrets
from typing import Any, Callable, Iterable, Mapping

from flask import (Blueprint, Flask, Response, abort, current_app, jsonify,
                   render_template, request, session, url_for)

from . import fields as F
from .db import QueryError
from .editor import AjaxTableEditor, ConfigError, PermissionDenied, ValidationError

log = logging.getLogger("mate")

bp = Blueprint("mate", __name__, template_folder="templates", static_folder="static",
               static_url_path="/mate-static")

REQUIRED_HEADER = "X-Mate-Request"
SAFE_PAGE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")     # page keys end up in URLs and DOM ids


def _editor(page: str) -> AjaxTableEditor:
    ed = current_app.extensions["mate_editors"].get(page)
    if ed is None:
        abort(404)
    return ed


def _prefs(ed: AjaxTableEditor) -> dict[str, Any]:
    return dict((session.get("mate") or {}).get(ed.cfg["instance_name"], {}))


def _save_prefs(ed: AjaxTableEditor, prefs: dict[str, Any]) -> None:
    store = dict(session.get("mate") or {})
    store[ed.cfg["instance_name"]] = prefs
    session["mate"] = store
    session.permanent = True


def _json() -> dict[str, Any]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.before_request
def _guard():
    if "/api/" in request.path:
        if request.method != "POST" or not request.headers.get(REQUIRED_HEADER):
            abort(400, "missing request header")


@bp.errorhandler(PermissionDenied)
def _denied(_exc):
    return jsonify(error="Not allowed."), 403


@bp.errorhandler(ValidationError)
def _invalid(exc: ValidationError):
    return jsonify(error=" ".join(exc.messages) or "Validation failed.",
                   invalid_fields=list(exc.fields.keys()),
                   invalid_labels=exc.fields), 422


@bp.errorhandler(QueryError)
def _query_error(exc: QueryError):
    log.error("query failed: %s | %s | %s", exc, exc.sql, exc.params)
    if os.environ.get("MATE_DEBUG"):
        return jsonify(error=str(exc), sql=exc.sql), 500
    return jsonify(error="A database error occurred."), 500


@bp.errorhandler(ConfigError)
def _config_error(exc: ConfigError):
    return jsonify(error=str(exc)), 400


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
MenuSpec = list  # entries: "page" | ("Label", ["page", ...]) | {"label": ..., "pages": [...]}


def normalize_menu(menu: Any, editors: Mapping[str, AjaxTableEditor]) -> list[dict[str, Any]]:
    """Validate the menu setting.  ``None`` = one "Tables" dropdown with every page."""
    if menu is None:
        menu = [("Tables", list(editors))]
    out: list[dict[str, Any]] = []

    def check(name: Any) -> str:
        if name not in editors:
            raise ConfigError(f"menu refers to unknown page {name!r} (known: {', '.join(editors) or 'none'})")
        return name

    for entry in menu:
        if isinstance(entry, str):
            out.append({"page": check(entry)})
            continue
        if isinstance(entry, Mapping):
            label, pages = entry["label"], entry.get("pages", entry.get("tables", []))
        else:
            label, pages = entry
        out.append({"label": str(label), "pages": [check(p) for p in pages]})
    return out


def menu_for(active: str | None) -> list[dict[str, Any]]:
    """Menu entries with titles, urls and the active flag, ready for the template."""
    editors = current_app.extensions["mate_editors"]

    def item(name: str) -> dict[str, Any]:
        ed = editors[name]
        return {"title": ed.cfg["nav_title"] or ed.cfg["table_title"],
                "url": url_for("mate.table_page", page=name), "active": name == active}

    out = []
    for entry in current_app.extensions["mate_menu"]:
        if "page" in entry:
            out.append(item(entry["page"]))
        else:
            children = [item(p) for p in entry["pages"]]
            out.append({"title": entry["label"], "children": children,
                        "active": any(c["active"] for c in children)})
    return out


def _page_context(lang: str) -> dict[str, Any]:
    cfg = current_app.config
    return {"lang": lang, "brand": cfg["MATE_BRAND"]}


@bp.get("/")
def index():
    """Static start page: brand bar, menu row and a short welcome text.  No database access."""
    cfg = current_app.config
    first = next(iter(current_app.extensions["mate_editors"].values()))
    return render_template(
        "home.html", **_page_context(first.lang.code), home_active=True, menu=menu_for(None),
        title=f"{cfg['MATE_HOME_TITLE']} - {cfg['MATE_PAGE_TITLE']}",
        home_title=cfg["MATE_HOME_TITLE"], home_html=cfg["MATE_HOME_HTML"])


@bp.get("/t/<page>/")
def table_page(page: str):
    ed = _editor(page)
    cfg = current_app.config
    urls = {key: url_for(f"mate.{endpoint}", page=page) for key, endpoint in (
        ("table", "api_table"), ("view", "api_view"), ("editForm", "api_edit_form"),
        ("update", "api_update"), ("addForm", "api_add_form"), ("insert", "api_insert"),
        ("del", "api_delete"), ("copy", "api_copy"), ("columns", "api_columns"),
        ("columnsSave", "api_columns_save"), ("distinct", "api_distinct"), ("exportCsv", "export_csv"))}
    return render_template(
        "index.html",
        **_page_context(ed.lang.code),
        instance=ed.cfg["instance_name"],
        title=f"{ed.cfg['table_title']} - {cfg['MATE_PAGE_TITLE']}",
        menu=menu_for(page),
        urls=urls,
        default_state={"orderByColumn": ed.primary_col},
    )


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
@bp.post("/t/<page>/api/table")
def api_table(page: str):
    ed = _editor(page)
    return jsonify(ed.get_table_data(_json().get("state"), _prefs(ed)))


@bp.post("/t/<page>/api/view")
def api_view(page: str):
    ed = _editor(page)
    return jsonify(ed.view_row(_json().get("id"), _prefs(ed)))


@bp.post("/t/<page>/api/edit-form")
def api_edit_form(page: str):
    ed = _editor(page)
    return jsonify(ed.edit_form(_json().get("id"), _prefs(ed)))


@bp.post("/t/<page>/api/update")
def api_update(page: str):
    ed = _editor(page)
    body = _json()
    values = body.get("values") if isinstance(body.get("values"), dict) else {}
    new_pk = ed.update_row(values, body.get("id"), in_place=bool(body.get("in_place")),
                           prefs=_prefs(ed), row_num=body.get("row_num", ""))
    return jsonify(ok=True, id=new_pk)


@bp.post("/t/<page>/api/add-form")
def api_add_form(page: str):
    ed = _editor(page)
    return jsonify(ed.add_form(_prefs(ed)))


@bp.post("/t/<page>/api/insert")
def api_insert(page: str):
    ed = _editor(page)
    values = _json().get("values")
    return jsonify(ok=True, id=ed.insert_row(values if isinstance(values, dict) else {}, prefs=_prefs(ed)))


@bp.post("/t/<page>/api/delete")
def api_delete(page: str):
    ed = _editor(page)
    ids = _json().get("ids")
    if not isinstance(ids, list):
        abort(400)
    return jsonify(ok=True, deleted=ed.delete_rows(ids))


@bp.post("/t/<page>/api/copy")
def api_copy(page: str):
    ed = _editor(page)
    ids = _json().get("ids")
    if not isinstance(ids, list):
        abort(400)
    return jsonify(ok=True, new_ids=ed.copy_rows(ids, _prefs(ed)))


@bp.post("/t/<page>/api/columns")
def api_columns(page: str):
    ed = _editor(page)
    return jsonify(ed.column_settings(_prefs(ed)))


@bp.post("/t/<page>/api/columns/save")
def api_columns_save(page: str):
    ed = _editor(page)
    body = _json()
    prefs = _prefs(ed)
    if isinstance(body.get("visible"), dict):
        prefs = ed.update_hidden_columns(prefs, body["visible"])
    if body.get("reset_order"):
        prefs = ed.reset_column_order(prefs)
    elif isinstance(body.get("order"), list):
        prefs = ed.update_column_order(prefs, [str(c) for c in body["order"]])
    _save_prefs(ed, prefs)
    return jsonify(ok=True)


@bp.post("/t/<page>/api/distinct")
def api_distinct(page: str):
    ed = _editor(page)
    body = _json()
    return jsonify(values=ed.distinct_values(body.get("state"), str(body.get("col", "")), _prefs(ed)))


@bp.post("/t/<page>/api/action")
def api_action(page: str):
    ed = _editor(page)
    body = _json()
    return jsonify(result=ed.user_action(str(body.get("action", "")), body.get("info")))


@bp.get("/t/<page>/export.csv")
def export_csv(page: str):
    ed = _editor(page)
    raw = request.args.get("session_data", "")
    state: dict[str, Any] = {}
    if raw:
        try:
            state = json.loads(base64.b64decode(raw.encode("ascii"), validate=True))
        except Exception:  # noqa: BLE001
            abort(400, "bad session_data")
    body = ed.export_csv(state, _prefs(ed))
    # utf-8 BOM so Excel on Windows detects the encoding (same as the original)
    return Response(
        ("﻿" + body).encode("utf-8"),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{ed.table_name}.csv"',
            "Cache-Control": "no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


# --------------------------------------------------------------------------
# App factory
# --------------------------------------------------------------------------
def create_app(editors: AjaxTableEditor | Mapping[str, AjaxTableEditor] | Iterable[AjaxTableEditor], *,
               secret_key: str | None = None, brand: str = "MATE", page_title: str = "MATE",
               menu: MenuSpec | None = None, home_title: str = "Welcome",
               home_html: str = "<p>Choose a page from the menu to open a table.</p>",
               current_user: Callable[[], str | None] | None = None) -> Flask:
    """Build the Flask app.  *editors* is one editor, a ``{page: editor}`` dict or a list
    (then the page key is the table name).  Each editor carries its own database, so
    every page can connect to a different database and table.

    *menu* defines the dropdown row under the brand bar: ``None`` for a single "Tables"
    dropdown, or a list whose entries are a page key (direct link) or
    ``("Label", ["page", ...])`` (dropdown).  *home_html* is trusted markup for the start page.
    """
    if isinstance(editors, AjaxTableEditor):
        editors = [editors]
    items = list(editors.items()) if isinstance(editors, Mapping) else [(e.table_name, e) for e in editors]
    if not items:
        raise ConfigError("no tables configured: run tools/generate_columns.py")
    ordered: dict[str, AjaxTableEditor] = dict(items)
    for page in ordered:
        if not SAFE_PAGE.match(page):
            raise ConfigError(f"unsupported page key {page!r} (letters, digits and _ only)")
    names = [e.cfg["instance_name"] for e in ordered.values()]
    if len(set(names)) != len(names):
        raise ConfigError("every editor needs its own instanceName (it keys the saved column settings)")

    app = Flask(__name__)
    key = secret_key or os.environ.get("MATE_SECRET_KEY")
    if not key:
        key = secrets.token_hex(32)
        log.warning("MATE_SECRET_KEY not set: using a random key, column preferences "
                    "will reset whenever the process restarts.")
    app.secret_key = key
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 365 * 2,
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        MATE_BRAND=brand,
        MATE_PAGE_TITLE=page_title,
        MATE_HOME_TITLE=home_title,
        MATE_HOME_HTML=home_html,
    )
    app.extensions["mate_editors"] = ordered
    app.extensions["mate_menu"] = normalize_menu(menu, ordered)
    if current_user:
        F.current_user = current_user
    app.register_blueprint(bp)

    @app.after_request
    def _headers(resp: Response) -> Response:
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if "/api/" in request.path:
            resp.headers["Cache-Control"] = "no-store"
        return resp

    return app
