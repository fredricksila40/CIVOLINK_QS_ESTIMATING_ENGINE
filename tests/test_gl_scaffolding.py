"""GL-tolerant scaffolding tests: optional enterprise fields render
when present and vanish without a trace when absent, plus dynamic
account-selection resolution. Synthetic fixtures stay invented-free;
shipped-data tests reconcile all 23 catalogue records against the
authoritative GL_ACCOUNTS lookup.
"""

from qs_engine.ui import views


class _StubRepo:
    def __init__(self, records):
        self._records = list(records)

    def list(self, domain):
        assert domain == "materials"
        return list(self._records)

    def get(self, domain, key):
        for record in self._records:
            if record.get("key") == key:
                return record
        raise KeyError(key)


def _gl_record():
    return {
        "key": "CEM-10175-PC425",
        "legacy_code": "portland_cement_42_5",
        "name": "Portland Cement 42.5",
        "category": "binder",
        "category_prefix": "CEM",
        "unit": "bag",
        "density": None,
        "default_wastage_pct": None,
        "verification_status": "NEEDS_VERIFICATION",
        "gl_code": "10175",
        "gl_account_name": "Cement & Binders",
        "gl_account_type": "Inventory (Asset)",
    }


def _plain_record():
    return {
        "key": "river_sand",
        "name": "River Sand",
        "category": "aggregate",
        "unit": "m³",
        "density": None,
        "default_wastage_pct": None,
        "verification_status": "NEEDS_VERIFICATION",
    }


# --- display helpers -----------------------------------------------------------

def test_gl_display_label_needs_both_parts():
    assert views.gl_display_label(_gl_record()) == (
        "10175 - Cement & Binders")
    assert views.gl_display_label(_plain_record()) == "—"
    assert views.gl_display_label({"gl_code": "10175"}) == "—"
    assert views.gl_display_label({"gl_account_name": "X"}) == "—"
    assert views.gl_display_label({}) == "—"


def test_gl_account_type_display():
    assert views.gl_account_type_display(_gl_record()) == (
        "Inventory (Asset)")
    assert views.gl_account_type_display(_plain_record()) == "—"
    assert views.gl_account_type_display({}) == "—"


def test_details_text_shows_gl_when_present_absent_otherwise():
    full = views.material_details_text(_gl_record())
    assert "GL Account: 10175 - Cement & Binders" in full
    assert "Account Type: Inventory (Asset)" in full
    assert "Portland Cement 42.5" in full
    plain = views.material_details_text(_plain_record())
    assert "GL Account: —" in plain
    assert "Account Type: —" in plain
    assert "River Sand" in plain


