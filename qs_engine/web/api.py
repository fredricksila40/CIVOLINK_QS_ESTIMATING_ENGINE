"""FastAPI REST layer (Phase 18): HTTP facade over existing controllers.

No calculation lives here: each endpoint shapes Pydantic-validated
input into the existing controller contract and returns the
controller's view-model as JSON. Any engine/validation failure
surfaces as the controller's ErrorView, mapped to HTTP 422 — the
Tkinter UI, controllers, adapters, and parsers are untouched.

Security (local sidecar hardening, S-1..S-5):
  * every endpoint requires `Authorization: Bearer <api_token>`;
  * cross-origin browser requests are rejected (CSRF/drive-by);
  * Content-Length is capped at MAX_REQUEST_BYTES (413 otherwise).
"""

import ast
import hmac
import json
import os
import secrets
import tempfile
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from qs_engine import __version__ as QS_ENGINE_VERSION
from qs_engine.core.errors import QSEngineError

#: Largest accepted request body (16 MB): bounds JSON payloads and
#: .xlsx/.clk uploads without constraining legitimate project files.
MAX_REQUEST_BYTES = 16 * 1024 * 1024

#: Bearer token guarding every endpoint. CIVOLINK_API_TOKEN pins a
#: stable value for scripts/CI; otherwise a random per-process token
#: is generated (never empty, never disabled — fail closed by default).
#: The uvicorn launcher prints the active token for local operators.
api_token = (os.environ.get("CIVOLINK_API_TOKEN", "").strip()
             or secrets.token_urlsafe(32))

_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

app = FastAPI(
    title="CIVOLINK QS Estimating Engine API",
    version=QS_ENGINE_VERSION,
    description=("REST facade over the CIVOLINK QS controllers: "
                 "take-offs, rate build-ups, BOQ compilation, and "
                 "tender reconciliation. Interactive docs at /docs."),
)

# No cross-origin browser access: empty allow_origins means no CORS
# headers are ever emitted, so browsers cannot read responses from
# another origin (defence in depth alongside the Origin check below).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
)


def _origin_is_local(origin: str) -> bool:
    """True only for loopback origins (the app's own hostnames)."""
    try:
        host = (urlparse(origin).hostname or "").lower()
    except ValueError:
        return False
    return host in _LOCAL_HOSTS


@app.middleware("http")
async def _sidecar_guard(request, call_next):
    """Bearer auth + local-only origins + payload cap (S-1/S-3/S-4)."""
    origin = request.headers.get("origin", "")
    if origin and not _origin_is_local(origin):
        return JSONResponse(
            status_code=403,
            content={"detail": "Cross-origin requests are not allowed"})
    content_length = request.headers.get("content-length", "")
    if content_length:
        try:
            size = int(content_length)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid Content-Length header"})
        if size > MAX_REQUEST_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail":
                         f"Request body exceeds {MAX_REQUEST_BYTES} bytes"})
    presented = request.headers.get("authorization", "")
    if not hmac.compare_digest(presented, f"Bearer {api_token}"):
        return JSONResponse(
            status_code=401,
            content={"detail":
                     "Missing or invalid bearer token "
                     "(Authorization: Bearer <api_token>)"},
            headers={"WWW-Authenticate": "Bearer"})
    return await call_next(request)

_REPOSITORY = None


def _repository():
    """Material lookup boundary: MaterialResolver over read-only seed.

    Built through the shared resources factory — the same Phase 25
    primary interface the UI shell uses — so user material overrides
    resolve identically in the API and the desktop app. Unreadable
    user data fails closed to the seed-only catalogue (drop-in
    semantics; no endpoint can price a material the resolver rejects).
    """
    global _REPOSITORY
    if _REPOSITORY is None:
        from qs_engine.resources import default_repository
        _REPOSITORY, _stack, _error = default_repository()
    return _REPOSITORY


@lru_cache(maxsize=1)
def _test_count() -> Optional[int]:
    """Number of collected test functions (None when unavailable)."""
    tests_dir = Path(__file__).resolve().parent.parent.parent / "tests"
    if not tests_dir.is_dir():
        return None
    try:
        total = 0
        for path in sorted(tests_dir.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"),
                             filename=str(path))
            total += sum(isinstance(node, ast.FunctionDef)
                         and node.name.startswith("test_")
                         for node in ast.walk(tree))
        return total
    except Exception:
        return None


