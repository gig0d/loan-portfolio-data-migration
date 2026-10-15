# Owner's walkthrough: from setup to Phase 6

This is the complete Windows checklist for the project owner. Follow it in order,
one command at a time. Paste commands into **PowerShell**, not a Python file or
the `>>>` Python prompt. Press Enter and wait for each command to finish. If it
fails, stop at that step and use the troubleshooting section.

## Start here: what is already done and what is yours to do

On the current computer, the assistant has prepared Python's `.venv`, installed
dependencies, created the project files, generated data, run the pipeline through
Phase 6, tested it, and pushed the completed phases to your GitHub repository.
Python and Git are installed. You do not need to recreate files, initialize Git
again, create another repository, or repeat an existing commit.

Your role is to verify the setup, practice running the project, inspect results,
review each phase, and write and explain your own learning. Account settings and
portfolio presentation are also your choices.

| Phase | Supplied by the assistant | Your action |
| --- | --- | --- |
| 1: setup | Folders, package, requirements, ignore rules, configuration example, Git remote | Follow steps 1-6; install or create only missing items |
| 2: generation | Reproducible generator and tiny sample | Run step 7 and inspect deliberate defects |
| 3: cleanup | Extraction, conversions, duplicate diagnostics | Run step 8 and inspect cleaned data |
| 4: validation | Named rules, accepted CSVs, rejection report | Run step 9 and read a rejection |
| 5: loading | SQL schema, transactions, repeat-load handling | Follow step 9a; no SQL server is needed for SQLite |
| 6: reconciliation | Record counts, rejection breakdown, PASS/FAIL report | Follow step 9c and explain the accounting equation |
| Checks and GitHub | Tests and phase commits | Verify steps 10-11; commit only your own new changes |
| Portfolio | README and design explanations | Complete step 12 and write your final learning section |
| 7-8 | Still planned | Review the current phase before authorizing the next one |

**Current-computer route:** start at step 1. Use the verification commands; skip
installation and cloning branches when the item already exists.

**Fresh-computer route:** install missing tools in step 2, clone in step 3, then
complete the remaining steps. `.venv`, `.env`, full data, and outputs are local
artifacts and will not arrive from GitHub.

## 1. Open the project root and PowerShell

1. Open VS Code.
2. Select **File > Open Folder** and choose `loan-portfolio-data-migration`, not
   its `docs` or `src` subfolder. On a fresh computer, complete steps 2-3 first.
3. Select **Terminal > New Terminal**.
4. If needed, select **Terminal > Select Default Profile > PowerShell**, then
   create a new terminal.
5. Run:

```powershell
Get-Location
```

The last directory must be `loan-portfolio-data-migration`. Keep this terminal
for the remaining commands. If its prompt is `>>>`, type `exit()` to leave
Python and return to PowerShell.

## 2. Check tools; install only missing ones

On the current computer, run:

```powershell
git --version
.\.venv\Scripts\python.exe --version
```

Expect a Git version and Python 3.11 or newer. The current workspace was tested
with Python 3.13. If both commands work, continue to step 3.

### Git missing: fresh-computer installation

