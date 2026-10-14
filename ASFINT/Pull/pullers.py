import pandas as pd
from pathlib import Path


def pull_csv(path, process_type):
    """
    Load .csv inputs.
    - If `path` is a directory: read all *.csv files into {stem: DataFrame}.
    - If `path` is a file: read that file only.
    FR note: if FR expects (df, text), adapt here (e.g., pair with a .txt of same stem).
    """
    p = Path(path)

    if not p.exists():
        raise FileNotFoundError(f"Input path does not exist: {p}")

    out = {}
    if p.is_dir():
        for f in sorted(p.glob("*.csv")):
            df = pd.read_csv(f)
            out[f.stem] = df
    else:
        if p.suffix.lower() != ".csv":
            raise ValueError(f"Expected a .csv file, got: {p.name}")
        df = pd.read_csv(p)
        out[p.stem] = df

    return out

def pull_txt(path, process_type):
    """
    Load .txt inputs.
    - If `path` is a directory: read all *.txt files into {stem: text}.
    - If `path` is a file: read that file only.
    """
    p = Path(path)

    if not p.exists():
        raise FileNotFoundError(f"Input path does not exist: {p}")

    out = {}
    if p.is_dir():
        for f in sorted(p.glob("*.txt")):
            text = f.read_text(encoding="utf-8", errors="ignore")
            out[f.stem] = text
    else:
        if p.suffix.lower() != ".txt":
            raise ValueError(f"Expected a .txt file, got: {p.name}")
        text = p.read_text(encoding="utf-8", errors="ignore")
        out[p.stem] = text

    return out

def pull_fr(path, process_type):
    """
    Load FR inputs as (DataFrame, text) tuples.
    - Pairs .csv files with matching .txt files by stem name
    - If no matching .txt exists, uses empty string as text
    - Returns {stem: (DataFrame, text)}

    IMPORTANT: FR CSVs are read with header=None because:
    - Row 1 is blank/separators
    - Row 2 contains the date (YYYY-MM-DD Finance Committee...)
    - The actual data table headers start later
    """
    p = Path(path)

    if not p.exists():
        raise FileNotFoundError(f"Input path does not exist: {p}")

    out = {}
    if p.is_dir():
        # Find all CSV files
        for csv_file in sorted(p.glob("*.csv")):
            # Read FR CSV with no header (date is in row 2, table headers come later)
            df = pd.read_csv(csv_file, header=None)
            # Look for matching TXT file
            txt_file = csv_file.with_suffix(".txt")
            if txt_file.exists():
                text = txt_file.read_text(encoding="utf-8", errors="ignore")
            else:
                text = ""  # Empty string if no matching txt
            out[csv_file.stem] = (df, text)
    else:
        if p.suffix.lower() != ".csv":
            raise ValueError(f"Expected a .csv file, got: {p.name}")
        # Read FR CSV with no header (date is in row 2, table headers come later)
        df = pd.read_csv(p, header=None)
        # Look for matching TXT file
        txt_file = p.with_suffix(".txt")
        if txt_file.exists():
            text = txt_file.read_text(encoding="utf-8", errors="ignore")
        else:
            text = ""  # Empty string if no matching txt
        out[p.stem] = (df, text)

    return out

def pull_reconcile(path, process_type):
    """
    Load FR and Agenda CSV files for reconciliation.
    - Looks for files matching patterns: '*Cleaned*.csv' (FR) and '*Agenda*.csv' (Agenda)
    - Returns {'fr': fr_df, 'agenda': agenda_df}
    - Raises error if either file type is not found
    """
    p = Path(path)

    if not p.exists():
        raise FileNotFoundError(f"Input path does not exist: {p}")

    if not p.is_dir():
        raise ValueError(f"Reconcile process requires a directory path, got file: {p}")

    # Find FR file (contains "Cleaned" or "clean" in filename, case-insensitive)
    fr_files = [f for f in p.glob("*.csv") if "clean" in f.name.lower() and "agenda" not in f.name.lower()]
    if not fr_files:
        raise FileNotFoundError(f"No FR file found in {p}. Expected file with 'clean' or 'Cleaned' in name.")

    # Find Agenda file (contains "Agenda" in filename)
    agenda_files = list(p.glob("*Agenda*.csv"))
    if not agenda_files:
        raise FileNotFoundError(f"No Agenda file found in {p}. Expected file with 'Agenda' in name.")

    # Use the most recent file if multiple matches
    fr_file = sorted(fr_files, key=lambda x: x.stat().st_mtime)[-1]
    agenda_file = sorted(agenda_files, key=lambda x: x.stat().st_mtime)[-1]

    print(f"[RECONCILE PULL] Using FR file: {fr_file.name}")
    print(f"[RECONCILE PULL] Using Agenda file: {agenda_file.name}")

    # Load the dataframes
    # Try reading with default header first (for new format)
    # If 'Org Name' column is missing, try header=1 (for old format with blank header row)
    fr_df = pd.read_csv(fr_file)
    if 'Org Name' not in fr_df.columns:
        print(f"[RECONCILE PULL] Warning: 'Org Name' not found in header, trying header=1")
        fr_df = pd.read_csv(fr_file, header=1)
    agenda_df = pd.read_csv(agenda_file)

    # Extract FR filename stem (without extension) for use in output naming
    fr_filename = fr_file.stem

    # Return as tuple (fr_df, agenda_df, fr_filename) to pass filename info
    return {'reconcile': (fr_df, agenda_df, fr_filename)}