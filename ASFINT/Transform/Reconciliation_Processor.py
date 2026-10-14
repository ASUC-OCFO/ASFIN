"""Finance Committee FR/Agenda reconciliation utilities.

``Reconcile_FR_Agenda`` retains the legacy agenda-priority behavior.
``Merge_FR_Agenda`` is the current lossless matcher and preserves values from
both source documents for review.
"""

import pandas as pd
import numpy as np
from typing import Tuple, Dict
from pathlib import Path


def Reconcile_FR_Agenda(fr_df: pd.DataFrame, agenda_df: pd.DataFrame) -> pd.DataFrame:
    """Reconcile FR and Agenda outputs using the legacy agenda-priority rules.

    The function performs an outer join on organization name and uses Agenda
    values for amount, committee status, and request type when both sources
    contain a value.
    """

    # Return the available source unchanged when its counterpart is empty.
    if fr_df is None or fr_df.empty:
        print("[RECONCILE] FR DataFrame is empty, returning Agenda data only")
        return agenda_df.copy() if agenda_df is not None else pd.DataFrame()

    if agenda_df is None or agenda_df.empty:
        print("[RECONCILE] Agenda DataFrame is empty, returning FR data only")
        return fr_df.copy()

    # Both inputs require an organization-name column for reconciliation.
    if 'Org Name' not in fr_df.columns:
        raise ValueError("FR DataFrame missing 'Org Name' column")
    if 'Org Name' not in agenda_df.columns:
        raise ValueError("Agenda DataFrame missing 'Org Name' column")

    # Trim organization names before matching.
    fr_df = fr_df.copy()
    agenda_df = agenda_df.copy()

    fr_df['Org Name'] = fr_df['Org Name'].astype(str).str.strip()
    agenda_df['Org Name'] = agenda_df['Org Name'].astype(str).str.strip()

    # Select FR columns used by the legacy reconciliation output.
    fr_cols = ['Org Name', 'Request Type']
    if 'Amount Requested' in fr_df.columns:
        fr_cols.append('Amount Requested')
    if 'Org Type (year)' in fr_df.columns:
        fr_cols.append('Org Type (year)')

    # Include FR decision fields before adding Agenda-specific suffixes.
    if 'Amount' in fr_df.columns:
        fr_cols.append('Amount')
    if 'Committee Status' in fr_df.columns:
        fr_cols.append('Committee Status')

    fr_subset = fr_df[[col for col in fr_cols if col in fr_df.columns]].copy()

    # Select Agenda columns used by the legacy reconciliation output.
    agenda_subset = agenda_df[['Org Name', 'Request Type', 'Amount', 'Committee Status', 'Date']].copy()

    # Keep Agenda decision fields distinct through the merge.
    agenda_subset = agenda_subset.rename(columns={
        'Amount': 'Agenda_Amount',
        'Committee Status': 'Agenda_Status',
        'Request Type': 'Agenda_Request_Type',
        'Date': 'Agenda_Date'
    })

    # Preserve organizations that occur in only one source.
    merged = fr_subset.merge(
        agenda_subset,
        on='Org Name',
        how='outer',
        indicator=True
    )

    # Legacy behavior gives Agenda values precedence when both sources are populated.

    # Reconcile amount.
    if 'Amount' in merged.columns:
        merged['Amount_Final'] = merged['Agenda_Amount'].combine_first(merged['Amount'])
    else:
        merged['Amount_Final'] = merged['Agenda_Amount']

    # Reconcile committee status.
    if 'Committee Status' in merged.columns:
        merged['Committee_Status_Final'] = merged['Agenda_Status'].combine_first(merged['Committee Status'])
    else:
        merged['Committee_Status_Final'] = merged['Agenda_Status']

    # Reconcile request type.
    if 'Request Type' in merged.columns:
        merged['Request_Type_Final'] = merged['Agenda_Request_Type'].combine_first(merged['Request Type'])
    else:
        merged['Request_Type_Final'] = merged['Agenda_Request_Type']

    # Record which source documents contributed to each row.
    merged['Data_Source'] = merged['_merge'].map({
        'left_only': 'FR Only',
        'right_only': 'Agenda Only',
        'both': 'Both (Agenda Priority)'
    })

    # Legacy amount rules set non-approved requests to zero except tabled/denied sponsorships.
    merged['Committee_Status_Final'] = merged['Committee_Status_Final'].fillna('')
    is_approved = merged['Committee_Status_Final'].astype(str).str.contains('Approved', case=False, na=False)

    # Set non-approved requests to zero.
    merged.loc[~is_approved, 'Amount_Final'] = 0

    # Keep tabled or denied sponsorship amounts blank.
    is_sponsorship = merged['Request_Type_Final'].astype(str).str.contains('Sponsorship', case=False, na=False)
    is_tabled_or_denied = (
        merged['Committee_Status_Final'].astype(str).str.contains('Table', case=False, na=False) |
        merged['Committee_Status_Final'].astype(str).str.contains('Denied', case=False, na=False)
    )
    merged.loc[is_sponsorship & is_tabled_or_denied, 'Amount_Final'] = None

    # Build the legacy output schema in a stable column order.
    final_cols_ordered = []
    final_col_mapping = {}

    # Required output columns.
    final_cols_ordered.append('Org Name')
    final_col_mapping['Org Name'] = 'Org Name'

    final_cols_ordered.append('Request_Type_Final')
    final_col_mapping['Request_Type_Final'] = 'Request Type'

    # Requested amount from FR.
    if 'Amount Requested' in merged.columns:
        final_cols_ordered.append('Amount Requested')
        final_col_mapping['Amount Requested'] = 'Amount Requested'

    final_cols_ordered.append('Amount_Final')
    final_col_mapping['Amount_Final'] = 'Amount'

    final_cols_ordered.append('Committee_Status_Final')
    final_col_mapping['Committee_Status_Final'] = 'Committee Status'

    final_cols_ordered.append('Data_Source')
    final_col_mapping['Data_Source'] = 'Source'

    # Organization type from FR.
    if 'Org Type (year)' in merged.columns:
        final_cols_ordered.append('Org Type (year)')
        final_col_mapping['Org Type (year)'] = 'Org Type (year)'

    # Meeting date from Agenda.
    if 'Agenda_Date' in merged.columns:
        final_cols_ordered.append('Agenda_Date')
        final_col_mapping['Agenda_Date'] = 'Date'

    # Select available output columns and apply final names.
    result = merged[[col for col in final_cols_ordered if col in merged.columns]].copy()
    result.columns = [final_col_mapping[col] for col in result.columns]

    # Sort by request type, then organization name.
    request_type_order = {
        'Contingency': 1,
        'Finance Rule': 2,
        'Space Reservation': 3,
        'Sponsorship': 4
    }

    # Unrecognized request types sort after the configured categories.
    result['_sort_key'] = result['Request Type'].map(request_type_order).fillna(999)

    # Apply the stable output ordering.
    result = result.sort_values(['_sort_key', 'Org Name']).reset_index(drop=True)

    # Remove the temporary sort key.
    result = result.drop(columns=['_sort_key'])

    # Report reconciliation counts.
    both_count = (merged['_merge'] == 'both').sum()
    fr_only_count = (merged['_merge'] == 'left_only').sum()
    agenda_only_count = (merged['_merge'] == 'right_only').sum()

    print(f"[RECONCILE] Summary:")
    print(f"  - Organizations in both FR and Agenda: {both_count} (Agenda data used)")
    print(f"  - Organizations only in FR: {fr_only_count}")
    print(f"  - Organizations only in Agenda: {agenda_only_count}")
    print(f"  - Total organizations: {len(result)}")

    return result


