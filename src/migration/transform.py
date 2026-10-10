"""Standardize legacy fields and record duplicates and conversion issues."""

import argparse
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from migration.extract import LEGACY_FILES, extract_legacy_data

logger = logging.getLogger(__name__)

ISSUE_COLUMNS = ("table", "_source_row", "field", "raw_value", "reason")
PROBABLE_COLUMNS = (
    "_source_row",
    "customer_id",
    "full_name",
    "email",
    "date_of_birth",
    "reason",
)


@dataclass
class TransformationResult:
    """Keep cleaned tables and every removed or flagged source record auditable."""

    tables: dict[str, pd.DataFrame]
    read_counts: dict[str, int]
    exact_duplicates: pd.DataFrame
    probable_duplicates: pd.DataFrame
    transformation_issues: pd.DataFrame


def normalize_text(value: str | None) -> str | None:
    """Strip and collapse whitespace, returning None for an empty field."""
    if value is None:
        return None
    return " ".join(value.split()) or None


def normalize_identifier(value: str | None) -> str | None:
    """Normalize synthetic identifiers and country codes to uppercase."""
    text = normalize_text(value)
    return text.upper() if text else None


def normalize_name(value: str | None) -> str | None:
    """Apply simple title casing to display names after whitespace cleanup."""
    text = normalize_text(value)
    return text.title() if text else None


def normalize_email(value: str | None) -> str | None:
    """Lowercase legacy email text without claiming that it is valid."""
    text = normalize_text(value)
    return text.lower() if text else None


def normalize_status(value: str | None) -> str | None:
    """Map known status aliases and retain unknown statuses for validation."""
    text = normalize_text(value)
    if not text:
        return None
    text = text.lower()
    return {"active": "active", "act.": "active", "closed": "closed"}.get(text, text)


def normalize_date(value: str | None) -> date | None:
    """Parse the three legacy date formats with explicit separator rules."""
    text = normalize_text(value)
    if not text:
        return None
    formats = (
        (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
        (r"\d{2}/\d{2}/\d{4}", "%d/%m/%Y"),
        (r"\d{2}-\d{2}-\d{4}", "%m-%d-%Y"),
    )
    for pattern, date_format in formats:
        if re.fullmatch(pattern, text):
            try:
                return datetime.strptime(text, date_format).date()
            except ValueError as exc:
                raise ValueError(f"Invalid calendar date: {text}") from exc
    raise ValueError(f"Unsupported date format: {text}")


def normalize_amount(value: str | None) -> Decimal | None:
    """Parse dollar-formatted or plain amounts without rounding extra precision."""
    text = normalize_text(value)
    if not text:
        return None
    number = "-" + text[2:] if text.startswith("-$") else text.removeprefix("$")
    if not re.fullmatch(r"-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?", number):
        raise ValueError(f"Unsupported amount format: {text}")
    try:
        return Decimal(number.replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(
            f"Amount cannot be represented at cent precision: {text}"
        ) from exc


COLUMN_NORMALIZERS: dict[str, Callable[[str | None], object]] = {
    "customer_id": normalize_identifier,
    "loan_id": normalize_identifier,
    "payment_id": normalize_identifier,
    "full_name": normalize_name,
    "email": normalize_email,
    "country_code": normalize_identifier,
    "date_of_birth": normalize_date,
    "principal_amount": normalize_amount,
    "start_date": normalize_date,
    "status": normalize_status,
    "amount": normalize_amount,
    "payment_date": normalize_date,
}


def _transform_table(
    table: str, frame: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, object]]]:
    columns = LEGACY_FILES[table][1]
    duplicate_mask = frame.duplicated(subset=list(columns), keep="first")
    duplicates = frame.loc[duplicate_mask].copy()
    duplicates.insert(0, "table", table)
    cleaned = frame.loc[~duplicate_mask].copy().reset_index(drop=True)
    issues: list[dict[str, object]] = []

    for column in columns:
        values: list[object] = []
        for source_row, value in zip(
            cleaned["_source_row"], cleaned[column], strict=True
        ):
            try:
                values.append(COLUMN_NORMALIZERS[column](value))
            except ValueError as exc:
                # Keep the raw text so validation can reject it with a useful reason.
                values.append(value)
                issues.append(
                    {
                        "table": table,
                        "_source_row": int(source_row),
                        "field": column,
                        "raw_value": value,
                        "reason": str(exc),
                    }
                )
        cleaned[column] = pd.Series(values, index=cleaned.index, dtype=object)

    logger.info(
        "Cleaned %s: %s rows; %s exact duplicates removed",
        table,
        len(cleaned),
        len(duplicates),
    )
    return cleaned, duplicates, issues


def flag_probable_duplicates(customers: pd.DataFrame) -> pd.DataFrame:
    """Flag different customer IDs sharing a nonempty email, without merging them."""
    candidates = customers.loc[
        customers["email"].notna() & customers["email"].str.contains("@", na=False)
    ]
    id_counts = candidates.groupby("email")["customer_id"].transform("nunique")
    flagged = candidates.loc[id_counts > 1].copy()
    flagged["reason"] = (
        "Different customer IDs share a normalized email; review required."
    )
    return flagged.loc[:, list(PROBABLE_COLUMNS)].reset_index(drop=True)


def transform_legacy_data(tables: dict[str, pd.DataFrame]) -> TransformationResult:
    """Clean all tables, retaining exact duplicates and conversion diagnostics."""
    cleaned: dict[str, pd.DataFrame] = {}
    duplicate_frames: list[pd.DataFrame] = []
    issues: list[dict[str, object]] = []
    for table in LEGACY_FILES:
        cleaned[table], duplicates, table_issues = _transform_table(
            table, tables[table]
        )
        duplicate_frames.append(duplicates)
        issues.extend(table_issues)

    probable = flag_probable_duplicates(cleaned["customers"])
    cleaned["customers"]["_probable_duplicate"] = cleaned["customers"][
        "_source_row"
    ].isin(probable["_source_row"])
    logger.info(
        "Flagged %s customer rows for duplicate review; recorded %s conversion issues",
        len(probable),
        len(issues),
    )
    return TransformationResult(
        tables=cleaned,
        read_counts={table: len(tables[table]) for table in LEGACY_FILES},
        exact_duplicates=pd.concat(duplicate_frames, ignore_index=True),
        probable_duplicates=probable,
        transformation_issues=pd.DataFrame(issues, columns=ISSUE_COLUMNS),
    )


def run_transformation(input_dir: Path, output_dir: Path) -> TransformationResult:
    """Extract and clean legacy files, then write inspection CSVs to a destination."""
    result = transform_legacy_data(extract_legacy_data(input_dir))
    exports = {f"{table}_cleaned.csv": frame for table, frame in result.tables.items()}
    exports.update(
        {
            "exact_duplicates.csv": result.exact_duplicates,
            "probable_duplicates.csv": result.probable_duplicates,
            "transformation_issues.csv": result.transformation_issues,
        }
    )
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        for filename, frame in exports.items():
            frame.to_csv(
                output_dir / filename,
                index=False,
                encoding="utf-8",
                lineterminator="\n",
            )
    except OSError as exc:
        raise OSError(
            f"Could not write transformation outputs to {output_dir}: {exc}"
        ) from exc
    logger.info("Wrote transformation outputs to %s", output_dir)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone cleaning step while the unified CLI remains deferred."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        run_transformation(args.input_dir, args.output_dir)
    except (ValueError, OSError) as exc:
        logger.error("Transformation failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
