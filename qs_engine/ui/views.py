"""CIVOLINK QS desktop shell: project-centric sidebar application.

Two-pane layout (sidebar + workspace) with domain-grouped navigation.
Pages collect input, dispatch through existing controllers, and render
view-models; session state (take-off schedule, project profile, last
compilation) lives in session.py. Zero calculation logic here.

Importing this module needs no display; only instantiating widgets
does. Provider identity: CIVOLINK blue #004F9D, slate grey #555D6B,
canvas #F4F6F9. Stdlib tkinter/ttk only.
"""

import tkinter as tk
from tkinter import ttk

from . import controllers
from .session import TakeoffLine, TakeoffSession, TRADE_SECTIONS
from .viewmodels import ErrorView
from .widgets import (
    HelpIconButton,
    HelpIconLabel,
    PopoverGuide as _WidgetPopoverGuide,
    ToolTip,
    close_all_popovers,
    close_all_tooltips,
)
from qs_engine.boq.compiler import compile_boq
from qs_engine.core.errors import QSEngineError, ValidationError
from qs_engine.core.security import SessionContext, UserRole
from qs_engine.master_data.repository import MasterDataRepository

# --------------------------------------------------------------------------
# CIVOLINK provider brand tokens (presentation only — never touch engine).
# --------------------------------------------------------------------------
APP_TITLE = "CIVOLINK QS Estimating Engine v1.4.2"
FOOTER_BADGE = "Powered by CIVOLINK"

CIVOLINK_BLUE = "#004F9D"
SLATE_GREY = "#555D6B"
CANVAS_BG = "#F4F6F9"
STATUSBAR_BG = "#E9EDF3"
INSTRUCTION_FILL = "#EBF3FA"
INSTRUCTION_BORDER = "#B8D4E3"
OK_GREEN = "#1E7B34"
WARN_AMBER = "#B45309"
BAD_RED = "#B91C1C"

HEADER_FONT = ("TkDefaultFont", 12, "bold")
SECTION_FONT = ("TkDefaultFont", 11, "bold")
FOOTER_FONT = ("TkDefaultFont", 9)
BUTTON_FONT = ("TkDefaultFont", 10, "bold")
ICON_FONT = ("TkDefaultFont", 10)

#: Standard resource-lookup trigger. One clean, square glyph button sits
#: adjacent to the field it fills; the field itself stays compact and never
#: carries a long instructional sentence pointing the user at the button.
#: The glyph is unicode by design: this module is stdlib tkinter/ttk only
#: (no PIL/ImageTk asset loader, no qs_engine/ui/assets/ tree), so the
#: symbol is rendered centered at ICON_FONT for high-DPI crispness.
PICKER_ICON = "\U0001F50D"
#: Compact placeholder for lookup-driven fields (display only; reads go
#: through _entry_text so it can never serialize into a calculation).
PICKER_HINT = "Select..."
PICKER_BUTTON_STYLE = "Picker.TButton"

#: Panel specs: key -> (title, controller name, [(field, label)]).
#: Tests pin that every spec maps to a real controller (no widgets needed).
#: Shape is frozen — instruction banners live in PANEL_INSTRUCTIONS.
PANEL_SPECS = {
    "project": ("Project Setup", "project_setup_controller",
                [("standard", "Standard (SMM/CESMM)"),
                 ("edition", "Edition")]),
    "concrete": ("Concrete Take-off", "concrete_controller",
                 [("element", "Element"), ("length", "Length (m)"),
                  ("width", "Width (m)"), ("thickness", "Thickness (m)"),
                  ("unit", "Unit (default m)"),
                  ("class_key", "Concrete Grade")]),
    "masonry": ("Masonry Take-off", "masonry_controller",
                [("element", "Element"), ("wall_length", "Wall length"),
                 ("wall_height", "Wall height"), ("unit", "Unit (default m)"),
                 ("unit_key", "Unit key")]),
    "earthworks": ("Earthworks", "earthworks_controller",
                   [("element", "Element"), ("length", "Length"),
                    ("width", "Width"), ("depth", "Depth"),
                    ("unit", "Unit (default m)"),
                    ("working_space_m", "Working space"),
                    ("soil_key", "Soil key"),
                    ("displaced_substructure_m3", "Displaced (m³)")]),
    "finishes": ("Finishes Take-off", "finishes_controller",
                 [("kind", "Kind (plaster/screed/tiles/paint)"),
                  ("element", "Element"), ("length", "Length"),
                  ("width", "Width (screed/tiles)"),
                  ("height", "Height (plaster/paint)"),
                  ("thickness", "Thickness"),
                  ("tile_length_mm", "Tile length (mm)"),
                  ("tile_width_mm", "Tile width (mm)"),
                  ("joint_mm", "Joint (mm)"),
                  ("wastage_pct", "Wastage % (tiles, optional)"),
                  ("coats", "Coats (paint)")]),
    "labour": ("Labour", "labour_controller",
               [("element", "Element"), ("work_quantity", "Work quantity"),
                ("trade_key", "Trade key"), ("hours_per_day", "Hours/day")]),
    "plant": ("Plant", "plant_controller",
              [("element", "Element"), ("work_quantity", "Work quantity"),
               ("equipment_key", "Equipment key"),
               ("hours_per_day", "Hours/day")]),
    "logistics": ("Haulage Plan", "logistics_plan_controller",
                  [("element", "Element"),
                   ("total_loose_m3", "Loose volume (m³)"),
                   ("loose_density_t_per_m3", "Loose density (t/m³)"),
                   ("truck_key", "Truck key"),
                   ("distance_km", "Distance (km)"),
                   ("available_minutes_per_day", "Minutes/day"),
                   ("target_per_day", "Daily target"),
                   ("target_unit", "Target unit (tonne/m3)")]),
    "rates": ("Rate Builder", "rate_builder_controller",
              [("element", "Element"), ("work_unit", "Rate Unit"),
               ("markup_policy", "Policy (sequential/parallel)")]),
     "boq": ("BOQ View", "boq_view_controller", []),
     "mix_design": ("Mix Design", "mix_design_controller",
               [("element", "Element"),
                ("designation", "Strength Class"),
                ("net_volume", "Target Volume (m³)"),
                ("wastage_pct", "Site Wastage %")]),
 }

#: Per-tab instruction banners (spec text, verbatim).
PANEL_INSTRUCTIONS = {
    "project": "\u2022 Enter Measurement Standard ('CESMM' or 'SMM') and "
               "Edition ('CESMM4' or 'SMM7'). Click Calculate to bind "
               "metadata to downstream take-offs.",
    "concrete": "\u2022 Enter Length, Width, Thickness (m) and pick a "
                "concrete grade from the dropdown (master-data grades "
                "only). Dry constituent densities default from Project "
                "Setup and apply live. Output calculates wet volume & dry "
                "constituent quantities.",
    "masonry": "\u2022 Enter wall area (m\u00b2), thickness (mm), unit type, "
               "and mortar mix ratio (e.g. 1:3, 1:4). Output calculates "
               "block count & wet/dry mortar volumes.",
    "earthworks": "\u2022 Enter cut/fill plan dimensions, depth (m), "
                  "bulking & shrinkage factors. Output calculates bank and "
                  "compacted volume adjustments.",
    "finishes": "\u2022 Enter surface area (m\u00b2) and thickness (mm) for "
                "plaster, screed, tiles, or paint. Output computes material "
                "quantities & coverage requirements.",
    "labour": "\u2022 Input gang productivity rates or hourly requirements. "
              "Select standard trade roles or heavy machinery plant "
              "categories.",
    "plant": "\u2022 Input gang productivity rates or hourly requirements. "
             "Select standard trade roles or heavy machinery plant "
             "categories.",
    "logistics": "\u2022 Enter material tonnage/volume, haul distance (km), "
                 "and truck payload capacity. Computes trip counts and "
                 "logistics rate build-up.",
    "rates": "\u2022 Combines Material, Labour, and Plant rates. Apply "
             "Overheads & Profit % to build final unit composite rates.",
     "boq": "\u2022 Click 'Compile BOQ' to aggregate all trade items. "
            "Displays itemized bill with standard citations. Triggers Excel "
            "and document data exports.",
     "mix_design": "\u2022 Pick a Eurocode strength class (C20/25, "
                   "C25/30, C30/37) and enter the target net volume "
                   "(m\u00b3). Constituent quantities (cement bags, "
                   "sand, coarse aggregate, water) compute live "
                   "from the BS EN 206 / BS 8500 mass-based targets.",
 }

INSTRUCTION_TITLE = "\u2139\ufe0f Panel Instructions & Input Guide"

#: Example cues for take-off form fields, keyed by (panel spec key, field
#: name). Cues are display-only ghost text: QSPanel.collect() reads through
#: the cue-safe getter, so a cue can never reach a controller or the engine.
#: Every cue is an "e.g.," example of what the field actually accepts — the
#: vocabulary shown is drawn from master data, never invented. Fields absent
#: from this map (dimensions, units, keys) stay uncued because their label
#: plus unit already says everything.
FIELD_CUES = {
    ("concrete", "element"): "e.g., Ground Floor Slab S1",
    ("concrete", "class_key"): "e.g., C20 or C25",
    ("masonry", "element"): "e.g., W1 - 200mm Outer Leaf",
    ("masonry", "unit_key"): "e.g., concrete_block_200mm",
    ("earthworks", "element"): "e.g., Strip Footing Trench Line A-C",
    ("finishes", "element"): "e.g., Internal Wall Plaster (12mm)",
     ("logistics", "element"): "e.g., Site to Quarry (15 km)",
}

#: Project Setup identity cues (the page builds its own grid, not a QSPanel).
PROJECT_FIELD_CUES = {
    "name": "e.g., Proposed Kitise Residence",
}

#: Sidebar navigation: group -> ((key, label, kind)). kind "page" has a
#: working view; "placeholder" is a clearly marked unavailable module.
NAV_GROUPS = (
    ("PROJECT", (
        ("overview", "Overview", "page"),
        ("project", "Project Setup", "page"),
    )),
    ("TAKE-OFF", (
        ("concrete", "Concrete", "page"),
        ("masonry", "Masonry", "page"),
        ("rebar", "Reinforcement & Formwork", "page"),
        ("earthworks", "Earthworks", "page"),
        ("finishes", "Finishes", "page"),
    )),
    ("RESOURCES", (
        ("materials", "Materials", "page"),
        ("labour_plant", "Labour & Plant", "page"),
        ("logistics", "Haulage Plan", "page"),
        ("reconciliation", "Site Reconciliation", "page"),
    )),
    ("COMMERCIAL", (
        ("rates", "Rate Builder", "page"),
        ("boq", "Bill of Quantities", "page"),
        ("estimate", "Estimate", "page"),
    )),
     ("OUTPUT & EXPORT", (
         ("excel", "Excel Export / Reconciliation", "page"),
         ("corpdoc", "Corporate Document Integration", "page"),
         ("valuations", "Valuations & IPC", "page"),
     )),
     ("CONSTITUENTS", (
         ("mix_design", "Mix Design", "page"),
     )),
     ("ADMINISTRATION", (
         ("admin_setup", "Admin Setup", "page"),
         ("global_policy_editor", "Global Policy", "page"),
         ("security_policy", "Security Policy", "page"),
     )),
 )

#: Sidebar groups rendered only for an unlocked administrative session.
RESTRICTED_NAV_GROUPS = frozenset({"ADMINISTRATION"})


#: Routes behind the ADMINISTRATION sidebar group (Tier 1+ / Tier 2).
ADMIN_VIEW_KEYS = frozenset(
    key for group, items in NAV_GROUPS if group in RESTRICTED_NAV_GROUPS
    for key, _label, _kind in items)


def admin_nav_visible(session_context) -> bool:
    """True when the sidebar may show the ADMINISTRATION group.

    Least privilege: an unprivileged session never sees the entry, so a
    site clerk cannot discover the administration surface by looking.
    """
    return bool(session_context is not None
                and session_context.is_admin())

#: Sidebar section-header icons (display only; group keys unchanged).
NAV_GROUP_ICONS = {
     "PROJECT": "📂",
     "TAKE-OFF": "📐",
     "RESOURCES": "📦",
     "COMMERCIAL": "💰",
     "OUTPUT & EXPORT": "📤",
    "ADMINISTRATION": "🔐",
     "CONSTITUENTS": "⚙️",
 }

#: Sidebar item + page-header icons keyed by navigation key
#: (display only; PAGES keys and NAV_GROUPS labels unchanged).
NAV_ITEM_ICONS = {
    "overview": "📊",
    "project": "⚙️",
    "concrete": "🏗️",
    "masonry": "🧱",
    "rebar": "🔩",
    "earthworks": "🚜",
    "finishes": "🎨",
    "materials": "📦",
    "labour_plant": "👷",
    "logistics": "🚚",
    "reconciliation": "🧾",
    "rates": "🧮",
    "boq": "📋",
    "estimate": "💵",
    "excel": "📊",
    "corpdoc": "📑",
     "valuations": "📈",
     "mix_design": "🏗️",
    "admin_setup": "🔧",
    "global_policy_editor": "📜",
    "security_policy": "🛡️",
 }

#: Placeholder copy for modules without backend backing in this build.
#: Empty since Phase 16 (materials catalogue and estimate dashboard are
#: working pages); retained with the builder for future modules.
PLACEHOLDER_COPY = {}

#: Status text + restrained indicator colour per BOQ status.
STATUS_STYLES = {
    "priced": ("\u25cf Priced", OK_GREEN),
    "provisional": ("\u25cf Provisional", "#8A6D00"),
    "unpriced": ("\u26a0 Unpriced", WARN_AMBER),
    "unresolved": ("\u26a0 Unresolved", BAD_RED),
}


def status_badge(status: str):
    """(Indicator text, colour) for a BOQ status; unknown values flagged."""
    return STATUS_STYLES.get(status, ("\u26a0 " + str(status), WARN_AMBER))


def format_verification(known: bool) -> str:
    """Honest verification line for a bound measurement standard.

    The backend reports only name recognition (known flag); no
    verified-standard registry exists, so verification is always
    outstanding. Never imply otherwise.
    """
    recognised = ("Recognized standard." if known
                  else "Custom standard name.")
    return (recognised + " \u26a0 Needs Verification — no "
            "verified-standard registry is bound in this build.")


def default_bindings():
    """Controller bindings shared by all take-off forms (unchanged logic).

    Every binding accepts ``(inputs, repository, overrides=None)`` —
    the unified override channel. Trade bindings forward ``overrides``
    to their controller (which feeds the domain engine); bindings whose
    controller has no override surface simply ignore the argument. A
    call without the third argument stays valid (back-compatible).
    """
    return {
        "project": lambda inputs, _repo=None, _overrides=None: (
            controllers.project_setup_controller(
                standard=inputs.get("standard", ""),
                edition=inputs.get("edition", ""))),
        "concrete": controllers.concrete_controller,
        "masonry": controllers.masonry_controller,
        "earthworks": controllers.earthworks_controller,
        "finishes": lambda inputs, repo, _overrides=None: (
            controllers.finishes_controller(
                (inputs.get("kind") or "").strip(), inputs)),
        "labour": lambda inputs, repo, overrides=None: (
            controllers.labour_controller(
                inputs, repo, overrides,
                hours_per_day=inputs.get("hours_per_day") or None)),
        "plant": lambda inputs, repo, overrides=None: (
            controllers.plant_controller(
                inputs, repo, overrides,
                hours_per_day=inputs.get("hours_per_day") or None)),
        "logistics": controllers.logistics_plan_controller,
        "rates": lambda inputs, repo, _overrides=None: (
            controllers.rate_builder_controller(
                [], [], inputs.get("markup_policy") or "sequential",
                inputs.get("element") or "",
                inputs.get("work_unit") or "m²", repo)),
         "boq": lambda inputs, repo, _overrides=None: (
             controllers.boq_view_controller(None)),
         "mix_design": controllers.mix_design_controller,
     }


