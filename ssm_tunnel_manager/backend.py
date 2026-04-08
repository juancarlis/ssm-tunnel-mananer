from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ssm_tunnel_manager.models import (
    BackendInspection,
    BackendStartResult,
    EffectiveTunnel,
    TunnelRuntimeState,
)


class BackendError(RuntimeError):
    """Raised when a runtime backend cannot perform an operation."""


class TunnelBackend(Protocol):
    name: str

    def start(
        self, tunnel: EffectiveTunnel, command: list[str], log_path: Path
    ) -> BackendStartResult: ...

    def stop(self, runtime_state: TunnelRuntimeState) -> None: ...

    def inspect(self, runtime_state: TunnelRuntimeState) -> BackendInspection: ...


def get_backend(name: str):
    if name == "tmux":
        from ssm_tunnel_manager.tmux_backend import TmuxBackend

        return TmuxBackend()
    raise BackendError(f"Unsupported backend: {name}")
