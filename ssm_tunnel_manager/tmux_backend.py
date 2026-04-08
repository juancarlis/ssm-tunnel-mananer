from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from ssm_tunnel_manager.backend import BackendError
from ssm_tunnel_manager.models import (
    BackendInspection,
    BackendStartResult,
    EffectiveTunnel,
    TunnelRuntimeState,
)


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def tmux_session_name(name: str) -> str:
    safe_name = "".join(char if char.isalnum() else "-" for char in name)
    return f"ssm-tunnel-{safe_name}"


class TmuxBackend:
    name = "tmux"

    def __init__(self, runner=_run_command):
        self._runner = runner

    def start(
        self, tunnel: EffectiveTunnel, command: list[str], log_path: Path
    ) -> BackendStartResult:
        session_name = tmux_session_name(tunnel.name)
        shell_command = (
            f"exec {shlex.join(command)} >> {shlex.quote(str(log_path))} 2>&1"
        )
        try:
            self._runner(
                ["tmux", "new-session", "-d", "-s", session_name, shell_command]
            )
            pane_info = self._runner(
                ["tmux", "display-message", "-p", "-t", session_name, "#{pane_pid}"]
            )
        except subprocess.CalledProcessError as exc:
            raise BackendError(f"tmux start failed for tunnel '{tunnel.name}'") from exc

        pid = _parse_pid(pane_info.stdout)
        return BackendStartResult(backend_session=session_name, pid=pid)

    def stop(self, runtime_state: TunnelRuntimeState) -> None:
        if not runtime_state.backend_session:
            raise BackendError(
                f"Tunnel '{runtime_state.name}' has no tmux session reference"
            )

        try:
            self._runner(["tmux", "kill-session", "-t", runtime_state.backend_session])
        except subprocess.CalledProcessError as exc:
            raise BackendError(
                f"tmux stop failed for tunnel '{runtime_state.name}'"
            ) from exc

    def inspect(self, runtime_state: TunnelRuntimeState) -> BackendInspection:
        if not runtime_state.backend_session:
            return BackendInspection(is_running=False)

        try:
            self._runner(["tmux", "has-session", "-t", runtime_state.backend_session])
        except subprocess.CalledProcessError:
            return BackendInspection(
                is_running=False, backend_session=runtime_state.backend_session
            )

        pane_info = self._runner(
            [
                "tmux",
                "display-message",
                "-p",
                "-t",
                runtime_state.backend_session,
                "#{pane_pid}",
            ]
        )
        return BackendInspection(
            is_running=True,
            backend_session=runtime_state.backend_session,
            pid=_parse_pid(pane_info.stdout),
        )


def _parse_pid(value: str) -> int | None:
    stripped = value.strip()
    if stripped.isdigit():
        return int(stripped)
    return None
