from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.models import Dataset, Ingestion
from app.services.publish_service import PostgreSQLWarehousePublisher, PublishService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def _make_dataset(db, name="finance-committee"):
    dataset = Dataset(name=name, process_type="FR")
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


def _make_ingestion(db, dataset_id, clean_path, *, status="clean_ready", sha="abc123"):
    ingestion = Ingestion(
        dataset_id=dataset_id,
        status=status,
        original_filename="report.csv",
        file_ext=".csv",
        raw_path="unused.csv",
        clean_path=str(clean_path),
        file_sha256=sha,
    )
    db.add(ingestion)
    db.commit()
    db.refresh(ingestion)
    return ingestion


def test_postgres_publisher_sanitizes_names_and_writes_table():
    engine = create_engine("sqlite:///:memory:")
    publisher = PostgreSQLWarehousePublisher(engine=engine)

    df = pd.DataFrame(
        [["A", 100, 100], ["B", 200, 200]],
        columns=["Org Name", "Amount($)", "Amount($)"],
    )

    table_name, row_count, schema_snapshot = publisher.publish(
        df,
        dataset_name="Finance Committee Report",
        version_number=3,
    )

    assert table_name == "Finance_Committee_Report_v3"
    assert row_count == 2
    assert "Org_Name" in schema_snapshot
    assert "Amount" in schema_snapshot

    inspector = inspect(engine)
    assert table_name in inspector.get_table_names()

    with engine.connect() as conn:
        rows = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one()
        assert rows == 2


def test_publish_creates_version_and_marks_ingestion_published(db, tmp_path):
    warehouse_engine = create_engine("sqlite:///:memory:")
    dataset = _make_dataset(db, name="finance committee")

    parquet_path = tmp_path / "clean.parquet"
    pd.DataFrame({"Org Name": ["A", "B"], "Amount($)": [100, 200]}).to_parquet(parquet_path, index=False)
    ingestion = _make_ingestion(db, dataset.id, parquet_path)

    service = PublishService(db, publisher=PostgreSQLWarehousePublisher(engine=warehouse_engine))
    result = service.publish(ingestion.id)

    assert result.version.version_number == 1
    assert result.version.is_latest is True
    assert result.row_count == 2

    db.refresh(ingestion)
    assert ingestion.status == "published"


def test_publish_twice_flips_is_latest(db, tmp_path):
    warehouse_engine = create_engine("sqlite:///:memory:")
    dataset = _make_dataset(db, name="budget")

    p1 = tmp_path / "first.parquet"
    p2 = tmp_path / "second.parquet"
    pd.DataFrame({"Org Name": ["A"], "Amount": [100]}).to_parquet(p1, index=False)
    pd.DataFrame({"Org Name": ["B"], "Amount": [200]}).to_parquet(p2, index=False)

    i1 = _make_ingestion(db, dataset.id, p1, sha="sha1")
    i2 = _make_ingestion(db, dataset.id, p2, sha="sha2")

    service = PublishService(db, publisher=PostgreSQLWarehousePublisher(engine=warehouse_engine))
    v1 = service.publish(i1.id).version
    v2 = service.publish(i2.id).version

    db.refresh(v1)
    db.refresh(v2)
    assert v1.version_number == 1
    assert v1.is_latest is False
    assert v2.version_number == 2
    assert v2.is_latest is True


def test_publish_rejects_non_clean_ready_ingestion(db, tmp_path):
    dataset = _make_dataset(db)
    parquet_path = tmp_path / "clean.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(parquet_path, index=False)
    ingestion = _make_ingestion(db, dataset.id, parquet_path, status="pending")

    service = PublishService(
        db,
        publisher=PostgreSQLWarehousePublisher(engine=create_engine("sqlite:///:memory:")),
    )
    with pytest.raises(HTTPException) as exc:
        service.publish(ingestion.id)

    assert exc.value.status_code == 409
