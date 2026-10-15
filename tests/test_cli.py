"""Verify the CLI through real subprocesses and synthetic SQLite migrations."""

import csv
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import URL

from migration.cli import main
from migration.config import PROJECT_ROOT
from migration.reconcile import REPORT_FILENAME


@pytest.fixture
def cli_environment(tmp_path: Path) -> dict[str, str]:
    return {
        **os.environ,
        "DATABASE_URL": URL.create(
            "sqlite", database=str(tmp_path / "portfolio.db")
        ).render_as_string(),
        "LEGACY_DATA_DIR": str(tmp_path / "legacy"),
        "OUTPUT_DATA_DIR": str(tmp_path / "output"),
        "SCHEMA_PATH": str(PROJECT_ROOT / "sql/schema.sql"),
        "CUSTOMER_COUNT": "20",
        "RANDOM_SEED": "42",
        "LOG_LEVEL": "INFO",
        "PYTHONIOENCODING": "utf-8",
    }


def invoke(
    arguments: list[str], directory: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Call the installed module from an unrelated working directory."""
    return subprocess.run(
        [sys.executable, "-m", "migration.cli", *arguments],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def database_counts(path: Path) -> tuple[int, int, int]:
    """Inspect the persisted portfolio after a CLI process exits."""
    with sqlite3.connect(path) as connection:
        return tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("customers", "loans", "payments")
        )


def test_generate_run_repeat_and_report_end_to_end(
    tmp_path: Path, cli_environment: dict[str, str]
) -> None:
    generated = invoke(["generate"], tmp_path, cli_environment)
    assert generated.returncode == 0, generated.stderr
    assert not (tmp_path / "portfolio.db").exists()
    legacy = tmp_path / "legacy"
    source_bytes = {path.name: path.read_bytes() for path in legacy.iterdir()}
    assert invoke(["generate"], tmp_path, cli_environment).returncode == 0
    assert source_bytes == {path.name: path.read_bytes() for path in legacy.iterdir()}

    first = invoke(["run"], tmp_path, cli_environment)
    assert first.returncode == 0, first.stderr
    assert "Reconciliation PASS" in first.stderr
    assert database_counts(tmp_path / "portfolio.db") == (13, 10, 19)
    with (tmp_path / "output/rejected_records.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        assert len(list(csv.DictReader(handle))) == 40
    assert "| customers | 13 | 0 |" in (
        tmp_path / "output" / REPORT_FILENAME
    ).read_text(encoding="utf-8")

    repeated = invoke(["run"], tmp_path, cli_environment)
    assert repeated.returncode == 0, repeated.stderr
    assert database_counts(tmp_path / "portfolio.db") == (13, 10, 19)
    report_path = tmp_path / "output" / REPORT_FILENAME
    content = report_path.read_text(encoding="utf-8")
    assert "| customers | 0 | 13 |" in content
    assert "| **Total** | 82 | 81 | 40 | 42 | **PASS** |" in content
    before = report_path.stat().st_mtime_ns
    displayed = invoke(
        ["report", "--log-level", "ERROR"],
        tmp_path,
        {
            **cli_environment,
            "DATABASE_URL": "mysql+pymysql://demo:placeholder@unreachable.invalid/portfolio",
        },
    )
    assert displayed.returncode == 0, displayed.stderr
    assert displayed.stdout == content
    assert report_path.stat().st_mtime_ns == before
    assert source_bytes == {path.name: path.read_bytes() for path in legacy.iterdir()}


def test_flags_override_environment_and_paths_resolve_from_cwd(
    tmp_path: Path, cli_environment: dict[str, str]
) -> None:
    # Invalid configured values are replaced by valid command arguments before parsing.
    environment = {
        **cli_environment,
        "CUSTOMER_COUNT": "invalid",
        "RANDOM_SEED": "invalid",
    }
    result = invoke(
        ["generate", "--size", "40", "--seed", "7", "--output-dir", "custom"],
        tmp_path,
        environment,
    )
    assert result.returncode == 0, result.stderr
    with (tmp_path / "custom/customers_legacy.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        assert len(list(csv.DictReader(handle))) == 44
    assert not (tmp_path / "legacy").exists()
    result = invoke(
        [
            "run",
            "--input-dir",
            "custom",
            "--output-dir",
            "reports",
            "--schema-path",
            str(PROJECT_ROOT / "sql/schema.sql"),
        ],
        tmp_path,
        cli_environment,
    )
    assert result.returncode == 0, result.stderr
    assert database_counts(tmp_path / "portfolio.db") == (26, 20, 38)
    assert (tmp_path / "reports" / REPORT_FILENAME).exists()
    assert not (tmp_path / "output").exists()
    assert (
        invoke(
            ["report", "--output-dir", "reports"], tmp_path, cli_environment
        ).returncode
        == 0
    )


def test_changed_snapshot_fails_and_report_shows_incomplete_status(
    tmp_path: Path, cli_environment: dict[str, str]
) -> None:
    assert invoke(["generate"], tmp_path, cli_environment).returncode == 0
    assert invoke(["run"], tmp_path, cli_environment).returncode == 0
    counts = database_counts(tmp_path / "portfolio.db")
    assert (
        invoke(["generate", "--seed", "7"], tmp_path, cli_environment).returncode == 0
    )
    failed = invoke(["run"], tmp_path, cli_environment)
    assert failed.returncode == 1
    assert "Changed existing" in failed.stderr
    assert "Traceback" not in failed.stderr
    assert database_counts(tmp_path / "portfolio.db") == counts
    reported = invoke(["report"], tmp_path, cli_environment)
    assert reported.returncode == 1
    assert "**Overall status: FAIL**" in reported.stdout
    assert "has not completed" in reported.stdout


@pytest.mark.parametrize(
    "arguments, expected_code",
    [
        (["--help"], 0),
        (["generate", "--help"], 0),
        (["run", "--help"], 0),
        (["report", "--help"], 0),
        ([], 2),
        (["unknown"], 2),
        (["generate", "--customers", "many"], 2),
        (["run", "--unknown"], 2),
    ],
)
def test_help_and_usage_errors_do_not_create_artifacts(
    tmp_path: Path,
    cli_environment: dict[str, str],
    arguments: list[str],
    expected_code: int,
) -> None:
    result = invoke(arguments, tmp_path, cli_environment)
    assert result.returncode == expected_code
    assert "usage:" in result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "arguments, expected_error",
    [
        (["generate", "--customers", "0"], "CUSTOMER_COUNT must be at least 1"),
        (["report"], "Run 'run' first"),
        (["run"], "Run the generator"),
    ],
)
def test_operational_failures_are_helpful_and_nonzero(
    tmp_path: Path,
    cli_environment: dict[str, str],
    arguments: list[str],
    expected_error: str,
) -> None:
    result = invoke(arguments, tmp_path, cli_environment)
    assert result.returncode == 1
    assert expected_error in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "content",
    [
        "# Missing status\n",
        "**Overall status: UNKNOWN**\n",
        "**Overall status: PASS**\n**Overall status: FAIL**\n",
    ],
)
def test_unrecognized_report_is_not_reported_as_success(
    tmp_path: Path, cli_environment: dict[str, str], content: str
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    path = output / REPORT_FILENAME
    path.write_text(content, encoding="utf-8")
    result = invoke(["report"], tmp_path, cli_environment)
    assert result.returncode == 1
    assert "no recognized overall status" in result.stderr
    assert path.read_text(encoding="utf-8") == content
    assert not (tmp_path / "portfolio.db").exists()


def test_configuration_errors_do_not_expose_connection_secrets(
    tmp_path: Path, cli_environment: dict[str, str]
) -> None:
    result = invoke(
        ["run"],
        tmp_path,
        {
            **cli_environment,
            "DATABASE_URL": "mysql+pymysql://demo:synthetic-private-token@localhost:notaport/db",
        },
    )
    assert result.returncode == 1
    assert "synthetic-private-token" not in result.stderr + result.stdout
    assert "DATABASE_URL" in result.stderr


def test_accounting_fail_exits_nonzero_after_complete_report(
    tmp_path: Path,
    cli_environment: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from migration.load import load_valid_records

    for variable, value in cli_environment.items():
        monkeypatch.setenv(variable, value)
    assert main(["generate"]) == 0

    def inconsistent_load(*args, **kwargs):
        result = load_valid_records(*args, **kwargs)
        result.inserted_counts["payments"] -= 1
        return result

    monkeypatch.setattr("migration.reconcile.load_valid_records", inconsistent_load)
    assert main(["run"]) == 1
    assert main(["report"]) == 1
    assert "read = loaded + rejected" in capsys.readouterr().out