def _scan_outputs_by_date(output_dir: str) -> Dict[str, Dict[str, Tuple[str, pd.DataFrame]]]:
    """Scan processed CSV files and group FR/Agenda outputs by Date.

    Each dictionary entry contains the optional FR and Agenda output associated
    with one meeting date. Files without a usable Date value are skipped.
    """
    output_path = Path(output_dir)

    if not output_path.exists():
        raise FileNotFoundError(f"Output directory does not exist: {output_dir}")

    if not output_path.is_dir():
        raise ValueError(f"Expected directory path, got file: {output_dir}")

    # Group processed files by their Date column.
    files_by_date = {}

    print(f"\n[BATCH RECONCILE] Scanning {output_dir} for FR and Agenda files...")

    # Scan processed CSV files.
    for csv_file in output_path.glob("*.csv"):
        try:
            df = pd.read_csv(csv_file)

            # Files without a Date column cannot be paired by meeting date.
            if 'Date' not in df.columns:
                print(f"  [SKIP] {csv_file.name} - no Date column")
                continue

            # Processed files use one meeting date per file.
            date = df['Date'].iloc[0]

            if pd.isna(date) or str(date).strip() == "" or str(date) == "undated":
                print(f"  [SKIP] {csv_file.name} - invalid date: {date}")
                continue

            # Initialize the date group on first use.
            if date not in files_by_date:
                files_by_date[date] = {'fr': None, 'agenda': None}

            # Classify processed files by filename.
            filename_stem = csv_file.stem  # filename without extension

            # Treat FR and SR filenames as Finance Resolution outputs.
            if 'Cleaned' in csv_file.name and ('FR' in csv_file.name or 'SR' in csv_file.name or 'fr' in csv_file.name.lower() or 'sr' in csv_file.name.lower()):
                files_by_date[date]['fr'] = (filename_stem, df)
                print(f"  [FR/SR]  {csv_file.name} | Date: {date}")
            elif 'Agenda' in csv_file.name:
                files_by_date[date]['agenda'] = (filename_stem, df)
                print(f"  [AGENDA] {csv_file.name} | Date: {date}")
            else:
                print(f"  [SKIP] {csv_file.name} - doesn't match FR or Agenda pattern")

        except Exception as e:
            print(f"  [ERROR] {csv_file.name} - {e}")
            continue

    return files_by_date