def test_shipped_gl_rows_match_supplied_table():
    from qs_engine.master_data.repository import MasterDataRepository
    repo = MasterDataRepository()
    expected = {
        "portland_cement_42_5": ("CEM", "10175", "Cement & Binders",
                                 "Inventory (Asset)", "CEM-10175-PC425"),
        "hydrated_lime": ("CEM", "10175", "Cement & Binders",
                          "Inventory (Asset)", "CEM-10175-LIM01"),
        "river_sand": ("AGG", "10176", "Aggregates",
                       "Inventory (Asset)", "AGG-10176-SND01"),
        "quarry_dust": ("QRY", "10138", "Quarry Products",
                        "Inventory (Asset)", "QRY-10138-QDT01"),
        "ballast_20mm": ("AGG", "10176", "Aggregates",
                         "Inventory (Asset)", "AGG-10176-BAL20"),
        "hardcore": ("QRY", "10138", "Quarry Products",
                     "Inventory (Asset)", "QRY-10138-HCR01"),
        "murram": ("QRY", "10138", "Quarry Products",
                   "Inventory (Asset)", "QRY-10138-MRM01"),
        "building_stone": ("QRY", "10138", "Quarry Products",
                           "Inventory (Asset)", "QRY-10138-STN01"),
        "concrete_block_200mm": ("PRC", "10183",
                                 "Precast & Concrete Products",
                                 "Inventory (Asset)", "PRC-10183-BLK200"),
        "concrete_block_150mm": ("PRC", "10183",
                                 "Precast & Concrete Products",
                                 "Inventory (Asset)", "PRC-10183-BLK150"),
        "binding_wire": ("HRD", "10131", "General Hardware & Fixing",
                         "Inventory (Asset)", "HRD-10131-BWR01"),
        "wire_nails": ("HRD", "10131", "General Hardware & Fixing",
                       "Inventory (Asset)", "HRD-10131-NLS01"),
        "formwork_timber": ("SCF", "10130", "Scaffolding & Formwork",
                            "Inventory (Asset)", "SCF-10130-TMB01"),
        "plywood_18mm": ("SCF", "10130", "Scaffolding & Formwork",
                         "Inventory (Asset)", "SCF-10130-PLY18"),
        "emulsion_paint": ("PNT", "10186", "Painting & Coating",
                           "Inventory (Asset)", "PNT-10186-PNT01"),
        "gloss_paint": ("PNT", "10186", "Painting & Coating",
                        "Inventory (Asset)", "PNT-10186-GLS01"),
        "tile_adhesive": ("CHM", "10188",
                          "Adhesives & Construction Chemicals",
                          "Inventory (Asset)", "CHM-10188-ADH01"),
        "tile_grout": ("CHM", "10188",
                       "Adhesives & Construction Chemicals",
                       "Inventory (Asset)", "CHM-10188-GRT01"),
        "gypsum_plaster": ("WCS", "10185", "Wall & Ceiling Systems",
                           "Inventory (Asset)", "WCS-10185-GYP01"),
        "ceiling_board": ("WCS", "10185", "Wall & Ceiling Systems",
                          "Inventory (Asset)", "WCS-10185-CLG01"),
        "water": ("WSU", "50066", "Site Utilities - Water",
                  "Direct Cost / Expense", "WSU-50066-WTR01"),
        "polythene_sheeting": ("WPF", "10187",
                               "Waterproofing & Sealants",
                               "Inventory (Asset)", "WPF-10187-SHT01"),
        "release_agent": ("CHM", "10188",
                          "Adhesives & Construction Chemicals",
                          "Inventory (Asset)", "CHM-10188-RLA01"),
    }
    for key, (prefix, code, name, typ, item) in expected.items():
        record = repo.get("materials", key)
        assert record["category_prefix"] == prefix
        assert record["gl_code"] == code
        assert record["gl_account_name"] == name
        assert record["gl_account_type"] == typ
        assert record["code"] == item
        assert record["legacy_code"] == key
        assert views.gl_display_label(record) == f"{code} - {name}"
    assert len(expected) == 23
    assert len(repo.list("materials")) == 23


def test_every_shipped_row_reconciles_with_gl_lookup():
    # All 23 records carry populated GL state; each row must agree
    # with the authoritative account lookup and the code derivation
    # rule code == "[PREFIX]-[GL_CODE]-[ITEM_ID]".
    from qs_engine.master_data.repository import MasterDataRepository
    repo = MasterDataRepository()
    records = repo.list("materials")
    assert len(records) == 23
    for record in records:
        key = record["key"]
        resolved = views.resolve_gl_account(record["gl_account_name"])
        assert resolved is not None, key
        prefix, gl_code, account_type = resolved
        assert record["category_prefix"] == prefix, key
        assert record["gl_code"] == gl_code, key
        assert record["gl_account_type"] == account_type, key
        item_id = str(record["code"]).rsplit("-", 1)[-1]
        assert record["code"] == views.derive_material_code(
            record["gl_account_name"], item_id), key
        assert views.gl_display_label(record) == (
            f"{gl_code} - {record['gl_account_name']}"), key
        assert views.gl_account_type_display(record) == account_type, key
        assert views.resolve_material_record(key, repo) is not None


