"""Single-file project persistence (Phase 20): `.clk` format.

A `.clk` (CIVOLINK Project File) file is zlib-compressed JSON
describing complete session state: project identity, measurement
binding, take-off lines, rate builder state, BOQ references, and the
IPC valuation record. Legacy `.civolink` files carry the identical
payload and remain fully readable. Master enterprise price lists are
NOT duplicated here — they live in the SQLite rate library
(rate_library.py), which is the single source of truth for shared
rates across projects.

Schema versioning: every file carries ``"version": "1.0.0"``. Loads
with any other version fail closed (migration guard) instead of
half-loading an incompatible layout. Corrupt or non-project files
fail closed the same way — never a partial session.
"""

import json
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from qs_engine.core.errors import ValidationError

SCHEMA_VERSION = "1.0.0"

#: Standard project file extension (CIVOLINK Project File).
PROJECT_FILE_EXTENSION = ".clk"
#: Legacy extension (identical payload; read support retained).
LEGACY_PROJECT_FILE_EXTENSION = ".civolink"

#: Extensions accepted when opening a project file, primary first.
READABLE_EXTENSIONS = (PROJECT_FILE_EXTENSION,
                       LEGACY_PROJECT_FILE_EXTENSION)

#: Payload bounds (S-2): compressed input and decompressed JSON are
#: both capped far above real project files but far below a
#: decompression bomb. zlib.decompress() has no max_length parameter
#: in CPython, so decode() drives decompressobj().decompress(data,
#: max_length) — the equivalent bounded-output call.
MAX_ENCODED_BYTES = 8 * 1024 * 1024
MAX_DECODED_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class SessionState:
    """Serializable session snapshot (all plain JSON types)."""
    version: str = SCHEMA_VERSION
    project: Dict[str, str] = field(default_factory=dict)
    project_saved: bool = False
    standard: Optional[Dict[str, str]] = None
    lines: List[Dict[str, str]] = field(default_factory=list)
    last_rate: Optional[Dict[str, str]] = None
    last_ipc: Optional[Dict[str, object]] = None
    boq: Optional[Dict[str, str]] = None

    def to_dict(self) -> dict:
        """Plain-JSON dict (round-trippable through json + zlib)."""
        import dataclasses

        def convert(value):
            if dataclasses.is_dataclass(value):
                return {f.name: convert(getattr(value, f.name))
                        for f in dataclasses.fields(value)}
            if isinstance(value, (tuple, list)):
                return [convert(v) for v in value]
            if isinstance(value, dict):
                return {k: convert(v) for k, v in value.items()}
            return value

        return convert(self)


def _require_mapping(data, field: str) -> dict:
    if not isinstance(data, dict):
        raise ValidationError(
            f"Project file field {field!r} must be a mapping; "
            f"got {type(data).__name__}")
    return data


def state_from_dict(data: dict) -> SessionState:
    """Validate a decoded mapping into SessionState (migration guard)."""
    data = _require_mapping(data, "document")
    version = data.get("version", "")
    if version != SCHEMA_VERSION:
        raise ValidationError(
            f"Unsupported project file version {version!r}; "
            f"this build reads {SCHEMA_VERSION} only")
    project = {str(k): str(v) for k, v in
               _require_mapping(data.get("project", {}), "project").items()}
    # Material Code Formatting rides the project profile: an unknown
    # policy token (or an invalid custom prefix) fails closed here
    # instead of half-loading and generating the wrong code shape.
    policy_token = str(project.get("material_code_policy", "") or "").strip()
    if policy_token:
        from qs_engine.resources.code_policy import MaterialCodePolicy
        MaterialCodePolicy.parse(
            policy_token, project.get("material_code_prefix", ""))
    standard = data.get("standard")
    if standard is not None:
        standard = _require_mapping(standard, "standard")
        if not str(standard.get("standard", "") or "").strip():
            raise ValidationError(
                "Project file standard needs a non-blank 'standard'")
        standard = {"standard": str(standard.get("standard", "")),
                    "edition": str(standard.get("edition", "") or "")}
    lines = data.get("lines", [])
    if not isinstance(lines, list):
        raise ValidationError("Project file 'lines' must be a list")
    for index, line in enumerate(lines):
        _require_mapping(line, f"lines[{index}]")
    last_rate = data.get("last_rate")
    if last_rate is not None:
        _require_mapping(last_rate, "last_rate")
    last_ipc = data.get("last_ipc")
    if last_ipc is not None:
        _require_mapping(last_ipc, "last_ipc")
    boq = data.get("boq")
    if boq is not None:
        boq = _require_mapping(boq, "boq")
        if not str(boq.get("project_ref", "") or "").strip() or not str(
                boq.get("boq_ref", "") or "").strip():
            raise ValidationError(
                "Project file 'boq' needs project_ref and boq_ref")
        boq = {"project_ref": str(boq["project_ref"]),
               "boq_ref": str(boq["boq_ref"])}
    return SessionState(
        version=SCHEMA_VERSION,
        project=project,
        project_saved=bool(data.get("project_saved", False)),
        standard=standard,
        lines=[dict(line) for line in lines],
        last_rate=(dict(last_rate) if last_rate is not None else None),
        last_ipc=(dict(last_ipc) if last_ipc is not None else None),
        boq=boq,
    )


