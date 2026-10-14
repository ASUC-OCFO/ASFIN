"""Command-line entry point for the generic ASFIN processing workflow."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from ASFINT.Pipeline.workflow import run
from ASFINT.Utility.Utils import ensure_folder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an ASFIN processor locally.")
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=Path("files/input"),
        help="Input file or directory",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("files/output"),
        help="Output directory",
    )
    parser.add_argument(
        "--process",
        "-p",
        default="fr",
        help="Processor type, such as fr, absa, or agenda",
    )
    parser.add_argument(
        "--reporting",
        "-r",
        action="store_true",
        help="Enable processor reporting output",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    pull_path = args.input.expanduser().resolve()
    push_path = args.output.expanduser().resolve()

    if not pull_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {pull_path}")

    ensure_folder(push_path)

    run(
        pull_path=str(pull_path),
        push_path=str(push_path),
        process_type=args.process,
        reporting=args.reporting,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
