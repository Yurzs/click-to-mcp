"""Tests covering tool generation and execution."""

from __future__ import annotations

import anyio
import pytest

from fastmcp.exceptions import ToolError

from click_to_mcp.loader import load_click_command
from click_to_mcp.server import create_server


def _run_tool(tool, **kwargs):
    async def invoke():
        return await tool.fn(**kwargs)

    return anyio.run(invoke)


@pytest.fixture(scope="module")
def server():
    loaded = load_click_command("tests.sample_cli:cli")
    return create_server(loaded, name="sample-server")


@pytest.fixture(scope="module")
def tools(server):
    return anyio.run(server.get_tools)


def test_tools_discovered(tools):
    assert {
        "cli",
        "cli_hello",
        "cli_math",
        "cli_math_add",
        "cli_math_multiply",
    }.issubset(set(tools))


def test_parameter_schema_for_hello(tools):
    hello = tools["cli_hello"]
    schema = hello.parameters
    assert schema["type"] == "object"
    assert schema["properties"]["name"]["type"] == "string"
    assert "name" in schema["required"]
    assert schema["properties"]["count"]["type"] == "integer"
    assert "count" not in schema.get("required", [])


def test_execute_hello(tools):
    hello = tools["cli_hello"]
    result = _run_tool(hello, name="Ada", count=2)
    structured = result.structured_content
    assert structured["stdout"].count("Hello, Ada!") == 2
    assert structured["return_value"] is None


def test_execute_add_with_boolean_flag(tools):
    add = tools["cli_math_add"]
    result = _run_tool(add, left=4, right=5, announce=False)
    assert result.structured_content["return_value"] == 9
    assert result.structured_content["stdout"] is None


def test_missing_required_argument(tools):
    hello = tools["cli_hello"]
    with pytest.raises(ToolError):
        _run_tool(hello, count=1)
