"""Column definition helpers.

Port of ``include/mate_field_func.php``.  Every function returns the same kind of
column-definition ``dict`` as the PHP original (same keys, same permission
letters) so existing column configs translate one-to-one.

Column permission letters (as in the original):

====  ==========================================================
T     show the column in the table
V     show in the "view row" dialog
A     input shown on the *add* form
E     input shown on the *edit* form (and allowed to be updated)
C     value is copied when a row is copied
Q     searched by the quick-search box
S     selectable in advanced search
F     gets a filter box in the table header
X     included in the CSV export
H     the user may hide/show the column
O     the user may re-order the column
====  ==========================================================

Two deliberate API changes compared with the PHP helpers:

* ``col_header_info`` was a raw HTML attribute string
  (``'title="..." style="min-width: 50px;"'``).  It is now structured:
  ``title`` (tooltip) and ``min_width`` (pixels).  The same goes for
  ``input_info`` -> ``readonly``.
* ``table_fun`` / ``view_fun`` callbacks return a plain string or a
  :class:`Cell`; the browser escapes it.  The PHP helpers returned raw HTML,
  which was an XSS hole for any column holding user supplied text.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

# --------------------------------------------------------------------------
# Label registries (the PHP helpers read the globals $long_desc / $description)
# --------------------------------------------------------------------------
long_desc: dict[str, str] = {}      # column -> display text
description: dict[str, str] = {}    # column -> header tooltip
title: dict[str, str] = {}          # column -> raw_field tooltip

# Hook set by the web layer so create_user_field() & co can look up the user
current_user: Callable[[], str | None] = lambda: None


def set_labels(*, long_desc_: Mapping[str, str] | None = None,
               description_: Mapping[str, str] | None = None) -> None:
    if long_desc_:
        long_desc.update(long_desc_)
    if description_:
        description.update(description_)


def _disp(f: str) -> str:
    return long_desc.get(f, f)


def _desc(f: str) -> str:
    return description.get(f, f)


# --------------------------------------------------------------------------
# Cell formatting
# --------------------------------------------------------------------------
@dataclass
class Cell:
    """Rich cell value returned by ``table_fun`` / ``view_fun``."""
    text: str = ""
    align: str | None = None            # 'left' | 'right'
    options: list[str] = field(default_factory=list)  # render as <select>


def format_yn(col, val, row=None, *_):
    return "No" if str(val) == "0" else "Yes"


def format_log_date(*_):
    return _dt.date.today().isoformat()


def format_rem_input(col, val, row=None, *_):
    return val


def format_date(col, val, row=None, *_):
    """``formatDate``: blank for the zero dates MySQL likes to store."""
    s = "" if val is None else str(val)
    if s in ("", "0000-00-00", "9999-12-31", "1111-11-11"):
        return ""
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(s[:19], pattern).strftime("%d %b %Y")
        except ValueError:
            continue
    return s


def format_radio(col, val, row=None, *_):
    """Sentinel: the front-end renders a Yes/No radio pair for this column."""
    return val


def format_left_align(col, val, row=None, *_):
    return Cell("" if val is None else str(val), align="left")


def format_right_align(col, val, row=None, *_):
    return Cell("" if val is None else str(val), align="right")


def show_values_2_select(col, val, row=None, *_):
    """Semicolon separated list -> dropdown (read-only), single value -> text."""
    s = "" if val is None else str(val)
    parts = s.split(";")
    if len(parts) == 1:
        return s
    return Cell(s, options=parts)


# --------------------------------------------------------------------------
# Simple fields
# --------------------------------------------------------------------------
def id_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": "Id",
        "perms": "EVHOM",
        "hidden_edit": True,
        "hidden_add": True,
        "readonly": True,
        "title": _desc(f),
    }


def ro_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": _disp(f),
        "perms": "EVCATXQSHOF",
        "format_input_fun": format_rem_input,
        "readonly": True,
        "title": _desc(f),
    }


def txt_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": _disp(f),
        "perms": "VXQSHOF" + p,
        "table_fun": format_left_align,
        "title": _desc(f),
        "min_width": 50,
    }


def select_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": _disp(f),
        "perms": "VXQSHOF" + p,
        "view_fun": show_values_2_select,
        "table_fun": show_values_2_select,
        "title": _desc(f),
    }


def windows_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": _disp(f),
        "display_mask": "concat(cifs_share,'\\\\',replace(file_name,'/','\\\\'))",
        "perms": "VXQSHOF" + p,
        "table_fun": format_left_align,
        "title": _desc(f),
    }


def raw_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": f,
        "perms": "VXQSHOF" + p,
        "table_fun": format_left_align,
        "title": _desc(f),
        "min_width": 50,
    }


def txtarea_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": _disp(f),
        "textarea": {"rows": 5, "cols": 21},
        "perms": "VXQSHOF" + p,
        "table_fun": format_left_align,
        "title": _desc(f),
    }


def num_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": _disp(f),
        "table_fun": format_right_align,
        "perms": "VXQSHOF" + p,
        "title": _desc(f),
        "min_width": 50,
    }


def nummb_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": _disp(f),
        "display_mask": f"TRUNCATE({f}/(1024 * 1024),2)",
        "perms": "VXQSHOF" + p,
        "title": _desc(f),
    }


def curr_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": _disp(f),
        "display_mask": f"TRUNCATE({f} ,2)",
        "perms": "VXQSHOF" + p,
        "title": _desc(f),
    }


def yn_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": _disp(f),
        "perms": "VXQSHOF" + p,
        "select_array": {"0": "No", "1": "Yes"},
        "display_mask": f"if({f} = '0','No','Yes')",
        "title": _desc(f),
    }


def ynradio_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": _disp(f),
        "perms": "VXQSHOF" + p,
        "display_mask": f"if({f} = '0','No','Yes')",
        "format_input_fun": format_radio,
        "title": _desc(f),
    }


_DATE_COMMON = {
    "display_mask_tpl": 'date_format({f},"%d %M %Y")',
    "order_mask_tpl": 'date_format({f},"%Y-%m-%d %T")',
}


def _date_cols(f: str) -> dict[str, Any]:
    return {
        "display_mask": f'date_format({f},"%d %M %Y")',
        "order_mask": f'date_format({f},"%Y-%m-%d %T")',
        "range_mask": f'date_format({f},"%Y-%m-%d %T")',
        "calendar": {"js_format": "dd MM yy", "options": {"showButtonPanel": True}},
    }


def date_field(f: str, p: str = "") -> dict[str, Any]:
    return {"display_text": _disp(f), "perms": "VXQSHOF" + p, **_date_cols(f), "title": _desc(f)}


def hidden_txt_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": _disp(f),
        "perms": "XQSHOF" + p,
        "table_fun": format_left_align,
        "hidden": True,
        "title": _desc(f),
    }


def hidden_num_field(f: str, p: str = "") -> dict[str, Any]:
    return {"display_text": _disp(f), "perms": "XQSHOF" + p, "hidden": True, "title": _desc(f)}


def hidden_date_field(f: str, p: str = "") -> dict[str, Any]:
    return {"display_text": _disp(f), "perms": "XQSHOF" + p, **_date_cols(f), "title": _desc(f)}


def ro_date_field(f: str, p: str = "") -> dict[str, Any]:
    return {
        "display_text": _disp(f),
        "perms": "VXQSHOF" + p,
        "format_input_fun": format_rem_input,
        "table_fun": format_date,
        "edit_fun": format_date,
        "title": _desc(f),
    }


def dummy_field(f: str) -> dict[str, Any]:
    return {"display_text": "", "perms": "EF", "display_mask": f}


# --------------------------------------------------------------------------
# Audit / bookkeeping fields
# --------------------------------------------------------------------------
def return_today(col, val, row=None, instance=None, *_):
    return _dt.date.today().isoformat()


def return_session_user(col, val, row=None, instance=None, *_):
    return current_user()


def create_date_field(f: str = "create_date", p: str = "") -> dict[str, Any]:
    return {
        "display_text": "Create Date",
        "perms": "XQSHOFTVA",
        "default": lambda: _dt.date.today().isoformat(),
        "hidden_edit": True,
        "hidden_add": True,
    }


def create_user_field(f: str = "create_user", p: str = "") -> dict[str, Any]:
    return {
        "display_text": "Create User",
        "perms": "XQSHOFTVA",
        "default": lambda: current_user(),
        "hidden_edit": True,
        "hidden_add": True,
    }


def change_date_field(f: str = "change_date", p: str = "") -> dict[str, Any]:
    return {
        "display_text": "Change Date",
        "perms": "XQSHOFTVEA",
        "default": lambda: _dt.date.today().isoformat(),
        "on_add_fun": return_today,
        "on_edit_fun": return_today,
        "hidden_edit": True,
        "hidden_add": True,
    }


def change_user_field(f: str = "change_user", p: str = "") -> dict[str, Any]:
    return {
        "display_text": "Change User",
        "perms": "XQSHOFTVEA",
        "default": lambda: current_user(),
        "on_add_fun": return_session_user,
        "on_edit_fun": return_session_user,
        "hidden_edit": True,
        "hidden_add": True,
    }


# --------------------------------------------------------------------------
# Join fields
# --------------------------------------------------------------------------
def _join(t: str, display_mask: str, *, column: str = "uniq_key",
          real_column: str = "uniq_key") -> dict[str, Any]:
    return {
        "table": t,
        "column": column,
        "display_mask": display_mask,
        "real_column": real_column,
        "type": "left",
        "alias": t,
    }


def join_txt_field(f: str, t: str, p: str = "") -> dict[str, Any]:
    return {"display_text": _disp(f), "perms": "VXQSHOF" + p, "table_fun": format_left_align,
            "join": _join(t, f"{t}.{f}"), "title": _desc(f)}


def join_num_field(f: str, t: str, p: str = "") -> dict[str, Any]:
    return {"display_text": _disp(f), "perms": "VXQSHOF" + p,
            "join": _join(t, f"{t}.{f}"), "title": _desc(f)}


def join_yn_field(f: str, t: str, p: str = "") -> dict[str, Any]:
    mask = f"IF({f} = '0','No','Yes')"
    return {"display_text": _disp(f), "perms": "VXQSHOF" + p, "display_mask": mask,
            "select_array": {"0": "No", "1": "Yes"}, "join": _join(t, mask), "title": _desc(f)}


def join_ynull_field(f: str, t: str, p: str = "") -> dict[str, Any]:
    mask = f"IF({f} IS NULL,'No','Yes')"
    return {"display_text": _disp(f), "perms": "VXQSHOF" + p, "display_mask": mask,
            "select_array": {"0": "No", "1": "Yes"}, "join": _join(t, mask), "title": _desc(f)}


def join_date_field(f: str, t: str, p: str = "") -> dict[str, Any]:
    d = {"display_text": _disp(f), "perms": "VXQSHOF" + p, **_date_cols(f),
         "join": _join(t, f"{t}.{f}"), "title": _desc(f)}
    return d


def join_select_field(f: str, t: str, p: str = "") -> dict[str, Any]:
    return {"display_text": _disp(f), "perms": "VXQSHOF" + p,
            "table_fun": show_values_2_select, "view_fun": show_values_2_select,
            "join": _join(t, f"{t}.{f}"), "title": _desc(f)}


def hidden_join_txt_field(f: str, t: str, p: str = "") -> dict[str, Any]:
    d = join_txt_field(f, t, p)
    d["hidden"] = True
    return d


def hidden_join_num_field(f: str, t: str, p: str = "") -> dict[str, Any]:
    d = join_num_field(f, t, p)
    d["hidden"] = True
    return d


def hidden_join_yn_field(f: str, t: str, p: str = "") -> dict[str, Any]:
    mask = f"IF({f} = '0','No','Yes')"
    return {"display_text": _disp(f), "perms": "VXQSHOF" + p, "display_mask": mask,
            "select_array": {"0": "No", "1": "Yes"}, "hidden": True,
            "join": _join(t, mask), "title": _desc(f)}


def hidden_join_date_field(f: str, t: str, p: str = "") -> dict[str, Any]:
    return {"display_text": _disp(f), "perms": "VXQSHO" + p, "table_fun": format_date,
            "calendar": "%d %b %Y", "hidden": True, "join": _join(t, f"{t}.{f}"),
            "title": _desc(f)}


def join_qmf_txt_field(f: str, t: str, p: str = "") -> dict[str, Any]:
    return {"display_text": _disp(f), "perms": "VXQSHOF" + p, "table_fun": format_left_align,
            "join": _join(t, f"{t}.{f}", column="uniq_qtree", real_column="qtreeasusedindads"),
            "title": _desc(f)}


def join_qmf_date_field(f: str, t: str, p: str = "") -> dict[str, Any]:
    return {"display_text": _disp(f), "perms": "VXQSHOF" + p, **_date_cols(f),
            "join": _join(t, f"{t}.{f}", column="uniq_qtree", real_column="qtreeasusedindads"),
            "title": _desc(f)}
