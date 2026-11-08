"""Run the Well List Manager demo:  python run.py   ->  http://127.0.0.1:5000/"""
import os

from examples.well_list import build_editor
from mate.db import Database
from mate.seed import seed_demo
from mate.web import create_app

db = Database()
if os.environ.get("MATE_SEED", "1") == "1":
    seed_demo(db)                      # only fills an empty/missing test_data table
app = create_app(build_editor(db, lang=os.environ.get("MATE_LANG", "en")))

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)),
            debug=bool(os.environ.get("MATE_DEBUG")))
