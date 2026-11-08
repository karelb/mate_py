# mate_py – Python port of `mate_bs` (MySQL Ajax Table Editor, Bootstrap edition)

The tarball is a PHP app: a generic, configurable AJAX table editor ("MATE") plus one page built on it,
the **OpenWorks Well List Manager** (`example/index.php`) over the `test_data` table.

## Run
```
pip install -r requirements.txt
python run.py                 # http://127.0.0.1:5000  (SQLite demo, auto-seeded from sql/test_data.sql)
pytest                        # 9 tests
```
Use MySQL/MariaDB: `MATE_DB_URL=mysql+pymysql://user:pw@host/demo` (or `MATE_DB_HOST/NAME/USER/PASSWORD`,
or a `dbc.ini`). Also: `MATE_SECRET_KEY`, `MATE_LANG` (en de es fr it nl pt-br ru tr zh), `MATE_DEBUG`.

## Mapping
| PHP | Python |
|---|---|
| `include/DBC.php`, `db.php`, `db_functions.php` | `mate/db.py` (SQLAlchemy, named params, no creds in code) |
| `include/mate_field_func.php` | `mate/fields.py` (same helpers & permission letters) |
| `php/mate/AjaxTableEditor.php` + `BSAjaxTableEditor.php` | `mate/editor.py` |
| `php/mate/lang/LangVars-*.php` | `mate/lang/*.json` + `mate/lang.py` |
| `include/Common.php`, `example/index.php` request handling | `mate/web.py` (Flask), `templates/index.html` |
| `js/mate/ajax_table_editor.js`, `seistt_functions.js` | `static/js/mate.js` (vanilla JS, no jQuery) on stock **Bootstrap 3.4.1** (bundled, offline) |
| `example/index.php` config | `examples/well_list.py` |

Ported: quick/advanced search, column filters, distinct-value picker, sorting, pagination (links/dropdown),
rows-per-page, view dialog, in-place edit (and modal edit), add/copy/delete, show/hide + reorder columns,
CSV export (BOM, same quoting), joins, data filters, having/group by, hooks (`after_*`, `user_*_fun`),
validation (`req`, `val_fun`, `on_*_fun`), 10 languages, `setConfig` (camelCase accepted).

## Deliberate differences
* Server returns **data**, not HTML + JS commands; view state is passed explicitly (stateless server).
* **Security**: DB credentials were hard-coded in `DBC.php` (host, user, password) – not copied; rotate them.
  Cell values are escaped (PHP emitted raw HTML); `select_array` values are validated server-side;
  `display_num` is clamped; JSON endpoints need an `X-Mate-Request` header (CSRF); `handleHacking()`→HTTP 403.
* Column prefs: signed Flask session instead of an `mcrypt` cookie (mcrypt is gone in modern PHP; key was hard-coded).
* `INSERT … SET` rewritten as standard `INSERT … VALUES`. SQLite gets shims for `if()`, `concat()`, `date_format()`, `truncate()`.
* `col_header_info`/`input_info` HTML strings became `title`/`min_width`/`readonly`.

## Not ported
File uploads, multi-row edit form, user buttons/icons/columns, browser back-button history, login/logout
(`../main/login.php` wasn't in the tar; set `create_app(current_user=...)`), help file `../help/*.html`
(help text is shown from `help_html`), the unused jQuery/w2ui/jQuery-UI assets. The original `test_data` table has no
PRIMARY KEY/AUTO_INCREMENT, so add/copy (disabled by the example's permissions) need one on MySQL.

## UI
Stock Bootstrap 3.4.1 (+ theme) look: inverse navbar with search input-group, panel with `table-striped table-hover`, `btn-group-xs` row actions, `pagination-sm`, Bootstrap modals (form-horizontal), `alert` messages, `list-group` for column order/distinct values. Modals are toggled with Bootstrap's CSS classes, so no Bootstrap JS/jQuery is needed.
