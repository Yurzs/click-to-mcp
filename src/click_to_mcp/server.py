"""Conversion utilities that expose Click commands as MCP tools."""

from __future__ import annotations

import contextlib
import io
import re
from dataclasses import dataclass
from typing import Any, Iterator, Sequence

import anyio
import click
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.tool import FunctionTool, ToolResult
from mcp.types import TextContent

from .loader import ClickToMcpError, LoadedCommand

_JSON_SAFE_TYPES = (str, int, float, bool)


@dataclass(slots=True)
class CommandEntry:
    """Represents a command along a path within a Click command tree."""

    command: click.BaseCommand
    invocation: str | None


@dataclass(slots=True)
class ParameterSpec:
    """Metadata describing how to surface a Click parameter as a MCP field."""

    param: click.Parameter
    info: dict[str, Any]
    user_name: str
    entry: CommandEntry
    required: bool


def create_server(
    loaded: LoadedCommand,
    *,
    name: str | None = None,
    instructions: str | None = None,
    tool_prefix: str | None = None,
) -> FastMCP:
    """Create a :class:`FastMCP` instance exposing *loaded*'s commands."""

    root_command = loaded.command
    server_name = name or _derive_server_name(root_command)
    server_instructions = instructions or (
        "Interact with the provided Click application through MCP tools."
    )

    server = FastMCP(name=server_name, instructions=server_instructions)

    registered = False
    for path in _iter_command_paths(root_command):
        specs = _collect_parameter_specs(path)
        tool = _build_function_tool(
            root_command=root_command,
            path=path,
            specs=specs,
            tool_prefix=tool_prefix,
        )
        server.add_tool(tool)
        registered = True

    if not registered:  # pragma: no cover - defensive guard
        msg = "No callable commands discovered on the provided Click application."
        raise ClickToMcpError(msg)

    return server


def _derive_server_name(command: click.BaseCommand) -> str:
    if command.name:
        return command.name
    if command.callback and getattr(command.callback, "__name__", None):
        return command.callback.__name__
    return "click-to-mcp"


def _iter_command_paths(command: click.BaseCommand) -> Iterator[list[CommandEntry]]:
    """Yield command paths that terminate in callable commands."""

    root_entry = CommandEntry(command=command, invocation=None)
    yield from _walk_command_entries([root_entry])


def _walk_command_entries(path: list[CommandEntry]) -> Iterator[list[CommandEntry]]:
    current = path[-1]
    command = current.command

    if command.callback is not None:
        yield list(path)

    if hasattr(command, "list_commands") and hasattr(command, "get_command"):
        ctx = click.Context(command)
        for sub_name in command.list_commands(ctx):
            sub = command.get_command(ctx, sub_name)
            if sub is None:
                continue
            path.append(CommandEntry(command=sub, invocation=sub_name))
            yield from _walk_command_entries(path)
            path.pop()


def _collect_parameter_specs(path: Sequence[CommandEntry]) -> list[ParameterSpec]:
    seen: dict[str, int] = {}
    specs: list[ParameterSpec] = []

    for entry in path:
        for param in entry.command.params:
            if not param.expose_value or param.name is None:
                continue
            base_name = param.name
            count = seen.get(base_name, 0)
            seen[base_name] = count + 1
            user_name = base_name if count == 0 else f"{base_name}_{count+1}"
            info = param.to_info_dict()
            specs.append(
                ParameterSpec(
                    param=param,
                    info=info,
                    user_name=user_name,
                    entry=entry,
                    required=bool(info.get("required")),
                )
            )
    return specs


