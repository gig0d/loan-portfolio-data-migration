"""Apply named quality rules and preserve one rejection outcome per source row."""

import argparse
import json
import logging
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pycountry

from migration.extract import LEGACY_FILES, extract_legacy_data
from migration.transform import TransformationResult, transform_legacy_data

logger = logging.getLogger(__name__)

Row = Mapping[str, object]
REJECTION_COLUMNS = (
    "table",
    "_source_row",
    "record_id",
    "rule",
    "reason",
    "violations",
    "record_json",
)
ID_FIELDS = {"customers": "customer_id", "loans": "loan_id", "payments": "payment_id"}


@dataclass(frozen=True)
class Violation:
    """Describe a failed rule for one field of a source record."""

    rule: str
    field: str
    reason: str


@dataclass
class ValidationResult:
    """Keep accepted tables, rejected source records, and cleaning diagnostics."""

    valid_tables: dict[str, pd.DataFrame]
    rejected_records: pd.DataFrame
    transformation: TransformationResult


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _common_failures(
    row: Row, table: str, duplicate_ids: Collection[str]
) -> list[Violation]:
    failures = [
        Violation("VR003_MISSING_REQUIRED", field, f"{field} is required.")
        for field in LEGACY_FILES[table][1]
        if _is_missing(row.get(field))
    ]
    id_field = ID_FIELDS[table]
    if row.get(id_field) in duplicate_ids:
        failures.append(
            Violation(
                "VR008_DUPLICATE_ID",
                id_field,
                f"{id_field} {row[id_field]} occurs in conflicting source records.",
            )
        )
    return failures


def _date_failures(row: Row, field: str) -> list[Violation]:
    value = row.get(field)
    if not _is_missing(value) and not isinstance(value, date):
        return [
            Violation(
                "VR004_INVALID_DATE",
                field,
                f"{field} cannot be parsed as a supported calendar date: {value}.",
            )
        ]
    return []


def _amount_failures(row: Row, field: str) -> list[Violation]:
    value = row.get(field)
    if _is_missing(value):
        return []
    if not isinstance(value, Decimal) or not value.is_finite():
        return [
            Violation(
                "VR005_INVALID_AMOUNT",
                field,
                f"{field} is not a supported exact monetary amount: {value}.",
            )
        ]
    if value.as_tuple().exponent < -2:
        return [
            Violation(
                "VR005_INVALID_AMOUNT",
                field,
                f"{field} has more than two decimal places: {value}.",
            )
        ]
    if value <= 0:
        return [
            Violation(
                "VR006_NON_POSITIVE_AMOUNT",
                field,
                f"{field} must be greater than zero; received {value}.",
            )
        ]
    return []


def validate_customer(row: Row, duplicate_ids: Collection[str] = ()) -> list[Violation]:
    """Check required customer fields, email syntax, country, date, and identity."""
    failures = _common_failures(row, "customers", duplicate_ids)
    email = row.get("email")
    if not _is_missing(email) and (
        not isinstance(email, str)
        or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
    ):
        failures.append(
            Violation(
                "VR001_INVALID_EMAIL",
                "email",
                f"Email has an invalid basic syntax: {email}.",
            )
        )
    country = row.get("country_code")
    if not _is_missing(country) and (
        not isinstance(country, str) or pycountry.countries.get(alpha_2=country) is None
    ):
        failures.append(
            Violation(
                "VR002_INVALID_COUNTRY_CODE",
                "country_code",
                f"Country code is not ISO 3166-1 alpha-2: {country}.",
            )
        )
    failures.extend(_date_failures(row, "date_of_birth"))
    if row.get("_probable_duplicate", False):
        failures.append(
            Violation(
                "VR009_PROBABLE_DUPLICATE_CUSTOMER",
                "email",
                "Different customer IDs share this email; identity requires review.",
            )
        )
    return failures


def validate_loan(
    row: Row, valid_customer_ids: Collection[str], duplicate_ids: Collection[str] = ()
) -> list[Violation]:
    """Check loan fields and require a customer accepted by validation."""
    failures = _common_failures(row, "loans", duplicate_ids)
    failures.extend(_amount_failures(row, "principal_amount"))
    failures.extend(_date_failures(row, "start_date"))
    status = row.get("status")
    if not _is_missing(status) and status not in {"active", "closed"}:
        failures.append(
            Violation(
                "VR007_INVALID_STATUS",
                "status",
                f"Loan status must be active or closed; received {status}.",
            )
        )
    customer_id = row.get("customer_id")
    if not _is_missing(customer_id) and customer_id not in valid_customer_ids:
        failures.append(
            Violation(
                "VR010_CUSTOMER_NOT_FOUND",
                "customer_id",
                f"Customer {customer_id} is missing or was rejected; "
                "the loan cannot be loaded.",
            )
        )
    return failures


