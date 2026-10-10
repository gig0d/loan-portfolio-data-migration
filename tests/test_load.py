"""Exercise SQL integrity, rollback, exact cents, and repeat synthetic loads."""

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import IntegrityError

from migration.config import PROJECT_ROOT
from migration.extract import extract_legacy_data
from migration.generate_legacy_data import generate_legacy_data
from migration.load import (
    amount_to_cents,
    create_database_engine,
    create_schema,
    load_valid_records,
    main,
)
from migration.validate import ValidationResult, validate_legacy_data

SCHEMA = PROJECT_ROOT / "sql/schema.sql"


@pytest.fixture
def engine(tmp_path: Path):
    database = create_database_engine(
        URL.create("sqlite", database=str(tmp_path / "test.db"))
    )
    yield database
    database.dispose()


@pytest.fixture
def validation(tmp_path: Path) -> ValidationResult:
    generate_legacy_data(tmp_path / "legacy", customer_count=20, seed=42)
    return validate_legacy_data(extract_legacy_data(tmp_path / "legacy"))


def table_counts(engine: Engine) -> dict[str, int]:
    tables = create_schema(engine, SCHEMA)
    with engine.connect() as connection:
        return {
            name: connection.scalar(select(func.count()).select_from(table))
            for name, table in tables.items()
        }


def test_load_twice_preserves_exact_rows_and_cents(
    engine: Engine, validation: ValidationResult
) -> None:
    first = load_valid_records(validation, engine, SCHEMA)
    second = load_valid_records(validation, engine, SCHEMA)
    expected = {name: len(frame) for name, frame in validation.valid_tables.items()}
    assert first.inserted_counts == expected
    assert second.inserted_counts == dict.fromkeys(expected, 0)
    assert second.existing_counts == expected
    assert second.loaded_counts == expected == table_counts(engine)
    tables = create_schema(engine, SCHEMA)
    with engine.connect() as connection:
        stored = {
            row.loan_id: row.principal_amount_cents
            for row in connection.execute(select(tables["loans"]))
        }
    for row in validation.valid_tables["loans"].to_dict(orient="records"):
        assert stored[row["loan_id"]] == int(row["principal_amount"] * 100)


def test_changed_id_rolls_back_new_parent_inserts(
    engine: Engine, validation: ValidationResult
) -> None:
    load_valid_records(validation, engine, SCHEMA)
    before = table_counts(engine)
    customer = validation.valid_tables["customers"].iloc[0].copy()
    customer["customer_id"] = "CNEW"
    customer["email"] = "new@example.com"
    validation.valid_tables["customers"] = pd.concat(
        [validation.valid_tables["customers"], pd.DataFrame([customer])],
        ignore_index=True,
    )
    validation.valid_tables["loans"].loc[0, "status"] = (
        "closed"
        if validation.valid_tables["loans"].loc[0, "status"] == "active"
        else "active"
    )
    with pytest.raises(ValueError, match="Changed existing loans ID"):
        load_valid_records(validation, engine, SCHEMA)
    assert table_counts(engine) == before


def test_child_constraint_failure_rolls_back_all_tables(
    engine: Engine, validation: ValidationResult
) -> None:
    validation.valid_tables["payments"].loc[0, "loan_id"] = "MISSING"
    with pytest.raises(ValueError, match="no new portfolio records were committed"):
        load_valid_records(validation, engine, SCHEMA)
    assert table_counts(engine) == {"customers": 0, "loans": 0, "payments": 0}


@pytest.mark.parametrize(
    "changes",
    [
        {"customer_id": None},
        {"full_name": None},
        {"email": "repeat@example.com"},
        {"customer_id": "C1", "email": "different@example.com"},
    ],
)
def test_customer_sql_constraints(engine: Engine, changes: dict[str, object]) -> None:
    table = create_schema(engine, SCHEMA)["customers"]
    record = {
        "customer_id": "C1",
        "full_name": "Synthetic Demo",
        "email": "repeat@example.com",
        "country_code": "CR",
        "date_of_birth": date(1980, 1, 1),
    }
    with engine.begin() as connection:
        connection.execute(table.insert(), record)
    record = {**record, "customer_id": "C2", **changes}
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(table.insert(), record)


