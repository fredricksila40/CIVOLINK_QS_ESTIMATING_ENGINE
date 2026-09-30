"""Phase 20 persistence tests: headless, no widgets.

Covers the `.clk` round-trip (schema guard, session fidelity,
hydration with recompilation), the SQLite rate library (CRUD,
validation, all-or-nothing CSV sync), and the File menu / page file
controls wiring. Engine, controller, and adapter contracts elsewhere
are untouched.
"""

import json
import sqlite3
import zlib

import pytest

from qs_engine.core.errors import ValidationError
from qs_engine.persistence.project_file import (
    SCHEMA_VERSION,
    ProjectFileAdapter,
    SessionState,
    load_session,
    save_session,
    state_from_dict,
)
from qs_engine.persistence.rate_library import (
    CATEGORIES,
    CSV_COLUMNS,
    RateLibrary,
)
from qs_engine.ui import views
from qs_engine.ui.session import TakeoffLine, TakeoffSession


def _rich_session():
    from qs_engine.boq.compiler import compile_boq
    from qs_engine.ui.controllers import project_setup_controller
    from qs_engine.valuation.ipc_engine import compute_ipc
    session = TakeoffSession()
    session.save_project(name="Demo", reference="D-1", client="ACME")
    session.standard = project_setup_controller(
        standard="CESMM", edition="CESMM4")
    session.add_line(TakeoffLine(
        trade="concrete", description="Slab", unit="m\u00b3",
        quantity="3.00", rate="242.00", rate_ref="R-C1",
        takeoff_ref="S1"))
    session.add_line(TakeoffLine(
        trade="masonry", description="Wall", unit="piece",
        quantity="8", takeoff_ref="W1"))
    session.last_compiled = compile_boq(
        session.to_boq("P", "B"))
    session.last_rate = {"gross": "242.00", "ref": "rate-builder"}
    session.last_ipc = compute_ipc(
        "1000000", "10", "50000", previous_valuation="100000",
        items=[{"item_no": "1", "description": "Slab",
                "unit": "m\u00b3", "rate": "100",
                "completed_qty": "500"}],
        onsite_materials="10000", advance_repaid="20000",
        advance_balance="50000", previous_payments="90000",
        valuation_no="IPC-01")
    return session


# --- project file round-trip ---------------------------------------------------------

def test_save_load_round_trip_preserves_session(tmp_path):
    session = _rich_session()
    path = ProjectFileAdapter.save_project(
        tmp_path / "demo.clk", session)
    assert path.endswith(".clk")
    raw = (tmp_path / "demo.clk").read_bytes()
    assert raw[:2] == b"x\x9c" or raw.startswith(b"{")
    state = ProjectFileAdapter.load_project(path)
    assert state.version == SCHEMA_VERSION
    assert state.project == {"name": "Demo", "reference": "D-1",
                             "client": "ACME"}
    assert state.project_saved is True
    assert state.standard == {"standard": "CESMM", "edition": "CESMM4"}
    assert len(state.lines) == 2
    assert state.lines[0]["rate"] == "242.00"
    assert state.lines[1]["rate"] is None
    assert state.last_rate == {"gross": "242.00", "ref": "rate-builder"}
    assert state.last_ipc["net_payable"] == "35000"
    assert state.boq == {"project_ref": "P", "boq_ref": "B"}


def test_state_json_serializable_and_compressed():
    session = _rich_session()
    from qs_engine.persistence.project_file import state_from_session
    encoded = ProjectFileAdapter.encode(state_from_session(session))
    assert isinstance(encoded, bytes)
    decoded = json.loads(zlib.decompress(encoded).decode("utf-8"))
    assert decoded["version"] == "1.0.0"
    assert isinstance(SessionState().to_dict(), dict)


def test_version_guard_rejects_foreign_schema(tmp_path):
    from qs_engine.persistence.project_file import state_from_session
    data = state_from_session(_rich_session()).to_dict()
    data["version"] = "2.0.0"
    foreign = tmp_path / "foreign.clk"
    foreign.write_bytes(zlib.compress(json.dumps(data).encode()))
    with pytest.raises(ValidationError) as exc_info:
        ProjectFileAdapter.load_project(foreign)
    assert "2.0.0" in str(exc_info.value)