def test_shipped_prefix_and_gl_search():
    from qs_engine.master_data.repository import MasterDataRepository
    records = MasterDataRepository().list("materials")
    # prefix search resolves the whole account family
    assert {r["key"] for r in views.filter_catalogue(records, "CEM")} == {
        "portland_cement_42_5", "hydrated_lime"}
    assert {r["key"] for r in views.filter_catalogue(records, "QRY")} == {
        "quarry_dust", "hardcore", "murram", "building_stone"}
    assert {r["key"] for r in views.filter_catalogue(records, "WSU")} == {
        "water"}
    # GL-code search resolves every row booked to that account
    assert sorted(r["key"] for r in views.filter_catalogue(
        records, "10175")) == ["hydrated_lime", "portland_cement_42_5"]
    assert sorted(r["key"] for r in views.filter_catalogue(
        records, "10176")) == ["ballast_20mm", "river_sand"]
    assert [r["key"] for r in views.filter_catalogue(
        records, "50066")] == ["water"]
    assert views.filter_catalogue(records, "STL") == []
    rows = views.picker_records("materials", MasterDataRepository())
    cem_row = next(r for r in rows if r["code"] == "portland_cement_42_5")
    assert "GL: 10175 - Cement & Binders" in cem_row["detail"]
    water_row = next(r for r in rows if r["code"] == "water")
    assert "GL: 50066 - Site Utilities - Water" in water_row["detail"]
    # every shipped picker row now carries its GL segment
    assert all("GL: " in row["detail"] for row in rows)


def test_shipped_details_pane_shows_account_type():
    from qs_engine.master_data.repository import MasterDataRepository
    repo = MasterDataRepository()
    cement = views.material_details_text(
        repo.get("materials", "portland_cement_42_5"))
    assert "GL Account: 10175 - Cement & Binders" in cement
    assert "Account Type: Inventory (Asset)" in cement
    water = views.material_details_text(repo.get("materials", "water"))
    assert "GL Account: 50066 - Site Utilities - Water" in water
    assert "Account Type: Direct Cost / Expense" in water


# --- dual lookup ---------------------------------------------------------------

def test_resolve_by_code_and_legacy_code():
    repo = _StubRepo([_gl_record(), _plain_record()])
    assert views.resolve_material_record(
        "CEM-10175-PC425", repo)["name"] == "Portland Cement 42.5"
    assert views.resolve_material_record(
        "portland_cement_42_5", repo)["name"] == "Portland Cement 42.5"
    assert views.resolve_material_record("river_sand", repo)["name"] == (
        "River Sand")
    assert views.resolve_material_record("no-such-key", repo) is None
    assert views.resolve_material_record("", repo) is None
    assert views.resolve_material_record(None, repo) is None


def test_display_name_prefers_code_falls_back_to_legacy():
    repo = _StubRepo([_gl_record()])
    name, _unit = views.resource_display_name(
        "materials", "CEM-10175-PC425", repo)
    assert name == "Portland Cement 42.5"
    name, _unit = views.resource_display_name(
        "materials", "portland_cement_42_5", repo)
    assert name == "Portland Cement 42.5"
    assert views.resource_display_name(
        "materials", "missing", repo)[0] == "⚠ unknown key"


# --- GL-aware search -----------------------------------------------------------

def test_all_scope_matches_gl_fields_when_present():
    records = [_gl_record(), _plain_record()]
    assert [r["key"] for r in views.filter_catalogue(records, "10175")] == [
        "CEM-10175-PC425"]
    assert [r["key"] for r in views.filter_catalogue(records, "cem")] == [
        "CEM-10175-PC425"]
    assert [r["key"] for r in views.filter_catalogue(records, "STL")] == []
    # Scoped search stays strict (GL names are All-scope only).
    assert views.filter_catalogue(
        records, "binders", scope="Code") == []
    assert [r["key"] for r in views.filter_catalogue(
        records, "binders")] == ["CEM-10175-PC425"]


def test_absent_gl_fields_change_nothing():
    records = [_plain_record()]
    assert views.filter_catalogue(records, "sand") == records
    assert views.filter_catalogue(records, "") == records
    rows = views.picker_records("materials", _StubRepo(records))
    assert len(rows) == 1
    assert "GL:" not in rows[0]["detail"]


