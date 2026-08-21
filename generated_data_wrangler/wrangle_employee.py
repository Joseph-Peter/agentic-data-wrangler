import pandas as pd
from pathlib import Path

# Module-level constants for file paths relative to this script's directory
EMPLOYEE_CSV = Path(__file__).with_name('employee.csv')
OUTPUT_CSV = Path(__file__).with_name('employee_enhanced.csv')

# ---------------------------------------------------------------------------
# New public API (required by the task description)
# ---------------------------------------------------------------------------

def load_data(csv_path: str | Path) -> pd.DataFrame:
    """Load employee data from a CSV file.

    Parameters
    ----------
    csv_path : str | Path
        Path to the CSV file containing employee records.

    Returns
    -------
    pd.DataFrame
        DataFrame with the employee data.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    pd.errors.EmptyDataError
        If the file is empty.
    pd.errors.ParserError
        If the CSV cannot be parsed.
    KeyError
        If required columns are missing.
    """
    path = Path(csv_path)
    try:
        df = pd.read_csv(path)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Employee data file not found at '{path}'.") from exc
    except pd.errors.EmptyDataError as exc:
        raise pd.errors.EmptyDataError(f"Employee data file '{path}' is empty.") from exc
    except pd.errors.ParserError as exc:
        raise pd.errors.ParserError(f"Failed to parse employee data file '{path}'.") from exc

    # Validate required columns
    required = {"employee_id", "department", "salary"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(
            f"Input DataFrame is missing required column(s): {', '.join(sorted(missing))}"
        )
    return df


def compute_department_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per‑department salary statistics.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame that must contain ``department`` and ``salary`` columns.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns ``department``, ``dept_max_salary`` and
        ``dept_min_salary``.
    """
    # Ensure required columns are present
    required = {"department", "salary"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(
            f"Input DataFrame is missing required column(s): {', '.join(sorted(missing))}"
        )
    try:
        agg = (
            df.groupby("department", as_index=False)["salary"]
            .agg(dept_max_salary="max", dept_min_salary="min")
        )
    except Exception as exc:
        raise RuntimeError("Failed to compute department statistics") from exc
    return agg


def augment_with_dept_stats(df: pd.DataFrame, dept_stats: pd.DataFrame) -> pd.DataFrame:
    """Merge employee records with department statistics.

    Parameters
    ----------
    df : pd.DataFrame
        Original employee DataFrame.
    dept_stats : pd.DataFrame
        DataFrame returned by :func:`compute_department_stats`.

    Returns
    -------
    pd.DataFrame
        Enriched DataFrame containing the original columns plus the department
        statistics.
    """
    if "department" not in df.columns:
        raise KeyError("Employee DataFrame must contain a 'department' column.")
    if "department" not in dept_stats.columns:
        raise KeyError("Department stats DataFrame must contain a 'department' column.")
    try:
        merged = pd.merge(df, dept_stats, on="department", how="left")
    except Exception as exc:
        raise RuntimeError("Failed to merge employee data with department statistics") from exc
    return merged


def save_data(df: pd.DataFrame, out_path: str | Path) -> None:
    """Save a DataFrame to a CSV file.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to be saved.
    out_path : str | Path
        Destination file path.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("save_data expects a pandas DataFrame as input")
    path = Path(out_path)
    try:
        df.to_csv(path, index=False)
    except OSError as exc:
        raise OSError(f"Failed to write data to '{path}'.") from exc


def main(input_path: str = "employee.csv", output_path: str = "employee_enriched.csv") -> None:
    """Execute the full employee data wrangling pipeline.

    Parameters
    ----------
    input_path : str, optional
        Path to the source CSV file. Defaults to ``'employee.csv'``.
    output_path : str, optional
        Path where the enriched CSV will be written. Defaults to
        ``'employee_enriched.csv'``.
    """
    df = load_data(input_path)
    dept_stats = compute_department_stats(df)
    enriched_df = augment_with_dept_stats(df, dept_stats)
    save_data(enriched_df, output_path)


# ---------------------------------------------------------------------------
# Backward‑compatible wrappers (retain original public functions)
# ---------------------------------------------------------------------------

def load_employee_data() -> pd.DataFrame:
    """Legacy wrapper that loads data from the module‑level ``EMPLOYEE_CSV``.
    """
    return load_data(EMPLOYEE_CSV)


def compute_department_salary_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Legacy wrapper preserving original function name.
    """
    return compute_department_stats(df)


def augment_with_salary_stats(df: pd.DataFrame, stats_df: pd.DataFrame) -> pd.DataFrame:
    """Legacy wrapper preserving original function name.
    """
    return augment_with_dept_stats(df, stats_df)


def save_enhanced_data(df: pd.DataFrame) -> None:
    """Legacy wrapper that saves to the module‑level ``OUTPUT_CSV``.
    """
    save_data(df, OUTPUT_CSV)


if __name__ == "__main__":
    main()