def _apply_civolink_theme(root) -> None:
    """Apply the CIVOLINK ttk palette to a live root window.

    Called from QSApp.__init__ only (needs a display). Best-effort on
    exotic themes: unknown style options fail silently by design.
    """
    root.configure(background=CANVAS_BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    try:
        style.configure("TFrame", background=CANVAS_BG)
        style.configure("TLabel", background=CANVAS_BG,
                        foreground=SLATE_GREY)
        style.configure("Header.TLabel", background=CANVAS_BG,
                        foreground=CIVOLINK_BLUE, font=HEADER_FONT)
        style.configure("Section.TLabel", background=CANVAS_BG,
                        foreground=CIVOLINK_BLUE, font=SECTION_FONT)
        style.configure("Footer.TLabel", background=STATUSBAR_BG,
                        foreground=SLATE_GREY, font=FOOTER_FONT)
        style.configure("Status.TLabel", background=CANVAS_BG,
                        foreground=SLATE_GREY)
        style.configure("StatusBar.TFrame", background=STATUSBAR_BG)
        style.configure("Segment.TLabel", background=STATUSBAR_BG,
                        foreground=SLATE_GREY)
        style.configure("Instructions.TLabelframe", background=INSTRUCTION_FILL,
                        bordercolor=INSTRUCTION_BORDER)
        style.configure("Instructions.TLabelframe.Label",
                        background=INSTRUCTION_FILL,
                        foreground=CIVOLINK_BLUE)
        style.configure("Instructions.TLabel", background=INSTRUCTION_FILL,
                        foreground=SLATE_GREY)
        style.configure("Accent.TButton", background=CIVOLINK_BLUE,
                        foreground="white", font=BUTTON_FONT)
        style.map("Accent.TButton",
                  background=[("active", "#003A75"), ("pressed", "#002E5C")],
                  foreground=[("active", "white"), ("pressed", "white")])
        style.configure("Nav.TButton", font=BUTTON_FONT, anchor="w")
        # Clean square icon button: tight padding + centered glyph so the
        # picker trigger reads as an icon, not a stretched text button.
        style.configure(PICKER_BUTTON_STYLE, font=ICON_FONT, padding=1,
                        anchor="center")
        style.map(PICKER_BUTTON_STYLE,
                  background=[("active", INSTRUCTION_FILL),
                              ("pressed", INSTRUCTION_BORDER),
                              ("disabled", CANVAS_BG)],
                  foreground=[("active", CIVOLINK_BLUE),
                              ("pressed", CIVOLINK_BLUE),
                              ("disabled", SLATE_GREY)])
        style.configure("TNotebook", background=CANVAS_BG)
        style.configure("TNotebook.Tab", font=BUTTON_FONT)
    except Exception:
        pass


def parse_rate_lines(text: str):
    """Parse a rate-builder line editor into controller line mappings.

    Grammar (one component per line, '#' comments and blanks skipped):
        material | key=<material_key> | qty=<n> | price=<n> | waste=<n> | desc=<text>
        labour | hours=<n> | rate=<n> | desc=<text>
        logistics | total=<n> | qty=<n> | desc=<text>
        subcontract | amount=<n> | desc=<text> | provisional=yes/no
        other | amount=<n> | desc=<text>
    Raises ValidationError naming the offending line.
    """
    from qs_engine.core.errors import ValidationError
    lines = []
    for lineno, raw in enumerate(str(text or "").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = [part.strip() for part in stripped.split("|")]
        kind = parts[0].lower() if parts else ""
        fields = {}
        for part in parts[1:]:
            if "=" not in part:
                raise ValidationError(
                    f"Rate line {lineno}: expected key=value, got {part!r}")
            key, _, value = part.partition("=")
            fields[key.strip().lower()] = value.strip()
        if kind == "material":
            lines.append({"kind": "material",
                          "material_key": fields.get("key", ""),
                          "qty_per_unit": fields.get("qty", ""),
                          "unit_price": fields.get("price", ""),
                          "wastage_pct": fields.get("waste", ""),
                          "description": fields.get("desc", "")})
        elif kind == "labour":
            lines.append({"kind": "labour",
                          "hours_per_unit": fields.get("hours", ""),
                          "rate_per_hour": fields.get("rate", ""),
                          "description": fields.get("desc", "")})
        elif kind == "logistics":
            lines.append({"kind": "logistics",
                          "total_haulage_cost": fields.get("total", ""),
                          "work_quantity": fields.get("qty", ""),
                          "description": fields.get("desc", "")})
        elif kind == "subcontract":
            lines.append({"kind": "subcontract",
                          "amount_per_unit": fields.get("amount", ""),
                          "description": fields.get("desc", ""),
                          "provisional": fields.get("provisional", "no")})
        elif kind == "other":
            lines.append({"kind": "other",
                          "amount_per_unit": fields.get("amount", ""),
                          "description": fields.get("desc", "")})
        else:
            raise ValidationError(
                f"Rate line {lineno}: unknown kind {parts[0]!r}; expected "
                f"material, labour, logistics, subcontract, or other")
    return lines


def parse_markup_lines(text: str):
    """Parse 'label: pct' markup lines (blanks and '#' skipped)."""
    from qs_engine.core.errors import ValidationError
    markups = []
    for lineno, raw in enumerate(str(text or "").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise ValidationError(
                f"Markup line {lineno}: expected 'label: pct', "
                f"got {stripped!r}")
        label, _, pct = stripped.partition(":")
        markups.append((label.strip(), pct.strip()))
    return markups


def parse_rebar_lines(text: str):
    """Parse a rebar schedule editor into controller line mappings.

    One bar line per row:
        Y12 | count=10 | len=6 | laps=2 | lap=1.0 | hooks=0.3 | mass=2
    Only bar_key is mandatory here; missing numerics surface as engine
    validation messages downstream.
    """
    from qs_engine.core.errors import ValidationError
    lines = []
    for lineno, raw in enumerate(str(text or "").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = [part.strip() for part in stripped.split("|")]
        if not parts[0]:
            raise ValidationError(
                f"Rebar line {lineno}: bar key (e.g. Y12) is required")
        fields = {"bar_key": parts[0]}
        names = {"count": "count", "len": "length_per_bar_m",
                 "laps": "laps_per_bar", "lap": "lap_length_m",
                 "hooks": "hook_extra_per_bar_m", "mass": "mass_kg_per_m",
                 "diameter": "diameter_mm", "density": "steel_density_kg_per_m3"}
        for part in parts[1:]:
            if "=" not in part:
                raise ValidationError(
                    f"Rebar line {lineno}: expected key=value, "
                    f"got {part!r}")
            key, _, value = part.partition("=")
            key = key.strip().lower()
            if key not in names:
                raise ValidationError(
                    f"Rebar line {lineno}: unknown field {key!r}")
            fields[names[key]] = value.strip()
        lines.append(fields)
    return lines


def label_column_width(fields) -> int:
    """Widest field label, floored at 24 chars (headless-testable).

    Prevents long labels (e.g. finishes Kind) truncating in fixed-width
    label columns.
    """
    return max([24] + [len(label) for _, label in fields])


#: Standard concrete grade display names. The grade dropdown only offers
#: grades present in the concrete_classes master table (C35/C40 join
#: automatically once verified into master data) so every selection maps
#: directly to a table key.
STANDARD_CONCRETE_GRADES = ("C15", "C20", "C25", "C30", "C35", "C40")


def concrete_grade_choices(repository=None) -> tuple:
    """Grade display names present in the concrete_classes table."""
    if repository is None:
        return STANDARD_CONCRETE_GRADES
    try:
        names = [str(rec.get("class_name", "") or "")
                 for rec in repository.list("concrete_classes")]
    except Exception:
        return STANDARD_CONCRETE_GRADES
    ordered = tuple(grade for grade in STANDARD_CONCRETE_GRADES
                    if grade in names)
    return ordered or STANDARD_CONCRETE_GRADES


def resolve_concrete_class_key(text, repository=None) -> str:
    """Map a grade display name (C20) to its master-data key (class_c20).

    Verbatim table keys pass through untouched so typed keys keep
    working; unknown text returns verbatim and fails closed in the
    engine with an honest message.
    """
    raw = str(text or "").strip()
    if not raw or repository is None:
        return raw
    try:
        records = repository.list("concrete_classes")
    except Exception:
        return raw
    for record in records:
        if (str(record.get("class_name", "") or "").strip().upper()
                == raw.upper()):
            return str(record.get("key", raw))
    return raw


#: Project Setup engineering-input fields: field -> label. Entries stay
#: blank unless the estimator sets a project-level override; blank
#: means "engine/master default". No universal defaults are baked in —
#: verified values surface from master data with provenance instead.
CONCRETE_DENSITY_FIELDS = (
    ("cement_density_kg_per_m3", "Cement Density (kg/m³)"),
    ("sand_density_kg_per_m3", "Sand Density (kg/m³)"),
    ("aggregate_density_kg_per_m3", "Aggregates Density (kg/m³)"),
)

#: Short display names for density provenance lines.
_DENSITY_SHORT_NAMES = {
    "cement_density_kg_per_m3": "cement",
    "sand_density_kg_per_m3": "sand",
    "aggregate_density_kg_per_m3": "aggregates",
}


def session_density_overrides(project) -> dict:
    """Non-blank session density overrides as controller override strings.

    Pure mapping only — parsing and engineering stay in the controller
    and engine. Blank entries mean "engine default".
    """
    overrides = {}
    for field, _label in CONCRETE_DENSITY_FIELDS:
        raw = str((project or {}).get(field, "") or "").strip()
        if raw:
            overrides[field] = raw
    return overrides


def session_override_context(project, trade="") -> dict:
    """Live estimator override context for ONE trade's panel.

    The single session-backed channel every take-off panel now shares:
    Concrete previously held this wiring in a private binding
    (``concrete_controller_with_session_densities``); the generic page
    runner accepts an ``override_source`` instead, so Masonry,
    Earthworks, Labour, Plant and Haulage flow through exactly the same
    path.

    Contexts are trade-scoped so an override written for one trade can
    never leak into another: Concrete reads Project Setup dry-density
    overrides, every other trade currently resolves to an empty context
    (the channel is wired and live; it fills in as the session grows
    fields for that trade). Controllers additionally ignore keys outside
    their own override field set — defence in depth, never a guess.
    """
    if str(trade) == "concrete":
        return session_density_overrides(project)
    return {}


def resolve_override_source(source) -> dict:
    """Resolve an ``override_source`` (mapping or zero-arg callable).

    Returns the override dict to pass to the controller binding; an
    absent source resolves to an empty dict. The mapping is copied so a
    caller's context can never be mutated by a binding.
    """
    if callable(source):
        source = source()
    if source is None:
        return {}
    return dict(source)


def master_density_reference(repository=None) -> dict:
    """Master-data dry densities: field -> (value, verified).

    A value counts as verified only when a concrete_classes record
    carries a non-null density with VERIFIED status. Shipped tables
    hold nulls, so every field reports (None, False) until engineering
    verifies real values — the UI then shows blank plus a
    "Needs Verification" indicator instead of invented numbers.
    """
    reference = {field: (None, False)
                 for field, _label in CONCRETE_DENSITY_FIELDS}
    if repository is None:
        return reference
    try:
        records = repository.list("concrete_classes")
    except Exception:
        return reference
    for record in records:
        if str(record.get("verification_status", "") or "") != "VERIFIED":
            continue
        for field in reference:
            value = record.get(field)
            if value is not None and reference[field] == (None, False):
                reference[field] = (str(value), True)
    return reference


def density_field_status(field, project_value, repository=None) -> str:
    """One-line provenance indicator for an engineering-input row."""
    if str(project_value or "").strip():
        return f"Project override: {str(project_value).strip()}"
    value, verified = master_density_reference(repository).get(
        field, (None, False))
    if verified:
        return f"Master verified: {value}"
    return "\u26a0 Needs Verification"


def nominal_mix_reference(class_key, repository=None):
    """Nominal mix reference for a concrete class key, if any.

    Returns (text, True) labelled reference-only when master data
    carries a nominal-mix reference, else None ("Not available").
    Ratios are never inferred here — only displayed when present.
    """
    raw = str(class_key or "").strip()
    if not raw or repository is None:
        return None
    try:
        records = repository.list("concrete_classes")
    except Exception:
        return None
    for record in records:
        if raw not in (str(record.get("key", "") or ""),
                       str(record.get("class_name", "") or "")):
            continue
        for candidate in ("nominal_mix", "nominal_ratio",
                          "mix_reference", "reference_mix"):
            value = record.get(candidate)
            if value not in (None, ""):
                return (str(value).strip(), True)
    return None


def concrete_supplement_lines(class_key, project, repository=None) -> list:
    """Read-only engineering reference lines for the concrete page.

    Nominal mix plus per-constituent dry-density provenance (project
    override, master verified, or needs-verification). Display only —
    nothing here feeds the calculation.
    """
    lines = []
    reference = nominal_mix_reference(class_key, repository)
    if reference is None:
        lines.append("Nominal Mix Reference: Not available")
    else:
        lines.append(f"Nominal Mix Reference: {reference[0]} "
                     f"(\u26a0 Reference Only)")
    master = master_density_reference(repository)
    parts = []
    for field, _label in CONCRETE_DENSITY_FIELDS:
        short = _DENSITY_SHORT_NAMES[field]
        project_value = str((project or {}).get(field, "") or "").strip()
        if project_value:
            parts.append(f"{short} {project_value} (project override)")
            continue
        value, verified = master.get(field, (None, False))
        if verified:
            parts.append(f"{short} {value} (master verified)")
        else:
            parts.append(f"{short} \u2014 (\u26a0 Needs Verification)")
    lines.append("Dry densities (kg/m\u00b3): " + "; ".join(parts))
    return lines


def concrete_controller_with_session_densities(app):
    """Concrete binding reading Project Setup density overrides live.

    Densities are read from the session at click time, so edits on the
    Project Setup page apply to the next calculation without an
    app restart (live override capability).
    """
    def bound(inputs, repository):
        return controllers.concrete_controller(
            inputs, repository,
            overrides=session_density_overrides(app.session.project))
    return bound


#: Fallback bar sizes when the rebar_bars table is unreachable.
STANDARD_REBAR_BARS = ("Y8", "Y10", "Y12", "Y16", "Y20", "Y25", "Y32")


def rebar_bar_sizes(repository=None) -> tuple:
    """Bar keys present in the rebar_bars master table."""
    if repository is None:
        return STANDARD_REBAR_BARS
    try:
        keys = tuple(str(rec.get("key", "") or "")
                     for rec in repository.list("rebar_bars"))
    except Exception:
        return STANDARD_REBAR_BARS
    return keys or STANDARD_REBAR_BARS


#: Structured rebar BBS grid columns: field -> heading (units explicit).
#: The simplified grid folds laps into a Lap/Bend Extra length addition
#: (Total Length = Cut Length + Extra); the full laps/lap/hooks grammar
#: stays available through Advanced Input. Engine contract note:
#: Hooks/Bends is a length addition per bar — never a count.
REBAR_GRID_COLUMNS = (
    ("member", "Member / Location"),
    ("mark", "Bar Mark"),
    ("grade", "Steel Grade"),
    ("size", "Diameter (mm)"),
    ("bar", "Designation"),
    ("members", "No. of Members"),
    ("bars", "Bars / Member"),
    ("length", "Cut Length (m)"),
    ("extra", "Lap/Bend Extra (m)"),
    ("mass", "Unit Mass (kg/m)"),
    ("weight", "Weight (kg)"),
)

#: Steel grade prefixes (BS 8666 / Eurocode designations). Custom
#: leaves the Designation cell for manual entry.
REBAR_STEEL_GRADES = ("H (500 MPa)", "Y (460 MPa)", "R (250 MPa)",
                      "B (Mesh)", "Custom")
REBAR_GRADE_PREFIXES = {"H (500 MPa)": "H", "Y (460 MPa)": "Y",
                        "R (250 MPa)": "R", "B (Mesh)": "B",
                        "Custom": ""}
#: Diameter options driving the composed designation (mm, integers).
#: Unit mass is NEVER derived here — the engine resolves it from an
#: explicit estimator entry, a verified table value, or the nominal
#: formula with an explicitly supplied steel density.
REBAR_BAR_SIZES_MM = ("8", "10", "12", "16", "20", "25", "32", "40")


def rebar_designation(grade, size_mm) -> str:
    """Compose a bar designation from grade + diameter (display input).

    "H (500 MPa)" + "12" -> "H12". The Custom grade yields "" so the
    estimator types the designation manually into Designation.
    """
    prefix = REBAR_GRADE_PREFIXES.get(str(grade or ""), "")
    size = str(size_mm or "").strip()
    if not prefix or not size:
        return ""
    return f"{prefix}{size}"


def _plain_decimal(value) -> str:
    """Display string without trailing zeros or exponents."""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def rebar_row_totals(members, bars, length, extra, mass):
    """Display-only BBS row totals: (bars, length, weight) strings.

    Total Bars = members x bars; Total Length = cut + extra;
    Weight = bars x length x mass. Returns "" fields for blank or
    invalid input — never invented zeros (members defaults to 1 per
    the grid default).
    """
    from decimal import Decimal, InvalidOperation
    try:
        members_text = str(members or "").strip() or "1"
        bars_value = Decimal(str(bars or "").strip())
        total_bars = Decimal(members_text) * bars_value
        length_value = Decimal(str(length or "").strip())
        extra_text = str(extra or "").strip()
        extra_value = Decimal(extra_text) if extra_text else Decimal("0")
        total_length = length_value + extra_value
        mass_value = Decimal(str(mass or "").strip())
    except InvalidOperation:
        return ("", "", "")
    return (_plain_decimal(total_bars), _plain_decimal(total_length),
            _plain_decimal(total_bars * total_length * mass_value))


def rebar_row_inputs_to_dsl(values) -> list:
    """BBS row strings -> DSL lines (comment + bar line); [] if blank.

    Member/mark annotations travel as # comments: the bar grammar has
    no description field. Unknown designations pass through verbatim
    for fail-closed engine validation.
    """
    member = str(values.get("member", "") or "").strip()
    mark = str(values.get("mark", "") or "").strip()
    bar = str(values.get("bar", "") or "").strip()
    if not bar and not any(str(values.get(field, "") or "").strip()
                           for field in ("bars", "length", "extra",
                                         "mass")):
        return []
    total_bars, total_length, _weight = rebar_row_totals(
        values.get("members"), values.get("bars"), values.get("length"),
        values.get("extra"), values.get("mass"))
    lines = []
    comment = " / ".join(part for part in (member, mark) if part)
    if comment:
        lines.append(f"# {comment}")
    lines.append(format_rebar_line({
        "bar": bar, "count": total_bars, "length": total_length,
        "laps": "", "lap": "", "hooks": "",
        "mass": str(values.get("mass", "") or "").strip()}))
    return lines


def format_rebar_line(entry) -> str:
    """Serialize one grid row into the exact bar input syntax consumed
    by parse_rebar_lines().

    Blank numerics are omitted (the parser leaves them for honest engine
    validation downstream); the bar size is always emitted so a missing
    bar fails closed with the parser's own message.
    """
    from qs_engine.core.errors import ValidationError
    if not isinstance(entry, dict):
        raise ValidationError(
            "Rebar grid row must be a mapping; "
            f"got {type(entry).__name__}")
    parts = [str(entry.get("bar", "") or "").strip()]
    for field, dsl in (("count", "count"), ("length", "len"),
                       ("laps", "laps"), ("lap", "lap"),
                       ("hooks", "hooks"), ("mass", "mass")):
        raw = str(entry.get(field, "") or "").strip()
        if raw:
            parts.append(f"{dsl}={raw}")
    return " | ".join(parts)


#: Rate Builder kind selector (spec set; logistics/other stay available
#: through the Advanced Input toggle).
RATE_COMPONENT_KINDS = ("material", "labour", "plant", "subcontract")

#: Markup policies accepted by the build-up engine (composite_rate
#: rejects anything else, so the Policy dropdown offers exactly these).
RATE_POLICIES = ("sequential", "parallel")

#: Rate-unit choices: the complete engine-supported unit vocabulary
#: (qs_engine.core.units.SUPPORTED_UNITS), QS-ordered most-common first.
#: Read-only by design — every option is guaranteed engine-valid, so the
#: box can never offer a unit the engine must reject, and no supported
#: unit is left unreachable. The shorthand "t"/"hr"/"nr"/"sum"/"item" is
#: deliberately absent: "tonne"/"hour" are the canonical engine spellings
#: and nr/sum/item do not exist in SUPPORTED_UNITS at all.
RATE_WORK_UNITS = ("m³", "m²", "m", "kg", "tonne", "L", "bag", "piece",
                   "pair", "set", "sheet", "hour", "day",
                   "mm", "cm", "mm²", "mm³")

#: Component-unit suggestions (estimator context only; never parsed).
COMPONENT_UNITS = ("bag", "m³", "m²", "m", "kg", "t", "nr", "day",
                   "hr", "shift", "trip")

#: Provisional flag choices (readonly); "No" serializes to nothing.
PROVISIONAL_CHOICES = ("No", "Yes")

#: Muted colour for every cue (ghost) value. Cue text is always visibly
#: secondary to estimator input and never shares the widget's normal text
#: colour, so unfocused panels carry no misleading solid-black values.
CUE_TEXT_COLOR = "#888888"

#: Compact hint for the rate Element field. Short by policy: cue text is
#: display-only (never serialized — reads go through _entry_text) and must
#: stay narrower than its entry so it can never clip.
ELEMENT_HINT = "e.g., Beam B1"

#: Resource Code cell cue. Deliberately different from the Resource readout
#: hint: the audit found two adjacent cells showing the same ghost text
#: ("Select..."), which never told the estimator which cell wants a code and
#: which one resolves that code into a resource.
RATE_CODE_CUE = "Code / Item ID..."

#: Resource search cue: the picker's search field (it searches code, name
#: and catalogue scope fields, so one honest description covers them all).
PICKER_SEARCH_CUE = "Search catalog description..."

#: Cue text per rate-grid input (display only; never serialized — reads go
#: through _entry_text and writes through _set_entry_value). The Description
#: cell is kind-dependent: see RATE_DESCRIPTION_CUES.
RATE_ROW_PLACEHOLDERS = {
    "key": RATE_CODE_CUE,
    "qty": "1.0",
    "price": "0.00",
    "waste": "5.0",
}

#: Description-cell cue per component kind. The audit's combined example
#: ("20mm Ballast / Class 1 Mason") is split per kind because the cell is
#: 20 characters wide: each cue names the vocabulary that kind's row really
#: accepts, and every cue fits the cell without clipping.
RATE_DESCRIPTION_CUES = {
    "material": "e.g., 20mm Ballast",
    "labour": "e.g., Class 1 Mason",
    "subcontract": "e.g., PC sum",
}

#: Description entry width: the widest per-kind cue plus one character.
#: Unchanged from the pre-cue width so the component grid keeps its exact
#: footprint (no column can be pushed off the viewport).
RATE_DESCRIPTION_WIDTH = max(
    len(hint) for hint in RATE_DESCRIPTION_CUES.values()) + 1


def rate_description_cue(kind) -> str:
    """Description-cell cue for a component kind ("" when none applies).

    Plant rows price through the Plant take-off, so their inputs stay
    disabled and carry no cue — a hint the field cannot accept would lie.
    """
    return RATE_DESCRIPTION_CUES.get(str(kind or "").strip().lower(), "")


def format_rate_line(entry) -> str:
    """Serialize one component row into pipe-delimited input syntax for
    parse_rate_lines().

    Column mapping: key -> material key / plant key; qty -> material
    qty / labour hours / plant qty (ignored for subcontract, whose
    amount is the Unit Rate entry); price -> material price / labour
    rate / plant price / subcontract amount; waste -> material wastage
    % (omitted entirely when blank: the engine then falls back to the
    master record's default_wastage_pct or fails closed — blank is
    never silently serialized as 0); desc -> description. An optional
    "unit" entry (resource measurement unit) is accepted and ignored:
    the parser grammar has no unit field, so serializing it would
    corrupt the contract — output is byte-identical with or without
    it.

    Plant rows emit `plant | ...`, which parse_rate_lines rejects with
    guidance (string plant lines need resolved PlantRequirement
    objects) — the page surfaces that message honestly instead of
    inventing plant pricing in the view layer.
    """
    from qs_engine.core.errors import ValidationError
    if not isinstance(entry, dict):
        raise ValidationError(
            "Rate grid row must be a mapping; "
            f"got {type(entry).__name__}")
    kind = str(entry.get("kind", "") or "").strip().lower()
    key = str(entry.get("key", "") or "").strip()
    qty = str(entry.get("qty", "") or "").strip()
    price = str(entry.get("price", "") or "").strip()
    waste = str(entry.get("waste", "") or "").strip()
    desc = str(entry.get("desc", "") or "").strip()
    prov = entry.get("provisional", False)
    provisional = (prov is True
                   or str(prov or "").strip().lower() == "yes")
    if kind == "material":
        line = f"material | key={key} | qty={qty} | price={price}"
        if waste:
            line += f" | waste={waste}"
    elif kind == "labour":
        line = f"labour | hours={qty} | rate={price}"
    elif kind == "plant":
        line = f"plant | key={key} | qty={qty} | price={price}"
    elif kind == "subcontract":
        line = f"subcontract | amount={price}"
    else:
        raise ValidationError(
            f"Rate grid row has unknown kind {entry.get('kind')!r}; "
            f"expected one of {list(RATE_COMPONENT_KINDS)}")
    if desc:
        line += f" | desc={desc}"
    if provisional and kind == "subcontract":
        line += " | provisional=yes"
    return line


#: Read-only materials catalogue columns. No price column exists by
#: design: prices arrive per call/context and no universal verified
#: price library exists in master data.
MATERIALS_COLUMNS = {
    "code": ("Material Code", 150),
    "name": ("Material Name", 200),
    "category": ("Category", 100),
    "subcategory": ("Subcategory", 110),
    "unit": ("Default Unit", 90),
    "density": ("Density", 110),
    "wastage": ("Wastage Default", 110),
    "status": ("Verification Status", 130),
}

#: Site reconciliation variance grid columns (Phase 6.2).
RECONCILIATION_COLUMNS = {
    "code": ("Material Code", 140),
    "name": ("Material Name", 190),
    "unit": ("Unit", 70),
    "theoretical": ("Theoretical Qty", 110),
    "issued": ("Actual Issued", 100),
    "balance": ("Store Balance", 100),
    "variance": ("Variance Qty", 100),
    "variance_pct": ("Variance %", 90),
    "status": ("Status", 150),
}


def display_material_code(record, policy=None, seed_records=None) -> str:
    """Catalogue code column for one record.

    User rows show the user's editable material code — the canonical
    ``user:<stable-id>`` key stays on the record and remains what the
    engines resolve, so renaming a code can never move a material's
    identity. Un-customized seed rows show the structured code from the
    active MaterialCodePolicy when one is supplied (``quarry_dust`` ->
    ``AGG-002``); without a policy the canonical key is shown exactly as
    before.
    """
    key = str(record.get("key", "") or "")
    if key.startswith("user:"):
        return str(record.get("code", "") or key)
    if policy is not None:
        return policy.resolve_display_code(record,
                                           seed_records=seed_records)
    return key


def _catalogue_row(record, policy=None, seed_records=None) -> tuple:
    """One catalogue grid row (em-dash for nulls; never invented)."""
    density = record.get("density")
    density_unit = str(record.get("density_unit", "") or "").strip()
    wastage = record.get("default_wastage_pct")
    return (
        display_material_code(record, policy=policy,
                              seed_records=seed_records),
        str(record.get("name", "") or record.get("key", "") or ""),
        str(record.get("category_name")
            or record.get("category", "") or "—"),
        str(record.get("subcategory", "") or "—"),
        str(record.get("unit", "") or "—"),
        (f"{density} {density_unit}".strip() if density is not None
         else "—"),
        (str(wastage) if wastage is not None else "—"),
        str(record.get("verification_status", "") or "—"),
    )


def material_catalogue_rows(repository, policy=None) -> list:
    """Master-data material rows for the read-only catalogue grid.

    Density and wastage show an em-dash where master data holds nulls
    (null-numeric rule) — never invented values. Pricing flows through
    the Rate Builder per call/context. When a MaterialCodePolicy is
    supplied, un-customized seed rows render its structured display
    code instead of the raw seed slug; user rows always render the
    user's editable code.
    """
    records = list(repository.list("materials"))
    seed_records = None
    if policy is not None:
        seed_records = [record for record in records
                        if not str(record.get("key", "")).startswith("user:")]
    return [_catalogue_row(record, policy=policy, seed_records=seed_records)
            for record in records]


def material_details_text(record) -> str:
    """Multi-line read-only readout for one material record."""
    density = record.get("density")
    density_unit = str(record.get("density_unit", "") or "").strip()
    wastage = record.get("default_wastage_pct")
    return "\n".join([
        f"Name: {record.get('name', '') or record.get('key', '')}",
        f"Code: {display_material_code(record)}",
        f"Category: {record.get('category_name') or record.get('category', '') or '—'}",
        f"Default Unit: {record.get('unit', '') or '—'}",
        "Density: " + (f"{density} {density_unit}".strip()
                       if density is not None
                       else "— (unverified)"),
        "Wastage Default: " + (str(wastage)
                               if wastage is not None
                               else "— (unverified)"),
        f"Verification: {record.get('verification_status', '') or '—'}",
        f"GL Account: {gl_display_label(record)}",
        f"Account Type: {gl_account_type_display(record)}",
    ])


def _search_norm(text) -> str:
    """Case/underscore/punctuation-insensitive search folding."""
    out = str(text or "").lower()
    for char in ("_", " ", ".", "-", "/"):
        out = out.replace(char, "")
    return out


#: Optional GL/financial record fields honored when present.
#: The shipped catalogue supplies category_prefix, gl_code,
#: gl_account_name, gl_account_type and legacy_code on every record
#: (reconciled against GL_ACCOUNTS by the test suite); records
#: without them still render and search exactly as before — never
#: invented, never required.
GL_OPTIONAL_FIELDS = ("category_prefix", "gl_code", "gl_account_name")


def _record_matches(record, needle, fields) -> bool:
    """Folded substring match of one record over the given fields."""
    return any(needle in _search_norm(record.get(field, ""))
               for field in fields)


def _all_scope_fields(record, base_fields) -> list:
    """All-scope fields plus any GL/financial fields actually present."""
    fields = list(base_fields)
    for field in GL_OPTIONAL_FIELDS:
        if (field not in fields
                and str(record.get(field, "") or "").strip()):
            fields.append(field)
    return fields


def search_records(records, query, fields) -> list:
    """Case-insensitive substring match over folded record fields.

    "cement" finds Portland Cement; "portland_cement_42_5" finds
    "Portland Cement 42.5". Empty query returns every record.
    """
    needle = _search_norm(query)
    if not needle:
        return list(records)
    fields = tuple(fields)
    return [record for record in records
            if _record_matches(record, needle, fields)]


#: Catalogue search scopes: label -> record fields searched. There is
#: no subcategory field in master data, so Category is the finest cut.
MATERIAL_SEARCH_SCOPES = (
    ("All", ("key", "name", "category")),
    ("Code", ("key",)),
    ("Name", ("name",)),
    ("Category", ("category",)),
)

#: Catalogue verification filter options (master-data statuses).
MATERIAL_STATUSES = ("All", "VERIFIED", "NEEDS_VERIFICATION",
                     "PROVISIONAL")


def filter_catalogue(records, query="", scope="All", status="All"):
    """Search + verification filter over material records (pure).

    The All scope additionally matches any GL/financial fields a
    record actually carries (category_prefix, gl_code,
    gl_account_name); scoped searches stay strict.
    """
    if scope == "All":
        needle = _search_norm(query)
        if not needle:
            matches = list(records)
        else:
            base = dict(MATERIAL_SEARCH_SCOPES)["All"]
            matches = [record for record in records
                       if _record_matches(
                           record, needle,
                           _all_scope_fields(record, base))]
    else:
        fields = dict(MATERIAL_SEARCH_SCOPES).get(
            scope, dict(MATERIAL_SEARCH_SCOPES)["All"])
        matches = search_records(records, query, fields)
    if status != "All":
        matches = [record for record in matches
                   if str(record.get("verification_status", "")) == status]
    return matches


def gl_display_label(record) -> str:
    """'[GL_CODE] - [GL_ACCOUNT_NAME]' when both present, else em-dash.

    Never invents: without source GL fields there is no GL label.
    """
    code = str(record.get("gl_code", "") or "").strip()
    name = str(record.get("gl_account_name", "") or "").strip()
    if code and name:
        return f"{code} - {name}"
    return "—"


def gl_account_type_display(record) -> str:
    """Financial account type when supplied, else em-dash."""
    return str(record.get("gl_account_type", "") or "").strip() or "—"


#: Authoritative enterprise GL account lookup (single source of truth).
#: Selecting an account name binds its category prefix, GL code and
#: account type; the material code then derives dynamically as
#: "[PREFIX]-[GL_CODE]-[ITEM_ID]". Shipped master data mirrors this
#: table exactly (reconciled by the test suite).
GL_ACCOUNTS = {
    "Cement & Binders": ("CEM", "10175", "Inventory (Asset)"),
    "Aggregates": ("AGG", "10176", "Inventory (Asset)"),
    "Quarry Products": ("QRY", "10138", "Inventory (Asset)"),
    "Precast & Concrete Products": ("PRC", "10183", "Inventory (Asset)"),
    "General Hardware & Fixing": ("HRD", "10131", "Inventory (Asset)"),
    "Scaffolding & Formwork": ("SCF", "10130", "Inventory (Asset)"),
    "Painting & Coating": ("PNT", "10186", "Inventory (Asset)"),
    "Adhesives & Construction Chemicals": ("CHM", "10188",
                                           "Inventory (Asset)"),
    "Wall & Ceiling Systems": ("WCS", "10185", "Inventory (Asset)"),
    "Waterproofing & Sealants": ("WPF", "10187", "Inventory (Asset)"),
    "Site Utilities - Water": ("WSU", "50066", "Direct Cost / Expense"),
}

#: Account-selection choices for editor comboboxes (stable order).
GL_ACCOUNT_CHOICES = tuple(GL_ACCOUNTS)


def resolve_gl_account(account_name):
    """(category_prefix, gl_code, gl_account_type) for an account name.

    None when the name is unknown or blank — GL state is looked up
    from the authoritative table, never invented.
    """
    return GL_ACCOUNTS.get(str(account_name or "").strip())


def derive_material_code(account_name, item_id):
    """'[PREFIX]-[GL_CODE]-[ITEM_ID]' driven by the account selection.

    Empty string when the account is unknown or the item id is blank:
    a material code is only ever derived, never guessed.
    """
    resolved = resolve_gl_account(account_name)
    item = str(item_id or "").strip()
    if resolved is None or not item:
        return ""
    prefix, gl_code, _account_type = resolved
    return f"{prefix}-{gl_code}-{item}"


def material_code_preview(label, custom_prefix, template, sequence_padding,
                          separator) -> str:
    """Live-preview text for the Material Coding Configuration panel.

    Evaluates the SAME MaterialCodePolicy generation path the rest of
    the application uses for real codes (sample category ``aggregate``,
    sequence 1), so the preview can never diverge from what would
    actually be written.

    Failures are always visible, never plausible: a template with an
    unsupported or malformed token renders ``(invalid template)`` —
    never an apparently valid code still containing the raw token —
    an unset Custom Prefix renders its own hint, and the Manual policy
    reports ``(manual entry)`` without inventing a code.
    """
    from qs_engine.core.errors import ValidationError
    from qs_engine.resources.code_policy import (
        CUSTOM_PREFIX,
        DEFAULT_PADDING,
        MANUAL,
        MaterialCodePolicy,
        mode_from_label,
    )

    padding = sequence_padding if isinstance(sequence_padding, int) \
        else DEFAULT_PADDING
    try:
        mode = mode_from_label(label)
        if mode == CUSTOM_PREFIX and not str(custom_prefix or "").strip():
            return "(enter a custom prefix)"
        policy = MaterialCodePolicy.parse(
            mode,
            custom_prefix,
            format_template=str(template or "").strip() or None,
            sequence_padding=padding,
            separator=separator or None,
        )
        code = policy.suggest("Preview Material", category="aggregate")
    except ValidationError:
        return "(invalid template)"
    if not code:
        return "(manual entry)" if policy.mode == MANUAL \
            else "(invalid template)"
    if "{" in code or "}" in code:
        # An unsupported token survived substitution: show the failure
        # instead of an apparently valid code.
        return "(invalid template)"
    return code


def gl_fields_for_selection(account_name, item_id="") -> dict:
    """Display-ready GL state for one account selection (pure).

    Keys mirror the editor readouts: category_prefix, gl_code,
    gl_account_type and the derived code. Unknown selections show
    em-dashes; a blank item id withholds the code (em-dash) while the
    account fields still resolve.
    """
    resolved = resolve_gl_account(account_name)
    if resolved is None:
        return {"category_prefix": "—", "gl_code": "—",
                "gl_account_type": "—", "code": "—"}
    prefix, gl_code, account_type = resolved
    return {"category_prefix": prefix, "gl_code": gl_code,
            "gl_account_type": account_type,
            "code": derive_material_code(account_name, item_id) or "—"}


def apply_gl_account_selection(widgets) -> dict:
    """UI wiring: account combo change re-resolves every GL readout.

    widgets: 'gl_account_name' (source combobox), 'item_id' (entry)
    and the readouts 'category_prefix', 'gl_code', 'gl_account_type'
    and 'code'. Bind to <<ComboboxSelected>> (plus item-id changes)
    so selecting or changing the account dynamically looks up the GL
    parameters and regenerates the material code. Returns the fields
    that were applied.
    """
    fields = gl_fields_for_selection(
        widgets["gl_account_name"].get(), widgets["item_id"].get())
    for field, text in fields.items():
        _set_readout(widgets[field], text)
    return fields


def resolve_material_record(key_or_legacy, repository):
    """Record by modern code or legacy_code; None when unknown.

    Forward-compatible lookup for enterprise-renumbered catalogues:
    today's keys resolve directly; a future table carrying
    legacy_code keeps saved rate items and .clk files valid.
    """
    key = str(key_or_legacy or "").strip()
    if not key:
        return None
    try:
        return repository.get("materials", key)
    except Exception:
        pass
    try:
        records = repository.list("materials")
    except Exception:
        return None
    for record in records:
        if str(record.get("legacy_code", "") or "") == key:
            return record
    return None


#: Rate-grid per-kind field policy. Mirrors the parser grammar exactly:
#: material validates its key; labour is direct hours x rate (no trade
#: key exists in the grammar); grid plant rows cannot price (resolved
#: PlantRequirement objects only - priced on the Plant take-off page);
#: subcontract needs amount + description, provisional optional.
RATE_ROW_FIELDS = {
    "material": {"enabled": ("key", "qty", "unit", "price", "waste",
                             "desc"),
                 "picker": "materials"},
    "labour": {"enabled": ("qty", "unit", "price", "desc"),
               "picker": "labour"},
    "plant": {"enabled": (),
              "picker": None},
    "subcontract": {"enabled": ("price", "desc", "prov"),
                    "picker": None},
}


def rate_row_field_states(kind) -> dict:
    """Enabled inputs + picker domain for a rate kind (headless-safe)."""
    return dict(RATE_ROW_FIELDS.get(
        str(kind or "").strip().lower(),
        RATE_ROW_FIELDS["material"]))


def _lookup_material_record(key, records, policy):
    """Material record for one reference: identity, then display code.

    Identity (canonical key, legacy code) always wins; only an
    unresolved reference falls back to the policy's display code.
    """
    for record in records:
        if (str(record.get("key", "") or "") == key
                or str(record.get("legacy_code", "") or "") == key):
            return record
    if policy is None:
        return None
    seed_records = [record for record in records
                    if not str(record.get("key", "")).startswith("user:")]
    needle = key.casefold()
    for record in seed_records:
        if policy.resolve_display_code(
                record, seed_records=seed_records).casefold() == needle:
            return record
    return None


def resource_display_name(domain, key, repository, policy=None):
    """(display name, unit context) for a resource key.

    Unknown keys report an explicit warning (they fail closed at
    Build); blank keys report an em-dash. No values invented. For
    materials, a reference that is not an identity falls back to the
    active MaterialCodePolicy's display code, so a catalogue display
    code resolves to the same record it names.
    """
    key = str(key or "").strip()
    if not key:
        return ("—", "")
    try:
        records = repository.list(domain)
    except Exception:
        return ("—", "")
    if domain == "materials":
        record = _lookup_material_record(key, records, policy)
        if record is not None:
            return (str(record.get("name", "") or key),
                    str(record.get("unit", "") or ""))
        return ("⚠ unknown key", "")
    for record in records:
        if (str(record.get("key", "") or "") != key
                and str(record.get("legacy_code", "") or "") != key):
            continue
        if domain == "labour":
            return (str(record.get("trade", "") or key),
                    str(record.get("work_unit", "") or ""))
        if domain == "plant":
            return (str(record.get("equipment", "") or key),
                    str(record.get("work_unit", "")
                         or record.get("rate_unit", "") or ""))
    return ("⚠ unknown key", "")


def apply_kind_states(widgets):
    """Enable only the inputs the parser grammar consumes per kind."""
    kind = widgets["kind"].get().strip().lower()
    enabled = set(rate_row_field_states(kind)["enabled"])
    for field in ("key", "qty", "unit", "price", "waste", "desc",
                  "prov"):
        widgets[field].config(
            state="normal" if field in enabled else "disabled")
    picker = rate_row_field_states(kind)["picker"]
    widgets["pick"].config(state="normal" if picker else "disabled")


def make_picker_button(parent, command):
    """Standard clean, square lookup button placed beside its input field.

    Single source of truth for the resource-picker trigger so every panel
    renders an identical icon button (same glyph, width, style, centering)
    instead of ad-hoc text buttons. Unicode glyph by design — see
    PICKER_ICON: stdlib tkinter/ttk only, no image asset loader.
    """
    return ttk.Button(parent, text=PICKER_ICON, width=2,
                      style=PICKER_BUTTON_STYLE, command=command)


def _set_readout(widget, text):
    """Write a disabled readout entry (programmatic pass-through)."""
    widget.config(state="normal")
    widget.delete(0, "end")
    widget.insert(0, text)
    widget.config(state="disabled")


def _raw_widget_text(entry):
    """Text exactly as displayed (never through a cue-safe getter)."""
    reader = getattr(entry, "display_text", None)
    if reader is not None:
        return reader()
    return entry.get()


def _placeholder_showing(entry):
    """True only while the widget truly displays its cue text.

    A cue flag goes stale whenever real input arrives without a focus event
    (a dropdown pick, a programmatic write). That case retires the flag, so a
    genuine value can never be mistaken for — or deleted as — a cue.
    """
    if not getattr(entry, "_placeholder_active", False):
        return False
    if _raw_widget_text(entry) == getattr(entry, "_placeholder_text", ""):
        return True
    entry._placeholder_active = False
    return False


def _write_widget_text(entry, text):
    """Replace an entry's text, lifting a disabled/readonly state to do it.

    ttk ignores programmatic text edits while a widget is disabled or
    read-only, so a cue written (or cleared) without this dance can survive
    as a stale ghost value on a disabled cell. The prior state is always
    restored, so cue handling can never unlock an input.
    """
    try:
        state = str(entry.cget("state"))
    except tk.TclError:
        state = "normal"
    locked = state in ("disabled", "readonly")
    if locked:
        entry.config(state="normal")
    entry.delete(0, "end")
    if text:
        entry.insert(0, text)
    if locked:
        entry.config(state=state)


def _show_placeholder(entry, text):
    """Muted cue text for an empty entry (display only, never data)."""
    _write_widget_text(entry, text)
    try:
        entry.config(foreground=CUE_TEXT_COLOR)
    except tk.TclError:
        pass
    entry._placeholder_text = text
    entry._placeholder_active = True


def _clear_placeholder(entry):
    """Drop the cue, restoring normal text colour for real input.

    Only a cue that is still displayed is deleted; a value that arrived
    while the cue was showing keeps its text and just gets its colour back.
    The flag is retired before the text write so a cue-aware widget's own
    insert/delete guard can never re-enter this function.
    """
    if not getattr(entry, "_placeholder_active", False):
        return
    showing = _placeholder_showing(entry)
    entry._placeholder_active = False
    if showing:
        _write_widget_text(entry, "")
    try:
        entry.config(foreground=entry._placeholder_fg)
    except (tk.TclError, AttributeError):
        pass


def _wire_placeholder(entry, text):
    """Muted cue until real input; safe for typed + programmatic use.

    Clears on focus, restores on blur when still empty. Read the value only
    through CueEntry.get_value() / _entry_text and write only through
    CueEntry.set_value() / _set_entry_value so cue text can never leak into
    calculations. Wiring is idempotent: an already-wired widget only has its
    cue text retargeted (CueEntry.set_cue relies on this), so focus handlers
    can never stack up however often a row or kind is switched.
    """
    if not getattr(entry, "_placeholder_bound", False):
        try:
            entry._placeholder_fg = entry.cget("foreground")
        except tk.TclError:
            entry._placeholder_fg = "black"
        entry.bind("<FocusIn>",
                   lambda _event, widget=entry: _clear_placeholder(widget),
                   add="+")
        entry.bind("<FocusOut>",
                   lambda _event, widget=entry: _restore_placeholder(widget),
                   add="+")
        entry._placeholder_bound = True
    _show_placeholder(entry, text)


def _restore_placeholder(entry):
    """Re-show the cue when the entry was left empty."""
    _clear_placeholder(entry)  # retires a stale flag, fixes the text colour
    text = getattr(entry, "_placeholder_text", "")
    if text and not _raw_widget_text(entry).strip():
        _show_placeholder(entry, text)


def _entry_text(entry):
    """User value; an active cue reads as blank (never data).

    Cue widgets answer through their own safe getter; plain ttk widgets
    answer through the shared cue attribute contract, so both read the
    same way at every call site.
    """
    get_value = getattr(entry, "get_value", None)
    if get_value is not None:
        return get_value()
    if getattr(entry, "_placeholder_active", False):
        return ""
    return entry.get().strip()


def _set_entry_value(entry, text):
    """Programmatic write that first clears any cue."""
    _clear_placeholder(entry)
    _write_widget_text(entry, text)


class _CueMixin:
    """Muted example text (a "cue") for ttk input widgets.

    Single implementation of the cue contract shared by CueEntry and
    CueCombobox, built on the module-level helpers above so plain ttk
    widgets and cue widgets never drift apart:

    * ``<FocusIn>`` clears an active cue (and only a cue — typed text is
      never touched) and restores the widget's normal text colour;
    * ``<FocusOut>`` restores the cue only while the field is still blank
      (whitespace-only counts as blank);
    * ``get()`` and ``get_value()`` return ``""`` while the cue is showing,
      so ghost text can never be read as estimator input;
    * ``set_value()`` clears the cue first and re-arms it when the
      programmatic write is blank;
    * a raw ``insert()`` (a real write) drops any active cue first, so
      programmatic callers can never end up with cue text glued to data.

    Owners that need to re-run work after the text changes (a search field
    filtering a list) assign ``on_text_changed``: it fires for every
    programmatic edit this widget performs — ``insert``, ``delete``,
    ``set_value``, ``set`` — as well as for the cue writes cue handling
    itself makes. User keystrokes are reported to the owner by the widget's
    normal Tk events, so no mirrored StringVar is needed; the widget text
    stays the single source of truth.
    """

    #: Optional zero-arg callback invoked after a text edit this widget made.
    on_text_changed = None

    def _notify_text_changed(self):
        """Tell the owner that a programmatic edit landed, if it cares."""
        callback = self.on_text_changed
        if callable(callback):
            callback()

    def _init_cue(self, cue=""):
        """Wire focus handling once and display the opening cue."""
        if str(cue or "").strip():
            _wire_placeholder(self, cue)

    def get_value(self):
        """Safe form getter: user text only, an active cue reads as blank."""
        if getattr(self, "_placeholder_active", False):
            return ""
        return super().get().strip()

    def set_value(self, text):
        """Programmatic write: cue cleared first, re-shown when blank."""
        value = "" if text is None else str(text)
        _set_entry_value(self, value)
        if not value.strip():
            self.show_cue()

    def display_text(self):
        """Exactly what the widget shows, cue included (display only)."""
        return super().get()

    def show_cue(self):
        """Display this widget's cue (no-op when it has none)."""
        if getattr(self, "_placeholder_text", ""):
            _show_placeholder(self, self._placeholder_text)

    def hide_cue(self):
        """Drop an active cue and restore the normal text colour."""
        _clear_placeholder(self)

    def set_cue(self, text):
        """Retarget the cue text; an empty value removes the cue entirely."""
        text = str(text or "")
        if text:
            _wire_placeholder(self, text)
        else:
            self.hide_cue()
            self._placeholder_text = ""

    def get(self):
        """Widget text; while a cue is showing the field reads as blank."""
        if getattr(self, "_placeholder_active", False):
            return ""
        return super().get()

    def insert(self, index, text):
        """Raw insert is real input: any active cue is dropped first."""
        if getattr(self, "_placeholder_active", False):
            _clear_placeholder(self)
        result = super().insert(index, text)
        self._notify_text_changed()
        return result

    def delete(self, first, last=None):
        """Raw delete is real input: any active cue is dropped first."""
        if getattr(self, "_placeholder_active", False):
            _clear_placeholder(self)
        result = super().delete(first, last)
        self._notify_text_changed()
        return result


class CueEntry(_CueMixin, ttk.Entry):
    """ttk.Entry whose muted example cue can never be read as data.

    Usage: ``CueEntry(parent, cue="e.g., Ground Floor Slab S1")``. Load
    stored values with ``set_value()`` and read submitted values with
    ``get()``/``get_value()``; both are cue-safe, so a form can go straight
    from widget to controller payload without a scrubbing step.
    """

    def __init__(self, parent=None, cue="", **kwargs):
        ttk.Entry.__init__(self, parent, **kwargs)
        self._init_cue(cue)


class CueCombobox(_CueMixin, ttk.Combobox):
    """Editable ttk.Combobox with the same cue contract as CueEntry.

    A dropdown pick (``<<ComboboxSelected>>``) is real input and drops the
    cue; ``set()`` and ``set_value()`` clear it too and re-arm it only when
    the write is blank.
    """

    def __init__(self, parent=None, cue="", **kwargs):
        ttk.Combobox.__init__(self, parent, **kwargs)
        self.bind("<<ComboboxSelected>>", self._cue_pick, add="+")
        self._init_cue(cue)

    def set(self, value):
        """Set a value: cue cleared first, re-shown when the value is blank."""
        self.hide_cue()
        ttk.Combobox.set(self, value)
        if not str(value or "").strip():
            self.show_cue()

    def _cue_pick(self, _event=None):
        """A dropdown pick is real input, so the cue goes away."""
        self.hide_cue()


def refresh_resource_readout(widgets, repository, policy=None):
    """Kind-aware Resource cell text (names, hints, honest warnings)."""
    kind = widgets["kind"].get().strip().lower()
    if kind == "material":
        name, _unit = resource_display_name(
            "materials", _entry_text(widgets["key"]), repository,
            policy=policy)
        _set_readout(widgets["resource"], name)
    elif kind == "labour":
        description = _entry_text(widgets["desc"])
        _set_readout(widgets["resource"],
                     description if description else "Direct hours x rate")
    elif kind == "plant":
        _set_readout(widgets["resource"], "Price via Plant take-off")
    elif kind == "subcontract":
        if not _entry_text(widgets["desc"]):
            _set_readout(widgets["resource"], "⚠ description required")
        elif widgets["prov"].get().strip() == "Yes":
            _set_readout(widgets["resource"], "Provisional sum")
        else:
            _set_readout(widgets["resource"], "—")
    else:
        _set_readout(widgets["resource"], "—")


#: Resource picker search scopes per domain.
PICKER_SCOPES = {
    "materials": (("All", ("key", "name", "category")),
                  ("Code", ("key",)),
                  ("Name", ("name",)),
                  ("Category", ("category",))),
    "labour": (("All", ("key", "trade")),
               ("Code", ("key",)),
               ("Trade", ("trade",))),
    "plant": (("All", ("key", "equipment")),
              ("Code", ("key",)),
              ("Equipment", ("equipment",))),
}

PICKER_TITLES = {"materials": "Select Material",
                 "labour": "Select Labour",
                 "plant": "Select Plant"}


def picker_records(domain, repository):
    """Normalized picker rows: code, name, unit, detail + raw record."""
    rows = []
    try:
        records = repository.list(domain)
    except Exception:
        return rows
    for record in records:
        gl_segment = ""
        gl_label = gl_display_label(record)
        if gl_label != "—":
            gl_segment = f" | GL: {gl_label}"
        if domain == "materials":
            density = record.get("density")
            wastage = record.get("default_wastage_pct")
            rows.append({
                "code": str(record.get("key", "") or ""),
                "name": str(record.get("name", "")
                             or record.get("key", "")),
                "unit": str(record.get("unit", "") or "—"),
                "detail": (
                    f"Category: {record.get('category', '') or '—'} | "
                    "Density: "
                    f"{density if density is not None else '—'} | "
                    "Wastage: "
                    f"{wastage if wastage is not None else '—'} | "
                    "Status: "
                    f"{record.get('verification_status', '') or '—'}"
                    f"{gl_segment}"),
                "record": record})
        elif domain == "labour":
            rows.append({
                "code": str(record.get("key", "") or ""),
                "name": str(record.get("trade", "")
                             or record.get("key", "")),
                "unit": str(record.get("work_unit", "") or "—"),
                "detail": (
                    f"Trade: {record.get('trade', '') or '—'} | "
                    f"Basis: {record.get('work_unit', '') or '—'} | "
                    "Status: "
                    f"{record.get('verification_status', '') or '—'}"
                    f"{gl_segment}"),
                "record": record})
        elif domain == "plant":
            rows.append({
                "code": str(record.get("key", "") or ""),
                "name": str(record.get("equipment", "")
                             or record.get("key", "")),
                "unit": str(record.get("work_unit", "")
                             or record.get("rate_unit", "") or "—"),
                "detail": (
                    f"Basis: {record.get('work_unit', '') or record.get('rate_unit', '') or '—'} | "
                    "Status: "
                    f"{record.get('verification_status', '') or '—'}"
                    f"{gl_segment}"),
                "record": record})
    return rows


def select_resource_dialog(parent, domain, repository, on_select=None):
    """Searchable resource picker (modeless; None when headless).

    Returns the dialog; the chosen raw record dict arrives via
    on_select (Select button or double-click), then the dialog
    closes. Cancel closes without calling back.
    """
    try:
        dialog = tk.Toplevel(
            parent if isinstance(parent, tk.Widget) else None)
    except tk.TclError:
        return None
    dialog.title(PICKER_TITLES.get(domain, "Select Resource"))
    rows = picker_records(domain, repository)
    scopes = PICKER_SCOPES.get(domain, PICKER_SCOPES["materials"])
    scope_fields = {label: fields for label, fields in scopes}
    scope_var = tk.StringVar(master=dialog, value=scopes[0][0])
    toolbar = ttk.Frame(dialog, padding=(10, 10, 10, 0))
    toolbar.pack(fill="x")
    # The search field owns its cue: the query is read through the cue-safe
    # getter, so the example cue can never be mistaken for a filter and an
    # untouched dialog always lists the whole catalogue.
    search_entry = CueEntry(toolbar, width=28, name="resource_search",
                            cue=PICKER_SEARCH_CUE)
    search_entry.pack(side="left")
    ttk.Combobox(toolbar, textvariable=scope_var, state="readonly",
                 values=[label for label, _fields in scopes],
                 width=10).pack(side="left", padx=(6, 0))
    count_label = ttk.Label(toolbar, text="", style="Status.TLabel")
    count_label.pack(side="left", padx=(8, 0))
    grid_frame = ttk.Frame(dialog, padding=10)
    grid_frame.pack(fill="both", expand=True)
    tree = make_grid(grid_frame, {"code": ("Code", 140),
                                  "name": ("Name", 220),
                                  "unit": ("Unit", 80)}, height=8)
    tree.pack(fill="both", expand=True)
    detail_label = ttk.Label(dialog, text="", style="Status.TLabel",
                             wraplength=440, justify="left")
    detail_label.pack(anchor="w", padx=10)
    by_code = {}

    def refresh():
        scope_label = scope_var.get()
        base_fields = dict(scopes)["All"]
        # Cue-safe read: the search field's example cue is not a query, so
        # an untouched dialog lists the whole catalogue.
        needle = _search_norm(_entry_text(search_entry))
        for child in tree.get_children():
            tree.delete(child)
        by_code.clear()
        shown = 0
        for row in rows:
            record = row["record"]
            if needle:
                if scope_label == "All":
                    fields = _all_scope_fields(record, base_fields)
                else:
                    fields = scope_fields.get(scope_label, base_fields)
                if not any(needle in _search_norm(record.get(field, ""))
                           for field in fields):
                    continue
            iid = row["code"] or f"row-{shown}"
            tree.insert("", "end", iid=iid,
                        values=(row["code"], row["name"], row["unit"]))
            by_code[iid] = row
            shown += 1
        count_label.config(text=f"{shown} of {len(rows)} resources")

    def on_pick():
        selection = tree.selection()
        if not selection:
            return
        row = by_code.get(selection[0])
        if row is None:
            return
        if callable(on_select):
            on_select(row["record"])
        dialog.destroy()

    def on_select_row(_event=None):
        selection = tree.selection()
        if not selection:
            return
        row = by_code.get(selection[0])
        if row is not None:
            detail_label.config(text=row["detail"])

    search_entry.bind("<KeyRelease>", lambda _e: refresh())
    # Clipboard and programmatic edits re-run the filter too (typing arrives
    # through <KeyRelease>), so the list can never disagree with the query.
    for sequence in ("<<Paste>>", "<<Cut>>", "<<Clear>>"):
        search_entry.bind(sequence, lambda _e: refresh())
    search_entry.on_text_changed = refresh
    tree.bind("<<TreeviewSelect>>", on_select_row)
    tree.bind("<Double-1>", lambda _e: on_pick())
    buttons = ttk.Frame(dialog, padding=(10, 0, 10, 10))
    buttons.pack(fill="x")
    ttk.Button(buttons, text="Select", style="Accent.TButton",
               command=on_pick).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Cancel",
               command=dialog.destroy).pack(side="left")
    refresh()
    return dialog


def catalogue_browser(parent, app, grid, status_label):
    """Search toolbar + details panel for the materials catalogue.

    Lives outside build_materials_page so that page keeps its
    read-only grid contract; the grid itself is never editable —
    search and filters only narrow the displayed rows.
    Returns (toolbar, details) frames for the caller to pack around
    the grid card.
    """
    scope_var = tk.StringVar(master=parent, value="All")
    status_var = tk.StringVar(master=parent, value="All")
    search_var = tk.StringVar(master=parent)
    toolbar = ttk.Frame(parent)
    ttk.Label(toolbar, text="Search resources:").pack(side="left")
    search_entry = ttk.Entry(toolbar, width=30, name="catalogue_search",
                             textvariable=search_var)
    search_entry.pack(side="left", padx=(4, 6))
    ttk.Combobox(toolbar, textvariable=scope_var, state="readonly",
                 values=[label for label, _f in MATERIAL_SEARCH_SCOPES],
                 width=10).pack(side="left")
    ttk.Label(toolbar, text="Status:").pack(side="left", padx=(6, 2))
    ttk.Combobox(toolbar, textvariable=status_var, state="readonly",
                 values=list(MATERIAL_STATUSES),
                 width=18).pack(side="left")
    count_label = ttk.Label(toolbar, text="", style="Status.TLabel")
    count_label.pack(side="left", padx=(8, 0))
    ttk.Button(toolbar, text="Use in Rate Builder",
               style="Accent.TButton",
               command=lambda: _send_to_rate_builder(
                   app, grid, status_label)).pack(side="right")
    details = ttk.LabelFrame(parent, text="Resource Details")
    details_label = ttk.Label(details, text="Select a row for details.",
                              style="Status.TLabel", wraplength=640,
                              justify="left")
    details_label.pack(anchor="w", padx=8, pady=6)

    def refresh(*_args):
        try:
            records = app.repository.list("materials")
        except Exception as exc:
            status_label.config(text=f"Could not load materials: {exc}")
            return
        matches = filter_catalogue(
            records, search_var.get(),
            scope_var.get(), status_var.get())
        policy = active_material_code_policy(app)
        seed_records = [record for record in matches
                        if not str(record.get("key", "")).startswith("user:")]
        refresh_grid(grid, [_catalogue_row(record, policy=policy,
                                           seed_records=seed_records)
                            for record in matches])
        count_label.config(
            text=f"{len(matches)} of {len(records)} resources")

    def show_details(_event=None):
        selection = grid.selection()
        if not selection:
            return
        values = grid.item(selection[0], "values")
        if not values:
            return
        record = resolve_material_reference(app, str(values[0]))
        if record is None:
            details_label.config(
                text=f"Could not load record: {values[0]}")
            return
        details_label.config(text=material_details_text(record))

    search_entry.bind("<KeyRelease>", refresh)
    search_var.trace_add("write", lambda *_a: refresh())
    scope_var.trace_add("write", lambda *_a: refresh())
    status_var.trace_add("write", lambda *_a: refresh())
    grid.bind("<<TreeviewSelect>>", show_details, add="+")
    try:
        total = len(app.repository.list("materials"))
    except Exception:
        total = 0
    count_label.config(text=f"{total} of {total} resources")
    return toolbar, details


def _send_to_rate_builder(app, grid, status_label):
    """Stage the selected catalogue code for the Rate Builder page."""
    selection = grid.selection()
    if not selection:
        status_label.config(text="Select a resource first.")
        return
    values = grid.item(selection[0], "values")
    if not values:
        status_label.config(text="Select a resource first.")
        return
    app.session.pending_material_key = values[0]
    app.show("rates")


#: Estimate dashboard groups in display order.
ESTIMATE_GROUP_ORDER = (
    ("materials", "Direct Materials"),
    ("labour", "Direct Labour"),
    ("plant", "Plant & Haulage"),
    ("other", "Other Sections"),
)

_ESTIMATE_GROUP_CODES = {
    "materials": ("C", "M", "R", "E", "F"),
    "labour": ("L",),
    "plant": ("P", "H"),
}


def _estimate_field(source, name, default=None):
    """Read name from an object attribute or a mapping key."""
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _estimate_source(compiled):
    """Normalize a compiled BOQ or BOQ document-data payload.

    Accepts the Phase 10 CompiledBoq (sections with code/title/total;
    resolved_subtotal/total/unresolved_items) or a DocumentPayload (or
    its plain-dict form: sections[].code/title/total plus
    summary.grand_total/resolved_subtotal/unresolved_items). Only these
    supported DTO fields are read — nothing is inferred or invented.
    Returns (sections, resolved_subtotal, grand_total, unresolved).
    """
    from qs_engine.core.errors import ValidationError
    if compiled is None:
        raise ValidationError(
            "Estimate needs a compiled BOQ — compile it on the BOQ "
            "View first")
    summary = _estimate_field(compiled, "summary", None)
    if summary is not None:
        sections = _estimate_field(compiled, "sections", ())
        resolved = _estimate_field(summary, "resolved_subtotal", "")
        grand = _estimate_field(summary, "grand_total", None)
        unresolved = _estimate_field(summary, "unresolved_items", ())
    else:
        sections = _estimate_field(compiled, "sections", None)
        resolved = _estimate_field(compiled, "resolved_subtotal", "")
        grand = _estimate_field(compiled, "total", None)
        unresolved = _estimate_field(compiled, "unresolved_items", ())
    if sections is None:
        raise ValidationError(
            "Estimate needs BOQ sections — compile it on the BOQ "
            "View first")
    return (tuple(sections), resolved, grand, tuple(unresolved or ()))


def estimate_cost_groups(compiled) -> dict:
    """Roll BOQ section totals into estimate cost groups.

    Presentation roll-up of compiled/document-data truth only (no
    engineering math): priced section totals are summed per group;
    groups with unresolved sections are flagged partial so a partial
    sum can never pose as a complete one. Overheads/markups have no
    BOQ document-data layer and report an em-dash with Rate Builder
    guidance on the page.
    """
    from decimal import Decimal
    sections, resolved, grand, unresolved = _estimate_source(compiled)
    code_to_group = {}
    for group_key, codes in _ESTIMATE_GROUP_CODES.items():
        for code in codes:
            code_to_group[code] = group_key
    totals = {key: Decimal("0") for key, _label in ESTIMATE_GROUP_ORDER}
    priced = {key: False for key, _label in ESTIMATE_GROUP_ORDER}
    partial = {key: False for key, _label in ESTIMATE_GROUP_ORDER}
    for section in sections:
        group_key = code_to_group.get(
            _estimate_field(section, "code", ""), "other")
        total = _estimate_field(section, "total", None)
        if total is None:
            partial[group_key] = True
        else:
            totals[group_key] += total if isinstance(total, Decimal) \
                else Decimal(str(total))
            priced[group_key] = True
    groups = tuple(
        (key, label,
         (str(totals[key]) if priced[key] else None),
         partial[key])
        for key, label in ESTIMATE_GROUP_ORDER)
    return {
        "groups": groups,
        "resolved_subtotal": str(resolved),
        "grand_total": (str(grand) if grand is not None else None),
        "unresolved_items": unresolved,
    }


#: Edition choices per measurement standard (UI conveniences: the
#: engine stores the edition string verbatim with no edition registry,
#: and unregistered standards bind as custom/unverified via known=False
#: — NRM stays selectable and honest until registered in
#: qs_engine.boq.measurement.KNOWN_STANDARDS).
STANDARD_EDITIONS = {
    "CESMM": ("CESMM4", "CESMM3"),
    "SMM": ("SMM7",),
    "NRM": ("NRM2",),
}


def measurement_standard_choices() -> tuple:
    """Standard dropdown values: registered standards, then defaults."""
    from qs_engine.boq.measurement import KNOWN_STANDARDS
    registered = sorted({str(name).strip().upper()
                         for name in KNOWN_STANDARDS})
    extras = [standard for standard in STANDARD_EDITIONS
              if standard not in registered]
    return tuple(registered + extras)


def measurement_edition_choices(standard) -> tuple:
    """Edition dropdown values for a standard (() when custom)."""
    return STANDARD_EDITIONS.get(str(standard or "").strip().upper(), ())


#: Footer status bar segment keys in display order.
STATUS_SEGMENTS = ("lines", "project", "boq", "standard", "rules")


def status_segments(session) -> tuple:
    """Five footer segments from session state (headless-testable).

    Presentation sibling of build_status_text (which stays frozen for
    backwards compatibility): line count, project indicator, BOQ
    compile state (uncompiled / unresolved / compiled), active
    standard, and the standing measurement-rules governance flag
    (always outstanding — no verified-standard registry is bound in
    this build).
    """
    counts = session.summary_counts()
    segments = [f"Lines: {counts['lines']}"]
    if session.project_saved:
        name = str(session.project.get("name", "") or "").strip()
        segments.append(f"\U0001f7e2 Project: {name or 'Unnamed Project'}")
    else:
        segments.append("\U0001f4c1 No Active Project")
    compiled = session.last_compiled
    if compiled is None:
        segments.append("\u26aa BOQ: Uncompiled")
    elif compiled.has_unresolved:
        segments.append(f"\u26a0 BOQ: {len(compiled.unresolved_items)} "
                        f"Unresolved")
    else:
        segments.append("\U0001f7e2 BOQ: Compiled")
    standard = session.standard
    if standard is None:
        segments.append("\u26aa Standard: [Not Bound]")
    else:
        edition = str(standard.edition or "").strip()
        segments.append(
            f"\U0001f4d0 Standard: {edition or standard.standard}")
    segments.append("\u26a0 Measurement Rules Need Verification")
    return tuple(segments)


def field_choices(spec_key, field, repository=None):
    """Dropdown values for choice-driven fields (None keeps ttk.Entry).

    Currently the concrete grade selector, populated from the
    concrete_classes master table so selections map to real keys.
    """
    if (spec_key, field) == ("concrete", "class_key"):
        return concrete_grade_choices(repository)
    return None


def translate_field_value(spec_key, field, value, repository=None):
    """Map display text to engine keys (grade C20 -> class_c20).

    Pure pass-through for every other field; verbatim fallback keeps
    typed keys working and unknown grades failing closed in the engine.
    """
    if (spec_key, field) == ("concrete", "class_key"):
        return resolve_concrete_class_key(value, repository)
    return value


class QSPanel(ttk.Frame):
    """One workflow panel: entries in, controller call, text output."""

    def __init__(self, parent, spec_key, controller, repository=None,
                 action_label="Calculate", on_result=None, chrome=True,
                 override_source=None):
        """One panel; ``override_source`` is the unified override channel.

        ``override_source`` may be a mapping or a zero-arg callable
        returning one (resolved live at click time — session-backed
        contexts read the freshest values). When set, ``run()`` invokes
        ``controller(inputs, repository, overrides)``; when None the
        controller is invoked with the original two arguments, so
        custom two-argument bindings keep working unchanged. With a
        source set, the controller must accept the third parameter.
        """
        super().__init__(parent)
        title, _, fields = PANEL_SPECS[spec_key]
        self._spec_key = spec_key
        self._controller = controller
        self._repository = repository
        self._override_source = override_source
        self._entries = {}
        self.last_result = None
        self._on_result = on_result
        if chrome:
            ttk.Label(self, text=title, style="Header.TLabel").pack(
                anchor="w", pady=(0, 4))
            guide = ttk.LabelFrame(self, text=INSTRUCTION_TITLE,
                                   style="Instructions.TLabelframe")
            guide.pack(fill="x", pady=(0, 8))
            ttk.Label(guide, text=PANEL_INSTRUCTIONS[spec_key],
                      style="Instructions.TLabel",
                      wraplength=560, justify="left").pack(
                          fill="x", padx=8, pady=6)
        label_width = label_column_width(fields)
        form_grid = ttk.Frame(self)
        form_grid.pack(fill="x", pady=2)
        form_grid.grid_columnconfigure(1, weight=1)
        form_grid.grid_columnconfigure(3, weight=1)
        for index, (field, label) in enumerate(fields):
            rownum, half = divmod(index, 2)
            ttk.Label(form_grid, text=label, width=label_width).grid(
                row=rownum, column=half * 2,
                padx=(0, 2) if half == 0 else (6, 2),
                pady=2, sticky="w")
            choices = field_choices(spec_key, field, repository)
            cue = FIELD_CUES.get((spec_key, field), "")
            if choices:
                entry = CueCombobox(form_grid, width=22,
                                    values=list(choices), cue=cue)
            elif cue:
                # Width follows the cue so the example can never clip; the
                # form columns still stretch to the panel width.
                entry = CueEntry(form_grid, width=max(22, len(cue) + 2),
                                 cue=cue)
            else:
                entry = ttk.Entry(form_grid, width=22)
            if len(fields) % 2 == 1 and index == len(fields) - 1:
                entry.grid(row=rownum, column=1, columnspan=3,
                           padx=2, pady=2, sticky="ew")
            else:
                entry.grid(row=rownum, column=half * 2 + 1, padx=2, pady=2,
                           sticky="ew")
            self._entries[field] = entry
        ttk.Button(self, text=action_label, style="Accent.TButton",
                   command=self.run).pack(anchor="w", pady=8)
        self.output = tk.Text(self, height=8, wrap="word",
                               background="white")
        self.output.pack(fill="both", expand=True)
        self.message = ttk.Label(self, text="", foreground="red")
        self.message.pack(anchor="w")

    def collect(self):
        """Gather raw widget strings (grade displays mapped to keys).

        Reads go through the cue-safe getter: ghost/example text is never
        collected as input, so a form can never hand a cue to a controller.
        """
        return {
            name: translate_field_value(
                self._spec_key, name, _entry_text(entry), self._repository)
            for name, entry in self._entries.items()
        }

    def run(self):
        """Invoke the controller; render view-model or ErrorView.

        With an ``override_source`` configured the resolved override
        dict is passed as the controller's third argument — the one
        channel through which Masonry, Earthworks, Labour, Plant,
        Haulage and Concrete receive estimator overrides.
        """
        self.output.delete("1.0", "end")
        self.message.config(text="")
        inputs = self.collect()
        if self._override_source is None:
            result = self._controller(inputs, self._repository)
        else:
            result = self._controller(
                inputs, self._repository,
                resolve_override_source(self._override_source))
        self.last_result = result
        if self._on_result is not None:
            self._on_result(result)
        if isinstance(result, ErrorView):
            self.message.config(text=result.message)
            return result
        self.output.insert("end", _render(result))
        return result


def _render(view) -> str:
    """Render any view-model dataclass as indented text lines."""
    lines = []
    for name in getattr(view, "__dataclass_fields__", {}):
        value = getattr(view, name)
        lines.append(f"{name}: {value}")
    return "\n".join(lines)


def provenance_status_text(result) -> str:
    """One-line provenance summary for a calculated view-model.

    Surfaces whether the displayed result used manual overrides (and
    which fields) plus the master-table version it resolved against.
    Returns "" when the result carries no provenance fields or the
    calculation failed (ErrorView), so a stale provenance bar can never
    sit beneath an error message.
    """
    if result is None or isinstance(result, ErrorView):
        return ""
    overrides = getattr(result, "overrides_used", None)
    version = getattr(result, "master_version", None)
    if overrides is None and version is None:
        return ""
    if isinstance(overrides, bool):
        detail = ("manual overrides applied" if overrides
                  else "master data only")
    elif overrides:
        detail = "manual overrides: " + ", ".join(
            str(field) for field in overrides)
    else:
        detail = "master data only"
    suffix = f" · master {version}" if version else ""
    return f"Provenance: {detail}{suffix}"


# --------------------------------------------------------------------------
# Session-backed workspace pages (each build_*(body, app) fills a frame).
# --------------------------------------------------------------------------

def _trade_grid_rows(session, trade=None):
    """(iid, trade, description, unit, quantity, rate, ref) row tuples."""
    rows = []
    for index, line in enumerate(session.lines()):
        if trade is not None and line.trade != trade:
            continue
        rows.append((str(index), line.trade, line.description, line.unit,
                     line.quantity, line.rate or "—", line.takeoff_ref))
    return rows


def _refresh_trade_grid(tree, session, trade=None):
    refresh_grid(tree, [row[1:] for row in _trade_grid_rows(session, trade)])
    for row in _trade_grid_rows(session, trade):
        children = tree.get_children()
        tree.item(children[-1], tags=(row[0],))


def build_takeoff_page(body, app, trade, spec_key, add_enabled=True,
                       summary_spec=None, controller=None,
                       override_source=None):
    """Generic take-off page: form + calculate + schedule grid.

    add_enabled=False renders the calculation form only (for trades
    whose results price time or logistics rather than BOQ quantities —
    their costs flow through the Rate Builder instead).
    summary_spec is an optional (card title, ((attr, caption), ...))
    pair rendering a planning summary card from the view-model after
    each calculation (attributes read by name; display only).
    controller optionally overrides the default binding.
    override_source is the unified override channel (mapping or
    zero-arg callable) passed through to the panel's ``run()`` — the
    generic equivalent of the concrete page's former private binding;
    when both are supplied, ``controller`` must accept the resolved
    override dict as its third argument.
    """
    from qs_engine.core.errors import QSEngineError
    title, _, _ = PANEL_SPECS[spec_key]
    build_page_header(body, title, PANEL_INSTRUCTIONS[spec_key],
                      guide_key=spec_key,
                      icon=NAV_ITEM_ICONS[spec_key])
    summary_labels = None
    provenance_label = ttk.Label(body, text="", style="Status.TLabel",
                                 wraplength=640, justify="left")

    def on_result(result):
        provenance_label.config(text=provenance_status_text(result))
        if isinstance(result, ErrorView) or summary_labels is None:
            return
        for attr, _caption in summary_spec[1]:
            summary_labels[attr].config(text=str(getattr(result, attr)))

    panel = QSPanel(body, spec_key,
                    controller or default_bindings()[spec_key],
                    app.repository, action_label="Calculate Element",
                    on_result=on_result,
                    chrome=False,
                    override_source=override_source)
    panel.pack(fill="x")
    provenance_label.pack(anchor="w", pady=(2, 0))
    if summary_spec is not None:
        # Rendered after the form: Title → Banner → Form → Summary.
        summary_labels = _summary_card(
            body, summary_spec[0], summary_spec[1])
    status = status_line(body)
    if not add_enabled:
        ttk.Label(
            body,
            text="Note: this result prices time/logistics, not BOQ "
                 "quantities — its costs flow into rates through the "
                 "Rate Builder, not through take-off lines.",
            style="Status.TLabel", wraplength=640,
            justify="left").pack(anchor="w", pady=(8, 0))
        return {"panel": panel, "status": status}
    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=6)
    card = ttk.LabelFrame(body, text="Take-off Schedule")
    card.pack(fill="both", expand=True, pady=(6, 0))
    grid = make_grid(card, SCHEDULE_COLUMNS)
    grid.pack(fill="both", expand=True)

    def refresh():
        for child in grid.get_children():
            grid.delete(child)
        for index, line in enumerate(app.session.lines()):
            if line.trade != trade:
                continue
            grid.insert("", "end", iid=str(index), values=(
                line.trade, line.description, line.unit, line.quantity,
                line.rate or "—", line.takeoff_ref))

    def on_add():
        result = panel.run()  # always fresh: never add a stale result
        if isinstance(result, ErrorView):
            status.config(text=result.message)
            return
        try:
            line = extract_takeoff_line(trade, result, panel.collect())
            app.session.add_line(line)
        except QSEngineError as exc:
            status.config(text=str(exc))
            app.refresh_status()
            return
        refresh()
        status.config(text=f"● Saved take-off line "
                           f"({line.description}, {line.quantity} "
                           f"{line.unit})")
        app.refresh_status()

    rate_row = ttk.Frame(body)
    rate_row.pack(fill="x", pady=4)
    ttk.Label(rate_row, text="Rate for selected:").pack(side="left")
    rate_entry = ttk.Entry(rate_row, width=16)
    rate_entry.pack(side="left", padx=4)
    rate_ref_entry = ttk.Entry(rate_row, width=16)
    rate_ref_entry.pack(side="left", padx=4)
    ttk.Label(rate_row, text="(ref)").pack(side="left")

    def on_set_rate():
        selection = grid.selection()
        if not selection:
            status.config(text="Select a take-off line first")
            return
        try:
            app.session.set_line_rate(
                int(selection[0]), rate_entry.get().strip(),
                rate_ref_entry.get().strip())
        except (QSEngineError, ValueError, IndexError) as exc:
            status.config(text=str(exc))
            app.refresh_status()
            return
        refresh()
        status.config(text="● Saved rate on selected line")
        app.refresh_status()

    def on_remove():
        selection = grid.selection()
        if not selection:
            status.config(text="Select a take-off line first")
            return
        try:
            removed = app.session.remove_line(int(selection[0]))
        except (QSEngineError, ValueError, IndexError) as exc:
            status.config(text=str(exc))
            app.refresh_status()
            return
        refresh()
        status.config(text=f"● Removed take-off line "
                           f"({removed.description})")
        app.refresh_status()

    ttk.Button(actions, text="Add to Take-Off", style="Accent.TButton",
               command=on_add).pack(side="left", padx=(0, 6))
    ttk.Button(actions, text="Set Rate on Selected",
               style="Accent.TButton",
               command=on_set_rate).pack(side="left", padx=(0, 6))
    ttk.Button(actions, text="Remove Selected", style="Accent.TButton",
               command=on_remove).pack(side="left")
    rate_row.pack(fill="x", pady=4)
    refresh()
    return {"panel": panel, "grid": grid, "status": status,
            "refresh": refresh}


def build_concrete_page(body, app):
    """Concrete take-off with live density overrides + reference readout.

    The standard take-off form (grade dropdown, live Project Setup
    density overrides) plus a read-only Engineering Reference strip:
    nominal mix reference and dry-density provenance. Display only —
    the readout never feeds the calculation. The density flow itself is
    no longer a private binding: it travels the same ``override_source``
    channel every other trade page uses.
    """
    refs = build_takeoff_page(
        body, app, "concrete", "concrete",
        override_source=lambda: session_override_context(
            app.session.project, "concrete"))
    panel = refs["panel"]
    supplement = ttk.LabelFrame(body, text="Engineering Reference")
    supplement.pack(fill="x", pady=(6, 0))
    lines_label = ttk.Label(supplement, text="", style="Status.TLabel",
                            wraplength=640, justify="left")
    lines_label.pack(fill="x", padx=8, pady=6)

    def refresh_supplement():
        collected = panel.collect()
        lines_label.config(text=" | ".join(concrete_supplement_lines(
            collected.get("class_key", ""), app.session.project,
            app.repository)))

    previous = panel._on_result

    def on_result(result):
        if previous is not None:
            previous(result)
        refresh_supplement()

    panel._on_result = on_result
    refresh_supplement()
    refs["supplement"] = lines_label
    return refs


def build_rebar_page(body, app):
    """Rebar schedule form (structured grid + advanced input)."""
    from qs_engine.core.errors import QSEngineError
    build_page_header(
        body, "Reinforcement Take-off",
        guide_key="rebar",
        icon="🔩")
    grid_host = ttk.Frame(body)
    grid_host.pack(fill="x")
    for col, (_field, heading) in enumerate(REBAR_GRID_COLUMNS):
        ttk.Label(grid_host, text=heading).grid(
            row=0, column=col, padx=2, sticky="w")
    grid_rows = []

    def add_bar_row():
        """Append one BBS bar row (grade/size dropdowns + entries)."""
        widgets = {}
        row_index = len(grid_rows) + 1
        widths = {"member": 12, "mark": 6, "grade": 12, "size": 6,
                  "bar": 8, "members": 6, "bars": 6, "length": 8,
                  "extra": 8, "mass": 8, "weight": 12}
        for col, (field, _heading) in enumerate(REBAR_GRID_COLUMNS):
            if field == "grade":
                widget = ttk.Combobox(
                    grid_host, state="readonly",
                    values=list(REBAR_STEEL_GRADES),
                    width=widths[field])
                widget.set("Y (460 MPa)")
            elif field == "size":
                widget = ttk.Combobox(
                    grid_host, state="readonly",
                    values=list(REBAR_BAR_SIZES_MM),
                    width=widths[field])
                widget.set("12")
            elif field == "weight":
                widget = ttk.Label(grid_host, text="—",
                                   width=widths[field])
            else:
                widget = ttk.Entry(grid_host, width=widths[field])
            widget.grid(row=row_index, column=col, padx=2, pady=1,
                        sticky="ew")
            widgets[field] = widget
        widgets["members"].insert(0, "1")
        for field in ("member", "mark", "bar", "members", "bars",
                      "length", "extra", "mass"):
            widgets[field].bind(
                "<KeyRelease>",
                lambda _event, row=widgets: refresh_row(row))
            widgets[field].bind(
                "<FocusOut>",
                lambda _event, row=widgets: refresh_row(row))
        widgets["grade"].bind(
            "<<ComboboxSelected>>",
            lambda _event, row=widgets: on_grade_size_change(row))
        widgets["size"].bind(
            "<<ComboboxSelected>>",
            lambda _event, row=widgets: on_grade_size_change(row))
        on_grade_size_change(widgets)
        grid_rows.append(widgets)

    def on_grade_size_change(widgets):
        """Compose the designation from grade/size dropdowns only.

        Custom grade leaves a manually typed designation alone. Unit
        mass is never written here: it stays exactly what the estimator
        typed (blank until they enter it), so no fabricated value can
        reach the engine.
        """
        grade = widgets["grade"].get()
        size = widgets["size"].get()
        if REBAR_GRADE_PREFIXES.get(grade, ""):
            widgets["bar"].delete(0, "end")
            widgets["bar"].insert(0, rebar_designation(grade, size))
        refresh_row(widgets)

    def refresh_row(widgets):
        """Recompute the live Weight readout from row entries."""
        _bars, _length, weight = rebar_row_totals(
            widgets["members"].get(), widgets["bars"].get(),
            widgets["length"].get(), widgets["extra"].get(),
            widgets["mass"].get())
        widgets["weight"].config(text=weight or "—")

    def remove_bar_row():
        """Drop the last structured bar row."""
        if grid_rows:
            for widget in grid_rows.pop().values():
                widget.destroy()

    add_bar_row()
    row_buttons = ttk.Frame(body)
    row_buttons.pack(fill="x", pady=2)
    ttk.Button(row_buttons, text="Add Bar Row", style="Accent.TButton",
               command=add_bar_row).pack(side="left", padx=(0, 6))
    ttk.Button(row_buttons, text="Remove Last Row", style="Accent.TButton",
               command=remove_bar_row).pack(side="left")
    raw_visible = tk.BooleanVar(value=False)
    raw_frame = ttk.LabelFrame(body, text="Advanced Input")
    ttk.Label(raw_frame,
              text="Bar schedule input (one line per bar):").pack(anchor="w")
    lines_text = tk.Text(raw_frame, height=5, wrap="word",
                         background="white")
    lines_text.pack(fill="x")

    def toggle_raw():
        if raw_visible.get():
            raw_frame.pack(fill="x", pady=(6, 0))
        else:
            raw_frame.pack_forget()

    ttk.Checkbutton(body, text="Show Advanced Input",
                    variable=raw_visible,
                    command=toggle_raw).pack(anchor="w", pady=(4, 0))
    opts = ttk.Frame(body)
    opts.pack(fill="x", pady=4)
    waste_entry, wire_entry = ttk.Entry(opts, width=10), ttk.Entry(opts,
                                                                   width=16)
    density_entry = ttk.Entry(opts, width=14)
    for label, widget in (("Wastage %:", waste_entry),
                          ("Wire kg/t (optional):", wire_entry),
                          ("Steel density (kg/m³, optional):", density_entry)):
        ttk.Label(opts, text=label).pack(side="left")
        widget.pack(side="left", padx=4)
    output = tk.Text(body, height=8, wrap="word", background="white")
    message = ttk.Label(body, text="", foreground="red")
    provenance = ttk.Label(body, text="", style="Status.TLabel",
                           wraplength=640, justify="left")
    state = {}

    def grid_to_dsl():
        """Serialize non-blank grid rows into bar schedule input lines.

        Member/mark annotations travel as # comments (the bar grammar
        has no description field); unknown designations pass through
        verbatim for fail-closed engine validation.
        """
        rows = []
        for widgets in grid_rows:
            values = {field: widgets[field].get().strip()
                      for field in ("member", "mark", "bar", "members",
                                    "bars", "length", "extra", "mass")}
            rows.extend(rebar_row_inputs_to_dsl(values))
        return "\n".join(rows)

    def on_calculate():
        from qs_engine.ui.controllers import rebar_controller
        output.delete("1.0", "end")
        message.config(text="")
        dsl = grid_to_dsl()
        if dsl.strip():
            lines_text.delete("1.0", "end")
            lines_text.insert("end", dsl)
        result = rebar_controller(
            parse_rebar_lines(lines_text.get("1.0", "end")),
            waste_entry.get(), wire_entry.get() or None, app.repository,
            steel_density_kg_per_m3=density_entry.get().strip() or None)
        state["result"] = result
        provenance.config(text=provenance_status_text(result))
        if isinstance(result, ErrorView):
            message.config(text=result.message)
            return result
        output.insert("end", _render(result))
        return result

    ttk.Button(body, text="Calculate Schedule", style="Accent.TButton",
               command=on_calculate).pack(anchor="w", pady=6)
    status = status_line(body)
    card = ttk.LabelFrame(body, text="Take-off Schedule")
    card.pack(fill="both", expand=True, pady=(6, 0))
    grid = make_grid(card, SCHEDULE_COLUMNS)
    grid.pack(fill="both", expand=True)

    def refresh():
        for child in grid.get_children():
            grid.delete(child)
        for index, line in enumerate(app.session.lines()):
            if line.trade not in ("rebar", "formwork"):
                continue
            grid.insert("", "end", iid=str(index), values=(
                line.trade, line.description, line.unit, line.quantity,
                line.rate or "—", line.takeoff_ref))

    def on_add():
        result = on_calculate()  # always fresh: never add a stale result
        if isinstance(result, ErrorView):
            status.config(text=result.message)
            app.refresh_status()
            return
        try:
            line = extract_takeoff_line("rebar", result, {})
            app.session.add_line(line)
        except QSEngineError as exc:
            status.config(text=str(exc))
            app.refresh_status()
            return
        refresh()
        status.config(text="● Saved take-off line")
        app.refresh_status()

    def on_remove():
        selection = grid.selection()
        if not selection:
            status.config(text="Select a take-off line first")
            return
        try:
            removed = app.session.remove_line(int(selection[0]))
        except (QSEngineError, ValueError, IndexError) as exc:
            status.config(text=str(exc))
            app.refresh_status()
            return
        refresh()
        status.config(text=f"● Removed take-off line "
                           f"({removed.description})")
        app.refresh_status()

    buttons = ttk.Frame(body)
    buttons.pack(fill="x", pady=6)
    ttk.Button(buttons, text="Add to Take-Off", style="Accent.TButton",
               command=on_add).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Remove Selected", style="Accent.TButton",
               command=on_remove).pack(side="left")
    message.pack(anchor="w")
    provenance.pack(anchor="w")

    # -- Formwork take-off: own controller, shared take-off schedule grid --
    from qs_engine.ui.controllers import (
        FORMWORK_ELEMENT_TYPES,
        formwork_controller as run_formwork,
    )
    form_frame = ttk.LabelFrame(body, text="Formwork Take-off")
    form_frame.pack(fill="x", pady=(8, 0))
    ttk.Label(
        form_frame,
        text="Contact area by element type (dimensions in the chosen "
             "unit). Deductions subtract as label:area; leave the "
             "scheduling rates blank unless you want plywood sheets, "
             "props, or release agent costed quantities.",
        style="Status.TLabel", wraplength=640, justify="left").pack(
            anchor="w", padx=6, pady=(4, 0))
    form_type_labels = {
        " ".join(part.capitalize() for part in token.split("_")): token
        for token in FORMWORK_ELEMENT_TYPES
    }

    def form_cell(parent, label, width, values=None):
        """One labelled formwork input (readonly combo when values given)."""
        cell = ttk.Frame(parent)
        cell.pack(side="left", padx=(0, 8))
        ttk.Label(cell, text=label).pack(anchor="w")
        if values is None:
            widget = ttk.Entry(cell, width=width)
        else:
            widget = ttk.Combobox(cell, state="readonly", width=width,
                                  values=list(values))
        widget.pack()
        return widget

    form_row_a = ttk.Frame(form_frame)
    form_row_a.pack(fill="x", padx=6, pady=2)
    form_element_entry = form_cell(
        form_row_a, "Element / mark", 16)
    form_type_combo = form_cell(
        form_row_a, "Element type", 13, values=form_type_labels)
    form_type_combo.set(next(iter(form_type_labels)))
    form_unit_entry = form_cell(form_row_a, "Unit", 4)
    form_unit_entry.insert(0, "m")
    form_faces_entry = form_cell(form_row_a, "Faces (walls)", 6)

    form_row_b = ttk.Frame(form_frame)
    form_row_b.pack(fill="x", padx=6, pady=2)
    form_length_entry = form_cell(form_row_b, "Length", 9)
    form_width_entry = form_cell(form_row_b, "Width", 9)
    form_depth_entry = form_cell(form_row_b, "Depth", 9)
    form_height_entry = form_cell(form_row_b, "Height", 9)
    form_deductions_entry = form_cell(
        form_row_b, "Deductions (label:area; label:area)", 28)

    form_row_c = ttk.Frame(form_frame)
    form_row_c.pack(fill="x", padx=6, pady=2)
    form_sheet_entry = form_cell(form_row_c, "Sheet area (m²)", 10)
    form_reuses_entry = form_cell(form_row_c, "Reuses", 7)
    form_props_entry = form_cell(form_row_c, "Props (m per m²)", 11)
    form_agent_entry = form_cell(form_row_c, "Release (L per m²)", 12)

    form_output = tk.Text(form_frame, height=6, wrap="word",
                          background="white")
    form_output.pack(fill="x", padx=6, pady=2)
    form_message = ttk.Label(form_frame, text="", foreground="red")
    form_message.pack(anchor="w", padx=6)
    form_state = {}

    def formwork_values():
        return {
            "element": form_element_entry.get(),
            "element_type": form_type_labels.get(
                form_type_combo.get(), form_type_combo.get()),
            "unit": form_unit_entry.get(),
            "length": form_length_entry.get(),
            "width": form_width_entry.get(),
            "depth": form_depth_entry.get(),
            "height": form_height_entry.get(),
            "faces": form_faces_entry.get(),
            "sheet_area_m2": form_sheet_entry.get(),
            "reuses": form_reuses_entry.get(),
            "linear_m_per_m2": form_props_entry.get(),
            "litres_per_m2": form_agent_entry.get(),
        }

    def on_formwork_calculate():
        form_output.delete("1.0", "end")
        form_message.config(text="")
        result = run_formwork(
            formwork_values(), form_deductions_entry.get())
        form_state["result"] = result
        if isinstance(result, ErrorView):
            form_message.config(text=result.message)
            return result
        form_output.insert("end", _render(result))
        return result

    def on_formwork_add():
        result = on_formwork_calculate()
        if isinstance(result, ErrorView):
            status.config(text=result.message)
            app.refresh_status()
            return
        try:
            line = extract_takeoff_line(
                "formwork", result,
                {"element": form_element_entry.get()})
        except QSEngineError as exc:
            status.config(text=str(exc))
            app.refresh_status()
            return
        app.session.add_line(line)
        refresh()
        status.config(text="● Saved formwork take-off line")
        app.refresh_status()

    form_buttons = ttk.Frame(form_frame)
    form_buttons.pack(fill="x", padx=6, pady=(2, 6))
    ttk.Button(form_buttons, text="Calculate Formwork",
               style="Accent.TButton",
               command=on_formwork_calculate).pack(
                   side="left", padx=(0, 6))
    ttk.Button(form_buttons, text="Add Formwork to Take-Off",
               command=on_formwork_add).pack(side="left")
    refresh()
    return {"status": status, "refresh": refresh}


def _summary_card(parent, title, fields, badge=True):
    """Compact 2-column summary card; returns {field: value_label}.

    Value labels update in place via the returned mapping. The
    planning-data note renders once as a full-width footer below the
    card (pass badge=False for companion cards sharing a page).
    """
    card = ttk.LabelFrame(parent, text=title)
    card.pack(fill="x", pady=(6, 0))
    card.grid_columnconfigure(1, weight=1)
    card.grid_columnconfigure(3, weight=1)
    labels = {}
    for index, (field, caption) in enumerate(fields):
        rownum, half = divmod(index, 2)
        ttk.Label(card, text=caption,
                  width=22 if half == 0 else 20).grid(
                      row=rownum, column=half * 2,
                      padx=(8, 2) if half == 0 else (6, 2),
                      pady=1, sticky="w")
        value = ttk.Label(card, text="—", style="Status.TLabel")
        value.grid(row=rownum, column=half * 2 + 1, padx=2, pady=1,
                   sticky="w")
        labels[field] = value
    if badge:
        ttk.Label(
            parent,
            text="\u2139\ufe0f Planning Quantities — Labour and plant "
                 "requirements calculated here are maintained as project "
                 "planning data and are not automatically assigned to "
                 "direct BOQ items.",
            style="Status.TLabel", wraplength=640,
            justify="left").pack(anchor="w", padx=8, pady=(4, 6))
    return labels


def _update_labour_card(labels, result) -> None:
    """Fill a labour summary card from a LabourView (display only)."""
    labels["duration"].config(text=result.duration_gang_days)
    labels["skilled"].config(text=result.skilled_person_days)
    labels["unskilled"].config(text=result.unskilled_person_days)
    labels["total"].config(text=result.total_cost)


def _update_plant_card(labels, result) -> None:
    """Fill a plant summary card from a PlantView (display only)."""
    labels["duration"].config(
        text=f"{result.duration_value} {result.duration_basis}")
    labels["hire"].config(text=result.hire_cost)
    labels["operating"].config(text=result.operating_cost)
    labels["total"].config(text=result.total_cost)


def build_labour_plant_page(body, app):
    """Combined Labour & Plant view: two independent calculation forms."""
    # One help icon serves both forms: the shared PANEL_INSTRUCTIONS
    # copy covers gang productivity and plant hourly rates alike, so a
    # second (identical-text) icon would only be noise.
    build_page_header(body, "Labour & Plant",
                        PANEL_INSTRUCTIONS["labour"], guide_key="labour",
                        icon="👷")
    row = ttk.Frame(body)
    row.pack(fill="both", expand=True)
    left = ttk.Frame(row)
    left.pack(side="left", fill="both", expand=True, padx=(0, 4))
    right = ttk.Frame(row)
    right.pack(side="left", fill="both", expand=True, padx=(4, 0))
    bindings = default_bindings()

    def on_labour(result):
        if isinstance(result, ErrorView):
            return
        _update_labour_card(labels["labour"], result)

    def on_plant(result):
        if isinstance(result, ErrorView):
            return
        _update_plant_card(labels["plant"], result)

    QSPanel(left, "labour", bindings["labour"], app.repository,
            action_label="Calculate Element",
            on_result=on_labour, chrome=False,
            override_source=lambda: session_override_context(
                app.session.project, "labour")).pack(fill="x")
    QSPanel(right, "plant", bindings["plant"], app.repository,
            action_label="Calculate Element",
            on_result=on_plant, chrome=False,
            override_source=lambda: session_override_context(
                app.session.project, "plant")).pack(fill="x")
    labels = {
        "labour": _summary_card(left, "Labour Summary", (
            ("duration", "Duration (gang-days)"),
            ("skilled", "Skilled person-days"),
            ("unskilled", "Unskilled person-days"),
            ("total", "Total cost"),
        )),
        "plant": _summary_card(right, "Plant Summary", (
            ("duration", "Duration"),
            ("hire", "Hire cost"),
            ("operating", "Operating cost"),
            ("total", "Total cost"),
        ), badge=False),
    }
    ttk.Label(
        body,
        text="Note: labour and plant results price time, not BOQ "
             "quantities — their costs flow into rates through the Rate "
             "Builder, not through take-off lines.",
        style="Status.TLabel", wraplength=640,
        justify="left").pack(anchor="w", pady=(8, 0))


# --------------------------------------------------------------------------
# Page chrome helpers (all headless-safe until widgets are built).
# --------------------------------------------------------------------------

def page_title(parent, text: str) -> None:
    """Bold CIVOLINK page heading."""
    ttk.Label(parent, text=text, style="Header.TLabel").pack(
        anchor="w", pady=(0, 4))


#: Compact header button opening a page's floating instruction guide.
#: Legacy alias retained for tests/docs; headers now render the unified
#: HelpIconButton (circled-i glyph) from qs_engine/ui/widgets.py.
GUIDE_BUTTON_TEXT = "ℹ  Panel Guide"


def _guide_registry():
    """Live PopoverGuide instances (weak refs; dead pages vanish)."""
    from .widgets import _guide_registry as _widget_registry
    return _widget_registry()


class PopoverGuide(_WidgetPopoverGuide):
    """Backwards-compatible subclass of widgets.PopoverGuide.

    Legacy signature ``PopoverGuide(button, text)`` is preserved; the
    popover title matches the legacy INSTRUCTION_TITLE constant.
    """

    _HOVER_DELAY_MS = 400
    _POPOVER_WRAP = 420

    def __init__(self, button, text, title=None):
        super().__init__(button, text,
                         title=title or INSTRUCTION_TITLE)


def build_page_header(parent, title, guide_text=None, extra_buttons=(),
                      icon="", guide_key=None, extra_guides=(),
                      severity="info"):
    """Compact title row: heading left, help icon button(s) right.

    Replaces the page_title/guidance_box pair: the full guide text
    lives on the unified HelpIconButton (button.guide_text / guide_key)
    and in its floating popover instead of a static banner. An optional
    thematic icon prefixes the heading (display only).

    ``guide_key`` names the panel guide in the shared registry
    (``qs_engine/ui/widgets.py``); pass it when available so headers
    read ``HelpIconButton(parent, guide_key="...")``. ``guide_text``
    stays as a backwards-compatible alias (explicit text wins).
    ``extra_guides`` is an optional sequence of
    ``(guide_key, guide_text[, severity])`` tuples rendered as
    additional icon buttons — used to adopt legacy header helpers
    such as the Project Setup ``[?] Verification Help`` button.
    ``extra_buttons`` (legacy ``(label, command)`` pairs) still works
    for non-guide actions.
    """
    from .widgets import register_guide
    header = ttk.Frame(parent)
    header.pack(fill="x", pady=(0, 4))
    heading = f"{icon} {title}" if icon else title
    ttk.Label(header, text=heading, style="Header.TLabel").pack(side="left")
    for label, command in extra_buttons:
        ttk.Button(header, text=label, command=command).pack(
            side="right", padx=(6, 0))
    guides = []
    if guide_key is not None or guide_text is not None:
        guides.append((guide_key, guide_text, severity))
    for spec in extra_guides:
        key = spec[0] if len(spec) > 0 else None
        text = spec[1] if len(spec) > 1 else None
        sev = spec[2] if len(spec) > 2 else "info"
        guides.append((key, text, sev))
    for key, text, sev in guides:
        resolved = text if text is not None else None
        if resolved is None and key is not None:
            # Registry first (honours the page-id alias), module dict next.
            try:
                from .widgets import guide_text_for
                resolved = guide_text_for(key, None)
            except Exception:
                resolved = None
            if resolved is None:
                try:
                    resolved = _GUIDE_CONTENT.get(str(key))
                except NameError:
                    resolved = None
        if resolved is not None and key is not None:
            try:
                register_guide(key, resolved)
            except Exception:
                pass
        try:
            button = HelpIconButton(header, guide_key=key,
                                    guide_text=resolved,
                                    severity=sev)
        except Exception:
            button = ttk.Button(header, text=GUIDE_BUTTON_TEXT)
            if resolved is not None:
                try:
                    button.guide_text = resolved
                except Exception:
                    pass
            if key is not None:
                try:
                    button.guide_key = key
                except Exception:
                    pass
            if resolved is not None:
                try:
                    guide = PopoverGuide(button, resolved)
                    button.config(command=guide.toggle)
                except Exception:
                    pass
        button.pack(side="right", padx=(6, 0))
    return header


def status_line(parent):
    """Small grey status label; caller sets its text."""
    label = ttk.Label(parent, text="", style="Status.TLabel")
    label.pack(anchor="w", pady=(6, 0))
    return label


#: Standard uncompiled-state warning shown at the top of the output
#: views (Excel Export, Valuations & IPC, Corporate Documents) and on
#: the buttons it guards.
EXPORT_GUARD_BANNER = (
    "Action Required: Compile BOQ in Bill of Quantities view "
    "prior to exporting."
)


def guard_banner(parent) -> ttk.Label:
    """Top warning banner for an output view (text owned by the guards)."""
    banner = ttk.Label(parent, text="", style="Status.TLabel",
                       wraplength=640, justify="left",
                       foreground=WARN_AMBER)
    banner.pack(anchor="w", pady=(0, 4))
    return banner


def register_export_guard(app, button, banner=None) -> None:
    """Track one ``(button, banner)`` pair driven by session.boq_compiled.

    Every output view registers its primary action here; the state is
    applied immediately and re-applied on every refresh_status() so a
    compile anywhere flips all guards live.
    """
    guards = getattr(app, "_export_guards", None)
    if guards is None:
        guards = []
        app._export_guards = guards
    guards.append((button, banner))
    sync_export_guards(app)


def sync_export_guards(app) -> int:
    """Apply the session's compile state to every registered guard.

    Guards whose widgets belong to a destroyed page are pruned as they
    are encountered, so repeated page switches never accumulate stale
    references. Returns the number of live guards updated.
    """
    ready = bool(getattr(app.session, "boq_compiled", False))
    live = []
    for button, banner in getattr(app, "_export_guards", ()):
        try:
            alive = button.winfo_exists()
        except Exception:
            alive = False
        if not alive:
            continue
        live.append((button, banner))
        try:
            button.config(state="normal" if ready else "disabled")
        except tk.TclError:
            pass
        if banner is not None:
            try:
                banner.config(text="" if ready else EXPORT_GUARD_BANNER)
            except tk.TclError:
                pass
    app._export_guards = live
    return len(live)


#: Setup & verification guidance (Help menu + Project Setup banner).
#: Density figures are commonly cited textbook starting points only —
#: CIVOLINK ships no density defaults and blank means engine/master
#: default, so the guide instructs confirmation against project data.
VERIFICATION_GUIDE_TEXT = (
    "SETUP & VERIFICATION GUIDE\n"
    "==========================\n"
    "\n"
    "1. BIND A MEASUREMENT STANDARD\n"
    "On Project Setup, pick Measurement Standard (CESMM, SMM or NRM) "
    "and Edition (CESMM4 / CESMM3, SMM7, NRM2 — the edition list "
    "follows the selected standard), then click Bind Standard.\n"
    "• Clears 'Measurement Standard: [Not Bound]' and attaches the "
    "standard to downstream take-offs.\n"
    "• The Needs Verification suffix stays: this build has no "
    "verified-standard registry, so every binding reports name "
    "recognition only. Unlisted names bind as custom/unverified and "
    "fail closed downstream.\n"
    "\n"
    "2. ENGINEERING DENSITY INPUTS\n"
    "Project Setup → Engineering Inputs (Settings). Blank means "
    "engine/master default; shipped master tables hold nulls, so "
    "blank rows show '⚠ Needs Verification' instead of invented "
    "numbers.\n"
    "• Type a project-specific value (project specification or lab "
    "data) and the badge becomes 'Project override: <value>'.\n"
    "• A value counts as master-verified only once a concrete_classes "
    "record carries it with VERIFIED status.\n"
    "• Type the project specification or lab-tested value for each "
    "constituent — CIVOLINK ships no density defaults and the guide "
    "names none, so only confirmed project data ever clears a badge.\n"
    "\n"
    "3. PROJECT FILES (.clk)\n"
    "File menu (or the Project Setup file buttons): New Project, Open "
    "Project (.clk), Save, Save As (.clk). The session persists "
    "take-off lines, project profile, bindings, BOQ and IPC state. "
    "Legacy .civolink files still open; new saves always use .clk."
)

#: Measurement-standard reference (Help menu). Edition lists mirror
#: STANDARD_EDITIONS; custom names bind honestly as unverified.
STANDARDS_GUIDE_TEXT = (
    "MEASUREMENT STANDARDS (CESMM / SMM / NRM)\n"
    "========================================\n"
    "• CESMM → editions CESMM4, CESMM3\n"
    "• SMM → edition SMM7\n"
    "• NRM → edition NRM2\n"
    "The Edition dropdown cascades from the selected standard; an "
    "incompatible typed edition resets to the first valid choice. "
    "Custom standard names are accepted and reported as "
    "custom/unverified — unknown rules fail closed in the engines "
    "rather than guessing."
)

#: About dialog body (Help menu). Version mirrors APP_TITLE.
ABOUT_TEXT = (
    f"{APP_TITLE}\n"
    f"{FOOTER_BADGE}\n"
    "Take-off, measurement, rating, BOQ, IPC valuation and tender "
    "export for civil engineering quantities. Session files use the "
    ".clk format."
)


def _show_modal_text(parent, title, body_text):
    """Blocking read-only text modal; returns None when headless."""
    import tkinter as tk
    from tkinter import ttk
    try:
        dialog = tk.Toplevel(parent)
    except Exception:
        # Headless or unusable parent: skip silently, never raise.
        return None
    dialog.title(title)
    if parent is not None:
        try:
            dialog.transient(parent)
        except tk.TclError:
            pass
    text = tk.Text(dialog, wrap="word", background="white")
    text.pack(fill="both", expand=True, padx=10, pady=(10, 0))
    text.insert("end", body_text)
    text.config(state="disabled")
    ttk.Button(dialog, text="Close",
               command=dialog.destroy).pack(pady=10)
    try:
        dialog.grab_set()
        dialog.wait_window()
    except tk.TclError:
        pass
    return dialog


def show_verification_guide(parent=None):
    """Setup & Verification Guide modal (Help menu + [?] banner).

    Headless-safe: returns None without a display instead of raising.
    """
    return _show_modal_text(
        parent, "Setup & Verification Guide", VERIFICATION_GUIDE_TEXT)


def show_standards_guide(parent=None):
    """Measurement-standard reference modal (Help menu)."""
    return _show_modal_text(
        parent, "Measurement Standards (CESMM/SMM/NRM)",
        STANDARDS_GUIDE_TEXT)


def show_about_dialog(parent=None):
    """About CIVOLINK QS modal (Help menu)."""
    return _show_modal_text(parent, "About CIVOLINK QS", ABOUT_TEXT)


#: guide_key -> full panel text for HelpIconButton(guide_key="...").
#: Populated once the page-level guide constants below exist; headers
#: may reference keys defined later in this module via lazy lookup.
_GUIDE_CONTENT = {}


def _register_panel_guides():
    """Publish panel guide texts to the shared widget registry."""
    from .widgets import register_guide
    for _key, _text in _GUIDE_CONTENT.items():
        try:
            register_guide(_key, _text)
        except Exception:
            pass
    # Navigation page ids double as lookup keys (see PAGE_GUIDE_KEYS),
    # so publish those aliases too - registry lookups then never depend
    # on the resolver hook being installed.
    for _page, _key in PAGE_GUIDE_KEYS.items():
        try:
            if _GUIDE_CONTENT.get(_key):
                register_guide(_page, _GUIDE_CONTENT[_key])
        except Exception:
            pass


#: Navigation page id -> guide key, for the few pages whose sidebar id
#: differs from the guide key (so guide_text_for(page_id) always resolves).
PAGE_GUIDE_KEYS = {"labour_plant": "labour"}


def _guide_text_resolver(key):
    """widgets.py resolver hook: guide_key -> full text (or '')."""
    try:
        text = _GUIDE_CONTENT.get(str(key), "")
        if not text:
            alias = PAGE_GUIDE_KEYS.get(str(key))
            if alias:
                text = _GUIDE_CONTENT.get(alias, "")
        return text
    except Exception:
        return ""


def _license_service_for(app):
    """LicensingService bound to the app (unlicensed default)."""
    from qs_engine.licensing.service import LicensingService
    service = getattr(app, "license_service", None)
    if service is not None:
        return service
    return LicensingService()


def _export_entitlement_error(app):
    """Status message when commercial export is not entitled, else None.

    ACTIVE and OFFLINE_GRACE may export; every other state is blocked
    with a pointer to activation. Take-off, rating, local save/load,
    and read-only review never consult this gate. Hosts without a
    license service stay fully working.
    """
    from qs_engine.licensing.models import LicenseState, license_display
    service = getattr(app, "license_service", None)
    if service is None:
        return None
    try:
        state = service.snapshot().state
    except Exception:
        return None
    if state in (LicenseState.ACTIVE, LicenseState.OFFLINE_GRACE):
        return None
    return (f"Export requires an active license "
            f"(current: {license_display(state)}). "
            f"Open Help → Activate License.")


def show_license_status(app=None):
    """License status dialog (modeless; None when headless).

    Customer-safe fields only: product, license state, organization,
    expiration, device activation, connection. Results render inline
    (no blocking popups) so display tests can drive every button.
    """
    from qs_engine.licensing.models import (
        LicenseState,
        connection_display,
        expiration_display,
        license_display,
    )
    service = _license_service_for(app)
    master = app if isinstance(app, tk.Widget) else None
    try:
        dialog = tk.Toplevel(master)
    except tk.TclError:
        return None
    dialog.title("License Status")
    body = ttk.Frame(dialog, padding=12)
    body.pack(fill="both", expand=True)
    rows = ttk.Frame(body)
    rows.pack(fill="x")
    message = ttk.Label(body, text="", style="Status.TLabel",
                        wraplength=420, justify="left")
    message.pack(anchor="w", pady=(6, 0))

    def render():
        info = service.snapshot()
        for child in rows.winfo_children():
            child.destroy()
        pairs = (
            ("Product", info.product),
            ("License", license_display(info.state)),
            ("Licensed Organization", info.organization or "—"),
            ("Expiration", expiration_display(info.expires)),
            ("Device", "Activated"
             if info.device_activated else "Not Activated"),
            ("Connection",
             connection_display(info.offline, info.state)),
        )
        for rownum, (caption, value) in enumerate(pairs):
            ttk.Label(rows, text=caption, width=22).grid(
                row=rownum, column=0, padx=(0, 4), pady=1, sticky="w")
            ttk.Label(rows, text=value, style="Status.TLabel").grid(
                row=rownum, column=1, pady=1, sticky="w")
        if info.message:
            message.config(text=info.message)

    def on_refresh():
        try:
            info = service.refresh()
            message.config(text=info.message)
        except Exception as exc:
            message.config(text=f"License check failed: {exc}")
        render()

    def on_deactivate():
        try:
            info = service.deactivate()
            message.config(text=info.message)
        except Exception as exc:
            message.config(text=f"Deactivation failed: {exc}")
        render()

    buttons = ttk.Frame(body)
    buttons.pack(fill="x", pady=(8, 0))
    ttk.Button(buttons, text="Activate License…",
               style="Accent.TButton",
               command=lambda: show_license_activation(app)).pack(
                   side="left", padx=(0, 6))
    ttk.Button(buttons, text="Refresh", style="Accent.TButton",
               command=on_refresh).pack(side="left", padx=(0, 6))
    if service.provider.supports_deactivation:
        ttk.Button(buttons, text="Deactivate Device",
                   style="Accent.TButton",
                   command=on_deactivate).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Close",
               command=dialog.destroy).pack(side="right")
    render()
    return dialog


