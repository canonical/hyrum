"""CLI entrypoint stub. Real wiring lands in a later commit."""

import click


@click.command()
def main() -> None:
    """Run a check across many charm repositories, optionally swapping a dependency."""
    click.echo("super-tox: CLI not wired up yet; see README.")
