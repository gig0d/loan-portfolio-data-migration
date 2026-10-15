# Design decisions

## Phase 1: setup

- **Synthetic data only.** A script will generate every customer, loan, and
  payment. Generated exports are ignored; only a tiny synthetic sample will be
  tracked under `data/legacy/sample/` after Phase 2.
- **A small Python package with a `src` layout.** Each migration step has one
  module. Minimal `pyproject.toml` metadata supports editable installation,
  making imports work consistently in tests and future CLI usage.
- **One dependency file.** `requirements.txt` includes runtime and development
  dependencies for an easy portfolio setup. Core libraries have compatible
  version ranges; this is not a fully pinned lockfile. Faker is not pinned yet.
  Phase 2 must document the Faker version used for reproducibility because a
  seed alone does not guarantee identical output across library versions.
- **SQLite by default.** It lets a reviewer run the project without a database
  server. `DATABASE_URL` will select the SQLAlchemy database connection;
  PyMySQL provides the optional MySQL driver. Cross-database schema behavior
  will be designed and tested in Phase 5.
- **Environment-based configuration.** `.env.example` is a safe configuration
  contract, with no live credentials. The future configuration module will
  resolve relative paths from the repository root and validate settings.
- **Ignored local artifacts.** Virtual environments, local `.env` files,
  generated exports, reports, and databases stay out of Git. `.gitkeep` files
  preserve empty directories. The sample directory is the only CSV exception.
- **Setup checks now, business-rule tests later.** Import smoke tests verify
  that the installed package exposes every planned module. Transformation,
  validation, loading, and reconciliation tests will accompany those phases.
- **No behavior in placeholders.** Modules contain only docstrings, and
  `sql/schema.sql` contains only comments. Configuration, CLI commands, and
  database creation are deliberately deferred until their authorized phases.

## Topics to resolve in later phases

- Run the optional live MySQL integration test on a disposable server database.
- Use the explicit duplicate rejection outcomes in the final reconciliation
  check so it can account for every source record (implemented in Phase 6).

## Phase 2: synthetic legacy generator

- **Explicit output path.** `generate_legacy_data(output_dir, customer_count,
  seed)` and the standalone module command require a destination. The default
  size is 1,000 base customers and the default seed is 42. Environment loading
  and the unified CLI remain deferred; this command accepts explicit arguments.
- **Local random generators and fixed dates.** A separate `random.Random`
  instance and a locally seeded Faker instance avoid shared random state.
  Birth dates start from 1960-01-01, and loan dates from 2020-01-01, with bounded
  random offsets. No dates depend on the machine clock.
- **Pinned Faker version.** `Faker==40.43.0` is the version used for the sample.
  Repeatability assumes the same version, seed, and size. UTF-8 CSVs with fixed
  LF line endings avoid operating-system newline differences. Other dependency
  ranges remain as established in Phase 1.
- **Safe synthetic identities.** Faker supplies invented names. Email addresses
  use numbered identifiers at `example.com`, never Faker's random email domains.
  IDs use `C`, `L`, and `P` prefixes. Generated people have no intended connection
  to real individuals.
- **Simple relationships.** Each base customer receives one loan and each loan
  two payments. Every 20-customer block adds one exact duplicate customer row
  and one probable duplicate with a new ID, shared email, and altered casing or
  spelling. The size parameter counts base customers, not duplicate rows.
- **Controlled defects.** Fixed positions in each block receive blank fields,
  invalid emails, `ZZ` country codes, whitespace, or orphan customer references.
  Other fields cycle through the three requested date formats, five status
  spellings, and plain versus currency-formatted amounts. Selected payments
  are negative or precede the loan start. At least 20 base customers cover every
  defect category; 21 also includes both casing and spelling duplicate variants.
  Small exports intentionally contain fewer categories.
- **Exact money generation.** Integer cents converted through `Decimal` keep
  generated amounts at two decimal places without binary floating-point noise.
  CSV fields remain raw text for the transformation phase.
- **Standard-library CSV writing.** `csv.DictWriter` keeps the generation step
  small and preserves intentional blanks and exact text. Pandas will handle the
  extraction and transformation work in Phase 3.
- **Repeatable replacement.** Re-running overwrites the three named exports,
  without modifying other files in the destination. Invalid sizes fail before
  directory creation. Filesystem errors include the destination in the message.
- **Small tracked sample.** `data/legacy/sample/` contains exports generated with
  10 base customers and seed 42. Full default exports remain ignored by Git.