def _or_422(result):
    """Map a controller ErrorView to HTTP 422; pass views through."""
    from qs_engine.ui.viewmodels import ErrorView
    if isinstance(result, ErrorView):
        raise HTTPException(status_code=422, detail=result.message)
    return result


# --------------------------------------------------------------------------
# Schemas (request shapes mirror controller input contracts; response
# shapes mirror the view-model DTOs field for field).
# --------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    version: str
    test_count: Optional[int] = None


class KVEntry(BaseModel):
    label: str
    value: str


class ConcreteTakeoffRequest(BaseModel):
    element: str = ""
    length: str = Field(..., description="Length value as text")
    width: str = Field(...)
    thickness: str = Field(...)
    unit: str = "m"
    class_key: str = Field(...)
    overrides: dict = {}


class ConcreteResponse(BaseModel):
    element: str
    wet_m3: str
    dry_m3: str
    cement_m3: str
    sand_m3: str
    aggregate_m3: str
    cement_kg: str
    sand_kg: str
    aggregate_kg: str
    bags_exact: str
    bags_order: str
    water_litres: str
    class_key: str
    master_version: str
    overrides_used: bool


class RebarTakeoffRequest(BaseModel):
    lines: List[dict] = Field(
        ..., description="Bar line mappings (bar_key/count/length_per_bar_m/...)")
    wastage_pct: str = Field(...)
    tying_wire_kg_per_tonne: Optional[str] = None


class RebarResponse(BaseModel):
    lines: List[KVEntry]
    total_length_m: str
    total_mass_kg: str
    total_mass_tonnes: str
    wastage_pct: str
    after_wastage_kg: str
    tying_wire_kg: str


class MarkupEntry(BaseModel):
    label: str = ""
    pct: str = Field(...)


class RateBuildRequest(BaseModel):
    lines: List[dict] = Field(
        ..., description="Rate line mappings (kind + numeric strings)")
    markups: List[MarkupEntry] = []
    markup_policy: str = "sequential"
    element: str = ""
    work_unit: str = "m\u00b2"


class RateBuildResponse(BaseModel):
    element: str
    work_unit: str
    components: List[KVEntry]
    direct_cost: str
    markups: List[KVEntry]
    markup_policy: str
    net_rate: str
    gross_rate: str


class TakeoffLineEntry(BaseModel):
    trade: str
    description: str
    unit: str
    quantity: str
    rate: Optional[str] = None
    rate_ref: str = ""
    takeoff_ref: str = ""


class BoqCompileRequest(BaseModel):
    project_ref: str = Field(...)
    boq_ref: str = Field(...)
    lines: List[TakeoffLineEntry] = Field(...)


class BoqItemResponse(BaseModel):
    item_no: str
    description: str
    quantity: str
    unit: str
    rate: str
    amount: str
    status: str


class BoqSectionResponse(BaseModel):
    code: str
    title: str
    items: List[BoqItemResponse]
    total: str
    has_unresolved: bool


class BoqResponse(BaseModel):
    project_ref: str
    boq_ref: str
    sections: List[BoqSectionResponse]
    grand_total: str
    resolved_subtotal: str
    has_unresolved: bool
    unresolved_items: List[str]


class ReconcileRowResponse(BaseModel):
    item_no: str
    description: str
    unit: str
    q_boq: str
    r_boq: Optional[str] = None
    a_boq: Optional[str] = None
    q_tender: str
    r_tender: Optional[str] = None
    a_tender: Optional[str] = None
    dq: str
    dr: Optional[str] = None
    variance: Optional[str] = None
    modified: bool = False
    flags: List[str] = []


class ReconcileResponse(BaseModel):
    base_estimate: str
    tender_total: str
    tender_has_unpriced: bool = False
    variance_amount: str = "0"
    variance_pct: Optional[str] = None
    modified_count: int = 0
    quantity_changed_count: int = 0
    rate_changed_count: int = 0
    unpriced_count: int = 0
    unmatched_count: int = 0
    rows: List[ReconcileRowResponse] = []


