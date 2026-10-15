"""Check environment precedence, stable paths, and safe configuration errors."""

from pathlib import Path

import pytest

from migration.config import load_settings


def test_defaults_resolve_from_checkout_not_working_directory(tmp_path: Path) -> None:
    settings = load_settings(tmp_path, environ={})
    assert (
        settings.database_url.database
        == (tmp_path / "data/output/loan_portfolio.db").as_posix()
    )
    assert settings.legacy_data_dir == tmp_path / "data/legacy"
    assert settings.schema_path == tmp_path / "sql/schema.sql"
    assert settings.customer_count == 1000
    assert settings.random_seed == 42


def test_environment_overrides_dotenv_without_mutating_it(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OUTPUT_DATA_DIR=local\nLOG_LEVEL=WARNING\n", encoding="utf-8")
    settings = load_settings(tmp_path, environ={"OUTPUT_DATA_DIR": "override"})
    assert settings.output_data_dir == tmp_path / "override"
    assert settings.log_level == "WARNING"
    assert "OUTPUT_DATA_DIR=local" in env_file.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url-with-secret",
        "postgresql://localhost/db",
        "mysql+pymysql://localhost",
        "sqlite:///db?mode=ro",
    ],
)
def test_bad_database_configuration_has_safe_error(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValueError) as error:
        load_settings(tmp_path, environ={"DATABASE_URL": url})
    assert url not in str(error.value)


def test_mysql_credentials_are_parsed_but_redacted(tmp_path: Path) -> None:
    settings = load_settings(
        tmp_path,
        environ={
            "DATABASE_URL": "mysql+pymysql://demo:synthetic-password@localhost/portfolio"
        },
    )
    assert settings.database_url.password == "synthetic-password"
    assert "synthetic-password" not in str(settings.database_url)


def test_invalid_log_level_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        load_settings(tmp_path, environ={"LOG_LEVEL": "QUIET"})


@pytest.mark.parametrize(
    "values, message",
    [
        ({"CUSTOMER_COUNT": "0"}, "CUSTOMER_COUNT must be at least 1"),
        ({"CUSTOMER_COUNT": "many"}, "CUSTOMER_COUNT must be an integer"),
        ({"RANDOM_SEED": "invalid"}, "RANDOM_SEED must be an integer"),
    ],
)
def test_generation_settings_are_validated(
    tmp_path: Path, values: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        load_settings(tmp_path, environ=values)


def test_generation_environment_overrides_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "CUSTOMER_COUNT=20\nRANDOM_SEED=7\n", encoding="utf-8"
    )
    settings = load_settings(tmp_path, environ={"RANDOM_SEED": "42"})
    assert settings.customer_count == 20
    assert settings.random_seed == 42