- **Meaningful checks.** Tests compare repeated CSV bytes, verify size and seed
  behavior, check the intentional defects and relationships, and exercise invalid
  sizes, filesystem errors, and the standalone command.

## SQL plan recorded before Phase 5

The following was the plan during Phase 4, when no database was created.
Phase 5 decisions and implementation details are recorded below.

| Table | Source fields | Planned relationship |
| --- | --- | --- |
| `customers` | `customer_id`, `full_name`, `email`, `country_code`, `date_of_birth` | One customer can have many loans |
| `loans` | `loan_id`, `customer_id`, `principal_amount`, `start_date`, `status` | `customer_id` references `customers` |
| `payments` | `payment_id`, `loan_id`, `amount`, `payment_date` | `loan_id` references `loans` |

1. Choose normalized column types, required fields, and exact money storage.
   SQLite and MySQL differ in type enforcement, so money must not rely on
   imprecise floating-point storage.
2. Define primary keys, foreign keys, `NOT NULL`, suitable `CHECK` constraints,
   and indexes for the relationships. Set the allowed normalized statuses.
   Decide whether email uniqueness is appropriate after defining duplicate
   handling; an email match alone is not enough to merge people automatically.
3. Implement the schema in `sql/schema.sql` and test its execution through
   SQLAlchemy. Enable foreign-key enforcement for SQLite connections. Resolve
   dialect differences explicitly rather than assuming a URL change is enough.
4. Load validated customers, then loans, then payments in one transaction.
   A failure must roll back the load. Python validation should explain bad data
   before database constraints provide a final integrity check.
5. Define idempotency using stable IDs and a clear policy for repeated or changed
   records. Count actual load outcomes for reconciliation rather than silently
   ignoring database errors.
6. Test constraints, rollback, and running the same load twice. Test MySQL
   separately before claiming the optional backend works.

Named email, country, duplicate, and cross-table date rules belong to the Python
validation phase. SQL constraints complement these rules and preserve relational
integrity; they do not replace rejected-record explanations.

## Phase 3: extraction and transformation

- **Text-first extraction.** Pandas reads every source field as text, preserving
  leading zeros, whitespace, blank fields, and literal values such as `NA`.
  Expected headers are checked. Missing files, incompatible headers, malformed
  CSVs, and decoding errors stop the step with a helpful file-specific message.
  Blank records are retained; excess fields must not be silently truncated.
- **Source provenance.** `_source_row` numbers CSV records from 2, counting the
  header as record 1. It is a record position, not a physical line number for
  CSVs with multiline quoted fields. It survives cleaning and duplicate removal.
- **Explicit dates.** `YYYY-MM-DD` is ISO, slash-separated `DD/MM/YYYY` is day
  first, and two-digit-first hyphen-separated `MM-DD-YYYY` is month first.
  For example, `03/04/2024` means April 3 and `03-04-2024` means March 4.
  Unsupported formats and impossible dates are diagnosed, never guessed.
- **Conservative money parsing.** Supported plain or dollar-formatted amounts
  become `Decimal` values with two decimal places. Commas must form valid
  thousands groups. Extra decimal places, other currencies, exponent notation,
  and non-finite tokens are not silently rounded or interpreted. Negative
  amounts remain negative for the later validation rules.
- **Simple casing rules.** Whitespace is collapsed, blank text becomes `None`,
  names use title case, emails use lowercase, and IDs and country codes use
  uppercase. `ACTIVE`, `active`, and `Act.` map to `active`; `closed` and
  `CLOSED` map to `closed`. Unknown statuses remain visible in lowercase.
  Title case is a display convention for this synthetic demo, not a reliable
  spelling correction for real names.
- **Exact duplicates before normalization.** Only source rows identical across
  all payload columns are removed, keeping the first occurrence. Provenance
  does not participate in the comparison. Removed rows retain their raw payload
  in `exact_duplicates.csv`. Rows sharing an ID but different source values stay
  in the cleaned data for validation; transformation does not resolve conflicts.
- **Probable duplicates require review.** Different normalized customer IDs
  sharing a nonempty normalized email containing `@` are flagged in
  `probable_duplicates.csv` and `_probable_duplicate`. Names may differ in
  spelling. Blank or placeholder invalid emails do not group customers. This
  signal is not email validation, an identity proof, or automatic merging.
  It deliberately does not attempt fuzzy matching of every name pair.
