from datetime import date

import pytest

from app.admin.periods import create_period, list_periods, set_uploads
from app.core.models import Dataset


def _dataset(db, name="Finance Committee"):
    dataset = Dataset(name=name, process_type="FICOMM")
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


def test_create_and_list_period(db):
    dataset = _dataset(db)

    created = create_period(
        db,
        dataset_id=dataset.id,
        label="Fall 2026",
        starts_on=date(2026, 8, 1),
        ends_on=date(2026, 12, 31),
    )

    periods = list_periods(db, dataset.id)
    assert [period.id for period in periods] == [created.id]
    assert created.accept_uploads is False


def test_create_period_rejects_overlap(db):
    dataset = _dataset(db)
    create_period(
        db,
        dataset_id=dataset.id,
        label="Fall 2026",
        starts_on=date(2026, 8, 1),
        ends_on=date(2026, 12, 31),
    )

    with pytest.raises(ValueError, match="overlaps period"):
        create_period(
            db,
            dataset_id=dataset.id,
            label="Late Fall 2026",
            starts_on=date(2026, 11, 1),
            ends_on=date(2027, 1, 15),
        )


def test_set_uploads_opens_and_closes_period(db):
    dataset = _dataset(db)
    period = create_period(
        db,
        dataset_id=dataset.id,
        label="Spring 2027",
        starts_on=date(2027, 1, 1),
        ends_on=date(2027, 5, 31),
    )

    assert set_uploads(db, period.id, True).accept_uploads is True
    assert set_uploads(db, period.id, False).accept_uploads is False