def show_license_activation(app=None):
    """License-key entry dialog (modeless; None when headless)."""
    from qs_engine.licensing.models import LicenseState, license_display
    service = _license_service_for(app)
    master = app if isinstance(app, tk.Widget) else None
    try:
        dialog = tk.Toplevel(master)
    except tk.TclError:
        return None
    dialog.title("Activate License")
    body = ttk.Frame(dialog, padding=12)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="License key:").pack(anchor="w")
    entry = ttk.Entry(body, width=36)
    entry.pack(fill="x", pady=(2, 6))
    entry.focus_set()
    status = ttk.Label(body, text="", style="Status.TLabel",
                       wraplength=420, justify="left")
    status.pack(anchor="w", pady=(0, 6))

    def on_activate():
        try:
            info = service.activate(entry.get())
        except Exception as exc:
            status.config(text=f"Activation failed: {exc}")
            return
        status.config(text=info.message
                      or license_display(info.state))
        if info.state == LicenseState.ACTIVE:
            entry.delete(0, "end")

    buttons = ttk.Frame(body)
    buttons.pack(fill="x")
    ttk.Button(buttons, text="Activate", style="Accent.TButton",
               command=on_activate).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Close",
               command=dialog.destroy).pack(side="right")
    return dialog


def make_grid(parent, columns, height=8):
    """Headed Treeview grid: {key: (heading, width)}."""
    tree = ttk.Treeview(parent, columns=list(columns),
                        show="headings", height=height)
    for key, (heading, width) in columns.items():
        tree.heading(key, text=heading)
        tree.column(key, width=width, anchor="w")
    return tree


