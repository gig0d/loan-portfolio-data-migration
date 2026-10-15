"""Account for every source record and write a readable migration report."""

import argparse
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from migration.config import load_settings
from migration.extract import LEGACY_FILES
from migration.load import LoadResult, create_database_engine, load_valid_records
from migration.validate import ValidationResult, run_validation

logger = logging.getLogger(__name__)
REPORT_FILENAME = "migration_report.md"


@dataclass(frozen=True)
class TableReconciliation:
    """Keep stage counts and failed accounting checks for one source table."""

    table: str
    read: int
    cleaned: int
    rejected: int
    inserted: int
    already_present: int
    failures: tuple[str, ...]

    @property
    def loaded(self) -> int:
        """Count incoming records inserted or confirmed identical after commit."""
        return self.inserted + self.already_present

    @property
    def passed(self) -> bool:
        """Indicate whether all source-accounting checks passed for this table."""
        return not self.failures


@dataclass(frozen=True)
class ReconciliationResult:
    """Hold per-table outcomes and one primary rejection count per source row."""

    tables: tuple[TableReconciliation, ...]
    rejections_by_rule: tuple[tuple[str, str, int], ...]

    @property
    def passed(self) -> bool:
        """Require every table to pass, even when opposite errors cancel in totals."""
        return all(table.passed for table in self.tables)


def reconcile(validation: ValidationResult, load: LoadResult) -> ReconciliationResult:
    """Compare committed load outcomes with source counts and rejection provenance."""
    expected_tables = set(LEGACY_FILES)
    for counts in (
        validation.transformation.read_counts,
        validation.valid_tables,
        validation.transformation.tables,
        load.inserted_counts,
        load.existing_counts,
    ):
        if set(counts) != expected_tables:
            raise ValueError(
                "Reconciliation requires outcomes for all three target tables."
            )
    rejected = validation.rejected_records
    if not set(rejected["table"]).issubset(expected_tables):
        raise ValueError("Rejected records contain an unknown source table.")
    results = []
    for table in LEGACY_FILES:
        read = validation.transformation.read_counts[table]
        cleaned = len(validation.transformation.tables[table])
        accepted = validation.valid_tables[table]
        table_rejections = rejected.loc[rejected["table"] == table]
        inserted = load.inserted_counts[table]
        existing = load.existing_counts[table]
        counts = (read, cleaned, len(table_rejections), inserted, existing)
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("Reconciliation counts must be nonnegative integers.")
        removed = int(
            (validation.transformation.exact_duplicates["table"] == table).sum()
        )
        accepted_rows = list(accepted["_source_row"])
        rejected_rows = list(table_rejections["_source_row"])
        checks = {
            "read = loaded + rejected": read
            == inserted + existing + len(table_rejections),
            "accepted = inserted + already present": len(accepted)
            == inserted + existing,
            "read = cleaned + exact duplicates removed": read == cleaned + removed,
            "accepted does not exceed cleaned": len(accepted) <= cleaned,
            "each source row has exactly one accepted or rejected outcome": (
                len(accepted_rows + rejected_rows) == read
                and len(set(accepted_rows + rejected_rows)) == read
                and set(accepted_rows + rejected_rows) == set(range(2, read + 2))
            ),
        }
        failures = tuple(label for label, passed in checks.items() if not passed)
        results.append(
            TableReconciliation(
                table,
                read,
                cleaned,
                len(table_rejections),
                inserted,
                existing,
                failures,
            )
        )
    breakdown = tuple(
        (table, rule, int(count))
        for (table, rule), count in rejected.groupby(["table", "rule"], sort=True)
        .size()
        .items()
    )
    return ReconciliationResult(tuple(results), breakdown)


