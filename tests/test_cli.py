from __future__ import annotations

import argparse
import os
import re
import subprocess
import textwrap

import pytest

import ssm_tunnel_manager.cli as cli_module
from ssm_tunnel_manager.cli import main
from ssm_tunnel_manager.config import load_config as load_config_file
from ssm_tunnel_manager.paths import packaged_template_config_text
from ssm_tunnel_manager.models import (
    BackendInspection,
    BackendStartResult,
    DependencyCheck,
    RuntimeStatus,
    TunnelRuntimeState,
)
from ssm_tunnel_manager.state import load_runtime_state, update_tunnel_state
from ssm_tunnel_manager.tui import SelectorError


def write_config(tmp_path, tunnels_yaml: str | None = None):
    config_path = tmp_path / "tunnels.yaml"
    tunnels_yaml = (
        tunnels_yaml
        or textwrap.dedent(
            """
        tunnels:
          - name: mysql
            remote_host: db.internal
            remote_port: 3306
            local_port: 13306
          - name: redis
            remote_host: cache.internal
            remote_port: 6379
            local_port: 16379
          - name: admin
            remote_host: admin.internal
            remote_port: 8443
            local_port: 18443
            enabled: false
        """
        ).strip()
    )
    config_path.write_text(
        "\n".join(
            [
                "version: 1",
                "defaults:",
                "  aws:",
                "    region: us-east-1",
                "    target: i-default",
                "    profile: team-profile",
                "    document: AWS-StartPortForwardingSessionToRemoteHost",
                "  ui:",
                "    backend: tmux",
                tunnels_yaml,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


SUMMARY_HEADERS = ["name", "status", "enabled", "local port", "summary"]


def summary_cells(
    name: str,
    status: str,
    enabled: str,
    local_port: int,
    summary: str = "-",
) -> list[str]:
    return [name, status, enabled, str(local_port), summary]


def _column_starts(line: str, cells: list[str]) -> list[int]:
    starts = []
    cursor = 0
    for cell in cells:
        start = line.index(cell, cursor)
        starts.append(start)
        cursor = start + len(cell)
    return starts


def assert_summary_table(output: str, expected_rows: list[list[str]]) -> None:
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    assert lines
    assert re.split(r"\s{2,}", lines[0].strip()) == SUMMARY_HEADERS
    assert len(lines) == len(expected_rows) + 1

    header_starts = _column_starts(lines[0], SUMMARY_HEADERS)
    data_rows = [re.split(r"\s{2,}", line.strip()) for line in lines[1:]]
    assert data_rows == expected_rows

    for line, expected_cells in zip(lines[1:], expected_rows, strict=True):
        assert _column_starts(line, expected_cells) == header_starts


class FakeBackend:
    name = "tmux"

    def __init__(self):
        self.start_calls = []
        self.stop_calls = []
        self.next_pid = 4100

    def start(self, tunnel, command, log_path):
        self.start_calls.append((tunnel.name, command, str(log_path)))
        self.next_pid += 1
        return BackendStartResult(
            backend_session=f"ssm-tunnel-{tunnel.name}", pid=self.next_pid
        )

    def stop(self, runtime_state):
        self.stop_calls.append(runtime_state.name)

    def inspect(self, runtime_state):
        return BackendInspection(
            is_running=runtime_state.status is RuntimeStatus.RUNNING,
            backend_session=runtime_state.backend_session,
            pid=runtime_state.pid,
        )


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    config_path = write_config(tmp_path)
    backend = FakeBackend()

    monkeypatch.setattr(
        "ssm_tunnel_manager.paths.default_data_dir", lambda: runtime_root
    )
    monkeypatch.setattr("ssm_tunnel_manager.cli.get_backend", lambda name: backend)
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.check_dependencies",
        lambda backend_name: [
            DependencyCheck(name="aws", ok=True, details="aws CLI found"),
            DependencyCheck(
                name="session-manager-plugin",
                ok=True,
                details="session-manager-plugin found",
            ),
            DependencyCheck(name="tmux", ok=True, details="tmux found"),
        ],
    )
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.evaluate_tunnel_health",
        lambda tunnel, runtime_state, backend_inspection=None: (
            RuntimeStatus.RUNNING
            if runtime_state and backend_inspection and backend_inspection.is_running
            else RuntimeStatus.STOPPED
        ),
    )

    return config_path, runtime_root, backend


def test_cli_dispatches_lifecycle_commands(cli_env, capsys):
    config_path, runtime_root, backend = cli_env

    assert main(["--config", str(config_path), "list"]) == 0
    out = capsys.readouterr().out
    assert_summary_table(
        out,
        [
            summary_cells("mysql", "stopped", "enabled", 13306),
            summary_cells("redis", "stopped", "enabled", 16379),
            summary_cells("admin", "stopped", "disabled", 18443),
        ],
    )
    assert "db.internal" not in out

    assert main(["--config", str(config_path), "start", "mysql"]) == 0
    out = capsys.readouterr().out
    assert "Started tunnel 'mysql' using tmux." in out
    assert backend.start_calls[0][0] == "mysql"

    state = load_runtime_state(runtime_root)
    assert state["mysql"].status is RuntimeStatus.RUNNING
    assert state["mysql"].backend_session == "ssm-tunnel-mysql"

    assert main(["--config", str(config_path), "status", "mysql"]) == 0
    out = capsys.readouterr().out
    assert "Name: mysql" in out
    assert "Status: running" in out
    assert "Session: ssm-tunnel-mysql" in out

    assert main(["--config", str(config_path), "logs", "mysql"]) == 0
    out = capsys.readouterr().out
    assert "Logs for tunnel 'mysql':" in out
    assert "started tunnel 'mysql'" in out

    assert main(["--config", str(config_path), "restart", "mysql"]) == 0
    out = capsys.readouterr().out
    assert "Restarted tunnel 'mysql'." in out
    assert backend.stop_calls == ["mysql"]
    assert len(backend.start_calls) == 2

    assert main(["--config", str(config_path), "stop", "mysql"]) == 0
    out = capsys.readouterr().out
    assert "Stopped tunnel 'mysql'." in out

    state = load_runtime_state(runtime_root)
    assert state["mysql"].status is RuntimeStatus.STOPPED
    assert state["mysql"].pid is None


def test_cli_reports_config_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--config", "/does/not/exist.yaml", "list"])

    assert excinfo.value.code == 2
    assert "Config error: Config file not found" in capsys.readouterr().err


def test_cli_help_command_prints_usage(capsys):
    assert main(["help"]) == 0

    out = capsys.readouterr().out
    assert "usage: ssm-tunnel" in out
    assert "help" in out
    assert "login" in out
    assert "Bootstrap config and self-install from a checkout" in out
    assert "tui" in out


def test_cli_help_command_skips_config_loading(capsys):
    assert main(["--config", "/does/not/exist.yaml", "help"]) == 0

    captured = capsys.readouterr()
    assert "usage: ssm-tunnel" in captured.out
    assert captured.err == ""


def test_cli_login_runs_aws_sso_login_with_default_profile(cli_env, monkeypatch):
    config_path, _runtime_root, _backend = cli_env
    calls = []

    def fake_run(command, check):
        calls.append((command, check))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run, raising=False)

    assert main(["--config", str(config_path), "login"]) == 0

    assert calls == [(["aws", "sso", "login", "--profile", "team-profile"], False)]


