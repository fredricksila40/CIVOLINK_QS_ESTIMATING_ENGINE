"""Phase 18 FastAPI integration tests (HTTP-level, no mocks).

Exercises every endpoint through TestClient: 200 payloads with exact
engine values, 422 paths for engine/validation failures and malformed
requests, the reconcile file-upload flow, and OpenAPI availability.
Controller, adapter, and UI code paths remain untouched.
"""

import io
import json

import pytest
from fastapi.testclient import TestClient

from qs_engine import __version__ as QS_ENGINE_VERSION
from qs_engine.web.api import api_token, app, get_rate_library
from qs_engine.web.server import HOST, PORT

# Every endpoint requires the local bearer token (sidecar hardening):
# the shared client presents it on every request.
client = TestClient(app, headers={"Authorization": f"Bearer {api_token}"})

FULL_OVERRIDES = {
    "dry_factor": "2", "cement_ratio": "1", "sand_ratio": "1",
    "aggregate_ratio": "2", "wc_ratio": "0.5",
    "cement_density_kg_per_m3": "1000",
    "sand_density_kg_per_m3": "1000",
    "aggregate_density_kg_per_m3": "1000",
    "water_density_kg_per_L": "1", "bag_mass_kg": "50",
}

BOQ_LINES = [
    {"trade": "concrete", "description": "Slab", "unit": "m\u00b3",
     "quantity": "3.00", "takeoff_ref": "S1", "rate": "242.00",
     "rate_ref": "R-C1"},
    {"trade": "masonry", "description": "Wall", "unit": "piece",
     "quantity": "8", "takeoff_ref": "W1"},
]


def _boq_payload(**extra):
    payload = {"project_ref": "P", "boq_ref": "B", "lines": BOQ_LINES}
    payload.update(extra)
    return payload


# --- health / docs ------------------------------------------------------------------

def test_health_reports_status_version_and_tests():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == QS_ENGINE_VERSION
    assert isinstance(body["test_count"], int)
    assert body["test_count"] >= 500


def test_openapi_lists_all_endpoints():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert set(paths) == {
        "/health", "/api/v1/takeoff/concrete", "/api/v1/takeoff/rebar",
        "/api/v1/rate/build", "/api/v1/boq/compile", "/api/v1/reconcile",
        "/api/v1/valuation/ipc", "/api/v1/export/pdf/boq",
        "/api/v1/export/pdf/ipc", "/api/v1/project/save",
        "/api/v1/project/load", "/api/v1/library/rates",
    }
    assert response.json()["info"]["title"] == (
        "CIVOLINK QS Estimating Engine API")


def test_server_launcher_binding():
    assert (HOST, PORT) == ("127.0.0.1", 8000)


# --- concrete take-off -----------------------------------------------------------------

def test_concrete_takeoff_exact_values():
    response = client.post("/api/v1/takeoff/concrete", json={
        "element": "slab", "length": "1", "width": "1",
        "thickness": "1", "class_key": "class_c20",
        "overrides": FULL_OVERRIDES})
    assert response.status_code == 200
    body = response.json()
    assert body["wet_m3"] == "1"
    assert body["bags_exact"] == "10.0"
    assert body["water_litres"] == "250.00"
    assert body["overrides_used"] is True


def test_concrete_takeoff_engine_failure_is_422():
    # Skeleton master record without overrides fails closed honestly.
    response = client.post("/api/v1/takeoff/concrete", json={
        "length": "1", "width": "1", "thickness": "1",
        "class_key": "class_c20"})
    assert response.status_code == 422
    assert "detail" in response.json()


def test_concrete_takeoff_malformed_is_422():
    response = client.post("/api/v1/takeoff/concrete", json={
        "length": "1", "width": "1"})  # missing thickness/class_key
    assert response.status_code == 422


# --- rebar take-off -----------------------------------------------------------------------

def test_rebar_takeoff_totals():
    response = client.post("/api/v1/takeoff/rebar", json={
        "lines": [{"bar_key": "Y12", "count": "10",
                   "length_per_bar_m": "6", "laps_per_bar": "2",
                   "lap_length_m": "1.0",
                   "hook_extra_per_bar_m": "0.3",
                   "mass_kg_per_m": "2"}],
        "wastage_pct": "0"})
    assert response.status_code == 200
    body = response.json()
    # per bar 6 + 2x1.0 + 0.3 = 8.3 m; x10 bars, x2 kg/m.
    assert body["total_length_m"] == "83.0"
    assert body["total_mass_kg"] == "166.0"
    assert len(body["lines"]) == 1


def test_rebar_takeoff_empty_schedule_is_422():
    response = client.post("/api/v1/takeoff/rebar", json={
        "lines": [], "wastage_pct": "0"})
    assert response.status_code == 422


# --- rate build ------------------------------------------------------------------------------

