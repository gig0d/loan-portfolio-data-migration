"""Create the SQL schema and load accepted records in one repeatable transaction."""

import argparse
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, event, select
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from migration.config import load_settings
from migration.extract import LEGACY_FILES
from migration.validate import ID_FIELDS, ValidationResult, run_validation

logger = logging.getLogger(__name__)
MAX_AMOUNT_CENTS = 9_000_000_000_000_000
MONEY_FIELDS = {"loans": "principal_amount", "payments": "amount"}
TEXT_LIMITS = {
    "customer_id": 64,
    "loan_id": 64,
    "payment_id": 64,
    "full_name": 200,
    "email": 254,
    "country_code": 2,
    "status": 6,
}


@dataclass(frozen=True)
class LoadResult:
    """Count accepted records inserted or already present with identical values."""

    inserted_counts: dict[str, int]
    existing_counts: dict[str, int]

    @property
    def loaded_counts(self) -> dict[str, int]:
        """Count this run's accepted records confirmed in the database."""
        return {
            table: self.inserted_counts[table] + self.existing_counts[table]
            for table in LEGACY_FILES
        }


def create_database_engine(database_url: URL) -> Engine:
    """Create an engine with SQLite foreign-key enforcement enabled."""
    if database_url.get_backend_name() == "sqlite" and database_url.database:
        if database_url.database != ":memory:":
            Path(database_url.database).parent.mkdir(parents=True, exist_ok=True)
    connection_options = (
        {"charset": "utf8mb4"} if database_url.get_backend_name() == "mysql" else {}
    )
    engine = create_engine(
        database_url, hide_parameters=True, connect_args=connection_options
    )
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection: Any, connection_record: Any) -> None:
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        @event.listens_for(engine, "begin")
        def begin_sqlite(connection: Connection) -> None:
            connection.exec_driver_sql("BEGIN")

    return engine


def create_schema(engine: Engine, schema_path: Path) -> dict[str, Table]:
    """Execute the trusted project SQL file, then reflect the target tables."""
    sql = schema_path.read_text(encoding="utf-8")
    statements = [
        statement.strip() for statement in sql.split(";") if statement.strip()
    ]
    with engine.begin() as connection:
        if engine.dialect.name == "mysql":
            version = engine.dialect.server_version_info
            if engine.dialect.is_mariadb or version < (8, 0, 16):
                raise ValueError(
                    "This schema requires MySQL 8.0.16+; MariaDB is untested."
                )
        for statement in statements:
            if engine.dialect.name == "mysql":
                statement += " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            connection.exec_driver_sql(statement)
        metadata = MetaData()
        tables = {
            name: Table(name, metadata, autoload_with=connection)
            for name in LEGACY_FILES
        }
        if engine.dialect.name == "mysql":
            for table in tables.values():
                if table.dialect_options["mysql"].get("engine", "").upper() != "INNODB":
                    raise ValueError("Existing target tables must use InnoDB.")
    return tables


def amount_to_cents(value: Decimal) -> int:
    """Convert a positive cent-precision Decimal within the storage limit exactly."""
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value.as_tuple().exponent < -2
        or value <= 0
        or value > Decimal(MAX_AMOUNT_CENTS) / 100
    ):
        raise ValueError(
            "Money must be positive, have at most two decimals, and fit BIGINT cents."
        )
    return int(value * 100)


def _database_record(table: str, source: dict[str, object]) -> dict[str, object]:
    record = {field: source[field] for field in LEGACY_FILES[table][1]}
    for field, value in record.items():
        if field in TEXT_LIMITS:
            if (
                not isinstance(value, str)
                or not value
                or len(value) > TEXT_LIMITS[field]
            ):
                raise ValueError(
                    f"{table}.{field} must contain 1-{TEXT_LIMITS[field]} characters."
                )
        elif field not in MONEY_FIELDS.values() and type(value) is not date:
            raise ValueError(f"{table}.{field} must be a calendar date.")
    if table in MONEY_FIELDS:
        field = MONEY_FIELDS[table]
        record[f"{field}_cents"] = amount_to_cents(record.pop(field))
    return record


def load_valid_records(
    validation: ValidationResult, engine: Engine, schema_path: Path
) -> LoadResult:
    """Insert accepted parents before children; roll back on any changed ID or error."""
    inserted = dict.fromkeys(LEGACY_FILES, 0)
    existing = dict.fromkeys(LEGACY_FILES, 0)
    try:
        tables = create_schema(engine, schema_path)
        with engine.begin() as connection:
            for name, table in tables.items():
                id_field = ID_FIELDS[name]
                stored = {
                    row[id_field]: dict(row)
                    for row in connection.execute(select(table)).mappings()
                }
                records = [
                    _database_record(name, row)
                    for row in validation.valid_tables[name].to_dict(orient="records")
                ]
                new_records = []
                for record in records:
                    identity = record[id_field]
                    if identity in stored:
                        if record != stored[identity]:
                            raise ValueError(
                                f"Changed existing {name} ID {identity}; "
                                "no records were committed. Use a separate database "
                                "for a different synthetic snapshot."
                            )
                        existing[name] += 1
                    else:
                        new_records.append(record)
                if new_records:
                    connection.execute(table.insert(), new_records)
                inserted[name] = len(new_records)
    except SQLAlchemyError as exc:
        raise ValueError(
            "Database load failed; no new portfolio records were committed. "
            "Check connectivity, permissions, target schema, and integrity constraints."
        ) from exc
    result = LoadResult(inserted, existing)
    for table in LEGACY_FILES:
        logger.info(
            "Loaded %s: %s inserted; %s already present; %s accepted confirmed",
            table,
            inserted[table],
            existing[table],
            result.loaded_counts[table],
        )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Validate legacy CSVs and load them using environment-based configuration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--schema-path", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    engine = None
    try:
        settings = load_settings()
        logging.getLogger().setLevel(settings.log_level)
        validation = run_validation(
            args.input_dir or settings.legacy_data_dir,
            args.output_dir or settings.output_data_dir,
        )
        engine = create_database_engine(settings.database_url)
        load_valid_records(validation, engine, args.schema_path or settings.schema_path)
    except (ValueError, OSError, SQLAlchemyError) as exc:
        # Driver errors can contain connection details; do not log them directly.
        message = (
            "Could not connect to the configured database."
            if isinstance(exc, SQLAlchemyError)
            else str(exc)
        )
        logger.error("Load failed: %s", message)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