def test_cli_login_ignores_tunnel_specific_profile_overrides(tmp_path, monkeypatch):
    config_path = write_config(
        tmp_path,
        tunnels_yaml=textwrap.dedent(
            """
        tunnels:
          - name: mysql
            remote_host: db.internal
            remote_port: 3306
            local_port: 13306
            aws:
              profile: tunnel-profile
        """
        ).strip(),
    )
    calls = []

    monkeypatch.setattr(
        "ssm_tunnel_manager.paths.default_data_dir", lambda: tmp_path / "runtime"
    )
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.check_dependencies",
        lambda backend_name: [
            DependencyCheck(name="aws", ok=True, details="aws CLI found")
        ],
    )

    def fake_run(command, check):
        calls.append((command, check))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run, raising=False)

    assert main(["--config", str(config_path), "login"]) == 0

    assert calls == [(["aws", "sso", "login", "--profile", "team-profile"], False)]


def test_cli_login_requires_default_profile_in_config(tmp_path, monkeypatch, capsys):
    config_path = write_config(
        tmp_path,
        tunnels_yaml="tunnels: []",
    )
    config_path.write_text(
        "\n".join(
            [
                "version: 1",
                "defaults:",
                "  aws:",
                "    region: us-east-1",
                "    target: i-default",
                "    document: AWS-StartPortForwardingSessionToRemoteHost",
                "tunnels: []",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "ssm_tunnel_manager.paths.default_data_dir", lambda: tmp_path / "runtime"
    )
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.check_dependencies",
        lambda backend_name: [
            DependencyCheck(name="aws", ok=True, details="aws CLI found")
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), "login"])

    assert excinfo.value.code == 2
    assert (
        "Command 'login' requires defaults.aws.profile in config."
        in capsys.readouterr().err
    )


