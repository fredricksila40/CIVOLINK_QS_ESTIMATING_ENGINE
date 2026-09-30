"""Frozen export-path tests: asset resolution in normal runs and
simulated frozen (`sys.frozen` + `_MEIPASS`) runs.

Covers output/profile/scripts/master-table path generation only —
no Qt widgets, no network, no real freezing. Frozen state is faked
with monkeypatched sys attributes (auto-reverted).
"""

from pathlib import Path

from qs_engine.adapters.document.company_profile import (
    load_company_profile,
    resolve_profile_path,
)
from qs_engine.adapters.document.word_export import (
    resolve_output_dir,
    resolve_scripts_dir,
)
from qs_engine.master_data.repository import (
    DEFAULT_TABLES_DIR,
    MasterDataRepository,
)


def _freeze(monkeypatch, tmp_path):
    """Simulate a PyInstaller one-file runtime rooted at tmp_path."""
    exe = tmp_path / "CIVOLINK-QS.exe"
    exe.write_bytes(b"")  # existence only; never executed
    (tmp_path / "_MEIPASS").mkdir(exist_ok=True)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path / "_MEIPASS"),
                        raising=False)
    monkeypatch.setattr("sys.executable", str(exe), raising=False)
    return exe


# --- normal (source-tree) mode ---------------------------------------------------

def test_output_dir_defaults_to_engine_output():
    resolved = resolve_output_dir()
    assert resolved.name == "output"
    assert resolved.is_absolute()


def test_profile_path_defaults_to_engine_config():
    resolved = resolve_profile_path()
    assert resolved.name == "company_profile.json"
    assert resolved.parent.name == "config"


def test_scripts_dir_defaults_to_engine_scripts():
    resolved = resolve_scripts_dir()
    assert resolved.name == "scripts"
    assert (resolved / "document_base.py").is_file()
    assert (resolved / "quotation_word.py").is_file()
    assert (resolved / "invoice_word.py").is_file()


def test_master_tables_dir_ships_ten_domains():
    assert DEFAULT_TABLES_DIR.is_dir()
    tables = sorted(DEFAULT_TABLES_DIR.glob("*.json"))
    assert len(tables) >= 10
    repo = MasterDataRepository()
    assert len(repo.list("materials")) == 23


def test_default_company_profile_loads():
    profile = load_company_profile()
    assert profile.get("business_name")


def test_explicit_paths_are_honoured_verbatim(tmp_path):
    custom = tmp_path / "custom.json"
    assert resolve_output_dir(custom) == custom
    assert resolve_profile_path(custom) == custom
    assert resolve_scripts_dir(custom) == custom


def test_profile_save_writes_through(tmp_path):
    from qs_engine.adapters.document.company_profile import (
        save_company_profile,
    )
    target = tmp_path / "profile.json"
    saved = save_company_profile({"business_name": "Smoke Co"},
                                 path=target)
    assert saved == str(target)
    assert target.is_file()


# --- simulated frozen mode ---------------------------------------------------------

def test_frozen_output_dir_beside_executable(tmp_path, monkeypatch):
    exe = _freeze(monkeypatch, tmp_path)
    assert resolve_output_dir() == exe.parent / "output"


def test_frozen_profile_path_beside_executable(tmp_path, monkeypatch):
    exe = _freeze(monkeypatch, tmp_path)
    assert resolve_profile_path() == (
        exe.parent / "config" / "company_profile.json")


def test_frozen_scripts_dir_inside_bundle(tmp_path, monkeypatch):
    _freeze(monkeypatch, tmp_path)
    assert resolve_scripts_dir() == tmp_path / "_MEIPASS" / "scripts"


def test_frozen_paths_never_point_at_install_tree(tmp_path, monkeypatch):
    _freeze(monkeypatch, tmp_path)
    engine_root = Path(__file__).parent.parent
    for resolved in (resolve_output_dir(), resolve_profile_path(),
                     resolve_scripts_dir()):
        assert resolved.is_absolute()
        assert engine_root not in resolved.parents


def test_frozen_profile_save_round_trip(tmp_path, monkeypatch):
    from qs_engine.adapters.document.company_profile import (
        save_company_profile,
    )
    exe = _freeze(monkeypatch, tmp_path)
    saved = save_company_profile({"business_name": "Frozen Co"})
    assert saved == str(exe.parent / "config" / "company_profile.json")
    assert load_company_profile()["business_name"] == "Frozen Co"
