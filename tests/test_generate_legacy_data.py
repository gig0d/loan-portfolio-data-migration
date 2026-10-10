"""Check synthetic exports, reproducibility, and intentional legacy defects."""

import csv
from datetime import datetime
from pathlib import Path

import pytest

from migration.generate_legacy_data import generate_legacy_data, main


def _read_csv(directory: Path, filename: str) -> list[dict[str, str]]:
    with (directory / filename).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _parse_date(value: str) -> datetime:
    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    raise ValueError(f"Unexpected generated date: {value}")


def test_same_seed_produces_identical_bytes(tmp_path: Path) -> None:
    """Repeated runs and separate output directories must contain identical CSVs."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    counts = generate_legacy_data(first, customer_count=40, seed=42)
    original = {name: (first / name).read_bytes() for name in counts}

    generate_legacy_data(first, customer_count=40, seed=42)
    generate_legacy_data(second, customer_count=40, seed=42)

    for name, content in original.items():
        assert (first / name).read_bytes() == content
        assert (second / name).read_bytes() == content


def test_different_seed_changes_data(tmp_path: Path) -> None:
    generate_legacy_data(tmp_path / "first", customer_count=20, seed=42)
    generate_legacy_data(tmp_path / "second", customer_count=20, seed=99)

    assert (tmp_path / "first" / "customers_legacy.csv").read_bytes() != (
        tmp_path / "second" / "customers_legacy.csv"
    ).read_bytes()


@pytest.mark.parametrize("size", [1, 10, 20, 21])
def test_size_controls_base_customers_and_related_records(
    tmp_path: Path, size: int
) -> None:
    counts = generate_legacy_data(tmp_path, customer_count=size)
    customers = _read_csv(tmp_path, "customers_legacy.csv")
    loans = _read_csv(tmp_path, "loans_legacy.csv")
    payments = _read_csv(tmp_path, "payments_legacy.csv")

    assert len(customers) == size + 2 * ((size + 19) // 20)
    assert len(loans) == size
    assert len(payments) == 2 * size
    assert counts == {
        "customers_legacy.csv": len(customers),
        "loans_legacy.csv": len(loans),
        "payments_legacy.csv": len(payments),
    }
    assert all(
        row["loan_id"] in {loan["loan_id"] for loan in loans} for row in payments
    )
    assert all(
        not row["email"]
        or row["email"] == "invalid-email"
        or row["email"].endswith("@example.com")
        for row in customers
    )


def test_exports_include_required_messiness(tmp_path: Path) -> None:
    generate_legacy_data(tmp_path, customer_count=40)
    customers = _read_csv(tmp_path, "customers_legacy.csv")
    loans = _read_csv(tmp_path, "loans_legacy.csv")
    payments = _read_csv(tmp_path, "payments_legacy.csv")

    assert len({tuple(row.values()) for row in customers}) < len(customers)
    assert any(
        first["customer_id"] != second["customer_id"]
        and first["email"] == second["email"]
        and first["full_name"].casefold() == second["full_name"].casefold()
        for first in customers
        for second in customers
    )
    assert any(
        first["customer_id"] != second["customer_id"]
        and first["email"] == second["email"]
        and first["full_name"][:-1] == second["full_name"]
        for first in customers
        for second in customers
    )
    assert any(row["email"] == "invalid-email" for row in customers)
    assert any(row["country_code"] == "ZZ" for row in customers)
    assert any(row["full_name"] != row["full_name"].strip() for row in customers)
    assert any(
        value == ""
        for rows in (customers, loans, payments)
        for row in rows
        for value in row.values()
    )
    customer_ids = {row["customer_id"] for row in customers}
    assert any(row["customer_id"] not in customer_ids for row in loans)
    assert any(row["principal_amount"].startswith("$") for row in loans)
    assert any(
        "," in row["principal_amount"]
        for row in loans
        if row["principal_amount"].startswith("$")
    )
    assert {"ACTIVE", "active", "Act.", "closed", "CLOSED"} <= {
        row["status"] for row in loans
    }
    assert any(float(row["amount"]) < 0 for row in payments if row["amount"])
    loan_dates = {
        row["loan_id"]: _parse_date(row["start_date"])
        for row in loans
        if row["start_date"]
    }
    assert any(
        _parse_date(row["payment_date"]) < loan_dates[row["loan_id"]]
        for row in payments
        if row["payment_date"] and row["loan_id"] in loan_dates
    )
    dates = [row["date_of_birth"] for row in customers if row["date_of_birth"]]
    assert any("/" in value for value in dates)
    assert any(value[4:5] == "-" for value in dates)
    assert any(value[2:3] == "-" for value in dates)


def test_default_size_is_one_thousand_customers(tmp_path: Path) -> None:
    counts = generate_legacy_data(tmp_path)

    assert counts["customers_legacy.csv"] == 1100
    assert counts["loans_legacy.csv"] == 1000
    assert counts["payments_legacy.csv"] == 2000


@pytest.mark.parametrize("size", [0, -1])
def test_invalid_size_creates_no_exports(tmp_path: Path, size: int) -> None:
    output = tmp_path / "exports"
    with pytest.raises(ValueError, match="at least 1"):
        generate_legacy_data(output, customer_count=size)
    assert not output.exists()


def test_output_path_error_is_helpful(tmp_path: Path) -> None:
    output = tmp_path / "not-a-directory"
    output.write_text("Existing file", encoding="utf-8")

    with pytest.raises(OSError, match="Could not write legacy CSVs"):
        generate_legacy_data(output, customer_count=10)
    assert output.read_text(encoding="utf-8") == "Existing file"


def test_standalone_command_accepts_size_and_seed(tmp_path: Path) -> None:
    assert main(["--output-dir", str(tmp_path), "--size", "10", "--seed", "7"]) == 0
    assert len(_read_csv(tmp_path, "loans_legacy.csv")) == 10


def test_standalone_command_reports_invalid_size(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert main(["--output-dir", str(tmp_path), "--customers", "0"]) == 1
    assert "Customer count must be at least 1" in caplog.text
