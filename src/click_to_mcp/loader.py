"""Utilities for loading Click command objects from Python references."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterator

import click


class ClickToMcpError(RuntimeError):
    """Base error raised by the Click-to-MCP adapter."""


@dataclass(slots=True)
class LoadedCommand:
    """Represents a loaded Click command along with its origin metadata."""

    command: click.Command
    module: ModuleType
    reference: str


@contextmanager
def _temp_sys_path(path: Path) -> Iterator[None]:
    """Temporarily prepend a path to :data:`sys.path`."""

    path_str = str(path)
    if path_str in sys.path:
        yield
        return
    sys.path.insert(0, path_str)
    try:
        yield
    finally:
        try:
            sys.path.remove(path_str)
        except ValueError:  # pragma: no cover - defensive
            pass


def _load_module(module_ref: str) -> ModuleType:
    """Load a module from a module path or filesystem reference."""

    potential_path = Path(module_ref)
    if potential_path.exists() and potential_path.suffix == ".py":
        module_name = potential_path.stem
        spec = importlib.util.spec_from_file_location(module_name, potential_path)
        if spec is None or spec.loader is None:
            msg = f"Unable to create module spec for '{module_ref}'."
            raise ClickToMcpError(msg)
        module = importlib.util.module_from_spec(spec)
        with _temp_sys_path(potential_path.parent):
            spec.loader.exec_module(module)
        return module

    try:
        return importlib.import_module(module_ref)
    except ModuleNotFoundError as exc:  # pragma: no cover - pass-through
        fallback_path = Path(*module_ref.split(".")).with_suffix(".py")
        if fallback_path.exists():
            return _load_module(str(fallback_path))
        raise ClickToMcpError(f"Unable to import module '{module_ref}'.") from exc


def _resolve_attribute(module: ModuleType, attribute_path: str | None) -> object:
    """Resolve an attribute path like ``foo.bar`` on the provided module."""

    if not attribute_path:
        return None

    value: object = module
    for part in attribute_path.split("."):
        if not hasattr(value, part):
            msg = f"Module '{module.__name__}' does not define attribute '{attribute_path}'."
            raise ClickToMcpError(msg)
        value = getattr(value, part)
    return value


def load_click_command(reference: str, *, default_attribute: str | None = "cli") -> LoadedCommand:
    """Load a Click command from a ``module:attribute`` style reference.

    Parameters
    ----------
    reference:
        A string pointing to the Click application. The value should follow
        ``module:attribute`` semantics (for example ``"mypackage.cli:app"``).
        When the attribute is omitted, ``default_attribute`` is attempted. If
        that also fails, the loader falls back to discovering exactly one Click
        command defined in the module.
    default_attribute:
        Name of the attribute to look up when the reference omits an explicit
        attribute component. Pass ``None`` to disable the fallback lookup.

    Returns
    -------
    LoadedCommand
        The loaded Click command together with information about its origin.

    Raises
    ------
    ClickToMcpError
        If the reference cannot be resolved to a Click command.
    """

    module_ref, _, attribute_path = reference.partition(":")
    module = _load_module(module_ref)

    candidate = _resolve_attribute(module, attribute_path) if attribute_path else None
    if candidate is None and default_attribute:
        candidate = getattr(module, default_attribute, None)

    if candidate is None:
        candidate = _discover_single_click_command(module)

    if not isinstance(candidate, click.Command):
        msg = (
            f"Reference '{reference}' does not resolve to a Click command."
        )
        raise ClickToMcpError(msg)

    return LoadedCommand(command=candidate, module=module, reference=reference)


def _discover_single_click_command(module: ModuleType) -> click.Command | None:
    """Attempt to find a single Click command defined in *module*."""

    commands = [value for value in vars(module).values() if isinstance(value, click.Command)]
    if not commands:
        return None
    if len(commands) == 1:
        return commands[0]

    callable_commands = [
        cmd for cmd in commands if inspect.getmodule(cmd) is module
    ]
    if len(callable_commands) == 1:
        return callable_commands[0]

    msg = (
        f"Module '{module.__name__}' defines multiple Click commands. Provide an "
        "explicit attribute reference (e.g. 'module:command')."
    )
    raise ClickToMcpError(msg)
