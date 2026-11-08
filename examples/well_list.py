"""OpenWorks Well List Manager - port of ``example/index.php``.

Configures a generic :class:`mate.editor.AjaxTableEditor` for the ``test_data``
table exactly like the PHP page did: every column becomes a read-only text
field except ``to_delete``, which is a Yes/No flag editable in place.
"""
from __future__ import annotations

from mate import fields
from mate.db import Database
from mate.editor import AjaxTableEditor

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


def ucwords(s: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in s.split(" "))


def build_editor(db: Database | None = None, lang: str = "en") -> AjaxTableEditor:
    db = db or Database()
    table = "test_data"

    columns = {}
    for fn in db.table_fieldnames(table):
        if fn == "id":
            columns[fn] = fields.id_field(fn, "T")
        else:
            columns[fn] = fields.txt_field(fn, "T")
            if columns[fn]["display_text"] == fn:
                columns[fn]["display_text"] = ucwords(fn.replace("_", " "))

    columns["ow_project"]["display_text"] = "OW Project"
    columns["work_set_id"]["display_text"] = "Well List Id"
    columns["work_set_name"]["display_text"] = "Well List Name"
    columns["to_delete"] = fields.yn_field("to_delete", "TE")
    columns["to_delete"]["display_text"] = "Delete?"

    ed = AjaxTableEditor(table, "id", None, "SVQSXOHUIFE", columns, db=db, lang=lang)
    ed.set_config("tableTitle", "OpenWorks Well List Manager")
    ed.set_config("helpHtml", HELP_HTML)
    ed.set_config("editInPlace", True)
    ed.set_config("addRowTitle", "Add Login Info")
    ed.set_config("editRowTitle", "Edit Login Info")
    ed.set_config("viewRowTitle", "View Login Info")
    ed.set_config("filterPosition", "top-after")
    ed.set_config("paginationLinks", True)
    ed.set_config("iconColPosition", "first")
    return ed
