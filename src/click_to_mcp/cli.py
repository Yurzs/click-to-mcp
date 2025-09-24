"""Command-line interface for exposing Click CLIs via MCP."""

from __future__ import annotations

from typing import Optional

import anyio
import click

from .loader import ClickToMcpError, load_click_command
from .server import create_server

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


@click.command(context_settings={"auto_envvar_prefix": "CLICK_TO_MCP"})
@click.argument("reference", metavar="MODULE[:OBJECT]")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"], case_sensitive=False),
    default="stdio",
    show_default=True,
    help="MCP transport to expose.",
)
@click.option(
    "--host",
    default=DEFAULT_HOST,
    show_default=True,
    help="Host for the SSE transport.",
)
@click.option(
    "--port",
    type=int,
    default=DEFAULT_PORT,
    show_default=True,
    help="Port for the SSE transport.",
)
@click.option("--name", help="Optional server name override.")
@click.option("--instructions", help="Custom instructions for the MCP server.")
@click.option(
    "--tool-prefix",
    help="Prefix to prepend to generated tool names.",
)
@click.option(
    "--list-tools",
    is_flag=True,
    help="List generated tools and exit without starting the server.",
)
@click.version_option()
def main(
    reference: str,
    transport: str,
    host: str,
    port: int,
    name: Optional[str],
    instructions: Optional[str],
    tool_prefix: Optional[str],
    list_tools: bool,
) -> None:
    """Expose a Click utility as a FastMCP server."""

    try:
        loaded = load_click_command(reference)
    except ClickToMcpError as exc:
        raise click.ClickException(str(exc)) from exc

    server = create_server(
        loaded,
        name=name,
        instructions=instructions,
        tool_prefix=tool_prefix,
    )

    if list_tools:
        tools = anyio.run(server.get_tools)
        click.echo(f"Discovered {len(tools)} tool(s):")
        for tool in tools:
            click.echo(f"- {tool.name}: {tool.description or 'No description provided.'}")
        return

    if transport.lower() == "stdio":
        server.run(transport="stdio")
    elif transport.lower() == "sse":
        server.run(transport="sse", host=host, port=port)
    else:  # pragma: no cover - protected by click.Choice
        raise click.ClickException(f"Unsupported transport '{transport}'.")


__all__ = ["main"]
