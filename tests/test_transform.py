"""Verify field conversions and that cleaning never hides source outcomes."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from migration.extract import LEGACY_FILES, extract_legacy_data
from migration.generate_legacy_data import generate_legacy_data
from migration.transform import (
    flag_probable_duplicates,
    main,
    normalize_amount,
    normalize_date,
    normalize_email,
    normalize_identifier,
    normalize_name,
    normalize_status,
    normalize_text,
    run_transformation,
    transform_legacy_data,
)


@pytest.mark.parametrize("value", ["2024-02-13", "13/02/2024", "02-13-2024"])
def test_supported_dates_have_one_representation(value: str) -> None:
    assert normalize_date(value) == date(2024, 2, 13)


def test_date_separators_resolve_ambiguous_day_and_month() -> None:
    assert normalize_date("03/04/2024") == date(2024, 4, 3)
    assert normalize_date("03-04-2024") == date(2024, 3, 4)
    assert normalize_date("2024-02-29") == date(2024, 2, 29)


@pytest.mark.parametrize("value", ["31/02/2024", "2023-02-29", "2024/02/13"])
def test_invalid_dates_raise_instead_of_becoming_missing(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_date(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("$1,200.50", "1200.50"),
        (" 1200.5 ", "1200.50"),
        ("1200", "1200.00"),
        ("-$10.25", "-10.25"),
        ("$-10.25", "-10.25"),
        ("0.10", "0.10"),
    ],
)
def test_amounts_use_exact_decimals(value: str, expected: str) -> None:
    assert normalize_amount(value) == Decimal(expected)
    assert isinstance(normalize_amount(value), Decimal)


@pytest.mark.parametrize("value", ["1,20.50", "1.234", "NaN", "1e3", "$-$1", "EUR 10"])
def test_unsupported_amounts_are_not_guessed_or_rounded(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_amount(value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_empty_fields_become_none(value: str | None) -> None:
    for normalize in (
        normalize_text,
        normalize_date,
        normalize_amount,
        normalize_status,
    ):
        assert normalize(value) is None


def test_text_normalization_keeps_unknown_values_for_validation() -> None:
    assert normalize_name("  aLLISON   hILL ") == "Allison Hill"
    assert normalize_email(" Customer@EXAMPLE.COM ") == "customer@example.com"
    assert normalize_identifier(" cr ") == "CR"
    assert normalize_identifier(" c000001 ") == "C000001"
    assert normalize_status(" Act. ") == "active"
    assert normalize_status("CLOSED") == "closed"
    assert normalize_status("pending") == "pending"
    assert normalize_email("invalid-email") == "invalid-email"


def test_cleaning_preserves_source_accounting_and_does_not_mutate_input(
    tmp_path: Path,
) -> None:
    generate_legacy_data(tmp_path, customer_count=40)
    tables = extract_legacy_data(tmp_path)
    original = {table: frame.copy(deep=True) for table, frame in tables.items()}

    result = transform_legacy_data(tables)

    for table, frame in tables.items():
        pd.testing.assert_frame_equal(frame, original[table])
        duplicates = result.exact_duplicates.loc[
            result.exact_duplicates["table"] == table
        ]
        assert result.read_counts[table] == len(result.tables[table]) + len(duplicates)
        assert set(frame["_source_row"]) == (
            set(result.tables[table]["_source_row"]) | set(duplicates["_source_row"])
        )
    assert len(result.tables["customers"]) == 42
    assert len(result.exact_duplicates) == 2
    assert len(result.probable_duplicates) == 4
    assert result.tables["customers"]["_probable_duplicate"].sum() == 4
    assert result.transformation_issues.empty
    # Business-rule violations stay in place until Phase 4.
    assert any(
        value < 0 for value in result.tables["payments"]["amount"] if value is not None
    )
    assert "ZZ" in result.tables["customers"]["country_code"].tolist()


def test_conversion_issues_keep_raw_values_and_source_rows(tmp_path: Path) -> None:
    generate_legacy_data(tmp_path, customer_count=10)
    tables = extract_legacy_data(tmp_path)
    tables["loans"].loc[0, "principal_amount"] = "1,20.50"
    tables["loans"].loc[0, "start_date"] = "31/02/2024"

    result = transform_legacy_data(tables)

    assert result.tables["loans"].loc[0, "principal_amount"] == "1,20.50"
    assert result.tables["loans"].loc[0, "start_date"] == "31/02/2024"
    issues = result.transformation_issues
    assert set(issues["field"]) == {"principal_amount", "start_date"}
    assert issues["_source_row"].tolist() == [2, 2]
    assert set(issues["table"]) == {"loans"}
    assert all(issues["reason"])


def test_conflicting_rows_with_same_id_are_not_removed(tmp_path: Path) -> None:
    generate_legacy_data(tmp_path, customer_count=10)
    tables = extract_legacy_data(tmp_path)
    tables["customers"].loc[10, "full_name"] = "Different Name"

    result = transform_legacy_data(tables)

    assert result.exact_duplicates.empty
    assert len(result.tables["customers"]) == 12


def test_probable_duplicates_require_shared_email_and_different_ids() -> None:
    customers = pd.DataFrame(
        {
            "_source_row": [2, 3, 4, 5, 6, 7],
            "customer_id": ["C1", "C2", "C3", "C4", "C5", "C5"],
            "full_name": ["Same Name"] * 6,
            "email": [
                None,
                None,
                "same@example.com",
                "same@example.com",
                "other@example.com",
                "other@example.com",
            ],
            "date_of_birth": [None] * 6,
        }
    )

    report = flag_probable_duplicates(customers)

    assert report["customer_id"].tolist() == ["C3", "C4"]
    assert len(customers) == 6


def test_header_only_tables_produce_empty_outputs() -> None:
    tables = {
        table: pd.DataFrame(columns=["_source_row", *columns])
        for table, (_, columns) in LEGACY_FILES.items()
    }

    result = transform_legacy_data(tables)

    assert all(frame.empty for frame in result.tables.values())
    assert result.exact_duplicates.empty
    assert result.probable_duplicates.empty
    assert result.transformation_issues.empty


def test_standalone_step_writes_inspectable_outputs_without_changing_sources(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy"
    output = tmp_path / "output"
    generate_legacy_data(source, customer_count=10)
    original = {path.name: path.read_bytes() for path in source.glob("*.csv")}

    result = run_transformation(source, output)

    assert {path.name for path in output.glob("*.csv")} == {
        "customers_cleaned.csv",
        "loans_cleaned.csv",
        "payments_cleaned.csv",
        "exact_duplicates.csv",
        "probable_duplicates.csv",
        "transformation_issues.csv",
    }
    loans = pd.read_csv(output / "loans_cleaned.csv", dtype=str, keep_default_na=False)
    assert loans.loc[0, "principal_amount"] == "47580.64"
    assert loans.loc[0, "start_date"] == "2020-02-24"
    assert loans.loc[0, "status"] == "active"
    assert len(result.tables["customers"]) == 11
    assert original == {path.name: path.read_bytes() for path in source.glob("*.csv")}
    assert main(["--input-dir", str(source), "--output-dir", str(output)]) == 0


def test_missing_inputs_are_reported_without_outputs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    output = tmp_path / "output"
    assert (
        main(["--input-dir", str(tmp_path / "missing"), "--output-dir", str(output)])
        == 1
    )
    assert "Run the generator" in caplog.text
    assert not output.exists()