def test_picker_detail_carries_gl_when_present():
    rows = views.picker_records("materials", _StubRepo([_gl_record()]))
    assert len(rows) == 1
    assert "GL: 10175 - Cement & Binders" in rows[0]["detail"]
    assert rows[0]["code"] == "CEM-10175-PC425"


# --- contract guards -----------------------------------------------------------

def test_materials_columns_unchanged_no_price_column():
    assert set(views.MATERIALS_COLUMNS) == {
        "code", "name", "category", "subcategory", "unit", "density",
        "wastage", "status"}
    assert "price" not in views.MATERIALS_COLUMNS
    assert "gl_code" not in views.MATERIALS_COLUMNS


def test_shipped_catalogue_rows_byte_identical_shape():
    from qs_engine.master_data.repository import MasterDataRepository
    rows = views.material_catalogue_rows(MasterDataRepository())
    assert len(rows) == 23
    assert rows[0][0] == "portland_cement_42_5"
    assert all(len(row) == 8 for row in rows)


def test_shipped_records_carry_legacy_code():
    from qs_engine.master_data.repository import MasterDataRepository
    records = MasterDataRepository().list("materials")
    assert len(records) == 23
    assert all(record.get("legacy_code") == record.get("key")
               for record in records)


def test_legacy_resolution_on_shipped_data():
    from qs_engine.master_data.repository import MasterDataRepository
    repo = MasterDataRepository()
    record = views.resolve_material_record("river_sand", repo)
    assert record["name"] == "River Sand"
    # legacy_code mirrors key until an enterprise renumbering lands.
    assert views.resolve_material_record(
        "river_sand", repo)["legacy_code"] == "river_sand"
    name, _unit = views.resource_display_name(
        "materials", "ballast_20mm", repo)
    assert name == "Coarse Aggregate / Ballast 20mm"


# --- dynamic GL resolution & UI wiring -----------------------------------------

def test_gl_account_lookup_matches_authoritative_table():
    expected = {
        "Cement & Binders": ("CEM", "10175", "Inventory (Asset)"),
        "Aggregates": ("AGG", "10176", "Inventory (Asset)"),
        "Quarry Products": ("QRY", "10138", "Inventory (Asset)"),
        "Precast & Concrete Products": ("PRC", "10183",
                                        "Inventory (Asset)"),
        "General Hardware & Fixing": ("HRD", "10131",
                                      "Inventory (Asset)"),
        "Scaffolding & Formwork": ("SCF", "10130", "Inventory (Asset)"),
        "Painting & Coating": ("PNT", "10186", "Inventory (Asset)"),
        "Adhesives & Construction Chemicals": ("CHM", "10188",
                                               "Inventory (Asset)"),
        "Wall & Ceiling Systems": ("WCS", "10185", "Inventory (Asset)"),
        "Waterproofing & Sealants": ("WPF", "10187",
                                     "Inventory (Asset)"),
        "Site Utilities - Water": ("WSU", "50066",
                                   "Direct Cost / Expense"),
    }
    assert dict(views.GL_ACCOUNTS) == expected
    assert views.GL_ACCOUNT_CHOICES == tuple(views.GL_ACCOUNTS)
    for name, binding in expected.items():
        assert views.resolve_gl_account(name) == binding
        # surrounding whitespace never breaks the lookup
        assert views.resolve_gl_account(f"  {name} ") == binding
    # unknown / blank selections never invent GL state
    assert views.resolve_gl_account("No Such Account") is None
    assert views.resolve_gl_account("") is None
    assert views.resolve_gl_account(None) is None


def test_derive_material_code_formula():
    assert views.derive_material_code(
        "Cement & Binders", "PC425") == "CEM-10175-PC425"
    assert views.derive_material_code(
        "Site Utilities - Water", "WTR01") == "WSU-50066-WTR01"
    assert views.derive_material_code(
        "Adhesives & Construction Chemicals", "RLA01") == (
        "CHM-10188-RLA01")
    # surrounding whitespace is tolerated on both inputs
    assert views.derive_material_code(
        " Painting & Coating ", " GLS01 ") == "PNT-10186-GLS01"
    # nothing derived without a known account AND a non-empty item id
    assert views.derive_material_code("Painting & Coating", "") == ""
    assert views.derive_material_code("Painting & Coating", None) == ""
    assert views.derive_material_code("Unknown Account", "GLS01") == ""
    assert views.derive_material_code(None, None) == ""