def test_cli_login_reports_missing_aws_dependency(cli_env, monkeypatch, capsys):
    config_path, _runtime_root, _backend = cli_env
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.check_dependencies",
        lambda backend_name: [
            DependencyCheck(name="aws", ok=False, details="aws not found")
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), "login"])

    assert excinfo.value.code == 4
    assert "Dependency error: missing aws" in capsys.readouterr().err


def test_cli_login_returns_subprocess_failure_code(cli_env, monkeypatch):
    config_path, _runtime_root, _backend = cli_env

    def fake_run(command, check):
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run, raising=False)

    assert main(["--config", str(config_path), "login"]) == 7


def test_cli_login_reports_runtime_missing_aws_binary(cli_env, monkeypatch, capsys):
    config_path, _runtime_root, _backend = cli_env

    def fake_run(command, check):
        raise FileNotFoundError("aws")

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run, raising=False)

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), "login"])

    assert excinfo.value.code == 4
    assert "Dependency error: missing aws" in capsys.readouterr().err


def test_cli_reports_dependency_failures(cli_env, monkeypatch, capsys):
    config_path, runtime_root, _backend = cli_env
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.check_dependencies",
        lambda backend_name: [
            DependencyCheck(name="aws", ok=False, details="aws not found"),
            DependencyCheck(
                name="session-manager-plugin",
                ok=True,
                details="session-manager-plugin found",
            ),
            DependencyCheck(name="tmux", ok=False, details="tmux not found"),
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), "start", "mysql"])

    assert excinfo.value.code == 4
    assert "Dependency error: missing aws, tmux" in capsys.readouterr().err
    assert load_runtime_state(runtime_root) == {}


def test_cli_stop_and_restart_only_require_tmux_for_stop_phase(
    cli_env, monkeypatch, capsys
):
    config_path, runtime_root, backend = cli_env
    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.RUNNING,
            backend="tmux",
            pid=4101,
            backend_session="ssm-tunnel-mysql",
        ),
        runtime_root,
    )
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.check_dependencies",
        lambda backend_name: [
            DependencyCheck(name="aws", ok=False, details="aws not found"),
            DependencyCheck(
                name="session-manager-plugin",
                ok=False,
                details="session-manager-plugin not found",
            ),
            DependencyCheck(name="tmux", ok=True, details="tmux found"),
        ],
    )

    assert main(["--config", str(config_path), "stop", "mysql"]) == 0
    out = capsys.readouterr().out
    assert "Stopped tunnel 'mysql'." in out
    assert backend.stop_calls == ["mysql"]

    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.RUNNING,
            backend="tmux",
            pid=4102,
            backend_session="ssm-tunnel-mysql",
        ),
        runtime_root,
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), "restart", "mysql"])

    assert excinfo.value.code == 4
    assert backend.stop_calls == ["mysql", "mysql"]
    assert (
        "Dependency error: missing aws, session-manager-plugin"
        in capsys.readouterr().err
    )


def test_cli_status_surfaces_recorded_failure_summary(cli_env, capsys):
    config_path, runtime_root, _backend = cli_env
    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.FAILED,
            backend="tmux",
            log_path=str(runtime_root / "logs" / "mysql.log"),
            error_summary="tmux stop failed for tunnel 'mysql'",
        ),
        runtime_root,
    )

    assert main(["--config", str(config_path), "status", "mysql"]) == 0

    out = capsys.readouterr().out
    assert "Last Error: tmux stop failed for tunnel 'mysql'" in out

    assert main(["--config", str(config_path), "list"]) == 0
    out = capsys.readouterr().out
    assert_summary_table(
        out,
        [
            summary_cells(
                "mysql",
                "stopped",
                "enabled",
                13306,
                "tmux stop failed for tunnel 'mysql'",
            ),
            summary_cells("redis", "stopped", "enabled", 16379),
            summary_cells("admin", "stopped", "disabled", 18443),
        ],
    )
    assert "db.internal" not in out