class IPCLineEntry(BaseModel):
    item_no: str = Field(...)
    description: str = Field(...)
    unit: str = Field(...)
    rate: str = Field(...)
    completed_qty: str = Field(...)


class IPCRequest(BaseModel):
    contract_sum: str = Field(...)
    retention_rate_pct: str = Field(...)
    retention_limit: str = Field(...)
    advance_balance: str = "0"
    previous_payments: str = "0"
    previous_valuation: str = "0"
    items: List[IPCLineEntry] = []
    onsite_materials: str = "0"
    advance_repaid: str = "0"
    valuation_no: str = ""


class IPCLineResponse(BaseModel):
    item_no: str
    description: str
    unit: str
    rate: str
    completed_qty: str
    line_value: str


class IPCResponse(BaseModel):
    valuation_no: str
    contract_sum: str
    previous_valuation: str
    current_work: str
    work_to_date: str
    onsite_materials: str
    gross_certified: str
    retention_rate_pct: str
    retention_limit: str
    retention_withheld: str
    advance_repaid: str
    previous_payments: str
    total_deductions: str
    net_payable: str
    lines: List[IPCLineResponse] = []


class DocumentInfo(BaseModel):
    company_name: str = ""
    project_title: str = ""
    client: str = ""
    reference: str = ""
    measurement_standard: str = ""
    date: str = ""


class BoqPdfRequest(BaseModel):
    project_ref: str = Field(...)
    boq_ref: str = Field(...)
    lines: List[TakeoffLineEntry] = Field(...)
    info: DocumentInfo = DocumentInfo()


class IPCPdfRequest(BaseModel):
    ipc: IPCRequest = Field(...)
    info: DocumentInfo = DocumentInfo()


class ProjectStandardEntry(BaseModel):
    standard: str = Field(...)
    edition: str = ""


class ProjectFileRequest(BaseModel):
    project: dict = {}
    project_saved: bool = False
    standard: Optional[ProjectStandardEntry] = None
    lines: List[TakeoffLineEntry] = []
    last_rate: Optional[dict] = None
    last_ipc: Optional[dict] = None
    boq: Optional[dict] = None


class RateRowResponse(BaseModel):
    category: str
    code: str
    description: str = ""
    unit: str = ""
    rate: str
    source: str = ""
    updated_on: str = ""


class RateUpsertRequest(BaseModel):
    category: str = Field(...)
    code: str = Field(...)
    description: str = ""
    unit: str = ""
    rate: str = Field(...)
    source: str = ""


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _boq_from_entries(project_ref: str, boq_ref: str, lines: list):
    """Assemble a Boq from take-off line entries (422 on invalid)."""
    from qs_engine.ui.session import TakeoffLine, TakeoffSession
    try:
        session = TakeoffSession()
        for entry in lines:
            data = dict(entry) if isinstance(entry, dict) else (
                entry.model_dump())
            session.add_line(TakeoffLine(
                trade=data.get("trade", ""),
                description=data.get("description", ""),
                unit=data.get("unit", ""),
                quantity=data.get("quantity", ""),
                rate=data.get("rate"),
                rate_ref=data.get("rate_ref", ""),
                takeoff_ref=data.get("takeoff_ref", "")))
        return session.to_boq(project_ref, boq_ref)
    except QSEngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _compile_from_entries(project_ref: str, boq_ref: str,
                          lines: list):
    """Assemble and compile a BOQ from take-off line entries."""
    from qs_engine.boq.compiler import compile_boq
    try:
        return compile_boq(
            _boq_from_entries(project_ref, boq_ref, lines))
    except QSEngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
def health():
    """API status, active engine version, and collected test count."""
    return HealthResponse(status="ok", version=QS_ENGINE_VERSION,
                          test_count=_test_count())


@app.post("/api/v1/takeoff/concrete", response_model=ConcreteResponse)
def takeoff_concrete(body: ConcreteTakeoffRequest):
    """Execute a concrete take-off (strings in, rendered view out)."""
    from qs_engine.ui.controllers import concrete_controller
    result = _or_422(concrete_controller(
        {"element": body.element, "length": body.length,
         "width": body.width, "thickness": body.thickness,
         "unit": body.unit, "class_key": body.class_key},
        _repository(), dict(body.overrides or {})))
    return ConcreteResponse(**asdict(result))