def validate_payment(
    row: Row, valid_loans: Mapping[str, Row], duplicate_ids: Collection[str] = ()
) -> list[Violation]:
    """Check payment fields, accepted loan references, and payment chronology."""
    failures = _common_failures(row, "payments", duplicate_ids)
    failures.extend(_amount_failures(row, "amount"))
    failures.extend(_date_failures(row, "payment_date"))
    loan_id = row.get("loan_id")
    loan = valid_loans.get(loan_id) if isinstance(loan_id, str) else None
    if not _is_missing(loan_id) and loan is None:
        failures.append(
            Violation(
                "VR011_LOAN_NOT_FOUND",
                "loan_id",
                f"Loan {loan_id} is missing or was rejected; "
                "the payment cannot be loaded.",
            )
        )
    payment_date = row.get("payment_date")
    if loan is not None and isinstance(payment_date, date):
        if payment_date < loan["start_date"]:
            failures.append(
                Violation(
                    "VR012_PAYMENT_BEFORE_LOAN_START",
                    "payment_date",
                    f"Payment date {payment_date} precedes "
                    f"loan start {loan['start_date']}.",
                )
            )
    return failures


def _duplicate_ids(frame: pd.DataFrame, field: str) -> set[str]:
    return {
        value
        for value in frame.loc[frame[field].duplicated(keep=False), field]
        if isinstance(value, str) and value
    }


def _rejection(
    table: str, row: Row, violations: list[Violation], raw_record: Row
) -> dict[str, object]:
    return {
        "table": table,
        "_source_row": int(row["_source_row"]),
        "record_id": raw_record.get(ID_FIELDS[table], ""),
        "rule": violations[0].rule,
        "reason": violations[0].reason,
        "violations": json.dumps(
            [
                {"rule": item.rule, "field": item.field, "reason": item.reason}
                for item in violations
            ],
            ensure_ascii=False,
        ),
        "record_json": json.dumps(dict(raw_record), ensure_ascii=False),
    }


def _partition_table(
    table: str,
    frame: pd.DataFrame,
    validator: Callable[[Row], list[Violation]],
    raw_records: dict[int, Row],
    rejections: list[dict[str, object]],
) -> pd.DataFrame:
    accepted: list[bool] = []
    for row in frame.to_dict(orient="records"):
        violations = validator(row)
        accepted.append(not violations)
        if violations:
            rejections.append(
                _rejection(table, row, violations, raw_records[int(row["_source_row"])])
            )
    return frame.loc[accepted].copy().reset_index(drop=True)


def validate_legacy_data(tables: dict[str, pd.DataFrame]) -> ValidationResult:
    """Transform and validate source tables in dependency order without losing rows."""
    transformed = transform_legacy_data(tables)
    raw_records = {
        table: {
            int(row["_source_row"]): {
                field: row[field] for field in LEGACY_FILES[table][1]
            }
            for row in frame.to_dict(orient="records")
        }
        for table, frame in tables.items()
    }
    duplicate_ids = {
        table: _duplicate_ids(frame, ID_FIELDS[table])
        for table, frame in transformed.tables.items()
    }
    rejections: list[dict[str, object]] = []
    valid: dict[str, pd.DataFrame] = {}
    valid["customers"] = _partition_table(
        "customers",
        transformed.tables["customers"],
        lambda row: validate_customer(row, duplicate_ids["customers"]),
        raw_records["customers"],
        rejections,
    )
    customer_ids = set(valid["customers"]["customer_id"])
    valid["loans"] = _partition_table(
        "loans",
        transformed.tables["loans"],
        lambda row: validate_loan(row, customer_ids, duplicate_ids["loans"]),
        raw_records["loans"],
        rejections,
    )
    loans_by_id = {
        row["loan_id"]: row for row in valid["loans"].to_dict(orient="records")
    }
    valid["payments"] = _partition_table(
        "payments",
        transformed.tables["payments"],
        lambda row: validate_payment(row, loans_by_id, duplicate_ids["payments"]),
        raw_records["payments"],
        rejections,
    )
    for row in transformed.exact_duplicates.to_dict(orient="records"):
        table = row["table"]
        rejections.append(
            _rejection(
                table,
                row,
                [
                    Violation(
                        "VR013_EXACT_DUPLICATE",
                        "record",
                        "Exact duplicate source row; the first occurrence "
                        "was retained for validation.",
                    )
                ],
                raw_records[table][int(row["_source_row"])],
            )
        )

    rejected = pd.DataFrame(rejections, columns=REJECTION_COLUMNS)
    rejected = rejected.sort_values(["table", "_source_row"]).reset_index(drop=True)
    for table, frame in valid.items():
        rejected_count = int((rejected["table"] == table).sum())
        logger.info(
            "Validated %s: %s accepted; %s rejected source records",
            table,
            len(frame),
            rejected_count,
        )
    return ValidationResult(valid, rejected, transformed)


def run_validation(input_dir: Path, output_dir: Path) -> ValidationResult:
    """Validate legacy sources and write valid tables and rejected-record details."""
    result = validate_legacy_data(extract_legacy_data(input_dir))
    exports = {
        f"{table}_valid.csv": frame for table, frame in result.valid_tables.items()
    }
    exports["rejected_records.csv"] = result.rejected_records
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
            f"Could not write validation outputs to {output_dir}: {exc}"
        ) from exc
    logger.info("Wrote validation outputs to %s", output_dir)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone validation step; database loading remains deferred."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        run_validation(args.input_dir, args.output_dir)
    except (ValueError, OSError) as exc:
        logger.error("Validation failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
