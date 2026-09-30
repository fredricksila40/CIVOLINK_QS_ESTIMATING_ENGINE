"""Master-data schema + repository tests (structure only — no values)."""

import json

import pytest

from qs_engine.core.assumptions import VerificationStatus
from qs_engine.core.errors import (
    MissingFieldError,
    UnknownMasterDataDomainError,
    UnknownMasterDataKeyError,
    ValidationError,
)
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.master_data.schemas import DOMAINS, REQUIRED_FIELDS, validate_record


def valid_material(key="cement_42_5"):
    return {
        "key": key,
        "name": "Portland Cement",
        "category": "binder",
        "unit": "kg",
        "density": "1440",
        "density_unit": "kg/m3",
        "default_wastage_pct": "5",
        "source": "TEST FIXTURE ONLY - not a verified project value",
        "version": "t0",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.PROVISIONAL,
    }


def write_table(tmp_path, domain, records, table_version="t0"):
    path = tmp_path / f"{domain}.json"
    path.write_text(json.dumps({
        "domain": domain,
        "schema_version": "0.1",
        "table_version": table_version,
        "records": records,
    }), encoding="utf-8")
    return tmp_path


def test_all_domains_have_required_fields():
    # Phase 9 adds the rate_templates domain; Phase 6 adds mix_designs: eleven in total.
    assert set(DOMAINS) == {
        "materials", "concrete_classes", "masonry_units", "rebar_bars",
        "coverages", "labour", "plant", "trucks", "soils",
        "rate_templates", "mix_designs",
    }
    for domain in DOMAINS:
        assert REQUIRED_FIELDS[domain], domain


def test_validate_record_accepts_complete_record():
    assert validate_record("materials", valid_material())["key"] == "cement_42_5"


def test_validate_record_rejects_unknown_domain():
    with pytest.raises(UnknownMasterDataDomainError):
        validate_record("unobtainium", {"key": "x"})


def test_validate_record_rejects_missing_field():
    record = valid_material()
    del record["density"]
    with pytest.raises(MissingFieldError):
        validate_record("materials", record)


def test_validate_record_rejects_bad_status():
    record = valid_material()
    record["verification_status"] = "TRUST_ME"
    with pytest.raises(ValidationError):
        validate_record("materials", record)


def test_repository_get_and_list(tmp_path):
    repo = MasterDataRepository(write_table(tmp_path, "materials",
                                            [valid_material()]))
    record = repo.get("materials", "cement_42_5")
    assert record["density"] == "1440"
    assert len(repo.list("materials")) == 1
    assert repo.table_version("materials") == "t0"


def test_repository_missing_key_raises(tmp_path):
    repo = MasterDataRepository(write_table(tmp_path, "materials",
                                            [valid_material()]))
    with pytest.raises(UnknownMasterDataKeyError):
        repo.get("materials", "nope")


def test_repository_unknown_domain_raises(tmp_path):
    repo = MasterDataRepository(write_table(tmp_path, "materials", []))
    with pytest.raises(UnknownMasterDataDomainError):
        repo.get("nope", "x")
    with pytest.raises(UnknownMasterDataDomainError):
        repo.list("nope")


def test_repository_missing_file_is_empty_table(tmp_path):
    repo = MasterDataRepository(tmp_path)
    assert repo.list("materials") == []
    with pytest.raises(UnknownMasterDataKeyError):
        repo.get("materials", "anything")


def test_repository_rejects_wrong_schema_version(tmp_path):
    path = tmp_path / "materials.json"
    path.write_text(json.dumps({"schema_version": "9.9", "records": []}))
    with pytest.raises(ValueError):
        MasterDataRepository(tmp_path)


def test_repository_rejects_invalid_json(tmp_path):
    (tmp_path / "materials.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        MasterDataRepository(tmp_path)


def test_shipped_tables_load_empty():
    # Phase 1: materials is populated (identifiers only); Phase 2 adds
    # concrete skeleton keys. All other shipped tables remain empty.
    repo = MasterDataRepository()  # qs_engine/master_data/tables/
    assert len(repo.list("materials")) == 23
    assert len(repo.list("concrete_classes")) == 4
    assert len(repo.list("masonry_units")) == 3
    assert len(repo.list("rebar_bars")) == 7
    assert len(repo.list("coverages")) == 5
    assert len(repo.list("soils")) == 4
    assert len(repo.list("labour")) == 6
    assert len(repo.list("plant")) == 5
    assert len(repo.list("trucks")) == 3
    assert len(repo.list("rate_templates")) == 2
    for domain in DOMAINS:
        assert repo.list(domain) != [], domain
