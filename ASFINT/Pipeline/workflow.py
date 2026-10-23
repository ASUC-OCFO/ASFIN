"""ASFIN processing orchestration."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import Path
import re
import shutil
from typing import Optional

import pandas as pd

from ASFINT.Config.Config import get_pFuncs
from ASFINT.Transform.Agenda_Processor import AGENDA_COLUMNS, Agenda_Docx_Metadata, Agenda_Docx_Processor
from ASFINT.Transform.FR_Processor import FR_COLUMNS, FR_Embedded_Date, FR_ProcessorV2
from ASFINT.Transform.Reconciliation_Processor import MERGED_COLUMNS, Merge_FR_Agenda
from ASFINT.Utility.Utils import ensure_folder


def pull(path: str, process_type: str, reporting: bool = False):
    pull_func = get_pFuncs(process_type, "pull")
    return pull_func(path, process_type)


def process(files: dict, process_type: str, reporting: bool = False) -> dict[str, pd.DataFrame]:
    processor = get_pFuncs(process_type=process_type, func="process")
    dfs, names = processor.dispatch(files.values(), files.keys(), reporting=reporting)
    return dict(zip(names, dfs))


def push(dfs: dict, path: str, process_type: str, reporting: bool = False):
    push_func = get_pFuncs(process_type, "push")
    for name, df in dfs.items():
        push_func(df, name, path)


def run(pull_path: str, push_path: str, process_type: str, reporting: bool = False):
    process_type = (process_type or "").upper()
    ensure_folder(pull_path)
    ensure_folder(push_path)
    files = pull(pull_path, process_type, reporting=reporting)
    cleaned = process(files, process_type, reporting=reporting)
    push(cleaned, push_path, process_type, reporting=reporting)


@dataclass
class ReviewFlag:
    severity: str
    code: str
    message: str
    source: str = "Pipeline"
    details: str = ""


@dataclass
class SourceFile:
    kind: str
    path: Path
    week: Optional[str]
    filename_date: Optional[str]
    embedded_date: Optional[str] = None
    sha256: Optional[str] = None


@dataclass
class FinanceCommitteeWeekResult:
    week: str
    meeting_date: str
    status: str
    fr: pd.DataFrame
    agenda: pd.DataFrame
    merged: pd.DataFrame
    flags: list[ReviewFlag] = field(default_factory=list)
    fr_source: Optional[Path] = None
    agenda_source: Optional[Path] = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_week(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    match = re.search(r"\b([FS])\s*0*(\d{1,2})\b", str(value), re.I)
    if not match:
        return None
    return f"{match.group(1).upper()}{int(match.group(2)):02d}"


def _week_sort_key(week: str) -> tuple[int, int]:
    match = re.fullmatch(r"([FS])(\d+)", week.upper())
    if not match:
        return 99, 999
    return (0 if match.group(1) == "F" else 1, int(match.group(2)))


def _date_from_filename(path: Path) -> Optional[str]:
    from datetime import datetime
    for pattern, fmt in [
        (r"(20\d{2}-\d{1,2}-\d{1,2})", "%Y-%m-%d"),
        (r"(\d{1,2}_\d{1,2}_20\d{2})", "%m_%d_%Y"),
        (r"(\d{1,2}-\d{1,2}-20\d{2})", "%m-%d-%Y"),
    ]:
        match = re.search(pattern, path.name)
        if match:
            try:
                return datetime.strptime(match.group(1), fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
    return None


def _flag_from_dict(value: dict) -> ReviewFlag:
    return ReviewFlag(
        severity=value.get("severity", "warning"),
        code=value.get("code", "REVIEW"),
        message=value.get("message", ""),
        source=value.get("source", "Pipeline"),
        details=value.get("details", ""),
    )


def _read_fr(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, header=None)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, header=None)
    raise ValueError(f"Unsupported FR input format: {path.suffix}")


def _clean_fr(path: Path, meeting_date: str):
    flags: list[ReviewFlag] = []
    raw = _read_fr(path)
    embedded_date = FR_Embedded_Date(raw)
    result = FR_ProcessorV2(raw, "", "%m/%d/%Y", original_filename=path.name)
    cleaned = next(iter(result.values())).copy()
    cleaned["Date"] = pd.Timestamp(meeting_date).strftime("%m/%d/%Y")

    for column in FR_COLUMNS:
        if column not in cleaned.columns:
            cleaned[column] = pd.NA
    cleaned = cleaned[FR_COLUMNS]

    if cleaned.empty:
        flags.append(ReviewFlag("warning", "FR_EMPTY", "FR input produced no rows", "FR"))
    elif cleaned["Org Name"].isna().any():
        flags.append(ReviewFlag("warning", "FR_ORG_MISSING", "One or more FR rows are missing an organization name", "FR"))

    return cleaned.reset_index(drop=True), embedded_date, flags


def discover_finance_committee_year(agenda_dir: Path, fr_dir: Path):
    flags: list[ReviewFlag] = []
    agendas: dict[str, SourceFile] = {}
    frs: dict[str, SourceFile] = {}

    agenda_candidates: list[SourceFile] = []
    for path in sorted(Path(agenda_dir).rglob("*.docx")):
        if path.name.startswith("._"):
            continue
        embedded_week, embedded_date = Agenda_Docx_Metadata(path)
        agenda_candidates.append(
            SourceFile(
                kind="Agenda",
                path=path,
                week=_normalize_week(embedded_week),
                filename_date=_date_from_filename(path),
                embedded_date=embedded_date,
                sha256=_sha256(path),
            )
        )

    by_hash: defaultdict[str, list[SourceFile]] = defaultdict(list)
    for source in agenda_candidates:
        by_hash[source.sha256 or ""].append(source)

    deduped: list[SourceFile] = []
    for group in by_hash.values():
        if len(group) == 1:
            deduped.append(group[0])
            continue
        ranked = sorted(group, key=lambda source: source.filename_date == source.embedded_date, reverse=True)
        keep = ranked[0]
        deduped.append(keep)
        for duplicate in ranked[1:]:
            flags.append(
                ReviewFlag(
                    "warning",
                    "DUPLICATE_AGENDA_FILE",
                    f"Ignoring duplicate agenda copy {duplicate.path.name}",
                    "Agenda",
                    f"Same SHA-256 as {keep.path.name}",
                )
            )

    for source in deduped:
        if not source.week:
            flags.append(ReviewFlag("error", "AGENDA_WEEK_MISSING", f"Could not identify meeting week in {source.path.name}", "Agenda"))
            continue
        if source.week in agendas:
            flags.append(
                ReviewFlag(
                    "error",
                    "AGENDA_WEEK_DUPLICATE",
                    f"Multiple agendas identify themselves as {source.week}",
                    "Agenda",
                    f"{agendas[source.week].path.name}; {source.path.name}",
                )
            )
            continue
        agendas[source.week] = source

    for path in sorted(Path(fr_dir).rglob("*")):
        if not path.is_file() or path.name.startswith("._") or path.suffix.lower() not in {".xlsx", ".xls", ".csv"}:
            continue
        week = _normalize_week(path.stem)
        if not week:
            flags.append(ReviewFlag("error", "FR_WEEK_MISSING", f"Could not identify meeting week in {path.name}", "FR"))
            continue
        if week in frs:
            flags.append(
                ReviewFlag(
                    "error",
                    "FR_WEEK_DUPLICATE",
                    f"Multiple FR inputs found for {week}",
                    "FR",
                    f"{frs[week].path.name}; {path.name}",
                )
            )
            continue
        frs[week] = SourceFile("FR", path, week, None, sha256=_sha256(path))

    return agendas, frs, flags


def process_finance_committee_week(
    week: str,
    meeting_date: str,
    fr_source: Optional[Path],
    agenda_source: Optional[Path],
) -> FinanceCommitteeWeekResult:
    flags: list[ReviewFlag] = []
    fr = pd.DataFrame(columns=FR_COLUMNS)
    agenda = pd.DataFrame(columns=AGENDA_COLUMNS)

    if fr_source:
        fr, embedded_fr_date, fr_flags = _clean_fr(Path(fr_source), meeting_date)
        flags.extend(fr_flags)
        if embedded_fr_date and embedded_fr_date != meeting_date:
            flags.append(
                ReviewFlag(
                    "warning",
                    "FR_DATE_MISMATCH",
                    f"FR embedded date disagrees with the meeting date for {week}",
                    "FR",
                    f"embedded={embedded_fr_date}; meeting={meeting_date}",
                )
            )
    else:
        flags.append(ReviewFlag("warning", "FR_INPUT_MISSING", f"No FR input for {week}", "FR"))

    if agenda_source:
        agenda, embedded_week, embedded_agenda_date, agenda_flags = Agenda_Docx_Processor(Path(agenda_source), meeting_date)
        flags.extend(_flag_from_dict(flag) for flag in agenda_flags)
        if embedded_week and embedded_week != week:
            flags.append(ReviewFlag("warning", "AGENDA_WEEK_MISMATCH", f"Agenda says {embedded_week}, but it was paired to {week}", "Agenda"))
        if embedded_agenda_date and embedded_agenda_date != meeting_date:
            flags.append(
                ReviewFlag(
                    "warning",
                    "AGENDA_DATE_MISMATCH",
                    f"Agenda embedded date disagrees with the meeting date for {week}",
                    "Agenda",
                    f"embedded={embedded_agenda_date}; meeting={meeting_date}",
                )
            )
    else:
        flags.append(ReviewFlag("warning", "AGENDA_INPUT_MISSING", f"No Agenda input for {week}", "Agenda"))

    agenda_all_no_record = not agenda.empty and (agenda["Committee Status"] == "No record on input doc").all()
    if fr.empty and agenda_all_no_record:
        flags.append(
            ReviewFlag(
                "warning",
                "EMPTY_MEETING",
                f"{week} has no FR and no recorded agenda decisions",
                "Pipeline",
                f"{len(agenda)} agenda entries had no motions",
            )
        )
        agenda = pd.DataFrame(columns=AGENDA_COLUMNS)

    merged, merge_flags = Merge_FR_Agenda(fr, agenda, meeting_date)
    flags.extend(_flag_from_dict(flag) for flag in merge_flags)

    if fr.empty and agenda.empty:
        status = "empty"
    elif fr.empty:
        status = "agenda_only"
    elif agenda.empty:
        status = "fr_only"
    else:
        status = "complete"

    return FinanceCommitteeWeekResult(
        week=week,
        meeting_date=meeting_date,
        status=status,
        fr=fr,
        agenda=agenda,
        merged=merged,
        flags=flags,
        fr_source=Path(fr_source) if fr_source else None,
        agenda_source=Path(agenda_source) if agenda_source else None,
    )


def _flags_dataframe(flags: list[ReviewFlag]) -> pd.DataFrame:
    columns = ["severity", "code", "message", "source", "details"]
    return pd.DataFrame([asdict(flag) for flag in flags], columns=columns)


_MONEY_COLUMNS = {
    "Amount Requested",
    "Amount",
    "FR Amount Requested",
    "FR Amount",
    "Agenda Amount",
}


def _format_money_value(value):
    if pd.isna(value):
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ""
        numeric = stripped.replace("$", "").replace(",", "")
        try:
            return f"{float(numeric):.2f}"
        except ValueError:
            return value
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return value


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    output = df.copy()
    for column in _MONEY_COLUMNS.intersection(output.columns):
        output[column] = output[column].map(_format_money_value)
    output.to_csv(path, index=False)


def contingency_from_merged(merged: pd.DataFrame) -> pd.DataFrame:
    if merged.empty:
        return merged.copy()

    mask = pd.Series(False, index=merged.index)
    for column in ("FR Request Type", "Agenda Request Type", "Request Type"):
        if column in merged.columns:
            mask |= merged[column].astype("string").str.contains(
                r"\bcontingency\b", case=False, na=False
            )
    return merged.loc[mask].reset_index(drop=True)


def _write_finance_committee_week(result: FinanceCommitteeWeekResult, output_root: Path) -> dict:
    date_iso = pd.Timestamp(result.meeting_date).strftime("%Y-%m-%d")
    prefix = f"{result.week}_{date_iso}"
    week_dir = output_root / prefix
    week_dir.mkdir(parents=True, exist_ok=True)

    if result.fr_source:
        shutil.copy2(result.fr_source, week_dir / f"{prefix}_FR_input{result.fr_source.suffix.lower()}")
    if result.agenda_source:
        shutil.copy2(result.agenda_source, week_dir / f"{prefix}_Agenda_input{result.agenda_source.suffix.lower()}")

    contingency = contingency_from_merged(result.merged)
    _write_csv(result.fr, week_dir / f"{prefix}_FR_cleaned.csv")
    _write_csv(result.agenda, week_dir / f"{prefix}_Agenda_cleaned.csv")
    _write_csv(result.merged, week_dir / f"{prefix}_merged.csv")
    _write_csv(contingency, week_dir / f"{prefix}_contingency.csv")
    _flags_dataframe(result.flags).to_csv(week_dir / f"{prefix}_review.csv", index=False)

    return {
        "week": result.week,
        "date": date_iso,
        "status": result.status,
        "fr_input": result.fr_source.name if result.fr_source else "",
        "agenda_input": result.agenda_source.name if result.agenda_source else "",
        "fr_rows": len(result.fr),
        "agenda_rows": len(result.agenda),
        "merged_rows": len(result.merged),
        "contingency_rows": len(contingency),
        "warnings": sum(flag.severity == "warning" for flag in result.flags),
        "errors": sum(flag.severity == "error" for flag in result.flags),
    }


def process_finance_committee_year(agenda_dir: Path, fr_dir: Path, output_root: Path):
    agenda_dir = Path(agenda_dir)
    fr_dir = Path(fr_dir)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    agendas, frs, discovery_flags = discover_finance_committee_year(agenda_dir, fr_dir)
    weeks = sorted(set(agendas) | set(frs), key=_week_sort_key)
    results = []
    manifest_rows = []

    for week in weeks:
        agenda_source = agendas.get(week)
        fr_source = frs.get(week)
        meeting_date = agenda_source.filename_date if agenda_source else None
        if not meeting_date and fr_source:
            meeting_date = FR_Embedded_Date(_read_fr(fr_source.path))
        if not meeting_date:
            discovery_flags.append(ReviewFlag("error", "MEETING_DATE_MISSING", f"Could not determine a meeting date for {week}; week skipped", "Pipeline"))
            continue

        result = process_finance_committee_week(
            week,
            meeting_date,
            fr_source.path if fr_source else None,
            agenda_source.path if agenda_source else None,
        )
        results.append(result)
        manifest_rows.append(_write_finance_committee_week(result, output_root))

    manifest = pd.DataFrame(manifest_rows)
    manifest.to_csv(output_root / "manifest.csv", index=False)

    discovery_df = _flags_dataframe(discovery_flags)
    discovery_df.to_csv(output_root / "discovery_review.csv", index=False)

    frames = []
    if not discovery_df.empty:
        frame = discovery_df.copy()
        frame.insert(0, "date", "")
        frame.insert(0, "week", "")
        frames.append(frame)
    for result in results:
        frame = _flags_dataframe(result.flags)
        if frame.empty:
            continue
        frame.insert(0, "date", pd.Timestamp(result.meeting_date).strftime("%Y-%m-%d"))
        frame.insert(0, "week", result.week)
        frames.append(frame)

    columns = ["week", "date", "severity", "code", "message", "source", "details"]
    review_flags = pd.concat(frames, ignore_index=True)[columns] if frames else pd.DataFrame(columns=columns)
    review_flags.to_csv(output_root / "review_flags.csv", index=False)

    if review_flags.empty:
        summary = pd.DataFrame(columns=["severity", "code", "count"])
    else:
        summary = (
            review_flags.groupby(["severity", "code"], dropna=False)
            .size()
            .reset_index(name="count")
            .sort_values(["severity", "count", "code"], ascending=[True, False, True])
        )
    summary.to_csv(output_root / "review_summary.csv", index=False)
    return results, manifest, discovery_flags
