"""Generate reproducible, deliberately messy synthetic legacy CSV exports."""

import argparse
import csv
import logging
import random
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from faker import Faker

logger = logging.getLogger(__name__)

LegacyRow = dict[str, str]

CUSTOMER_FIELDS = ("customer_id", "full_name", "email", "country_code", "date_of_birth")
LOAN_FIELDS = ("loan_id", "customer_id", "principal_amount", "start_date", "status")
PAYMENT_FIELDS = ("payment_id", "loan_id", "amount", "payment_date")
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y")
COUNTRY_CODES = ("CR", "US", "CA", "GB", "MX")
STATUSES = ("ACTIVE", "active", "Act.", "closed", "CLOSED")


def _format_date(value: date, index: int) -> str:
    return value.strftime(DATE_FORMATS[index % len(DATE_FORMATS)])


def _build_customers(fake: Faker, rng: random.Random, count: int) -> list[LegacyRow]:
    rows: list[LegacyRow] = []
    duplicates: list[LegacyRow] = []
    probable_count = 0

    for index in range(count):
        number = index + 1
        birthday = date(1960, 1, 1) + timedelta(days=rng.randrange(16000))
        row = {
            "customer_id": f"C{number:06d}",
            "full_name": fake.name(),
            "email": f"customer{number:06d}@example.com",
            "country_code": rng.choice(COUNTRY_CODES),
            "date_of_birth": _format_date(birthday, index),
        }
        position = index % 20
        if position == 1:
            row["full_name"] = f"  {row['full_name'].lower()}  "
        elif position == 2:
            row["email"] = "invalid-email"
        elif position == 3:
            row["email"] = ""
        elif position == 4:
            row["full_name"] = ""
        elif position == 5:
            row["country_code"] = ""
        elif position == 6:
            row["country_code"] = "ZZ"
        elif position == 7:
            row["date_of_birth"] = ""

        rows.append(row)
        if position == 0:
            duplicates.append(row.copy())
            probable_count += 1
            probable = row.copy()
            probable["customer_id"] = f"C{count + probable_count:06d}"
            if probable_count % 2:
                probable["full_name"] = row["full_name"].upper()
            else:
                probable["full_name"] = row["full_name"][:-1]
            duplicates.append(probable)

    return rows + duplicates


def _build_loans(rng: random.Random, count: int) -> tuple[list[LegacyRow], list[date]]:
    rows: list[LegacyRow] = []
    start_dates: list[date] = []

    for index in range(count):
        number = index + 1
        start = date(2020, 1, 1) + timedelta(days=rng.randrange(1827))
        amount = Decimal(rng.randint(50000, 5000000)) / 100
        row = {
            "loan_id": f"L{number:06d}",
            "customer_id": f"C{number:06d}",
            "principal_amount": (
                f"${amount:,.2f}" if index % 3 == 0 else f"{amount:.2f}"
            ),
            "start_date": _format_date(start, index),
            "status": STATUSES[index % len(STATUSES)],
        }
        position = index % 20
        if position == 7:
            row["start_date"] = ""
        elif position == 8:
            # This ID is beyond both the base and probable-duplicate customers.
            row["customer_id"] = f"C{2 * count + number:06d}"
        elif position == 9:
            row["principal_amount"] = ""
        elif position == 10:
            row["status"] = ""

        rows.append(row)
        start_dates.append(start)

    return rows, start_dates


def _build_payments(
    rng: random.Random, loans: list[LegacyRow], start_dates: list[date]
) -> list[LegacyRow]:
    rows: list[LegacyRow] = []

    for index, (loan, start) in enumerate(zip(loans, start_dates, strict=True)):
        for installment in range(2):
            amount = Decimal(rng.randint(1000, 25000)) / 100
            payment_date = start + timedelta(days=30 * (installment + 1))
            if installment == 0 and index % 20 == 0:
                amount = -amount
            elif installment == 0 and index % 20 == 1:
                payment_date = start - timedelta(days=1)

            number = len(rows) + 1
            row = {
                "payment_id": f"P{number:06d}",
                "loan_id": loan["loan_id"],
                "amount": f"{amount:.2f}",
                "payment_date": _format_date(payment_date, number - 1),
            }
            if installment == 0 and index % 20 == 2:
                row["amount"] = ""
            elif installment == 0 and index % 20 == 3:
                row["payment_date"] = ""
            rows.append(row)

    return rows


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[LegacyRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate_legacy_data(
    output_dir: Path, customer_count: int = 1000, seed: int = 42
) -> dict[str, int]:
    """Write three synthetic CSVs and return their row counts, excluding headers."""
    if customer_count < 1:
        raise ValueError("Customer count must be at least 1.")

    rng = random.Random(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)
    customers = _build_customers(fake, rng, customer_count)
    loans, start_dates = _build_loans(rng, customer_count)
    payments = _build_payments(rng, loans, start_dates)
    exports = (
        ("customers_legacy.csv", CUSTOMER_FIELDS, customers),
        ("loans_legacy.csv", LOAN_FIELDS, loans),
        ("payments_legacy.csv", PAYMENT_FIELDS, payments),
    )

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        for filename, fields, rows in exports:
            _write_csv(output_dir / filename, fields, rows)
            logger.info("Generated %s: %s synthetic rows", filename, len(rows))
    except OSError as exc:
        raise OSError(f"Could not write legacy CSVs to {output_dir}: {exc}") from exc

    return {filename: len(rows) for filename, _, rows in exports}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone generator with explicit arguments and fixed defaults."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--customers", "--size", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        generate_legacy_data(args.output_dir, args.customers, args.seed)
    except (ValueError, OSError) as exc:
        logger.error("Generation failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