def test_cli_logs_command_handles_empty_log(cli_env, capsys):
    config_path, _runtime_root, _backend = cli_env

    assert main(["--config", str(config_path), "logs", "mysql"]) == 0

    assert "No log output for tunnel 'mysql' yet." in capsys.readouterr().out


def test_cli_tui_selection_dispatches_through_shared_runtime(
    cli_env, monkeypatch, capsys
):
    config_path, runtime_root, backend = cli_env
    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.RUNNING,
            backend="tmux",
            pid=4101,
            backend_session="ssm-tunnel-mysql",
        ),
        runtime_root,
    )
    monkeypatch.setattr(
        "ssm_tunnel_manager.tui.launch",
        lambda config: argparse.Namespace(
            command="start", names=["redis", "mysql"], all=False
        ),
    )

    assert main(["--config", str(config_path), "tui"]) == 0

    out = capsys.readouterr().out
    assert "Tunnel 'mysql' is already running." in out
    assert "Started tunnel 'redis' using tmux." in out
    assert [call[0] for call in backend.start_calls] == ["redis"]


def test_cli_tui_login_selection_dispatches_through_shared_login_path(
    cli_env, monkeypatch
):
    config_path, _runtime_root, _backend = cli_env
    calls = []

    monkeypatch.setattr(
        "ssm_tunnel_manager.tui.launch",
        lambda config: argparse.Namespace(command="login"),
    )

    def fake_run(command, check):
        calls.append((command, check))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run, raising=False)

    assert main(["--config", str(config_path), "tui"]) == 0

    assert calls == [(["aws", "sso", "login", "--profile", "team-profile"], False)]


def test_cli_tui_reports_selector_errors(cli_env, monkeypatch, capsys):
    config_path, _runtime_root, _backend = cli_env
    monkeypatch.setattr(
        "ssm_tunnel_manager.tui.launch",
        lambda config: (_ for _ in ()).throw(SelectorError("fzf is required")),
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), "tui"])

    assert excinfo.value.code == 4
    assert "TUI error: fzf is required" in capsys.readouterr().err


def test_cli_status_without_name_shows_all_tunnels(cli_env, capsys):
    config_path, runtime_root, _backend = cli_env
    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.RUNNING,
            backend="tmux",
            pid=4101,
            backend_session="ssm-tunnel-mysql",
        ),
        runtime_root,
    )

    assert main(["--config", str(config_path), "status"]) == 0

    out = capsys.readouterr().out
    assert_summary_table(
        out,
        [
            summary_cells("mysql", "running", "enabled", 13306),
            summary_cells("redis", "stopped", "enabled", 16379),
            summary_cells("admin", "stopped", "disabled", 18443),
        ],
    )
    assert "db.internal" not in out


def test_cli_status_filters_apply_to_global_summary_only(cli_env, capsys):
    config_path, runtime_root, _backend = cli_env
    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.RUNNING,
            backend="tmux",
            pid=4101,
            backend_session="ssm-tunnel-mysql",
        ),
        runtime_root,
    )

    assert main(["--config", str(config_path), "status", "--running"]) == 0
    out = capsys.readouterr().out
    assert_summary_table(
        out,
        [summary_cells("mysql", "running", "enabled", 13306)],
    )

    assert main(["--config", str(config_path), "status", "--stopped", "--enabled"]) == 0
    out = capsys.readouterr().out
    assert_summary_table(
        out,
        [summary_cells("redis", "stopped", "enabled", 16379)],
    )

    assert main(["--config", str(config_path), "status", "--disabled"]) == 0
    out = capsys.readouterr().out
    assert_summary_table(
        out,
        [summary_cells("admin", "stopped", "disabled", 18443)],
    )

    assert main(["--config", str(config_path), "status", "--running", "--stopped"]) == 0
    out = capsys.readouterr().out
    assert_summary_table(
        out,
        [
            summary_cells("mysql", "running", "enabled", 13306),
            summary_cells("redis", "stopped", "enabled", 16379),
            summary_cells("admin", "stopped", "disabled", 18443),
        ],
    )


def test_cli_defaults_to_global_status_when_only_global_options_are_provided(
    cli_env, capsys
):
    config_path, _runtime_root, _backend = cli_env

    assert main(["--config", str(config_path)]) == 0

    out = capsys.readouterr().out
    assert_summary_table(
        out,
        [
            summary_cells("mysql", "stopped", "enabled", 13306),
            summary_cells("redis", "stopped", "enabled", 16379),
            summary_cells("admin", "stopped", "disabled", 18443),
        ],
    )


