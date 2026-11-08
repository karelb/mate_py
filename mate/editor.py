"""Core table editor.

Python port of ``php/mate/AjaxTableEditor.php`` and its Bootstrap subclass
``BSAjaxTableEditor.php`` ("Mysql Ajax Table Editor", MATE).

What changed architecturally
----------------------------
The PHP class generated HTML on the server and replied with a list of
"replace this DOM node / run this JavaScript" commands.  This port keeps all of
the *logic* (query building, searching, filtering, sorting, paging, permission
checks, validation, CRUD, CSV export, column hiding/ordering) but returns plain
data (dicts, JSON-serialisable).  The browser side (``static/js/mate.js``)
renders it.  Consequently:

* there is no ``setInnerHtml`` / ``addJavascript`` command channel,
* view state (search, filters, sort, page, rows per page) is an explicit
  :class:`ViewState` passed in by the client - the equivalent of the PHP
  ``sessionData`` blob - and the server stays stateless,
* the per-user "hidden/ordered columns" preference lives in a signed Flask
  session instead of an ``mcrypt`` cookie (``mcrypt`` was removed from PHP 7.2
  and the original key was hard coded in the source).

Permission letters
------------------
Table level (``permissions`` string, case-insensitive):

====  ==========================================
A     add rows               C   copy rows
D     delete rows            E   edit rows
V     view-row dialog        I   per-row icon column
M     multi-select checkboxes
Q     quick search           S   advanced search
F     column filters         X   CSV export
H     show/hide columns      O   order columns
U     rows-per-page selector
====  ==========================================

Column-level letters are documented in :mod:`mate.fields`.
"""
from __future__ import annotations

import copy
import datetime as _dt
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from . import fields as F
from .db import Database, QueryError
from .lang import LangVars


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------
class PermissionDenied(Exception):
    """Replaces PHP's ``handleHacking()`` (which called ``exit()``)."""


class ValidationError(Exception):
    """One or more fields failed validation.  ``fields`` maps column -> label."""

    def __init__(self, fields: Mapping[str, str], messages: Iterable[str] = ()):
        super().__init__("validation failed")
        self.fields = dict(fields)
        self.messages = list(messages)


class ConfigError(Exception):
    pass


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def add_tick_marks(s: str) -> str:
    """``a.b`` -> ```a`.`b```  (same as the PHP helper)."""
    return "`" + "`.`".join(s.split(".")) + "`"


def _pname(s: str) -> str:
    return re.sub(r"\W", "_", s)


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _php_round(x: float) -> int:
    return int(math.floor(x + 0.5))


def _has(s: str | None, letter: str) -> bool:
    """PHP ``stristr($s, $letter) !== false``."""
    return bool(s) and letter.lower() in s.lower()


_DATE_PATTERNS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y",
    "%b %d, %Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S",
)


def parse_date(s: str) -> _dt.datetime | None:
    s = (s or "").strip()
    for p in _DATE_PATTERNS:
        try:
            return _dt.datetime.strptime(s[:19] if p.startswith("%Y-%m-%d") else s, p)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
_CONFIG_DEFAULTS: dict[str, Any] = {
    # titles
    "table_title": None, "add_row_title": None, "edit_row_title": None,
    "edit_mult_title": None, "view_row_title": None, "show_hide_title": None,
    "order_col_title": None, "help_html": "",
    # paging
    "default_display_num": 20, "display_num_inc": 5, "max_disp_num": 200,
    "pagination_links": False, "page_percent": 20, "page_range": 10,
    "page_begin": 5, "page_end": 5, "show_all": 200,
    # features
    "edit_in_place": False, "add_in_place": False, "persistent_add_form": None,
    "allow_edit_mult": True, "record_info": True, "use_highlight": True,
    "remove_criteria": False, "def_num_adv_searches": 3,
    "icon_col_position": "last", "icon_title": "", "remove_icons": "",
    "filter_position": "bottom", "display_filter_btns": True,
    "convert_range_dates": True, "default_db_date_format": "%Y-%m-%d %H:%M:%S",
    "req_marker": "*", "view_query": False,
    # css hints (carried through to the browser)
    "table_info": "", "view_table_info": "", "edit_table_info": "",
    "add_table_info": "", "show_hide_table_info": "",
    # sql
    "db_name": None, "sql_filters": "", "having_filters": "", "custom_join": "",
    "group_by_clause": "", "extra_order_by_info": "",
    # export
    "export_delimiter": ",", "export_line_break": "\r\n",
    # hooks
    "after_add_fun": None, "after_edit_fun": None, "after_copy_fun": None,
    "after_delete_fun": None, "before_delete_fun": None, "before_edit_fun": None,
    "user_insert_fun": None, "user_update_fun": None, "user_delete_fun": None,
    "handle_hacking_fun": None, "view_html_fun": None, "user_actions": None,
    "modify_row_sets": None,
    # naming
    "instance_name": "mate1_",
}

# PHP-only knobs that make no sense without server-rendered HTML.  Accepted and
# ignored so ported ``setConfig`` calls keep working.
_IGNORED_CONFIG = {
    "user_buttons", "user_icons", "user_columns", "extra_row_info", "val_error_styles",
    "no_val_error_styles", "storage_type", "default_table_class", "default_upload_max_size",
    "file_uploading", "disable_mult_cb_fun", "add_screen_fun", "edit_screen_fun",
    "view_screen_fun", "table_screen_fun", "show_hide_screen_fun", "order_col_screen_fun",
    "edit_in_place_fun", "add_in_place_fun", "as_column_info", "query_line_break",
    "mysql_fun_replace_str", "replace_with_id", "replace_with_row_num_str", "debug",
    "escape_html", "user_def_display", "mate_user_id", "table_info", "view_table_info",
}


