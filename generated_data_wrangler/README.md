# Employee Data Wrangling

## Project Overview

This repository contains a simple data‑wrangling utility for employee records. The main script **`wrangle_employee.py`** reads a raw CSV file containing basic employee information, enriches the data with derived columns (e.g., tenure, age groups, salary brackets), and writes the transformed dataset back to disk.  The project is deliberately lightweight, making it easy to extend or integrate into larger ETL pipelines.

## Prerequisites

- Python 3.9+ (the code is written using type hints compatible with recent Python versions)
- `pip` for package management

### Installing Dependencies

All required third‑party libraries are listed in `requirements.txt`. Install them with:

```bash
pip install -r requirements.txt
```

The primary dependency is **pandas**, which provides the data‑frame operations used throughout the script.

## Running the Script

The script can be executed directly from the command line.

### Using Default Filenames

```bash
python wrangle_employee.py
```

By default, the script expects an input file named **`employee.csv`** located in the project root and will produce an enriched output file called **`employee_enriched.csv`** in the same directory.

### Specifying Custom Paths

While the current implementation uses the default filenames, the code is structured so that it can be easily extended to accept CLI arguments.  When that extension is added, you will be able to run:

```bash
python wrangle_employee.py --input path/to/employee.csv --output path/to/employee_enriched.csv
```

*Note:* At the moment the script does not parse these arguments; they are shown here as a future‑proof example.

## Running the Test Suite

Unit tests are provided using **pytest**. To execute the full test suite with verbose output, run:

```bash
pytest -v
```

The tests cover typical data‑wrangling scenarios, error handling for missing files, and validation of the enrichment logic.

## Example Input & Output

### Input CSV (`employee.csv`)

| employee_id | first_name | last_name | hire_date  | birth_date | salary | department |
|-------------|------------|-----------|------------|------------|--------|------------|
| 1           | Alice      | Smith     | 2015-06-01 | 1990-04-12 | 72000  | Engineering |
| 2           | Bob        | Jones     | 2018-09-15 | 1985-11-23 | 58000  | Marketing   |
| 3           | Carol      | Lee       | 2020-01-20 | 1992-07-30 | 65000  | Sales       |

### Enriched Output (`employee_enriched.csv`)

| employee_id | first_name | last_name | hire_date  | birth_date | salary | department | tenure_years | age | salary_bracket |
|-------------|------------|-----------|------------|------------|--------|------------|--------------|-----|----------------|
| 1           | Alice      | Smith     | 2015-06-01 | 1990-04-12 | 72000  | Engineering | 9.3          | 34  | 70k‑80k        |
| 2           | Bob        | Jones     | 2018-09-15 | 1985-11-23 | 58000  | Marketing   | 6.0          | 38  | 50k‑70k        |
| 3           | Carol      | Lee       | 2020-01-20 | 1992-07-30 | 65000  | Sales       | 4.6          | 32  | 60k‑70k        |

The enriched columns illustrate typical transformations:
- **`tenure_years`** – calculated as the difference between today and the hire date.
- **`age`** – derived from the birth date.
- **`salary_bracket`** – a categorical bucket based on the raw salary.

---

Feel free to explore the code, add new enrichment steps, or plug the script into your own data pipelines!