def _build_function_tool(
    *,
    root_command: click.BaseCommand,
    path: Sequence[CommandEntry],
    specs: Sequence[ParameterSpec],
    tool_prefix: str | None,
) -> FunctionTool:
    description = _build_command_description(path[-1].command, path)
    tool_name = _build_tool_name(path, prefix=tool_prefix)
    parameters_schema = _build_parameters_schema(specs)

    async def tool_fn(**kwargs: Any) -> ToolResult:
        values = _merge_with_defaults(specs, kwargs)
        cli_args = _build_cli_arguments(path, specs, values)

        async def invoke() -> tuple[Any, str, str]:
            def _call() -> tuple[Any, str, str]:
                stdout = io.StringIO()
                stderr = io.StringIO()
                try:
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                        stderr
                    ):
                        result = root_command.main(cli_args, standalone_mode=False)
                except click.exceptions.Exit as exc:
                    if exc.exit_code == 0:
                        return None, stdout.getvalue(), stderr.getvalue()
                    raise ToolError(f"Command exited with code {exc.exit_code}.") from exc
                except click.ClickException as exc:
                    raise ToolError(exc.format_message()) from exc
                except click.Abort as exc:
                    raise ToolError("Command execution aborted.") from exc
                except SystemExit as exc:  # pragma: no cover - defensive
                    raise ToolError(
                        f"Command exited with code {exc.code}."
                    ) from exc
                return result, stdout.getvalue(), stderr.getvalue()

            return await anyio.to_thread.run_sync(_call)

        result, stdout, stderr = await invoke()
        command_tokens = [
            entry.invocation or entry.command.name
            for entry in path
            if entry.invocation
        ]
        structured = {
            "command_path": command_tokens,
            "stdout": stdout or None,
            "stderr": stderr or None,
            "return_value": _ensure_jsonable(result),
        }
        text_output = stdout.strip()
        if stderr:
            text_output = f"{text_output}\n{stderr.strip()}" if text_output else stderr.strip()
        if result not in (None, ""):
            result_text = str(result)
            text_output = f"{text_output}\n{result_text}" if text_output else result_text
        content = None
        if text_output:
            content = [TextContent(type="text", text=text_output)]
        return ToolResult(content=content, structured_content=structured)

    return FunctionTool(
        name=tool_name,
        description=description,
        parameters=parameters_schema,
        fn=tool_fn,
        meta={
            "path": [
                entry.invocation or entry.command.name
                for entry in path
                if entry.invocation
            ],
            "root_command": root_command.name or "<anonymous>",
        },
    )