def refresh_grid(tree, rows):
    """Replace grid content with row tuples (pure display update)."""
    for child in tree.get_children():
        tree.delete(child)
    for row in rows:
        tree.insert("", "end", values=tuple(row))


SCHEDULE_COLUMNS = {
    "trade": ("Trade", 90),
    "description": ("Description", 220),
    "unit": ("Unit", 70),
    "quantity": ("Quantity", 110),
    "rate": ("Rate", 110),
    "ref": ("Take-off Reference", 140),
}

BOQ_COLUMNS = {
    "item_no": ("Item No.", 80),
    "description": ("Description", 240),
    "unit": ("Unit", 70),
    "quantity": ("Quantity", 110),
    "rate": ("Rate", 110),
    "amount": ("Amount", 120),
    "status": ("Status", 110),
}


def _kv_value(lines, label: str):
    """Find a value by label in a FinishesView-style KV tuple."""
    for line in lines:
        if line.label == label:
            return line.value
    return None


def extract_takeoff_line(trade: str, view, inputs):
    """Build a TakeoffLine from a successful take-off view-model.

    Raises ValidationError with a UI-friendly message when the result
    cannot become a BOQ quantity (e.g. tiles without wastage).
    """
    from qs_engine.core.errors import ValidationError
    from .session import TakeoffLine
    element = (inputs.get("element") or "").strip()
    if trade == "concrete":
        return TakeoffLine(
            trade=trade,
            description=f"{element or 'Concrete'} ({view.class_key})",
            unit="m³", quantity=str(view.wet_m3), takeoff_ref=element)
    if trade == "masonry":
        return TakeoffLine(
            trade=trade,
            description=f"{element or 'Wall'} ({view.unit_key})",
            unit="piece", quantity=str(view.units_order),
            takeoff_ref=element)
    if trade == "rebar":
        return TakeoffLine(
            trade=trade, description=element or "Rebar schedule",
            unit="kg", quantity=str(view.total_mass_kg),
            takeoff_ref=element)
    if trade == "formwork":
        return TakeoffLine(
            trade=trade,
            description=(f"{element} ({view.element_type})".strip()
                         if element else
                         f"Formwork ({view.element_type})"),
            unit="m²", quantity=str(view.net_m2),
            takeoff_ref=element)
    if trade == "earthworks":
        return TakeoffLine(
            trade=trade, description=element or "Excavation",
            unit="m³", quantity=str(view.excavation_bank_m3),
            takeoff_ref=element)
    if trade == "finishes":
        kind = (inputs.get("kind") or "").strip()
        if kind in ("plaster", "screed"):
            volume = _kv_value(view.lines, "Volume (m³)")
            if volume is None:
                raise ValidationError(
                    "Finishes result has no volume to add")
            return TakeoffLine(
                trade=trade,
                description=f"{kind} {element}".strip() or kind,
                unit="m³", quantity=str(volume), takeoff_ref=element)
        if kind == "tiles":
            order = _kv_value(view.lines, "Order quantity")
            if order is None or order == "—":
                raise ValidationError(
                    "Tiles need an explicit wastage % before the order "
                    "quantity exists — set it, calculate, then add")
            return TakeoffLine(
                trade=trade,
                description=f"tiles {element}".strip() or "tiles",
                unit="piece", quantity=str(order), takeoff_ref=element)
        if kind == "paint":
            coated = _kv_value(view.lines, "Total coated (m²)")
            if coated is None:
                raise ValidationError(
                    "Paint result has no coated area to add")
            return TakeoffLine(
                trade=trade,
                description=f"paint {element}".strip() or "paint",
                unit="m²", quantity=str(coated), takeoff_ref=element)
        raise ValidationError(f"Unknown finishes kind {kind!r}")
    raise ValidationError(
        f"Trade {trade!r} has no take-off quantity mapping; its costs "
        f"flow through the rate builder instead")


def find_compiled_item(compiled, item_no):
    """Look up a CompiledItem by number (None when absent/stale)."""
    if compiled is None:
        return None
    for section in compiled.sections:
        for item in section.items:
            if item.item_no == item_no:
                return item
    return None


def apply_built_rate_to_line(session, index: int, gross_rate: str,
                             rate_ref: str = ""):
    """Assign a built gross rate to a take-off line (headless-testable).

    Validates the rate through the session store; the gross figure comes
    verbatim from a RateBuildupView and is never recalculated here.
    """
    return session.set_line_rate(index, gross_rate, rate_ref)


def persist_session_to_file(app, path) -> str:
    """Save the live session to a `.clk` file (returns a summary).

    Tracks the path on the app for File -> Save. Raises
    ValidationError (shown by the caller) instead of half-saving.
    """
    from qs_engine.persistence.project_file import save_session
    saved = save_session(app.session, path)
    app._project_path = saved
    return f"Saved project file to {saved}"


def restore_session_from_file(app, path) -> str:
    """Load a `.clk` (or legacy `.civolink`) file into the session.

    Hydration runs through the existing contracts, so stored data that
    no longer validates fails closed. Callers rebuild the current page
    afterwards so widgets reflect the restored state.
    """
    from qs_engine.persistence.project_file import load_session
    summary = load_session(app.session, path)
    app._project_path = str(path)
    return f"Restored project file: {summary}"


def build_overview_page(body, app):
    """Project dashboard: identity, schedule size, BOQ status."""
    build_page_header(
        body, "Project Overview",
        guide_key="overview",
        icon="📊")
    project = app.session.project
    if project.get("name") or project.get("reference"):
        lines = [f"{key.replace('_', ' ').title()}: {project.get(key, '')}"
                 for key in ("name", "reference", "client", "location",
                             "estimator", "currency", "pricing_basis",
                             "revision", "project_status")
                 if project.get(key)]
    else:
        lines = ["No project profile yet — open Project Setup."]
    if app.session.standard is None:
        lines.append("Measurement Standard: [Not Bound]")
    else:
        view = app.session.standard
        edition = f" ({view.edition})" if view.edition else ""
        lines.append(f"Measurement Standard: {view.standard}{edition} — "
                     f"{format_verification(view.known)}")
    counts = app.session.summary_counts()
    lines.append(f"Take-off lines: {counts['lines']}")
    for trade in sorted(counts["by_trade"]):
        lines.append(f"  {trade}: {counts['by_trade'][trade]}")
    compiled = app.session.last_compiled
    if compiled is None:
        lines.append("BOQ: not compiled yet — add lines, then Compile BOQ.")
    else:
        lines.append(f"BOQ: {len(compiled.unresolved_items)} unresolved, "
                     f"resolved subtotal {compiled.resolved_subtotal}")
        for ref in compiled.unresolved_items:
            lines.append(f"  ⚠ {ref}")

    # --- Master-data verification summary start ---
    from qs_engine.master_data.repository import MasterDataRepository
    repo = MasterDataRepository()
    # EVERY master-data domain counts here (all tables, all records) —
    # the overview must never under-report unverified engineering data.
    status_counts = {"VERIFIED": 0, "NEEDS_VERIFICATION": 0, "PROVISIONAL": 0}
    for domain in repo.domains():
        records = repo.list(domain)
        for rec in records:
            vs = rec.get("verification_status", "NEEDS_VERIFICATION")
            if vs in status_counts:
                status_counts[vs] += 1
    lines.append(f"Verification: {status_counts['VERIFIED']} verified, "
                 f"{status_counts['NEEDS_VERIFICATION']} needs verification, "
                 f"{status_counts['PROVISIONAL']} provisional")
    # --- Master-data verification summary end ---

    text = tk.Text(body, height=20, wrap="word", background="white")
    text.pack(fill="both", expand=True, pady=(8, 0))
    text.insert("end", "\n".join(lines))
    text.config(state="disabled")
    file_row = ttk.Frame(body)
    file_row.pack(fill="x", pady=(8, 0))

    def on_save_state():
        from tkinter import filedialog, messagebox
        from qs_engine.core.errors import ValidationError
        path = filedialog.asksaveasfilename(
            defaultextension=".clk",
            filetypes=[("CIVOLINK Project (*.clk)", "*.clk")])
        if not path:
            return
        try:
            summary = persist_session_to_file(app, path)
        except ValidationError as exc:
            messagebox.showerror("Save Project State", str(exc))
            return
        messagebox.showinfo("Save Project State", summary)
        app.refresh_status()

    def on_load_state():
        from tkinter import filedialog, messagebox
        from qs_engine.core.errors import ValidationError
        path = filedialog.askopenfilename(
            filetypes=[("CIVOLINK Project (*.clk; *.civolink)",
                        "*.clk *.civolink"),
                       ("All Files", "*.*")])
        if not path:
            return
        try:
            summary = restore_session_from_file(app, path)
        except ValidationError as exc:
            messagebox.showerror("Load Project State", str(exc))
            return
        messagebox.showinfo("Load Project State", summary)
        app.show("overview")

    ttk.Button(file_row, text="Save Project State…",
               style="Accent.TButton",
               command=on_save_state).pack(side="left", padx=(0, 6))
    ttk.Button(file_row, text="Load Project State…",
               style="Accent.TButton",
               command=on_load_state).pack(side="left")


