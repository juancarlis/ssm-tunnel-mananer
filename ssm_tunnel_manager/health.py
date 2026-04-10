from __future__ import annotations

import os
import shutil
import socket
from pathlib import Path
from typing import Callable

from ssm_tunnel_manager.command_builder import build_start_session_command
from ssm_tunnel_manager.models import (
    BackendInspection,
    DependencyCheck,
    EffectiveTunnel,
    RuntimeStatus,
    TunnelRuntimeState,
)


def check_dependencies(
    backend: str, interactive: bool = False
) -> list[DependencyCheck]:
    checks = [
        _check_binary("aws", "aws CLI found"),
        _check_binary("session-manager-plugin", "session-manager-plugin found"),
    ]
    if backend == "tmux":
        checks.append(_check_binary("tmux", "tmux found"))
    return checks


def evaluate_tunnel_health(
    tunnel: EffectiveTunnel,
    runtime_state: TunnelRuntimeState | None,
    backend_inspection: BackendInspection | None = None,
    process_exists: Callable[[int], bool] | None = None,
    command_reader: Callable[[int], str | None] | None = None,
    port_listener: Callable[[int], bool] | None = None,
) -> RuntimeStatus:
    if runtime_state is None:
        return RuntimeStatus.STOPPED

    pid = runtime_state.pid
    if backend_inspection is not None and backend_inspection.pid is not None:
        pid = backend_inspection.pid

    backend_running = (
        True if backend_inspection is None else backend_inspection.is_running
    )

    if pid is None:
        if runtime_state.status == RuntimeStatus.FAILED:
            return RuntimeStatus.FAILED
        return RuntimeStatus.UNKNOWN if backend_running else RuntimeStatus.STOPPED

    process_exists = process_exists or _process_exists
    command_reader = command_reader or read_process_command
    port_listener = port_listener or is_local_port_listening

    if not process_exists(pid):
        return (
            RuntimeStatus.FAILED
            if runtime_state.status == RuntimeStatus.FAILED
            else RuntimeStatus.STOPPED
        )

    process_command = command_reader(pid)
    if process_command is None:
        return RuntimeStatus.UNKNOWN

    expected_command = build_start_session_command(tunnel)
    if not _command_matches(process_command, expected_command):
        return RuntimeStatus.DEGRADED

    if not port_listener(tunnel.local_port):
        return RuntimeStatus.DEGRADED

    return RuntimeStatus.RUNNING if backend_running else RuntimeStatus.DEGRADED


def read_process_command(pid: int, proc_root: Path | None = None) -> str | None:
    proc_dir = proc_root or Path("/proc")
    cmdline_path = proc_dir / str(pid) / "cmdline"
    try:
        raw_cmdline = cmdline_path.read_bytes()
    except FileNotFoundError:
        return None
    return (
        raw_cmdline.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
        or None
    )


def is_local_port_listening(
    port: int, host: str = "127.0.0.1", timeout: float = 0.2
) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _check_binary(name: str, ok_details: str) -> DependencyCheck:
    location = shutil.which(name)
    if location:
        return DependencyCheck(name=name, ok=True, details=ok_details)
    return DependencyCheck(name=name, ok=False, details=f"{name} not found")


def _command_matches(process_command: str, expected_command: list[str]) -> bool:
    expected_tokens = [token for token in expected_command if token != "--parameters"]
    return all(token in process_command for token in expected_tokens)