@pytest.mark.parametrize(
    "changes",
    [
        {"customer_id": "ORPHAN"},
        {"principal_amount_cents": 0},
        {"principal_amount_cents": -1},
        {"status": "unknown"},
    ],
)
def test_loan_sql_constraints(
    engine: Engine, validation: ValidationResult, changes: dict[str, object]
) -> None:
    load_valid_records(validation, engine, SCHEMA)
    table = create_schema(engine, SCHEMA)["loans"]
    customer_id = validation.valid_tables["customers"].iloc[0]["customer_id"]
    record = {
        "loan_id": "LNEW",
        "customer_id": customer_id,
        "principal_amount_cents": 120050,
        "start_date": date(2024, 1, 1),
        "status": "active",
        **changes,
    }
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(table.insert(), record)


@pytest.mark.parametrize("changes", [{"loan_id": "ORPHAN"}, {"amount_cents": -1}])
def test_payment_sql_constraints(
    engine: Engine, validation: ValidationResult, changes: dict[str, object]
) -> None:
    load_valid_records(validation, engine, SCHEMA)
    table = create_schema(engine, SCHEMA)["payments"]
    loan_id = validation.valid_tables["loans"].iloc[0]["loan_id"]
    record = {
        "payment_id": "PNEW",
        "loan_id": loan_id,
        "amount_cents": 123,
        "payment_date": date(2024, 1, 1),
        **changes,
    }
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(table.insert(), record)


@pytest.mark.parametrize(
    "amount, expected", [("0.01", 1), ("0.10", 10), ("1200.50", 120050)]
)
def test_exact_cent_conversion(amount: str, expected: int) -> None:
    assert amount_to_cents(Decimal(amount)) == expected


@pytest.mark.parametrize(
    "amount", ["0", "-1", "1.001", "NaN", "Infinity", "90000000000000.01"]
)
def test_unsafe_amounts_fail_without_rounding(amount: str) -> None:
    with pytest.raises(ValueError, match="Money must"):
        amount_to_cents(Decimal(amount))


def test_empty_validated_tables_can_be_loaded(
    engine: Engine, validation: ValidationResult
) -> None:
    validation.valid_tables = {
        name: frame.iloc[:0].copy() for name, frame in validation.valid_tables.items()
    }
    assert load_valid_records(
        validation, engine, SCHEMA
    ).loaded_counts == dict.fromkeys(validation.valid_tables, 0)


def test_standalone_command_uses_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate_legacy_data(tmp_path / "legacy", customer_count=20)
    monkeypatch.setenv(
        "DATABASE_URL",
        URL.create("sqlite", database=str(tmp_path / "cli.db")).render_as_string(),
    )
    monkeypatch.setenv("LEGACY_DATA_DIR", str(tmp_path / "legacy"))
    monkeypatch.setenv("OUTPUT_DATA_DIR", str(tmp_path / "output"))
    assert main([]) == 0
    assert main([]) == 0
    assert (tmp_path / "cli.db").is_file()
    assert (tmp_path / "output/rejected_records.csv").is_file()


def test_command_has_helpful_failure_for_missing_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("LEGACY_DATA_DIR", str(tmp_path / "missing"))
    assert main([]) == 1
    assert "Run the generator" in caplog.text


@pytest.mark.skipif(
    not os.environ.get("TEST_MYSQL_DATABASE_URL"),
    reason="Requires an explicitly supplied empty MySQL test database",
)
def test_mysql_load_repeat_and_rollback(tmp_path: Path) -> None:
    """Use only a disposable empty database; do not delete external records."""
    engine = create_database_engine(make_url(os.environ["TEST_MYSQL_DATABASE_URL"]))
    try:
        assert table_counts(engine) == {"customers": 0, "loans": 0, "payments": 0}, (
            "Use an empty disposable test database."
        )
        generate_legacy_data(tmp_path / "legacy", customer_count=20)
        validation = validate_legacy_data(extract_legacy_data(tmp_path / "legacy"))
        validation.valid_tables["payments"].loc[0, "loan_id"] = "MISSING"
        with pytest.raises(ValueError, match="no new portfolio records"):
            load_valid_records(validation, engine, SCHEMA)
        assert table_counts(engine) == {"customers": 0, "loans": 0, "payments": 0}
        validation = validate_legacy_data(extract_legacy_data(tmp_path / "legacy"))
        first = load_valid_records(validation, engine, SCHEMA)
        second = load_valid_records(validation, engine, SCHEMA)
        assert second.loaded_counts == first.loaded_counts == table_counts(engine)
        assert sum(second.inserted_counts.values()) == 0
    finally:
        engine.dispose()
