"""Assembly template honesty tests: the masonry wall template must
stay a clearly-marked unverified skeleton — structured and
cross-referenced, never presenting invented constants, rules, or
citations as verified truth.

The templates live under ``tests/fixtures/assemblies`` (relocated in
the Phase 2 release cleanup): they are TEST FIXTURES only — no runtime
loader consumes them, and they are deliberately absent from the release
manifest and PyInstaller bundles so dead artefacts never ship.
"""

import json
from pathlib import Path

TEMPLATE = (Path(__file__).parent / "fixtures" / "assemblies"
            / "masonry_wall.json")


def _template():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def test_template_structure():
    template = _template()
    assert template["template_id"] == "masonry-wall-assembly"
    assert template["version"] == "1.0.0"
    for section in ("measurement_basis", "parameters",
                    "internal_variables", "outputs", "verification"):
        assert section in template, section
    assert len(template["outputs"]) == 4


def test_template_status_needs_verification():
    template = _template()
    assert template["verification"]["status"] == "NEEDS_VERIFICATION"
    assert len(template["verification"]["gaps"]) >= 1


def test_template_quantities_never_baked_in():
    for output in _template()["outputs"]:
        assert output["quantity"] is None, output["resource_key"]


def test_template_references_real_master_keys_only():
    from qs_engine.master_data.repository import MasterDataRepository
    repo = MasterDataRepository()
    assert repo.get("materials", "concrete_block_200mm")
    assert repo.get("materials", "river_sand")
    for output in _template()["outputs"]:
        if output["kind"] == "material":
            repo.get("materials", output["resource_key"])
    assert repo.get("labour", "mason")


def test_template_gl_values_match_supplied_table_only():
    from qs_engine.master_data.repository import MasterDataRepository
    repo = MasterDataRepository()
    for output in _template()["outputs"]:
        if output["kind"] != "material":
            continue
        record = repo.get("materials", output["resource_key"])
        expected = record.get("gl_code")
        if expected is None:
            assert output["gl_account"] is None
        else:
            assert output["gl_account"] == (
                f"{record['gl_code']} - {record['gl_account_name']}")
            assert output["gl_account_type"] == (
                record["gl_account_type"])


def test_template_claims_no_verified_rules_or_constants():
    text = TEMPLATE.read_text(encoding="utf-8").lower()
    assert "unverified" in text
    for claim in ("smm7:", "nrm2:", "cesmm4:", "verified standard",
                  "500xx"):
        if claim == "500xx":
            # 500xx may appear solely to disclaim it as a placeholder.
            assert text.count(claim) <= 1
            continue
        assert claim not in text, claim


def _all_templates():
    return sorted(
        (Path(__file__).parent / "fixtures" / "assemblies").glob("*.json"))


def test_library_templates_share_required_structure():
    assert len(_all_templates()) >= 4
    for path in _all_templates():
        template = json.loads(path.read_text(encoding="utf-8"))
        assert template["version"] == "1.0.0", path.name
        for section in ("template_id", "measurement_basis", "parameters",
                        "internal_variables", "outputs", "verification"):
            assert section in template, (path.name, section)
        assert template["verification"]["status"] == (
            "NEEDS_VERIFICATION"), path.name
        assert len(template["verification"]["gaps"]) >= 1, path.name
        assert len(template["outputs"]) >= 1, path.name
        for output in template["outputs"]:
            assert output["quantity"] is None, (
                path.name, output.get("resource_key"))


def test_library_resource_keys_resolve_or_defer_honestly():
    from qs_engine.master_data.repository import MasterDataRepository
    repo = MasterDataRepository()
    for path in _all_templates():
        for output in json.loads(
                path.read_text(encoding="utf-8"))["outputs"]:
            key = output.get("resource_key")
            if key is None:
                note = str(output.get("note", ""))
                assert note.strip(), (path.name, output)
                continue
            domain = ("labour" if output.get("kind") == "labour"
                      else "materials")
            repo.get(domain, key)


def test_library_gl_values_match_supplied_table_only():
    from qs_engine.master_data.repository import MasterDataRepository
    repo = MasterDataRepository()
    for path in _all_templates():
        for output in json.loads(
                path.read_text(encoding="utf-8"))["outputs"]:
            if output.get("kind") != "material":
                continue
            key = output.get("resource_key")
            if key is None:
                assert output.get("gl_account") is None, path.name
                continue
            record = repo.get("materials", key)
            if record.get("gl_code") is None:
                assert output.get("gl_account") is None, (
                    path.name, key)
            else:
                assert output.get("gl_account") == (
                    f"{record['gl_code']} - {record['gl_account_name']}"), (
                    path.name, key)
                assert output.get("gl_account_type") == (
                    record["gl_account_type"]), (path.name, key)


def test_library_claims_no_verified_rules():
    for path in _all_templates():
        text = path.read_text(encoding="utf-8").lower()
        assert "unverified" in text, path.name
        for claim in ("smm7:", "nrm2:", "cesmm4:", "verified standard"):
            assert claim not in text, (path.name, claim)
