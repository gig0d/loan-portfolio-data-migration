"""Check source accounting, rejection counts, and committed SQLite load reports."""

import json
from pathlib import Path

import pytest
from sqlalchemy.engine import URL

from migration.config import PROJECT_ROOT
from migration.extract import extract_legacy_data
from migration.generate_legacy_data import generate_legacy_data
from migration.load import LoadResult, create_database_engine
from migration.reconcile import (
    REPORT_FILENAME,
    main,
    reconcile,
    render_report,
    run_reconciliation,
    write_report,
)
from migration.validate import ValidationResult, validate_legacy_data


@pytest.fixture
def validation(tmp_path: Path) -> ValidationResult:
    generate_legacy_data(tmp_path / "legacy", customer_count=20, seed=42)
    return validate_legacy_data(extract_legacy_data(tmp_path / "legacy"))


def successful_load(validation: ValidationResult) -> LoadResult:
    """Supply committed-outcome counts to the pure accounting unit tests."""
    return LoadResult(
        {table: len(frame) for table, frame in validation.valid_tables.items()},
        dict.fromkeys(validation.valid_tables, 0),
    )


def test_default_data_reconciles_after_first_and_repeat_loads(tmp_path: Path) -> None:
    input_dir = tmp_path / "legacy"
    output_dir = tmp_path / "output"
    generate_legacy_data(input_dir, customer_count=1000, seed=42)
    engine = create_database_engine(
        URL.create("sqlite", database=str(tmp_path / "test.db"))
    )
    try:
        first = run_reconciliation(
            input_dir, output_dir, engine, PROJECT_ROOT / "sql/schema.sql"
        )
        repeated = run_reconciliation(
            input_dir, output_dir, engine, PROJECT_ROOT / "sql/schema.sql"
        )
    finally:
        engine.dispose()
    assert first.passed and repeated.passed
    assert [
        (row.read, row.cleaned, row.rejected, row.loaded) for row in first.tables
    ] == [(1100, 1050, 450, 650), (1000, 1000, 500, 500), (2000, 2000, 1050, 950)]
    assert [row.inserted for row in first.tables] == [650, 500, 950]
    assert [row.inserted for row in repeated.tables] == [0, 0, 0]
    assert [row.already_present for row in repeated.tables] == [650, 500, 950]
    text = (output_dir / REPORT_FILENAME).read_text(encoding="utf-8")
    assert "**Overall status: PASS**" in text
    assert "| **Total** | 4100 | 4050 | 2000 | 2100 | **PASS** |" in text
    assert "| customers | 0 | 650 |" in text
    assert "VR013_EXACT_DUPLICATE" in text
    assert "@example.com" not in text


def test_one_missing_load_outcome_fails(validation: ValidationResult) -> None:
    load = successful_load(validation)
    load.inserted_counts["payments"] -= 1
    result = reconcile(validation, load)
    assert not result.passed
    assert "read = loaded + rejected" in result.tables[2].failures
    assert "**Overall status: FAIL**" in render_report(result)


def test_opposite_table_errors_cannot_cancel(validation: ValidationResult) -> None:
    load = successful_load(validation)
    load.inserted_counts["customers"] += 1
    load.inserted_counts["payments"] -= 1
    result = reconcile(validation, load)
    assert sum(row.read for row in result.tables) == sum(
        row.loaded + row.rejected for row in result.tables
    )
    assert not result.passed
    assert not result.tables[0].passed and not result.tables[2].passed


def test_balanced_counts_do_not_hide_duplicate_source_outcomes(
    validation: ValidationResult,
) -> None:
    load = successful_load(validation)
    accepted = validation.valid_tables["customers"]
    accepted.loc[1, "_source_row"] = accepted.loc[0, "_source_row"]
    result = reconcile(validation, load)
    assert not result.passed
    assert result.tables[0].read == result.tables[0].loaded + result.tables[0].rejected
    assert "exactly one" in " ".join(result.tables[0].failures)


def test_missing_exact_duplicate_accounting_fails(validation: ValidationResult) -> None:
    validation.transformation.read_counts["customers"] += 1
    result = reconcile(validation, successful_load(validation))
    assert not result.passed
    assert "read = cleaned + exact duplicates removed" in result.tables[0].failures


def test_primary_rule_breakdown_counts_records_once(
    validation: ValidationResult,
) -> None:
    validation.rejected_records.loc[0, "violations"] = json.dumps(
        [{"rule": "VR001_INVALID_EMAIL"}, {"rule": "VR002_INVALID_COUNTRY_CODE"}]
    )
    result = reconcile(validation, successful_load(validation))
    assert sum(count for _, _, count in result.rejections_by_rule) == len(
        validation.rejected_records
    )
    for table, rule, count in result.rejections_by_rule:
        assert count == len(
            validation.rejected_records.loc[
                (validation.rejected_records["table"] == table)
                & (validation.rejected_records["rule"] == rule)
            ]
        )


