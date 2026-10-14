import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.schemas import DatasetCreate, DatasetUpdate
from app.services.dataset_service import DatasetService


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_dataset(db):
    svc = DatasetService(db)
    ds = svc.create(DatasetCreate(name="q3-fr", process_type="FR"))
    assert ds.id is not None
    assert ds.name == "q3-fr"
    assert ds.process_type == "FR"
    assert ds.is_deleted is False


def test_create_normalises_process_type_to_uppercase(db):
    ds = DatasetService(db).create(DatasetCreate(name="absa-run", process_type="absa"))
    assert ds.process_type == "ABSA"


def test_create_invalid_process_type_rejected(db):
    with pytest.raises(HTTPException) as exc:
        DatasetService(db).create(DatasetCreate(name="bad", process_type="DOES_NOT_EXIST"))
    assert exc.value.status_code == 422


def test_create_duplicate_name_rejected(db):
    svc = DatasetService(db)
    svc.create(DatasetCreate(name="my-dataset", process_type="FR"))
    with pytest.raises(HTTPException) as exc:
        svc.create(DatasetCreate(name="my-dataset", process_type="ABSA"))
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# get / list
# ---------------------------------------------------------------------------


def test_get_dataset(db):
    svc = DatasetService(db)
    created = svc.create(DatasetCreate(name="fetched", process_type="OASIS"))
    fetched = svc.get(created.id)
    assert fetched.id == created.id


def test_get_missing_dataset_raises_404(db):
    with pytest.raises(HTTPException) as exc:
        DatasetService(db).get(99999)
    assert exc.value.status_code == 404


def test_list_excludes_deleted(db):
    svc = DatasetService(db)
    ds = svc.create(DatasetCreate(name="to-delete", process_type="FR"))
    svc.create(DatasetCreate(name="keep", process_type="ABSA"))
    svc.soft_delete(ds.id)
    results = svc.list()
    names = [d.name for d in results]
    assert "keep" in names
    assert "to-delete" not in names


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def test_update_description(db):
    svc = DatasetService(db)
    ds = svc.create(DatasetCreate(name="updatable", process_type="FR"))
    updated = svc.update(ds.id, DatasetUpdate(description="new desc"))
    assert updated.description == "new desc"


# ---------------------------------------------------------------------------
# soft_delete
# ---------------------------------------------------------------------------


def test_soft_delete_hides_dataset(db):
    svc = DatasetService(db)
    ds = svc.create(DatasetCreate(name="deleteme", process_type="ABSA"))
    svc.soft_delete(ds.id)
    with pytest.raises(HTTPException) as exc:
        svc.get(ds.id)
    assert exc.value.status_code == 404


def test_soft_delete_missing_dataset_raises_404(db):
    with pytest.raises(HTTPException) as exc:
        DatasetService(db).soft_delete(99999)
    assert exc.value.status_code == 404
