"""Local runner for Finance Committee processing."""

from __future__ import annotations

import argparse
from pathlib import Path

from ASFINT.Pipeline.workflow import process_finance_committee_year


def main() -> int:
    parser = argparse.ArgumentParser(description="Process Finance Committee FR and Agenda files")
    parser.add_argument("--agendas", required=True, type=Path)
    parser.add_argument("--frs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    results, manifest, discovery_flags = process_finance_committee_year(args.agendas, args.frs, args.output)
    print(manifest.to_string(index=False))
    print(f"\nProcessed {len(results)} weeks; discovery review flags: {len(discovery_flags)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