@app.post("/api/v1/takeoff/rebar", response_model=RebarResponse)
def takeoff_rebar(body: RebarTakeoffRequest):
    """Execute a rebar schedule calculation."""
    from qs_engine.ui.controllers import rebar_controller
    result = _or_422(rebar_controller(
        [dict(line) for line in body.lines], body.wastage_pct,
        body.tying_wire_kg_per_tonne, _repository()))
    return RebarResponse(**asdict(result))


@app.post("/api/v1/rate/build", response_model=RateBuildResponse)
def rate_build(body: RateBuildRequest):
    """Parse composite rate lines with markups into a built rate."""
    from qs_engine.ui.controllers import rate_builder_controller
    result = _or_422(rate_builder_controller(
        [dict(line) for line in body.lines],
        [{"label": markup.label, "pct": markup.pct}
         for markup in body.markups],
        body.markup_policy, body.element, body.work_unit,
        _repository()))
    return RateBuildResponse(**asdict(result))


@app.post("/api/v1/boq/compile", response_model=BoqResponse)
def boq_compile(body: BoqCompileRequest):
    """Compile take-off lines into a priced BOQ cost summary."""
    from qs_engine.ui.controllers import boq_view_controller
    result = _or_422(boq_view_controller(
        _boq_from_entries(body.project_ref, body.boq_ref, body.lines)))
    return BoqResponse(**asdict(result))


@app.post("/api/v1/reconcile", response_model=ReconcileResponse)
def reconcile_tender(file: UploadFile = File(...),
                     boq_json: str = Form(...)):
    """Accept a tender .xlsx upload and return variance JSON.

    boq_json carries {"project_ref": ..., "boq_ref": ...,
    "lines": [...]} describing the canonical session BOQ the file is
    reconciled against (session truth itself is never written).
    """
    from qs_engine.adapters.excel.reconciliation import (
        reconcile_tender_file,
    )
    if not str(file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=422,
                            detail="Tender upload must be an .xlsx file")
    try:
        payload = json.loads(boq_json)
    except ValueError as exc:
        raise HTTPException(status_code=422,
                            detail=f"boq_json is not valid JSON: "
                                   f"{exc}") from exc
    try:
        request = BoqCompileRequest(**payload)
    except Exception as exc:
        raise HTTPException(status_code=422,
                            detail=f"boq_json failed validation: "
                                   f"{exc}") from exc
    compiled = _compile_from_entries(
        request.project_ref, request.boq_ref, request.lines)
    suffix = Path(str(file.filename or "tender.xlsx")).suffix or ".xlsx"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix,
                                         delete=False) as tmp:
            tmp.write(file.file.read())
            tmp_path = tmp.name
    except Exception as exc:
        raise HTTPException(status_code=422,
                            detail=f"Could not stage upload: "
                                   f"{exc}") from exc
    try:
        summary = reconcile_tender_file(compiled, tmp_path)
    except QSEngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
    return ReconcileResponse(**summary.to_dict())


@app.post("/api/v1/valuation/ipc", response_model=IPCResponse)
def valuation_ipc(body: IPCRequest):
    """Compute an interim payment certificate valuation."""
    from qs_engine.ui.controllers import ipc_valuation_controller
    result = ipc_valuation_controller(
        body.contract_sum, body.retention_rate_pct, body.retention_limit,
        previous_valuation=body.previous_valuation,
        items=[entry.model_dump() for entry in body.items],
        onsite_materials=body.onsite_materials,
        advance_repaid=body.advance_repaid,
        advance_balance=body.advance_balance,
        previous_payments=body.previous_payments,
        valuation_no=body.valuation_no)
    return IPCResponse(**_or_422(result).to_dict())


