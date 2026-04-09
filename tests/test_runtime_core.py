from __future__ import annotations

import json

from ssm_tunnel_manager.command_builder import build_start_session_command
from ssm_tunnel_manager.logs import (
    append_tunnel_log,
    read_tunnel_log,
    summarize_tunnel_log,
)
from ssm_tunnel_manager.models import (
    AwsSettings,
    DesiredTunnelState,
    EffectiveTunnel,
    RuntimeStatus,
    TunnelRuntimeState,
)
from ssm_tunnel_manager.paths import (
    ensure_runtime_dirs,
    runtime_state_path,
    tunnel_log_path,
    tunnel_pid_path,
)
from ssm_tunnel_manager.state import (
    load_runtime_state,
    remove_tunnel_state,
    update_tunnel_state,
)


def make_tunnel(name: str = "mysql", local_port: int = 13306) -> EffectiveTunnel:
    return EffectiveTunnel(
        name=name,
        remote_host="db.internal",
        remote_port=3306,
        local_port=local_port,
        description=None,
        tags=["db"],
        enabled=True,
        aws=AwsSettings(
            region="us-east-1",
            target="i-1234567890",
            profile="team-profile",
            document="AWS-StartPortForwardingSessionToRemoteHost",
        ),
    )


def test_builds_canonical_aws_ssm_command():
    tunnel = make_tunnel()

    assert build_start_session_command(tunnel) == [
        "aws",
        "ssm",
        "start-session",
        "--region",
        "us-east-1",
        "--target",
        "i-1234567890",
        "--document-name",
        "AWS-StartPortForwardingSessionToRemoteHost",
        "--parameters",
        "host=db.internal,portNumber=3306,localPortNumber=13306",
        "--profile",
        "team-profile",
    ]


def test_runtime_paths_create_expected_layout(tmp_path):
    ensure_runtime_dirs(tmp_path)

    assert tunnel_log_path("mysql", tmp_path) == tmp_path / "logs" / "mysql.log"
    assert tunnel_pid_path("mysql", tmp_path) == tmp_path / "run" / "mysql.pid"
    assert runtime_state_path(tmp_path) == tmp_path / "run" / "state.json"
    assert (tmp_path / "config").is_dir()
    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / "run").is_dir()


def test_persists_runtime_state_to_json(tmp_path):
    update_tunnel_state(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.RUNNING,
            pid=4242,
            backend_session="ssm-tunnel-mysql",
            log_path=str(tunnel_log_path("mysql", tmp_path)),
        ),
        tmp_path,
    )

    state = load_runtime_state(tmp_path)

    assert state["mysql"].status is RuntimeStatus.RUNNING
    assert state["mysql"].desired_state is DesiredTunnelState.STOPPED
    assert state["mysql"].pid == 4242
    assert (
        json.loads(runtime_state_path(tmp_path).read_text(encoding="utf-8"))["version"]
        == 1
    )


def test_runtime_state_loads_legacy_running_entries_with_running_desired_state(
    tmp_path,
):
    ensure_runtime_dirs(tmp_path)
    runtime_state_path(tmp_path).write_text(
        json.dumps(
            {
                "version": 1,
                "tunnels": {
                    "mysql": {
                        "status": "running",
                        "backend": "tmux",
                        "pid": 4242,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    state = load_runtime_state(tmp_path)

    assert state["mysql"].status is RuntimeStatus.RUNNING
    assert state["mysql"].desired_state is DesiredTunnelState.RUNNING


def test_remove_tunnel_state_updates_state_file(tmp_path):
    update_tunnel_state(
        TunnelRuntimeState(name="mysql", status=RuntimeStatus.RUNNING), tmp_path
    )
    update_tunnel_state(
        TunnelRuntimeState(name="mssql", status=RuntimeStatus.STOPPED), tmp_path
    )

    state = remove_tunnel_state("mysql", tmp_path)

    assert "mysql" not in state
    assert set(load_runtime_state(tmp_path)) == {"mssql"}


def test_appends_and_reads_per_tunnel_logs(tmp_path):
    append_tunnel_log("mysql", "line one", tmp_path)
    append_tunnel_log("mysql", "line two", tmp_path)

    assert read_tunnel_log("mysql", tmp_path, max_lines=1) == ["line two"]
    assert summarize_tunnel_log("mysql", tmp_path) == "line two"