def test_corrupt_and_missing_files_fail_closed(tmp_path):
    garbage = tmp_path / "garbage.clk"
    garbage.write_bytes(b"definitely not a project file \x00\x01")
    with pytest.raises(ValidationError):
        ProjectFileAdapter.load_project(garbage)
    with pytest.raises(ValidationError):
        ProjectFileAdapter.load_project(tmp_path / "absent.clk")
    with pytest.raises(ValidationError):
        ProjectFileAdapter.decode("not-bytes")
    with pytest.raises(ValidationError):
        ProjectFileAdapter.encode({"not": "a-state"})
    with pytest.raises(ValidationError):
        state_from_dict({"version": "1.0.0", "lines": "not-a-list"})


def test_hydration_restores_live_session(tmp_path):
    session = _rich_session()
    path = ProjectFileAdapter.save_project(
        tmp_path / "demo.clk", session)
    fresh = TakeoffSession()
    summary = load_session(fresh, path)
    assert "2 take-off lines" in summary
    assert fresh.project_saved is True
    assert fresh.project["name"] == "Demo"
    assert fresh.standard.standard == "CESMM"
    assert fresh.standard.edition == "CESMM4"
    assert [line.description for line in fresh.lines()] == [
        "Slab", "Wall"]
    assert fresh.last_rate == {"gross": "242.00", "ref": "rate-builder"}
    assert fresh.last_ipc.net_payable == "35000"
    assert fresh.last_compiled is not None
    assert str(fresh.last_compiled.resolved_subtotal) == "726.0000"
    assert fresh.last_compiled.unresolved_items == ("2.1.1",)


def test_hydration_without_boq_skips_recompile(tmp_path):
    session = TakeoffSession()
    session.save_project(name="Bare")
    session.add_line(TakeoffLine(
        trade="concrete", description="Slab", unit="m\u00b3",
        quantity="1", takeoff_ref="S1"))
    path = ProjectFileAdapter.save_project(
        tmp_path / "bare.clk", session)
    fresh = TakeoffSession()
    load_session(fresh, path)
    assert fresh.last_compiled is None
    assert len(fresh.lines()) == 1


def test_save_session_helper_and_plain_json_fallback(tmp_path):
    session = _rich_session()
    path = save_session(session, tmp_path / "deep" / "demo.clk")
    assert path.endswith(".clk")
    # Debug/hand-edited plain JSON loads through the same guard.
    from qs_engine.persistence.project_file import state_from_session
    plain = tmp_path / "plain.clk"
    plain.write_text(json.dumps(
        state_from_session(session).to_dict()), encoding="utf-8")
    assert ProjectFileAdapter.load_project(plain).version == "1.0.0"


# --- rate library ----------------------------------------------------------------------

def test_library_crud_round_trip(tmp_path):
    library = RateLibrary(str(tmp_path / "rates.db"))
    try:
        assert library.count() == 0
        row = library.upsert_rate(
            "materials", "cement_50kg", "Cement 50kg bag", "bag",
            "850", source="supplier-A")
        assert row["rate"] == "850"
        assert library.get_rate("materials", "cement_50kg") == row
        updated = library.upsert_rate(
            "materials", "cement_50kg", "Cement 50kg bag", "bag",
            "875", source="supplier-B")
        assert updated["rate"] == "875"
        assert updated["updated_on"] == row["updated_on"]
        assert library.count() == 1
        library.delete_rate("materials", "cement_50kg")
        assert library.count() == 0
        with pytest.raises(ValidationError):
            library.get_rate("materials", "cement_50kg")
    finally:
        library.close()


def test_library_validates_category_and_rate():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        library = RateLibrary(str(Path(tmp) / "r.db"))
        try:
            with pytest.raises(ValidationError):
                library.upsert_rate("unobtainium", "x", rate="1")
            with pytest.raises(ValidationError):
                library.upsert_rate("labour", "mason", rate="-5")
            with pytest.raises(ValidationError):
                library.upsert_rate("labour", "mason", rate="1.5x")
            with pytest.raises(ValidationError):
                library.upsert_rate("labour", "mason", rate=1.5)
            with pytest.raises(ValidationError):
                library.upsert_rate("plant", "", rate="1")
            assert set(CATEGORIES) == {
                "materials", "labour", "plant", "haulage"}
        finally:
            library.close()


