from __future__ import annotations

import argparse

from app.core.database import SessionLocal
from app.core.models import ProcessingRun
from app.services.ficomm_publication_service import FiCommPublicationService
from app.services.ficomm_run_service import FiCommRunService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage FiComm processing runs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    period = subparsers.add_parser(
        "process-period",
        help="Process all accepted FiComm sources in one collection period",
    )
    period.add_argument("period_id", type=int)
    period.add_argument("--triggered-by")

    periods = subparsers.add_parser(
        "process-periods",
        help="Process accepted FiComm sources across multiple collection periods",
    )
    periods.add_argument("period_ids", nargs="+", type=int)
    periods.add_argument("--label")
    periods.add_argument("--triggered-by")

    publish = subparsers.add_parser(
        "publish-run",
        help="Load a completed weekly FiComm run into queryable tables",
    )
    publish.add_argument("run_id", type=int)
    publish.add_argument("--published-by")

    publish_period = subparsers.add_parser(
        "publish-period",
        help="Publish completed weekly FiComm runs in one collection period",
    )
    publish_period.add_argument("period_id", type=int)
    publish_period.add_argument("--published-by")

    subparsers.add_parser("list-runs", help="List FiComm processing runs")
    return parser


def _print_run(run: ProcessingRun) -> None:
    print(
        f"{run.id}\ttype={run.run_type}\tstatus={run.status}\t"
        f"publication={run.publication_status or '-'}\tperiod={run.period_id}\t"
        f"parent={run.parent_run_id}\tlabel={run.label or ''}"
    )


def main() -> int:
    args = _build_parser().parse_args()
    db = SessionLocal()
    try:
        service = FiCommRunService(db)
        if args.command == "process-period":
            run = service.process_period(args.period_id, triggered_by=args.triggered_by)
            _print_run(run)
        elif args.command == "process-periods":
            run = service.process_periods(
                args.period_ids,
                label=args.label,
                triggered_by=args.triggered_by,
            )
            _print_run(run)
        elif args.command == "publish-run":
            result = FiCommPublicationService(db).publish_run(
                args.run_id,
                published_by=args.published_by,
            )
            print(
                f"{result.run_id}\trecords={result.records.row_count}\t"
                f"review_flags={result.review_flags.row_count}"
            )
        elif args.command == "publish-period":
            result = FiCommPublicationService(db).publish_period(
                args.period_id,
                published_by=args.published_by,
            )
            print(
                f"period={result.period_id}\tattempted={result.attempted}\t"
                f"published={result.published}\tskipped={result.skipped}\t"
                f"failed={result.failed}"
            )
            for error in result.errors:
                print(f"error: {error}")
            if result.failed:
                return 1
        else:
            runs = (
                db.query(ProcessingRun)
                .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id.desc())
                .all()
            )
            for run in runs:
                _print_run(run)
    except (LookupError, ValueError) as exc:
        db.rollback()
        print(f"error: {exc}")
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
