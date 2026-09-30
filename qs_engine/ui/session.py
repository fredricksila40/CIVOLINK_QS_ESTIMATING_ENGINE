"""UI-layer session store (Phase 13 refactor): take-off schedule state.

Pure Python, no widgets, no arithmetic. Holds the estimator's working
take-off lines, the project profile, and the last compiled BOQ so pages
can navigate, grid, assemble, and export without backend changes.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json, os, zipfile, io

from qs_engine.boq.models import (
    Boq,
    BoqItem,
    BoqSection,
    explicit_rate,
    unpriced_item,
)
from qs_engine.core.errors import ValidationError

from .controllers import parse_decimal

#: Archive directory for .clk session files.
CLK_ARCHIVE_DIR = Path(os.environ.get("APPDATA", "")) / "CIVOLINK" / "sessions"

#: Trade key -> (section code, section title, subsection title) for the
#: session-to-BOQ assembly. Grouping only; measurement lives in engines.
TRADE_SECTIONS = {
    "concrete": ("C", "Concrete", "In-situ"),
    "masonry": ("M", "Masonry", "Blockwork"),
    "rebar": ("R", "Reinforcement", "Bars"),
    "formwork": ("T", "Formwork", "Temporary works"),
    "earthworks": ("E", "Earthworks", "Excavation"),
    "finishes": ("F", "Finishes", "General"),
    "labour": ("L", "Labour", "General"),
    "plant": ("P", "Plant", "General"),
    "logistics": ("H", "Haulage", "General"),
}


@dataclass(frozen=True)
class TakeoffLine:
    """One working take-off line. Quantity is an exact Decimal string;
    rate is an optional exact Decimal string (None = unpriced)."""
    trade: str
    description: str
    unit: str
    quantity: str
    rate: Optional[str] = None
    rate_ref: str = ""
    takeoff_ref: str = ""


class TakeoffSession:
    """Mutable working session with pure, inspectable behaviour."""

    def __init__(self):
        self.project: Dict[str, str] = {}
        # Set ONLY by a successful save_project() call below — never by
        # mere dict presence. Blank saves raise instead of flagging.
        self.project_saved: bool = False
        self.standard = None  # ProjectSetupView or None
        self._lines: List[TakeoffLine] = []
        self.last_boq_view = None
        self.last_compiled = None
        # Last rate built on the Rate Builder page, if any:
        # {"gross": <Decimal string>, "ref": <rate reference>}.
        # Display/plumbing state only — pricing lives in rate results.
        self.last_rate = None
        # Last IPC valuation computed on the Valuations page, if any:
        # an IPCValuation DTO. Display/plumbing state only.
        self.last_ipc = None
        # Last commercial valuation computed on the Valuations
        # page, if any: a CommercialValuation DTO. Plumbing state
        # only; never persisted to .clk files.
        self.last_commercial = None
        # Last mix design computed on the Mix Design page, if any:
        # a ConstituentResult DTO. Plumbing state only;
        # never persisted to .clk files.
        self.last_mix_design = None
        # Material key staged by the catalogue's "Use in Rate Builder"
        # action, consumed once by the next Rate Builder build.
        # Display-plumbing state only: never persisted to .clk files.
        self.pending_material_key = None
        # Site store-log transactions imported on the Site Reconciliation
        # page, if any: StockTransaction records. Display-plumbing state
        # only: never persisted to .clk files.
        self.store_transactions = None

    @property
    def boq_compiled(self) -> bool:
        """True once a compiled BOQ snapshot exists in this session.

        Read-only presentation flag driving the export action guards
        on the output pages (disable until the BOQ is compiled).
        """
        return self.last_compiled is not None

    # -- project profile (display fields only; no backend involved) --------

    def set_project(self, **fields) -> Dict[str, str]:
        """Store project identity fields (strings, stripped)."""
        for key, value in fields.items():
            self.project[key] = str(value or "").strip()
        return dict(self.project)

    def has_profile(self) -> bool:
        """True only when at least one profile field is non-empty.

        Data-presence check only — it does NOT mean the profile was
        saved. Only a successful save_project() sets project_saved.
        """
        return any(str(value or "").strip()
                   for value in self.project.values())

    def save_project(self, **fields) -> Dict[str, str]:
        """Validate, store, and flag a project profile as saved.

        Raises ValidationError (and leaves project_saved False) unless
        at least one field is non-empty — a blank save is never
        reported as saved.
        """
        cleaned = {key: str(value or "").strip()
                   for key, value in fields.items()}
        if not cleaned or not any(cleaned.values()):
            raise ValidationError(
                "Cannot save an empty project profile — "
                "fill at least one field")
        self.project = cleaned
        self.project_saved = True
        return dict(self.project)

    def clear_project(self) -> None:
        """Reset the profile; the saved flag is revoked with it."""
        self.project = {}
        self.project_saved = False

    # -- take-off lines ------------------------------------------------------

    def add_line(self, line: TakeoffLine) -> int:
        """Append a line; returns its index. Validates shape only."""
        if not isinstance(line, TakeoffLine):
            raise ValidationError(
                f"Takeoff line must be a TakeoffLine; "
                f"got {type(line).__name__}")
        if not line.trade or not line.trade.strip():
            raise ValidationError("Take-off line needs a trade")
        if not line.description or not line.description.strip():
            raise ValidationError("Take-off line needs a description")
        parse_decimal(line.quantity, "quantity")
        if line.rate not in (None, ""):
            parse_decimal(line.rate, "rate")
        self._lines.append(line)
        return len(self._lines) - 1

    def remove_line(self, index: int) -> TakeoffLine:
        """Remove and return the line at index (IndexError if absent)."""
        return self._lines.pop(index)

    def clear_lines(self) -> None:
        """Drop all working lines (compiled snapshots are kept)."""
        self._lines = []

    def lines(self) -> Tuple[TakeoffLine, ...]:
        """Current lines in entry order."""
        return tuple(self._lines)

    def lines_by_trade(self, trade: str):
        """Lines for one trade, in entry order."""
        return tuple(line for line in self._lines if line.trade == trade)

    def set_line_rate(self, index: int, rate: str,
                      rate_ref: str = "") -> TakeoffLine:
        """Assign an explicit rate to a line (replaces it immutably)."""
        current = self._lines[index]
        parse_decimal(rate, "rate")
        updated = TakeoffLine(
            trade=current.trade, description=current.description,
            unit=current.unit, quantity=current.quantity,
            rate=str(rate).strip(),
            rate_ref=str(rate_ref or "").strip(),
            takeoff_ref=current.takeoff_ref)
        self._lines[index] = updated
        return updated

    def summary_counts(self) -> Dict[str, int]:
        """Line/trade counts for overview and status bars."""
        by_trade: Dict[str, int] = {}
        for line in self._lines:
            by_trade[line.trade] = by_trade.get(line.trade, 0) + 1
        return {"lines": len(self._lines), "by_trade": by_trade}

    # -- BOQ assembly (existing contracts only) -------------------------------

    def to_boq(self, project_ref: str, boq_ref: str) -> Boq:
        """Assemble a Boq from working lines, grouped by trade.

        Lines carrying a rate become explicit-rate items; the rest become
        unpriced items. Deterministic: first-appearance trade order,
        entry order within trade.
        """
        if not self._lines:
            raise ValidationError(
                "No take-off lines to compile — add lines first")
        if not project_ref or not str(project_ref).strip():
            raise ValidationError("project_ref is required to compile a BOQ")
        if not boq_ref or not str(boq_ref).strip():
            raise ValidationError("boq_ref is required to compile a BOQ")
        order = []
        grouped = {}
        for line in self._lines:
            if line.trade not in grouped:
                grouped[line.trade] = []
                order.append(line.trade)
            grouped[line.trade].append(line)
        sections = []
        for trade in order:
            code, title, sub_title = TRADE_SECTIONS.get(
                trade, (trade.upper(), trade.title(), "General"))
            items = []
            for line in grouped[trade]:
                quantity = parse_decimal(line.quantity, "quantity")
                if line.rate not in (None, ""):
                    pricing = explicit_rate(
                        parse_decimal(line.rate, "rate"),
                        line.rate_ref or "session")
                else:
                    pricing = unpriced_item()
                items.append(BoqItem(
                    description=line.description, trade=trade,
                    unit=line.unit, quantity=quantity, pricing=pricing,
                    takeoff_ref=line.takeoff_ref))
            sections.append(BoqSection.single(code, title, tuple(items)))
        return Boq(project_ref=str(project_ref).strip(),
                   boq_ref=str(boq_ref).strip(),
                   sections=tuple(sections))

    # -- .clk session archive -----------------------------------------------

    def save_archive(self, name: str) -> Path:
        """Save the full session as a .clk archive file.

        Creates the archive directory if needed and writes a
        zip-based .clk file containing project profile, take-off
        lines, and session metadata. Returns the archive path.
        """
        CLK_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"{name}_{stamp}.clk" if name else f"session_{stamp}.clk"
        archive_path = CLK_ARCHIVE_DIR / archive_name
        payload = self._archive_payload()
        tmp = archive_path.with_name(archive_path.name + ".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("session.json", json.dumps(payload))
        os.replace(tmp, archive_path)
        return archive_path

    def load_archive(self, archive_path: Path) -> dict:
        """Load a .clk archive and return its payload dict.

        Validates the archive structure. Raises ValidationError
        on corrupt or invalid archives.
        """
        if not archive_path.exists():
            raise ValidationError(f"Archive {archive_path} not found")
        if archive_path.suffix != ".clk":
            raise ValidationError("Only .clk archives are supported")
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                if "session.json" not in zf.namelist():
                    raise ValidationError("Archive missing session.json")
                data = json.loads(zf.read("session.json"))
        except (OSError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            raise ValidationError(f"Invalid .clk archive: {exc}")
        self._validate_archive_payload(data)
        return data

    def export_clk(self) -> bytes:
        """Serialize the current session as a .clk byte stream."""
        return json.dumps(self._archive_payload()).encode("utf-8")

    def _archive_payload(self) -> dict:
        """Build the archive payload dict from the current session state."""
        return {
            "schema_version": "1.0",
            "exported_on": datetime.now().isoformat(),
            "project": self.project,
            "project_saved": self.project_saved,
            "lines": [
                {
                    "trade": l.trade,
                    "description": l.description,
                    "unit": l.unit,
                    "quantity": l.quantity,
                    "rate": l.rate,
                    "rate_ref": l.rate_ref,
                    "takeoff_ref": l.takeoff_ref,
                }
                for l in self._lines
            ],
            "last_boq_view": self.last_boq_view,
            "last_compiled": str(self.last_compiled) if self.last_compiled is not None else None,
            "last_rate": str(self.last_rate) if self.last_rate is not None else None,
            "last_mix_design": self.last_mix_design.designation if self.last_mix_design is not None else None,
        }

    def _validate_archive_payload(self, data: dict) -> None:
        """Validate an archive payload has required fields."""
        if not isinstance(data, dict):
            raise ValidationError("Archive payload must be a dict")
        if "schema_version" not in data:
            raise ValidationError("Archive missing schema_version")
        if "lines" not in data or not isinstance(data["lines"], list):
            raise ValidationError("Archive missing or invalid lines")
        for line in data["lines"]:
            for field in ("trade", "description", "quantity"):
                if field not in line or not str(line.get(field, "")).strip():
                    raise ValidationError(f"Archive line missing {field}")

    def import_clk(self, data: dict) -> None:
        """Import a .clk archive payload into the current session.

        Validates the payload, then replaces the current session
        lines and project profile with the archived state.
        """
        self._validate_archive_payload(data)
        self.project = data.get("project", {})
        self.project_saved = data.get("project_saved", False)
        self._lines = []
        for line_data in data.get("lines", []):
            line = TakeoffLine(
                trade=str(line_data["trade"]),
                description=str(line_data["description"]),
                unit=str(line_data.get("unit", "")),
                quantity=str(line_data["quantity"]),
                rate=line_data.get("rate"),
                rate_ref=str(line_data.get("rate_ref", "")),
                takeoff_ref=str(line_data.get("takeoff_ref", "")),
            )
            self._lines.append(line)