- **Conversion issues do not erase bad data.** Failed date or amount conversions
  keep the original raw token and record table, source row, field, value, and
  reason in `transformation_issues.csv`. Successfully converted dates and money
  use Python `date` and `Decimal`; missing values use `None`. Invalid conversion
  tokens remain strings and must be rejected before loading in Phase 4.
- **Accounting remains explicit.** Each table satisfies `read = cleaned + exact
  duplicates removed` at this stage. Flagged customers and conversion issues
  remain part of the cleaned count. Phase 4 must classify removed duplicate
  records explicitly so the final `read = loaded + rejected` check can account
  for all source records. Diagnostics are not final rejection reports.
- **Separate inspection outputs.** A standalone command writes the three
  cleaned CSVs and three diagnostic CSVs to an explicit output directory,
  including headers for empty diagnostics. It never alters the source exports.
  The full migration CLI and database loading remain deferred.
- **Repeatable walkthrough.** `docs/RUNBOOK.md` lists exact PowerShell commands,
  expected default counts, inspection steps, and common errors. SQLite will
  not require a separate database application; MySQL setup instructions will be
  added when that backend is implemented and tested.

## Phase 4: validation and rejected-record reporting

- **Named, explicit rules.** Small public customer, loan, and payment validators
  return `Violation` objects with a code, field, and human-readable reason.
  `docs/VALIDATION_RULES.md` describes the 13 rules. Every source business field
  is required in this demo; provenance and duplicate flags are metadata.