def test_cli_defaults_to_global_status_for_empty_argv(cli_env, monkeypatch, capsys):
    config_path, _runtime_root, _backend = cli_env
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.load_config",
        lambda path=None: load_config_file(str(config_path)),
    )

    assert main([]) == 0

    out = capsys.readouterr().out
    assert_summary_table(
        out,
        [
            summary_cells("mysql", "stopped", "enabled", 13306),
            summary_cells("redis", "stopped", "enabled", 16379),
            summary_cells("admin", "stopped", "disabled", 18443),
        ],
    )


def test_cli_status_rejects_filter_flags_with_named_tunnel(cli_env, capsys):
    config_path, _runtime_root, _backend = cli_env

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), "status", "mysql", "--running"])

    assert excinfo.value.code == 2
    assert (
        "Command 'status' does not allow filter flags with a tunnel name."
        in capsys.readouterr().err
    )


def test_cli_install_seeds_template_once_and_preserves_existing_config(
    tmp_path, monkeypatch, capsys
):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(
        "ssm_tunnel_manager.paths.default_data_dir", lambda: runtime_root
    )

    assert main(["install"]) == 0
    out = capsys.readouterr().out
    config_path = runtime_root / "config" / "tunnels.yaml"

    assert f"Seeded template config: {config_path}" in out
    assert f"Runtime root: {runtime_root}" in out
    assert config_path.exists()
    assert (runtime_root / "logs").is_dir()
    assert (runtime_root / "run").is_dir()
    assert config_path.read_text(encoding="utf-8") == packaged_template_config_text()
    assert "BackEnd-692642197054" not in config_path.read_text(encoding="utf-8")

    config_path.write_text("version: 1\ntunnels: []\n", encoding="utf-8")

    assert main(["install"]) == 0
    out = capsys.readouterr().out
    assert f"Preserved existing config: {config_path}" in out
    assert config_path.read_text(encoding="utf-8") == "version: 1\ntunnels: []\n"


def test_cli_install_reinstalls_global_command_from_checkout_before_bootstrap(
    tmp_path, monkeypatch, capsys
):
    runtime_root = tmp_path / "runtime"
    checkout_root = tmp_path / "checkout"
    checkout_root.mkdir()
    calls = []

    monkeypatch.setattr(
        "ssm_tunnel_manager.paths.default_data_dir", lambda: runtime_root
    )
    monkeypatch.setattr(
        cli_module, "detect_checkout_install_root", lambda: checkout_root, raising=False
    )

    def fake_run(command, check, capture_output, text, env):
        calls.append((command, check, capture_output, text, env))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run, raising=False)

    assert main(["install"]) == 0

    out = capsys.readouterr().out
    config_path = runtime_root / "config" / "tunnels.yaml"
    assert len(calls) == 1
    command, check, capture_output, text, env = calls[0]
    assert command == ["uv", "tool", "install", "--reinstall", str(checkout_root)]
    assert check is True
    assert capture_output is True
    assert text is True
    assert env["SSM_TUNNEL_SKIP_SELF_INSTALL"] == "1"
    for key, value in os.environ.items():
        if key == "SSM_TUNNEL_SKIP_SELF_INSTALL":
            continue
        assert env[key] == value
    assert f"Installed or upgraded global command from checkout: {checkout_root}" in out
    assert f"Seeded template config: {config_path}" in out


def test_cli_install_skips_checkout_reinstall_when_loop_guard_is_set(
    tmp_path, monkeypatch, capsys
):
    runtime_root = tmp_path / "runtime"
    config_path = runtime_root / "config" / "tunnels.yaml"
    calls = []

    monkeypatch.setattr(
        "ssm_tunnel_manager.paths.default_data_dir", lambda: runtime_root
    )
    monkeypatch.setenv("SSM_TUNNEL_SKIP_SELF_INSTALL", "1")
    runtime_root.joinpath("config").mkdir(parents=True)
    config_path.write_text("version: 1\ntunnels: []\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run, raising=False)

    assert main(["install"]) == 0

    out = capsys.readouterr().out
    assert calls == []
    assert "Runtime root:" in out
    assert f"Preserved existing config: {config_path}" in out
    assert config_path.read_text(encoding="utf-8") == "version: 1\ntunnels: []\n"


def test_cli_install_seeded_default_config_is_usable(tmp_path, monkeypatch, capsys):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(
        "ssm_tunnel_manager.paths.default_data_dir", lambda: runtime_root
    )
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.check_dependencies", lambda backend_name: []
    )

    assert main(["install"]) == 0
    capsys.readouterr()

    assert main(["status"]) == 0
    assert "No configured tunnels." in capsys.readouterr().out


