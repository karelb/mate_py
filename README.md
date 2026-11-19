# mate_py – Python port of `mate_bs` (MySQL Ajax Table Editor, Bootstrap edition)

The tarball is a PHP app: a generic, configurable AJAX table editor ("MATE") plus one page built on it,
the **OpenWorks Well List Manager** (`example/index.php`) over the `test_data` table.

## Run
```
pip install -r requirements.txt
python run.py                 # http://127.0.0.1:5000  (SQLite demo, auto-seeded from sql/test_data.sql)
pytest                        # 26 tests
```

## Use it for your own databases and tables
Everything you configure is in **`web.py`**. Every page in the menu connects to its own database and table.

1. **Databases** – name every database in `DATABASES`, e.g.
   `DATABASES = {"default": None, "crm": os.environ.get("CRM_DB_URL"), "northwind": "sqlite:///db/northwind.db"}`.
   `None` means `MATE_DB_URL=mysql+pymysql://user:pw@host/dbname` (or `MATE_DB_HOST/NAME/USER/PASSWORD`, or a
   `dbc.ini`). Each database gets one connection pool, shared by its pages. Other env vars: `MATE_SECRET_KEY`,
   `MATE_LANG` (en de es fr it nl pt-br ru tr zh), `MATE_DEBUG`.
2. **Pages** – let the generator read the table structure and write one `PAGES[key]` entry per table, holding the
   `database` name, the `table` and the column settings:
   ```
   python tools/generate_columns.py --tables customers,orders          # default database, read-only
   python tools/generate_columns.py --all --editable orders products   # these two get add/edit/copy/delete
   python tools/generate_columns.py --db crm --tables customers        # page "crm_customers" on DATABASES["crm"]
   python tools/generate_columns.py --db crm --tables customers --page clients   # choose the page key
   python tools/generate_columns.py --tables orders --print            # just show the code
   ```
   Options: `--db`, `--page`, `--url`, `--show-id`, `--primary-col`, `--replace`, `--target`. The page key is the
   table name for the default database and `<db>_<table>` otherwise, so equal table names in different databases
   don't clash. Types are mapped to field helpers (numbers, text, long text -> textarea, dates -> calendar,
   boolean/`tinyint(1)` -> Yes/No, blobs skipped); `NOT NULL` columns without a default become required when the
   table is editable. Pages already in the block are kept, so you can add one at a time.
3. **Tweaks** – change labels, permissions, titles or options in `OVERRIDES` (also in `web.py`, outside the
   generated block, so regenerating never overwrites them), keyed by page. An override may also set `database` or
   `table` to point a page elsewhere; two pages can show the same table (e.g. with different `sqlFilters`).
   The shipped `test_data` entry shows the idea.
4. **Start page and menu** – `/` is a static start page: the brand bar on top, a menu row underneath and a
   short welcome text (`HOME_TITLE`, `HOME_HTML`); it never touches a database. The menu row holds dropdowns
   whose entries open the pages (`/t/<page>/`), where the table is loaded from that page's database.
   `MENU` in `web.py` defines the layout, for example
   `MENU = [("Seismic", ["surveys", "lines"]), ("CRM", ["crm_customers"]), "orders"]`
   (a tuple is a dropdown, a plain name a direct link). With `MENU = None` all pages go in one "Tables" dropdown.
   `ENABLED_PAGES` selects the pages, `nav_title` in an override sets the menu text, and the active page is
   highlighted. On small screens the menu collapses behind a toggle button.

Run with `python run.py` or any WSGI server: `gunicorn web:app`.

## Mapping
| PHP | Python |
|---|---|
| `include/DBC.php`, `db.php`, `db_functions.php` | `mate/db.py` (SQLAlchemy, named params, no creds in code) |
| `include/mate_field_func.php` | `mate/fields.py` (same helpers & permission letters) |
| `php/mate/AjaxTableEditor.php` + `BSAjaxTableEditor.php` | `mate/editor.py` |
| `php/mate/lang/LangVars-*.php` | `mate/lang/*.json` + `mate/lang.py` |
| `include/Common.php`, `example/index.php` request handling | `mate/web.py` (Flask: start page + one page per configured page, each with its own database), `templates/` (`base.html` brand bar + menu, `home.html`, `index.html`) |
| `js/mate/ajax_table_editor.js`, `seistt_functions.js` | `static/js/mate.js` (vanilla JS, no jQuery) on stock **Bootstrap 3.4.1** (bundled, offline) |
| `example/index.php` config | `web.py` (`DATABASES`, `PAGES['test_data']`, `OVERRIDES['test_data']`) |
| *(new)* settings per table | `tools/generate_columns.py` + `mate/introspect.py` write the generated block in `web.py` |

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
