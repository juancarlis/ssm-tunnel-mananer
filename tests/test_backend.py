from __future__ import annotations

import subprocess

import pytest

from ssm_tunnel_manager.backend import BackendError
from ssm_tunnel_manager.models import (
    AwsSettings,
    EffectiveTunnel,
    RuntimeStatus,
    TunnelRuntimeState,
)
from ssm_tunnel_manager.tmux_backend import TmuxBackend, tmux_session_name


def make_tunnel() -> EffectiveTunnel:
    return EffectiveTunnel(
        name="mysql",
        remote_host="db.internal",
        remote_port=3306,
        local_port=13306,
        description=None,
        tags=[],
        enabled=True,
        aws=AwsSettings(
            region="us-east-1",
            target="i-1234567890",
            profile="team-profile",
            document="AWS-StartPortForwardingSessionToRemoteHost",
        ),
    )


def test_tmux_backend_starts_session_and_reads_pane_pid(tmp_path):
    calls = []

    def runner(command: list[str]):
        calls.append(command)
        if command[:3] == ["tmux", "display-message", "-p"]:
            return subprocess.CompletedProcess(command, 0, stdout="4567\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    backend = TmuxBackend(runner=runner)
    result = backend.start(
        make_tunnel(), ["aws", "ssm", "start-session"], tmp_path / "mysql.log"
    )

    assert result.backend_session == tmux_session_name("mysql")
    assert result.pid == 4567
    assert calls[0][:5] == ["tmux", "new-session", "-d", "-s", "ssm-tunnel-mysql"]
    assert "exec aws ssm start-session" in calls[0][-1]
    assert str(tmp_path / "mysql.log") in calls[0][-1]


def test_tmux_backend_stop_requires_session_reference():
    backend = TmuxBackend(
        runner=lambda command: subprocess.CompletedProcess(command, 0)
    )

    with pytest.raises(BackendError, match="has no tmux session reference"):
        backend.stop(TunnelRuntimeState(name="mysql", status=RuntimeStatus.RUNNING))


def test_tmux_backend_reports_missing_session_as_not_running():
    def runner(command: list[str]):
        if command[:3] == ["tmux", "has-session", "-t"]:
            raise subprocess.CalledProcessError(returncode=1, cmd=command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    backend = TmuxBackend(runner=runner)
    inspection = backend.inspect(
        TunnelRuntimeState(
            name="mysql",
            status=RuntimeStatus.RUNNING,
            backend_session="ssm-tunnel-mysql",
        )
    )

    assert inspection.is_running is False
    assert inspection.backend_session == "ssm-tunnel-mysql"
