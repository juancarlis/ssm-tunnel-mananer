from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RuntimeStatus(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class DesiredTunnelState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass(slots=True)
class AwsSettings:
    region: str | None = None
    target: str | None = None
    profile: str | None = None
    document: str | None = None

    def merge(self, override: "AwsSettings | None") -> "AwsSettings":
        if override is None:
            return AwsSettings(
                region=self.region,
                target=self.target,
                profile=self.profile,
                document=self.document,
            )

        return AwsSettings(
            region=override.region or self.region,
            target=override.target or self.target,
            profile=override.profile or self.profile,
            document=override.document or self.document,
        )

    def missing_fields(self) -> list[str]:
        missing = []
        for field_name in ("region", "target", "profile", "document"):
            if not getattr(self, field_name):
                missing.append(field_name)
        return missing


@dataclass(slots=True)
class DefaultsConfig:
    aws: AwsSettings = field(default_factory=AwsSettings)
    backend: str = "tmux"


@dataclass(slots=True)
class TunnelDefinition:
    name: str
    remote_host: str
    remote_port: int
    local_port: int
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    aws: AwsSettings | None = None


@dataclass(slots=True)
class EffectiveTunnel:
    name: str
    remote_host: str
    remote_port: int
    local_port: int
    description: str | None
    tags: list[str]
    enabled: bool
    aws: AwsSettings


@dataclass(slots=True)
class TunnelRuntimeState:
    name: str
    status: RuntimeStatus = RuntimeStatus.STOPPED
    desired_state: DesiredTunnelState = DesiredTunnelState.STOPPED
    backend: str = "tmux"
    pid: int | None = None
    started_at: str | None = None
    last_health_check_at: str | None = None
    last_exit_code: int | None = None
    log_path: str | None = None
    backend_session: str | None = None
    error_summary: str | None = None


@dataclass(slots=True)
class BackendStartResult:
    backend_session: str | None = None
    pid: int | None = None


@dataclass(slots=True)
class BackendInspection:
    is_running: bool
    backend_session: str | None = None
    pid: int | None = None


@dataclass(slots=True)
class DependencyCheck:
    name: str
    ok: bool
    details: str


@dataclass(slots=True)
class AppConfig:
    version: int
    defaults: DefaultsConfig
    tunnels: list[TunnelDefinition]
    effective_tunnels: list[EffectiveTunnel]

    def get_tunnel(self, name: str) -> EffectiveTunnel:
        for tunnel in self.effective_tunnels:
            if tunnel.name == name:
                return tunnel
        raise KeyError(name)
