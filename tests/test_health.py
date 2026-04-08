from __future__ import annotations

from ssm_tunnel_manager.health import (
    check_dependencies,
    evaluate_tunnel_health,
    read_process_command,
)
from ssm_tunnel_manager.models import (
    AwsSettings,
    BackendInspection,
    EffectiveTunnel,
    RuntimeStatus,
    TunnelRuntimeState,
)


def make_tunnel(local_port: int = 13306) -> EffectiveTunnel:
    return EffectiveTunnel(
        name="mysql",
        remote_host="db.internal",
        remote_port=3306,
        local_port=local_port,
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


def test_dependency_checks_include_tmux_for_tmux_backend(monkeypatch):
    locations = {
        "aws": "/usr/bin/aws",
        "session-manager-plugin": "/usr/bin/session-manager-plugin",
        "tmux": None,
    }
    monkeypatch.setattr("shutil.which", lambda name: locations.get(name))

    checks = check_dependencies("tmux")

    assert [check.name for check in checks] == ["aws", "session-manager-plugin", "tmux"]
    assert checks[-1].ok is False


def test_read_process_command_normalizes_proc_cmdline(tmp_path):
    cmdline_path = tmp_path / "4242" / "cmdline"
    cmdline_path.parent.mkdir(parents=True)
    cmdline_path.write_bytes(b"aws\x00ssm\x00start-session\x00")

    assert read_process_command(4242, proc_root=tmp_path) == "aws ssm start-session"


def test_health_is_running_when_process_command_and_port_match():
    status = evaluate_tunnel_health(
        make_tunnel(),
        TunnelRuntimeState(name="mysql", status=RuntimeStatus.RUNNING, pid=4242),
        backend_inspection=BackendInspection(is_running=True, pid=4242),
        process_exists=lambda pid: True,
        command_reader=lambda pid: (
            "aws ssm start-session --region us-east-1 --target i-1234567890 "
            "--document-name AWS-StartPortForwardingSessionToRemoteHost "
            "host=db.internal,portNumber=3306,localPortNumber=13306 --profile team-profile"
        ),
        port_listener=lambda port: True,
    )

    assert status is RuntimeStatus.RUNNING


def test_health_is_degraded_when_port_is_not_listening():
    status = evaluate_tunnel_health(
        make_tunnel(),
        TunnelRuntimeState(name="mysql", status=RuntimeStatus.RUNNING, pid=4242),
        backend_inspection=BackendInspection(is_running=True, pid=4242),
        process_exists=lambda pid: True,
        command_reader=lambda pid: "aws ssm start-session --region us-east-1 --target i-1234567890",
        port_listener=lambda port: False,
    )

    assert status is RuntimeStatus.DEGRADED


def test_health_preserves_failed_state_when_process_is_missing():
    status = evaluate_tunnel_health(
        make_tunnel(),
        TunnelRuntimeState(name="mysql", status=RuntimeStatus.FAILED, pid=4242),
        process_exists=lambda pid: False,
        command_reader=lambda pid: None,
        port_listener=lambda port: False,
    )

    assert status is RuntimeStatus.FAILED