def state_from_session(session) -> SessionState:
    """Snapshot a live TakeoffSession (read-only; session untouched)."""
    standard = None
    if session.standard is not None:
        standard = {"standard": str(session.standard.standard),
                    "edition": str(session.standard.edition or "")}
    last_ipc = None
    if session.last_ipc is not None:
        last_ipc = (session.last_ipc.to_dict()
                    if hasattr(session.last_ipc, "to_dict")
                    else dict(session.last_ipc))
    boq = None
    if session.last_compiled is not None:
        boq = {"project_ref": str(session.last_compiled.project_ref),
               "boq_ref": str(session.last_compiled.boq_ref)}
    return SessionState(
        # The whole profile travels verbatim, including the Material
        # Code Formatting fields (material_code_policy / prefix) —
        # validated on the way back in by state_from_dict.
        project=dict(session.project),
        project_saved=bool(session.project_saved),
        standard=standard,
        lines=[{"trade": line.trade, "description": line.description,
                "unit": line.unit, "quantity": line.quantity,
                "rate": line.rate,
                "rate_ref": line.rate_ref,
                "takeoff_ref": line.takeoff_ref}
               for line in session.lines()],
        last_rate=(dict(session.last_rate)
                   if session.last_rate is not None else None),
        last_ipc=last_ipc,
        boq=boq,
    )


