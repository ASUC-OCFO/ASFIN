from __future__ import annotations

import argparse

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.models import Dataset


CANONICAL_DATASETS = (
    {
        "name": "FICOMM",
        "process_type": "FICOMM",
        "description": "Finance Committee FR and Agenda processing",
    },
    {
        "name": "ABSA",
        "process_type": "ABSA",
        "description": "ABSA processing",
    },
)


def bootstrap_datasets(db: Session) -> list[Dataset]:
    datasets: list[Dataset] = []

    for spec in CANONICAL_DATASETS:
        dataset = db.query(Dataset).filter(Dataset.name == spec["name"]).first()
        if dataset:
            if dataset.process_type != spec["process_type"]:
                raise ValueError(
                    f"Dataset '{dataset.name}' has process_type={dataset.process_type}; "
                    f"expected {spec['process_type']}"
                )
            dataset.is_deleted = False
            if not dataset.description:
                dataset.description = spec["description"]
        else:
            dataset = Dataset(**spec)
            db.add(dataset)

        datasets.append(dataset)

    db.commit()
    for dataset in datasets:
        db.refresh(dataset)
    return datasets


def list_datasets(db: Session) -> list[Dataset]:
    return db.query(Dataset).order_by(Dataset.id).all()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage canonical datasets")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("bootstrap", help="Ensure canonical datasets exist")
    subparsers.add_parser("list", help="List datasets")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    db = SessionLocal()
    try:
        if args.command == "bootstrap":
            datasets = bootstrap_datasets(db)
            for dataset in datasets:
                print(f"{dataset.id}\t{dataset.name}\t{dataset.process_type}")
        else:
            for dataset in list_datasets(db):
                print(
                    f"{dataset.id}\t{dataset.name}\t{dataset.process_type}\t"
                    f"is_deleted={dataset.is_deleted}"
                )
    except ValueError as exc:
        db.rollback()
        print(f"error: {exc}")
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
