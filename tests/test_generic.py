"""Generator script, generated settings and the multi-table web app."""
import importlib
import importlib.util

import pytest

import web
from mate import introspect
from mate.db import Database
from mate.editor import ConfigError

H = {"X-Mate-Request": "1"}

SCHEMA = """
create table customers (
  id integer primary key,
  name varchar(100) not null,
  email varchar(255),
  notes varchar(1000),
  active boolean,
  created date,
  balance numeric(10,2),
  avatar blob
);
create table orders (
  id integer primary key,
  customer_id integer,
  total float,
  status varchar(20) not null
);
create table log_entries (code varchar(10), msg varchar(50));
insert into customers (name, email, active, created, balance) values
  ('Alice', 'a@example.com', 1, '2024-01-05', 10.5), ('Bob', 'b@example.com', 0, '2024-02-06', 20);
insert into orders (customer_id, total, status) values (1, 9.99, 'new'), (2, 5, 'paid'), (1, 7.25, 'paid');
"""


@pytest.fixture()
def dburl(tmp_path):
    url = f"sqlite:///{tmp_path / 'shop.db'}"
    db = Database(url)
    with db.engine.begin() as conn:
        raw = conn.connection
        raw.executescript(SCHEMA)
    return url


def generate(dburl, target, *args):
    gen = importlib.import_module("tools.generate_columns")
    return gen.main(["--url", dburl, "--target", str(target), *args])


def load_tables(path):
    ns = {}
    exec(compile(open(path, encoding="utf-8").read(), str(path), "exec"), ns)
    return ns["PAGES"]


def test_generated_column_settings(dburl, tmp_path):
    out = tmp_path / "gen.py"
    assert generate(dburl, out, "--tables", "customers,orders", "--editable", "orders") == 0
    text = out.read_text()
    assert "skipped column 'avatar': binary column" in text
    tables = load_tables(out)
    assert list(tables) == ["customers", "orders"]

    c, o = tables["customers"], tables["orders"]
    assert c["primary_col"] == "id" and c["title"] == "Customers"
    assert "E" not in c["permissions"] and "E" in o["permissions"] and "D" in o["permissions"]
    cols = c["columns"]
    assert "avatar" not in cols
    assert "T" in cols["name"]["perms"]
    assert "table_fun" in cols["name"] and cols["name"]["display_text"] == "Name"
    assert "textarea" in cols["notes"] and "T" not in cols["notes"]["perms"]       # long text: not in table
    assert cols["active"]["select_array"] == {"0": "No", "1": "Yes"}
    assert "calendar" in cols["created"]
    assert "T" not in cols["id"]["perms"]
    # editable table: add/edit/copy letters and required flag on NOT NULL columns
    assert all(l in o["columns"]["status"]["perms"] for l in "TAEC") and o["columns"]["status"]["req"] is True
    assert "req" not in o["columns"]["total"]


def test_regenerate_keeps_other_tables_and_manual_code(dburl, tmp_path):
    out = tmp_path / "app.py"
    out.write_text("HEAD = 1\n\n# BEGIN GENERATED PAGES\nPAGES = {}\n# END GENERATED PAGES\n\nOVERRIDES = {'x': 1}\n")
    assert generate(dburl, out, "--tables", "customers") == 0
    assert generate(dburl, out, "--tables", "orders", "--show-id") == 0
    text = out.read_text()
    assert text.startswith("HEAD = 1\n") and text.rstrip().endswith("OVERRIDES = {'x': 1}")
    tables = load_tables(out)
    assert list(tables) == ["customers", "orders"]
    assert "T" in tables["orders"]["columns"]["id"]["perms"]          # --show-id
    # same command again is idempotent; --replace drops the other table
    before = out.read_text()
    generate(dburl, out, "--tables", "orders", "--show-id")
    assert out.read_text() == before
    generate(dburl, out, "--tables", "customers", "--replace")
    assert list(load_tables(out)) == ["customers"]


def test_generator_errors(dburl, tmp_path):
    out = tmp_path / "x.py"
    assert generate(dburl, out, "--tables", "missing") == 1
    assert generate(dburl, out, "--tables", "log_entries") == 1                      # no primary key
    assert generate(dburl, out, "--tables", "log_entries", "--primary-col", "code") == 0
    assert generate(dburl, out, "--all") == 0          # --all reports tables without a key and carries on
    assert set(load_tables(out)) >= {"customers", "orders"}
    with pytest.raises(ConfigError):
        introspect.reflect_table(Database(dburl), "bad name;drop")