1. Open the official [Git for Windows download](https://git-scm.com/download/win).
2. Download and run the installer for your Windows architecture.
3. Keep the standard defaults, including command-line availability and Git
   Credential Manager.
4. Finish, close and reopen VS Code, and create a new PowerShell terminal.
5. Run `git --version` again; proceed when it prints a version.

### Python missing: fresh-computer installation

1. Open Microsoft Store in Windows.
2. Search for **Python 3.13**, published by **Python Software Foundation**, and
   install that package.
3. Close and reopen VS Code, then open a new PowerShell terminal.
4. Run `python --version`; expect Python 3.13.

This route is covered by the [official Python Windows guide](https://docs.python.org/3.13/using/windows.html#the-microsoft-store-package).
An existing Python 3.11+ installation is supported and need not be replaced.

### VS Code missing: fresh-computer installation

1. Open the [official VS Code download](https://code.visualstudio.com/Download).
2. Download the Windows installer for your architecture and finish installation.
3. Open VS Code and continue to the clone step.

## 3. Check the repository; clone only on a fresh computer

### Existing workspace

Run from the project root:

```powershell
git status --short --branch
git remote -v
git log -3 --oneline
```

Expect `main`, remote `https://github.com/gig0d/loan-portfolio-data-migration.git`,
and the completed phase commits. After a successful push, `main` is synchronized
with `origin/main`. An empty change list means no uncommitted tracked changes;
it does not mean that files are missing.

If Git reports **detected dubious ownership**, the assistant's sandbox account
may own the directory. Confirm `Get-Location` is this trusted repository root,
then trust only its exact path:

```powershell
$portfolioRepoPath = (Get-Location).Path
git config --global --add safe.directory "$portfolioRepoPath"
git status --short --branch
```

Do not use `safe.directory '*'`. This changes your user's Git trust setting for
one directory, not project data or history.

### Fresh computer only

1. Open a PowerShell terminal in VS Code.
2. Choose an existing parent folder for the project and enter its full path when
   the following command asks:

```powershell
$portfolioParent = Read-Host 'Full path of the parent folder for this project'
Set-Location -LiteralPath $portfolioParent
git clone https://github.com/gig0d/loan-portfolio-data-migration.git
Set-Location loan-portfolio-data-migration
```

3. Select **File > Open Folder** in VS Code and open the newly cloned folder.
4. Create a new terminal and run `Get-Location` again.

The GitHub repository already exists. Cloning downloads the code and configures
Git; do not create a second empty repository or run `git init` in the clone.
If the destination already exists, open that project instead of cloning over it.

## 4. Prepare `.venv`, dependencies, and VS Code's interpreter

Check for the local interpreter:

```powershell
Test-Path .venv/Scripts/python.exe
```

If `True`, keep the existing environment. If `False`, create it:

```powershell
python -m venv .venv
```

If your installed Python uses the launcher instead, use `py -3 -m venv .venv`
and check that its version is at least 3.11.

Install or update the project's dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Expect installation to finish without errors and `No broken requirements found.`
`Requirement already satisfied` is normal. Repeat the install after changes to
`requirements.txt`, including Phase 4's `pycountry` dependency.

Select the same interpreter in VS Code:

1. Press **Ctrl+Shift+X**, search for **Python** published by **Microsoft**, and
   install the extension if missing.
2. Press **Ctrl+Shift+P** and run **Python: Select Interpreter**.
3. Select `.venv`. If absent, choose **Enter interpreter path > Find**, then
   select this repository's `.venv/Scripts/python.exe`.

See the [official VS Code environment instructions](https://code.visualstudio.com/docs/python/environments#select-an-environment).
The commands here call `.venv` directly; activation and execution-policy changes
are unnecessary.

## 5. Prepare local configuration once

Copy the example only if `.env` is absent:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Open `.env` in VS Code. Keep SQLite and the supplied default paths and seed.
Leave MySQL's example commented out. The loader and reconciliation command read
`.env`; generation, transformation, and standalone validation still use explicit
arguments. There are no SQLite database
credentials to obtain. Existing `.env` settings are preserved by the command.
New optional keys such as `SCHEMA_PATH` have defaults, so do not overwrite your
existing `.env`. Shell environment values override values in this file.

Check ignored paths:

```powershell
git check-ignore .env .venv/pyvenv.cfg data/legacy/customers_legacy.csv data/output/rejected_records.csv
```

Expect all four paths. Patterns can be checked even before every output exists.
Do not force-add ignored files. `.env.example` remains tracked.

## 6. Check Git identity and GitHub access

Open [your repository](https://github.com/gig0d/loan-portfolio-data-migration) in a
browser and sign in. The **Code** tab should show `main` and the project files.

Inspect the author configuration:

```powershell
git config user.name
git config user.email
```

Choose a display name and an email verified in your GitHub account, or its
private `noreply` address. To find that address, open your profile menu >
**Settings > Emails**. The assistant uses the email you explicitly selected for
new commits; existing history is not rewritten automatically.

Only to set or change these choices, run and answer the prompts:

```powershell
$portfolioAuthorName = Read-Host 'Name to display on new commits'
$portfolioAuthorEmail = Read-Host 'GitHub verified or noreply email for new commits'
git config --local user.name "$portfolioAuthorName"
git config --local user.email "$portfolioAuthorEmail"
```

These settings affect this repository. Author emails are stored in Git history;
choose `noreply` for a private address. See [GitHub's commit email guide](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address).

If a future push opens Git Credential Manager's browser sign-in, authenticate as
the repository owner and return to PowerShell. Keep credentials out of project
files. See [GitHub's Git setup guide](https://docs.github.com/en/get-started/git-basics/set-up-git).

## 7. Phase 2: generate and inspect synthetic data

Run:

```powershell
.\.venv\Scripts\python.exe -m migration.generate_legacy_data --output-dir data/legacy --customers 1000 --seed 42
```

Expect 1,100 customers, 1,000 loans, and 2,000 payments. Customers include 50
exact and 50 probable duplicate rows.

In VS Code, expand `data > legacy` and open each CSV. Find blank fields, different
date formats, currency symbols, inconsistent statuses, and invalid emails. These
are deliberate defects: observe them rather than editing them away. The script
creates all data; you do not need to invent records manually.

The command replaces only three named exports. The same size, seed, and pinned
Faker version reproduce them. Full exports are ignored. The tiny tracked sample
already exists in `data/legacy/sample/` and needs no regeneration here.

## 8. Phase 3: transform and inspect diagnostics

Run:

```powershell
.\.venv\Scripts\python.exe -m migration.transform --input-dir data/legacy --output-dir data/output
```

Open `data > output` and inspect:

| File | Data rows | Meaning |
| --- | ---: | --- |
| `customers_cleaned.csv` | 1,050 | Standardized customers, including probable duplicates |
| `loans_cleaned.csv` | 1,000 | Plain amounts and normalized statuses |
| `payments_cleaned.csv` | 2,000 | Standardized fields; business violations still remain |
| `exact_duplicates.csv` | 50 | Removed raw rows retained for accounting |
| `probable_duplicates.csv` | 100 | Both members of each shared-email pair |
| `transformation_issues.csv` | 0 | Header only: generated dates/amounts are parseable |

`_source_row` is the source record number, counting the header as 1. Customers
also have `_probable_duplicate`. Missing fields are blank in CSV. Zero conversion
issues does not mean business validation passed.

For a terminal preview:

```powershell
Get-Content data/output/customers_cleaned.csv -TotalCount 6
Get-Content data/output/probable_duplicates.csv -TotalCount 6
```

This replaces six inspection files and preserves the sources.

## 9. Phase 4: validate and understand rejections

Run:

```powershell
.\.venv\Scripts\python.exe -m migration.validate --input-dir data/legacy --output-dir data/output
```

It rereads sources and transforms them in memory, not from edited cleaned CSVs.
Step 8 is helpful for inspection but not a technical prerequisite.

| Table | Read | Accepted | Rejected |
| --- | ---: | ---: | ---: |
| Customers | 1,100 | 650 | 450 |
| Loans | 1,000 | 500 | 500 |
| Payments | 2,000 | 950 | 1,050 |

Open `customers_valid.csv`, `loans_valid.csv`, `payments_valid.csv`, and
`rejected_records.csv`. The latter contains 2,000 rows: one per rejected source
record. Accepted loans have accepted customers; accepted payments have accepted
loans.

Read the first rejection clearly in PowerShell:

```powershell
$portfolioRejection = Import-Csv data/output/rejected_records.csv | Select-Object -First 1
$portfolioRejection | Format-List table, _source_row, record_id, rule, reason
$portfolioRejection.violations | ConvertFrom-Json | Format-Table rule, field, reason -Wrap
$portfolioRejection.record_json | ConvertFrom-Json | Format-List
```

The first default rejection is a customer requiring duplicate review. `rule` and
`reason` describe the first failure; `violations` lists all failures and
`record_json` preserves original fields. Look up rules in
[VALIDATION_RULES.md](VALIDATION_RULES.md).

Interpret rather than manually repairing this fixture. A rejected customer can
also reject its loans and payments because an accepted parent is required.
Ambiguous customer groups are held for review without selecting one identity.
Exact duplicates receive explicit rejection outcomes too.

This replaces four validation outputs. This command alone does not create or
populate a database; the next step does. Expected counts apply to 1,000 base
customers, seed 42, and the documented rules.

## 9a. Phase 5: create, load, and inspect SQLite

Use the default SQLite route first. Everything below runs in VS Code's integrated
PowerShell terminal. No database server, Workbench, or SQL extension is needed.

1. Open the project root using step 1. Open `.env` in the editor and confirm:

   ```dotenv
   DATABASE_URL=sqlite:///data/output/loan_portfolio.db
   LEGACY_DATA_DIR=data/legacy
   OUTPUT_DATA_DIR=data/output
   ```

   Save the file. Keep passwords out of committed files. No new SQL statements
   need to be typed manually to create these tables.
2. If you have not generated the default source files, run step 7. Existing
   default exports can be reused. Then run:

   ```powershell
   .\.venv\Scripts\python.exe -m migration.load
   ```

   It reads, cleans, and validates the CSVs; replaces the accepted/rejected CSV
   outputs; creates the schema; and loads accepted records. It does not read
   manually edited accepted CSVs. With a fresh database, expect:

   ```text
   INFO: Loaded customers: 650 inserted; 0 already present; 650 accepted confirmed
   INFO: Loaded loans: 500 inserted; 0 already present; 500 accepted confirmed
   INFO: Loaded payments: 950 inserted; 0 already present; 950 accepted confirmed
   ```

   On this computer, the assistant already ran the load. Your first personal run
   can therefore show zero inserted and those counts already present.
3. Verify that the database exists and stays excluded from Git:

   ```powershell
   Test-Path data/output/loan_portfolio.db
   git check-ignore data/output/loan_portfolio.db
   ```

   Expect `True` and the database path. A `.db` file is the database, not a text
   document to edit. You do not need to commit or upload it.
4. Repeat exactly the load command from item 2. Expect **0 inserted** for all
   three tables, with 650/500/950 already present. Repeating a snapshot does not
   create duplicates. A changed existing ID instead stops the load and rolls
   back all new rows; earlier committed records remain intact.
5. Inspect actual SQL counts using Python's bundled SQLite shell. This shell
   requires Python 3.12+; the current computer has Python 3.13.14:

   ```powershell
   .\.venv\Scripts\python.exe -m sqlite3 data/output/loan_portfolio.db
   ```

   At the `sqlite>` prompt, enter these statements one at a time, including `;`:

   ```sql
   SELECT 'customers' AS table_name, COUNT(*) AS rows FROM customers
   UNION ALL SELECT 'loans', COUNT(*) FROM loans
   UNION ALL SELECT 'payments', COUNT(*) FROM payments;
   SELECT loan_id, customer_id, principal_amount_cents, status FROM loans LIMIT 5;
   SELECT COUNT(*) FROM loans l LEFT JOIN customers c
     ON l.customer_id = c.customer_id WHERE c.customer_id IS NULL;
   SELECT COUNT(*) FROM payments p LEFT JOIN loans l
     ON p.loan_id = l.loan_id WHERE l.loan_id IS NULL;
   PRAGMA foreign_key_check;
   ```

   Expect counts 650/500/950, both orphan queries equal to zero, and no rows from
   `foreign_key_check`. For example, 120050 cents means 1200.50 monetary units.
   These checks do not replace the Phase 6 reconciliation report.
6. Enter `.quit` without a semicolon to return to PowerShell. Run step 10.

For Python 3.11, use this equivalent read-only inspection in PowerShell instead
of the SQLite shell. It also honors a configured database path:

```powershell
@'
import logging
from sqlalchemy import text
from migration.config import load_settings
from migration.load import create_database_engine
logging.basicConfig(level=logging.INFO, format="%(message)s")
engine = create_database_engine(load_settings().database_url)
try:
    with engine.connect() as connection:
        for table in ("customers", "loans", "payments"):
            count = connection.scalar(text(f"SELECT COUNT(*) FROM {table}"))
            logging.info("%s: %s", table, count)
finally:
    engine.dispose()
'@ | .\.venv\Scripts\python.exe -
```

**Different synthetic snapshot:** choose a new unused SQLite filename in `.env`,
such as `DATABASE_URL=sqlite:///data/output/loan_portfolio_seed7.db`, before
loading data generated with a different seed. A fresh schema is created there.
Do not delete your previous database to resolve an unexplained conflict.

## 9b. Optional MySQL route: separate server required

Skip this section for the default project. MySQL is selectable by URL, but the
live integration test has not been run in this workspace. SQLite is sufficient
for the current phase. Follow this route only to try the optional backend.

1. If a local MySQL server is absent, download the **MySQL Community Server 8.4
   Windows MSI** from [official downloads](https://dev.mysql.com/downloads/mysql/).
   Run the MSI and MySQL Configurator. Choose a development-machine
   configuration, TCP port 3306, and a local Windows service; keep the default
   service account. Set your own root password and finish initialization. This
   route needs no router or Workbench installation. See the
   [official Windows installation guide](https://dev.mysql.com/doc/refman/8.4/en/windows-installation.html).
2. Back in PowerShell, open the MySQL client. For a standard 8.4 installation:

   ```powershell
   $portfolioMysqlClient = 'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe'
   Test-Path $portfolioMysqlClient
   & $portfolioMysqlClient -u root -p
   ```

   If the path is absent, use the actual installation directory chosen in item 1.
   Enter the root password at its prompt, not as a command argument.
3. At `mysql>`, run the following SQL one statement at a time. Replace the
   password placeholder with a new local password of your choosing. Keep that
   password only in your local configuration, never in a tracked file:

   ```sql
   CREATE DATABASE loan_portfolio CHARACTER SET utf8mb4;
   CREATE USER 'portfolio_loader'@'localhost' IDENTIFIED BY 'REPLACE_WITH_LOCAL_PASSWORD';
   GRANT SELECT, INSERT, CREATE, REFERENCES ON loan_portfolio.*
     TO 'portfolio_loader'@'localhost';
   SELECT VERSION();
   ```

   Use a new empty database. The loader does not create databases or users and
   refuses versions below 8.0.16 and MariaDB. The account grants follow
   [MySQL's account documentation](https://dev.mysql.com/doc/refman/8.4/en/grant.html).
   Enter `exit` to return to PowerShell.
4. Install the current requirements using step 4, including PyMySQL's RSA extra.
   In VS Code, edit only your ignored `.env`:

   ```dotenv
   DATABASE_URL=mysql+pymysql://portfolio_loader:REPLACE_WITH_LOCAL_PASSWORD@localhost:3306/loan_portfolio
   ```

   Substitute your local password. URL-reserved characters in it must be percent
   encoded (for example `@` becomes `%40`, `#` becomes `%23`, `%` becomes `%25`).
   Save and run `git check-ignore .env`. Do not share its contents.
5. Run `.\.venv\Scripts\python.exe -m migration.load` twice in PowerShell.
   Expect the same first/repeat counts as SQLite. In the MySQL client, verify:

   ```sql
   USE loan_portfolio;
   SELECT COUNT(*) FROM customers;
   SELECT COUNT(*) FROM loans;
   SELECT COUNT(*) FROM payments;
   SHOW CREATE TABLE loans;
   ```

   The loader selects InnoDB, requires existing tables to use it, and creates
   positive-money/status checks. A load failure rolls back new rows, but MySQL
   schema DDL is separate and can leave empty tables.
6. To verify the opt-in test, create a **different empty disposable database**
   in the root client, then grant the same scoped rights:

   ```sql
   CREATE DATABASE loan_portfolio_test CHARACTER SET utf8mb4;
   GRANT SELECT, INSERT, CREATE, REFERENCES ON loan_portfolio_test.*
     TO 'portfolio_loader'@'localhost';
   ```

   In PowerShell, enter its URL at a hidden prompt so the password is not typed
   into command history. Use the same encoded password and database
   `loan_portfolio_test`:

   ```powershell
   $portfolioTestSecret = Read-Host 'MySQL test URL for the empty disposable database' -AsSecureString
   $env:TEST_MYSQL_DATABASE_URL = [System.Net.NetworkCredential]::new('', $portfolioTestSecret).Password
   .\.venv\Scripts\python.exe -m pytest tests/test_load.py -k mysql
   Remove-Item Env:TEST_MYSQL_DATABASE_URL
   Remove-Variable portfolioTestSecret
   ```

   The test creates tables, verifies rollback, and loads a 20-customer synthetic
   fixture twice. It intentionally leaves the successful fixture in this
   disposable database. A second test run needs a new empty test database; it
   will not delete external data for you.
7. To return to SQLite, restore its `DATABASE_URL` in `.env`. Do not commit
   database files, passwords, or test connection URLs.

## 9c. Phase 6: generate and read the reconciliation report

Use the default SQLite route. No new software, SQL statements, dependency
installation, or schema changes are required for this phase.

1. In VS Code, open a PowerShell terminal at the project root (step 1). Keep the
   default configuration from step 5. Reuse the default source files from step 7.
   You do not need to regenerate them or run the earlier commands separately.
2. Run the standalone command:

   ```powershell
   .\.venv\Scripts\python.exe -m migration.reconcile
   ```

   It reads, cleans, validates, and loads the source data before writing the
   reconciliation report. The database may already contain this snapshot; that
   is expected. The final log should say `Reconciliation PASS: wrote ...`.
3. Immediately check the exit code:

   ```powershell
   $LASTEXITCODE
   ```

   Expect `0`. A value of `1` means an accounting FAIL or an execution error;
   read the terminal error and report rather than continuing as if it passed.
4. Open `data/output/migration_report.md` in VS Code's Explorer. Press
   **Ctrl+Shift+V** to preview Markdown. Alternatively, read it in PowerShell:

   ```powershell
   Get-Content data/output/migration_report.md
   ```

   Expect **Overall status: PASS** and the default counts:

   | Table | Read | Cleaned | Rejected | Loaded | Check |
   | --- | ---: | ---: | ---: | ---: | --- |
   | customers | 1,100 | 1,050 | 450 | 650 | PASS |
   | loans | 1,000 | 1,000 | 500 | 500 | PASS |
   | payments | 2,000 | 2,000 | 1,050 | 950 | PASS |
   | Total | 4,100 | 4,050 | 2,000 | 2,100 | PASS |

5. Practice explaining the customer equation: `1100 = 650 + 450`. The 50 exact
   duplicates removed before validation are included among the 450 rejections.
   `Cleaned` is an intermediate count and is not added to the other outcomes.
   PASS means every source record is accounted for; it does not mean the messy
   source contained no invalid data.
6. Read **Load outcomes**. On this computer, expect 0 inserted and 650/500/950
   already present. These add up to the loaded counts. Repeat the command from
   item 2, check `$LASTEXITCODE`, and reopen the report. Totals should remain the
   same, with no duplicated database records.
7. Read **Rejections by primary rule**. Its counts sum to 2,000, with one rule
   counted per rejected source record. The first rule is used for this summary;
   `rejected_records.csv` retains all violations and original source fields.
   Look up any rule in [VALIDATION_RULES.md](VALIDATION_RULES.md).
8. Verify that the generated report stays local:

   ```powershell
   git check-ignore data/output/migration_report.md
   git status --short --branch
   ```

   Expect the report path to be ignored and no report staged for Git. This
   command replaces the local report on each attempt; no new commit is needed
   just to regenerate it. Then run step 10.

The report begins as a dated incomplete FAIL before validation/loading starts,
so a failed load does not leave an earlier PASS pretending to describe it. Only
a completed attempt publishes the full accounting result. Check the timestamp
and terminal log: configuration errors before the attempt starts, or an
unwritable output directory, can prevent replacing an old file. Report output
is separate from the data transaction; if writing fails after a successful
commit, correct the path/permissions and repeat the command to regenerate it.

Optional explicit paths use the same command, for example:

```powershell
.\.venv\Scripts\python.exe -m migration.reconcile --input-dir data/legacy --output-dir data/output --schema-path sql/schema.sql
```

The output directory selects reports and validation CSVs, while `DATABASE_URL`
still selects the database. Do not change the seed against an existing database
snapshot; follow the separate-database guidance in step 9a instead.

## 10. Run checks and verify that outputs stay local

Run one at a time:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
git status --short --branch
```

Expect passing tests, no Ruff errors, no dependency conflicts, and no generated
reports in Git's change list. Repeating generation only replaces ignored files;
it requires no new commit. If a check fails, provide its exact command and error
text to the assistant.

## 11. Check a phase commit; commit only your own new work

The assistant commits and pushes completed phases when requested. Verify with:

```powershell
git log -3 --oneline
git status --short --branch
```

Refresh GitHub's **Code** tab on branch `main` and open its commit history. Expect
the same latest commit and changed files. This phase's message is
`feat: add migration reconciliation report`.

If you later make a real README change, such as writing your learning section,
use this separate workflow:

```powershell
git diff -- README.md
git add -- README.md
git diff --cached --check
git diff --cached
git commit -m "docs: add personal project reflections"
git push origin main
git status --short --branch
```

Review the staged diff. For other changes, stage their actual paths and choose
an English Conventional Commits message describing them. Run step 10 before
committing code changes. `Nothing to commit` means your files match the latest
commit. If GitHub has newer work and rejects push, ask for help integrating it;
do not force-push.

## 12. Complete the owner tasks for a portfolio

1. On GitHub, check the repository's visibility. Public visibility is your
   choice. If making a private repository public, use **Settings > General >
   Danger Zone > Change repository visibility** and review its confirmation.
2. On **Code**, select the gear beside **About**. Add this description:
   `Synthetic loan portfolio migration with data quality rules and auditable rejections.`
3. Add topics `python`, `data-migration`, `data-quality`, `pandas`, `sqlalchemy`,
   `sqlite`, and `portfolio`, then save. See [GitHub's topics guide](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics).
4. On your profile, select **Customize your pins**, select this repository, and
   save. See [GitHub's pinning guide](https://docs.github.com/en/account-and-profile/how-tos/profile-customization/pinning-items-to-your-profile).
5. Read `docs/DESIGN.md`. Practice explaining how an invalid customer can also
   prevent acceptance of its loan and payments.
6. At the end of Phase 8, write **What I learned** in the README yourself, in
   English, describing what you actually understand. That section stays a TODO
   until you write it.
7. Add the repository link to your CV and applications. During development,
   describe it as in progress and mention the completed phase.

## Your tasks in the remaining phases

| Phase | Assistant work | Your task afterward |
| --- | --- | --- |
| 7 | Unified CLI | Practice the simpler `generate`, `run`, and `report` commands |
| 8 | Final diagram, documentation, report example | Write your learning section and review the GitHub presentation |

Phase 5's default SQL steps are available in step 9a. The optional MySQL route
is step 9b. Phase 6's report steps are in step 9c. The optional MySQL route is
not needed to complete the remaining phases with SQLite.

## Troubleshooting: stop at the failing step

| Symptom | Next action |
| --- | --- |
| Prompt is `>>>` | Run `exit()` and return to PowerShell |
| `.venv` interpreter is missing | Check `Get-Location`, open the project root, then complete step 4 |
| Fresh computer has no `python` | Complete step 2 and reopen VS Code |
| `ModuleNotFoundError`, including `pycountry` | Install `requirements.txt` using step 4, then retry |
| Missing legacy export | Run step 7 and repeat step 8 or 9 |
| Unexpected headers or malformed CSV | Regenerate with step 7; do not silently drop fields |
| Cannot write output | Close applications holding the CSV open; check the directory is writable |
| Changed existing ID during load | Review the snapshot; use a new database filename for a different seed |
| Database load failed | Check the configured database, schema, permissions, and constraints; no new portfolio rows were committed |
| Reconciliation reports FAIL | Read Accounting diagnostics and the terminal log; do not treat an incomplete run as a migration PASS |
| Cannot write migration report | Check the output directory and close applications locking the file; a completed database commit remains committed, so repeat after fixing output access |
| `No module named sqlite3.__main__` | Python 3.11 lacks the bundled shell; use the inspection snippet in step 9a |
| Dubious ownership | Use the exact-directory trust instructions in step 3 |
| Nothing to commit | Check status; no commit is needed for unchanged files |
| Push authentication fails | Use the credential-manager sign-in as the owner; provide persistent error text |
| Tests or Ruff fail | Stop and provide the failing command and error text |
