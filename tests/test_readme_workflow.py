from __future__ import annotations

import re
import tomllib
from pathlib import Path

from ssm_tunnel_manager.cli import build_parser


ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
PYPROJECT_PATH = ROOT / "pyproject.toml"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_readme_documents_supported_uv_workflow_commands():
    readme = read_text(README_PATH)

    assert "uv sync" in readme
    assert "uv sync --extra test" in readme
    assert "uv tool install ssm-tunnel-manager" in readme
    assert "uv run pytest" in readme
    assert "uv run python -m build" in readme
    assert "uv run ssm-tunnel" in readme
    assert "curl -fsSL <installer-url> | sh" in readme
    assert (
        "`restart` only restarts selected tunnels that are currently `running` or `degraded`"
        in readme
    )

    documented_cli_commands = {
        match.group(1)
        for match in re.finditer(
            r"^uv run ssm-tunnel(?: --config [^\n]+)? (\w+)", readme, re.MULTILINE
        )
    }
    assert documented_cli_commands >= {
        "help",
        "install",
        "uninstall",
        "login",
        "list",
        "start",
        "stop",
        "restart",
        "status",
        "logs",
        "tui",
    }


def test_readme_uv_workflow_matches_project_configuration():
    pyproject = tomllib.loads(read_text(PYPROJECT_PATH))
    project = pyproject["project"]

    assert project["scripts"]["ssm-tunnel"] == "ssm_tunnel_manager.cli:main"

    test_extra = project["optional-dependencies"]["test"]
    assert any(requirement.startswith("pytest") for requirement in test_extra)
    assert any(requirement.startswith("build") for requirement in test_extra)


def test_readme_cli_examples_only_use_supported_subcommands():
    parser = build_parser()
    subcommands = set(parser._subparsers._group_actions[0].choices)
    readme = read_text(README_PATH)

    documented_cli_commands = {
        match.group(1)
        for match in re.finditer(
            r"^uv run ssm-tunnel(?: --config [^\n]+)? (\w+)", readme, re.MULTILINE
        )
    }
    assert documented_cli_commands
    assert documented_cli_commands <= subcommands


def test_readme_documents_default_status_summary_format():
    readme = read_text(README_PATH)

    assert (
        "Bare `ssm-tunnel` defaults to the same global summary as `ssm-tunnel status`"
        in readme
    )
    assert "aligned five-column table" in readme
    assert "`name`, `status`, `enabled`, `local port`, and `summary`" in readme


def test_readme_documents_install_and_status_filters():
    readme = read_text(README_PATH)

    assert "`~/.local/share/ssm-tunnels/config/tunnels.yaml`" in readme
    assert "`uv run ssm-tunnel install`" in readme
    assert "`uv tool uninstall ssm-tunnel-manager`" in readme
    assert "preserves any existing user config instead of overwriting it" in readme
    assert "leaves `~/.local/share/ssm-tunnels/` untouched" in readme
    assert "`uv tool install --reinstall ssm-tunnel-manager`" in readme
    assert "uv run ssm-tunnel install" in readme
    assert "detects that checkout context and runs the reinstall step for you" in readme
    assert "already running from the globally installed command" in readme
    assert "template config only if it does not already exist" in readme
    assert "published package from the configured Python package index" in readme
    assert "`SSM_TUNNEL_PACKAGE_SPEC`" in readme
    assert "uv run ssm-tunnel login" in readme
    assert "aws sso login --profile <defaults.aws.profile>" in readme
    assert "`--running`, `--stopped`, `--enabled`, and `--disabled`" in readme
    assert "`status <name>` rejects filter flags" in readme


def test_pyproject_packages_template_config():
    pyproject = tomllib.loads(read_text(PYPROJECT_PATH))

    package_data = pyproject["tool"]["setuptools"]["package-data"]
    assert package_data["ssm_tunnel_manager"] == ["templates/*.yaml"]


def test_readme_documents_help_and_tui_workflow():
    readme = read_text(README_PATH)

    assert "uv run ssm-tunnel help" in readme
    assert "uv run ssm-tunnel tui" in readme
    assert "`fzf`" in readme
    assert "action first" in readme
    assert "normal `fzf` behavior" in readme
    assert "arrow keys move through the list" in readme
    assert "`Tab` to mark multiple tunnels" in readme
    assert "`login` is an action-only flow" in readme
    assert "`uninstall` is an action-only flow" in readme
    assert "`logs` remains single-tunnel only" in readme
    assert "`status` offers `all`" in readme
