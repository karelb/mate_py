"""Start the app:  python run.py   ->  http://127.0.0.1:5000/

Databases, pages and column settings are configured in web.py; every page connects to
the database and table named in its settings.  When the "default" database is not
configured it falls back to a local SQLite file (mate_demo.db); a page showing the demo
table ``test_data`` from a SQLite database gets it created and filled automatically
(set MATE_SEED=0 to prevent that).
"""
import os

import web
from mate.seed import seed_demo

if not web.PAGES:
    raise SystemExit("No pages configured. Run: python tools/generate_columns.py --tables <table,...>")

databases = web.open_databases()
if os.environ.get("MATE_SEED", "1") == "1":
    for page in web.enabled_pages():
        db = databases[web.page_setting(page, "database") or "default"]
        if web.page_setting(page, "table") == "test_data" and db.dialect == "sqlite" \
                and not db.table_exists("test_data"):
            seed_demo(db)
app = web.build_app(databases)

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)),
            debug=bool(os.environ.get("MATE_DEBUG")))
