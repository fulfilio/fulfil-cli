"""Tests for skills subcommands: install."""

from __future__ import annotations

from importlib.resources import files

import pytest
from typer.testing import CliRunner

from fulfil_cli.cli.app import app

runner = CliRunner()

SKILL = files("fulfil_cli").joinpath("skills", "fulfil", "SKILL.md").read_text()


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_bundled_skill_has_frontmatter():
    assert SKILL.startswith("---\nname: fulfil\ndescription: ")


def test_installs_for_agents_and_claude(cwd):
    result = runner.invoke(app, ["skills", "install"])
    assert result.exit_code == 0

    assert (cwd / ".agents/skills/fulfil/SKILL.md").read_text() == SKILL
    assert (cwd / ".claude/skills/fulfil/SKILL.md").read_text() == SKILL


def test_global_installs_into_home(cwd, monkeypatch):
    home = cwd / "home"
    monkeypatch.setenv("HOME", str(home))

    result = runner.invoke(app, ["skills", "install", "--global"])
    assert result.exit_code == 0

    assert (home / ".agents/skills/fulfil/SKILL.md").read_text() == SKILL
    assert (home / ".claude/skills/fulfil/SKILL.md").read_text() == SKILL
    assert not (cwd / ".agents").exists()


def test_target_dir_installs_only_there(cwd):
    result = runner.invoke(app, ["skills", "install", ".pi/skills"])
    assert result.exit_code == 0

    assert (cwd / ".pi/skills/fulfil/SKILL.md").read_text() == SKILL
    assert not (cwd / ".agents").exists()
    assert not (cwd / ".claude").exists()


def test_reinstall_is_a_no_op(cwd):
    runner.invoke(app, ["skills", "install"])
    result = runner.invoke(app, ["skills", "install"])
    assert result.exit_code == 0
    assert "already installed" in result.output


def test_edited_skill_needs_force(cwd):
    runner.invoke(app, ["skills", "install"])
    edited = cwd / ".claude/skills/fulfil/SKILL.md"
    edited.write_text("mine")
    (cwd / ".agents/skills/fulfil/SKILL.md").unlink()

    result = runner.invoke(app, ["skills", "install"])
    assert result.exit_code == 1
    assert "differs" in result.output
    assert edited.read_text() == "mine"
    assert not (cwd / ".agents/skills/fulfil/SKILL.md").exists()

    result = runner.invoke(app, ["skills", "install", "--force"])
    assert result.exit_code == 0
    assert edited.read_text() == SKILL


def test_target_dir_and_global_conflict(cwd):
    result = runner.invoke(app, ["skills", "install", "x", "--global"])
    assert result.exit_code == 2