def _pdf_stream(payload: bytes, filename: str):
    from fastapi.responses import Response
    return Response(
        content=payload, media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="{filename}"'})


_LIBRARY = None


def get_rate_library():
    """Shared master rate library (override in tests via dependency)."""
    global _LIBRARY
    if _LIBRARY is None:
        from qs_engine.persistence.rate_library import RateLibrary
        _LIBRARY = RateLibrary()
    return _LIBRARY


@app.post("/api/v1/export/pdf/boq")
def export_pdf_boq(body: BoqPdfRequest):
    """Return a formal BOQ summary PDF stream for take-off lines."""
    from qs_engine.export.pdf_exporter import build_boq_summary_pdf
    compiled = _compile_from_entries(
        body.project_ref, body.boq_ref, body.lines)
    try:
        payload = build_boq_summary_pdf(
            compiled, body.info.model_dump())
    except QSEngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _pdf_stream(payload, "boq_summary.pdf")


@app.post("/api/v1/export/pdf/ipc")
def export_pdf_ipc(body: IPCPdfRequest):
    """Return an IPC statement PDF stream for a valuation request."""
    from qs_engine.export.pdf_exporter import build_ipc_pdf
    from qs_engine.ui.controllers import ipc_valuation_controller
    ipc = body.ipc
    result = ipc_valuation_controller(
        ipc.contract_sum, ipc.retention_rate_pct, ipc.retention_limit,
        previous_valuation=ipc.previous_valuation,
        items=[entry.model_dump() for entry in ipc.items],
        onsite_materials=ipc.onsite_materials,
        advance_repaid=ipc.advance_repaid,
        advance_balance=ipc.advance_balance,
        previous_payments=ipc.previous_payments,
        valuation_no=ipc.valuation_no)
    valuation = _or_422(result)
    try:
        payload = build_ipc_pdf(valuation, body.info.model_dump())
    except QSEngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _pdf_stream(payload, "ipc_statement.pdf")


@app.post("/api/v1/project/save")
def project_save(body: ProjectFileRequest):
    """Serialize session JSON into a downloadable `.clk` stream."""
    from qs_engine.persistence.project_file import (
        PROJECT_FILE_EXTENSION,
        ProjectFileAdapter,
        SessionState,
    )
    try:
        state = SessionState(
            project={str(k): str(v)
                     for k, v in dict(body.project or {}).items()},
            project_saved=bool(body.project_saved),
            standard=(None if body.standard is None else {
                "standard": body.standard.standard,
                "edition": body.standard.edition}),
            lines=[entry.model_dump() for entry in body.lines],
            last_rate=(dict(body.last_rate)
                       if body.last_rate is not None else None),
            last_ipc=(dict(body.last_ipc)
                      if body.last_ipc is not None else None),
            boq=(dict(body.boq) if body.boq is not None else None),
        )
        from qs_engine.persistence.project_file import state_from_dict
        state_from_dict(state.to_dict())  # schema guard before streaming
        payload = ProjectFileAdapter.encode(state)
    except QSEngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    from fastapi.responses import Response
    return Response(
        content=payload, media_type="application/octet-stream",
        headers={"Content-Disposition":
                 f'attachment; filename="project'
                 f'{PROJECT_FILE_EXTENSION}"'})


@app.post("/api/v1/project/load")
def project_load(file: UploadFile = File(...)):
    """Ingest a `.clk` (or legacy `.civolink`) file; return session JSON."""
    from qs_engine.persistence.project_file import (
        ProjectFileAdapter,
        READABLE_EXTENSIONS,
    )
    if not str(file.filename or "").lower().endswith(READABLE_EXTENSIONS):
        raise HTTPException(
            status_code=422,
            detail="Project upload must be a .clk file "
                   "(legacy .civolink accepted)")
    try:
        content = file.file.read()
    except Exception as exc:
        raise HTTPException(status_code=422,
                            detail=f"Could not read upload: "
                                   f"{exc}") from exc
    try:
        state = ProjectFileAdapter.decode(content)
    except QSEngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return state.to_dict()


@app.get("/api/v1/library/rates", response_model=List[RateRowResponse])
def library_rates(category: str = "", search: str = "",
                  library=Depends(get_rate_library)):
    """Query master rates, optionally filtered by category/text."""
    try:
        rows = library.list_rates(category=category, search=search)
    except QSEngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [RateRowResponse(**row) for row in rows]


@app.post("/api/v1/library/rates", response_model=RateRowResponse)
def library_upsert(body: RateUpsertRequest,
                   library=Depends(get_rate_library)):
    """Insert or update one master rate (exact-string storage)."""
    try:
        row = library.upsert_rate(
            body.category, body.code, description=body.description,
            unit=body.unit, rate=body.rate, source=body.source)
    except QSEngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RateRowResponse(**row)
