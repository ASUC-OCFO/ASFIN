"""
Tests for ValidationService (Week 4):

- Tests create temporary raw CSV files, insert matching Dataset and Ingestion rows into the test database,
  and then call ValidationService.run().
- The service loads the raw file, runs SchemaValidator and ShapeValidator, writes validation_results rows,
  and updates the ingestion status.

Run 'pytest app/tests/test_validation_service.py' in terminal from repo root after installing requirements
- 'pip install requirements.txt' and 'pip install requirements.api.txt'
"""

import pytest
import pandas as pd

from app.core.models import Dataset, Ingestion, ValidationResult
from app.services.validation_service import ValidationService


def _make_dataset(db, *, schema_def=None, validation_cfg=None):
    dataset = Dataset(
        name=f"test_dataset_{id(schema_def)}",
        process_type="FR",
        description="Test dataset",
        schema_def=schema_def or [
            {"name": "name", "dtype": "str", "required": True},
            {"name": "amount", "dtype": "int", "required": True},
        ],
        validation_cfg=validation_cfg or {"min_rows": 1, "max_null_fraction": 0.5},
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


def _make_ingestion(db, dataset_id, raw_path, *, file_ext=".csv"):
    ingestion = Ingestion(
        dataset_id=dataset_id,
        status="pending",
        original_filename=raw_path.name,
        file_ext=file_ext,
        raw_path=str(raw_path),
        file_size_bytes=raw_path.stat().st_size,
        file_sha256="test-hash",
    )
    db.add(ingestion)
    db.commit()
    db.refresh(ingestion)
    return ingestion


def test_validation_passes_valid_file(db, tmp_path):
    raw_file = tmp_path / "valid.csv"
    pd.DataFrame({"name": ["A", "B", "C"], "amount": [10, 20, 30]}).to_csv(raw_file, index=False)

    dataset = _make_dataset(db)
    ingestion = _make_ingestion(db, dataset.id, raw_file)

    results = ValidationService(db).run(ingestion.id)

    db.refresh(ingestion)
    assert ingestion.status == "validated"
    assert len(results) == 4  # schema, shape, drift, join

    saved = db.query(ValidationResult).filter(ValidationResult.ingestion_id == ingestion.id).all()
    assert {r.check_name for r in saved} == {"schema", "shape", "drift", "join"}
    # schema and shape pass; drift and join skip (first upload, no join_key configured)
    by_name = {r.check_name: r for r in saved}
    assert by_name["schema"].status == "pass"
    assert by_name["shape"].status == "pass"
    assert by_name["drift"].status == "skipped"
    assert by_name["join"].status == "skipped"


def test_validation_fails_bad_shape(db, tmp_path):
    raw_file = tmp_path / "bad_shape.csv"
    pd.DataFrame({"name": ["A"], "amount": [10]}).to_csv(raw_file, index=False)

    dataset = _make_dataset(db, validation_cfg={"min_rows": 5, "max_null_fraction": 0.5})
    ingestion = _make_ingestion(db, dataset.id, raw_file)

    results = ValidationService(db).run(ingestion.id)

    db.refresh(ingestion)
    assert ingestion.status == "validation_failed"
    assert any(r.check_name == "shape" and r.status == "fail" for r in results)


def test_validation_fails_missing_column(db, tmp_path):
    raw_file = tmp_path / "bad_schema.csv"
    pd.DataFrame({"name": ["A", "B"]}).to_csv(raw_file, index=False)  # missing "amount"

    dataset = _make_dataset(db)
    ingestion = _make_ingestion(db, dataset.id, raw_file)

    results = ValidationService(db).run(ingestion.id)

    db.refresh(ingestion)
    assert ingestion.status == "validation_failed"
    schema_result = next(r for r in results if r.check_name == "schema")
    assert schema_result.status == "fail"
    assert "amount" in schema_result.details.get("missing_columns", [])


def test_validation_fails_wrong_dtype(db, tmp_path):
    raw_file = tmp_path / "bad_dtype.csv"
    pd.DataFrame({"name": ["A", "B"], "amount": ["x", "y"]}).to_csv(raw_file, index=False)

    dataset = _make_dataset(db)
    ingestion = _make_ingestion(db, dataset.id, raw_file)

    results = ValidationService(db).run(ingestion.id)

    db.refresh(ingestion)
    assert ingestion.status == "validation_failed"
    schema_result = next(r for r in results if r.check_name == "schema")
    assert schema_result.status == "fail"
    assert any(e["column"] == "amount" for e in schema_result.details.get("type_errors", []))


def test_validation_fails_missing_raw_file(db, tmp_path):
    raw_file = tmp_path / "ghost.csv"
    raw_file.write_text("name,amount\nA,1\n")  # write so stat() works, then remove it
    dataset = _make_dataset(db)
    ingestion = _make_ingestion(db, dataset.id, raw_file)
    raw_file.unlink()

    with pytest.raises(FileNotFoundError):
        ValidationService(db).run(ingestion.id)

    db.refresh(ingestion)
    assert ingestion.status == "validation_failed"
    assert ingestion.error_message is not None


def test_validation_raises_for_missing_ingestion(db):
    with pytest.raises(LookupError, match="not found"):
        ValidationService(db).run(ingestion_id=999999)


# ---------------------------------------------------------------------------
# Integration tests — HTTP layer
# ---------------------------------------------------------------------------


def test_upload_submits_validation_job(client, db, tmp_path, monkeypatch):
    """POST /ingestions calls job_submit with the new ingestion's id."""
    import app.services.storage as storage_module
    import app.api.routers.ingestions as ingestions_router

    monkeypatch.setattr(storage_module, "DATA_ROOT", tmp_path)

    submitted_ids = []
    monkeypatch.setattr(
        ingestions_router, "job_submit",
        lambda fn, *args, **kwargs: submitted_ids.append(args[0]),
    )

    dataset = Dataset(name="job_trigger_ds", process_type="FR")
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("name,amount\nA,1\n")

    with csv_file.open("rb") as f:
        resp = client.post(
            f"/api/v1/datasets/{dataset.id}/ingestions",
            files={"file": ("data.csv", f, "text/csv")},
        )

    assert resp.status_code == 201
    assert submitted_ids == [resp.json()["id"]]


def test_validation_routes_return_results(client, db, tmp_path):
    """GET /validation and /validation/{check} return per-check results seeded via the service."""
    raw_file = tmp_path / "bad.csv"
    raw_file.write_text("name\nA\nB\n")  # missing "amount" column

    dataset = _make_dataset(db)
    ingestion = _make_ingestion(db, dataset.id, raw_file)

    ValidationService(db).run(ingestion.id)

    # List all results.
    resp = client.get(f"/api/v1/ingestions/{ingestion.id}/validation")
    assert resp.status_code == 200
    results = resp.json()
    assert any(r["check_name"] == "schema" and r["status"] == "fail" for r in results)

    # Fetch a specific check.
    resp = client.get(f"/api/v1/ingestions/{ingestion.id}/validation/schema")
    assert resp.status_code == 200
    assert "amount" in resp.json()["details"]["missing_columns"]

    # Unknown check → 404.
    resp = client.get(f"/api/v1/ingestions/{ingestion.id}/validation/nonexistent")
    assert resp.status_code == 404