def build_project_page(body, app):
    """Structured project setup: identity + measurement control."""
    build_page_header(
        body, "Project Setup", PANEL_INSTRUCTIONS["project"],
        guide_key="project",
        extra_guides=(("verification", VERIFICATION_GUIDE_TEXT,
                       "question"),),
        icon="⚙️")
    project = app.session.project
    ttk.Label(body, text="Project Identity",
              style="Section.TLabel").pack(anchor="w", pady=(6, 2))
    entries = {}
    identity_grid = ttk.Frame(body)
    identity_grid.pack(fill="x", pady=2)
    identity_grid.grid_columnconfigure(1, weight=1)
    identity_grid.grid_columnconfigure(3, weight=1)
    for rownum, pair in enumerate((
            (("name", "Project Name"),
             ("reference", "Project Reference")),
            (("client", "Client"),
             ("location", "Project Location")))):
        for half, (field, label) in enumerate(pair):
            ttk.Label(identity_grid, text=label,
                      width=20 if half == 0 else 18).grid(
                          row=rownum, column=half * 2,
                          padx=(0, 2) if half == 0 else (6, 2),
                          pady=2, sticky="w")
            entry = CueEntry(identity_grid, width=25,
                             cue=PROJECT_FIELD_CUES.get(field, ""))
            entry.set_value(project.get(field, ""))
            entry.grid(row=rownum, column=half * 2 + 1, padx=2, pady=2,
                       sticky="ew")
            entries[field] = entry
    ttk.Label(identity_grid, text="Prepared By / Estimator",
              width=20).grid(row=2, column=0, padx=(0, 2), pady=2,
                             sticky="w")
    estimator_entry = ttk.Entry(identity_grid, width=25)
    estimator_entry.insert(0, project.get("estimator", ""))
    estimator_entry.grid(row=2, column=1, columnspan=3, padx=2, pady=2,
                         sticky="ew")
    entries["estimator"] = estimator_entry
    ttk.Label(body, text="Measurement & Commercial Control",
              style="Section.TLabel").pack(anchor="w", pady=(6, 2))
    bound = app.session.standard
    entries_std = {}
    commercial = {}
    control_grid = ttk.Frame(body)
    control_grid.pack(fill="x", pady=2)
    control_grid.grid_columnconfigure(1, weight=1)
    control_grid.grid_columnconfigure(3, weight=1)
    ttk.Label(control_grid, text="Measurement Standard", width=20).grid(
        row=0, column=0, padx=(0, 2), pady=2, sticky="w")
    standard_entry = ttk.Combobox(
        control_grid, width=25,
        values=list(measurement_standard_choices()))
    standard_entry.insert(0, bound.standard if bound else "")
    standard_entry.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
    entries_std["standard"] = standard_entry
    ttk.Label(control_grid, text="Edition", width=14).grid(
        row=0, column=2, padx=(6, 2), pady=2, sticky="w")
    edition_entry = ttk.Combobox(control_grid, width=25)
    edition_entry.insert(0, bound.edition if bound else "")
    edition_entry.grid(row=0, column=3, padx=2, pady=2, sticky="ew")
    entries_std["edition"] = edition_entry
    for rownum, pair in enumerate((
            (("currency", "Currency"),
             ("pricing_basis", "Pricing Basis")),
            (("revision", "Revision"),
             ("project_status", "Project Status"))), start=1):
        for half, (field, label) in enumerate(pair):
            ttk.Label(control_grid, text=label,
                      width=20 if half == 0 else 14).grid(
                          row=rownum, column=half * 2,
                          padx=(0, 2) if half == 0 else (6, 2),
                          pady=2, sticky="w")
            entry = ttk.Entry(control_grid, width=25)
            entry.insert(0, project.get(field, ""))
            entry.grid(row=rownum, column=half * 2 + 1, padx=2, pady=2,
                       sticky="ew")
            commercial[field] = entry

    from qs_engine.core.errors import ValidationError
    from qs_engine.resources import (
        CODE_PATTERN_PRESETS,
        DEFAULT_PADDING,
        DEFAULT_SEPARATOR,
        DEFAULT_TEMPLATE,
        MATERIAL_CODE_PADDING_FIELD,
        MATERIAL_CODE_SEPARATOR_FIELD,
        MATERIAL_CODE_TEMPLATE_FIELD,
        POLICY_LABEL_CHOICES,
        MaterialCodePolicy,
        mode_from_label,
        policy_label,
    )
    try:
        active_policy = MaterialCodePolicy.from_project(project)
    except ValidationError:
        # An unreadable saved token fails closed at save time; the page
        # still opens by showing the default choice.
        active_policy = MaterialCodePolicy()

    # --- Material Coding Configuration (dynamic formatting) ---
    ttk.Label(control_grid, text="Material Code Formatting", width=20).grid(
        row=3, column=0, padx=(0, 2), pady=2, sticky="w")
    ui_labels = tuple(
        label for mode, label in (
            (m, policy_label(m)) for m in
            ("CATEGORY_PREFIX", "SEQUENTIAL_NUMERIC", "CUSTOM_PREFIX",
             "MANUAL")))
    policy_combo = ttk.Combobox(
        control_grid, width=25, state="readonly", values=list(ui_labels))
    policy_combo.set(policy_label(active_policy.mode))
    policy_combo.grid(row=3, column=1, padx=2, pady=2, sticky="ew")
    ttk.Label(control_grid, text="Custom Prefix", width=14).grid(
        row=3, column=2, padx=(6, 2), pady=2, sticky="w")
    prefix_entry = ttk.Entry(control_grid, width=25)
    prefix_entry.insert(0, active_policy.custom_prefix)
    prefix_entry.grid(row=3, column=3, padx=2, pady=2, sticky="ew")

    # Dynamic formatting controls (template, padding, separator)
    fmt_frame = ttk.LabelFrame(body, text="Material Coding Configuration")
    fmt_frame.pack(fill="x", pady=(6, 0))
    fmt_frame.grid_columnconfigure(1, weight=1)
    fmt_frame.grid_columnconfigure(3, weight=1)

    ttk.Label(fmt_frame, text="Format Pattern Template", width=22).grid(
        row=0, column=0, padx=(8, 2), pady=2, sticky="w")
    template_var = tk.StringVar(
        value=active_policy.format_template or DEFAULT_TEMPLATE)
    template_entry = ttk.Entry(fmt_frame, textvariable=template_var, width=30)
    template_entry.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
    ttk.Label(fmt_frame, text="Tokens: {PREFIX} {SEPARATOR} {SEQUENCE} "
              "{CATEGORY_ID}", style="Status.TLabel",
              wraplength=200, justify="left").grid(
                  row=0, column=2, columnspan=2, padx=(2, 8), pady=2,
                  sticky="w")

    ttk.Label(fmt_frame, text="Sequence Padding", width=22).grid(
        row=1, column=0, padx=(8, 2), pady=2, sticky="w")
    padding_var = tk.StringVar(
        value=str(active_policy.sequence_padding or DEFAULT_PADDING))
    padding_spin = ttk.Spinbox(
        fmt_frame, from_=1, to=10, width=5, textvariable=padding_var)
    padding_spin.grid(row=1, column=1, padx=2, pady=2, sticky="w")
    ttk.Label(fmt_frame, text="Separator", width=14).grid(
        row=1, column=2, padx=(6, 2), pady=2, sticky="w")
    separator_var = tk.StringVar(
        value=active_policy.separator if active_policy.separator is not None
        else DEFAULT_SEPARATOR)
    separator_entry = ttk.Entry(fmt_frame, textvariable=separator_var,
                                width=5)
    separator_entry.grid(row=1, column=3, padx=2, pady=2, sticky="w")

    # Live preview
    preview_var = tk.StringVar(value="")
    ttk.Label(fmt_frame, text="Preview:", width=22).grid(
        row=2, column=0, padx=(8, 2), pady=2, sticky="w")
    preview_label = ttk.Label(fmt_frame, textvariable=preview_var,
                              style="Status.TLabel")
    preview_label.grid(row=2, column=1, columnspan=3, padx=2, pady=2,
                       sticky="w")

    def _update_preview(*_args):
        try:
            padding = int(padding_var.get())
        except (ValueError, TypeError):
            padding = DEFAULT_PADDING
        preview_var.set(material_code_preview(
            policy_combo.get(),
            prefix_entry.get(),
            template_var.get(),
            padding,
            separator_var.get(),
        ))

    template_var.trace_add("write", _update_preview)
    padding_var.trace_add("write", _update_preview)
    separator_var.trace_add("write", _update_preview)
    prefix_entry.bind("<KeyRelease>", _update_preview)
    policy_combo.bind("<<ComboboxSelected>>", _update_preview)
    _update_preview()

    ttk.Label(
        control_grid,
        text="Applied to newly generated Material Codes; saved with the "
             "project file.",
        style="Status.TLabel", wraplength=240, justify="left").grid(
            row=4, column=0, columnspan=4, padx=(0, 2), pady=(2, 4),
            sticky="w")

    def all_editions():
        return tuple(
            edition
            for standard in measurement_standard_choices()
            for edition in measurement_edition_choices(standard))

    initial_editions = (measurement_edition_choices(bound.standard)
                        if bound and bound.standard
                        else all_editions())
    edition_entry.config(values=list(initial_editions))

    def refresh_edition_choices(_event=None):
        """Cascade editions from the selected standard (data kept)."""
        choices = (measurement_edition_choices(standard_entry.get())
                   or all_editions())
        edition_entry.config(values=list(choices))
        if edition_entry.get().strip() not in choices:
            edition_entry.set(choices[0])

    standard_entry.bind("<<ComboboxSelected>>", refresh_edition_choices)
    eng = ttk.LabelFrame(body, text="Engineering Inputs (Settings)")
    eng.pack(fill="x", pady=(6, 0))
    eng.grid_columnconfigure(0, weight=0)
    eng.grid_columnconfigure(1, weight=1)
    eng.grid_columnconfigure(2, weight=0)
    densities = {}
    for rownum, (field, label) in enumerate(CONCRETE_DENSITY_FIELDS):
        ttk.Label(eng, text=label, width=26).grid(
            row=rownum, column=0, padx=(8, 2), pady=2, sticky="w")
        entry = ttk.Entry(eng, width=25)
        entry.insert(0, project.get(field, ""))
        entry.grid(row=rownum, column=1, padx=2, pady=2, sticky="ew")
        densities[field] = entry
        ttk.Label(eng, text=density_field_status(
            field, project.get(field, ""), app.repository),
            style="Status.TLabel", wraplength=220,
            justify="left").grid(
                row=rownum, column=2, padx=(2, 8), pady=2, sticky="w")
    status = status_line(body)
    verify_label = ttk.Label(body, text="", style="Status.TLabel",
                             wraplength=640, justify="left")
    verify_label.pack(anchor="w", pady=(4, 0))

    def refresh_binding():
        bound_now = app.session.standard
        if bound_now is None:
            verify_label.config(text="Measurement Standard: [Not Bound]")
        else:
            edition = (f" ({bound_now.edition})"
                       if bound_now.edition else "")
            verify_label.config(
                text=f"Measurement Standard: {bound_now.standard}"
                     f"{edition} — {format_verification(bound_now.known)}")

    def on_save():
        from qs_engine.core.errors import ValidationError
        try:
            # Validate the Material Code Formatting choice before it is
            # stored: an unknown token or an empty Custom Prefix fails
            # closed here, never written into the profile/.clk.
            padding_val = None
            padding_raw = padding_var.get().strip()
            if padding_raw:
                try:
                    padding_val = int(padding_raw)
                except (ValueError, TypeError):
                    raise ValidationError(
                        f"Sequence padding must be a positive integer; "
                        f"got {padding_raw!r}")
            code_policy = MaterialCodePolicy(
                mode_from_label(policy_combo.get()),
                prefix_entry.get(),
                format_template=template_var.get().strip() or None,
                sequence_padding=padding_val,
                separator=separator_var.get() or None,
            )
            # The formatting controls pre-fill the *effective* defaults
            # (template/padding/separator) while MaterialCodePolicy()
            # keeps them None ("inherit"): strip values that merely
            # repeat those defaults, so an untouched form is not a
            # deviation - otherwise every save merges policy fields,
            # a cue-only save stops being refused, and ghost text
            # lands in the profile.
            from dataclasses import replace
            if code_policy.format_template == DEFAULT_TEMPLATE:
                code_policy = replace(code_policy, format_template=None)
            if code_policy.sequence_padding == DEFAULT_PADDING:
                code_policy = replace(code_policy, sequence_padding=None)
            if code_policy.separator == DEFAULT_SEPARATOR:
                code_policy = replace(code_policy, separator=None)
            profile = {
                **{key: widget.get()
                   for key, widget in entries.items()},
                **{key: widget.get()
                   for key, widget in commercial.items()},
                **{key: widget.get()
                   for key, widget in densities.items()}}
            if code_policy != MaterialCodePolicy():
                # Only deviations from the default policy are stored, so
                # an otherwise-empty form still refuses to save (a cue-
                # only page never writes a ghost profile) while an
                # explicitly chosen policy always round-trips to .clk.
                profile.update(code_policy.project_fields())
            app.session.save_project(**profile)
        except ValidationError as exc:
            status.config(text=str(exc))
            app.refresh_status()
            return
        status.config(text="● Saved project profile")
        app.refresh_status()

    def on_bind():
        result = controllers.project_setup_controller(
            standard=standard_entry.get(), edition=edition_entry.get())
        if isinstance(result, ErrorView):
            status.config(text=result.message)
            return
        app.session.standard = result
        refresh_binding()
        status.config(text="\u25cf Saved measurement binding")
        app.refresh_status()

    buttons = ttk.Frame(body)
    buttons.pack(fill="x", pady=6)
    ttk.Button(buttons, text="Save Profile", style="Accent.TButton",
               command=on_save).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Bind Standard", style="Accent.TButton",
               command=on_bind).pack(side="left")
    file_buttons = ttk.Frame(body)
    file_buttons.pack(fill="x", pady=(0, 6))

    def on_save_file():
        from tkinter import filedialog
        from qs_engine.core.errors import ValidationError
        path = filedialog.asksaveasfilename(
            defaultextension=".clk",
            filetypes=[("CIVOLINK Project (*.clk)", "*.clk")])
        if not path:
            return
        try:
            summary = persist_session_to_file(app, path)
        except ValidationError as exc:
            status.config(text=str(exc))
            app.refresh_status()
            return
        status.config(text=f"\u25cf {summary}")
        app.refresh_status()

    def on_load_file():
        from tkinter import filedialog
        from qs_engine.core.errors import ValidationError
        path = filedialog.askopenfilename(
            filetypes=[("CIVOLINK Project (*.clk; *.civolink)",
                        "*.clk *.civolink"),
                       ("All Files", "*.*")])
        if not path:
            return
        try:
            restore_session_from_file(app, path)
        except ValidationError as exc:
            status.config(text=str(exc))
            app.refresh_status()
            return
        app.show("project")

    ttk.Button(file_buttons, text="Save Project File…",
               style="Accent.TButton",
               command=on_save_file).pack(side="left", padx=(0, 6))
    ttk.Button(file_buttons, text="Load Project File…",
               style="Accent.TButton",
               command=on_load_file).pack(side="left")
    refresh_binding()


def build_materials_page(body, app):
    """Materials catalogue: read-only seed table + user override materials.

    The seed catalogue comes straight from master data (managed through
    controlled configuration files — seed files are never written by the
    application). User materials are created/edited through the Phase 25
    override store and carry identifiers only; an em-dash marks every
    null (null-numeric rule) — values are never invented; pricing
    arrives per call through the Rate Builder.
    """
    build_page_header(
        body, "Materials Catalogue",
        guide_key="materials",
        icon="📦")
    status = status_line(body)
    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=(6, 0))

    def refresh_catalogue():
        try:
            refresh_grid(grid, material_catalogue_rows(
                app.repository, policy=active_material_code_policy(app)))
        except Exception as exc:
            status.config(text=f"Could not load materials catalogue: {exc}")

    #: Alias kept for the modal save & refresh loop: the grid refresh is
    #: triggered the moment a saved material lands, so the new row is
    #: visible without a manual reload.
    refresh_materials_grid = refresh_catalogue

    def on_material_saved(record):
        refresh_materials_grid()
        status.config(
            text=f"✓ Saved {record.get('code', record.get('key', ''))} — "
                 f"seed catalogue untouched")

    def _require_stack():
        stack = getattr(app, "material_stack", None)
        store = getattr(stack, "store", None) if stack is not None else None
        if store is None:
            error = getattr(app, "material_store_error", None)
            status.config(
                text=("Material editing unavailable: "
                      + (error or "read-only repository in this session")))
            return None
        return stack

    def on_add():
        if _require_stack() is not None:
            material_editor_dialog(app, on_saved=on_material_saved)

    def on_edit_selected():
        stack = _require_stack()
        if stack is None:
            return
        selection = grid.selection()
        if not selection:
            status.config(text="Select a material to edit first.")
            return
        values = grid.item(selection[0], "values")
        record = resolve_material_reference(app, str(values[0]))
        if record is None:
            status.config(text=f"Could not load record: {values[0]}")
            return
        if str(record.get("key", "")).startswith("user:"):
            # User material: "Edit User Material" with the code locked.
            material_editor_dialog(app, record=record,
                                   on_saved=on_material_saved,
                                   mode="edit_user")
        else:
            # Seed material: "Customize Material (Create User Override)"
            # — a fresh policy-assigned code; the seed row stays read-only.
            material_editor_dialog(app, record=record,
                                   on_saved=on_material_saved,
                                   mode="customize_seed")

    ttk.Button(actions, text="Add Material…", style="Accent.TButton",
               command=on_add).pack(side="left", padx=(0, 6))
    ttk.Button(actions, text="Edit Selected",
               command=on_edit_selected).pack(side="left")

    card = ttk.LabelFrame(body, text="Catalogue")
    card.pack(fill="both", expand=True, pady=(6, 0))
    grid = make_grid(card, MATERIALS_COLUMNS)
    grid.pack(fill="both", expand=True)
    toolbar, details = catalogue_browser(body, app, grid, status)
    toolbar.pack(fill="x", pady=(0, 4), before=card)
    details.pack(fill="x", pady=(6, 0))
    try:
        refresh_grid(grid, material_catalogue_rows(
            app.repository, policy=active_material_code_policy(app)))
    except Exception as exc:
        status.config(text=f"Could not load materials catalogue: {exc}")
    app.refresh_status()


def build_reconciliation_page(body, app):
    """Site material reconciliation (Phase 6.2): theoretical QS
    allowances vs actual site consumption.

    Imports a site store log (.xlsx/.csv), resolves each site material
    reference against the active MaterialResolver (master keys, user
    codes, policy display codes), and reconciles net BOQ quantities
    grossed up by wastage against store issue vouchers. Unmatched site
    lines are flagged in the status line — never silently dropped.
    Monetary values only appear where a rate actually exists.
    """
    from qs_engine.core.decimal_policy import to_decimal
    from qs_engine.core.errors import ValidationError
    from qs_engine.reconciliation import (
        STATUS_NORMAL,
        export_variance_report,
        import_store_log,
        reconcile,
    )

    build_page_header(
        body, "Site Reconciliation",
        guide_key="reconciliation",
        icon="🧾")
    status = status_line(body)

    # -- store log import ---------------------------------------------------
    import_card = ttk.LabelFrame(body, text="Store Log Import")
    import_card.pack(fill="x", pady=(6, 0))
    path_row = ttk.Frame(import_card)
    path_row.pack(fill="x", padx=6, pady=(6, 2))
    ttk.Label(path_row, text="Store log (.xlsx / .csv):").pack(side="left")
    # master=app keeps the variable on this app's root: a bare
    # StringVar() binds to the process default root, which in a
    # multi-root session (tests) is another window — the entry text
    # and the variable then fall out of sync.
    path_var = tk.StringVar(master=app)
    path_entry = ttk.Entry(path_row, textvariable=path_var, width=48)
    path_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))

    def on_browse():
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            filetypes=[("Site store log", "*.xlsx *.xlsm *.csv"),
                       ("Excel workbook", "*.xlsx *.xlsm"),
                       ("CSV log", "*.csv")])
        if path:
            path_var.set(path)

    ttk.Button(path_row, text="Browse…", command=on_browse).pack(side="left")
    threshold_row = ttk.Frame(import_card)
    threshold_row.pack(fill="x", padx=6, pady=(0, 6))
    ttk.Label(threshold_row, text="Overrun alert threshold (%):").pack(
        side="left")
    threshold_var = tk.StringVar(master=app, value="5")
    threshold_entry = ttk.Entry(threshold_row, textvariable=threshold_var,
                                width=8)
    threshold_entry.pack(side="left", padx=(6, 12))
    ttk.Label(threshold_row, text="Critical = threshold × 2",
              style="Status.TLabel").pack(side="left")

    state = {"summary": None}

    # -- summary metrics ----------------------------------------------------
    metrics = ttk.Frame(body)
    metrics.pack(fill="x", pady=(6, 0))
    metric_values = {}
    for label_text, key in (
            ("Total Materials Tracked", "total_materials_tracked"),
            ("Theoretical Budget Value", "theoretical_budget_value"),
            ("Actual Issued Value", "actual_issued_value"),
            ("Overall Material Variance", "overall_variance_value")):
        card = ttk.LabelFrame(metrics, text=label_text)
        card.pack(side="left", fill="both", expand=True, padx=4)
        value = ttk.Label(card, text="—", style="Header.TLabel")
        value.pack(anchor="w", padx=8, pady=6)
        metric_values[key] = value

    def refresh_metrics():
        summary = state["summary"]
        if summary is None:
            for value in metric_values.values():
                value.config(text="—", foreground="")
            return
        values = {
            "total_materials_tracked": str(summary.total_materials_tracked),
            "theoretical_budget_value": (
                "—" if summary.theoretical_budget_value is None
                else str(summary.theoretical_budget_value)),
            "actual_issued_value": (
                "—" if summary.actual_issued_value is None
                else str(summary.actual_issued_value)),
            "overall_variance_value": (
                "—" if summary.overall_variance_value is None
                else str(summary.overall_variance_value)),
        }
        for key, text in values.items():
            metric_values[key].config(text=text)
        variance = summary.overall_variance_value
        if variance is not None and variance > 0:
            metric_values["overall_variance_value"].config(
                foreground=BAD_RED)
        elif variance is not None and variance < 0:
            metric_values["overall_variance_value"].config(
                foreground=OK_GREEN)
        else:
            metric_values["overall_variance_value"].config(foreground="")

    # -- variance grid -------------------------------------------------------
    grid_card = ttk.LabelFrame(body, text="Material Variance")
    grid_card.pack(fill="both", expand=True, pady=(6, 0))
    grid = make_grid(grid_card, RECONCILIATION_COLUMNS)
    grid.pack(fill="both", expand=True)
    grid.tag_configure("WARNING", background="#FFEB9C")
    grid.tag_configure("CRITICAL_OVERRUN", background="#FFC7CE")

    def refresh_grid():
        for child in grid.get_children():
            grid.delete(child)
        summary = state["summary"]
        if summary is None:
            return
        for row in summary.rows:
            grid.insert("", "end", values=(
                row.code, row.name, row.unit,
                str(row.theoretical_qty), str(row.actual_issued),
                str(row.store_balance), str(row.variance_qty),
                ("" if row.variance_pct is None else str(row.variance_pct)),
                row.status), tags=(row.status,) if row.status != STATUS_NORMAL
                                  else ())

    def on_import():
        path = path_var.get().strip()
        if not path:
            status.config(text="Choose a store log file first.")
            return
        try:
            policy = active_material_code_policy(app)
            transactions, warnings = import_store_log(
                path, resolver=app.repository, policy=policy)
            threshold = to_decimal(threshold_var.get(), "threshold")
            summary = reconcile(
                app.session.last_compiled, transactions,
                resolver=app.repository, warning_threshold_pct=threshold)
        except (ValidationError, TypeError, ValueError) as exc:
            status.config(text=str(exc))
            return
        app.session.store_transactions = transactions
        state["summary"] = summary
        refresh_grid()
        refresh_metrics()
        if app.session.last_compiled is None:
            status.config(
                text="⚠ No compiled BOQ — theoretical allowances are "
                     "zero; compile on the BOQ View first.")
            return
        if warnings:
            extra = (f" (+{len(warnings) - 1} more)"
                     if len(warnings) > 1 else "")
            status.config(text=f"⚠ {warnings[0]}{extra}")
        else:
            status.config(
                text=f"✓ Imported {len(transactions)} store transactions")

    def on_export():
        summary = state["summary"]
        if summary is None:
            status.config(text="Import a store log first.")
            return
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return
        try:
            export_variance_report(path, summary)
        except ValidationError as exc:
            status.config(text=str(exc))
            return
        status.config(text=f"✓ Variance report saved: {path}")

    buttons = ttk.Frame(body)
    buttons.pack(fill="x", pady=6)
    ttk.Button(buttons, text="Import Store Log", style="Accent.TButton",
               command=on_import).pack(side="left", padx=(0, 6))
    ttk.Button(buttons, text="Export Variance Report…",
               style="Accent.TButton",
               command=on_export).pack(side="left")
    app.refresh_status()


def category_editor_dialog(parent, registry, on_added=None):
    """Create a user category ('+ Add Custom Category…').

    Updates the effective category registry (seed + user) without ever
    writing seed category data; duplicate/seed-shadowing names are
    rejected with a typed error shown in the dialog. Supports optional
    formatting parameters (prefix, GL code, GL description, template,
    padding, separator). Returns a handle dict, or None when headless.
    """
    master = parent if isinstance(parent, tk.Widget) else None
    try:
        dialog = tk.Toplevel(master)
    except tk.TclError:
        return None
    dialog.title("Add Custom Category")
    if master is not None:
        dialog.transient(master)
    form = ttk.Frame(dialog, padding=12)
    form.pack(fill="both", expand=True)
    ttk.Label(form, text="Category name:").grid(
        row=0, column=0, sticky="w", pady=(0, 6))
    name_var = tk.StringVar()
    name_entry = ttk.Entry(form, textvariable=name_var, width=32)
    name_entry.grid(row=0, column=1, sticky="we", pady=(0, 6), padx=(8, 0))

    ttk.Label(form, text="Prefix:").grid(
        row=1, column=0, sticky="w", pady=2)
    prefix_var = tk.StringVar()
    prefix_entry = ttk.Entry(form, textvariable=prefix_var, width=15)
    prefix_entry.grid(row=1, column=1, sticky="w", pady=2, padx=(8, 0))

    ttk.Label(form, text="SAP / GL Code:").grid(
        row=2, column=0, sticky="w", pady=2)
    gl_var = tk.StringVar()
    gl_entry = ttk.Entry(form, textvariable=gl_var, width=15)
    gl_entry.grid(row=2, column=1, sticky="w", pady=2, padx=(8, 0))

    ttk.Label(form, text="GL Description:").grid(
        row=3, column=0, sticky="w", pady=2)
    gl_desc_var = tk.StringVar()
    gl_desc_entry = ttk.Entry(form, textvariable=gl_desc_var, width=32)
    gl_desc_entry.grid(row=3, column=1, sticky="we", pady=2, padx=(8, 0))

    ttk.Label(form, text="Format Template:").grid(
        row=4, column=0, sticky="w", pady=2)
    template_var = tk.StringVar()
    template_entry = ttk.Entry(form, textvariable=template_var, width=32)
    template_entry.grid(row=4, column=1, sticky="we", pady=2, padx=(8, 0))

    ttk.Label(form, text="Sequence Padding:").grid(
        row=5, column=0, sticky="w", pady=2)
    padding_var = tk.StringVar()
    padding_entry = ttk.Entry(form, textvariable=padding_var, width=5)
    padding_entry.grid(row=5, column=1, sticky="w", pady=2, padx=(8, 0))

    ttk.Label(form, text="Separator:").grid(
        row=6, column=0, sticky="w", pady=2)
    separator_var = tk.StringVar()
    separator_entry = ttk.Entry(form, textvariable=separator_var, width=5)
    separator_entry.grid(row=6, column=1, sticky="w", pady=2, padx=(8, 0))

    status = ttk.Label(form, text="", style="Status.TLabel",
                       wraplength=340, justify="left")
    status.grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 8))
    handle = {"dialog": dialog, "name": name_entry, "status": status,
              "prefix": prefix_entry, "gl_code": gl_entry,
              "gl_description": gl_desc_entry, "template": template_entry,
              "padding": padding_entry, "separator": separator_entry,
              "result": None}

    def _add():
        try:
            padding_val = None
            padding_raw = padding_var.get().strip()
            if padding_raw:
                try:
                    padding_val = int(padding_raw)
                except (ValueError, TypeError):
                    from qs_engine.core.errors import ValidationError
                    raise ValidationError(
                        f"Sequence padding must be a positive integer; "
                        f"got {padding_raw!r}")
            record = registry.add_custom_category(
                name_var.get(),
                prefix=prefix_var.get(),
                sap_gl_code=gl_var.get(),
                gl_description=gl_desc_var.get(),
                format_template=template_var.get().strip() or None,
                sequence_padding=padding_val,
                separator=separator_var.get() or None,
            )
        except QSEngineError as exc:
            status.config(text=f"Not added: {exc}")
            return
        handle["result"] = record
        if on_added is not None:
            on_added(record)
        dialog.destroy()

    def _cancel():
        dialog.destroy()

    buttons = ttk.Frame(form)
    buttons.grid(row=8, column=0, columnspan=2, sticky="e")
    add_button = ttk.Button(buttons, text="Add Category",
                            style="Accent.TButton", command=_add)
    add_button.pack(side="left", padx=(0, 6))
    cancel_button = ttk.Button(buttons, text="Cancel", command=_cancel)
    cancel_button.pack(side="left")
    handle["add"] = add_button
    handle["cancel"] = cancel_button
    name_entry.focus_set()
    return handle


#: Sentinel entry in the category picker that opens the custom-category
#: dialog (creating a category updates the effective registry only).
ADD_CATEGORY_LABEL = "+ Add Custom Category…"


def active_material_code_policy(app):
    """The project's active MaterialCodePolicy (default when unset)."""
    from qs_engine.core.errors import ValidationError
    from qs_engine.resources import MaterialCodePolicy
    session = getattr(app, "session", None)
    project = getattr(session, "project", None) or {}
    try:
        return MaterialCodePolicy.from_project(project)
    except ValidationError:
        # An unknown saved token fails closed at the Project Setup save
        # point (validated before writing); a suggestion path falls back
        # to the default policy so the dialog stays usable.
        return MaterialCodePolicy()


def material_display_code_index(app):
    """casefold(display code) -> seed record, under the active policy.

    Presentation index only: it never feeds availability checks or
    suggestion, so a display code can never shadow an explicit
    identity. Empty when the repository cannot be listed.
    """
    repository = getattr(app, "repository", None)
    if repository is None:
        return {}
    try:
        records = repository.list("materials")
    except Exception:
        return {}
    policy = active_material_code_policy(app)
    seed_records = [record for record in records
                    if not str(record.get("key", "")).startswith("user:")]
    index = {}
    for record in seed_records:
        code = policy.resolve_display_code(record, seed_records=seed_records)
        if code:
            index.setdefault(code.casefold(), record)
    return index


def resolve_material_reference(app, ref):
    """Record for one catalogue reference: identity first, then display code.

    A reference that already resolves (seed key, user canonical key,
    user code or alias) is returned unchanged; only an unresolved
    reference falls back to the active policy's display-code index, so
    a display code can never shadow an explicit identity. None when
    nothing matches.
    """
    repository = getattr(app, "repository", None)
    if repository is None:
        return None
    text = str(ref or "").strip()
    if not text:
        return None
    try:
        return repository.get("materials", text)
    except Exception:
        pass
    return material_display_code_index(app).get(text.casefold())


def resolve_rate_line_material_keys(app, lines):
    """Translate catalogue display codes to record keys before the engine.

    Only references that do NOT already resolve are translated, so an
    explicit identity (seed key, user code) is never rewritten; a
    display code the estimator typed or handed off from the catalogue
    resolves to the same record it names.
    """
    repository = getattr(app, "repository", None)
    if repository is None:
        return list(lines)
    try:
        repository.list("materials")
    except Exception:
        return list(lines)
    index = material_display_code_index(app)
    resolved = []
    for line in lines:
        if (isinstance(line, dict)
                and str(line.get("kind", "")).strip().lower() == "material"):
            ref = str(line.get("material_key", "") or "").strip()
            if ref:
                try:
                    repository.get("materials", ref)
                except Exception:
                    match = index.get(ref.casefold())
                    if match is not None:
                        line = {**line,
                                "material_key": str(match.get("key", ""))}
        resolved.append(line)
    return resolved


def material_code_suggestions(app, name, category=None, policy=None):
    """Free code for one material under the project's active policy.

    Availability spans BOTH sources the resolver sees: the core seed
    catalogue and ``user_materials.json`` (via
    ``MaterialResolver.existing_codes()``). Returns "" under the MANUAL
    policy — the field stays empty for explicit user entry, and no
    code path ever concatenates a hardcoded prefix onto a generated
    suggestion.
    """
    from qs_engine.resources import MaterialCodePolicy
    active = (policy if policy is not None
              else active_material_code_policy(app))
    repository = getattr(app, "repository", None)
    if repository is not None and hasattr(repository, "suggest_code"):
        return repository.suggest_code(name, category=category,
                                       policy=active)
    taken = []
    if repository is not None:
        for record in repository.list("materials"):
            for field in ("key", "code", "legacy_code"):
                value = str(record.get(field, "") or "").strip()
                if value:
                    taken.append(value)
    stack = getattr(app, "material_stack", None)
    store = getattr(stack, "store", None) if stack is not None else None
    if store is not None:
        taken.extend(store.existing_codes())
    return active.suggest(name, category=category, taken=taken)


