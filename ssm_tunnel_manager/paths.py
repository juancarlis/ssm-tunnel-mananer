from __future__ import annotations

from importlib.resources.abc import Traversable
from importlib.resources import files
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def detect_checkout_install_root(start: str | Path | None = None) -> Path | None:
    current = resolve_path(start) if start is not None else Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "ssm_tunnel_manager" / "__init__.py"
        ).is_file():
            return candidate
    return None


def resolve_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def default_config_path(root: str | Path | None = None) -> Path:
    return config_dir(root) / "tunnels.yaml"


def packaged_template_config_path() -> Traversable:
    return files("ssm_tunnel_manager").joinpath("templates", "tunnels.yaml")


def packaged_template_config_text() -> str:
    return packaged_template_config_path().read_text(encoding="utf-8")


def default_data_dir() -> Path:
    return Path("~/.local/share/ssm-tunnels").expanduser()


def data_dir(root: str | Path | None = None) -> Path:
    if root is None:
        return default_data_dir()
    return resolve_path(root)


def config_dir(root: str | Path | None = None) -> Path:
    return data_dir(root) / "config"


def logs_dir(root: str | Path | None = None) -> Path:
    return data_dir(root) / "logs"


def run_dir(root: str | Path | None = None) -> Path:
    return data_dir(root) / "run"


def runtime_state_path(root: str | Path | None = None) -> Path:
    return run_dir(root) / "state.json"


def tunnel_log_path(name: str, root: str | Path | None = None) -> Path:
    return logs_dir(root) / f"{name}.log"


def tunnel_pid_path(name: str, root: str | Path | None = None) -> Path:
    return run_dir(root) / f"{name}.pid"


def ensure_runtime_dirs(root: str | Path | None = None) -> Path:
    base_dir = data_dir(root)
    for path in (config_dir(base_dir), logs_dir(base_dir), run_dir(base_dir)):
        path.mkdir(parents=True, exist_ok=True)
    return base_dir