def test_cli_summary_table_aligns_variable_width_values(tmp_path, monkeypatch, capsys):
    runtime_root = tmp_path / "runtime"
    config_path = write_config(
        tmp_path,
        tunnels_yaml=textwrap.dedent(
            """
        tunnels:
          - name: mysql-replica-west
            remote_host: db.internal
            remote_port: 3306
            local_port: 13306
          - name: redis
            remote_host: cache.internal
            remote_port: 6379
            local_port: 16379
        """
        ).strip(),
    )

    monkeypatch.setattr(
        "ssm_tunnel_manager.paths.default_data_dir", lambda: runtime_root
    )
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.check_dependencies", lambda backend_name: []
    )
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.get_backend", lambda name: FakeBackend()
    )
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.evaluate_tunnel_health",
        lambda tunnel, runtime_state, backend_inspection=None: RuntimeStatus.FAILED
        if runtime_state and runtime_state.error_summary
        else RuntimeStatus.STOPPED,
    )

    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql-replica-west",
            status=RuntimeStatus.FAILED,
            backend="tmux",
            error_summary="session exited with code 255 after reconnect attempt",
        ),
        runtime_root,
    )

    assert main(["--config", str(config_path), "list"]) == 0

    out = capsys.readouterr().out
    assert_summary_table(
        out,
        [
            summary_cells(
                "mysql-replica-west",
                "failed",
                "enabled",
                13306,
                "session exited with code 255 after reconnect attempt",
            ),
            summary_cells("redis", "stopped", "enabled", 16379),
        ],
    )
    assert "db.internal" not in out
    assert "cache.internal" not in out


def test_cli_status_with_name_keeps_detailed_view(cli_env, capsys):
    config_path, runtime_root, _backend = cli_env
    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.RUNNING,
            backend="tmux",
            pid=4101,
            backend_session="ssm-tunnel-mysql",
        ),
        runtime_root,
    )

    assert main(["--config", str(config_path), "status", "mysql"]) == 0

    out = capsys.readouterr().out
    assert "Name: mysql" in out
    assert "Remote: db.internal:3306" in out
    assert "local port" not in out
    assert "name  status" not in out


def test_cli_status_without_name_reports_empty_config(tmp_path, monkeypatch, capsys):
    runtime_root = tmp_path / "runtime"
    config_path = write_config(tmp_path, tunnels_yaml="tunnels: []")

    monkeypatch.setattr(
        "ssm_tunnel_manager.paths.default_data_dir", lambda: runtime_root
    )
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.check_dependencies", lambda backend_name: []
    )

    assert main(["--config", str(config_path), "status"]) == 0

    assert "No configured tunnels." in capsys.readouterr().out


@pytest.mark.parametrize("command", ["start", "stop", "restart"])
def test_cli_rejects_missing_or_mixed_multi_target_selectors(cli_env, command, capsys):
    config_path, _runtime_root, _backend = cli_env

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), command])

    assert excinfo.value.code == 2
    assert (
        f"Command '{command}' requires at least one tunnel name or --all."
        in capsys.readouterr().err
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), command, "mysql", "--all"])

    assert excinfo.value.code == 2
    assert (
        f"Command '{command}' does not allow tunnel names with --all."
        in capsys.readouterr().err
    )


def test_cli_rejects_unknown_multi_target_name(cli_env, capsys):
    config_path, _runtime_root, _backend = cli_env

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), "start", "mysql", "missing"])

    assert excinfo.value.code == 2
    assert "Unknown tunnel: missing" in capsys.readouterr().err


def test_cli_start_supports_multiple_names_in_config_order(cli_env, capsys):
    config_path, runtime_root, backend = cli_env
    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.RUNNING,
            backend="tmux",
            pid=4101,
            backend_session="ssm-tunnel-mysql",
        ),
        runtime_root,
    )

    assert main(["--config", str(config_path), "start", "redis", "mysql"]) == 0

    out = capsys.readouterr().out
    assert "Tunnel 'mysql' is already running." in out
    assert "Started tunnel 'redis' using tmux." in out
    assert [call[0] for call in backend.start_calls] == ["redis"]


