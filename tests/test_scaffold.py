"""Verify that every planned migration module can be imported after setup."""

from importlib import import_module

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "generate_legacy_data",
        "extract",
        "transform",
        "validate",
        "load",
        "reconcile",
        "cli",
        "config",
    ],
)
def test_migration_module_imports(module_name: str) -> None:
    """The installed package must expose each planned pipeline module."""
    module = import_module(f"migration.{module_name}")

    assert module.__doc__
