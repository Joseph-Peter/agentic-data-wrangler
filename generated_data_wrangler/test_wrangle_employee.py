import pandas as pd
import pytest
from pathlib import Path

# Import the functions to be tested
from wrangle_employee import (
    load_data,
    compute_department_stats,
    augment_with_dept_stats,
    main,
)


@pytest.fixture
def sample_df():
    """Return a small DataFrame with two departments and varying salaries."""
    data = {
        "employee_id": [1, 2, 3, 4, 5],
        "department": ["Engineering", "Engineering", "HR", "HR", "HR"],
        "salary": [120000, 130000, 70000, 75000, 80000],
    }
    return pd.DataFrame(data)


def test_compute_department_stats(sample_df):
    """Verify that department statistics are computed correctly."""
    stats = compute_department_stats(sample_df)
    # Expected values per department
    expected = {
        "Engineering": {"dept_max_salary": 130000, "dept_min_salary": 120000},
        "HR": {"dept_max_salary": 80000, "dept_min_salary": 70000},
    }
    # Ensure both departments are present
    assert set(stats["department"]).issuperset(expected.keys())
    # Check each row
    for _, row in stats.iterrows():
        dept = row["department"]
        assert dept in expected
        assert row["dept_max_salary"] == expected[dept]["dept_max_salary"]
        assert row["dept_min_salary"] == expected[dept]["dept_min_salary"]


def test_augment_with_dept_stats(sample_df):
    """Check that merging adds the correct columns and values."""
    stats = compute_department_stats(sample_df)
    enriched = augment_with_dept_stats(sample_df, stats)
    # New columns should exist
    assert "dept_max_salary" in enriched.columns
    assert "dept_min_salary" in enriched.columns
    # Verify values per row
    for _, row in enriched.iterrows():
        if row["department"] == "Engineering":
            assert row["dept_max_salary"] == 130000
            assert row["dept_min_salary"] == 120000
        elif row["department"] == "HR":
            assert row["dept_max_salary"] == 80000
            assert row["dept_min_salary"] == 70000
        else:
            pytest.fail(f"Unexpected department {row['department']}")


def test_end_to_end_flow(sample_df, tmp_path):
    """Write a CSV, run the main pipeline, and validate the output file."""
    # Write the sample DataFrame to a temporary CSV file
    input_csv = tmp_path / "input.csv"
    sample_df.to_csv(input_csv, index=False)

    # Define output path
    output_csv = tmp_path / "output.csv"

    # Execute the pipeline
    main(input_path=str(input_csv), output_path=str(output_csv))

    # Read back the result
    result_df = pd.read_csv(output_csv)

    # Expected columns
    for col in ["dept_max_salary", "dept_min_salary"]:
        assert col in result_df.columns

    # Verify a few rows for correctness
    eng_rows = result_df[result_df["department"] == "Engineering"]
    assert not eng_rows.empty
    assert eng_rows.iloc[0]["dept_max_salary"] == 130000
    assert eng_rows.iloc[0]["dept_min_salary"] == 120000

    hr_rows = result_df[result_df["department"] == "HR"]
    assert not hr_rows.empty
    assert hr_rows.iloc[0]["dept_max_salary"] == 80000
    assert hr_rows.iloc[0]["dept_min_salary"] == 70000
