from __future__ import annotations

from pathlib import Path

from ssm_tunnel_manager.paths import ensure_runtime_dirs, tunnel_log_path


def ensure_tunnel_log(name: str, root: str | Path | None = None) -> Path:
    ensure_runtime_dirs(root)
    path = tunnel_log_path(name, root)
    path.touch(exist_ok=True)
    return path


def append_tunnel_log(name: str, message: str, root: str | Path | None = None) -> Path:
    path = ensure_tunnel_log(name, root)
    line = message if message.endswith("\n") else f"{message}\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    return path


def read_tunnel_log(
    name: str, root: str | Path | None = None, max_lines: int | None = None
) -> list[str]:
    path = ensure_tunnel_log(name, root)
    lines = path.read_text(encoding="utf-8").splitlines()
    if max_lines is None or max_lines >= len(lines):
        return lines
    return lines[-max_lines:]


def summarize_tunnel_log(name: str, root: str | Path | None = None) -> str | None:
    for line in reversed(read_tunnel_log(name, root)):
        if line.strip():
            return line.strip()
    return None