# --------------------------------------------------------------------------
# View state (the PHP "sessionData")
# --------------------------------------------------------------------------
@dataclass
class ViewState:
    start: int = 0
    display_num: int = 20
    search_type: str = "quick"           # quick | advanced
    search_string: str = ""
    match_all: bool = True
    num_adv_searches: int = 3
    adv_searches: list[dict[str, str]] = field(default_factory=list)
    filter_searches: dict[str, str] = field(default_factory=dict)
    order_by_column: str = ""
    asc_or_desc: str = "asc"

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start, "displayNum": self.display_num,
            "searchType": self.search_type, "searchString": self.search_string,
            "matchAll": self.match_all, "numAdvSearches": self.num_adv_searches,
            "advSearches": self.adv_searches, "filterSearches": self.filter_searches,
            "orderByColumn": self.order_by_column, "ascOrDesc": self.asc_or_desc,
        }


@dataclass
class Built:
    """A fully assembled query (the PHP object kept these as properties)."""
    cols: dict[str, dict[str, Any]]
    select: str
    join: str
    where: str
    group_by: str
    having: str
    params: dict[str, Any]

    def sql(self, tail: str = "") -> str:
        return " ".join(
            p for p in (self.select, self.join, self.where, self.group_by, self.having, tail) if p
        )


