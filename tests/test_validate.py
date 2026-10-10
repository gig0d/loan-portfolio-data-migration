"""Verify named rules, dependency rejections, and source-record accounting."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from migration.extract import LEGACY_FILES, extract_legacy_data
from migration.generate_legacy_data import generate_legacy_data
from migration.validate import (
    main,
    run_validation,
    validate_customer,
    validate_legacy_data,
    validate_loan,
    validate_payment,
)


@pytest.fixture
def customer() -> dict[str, object]:
    return {
        "customer_id": "C000001",
        "full_name": "Demo Customer",
        "email": "customer000001@example.com",
        "country_code": "CR",
        "date_of_birth": date(1980, 1, 1),
        "_probable_duplicate": False,
    }


@pytest.fixture
def loan() -> dict[str, object]:
    return {
        "loan_id": "L000001",
        "customer_id": "C000001",
        "principal_amount": Decimal("1200.50"),
        "start_date": date(2024, 1, 1),
        "status": "active",
    }


@pytest.fixture
def payment() -> dict[str, object]:
    return {
        "payment_id": "P000001",
        "loan_id": "L000001",
        "amount": Decimal("100.00"),
        "payment_date": date(2024, 1, 31),
    }


def test_valid_records_pass_all_entity_rules(
    customer: dict[str, object], loan: dict[str, object], payment: dict[str, object]
) -> None:
    assert validate_customer(customer) == []
    assert validate_loan(loan, {"C000001"}) == []
    assert validate_payment(payment, {"L000001": loan}) == []


@pytest.mark.parametrize(
    "value", ["invalid-email", "customer@", "a@@example.com", "a b@example.com"]
)
def test_invalid_email_has_named_rule(customer: dict[str, object], value: str) -> None:
    customer["email"] = value
    failures = validate_customer(customer)
    assert [(item.rule, item.field) for item in failures] == [
        ("VR001_INVALID_EMAIL", "email")
    ]


@pytest.mark.parametrize("value", ["ZZ", "USA"])
def test_country_requires_real_alpha_two_code(
    customer: dict[str, object], value: str
) -> None:
    customer["country_code"] = value
    assert validate_customer(customer)[0].rule == "VR002_INVALID_COUNTRY_CODE"


def test_valid_country_outside_generator_subset_is_accepted(
    customer: dict[str, object],
) -> None:
    customer["country_code"] = "DE"
    assert validate_customer(customer) == []


@pytest.mark.parametrize(
    "field", ["customer_id", "full_name", "email", "country_code", "date_of_birth"]
)
def test_required_customer_fields_are_explicit(
    customer: dict[str, object], field: str
) -> None:
    customer[field] = None
    failures = validate_customer(customer)
    assert [(item.rule, item.field) for item in failures] == [
        ("VR003_MISSING_REQUIRED", field)
    ]


def test_unconverted_date_is_rejected(customer: dict[str, object]) -> None:
    customer["date_of_birth"] = "31/02/2024"
    assert validate_customer(customer)[0].rule == "VR004_INVALID_DATE"


@pytest.mark.parametrize(
    "value", ["1,20.50", Decimal("NaN"), Decimal("Infinity"), Decimal("1.001")]
)
def test_invalid_money_is_rejected(loan: dict[str, object], value: object) -> None:
    loan["principal_amount"] = value
    assert validate_loan(loan, {"C000001"})[0].rule == "VR005_INVALID_AMOUNT"


@pytest.mark.parametrize("value", [Decimal("0.00"), Decimal("-1.00")])
def test_loan_and_payment_amounts_must_be_positive(
    loan: dict[str, object], payment: dict[str, object], value: Decimal
) -> None:
    loan["principal_amount"] = value
    payment["amount"] = value
    assert validate_loan(loan, {"C000001"})[0].rule == "VR006_NON_POSITIVE_AMOUNT"
    assert (
        validate_payment(payment, {"L000001": loan})[0].rule
        == "VR006_NON_POSITIVE_AMOUNT"
    )


def test_unknown_status_is_rejected(loan: dict[str, object]) -> None:
    loan["status"] = "pending"
    assert validate_loan(loan, {"C000001"})[0].rule == "VR007_INVALID_STATUS"


def test_duplicate_ids_are_rejected_for_all_tables(
    customer: dict[str, object], loan: dict[str, object], payment: dict[str, object]
) -> None:
    assert validate_customer(customer, {"C000001"})[0].rule == "VR008_DUPLICATE_ID"
    assert validate_loan(loan, {"C000001"}, {"L000001"})[0].rule == "VR008_DUPLICATE_ID"
    assert (
        validate_payment(payment, {"L000001": loan}, {"P000001"})[0].rule
        == "VR008_DUPLICATE_ID"
    )


def test_probable_duplicates_require_review(customer: dict[str, object]) -> None:
    customer["_probable_duplicate"] = True
    assert validate_customer(customer)[0].rule == "VR009_PROBABLE_DUPLICATE_CUSTOMER"


def test_missing_or_rejected_customer_blocks_loan(loan: dict[str, object]) -> None:
    assert validate_loan(loan, set())[0].rule == "VR010_CUSTOMER_NOT_FOUND"


def test_missing_or_rejected_loan_blocks_payment(payment: dict[str, object]) -> None:
    assert validate_payment(payment, {})[0].rule == "VR011_LOAN_NOT_FOUND"


def test_payment_start_date_boundary(
    loan: dict[str, object], payment: dict[str, object]
) -> None:
    payment["payment_date"] = date(2023, 12, 31)
    assert (
        validate_payment(payment, {"L000001": loan})[0].rule
        == "VR012_PAYMENT_BEFORE_LOAN_START"
    )
    payment["payment_date"] = date(2024, 1, 1)
    assert validate_payment(payment, {"L000001": loan}) == []


def test_every_source_record_has_one_outcome_and_valid_foreign_keys(
    tmp_path: Path,
) -> None:
    generate_legacy_data(tmp_path, customer_count=40)
    tables = extract_legacy_data(tmp_path)
    original = {table: frame.copy(deep=True) for table, frame in tables.items()}

    result = validate_legacy_data(tables)

    for table, source in tables.items():
        valid = result.valid_tables[table]
        rejected = result.rejected_records.loc[
            result.rejected_records["table"] == table
        ]
        assert len(source) == len(valid) + len(rejected)
        assert not rejected["_source_row"].duplicated().any()
        assert set(valid["_source_row"]).isdisjoint(set(rejected["_source_row"]))
        assert set(source["_source_row"]) == set(valid["_source_row"]) | set(
            rejected["_source_row"]
        )
        pd.testing.assert_frame_equal(source, original[table])
    customer_ids = set(result.valid_tables["customers"]["customer_id"])
    loan_ids = set(result.valid_tables["loans"]["loan_id"])
    assert set(result.valid_tables["loans"]["customer_id"]) <= customer_ids
    assert set(result.valid_tables["payments"]["loan_id"]) <= loan_ids
    assert not result.valid_tables["customers"]["_probable_duplicate"].any()
    exact = result.rejected_records.loc[
        result.rejected_records["rule"] == "VR013_EXACT_DUPLICATE"
    ]
    assert len(exact) == 2


def test_multiple_failures_and_raw_values_share_one_rejection(tmp_path: Path) -> None:
    generate_legacy_data(tmp_path, customer_count=20)
    tables = extract_legacy_data(tmp_path)
    tables["customers"].loc[1, "email"] = "not-an-email"
    tables["customers"].loc[1, "country_code"] = "ZZ"
    tables["customers"].loc[1, "date_of_birth"] = "31/02/2024"

    result = validate_legacy_data(tables)
    rows = result.rejected_records.loc[
        (result.rejected_records["table"] == "customers")
        & (result.rejected_records["_source_row"] == 3)
    ]

    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["rule"] == "VR001_INVALID_EMAIL"
    assert {item["rule"] for item in json.loads(row["violations"])} == {
        "VR001_INVALID_EMAIL",
        "VR002_INVALID_COUNTRY_CODE",
        "VR004_INVALID_DATE",
    }
    assert (
        json.loads(row["record_json"])["full_name"]
        == tables["customers"].loc[1, "full_name"]
    )
    assert json.loads(row["record_json"])["date_of_birth"] == "31/02/2024"
    assert len(result.transformation.transformation_issues) == 1


def test_rejected_customer_cascades_to_loans_and_payments(tmp_path: Path) -> None:
    generate_legacy_data(tmp_path, customer_count=20)

    result = validate_legacy_data(extract_legacy_data(tmp_path))

    loan_row = result.rejected_records.loc[
        (result.rejected_records["table"] == "loans")
        & (result.rejected_records["record_id"] == "L000003")
    ].iloc[0]
    assert loan_row["rule"] == "VR010_CUSTOMER_NOT_FOUND"
    payment_row = result.rejected_records.loc[
        (result.rejected_records["table"] == "payments")
        & (result.rejected_records["record_id"] == "P000006")
    ].iloc[0]
    assert payment_row["rule"] == "VR011_LOAN_NOT_FOUND"


@pytest.mark.parametrize("table", ["customers", "loans", "payments"])
def test_conflicting_ids_reject_both_rows(tmp_path: Path, table: str) -> None:
    generate_legacy_data(tmp_path, customer_count=20)
    tables = extract_legacy_data(tmp_path)
    id_field = {
        "customers": "customer_id",
        "loans": "loan_id",
        "payments": "payment_id",
    }[table]
    tables[table].loc[12, id_field] = tables[table].loc[11, id_field]

    result = validate_legacy_data(tables)

    for source_row in (13, 14):
        row = result.rejected_records.loc[
            (result.rejected_records["table"] == table)
            & (result.rejected_records["_source_row"] == source_row)
        ].iloc[0]
        assert "VR008_DUPLICATE_ID" in {
            item["rule"] for item in json.loads(row["violations"])
        }


def test_empty_sources_produce_empty_outcomes() -> None:
    tables = {
        table: pd.DataFrame(columns=["_source_row", *columns])
        for table, (_, columns) in LEGACY_FILES.items()
    }
    result = validate_legacy_data(tables)
    assert result.rejected_records.empty
    assert all(frame.empty for frame in result.valid_tables.values())


def test_standalone_validation_writes_reports_and_repeats_safely(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy"
    output = tmp_path / "output"
    generate_legacy_data(source, customer_count=20)

    result = run_validation(source, output)
    original = {path.name: path.read_bytes() for path in output.glob("*.csv")}
    assert set(original) == {
        "customers_valid.csv",
        "loans_valid.csv",
        "payments_valid.csv",
        "rejected_records.csv",
    }
    report = pd.read_csv(output / "rejected_records.csv", keep_default_na=False)
    assert len(report) == len(result.rejected_records)
    assert all(report["reason"])
    assert main(["--input-dir", str(source), "--output-dir", str(output)]) == 0
    assert original == {path.name: path.read_bytes() for path in output.glob("*.csv")}


def test_report_has_headers_when_all_records_are_valid(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    output = tmp_path / "output"
    generate_legacy_data(source, customer_count=20)
    tables = extract_legacy_data(source)
    for table in tables:
        tables[table] = tables[table].iloc[[11]].copy()
    tables["payments"].loc[:, "loan_id"] = tables["loans"].iloc[0]["loan_id"]
    tables["payments"].loc[:, "payment_date"] = "2025-12-31"
    for table, (filename, columns) in LEGACY_FILES.items():
        tables[table].loc[:, list(columns)].to_csv(source / filename, index=False)

    result = run_validation(source, output)

    assert result.rejected_records.empty
    report = pd.read_csv(output / "rejected_records.csv")
    assert report.empty
    assert "rule" in report.columns


def test_missing_sources_return_helpful_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    output = tmp_path / "output"
    assert (
        main(["--input-dir", str(tmp_path / "missing"), "--output-dir", str(output)])
        == 1
    )
    assert "Run the generator" in caplog.text
    assert not output.exists()
