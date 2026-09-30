"""Release pipeline tests (Phase 23): signing, verification gates,
and orchestration â€” all offline with mocked tools and builders.

The modules under test are loaded by FILE PATH under alias names and
never via ``import scripts.*``: that keeps ``sys.modules["scripts"]``
pristine for the frozen-engine regression tests, which resolve an
external checkout through the real package name.
"""

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from unittest import mock

import pytest

ENGINE_ROOT = Path(__file__).parent.parent


def _load_alias(alias, filename):
    """Load a scripts/ module by path without importing the package."""
    assert "scripts" not in alias
    path = ENGINE_ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(alias, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sign_artifacts = _load_alias("civolink_sign_artifacts",
                             "sign_artifacts.py")
build_release = _load_alias("civolink_build_release", "build_release.py")

SigningConfig = sign_artifacts.SigningConfig
SigningError = sign_artifacts.SigningError
VerificationError = sign_artifacts.VerificationError
ToolNotFoundError = sign_artifacts.ToolNotFoundError

assert "scripts" not in sys.modules, \
    "release tooling must not claim the scripts package"


@pytest.fixture(autouse=True)
def _isolated_sign_module():
    """Route main()'s sign dependency at the alias copy.

    main() must never execute a real ``import scripts.*`` here: that
    would claim sys.modules["scripts"] and break the frozen-engine
    regression tests resolving an external checkout.
    """
    with mock.patch.object(build_release, "_sign_module",
                           return_value=sign_artifacts):
        yield


def _config(**kwargs):
    params = {"cert_path": "C:\\certs\\civolink.pfx",
              "cert_pass": "s3cret", "thumbprint": ""}
    params.update(kwargs)
    return SigningConfig(**params)


def _completed(returncode=0, stdout="", stderr=""):
    completed = mock.Mock()
    completed.returncode = returncode
    completed.stdout = stdout
    completed.stderr = stderr
    return completed


# --- tool resolution -----------------------------------------------------------

def test_find_signtool_prefers_path():
    with mock.patch.object(sign_artifacts, "shutil") as shutil:
        shutil.which.return_value = "C:\\tools\\signtool.exe"
        assert sign_artifacts.find_signtool() == (
            "C:\\tools\\signtool.exe")


def test_find_signtool_scans_sdk_dirs():
    with mock.patch.object(sign_artifacts, "shutil") as shutil, \
            mock.patch.object(sign_artifacts, "glob") as glob, \
            mock.patch("os.path.isfile", return_value=True):
        shutil.which.return_value = None
        glob.glob.return_value = [
            "C:\\kits\\10\\bin\\10.0.22621.0\\x64\\signtool.exe"]
        found = sign_artifacts.find_signtool()
        assert found is not None and found.endswith("signtool.exe")


def test_find_tools_missing_returns_none():
    with mock.patch.object(sign_artifacts, "shutil") as shutil, \
            mock.patch.object(sign_artifacts, "glob") as glob, \
            mock.patch("os.path.isfile", return_value=False):
        shutil.which.return_value = None
        glob.glob.return_value = []
        assert sign_artifacts.find_signtool() is None
        assert sign_artifacts.find_iscc() is None


def test_find_iscc_standard_path():
    with mock.patch.object(sign_artifacts, "shutil") as shutil, \
            mock.patch("os.path.isfile") as isfile:
        shutil.which.return_value = None
        isfile.side_effect = lambda path: path.endswith("ISCC.exe")
        found = sign_artifacts.find_iscc()
        assert found is not None and found.endswith("ISCC.exe")


# --- credentials ------------------------------------------------------------------

def test_config_from_env_mapping():
    config = SigningConfig.from_env({
        "CIVOLINK_SIGN_CERT_PATH": "C:\\c.pfx",
        "CIVOLINK_SIGN_CERT_PASS": "pw",
        "CIVOLINK_SIGN_THUMBPRINT": "AB12",
        "CIVOLINK_TIMESTAMP_URL": "http://ts.example.com",
        "CIVOLINK_ALLOW_UNSIGNED": "yes",
    })
    assert config.cert_path == "C:\\c.pfx"
    assert config.cert_pass == "pw"
    assert config.thumbprint == "AB12"
    assert config.timestamp_url == "http://ts.example.com"
    assert config.allow_unsigned is True
    assert config.credentials_ok() is True


def test_allow_unsigned_flag_parsing():
    for raw in ("1", "true", "yes", "True", "YES"):
        assert SigningConfig.from_env(
            {"CIVOLINK_ALLOW_UNSIGNED": raw}).allow_unsigned is True
    for raw in ("", "0", "no", "false"):
        assert SigningConfig.from_env(
            {"CIVOLINK_ALLOW_UNSIGNED": raw}).allow_unsigned is False


def test_config_repr_and_empty_config():
    assert "s3cret" not in repr(_config())
    assert "cert_path=" in repr(_config())
    assert "certs" in repr(_config())
    config = SigningConfig()
    assert config.credentials_ok() is False
    assert config.timestamp_url == sign_artifacts.DEFAULT_TIMESTAMP_URL


def test_redact_command_masks_password_only():
    cmd = ["signtool", "sign", "/f", "c.pfx", "/p", "s3cret",
           "app.exe"]
    redacted = sign_artifacts.redact_command(cmd)
    assert redacted == ["signtool", "sign", "/f", "c.pfx", "/p",
                        "***", "app.exe"]
    assert cmd[5] == "s3cret"  # original untouched
    plain = ["signtool", "verify", "/pa", "app.exe"]
    assert sign_artifacts.redact_command(plain) == plain


# --- signing / verification ----------------------------------------------------------

def test_sign_file_command_and_success():
    with mock.patch.object(sign_artifacts, "_run") as run, \
            mock.patch("os.path.isfile", return_value=True):
        run.return_value = _completed(0, "Signed OK")
        out = sign_artifacts.sign_file(
            "signtool.exe", "app.exe", _config())
        assert out == "Signed OK"
        cmd = run.call_args[0][0]
        assert cmd[:6] == ["signtool.exe", "sign", "/fd", "sha256",
                           "/tr", "http://timestamp.digicert.com"]
        assert cmd[6:8] == ["/td", "sha256"]
        assert "/f" in cmd and "/p" in cmd


def test_sign_file_thumbprint_path_has_no_password_flag():
    config = _config(cert_path="", cert_pass="", thumbprint="AB12")
    with mock.patch.object(sign_artifacts, "_run") as run, \
            mock.patch("os.path.isfile", return_value=True):
        run.return_value = _completed(0, "ok")
        sign_artifacts.sign_file("signtool.exe", "app.exe", config)
        cmd = run.call_args[0][0]
        assert "/sha1" in cmd and "/p" not in cmd and "/f" not in cmd


def test_sign_file_failures_raise():
    with mock.patch("os.path.isfile", return_value=False):
        try:
            sign_artifacts.sign_file("s", "missing.exe", _config())
        except SigningError:
            pass
        else:
            raise AssertionError("missing target must raise")
    with mock.patch("os.path.isfile", return_value=True):
        with mock.patch.object(sign_artifacts, "_run") as run:
            run.return_value = _completed(1, "", "bad digest")
            try:
                sign_artifacts.sign_file("s", "app.exe", _config())
            except SigningError as exc:
                assert "bad digest" in str(exc)
            else:
                raise AssertionError("non-zero exit must raise")
        try:
            sign_artifacts.sign_file("s", "app.exe", SigningConfig())
        except SigningError as exc:
            assert "CIVOLINK_SIGN_CERT_PATH" in str(exc)
        else:
            raise AssertionError("missing credentials must raise")


def test_verify_file_parses_success_marker():
    good = "SignTool ...\nSuccessfully verified: app.exe\n..."
    with mock.patch.object(sign_artifacts, "_run") as run, \
            mock.patch("os.path.isfile", return_value=True):
        run.return_value = _completed(0, good)
        assert "Successfully verified" in sign_artifacts.verify_file(
            "s", "app.exe")
        args = run.call_args[0][0]
        assert args[1:4] == ["verify", "/pa", "/v"]
        run.return_value = _completed(0, "no marker here")
        try:
            sign_artifacts.verify_file("s", "app.exe")
        except VerificationError:
            pass
        else:
            raise AssertionError("missing marker must raise")
        run.return_value = _completed(3, "chain error")
        try:
            sign_artifacts.verify_file("s", "app.exe")
        except VerificationError as exc:
            assert "chain error" in str(exc)
        else:
            raise AssertionError("non-zero exit must raise")


# --- orchestrator ----------------------------------------------------------------------

def test_pyinstaller_args_mirror_spec():
    args = build_release.pyinstaller_args()
    assert "--onedir" in args and "--windowed" in args
    assert "--manifest" in args and "civolink.manifest" in args
    assert "CIVOLINK-QS" in args
    assert "--hidden-import" in args
    for required in ("fastapi", "uvicorn", "reportlab", "docx",
                     "lxml", "sqlite3"):
        assert required in args
    assert any("company_profile.json" in arg for arg in args)
    assert any("master_data" in arg for arg in args)
    assert any("scripts" in arg for arg in args)
    assert args[-1].endswith("__main__.py")


def test_artifact_paths():
    assert build_release.inner_exe_path().endswith(
        "CIVOLINK-QS.exe")
    assert "dist" in build_release.inner_exe_path()
    assert build_release.installer_path("1.4.2").endswith(
        "CIVOLINK-QS-Setup-1.4.2.exe")
    assert "release" in build_release.installer_path("9.9.9")


def test_main_dev_path_skips_signing_in_order():
    order = []
    with mock.patch.object(build_release, "_run_pyinstaller") as build, \
            mock.patch("os.path.isfile", return_value=True), \
            mock.patch.object(sign_artifacts, "sign_file") as sign, \
            mock.patch.object(build_release, "compile_installer",
                              return_value="release\\setup.exe"):
        build.side_effect = lambda args: order.append("build")
        result = build_release.main(["--allow-unsigned"])
    assert result == 0
    assert order == ["build"]
    sign.assert_not_called()


def test_main_fails_closed_on_build_error():
    with mock.patch.object(build_release, "_run_pyinstaller") as build:
        build.side_effect = build_release.BuildError("boom")
        assert build_release.main(["--allow-unsigned"]) == 1


def test_main_fails_closed_on_signing_error():
    with mock.patch.object(build_release, "_run_pyinstaller"), \
            mock.patch("os.path.isfile", return_value=True), \
            mock.patch.object(sign_artifacts, "find_signtool",
                              return_value="signtool.exe"), \
            mock.patch.object(sign_artifacts, "sign_file") as sign, \
            mock.patch.object(build_release, "compile_installer",
                              return_value="x"), \
            mock.patch.dict("os.environ",
                            {"CIVOLINK_SIGN_CERT_PATH": "C:\\c.pfx"}):
        sign.side_effect = SigningError("bad cert")
        assert build_release.main([]) == 1


def test_main_requires_credentials_without_allow_flag():
    with mock.patch.object(build_release, "_run_pyinstaller") as build, \
            mock.patch.dict("os.environ", {}, clear=True):
        assert build_release.main([]) == 1
        build.assert_not_called()


def test_main_dev_without_iscc_warns_and_succeeds():
    with mock.patch.object(build_release, "_run_pyinstaller"), \
            mock.patch("os.path.isfile", return_value=True), \
            mock.patch.object(build_release, "compile_installer") as comp:
        comp.side_effect = ToolNotFoundError("no iscc")
        assert build_release.main(["--allow-unsigned"]) == 0


# --- deliverable files --------------------------------------------------------------------

def test_iss_and_gitignore_present_and_correct():
    iss = (ENGINE_ROOT / "civolink_setup.iss").read_text(encoding="utf-8")
    assert "OutputBaseFilename=CIVOLINK-QS-Setup-{#MyAppVersion}" in iss
    assert "dist\\CIVOLINK-QS" in iss
    assert "PrivilegesRequired" in iss
    gitignore = (ENGINE_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("*.pfx", "*.p12", "*.crt", "*.key", "release/"):
        assert pattern in gitignore


# --- assemblies demoted to test fixtures (Phase 2 Task 2.2) --------------------

def test_assemblies_live_only_as_test_fixtures():
    """No runtime loader consumes the templates; they are test fixtures
    under tests/fixtures/ and never ship in a bundle or manifest."""
    assert not (ENGINE_ROOT / "assemblies").exists()
    fixtures = ENGINE_ROOT / "tests" / "fixtures" / "assemblies"
    assert len(list(fixtures.glob("*.json"))) >= 4
    for spec_name in ("civolink.spec", "CIVOLINK-QS.spec"):
        text = (ENGINE_ROOT / spec_name).read_text(encoding="utf-8")
        assert "assemblies/*.json" not in text, spec_name
        assert 'os.path.join(SPECPATH, "assemblies"' not in text, spec_name
    for source, _dest in build_release.BUNDLED_DATA:
        assert "assemblies" not in str(source), source


# --- release manifest: canonical version + fresh hashes (Phase 2 Task 2.3) -----

def test_release_manifest_version_is_qs_engine_canonical():
    import tempfile

    import qs_engine
    assert build_release.app_version() == qs_engine.__version__
    with tempfile.TemporaryDirectory() as empty:
        manifest = build_release.release_manifest(engine_root=empty)
    assert manifest["version"] == qs_engine.__version__


def test_sha256_file_missing_returns_none(tmp_path):
    assert build_release.sha256_file(tmp_path / "absent.exe") is None


def test_write_release_manifest_records_hashes_and_schema(tmp_path):
    import qs_engine
    version = qs_engine.__version__
    (tmp_path / "dist" / "CIVOLINK-QS").mkdir(parents=True)
    exe = tmp_path / "dist" / "CIVOLINK-QS" / "CIVOLINK-QS.exe"
    exe.write_bytes(b"exe-bytes")
    archive = tmp_path / "dist" / f"CIVOLINK-QS-v{version}.zip"
    archive.write_bytes(b"zip-bytes")

    path = build_release.write_release_manifest(engine_root=tmp_path)
    assert Path(path) == tmp_path / "dist" / "RELEASE_MANIFEST.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == version
    assert data["exe_sha256"] == hashlib.sha256(b"exe-bytes").hexdigest()
    assert data["zip_sha256"] == hashlib.sha256(b"zip-bytes").hexdigest()
    assert data["installer_sha256"] is None  # absent artefact: honest null
    assert "bundled_assemblies" not in data
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                    data["build_timestamp"])
    assert not list(tmp_path.glob("**/*.tmp"))


def test_write_release_manifest_required_fails_closed_without_exe(
        tmp_path):
    with pytest.raises(build_release.BuildError) as exc_info:
        build_release.write_release_manifest(engine_root=tmp_path,
                                             required=True)
    assert "SHA-256" in str(exc_info.value)
    assert not (tmp_path / "dist" / "RELEASE_MANIFEST.json").exists()
    # Development mode tolerates a partial tree with null hashes.
    data = json.loads(build_release.write_release_manifest(
        engine_root=tmp_path).read_text(encoding="utf-8"))
    assert data["exe_sha256"] is None


def test_release_manifest_carries_forward_test_baseline(tmp_path):
    import qs_engine
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "RELEASE_MANIFEST.json").write_text(
        json.dumps({"version": "0.0.1",
                    "test_baseline": "817 passed, 0 failed"}),
        encoding="utf-8")
    carried = build_release.release_manifest(engine_root=tmp_path)
    assert carried["test_baseline"] == "817 passed, 0 failed"
    # The canonical package version always wins over a stale manifest.
    assert carried["version"] == qs_engine.__version__
    explicit = build_release.release_manifest(
        engine_root=tmp_path, test_baseline="900 passed, 0 failed")
    assert explicit["test_baseline"] == "900 passed, 0 failed"


def test_shipped_release_manifest_matches_canonical_version():
    import qs_engine
    path = Path(build_release.manifest_path())
    if not path.is_file():
        pytest.skip("no release tree in this checkout")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == qs_engine.__version__
    assert "bundled_assemblies" not in data
    assert isinstance(data.get("exe_sha256"), str)
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                    data["build_timestamp"])
