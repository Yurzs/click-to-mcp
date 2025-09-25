"""Tests for the command-line interface."""

from __future__ import annotations

import subprocess
import types

import click
import pytest
from click.testing import CliRunner

from click_to_mcp import cli as cli_module
from click_to_mcp.loader import LoadedCommand, MissingDependencyError


@click.command()
def _dummy_cli():
    """Simple Click command used in tests."""


_dummy_module = types.ModuleType("dummy_module")
_dummy_module.cli = _dummy_cli


class DummyServer:
    async def get_tools(self):
        return []

    def run(self, *args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("Server.run should not be invoked in this test")


def test_cli_attempts_install_for_missing_dependency(monkeypatch):
    runner = CliRunner()

    load_calls = {"count": 0}

    def fake_load(reference: str, **kwargs):
        load_calls["count"] += 1
        if load_calls["count"] == 1:
            raise MissingDependencyError("samplepkg", reference)
        return LoadedCommand(
            command=_dummy_cli,
            module=_dummy_module,
            reference=reference,
        )

    installs: list[str] = []

    def fake_install(requirement: str) -> None:
        installs.append(requirement)

    monkeypatch.setattr(cli_module, "load_click_command", fake_load)
    monkeypatch.setattr(cli_module, "create_server", lambda *args, **kwargs: DummyServer())
    monkeypatch.setattr(cli_module, "_attempt_install", fake_install)

    result = runner.invoke(
        cli_module.main,
        ["samplepkg.cli:cli", "--list-tools"],
    )

    assert result.exit_code == 0
    assert installs == ["samplepkg"]
    assert load_calls["count"] == 2


def test_attempt_install_requires_uv(monkeypatch):
    monkeypatch.setattr(cli_module.shutil, "which", lambda _: None)

    with pytest.raises(click.ClickException) as excinfo:
        cli_module._attempt_install("pkg")

    assert "uv" in str(excinfo.value)


def test_attempt_install_failure_bubbles_up(monkeypatch):
    monkeypatch.setattr(cli_module.shutil, "which", lambda _: "uv")

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)

    with pytest.raises(click.ClickException) as excinfo:
        cli_module._attempt_install("pkg")

    assert "Failed to install" in str(excinfo.value)