def Reconcile_FR_Agenda_Batch(
    output_dir: str,
    return_unmatched: bool = False,
    reporting: bool = True
) -> Dict[str, pd.DataFrame]:
    """Batch reconcile processed FR and Agenda files by Date.

    Args:
        output_dir: Directory containing processed FR and Agenda CSV files.
        return_unmatched: Include one-sided source files in the returned mapping.
        reporting: Retained for compatibility with existing callers.

    Returns:
        Mapping from output names to reconciled DataFrames.

    Raises:
        FileNotFoundError: If ``output_dir`` does not exist.
        ValueError: If no valid FR or Agenda files can be grouped by date.
    """
    # Group files by meeting date.
    files_by_date = _scan_outputs_by_date(output_dir)

    if not files_by_date:
        raise ValueError(f"No FR or Agenda files with Date columns found in {output_dir}")

    # Track batch reconciliation counts.
    reconciled_count = 0
    fr_only_count = 0
    agenda_only_count = 0

    # Store reconciled outputs by meeting date.
    results = {}

    print("\n" + "=" * 70)
    print("BATCH RECONCILIATION - MATCHING FILES BY DATE")
    print("=" * 70)

    # Process each meeting date.
    for date in sorted(files_by_date.keys()):
        files = files_by_date[date]
        fr_pair = files.get('fr')
        agenda_pair = files.get('agenda')

        print(f"\nDate: {date}")
        print("-" * 70)

        # Reconcile dates with both source outputs.
        if fr_pair and agenda_pair:
            fr_name, fr_df = fr_pair
            agenda_name, agenda_df = agenda_pair

            print(f"  [OK] FR:     {fr_name}.csv ({len(fr_df)} rows)")
            print(f"  [OK] Agenda: {agenda_name}.csv ({len(agenda_df)} rows)")
            print(f"  Reconciling...")

            try:
                # Use the single-pair legacy reconciliation function.
                reconciled_df = Reconcile_FR_Agenda(fr_df, agenda_df)

                # Derive the legacy finalized output name.
                if "Cleaned" in fr_name:
                    output_name = fr_name.replace("Cleaned", "Finalized")
                else:
                    output_name = f"{fr_name} Finalized"

                results[output_name] = reconciled_df
                reconciled_count += 1

                print(f"  [OK] Success: {output_name}.csv ({len(reconciled_df)} rows)")

            except Exception as e:
                print(f"  [ERROR] Reconciliation failed: {e}")

        # Report dates with only an FR output.
        elif fr_pair and not agenda_pair:
            fr_name, fr_df = fr_pair
            print(f"  [MISSING] FR:     {fr_name}.csv ({len(fr_df)} rows)")
            print(f"  [MISSING] Agenda: MISSING")
            print(f"  Cannot reconcile (no matching Agenda file)")
            fr_only_count += 1

            if return_unmatched:
                results[fr_name] = fr_df

        # Report dates with only an Agenda output.
        elif agenda_pair and not fr_pair:
            agenda_name, agenda_df = agenda_pair
            print(f"  [MISSING] FR:     MISSING")
            print(f"  [MISSING] Agenda: {agenda_name}.csv ({len(agenda_df)} rows)")
            print(f"  Cannot reconcile (no matching FR file)")
            agenda_only_count += 1

            if return_unmatched:
                results[agenda_name] = agenda_df

    # Print batch reconciliation counts.
    print("\n" + "=" * 70)
    print("BATCH RECONCILIATION SUMMARY")
    print("=" * 70)
    print(f"Total dates found: {len(files_by_date)}")
    print(f"  Successfully reconciled: {reconciled_count} pairs")
    print(f"  FR only (no Agenda):     {fr_only_count}")
    print(f"  Agenda only (no FR):     {agenda_only_count}")
    print(f"\nTotal output files: {len(results)}")
    print("=" * 70)

    if reconciled_count == 0:
        print("\nWARNING: No files were reconciled!")
        print("  - Make sure both FR and Agenda files have Date columns")
        print("  - Make sure dates match between FR and Agenda files")
        print("  - Reprocess FR files if they're missing Date columns")

    return results