def test_print_does_not_write(dburl, tmp_path, capsys):
    out = tmp_path / "never.py"
    assert generate(dburl, out, "--tables", "orders", "--print") == 0
    assert not out.exists() and "PAGES['orders']" in capsys.readouterr().out


@pytest.fixture()
def shop(dburl, tmp_path, monkeypatch):
    out = tmp_path / "shop_tables.py"
    generate(dburl, out, "--tables", "customers,orders", "--editable", "orders")
    monkeypatch.setattr(web, "PAGES", load_tables(out))
    monkeypatch.setattr(web, "OVERRIDES", {"orders": {"nav_title": "Sales", "columns": {"status": {"display_text": "State"}}}})
    monkeypatch.setattr(web, "ENABLED_PAGES", None)
    monkeypatch.setattr(web, "MENU", None)          # tests must not depend on the menu in web.py
    return web.build_app(Database(dburl), secret_key="t").test_client()


def test_start_page_is_static(shop, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the start page must not touch the database")
    monkeypatch.setattr(Database, "query", boom)
    r = shop.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "navbar-inverse" in html and "mate-menubar" in html and "SeisTT" in html      # brand bar + menu row
    assert "mate-table" not in html and "mate.js" not in html                               # no table, no table script
    assert "Choose a page from the menu" in html


def test_default_menu_is_one_dropdown(shop):
    html = shop.get("/t/orders/").get_data(as_text=True)
    assert html.count('<li class="dropdown') == 1 and "Tables" in html
    menu = html.split('class="dropdown-menu"')[1].split("</ul>")[0]
    assert 'href="/t/customers/"' in menu and 'href="/t/orders/"' in menu
    assert '<li class="active"><a href="/t/orders/">Sales</a></li>' in menu          # active item + nav_title override
    assert '<li class="dropdown active">' in html                                    # parent marked active too
    assert '<li class=""><a href="/t/customers/">Customers</a></li>' in menu
    assert shop.get("/t/nope/").status_code == 404
    assert shop.post("/t/nope/api/table", json={}, headers=H).status_code == 404


def test_custom_menu_groups_and_links(shop, dburl, monkeypatch):
    monkeypatch.setattr(web, "MENU", [("Selling", ["orders"]), "customers"])
    client = web.build_app(Database(dburl), secret_key="t").test_client()
    html = client.get("/t/customers/").get_data(as_text=True)
    assert html.count('<li class="dropdown') == 1 and "Selling" in html
    assert '<li class="active"><a href="/t/customers/">Customers</a></li>' in html   # direct (non-dropdown) link
    start = client.get("/").get_data(as_text=True)
    assert 'list-group-item" href="/t/orders/"' in start and 'list-group-item" href="/t/customers/"' in start


def test_menu_validation(shop, dburl, monkeypatch):
    for bad in ([("Group", ["orders", "ghost"])], ["ghost"]):
        monkeypatch.setattr(web, "MENU", bad)
        with pytest.raises(ConfigError, match="ghost"):
            web.build_app(Database(dburl))


def test_tables_are_independent(shop):
    c = shop.post("/t/customers/api/table", json={}, headers=H).json
    o = shop.post("/t/orders/api/table", json={}, headers=H).json
    assert c["num_results"] == 2 and o["num_results"] == 3
    assert [x["key"] for x in o["columns"]] == ["customer_id", "total", "status"]
    assert o["columns"][2]["text"] == "State"                               # override applied
    # hiding a column of one table does not touch the other
    assert shop.post("/t/customers/api/columns/save", json={"visible": {"email": False}}, headers=H).json["ok"]
    c = shop.post("/t/customers/api/table", json={}, headers=H).json
    o = shop.post("/t/orders/api/table", json={}, headers=H).json
    assert "email" not in [x["key"] for x in c["columns"]] and len(o["columns"]) == 3
    # permissions are per table: customers are read-only, orders editable
    assert shop.post("/t/customers/api/delete", json={"ids": [1]}, headers=H).status_code == 403
    assert shop.post("/t/orders/api/delete", json={"ids": [1]}, headers=H).json["deleted"] == [1]
    r = shop.post("/t/orders/api/insert", json={"values": {"customer_id": "2", "total": "3.5", "status": "new"}}, headers=H)
    assert r.json["ok"]
    assert shop.post("/t/orders/api/table", json={}, headers=H).json["num_results"] == 3
    assert shop.post("/t/orders/api/insert", json={"values": {"total": "1"}}, headers=H).status_code == 422   # status required
    csv = shop.get("/t/orders/export.csv").data
    assert csv.startswith(b"\xef\xbb\xbf") and b'"State"' in csv


def test_single_table_still_gets_menu(dburl, tmp_path, monkeypatch):
    out = tmp_path / "one.py"
    generate(dburl, out, "--tables", "orders")
    monkeypatch.setattr(web, "PAGES", load_tables(out))
    monkeypatch.setattr(web, "OVERRIDES", {})
    monkeypatch.setattr(web, "MENU", None)
    client = web.build_app(Database(dburl), secret_key="t").test_client()
    assert client.get("/").status_code == 200
    assert 'href="/t/orders/"' in client.get("/").get_data(as_text=True)


def test_enabled_tables_selects_and_orders(shop, dburl, monkeypatch):
    monkeypatch.setattr(web, "ENABLED_PAGES", ["orders"])
    client = web.build_app(Database(dburl), secret_key="t").test_client()
    html = client.get("/").get_data(as_text=True)
    assert 'href="/t/orders/"' in html and "/t/customers/" not in html
    assert client.get("/t/customers/").status_code == 404
    monkeypatch.setattr(web, "ENABLED_PAGES", ["nothere"])
    with pytest.raises(ConfigError):
        web.build_app(Database(dburl))


# --------------------------------------------------------------------------
# Every page its own database and table
# --------------------------------------------------------------------------
@pytest.fixture()
def crmurl(tmp_path):
    url = f"sqlite:///{tmp_path / 'crm.db'}"
    with Database(url).engine.begin() as conn:
        conn.connection.executescript("""
            create table customers (id integer primary key, name varchar(50) not null, city varchar(50));
            create table contacts (id integer primary key, email varchar(100));
            insert into customers (name, city) values ('Carol', 'Delft'), ('Dave', 'Assen'), ('Eve', 'Ede');
            insert into contacts (email) values ('x@example.com');
        """)
    return url


def test_generator_db_option_reads_databases_from_target(dburl, crmurl, tmp_path):
    out = tmp_path / "app.py"
    out.write_text(f"DATABASES = {{'default': {dburl!r}, 'crm': {crmurl!r}}}\n")
    assert generate_no_url(out, "--tables", "customers") == 0                      # default database
    assert generate_no_url(out, "--db", "crm", "--tables", "customers,contacts") == 0
    assert generate_no_url(out, "--db", "crm", "--tables", "customers", "--page", "clients") == 0
    pages = load_tables(out)
    assert list(pages) == ["customers", "crm_customers", "crm_contacts", "clients"]
    assert pages["customers"]["database"] == "default" and pages["customers"]["table"] == "customers"
    assert pages["crm_customers"]["database"] == "crm" and pages["crm_customers"]["table"] == "customers"
    assert "city" in pages["clients"]["columns"] and "city" not in pages["customers"]["columns"]
    # errors: unknown database name, --page with several tables, unsafe page key
    assert generate_no_url(out, "--db", "ghost", "--tables", "customers") == 2
    assert generate_no_url(out, "--db", "crm", "--tables", "customers,contacts", "--page", "x") == 2
    assert generate_no_url(out, "--db", "crm", "--tables", "customers", "--page", "a-b") == 2


def generate_no_url(target, *args):
    gen = importlib.import_module("tools.generate_columns")
    return gen.main(["--target", str(target), *args])


@pytest.fixture()
def multi(dburl, crmurl, tmp_path, monkeypatch):
    shop_out, crm_out = tmp_path / "shop_p.py", tmp_path / "crm_p.py"
    generate(dburl, shop_out, "--tables", "customers,orders", "--editable", "orders")
    generate(crmurl, crm_out, "--db", "crm", "--tables", "customers", "--editable")
    pages = {**load_tables(shop_out), **load_tables(crm_out)}
    monkeypatch.setattr(web, "PAGES", pages)
    monkeypatch.setattr(web, "DATABASES", {"default": dburl, "crm": crmurl})
    monkeypatch.setattr(web, "OVERRIDES", {"crm_customers": {"nav_title": "CRM customers"}})
    monkeypatch.setattr(web, "ENABLED_PAGES", None)
    monkeypatch.setattr(web, "MENU", [("Shop", ["customers", "orders"]), ("CRM", ["crm_customers"])])
    return web


def test_pages_connect_to_their_own_database(multi):
    client = multi.build_app(secret_key="t").test_client()
    shop = client.post("/t/customers/api/table", json={}, headers=H).json
    crm = client.post("/t/crm_customers/api/table", json={}, headers=H).json
    assert shop["num_results"] == 2 and crm["num_results"] == 3                 # same table name, other database
    assert "city" in [c["key"] for c in crm["columns"]] and "city" not in [c["key"] for c in shop["columns"]]
    html = client.get("/t/crm_customers/").get_data(as_text=True)
    assert '<li class="active"><a href="/t/crm_customers/">CRM customers</a></li>' in html
    # writes go to the page's own database only
    r = client.post("/t/crm_customers/api/insert", json={"values": {"name": "Frank", "city": "Zeist"}}, headers=H)
    assert r.json["ok"]
    assert Database(multi.DATABASES["crm"]).scalar("select count(*) from customers") == 4
    assert Database(multi.DATABASES["default"]).scalar("select count(*) from customers") == 2


def test_one_connection_per_database(multi):
    editors = multi.build_editors()
    assert editors["customers"].db is editors["orders"].db
    assert editors["customers"].db is not editors["crm_customers"].db
    assert editors["crm_customers"].cfg["instance_name"] == "mate_crm_customers_"


def test_override_switches_database_and_table(multi, monkeypatch):
    # a second page on the same table, and an override pointing a page at another database
    multi.PAGES["vip"] = dict(multi.PAGES["crm_customers"])
    monkeypatch.setattr(multi, "OVERRIDES", {"vip": {"title": "VIP", "config": {"sqlFilters": "city = 'Delft'"}}})
    client = multi.build_app(secret_key="t").test_client()
    assert client.post("/t/vip/api/table", json={}, headers=H).json["num_results"] == 1
    assert client.post("/t/crm_customers/api/table", json={}, headers=H).json["num_results"] == 3

    monkeypatch.setattr(multi, "OVERRIDES", {"crm_customers": {"database": "nowhere"}})
    with pytest.raises(ConfigError, match="nowhere"):
        multi.build_app(secret_key="t")


def test_unknown_page_database_is_reported(multi):
    multi.PAGES["crm_customers"]["database"] = "ghost"
    with pytest.raises(ConfigError, match="ghost"):
        multi.build_editors()


def test_importing_web_has_no_side_effects():
    import sys
    sys.modules.pop("web_probe", None)
    spec = importlib.util.spec_from_file_location("web_probe", web.__file__)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._app is None and "test_data" in mod.PAGES


def test_sqlite_text_columns_are_shown_in_the_table(tmp_path):
    """Northwind-style SQLite schema: every string is TEXT, keys and names in CamelCase."""
    url = f"sqlite:///{tmp_path / 'nw.db'}"
    with Database(url).engine.begin() as conn:
        conn.connection.executescript("""
            create table [Customers] ([CustomerID] TEXT, [CompanyName] TEXT, [Notes] varchar(2000),
                                      PRIMARY KEY (`CustomerID`));
            create table [Categories] ([CategoryID] INTEGER PRIMARY KEY AUTOINCREMENT, [CategoryName] TEXT);
        """)
    db = Database(url)
    cust = introspect.reflect_table(db, "Customers")
    assert {c.name: c.kind for c in cust.columns} == {"CustomerID": "text", "CompanyName": "text", "Notes": "longtext"}
    plan = {p["name"]: p for p in introspect.plan_columns(cust)}
    assert plan["CompanyName"]["helper"] == "txt_field" and "T" in plan["CompanyName"]["perms"]
    assert plan["CompanyName"]["text"] == "Company Name"
    assert "T" in plan["CustomerID"]["perms"] and plan["CustomerID"]["text"] == "Customer ID"   # text key shown
    cat = {p["name"]: p for p in introspect.plan_columns(introspect.reflect_table(db, "Categories"))}
    assert "T" not in cat["CategoryID"]["perms"]                                               # integer key hidden
    assert introspect.label("ow_project") == "Ow Project"