def material_editor_dialog(app, record=None, on_saved=None, *, mode=None):
    """Create, edit, or customize a user material through the store.

    Modes (``mode`` keyword; inferred from ``record`` when omitted):

    * ``add`` (no record) — new user material. The Material Code field
      starts with a suggestion from the project's active
      MaterialCodePolicy (empty under the Manual policy) and stays
      editable.
    * ``edit_user`` — "Edit User Material": name, category and unit
      pre-populated. When the catalogue's Edit Selected button opens
      the dialog (explicit ``mode``) the Material Code field is
      ``state="disabled"`` — codes stay assigned, never retyped; a
      direct ``record=`` call keeps the historical editable-code
      behaviour.
    * ``customize_seed`` — "Customize Material (Create User Override)":
      seed values pre-filled into a NEW user override carrying a fresh
      non-conflicting code from the active policy, plus an
      informational banner stating the seed catalogue stays read-only.

    Editable fields: Material Name, Material Code (unless disabled),
    Category, Default Unit. The suggested code follows the project's
    active policy (``qs_engine.resources.code_policy``) — no hardcoded
    ``MAT-`` formatting anywhere, so a redundant prefix can never be
    concatenated onto an already-prefixed suggestion. Engineering
    properties are deliberately NOT offered — a saved material carries
    identifiers only and stays NEEDS_VERIFICATION for every downstream
    calculation. Returns a handle dict (widgets + result), or None when
    headless or when the session has no writable override store.
    """
    from qs_engine.core.errors import ValidationError
    from qs_engine.core.units import SUPPORTED_UNITS

    stack = getattr(app, "material_stack", None)
    store = getattr(stack, "store", None) if stack is not None else None
    registry = getattr(stack, "registry", None) if stack is not None else None
    if store is None or registry is None:
        return None
    parent = app if isinstance(app, tk.Widget) else None
    try:
        dialog = tk.Toplevel(parent)
    except tk.TclError:
        return None
    key = str(record.get("key", "")) if record is not None else ""
    explicit_mode = mode is not None
    if mode is None:
        mode = ("add" if record is None
                else ("edit_user" if key.startswith("user:")
                      else "customize_seed"))
    if mode not in ("add", "edit_user", "customize_seed"):
        dialog.destroy()
        raise ValidationError(
            f"Unknown material editor mode {mode!r}; expected add, "
            f"edit_user or customize_seed")
    customizing = mode == "customize_seed"
    policy = active_material_code_policy(app)
    # Locked code: seed customization always (the policy assigns the
    # override's new code), and user-material edits opened through the
    # catalogue's Edit Selected button (explicit mode).
    code_disabled = (customizing and policy.mode != "MANUAL") or (
        mode == "edit_user" and explicit_mode)
    dialog.title({"add": "Add Material",
                  "edit_user": "Edit User Material",
                  "customize_seed":
                      "Customize Material (Create User Override)"}[mode])
    if parent is not None:
        dialog.transient(parent)
    form = ttk.Frame(dialog, padding=12)
    form.pack(fill="both", expand=True)

    prefill = record if mode != "add" else None
    name_var = tk.StringVar(
        value=str(prefill.get("name", "")) if prefill is not None else "")
    code_var = tk.StringVar(
        value=(str(prefill.get("code", ""))
               if mode == "edit_user" and prefill is not None else ""))
    unit_var = tk.StringVar(
        value=str(prefill.get("unit", "")) if prefill is not None else "")

    ttk.Label(form, text="Material Name:").grid(
        row=0, column=0, sticky="w", pady=2)
    name_entry = ttk.Entry(form, textvariable=name_var, width=40)
    name_entry.grid(row=0, column=1, sticky="we", pady=2, padx=(8, 0))
    ttk.Label(form, text="Material Code:").grid(
        row=1, column=0, sticky="w", pady=2)
    code_entry = ttk.Entry(form, textvariable=code_var, width=40)
    code_entry.grid(row=1, column=1, sticky="we", pady=2, padx=(8, 0))
    if code_disabled:
        code_entry.configure(state="disabled")
    ttk.Label(form, text="Category:").grid(
        row=2, column=0, sticky="w", pady=2)
    category_combo = ttk.Combobox(form, state="readonly", width=37)
    category_combo.grid(row=2, column=1, sticky="we", pady=2, padx=(8, 0))
    ttk.Label(form, text="Default Unit:").grid(
        row=3, column=0, sticky="w", pady=2)
    unit_combo = ttk.Combobox(
        form, textvariable=unit_var, state="readonly", width=37,
        values=sorted(SUPPORTED_UNITS))
    unit_combo.grid(row=3, column=1, sticky="we", pady=2, padx=(8, 0))
    if unit_var.get():
        unit_combo.set(unit_var.get())

    # Auto-populated registry fields (read-only)
    ttk.Label(form, text="Prefix:").grid(
        row=4, column=0, sticky="w", pady=2)
    prefix_var = tk.StringVar(value="")
    prefix_entry = ttk.Entry(form, textvariable=prefix_var, width=15,
                             state="readonly")
    prefix_entry.grid(row=4, column=1, sticky="w", pady=2, padx=(8, 0))
    ttk.Label(form, text="SAP / GL Code:").grid(
        row=5, column=0, sticky="w", pady=2)
    gl_var = tk.StringVar(value="")
    gl_entry = ttk.Entry(form, textvariable=gl_var, width=15,
                         state="readonly")
    gl_entry.grid(row=5, column=1, sticky="w", pady=2, padx=(8, 0))
    ttk.Label(form, text="GL Description:").grid(
        row=6, column=0, sticky="w", pady=2)
    gl_desc_var = tk.StringVar(value="")
    gl_desc_entry = ttk.Entry(form, textvariable=gl_desc_var, width=40,
                              state="readonly")
    gl_desc_entry.grid(row=6, column=1, sticky="we", pady=2, padx=(8, 0))

    next_row = 7
    banner = None
    if customizing:
        if code_disabled:
            banner_text = (
                "Creating a user override of seed material "
                f"\u201c{name_var.get() or key}\u201d with the assigned "
                "code above \u2014 the seed catalogue stays read-only.")
        else:
            banner_text = (
                "Creating a user override of seed material "
                f"\u201c{name_var.get() or key}\u201d \u2014 enter a "
                "Material Code; the seed catalogue stays read-only.")
        banner = ttk.Label(form, text=banner_text, style="Status.TLabel",
                           wraplength=400, justify="left")
        banner.grid(row=next_row, column=0, columnspan=2, sticky="w",
                    pady=(4, 0))
        next_row += 1
    status = ttk.Label(form, text="", style="Status.TLabel",
                       wraplength=400, justify="left")
    status.grid(row=next_row, column=0, columnspan=2, sticky="w",
                pady=(8, 4))
    next_row += 1

    handle = {"dialog": dialog, "name": name_entry, "code": code_entry,
              "category": category_combo, "unit": unit_combo,
              "prefix": prefix_entry, "gl_code": gl_entry,
              "gl_description": gl_desc_entry,
              "status": status, "banner": banner, "result": None}

    def _label_map():
        return {entry["category_name"]: entry["category_id"]
                for entry in registry.list_categories()}

    label_to_id = _label_map()

    def refresh_categories(select_name=None):
        nonlocal label_to_id
        label_to_id = _label_map()
        category_combo.configure(
            values=list(label_to_id) + [ADD_CATEGORY_LABEL])
        if select_name and select_name in label_to_id:
            category_combo.set(select_name)

    if mode != "add" and record is not None:
        category_combo.set(
            str(record.get("category_name")
                or record.get("category", "")))
    elif label_to_id:
        category_combo.set(next(iter(label_to_id)))
    refresh_categories(select_name=category_combo.get())
    last_category = {"name": category_combo.get()}

    def _category_ref():
        picked = category_combo.get()
        if picked == ADD_CATEGORY_LABEL:
            picked = last_category["name"]
        return picked

    code_dirty = mode == "edit_user"

    def _refresh_suggestion():
        # The suggestion tracks name + category only until the user
        # edits the code; locked fields and the Manual policy leave the
        # field exactly as assigned (empty for Manual — explicit entry).
        if code_dirty or code_disabled:
            return
        code_var.set(material_code_suggestions(
            app, name_var.get(), category=_category_ref(), policy=policy))

    if mode == "customize_seed":
        code_var.set(material_code_suggestions(
            app, str(record.get("name", "") or ""),
            category=str(record.get("category_name")
                         or record.get("category", "") or ""),
            policy=policy))
    elif mode == "add":
        _refresh_suggestion()

    def on_name_key(_event=None):
        _refresh_suggestion()

    def on_code_key(_event=None):
        nonlocal code_dirty
        code_dirty = True

    def _update_registry_fields():
        """Auto-populate read-only registry fields from the selected category."""
        try:
            cat = registry.resolve_category(_category_ref())
            prefix_var.set(cat.prefix)
            gl_var.set(cat.sap_gl_code)
            gl_desc_var.set(cat.gl_description)
        except Exception:
            prefix_var.set("")
            gl_var.set("")
            gl_desc_var.set("")

    def on_category_selected(_event=None):
        picked = category_combo.get()
        if picked == ADD_CATEGORY_LABEL:
            category_combo.set(last_category["name"])

            def _added(created):
                last_category["name"] = created["category_name"]
                refresh_categories(select_name=created["category_name"])
                _update_registry_fields()

            category_editor_dialog(dialog, registry, on_added=_added)
        else:
            last_category["name"] = picked
        _update_registry_fields()
        _refresh_suggestion()

    name_entry.bind("<KeyRelease>", on_name_key)
    code_entry.bind("<KeyRelease>", on_code_key)
    category_combo.bind("<<ComboboxSelected>>", on_category_selected)
    _update_registry_fields()

    def _save():
        dto = {"name": name_var.get(),
               "category_id": _category_ref(),
               "unit": unit_var.get()}
        if not (mode == "edit_user" and code_disabled):
            # Disabled code fields never submit; every other path sends
            # the shown code (assigned suggestion or user's entry).
            dto["code"] = code_var.get()
        try:
            if mode == "edit_user":
                # User material update -> update_material (identity kept;
                # a changed code retires the old one into aliases).
                saved = store.update_material(key, dto)
            else:
                # New material AND seed customization both create a user
                # override through add_material — seed stays read-only.
                saved = store.add_material(dto)
        except QSEngineError as exc:
            # Fail closed in the dialog — never a partial or silent save.
            status.config(text=f"Not saved: {exc}")
            return
        handle["result"] = saved
        if on_saved is not None:
            on_saved(saved)
        dialog.destroy()

    def _cancel():
        dialog.destroy()

    buttons = ttk.Frame(form)
    buttons.grid(row=next_row, column=0, columnspan=2, sticky="e",
                 pady=(8, 0))
    save_button = ttk.Button(buttons, text="Save Material",
                             style="Accent.TButton", command=_save)
    save_button.pack(side="left", padx=(0, 6))
    cancel_button = ttk.Button(buttons, text="Cancel", command=_cancel)
    cancel_button.pack(side="left")
    handle["save"] = save_button
    handle["cancel"] = cancel_button
    name_entry.focus_set()
    return handle


def build_estimate_page(body, app):
    """Cost Summary Dashboard derived from BOQ document data."""
    build_page_header(
        body, "Estimate",
        guide_key="estimate",
        icon="💵")
    from qs_engine.core.errors import ValidationError
    status = status_line(body)
    compiled = app.session.last_compiled
    if compiled is None:
        ttk.Label(body, text="No compiled BOQ in this session yet — "
                             "compile it on the BOQ View first.",
                  style="Status.TLabel", wraplength=640,
                  justify="left").pack(anchor="w", pady=(8, 0))
        app.refresh_status()
        return
    try:
        summary = estimate_cost_groups(compiled)
    except ValidationError as exc:
        status.config(text=str(exc))
        app.refresh_status()
        return
    card = ttk.LabelFrame(body, text="Cost Summary")
    card.pack(fill="x", pady=(6, 0))
    summary_rows = []
    for key, label, total, partial in summary["groups"]:
        if total is None:
            text = ("— (unresolved)" if partial
                    else "— (no sections)")
        elif partial:
            text = f"{total} (partial — section unresolved)"
        else:
            text = total
        summary_rows.append((label, text))
    summary_rows.extend([
        ("Overheads/Markups",
         "— (price via Rate Builder markups)"),
        ("Resolved subtotal", summary["resolved_subtotal"]),
        ("Tender Value",
         summary["grand_total"] if summary["grand_total"] is not None
         else f"UNRESOLVED — "
              f"{len(summary['unresolved_items'])} item(s): "
              f"{', '.join(summary['unresolved_items'])}")])
    for index, (label, text) in enumerate(summary_rows):
        rownum, half = divmod(index, 2)
        ttk.Label(card, text=label, width=24).grid(
            row=rownum, column=half * 2,
            padx=(8, 2) if half == 0 else (6, 2), pady=1, sticky="w")
        ttk.Label(card, text=text, style="Status.TLabel").grid(
            row=rownum, column=half * 2 + 1, padx=2, pady=1, sticky="w")
    detail = tk.Text(body, height=8, wrap="word", background="white")
    detail.pack(fill="both", expand=True, pady=(6, 0))
    detail.insert("end", "\n".join(
        [f"Section {section.code} — {section.title}: "
         f"{section.total if section.total is not None else 'UNRESOLVED'}"
         for section in compiled.sections]))
    detail.config(state="disabled")
    app.refresh_status()


def build_placeholder_page(body, app, title, message):
    """Clearly marked unavailable module (no functionality implied)."""
    page_title(body, title)
    ttk.Label(body, text="\u26a0 Not yet implemented in this build.",
              foreground=WARN_AMBER,
              font=("TkDefaultFont", 11, "bold")).pack(
                  anchor="w", pady=(8, 4))
    ttk.Label(body, text=message, wraplength=640,
              justify="left").pack(anchor="w")
    status_line(body)


def build_rates_page(body, app):
    """Rate builder: line editor + markups + component tables."""
    from qs_engine.core.errors import QSEngineError
    build_page_header(body, "Rate Builder",
                        PANEL_INSTRUCTIONS["rates"], guide_key="rates",
                        icon="🧮")
    meta = ttk.Frame(body)
    meta.pack(fill="x", pady=2)
    element_entry = CueEntry(meta, width=24, cue=ELEMENT_HINT)
    unit_entry = ttk.Combobox(meta, width=10, state="readonly",
                              values=list(RATE_WORK_UNITS))
    policy_entry = ttk.Combobox(meta, width=16, state="readonly",
                                values=list(RATE_POLICIES))
    ttk.Label(meta, text="Element").pack(side="left")
    element_entry.pack(side="left", padx=(2, 10))
    ttk.Label(meta, text="Rate Unit").pack(side="left")
    unit_entry.set("m²")
    unit_entry.pack(side="left", padx=(2, 10))
    ttk.Label(meta, text="Policy").pack(side="left")
    policy_entry.set(RATE_POLICIES[0])
    policy_entry.pack(side="left", padx=(2, 10))
    ttk.Button(meta, text="Build Rate", style="Accent.TButton",
               command=lambda: on_build()).pack(side="left", padx=(0, 6))
    ttk.Button(meta, text="Apply Gross Rate to Selected",
               style="Accent.TButton",
               command=lambda: on_apply_rate()).pack(side="left")
    ttk.Label(body, text="Components (one row per build-up line):").pack(
        anchor="w")
    rate_grid_host = ttk.Frame(body)
    rate_grid_host.pack(fill="x")
    for col, heading in enumerate(
            ("Kind", "Resource Code", "Quantity", "Unit", "Unit Rate",
             "Wastage %", "Description", "Resource", "Pick",
             "Provisional")):
        ttk.Label(rate_grid_host, text=heading).grid(
            row=0, column=col, padx=2, sticky="w")
    rate_rows = []

    def add_rate_row():
        """Append one component row (kind selector + entries).

        Unit records the resource measurement unit (e.g. hr, bag, m³)
        as estimator context; it is never serialized into the rate
        input syntax (the parser grammar has no unit field).
        """
        widgets = {}
        row_index = len(rate_rows) + 1
        kind_box = ttk.Combobox(rate_grid_host, state="readonly",
                                values=list(RATE_COMPONENT_KINDS), width=12)
        kind_box.set(RATE_COMPONENT_KINDS[0])
        kind_box.grid(row=row_index, column=0, padx=2, pady=1, sticky="ew")
        widgets["kind"] = kind_box
        for col, field in enumerate(
                ("key", "qty", "unit", "price", "waste", "desc"), start=1):
            if field == "unit":
                entry = ttk.Combobox(
                    rate_grid_host, width=10,
                    values=list(COMPONENT_UNITS))
            elif field == "desc":
                entry = CueEntry(rate_grid_host, width=RATE_DESCRIPTION_WIDTH,
                                 cue=rate_description_cue(
                                     RATE_COMPONENT_KINDS[0]))
            else:
                entry = CueEntry(rate_grid_host, width=10,
                                 cue=RATE_ROW_PLACEHOLDERS[field])
            entry.grid(row=row_index, column=col, padx=2, pady=1,
                       sticky="ew")
            widgets[field] = entry
        resource_entry = ttk.Entry(rate_grid_host, width=18,
                                   state="disabled")
        resource_entry.grid(row=row_index, column=7, padx=2, pady=1,
                            sticky="ew")
        widgets["resource"] = resource_entry
        _set_readout(resource_entry, PICKER_HINT)
        pick_button = make_picker_button(
            rate_grid_host, lambda w=widgets: open_row_picker(w))
        pick_button.grid(row=row_index, column=8, padx=2, pady=1)
        widgets["pick"] = pick_button
        prov_box = ttk.Combobox(rate_grid_host, state="readonly",
                                values=list(PROVISIONAL_CHOICES), width=12)
        prov_box.set(PROVISIONAL_CHOICES[0])
        prov_box.grid(row=row_index, column=9, padx=2, pady=1,
                      sticky="ew")
        widgets["prov"] = prov_box
        kind_box.bind("<<ComboboxSelected>>",
                      lambda _event, w=widgets: on_kind_change(w))
        rate_rows.append(widgets)

    def open_row_picker(widgets):
        """Catalogue picker for material/labour rows (display only)."""
        kind = widgets["kind"].get().strip().lower()
        domain = rate_row_field_states(kind)["picker"]
        if not domain:
            return

        def on_select(record):
            if kind == "material":
                _set_entry_value(
                    widgets["key"], str(record.get("key", "") or ""))
                if not _entry_text(widgets["unit"]):
                    unit = str(record.get("unit", "") or "")
                    if unit:
                        _set_entry_value(widgets["unit"], unit)
            elif kind == "labour":
                if not _entry_text(widgets["desc"]):
                    _set_entry_value(
                        widgets["desc"],
                        str(record.get("trade", "")
                            or record.get("key", "")))
            refresh_resource_readout(
                widgets, app.repository,
                policy=active_material_code_policy(app))

        select_resource_dialog(body, domain, app.repository, on_select)

    def on_kind_change(widgets):
        """Re-apply conditional inputs + readout after a kind switch.

        The Description cell carries a kind-specific example cue because the
        cell serves materials, labour and subcontract rows with different
        vocabularies; retargeting keeps the example truthful per kind.
        """
        apply_kind_states(widgets)
        widgets["desc"].set_cue(rate_description_cue(widgets["kind"].get()))
        refresh_resource_readout(
            widgets, app.repository,
            policy=active_material_code_policy(app))

    def remove_rate_row():
        """Drop the last component row."""
        if rate_rows:
            for widget in rate_rows.pop().values():
                widget.destroy()

    add_rate_row()
    pending_key = getattr(app.session, "pending_material_key", None)
    if pending_key:
        app.session.pending_material_key = None
        first = rate_rows[0]
        _set_entry_value(first["key"], pending_key)
        apply_kind_states(first)
        refresh_resource_readout(
            first, app.repository,
            policy=active_material_code_policy(app))
    rate_row_buttons = ttk.Frame(body)
    rate_row_buttons.pack(fill="x", pady=2)
    ttk.Button(rate_row_buttons, text="Add Component Row",
               style="Accent.TButton",
               command=add_rate_row).pack(side="left", padx=(0, 6))
    ttk.Button(rate_row_buttons, text="Remove Last Row",
               style="Accent.TButton",
               command=remove_rate_row).pack(side="left")
    raw_rate_visible = tk.BooleanVar(value=False)
    raw_rate_frame = ttk.LabelFrame(body, text="Advanced Input")
    ttk.Label(raw_rate_frame,
              text="Component lines (one per row):").pack(anchor="w")
    lines_text = tk.Text(raw_rate_frame, height=6, wrap="word",
                         background="white")
    lines_text.pack(fill="x")
    lines_text.insert(
        "end", "# material | key=<k> | qty=<n> | price=<n> | waste=<n> "
        "| desc=<text>\n# labour | hours=<n> | rate=<n> | desc=<text>")

    def toggle_raw_rate():
        if raw_rate_visible.get():
            raw_rate_frame.pack(fill="x", pady=(6, 0))
        else:
            raw_rate_frame.pack_forget()

    ttk.Checkbutton(body, text="Show Advanced Input",
                    variable=raw_rate_visible,
                    command=toggle_raw_rate).pack(anchor="w", pady=(4, 0))
    ttk.Label(body, text="Markups — Label: Pct (e.g., Overhead: 10, "
                         "Profit: 15)").pack(anchor="w")
    markups_text = tk.Text(body, height=2, wrap="word", background="white")
    markups_text.pack(fill="x")
    results = ttk.Frame(body)
    results.pack(fill="x", pady=(6, 0))
    comp_grid = make_grid(results, {"kind": ("Kind", 100),
                                    "description": ("Description", 260),
                                    "cost": ("Cost / unit", 130)})
    comp_grid.pack(side="left", fill="both", expand=True, padx=(0, 4))
    markup_grid = make_grid(results, {"label": ("Markup", 200),
                                      "amount": ("Amount", 130)}, height=4)
    markup_grid.pack(side="left", fill="both", expand=True, padx=(4, 0))
    summary = ttk.Label(body, text="", style="Status.TLabel")
    summary.pack(anchor="w", pady=(4, 0))
    message = ttk.Label(body, text="", foreground="red")
    message.pack(anchor="w")

    def rate_grid_to_dsl():
        """Serialize non-blank component rows into rate input lines.

        The per-row Unit entry is estimator context only and never
        enters the serialized syntax (the parser grammar has no unit
        field); the Resource readout and Pick button are display-only.
        A set Provisional flag serializes only on subcontract rows.
        """
        rows = []
        for widgets in rate_rows:
            values = {field: _entry_text(widgets[field])
                      for field in ("key", "qty", "unit", "price",
                                    "waste", "desc")}
            values["kind"] = widgets["kind"].get().strip()
            values["provisional"] = (
                widgets["prov"].get().strip() == "Yes")
            if any(values.get(field) for field in
                   ("key", "qty", "price", "waste", "desc")) \
                    or widgets["prov"].get().strip() not in ("", "No"):
                rows.append(format_rate_line(values))
        return "\n".join(rows)

    def on_build():
        from qs_engine.ui.controllers import rate_builder_controller
        message.config(text="")
        policy = active_material_code_policy(app)
        for widgets in rate_rows:
            apply_kind_states(widgets)
            refresh_resource_readout(
                widgets, app.repository, policy=policy)
        try:
            dsl = rate_grid_to_dsl()
            if dsl.strip():
                lines_text.delete("1.0", "end")
                lines_text.insert("end", dsl)
            lines = parse_rate_lines(lines_text.get("1.0", "end"))
            lines = resolve_rate_line_material_keys(app, lines)
            markups = parse_markup_lines(markups_text.get("1.0", "end"))
            result = rate_builder_controller(
                lines, markups, policy_entry.get().strip() or "sequential",
                _entry_text(element_entry),
                unit_entry.get().strip() or "m²", app.repository)
        except QSEngineError as exc:
            message.config(text=str(exc))
            return
        if isinstance(result, ErrorView):
            message.config(text=result.message)
            return
        refresh_grid(comp_grid, [(c.label.split(":")[0].strip(),
                                  c.label.split(":", 1)[1].strip()
                                  if ":" in c.label else "",
                                  c.value)
                                 for c in result.components])
        refresh_grid(markup_grid, [(m.label, m.value)
                                   for m in result.markups])
        unit_suffix = (f" per {result.work_unit}"
                       if str(result.work_unit or "").strip() else "")
        summary.config(
            text=f"Direct Cost: {result.direct_cost} | "
                 f"Net: {result.net_rate} | "
                 f"Composite Unit Rate: {result.gross_rate}"
                 f"{unit_suffix} ({result.markup_policy})")
        app.session.last_rate = {
            "gross": str(result.gross_rate),
            "ref": _entry_text(element_entry) or "rate-builder",
        }
        app.refresh_status()

    schedule_card = ttk.LabelFrame(body, text="Take-off Schedule")
    schedule_card.pack(fill="both", expand=True, pady=(6, 0))
    schedule_grid = make_grid(schedule_card, SCHEDULE_COLUMNS, height=6)
    schedule_grid.pack(fill="both", expand=True)
    apply_status = status_line(body)

    def refresh_schedule():
        for child in schedule_grid.get_children():
            schedule_grid.delete(child)
        for index, line in enumerate(app.session.lines()):
            schedule_grid.insert("", "end", iid=str(index), values=(
                line.trade, line.description, line.unit, line.quantity,
                line.rate or "—", line.takeoff_ref))

    def on_apply_rate():
        from qs_engine.core.errors import QSEngineError
        selection = schedule_grid.selection()
        if not selection:
            apply_status.config(text="Select a take-off line first")
            return
        if not app.session.last_rate:
            apply_status.config(
                text="Build a rate first, then apply its gross rate")
            return
        try:
            updated = apply_built_rate_to_line(
                app.session, int(selection[0]),
                app.session.last_rate["gross"],
                app.session.last_rate["ref"])
        except (QSEngineError, ValueError, IndexError) as exc:
            apply_status.config(text=str(exc))
            app.refresh_status()
            return
        refresh_schedule()
        apply_status.config(
            text=f"● Applied gross rate {updated.rate} to "
                 f"{updated.description}")
        app.refresh_status()

    refresh_schedule()


def build_boq_page(body, app):
    """BOQ compilation: refs in, grid + detail + unresolved out."""
    from qs_engine.boq.compiler import compile_boq
    from qs_engine.core.errors import QSEngineError
    build_page_header(body, "Bill of Quantities",
                        PANEL_INSTRUCTIONS["boq"], guide_key="boq",
                        icon="📋")
    refs = ttk.Frame(body)
    refs.pack(fill="x", pady=2)
    project_entry, boq_entry = (ttk.Entry(refs, width=20),
                                  ttk.Entry(refs, width=20))
    project_entry.insert(0, app.session.project.get("reference", ""))
    for label, widget in (("Project ref", project_entry),
                          ("BOQ ref", boq_entry)):
        ttk.Label(refs, text=label).pack(side="left")
        widget.pack(side="left", padx=(2, 10))
    ttk.Button(body, text="Compile BOQ", style="Accent.TButton",
               command=lambda: on_compile()).pack(anchor="w", pady=6)
    grid = make_grid(body, BOQ_COLUMNS, height=10)
    grid.pack(fill="both", expand=True)
    for status, _ in STATUS_STYLES.items():
        _, colour = status_badge(status)
        grid.tag_configure(f"status-{status}", foreground=colour)
    detail = tk.Text(body, height=6, wrap="word", background="white")
    detail.pack(fill="x", pady=(6, 0))
    unresolved_label = ttk.Label(body, text="", style="Status.TLabel",
                                 wraplength=640, justify="left")
    unresolved_label.pack(anchor="w", pady=(4, 0))
    message = ttk.Label(body, text="", foreground="red")
    message.pack(anchor="w")

    def on_select(_event=None):
        selection = grid.selection()
        if not selection:
            return
        values = grid.item(selection[0], "values")
        if not values:
            return
        found = find_compiled_item(app.session.last_compiled, values[0])
        detail.delete("1.0", "end")
        if found is None:
            detail.insert("end", "No compiled detail for this row "
                                 "(compile the BOQ first).")
            return
        detail.insert("end", "\n".join([
            f"Item: {found.item_no} — {found.description}",
            f"Status: {found.status} | Pricing: {found.pricing_kind}",
            f"Rate ref: {found.rate_ref or '—'}",
            f"Take-off Reference: {found.takeoff_ref or '—'}",
            f"Measurement: {found.measurement_ref or '—'}",
            f"Provenance: {'; '.join(found.provenance) or '—'}",
            f"Notes: {found.notes or '—'}",
        ]))

    def on_compile():
        message.config(text="")
        try:
            boq = app.session.to_boq(
                project_entry.get().strip(), boq_entry.get().strip())
            compiled = compile_boq(boq)
        except QSEngineError as exc:
            message.config(text=str(exc))
            app.refresh_status()
            return
        from qs_engine.ui.controllers import boq_view_controller
        view = boq_view_controller(boq)
        if isinstance(view, ErrorView):  # defensive: same input compiled
            message.config(text=view.message)
            app.refresh_status()
            return
        app.session.last_compiled = compiled
        for child in grid.get_children():
            grid.delete(child)
        for section in view.sections:
            for item in section.items:
                grid.insert("", "end", values=(
                    item.item_no, item.description, item.unit,
                    item.quantity, item.rate, item.amount, item.status),
                    tags=(f"status-{item.status}",))
        if compiled.has_unresolved:
            unresolved_label.config(
                text="\u26a0 Unresolved: "
                     + ", ".join(compiled.unresolved_items))
        else:
            unresolved_label.config(
                text=f"\u25cf Complete — grand total "
                     f"{compiled.total}")
        app.refresh_status()

    grid.bind("<<TreeviewSelect>>", on_select)


def build_mix_design_page(body, app):
    """Mix Design Lookup & Breakdown Engine (BS EN 206 / BS 8500).

    Selection controls (strength class, target volume, wastage)
    feed a live constituent summary grid: cement bags + mass,
    sand volume/mass, coarse aggregate volume/mass, and batch
    water. A Link-to-Materials-Store button resolves constituent
    codes against the materials catalogue.
    """
    from qs_engine.core.errors import ValidationError
    from qs_engine.master_data.repository import (
        MasterDataRepository,
    )
    from qs_engine.mixes.calculator import (
        ConstituentCalculator,
    )
    from qs_engine.ui.viewmodels import ErrorView

    build_page_header(
        body, "Mix Design",
        guide_key="mix_design", icon="🏗️")
    inputs_host = ttk.Frame(body)
    inputs_host.pack(fill="x", pady=4)

    def _entry(parent, label, width=14, default=""):
        ttk.Label(parent, text=label).pack(side="left")
        entry = ttk.Entry(parent, width=width)
        entry.insert(0, default)
        entry.pack(side="left", padx=4)
        return entry

    designation_combo = ttk.Combobox(
        inputs_host, state="readonly", width=22,
        values=[
            "C8/10", "C12/15", "C16/20",
            "C20/25", "C25/30", "C30/37"])
    designation_combo.pack(side="left", padx=4)
    designation_combo.set("C20/25")
    net_vol_entry = _entry(inputs_host, "Net Volume (m³):", 14, "10")
    waste_entry = _entry(inputs_host, "Wastage %:", 10, "5.0")

    result_frame = ttk.LabelFrame(body, text="Constituent Summary")
    result_frame.pack(fill="x", pady=6)
    card_labels = {}
    for col, (label, key) in enumerate((
            ("Cement Mass", "cement_mass"),
            ("Cement Bags", "cement_bags"),
            ("Water (L)", "water_liters"),
            ("Sand Mass (t)", "sand_mass"),
            ("Coarse Agg Mass (t)", "coarse_agg_mass"),
            ("Sand Volume (m³)", "sand_volume"),
            ("Coarse Agg Volume (m³)", "coarse_agg_volume"))):
        cell = ttk.Frame(result_frame)
        cell.grid(row=0, column=col, padx=4, sticky="ew")
        ttk.Label(cell, text=label, style="Status.TLabel",
                    wraplength=80).pack(anchor="w")
        value = ttk.Label(cell, text="\u2014",
                            style="Heading.TLabel")
        value.pack(anchor="w")
        setattr(value, "key", key)
        card_labels[key] = value
    result_frame.grid_columnconfigure(0, weight=1)
    result_frame.grid_columnconfigure(1, weight=1)
    result_frame.grid_columnconfigure(2, weight=1)
    result_frame.grid_columnconfigure(3, weight=1)

    status_line = ttk.Label(body, text="", style="Status.TLabel",
                               wraplength=640, justify="left")
    status_line.pack(anchor="w", pady=4)
    detail_lines = ttk.Label(body, text="", style="Status.TLabel",
                                wraplength=640, justify="left")
    detail_lines.pack(anchor="w", pady=2)

    def on_compute():
        try:
            calc = ConstituentCalculator(app.repository)
            result = calc.compute(
                designation_combo.get().strip(),
                net_vol_entry.get().strip() or "0",
                (waste_entry.get().strip() or "0.05"))
            if isinstance(result, ErrorView):
                status_line.config(text=result.message)
                app.refresh_status()
                return
            app.session.last_mix_design = result
            card_labels["cement_mass"].config(
                text=str(result.cement_mass))
            card_labels["cement_bags"].config(
                text=str(result.cement_bags))
            card_labels["water_liters"].config(
                text=str(result.water_liters))
            card_labels["sand_mass"].config(
                text=str(result.sand_mass))
            card_labels["coarse_agg_mass"].config(
                text=str(result.coarse_agg_mass))
            card_labels["sand_volume"].config(
                text=str(result.sand_volume))
            card_labels["coarse_agg_volume"].config(
                text=str(result.coarse_agg_volume))
            status_line.config(
                text=f"\u25cf {result.designation} "
                     f"({result.bs_8500_designation}) \u2014 "
                     f"Gross Volume: {result.gross_volume} m\u00b3")
            detail_lines.config(
                text=f"Cement: {result.cement_code} | "
                     f"Sand: {result.fine_agg_code} | "
                     f"Coarse Agg: {result.coarse_agg_code}")
            app.refresh_status()
        except ValidationError as exc:
            status_line.config(text=f"\u25cf {exc.message}")
        except Exception as exc:
            status_line.config(text=f"\u25cf {exc}")

    def on_link_materials():
        result = getattr(app.session, "last_mix_design", None)
        if result is None:
            detail_lines.config(
                text="Compute a mix design first")
            return
        from qs_engine.master_data.repository import (
            MasterDataRepository,
        )
        codes = [result.cement_code,
                  result.fine_agg_code,
                  result.coarse_agg_code]
        found = []
        for code in codes:
            try:
                recs = [r for r in
                        app.repository.list("materials")
                        if r.get("code") == code]
                if recs:
                    found.append(
                        f"{code}: {recs[0].get('name')} "
                        f"({recs[0].get('category')})")
                else:
                    found.append(f"{code}: not in catalogue")
            except Exception:
                found.append(f"{code}: lookup failed")
        detail_lines.config(
            text="Material link: " + " | ".join(found))

    ttk.Button(body, text="Compute Mix Design",
               style="Accent.TButton",
               command=on_compute).pack(anchor="w", pady=6)
    ttk.Button(body, text="Link to Materials Store",
               command=on_link_materials).pack(anchor="w", pady=(0, 6))


#: Reconciliation review grid columns.
RECON_COLUMNS = {
    "item": ("Item No.", 80),
    "description": ("Description", 200),
    "q_boq": ("Qty (BOQ)", 90),
    "q_tender": ("Qty (Tender)", 90),
    "dq": ("Quantity Variance", 120),
    "r_boq": ("Tender Rate (BOQ)", 110),
    "r_tender": ("Tender Rate (Return)", 120),
    "dr": ("Rate Delta", 100),
    "variance": ("Cost Difference", 120),
    "flags": ("Flags", 160),
}