# Lossless FR/Agenda matching used by the current pipeline.
from ASFINT.Utility.Matching import normalize_entity_name, unique_fuzzy_match

MERGED_COLUMNS = [
    "Document Match Type",
    "Document Match Score",
    "FR Org Name",
    "Agenda Org Name",
    "FR Request Type",
    "Agenda Request Type",
    "FR Appx.",
    "FR Org Type (year)",
    "FR Amount Requested",
    "FR Amount",
    "Agenda Amount",
    "FR Committee Status",
    "Agenda Committee Status",
    "FR Funding Source",
    "FR Primary Contact",
    "FR Email Address",
    "FR Date",
    "Agenda Date",
    "Meeting Date",
]


def _merge_compact(value) -> str:
    import re
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _merge_request_type_key(value) -> str:
    text = _merge_compact(value).lower()
    if "contingency" in text:
        return "contingency"
    if "finance" in text or "rule waiver" in text:
        return "finance rule"
    if "space" in text:
        return "space reservation"
    if "sponsor" in text:
        return "sponsorship"
    if "absa" in text and "appeal" in text:
        return "absa budget appeals"
    if "senate" in text:
        return "senate bill"
    return text


def _merge_entity_key(name, request_type) -> str:
    import re

    type_key = _merge_request_type_key(request_type)
    if type_key == "senate bill":
        text = _merge_compact(name)
        match = re.search(r"\bSR\s*(\d{2})\s*/\s*(\d{2})\s*[- ]?\s*(\d{3})\b", text, re.I)
        if not match:
            match = re.search(r"\bSenate\s+Resolution(?:\s+No\.?)?\s*(\d{4})\s*/\s*(\d{4})\s*[- ]?\s*(\d{3})\b", text, re.I)
            if match:
                return f"sr {match.group(1)[-2:]} {match.group(2)[-2:]} {int(match.group(3))}"
        if match:
            return f"sr {match.group(1)} {match.group(2)} {int(match.group(3))}"
    return normalize_entity_name(name)


