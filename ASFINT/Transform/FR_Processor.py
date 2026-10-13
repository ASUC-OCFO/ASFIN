from __future__ import annotations

from datetime import datetime
import re
from typing import Optional

import numpy as np
import pandas as pd


FR_COLUMNS = [
    "Appx.",
    "Org Name",
    "Request Type",
    "Org Type (year)",
    "Amount Requested",
    "Amount",
    "Committee Status",
    "Funding Source",
    "Primary Contact",
    "Email Address",
    "Date",
]


def _sanitize_date_for_filename(date_str: str) -> str:
    return str(date_str).replace("/", "-").replace("\\", "-").replace(":", "-")


def _compact(value: object) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def FR_Embedded_Date(df: pd.DataFrame) -> Optional[str]:
    """Return the first date embedded in an FR sheet as YYYY-MM-DD."""
    if df is None or df.empty:
        return None
    patterns = [
        (r"\b(\d{1,2}/\d{1,2}/20\d{2})\b", "%m/%d/%Y"),
        (r"\b(20\d{2}-\d{1,2}-\d{1,2})\b", "%Y-%m-%d"),
    ]
    for i in range(min(12, len(df))):
        for value in df.iloc[i].astype(str).tolist():
            for pattern, source_format in patterns:
                match = re.search(pattern, value)
                if not match:
                    continue
                try:
                    return datetime.strptime(match.group(1), source_format).strftime("%Y-%m-%d")
                except ValueError:
                    pass
    return None


def _extract_date(df: pd.DataFrame, txt: str, date_format: str) -> str:
    embedded = FR_Embedded_Date(df)
    if embedded:
        return datetime.strptime(embedded, "%Y-%m-%d").strftime(date_format)
    if txt:
        for pattern, source_format in [
            (r"\b(\d{1,2}/\d{1,2}/20\d{2})\b", "%m/%d/%Y"),
            (r"\b(20\d{2}-\d{1,2}-\d{1,2})\b", "%Y-%m-%d"),
        ]:
            match = re.search(pattern, str(txt))
            if match:
                try:
                    return datetime.strptime(match.group(1), source_format).strftime(date_format)
                except ValueError:
                    pass
    return "undated"


def _header_rows(df: pd.DataFrame) -> list[int]:
    rows: list[int] = []
    for i in range(len(df)):
        values = {_compact(x).lower() for x in df.iloc[i].tolist()}
        if {"org name", "request type"}.issubset(values) and any(v.startswith("appx") for v in values):
            rows.append(i)
    return rows


def _column_index(header: pd.Series, *names: str) -> Optional[int]:
    wanted = {_compact(name).lower() for name in names}
    for idx, value in enumerate(header.tolist()):
        if _compact(value).lower() in wanted:
            return idx
    return None


def _email_column_index(header: pd.Series, block: pd.DataFrame) -> Optional[int]:
    explicit = _column_index(header, "Email Address", "Email")
    if explicit is not None:
        return explicit

    best_idx = None
    best_count = 0
    for idx in range(block.shape[1]):
        count = block.iloc[:, idx].astype(str).str.contains(r"@", regex=True, na=False).sum()
        if count > best_count:
            best_idx = idx
            best_count = int(count)
    return best_idx if best_count > 0 else None


def _valid_data_rows(block: pd.DataFrame) -> pd.DataFrame:
    if block.empty:
        return block
    appx = block["Appx."].map(_compact)
    org = block["Org Name"].map(_compact)
    mask = appx.ne("") & ~appx.str.lower().str.startswith("appx") & org.ne("") & org.str.lower().ne("nan")
    return block.loc[mask].reset_index(drop=True)


def _normalize_request_type(value: object) -> object:
    text = _compact(value)
    low = text.lower()
    if not text:
        return np.nan
    if "contingency" in low:
        return "Contingency"
    if "finance" in low or "rule waiver" in low:
        return "Finance Rule"
    if "space" in low:
        return "Space Reservation"
    if "sponsor" in low:
        return "Sponsorship"
    if "senate" in low or low.startswith("sr "):
        return "Senate Bill"
    return text


def _normalize_status(value: object) -> object:
    text = _compact(value)
    if not text:
        return np.nan
    low = text.lower().replace("indefinetly", "indefinitely")
    if "table" in low and "indefinit" in low:
        return "Tabled Indefinitely"
    if "table" in low:
        return "Tabled"
    if "partial" in low and "approv" in low:
        return "Partially Approved"
    if "recommend" in low and "approv" in low:
        return "Recommended for approval"
    if "approv" in low:
        return "Approved"
    if "denied" in low or "deny" in low:
        return "Denied"
    if "forward" in low and "senate" in low:
        return "Forwarded to Senate"
    return text


