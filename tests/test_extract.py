"""Verify text preservation, CSV contracts, and useful extraction failures."""

from pathlib import Path

import pytest

from migration.extract import extract_legacy_data, read_legacy_csv
from migration.generate_legacy_data import generate_legacy_data


def test_extraction_preserves_text_blanks_and_source_records(tmp_path: Path) -> None:
    source = tmp_path / "text.csv"
    source.write_text("id,value\n0001,NA\n0002,\n0003,  text  \n", encoding="utf-8")

    frame = read_legacy_csv(source, ("id", "value"))

    assert frame["id"].tolist() == ["0001", "0002", "0003"]
    assert frame["value"].tolist() == ["NA", "", "  text  "]
    assert frame["_source_row"].tolist() == [2, 3, 4]


def test_blank_records_are_not_silently_skipped(tmp_path: Path) -> None:
    source = tmp_path / "blanks.csv"
    source.write_text("id,value\n0001,text\n\n0002,other\n", encoding="utf-8")

    frame = read_legacy_csv(source, ("id", "value"))

    assert len(frame) == 3
    assert frame.iloc[1]["id"] == ""
    assert frame["_source_row"].tolist() == [2, 3, 4]


def test_header_only_export_is_allowed(tmp_path: Path) -> None:
    source = tmp_path / "empty.csv"
    source.write_text("id,value\n", encoding="utf-8")

    frame = read_legacy_csv(source, ("id", "value"))

    assert frame.empty
    assert frame.columns.tolist() == ["_source_row", "id", "value"]


@pytest.mark.parametrize("header", ["id", "id,value,extra", "id,value,value"])
def test_unexpected_columns_fail_with_file_context(tmp_path: Path, header: str) -> None:
    source = tmp_path / "wrong_columns.csv"
    source.write_text(header + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unexpected columns.*wrong_columns.csv"):
        read_legacy_csv(source, ("id", "value"))


@pytest.mark.parametrize(
    "contents", ["", "id,value\n1,text,extra\n", 'id,value\n1,"open']
)
def test_malformed_files_fail_instead_of_losing_fields(
    tmp_path: Path, contents: str
) -> None:
    source = tmp_path / "broken.csv"
    source.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match="Could not parse legacy CSV.*broken.csv"):
        read_legacy_csv(source, ("id", "value"))


def test_missing_export_has_actionable_message(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Run the generator"):
        extract_legacy_data(tmp_path)


def test_all_generated_exports_match_the_extraction_contract(tmp_path: Path) -> None:
    generate_legacy_data(tmp_path, customer_count=20)

    tables = extract_legacy_data(tmp_path)

    assert set(tables) == {"customers", "loans", "payments"}
    assert {table: len(frame) for table, frame in tables.items()} == {
        "customers": 22,
        "loans": 20,
        "payments": 40,
    }