def build_excel_page(body, app):
    """Tender export + reconciliation centre: dual-panel workspace.

    Left: Export Settings & Action (path, template style, Export BOQ).
    Right: Reconciliation & Tender Review (returned-file picker, Run
    Variance Analysis, colour-badged variance rows). Reconciliation is
    read-only review — session truth is never overwritten.
    """
    from qs_engine.adapters.document.company_profile import (
        load_company_profile,
    )
    from qs_engine.adapters.excel.tender_workbook import TENDER_STYLES
    build_page_header(
        body, "Excel Export / Reconciliation",
        guide_key="excel",
        icon="📊")
    export_banner = guard_banner(body)
    panes = ttk.Frame(body)
    panes.pack(fill="both", expand=True)
    left = ttk.LabelFrame(panes, text="Export Settings & Action")
    left.pack(side="left", fill="both", expand=True, padx=(0, 4))
    right = ttk.LabelFrame(panes, text="Reconciliation & Tender Review")
    right.pack(side="left", fill="both", expand=True, padx=(4, 0))

    # -- left: export settings -------------------------------------------
    readiness = ttk.Label(left, text="", style="Status.TLabel",
                          wraplength=420, justify="left")
    readiness.pack(anchor="w", pady=(2, 0))

    def refresh_readiness():
        compiled = app.session.last_compiled
        if compiled is None:
            readiness.config(text="Status: no compiled BOQ in this "
                                  "session yet.")
        else:
            readiness.config(
                text=f"Ready: {len(compiled.unresolved_items)} unresolved, "
                     f"resolved subtotal {compiled.resolved_subtotal}")

    ttk.Label(left, text="Output file (.xlsx):").pack(anchor="w",
                                                      pady=(6, 0))
    export_row = ttk.Frame(left)
    export_row.pack(fill="x")
    export_entry = ttk.Entry(export_row)
    export_entry.pack(side="left", fill="x", expand=True)

    def on_browse_export():
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")])
        if path:
            export_entry.delete(0, "end")
            export_entry.insert(0, path)

    ttk.Button(export_row, text="Browse…", style="Accent.TButton",
               command=on_browse_export).pack(side="left", padx=(4, 0))
    ttk.Label(left, text="Excel template style:").pack(anchor="w",
                                                       pady=(6, 0))
    style_labels = [label for _key, (label, _fill)
                    in TENDER_STYLES.items()]
    style_keys = list(TENDER_STYLES)
    style_combo = ttk.Combobox(left, state="readonly",
                               values=style_labels, width=28)
    style_combo.current(0)
    style_combo.pack(anchor="w")
    export_status = status_line(left)

    def standard_text():
        standard = app.session.standard
        if standard is None:
            return ""
        return str(standard.edition or standard.standard or "").strip()

    def on_export():
        from qs_engine.ui import controllers
        from qs_engine.ui.viewmodels import ExportView
        blocked = _export_entitlement_error(app)
        if blocked is not None:
            export_status.config(text=blocked)
            return
        compiled = app.session.last_compiled
        if compiled is None:
            export_status.config(text="Compile the BOQ first (BOQ View)")
            return
        path = export_entry.get().strip()
        if not path:
            export_status.config(text="Pick an output file first")
            return
        profile = load_company_profile()
        project = app.session.project
        result = controllers.tender_export_controller(
            compiled, path,
            company_name=profile.get("business_name", ""),
            project_title=(project.get("name", "")
                           or compiled.project_ref),
            client=project.get("client", ""),
            reference=compiled.boq_ref,
            measurement_standard=standard_text(),
            template_style=style_keys[style_combo.current()])
        if isinstance(result, ExportView):
            export_status.config(text=f"\u25cf Exported {result.path}")
        else:
            export_status.config(text=result.message)
        refresh_readiness()
        app.refresh_status()

    export_button = ttk.Button(left, text="Export BOQ",
                               style="Accent.TButton",
                               command=on_export)
    export_button.pack(anchor="w", pady=6)
    register_export_guard(app, export_button, export_banner)

    # -- right: reconciliation -------------------------------------------
    ttk.Label(right, text="Returned tender file (.xlsx):").pack(
        anchor="w", pady=(2, 0))
    tender_row = ttk.Frame(right)
    tender_row.pack(fill="x")
    tender_entry = ttk.Entry(tender_row)
    tender_entry.pack(side="left", fill="x", expand=True)

    def on_browse_tender():
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            filetypes=[("Excel workbook", "*.xlsx"),
                       ("All files", "*.*")])
        if path:
            tender_entry.delete(0, "end")
            tender_entry.insert(0, path)

    ttk.Button(tender_row, text="Browse…", style="Accent.TButton",
               command=on_browse_tender).pack(side="left", padx=(4, 0))
    recon_grid = make_grid(right, RECON_COLUMNS, height=10)
    recon_grid.pack(fill="both", expand=True, pady=(6, 0))
    recon_grid.tag_configure("rate", foreground=WARN_AMBER)
    recon_grid.tag_configure("qty", foreground=CIVOLINK_BLUE)
    recon_grid.tag_configure("unpriced", foreground=SLATE_GREY)
    summary_label = ttk.Label(right, text="", style="Status.TLabel",
                              wraplength=420, justify="left")
    summary_label.pack(anchor="w", pady=(4, 0))
    recon_status = status_line(right)

    def on_reconcile():
        from qs_engine.adapters.excel.reconciliation import (
            FLAG_LUMP,
            FLAG_OPEN,
            FLAG_PRICED,
            FLAG_QTY,
            FLAG_RATE,
            FLAG_UNPRICED,
            FLAG_UNRESOLVED,
        )
        from qs_engine.ui import controllers
        compiled = app.session.last_compiled
        if compiled is None:
            recon_status.config(text="Compile the BOQ first (BOQ View)")
            return
        path = tender_entry.get().strip()
        if not path:
            recon_status.config(text="Pick a returned tender file first")
            return
        result = controllers.tender_reconciliation_controller(
            compiled, path)
        if isinstance(result, ErrorView):
            recon_status.config(text=result.message)
            return
        for child in recon_grid.get_children():
            recon_grid.delete(child)
        for row in result.rows:
            if FLAG_OPEN in row.flags:
                tag = "unpriced"
            elif (FLAG_RATE in row.flags or FLAG_PRICED in row.flags
                    or FLAG_UNPRICED in row.flags
                    or FLAG_LUMP in row.flags):
                tag = "rate"
            elif FLAG_QTY in row.flags:
                tag = "qty"
            else:
                tag = ""
            if row.variance is None:
                cost_text = ("Unresolved"
                             if FLAG_UNRESOLVED in row.flags
                             else "Unpriced Item")
            else:
                cost_text = row.variance
            recon_grid.insert(
                "", "end",
                values=(row.item_no, row.description, row.q_boq,
                        row.q_tender, row.dq, row.r_boq or "—",
                        row.r_tender or "—", row.dr or "—",
                        cost_text,
                        ", ".join(row.flags) or "—"),
                tags=(tag,) if tag else ())
        tender_note = (" (tender has unpriced items)"
                       if result.tender_has_unpriced else "")
        summary_label.config(
            text=f"Base Estimate: {result.base_estimate} | "
                 f"Tender Price: {result.tender_total}{tender_note} | "
                 f"Cost Difference: {result.variance_amount} "
                 f"({result.variance_pct or '—'}%) | "
                 f"Modified: {result.modified_count} | "
                 f"Unpriced: {result.unpriced_count}")
        recon_status.config(
            text="\u25cf Variance analysis complete — review only, "
                 "session truth unchanged")
        app.refresh_status()

    ttk.Button(right, text="Run Variance Analysis", style="Accent.TButton",
               command=on_reconcile).pack(anchor="w", pady=6)
    refresh_readiness()


#: Valued-line grid columns for the IPC page (units explicit).
IPC_GRID_COLUMNS = (
    ("item_no", "Item No."),
    ("description", "Description"),
    ("unit", "Unit"),
    ("rate", "Rate"),
    ("completed_qty", "Completed Qty"),
)

#: BOQ line-item grid for multi-period valuation (present
#: quantity is editable).
BOQ_LINE_ITEMS = (
    ("boq_ref", "BOQ Ref"),
    ("description", "Description"),
    ("unit", "Unit"),
    ("rate", "Rate"),
    ("boq_qty", "BOQ Qty"),
    ("prev_qty", "Prev Qty"),
    ("present_qty", "Present Qty"),
    ("total_qty", "Total Qty"),
    ("present_value", "Present Value"),
)


def build_valuations_page(body, app):
    """Valuations & IPC centre: dual-panel workspace.

    Left: IPC Valuation Inputs (contract terms, period figures, valued
    lines, Compute Valuation). Right: PDF Export (one-click BOQ
    summary and IPC statement export). Valuation math lives in the
    IPC engine; the page only collects strings and renders results.
    """
    from qs_engine.adapters.document.company_profile import (
        load_company_profile,
    )
    build_page_header(
        body, "Valuations & IPC",
        guide_key="valuations",
        icon="📈")
    export_banner = guard_banner(body)
    # ---- contract summary cards ----
    cards = ttk.Frame(body)
    cards.pack(fill="x", pady=(2, 6))
    card_values = {}
    for col, (label, key) in enumerate((
            ("Contract Sum", "contract_sum"),
            ("Total Certified", "gross_certified"),
            ("Retention Held", "retention_withheld"),
            ("Net Payable", "net_payable"))):
        cell = ttk.Frame(cards)
        cell.grid(row=0, column=col, padx=3, sticky="ew")
        ttk.Label(cell, text=label, style="Status.TLabel",
                    wraplength=90, justify="left").pack(
                        anchor="w")
        value = ttk.Label(cell, text="\u2014",
                            style="Heading.TLabel")
        value.pack(anchor="w")
        setattr(value, "key", key)
        card_values[key] = value
    cards.grid_columnconfigure(0, weight=1)
    cards.grid_columnconfigure(1, weight=1)
    cards.grid_columnconfigure(2, weight=1)
    cards.grid_columnconfigure(3, weight=1)
    panes = ttk.Frame(body)
    panes.pack(fill="both", expand=True)
    left = ttk.LabelFrame(panes, text="IPC Valuation Inputs")
    left.pack(side="left", fill="both", expand=True, padx=(0, 4))
    right = ttk.LabelFrame(panes, text="PDF Export")
    right.pack(side="left", fill="both", expand=True, padx=(4, 0))

    # -- left: contract terms + period figures ---------------------------
    entries = {}
    terms_grid = ttk.Frame(left)
    terms_grid.pack(fill="x", pady=1)
    terms_grid.grid_columnconfigure(1, weight=1)
    terms_grid.grid_columnconfigure(3, weight=1)
    for rownum, pair in enumerate((
            (("contract_sum", "Contract Sum"),
             ("retention_rate_pct", "Retention Rate %")),
            (("retention_limit", "Retention Limit (cap)"),
             ("advance_balance", "Advance Balance O/S")),
            (("previous_payments", "Previous Payments"),
             ("previous_valuation", "Previous Valuation")),
            (("onsite_materials", "On-site Materials"),
             ("advance_repaid", "Advance Repaid (period)")))):
        for half, (field, label) in enumerate(pair):
            ttk.Label(terms_grid, text=label,
                      width=22 if half == 0 else 24).grid(
                          row=rownum, column=half * 2,
                          padx=(0, 2) if half == 0 else (6, 2),
                          pady=1, sticky="w")
            entry = ttk.Entry(terms_grid, width=22)
            entries[field] = entry
            entry.grid(row=rownum, column=half * 2 + 1, padx=2, pady=1,
                       sticky="ew")
    ttk.Label(terms_grid, text="Valuation No.", width=22).grid(
        row=4, column=0, padx=(0, 2), pady=1, sticky="w")
    valuation_no_entry = ttk.Entry(terms_grid, width=22)
    entries["valuation_no"] = valuation_no_entry
    valuation_no_entry.grid(row=4, column=1, columnspan=3, padx=2, pady=1,
                            sticky="ew")
    ttk.Label(left, text="Valued lines (current period):").pack(
        anchor="w", pady=(4, 0))
    ipc_host = ttk.Frame(left)
    ipc_host.pack(fill="x")
    for col, (_field, heading) in enumerate(IPC_GRID_COLUMNS):
        ttk.Label(ipc_host, text=heading).grid(
            row=0, column=col, padx=2, sticky="w")
    ipc_rows = []

    def add_ipc_row():
        """Append one valued-line row."""
        widgets = {}
        row_index = len(ipc_rows) + 1
        for col, (field, _heading) in enumerate(IPC_GRID_COLUMNS):
            widget = ttk.Entry(ipc_host, width=12)
            widget.grid(row=row_index, column=col, padx=2, pady=1,
                        sticky="ew")
            widgets[field] = widget
        ipc_rows.append(widgets)

    def remove_ipc_row():
        """Drop the last valued-line row."""
        if ipc_rows:
            for widget in ipc_rows.pop().values():
                widget.destroy()

    add_ipc_row()
    ipc_buttons = ttk.Frame(left)
    ipc_buttons.pack(fill="x", pady=2)
    ttk.Button(ipc_buttons, text="Add Valuation Row",
               style="Accent.TButton",
               command=add_ipc_row).pack(side="left", padx=(0, 6))
    ttk.Button(ipc_buttons, text="Remove Last Row",
               style="Accent.TButton",
               command=remove_ipc_row).pack(side="left")
    ipc_summary = ttk.Label(left, text="", style="Status.TLabel",
                            wraplength=420, justify="left")
    ipc_summary.pack(anchor="w", pady=(4, 0))
    ipc_status = status_line(left)

    def on_compute():
        from qs_engine.ui import controllers
        items = []
        for widgets in ipc_rows:
            values = {field: widget.get().strip()
                      for field, widget in widgets.items()}
            if any(values.values()):
                items.append(values)
        result = controllers.ipc_valuation_controller(
            entries["contract_sum"].get().strip() or "0",
            entries["retention_rate_pct"].get().strip() or "0",
            entries["retention_limit"].get().strip() or "0",
            previous_valuation=(
                entries["previous_valuation"].get().strip() or "0"),
            items=items,
            onsite_materials=(
                entries["onsite_materials"].get().strip() or "0"),
            advance_repaid=(
                entries["advance_repaid"].get().strip() or "0"),
            advance_balance=(
                entries["advance_balance"].get().strip() or "0"),
            previous_payments=(
                entries["previous_payments"].get().strip() or "0"),
            valuation_no=entries["valuation_no"].get().strip())
        if isinstance(result, ErrorView):
            ipc_status.config(text=result.message)
            app.refresh_status()
            return
        app.session.last_ipc = result
        ipc_summary.config(
            text=f"Work to Date: {result.work_to_date} | "
                 f"Gross Certified: {result.gross_certified} | "
                 f"Retention: {result.retention_withheld} | "
                 f"Deductions: {result.total_deductions} | "
                 f"Net Payable: {result.net_payable}")
        for _key, _widget in card_values.items():
            _widget.config(text=str(getattr(result, _key)))
        ipc_status.config(text="\u25cf Valuation computed — review only, "
                                "session BOQ unchanged")
        refresh_pdf_readiness()
        app.refresh_status()

    ttk.Button(left, text="Compute Valuation", style="Accent.TButton",
               command=on_compute).pack(anchor="w", pady=6)

    # ---- period selector + BOQ line-items grid ----
    period_row = ttk.Frame(left)
    period_row.pack(fill="x", pady=(8, 2))
    ttk.Label(period_row, text="Period No.:").pack(side="left")
    period_spin = ttk.Spinbox(period_row, from_=1, to=999,
                                 width=6, value=1)
    period_spin.pack(side="left", padx=4)
    ttk.Label(period_row, text="Valuation No.:").pack(
        side="left", padx=(8, 0))
    valuation_no_entry = ttk.Entry(period_row, width=14)
    valuation_no_entry.insert(0, "01")
    valuation_no_entry.pack(side="left", padx=4)

    boq_status = status_line(left)
    boq_lines: list[dict] = []
    tree = ttk.Treeview(
        left, columns=[c[0] for c in BOQ_LINE_ITEMS],
        show="headings", height=6)
    for col_id, col_title in BOQ_LINE_ITEMS:
        tree.heading(col_id, text=col_title)
        tree.column(col_id, width=70, minwidth=40)
    tree.column("description", width=180, minwidth=90)
    tree.pack(fill="x", pady=4)

    def on_compute_period():
        try:
            from qs_engine.valuation.calculator import (
                CommercialCalculator,
            )
            from qs_engine.valuation.exporter import (
                ensure_export_allowed,
            )
            from qs_engine.core.errors import ValidationError
        except ImportError as exc:
            boq_status.config(text=f"Import error: {exc}")
            return
        contract = entries["contract_sum"].get().strip() or "0"
        retention_rate = (entries["retention_rate_pct"].get().strip()
                          or "0")
        retention_limit = (entries["retention_limit"].get().strip()
                           or "0")
        advance = entries["advance_balance"].get().strip() or "0"
        previous_payments = (
            entries["previous_payments"].get().strip() or "0")
        prev_valuation = (
            entries["previous_valuation"].get().strip() or "0")
        onsite = entries["onsite_materials"].get().strip() or "0"
        advance_repaid = (entries["advance_repaid"].get().strip()
                          or "0")
        tax_rate = entries.get("tax_rate", None)
        tax_rate_val = (tax_rate.get().strip() if tax_rate
                        else "0")
        tax_mode = "withheld"
        items = []
        for widgets in ipc_rows:
            values = {field: widget.get().strip()
                      for field, widget in widgets.items()}
            if any(values.values()):
                items.append(values)
        for widget in tree.get_children():
            vals = {c[0]: tree.set(widget, c[0])
                    for c in BOQ_LINE_ITEMS}
            if vals["boq_ref"] or vals["description"]:
                items.append(vals)
        try:
            calc = CommercialCalculator(
                contract, retention_rate, retention_limit,
                advance_balance=advance,
                previous_payments=previous_payments,
                tax_rate_pct=tax_rate_val, tax_mode=tax_mode)
            result = calc.compute(
                previous_valuation=prev_valuation,
                items=items, onsite_materials=onsite,
                advance_repaid=advance_repaid,
                valuation_no=valuation_no_entry.get().strip()
                or "01",
                period_no=int(period_spin.get() or "1"),
                boq_limits=None)
        except ValidationError as exc:
            boq_status.config(text=f"\u25cf {exc.message}")
            return
        app.session.last_commercial = result
        for _key, _widget in card_values.items():
            _widget.config(text=str(getattr(result, _key)))
        boq_status.config(
            text=f"\u25cf Period {period_spin.get()} computed — "
                 f"Net: {result.net_payable} | "
                 f"Advance recovery: "
                 f"{result.advance_recovery_this_period}")
        refresh_pdf_readiness()
        app.refresh_status()

    def on_export_period_statement():
        from tkinter import filedialog
        from qs_engine.valuation.exporter import (
            export_ipc_statement_excel,
        )
        result = app.session.last_commercial
        if result is None:
            boq_status.config(
                text="Compute a period first "
                     "(Compute Period)")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV / Excel", "*.csv"),
                       ("Excel files", "*.xlsx")])
        if not path:
            return
        try:
            export_ipc_statement_excel(result, {}, path, app=app)
        except ValidationError as exc:
            boq_status.config(text=f"\u25cf {exc.message}")
            return
        boq_status.config(text=f"\u25cf Exported {path}")
        app.refresh_status()

    ttk.Button(left, text="Compute Period",
               style="Accent.TButton",
               command=on_compute_period).pack(anchor="w", pady=6)

    # -- right: one-click PDF export --------------------------------------
    pdf_readiness = ttk.Label(right, text="", style="Status.TLabel",
                              wraplength=420, justify="left")
    pdf_readiness.pack(anchor="w", pady=(2, 0))

    def refresh_pdf_readiness():
        compiled = app.session.last_compiled
        ipc = app.session.last_ipc
        commercial = app.session.last_commercial
        pdf_readiness.config(
            text="BOQ: "
                 f"{'ready' if compiled is not None else 'not compiled'} | "
                 f"IPC: {'ready' if ipc is not None else 'not computed'} | "
                 f"Commercial: "
                 f"{'ready' if commercial is not None else 'not computed'}")

    def document_info():
        project = app.session.project
        standard = app.session.standard
        return {
            "company_name": load_company_profile().get(
                "business_name", ""),
            "project_title": project.get("name", ""),
            "client": project.get("client", ""),
            "reference": project.get("reference", ""),
            "measurement_standard": (
                "" if standard is None else str(
                    standard.edition or standard.standard or "")),
            "date": "",
        }

    pdf_status = status_line(right)

    def on_export_boq_pdf():
        from tkinter import filedialog
        from qs_engine.ui import controllers
        from qs_engine.ui.viewmodels import ExportView
        blocked = _export_entitlement_error(app)
        if blocked is not None:
            pdf_status.config(text=blocked)
            return
        compiled = app.session.last_compiled
        if compiled is None:
            pdf_status.config(text="Compile the BOQ first (BOQ View)")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF document", "*.pdf")])
        if not path:
            return
        result = controllers.boq_pdf_controller(
            compiled, document_info(), path)
        if isinstance(result, ExportView):
            pdf_status.config(text=f"\u25cf Exported {result.path}")
        else:
            pdf_status.config(text=result.message)
        app.refresh_status()

    def on_export_ipc_pdf():
        from tkinter import filedialog
        from qs_engine.ui import controllers
        from qs_engine.ui.viewmodels import ExportView
        blocked = _export_entitlement_error(app)
        if blocked is not None:
            pdf_status.config(text=blocked)
            return
        valuation = app.session.last_ipc
        if valuation is None:
            pdf_status.config(
                text="Compute a valuation first (Compute Valuation)")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF document", "*.pdf")])
        if not path:
            return
        result = controllers.ipc_pdf_controller(
            valuation, document_info(), path)
        if isinstance(result, ExportView):
            pdf_status.config(text=f"\u25cf Exported {result.path}")
        else:
            pdf_status.config(text=result.message)
        app.refresh_status()

    ttk.Button(right, text="Export BOQ Summary PDF",
               style="Accent.TButton",
               command=on_export_boq_pdf).pack(anchor="w", pady=6)
    ipc_pdf_button = ttk.Button(right, text="Export IPC Statement PDF",
                                style="Accent.TButton",
                                command=on_export_ipc_pdf)
    ipc_pdf_button.pack(anchor="w", pady=(0, 6))
    register_export_guard(app, ipc_pdf_button, export_banner)
    period_csv_button = ttk.Button(
        right, text="Export Period Statement (CSV)",
        command=on_export_period_statement)
    period_csv_button.pack(anchor="w", pady=(6, 0))
    register_export_guard(app, period_csv_button,
                              export_banner)
    refresh_pdf_readiness()


#: Guidance banner for the Corporate Document Integration page.
CORPDOC_GUIDANCE = (
    "Edit the company identity on the left (saved to "
    "config/company_profile.json), pick a template on the right, then "
    "Generate Branded Document to stamp the last compiled BOQ into "
    ".docx in output/ (tick Export to PDF for a print-ready PDF summary "
    "alongside it). Compile the BOQ first (BOQ View)."
)

#: Full guide copy behind the registry keys used by page headers
#: (guide_key="...").  Single source of truth: page headers pass only
#: the key, tooltips derive their summary from this text, and the
#: "verification" key reuses the modal constant so the ? icon always
#: matches the Setup & Verification Guide verbatim.
REBAR_GUIDE_TEXT = (
    "• Fill the bar grid (units head each column) and "
    "Calculate — rows feed the schedule input below, then into a "
    "bar schedule with laps, hooks, and mass. Pick a steel grade "
    "and diameter to compose the bar designation; Unit Mass is an "
    "estimator entry (no value is auto-generated), and designations "
    "calculate only when a matching master-data record exists "
    "(Y grades work out of the box). Leave Unit Mass blank and "
    "supply Steel density instead to resolve mass through the "
    "engine's nominal-mass formula (diameter x density); with "
    "neither, the calculation fails closed. The schedule input "
    "stays editable under Advanced Input. Use the Formwork panel "
    "below for contact-area take-off with itemised deductions and "
    "optional material schedules."
)
OVERVIEW_GUIDE_TEXT = (
    "Central dashboard: project identity, take-off schedule "
    "size, BOQ status, and unresolved items. Work by domain from "
    "the sidebar."
)
MATERIALS_GUIDE_TEXT = (
    "Seed catalogue (read-only master data) plus user materials you "
    "add here, stored in your writable data folder — seed files are "
    "never modified. User materials carry identifiers only (name, "
    "code, category, unit); engineering values stay NEEDS_VERIFICATION "
    "until verified. Codes, names, categories, default units, "
    "densities, wastage defaults, and verification state; em-dashes "
    "mark nulls; pricing arrives per call through the Rate Builder — "
    "no universal price library exists. Select a row for details, "
    "or send a material to the Rate Builder."
)
ESTIMATE_GUIDE_TEXT = (
    "Cost summary rolled up from the last compiled BOQ: cost "
    "groups, resolved subtotal, and the tender value. Groups "
    "with unresolved sections are flagged partial; overheads and "
    "markups live in the Rate Builder and report separately. "
    "Compile the BOQ first (BOQ View)."
)
EXCEL_GUIDE_TEXT = (
    "Export the last compiled BOQ as a live-formula tender "
    "schedule, then reconcile a returned tender file against it. "
    "Reconciliation is read-only review — session truth is never "
    "overwritten unless you confirm it elsewhere. "
    "Compile the BOQ first (BOQ View)."
)
RECONCILIATION_GUIDE_TEXT = (
    "Reconcile theoretical QS allowances against actual site "
    "consumption. Import a site store log (.xlsx or .csv: Date, "
    "Transaction Type, Material, Quantity, Unit, Document Ref) — site "
    "material names and codes resolve against master keys, user "
    "codes, and the active material-code policy; unmatched lines are "
    "flagged, never dropped. Theoretical allowance = net BOQ quantity "
    "x (1 + wastage); variance = actual issued - theoretical. Set the "
    "overrun alert threshold, review the colour-coded variance grid, "
    "and export the variance report. Compile a BOQ first (BOQ View)."
)
VALUATIONS_GUIDE_TEXT = (
    "Value the current interim period from contract terms and "
    "completed quantities, then export formal PDFs. Retention is "
    "withheld at the contract rate up to its cap; advance recovery "
    "can never exceed the outstanding balance."
)
MIX_DESIGN_GUIDE_TEXT = (
    "Look up a concrete mix by Eurocode strength class (C8/10 to "
    "C30/37) for the target net volume and wastage %. Constituent "
    "quantities — cement bags + mass, sand, coarse aggregate, and "
    "batch water — compute live into the summary grid from BS EN 206 "
    "/ BS 8500 mass-based targets. Link to Materials Store to "
    "resolve constituent codes against the materials catalogue."
)

_GUIDE_CONTENT.update({
    "project": PANEL_INSTRUCTIONS["project"],
    "concrete": PANEL_INSTRUCTIONS["concrete"],
    "masonry": PANEL_INSTRUCTIONS["masonry"],
    "earthworks": PANEL_INSTRUCTIONS["earthworks"],
    "finishes": PANEL_INSTRUCTIONS["finishes"],
    "labour": PANEL_INSTRUCTIONS["labour"],
    "plant": PANEL_INSTRUCTIONS["plant"],
    "logistics": PANEL_INSTRUCTIONS["logistics"],
    "rates": PANEL_INSTRUCTIONS["rates"],
    "boq": PANEL_INSTRUCTIONS["boq"],
    "rebar": REBAR_GUIDE_TEXT,
    "overview": OVERVIEW_GUIDE_TEXT,
    "materials": MATERIALS_GUIDE_TEXT,
    "estimate": ESTIMATE_GUIDE_TEXT,
    "excel": EXCEL_GUIDE_TEXT,
    "corpdoc": CORPDOC_GUIDANCE,
    "valuations": VALUATIONS_GUIDE_TEXT,
    "verification": VERIFICATION_GUIDE_TEXT,
    "reconciliation": RECONCILIATION_GUIDE_TEXT,
    "mix_design": MIX_DESIGN_GUIDE_TEXT,
    "admin_setup": (
        "Administration (Tier 1 daily access). Unlock with the 6-12 digit "
        "operational PIN to open daily administration: rate updates, GL "
        "mapping and the Support & Helpdesk address (system.support_email "
        "in user_config.json). Five consecutive wrong PINs lock the "
        "operational tier out for five minutes. PIN rotation and security "
        "policy are never available here: they need the System Owner's "
        "Master Recovery Key (CVLK-XXXX-XXXX-XXXX)."
    ),
    "global_policy_editor": (
        "Locked security policy parameters, shown read-only: operational "
        "PIN length, failed attempts before lockout, lockout duration, "
        "PIN hashing cost, and the Master Recovery Key format. These "
        "values are enforced in code and can only be changed by the "
        "System Owner (SUPER_ADMIN) in Security Policy."
    ),
    "security_policy": (
        "System Owner view (Tier 2 - Master Recovery Key). Shows the "
        "active tier, whether the operational PIN and owner key are "
        "configured, the support desk address, and the Tier 2-only "
        "routes. Reaching this page requires the Master Recovery Key "
        "issued with a signed master_admin.lic."
    ),
})
_register_panel_guides()
try:
    from .widgets import set_guide_resolver as _set_resolver
    _set_resolver(_guide_text_resolver)
except Exception:
    pass

#: Company-profile editor rows: field -> label (disclaimers uses a
#: multi-line editor; logo and colour get picker widgets).
PROFILE_FIELD_LABELS = {
    "business_name": "Business Name",
    "registration_tax_id": "Registration / Tax ID",
    "contact_phone": "Contact Phone",
    "email": "Email",
    "physical_address": "Physical Address",
    "logo_path": "Logo (.png / .jpg)",
    "brand_accent_color": "Brand Accent Color",
}


def build_corpdoc_page(body, app):
    """Corporate Document & Template Manager: dual-pane workspace.

    Left: Company Profile Editor (identity fields, logo picker, brand
    colour, JSON persistence). Right: Document Output (template
    dropdown, document kind, custom .docx template, PDF toggle,
    Generate Branded Document pipeline).
    """
    from qs_engine.adapters.document.company_profile import (
        load_company_profile,
        save_company_profile,
    )
    from qs_engine.adapters.document.word_export import (
        CORPORATE_TEMPLATES,
        DOCUMENT_KINDS,
        TEMPLATE_DESCRIPTIONS,
    )
    build_page_header(body, "Corporate Document Integration",
                        CORPDOC_GUIDANCE, guide_key="corpdoc",
                        icon="📑")
    export_banner = guard_banner(body)
    panes = ttk.Frame(body)
    panes.pack(fill="both", expand=True)
    left = ttk.LabelFrame(panes, text="Company Profile Editor")
    left.pack(side="left", fill="both", expand=True, padx=(0, 4))
    right = ttk.LabelFrame(panes, text="Document Output")
    right.pack(side="left", fill="both", expand=True, padx=(4, 0))

    # -- left: company profile & identity editor -------------------------
    profile = load_company_profile()
    entries = {}
    profile_grid = ttk.Frame(left)
    profile_grid.pack(fill="x", pady=2)
    profile_grid.grid_columnconfigure(1, weight=1)
    for index, (field, label) in enumerate(PROFILE_FIELD_LABELS.items()):
        if index < 4:
            rownum, half = divmod(index, 2)
            label_col, entry_col, span = half * 2, half * 2 + 1, 1
        elif index == 4:
            rownum, label_col, entry_col, span = 2, 0, 1, 3
        else:
            rownum, label_col, entry_col, span = index - 1, 0, 1, 1
        ttk.Label(profile_grid, text=label,
                  width=18 if label_col == 0 else 22).grid(
                      row=rownum, column=label_col,
                      padx=(0, 2) if label_col == 0 else (6, 2),
                      pady=2, sticky="w")
        entry = ttk.Entry(profile_grid, width=22)
        entry.insert(0, profile.get(field, ""))
        entry.grid(row=rownum, column=entry_col, columnspan=span,
                   padx=2, pady=2, sticky="ew")
        entries[field] = entry
    ttk.Label(left, text="Legal Disclaimers:").pack(anchor="w", pady=(4, 0))
    disclaimers = tk.Text(left, height=4, wrap="word", background="white")
    disclaimers.pack(fill="x")
    disclaimers.insert("end", profile.get("legal_disclaimers", ""))
    # tk.Text has no -disabledbackground option (that is a ttk.Entry
    # option); the white background is set at construction instead.
    disclaimers.configure(state="disabled")
    profile_status = status_line(left)

    def collect_profile():
        collected = {field: widget.get()
                     for field, widget in entries.items()}
        collected["legal_disclaimers"] = profile.get("legal_disclaimers", "")
        return collected

    def fill_profile_widgets(values):
        for field, widget in entries.items():
            widget.delete(0, "end")
            widget.insert(0, values.get(field, ""))
        disclaimers.delete("1.0", "end")
        disclaimers.insert("end", values.get("legal_disclaimers", ""))

    def on_browse_logo():
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            filetypes=[("Images", "*.png *.jpg *.jpeg"),
                       ("All files", "*.*")])
        if path:
            entries["logo_path"].delete(0, "end")
            entries["logo_path"].insert(0, path)

    def on_pick_colour():
        from tkinter import colorchooser
        current = entries["brand_accent_color"].get().strip() or "#004F9D"
        picked = colorchooser.askcolor(color=current)[1]
        if picked:
            entries["brand_accent_color"].delete(0, "end")
            entries["brand_accent_color"].insert(0, picked.upper())

    def on_save_profile():
        from qs_engine.core.errors import ValidationError
        try:
            saved = save_company_profile(collect_profile())
        except ValidationError as exc:
            profile_status.config(text=str(exc))
            app.refresh_status()
            return
        profile_status.config(text=f"\u25cf Saved company profile to "
                                   f"{saved}")
        app.refresh_status()

    def on_reload_profile():
        fill_profile_widgets(load_company_profile())
        profile_status.config(text="\u25cf Reloaded company profile "
                                   "from config/company_profile.json")
        app.refresh_status()

    ttk.Button(profile_grid, text="Browse Logo…",
               style="Accent.TButton",
               command=on_browse_logo).grid(row=3, column=2, padx=(4, 0),
                                            pady=2, sticky="w")
    ttk.Button(profile_grid, text="Pick Accent Colour…",
               style="Accent.TButton",
               command=on_pick_colour).grid(row=4, column=2, padx=(4, 0),
                                            pady=2, sticky="w")
    save_row = ttk.Frame(left)
    save_row.pack(fill="x", pady=2)
    ttk.Button(save_row, text="Save Profile", style="Accent.TButton",
               command=on_save_profile).pack(side="left", padx=(0, 6))
    ttk.Button(save_row, text="Reload", style="Accent.TButton",
               command=on_reload_profile).pack(side="left")

    # -- right: template selection hub + export pipeline ------------------
    template_labels = [label for _key, label in CORPORATE_TEMPLATES]
    template_keys = [key for key, _label in CORPORATE_TEMPLATES]
    kind_labels = [label for _key, label in DOCUMENT_KINDS]
    kind_keys = [key for key, _label in DOCUMENT_KINDS]
    ttk.Label(right, text="Template:").pack(anchor="w", pady=(2, 0))
    template_combo = ttk.Combobox(right, state="readonly",
                                  values=template_labels)
    template_combo.current(0)
    template_combo.pack(fill="x")
    template_desc = ttk.Label(right, text="", style="Status.TLabel",
                              wraplength=420, justify="left")
    template_desc.pack(anchor="w", pady=(2, 0))

    def refresh_template_desc(_event=None):
        key = template_keys[template_combo.current()]
        template_desc.config(text=TEMPLATE_DESCRIPTIONS[key])

    template_combo.bind("<<ComboboxSelected>>", refresh_template_desc)
    refresh_template_desc()
    ttk.Label(right, text="Document kind:").pack(anchor="w", pady=(6, 0))
    kind_combo = ttk.Combobox(right, state="readonly", values=kind_labels)
    kind_combo.current(0)
    kind_combo.pack(fill="x")
    ttk.Label(right, text="Custom template (.docx with "
                          "{{merge tags}}):").pack(anchor="w", pady=(6, 0))
    custom_row = ttk.Frame(right)
    custom_row.pack(fill="x")
    custom_entry = ttk.Entry(custom_row, width=30)
    custom_entry.pack(side="left", fill="x", expand=True)

    def on_browse_custom():
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            filetypes=[("Word template", "*.docx"),
                       ("All files", "*.*")])
        if path:
            custom_entry.delete(0, "end")
            custom_entry.insert(0, path)

    ttk.Button(custom_row, text="Browse…", style="Accent.TButton",
               command=on_browse_custom).pack(side="left", padx=(4, 0))
    pdf_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(right, text="Export to PDF (print-ready summary "
                                "alongside the .docx)",
                    variable=pdf_var).pack(anchor="w", pady=(6, 0))
    readiness = ttk.Label(right, text="", style="Status.TLabel",
                          wraplength=420, justify="left")
    readiness.pack(anchor="w", pady=(4, 0))

    def refresh_readiness():
        compiled = app.session.last_compiled
        if compiled is None:
            readiness.config(text="Status: no compiled BOQ in this "
                                  "session yet — compile it on the BOQ "
                                  "View first.")
        else:
            readiness.config(
                text=f"Ready: {len(compiled.unresolved_items)} "
                     f"unresolved, resolved subtotal "
                     f"{compiled.resolved_subtotal}")

    doc_status = status_line(right)

    def on_compile():
        from qs_engine.ui import controllers
        from qs_engine.ui.viewmodels import ExportView
        blocked = _export_entitlement_error(app)
        if blocked is not None:
            doc_status.config(text=blocked)
            return
        compiled = app.session.last_compiled
        if compiled is None:
            doc_status.config(text="Compile the BOQ first (BOQ View)")
            return
        result = controllers.branded_document_controller(
            compiled, profile=collect_profile(),
            template=template_keys[template_combo.current()],
            document_kind=kind_keys[kind_combo.current()],
            custom_template_path=custom_entry.get().strip() or None,
            export_pdf=bool(pdf_var.get()))
        if isinstance(result, ExportView):
            doc_status.config(text=f"\u25cf {result.detail}: "
                                   f"{result.path}")
        else:
            doc_status.config(text=result.message)
        refresh_readiness()
        app.refresh_status()

    generate_button = ttk.Button(right, text="Generate Branded Document",
                                 style="Accent.TButton",
                                 command=on_compile)
    generate_button.pack(anchor="w", pady=6)
    register_export_guard(app, generate_button, export_banner)
    refresh_readiness()