def _ipc_from_dict(data: dict):
    """Rebuild an IPCValuation from stored dict form (validated)."""
    from qs_engine.valuation.ipc_engine import IPCLine, IPCValuation
    try:
        lines = tuple(IPCLine(
            item_no=str(line.get("item_no", "")),
            description=str(line.get("description", "")),
            unit=str(line.get("unit", "")),
            rate=str(line.get("rate", "")),
            completed_qty=str(line.get("completed_qty", "")),
            line_value=str(line.get("line_value", "")),
        ) for line in data.get("lines", ()))
        return IPCValuation(
            valuation_no=str(data.get("valuation_no", "") or ""),
            contract_sum=str(data["contract_sum"]),
            previous_valuation=str(data["previous_valuation"]),
            current_work=str(data["current_work"]),
            work_to_date=str(data["work_to_date"]),
            onsite_materials=str(data["onsite_materials"]),
            gross_certified=str(data["gross_certified"]),
            retention_rate_pct=str(data["retention_rate_pct"]),
            retention_limit=str(data["retention_limit"]),
            retention_withheld=str(data["retention_withheld"]),
            advance_repaid=str(data["advance_repaid"]),
            previous_payments=str(data["previous_payments"]),
            total_deductions=str(data["total_deductions"]),
            net_payable=str(data["net_payable"]),
            lines=lines,
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValidationError(
            f"Stored IPC valuation is incomplete: {exc}") from exc


class ProjectFileAdapter:
    """Save/load `.clk` project files (compressed JSON)."""

    @staticmethod
    def encode(state: SessionState) -> bytes:
        """SessionState -> compressed `.clk` bytes."""
        if not isinstance(state, SessionState):
            raise ValidationError(
                "encode needs a SessionState; "
                f"got {type(state).__name__}")
        return zlib.compress(
            json.dumps(state.to_dict(), indent=2).encode("utf-8"))

    @staticmethod
    def decode(payload: bytes) -> SessionState:
        """Compressed (or plain JSON) bytes -> validated SessionState."""
        if not isinstance(payload, (bytes, bytearray)):
            raise ValidationError(
                "decode needs bytes; "
                f"got {type(payload).__name__}")
        payload = bytes(payload)
        if len(payload) > MAX_ENCODED_BYTES:
            raise ValidationError(
                f"Project file payload is {len(payload)} bytes; "
                f"the limit is {MAX_ENCODED_BYTES} bytes")
        try:
            raw = zlib.decompressobj().decompress(
                payload, MAX_DECODED_BYTES + 1)
        except Exception:
            raw = payload  # debug/hand-edited plain JSON fallback
        if len(raw) > MAX_DECODED_BYTES:
            raise ValidationError(
                f"Project file decompresses beyond {MAX_DECODED_BYTES} "
                f"bytes; refusing to load")
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValidationError(
                f"Not a readable project file: {exc}") from exc
        return state_from_dict(data)

    @classmethod
    def save_project(cls, path, session_data) -> str:
        """Snapshot a session (or SessionState) to a `.clk` file.

        The write commits atomically (tmp + fsync + os.replace) through
        the shared helper in licensing/storage, so a crash mid-save can
        never leave a half-written project file behind — the previous
        file survives intact until the replacement is fully durable.
        """
        from qs_engine.licensing.storage import atomic_write_bytes
        from qs_engine.ui.session import TakeoffSession
        if isinstance(session_data, SessionState):
            state = session_data
        elif isinstance(session_data, TakeoffSession):
            state = state_from_session(session_data)
        else:
            raise ValidationError(
                "save_project needs a TakeoffSession or SessionState; "
                f"got {type(session_data).__name__}")
        output = Path(path)
        try:
            atomic_write_bytes(output, cls.encode(state))
        except OSError as exc:
            raise ValidationError(
                f"Could not write project file: {exc}") from exc
        return str(output)

    @classmethod
    def load_project(cls, path) -> SessionState:
        """Read and validate a `.clk` file into SessionState."""
        file_path = Path(path)
        if not file_path.is_file():
            raise ValidationError(
                f"Project file not found: {file_path}")
        try:
            payload = file_path.read_bytes()
        except OSError as exc:
            raise ValidationError(
                f"Could not read project file: {exc}") from exc
        return cls.decode(payload)


def save_session(session, path) -> str:
    """Snapshot a live session to a `.clk` file (returns path)."""
    return ProjectFileAdapter.save_project(path, session)


def load_session(session, path) -> str:
    """Hydrate a live session from a `.clk` file (in place).

    Standard rebinding, line validation, and BOQ recompilation all run
    through the existing contracts, so stored data that no longer
    validates fails closed instead of half-loading. Returns a short
    human summary of what was restored.
    """
    from qs_engine.boq.compiler import compile_boq
    from qs_engine.ui.controllers import project_setup_controller
    from qs_engine.ui.session import TakeoffLine
    from qs_engine.ui.viewmodels import ErrorView
    state = ProjectFileAdapter.load_project(path)
    session.project = dict(state.project)
    session.project_saved = bool(state.project_saved)
    if state.standard is None:
        session.standard = None
    else:
        bound = project_setup_controller(
            standard=state.standard["standard"],
            edition=state.standard.get("edition", ""))
        if isinstance(bound, ErrorView):
            raise ValidationError(
                f"Stored measurement standard rejected: {bound.message}")
        session.standard = bound
    session.clear_lines()
    for raw in state.lines:
        session.add_line(TakeoffLine(
            trade=str(raw.get("trade", "")),
            description=str(raw.get("description", "")),
            unit=str(raw.get("unit", "")),
            quantity=str(raw.get("quantity", "")),
            rate=raw.get("rate"),
            rate_ref=str(raw.get("rate_ref", "") or ""),
            takeoff_ref=str(raw.get("takeoff_ref", "") or "")))
    session.last_rate = (dict(state.last_rate)
                         if state.last_rate is not None else None)
    session.last_ipc = (_ipc_from_dict(state.last_ipc)
                        if state.last_ipc is not None else None)
    session.last_compiled = None
    session.last_boq_view = None
    if state.boq is not None and session.lines():
        session.last_compiled = compile_boq(session.to_boq(
            state.boq["project_ref"], state.boq["boq_ref"]))
    boq_state = ("recompiled" if session.last_compiled is not None
                 else "not compiled")
    project_state = "saved" if session.project_saved else "open"
    restored = (f"{len(state.lines)} take-off lines, "
                f"project {project_state}, BOQ {boq_state}")
    return restored
