"""Read legacy CSV exports as text while preserving source record numbers."""

import logging
import warnings
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

LEGACY_FILES: dict[str, tuple[str, tuple[str, ...]]] = {
    "customers": (
        "customers_legacy.csv",
        ("customer_id", "full_name", "email", "country_code", "date_of_birth"),
    ),
    "loans": (
        "loans_legacy.csv",
        ("loan_id", "customer_id", "principal_amount", "start_date", "status"),
    ),
    "payments": (
        "payments_legacy.csv",
        ("payment_id", "loan_id", "amount", "payment_date"),
    ),
}


def read_legacy_csv(path: Path, expected_columns: tuple[str, ...]) -> pd.DataFrame:
    """Read a CSV without type inference or silently dropping malformed records."""
    if not path.is_file():
        raise FileNotFoundError(f"Legacy export not found: {path}. Run the generator.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", pd.errors.ParserWarning)
            frame = pd.read_csv(
                path,
                dtype=str,
                keep_default_na=False,
                na_filter=False,
                skip_blank_lines=False,
                index_col=False,
                encoding="utf-8-sig",
                on_bad_lines="error",
            )
    except (
        pd.errors.ParserError,
        pd.errors.EmptyDataError,
        pd.errors.ParserWarning,
        UnicodeError,
    ) as exc:
        raise ValueError(f"Could not parse legacy CSV {path}: {exc}") from exc
    except OSError as exc:
        raise OSError(f"Could not read legacy CSV {path}: {exc}") from exc

    missing = sorted(set(expected_columns) - set(frame.columns))
    unexpected = sorted(set(frame.columns) - set(expected_columns))
    if missing or unexpected:
        raise ValueError(
            f"Unexpected columns in {path}. Missing: {missing}; extra: {unexpected}."
        )

    frame = frame.loc[:, list(expected_columns)].copy()
    frame.insert(0, "_source_row", range(2, len(frame) + 2))
    logger.info("Read %s: %s source records", path.name, len(frame))
    return frame


def extract_legacy_data(input_dir: Path) -> dict[str, pd.DataFrame]:
    """Read all three exports using the expected legacy column contract."""
    return {
        table: read_legacy_csv(input_dir / filename, columns)
        for table, (filename, columns) in LEGACY_FILES.items()
    }