def _provision_licensing_backups():
    """Create the licensing backups root on launch (never raises).

    ``%APPDATA%\\CIVOLINK\\licensing\\backups`` holds timestamped copies of
    license artifacts and owner recovery state; provisioning it up front
    means the first backup can never fail for a missing directory.
    """
    try:
        from pathlib import Path as _Path
        from qs_engine.licensing.storage import default_license_dir
        backups = _Path(default_license_dir()) / "licensing" / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        return backups
    except Exception:
        return None      # read-only profile: backups are best-effort


def _security_context(app):
    """Session security context (Tier 1/2 state), created on first use."""
    context = getattr(app, "security", None)
    if context is None:
        from qs_engine.core.security import SessionContext
        context = SessionContext()
        try:
            app.security = context
        except Exception:
            pass
    return context


def _sync_admin_nav(app) -> None:
    """Re-evaluate ADMINISTRATION sidebar visibility after a tier change."""
    sync = getattr(app, "_sync_admin_nav", None)
    if callable(sync):
        sync()


def build_admin_setup_page(body, app):
    """Administration: Tier 1 PIN unlock, support desk, Tier 2 rotation."""
    from qs_engine.core.errors import QSEngineError, ValidationError
    build_page_header(body, "Administration",
                      guide_key="admin_setup", icon="🔧")
    ctx = _security_context(app)
    status = status_line(body)

    ttk.Label(body, text="Unlock daily administration (Tier 1)",
              style="Header.TLabel").pack(anchor="w", pady=(8, 2))
    unlock_row = ttk.Frame(body)
    unlock_row.pack(fill="x")
    pin_var = tk.StringVar()
    ttk.Label(unlock_row, text="Operational PIN:").pack(side="left")
    ttk.Entry(unlock_row, textvariable=pin_var, width=14,
              show="*").pack(side="left", padx=4)

    def _unlock():
        try:
            ctx.unlock_with_pin(pin_var.get())
        except (QSEngineError, ValidationError) as exc:
            status.config(text=f"Unlock refused: {exc}")
            return
        pin_var.set("")
        _sync_admin_nav(app)
        status.config(text="● Unlocked as OPERATIONAL_ADMIN")

    ttk.Button(unlock_row, text="Unlock", style="Accent.TButton",
               command=_unlock).pack(side="left", padx=4)

    ttk.Label(body, text="Support & Helpdesk",
              style="Header.TLabel").pack(anchor="w", pady=(10, 2))
    email_row = ttk.Frame(body)
    email_row.pack(fill="x")
    email_var = tk.StringVar(value=ctx.support_email)
    ttk.Entry(email_row, textvariable=email_var,
              width=34).pack(side="left", padx=4)

    def _save_email():
        try:
            saved = ctx.set_support_email(email_var.get())
        except (QSEngineError, ValidationError) as exc:
            status.config(text=f"Not saved: {exc}")
            return
        status.config(text=f"● Support email saved: {saved}" if saved
                      else "● Support email cleared")

    ttk.Button(email_row, text="Save Support Email",
               command=_save_email).pack(side="left", padx=4)

    ttk.Label(body,
              text="Owner recovery (Tier 2 — Master Recovery Key)",
              style="Header.TLabel").pack(anchor="w", pady=(10, 2))
    owner_row = ttk.Frame(body)
    owner_row.pack(fill="x")
    key_var = tk.StringVar()
    new_pin_var = tk.StringVar()
    ttk.Label(owner_row, text="Master Key:").pack(side="left")
    ttk.Entry(owner_row, textvariable=key_var,
              width=24).pack(side="left", padx=4)
    ttk.Label(owner_row, text="New PIN:").pack(side="left", padx=(8, 0))
    ttk.Entry(owner_row, textvariable=new_pin_var,
              width=12).pack(side="left", padx=4)

    def _rotate():
        try:
            ctx.reset_pin_with_recovery(key_var.get(), new_pin_var.get())
        except (QSEngineError, ValidationError) as exc:
            status.config(text=f"PIN rotation refused: {exc}")
            return
        key_var.set("")
        new_pin_var.set("")
        _sync_admin_nav(app)
        status.config(text="● Owner reset complete — session is SUPER_ADMIN")

    ttk.Button(owner_row, text="Rotate PIN (Owner)",
               command=_rotate).pack(side="left", padx=4)
    return body


def _policy_row(body, label, value):
    """One label/value row for the read-only policy views."""
    row = ttk.Frame(body)
    row.pack(fill="x", pady=1)
    ttk.Label(row, text=label, width=32).pack(side="left")
    ttk.Label(row, text=value, style="Status.TLabel").pack(side="left")


def build_global_policy_editor_page(body, app):
    """Global policy reference (read-only snapshot of locked parameters)."""
    from qs_engine.core import security as sec
    build_page_header(body, "Global Policy",
                      guide_key="global_policy_editor", icon="📜")
    status = status_line(body)
    ttk.Label(body, text="Locked policy parameters",
              style="Header.TLabel").pack(anchor="w", pady=(6, 2))
    _policy_row(body, "Operational PIN length",
                f"{sec.PIN_MIN_LEN}-{sec.PIN_MAX_LEN} digits")
    _policy_row(body, "Failed attempts before lockout",
                str(sec.PIN_LOCKOUT_THRESHOLD))
    _policy_row(body, "Lockout duration",
                f"{sec.PIN_LOCKOUT_SECONDS} seconds")
    _policy_row(body, "PIN hashing",
                f"PBKDF2-HMAC-SHA256, {sec.PBKDF2_ITERATIONS} rounds")
    _policy_row(body, "Master Recovery Key format",
                f"{sec.MASTER_KEY_PREFIX}-XXXX-XXXX-XXXX")
    status.config(text="● Policy is enforced in code; values are read-only.")
    return body


def build_security_policy_page(body, app):
    """Security policy (SUPER_ADMIN only): tier matrix and owner state."""
    from qs_engine.core import security as sec
    build_page_header(body, "Security Policy",
                      guide_key="security_policy", icon="🛡️")
    ctx = _security_context(app)
    status = status_line(body)
    state = ctx.get_admin_status()
    ttk.Label(body, text="Active session", style="Header.TLabel").pack(
        anchor="w", pady=(6, 2))
    _policy_row(body, "Role", state["role"])
    _policy_row(body, "Administrative access",
                "yes" if state["is_admin"] else "no")
    _policy_row(body, "System Owner",
                "yes" if state["is_super_admin"] else "no")
    _policy_row(body, "Operational PIN configured",
                "yes" if state["pin_configured"] else "no")
    _policy_row(body, "Owner key loaded",
                "yes" if state["master_key_configured"] else "no")
    _policy_row(body, "Support desk", state["support_email"] or "not set")
    ttk.Label(body, text="Tier 2 views: "
              + ", ".join(sorted(sec.SUPER_ADMIN_ONLY_VIEWS)),
              style="Status.TLabel").pack(anchor="w", pady=(8, 2))
    status.config(text="● Owner tier — PIN rotation and policy are yours.")
    return body


PAGES = {
    "overview": build_overview_page,
    "project": build_project_page,
    "concrete": build_concrete_page,
    "masonry": lambda body, app: build_takeoff_page(
        body, app, "masonry", "masonry",
        override_source=lambda app=app: session_override_context(
            app.session.project, "masonry")),
    "rebar": build_rebar_page,
    "earthworks": lambda body, app: build_takeoff_page(
        body, app, "earthworks", "earthworks",
        override_source=lambda app=app: session_override_context(
            app.session.project, "earthworks")),
    "finishes": lambda body, app: build_takeoff_page(
        body, app, "finishes", "finishes"),
    "materials": build_materials_page,
    "labour_plant": build_labour_plant_page,
    "reconciliation": build_reconciliation_page,
    "logistics": lambda body, app: build_takeoff_page(
        body, app, "logistics", "logistics", add_enabled=False,
        override_source=lambda app=app: session_override_context(
            app.session.project, "logistics"),
        summary_spec=("Haulage Summary", (
            ("limiting", "Limiting constraint"),
            ("cycle_minutes", "Cycle (minutes)"),
            ("trips_ordered", "Trips (ordered)"),
            ("trucks_required", "Trucks required"),
            ("daily_capacity", "Daily capacity"),
        ))),
    "rates": build_rates_page,
    "boq": build_boq_page,
    "estimate": build_estimate_page,
    "excel": build_excel_page,
    "corpdoc": build_corpdoc_page,
     "valuations": build_valuations_page,
     "mix_design": build_mix_design_page,
    "admin_setup": build_admin_setup_page,
    "global_policy_editor": build_global_policy_editor_page,
    "security_policy": build_security_policy_page,
 }


def build_status_text(session) -> str:
    """Pure status-bar text from session state (headless-testable).

    Indicators: project saved marker, BOQ state (reconciled total,
    unresolved count, or not compiled), bound standard, and the standing
    measurement-rules governance flag.
    """
    counts = session.summary_counts()
    parts = [f"Lines: {counts['lines']}"]
    parts.append("● Project Saved" if session.project_saved
                 else "○ No Project")
    compiled = session.last_compiled
    if compiled is None:
        parts.append("○ BOQ: Not Compiled")
    elif compiled.has_unresolved:
        parts.append(f"⚠ BOQ: {len(compiled.unresolved_items)} unresolved")
    else:
        parts.append(f"● BOQ Reconciled: {compiled.total}")
    standard = session.standard
    parts.append(f"Standard: {standard.standard}"
                 if standard is not None else "Standard: [Not Bound]")
    parts.append("⚠ Measurement Rules Need Verification")
    return " | ".join(parts)


class ScrollableFrame(ttk.Frame):
    """Vertically scrollable container (headless-safe until packed).

    Pages build into .interior exactly as before; a scrollbar appears
    only when content exceeds the viewport (e.g. tall take-off pages
    at 1080p). Mouse-wheel scrolling binds while the pointer is over
    the canvas or any child (recursive hover bindings pick up
    dynamically added rows too); Shift+wheel pans horizontally,
    PageUp/PageDown/Home/End/arrows work from keyboard focus or hover
    (never stealing keystrokes from entries), and middle-drag pans.
    """

    #: Keysyms for keyboard page navigation (widget + hover bindings).
    _NAV_KEYS = ("<Prior>", "<Next>", "<Home>", "<End>",
                 "<Up>", "<Down>")

    #: Widget classes that keep their own keystrokes (never hijacked).
    _TYPING_CLASSES = ("TEntry", "TCombobox", "TSpinbox", "Text",
                       "Entry", "Spinbox")

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, background=CANVAS_BG,
                                highlightthickness=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical",
                                  command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.interior = ttk.Frame(self.canvas, padding=10)
        self.canvas_window_id = self.canvas.create_window(
            (0, 0), window=self.interior, anchor="nw")
        #: Debounce state for <Configure> storm suppression
        self._configure_job = None
        self._canvas_width = None
        #: Debounce / dedup state for mousewheel events
        self._mousewheel_bound = set()
        self._last_wheel_sig = None
        self._last_wheel_time = 0
        self.interior.bind(
            "<Configure>",
            lambda _event: self._schedule_layout_update())
        self.canvas.bind(
            "<Configure>",
            lambda event: self._schedule_layout_update(event.width))
        self._wheel_bound = set()
        self._hover_keys_active = False
        self._bind_tree(self)
        self._bind_mousewheel_tree(self)
        for surface in (self.canvas, self.interior):
            surface.bind("<ButtonPress-2>", self._pan_mark, add="+")
            surface.bind("<B2-Motion>", self._pan_drag, add="+")
            surface.bind("<ButtonRelease-2>", self._pan_end, add="+")

    def refresh_wheel_bindings(self):
        """(Re)bind hover scrolling over the current widget subtree."""
        self._bind_tree(self)
        self._bind_mousewheel_tree(self)

    def _bind_tree(self, widget):
        """Recursive Enter/Leave (+ Linux wheel, nav keys) binding.

        add="+" preserves every existing widget binding; already-bound
        widgets are skipped so dynamic rows can re-run this safely.
        """
        try:
            key = str(widget)
            children = widget.winfo_children()
        except Exception:
            return
        if key not in self._wheel_bound:
            self._wheel_bound.add(key)
            widget.bind("<Enter>", self._on_sub_enter, add="+")
            widget.bind("<Leave>", self._on_sub_leave, add="+")
            widget.bind("<Button-4>", self._on_mousewheel, add="+")
            widget.bind("<Button-5>", self._on_mousewheel, add="+")
            for keysym in self._NAV_KEYS:
                widget.bind(keysym, self._on_nav_key_widget, add="+")
        for child in children:
            self._bind_tree(child)

    def _bind_mousewheel_tree(self, widget):
        """Recursively bind mousewheel delegation on child widgets.

        Binds <MouseWheel> (Windows/macOS) and <Button-4>/<Button-5>
        (Linux) directly on each non-Combobox descendant so that wheel
        gestures over labels, entries, and panels are captured even
        when the widget swallows the event before it reaches bind_all.

        Comboboxes are spared to preserve their dropdown option-cycling.
        The add="+" flag preserves existing widget bindings; an
        _mousewheel_bound set guards against duplicate binds so
        dynamic rows can re-run this safely.
        """
        try:
            key = str(widget)
            children = widget.winfo_children()
        except Exception:
            return
        if key not in self._mousewheel_bound:
            self._mousewheel_bound.add(key)
            cls = widget.winfo_class()
            if cls not in ("TCombobox", "Combobox"):
                widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
                widget.bind("<Button-4>", self._on_mousewheel, add="+")
                widget.bind("<Button-5>", self._on_mousewheel, add="+")
        for child in children:
            self._bind_mousewheel_tree(child)

    def _unbind_mousewheel_tree(self, widget):
        """Recursively remove mousewheel delegation from child widgets."""
        try:
            key = str(widget)
            children = widget.winfo_children()
        except Exception:
            return
        if key in self._mousewheel_bound:
            self._mousewheel_bound.discard(key)
            cls = widget.winfo_class()
            if cls not in ("TCombobox", "Combobox"):
                widget.unbind("<MouseWheel>")
                widget.unbind("<Button-4>")
                widget.unbind("<Button-5>")
        for child in children:
            self._unbind_mousewheel_tree(child)

    def _bind_wheel(self, _event=None):
        if self._hover_keys_active:
            return  # already bound: bind_all appends, never replace
        self._bind_mousewheel_tree(self)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.canvas.bind_all("<Button-4>", self._on_mousewheel, add="+")
        self.canvas.bind_all("<Button-5>", self._on_mousewheel, add="+")
        for keysym in self._NAV_KEYS:
            self.canvas.bind_all(keysym, self._on_nav_key_global,
                                 add="+")
        self._hover_keys_active = True

    def _unbind_wheel(self, _event=None):
        self._unbind_mousewheel_tree(self)
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")
        for keysym in self._NAV_KEYS:
            self.canvas.unbind_all(keysym)
        self._hover_keys_active = False

    def _on_sub_enter(self, _event=None):
        self._bind_tree(self)  # pick up dynamically added rows
        self._bind_mousewheel_tree(self)
        self._bind_wheel()

    def _is_cursor_inside(self, widget_under_mouse=None):
        """Is the pointer inside this container (widget tree or bounds)?

        1. Hierarchy walk for explicit widget validation (precise,
        headless-safe, and loop-guarded at the root window).
        2. Screen-coordinate bounding-box check: bulletproof across
        dynamically generated children and canvas items that the
        containing lookup may miss.
        """
        if widget_under_mouse is not None:
            curr = widget_under_mouse
            while curr is not None:
                if (curr == self or curr == self.canvas
                        or curr == self.interior):
                    return True
                try:
                    parent_name = curr.winfo_parent()
                except (KeyError, AttributeError, tk.TclError):
                    break
                if not parent_name:  # root window or unparented widget
                    break
                try:
                    parent_widget = curr.nametowidget(parent_name)
                except (KeyError, AttributeError, tk.TclError):
                    break
                if parent_widget is None or parent_widget == curr:
                    break
                curr = parent_widget
        try:
            if not self.winfo_viewable():
                return False
            x, y = self.winfo_pointerx(), self.winfo_pointery()
            wx, wy = self.winfo_rootx(), self.winfo_rooty()
            ww, wh = self.winfo_width(), self.winfo_height()
            return wx <= x <= wx + ww and wy <= y <= wy + wh
        except Exception:
            return False

    def _on_sub_leave(self, event=None):
        # Do NOT unbind if the cursor is simply moving between child
        # widgets inside the container
        if not self._is_cursor_inside():
            self._unbind_wheel()

    def _scroll(self, event):
        delta = getattr(event, "delta", 0)
        if delta:
            # Direct unit stepping for any non-zero delta (precision
            # touchpad ticks or wheel clicks): small deltas collapse to
            # a single signed unit instead of truncating to zero.
            if abs(delta) < 120:
                lines = -1 if delta > 0 else 1
            else:
                lines = int(-1 * (delta / 120))
            try:
                if getattr(event, "state", 0) & 0x1:  # Shift: horizontal
                    self.canvas.xview_scroll(lines, "units")
                else:
                    self.canvas.yview_scroll(lines, "units")
            except tk.TclError:
                pass  # frame destroyed mid-gesture: nothing to scroll

    def _on_mousewheel(self, event):
        """Single entry point for all wheel events, all platforms.

        Validates the real-time pointer location first: events firing
        while the pointer is outside this container are ignored, so
        nested-child crossings can never leak scrolls elsewhere.
        Windows/macOS deltas pass straight through; Linux Button-4/5
        carry direction in event.num and are normalized to raw-delta
        form before delegating to _scroll.

        A short time-based guard deduplicates events that fire from
        both widget-level bindings and bind_all during the same
        gesture, preventing scroll-doubling.
        """
        import sys
        import time
        from types import SimpleNamespace
        # Deduplicate concurrent widget-level + bind_all dispatch
        now = time.monotonic()
        sig = (getattr(event, "num", None), getattr(event, "delta", 0))
        if sig == self._last_wheel_sig and now - self._last_wheel_time < 50 / 1000:
            return
        self._last_wheel_sig = sig
        self._last_wheel_time = now
        try:
            x, y = self.winfo_pointerx(), self.winfo_pointery()
            widget_under_mouse = self.winfo_containing(x, y)
        except tk.TclError:
            return
        if not self._is_cursor_inside(widget_under_mouse):
            return
        if sys.platform.startswith("win") or sys.platform == "darwin":
            self._scroll(event)
            return
        num = getattr(event, "num", None)
        state = getattr(event, "state", 0)
        if num == 4:
            self._scroll(SimpleNamespace(delta=120, state=state))
        elif num == 5:
            self._scroll(SimpleNamespace(delta=-120, state=state))
        # else: unknown button event → ignore

    def _typing_has_focus(self, event):
        """True when keystrokes belong to an entry/text widget."""
        widget = getattr(event, "widget", None)
        try:
            focused = widget.focus_get() if widget is not None else None
            cls = (focused.winfo_class()
                   if focused is not None else widget.winfo_class())
        except Exception:
            return False
        return cls in self._TYPING_CLASSES

    def _do_nav_key(self, event):
        keysym = getattr(event, "keysym", "")
        try:
            if keysym in ("Prior", "Page_Up"):
                self.canvas.yview_scroll(-1, "pages")
            elif keysym in ("Next", "Page_Down"):
                self.canvas.yview_scroll(1, "pages")
            elif keysym == "Home":
                self.canvas.yview_moveto("0.0")
            elif keysym == "End":
                self.canvas.yview_moveto("1.0")
            elif keysym == "Up":
                self.canvas.yview_scroll(-1, "units")
            elif keysym == "Down":
                self.canvas.yview_scroll(1, "units")
        except tk.TclError:
            pass  # frame destroyed mid-gesture: nothing to scroll

    def _on_nav_key_widget(self, event):
        """Widget-level nav keys (keyboard focus inside the frame).

        Defers to the hover binding when active so one keypress never
        scrolls twice; typing widgets always keep their keystrokes.
        """
        if self._typing_has_focus(event) or self._hover_keys_active:
            return
        self._do_nav_key(event)

    def _on_nav_key_global(self, event):
        """Hover-level nav keys (pointer over the frame)."""
        if self._typing_has_focus(event):
            return
        self._do_nav_key(event)

    def _pan_mark(self, event):
        try:
            self.canvas.scan_mark(event.x, event.y)
        except Exception:
            pass

    def _pan_drag(self, event):
        try:
            self.canvas.scan_dragto(event.x, event.y)
        except Exception:
            pass

    def _pan_end(self, _event=None):
        pass

    def _schedule_layout_update(self, canvas_width=None):
        """Debounce canvas/interior <Configure> events.

        Coalesces rapid-fire configure events (resize, content
        add/remove) into a single deferred layout pass via
        after_idle, preventing CPU/GPU redraw storms and audible
        coil whine during live resize.
        """
        if canvas_width is not None:
            self._canvas_width = canvas_width
        if self._configure_job is not None:
            self.after_cancel(self._configure_job)
        self._configure_job = self.after_idle(self._do_layout_update)

    def _do_layout_update(self):
        """Apply deferred layout: scrollregion + canvas window width."""
        self._configure_job = None
        try:
            self.canvas.configure(
                scrollregion=self.canvas.bbox("all"))
        except tk.TclError:
            pass  # widget destroyed mid-event
        if self._canvas_width is not None:
            try:
                self.canvas.itemconfig(
                    self.canvas_window_id, width=self._canvas_width)
            except tk.TclError:
                pass  # widget destroyed mid-event





def _enable_windows_dpi_awareness() -> None:
    """Process-wide Windows DPI awareness for crisp native rendering.

    Per-Monitor V2 when available, legacy system-aware fallback.
    No-op off Windows; idempotent and exception-proof so headless
    suites and repeated construction can never fail. Must run before
    any tk.Tk window exists (first call wins per process).
    """
    import sys
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class QSApp(tk.Tk):
    """Project-centric shell: sidebar navigation + workspace + status."""

    def __init__(self, repository=None):
        _enable_windows_dpi_awareness()
        super().__init__()
        self.title(APP_TITLE)
        _apply_civolink_theme(self)
        # Phase 25 material override stack. Default sessions get the full
        # seed + user resolution boundary through the shared
        # default_repository() factory (the same primary lookup interface
        # the HTTP API uses); an explicitly injected repository is
        # respected verbatim (tests/fixtures stay exact).
        self.material_stack = None
        self.material_store_error = None
        if repository is None:
            from qs_engine.resources import default_repository
            (self.repository, self.material_stack,
             self.material_store_error) = default_repository()
        else:
            self.repository = repository
            try:
                from qs_engine.resources import MaterialStack, MaterialResolver
                if isinstance(repository, MaterialResolver):
                    self.material_stack = MaterialStack(
                        resolver=repository, store=repository.store,
                        registry=repository.registry)
            except ImportError:
                pass
        self.session = TakeoffSession()
        from qs_engine.licensing.provider import NullProvider
        from qs_engine.licensing.service import LicensingService
        from qs_engine.licensing.storage import LicenseStore
        self.license_service = LicensingService(
            provider=NullProvider(), store=LicenseStore())
        self._nav_buttons = {}
        self._admin_nav_widgets = []
        # Two-tier security context: least privilege at launch, plus the
        # System Owner's signed master_admin.lic when one is installed.
        self.security = _security_context(self)
        try:
            self.security.load_master_recovery_key()
        except Exception:
            pass  # a missing/tampered owner license is simply no key
        _provision_licensing_backups()
        self._current = None
        self.active_route_key = None
        self._project_path = None
        self._build_menu()

        self.panes = ttk.PanedWindow(self, orient="horizontal")
        sidebar = ttk.Frame(self.panes, width=230)
        sidebar.pack_propagate(False)
        nav_canvas = tk.Canvas(sidebar, highlightthickness=0,
                               background=CANVAS_BG)
        nav_vbar = ttk.Scrollbar(sidebar, orient="vertical",
                                 command=nav_canvas.yview)
        nav_canvas.configure(yscrollcommand=nav_vbar.set)
        nav_vbar.pack(side="right", fill="y")
        nav_canvas.pack(side="left", fill="both", expand=True)
        nav_inner = ttk.Frame(nav_canvas)
        nav_window_id = nav_canvas.create_window(
            (0, 0), window=nav_inner, anchor="nw")
        nav_inner.bind(
            "<Configure>",
            lambda _event: nav_canvas.configure(
                scrollregion=nav_canvas.bbox("all")))
        nav_canvas.bind(
            "<Configure>",
            lambda event: nav_canvas.itemconfig(
                nav_window_id, width=event.width))
        ttk.Label(nav_inner, text="CIVOLINK QS", style="Header.TLabel").pack(
            anchor="w", padx=8, pady=(8, 0))
        ttk.Label(nav_inner, text="Estimating Engine",
                  style="Status.TLabel").pack(anchor="w", padx=8)
        for group, items in NAV_GROUPS:
            restricted = group in RESTRICTED_NAV_GROUPS
            group_label = ttk.Label(
                nav_inner,
                text=f"{NAV_GROUP_ICONS[group]} {group}",
                style="Status.TLabel")
            group_label.pack(anchor="w", padx=8, pady=(10, 2))
            if restricted:
                self._admin_nav_widgets.append(
                    (group_label, {"anchor": "w", "padx": 8,
                                    "pady": (10, 2)}))
            for key, label, _kind in items:
                button = tk.Button(
                    nav_inner,
                    text="  " + f"{NAV_ITEM_ICONS.get(key, '')} {label}",
                    anchor="w", relief="flat",
                    bg=CANVAS_BG, fg=SLATE_GREY, activebackground=CIVOLINK_BLUE,
                    activeforeground="white", borderwidth=0,
                    command=lambda key=key: self.show(key))
                button.pack(fill="x", padx=4, pady=1)
                if restricted:
                    self._admin_nav_widgets.append(
                        (button, {"fill": "x", "padx": 4, "pady": 1}))
                self._nav_buttons[key] = button
        # ADMINISTRATION stays hidden until the session unlocks Tier 1+.
        self._sync_admin_nav()

        def _scroll_nav(event):
            """Sidebar wheel scroll (widget-level; stops propagation).

            Bound directly on every nav widget with add="+", so the
            workspace hover bindings never double-scroll. Returns
            "break" to keep the event inside the sidebar.
            """
            delta = getattr(event, "delta", 0)
            steps = None
            if delta:
                steps = (-1 if delta > 0 else 1) if abs(delta) < 120 \
                    else int(-delta / 120)
            elif getattr(event, "num", None) == 4:
                steps = -1
            elif getattr(event, "num", None) == 5:
                steps = 1
            if steps is not None:
                try:
                    nav_canvas.yview_scroll(steps, "units")
                except tk.TclError:
                    pass
            return "break"

        def _bind_nav_tree(widget):
            try:
                children = widget.winfo_children()
            except Exception:
                return
            widget.bind("<MouseWheel>", _scroll_nav, add="+")
            widget.bind("<Button-4>", _scroll_nav, add="+")
            widget.bind("<Button-5>", _scroll_nav, add="+")
            for child in children:
                _bind_nav_tree(child)

        _bind_nav_tree(sidebar)

        self.workspace = ScrollableFrame(self.panes)
        # Bottom chrome packs BEFORE the expanding workspace. Tk pack
        # carves each slave's parcel from the remaining cavity in
        # order: side=bottom widgets packed after an expand=True
        # workspace steal its horizontal space, collapsing the canvas
        # to requested width and parking the vbar mid-window. Packing
        # the status strip first reserves the bottom band and lets the
        # workspace claim the full remaining region
        # (sidebar -> chrome -> fill).
        self.status_bar = ttk.Frame(self, style="StatusBar.TFrame")
        self._segments = []
        for index, _key in enumerate(STATUS_SEGMENTS):
            if index:
                ttk.Separator(self.status_bar,
                              orient="vertical").pack(
                                  side="left", fill="y", padx=6, pady=2)
            label = ttk.Label(self.status_bar, text="",
                              style="Segment.TLabel", wraplength=220,
                              justify="left")
            label.pack(side="left", padx=2, pady=2)
            self._segments.append(label)
        self.watermark = ttk.Label(self.status_bar, text=FOOTER_BADGE,
                                   style="Footer.TLabel")
        self.watermark.pack(side="right", padx=10)
        self.status_bar.pack(side="bottom", fill="x")
        self.panes.add(sidebar, weight=0)
        self.panes.add(self.workspace, weight=1)
        # Tk 9 ttk::panedwindow has no per-pane minsize: snap the sash
        # back to the 210px sidebar floor when a drag releases below it.
        self.panes.bind("<ButtonRelease-1>", self._clamp_sidebar,
                        add="+")
        self.panes.pack(side="left", fill="both", expand=True)
        self.show("overview")

    def _clamp_sidebar(self, _event=None) -> None:
        """Snap the sidebar sash back to its 210px floor after a drag."""
        try:
            if self.panes.sashpos(0) < 210:
                self.panes.sashpos(0, 210)
        except tk.TclError:
            pass

    def _build_menu(self) -> None:
        """Top-level File + Help menus: project files and guidance."""
        menubar = tk.Menu(self)
        self.show_guides = tk.BooleanVar(value=True)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Project",
                              command=self.new_project)
        file_menu.add_command(label="Open Project (.clk)…",
                              command=self.open_project_file)
        file_menu.add_command(label="Save",
                              command=self.save_project_file)
        file_menu.add_command(label="Save As (.clk)…",
                              command=self.save_project_file_as)
        menubar.add_cascade(label="File", menu=file_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Setup & Verification Guide…",
                              command=lambda: show_verification_guide(self))
        help_menu.add_command(
            label="Measurement Standards (CESMM/SMM/NRM)…",
            command=lambda: show_standards_guide(self))
        help_menu.add_command(label="About CIVOLINK QS…",
                              command=lambda: show_about_dialog(self))
        help_menu.add_separator()
        help_menu.add_command(label="License Status…",
                              command=lambda: show_license_status(self))
        help_menu.add_command(label="Activate License…",
                              command=lambda: show_license_activation(self))
        help_menu.add_separator()
        help_menu.add_checkbutton(label="Show Panel Instructions",
                                  variable=self.show_guides,
                                  command=self._toggle_guides)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)

    def _toggle_guides(self) -> None:
        """Enable/disable header guide buttons; close open popovers."""
        enabled = bool(self.show_guides.get())
        for guide in list(_guide_registry()):
            guide.set_enabled(enabled)

    def new_project(self) -> None:
        """Reset to a blank session (confirmed when work exists)."""
        from tkinter import messagebox
        if (self.session.lines() or self.session.project_saved
                or self.session.last_compiled is not None):
            if not messagebox.askyesno(
                    "New Project",
                    "Discard the current session and start blank?"):
                return
        self.session = TakeoffSession()
        self._project_path = None
        self.show(self._current or "overview")

    def open_project_file(self) -> None:
        """Load a `.clk` (or legacy `.civolink`) file into the session."""
        from tkinter import filedialog, messagebox
        from qs_engine.core.errors import ValidationError
        path = filedialog.askopenfilename(
            filetypes=[("CIVOLINK Project (*.clk; *.civolink)",
                        "*.clk *.civolink"),
                       ("All Files", "*.*")])
        if not path:
            return
        try:
            restore_session_from_file(self, path)
        except ValidationError as exc:
            messagebox.showerror("Open Project", str(exc))
            return
        self.show(self._current or "overview")

    def save_project_file(self) -> None:
        """Save to the current path, or fall back to Save As."""
        if self._project_path is None:
            self.save_project_file_as()
            return
        self._save_to_path(self._project_path)

    def save_project_file_as(self) -> None:
        """Save the session to a chosen `.clk` path."""
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".clk",
            filetypes=[("CIVOLINK Project (*.clk)", "*.clk")])
        if not path:
            return
        self._save_to_path(path)

    def _save_to_path(self, path) -> None:
        from tkinter import messagebox
        from qs_engine.core.errors import ValidationError
        try:
            persist_session_to_file(self, path)
        except ValidationError as exc:
            messagebox.showerror("Save Project", str(exc))
            return
        self.refresh_status()

    def _sync_admin_nav(self) -> None:
        """Show or hide the ADMINISTRATION group for the current tier."""
        visible = admin_nav_visible(self.security)
        for widget, options in self._admin_nav_widgets:
            if visible:
                widget.pack(**options)
            else:
                widget.pack_forget()
        self._admin_nav_visible = visible

    def toast(self, message: str) -> None:
        """Non-blocking notice: never modal, so it can never stall the UI.

        Used for route-guard refusals and owner actions that fail closed.
        """
        text = str(message or "").strip()
        if not text:
            return
        self._toast_text = text
        label = getattr(self, "_toast_label", None)
        if label is None:
            label = tk.Label(self, text=f"⚠ {text}", bg=WARN_AMBER,
                             fg="white", anchor="w", padx=10, pady=6)
            self._toast_label = label
            self.bind("<Configure>", self._reposition_toast, add="+")
        else:
            label.config(text=f"⚠ {text}")
        self._reposition_toast()
        try:
            self.after(6000, self._dismiss_toast)
        except Exception:
            pass

    def _reposition_toast(self, _event=None) -> None:
        """Pin the notice to the lower-right corner (integer geometry only)."""
        label = getattr(self, "_toast_label", None)
        if label is None:
            return
        label.update_idletasks()
        label.place(
            x=max(0, self.winfo_width() - label.winfo_reqwidth() - 16),
            y=max(0, self.winfo_height() - label.winfo_reqheight() - 16),
            anchor="se")

    def _dismiss_toast(self) -> None:
        """Remove the transient notice (no-op when already gone)."""
        label = getattr(self, "_toast_label", None)
        if label is not None:
            label.destroy()
            self._toast_label = None
        self._toast_text = ""

    def show(self, key: str) -> None:
        """Display a navigation page and refresh chrome state.

        Open help popovers and hover tooltips are dismissed first so
        overlay windows never survive a view switch.
        """
        if key not in PAGES:
            raise KeyError(f"Unknown navigation page {key!r}")
        # Route guarding: block unauthorized navigation to admin views.
        # The context is the session's own tier state (Tier 1/2), never a
        # detached one, so a guard can never be silently bypassed.
        try:
            ctx = _security_context(self)
            ctx.check_access(key)
        except ValidationError as exc:
            # Explicit, non-blocking refusal notice for the operator.
            self.toast(str(exc))
            self.refresh_status()
            return
        close_all_popovers()
        close_all_tooltips()
        for child in self.workspace.interior.winfo_children():
            child.destroy()
        PAGES[key](self.workspace.interior, self)
        self.workspace.refresh_wheel_bindings()
        self._current = key
        self.active_route_key = key
        self._sync_nav_highlight()
        self.refresh_status()

    def _sync_nav_highlight(self) -> None:
        """Render the active selection on exactly the current route.

        Single owner of sidebar highlight state: the active route key
        alone decides which button carries the selection styling, so a
        click can never update the panel without moving the highlight.
        """
        for name, button in self._nav_buttons.items():
            if name == self.active_route_key:
                button.configure(bg=CIVOLINK_BLUE, fg="white")
            else:
                button.configure(bg=CANVAS_BG, fg=SLATE_GREY)

    def refresh_status(self) -> str:
        """Recompute the segmented status bar; returns the legacy text.

        build_status_text stays the frozen serialization contract; the
        five segment labels render the same state as discrete cells.
        """
        text = build_status_text(self.session)
        for label, value in zip(self._segments,
                                status_segments(self.session)):
            label.config(text=value)
        sync_export_guards(self)
        return text


def launch(repository=None):
    """Start the desktop UI (requires a display; never called in tests)."""
    QSApp(repository).mainloop()


if __name__ == "__main__":
    launch()