def test_cli_start_all_rejects_disabled_tunnels_before_execution(cli_env, capsys):
    config_path, runtime_root, backend = cli_env

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), "start", "--all"])

    assert excinfo.value.code == 2
    assert "Tunnel 'admin' is disabled in config." in capsys.readouterr().err
    assert backend.start_calls == []
    assert load_runtime_state(runtime_root) == {}


def test_cli_start_all_supports_all_enabled_tunnels(tmp_path, monkeypatch, capsys):
    runtime_root = tmp_path / "runtime"
    config_path = write_config(
        tmp_path,
        tunnels_yaml=textwrap.dedent(
            """
        tunnels:
          - name: mysql
            remote_host: db.internal
            remote_port: 3306
            local_port: 13306
          - name: redis
            remote_host: cache.internal
            remote_port: 6379
            local_port: 16379
          - name: admin
            remote_host: admin.internal
            remote_port: 8443
            local_port: 18443
        """
        ).strip(),
    )
    backend = FakeBackend()

    monkeypatch.setattr(
        "ssm_tunnel_manager.paths.default_data_dir", lambda: runtime_root
    )
    monkeypatch.setattr("ssm_tunnel_manager.cli.get_backend", lambda name: backend)
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.check_dependencies",
        lambda backend_name: [
            DependencyCheck(name="aws", ok=True, details="aws CLI found"),
            DependencyCheck(
                name="session-manager-plugin",
                ok=True,
                details="session-manager-plugin found",
            ),
            DependencyCheck(name="tmux", ok=True, details="tmux found"),
        ],
    )
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.evaluate_tunnel_health",
        lambda tunnel, runtime_state, backend_inspection=None: (
            RuntimeStatus.RUNNING
            if runtime_state and backend_inspection and backend_inspection.is_running
            else RuntimeStatus.STOPPED
        ),
    )

    assert main(["--config", str(config_path), "start", "--all"]) == 0

    out = capsys.readouterr().out
    assert "Started tunnel 'mysql' using tmux." in out
    assert "Started tunnel 'redis' using tmux." in out
    assert "Started tunnel 'admin' using tmux." in out
    assert [call[0] for call in backend.start_calls] == ["mysql", "redis", "admin"]

    state = load_runtime_state(runtime_root)
    assert set(state) == {"mysql", "redis", "admin"}
    assert all(tunnel.status is RuntimeStatus.RUNNING for tunnel in state.values())


def test_cli_stop_supports_multiple_names_in_config_order(cli_env, capsys):
    config_path, runtime_root, backend = cli_env
    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.RUNNING,
            backend="tmux",
            pid=4101,
            backend_session="ssm-tunnel-mysql",
        ),
        runtime_root,
    )
    update_tunnel_state(
        TunnelRuntimeState(
            name="redis",
            status=RuntimeStatus.RUNNING,
            backend="tmux",
            pid=4102,
            backend_session="ssm-tunnel-redis",
        ),
        runtime_root,
    )

    assert main(["--config", str(config_path), "stop", "redis", "mysql"]) == 0

    out = capsys.readouterr().out
    assert "Stopped tunnel 'mysql'." in out
    assert "Stopped tunnel 'redis'." in out
    assert backend.stop_calls == ["mysql", "redis"]


def test_cli_stop_all_visits_all_selected_tunnels(cli_env, capsys):
    config_path, runtime_root, backend = cli_env
    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.RUNNING,
            backend="tmux",
            pid=4101,
            backend_session="ssm-tunnel-mysql",
        ),
        runtime_root,
    )

    assert main(["--config", str(config_path), "stop", "--all"]) == 0

    out = capsys.readouterr().out
    assert "Stopped tunnel 'mysql'." in out
    assert "Tunnel 'redis' is not running." in out
    assert "Tunnel 'admin' is not running." in out
    assert backend.stop_calls == ["mysql"]


def test_cli_restart_supports_multiple_names_in_config_order(cli_env, capsys):
    config_path, runtime_root, backend = cli_env
    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.RUNNING,
            backend="tmux",
            pid=4101,
            backend_session="ssm-tunnel-mysql",
        ),
        runtime_root,
    )

    assert main(["--config", str(config_path), "restart", "redis", "mysql"]) == 0

    out = capsys.readouterr().out
    assert "Restarted tunnel 'mysql'." in out
    assert "Skipped tunnel 'redis' (stopped; unchanged)." in out
    assert backend.stop_calls == ["mysql"]
    assert [call[0] for call in backend.start_calls] == ["mysql"]