def render_report(result: ReconciliationResult) -> str:
    """Render aggregate counts and failures without source payloads or credentials."""
    status = "PASS" if result.passed else "FAIL"
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Migration reconciliation report",
        "",
        f"Generated at (UTC): {generated_at}",
        "",
        f"**Overall status: {status}**",
        "",
        "Synthetic data only.",
        "",
        "## Record counts",
        "",
        "Check: `read = loaded + rejected` for each table.",
        "",
        "| Table | Read | Cleaned | Rejected | Loaded | Check |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in result.tables:
        check = "PASS" if row.passed else "FAIL"
        lines.append(
            f"| {row.table} | {row.read} | {row.cleaned} | {row.rejected} "
            f"| {row.loaded} | {check} |"
        )
    totals = [
        sum(getattr(row, field) for row in result.tables)
        for field in ("read", "cleaned", "rejected", "loaded")
    ]
    lines.extend(
        [
            "| **Total** | "
            + " | ".join(str(value) for value in totals)
            + f" | **{status}** |",
            "",
            "Cleaned means retained after exact duplicate removal, before validation.",
            "Removed exact duplicates are included in rejected records.",
            "",
            "Loaded means accepted records confirmed after a successful commit:",
            "newly inserted plus already present with identical values. It is not the",
            "database's lifetime total or the number of new inserts alone.",
            "",
            "## Load outcomes",
            "",
            "| Table | Inserted | Already present |",
            "| --- | ---: | ---: |",
        ]
    )
    lines.extend(
        f"| {row.table} | {row.inserted} | {row.already_present} |"
        for row in result.tables
    )
    lines.extend(
        [
            "",
            "## Rejections by primary rule",
            "",
            "Each rejected record contributes once, using its first failed rule.",
            "All failed rules and original payloads remain in `rejected_records.csv`.",
            "",
            "| Table | Rule | Rejected records |",
            "| --- | --- | ---: |",
        ]
    )
    lines.extend(
        f"| {table} | {rule} | {count} |"
        for table, rule, count in result.rejections_by_rule
    )
    if not result.rejections_by_rule:
        lines.append("| All tables | No rejections | 0 |")
    lines.append(f"| **Total** | | **{sum(row.rejected for row in result.tables)}** |")
    lines.extend(["", "## Accounting diagnostics", ""])
    failures = [
        f"- {row.table}: {failure}."
        for row in result.tables
        for failure in row.failures
    ]
    lines.extend(
        failures
        or [
            "All table equations, accepted/load counts, duplicate-removal counts, and",
            "source-row partitions passed. Every source row has exactly one outcome.",
        ]
    )
    lines.extend(
        [
            "",
            "PASS confirms source accounting; deliberately rejected records do not",
            "cause FAIL when they are accounted for. It does not mean every source",
            "record was valid, or certify correctness beyond the implemented rules.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_report(content: str, output_dir: Path) -> Path:
    """Replace the generated report atomically with UTF-8 text."""
    temporary = None
    destination = output_dir / REPORT_FILENAME
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output_dir,
            prefix=".migration_report_",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.replace(destination)
    except OSError as exc:
        raise OSError(f"Could not write migration report to {destination}.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def run_reconciliation(
    input_dir: Path, output_dir: Path, engine: Engine, schema_path: Path
) -> ReconciliationResult:
    """Validate, load, and reconcile one attempt using the same in-memory outcomes."""
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_report(
        "# Migration reconciliation report\n\n**Overall status: FAIL**\n\n"
        f"Attempt started at (UTC): {started_at}\n\n"
        "This attempt has not completed validation, loading, and reconciliation.\n"
        "No successful accounting result is available. Check the terminal logs.\n",
        output_dir,
    )
    validation = run_validation(input_dir, output_dir)
    load = load_valid_records(validation, engine, schema_path)
    result = reconcile(validation, load)
    path = write_report(render_report(result), output_dir)
    logger.info(
        "Reconciliation %s: wrote %s", "PASS" if result.passed else "FAIL", path
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone load-and-reconcile step; return nonzero on FAIL or error."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--schema-path", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    engine = None
    try:
        settings = load_settings()
        logging.getLogger().setLevel(settings.log_level)
        engine = create_database_engine(settings.database_url)
        result = run_reconciliation(
            args.input_dir or settings.legacy_data_dir,
            args.output_dir or settings.output_data_dir,
            engine,
            args.schema_path or settings.schema_path,
        )
    except (ValueError, OSError, SQLAlchemyError) as exc:
        message = (
            "Could not connect to the configured database."
            if isinstance(exc, SQLAlchemyError)
            else str(exc)
        )
        logger.error("Reconciliation failed: %s", message)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