- **Local ISO country lookup.** `pycountry==24.6.1` supplies the ISO 3166-1
  alpha-2 catalog, avoiding a hand-maintained country list or an online service.
  Valid countries outside the generator's five-code subset also pass. This is
  an added data dependency, not a validation framework. See the
  [library documentation](https://github.com/pycountry/pycountry#countries-iso-3166-1).
- **Pragmatic field checks.** Email checks cover basic syntax, not mailbox
  ownership or full RFC compliance. Dates must have converted to Python `date`.
  Money must be finite `Decimal` at no more than cent precision and strictly
  positive. Canonical loan statuses are `active` and `closed`.
- **No arbitrary identity choice.** All conflicting rows sharing a normalized
  primary ID are rejected. Every member of a probable shared-email customer
  group is held for review. The project does not select a winner or merge
  people automatically. This conservative policy sacrifices acceptance counts
  in exchange for explainable identity handling.
- **Dependency order.** Customers are validated first. Loans require accepted
  customers, and payments require accepted loans. Missing or rejected parents
  receive explicit reference-rule failures. Payment dates are compared only
  against accepted loans with valid start dates.
- **One outcome per source record.** One rejected CSV row contains its first
  failure in `rule` and `reason`, plus every failure in JSON `violations`.
  The first failure follows deterministic check order: missing required fields,
  conflicting ID, then entity-specific field and relationship checks. There is
  no hidden severity ranking. Multiple failed rules do not multiply row counts.
- **Original payloads remain auditable.** `record_json` comes from the raw
  extracted row, not the title-cased or parsed data. The table and `_source_row`
  identify it even when its primary ID is blank or conflicting. Exact duplicates
  removed during transformation receive `VR013_EXACT_DUPLICATE`, so none vanish
  from the rejection accounting.
- **Typed data stays in memory.** The standalone validation command starts from
  legacy files and reuses extraction/transformation; it does not reload the
  inspection CSVs and lose `date`/`Decimal` types. It returns `ValidationResult`
  for the future loader and writes three accepted CSVs plus rejected records.
- **Acceptance is not loading.** The stage accounts for `read = accepted +
  rejected`, with source-row tests checking disjoint outcomes and full coverage.
  No SQL is executed yet. The final loaded counts, named-rule breakdown, and
  reconciliation report remain Phase 6 work.
- **Owner instructions from the beginning.** The rewritten runbook separates
  current-workspace checks from fresh-machine setup, then covers configuration,
  interpreter selection, generation, cleanup, validation, checks, commits,
  GitHub author settings, and personal portfolio tasks. Account changes remain
  the owner's choices. Project documentation remains in English.

## Phase 5: relational schema and transactional loading

- **One SQL schema, reflected by SQLAlchemy Core.** The loader executes the
  trusted checkout's simple DDL file and reflects its columns; there is no ORM
  or second Python table definition. The script contains three CREATE TABLE
  statements, without procedures or semicolons inside values. Primary keys and
  NOT NULL protect identity and required fields. Unique customer emails enforce
  the conservative shared-email policy established in Phase 4. Composite unique
  indexes beginning with the parent ID support relationship lookups on both
  databases; their uniqueness is already implied by each child primary key.
- **Exact money in integer cents.** `principal_amount` and `amount` remain
  Decimal during cleaning/validation; the database stores their integer-cent
  equivalents with an explicit 9,000,000,000,000,000-cent maximum below BIGINT's
  limit. The loader refuses rounding, overflow, or oversized text. These storage
  failures stop the transaction rather than inventing a new rejection rule.
  SQLite type affinity is weaker than MySQL typing; application conversion
  guarantees integer cents on this load path.
- **Environment configuration now serves the loader.** `.env` is read without
  changing process variables; shell values win. Relative configured data,
  database, and schema paths resolve from the checkout, not the working directory.
  Standalone generation/cleanup/validation retain their explicit arguments until
  Phase 7. Safe defaults let an existing `.env` omit newly added `SCHEMA_PATH`.
  Connection URLs and driver exceptions are not printed with credentials.
- **SQLite integrity and transactions are explicit.** Every connection enables
  foreign keys before a transaction. SQLAlchemy emits BEGIN explicitly, avoiding
  dependence on Python sqlite3's legacy transaction behavior. See the
  [SQLAlchemy SQLite documentation](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#foreign-key-support).
- **Schema creation precedes the data transaction.** All new customers, loans,
  and payments load in a single `engine.begin()` block, in dependency order.
  Any exception rolls back all new rows, preserving previously committed data.
  Empty tables can remain after failure: MySQL CREATE TABLE can commit implicitly.
  See [MySQL implicit commits](https://dev.mysql.com/doc/refman/8.4/en/implicit-commit.html).
  Existing schemas are not upgraded; this portfolio targets fresh databases.
- **Identical IDs are confirmed, changed IDs fail.** Every incoming business
  column is compared with its existing record. Matching rows are counted as
  already present; new rows are inserted; conflicting values stop the load.
  There is no INSERT IGNORE, automatic overwrite, or deletion of earlier rows.
  Selecting existing rows is easy to explain at portfolio scale; a large
  production migration would query keys in batches instead.
- **Per-run outcomes support future reconciliation.** `LoadResult` separates
  inserted and already-present records. `loaded_counts` is their sum for the
  current accepted source set, not the database's lifetime total. Counts are
  returned/logged only after commit. Phase 6 will combine these outcomes with
  source and rejection counts; no reconciliation report is implemented here.
- **MySQL has explicit prerequisites and an honest test boundary.** The URL
  selects PyMySQL, tables use InnoDB/utf8mb4, and versions before 8.0.16 or MariaDB
  are refused. That minimum is needed for enforced
  [MySQL CHECK constraints](https://dev.mysql.com/doc/refman/8.0/en/create-table-check-constraints.html).
  PyMySQL's RSA extra supports modern password authentication. MySQL is optional
  and has not been verified against a live server here; an opt-in integration
  test checks rollback and repeat loads using an empty disposable database.
- **Meaningful load checks.** SQLite tests exercise keys, required fields,
  foreign keys, unique emails, positive amounts, status constraints, exact cents,
  changed-ID rollback after new parent inserts, child-failure rollback, repeat
  loading, empty accepted sets, configuration precedence, and command errors.

## Phase 6: source reconciliation report

- **Use one attempt's typed outcomes.** `run_reconciliation` reuses validation
  and the committed `LoadResult`, then writes `migration_report.md`. The
  standalone module performs validation/loading itself, so its counts cannot
  come from stale inspection CSVs or an unrelated database snapshot. The
  unified CLI is still deferred to Phase 7.
- **Reconcile each table, not just totals.** The main equation is `read = loaded
  + rejected`. Cleaned rows are retained after exact duplicate removal and still
  include records later rejected. Removed duplicates count in rejected records.
  The check also compares accepted versus loaded counts, read versus cleaned
  plus removed duplicates, and the complete source-row partition. Each original
  record position must appear once across accepted/rejected outcomes. Opposite
  errors in two tables cannot cancel into an overall PASS.
- **Loaded includes confirmed existing records.** Reports show inserted and
  already-present counts separately, then add them for the current run's loaded
  count. Repeated runs can pass with zero inserts. Existing database rows outside
  the current source snapshot are not counted. This is source reconciliation,
  not a database inventory or an independent post-commit audit under concurrent
  database changes.
- **Primary-rule counts avoid double-counting.** The rejection breakdown groups
  the existing `rule` column by table. A row with several failures contributes
  once, while the full `violations` JSON remains in `rejected_records.csv`.
  Reports contain counts and rule codes, without raw source payloads, local
  connection URLs, or credentials.
- **PASS means accounting completeness.** Deliberately rejected rows do not
  cause FAIL when accounted for. FAIL can indicate an incomplete attempt or
  inconsistent outcomes. It is not a claim that all accepted data is correct
  beyond the implemented rules. Commands return 0 on PASS and 1 on FAIL/error.
- **Make incomplete attempts visible.** Once configuration and the engine are
  prepared, the command replaces the previous report with a dated incomplete
  FAIL before validation or loading. A successful commit and completed checks
  produce the final report. UTF-8 text is written to a temporary file in the same
  directory, then atomically replaced, preventing partially written reports.
  Configuration/startup failures before this step cannot update the old report;
  the timestamp and terminal exit code identify the attempt. A report-writing
  failure after commit cannot roll back that committed data; repeat the command
  after fixing the output path to confirm existing rows and regenerate it.
- **Stay local and reproducible in scope.** Reports use the configured output
  directory and remain ignored by Git. Each report includes a runtime UTC
  timestamp; counts are reproducible for the same synthetic snapshot and rules,
  while report bytes can differ by time and first-versus-repeat load outcomes.
- **Exercise failure paths as well as PASS.** Tests run the default 1,000-customer
  snapshot through SQLite twice, check known counts, detect missing outcomes,
  cancelling table errors, duplicated provenance, and missing duplicate counts,
  and cover empty/all-rejected inputs, invalid counters, report replacement,
  filesystem errors, failed-load markers, and standalone command exit codes.

## Phase 7: unified CLI and end-to-end checks

- **A small argparse entry point.** `python -m migration.cli` exposes `generate`,
  `run`, and `report`, with command-specific help. It works with the existing
  editable installation and adds no framework or console-script installation.
  Existing standalone modules remain available for learning individual stages.
- **Reuse the tested pipeline.** `generate` calls the existing synthetic
  generator; `run` calls `run_reconciliation`, which validates, transactionally
  loads, and reports using one attempt's outcomes. It does not duplicate rules
  or reload inspection CSVs. Run outputs are the accepted CSVs, rejection CSV,
  and Markdown report; optional transformation inspection exports still use
  the standalone transform command.
- **Explicit configuration precedence.** Command flags override shell variables,
  then `.env`, then defaults. Overrides are passed to the existing configuration
  loader without mutating the process environment. `CUSTOMER_COUNT` must be a
  positive integer and `RANDOM_SEED` an integer. Settings are validated before
  execution; help and argument-usage errors do not need configuration loading.
  The older standalone generator retains its fixed argument defaults.
- **Conventional path behavior.** Relative command-line paths resolve from the
  caller's working directory; paths in configuration resolve from the checkout.
  Generation's output directory overrides `LEGACY_DATA_DIR`, while run/report
  output directories override `OUTPUT_DATA_DIR`. The database remains selected
  by `DATABASE_URL`; credentials are not command-line options or log output.
- **Report is a read-only view of the saved attempt.** It reads the generated
  Markdown file and its single recognized PASS/FAIL status. It does not connect
  to the database, refresh counts, or alter files. Missing or unrecognized reports
  receive a helpful error directing the user to `run`. Its timestamp still
  matters: displaying a saved PASS does not verify a changed source snapshot.
- **Separate report data from operational logs.** Logs use logging on standard
  error. Requested report content goes to standard output with `sys.stdout.write`,
  without print statements; it remains visible at any log level and can be
  redirected independently. Help and malformed arguments use argparse's normal
  output. Exit codes are 0 for success/PASS, 1 for FAIL/operational errors, and 2
  for usage errors. A saved FAIL is displayed and returns 1.
- **Test real process boundaries.** New tests launch the module from a different
  working directory with isolated synthetic inputs and temporary SQLite files.
  They check generation bytes, persisted counts, rejections, repeat loading,
  source preservation, flag/environment precedence, and report reads with an
  unreachable database URL. Failure tests exercise changed-snapshot rollback,
  inconsistent accounting, absent reports/inputs, malformed saved statuses,
  usage errors, and credential redaction. Earlier transformation and named-rule
  unit tests remain part of the full suite.
