from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.models import CollectionPeriod, Dataset


def create_period(
    db: Session,
    dataset_id: int,
    label: str,
    starts_on: date,
    ends_on: date,
    accept_uploads: bool = False,
) -> CollectionPeriod:
    if starts_on > ends_on:
        raise ValueError("starts_on must be on or before ends_on")

    dataset = (
        db.query(Dataset)
        .filter(Dataset.id == dataset_id, Dataset.is_deleted.is_(False))
        .first()
    )
    if not dataset:
        raise ValueError(f"Dataset {dataset_id} not found")

    duplicate = (
        db.query(CollectionPeriod)
        .filter(
            CollectionPeriod.dataset_id == dataset_id,
            CollectionPeriod.label == label,
        )
        .first()
    )
    if duplicate:
        raise ValueError(f"Period '{label}' already exists for dataset {dataset_id}")

    overlap = (
        db.query(CollectionPeriod)
        .filter(
            CollectionPeriod.dataset_id == dataset_id,
            CollectionPeriod.starts_on <= ends_on,
            CollectionPeriod.ends_on >= starts_on,
        )
        .first()
    )
    if overlap:
        raise ValueError(
            f"Date range overlaps period {overlap.id} '{overlap.label}' "
            f"({overlap.starts_on} to {overlap.ends_on})"
        )

    period = CollectionPeriod(
        dataset_id=dataset_id,
        label=label,
        starts_on=starts_on,
        ends_on=ends_on,
        accept_uploads=accept_uploads,
    )
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


def list_periods(db: Session, dataset_id: int | None = None) -> list[CollectionPeriod]:
    query = db.query(CollectionPeriod)
    if dataset_id is not None:
        query = query.filter(CollectionPeriod.dataset_id == dataset_id)
    return query.order_by(CollectionPeriod.starts_on, CollectionPeriod.id).all()


def set_uploads(db: Session, period_id: int, accept_uploads: bool) -> CollectionPeriod:
    period = db.query(CollectionPeriod).filter(CollectionPeriod.id == period_id).first()
    if not period:
        raise ValueError(f"Period {period_id} not found")

    period.accept_uploads = accept_uploads
    db.commit()
    db.refresh(period)
    return period


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage collection periods")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a whitelisted period")
    create.add_argument("--dataset-id", type=int, required=True)
    create.add_argument("--label", required=True)
    create.add_argument("--start", type=_date, required=True)
    create.add_argument("--end", type=_date, required=True)
    create.add_argument("--open", action="store_true", dest="accept_uploads")

    list_command = subparsers.add_parser("list", help="List collection periods")
    list_command.add_argument("--dataset-id", type=int)

    open_command = subparsers.add_parser("open", help="Allow normal uploads for a period")
    open_command.add_argument("period_id", type=int)

    close_command = subparsers.add_parser("close", help="Block normal uploads for a period")
    close_command.add_argument("period_id", type=int)

    return parser


def main() -> int:
    args = _build_parser().parse_args()
    db = SessionLocal()
    try:
        if args.command == "create":
            period = create_period(
                db,
                dataset_id=args.dataset_id,
                label=args.label,
                starts_on=args.start,
                ends_on=args.end,
                accept_uploads=args.accept_uploads,
            )
            print(
                f"created period {period.id}: {period.label} "
                f"({period.starts_on} to {period.ends_on}), "
                f"accept_uploads={period.accept_uploads}"
            )
        elif args.command == "list":
            periods = list_periods(db, args.dataset_id)
            for period in periods:
                print(
                    f"{period.id}\tdataset={period.dataset_id}\t{period.label}\t"
                    f"{period.starts_on}\t{period.ends_on}\t"
                    f"accept_uploads={period.accept_uploads}"
                )
        elif args.command == "open":
            period = set_uploads(db, args.period_id, True)
            print(f"period {period.id} accept_uploads=True")
        else:
            period = set_uploads(db, args.period_id, False)
            print(f"period {period.id} accept_uploads=False")
    except ValueError as exc:
        db.rollback()
        print(f"error: {exc}")
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
