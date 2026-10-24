"""Skills commands: install the bundled agent skill."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import typer
from rich.console import Console

from fulfil_cli.client.errors import EXIT_GENERAL, EXIT_USAGE

app = typer.Typer(help="Install the Fulfil skill for coding agents.")
console = Console()

SKILL_NAME = "fulfil"
# Codex and most other agents read .agents/skills; Claude Code reads .claude/skills.
SKILL_DIRS = (".agents/skills", ".claude/skills")


@app.command("install")
def skills_install(
    target_dir: Path | None = typer.Argument(
        None, help="Skills directory to install into, instead of the defaults"
    ),
    global_: bool = typer.Option(
        False, "--global", help="Install into ~/.agents/skills and ~/.claude/skills"
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite an installed skill that differs"),
) -> None:
    """Install the bundled Fulfil skill.

    By default it goes into .agents/skills (Codex and others) and .claude/skills
    (Claude Code) in the current directory.

    \b
    Examples:
      fulfil skills install
      fulfil skills install --global
      fulfil skills install .pi/skills
    """
    if target_dir and global_:
        console.print("[red]Pass a TARGET_DIR or --global, not both.[/red]")
        raise typer.Exit(code=EXIT_USAGE)

    if target_dir:
        roots = [target_dir.expanduser()]
    else:
        base = Path.home() if global_ else Path()
        roots = [base / d for d in SKILL_DIRS]

    content = files("fulfil_cli").joinpath("skills", SKILL_NAME, "SKILL.md").read_text()
    destinations = [root / SKILL_NAME / "SKILL.md" for root in roots]

    differs = [d for d in destinations if d.exists() and d.read_text() != content]
    if differs and not force:
        for d in differs:
            console.print(f"[red]{d} already exists and differs.[/red]")
        console.print("Re-run with --force to overwrite.")
        raise typer.Exit(code=EXIT_GENERAL)

    for destination in destinations:
        if destination.exists() and destination.read_text() == content:
            console.print(f"Skill '{SKILL_NAME}' is already installed at {destination}")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
        console.print(f"[green]Installed skill '{SKILL_NAME}' to {destination}[/green]")
