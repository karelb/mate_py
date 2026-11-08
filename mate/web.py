"""Flask integration.

Replaces the request handling in ``example/index.php`` (the ``$_POST['json']``
dispatcher, the ``?mate_export`` CSV download and the HTML page) and
``include/Common.php`` (page chrome).

Endpoints (all JSON unless noted).  The PHP action names are given in brackets:

=======================  ===========================================================
``GET  /``                the page (shell only; the table is drawn by mate.js)
``POST /api/table``       rows + paging + UI flags    [update_html, handle_search,
                           page_num_changed, display_num_changed, order_by_changed,
                           handle_filter_search, clear_filters, advanced_search ...]
``POST /api/view``        view-row dialog data        [view_row]
``POST /api/edit-form``   inputs for editing a row    [edit_in_place / edit_row]
``POST /api/update``      save an edited row          [update_rows_in_place / update_row]
``POST /api/add-form``    inputs for a new row        [add_row]
``POST /api/insert``      create a row                [insert_row]
``POST /api/delete``      delete rows                 [delete_rows]
``POST /api/copy``        copy rows                   [copy_rows]
``POST /api/columns``     show/hide + order settings  [show_hide_columns, order_columns_screen]
``POST /api/columns/save``  persist hide/order choice [update_hidden_columns, update_column_order,
                                                       reset_column_order]
``POST /api/distinct``    distinct values of a column (Bootstrap "list" icon)
``POST /api/action``      user defined actions        [doDefault / userActions]
``GET  /export.csv``      CSV download                [?mate_export=1]
=======================  ===========================================================

Security notes
--------------
* State-changing and data endpoints require the ``X-Mate-Request`` header; a
  cross-site form post cannot set it, so this doubles as CSRF protection.
* Column/row permissions are enforced in :class:`mate.editor.AjaxTableEditor`
  (``PermissionDenied`` -> HTTP 403).
* Database errors return a generic message unless ``MATE_DEBUG`` is set.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
from typing import Any, Callable

from flask import Blueprint, Flask, Response, abort, jsonify, render_template, request, session

from . import fields as F
from .db import QueryError
from .editor import AjaxTableEditor, ConfigError, PermissionDenied, ValidationError

log = logging.getLogger("mate")

bp = Blueprint("mate", __name__, template_folder="templates", static_folder="static",
               static_url_path="/mate-static")

REQUIRED_HEADER = "X-Mate-Request"


def _editor() -> AjaxTableEditor:
    from flask import current_app
    return current_app.extensions["mate_editor"]


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
    if request.path.startswith("/api/"):
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
# Page
# --------------------------------------------------------------------------
@bp.get("/")
def index():
    ed = _editor()
    from flask import current_app
    return render_template(
        "index.html",
        instance=ed.cfg["instance_name"],
        title=current_app.config.get("MATE_PAGE_TITLE", "SeisTT 3.1"),
        brand=current_app.config.get("MATE_BRAND", "SeisTT"),
        lang=ed.lang.code,
        default_state={"orderByColumn": ed.primary_col},
    )


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
@bp.post("/api/table")
def api_table():
    ed = _editor()
    body = _json()
    return jsonify(ed.get_table_data(body.get("state"), _prefs(ed)))


@bp.post("/api/view")
def api_view():
    ed = _editor()
    return jsonify(ed.view_row(_json().get("id"), _prefs(ed)))


@bp.post("/api/edit-form")
def api_edit_form():
    ed = _editor()
    return jsonify(ed.edit_form(_json().get("id"), _prefs(ed)))


@bp.post("/api/update")
def api_update():
    ed = _editor()
    body = _json()
    values = body.get("values") if isinstance(body.get("values"), dict) else {}
    new_pk = ed.update_row(values, body.get("id"), in_place=bool(body.get("in_place")),
                           prefs=_prefs(ed), row_num=body.get("row_num", ""))
    return jsonify(ok=True, id=new_pk)


@bp.post("/api/add-form")
def api_add_form():
    ed = _editor()
    return jsonify(ed.add_form(_prefs(ed)))


@bp.post("/api/insert")
def api_insert():
    ed = _editor()
    body = _json()
    values = body.get("values") if isinstance(body.get("values"), dict) else {}
    return jsonify(ok=True, id=ed.insert_row(values, prefs=_prefs(ed)))


@bp.post("/api/delete")
def api_delete():
    ed = _editor()
    ids = _json().get("ids")
    if not isinstance(ids, list):
        abort(400)
    return jsonify(ok=True, deleted=ed.delete_rows(ids))


@bp.post("/api/copy")
def api_copy():
    ed = _editor()
    ids = _json().get("ids")
    if not isinstance(ids, list):
        abort(400)
    return jsonify(ok=True, new_ids=ed.copy_rows(ids, _prefs(ed)))


@bp.post("/api/columns")
def api_columns():
    ed = _editor()
    return jsonify(ed.column_settings(_prefs(ed)))


@bp.post("/api/columns/save")
def api_columns_save():
    ed = _editor()
    body = _json()
    prefs = _prefs(ed)
    if "visible" in body and isinstance(body["visible"], dict):
        prefs = ed.update_hidden_columns(prefs, body["visible"])
    if body.get("reset_order"):
        prefs = ed.reset_column_order(prefs)
    elif isinstance(body.get("order"), list):
        prefs = ed.update_column_order(prefs, [str(c) for c in body["order"]])
    _save_prefs(ed, prefs)
    return jsonify(ok=True)


@bp.post("/api/distinct")
def api_distinct():
    ed = _editor()
    body = _json()
    return jsonify(values=ed.distinct_values(body.get("state"), str(body.get("col", "")), _prefs(ed)))


@bp.post("/api/action")
def api_action():
    ed = _editor()
    body = _json()
    return jsonify(result=ed.user_action(str(body.get("action", "")), body.get("info")))


@bp.get("/export.csv")
def export_csv():
    ed = _editor()
    raw = request.args.get("session_data", "")
    state: dict[str, Any] = {}
    if raw:
        try:
            state = json.loads(base64.b64decode(raw.encode("ascii"), validate=True))
        except Exception:  # noqa: BLE001
            abort(400, "bad session_data")
    body = ed.export_csv(state, _prefs(ed))
    # utf-8 BOM so Excel on Windows detects the encoding (same as the original)
    payload = "\ufeff" + body
    return Response(
        payload.encode("utf-8"),
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
def create_app(editor: AjaxTableEditor, *, secret_key: str | None = None,
               current_user: Callable[[], str | None] | None = None) -> Flask:
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
    )
    app.extensions["mate_editor"] = editor
    if current_user:
        F.current_user = current_user
    app.register_blueprint(bp)

    @app.after_request
    def _headers(resp: Response) -> Response:
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    return app