def test_library_search_and_filter(tmp_path):
    library = RateLibrary(str(tmp_path / "rates.db"))
    try:
        library.upsert_rate("labour", "mason", "Mason", "day", "1500")
        library.upsert_rate("labour", "labourer", "Labourer", "day",
                            "800")
        library.upsert_rate("plant", "excavator", "Excavator", "hr",
                            "5000")
        assert len(library.list_rates()) == 3
        assert [r["code"] for r in
                library.list_rates(category="labour")] == [
            "labourer", "mason"]
        assert [r["code"] for r in library.list_rates(search="MAS")] == [
            "mason"]
        with pytest.raises(ValidationError):
            library.list_rates(category="nope")
    finally:
        library.close()


def test_library_csv_round_trip_and_template(tmp_path):
    library = RateLibrary(str(tmp_path / "rates.db"))
    try:
        library.upsert_rate("haulage", "tipper_10t", "10t tipper",
                            "trip", "7500", source="fleet")
        template = RateLibrary.export_template_csv(
            tmp_path / "template.csv")
        header = (tmp_path / "template.csv").read_text(
            encoding="utf-8").strip()
        assert header == ",".join(CSV_COLUMNS)
        assert template.endswith(".csv")
        exported = library.export_to_csv(tmp_path / "rates.csv")
        assert exported.endswith(".csv")
        clone = RateLibrary(str(tmp_path / "clone.db"))
        try:
            result = clone.import_from_csv(exported)
            assert result == {"inserted": 1, "updated": 0}
            assert clone.get_rate("haulage", "tipper_10t")["rate"] == (
                "7500")
            again = clone.import_from_csv(exported)
            assert again == {"inserted": 0, "updated": 1}
        finally:
            clone.close()
    finally:
        library.close()


def test_library_import_all_or_nothing(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "category,code,description,unit,rate,source\n"
        "materials,cement,Cement,bag,850,s1\n"
        "labour,mason,Mason,day,not-a-rate,s1\n",
        encoding="utf-8")
    library = RateLibrary(str(tmp_path / "rates.db"))
    try:
        with pytest.raises(ValidationError) as exc_info:
            library.import_from_csv(bad)
        assert "row 3" in str(exc_info.value)
        assert library.count() == 0  # rolled back, nothing staged
        with pytest.raises(ValidationError):
            library.import_from_csv(tmp_path / "absent.csv")
        empty = tmp_path / "empty.csv"
        empty.write_text("category,code,description,unit,rate,source\n",
                         encoding="utf-8")
        with pytest.raises(ValidationError):
            library.import_from_csv(empty)
    finally:
        library.close()
    assert sqlite3.connect(":memory:") is not None  # stdlib backend


# --- UI wiring ------------------------------------------------------------------------------

def test_file_menu_and_state_actions_wired():
    import inspect as _inspect
    assert views.PAGES["valuations"] is not None  # unrelated page intact
    app_source = _inspect.getsource(views.QSApp.__init__)
    assert "_build_menu" in app_source
    menu_source = _inspect.getsource(views.QSApp._build_menu)
    assert "New Project" in menu_source
    assert "Open Project (.clk)" in menu_source
    assert "Save As (.clk)" in menu_source
    assert "Open Project (.civolink)" not in menu_source
    for method in ("new_project", "open_project_file",
                   "save_project_file", "save_project_file_as"):
        assert callable(getattr(views.QSApp, method, None)), method
    overview_source = _inspect.getsource(views.build_overview_page)
    assert "Save Project State" in overview_source
    assert "Load Project State" in overview_source
    setup_source = _inspect.getsource(views.build_project_page)
    assert "Save Project File" in setup_source
    assert "Load Project File" in setup_source
    assert "persist_session_to_file" in setup_source
    assert "restore_session_from_file" in setup_source


def test_legacy_civolink_files_remain_readable(tmp_path):
    from qs_engine.persistence.project_file import (
        LEGACY_PROJECT_FILE_EXTENSION,
        PROJECT_FILE_EXTENSION,
        READABLE_EXTENSIONS,
    )
    assert PROJECT_FILE_EXTENSION == ".clk"
    assert LEGACY_PROJECT_FILE_EXTENSION == ".civolink"
    assert READABLE_EXTENSIONS == (".clk", ".civolink")
    session = _rich_session()
    legacy = tmp_path / "legacy.civolink"
    ProjectFileAdapter.save_project(legacy, session)
    state = ProjectFileAdapter.load_project(legacy)
    assert state.project["name"] == "Demo"
    assert len(state.lines) == 2
    fresh = TakeoffSession()
    load_session(fresh, legacy)
    assert fresh.last_compiled is not None
