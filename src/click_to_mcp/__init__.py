"""Expose Click command-line interfaces as MCP servers."""

from __future__ import annotations

from .cli import main
from .loader import (
    ClickToMcpError,
    LoadedCommand,
    MissingDependencyError,
    load_click_command,
)
from .server import create_server

__all__ = [
    "ClickToMcpError",
    "LoadedCommand",
    "MissingDependencyError",
    "create_server",
    "load_click_command",
    "main",
]