def _merge_with_defaults(
    specs: Sequence[ParameterSpec], kwargs: dict[str, Any]
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    unexpected = set(kwargs) - {spec.user_name for spec in specs}
    if unexpected:
        msg = ", ".join(sorted(unexpected))
        raise ToolError(f"Unexpected parameters provided: {msg}.")

    for spec in specs:
        if spec.user_name in kwargs:
            values[spec.user_name] = kwargs[spec.user_name]
        elif spec.required:
            raise ToolError(f"Missing required parameter '{spec.user_name}'.")
    return values


def _build_parameters_schema(specs: Sequence[ParameterSpec]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for spec in specs:
        schema = _parameter_schema(spec)
        properties[spec.user_name] = schema
        if spec.required:
            required.append(spec.user_name)
    schema_obj = {"type": "object", "properties": properties}
    if required:
        schema_obj["required"] = required
    return schema_obj


def _parameter_schema(spec: ParameterSpec) -> dict[str, Any]:
    info = spec.info
    param_type = info.get("type", {})
    base_type = param_type.get("name") or "string"
    schema: dict[str, Any]

    if info.get("is_flag") or base_type == "boolean":
        schema = {"type": "boolean"}
    elif base_type in {"integer", "int", "int range", "count"}:
        schema = {"type": "integer"}
        if param_type.get("min") is not None:
            schema["minimum"] = param_type.get("min")
        if param_type.get("max") is not None:
            schema["maximum"] = param_type.get("max")
    elif base_type in {"float", "float range"}:
        schema = {"type": "number"}
        if param_type.get("min") is not None:
            schema["minimum"] = param_type.get("min")
        if param_type.get("max") is not None:
            schema["maximum"] = param_type.get("max")
    elif base_type == "choice":
        schema = {"type": "string", "enum": list(param_type.get("choices", []))}
    elif base_type == "datetime":
        schema = {"type": "string", "format": "date-time"}
    elif base_type == "date":
        schema = {"type": "string", "format": "date"}
    else:
        schema = {"type": "string"}

    if info.get("multiple") or (info.get("nargs") not in (None, 1)):
        items_schema = schema
        if info.get("nargs") and info.get("nargs") > 1 and not info.get("multiple"):
            schema = {
                "type": "array",
                "items": items_schema,
                "minItems": info["nargs"],
                "maxItems": info["nargs"],
            }
        else:
            schema = {"type": "array", "items": items_schema}

    description_parts: list[str] = []
    help_text = info.get("help")
    if help_text:
        description_parts.append(help_text)
    option_names = info.get("opts") or []
    if option_names:
        description_parts.append(f"Option names: {'/'.join(option_names)}")
    secondary = info.get("secondary_opts") or []
    if secondary:
        description_parts.append(f"Alternate names: {'/'.join(secondary)}")
    if description_parts:
        schema["description"] = "\n\n".join(description_parts)

    default = info.get("default")
    if default not in (None, ()):  # ignore Click's empty tuple default for multiple
        schema["default"] = _ensure_jsonable(default)

    return schema


def _build_cli_arguments(
    path: Sequence[CommandEntry],
    specs: Sequence[ParameterSpec],
    values: dict[str, Any],
) -> list[str]:
    args: list[str] = []
    for index, entry in enumerate(path):
        entry_specs = [spec for spec in specs if spec.entry is entry]
        for spec in entry_specs:
            args.extend(_render_argument(spec, values.get(spec.user_name)))
        if index < len(path) - 1:
            invocation = path[index + 1].invocation
            if invocation:
                args.append(invocation)
    return args


def _render_argument(spec: ParameterSpec, value: Any) -> list[str]:
    param = spec.param
    info = spec.info
    if value is None:
        return []

    if isinstance(param, click.Option):
        return _render_option(param, info, value)
    return _render_positional(info, value)


def _render_option(param: click.Option, info: dict[str, Any], value: Any) -> list[str]:
    if info.get("is_flag"):
        if value:
            return [param.opts[0]] if param.opts else []
        if info.get("secondary_opts"):
            return [info["secondary_opts"][0]]
        return []

    option_flag = param.opts[0] if param.opts else f"--{param.name}"

    if info.get("multiple") and info.get("nargs", 1) == 1:
        values = value if isinstance(value, (list, tuple)) else [value]
        rendered: list[str] = []
        for item in values:
            rendered.extend([option_flag, _stringify(item)])
        return rendered

    nargs = info.get("nargs", 1)
    if nargs not in (None, 1):
        if info.get("multiple"):
            rendered: list[str] = []
            chunks = value if isinstance(value, (list, tuple)) else [value]
            for chunk in chunks:
                rendered.append(option_flag)
                rendered.extend(_stringify_each(chunk, expected_length=nargs))
            return rendered
        rendered = [option_flag]
        rendered.extend(_stringify_each(value, expected_length=nargs))
        return rendered

    return [option_flag, _stringify(value)]


def _render_positional(info: dict[str, Any], value: Any) -> list[str]:
    nargs = info.get("nargs", 1)
    if nargs in (None, 1):
        return [_stringify(value)]
    if nargs == -1:
        values = value if isinstance(value, (list, tuple)) else [value]
        return [_stringify(item) for item in values]
    return _stringify_each(value, expected_length=nargs)


def _stringify_each(value: Any, *, expected_length: int) -> list[str]:
    seq = value if isinstance(value, (list, tuple)) else [value]
    if len(seq) != expected_length:
        raise ToolError(
            f"Expected {expected_length} values for parameter, received {len(seq)}."
        )
    return [_stringify(item) for item in seq]


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _ensure_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, _JSON_SAFE_TYPES):
        return value
    if isinstance(value, (list, tuple)):
        return [_ensure_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _ensure_jsonable(v) for k, v in value.items()}
    return repr(value)


def _build_command_description(command: click.BaseCommand, path: Sequence[CommandEntry]) -> str:
    help_text = command.help or command.short_help
    path_tokens = [entry.invocation or entry.command.name for entry in path if entry.invocation]
    path_repr = " ".join(token for token in path_tokens if token)
    if help_text and path_repr:
        return f"{help_text.strip()} (CLI path: {path_repr})"
    if help_text:
        return help_text.strip()
    if path_repr:
        return f"Invoke CLI command '{path_repr}'."
    return "Invoke the root CLI command."


def _build_tool_name(path: Sequence[CommandEntry], prefix: str | None) -> str:
    tokens = [entry.invocation or entry.command.name or "command" for entry in path]
    sanitized = [re.sub(r"[^a-zA-Z0-9_.-]", "_", token or "command") for token in tokens if token]
    name = "_".join(filter(None, sanitized)) or "command"
    if prefix:
        return f"{prefix}_{name}"
    return name