def test_cli_restart_all_rejects_disabled_tunnels_before_execution(cli_env, capsys):
    config_path, runtime_root, backend = cli_env

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), "restart", "--all"])

    assert excinfo.value.code == 2
    assert "Tunnel 'admin' is disabled in config." in capsys.readouterr().err
    assert backend.stop_calls == []
    assert backend.start_calls == []
    assert load_runtime_state(runtime_root) == {}


def test_cli_restart_all_supports_all_enabled_tunnels(tmp_path, monkeypatch, capsys):
    runtime_root = tmp_path / "runtime"
    config_path = write_config(
        tmp_path,
        tunnels_yaml=textwrap.dedent(
            """
        tunnels:
          - name: mysql
            remote_host: db.internal
            remote_port: 3306
            local_port: 13306
          - name: redis
            remote_host: cache.internal
            remote_port: 6379
            local_port: 16379
          - name: admin
            remote_host: admin.internal
            remote_port: 8443
            local_port: 18443
        """
        ).strip(),
    )
    backend = FakeBackend()

    monkeypatch.setattr(
        "ssm_tunnel_manager.paths.default_data_dir", lambda: runtime_root
    )
    monkeypatch.setattr("ssm_tunnel_manager.cli.get_backend", lambda name: backend)
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.check_dependencies",
        lambda backend_name: [
            DependencyCheck(name="aws", ok=True, details="aws CLI found"),
            DependencyCheck(
                name="session-manager-plugin",
                ok=True,
                details="session-manager-plugin found",
            ),
            DependencyCheck(name="tmux", ok=True, details="tmux found"),
        ],
    )
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.evaluate_tunnel_health",
        lambda tunnel, runtime_state, backend_inspection=None: (
            RuntimeStatus.RUNNING
            if runtime_state and backend_inspection and backend_inspection.is_running
            else RuntimeStatus.STOPPED
        ),
    )

    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.RUNNING,
            backend="tmux",
            pid=4101,
            backend_session="ssm-tunnel-mysql",
        ),
        runtime_root,
    )
    update_tunnel_state(
        TunnelRuntimeState(
            name="redis",
            status=RuntimeStatus.RUNNING,
            backend="tmux",
            pid=4102,
            backend_session="ssm-tunnel-redis",
        ),
        runtime_root,
    )

    assert main(["--config", str(config_path), "restart", "--all"]) == 0

    out = capsys.readouterr().out
    assert "Restarted tunnel 'mysql'." in out
    assert "Restarted tunnel 'redis'." in out
    assert "Skipped tunnel 'admin' (stopped; unchanged)." in out
    assert backend.stop_calls == ["mysql", "redis"]
    assert [call[0] for call in backend.start_calls] == ["mysql", "redis"]


def test_cli_restart_restarts_degraded_tunnel_but_skips_stopped_tunnel(
    cli_env, monkeypatch, capsys
):
    config_path, runtime_root, backend = cli_env
    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.DEGRADED,
            backend="tmux",
            pid=4101,
            backend_session="ssm-tunnel-mysql",
        ),
        runtime_root,
    )
    monkeypatch.setattr(
        "ssm_tunnel_manager.cli.evaluate_tunnel_health",
        lambda tunnel, runtime_state, backend_inspection=None: (
            runtime_state.status if runtime_state else RuntimeStatus.STOPPED
        ),
    )

    assert main(["--config", str(config_path), "restart", "mysql", "redis"]) == 0

    out = capsys.readouterr().out
    assert "Restarted tunnel 'mysql'." in out
    assert "Skipped tunnel 'redis' (stopped; unchanged)." in out
    assert backend.stop_calls == ["mysql"]
    assert [call[0] for call in backend.start_calls] == ["mysql"]


def test_cli_status_unknown_name_exits_with_status_2(cli_env, capsys):
    config_path, _runtime_root, _backend = cli_env

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), "status", "missing"])

    assert excinfo.value.code == 2
    assert "Unknown tunnel: missing" in capsys.readouterr().err


def test_cli_logs_rejects_multiple_target_names(cli_env, capsys):
    config_path, _runtime_root, _backend = cli_env

    with pytest.raises(SystemExit) as excinfo:
        main(["--config", str(config_path), "logs", "mysql", "redis"])

    assert excinfo.value.code == 2
    assert "unrecognized arguments: redis" in capsys.readouterr().err
