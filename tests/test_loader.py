"""Tests for module loading helpers."""

from __future__ import annotations

import types

import pytest

from click_to_mcp.loader import (
    ClickToMcpError,
    MissingDependencyError,
    load_click_command,
)


def test_load_click_command_explicit() -> None:
    loaded = load_click_command("tests.sample_cli:cli")
    assert loaded.command.name == "cli"
    assert isinstance(loaded.module, types.ModuleType)


def test_load_click_command_missing() -> None:
    with pytest.raises(ClickToMcpError):
        load_click_command("tests.sample_cli:missing")


def test_discover_without_attribute() -> None:
    loaded = load_click_command("tests.sample_cli")
    assert loaded.command.name == "cli"


def test_missing_module_error_contains_requirement() -> None:
    with pytest.raises(MissingDependencyError) as excinfo:
        load_click_command("nonexistent_package:cli")

    assert excinfo.value.requirement == "nonexistent_package"
