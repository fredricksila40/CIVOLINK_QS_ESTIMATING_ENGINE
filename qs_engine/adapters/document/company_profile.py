"""Company profile store (Phase 15).

Standard JSON read/write handlers for the corporate identity edited on
the Corporate Document Integration page and stamped onto every branded
Word/PDF export. Pure stdlib: no docx, no tkinter, no engine contact.

Profile schema (all strings):
- business_name, registration_tax_id, contact_phone, email,
  physical_address, legal_disclaimers, logo_path, brand_accent_color.

Persistence: <engine-root>/config/company_profile.json. Missing file
or missing keys fall back to DEFAULT_COMPANY_PROFILE so exports never
crash on a fresh checkout.
"""

import json
import re
from pathlib import Path

from qs_engine.core.errors import ValidationError

COMPANY_PROFILE_FILENAME = "company_profile.json"

COMPANY_PROFILE_FIELDS = (
    "business_name",
    "registration_tax_id",
    "contact_phone",
    "email",
    "physical_address",
    "legal_disclaimers",
    "logo_path",
    "brand_accent_color",
)

DEFAULT_COMPANY_PROFILE = {
    "business_name": "CIVOLINK Construction Ltd",
    "registration_tax_id": "",
    "contact_phone": "",
    "email": "",
    "physical_address": "",
    "legal_disclaimers": (
        "QS Engine = Source of Truth | Document = Presentation "
        "Surface. Amounts derived from the compiled BOQ; unresolved "
        "items are shown explicitly and never priced as zero."
    ),
    "logo_path": "",
    "brand_accent_color": "#004F9D",
}

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_LOGO_EXTENSIONS = (".png", ".jpg", ".jpeg")


def _runtime_base() -> Path:
    """Writable base directory for profile storage.

    Source runs use the engine root (three levels above this file);
    PyInstaller frozen binaries use the executable's directory so
    profile saves persist outside the temporary _MEIPASS bundle.
    """
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent.parent


def resolve_profile_path(path=None) -> Path:
    """Absolute path of the company-profile JSON file.

    Default: <base>/config/company_profile.json where base is the
    engine root in source runs or the executable directory in frozen
    builds (this file lives in qs_engine/adapters/document/, so
    engine root is three levels up).
    An explicit path (str or Path) is honoured verbatim — tests use it
    to isolate fixtures from the real config.
    """
    if path is not None:
        return Path(path)
    return _runtime_base() / "config" / COMPANY_PROFILE_FILENAME


def validate_company_profile(profile: dict) -> dict:
    """Validate a profile mapping; returns a cleaned copy.

    Raises ValidationError naming the offending field. Unknown keys are
    dropped so forward-compatible files never break the editor.
    """
    if not isinstance(profile, dict):
        raise ValidationError(
            "Company profile must be a mapping; "
            f"got {type(profile).__name__}")
    cleaned = {}
    for field in COMPANY_PROFILE_FIELDS:
        value = profile.get(field, "")
        cleaned[field] = "" if value is None else str(value).strip()
    color = cleaned["brand_accent_color"] or DEFAULT_COMPANY_PROFILE[
        "brand_accent_color"]
    if not _HEX_COLOR.match(color):
        raise ValidationError(
            "brand_accent_color must be #RRGGBB hex; "
            f"got {cleaned['brand_accent_color']!r}")
    cleaned["brand_accent_color"] = color.upper()
    logo = cleaned["logo_path"]
    if logo and not logo.lower().endswith(_LOGO_EXTENSIONS):
        raise ValidationError(
            "logo_path must be a .png/.jpg image; "
            f"got {logo!r}")
    return cleaned


def load_company_profile(path=None) -> dict:
    """Load the company profile (defaults for missing file/keys).

    Never raises on a missing or corrupt file: returns defaults (or the
    decodable subset merged over defaults) so the editor and exporters
    always have something honest to render.
    """
    resolved = resolve_profile_path(path)
    merged = dict(DEFAULT_COMPANY_PROFILE)
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return merged
    if not isinstance(raw, dict):
        return merged
    for field in COMPANY_PROFILE_FIELDS:
        if field in raw and raw[field] is not None:
            merged[field] = str(raw[field]).strip()
    try:
        return validate_company_profile(merged)
    except ValidationError:
        # A hand-edited file with a bad colour/extension still loads;
        # the editor surfaces the error on save. Repair just the colour.
        if not _HEX_COLOR.match(merged.get("brand_accent_color", "")):
            merged["brand_accent_color"] = DEFAULT_COMPANY_PROFILE[
                "brand_accent_color"]
        return merged


def save_company_profile(profile: dict, path=None) -> str:
    """Validate and persist a profile; returns the file path as string."""
    cleaned = validate_company_profile(profile)
    resolved = resolve_profile_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(cleaned, indent=2) + "\n",
                        encoding="utf-8")
    return str(resolved)
