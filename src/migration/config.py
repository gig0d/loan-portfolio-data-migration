"""Read local configuration without exposing credentials or changing the environment."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    """Hold resolved paths and the database connection for a checkout."""

    database_url: URL
    legacy_data_dir: Path
    output_data_dir: Path
    schema_path: Path
    log_level: str


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def load_settings(
    project_root: Path = PROJECT_ROOT,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Read .env with environment overrides; resolve paths from the project root."""
    root = project_root.resolve()
    values = {
        key: value
        for key, value in dotenv_values(root / ".env").items()
        if value is not None
    }
    values.update(os.environ if environ is None else environ)
    try:
        url = make_url(
            values.get("DATABASE_URL", "sqlite:///data/output/loan_portfolio.db")
        )
    except (ArgumentError, ValueError) as exc:
        raise ValueError(
            "DATABASE_URL must be a valid SQLAlchemy connection URL."
        ) from exc
    if url.drivername not in {"sqlite", "sqlite+pysqlite", "mysql+pymysql"}:
        raise ValueError("Use SQLite or mysql+pymysql in DATABASE_URL.")
    if url.get_backend_name() == "sqlite":
        if url.host or url.username or url.password or url.query:
            raise ValueError(
                "SQLite requires a plain file URL without connection options."
            )
        if url.database and url.database != ":memory:":
            url = url.set(database=_resolve_path(root, url.database).as_posix())
    elif not url.database or not url.host or not url.username:
        raise ValueError("MySQL DATABASE_URL requires a host, user, and database name.")
    log_level = values.get("LOG_LEVEL", "INFO").upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.")
    return Settings(
        database_url=url,
        legacy_data_dir=_resolve_path(
            root, values.get("LEGACY_DATA_DIR", "data/legacy")
        ),
        output_data_dir=_resolve_path(
            root, values.get("OUTPUT_DATA_DIR", "data/output")
        ),
        schema_path=_resolve_path(root, values.get("SCHEMA_PATH", "sql/schema.sql")),
        log_level=log_level,
    )
