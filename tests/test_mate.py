import pytest
from examples.well_list import build_editor
from mate.db import Database
from mate.editor import PermissionDenied, ValidationError
from mate.seed import seed_demo
from mate.web import create_app

H = {"X-Mate-Request": "1"}


@pytest.fixture()
def ed():
    db = Database("sqlite:///:memory:")
    seed_demo(db)
    return build_editor(db)


@pytest.fixture()
def client(ed):
    app = create_app(ed, secret_key="t")
    return app.test_client()


def n(ed, st, prefs=None):
    return ed.get_table_data(st, prefs)["num_results"]


def test_seed_and_defaults(ed):
    d = ed.get_table_data({})
    assert d["num_results"] == 100 and len(d["rows"]) == 20
    assert d["record_text"] == "Displaying 1 - 20 of 100 Records"
    assert "id" not in [c["key"] for c in d["columns"]]  # id has no T perm


def test_search_filter_sort_page(ed):
    assert n(ed, {"searchString": "Tjeerd"}) == 10
    assert n(ed, {"searchString": "Yes"}) == 7                # display_mask searched
    assert n(ed, {"filterSearches": {"ow_project": "NL_ONSHORE"}}) == 15
    adv = {"searchType": "advanced", "matchAll": True, "advSearches": [
        {"cols": "ow_project", "opts": "like", "strs": "OFFSHORE"}, {"cols": "nr_bh", "opts": ">", "strs": "20"}]}
    assert n(ed, adv) == 7
    adv["matchAll"] = False
    assert n(ed, adv) == 57
    d = ed.get_table_data({"orderByColumn": "nr_bh", "ascOrDesc": "desc", "displayNum": 10, "start": 30})
    assert d["paging"]["cur_page"] == 3 and d["rows"][0]["cells"][3]["t"]


def test_injection_is_inert(ed):
    d = ed.get_table_data({"orderByColumn": "id; drop table test_data", "searchString": "x' or '1'='1"})
    assert d["state"]["orderByColumn"] == "id" and d["num_results"] == 0
    assert n(ed, {}) == 100


def test_update_validation_permissions(ed):
    assert ed.update_row({"to_delete": "1"}, 2302, in_place=True) == 2302
    assert ed.db.scalar("select to_delete from test_data where id=2302") == 1
    with pytest.raises(ValidationError):
        ed.update_row({"to_delete": "7"}, 2302)
    with pytest.raises(PermissionDenied):
        ed.update_row({"ow_project": "x"}, 2302)
    with pytest.raises(PermissionDenied):
        ed.delete_rows([2302])
    with pytest.raises(PermissionDenied):
        ed.insert_row({"to_delete": "0"})


def test_sql_filters_limit_rights(ed):
    ed.set_config("sqlFilters", "test_data.to_delete = 0")
    assert not ed.has_rights_to_row(316)        # row 316 has to_delete=1
    with pytest.raises(PermissionDenied):
        ed.update_row({"to_delete": "0"}, 316)


def test_crud_with_full_permissions():
    db = Database("sqlite:///:memory:")
    seed_demo(db)
    ed = build_editor(db)
    ed.permissions = "ACDEVQ"
    for c in ("ow_project", "work_set_id", "work_set_name", "create_date", "create_user_id", "first_date", "last_date"):
        ed.table_columns[c]["perms"] += "AC"
    new = ed.insert_row({"ow_project": "P", "work_set_id": "1", "work_set_name": "w", "create_date": "2024-01-01",
                         "create_user_id": "u", "first_date": "2024-01-01", "last_date": "2024-01-01"})
    assert new
    assert ed.copy_rows([new]) and n(ed, {}) == 102
    assert ed.delete_rows([new]) == [new] and n(ed, {}) == 101


def test_columns_prefs_and_export(ed):
    prefs = ed.update_hidden_columns({}, {"nr_bh": False})
    prefs = ed.update_column_order(prefs, ["last_date"])
    keys = [c["key"] for c in ed.get_table_data({}, prefs)["columns"]]
    assert keys[0] == "last_date" and "nr_bh" not in keys
    csv = ed.export_csv({"searchString": "Tjeerd"}).split("\r\n")
    assert csv[0].startswith('"OW Project"') and len(csv) == 12


def test_languages(ed):
    from mate.lang import LangVars, available_languages
    assert len(available_languages()) == 10
    assert "Rijen" in LangVars("nl").ttlDispRecs


def test_api(client):
    assert client.post("/api/table", json={}).status_code == 400          # CSRF header required
    r = client.post("/api/table", json={"state": {"searchString": "wcc_cafe"}}, headers=H)
    assert r.json["num_results"] == 1
    assert client.post("/api/update", json={"id": 1389, "values": {"to_delete": "1"}}, headers=H).json["ok"]
    assert client.post("/api/update", json={"id": 1389, "values": {"to_delete": "9"}}, headers=H).status_code == 422
    assert client.post("/api/delete", json={"ids": [1389]}, headers=H).status_code == 403
    assert client.post("/api/columns/save", json={"visible": {"nr_bh": False}}, headers=H).json["ok"]
    cols = [c["key"] for c in client.post("/api/table", json={}, headers=H).json["columns"]]
    assert "nr_bh" not in cols                                              # persisted in session
    import base64, json
    sd = base64.b64encode(json.dumps({"searchString": "cafe"}).encode()).decode()
    r = client.get("/export.csv", query_string={"session_data": sd})
    assert r.data.startswith(b"\xef\xbb\xbf") and b"wcc_cafe" in r.data
    assert client.get("/").status_code == 200
