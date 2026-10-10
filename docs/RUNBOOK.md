# Execution runbook

This guide covers the implemented steps through Phase 3. All data is synthetic.
Commands below use Windows PowerShell and run from the repository root.
No SQL server, database GUI, or separate PowerShell window is needed yet.

## 1. Open a PowerShell terminal in VS Code

1. Open the `loan-portfolio-data-migration` folder in VS Code.
2. Select **Terminal > New Terminal**.
3. If the terminal is not PowerShell, select **Terminal > Select Default
   Profile > PowerShell**, then open a new terminal.
4. Check the working directory:

```powershell
Get-Location
```

The final directory name must be `loan-portfolio-data-migration`, not `src` or
`docs`. Opening the repository folder in a new VS Code window and creating a
new terminal is an easy way to return to its root.

## 2. Prepare Python on a fresh clone

The existing workspace already has `.venv`. On a fresh clone, install Python
3.11 or newer with its official Windows installer and enable its PATH option.
Restart VS Code after installation, then run:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If the Python launcher is available instead, replace the environment-creation
command with `py -3 -m venv .venv`. Check that its Python version is at least
3.11. No activation command or execution-policy change is required.

For an existing environment, check its interpreter and install the dependencies
if needed:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`.env` loading is not used by the current standalone commands. All directory
arguments below are explicit; there are no database credentials to configure.

## 3. Generate the default synthetic source files

```powershell
.\.venv\Scripts\python.exe -m migration.generate_legacy_data --output-dir data/legacy --customers 1000 --seed 42
```

Expect log messages for 1,100 customer rows, 1,000 loan rows, and 2,000 payment
rows. The customer total includes 50 exact and 50 probable duplicate rows.
This command replaces only the three named legacy exports in `data/legacy/`.

## 4. Extract and transform

```powershell
.\.venv\Scripts\python.exe -m migration.transform --input-dir data/legacy --output-dir data/output
```

Expect logs showing the source and cleaned counts, 50 removed exact duplicates,
100 customer rows flagged for review, and zero conversion issues.

| Output in `data/output/` | Expected data rows | Meaning |
| --- | ---: | --- |
| `customers_cleaned.csv` | 1,050 | Standardized customers, including probable duplicates |
| `loans_cleaned.csv` | 1,000 | Standardized loans, including invalid business records |
| `payments_cleaned.csv` | 2,000 | Standardized payments, including negative or early payments |
| `exact_duplicates.csv` | 50 | Removed raw source rows with table and record position |
| `probable_duplicates.csv` | 100 | Both members of each of 50 shared-email groups |
| `transformation_issues.csv` | 0 | Unsupported conversions; header only for this dataset |

The cleaned files are **not approved for database loading**. The generator's
dates and amounts are parseable even where emails, countries, references, or
payment dates violate business rules. Validation is the next phase.

This command replaces the six named outputs. Other files are left alone.

## 5. Inspect the results

In the VS Code Explorer, open the files under `data/output/`. You can also view
the first lines from PowerShell:

```powershell
Get-Content data/output/customers_cleaned.csv -TotalCount 6
Get-Content data/output/loans_cleaned.csv -TotalCount 6
Get-Content data/output/exact_duplicates.csv -TotalCount 6
Get-Content data/output/probable_duplicates.csv -TotalCount 6
Get-Content data/output/transformation_issues.csv -TotalCount 6
```

Verify that dates use `YYYY-MM-DD`, amounts have no dollar symbols or thousands
commas, statuses are lowercase, and `_source_row` is present. The customer file
also includes `_probable_duplicate`. CSVs write missing values as empty fields.

Count customer rows, excluding the header:

```powershell
Import-Csv data/output/customers_cleaned.csv | Measure-Object
```

The `Count` should be `1050`. The diagnostic files retain records so no removed
exact duplicate silently disappears from the source accounting.

## 6. Run the checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

All tests and both Ruff checks must pass before considering the phase complete.
Generated outputs are ignored by Git; they do not need to be committed.

## Common errors

- **Interpreter not found:** check `Get-Location` and complete step 2. If the
  `python` command is unavailable, restart VS Code after Python installation or
  try the installed `py` launcher.
- **Missing legacy export:** run step 3, then repeat step 4.
- **Unexpected CSV columns:** compare the file header with the tiny sample in
  `data/legacy/sample/`. Regenerate the synthetic files for this walkthrough.
- **Malformed CSV:** inspect the named file for extra fields or unclosed quotes.
  The extraction step stops rather than silently discarding fields.
- **Cannot write output:** check the destination and close any application
  holding the CSVs open. A destination must be a directory, not an existing file.

## SQL in a later phase

Phase 5 will create tables from `sql/schema.sql` through Python and SQLAlchemy.
The default SQLite database will be a local file, so a separate database server
or SQL application will not be required. Exact execution and inspection steps
will be added with that implementation. Optional MySQL server setup, database
creation, connection configuration, and backend checks will get their own steps
when implemented; there is no MySQL setup to perform for Phase 3.
