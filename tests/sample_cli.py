"""Sample Click application used in unit tests."""

from __future__ import annotations

import click


@click.group(help="Root command for testing")
@click.option("--verbose", is_flag=True, help="Enable verbose output.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Root group that stores a verbose flag on the context."""

    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    if verbose:
        click.echo("Verbose mode enabled.")


@cli.command(help="Echo a greeting.")
@click.argument("name")
@click.option("--count", type=int, default=1, show_default=True)
@click.pass_obj
def hello(obj: dict[str, bool], name: str, count: int) -> None:
    """Greet *name* a configurable number of times."""

    prefix = "[verbose] " if obj.get("verbose") else ""
    for _ in range(count):
        click.echo(f"{prefix}Hello, {name}!")


@cli.group(help="Mathematical helpers.")
@click.pass_context
def math(ctx: click.Context) -> None:
    """Nested command group."""

    ctx.obj = ctx.obj or {}


@math.command(help="Add two integers and print the result.")
@click.argument("left", type=int)
@click.argument("right", type=int)
@click.option("--announce/--no-announce", default=True, show_default=True)
def add(left: int, right: int, announce: bool) -> int:
    """Return the sum of *left* and *right*."""

    result = left + right
    if announce:
        click.echo(f"The result is {result}.")
    return result


@math.command(help="Multiply provided factors.")
@click.argument("factors", nargs=-1, type=int)
def multiply(factors: tuple[int, ...]) -> None:
    """Multiply all provided factors and print the product."""

    product = 1
    for factor in factors:
        product *= factor
    click.echo(str(product))