# --------------------------------------------------------------------------
# The editor
# --------------------------------------------------------------------------
class AjaxTableEditor:
    def __init__(
        self,
        table_name: str,
        primary_col: str,
        error_fun: Callable[..., Any] | None,
        permissions: str,
        table_columns: Mapping[str, Mapping[str, Any]],
        *,
        db: Database | None = None,
        lang: str = "en",
    ):
        self.table_name = table_name
        self.primary_col = primary_col
        self.error_fun = error_fun
        self.permissions = permissions
        self.table_columns: dict[str, dict[str, Any]] = {k: dict(v) for k, v in table_columns.items()}
        self.db = db or Database()
        self.lang = LangVars(lang)
        self.cfg: dict[str, Any] = dict(_CONFIG_DEFAULTS)
        for k, v in self.table_columns.items():
            v.setdefault("perms", "")
            v.setdefault("display_text", k)
        if primary_col not in self.table_columns:
            raise ConfigError(f"primary column {primary_col!r} must be present in table_columns")
        self._apply_title_defaults()

    # -- configuration -----------------------------------------------------
    def _apply_title_defaults(self) -> None:
        L = self.lang
        c = self.cfg
        c["table_title"] = c["table_title"] or self.table_name.replace("_", " ").title()
        c["add_row_title"] = c["add_row_title"] or L.ttlAddRow
        c["edit_row_title"] = c["edit_row_title"] or L.ttlEditRow
        c["edit_mult_title"] = c["edit_mult_title"] or L.ttlEditMult
        c["view_row_title"] = c["view_row_title"] or L.ttlViewRow
        c["show_hide_title"] = c["show_hide_title"] or L.ttlShowHide
        c["order_col_title"] = c["order_col_title"] or L.ttlOrderCols

    def set_config(self, var: str, val: Any) -> None:
        """``setConfig('editInPlace', true)`` -> ``set_config('editInPlace', True)``.

        camelCase (PHP) and snake_case names are both accepted.
        """
        key = _snake(var)
        if key in _IGNORED_CONFIG and key not in self.cfg:
            return
        if key not in self.cfg:
            raise ConfigError(f"unknown config option {var!r}")
        self.cfg[key] = val
        if key.endswith("_title"):
            self._apply_title_defaults()

    # shortcuts ------------------------------------------------------------
    def __getattr__(self, name: str) -> Any:  # cfg values readable as attributes
        cfg = self.__dict__.get("cfg")
        if cfg is not None and name in cfg:
            return cfg[name]
        raise AttributeError(name)

    @property
    def db_and_table(self) -> str:
        return f"{self.db_name}.{self.table_name}" if self.cfg["db_name"] else self.table_name

    def can(self, letter: str) -> bool:
        return _has(self.permissions, letter)

    @staticmethod
    def col_can(info: Mapping[str, Any], letter: str) -> bool:
        return _has(info.get("perms", ""), letter)

    def deny(self) -> None:
        fn = self.cfg["handle_hacking_fun"]
        if callable(fn):
            fn(self.cfg["instance_name"])
        raise PermissionDenied("not allowed")

    # -- state -------------------------------------------------------------
    def make_state(self, raw: Mapping[str, Any] | None = None) -> ViewState:
        """Sanitise untrusted client state."""
        raw = raw or {}
        c = self.cfg

        def as_int(v: Any, default: int) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return default

        st = ViewState()
        st.display_num = min(max(as_int(raw.get("displayNum"), c["default_display_num"]), 1),
                             max(c["max_disp_num"], c["default_display_num"]))
        st.start = max(as_int(raw.get("start"), 0), 0)
        st.search_type = "advanced" if raw.get("searchType") == "advanced" else "quick"
        st.search_string = str(raw.get("searchString") or "")
        st.match_all = bool(raw.get("matchAll", True))
        st.num_adv_searches = max(as_int(raw.get("numAdvSearches"), c["def_num_adv_searches"]), 1)
        st.num_adv_searches = min(st.num_adv_searches, 50)
        advs = raw.get("advSearches") or []
        if isinstance(advs, Mapping):
            advs = [advs[k] for k in sorted(advs, key=lambda x: int(x) if str(x).isdigit() else 0)]
        st.adv_searches = [
            {"cols": str(a.get("cols") or ""), "opts": str(a.get("opts") or "like"),
             "strs": str(a.get("strs") or "")}
            for a in advs if isinstance(a, Mapping)
        ][:50]
        fs = raw.get("filterSearches") or {}
        st.filter_searches = {
            str(k): str(v) for k, v in fs.items() if k in self.table_columns and str(v) != ""
        } if isinstance(fs, Mapping) else {}
        oc = raw.get("orderByColumn")
        st.order_by_column = oc if oc in self.table_columns else self.primary_col
        st.asc_or_desc = "desc" if raw.get("ascOrDesc") == "desc" else "asc"
        return st

    # -- column preparation (setHiddenColumns / setColumnOrder / joins) -----
    def prepare_columns(self, prefs: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
        prefs = prefs or {}
        cols = copy.deepcopy(self.table_columns)
        if self.can("H"):
            hidden = prefs.get("hidden") or {}
            for col, info in cols.items():
                if self.col_can(info, "H") and col != self.primary_col and col in hidden:
                    info["hidden"] = bool(hidden[col])
        for info in cols.values():
            if info.get("hidden"):
                info["hidden_add"] = True
                info["hidden_edit"] = True
        if self.can("O"):
            order = prefs.get("order") or []
            ordered: dict[str, dict[str, Any]] = {}
            for col in order:
                if col in cols and self.col_can(cols[col], "O"):
                    ordered[col] = cols.pop(col)
            ordered.update(cols)
            cols = ordered
        return cols

    def _resolve_joins(self, cols: dict[str, dict[str, Any]]) -> str:
        """Port of ``formatJoinClause``.  Mutates *cols*' join info, returns SQL."""
        sets: list[str] = []
        joins: dict[str, str] = {}
        for col, info in cols.items():
            j = info.get("join")
            if not isinstance(j, dict):
                continue
            j["orig_display_mask"] = j.get("display_mask", "")
            join_table = f"{j['db']}.{j['table']}" if j.get("db") else j["table"]
            join_type = j.get("type", "left")
            join_col = j.get("real_column", col)
            foreign = j["column"]
            ident = j.get("custom_join") or f"{join_table}{join_col}{foreign}{join_type}"
            save = True
            if ident in joins:
                j["alias"] = joins[ident]
                alias = j["alias"]
                save = False
            else:
                j.setdefault("alias", j["table"])
                alias = j["alias"]
                joins[ident] = alias
            if "display_mask" in j:
                if "custom_join" not in j:
                    parts = j["display_mask"].split(",")
                    parts = [re.sub(re.escape(j["table"]), lambda _m: alias, p, count=1) for p in parts]
                    j["display_mask"] = ",".join(parts)
            else:
                j["display_mask"] = f"{alias}.{foreign}"
            if save:
                if "custom_join" in j:
                    sets.append(j["custom_join"])
                else:
                    sets.append(
                        f"{join_type} join {add_tick_marks(join_table)} as {add_tick_marks(alias)} "
                        f"on {add_tick_marks(self.db_and_table + '.' + join_col)} = "
                        f"{add_tick_marks(alias + '.' + foreign)}"
                    )
        out = "\n".join(sets) + "\n" if sets else ""
        if self.cfg["custom_join"]:
            out += self.cfg["custom_join"] + "\n"
        return out

    def _select_set(self, col: str, info: Mapping[str, Any]) -> str:
        j = info.get("join")
        if isinstance(j, dict):
            mask = j.get("display_mask") or f"{j['alias']}.{j['column']}"
            return f"{mask} as {add_tick_marks(col)}"
        if "display_mask" in info:
            return f"{info['display_mask']} as {add_tick_marks(col)}"
        return add_tick_marks(f"{self.db_and_table}.{col}")

    def _select_clause(self, cols: Mapping[str, Mapping[str, Any]]) -> str:
        sets = [self._select_set(c, i) for c, i in cols.items()]
        return "select " + ",\n".join(sets) + "\nfrom " + self.db_and_table + "\n"

    # -- search / filter SQL ------------------------------------------------
    def _col_expr(self, col: str, info: Mapping[str, Any]) -> tuple[str, bool]:
        """Expression to search/filter on, and whether it still needs tick marks."""
        j = info.get("join")
        if isinstance(j, dict):
            return (j.get("display_mask") or f"{j['alias']}.{j['column']}"), False
        if "display_mask" in info:
            return info["display_mask"], False
        return f"{self.db_and_table}.{col}", True

    def _prepared(self, expr: str, op: str, param: str, tick: bool) -> str:
        return f"{add_tick_marks(expr) if tick else expr} {op} :{param}"

    @staticmethod
    def _in_scope(info: Mapping[str, Any], having: bool) -> bool:
        return ("having" in info) == having

    def _quick_sets(self, cols, st: ViewState, params: dict, having: bool) -> list[str]:
        out = []
        for col, info in cols.items():
            if self.col_can(info, "Q") and self._in_scope(info, having):
                p = _pname(col) + "_qsearch"
                expr, tick = self._col_expr(col, info)
                out.append(self._prepared(expr, "like", p, tick))
                params[p] = f"%{st.search_string}%"
        return out

    def _advanced_sets(self, cols, st: ViewState, params: dict, having: bool) -> list[str]:
        opts = self.search_operators()
        range_ops = (">", "<", ">=", "<=")
        out = []
        for i, a in enumerate(st.adv_searches):
            col = a.get("cols")
            if not col or col not in cols or not self.col_can(cols[col], "S"):
                continue
            info = cols[col]
            if not self._in_scope(info, having):
                continue
            if a["opts"] not in opts:
                self.deny()
            is_range = a["opts"] in range_ops
            value = a["strs"]
            if self.cfg["convert_range_dates"] and "calendar" in info and is_range:
                value = self.format_date(value, self.cfg["default_db_date_format"])
            if "range_mask" in info and is_range:
                expr, tick = info["range_mask"], False
            else:
                expr, tick = self._col_expr(col, info)
            if a["opts"] in ("like", "not like"):
                value = f"%{value}%"
            p = f"{_pname(col)}_{i}_asearch"
            out.append(self._prepared(expr, a["opts"], p, tick))
            params[p] = value
        return out

    def _filter_sets(self, cols, st: ViewState, params: dict, having: bool) -> list[str]:
        out = []
        for col, text in st.filter_searches.items():
            info = cols.get(col)
            if info and self.col_can(info, "F") and self._in_scope(info, having):
                p = _pname(col) + "_qfilter"
                expr, tick = self._col_expr(col, info)
                out.append(self._prepared(expr, "like", p, tick))
                params[p] = f"%{text}%"
        return out

    def _data_filter_sets(self, cols, having: bool) -> list[str]:
        out = []
        for col, info in cols.items():
            if not self._in_scope(info, having) or "data_filters" not in info:
                continue
            df = info["data_filters"]
            j = info.get("join")
            if isinstance(j, dict) and "display_mask" in j:
                base = j["display_mask"]
            elif "display_mask" in info:
                base = info["display_mask"]
            else:
                base = add_tick_marks(f"{self.db_and_table}.{col}")
            subs = [f"{base} {f}" for f in df["filters"]]
            if df.get("criteria") == "any":
                out.append("(" + " or\n".join(subs) + ")")
            else:
                out.append(" and\n".join(subs))
        return out

    def search_operators(self) -> dict[str, str]:
        L = self.lang
        return {"like": L.optLike, "not like": L.optNotLike, "=": L.optEq, "<>": L.optNotEq,
                ">": L.optGreat, "<": L.optLess, ">=": L.optGreatEq, "<=": L.optLessEq}

    def _bool_clause(self, cols, st, params, having: bool, include_searches: bool) -> str:
        sets: list[str] = []
        clause = ""
        if include_searches:
            if st.search_string and st.search_type == "quick":
                sets += self._quick_sets(cols, st, params, having)
            elif st.adv_searches and st.search_type == "advanced":
                sets += self._advanced_sets(cols, st, params, having)
            glue = "and" if (st.search_type == "advanced" and st.match_all) else "or"
            if sets:
                clause += "(" + f" {glue}\n".join(sets) + ")"
            fsets = self._filter_sets(cols, st, params, having) if st.filter_searches else []
            if fsets:
                fc = "(" + " and\n".join(fsets) + ")"
                clause = f"{clause}\n and \n{fc}" if clause else fc
        dsets = self._data_filter_sets(cols, having)
        if dsets:
            clause = (clause + " and \n" if clause else " ") + " and \n".join(dsets)
        return clause

    def build(self, state: ViewState, prefs: Mapping[str, Any] | None = None,
              include_searches: bool = True) -> Built:
        cols = self.prepare_columns(prefs)
        join = self._resolve_joins(cols)
        select = self._select_clause(cols)
        params: dict[str, Any] = {}
        where_body = self._bool_clause(cols, state, params, False, include_searches)
        where = f" where {where_body}\n" if where_body else ""
        if self.cfg["sql_filters"]:
            where = (where + f" and {self.cfg['sql_filters']}\n") if where else f"where {self.cfg['sql_filters']}\n"
        group_by = self.cfg["group_by_clause"] or ""
        having = ""
        if group_by:
            body = self._bool_clause(cols, state, params, True, include_searches)
            if body:
                having = f" having {body}\n"
            if self.cfg["having_filters"]:
                having = (having + f" and {self.cfg['having_filters']}\n") if having else f"having {self.cfg['having_filters']}\n"
        return Built(cols, select, join, where, group_by, having, params)

    # -- querying ----------------------------------------------------------
    def order_expr(self, cols, column: str) -> str:
        if column in cols and "order_mask" in cols[column]:
            return cols[column]["order_mask"]
        if column in cols:
            return add_tick_marks(column)
        return add_tick_marks(self.primary_col)

    def count_rows(self, b: Built) -> int:
        if b.group_by:
            q = f"select * from {self.table_name} {b.join} {b.where} {b.group_by} {b.having}"
            return len(self.db.query(q, b.params))
        q = f"select count(*) as num_results from {self.table_name} {b.join} {b.where}"
        return int(self.db.scalar(q, b.params) or 0)

    def _order_sql(self, b: Built, st: ViewState) -> str:
        extra = f", {self.cfg['extra_order_by_info']}" if self.cfg["extra_order_by_info"] else ""
        return f"order by {self.order_expr(b.cols, st.order_by_column)} {st.asc_or_desc} {extra}"

    # -- paging helpers ----------------------------------------------------
    @staticmethod
    def page_numbers(num_pages: int, cur_page: int, *, page_percent: int, page_range: int,
                     page_begin: int, page_end: int, show_all: int) -> list[int]:
        """Port of the page-list algorithm shared by the page links and the dropdown."""
        if num_pages == 0:
            return [0]
        if num_pages < show_all:
            return list(range(1, num_pages + 1))
        pages = set(range(1, page_begin + 1))
        pages.update(range(num_pages - page_end, num_pages + 1))
        i, x, met = page_begin, num_pages - page_end, False
        step = max(1, num_pages // max(page_percent, 1))
        guard = 0
        while i <= x and guard < 100000:
            guard += 1
            if cur_page - page_range <= i <= cur_page + page_range:
                i += 1
                met = True
            else:
                i += step
                if i > cur_page - page_range and not met:
                    i = cur_page - page_range
            if 0 < i <= x:
                pages.add(i)
        return sorted(pages)

    def display_num_options(self, st: ViewState, num_results: int) -> list[int]:
        c = self.cfg
        opts, value = [], c["display_num_inc"]
        while value < c["max_disp_num"] and (value < num_results or value <= st.display_num):
            value += c["display_num_inc"]
            opts.append(value)
        return opts or [st.display_num]

    # -- main data endpoint ------------------------------------------------
    def get_table_data(self, raw_state: Mapping[str, Any] | None,
                       prefs: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Everything the browser needs to draw the table (``update_html``)."""
        st = self.make_state(raw_state)
        b = self.build(st, prefs)
        num_results = self.count_rows(b)
        if st.start >= num_results:
            st.start = 0
        sql = b.sql(f"{self._order_sql(b, st)} limit {int(st.start)}, {int(st.display_num)}")
        rows = self.db.query(sql, b.params)
        cols = b.cols
        visible = [c for c, i in cols.items() if self.col_can(i, "T") and not i.get("hidden")]

        columns = []
        for c in visible:
            i = cols[c]
            can_filter = self.can("F") and self.col_can(i, "F")
            columns.append({
                "key": c, "text": i["display_text"], "title": i.get("title", ""),
                "min_width": i.get("min_width"), "filterable": can_filter,
                "filter": st.filter_searches.get(c, ""),
                "distinct": bool(i.get("distinct")),
                "sorted": st.asc_or_desc if st.order_by_column == c else None,
                "editable": self.col_can(i, "E"),
            })

        out_rows, totals = [], {}
        for n, row in enumerate(rows, start=1):
            cells = []
            for c in visible:
                cells.append(self._render_cell(c, cols[c], row, n))
                if cols[c].get("total_column"):
                    try:
                        totals[c] = totals.get(c, 0) + float(row.get(c) or 0)
                    except (TypeError, ValueError):
                        pass
            out_rows.append({"id": row.get(self.primary_col), "num": n, "cells": cells})

        cur_page = _php_round(st.start / st.display_num)
        num_pages = math.ceil(num_results / st.display_num)
        link_cfg = dict(page_percent=5, page_range=2, page_begin=3, page_end=2, show_all=10)
        drop_cfg = dict(page_percent=self.cfg["page_percent"], page_range=self.cfg["page_range"],
                        page_begin=self.cfg["page_begin"], page_end=self.cfg["page_end"],
                        show_all=self.cfg["show_all"])

        def page_items(cfg):
            return [{"label": p, "start": max((p - 1) * st.display_num, 0), "active": (p - 1) == cur_page}
                    for p in self.page_numbers(num_pages, cur_page, **cfg)]

        end = min(st.display_num + st.start, num_results)
        if num_results > 0:
            record_text = self.lang.ttlDispRecs % (
                "", st.start + 1, "", end, "", f"{num_results:,}")
            record_text = re.sub(r"<[^>]+>", "", record_text)
        else:
            record_text = self.lang.ttlDispNoRecs

        data = {
            "title": self.cfg["table_title"],
            "help_html": self.cfg["help_html"],
            "state": st.to_dict(),
            "columns": columns,
            "rows": out_rows,
            "totals": totals if not self.cfg["edit_in_place"] and not self.cfg["add_in_place"] else {},
            "num_results": num_results,
            "record_text": record_text,
            "paging": {
                "cur_page": cur_page, "num_pages": num_pages,
                "links": page_items(link_cfg), "dropdown": page_items(drop_cfg),
                "display_num_options": self.display_num_options(st, num_results),
            },
            "ui": self.ui_flags(),
            "adv": {
                "columns": [{"key": c, "text": i["display_text"]} for c, i in cols.items()
                            if self.col_can(i, "S")],
                "operators": [{"sign": k, "text": v} for k, v in self.search_operators().items()],
            },
            "lang": self.lang.as_dict(),
            "no_records": num_results == 0,
        }
        if self.cfg["view_query"]:
            data["query"] = sql
        return data

    def ui_flags(self) -> dict[str, Any]:
        c = self.cfg
        return {
            "view": self.can("V"), "edit": self.can("E"), "add": self.can("A"),
            "copy": self.can("C"), "delete": self.can("D"), "export": self.can("X"),
            "hide": self.can("H"), "order": self.can("O"), "filter": self.can("F"),
            "quick": self.can("Q"), "advanced": self.can("S"), "display_num": self.can("U"),
            "multi": self.can("M"), "icons": self.can("I"),
            "icon_position": c["icon_col_position"], "remove_icons": c["remove_icons"] or "",
            "edit_in_place": c["edit_in_place"], "filter_position": c["filter_position"],
            "display_filter_btns": c["display_filter_btns"], "pagination_links": c["pagination_links"],
            "record_info": c["record_info"], "highlight": c["use_highlight"],
            "remove_criteria": c["remove_criteria"], "req_marker": c["req_marker"],
        }

    def _render_cell(self, col: str, info: Mapping[str, Any], row: Mapping[str, Any], n: int) -> dict[str, Any]:
        val = row.get(col)
        fn = info.get("table_fun")
        out: Any = val
        if callable(fn):
            out = fn(col, val, row, self.cfg["instance_name"], n)
        cell = out if isinstance(out, F.Cell) else F.Cell("" if out is None else str(out))
        text = cell.text
        title = None
        sub = info.get("sub_str")
        if sub and len(text) > sub:
            title, text = text, text[:sub] + "..."
        d: dict[str, Any] = {"t": text}
        if cell.align:
            d["a"] = cell.align
        if cell.options:
            d["o"] = cell.options
        if title:
            d["title"] = title
        return d

    # -- distinct values (BS feature) ---------------------------------------
    def distinct_values(self, raw_state: Mapping[str, Any] | None, col: str,
                        prefs: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        st = self.make_state(raw_state)
        b = self.build(st, prefs)
        if col not in b.cols or not b.cols[col].get("distinct"):
            self.deny()
        raw_expr, tick = self._col_expr(col, b.cols[col])
        expr = add_tick_marks(raw_expr) if tick else raw_expr
        sql = (f"select {expr} as {add_tick_marks('value')}, count(*) as {add_tick_marks('count')} "
               f"from {self.db_and_table} {b.join} {b.where} group by 1 order by 1")
        rows = self.db.query(sql, b.params)
        return [{"value": r["value"], "count": r["count"]} for r in rows]

    # -- single row access -------------------------------------------------
    def get_table_row(self, pk: Any) -> dict[str, Any] | None:
        rows = self.db.query(
            f"select * from {self.table_name} where {self.primary_col} = :pk", {"pk": pk})
        return rows[0] if rows else None

    def has_rights_to_row(self, pk: Any) -> bool:
        """The row must be inside the editor's permanent filters (sql_filters etc.)."""
        b = self.build(ViewState(), None, include_searches=False)
        tail = f"{'and' if b.where else 'where'} {self.table_name}.{self.primary_col} = :__pk"
        params = dict(b.params, __pk=pk)
        q = f"select 1 as ok from {self.table_name} {b.join} {b.where} {tail}"
        return bool(self.db.query(q, params))

    def has_rights_to_rows(self, ids: list[Any]) -> bool:
        return all(self.has_rights_to_row(i) for i in ids)

    def view_row(self, pk: Any, prefs: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not self.can("V"):
            self.deny()
        cols = self.prepare_columns(prefs)
        join = self._resolve_joins(cols)
        select = self._select_clause(cols)
        rows = self.db.query(
            f"{select} {join} where {self.table_name}.{self.primary_col} = :pk", {"pk": pk})
        if not rows:
            return {"title": self.cfg["view_row_title"], "fields": []}
        row = rows[0]
        items = []
        for col, info in cols.items():
            if not self.col_can(info, "V"):
                continue
            val = row.get(col)
            fn = info.get("view_fun")
            if callable(fn):
                val = fn(col, val, row, self.cfg["instance_name"])
            cell = val if isinstance(val, F.Cell) else F.Cell("" if val is None else str(val))
            item = {"key": col, "label": info["display_text"], "value": cell.text}
            if cell.options:
                item["options"] = cell.options
            items.append(item)
        extra = ""
        if callable(self.cfg["view_html_fun"]):
            extra = self.cfg["view_html_fun"](row, self.cfg["instance_name"]) or ""
        return {"title": self.cfg["view_row_title"], "fields": items, "extra": extra}

    # -- forms -------------------------------------------------------------
    def _select_options(self, query: str) -> list[dict[str, Any]]:
        rows = self.db.query(query)
        out = []
        for r in rows:
            vals = list(r.values())
            out.append({"value": vals[0], "label": vals[1] if len(vals) > 1 else vals[0]})
        return out

    def _default_value(self, info: Mapping[str, Any], row: Mapping[str, Any], col: str, mode: str) -> Any:
        val = row.get(col)
        has_val = val is not None and len(str(val)) > 0
        if has_val:
            fn = info.get(f"{mode}_fun")
            if callable(fn):
                return fn(col, val, row, self.cfg["instance_name"])
            return val
        if "default" in info and mode == "add":
            d = info["default"]
            return d() if callable(d) else d
        return "" if val is None else val

    def input_spec(self, col: str, info: Mapping[str, Any], row: Mapping[str, Any], mode: str) -> dict[str, Any]:
        """Describe the input control for a column (``getInputHtmlInfo``)."""
        value = self._default_value(info, row, col, mode)
        spec: dict[str, Any] = {
            "key": col, "label": info["display_text"], "value": "" if value is None else value,
            "required": bool(info.get("req")), "readonly": bool(info.get("readonly")),
            "hidden": bool(info.get(f"hidden_{mode}")),
        }
        fif = info.get("format_input_fun")
        j = info.get("join")
        if fif is F.format_radio:
            spec["type"] = "radio"
            spec["options"] = [{"value": "1", "label": "Yes"}, {"value": "0", "label": "No"}]
        elif callable(fif):
            spec["type"] = "text"
            spec["value"] = fif(col, value, row)
            spec["readonly"] = True
        elif spec["hidden"]:
            spec["type"] = "hidden"
        elif "select_query" in info:
            spec["type"] = "select"
            spec["options"] = self._select_options(info["select_query"])
        elif isinstance(info.get("select_array"), Mapping):
            spec["type"] = "select"
            spec["options"] = [{"value": str(k), "label": v} for k, v in info["select_array"].items()]
        elif "textarea" in info:
            spec["type"] = "textarea"
            spec["rows"] = info["textarea"].get("rows", 7)
            spec["cols"] = info["textarea"].get("cols", 25)
        elif "checkbox" in info:
            spec["type"] = "checkbox"
            spec["checked_value"] = info["checkbox"].get("checked_value", "")
            spec["unchecked_value"] = info["checkbox"].get("un_checked_value", "")
        elif isinstance(j, dict) and not j.get("no_auto_select"):
            join_table = f"{j['db']}.{j['table']}" if j.get("db") else j["table"]
            if j.get("alias"):
                join_table += f" AS {j['alias']}"
            mask = j.get("orig_display_mask") or j.get("display_mask") or f"{join_table}.{j['column']}"
            q = f"select distinct({j['column']}), {mask} from {join_table} order by {mask} asc"
            spec["type"] = "select"
            spec["options"] = self._select_options(q)
        elif "calendar" in info:
            spec["type"] = "date"
            parsed = parse_date(str(value)) if value not in (None, "") else None
            spec["value"] = parsed.strftime("%Y-%m-%d") if parsed else ""
        else:
            spec["type"] = info.get("input_type", "text")
            if "maxlen" in info:
                spec["maxlen"] = info["maxlen"]
        if spec["type"] == "select" and value not in (None, ""):
            spec["allow_blank"] = False
        elif spec["type"] == "select":
            spec["allow_blank"] = True
        return spec

    def edit_form(self, pk: Any, prefs: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not self.can("E"):
            self.deny()
        if not self.has_rights_to_row(pk):
            self.deny()
        row = self.get_table_row(pk)
        if row is None:
            return {"id": pk, "inputs": [], "title": self.cfg["edit_row_title"]}
        before = self.cfg["before_edit_fun"]
        if callable(before) and before(self.primary_col, pk, row, self.cfg["instance_name"], "") is False:
            self.deny()
        cols = self.prepare_columns(prefs)
        inputs = []
        for col, info in cols.items():
            j = info.get("join")
            if self.col_can(info, "E") and not (isinstance(j, dict) and "real_column" in j):
                inputs.append(self.input_spec(col, info, row, "edit"))
        return {"id": pk, "inputs": inputs, "title": self.cfg["edit_row_title"]}

    def add_form(self, prefs: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not self.can("A"):
            self.deny()
        cols = self.prepare_columns(prefs)
        inputs = []
        for col, info in cols.items():
            j = info.get("join")
            if self.col_can(info, "A") and not (isinstance(j, dict) and "real_column" in j):
                inputs.append(self.input_spec(col, info, {}, "add"))
        return {"inputs": inputs, "title": self.cfg["add_row_title"]}

    # -- validation --------------------------------------------------------
    def format_date(self, date: str, fmt: str) -> str:
        d = parse_date(date)
        return d.strftime(fmt) if d else ""

    def validate_input_value(self, cols, col: str, val: Any, row: Mapping[str, Any], mode: str,
                             in_place: bool, errors: dict[str, str]) -> Any:
        info = cols[col]
        bad = False
        fn = info.get(f"on_{mode}_fun")
        if callable(fn):
            val = fn(col, val, row, self.cfg["instance_name"])
        elif "calendar" in info and val not in (None, ""):
            val = self.format_date(str(val), self.cfg["default_db_date_format"])
        vfn = info.get("val_fun")
        sval = "" if val is None else str(val)
        if callable(vfn) and not vfn(col, val, row, self.cfg["instance_name"]):
            bad = True
        elif info.get("req"):
            if info.get("hidden") and in_place:
                bad = False
            elif sval.strip() == "":
                bad = True
            elif "calendar" in info and sval[:10] == "0000-00-00":
                bad = True
        sa = info.get("select_array")
        if isinstance(sa, Mapping) and sval != "" and sval not in {str(k) for k in sa}:
            bad = True
        if bad:
            errors[col] = info["display_text"]
        return val

    def _add_edit_set(self, cols, col: str, val: Any, mode: str, params: dict) -> tuple[str, Any]:
        """Return (column, sql-expression) for an insert/update (``getAddEditPreparedSet``)."""
        info = cols[col]
        p = _pname(col)
        fun = info.get(f"mysql_{mode}_fun")
        tick = add_tick_marks(col)
        if fun:
            if "#VALUE#" in fun.upper() or ")" in fun:
                expr = re.sub("#VALUE#", f":{p}", fun, flags=re.I)
            else:
                expr = f"{fun}(:{p})"
            params[p] = val
            return tick, expr
        if val is None:
            return tick, "null"
        params[p] = val
        return tick, f":{p}"

    def _null_value(self, info: Mapping[str, Any], val: Any) -> Any:
        na = info.get("null_array")
        if na is not None and val in na:
            return None
        return val

    # -- CRUD --------------------------------------------------------------
    def update_row(self, info: Mapping[str, Any], old_pk: Any, *, in_place: bool = False,
                   prefs: Mapping[str, Any] | None = None, row_num: Any = "") -> Any:
        if not self.can("E") or not self.has_rights_to_row(old_pk):
            self.deny()
        cols = self.prepare_columns(prefs)
        errors: dict[str, str] = {}
        sets: list[str] = []
        params: dict[str, Any] = {}
        after: dict[str, Any] = {}
        new_pk = ""
        for col, val in info.items():
            if col not in cols:
                continue
            if not self.col_can(cols[col], "E"):
                self.deny()
            val = self.validate_input_value(cols, col, val, info, "edit", in_place, errors)
            val = self._null_value(cols[col], val)
            tick, expr = self._add_edit_set(cols, col, val, "edit", params)
            sets.append(f"{tick} = {expr}")
            if col == self.primary_col:
                new_pk = val
            after[col] = val
        if errors:
            raise ValidationError(errors, [self.lang.errValInPlace if in_place else self.lang.errVal])
        if new_pk in ("", None):
            new_pk = old_pk
        if sets:
            uf = self.cfg["user_update_fun"]
            if callable(uf):
                return uf(self.primary_col, old_pk, after, self.cfg["instance_name"], row_num)
            params["old_primary_key_value"] = old_pk
            self.db.execute(
                f"update {self.table_name} set {', '.join(sets)} "
                f"where {self.primary_col} = :old_primary_key_value", params)
            af = self.cfg["after_edit_fun"]
            if callable(af):
                af(self.primary_col, old_pk, after, self.cfg["instance_name"], row_num)
        return new_pk

    def _insert(self, cols_sql: list[str], exprs: list[str], params: dict) -> Any:
        if cols_sql:
            q = f"insert into {self.table_name} ({', '.join(cols_sql)}) values ({', '.join(exprs)})"
        elif self.db.dialect == "sqlite":
            q = f"insert into {self.table_name} default values"
        else:
            q = f"insert into {self.table_name} () values ()"
        _, last_id = self.db.execute(q, params)
        return last_id

    def insert_row(self, info: Mapping[str, Any], *, prefs: Mapping[str, Any] | None = None,
                   in_place: bool = False, row_num: Any = "") -> Any:
        if not self.can("A"):
            self.deny()
        cols = self.prepare_columns(prefs)
        errors: dict[str, str] = {}
        names: list[str] = []
        exprs: list[str] = []
        params: dict[str, Any] = {}
        after: dict[str, Any] = {}
        for col, val in info.items():
            if col not in cols:
                continue
            if not self.col_can(cols[col], "A"):
                self.deny()
            val = self.validate_input_value(cols, col, val, info, "add", in_place, errors)
            val = self._null_value(cols[col], val)
            tick, expr = self._add_edit_set(cols, col, val, "add", params)
            names.append(tick)
            exprs.append(expr)
            after[col] = val
        if errors:
            raise ValidationError(errors, [self.lang.errVal])
        uf = self.cfg["user_insert_fun"]
        if callable(uf):
            return uf(self.primary_col, "", after, self.cfg["instance_name"], row_num)
        new_id = self._insert(names, exprs, params)
        af = self.cfg["after_add_fun"]
        if callable(af):
            af(self.primary_col, new_id, after, self.cfg["instance_name"], row_num)
        return new_id

    def delete_rows(self, ids: Iterable[Any]) -> list[Any]:
        deleted: list[Any] = []
        if not self.can("D"):
            self.deny()
        ids = list(ids)
        for pk in ids:
            if not self.has_rights_to_row(pk):
                self.deny()
        for n, pk in enumerate(ids, start=1):
            row: dict[str, Any] = {}
            c = self.cfg
            if any(callable(c[k]) for k in ("before_delete_fun", "after_delete_fun", "user_delete_fun")):
                row = self.get_table_row(pk) or {}
            if callable(c["before_delete_fun"]) and \
                    c["before_delete_fun"](self.primary_col, pk, row, c["instance_name"], n) is False:
                continue
            if callable(c["user_delete_fun"]):
                if c["user_delete_fun"](self.primary_col, pk, row, c["instance_name"], n):
                    deleted.append(pk)
            else:
                self.db.execute(
                    f"delete from {self.table_name} where {self.primary_col} = :id", {"id": pk})
                deleted.append(pk)
                if callable(c["after_delete_fun"]):
                    c["after_delete_fun"](self.primary_col, pk, row, c["instance_name"], n)
        return deleted

    def copy_rows(self, ids: Iterable[Any], prefs: Mapping[str, Any] | None = None) -> list[Any]:
        if not self.can("C"):
            self.deny()
        ids = list(ids)
        if not self.has_rights_to_rows(ids):
            self.deny()
        cols = self.prepare_columns(prefs)
        new_ids: list[Any] = []
        for n, pk in enumerate(ids, start=1):
            row = self.get_table_row(pk)
            if not row:
                continue
            names, exprs, params = [], [], {}
            for col, info in cols.items():
                j = info.get("join")
                if self.col_can(info, "C") and not (isinstance(j, dict) and "real_column" in j):
                    val = self._null_value(info, row.get(col))
                    fn = info.get("on_copy_fun")
                    if callable(fn):
                        val = fn(col, val, row, self.cfg["instance_name"], n)
                    tick, expr = self._add_edit_set(cols, col, val, "add", params)
                    names.append(tick)
                    exprs.append(expr)
            new_id = self._insert(names, exprs, params)
            new_ids.append(new_id)
            af = self.cfg["after_copy_fun"]
            if callable(af):
                af(self.primary_col, new_id, row, self.cfg["instance_name"], n)
        return new_ids

    # -- custom actions ----------------------------------------------------
    def user_action(self, action: str, info: Any) -> Any:
        actions = self.cfg["user_actions"] or {}
        fn = actions.get(action)
        if not callable(fn):
            raise ConfigError(self.lang.errNoAction % action)
        return fn(info, self.cfg["instance_name"])

    # -- column show/hide & ordering --------------------------------------
    def column_settings(self, prefs: Mapping[str, Any] | None = None) -> dict[str, Any]:
        cols = self.prepare_columns(prefs)
        hide_items = [
            {"key": c, "text": i["display_text"], "visible": not i.get("hidden")}
            for c, i in cols.items() if self.col_can(i, "H") and c != self.primary_col
        ]
        order_items = [
            {"key": c, "text": i["display_text"]}
            for c, i in cols.items() if self.col_can(i, "O") and self.col_can(i, "T")
        ]
        return {"hide": hide_items if self.can("H") else [],
                "order": order_items if self.can("O") else [],
                "show_hide_title": self.cfg["show_hide_title"],
                "order_title": self.cfg["order_col_title"]}

    def update_hidden_columns(self, prefs: dict[str, Any], visible: Mapping[str, bool]) -> dict[str, Any]:
        if not self.can("H"):
            self.deny()
        hidden = dict(prefs.get("hidden") or {})
        for col, checked in visible.items():
            if col in self.table_columns and self.col_can(self.table_columns[col], "H") \
                    and col != self.primary_col:
                hidden[col] = not checked
        prefs = dict(prefs)
        prefs["hidden"] = hidden
        return prefs

    def update_column_order(self, prefs: dict[str, Any], order: list[str]) -> dict[str, Any]:
        if not self.can("O"):
            self.deny()
        prefs = dict(prefs)
        prefs["order"] = [c for c in order if c in self.table_columns]
        return prefs

    def reset_column_order(self, prefs: dict[str, Any]) -> dict[str, Any]:
        prefs = dict(prefs)
        prefs["order"] = []
        return prefs

    # -- export ------------------------------------------------------------
    def export_csv(self, raw_state: Mapping[str, Any] | None,
                   prefs: Mapping[str, Any] | None = None) -> str:
        """CSV text, byte-compatible with ``exportInfo()`` (without the BOM)."""
        if not self.can("X"):
            self.deny()
        st = self.make_state(raw_state)
        b = self.build(st, prefs)
        rows = self.db.query(b.sql(self._order_sql(b, st)), b.params)
        if not rows:
            return ""
        cols = [c for c, i in b.cols.items() if self.col_can(i, "X") and not i.get("hidden")]
        delim, lb = self.cfg["export_delimiter"], self.cfg["export_line_break"]
        out = [delim.join('"' + b.cols[c]["display_text"] + '"' for c in cols)]
        for row in rows:
            cells = []
            for c in cols:
                v = row.get(c)
                fn = b.cols[c].get("csv_export_fun")
                if callable(fn):
                    v = fn(c, v, row, self.cfg["instance_name"])
                s = "" if v is None else str(v)
                cells.append('"' + s.replace("\r", "").replace("\n", "").replace('"', '""') + '"')
            out.append(delim.join(cells))
        return lb.join(out) + lb