def _numeric(value: object) -> Optional[float]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    text = _compact(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _request_table(df: pd.DataFrame, header_idx: int, end_idx: int) -> pd.DataFrame:
    header = df.iloc[header_idx]
    rows = df.iloc[header_idx + 1 : end_idx].copy()

    indices = {
        "Appx.": _column_index(header, "Appx.", "Appx"),
        "Org Name": _column_index(header, "Org Name"),
        "Request Type": _column_index(header, "Request Type"),
        "Org Type (year)": _column_index(header, "Org Type (year)", "Org Type"),
        "Amount Requested": _column_index(header, "Amount Requested"),
        "Funding Source": _column_index(header, "Funding Source"),
        "Primary Contact": _column_index(header, "Primary Contact"),
        "Email Address": _email_column_index(header, rows),
    }

    out = pd.DataFrame(index=rows.index)
    for name, idx in indices.items():
        out[name] = rows.iloc[:, idx] if idx is not None else np.nan

    out = _valid_data_rows(out)
    out["Request Type"] = out["Request Type"].map(_normalize_request_type)
    return out


def _decision_table(df: pd.DataFrame, header_idx: int) -> pd.DataFrame:
    header = df.iloc[header_idx]
    rows = df.iloc[header_idx + 1 :].copy()

    appx_idx = _column_index(header, "Appx.", "Appx")
    org_idx = _column_index(header, "Org Name")
    status_idx = _column_index(header, "Committee Status")
    amount_idx = _column_index(header, "Amount", "Amount Approved")

    # Some historical sheets store the decision in a column labeled for the
    # request amount or granted amount.
    combined_idx = None
    if status_idx is None and amount_idx is None:
        combined_idx = _column_index(header, "Amount Requested", "Amount Granted")

    out = pd.DataFrame(index=rows.index)
    out["Appx."] = rows.iloc[:, appx_idx] if appx_idx is not None else np.nan
    out["Decision Org Name"] = rows.iloc[:, org_idx] if org_idx is not None else np.nan
    out["Committee Status"] = rows.iloc[:, status_idx] if status_idx is not None else np.nan
    out["Amount"] = rows.iloc[:, amount_idx] if amount_idx is not None else np.nan
    out["_combined_decision"] = rows.iloc[:, combined_idx] if combined_idx is not None else np.nan

    # Remove repeated headings and blank trailing rows before matching decisions.
    appx = out["Appx."].map(_compact)
    org = out["Decision Org Name"].map(_compact)
    mask = appx.ne("") & ~appx.str.lower().str.startswith("appx") & org.ne("") & org.str.lower().ne("nan")
    return out.loc[mask].reset_index(drop=True)


def _apply_decisions(requests: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    out = requests.copy()
    out["Amount"] = pd.Series(np.nan, index=out.index, dtype="float64")
    out["Committee Status"] = pd.Series(pd.NA, index=out.index, dtype="object")
    if decisions.empty:
        return out

    decision_by_appx = decisions.drop_duplicates(subset=["Appx."], keep="first").set_index("Appx.")
    for idx, row in out.iterrows():
        appx = row.get("Appx.")
        if appx not in decision_by_appx.index:
            continue
        decision = decision_by_appx.loc[appx]

        status = _normalize_status(decision.get("Committee Status"))
        amount = _numeric(decision.get("Amount"))
        combined = decision.get("_combined_decision")

        if pd.isna(status) and combined is not None and not pd.isna(combined):
            numeric = _numeric(combined)
            if numeric is not None:
                amount = numeric
                requested = _numeric(row.get("Amount Requested"))
                if requested is not None and abs(requested - numeric) <= 0.005:
                    status = "Approved"
                else:
                    status = "Partially Approved"
            else:
                status = _normalize_status(combined)

        out.at[idx, "Amount"] = amount if amount is not None else np.nan
        out.at[idx, "Committee Status"] = status

    return out


def FR_Helper(df):
    """Backward-compatible helper returning the raw sheet and detected tables."""
    if df is None or df.empty:
        return df, None, None
    headers = _header_rows(df)
    if not headers:
        return df, None, None
    requests = _request_table(df, headers[0], headers[1] if len(headers) > 1 else len(df))
    decisions = _decision_table(df, headers[1]) if len(headers) > 1 else None
    return df, requests, decisions


def FR_ProcessorV2(
    df: pd.DataFrame,
    txt: str = "",
    date_format: str = "%m/%d/%Y",
    original_filename: str | None = None,
):
    """Clean one Finance Resolution spreadsheet.

    Finance Resolution sheets contain a request table followed by a committee
    decision table. Historical sheets occasionally repeat the request header for
    the decision table, so table boundaries are identified by repeated Appx/Org
    Name/Request Type headers instead of relying on the decision column name.
    """
    extracted_date = _extract_date(df, txt, date_format)

    if original_filename:
        base_name = re.sub(r"\.(csv|xlsx|xls|gsheet)$", "", original_filename, flags=re.I)
        base_name = re.sub(r"\([\d]+\)", "", base_name).strip()
        base_name = base_name.replace(" - Sheet1", "").replace("- Sheet1", "").strip()
        out_name = f"{base_name} Cleaned"
    else:
        out_name = f"FR_clean_{_sanitize_date_for_filename(extracted_date)}"

    if df is None or df.empty:
        return {out_name: pd.DataFrame(columns=FR_COLUMNS)}

    headers = _header_rows(df)
    if not headers:
        return {out_name: pd.DataFrame(columns=FR_COLUMNS)}

    requests = _request_table(df, headers[0], headers[1] if len(headers) > 1 else len(df))
    decisions = _decision_table(df, headers[1]) if len(headers) > 1 else pd.DataFrame()
    cleaned = _apply_decisions(requests, decisions)
    cleaned["Date"] = extracted_date

    for col in FR_COLUMNS:
        if col not in cleaned.columns:
            cleaned[col] = np.nan
    cleaned = cleaned[FR_COLUMNS].reset_index(drop=True)
    return {out_name: cleaned}


def FR_ProcessorV2_Multi(
    dfs_with_txt: list,
    date_format: str = "%Y-%m-%d",
    original_filenames: list | None = None,
):
    all_results = {}
    for idx, pair in enumerate(dfs_with_txt):
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise ValueError(f"Expected (df, txt) tuple at index {idx}, got {type(pair)}")
        df, txt = pair
        if not isinstance(df, pd.DataFrame):
            raise ValueError(f"Expected pandas DataFrame at index {idx}, got {type(df)}")
        original = original_filenames[idx] if original_filenames and idx < len(original_filenames) else None
        all_results.update(FR_ProcessorV2(df, txt, date_format, original_filename=original))
    return all_results