def _add_merge_keys(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        cols = list(df.columns) if df is not None else []
        return pd.DataFrame(columns=cols + ["_org_key", "_type_key", "_occ"])
    out = df.copy()
    out["_type_key"] = out["Request Type"].map(_merge_request_type_key)
    out["_org_key"] = [
        _merge_entity_key(name, request_type)
        for name, request_type in zip(out["Org Name"], out["Request Type"])
    ]
    out["_occ"] = out.groupby(["_org_key", "_type_key"]).cumcount()
    return out


def _merge_status_key(value) -> str:
    text = _merge_compact(value).lower()
    if not text:
        return ""
    if "partial" in text and "approv" in text:
        return "partially approved"
    if "table" in text and "indef" in text:
        return "tabled indefinitely"
    if "table" in text:
        return "tabled"
    if "den" in text:
        return "denied"
    if "forward" in text and "senate" in text:
        return "forwarded to senate"
    if "approv" in text:
        return "approved"
    return text


def _merge_numeric(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _recover_combined_agenda_orgs(fr: pd.DataFrame, agenda: pd.DataFrame):
    """Recover a malformed Agenda org cell only when FR context makes it unambiguous."""
    flags = []
    if fr.empty or agenda.empty:
        return fr, agenda, flags

    fr = fr.copy()
    agenda = agenda.copy()
    if "_fuzzy_match_score" not in agenda.columns:
        agenda["_fuzzy_match_score"] = np.nan
    if "_skip_fuzzy_match" not in agenda.columns:
        agenda["_skip_fuzzy_match"] = False

    fr_pairs = set(zip(fr["_org_key"], fr["_type_key"]))
    agenda_pairs = set(zip(agenda["_org_key"], agenda["_type_key"]))

    for idx, row in agenda.iterrows():
        pair = (row["_org_key"], row["_type_key"])
        if pair in fr_pairs:
            continue

        agenda_key = row["_org_key"]
        if not agenda_key:
            continue

        candidates = fr[
            (fr["_type_key"] == row["_type_key"])
            & ~fr.apply(lambda r: (r["_org_key"], r["_type_key"]) in agenda_pairs, axis=1)
        ].copy()
        candidates = candidates[
            candidates["_org_key"].map(
                lambda key: bool(key) and f" {key} " in f" {agenda_key} "
            )
        ]

        if len(candidates) < 2:
            continue

        agenda_amount = _merge_numeric(row.get("Amount"))
        agenda_status = _merge_status_key(row.get("Committee Status"))

        chosen = None
        if agenda_amount is not None:
            amount_matches = candidates[
                candidates["Amount"].map(
                    lambda value: (
                        (candidate_amount := _merge_numeric(value)) is not None
                        and abs(candidate_amount - agenda_amount) < 0.005
                    )
                )
            ] if "Amount" in candidates.columns else candidates.iloc[0:0]
            if len(amount_matches) == 1:
                chosen = amount_matches.iloc[0]
            elif len(amount_matches) > 1 and agenda_status:
                status_matches = amount_matches[
                    amount_matches["Committee Status"].map(_merge_status_key) == agenda_status
                ] if "Committee Status" in amount_matches.columns else amount_matches.iloc[0:0]
                if len(status_matches) == 1:
                    chosen = status_matches.iloc[0]

        if chosen is None and agenda_status and "Committee Status" in candidates.columns:
            status_matches = candidates[
                candidates["Committee Status"].map(_merge_status_key) == agenda_status
            ]
            if len(status_matches) == 1:
                chosen = status_matches.iloc[0]

        candidate_names = [str(value) for value in candidates["Org Name"].tolist()]
        agenda.at[idx, "_skip_fuzzy_match"] = True
        if chosen is not None:
            agenda.at[idx, "_org_key"] = chosen["_org_key"]
            agenda.at[idx, "_fuzzy_match_score"] = 100.0
            details = (
                f"recovered_match={chosen.get('Org Name')}; "
                f"candidates={' | '.join(candidate_names)}; "
                f"request_type={row.get('Request Type')}"
            )
        else:
            details = (
                f"no automatic match; candidates={' | '.join(candidate_names)}; "
                f"request_type={row.get('Request Type')}"
            )

        flags.append({
            "severity": "warning",
            "code": "POTENTIAL_CLERICAL_ERROR",
            "message": (
                "Potential clerical error in Agenda organization text: "
                f"{row.get('Org Name')}"
            ),
            "source": "Merge",
            "details": details,
        })

    fr["_occ"] = fr.groupby(["_org_key", "_type_key"]).cumcount()
    agenda["_occ"] = agenda.groupby(["_org_key", "_type_key"]).cumcount()
    return fr, agenda, flags


def _align_fuzzy_names(fr: pd.DataFrame, agenda: pd.DataFrame, threshold: float = 93.0):
    flags = []
    if fr.empty or agenda.empty:
        return fr, agenda, flags

    fr = fr.copy()
    agenda = agenda.copy()
    if "_fuzzy_match_score" not in agenda.columns:
        agenda["_fuzzy_match_score"] = np.nan
    fr_pairs = set(zip(fr["_org_key"], fr["_type_key"]))
    agenda_pairs = set(zip(agenda["_org_key"], agenda["_type_key"]))
    fr_counts = fr.groupby(["_org_key", "_type_key"]).size().to_dict()
    agenda_counts = agenda.groupby(["_org_key", "_type_key"]).size().to_dict()

    for idx, row in agenda.iterrows():
        pair = (row["_org_key"], row["_type_key"])
        if bool(row.get("_skip_fuzzy_match", False)):
            continue
        if pair in fr_pairs or agenda_counts.get(pair, 0) != 1:
            continue
        candidates = fr[
            (fr["_type_key"] == row["_type_key"])
            & ~fr.apply(lambda r: (r["_org_key"], r["_type_key"]) in agenda_pairs, axis=1)
        ]
        eligible = []
        for _, candidate in candidates.iterrows():
            candidate_pair = (candidate["_org_key"], candidate["_type_key"])
            if fr_counts.get(candidate_pair, 0) == 1:
                eligible.append(candidate["_org_key"])
        match = unique_fuzzy_match(row["_org_key"], eligible, threshold=threshold, min_margin=2.0)
        if match is None:
            continue

        best_key, score = match
        best = candidates[candidates["_org_key"] == best_key].iloc[0]
        agenda.at[idx, "_org_key"] = best_key
        agenda.at[idx, "_fuzzy_match_score"] = score
        flags.append({
            "severity": "warning",
            "code": "FUZZY_NAME_MATCH",
            "message": f"Matched likely name variant: {row.get('Org Name')} / {best.get('Org Name')}",
            "source": "Merge",
            "details": f"score={score:.1f}; request_type={row.get('Request Type')}",
        })

    fr["_occ"] = fr.groupby(["_org_key", "_type_key"]).cumcount()
    agenda["_occ"] = agenda.groupby(["_org_key", "_type_key"]).cumcount()
    return fr, agenda, flags


def Merge_FR_Agenda(fr_df: pd.DataFrame, agenda_df: pd.DataFrame, meeting_date: str):
    """Match FR and Agenda rows while keeping both documents' values."""
    fr = _add_merge_keys(fr_df)
    agenda = _add_merge_keys(agenda_df)
    fr, agenda, clerical_flags = _recover_combined_agenda_orgs(fr, agenda)
    fr, agenda, fuzzy_flags = _align_fuzzy_names(fr, agenda)
    flags = clerical_flags + fuzzy_flags
    date = pd.Timestamp(meeting_date).strftime("%m/%d/%Y")

    if fr.empty and agenda.empty:
        return pd.DataFrame(columns=MERGED_COLUMNS), flags

    if fr.empty:
        merged = agenda.copy()
        merged["_merge"] = "right_only"
    elif agenda.empty:
        merged = fr.copy()
        merged["_merge"] = "left_only"
    else:
        merged = fr.merge(
            agenda,
            on=["_org_key", "_type_key", "_occ"],
            how="outer",
            suffixes=("_fr", "_agenda"),
            indicator=True,
        )

    rows = []
    for _, row in merged.iterrows():
        side = row["_merge"]
        if side == "both":
            fuzzy_score = row.get("_fuzzy_match_score")
            match_type = "Fuzzy" if pd.notna(fuzzy_score) else "Exact"
            match_score = float(fuzzy_score) if pd.notna(fuzzy_score) else 100.0
        elif side == "left_only":
            match_type, match_score = "FR Only", np.nan
        else:
            match_type, match_score = "Agenda Only", np.nan

        def source_value(name, source):
            if source == "fr" and side == "right_only":
                return np.nan
            if source == "agenda" and side == "left_only":
                return np.nan
            suffixed = f"{name}_{source}"
            if suffixed in row.index:
                return row.get(suffixed, np.nan)
            return row.get(name, np.nan)

        rows.append({
            "Document Match Type": match_type,
            "Document Match Score": match_score,
            "FR Org Name": source_value("Org Name", "fr"),
            "Agenda Org Name": source_value("Org Name", "agenda"),
            "FR Request Type": source_value("Request Type", "fr"),
            "Agenda Request Type": source_value("Request Type", "agenda"),
            "FR Appx.": source_value("Appx.", "fr"),
            "FR Org Type (year)": source_value("Org Type (year)", "fr"),
            "FR Amount Requested": source_value("Amount Requested", "fr"),
            "FR Amount": source_value("Amount", "fr"),
            "Agenda Amount": source_value("Amount", "agenda"),
            "FR Committee Status": source_value("Committee Status", "fr"),
            "Agenda Committee Status": source_value("Committee Status", "agenda"),
            "FR Funding Source": source_value("Funding Source", "fr"),
            "FR Primary Contact": source_value("Primary Contact", "fr"),
            "FR Email Address": source_value("Email Address", "fr"),
            "FR Date": source_value("Date", "fr"),
            "Agenda Date": source_value("Date", "agenda"),
            "Meeting Date": date,
        })

    result = pd.DataFrame(rows, columns=MERGED_COLUMNS)
    order = {
        "contingency": 1,
        "finance rule": 2,
        "space reservation": 3,
        "sponsorship": 4,
        "absa budget appeals": 5,
        "senate bill": 6,
    }
    result["_sort_type"] = result["FR Request Type"].fillna(result["Agenda Request Type"]).map(
        lambda value: order.get(_merge_request_type_key(value), 999)
    )
    result["_sort_org"] = result["FR Org Name"].fillna(result["Agenda Org Name"]).fillna("")
    result = result.sort_values(["_sort_type", "_sort_org"]).drop(columns=["_sort_type", "_sort_org"]).reset_index(drop=True)
    return result, flags
