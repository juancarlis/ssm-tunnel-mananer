from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ssm_tunnel_manager.models import (
    AppConfig,
    AwsSettings,
    DefaultsConfig,
    EffectiveTunnel,
    TunnelDefinition,
)
from ssm_tunnel_manager.paths import default_config_path, resolve_path


class ConfigError(ValueError):
    """Raised when the operator-provided config is invalid."""


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = (
        resolve_path(path) if path is not None else default_config_path().resolve()
    )

    try:
        raw_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc

    if raw_data is None:
        raw_data = {}
    if not isinstance(raw_data, dict):
        raise ConfigError("Config root must be a mapping")

    version = raw_data.get("version", 1)
    defaults = _parse_defaults(raw_data.get("defaults"))

    raw_tunnels = raw_data.get("tunnels", [])
    if not isinstance(raw_tunnels, list):
        raise ConfigError("tunnels must be a list")

    tunnels = [
        _parse_tunnel(item, index) for index, item in enumerate(raw_tunnels, start=1)
    ]
    effective_tunnels = _build_effective_tunnels(tunnels, defaults.aws)
    _validate_tunnels(effective_tunnels)

    return AppConfig(
        version=version,
        defaults=defaults,
        tunnels=tunnels,
        effective_tunnels=effective_tunnels,
    )


def _parse_defaults(raw_defaults: Any) -> DefaultsConfig:
    if raw_defaults is None:
        raw_defaults = {}
    if not isinstance(raw_defaults, dict):
        raise ConfigError("defaults must be a mapping")

    raw_aws = raw_defaults.get("aws")
    raw_ui = raw_defaults.get("ui")

    if raw_ui is None:
        raw_ui = {}
    if not isinstance(raw_ui, dict):
        raise ConfigError("defaults.ui must be a mapping")

    aws_settings = _parse_aws_settings(raw_aws) or AwsSettings()

    return DefaultsConfig(
        aws=aws_settings,
        backend=str(raw_ui.get("backend", "tmux")),
    )


def _parse_tunnel(raw_tunnel: Any, index: int) -> TunnelDefinition:
    if not isinstance(raw_tunnel, dict):
        raise ConfigError(f"Tunnel #{index} must be a mapping")

    tags = raw_tunnel.get("tags", [])
    if tags is None:
        tags = []
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ConfigError(f"Tunnel #{index} tags must be a list of strings")

    try:
        return TunnelDefinition(
            name=_require_string(raw_tunnel, "name", index),
            remote_host=_require_string(raw_tunnel, "remote_host", index),
            remote_port=_require_int(raw_tunnel, "remote_port", index),
            local_port=_require_int(raw_tunnel, "local_port", index),
            description=_optional_string(
                raw_tunnel.get("description"), f"Tunnel #{index} description"
            ),
            tags=tags,
            enabled=bool(raw_tunnel.get("enabled", True)),
            aws=_parse_aws_settings(raw_tunnel.get("aws")),
        )
    except KeyError as exc:
        raise ConfigError(
            f"Tunnel #{index} is missing required field: {exc.args[0]}"
        ) from exc


def _build_effective_tunnels(
    tunnels: list[TunnelDefinition], default_aws: AwsSettings
) -> list[EffectiveTunnel]:
    effective_tunnels = []
    for tunnel in tunnels:
        merged_aws = default_aws.merge(tunnel.aws)
        missing_fields = merged_aws.missing_fields()
        if missing_fields:
            missing = ", ".join(missing_fields)
            raise ConfigError(
                f"Tunnel '{tunnel.name}' is missing required AWS settings after merge: {missing}"
            )

        effective_tunnels.append(
            EffectiveTunnel(
                name=tunnel.name,
                remote_host=tunnel.remote_host,
                remote_port=tunnel.remote_port,
                local_port=tunnel.local_port,
                description=tunnel.description,
                tags=list(tunnel.tags),
                enabled=tunnel.enabled,
                aws=merged_aws,
            )
        )
    return effective_tunnels


def _validate_tunnels(tunnels: list[EffectiveTunnel]) -> None:
    seen_names: set[str] = set()
    enabled_ports: dict[int, str] = {}

    for tunnel in tunnels:
        if tunnel.name in seen_names:
            raise ConfigError(f"Duplicate tunnel name: {tunnel.name}")
        seen_names.add(tunnel.name)

        _validate_port(tunnel.name, "remote_port", tunnel.remote_port)
        _validate_port(tunnel.name, "local_port", tunnel.local_port)

        if not tunnel.enabled:
            continue

        existing_name = enabled_ports.get(tunnel.local_port)
        if existing_name is not None:
            raise ConfigError(
                f"Enabled tunnels '{existing_name}' and '{tunnel.name}' both use local_port {tunnel.local_port}"
            )
        enabled_ports[tunnel.local_port] = tunnel.name


def _parse_aws_settings(raw_aws: Any) -> AwsSettings | None:
    if raw_aws is None:
        return None
    if not isinstance(raw_aws, dict):
        raise ConfigError("aws must be a mapping")

    return AwsSettings(
        region=_optional_string(raw_aws.get("region"), "aws.region"),
        target=_optional_string(raw_aws.get("target"), "aws.target"),
        profile=_optional_string(raw_aws.get("profile"), "aws.profile"),
        document=_optional_string(raw_aws.get("document"), "aws.document"),
    )


def _require_string(data: dict[str, Any], field_name: str, index: int) -> str:
    value = data[field_name]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"Tunnel #{index} field '{field_name}' must be a non-empty string"
        )
    return value.strip()


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{label} must be a string")
    stripped = value.strip()
    return stripped or None


def _require_int(data: dict[str, Any], field_name: str, index: int) -> int:
    value = data[field_name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"Tunnel #{index} field '{field_name}' must be an integer")
    return value


def _validate_port(tunnel_name: str, field_name: str, value: int) -> None:
    if not 1 <= value <= 65535:
        raise ConfigError(f"Tunnel '{tunnel_name}' has invalid {field_name}: {value}")
