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

- Choose explicit date parsing rules for ambiguous dates.
- Define how probable customer duplicates are reviewed or rejected.
- Assign named validation rules and determine dependent-record handling.
- Define idempotent loading and SQLite/MySQL schema differences.
- Count removed duplicates explicitly so reconciliation accounts for every
  source row and can check `read = loaded + rejected` without losing records.

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

## Planned SQL work (Phase 5)

The following describes future work; `sql/schema.sql` still contains comments
only, and no database is created in Phase 2.

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
