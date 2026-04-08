from __future__ import annotations

from ssm_tunnel_manager.models import EffectiveTunnel


def build_start_session_command(tunnel: EffectiveTunnel) -> list[str]:
    return [
        "aws",
        "ssm",
        "start-session",
        "--region",
        tunnel.aws.region,
        "--target",
        tunnel.aws.target,
        "--document-name",
        tunnel.aws.document,
        "--parameters",
        (
            f"host={tunnel.remote_host},"
            f"portNumber={tunnel.remote_port},"
            f"localPortNumber={tunnel.local_port}"
        ),
        "--profile",
        tunnel.aws.profile,
    ]