def test_gl_fields_for_selection_pure_state():
    assert views.gl_fields_for_selection(
        "Quarry Products", "HCR01") == {
        "category_prefix": "QRY", "gl_code": "10138",
        "gl_account_type": "Inventory (Asset)",
        "code": "QRY-10138-HCR01"}
    # known account + blank item id: GL resolves, code withheld
    assert views.gl_fields_for_selection("Aggregates") == {
        "category_prefix": "AGG", "gl_code": "10176",
        "gl_account_type": "Inventory (Asset)", "code": "—"}
    # unknown account: everything em-dash, nothing invented
    assert views.gl_fields_for_selection("Nope", "XXX") == {
        "category_prefix": "—", "gl_code": "—",
        "gl_account_type": "—", "code": "—"}


class _StubWidget:
    """Minimal headless stand-in for a ttk Entry/Combobox."""

    def __init__(self, value=""):
        self._value = str(value)
        self.state = "normal"

    def get(self):
        return self._value

    def config(self, **kwargs):
        if "state" in kwargs:
            self.state = kwargs["state"]

    def delete(self, *_args):
        self._value = ""

    def insert(self, _index, text):
        self._value = str(text)


def _gl_editor_widgets(account="", item_id=""):
    return {
        "gl_account_name": _StubWidget(account),
        "item_id": _StubWidget(item_id),
        "category_prefix": _StubWidget(),
        "gl_code": _StubWidget(),
        "gl_account_type": _StubWidget(),
        "code": _StubWidget(),
    }


def test_account_selection_resolves_readouts_and_code():
    widgets = _gl_editor_widgets("Cement & Binders", "PC425")
    fields = views.apply_gl_account_selection(widgets)
    assert fields == {"category_prefix": "CEM", "gl_code": "10175",
                      "gl_account_type": "Inventory (Asset)",
                      "code": "CEM-10175-PC425"}
    assert widgets["category_prefix"].get() == "CEM"
    assert widgets["gl_code"].get() == "10175"
    assert widgets["gl_account_type"].get() == "Inventory (Asset)"
    assert widgets["code"].get() == "CEM-10175-PC425"
    # readouts are left disabled (write-through contract)
    assert widgets["code"].state == "disabled"
    assert widgets["gl_account_type"].state == "disabled"


def test_account_change_re_resolves_dynamically():
    widgets = _gl_editor_widgets("Cement & Binders", "LIM01")
    views.apply_gl_account_selection(widgets)
    assert widgets["code"].get() == "CEM-10175-LIM01"
    # changing the account rebinds prefix/code/type, regenerates code
    widgets["gl_account_name"] = _StubWidget("Site Utilities - Water")
    fields = views.apply_gl_account_selection(widgets)
    assert fields == {"category_prefix": "WSU", "gl_code": "50066",
                      "gl_account_type": "Direct Cost / Expense",
                      "code": "WSU-50066-LIM01"}
    assert widgets["gl_account_type"].get() == "Direct Cost / Expense"
    # editing the item id alone also regenerates the code
    widgets["item_id"] = _StubWidget("WTR01")
    views.apply_gl_account_selection(widgets)
    assert widgets["code"].get() == "WSU-50066-WTR01"


def test_unknown_or_incomplete_selection_invents_nothing():
    widgets = _gl_editor_widgets("Not An Account", "XXX01")
    fields = views.apply_gl_account_selection(widgets)
    assert fields == {"category_prefix": "—", "gl_code": "—",
                      "gl_account_type": "—", "code": "—"}
    assert widgets["category_prefix"].get() == "—"
    assert widgets["code"].get() == "—"
    # blank selection behaves identically
    widgets = _gl_editor_widgets("", "")
    fields = views.apply_gl_account_selection(widgets)
    assert fields["code"] == "—"
    assert widgets["gl_code"].get() == "—"