def test_rate_build_exact_values():
    response = client.post("/api/v1/rate/build", json={
        "lines": [{"kind": "material", "material_key": "river_sand",
                   "qty_per_unit": "1", "unit_price": "90",
                   # Blank wastage no longer coerces to 0 (E-24): an
                   # unspecified value fails closed, so this arithmetic
                   # test states its wastage explicitly.
                   "wastage_pct": "0"}],
        "markups": [{"label": "profit", "pct": "10"}],
        "markup_policy": "sequential", "element": "bedding",
        "work_unit": "m³"})
    assert response.status_code == 200
    body = response.json()
    assert body["direct_cost"] == "90"
    assert body["net_rate"] == "90"
    assert body["gross_rate"] == "99"
    assert len(body["components"]) == 1


def test_rate_build_unknown_kind_is_422():
    response = client.post("/api/v1/rate/build", json={
        "lines": [{"kind": "teleport", "amount_per_unit": "5"}],
        "markups": []})
    assert response.status_code == 422


# --- BOQ compile ---------------------------------------------------------------------------------

def test_boq_compile_summary_values():
    response = client.post("/api/v1/boq/compile",
                           json=_boq_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["project_ref"] == "P"
    assert body["resolved_subtotal"] == "726.0000"
    assert body["has_unresolved"] is True
    assert body["unresolved_items"] == ["2.1.1"]
    assert body["sections"][0]["items"][0]["amount"] == "726.0000"


def test_boq_compile_empty_lines_is_422():
    response = client.post("/api/v1/boq/compile",
                           json=_boq_payload(lines=[]))
    assert response.status_code == 422


# --- reconcile upload -------------------------------------------------------------------------------

def _tender_bytes(lines):
    from qs_engine.adapters.excel.tender_workbook import (
        export_tender_to_excel,
    )
    from qs_engine.boq.compiler import compile_boq
    from qs_engine.ui.session import TakeoffLine, TakeoffSession
    session = TakeoffSession()
    for line in lines:
        session.add_line(TakeoffLine(**line))
    compiled = compile_boq(session.to_boq("P", "B"))
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tender.xlsx"
        export_tender_to_excel(compiled, path)
        return path.read_bytes()


def test_reconcile_upload_variance_json(tmp_path):
    content = _tender_bytes(BOQ_LINES)
    response = client.post(
        "/api/v1/reconcile",
        files={"file": ("tender.xlsx", io.BytesIO(content),
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet")},
        data={"boq_json": json.dumps(_boq_payload())})
    assert response.status_code == 200
    body = response.json()
    assert body["base_estimate"] == "726.0000"
    # Tender legs pass through .xlsx doubles, so scale differs while
    # value stays exact — compare numerically, not textually.
    from decimal import Decimal as _Decimal
    assert _Decimal(body["tender_total"]) == _Decimal("726.0000")
    assert _Decimal(body["variance_amount"]) == 0
    assert body["tender_has_unpriced"] is True
    assert len(body["rows"]) == 2


def test_reconcile_rejects_non_xlsx_upload():
    response = client.post(
        "/api/v1/reconcile",
        files={"file": ("tender.txt", io.BytesIO(b"hello"),
                        "text/plain")},
        data={"boq_json": json.dumps(_boq_payload())})
    assert response.status_code == 422


def test_reconcile_rejects_malformed_boq_json():
    content = _tender_bytes(BOQ_LINES)
    response = client.post(
        "/api/v1/reconcile",
        files={"file": ("tender.xlsx", io.BytesIO(content),
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet")},
        data={"boq_json": "{not-json"})
    assert response.status_code == 422
    response = client.post(
        "/api/v1/reconcile",
        files={"file": ("tender.xlsx", io.BytesIO(content),
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet")},
        data={"boq_json": json.dumps({"project_ref": "P"})})
    assert response.status_code == 422


# --- valuation + PDF streams ---------------------------------------------------------------------

IPC_BODY = {
    "contract_sum": "1000000",
    "retention_rate_pct": "10",
    "retention_limit": "50000",
    "advance_balance": "50000",
    "previous_payments": "90000",
    "previous_valuation": "100000",
    "items": [{"item_no": "1", "description": "Slab",
               "unit": "m\u00b3", "rate": "100",
               "completed_qty": "500"}],
    "onsite_materials": "10000",
    "advance_repaid": "20000",
    "valuation_no": "IPC-01",
}

PDF_INFO = {"company_name": "Test Corp Ltd", "project_title": "Demo",
            "client": "ACME", "reference": "CTR-1",
            "measurement_standard": "CESMM4", "date": "2026-01-01"}


def test_valuation_ipc_exact_values():
    response = client.post("/api/v1/valuation/ipc", json=IPC_BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["work_to_date"] == "150000"
    assert body["gross_certified"] == "160000"
    assert body["retention_withheld"] == "15000"
    assert body["total_deductions"] == "125000"
    assert body["net_payable"] == "35000"


def test_valuation_ipc_invalid_is_422():
    response = client.post("/api/v1/valuation/ipc",
                           json=dict(IPC_BODY, contract_sum="-1"))
    assert response.status_code == 422
    response = client.post("/api/v1/valuation/ipc",
                           json={"contract_sum": "1000"})
    assert response.status_code == 422  # missing retention terms


def test_export_pdf_boq_stream():
    response = client.post("/api/v1/export/pdf/boq", json={
        "project_ref": "P", "boq_ref": "B", "lines": BOQ_LINES,
        "info": PDF_INFO})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:5] == b"%PDF-"
    assert len(response.content) > 1000


def test_export_pdf_ipc_stream():
    response = client.post("/api/v1/export/pdf/ipc",
                           json={"ipc": IPC_BODY, "info": PDF_INFO})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:5] == b"%PDF-"
    assert len(response.content) > 1000


def test_export_pdf_boq_invalid_is_422():
    response = client.post("/api/v1/export/pdf/boq", json={
        "project_ref": "P", "boq_ref": "B", "lines": [],
        "info": PDF_INFO})
    assert response.status_code == 422


# --- project file persistence ---------------------------------------------------------------------

PROJECT_FILE_BODY = {
    "project": {"name": "Demo", "reference": "D-1"},
    "project_saved": True,
    "standard": {"standard": "CESMM", "edition": "CESMM4"},
    "lines": [
        {"trade": "concrete", "description": "Slab", "unit": "m\u00b3",
         "quantity": "3.00", "takeoff_ref": "S1", "rate": "242.00",
         "rate_ref": "R-C1"},
    ],
    "last_rate": {"gross": "242.00", "ref": "rate-builder"},
    "last_ipc": None,
    "boq": {"project_ref": "P", "boq_ref": "B"},
}


def test_project_save_returns_clk_stream():
    from qs_engine.persistence.project_file import ProjectFileAdapter
    response = client.post("/api/v1/project/save",
                           json=PROJECT_FILE_BODY)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"] == (
        'attachment; filename="project.clk"')
    state = ProjectFileAdapter.decode(response.content)
    assert state.version == "1.0.0"
    assert state.project["name"] == "Demo"
    assert len(state.lines) == 1


def test_project_load_hydrates_session_json():
    from qs_engine.persistence.project_file import ProjectFileAdapter
    from qs_engine.persistence.project_file import state_from_dict
    payload = ProjectFileAdapter.encode(
        state_from_dict(dict(PROJECT_FILE_BODY, version="1.0.0")))
    response = client.post(
        "/api/v1/project/load",
        files={"file": ("demo.clk", payload,
                        "application/octet-stream")})
    assert response.status_code == 200
    body = response.json()
    assert body["project"]["reference"] == "D-1"
    assert body["standard"] == {"standard": "CESMM",
                                "edition": "CESMM4"}
    assert body["boq"] == {"project_ref": "P", "boq_ref": "B"}


def test_project_load_accepts_legacy_civolink():
    from qs_engine.persistence.project_file import ProjectFileAdapter
    from qs_engine.persistence.project_file import state_from_dict
    payload = ProjectFileAdapter.encode(
        state_from_dict(dict(PROJECT_FILE_BODY, version="1.0.0")))
    response = client.post(
        "/api/v1/project/load",
        files={"file": ("demo.civolink", payload,
                        "application/octet-stream")})
    assert response.status_code == 200
    assert response.json()["project"]["name"] == "Demo"


def test_project_load_rejects_non_project_files():
    response = client.post(
        "/api/v1/project/load",
        files={"file": ("demo.txt", b"hello", "text/plain")})
    assert response.status_code == 422
    response = client.post(
        "/api/v1/project/load",
        files={"file": ("demo.clk", b"garbage-bytes",
                        "application/octet-stream")})
    assert response.status_code == 422


# --- master rate library -------------------------------------------------------------------------------

@pytest.fixture()
def isolated_library(tmp_path):
    from qs_engine.persistence.rate_library import RateLibrary
    app.dependency_overrides[get_rate_library] = (
        lambda: RateLibrary(str(tmp_path / "test_rates.db")))
    yield
    app.dependency_overrides.pop(get_rate_library, None)


def test_library_upsert_and_query(isolated_library):
    response = client.post("/api/v1/library/rates", json={
        "category": "materials", "code": "cement_50kg",
        "description": "Cement 50kg bag", "unit": "bag",
        "rate": "850", "source": "supplier-A"})
    assert response.status_code == 200
    assert response.json()["rate"] == "850"
    response = client.get("/api/v1/library/rates",
                          params={"category": "materials"})
    assert response.status_code == 200
    assert [row["code"] for row in response.json()] == ["cement_50kg"]
    response = client.get("/api/v1/library/rates",
                          params={"search": "CEMENT"})
    assert [row["code"] for row in response.json()] == ["cement_50kg"]


def test_library_upsert_invalid_is_422(isolated_library):
    response = client.post("/api/v1/library/rates", json={
        "category": "unobtainium", "code": "x", "rate": "1"})
    assert response.status_code == 422
    response = client.post("/api/v1/library/rates", json={
        "category": "labour", "code": "mason", "rate": "-5"})
    assert response.status_code == 422
