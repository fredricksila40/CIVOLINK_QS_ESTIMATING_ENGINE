"""Phase 21 distribution tests: launcher flags + spec validation.

Verifies mode parsing/dispatch contracts, daemonized background API
thread construction (never binding a port), and the PyInstaller spec
(hidden imports, entry script, bundled asset paths, windowed EXE
metadata) — all statically, without compiling any binary.
"""

import ast
import glob
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from qs_engine.main import (
    DEFAULT_API_HOST,
    DEFAULT_API_PORT,
    make_api_thread,
    parse_args,
    resolve_mode,
    run_cli,
)

ENGINE_ROOT = Path(__file__).parent.parent
SPEC_PATH = ENGINE_ROOT / "civolink.spec"

REQUIRED_HIDDEN = {"fastapi", "uvicorn", "pydantic", "reportlab",
                   "sqlite3"}


# --- launcher flags ------------------------------------------------------------------

def test_parse_defaults_to_desktop_gui():
    args = parse_args([])
    assert args.cli is False and args.server is False
    assert args.with_api is False
    assert (args.api_host, args.api_port) == (DEFAULT_API_HOST,
                                              DEFAULT_API_PORT)
    assert resolve_mode(args) == "gui"


def test_parse_cli_and_server_modes():
    assert resolve_mode(parse_args(["--cli"])) == "cli"
    assert resolve_mode(parse_args(["--server"])) == "server"
    server = parse_args(["--server", "--api-host", "0.0.0.0",
                         "--api-port", "9000"])
    assert (server.api_host, server.api_port) == ("0.0.0.0", 9000)
    assert resolve_mode(parse_args(["--with-api"])) == "gui"
    assert parse_args(["--with-api"]).with_api is True


def test_cli_and_server_flags_conflict():
    with pytest.raises(SystemExit):
        parse_args(["--cli", "--server"])


def test_run_cli_returns_dashboard_zero(capsys):
    assert run_cli() == 0
    assert "CIVOLINK QS Estimating Engine" in capsys.readouterr().out


def test_make_api_thread_daemonized_unstarted():
    thread = make_api_thread("127.0.0.1", 8765)
    assert isinstance(thread, threading.Thread)
    assert thread.daemon is True
    assert thread.is_alive() is False
    assert thread.name == "civolink-api"


def test_package_entry_invokes_launcher():
    proc = subprocess.run(
        [sys.executable, "-m", "qs_engine", "--help"],
        cwd=str(ENGINE_ROOT), capture_output=True, text=True,
        timeout=60)
    assert proc.returncode == 0
    assert "--cli" in proc.stdout and "--server" in proc.stdout


# --- PyInstaller spec (static validation only) ------------------------------------------

def _spec_tree():
    return ast.parse(SPEC_PATH.read_text(encoding="utf-8"),
                     filename=str(SPEC_PATH))


def _spec_assignments():
    """Top-level NAME -> AST value for plain assignments in the spec."""
    found = {}
    for node in _spec_tree().body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            found[node.targets[0].id] = node.value
    return found


def _spec_call_kwargs(func_name):
    """Keyword args of the first Call to func_name in the spec."""
    for node in ast.walk(_spec_tree()):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == func_name:
            return {kw.arg: kw.value for kw in node.keywords}
    raise AssertionError(f"{func_name}(...) not found in civolink.spec")


def _eval_spec_string(node, root):
    """Evaluate a spec path expression with SPECPATH -> engine root."""
    return eval(compile(ast.Expression(node), str(SPEC_PATH), "eval"),
                {"os": os, "SPECPATH": str(root), "SEP": os.sep},
                {})


def test_spec_hidden_imports_cover_web_and_pdf_stack():
    assignments = _spec_assignments()
    listed = set(ast.literal_eval(assignments["HIDDEN_IMPORTS"]))
    assert REQUIRED_HIDDEN <= listed


def test_spec_entry_script_exists():
    scripts = None
    for node in ast.walk(_spec_tree()):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "Analysis" and node.args:
            scripts = node.args[0]
    assert isinstance(scripts, ast.List) and len(scripts.elts) == 1
    entry = _eval_spec_string(scripts.elts[0], ENGINE_ROOT)
    assert Path(entry).is_file()
    assert Path(entry).name == "__main__.py"


def test_spec_bundled_asset_paths_exist():
    assignments = _spec_assignments()
    datas = assignments["BUNDLED_DATA"]
    assert isinstance(datas, ast.List) and len(datas.elts) >= 2
    for entry in datas.elts:
        src = _eval_spec_string(entry.elts[0], ENGINE_ROOT)
        assert glob.glob(src), f"bundled asset missing: {src}"


def test_spec_bundled_assets_evaluated_from_engine_root():
    assignments = _spec_assignments()
    dumped = ast.dump(assignments["BUNDLED_DATA"])
    assert "SPECPATH" in dumped
    assert "'join'" in dumped  # os.path.join-composed portable paths


def test_spec_exe_metadata_windowed_named():
    kwargs = _spec_call_kwargs("EXE")
    assert ast.literal_eval(kwargs["name"]) == "CIVOLINK-QS"
    assert ast.literal_eval(kwargs["console"]) is False
