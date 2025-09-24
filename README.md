# click-to-mcp

Expose any Python [Click](https://click.palletsprojects.com/) command-line application as a [Model Context Protocol](https://github.com/modelcontextprotocol/specification) (MCP) server. The generated server uses [FastMCP](https://pypi.org/project/fastmcp/) and supports both STDIO and Server Sent Events (SSE) transports so tools can be consumed by MCP-compatible clients.

## Features

- 🔌 Load Click CLIs from modules or Python files (``module:object`` syntax) and automatically register every command as an MCP tool.
- 🧩 Preserve Click option metadata (types, defaults, choices, etc.) in the generated JSON schemas so MCP clients understand each tool's interface.
- 🔁 Execute Click commands in a background thread, capturing their stdout/stderr output and return value for structured responses.
- 🚏 Run over STDIO or SSE transports with a single flag.
- 🔍 Inspect generated tools without starting the server using `--list-tools`.

## Quick start

The project is managed with [uv](https://github.com/astral-sh/uv). To run the CLI without installing it globally, use `uvx`:

```bash
uvx click-to-mcp tests.sample_cli:cli --transport stdio
```

The argument `tests.sample_cli:cli` follows the standard `module:object` pattern. You can point at any importable module or Python file that exposes a Click command (group or standalone). When omitted, the loader attempts to resolve a `cli` attribute or auto-discovers a single Click command in the module.

### Listing available tools

```bash
uvx click-to-mcp tests.sample_cli:cli --list-tools
```

Example output:

```
Discovered 5 tool(s):
- cli: Root command for testing
- cli_hello: Echo a greeting. (CLI path: hello)
- cli_math: Mathematical helpers. (CLI path: math)
- cli_math_add: Add two integers and print the result. (CLI path: math add)
- cli_math_multiply: Multiply provided factors. (CLI path: math multiply)
```

### Running over SSE

```bash
uvx click-to-mcp tests.sample_cli:cli --transport sse --host 0.0.0.0 --port 8765
```

SSE transport exposes an HTTP endpoint compatible with MCP's SSE handshake. Customize the host and port with the corresponding options.

## Library usage

The package also exposes helper functions if you prefer to embed it programmatically:

```python
from click_to_mcp import create_server, load_click_command

loaded = load_click_command("my_app.cli:cli")
server = create_server(loaded, name="my-cli")
server.run(transport="stdio")
```

## Development

Install dependencies and run the test suite:

```bash
uv sync
uv run pytest
```

The tests include a sample Click application under `tests/sample_cli.py` that exercises nested groups, positional arguments, options with defaults, and boolean flags.
