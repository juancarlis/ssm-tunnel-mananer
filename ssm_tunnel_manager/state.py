from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ssm_tunnel_manager.models import RuntimeStatus, TunnelRuntimeState
from ssm_tunnel_manager.paths import ensure_runtime_dirs, runtime_state_path


def load_runtime_state(root: str | Path | None = None) -> dict[str, TunnelRuntimeState]:
    path = runtime_state_path(root)
    if not path.exists():
        return {}

    raw_state = json.loads(path.read_text(encoding="utf-8"))
    tunnels = raw_state.get("tunnels", {}) if isinstance(raw_state, dict) else {}
    if not isinstance(tunnels, dict):
        return {}

    return {
        name: _deserialize_tunnel_state(name, payload)
        for name, payload in tunnels.items()
        if isinstance(payload, dict)
    }


def save_runtime_state(
    tunnel_states: dict[str, TunnelRuntimeState], root: str | Path | None = None
) -> Path:
    ensure_runtime_dirs(root)
    path = runtime_state_path(root)
    payload = {
        "version": 1,
        "tunnels": {
            name: _serialize_tunnel_state(state)
            for name, state in sorted(tunnel_states.items())
        },
    }
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temp_path.replace(path)
    return path


def update_tunnel_state(
    tunnel_state: TunnelRuntimeState, root: str | Path | None = None
) -> dict[str, TunnelRuntimeState]:
    states = load_runtime_state(root)
    states[tunnel_state.name] = tunnel_state
    save_runtime_state(states, root)
    return states


def remove_tunnel_state(
    name: str, root: str | Path | None = None
) -> dict[str, TunnelRuntimeState]:
    states = load_runtime_state(root)
    states.pop(name, None)
    save_runtime_state(states, root)
    return states


def _serialize_tunnel_state(state: TunnelRuntimeState) -> dict[str, object]:
    payload = asdict(state)
    payload["status"] = state.status.value
    return payload


def _deserialize_tunnel_state(
    name: str, payload: dict[str, object]
) -> TunnelRuntimeState:
    status = payload.get("status", RuntimeStatus.UNKNOWN.value)
    status_value = RuntimeStatus(status)
    return TunnelRuntimeState(
        name=name,
        status=status_value,
        backend=_optional_str(payload.get("backend")) or "tmux",
        pid=_optional_int(payload.get("pid")),
        started_at=_optional_str(payload.get("started_at")),
        last_health_check_at=_optional_str(payload.get("last_health_check_at")),
        last_exit_code=_optional_int(payload.get("last_exit_code")),
        log_path=_optional_str(payload.get("log_path")),
        backend_session=_optional_str(payload.get("backend_session")),
        error_summary=_optional_str(payload.get("error_summary")),
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