@pytest.mark.parametrize("scenario", ["empty", "all_rejected"])
def test_zero_loaded_can_pass_when_every_source_is_accounted_for(
    tmp_path: Path, scenario: str
) -> None:
    generate_legacy_data(tmp_path / "legacy", customer_count=20)
    raw = extract_legacy_data(tmp_path / "legacy")
    if scenario == "empty":
        raw = {table: frame.iloc[:0].copy() for table, frame in raw.items()}
    else:
        raw["customers"]["full_name"] = ""
    validation = validate_legacy_data(raw)
    result = reconcile(validation, successful_load(validation))
    assert result.passed
    assert sum(row.loaded for row in result.tables) == 0
    text = render_report(result)
    assert "**Overall status: PASS**" in text
    if scenario == "empty":
        assert "No rejections | 0" in text
    else:
        assert sum(row.rejected for row in result.tables) > 0


@pytest.mark.parametrize("bad_count", [-1, 0.5, True])
def test_invalid_outcome_counts_are_rejected(
    validation: ValidationResult, bad_count: object
) -> None:
    load = successful_load(validation)
    load.inserted_counts["customers"] = bad_count
    with pytest.raises(ValueError, match="nonnegative integers"):
        reconcile(validation, load)


def test_missing_table_is_not_silently_ignored(validation: ValidationResult) -> None:
    load = successful_load(validation)
    del load.existing_counts["payments"]
    with pytest.raises(ValueError, match="all three"):
        reconcile(validation, load)


def test_unknown_rejection_table_is_not_silently_ignored(
    validation: ValidationResult,
) -> None:
    validation.rejected_records.loc[0, "table"] = "unexpected"
    with pytest.raises(ValueError, match="unknown source table"):
        reconcile(validation, successful_load(validation))


def test_failed_load_cannot_leave_an_old_pass_report(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    output = tmp_path / "output"
    generate_legacy_data(source, customer_count=20, seed=42)
    engine = create_database_engine(
        URL.create("sqlite", database=str(tmp_path / "test.db"))
    )
    try:
        assert run_reconciliation(
            source, output, engine, PROJECT_ROOT / "sql/schema.sql"
        ).passed
        generate_legacy_data(source, customer_count=20, seed=7)
        with pytest.raises(ValueError, match="Changed existing"):
            run_reconciliation(source, output, engine, PROJECT_ROOT / "sql/schema.sql")
    finally:
        engine.dispose()
    report = (output / REPORT_FILENAME).read_text(encoding="utf-8")
    assert "**Overall status: FAIL**" in report
    assert "has not completed" in report
    assert "**Overall status: PASS**" not in report


def test_report_replacement_cleans_up_temporary_files(tmp_path: Path) -> None:
    path = write_report("First report\n", tmp_path)
    assert write_report("Replacement report\n", tmp_path) == path
    assert path.read_bytes() == b"Replacement report\n"
    assert list(tmp_path.iterdir()) == [path]


def test_report_write_errors_name_the_destination(tmp_path: Path) -> None:
    blocked = tmp_path / "not_a_directory"
    blocked.write_text("Synthetic fixture", encoding="utf-8")
    with pytest.raises(OSError, match="Could not write migration report"):
        write_report("Report", blocked)


def test_command_uses_configured_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate_legacy_data(tmp_path / "legacy", customer_count=20)
    monkeypatch.setenv(
        "DATABASE_URL",
        URL.create("sqlite", database=str(tmp_path / "test.db")).render_as_string(),
    )
    monkeypatch.setenv("LEGACY_DATA_DIR", str(tmp_path / "legacy"))
    monkeypatch.setenv("OUTPUT_DATA_DIR", str(tmp_path / "output"))
    assert main([]) == 0
    assert (tmp_path / "output" / REPORT_FILENAME).exists()


def test_command_returns_nonzero_and_marks_incomplete_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        URL.create("sqlite", database=str(tmp_path / "test.db")).render_as_string(),
    )
    monkeypatch.setenv("OUTPUT_DATA_DIR", str(tmp_path / "output"))
    assert main(["--input-dir", str(tmp_path / "missing")]) == 1
    assert "Run the generator" in caplog.text
    assert "**Overall status: FAIL**" in (
        tmp_path / "output" / REPORT_FILENAME
    ).read_text(encoding="utf-8")
