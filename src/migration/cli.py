"""Generate synthetic exports, run the migration, or read its saved report."""

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from migration.config import Settings, load_settings
from migration.generate_legacy_data import generate_legacy_data
from migration.load import create_database_engine
from migration.reconcile import REPORT_FILENAME, run_reconciliation

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser(
        "generate", help="Create reproducible synthetic CSVs."
    )
    generate.add_argument(
        "--customers",
        "--size",
        type=int,
        help="Base customers; defaults to CUSTOMER_COUNT (1000).",
    )
    generate.add_argument("--seed", type=int, help="Defaults to RANDOM_SEED (42).")
    generate.add_argument(
        "--output-dir", type=Path, help="CSV destination; defaults to LEGACY_DATA_DIR."
    )
    run = commands.add_parser("run", help="Validate, load, and reconcile legacy CSVs.")
    run.add_argument("--input-dir", type=Path, help="Defaults to LEGACY_DATA_DIR.")
    run.add_argument("--output-dir", type=Path, help="Defaults to OUTPUT_DATA_DIR.")
    run.add_argument("--schema-path", type=Path, help="Defaults to SCHEMA_PATH.")
    report = commands.add_parser(
        "report", help="Display the saved report without a migration."
    )
    report.add_argument(
        "--output-dir", type=Path, help="Report directory; defaults to OUTPUT_DATA_DIR."
    )
    for command in (generate, run, report):
        command.add_argument(
            "--log-level",
            choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
            help="Override LOG_LEVEL for this command.",
        )
    return parser


def _command_settings(args: argparse.Namespace) -> Settings:
    paths = {
        "output_dir": "LEGACY_DATA_DIR"
        if args.command == "generate"
        else "OUTPUT_DATA_DIR",
        "input_dir": "LEGACY_DATA_DIR",
        "schema_path": "SCHEMA_PATH",
    }
    overrides = {}
    for flag, variable in paths.items():
        value = getattr(args, flag, None)
        if value is not None:
            overrides[variable] = str(value.resolve())
    for flag, variable in (
        ("customers", "CUSTOMER_COUNT"),
        ("seed", "RANDOM_SEED"),
        ("log_level", "LOG_LEVEL"),
    ):
        value = getattr(args, flag, None)
        if value is not None:
            overrides[variable] = str(value)
    return load_settings(environ={**os.environ, **overrides})


def _run(settings: Settings) -> int:
    engine = create_database_engine(settings.database_url)
    try:
        result = run_reconciliation(
            settings.legacy_data_dir,
            settings.output_data_dir,
            engine,
            settings.schema_path,
        )
    finally:
        engine.dispose()
    return 0 if result.passed else 1


def _show_report(output_dir: Path) -> int:
    path = output_dir / REPORT_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"Migration report not found: {path}. Run 'run' first.")
    content = path.read_text(encoding="utf-8")
    statuses = [
        line.strip()
        for line in content.splitlines()
        if line.strip().startswith("**Overall status:")
    ]
    if len(statuses) != 1 or statuses[0] not in {
        "**Overall status: PASS**",
        "**Overall status: FAIL**",
    }:
        raise ValueError(
            "Saved report has no recognized overall status. Run 'run' to regenerate it."
        )
    # The requested report is command output; operational events use logging.
    sys.stdout.write(content)
    logger.info("Displayed saved report: %s", path)
    return 0 if statuses[0] == "**Overall status: PASS**" else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command; return 0 for success, 1 for failure, or 2 for usage errors."""
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        settings = _command_settings(args)
        logging.getLogger().setLevel(settings.log_level)
        if args.command == "generate":
            generate_legacy_data(
                settings.legacy_data_dir, settings.customer_count, settings.random_seed
            )
            return 0
        if args.command == "run":
            return _run(settings)
        return _show_report(settings.output_data_dir)
    except (OSError, UnicodeError, ValueError, SQLAlchemyError) as exc:
        message = (
            "Could not connect to the configured database."
            if isinstance(exc, SQLAlchemyError)
            else str(exc)
        )
        logger.error("%s failed: %s", args.command, message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
