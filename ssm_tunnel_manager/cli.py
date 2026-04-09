from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime

from ssm_tunnel_manager import __version__
from ssm_tunnel_manager.backend import BackendError, get_backend
from ssm_tunnel_manager.command_builder import build_start_session_command
from ssm_tunnel_manager.config import ConfigError, load_config
from ssm_tunnel_manager.health import check_dependencies, evaluate_tunnel_health
from ssm_tunnel_manager.logs import (
    append_tunnel_log,
    ensure_tunnel_log,
    read_tunnel_log,
    summarize_tunnel_log,
)
from ssm_tunnel_manager.models import (
    AppConfig,
    DesiredTunnelState,
    EffectiveTunnel,
    RuntimeStatus,
    TunnelRuntimeState,
)
from ssm_tunnel_manager.paths import (
    default_config_path,
    ensure_runtime_dirs,
    packaged_template_config_text,
)
from ssm_tunnel_manager.state import load_runtime_state, update_tunnel_state


SELF_INSTALL_SKIP_ENV = "SSM_TUNNEL_SKIP_SELF_INSTALL"
PACKAGE_SPEC_ENV = "SSM_TUNNEL_PACKAGE_SPEC"
PACKAGED_TOOL_NAME = "ssm-tunnel-manager"
DEFAULT_PACKAGE_SPEC = "git+https://github.com/juancarlis/ssm-tunnel-mananer.git"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ssm-tunnel", description="Manage AWS SSM tunnels"
    )
    parser.add_argument("--config", help="Path to the YAML config file")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("help", help="Show command usage")
    subparsers.add_parser(
        "upgrade",
        help="Upgrade the packaged CLI and bootstrap runtime/config state",
    )
    subparsers.add_parser(
        "uninstall",
        help="Remove the packaged CLI installed via uv tool",
    )
    subparsers.add_parser("login", help="Run AWS SSO login for the default profile")
    subparsers.add_parser("list", help="Show configured tunnels")

    for command in ("start", "stop", "restart"):
        command_parser = subparsers.add_parser(
            command, help=f"{command.title()} tunnel targets"
        )
        command_parser.add_argument("names", nargs="*", help="Tunnel names")
        command_parser.add_argument(
            "--all", action="store_true", help="Select all configured tunnels"
        )

    status_parser = subparsers.add_parser("status", help="Show tunnel status")
    status_parser.add_argument("name", nargs="?", help="Tunnel name")
    status_parser.add_argument(
        "--running", action="store_true", help="Show only running tunnels"
    )
    status_parser.add_argument(
        "--stopped", action="store_true", help="Show only stopped tunnels"
    )
    status_parser.add_argument(
        "--enabled", action="store_true", help="Show only enabled tunnels"
    )
    status_parser.add_argument(
        "--disabled", action="store_true", help="Show only disabled tunnels"
    )

    logs_parser = subparsers.add_parser("logs", help="Show tunnel logs")
    logs_parser.add_argument("name", help="Tunnel name")

    subparsers.add_parser("tui", help="Launch the interactive tunnel picker")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(_normalize_argv(sys.argv[1:] if argv is None else argv))

    if args.command == "help":
        return _run_help_command(parser)
    if args.command == "upgrade":
        return _run_upgrade_command()
    if args.command == "uninstall":
        return _run_uninstall_command()

    if args.command == "tui":
        from ssm_tunnel_manager.tui import SelectorError, launch

        try:
            selection = launch(None)
        except SelectorError as exc:
            parser.exit(status=4, message=f"TUI error: {exc}\n")
        if selection is None:
            return 0
        if selection.command == "help":
            return _run_help_command(parser)
        if selection.command == "upgrade":
            return _run_upgrade_command()
        if selection.command == "uninstall":
            return _run_uninstall_command()

        config = _load_config_or_exit(args.config, parser)
        if selection.command == "tui":
            try:
                selection = launch(config, action=selection.action)
            except SelectorError as exc:
                parser.exit(status=4, message=f"TUI error: {exc}\n")
            if selection is None:
                return 0

        return _dispatch_command(selection, parser, config)

    config = _load_config_or_exit(args.config, parser)
    return _dispatch_command(args, parser, config)


def _load_config_or_exit(
    config_path: str | None, parser: argparse.ArgumentParser
) -> AppConfig:
    try:
        return load_config(config_path)
    except ConfigError as exc:
        parser.exit(status=2, message=f"Config error: {exc}\n")
        raise AssertionError("unreachable")


def _run_help_command(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 0


def _dispatch_command(
    args: argparse.Namespace, parser: argparse.ArgumentParser, config: AppConfig
) -> int:
    if args.command == "help":
        return _run_help_command(parser)

    if args.command == "list":
        return _run_list_command(config)
    if args.command == "login":
        return _run_login_command(config, parser)
    if args.command == "start":
        tunnels = _resolve_target_tunnels(
            config,
            command="start",
            names=getattr(args, "names", []),
            select_all=getattr(args, "all", False),
            parser=parser,
            require_enabled=True,
        )
        return _run_start_command(config, tunnels, parser)
    if args.command == "stop":
        tunnels = _resolve_target_tunnels(
            config,
            command="stop",
            names=getattr(args, "names", []),
            select_all=getattr(args, "all", False),
            parser=parser,
        )
        return _run_stop_command(config, tunnels, parser)
    if args.command == "restart":
        tunnels = _resolve_target_tunnels(
            config,
            command="restart",
            names=getattr(args, "names", []),
            select_all=getattr(args, "all", False),
            parser=parser,
            require_enabled=True,
        )
        return _run_restart_command(config, tunnels, parser)
    if args.command == "status":
        return _run_status_command(
            config,
            getattr(args, "name", None),
            parser,
            running=getattr(args, "running", False),
            stopped=getattr(args, "stopped", False),
            enabled=getattr(args, "enabled", False),
            disabled=getattr(args, "disabled", False),
        )
    if args.command == "logs":
        return _run_logs_command(config, args.name, parser)

    parser.exit(status=3, message=f"Unknown command: {args.command}\n")
    return 3


def _run_list_command(config: AppConfig) -> int:
    runtime_states = load_runtime_state()
    rows = []
    for tunnel in config.effective_tunnels:
        status, runtime_state = _resolve_tunnel_status(config, tunnel, runtime_states)
        rows.append(_build_tunnel_summary_row(tunnel, status, runtime_state))

    _print_tunnel_summary_table(rows)
    return 0


def _run_upgrade_command() -> int:
    if os.environ.get(SELF_INSTALL_SKIP_ENV) != "1":
        install_status = _upgrade_global_command()
        if install_status != 0:
            return install_status

    runtime_root = ensure_runtime_dirs()
    config_path = default_config_path()

    if config_path.exists():
        print(f"Preserved existing config: {config_path}")
    else:
        config_path.write_text(packaged_template_config_text(), encoding="utf-8")
        print(f"Seeded template config: {config_path}")

    print(f"Runtime root: {runtime_root}")
    print(f"Edit config: {config_path}")
    return 0


def _run_uninstall_command() -> int:
    try:
        subprocess.run(
            ["uv", "tool", "uninstall", PACKAGED_TOOL_NAME],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print(
            f"Uninstall error: 'uv' is required in PATH to uninstall {PACKAGED_TOOL_NAME}.",
            file=sys.stderr,
        )
        return 4
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        print(
            f"Uninstall error: uv tool uninstall {PACKAGED_TOOL_NAME} failed: {detail}",
            file=sys.stderr,
        )
        return 5

    print(f"Removed packaged CLI: {PACKAGED_TOOL_NAME}")
    print("Preserved user data under ~/.local/share/ssm-tunnels/.")
    return 0


def _run_login_command(config: AppConfig, parser: argparse.ArgumentParser) -> int:
    profile = _resolve_login_profile(config, parser)
    _ensure_dependencies(config.defaults.backend, parser, required={"aws"})

    try:
        result = subprocess.run(
            ["aws", "sso", "login", "--profile", profile],
            check=False,
        )
    except FileNotFoundError:
        parser.exit(status=4, message="Dependency error: missing aws\n")
        raise AssertionError("unreachable")

    return result.returncode


def _resolve_login_profile(config: AppConfig, parser: argparse.ArgumentParser) -> str:
    profile = config.defaults.aws.profile
    if profile:
        return profile

    parser.exit(
        status=2, message="Command 'login' requires defaults.aws.profile in config.\n"
    )
    raise AssertionError("unreachable")


def _package_spec() -> str:
    return os.environ.get(PACKAGE_SPEC_ENV, DEFAULT_PACKAGE_SPEC)


def _upgrade_global_command() -> int:
    env = dict(os.environ)
    env[SELF_INSTALL_SKIP_ENV] = "1"
    package_spec = _package_spec()

    try:
        subprocess.run(
            ["uv", "tool", "install", "--reinstall", package_spec],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        print(
            "Upgrade error: 'uv' is required in PATH to upgrade ssm-tunnel-manager.",
            file=sys.stderr,
        )
        return 4
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        print(
            f"Upgrade error: uv tool install --reinstall {package_spec} failed: {detail}",
            file=sys.stderr,
        )
        return 5

    print(f"Upgraded packaged CLI from: {package_spec}")
    return 0


def _run_start_command(
    config: AppConfig, tunnels: list[EffectiveTunnel], parser: argparse.ArgumentParser
) -> int:
    for tunnel in tunnels:
        _run_start_tunnel(config, tunnel, parser)
    return 0


def _run_start_tunnel(
    config: AppConfig, tunnel: EffectiveTunnel, parser: argparse.ArgumentParser
) -> int:
    if not tunnel.enabled:
        parser.exit(
            status=2, message=f"Tunnel '{tunnel.name}' is disabled in config.\n"
        )

    _ensure_dependencies(
        config.defaults.backend,
        parser,
        required={"aws", "session-manager-plugin", "tmux"},
    )

    runtime_states = load_runtime_state()
    status, _ = _resolve_tunnel_status(config, tunnel, runtime_states)
    if status is RuntimeStatus.RUNNING:
        print(f"Tunnel '{tunnel.name}' is already running.")
        return 0

    backend = get_backend(config.defaults.backend)
    log_path = ensure_tunnel_log(tunnel.name)
    append_tunnel_log(tunnel.name, f"[{_timestamp()}] starting tunnel '{tunnel.name}'")
    command = build_start_session_command(tunnel)

    try:
        result = backend.start(tunnel, command, log_path)
    except BackendError as exc:
        _record_failure(tunnel.name, config.defaults.backend, log_path, str(exc))
        parser.exit(
            status=5, message=f"Start failed for tunnel '{tunnel.name}': {exc}\n"
        )

    runtime_state = TunnelRuntimeState(
        name=tunnel.name,
        status=RuntimeStatus.RUNNING,
        desired_state=DesiredTunnelState.RUNNING,
        backend=config.defaults.backend,
        pid=result.pid,
        started_at=_timestamp(),
        last_health_check_at=_timestamp(),
        log_path=str(log_path),
        backend_session=result.backend_session,
    )
    update_tunnel_state(runtime_state)
    append_tunnel_log(tunnel.name, f"[{_timestamp()}] started tunnel '{tunnel.name}'")
    print(
        f"Started tunnel '{tunnel.name}' using {config.defaults.backend}. "
        f"Log: {log_path}"
    )
    return 0


def _run_stop_command(
    config: AppConfig, tunnels: list[EffectiveTunnel], parser: argparse.ArgumentParser
) -> int:
    for tunnel in tunnels:
        _run_stop_tunnel(config, tunnel, parser)
    return 0


def _run_stop_tunnel(
    config: AppConfig,
    tunnel: EffectiveTunnel,
    parser: argparse.ArgumentParser,
    *,
    set_desired_stopped: bool = True,
) -> int:
    runtime_states = load_runtime_state()
    runtime_state = runtime_states.get(tunnel.name)
    status, runtime_state = _resolve_tunnel_status(config, tunnel, runtime_states)
    if runtime_state is None or status is RuntimeStatus.STOPPED:
        if set_desired_stopped:
            update_tunnel_state(
                TunnelRuntimeState(
                    name=tunnel.name,
                    status=RuntimeStatus.STOPPED,
                    desired_state=DesiredTunnelState.STOPPED,
                    backend=(
                        runtime_state.backend
                        if runtime_state is not None
                        else config.defaults.backend
                    ),
                    log_path=(
                        runtime_state.log_path if runtime_state is not None else None
                    ),
                    last_health_check_at=_timestamp(),
                )
            )
        print(f"Tunnel '{tunnel.name}' is not running.")
        return 0

    _ensure_dependencies(runtime_state.backend, parser, required={"tmux"})

    log_path = ensure_tunnel_log(tunnel.name)
    backend = get_backend(runtime_state.backend)

    try:
        backend.stop(runtime_state)
    except BackendError as exc:
        _record_failure(tunnel.name, runtime_state.backend, log_path, str(exc))
        parser.exit(
            status=5, message=f"Stop failed for tunnel '{tunnel.name}': {exc}\n"
        )

    stopped_state = replace(
        runtime_state,
        status=RuntimeStatus.STOPPED,
        desired_state=(
            DesiredTunnelState.STOPPED
            if set_desired_stopped
            else runtime_state.desired_state
        ),
        pid=None,
        backend_session=None,
        last_health_check_at=_timestamp(),
        error_summary=None,
        last_exit_code=0,
        log_path=str(log_path),
    )
    update_tunnel_state(stopped_state)
    append_tunnel_log(tunnel.name, f"[{_timestamp()}] stopped tunnel '{tunnel.name}'")
    print(f"Stopped tunnel '{tunnel.name}'.")
    return 0


def _run_restart_command(
    config: AppConfig, tunnels: list[EffectiveTunnel], parser: argparse.ArgumentParser
) -> int:
    for tunnel in tunnels:
        _run_restart_tunnel(config, tunnel, parser)
    return 0


def _run_restart_tunnel(
    config: AppConfig, tunnel: EffectiveTunnel, parser: argparse.ArgumentParser
) -> int:
    runtime_states = load_runtime_state()
    status, runtime_state = _resolve_tunnel_status(config, tunnel, runtime_states)
    if not _should_restart_tunnel(runtime_state):
        print(f"Skipped tunnel '{tunnel.name}' ({status.value}; unchanged).")
        return 0

    if status in {RuntimeStatus.RUNNING, RuntimeStatus.DEGRADED}:
        _run_stop_tunnel(config, tunnel, parser, set_desired_stopped=False)
    _run_start_tunnel(config, tunnel, parser)
    print(f"Restarted tunnel '{tunnel.name}'.")
    return 0


def _run_status_command(
    config: AppConfig,
    tunnel_name: str | None,
    parser: argparse.ArgumentParser,
    *,
    running: bool,
    stopped: bool,
    enabled: bool,
    disabled: bool,
) -> int:
    runtime_filters, enabled_filters = _build_status_filters(
        running=running,
        stopped=stopped,
        enabled=enabled,
        disabled=disabled,
    )

    if tunnel_name is None:
        return _run_global_status_command(config, runtime_filters, enabled_filters)

    if runtime_filters or enabled_filters:
        parser.exit(
            status=2,
            message="Command 'status' does not allow filter flags with a tunnel name.\n",
        )

    tunnel = _require_tunnel(config, tunnel_name, parser)
    runtime_states = load_runtime_state()
    status, runtime_state = _resolve_tunnel_status(config, tunnel, runtime_states)
    log_summary = summarize_tunnel_log(tunnel.name) or "-"

    print(f"Name: {tunnel.name}")
    print(f"Enabled: {'yes' if tunnel.enabled else 'no'}")
    print(f"Status: {status.value}")
    print(
        f"Backend: {(runtime_state.backend if runtime_state else config.defaults.backend)}"
    )
    print(f"Local: localhost:{tunnel.local_port}")
    print(f"Remote: {tunnel.remote_host}:{tunnel.remote_port}")
    print(f"Log: {ensure_tunnel_log(tunnel.name)}")
    print(f"PID: {runtime_state.pid if runtime_state and runtime_state.pid else '-'}")
    print(
        "Session: "
        f"{runtime_state.backend_session if runtime_state and runtime_state.backend_session else '-'}"
    )
    print(f"Last Error: {_status_summary(runtime_state)}")
    print(f"Recent Log: {log_summary}")
    return 0


def _run_global_status_command(
    config: AppConfig,
    runtime_filters: set[RuntimeStatus],
    enabled_filters: set[bool],
) -> int:
    if not config.effective_tunnels:
        print("No configured tunnels.")
        return 0

    runtime_states = load_runtime_state()
    rows = []
    for tunnel in config.effective_tunnels:
        status, runtime_state = _resolve_tunnel_status(config, tunnel, runtime_states)
        if not _matches_status_filters(
            tunnel,
            status,
            runtime_filters=runtime_filters,
            enabled_filters=enabled_filters,
        ):
            continue
        rows.append(_build_tunnel_summary_row(tunnel, status, runtime_state))

    _print_tunnel_summary_table(rows)
    return 0


def _run_logs_command(
    config: AppConfig, tunnel_name: str, parser: argparse.ArgumentParser
) -> int:
    tunnel = _require_tunnel(config, tunnel_name, parser)
    lines = read_tunnel_log(tunnel.name)
    if not lines:
        print(f"No log output for tunnel '{tunnel.name}' yet.")
        return 0

    print(f"Logs for tunnel '{tunnel.name}':")
    for line in lines:
        print(line)
    return 0


def _require_tunnel(
    config: AppConfig, tunnel_name: str, parser: argparse.ArgumentParser
) -> EffectiveTunnel:
    try:
        return config.get_tunnel(tunnel_name)
    except KeyError:
        parser.exit(status=2, message=f"Unknown tunnel: {tunnel_name}\n")
        raise AssertionError("unreachable")


def _resolve_target_tunnels(
    config: AppConfig,
    *,
    command: str,
    names: list[str],
    select_all: bool,
    parser: argparse.ArgumentParser,
    require_enabled: bool = False,
) -> list[EffectiveTunnel]:
    if select_all and names:
        parser.exit(
            status=2,
            message=f"Command '{command}' does not allow tunnel names with --all.\n",
        )

    if select_all:
        selected = list(config.effective_tunnels)
    elif names:
        selected_names: set[str] = set()
        for name in names:
            _require_tunnel(config, name, parser)
            selected_names.add(name)
        selected = [
            tunnel
            for tunnel in config.effective_tunnels
            if tunnel.name in selected_names
        ]
    else:
        parser.exit(
            status=2,
            message=f"Command '{command}' requires at least one tunnel name or --all.\n",
        )
        raise AssertionError("unreachable")

    if require_enabled:
        disabled_tunnel = next(
            (tunnel for tunnel in selected if not tunnel.enabled), None
        )
        if disabled_tunnel is not None:
            parser.exit(
                status=2,
                message=f"Tunnel '{disabled_tunnel.name}' is disabled in config.\n",
            )

    return selected


def _resolve_tunnel_status(
    config: AppConfig,
    tunnel: EffectiveTunnel,
    runtime_states: dict[str, TunnelRuntimeState],
) -> tuple[RuntimeStatus, TunnelRuntimeState | None]:
    runtime_state = runtime_states.get(tunnel.name)
    if runtime_state is None:
        return RuntimeStatus.STOPPED, None

    inspection = None
    try:
        inspection = get_backend(runtime_state.backend).inspect(runtime_state)
    except BackendError as exc:
        runtime_state = replace(runtime_state, error_summary=str(exc))

    status = evaluate_tunnel_health(tunnel, runtime_state, inspection)
    refreshed_state = replace(
        runtime_state,
        status=status,
        last_health_check_at=_timestamp(),
        pid=(
            inspection.pid
            if inspection and inspection.pid is not None
            else runtime_state.pid
        ),
        backend_session=(
            inspection.backend_session
            if inspection and inspection.backend_session is not None
            else runtime_state.backend_session
        ),
    )
    update_tunnel_state(refreshed_state)
    runtime_states[tunnel.name] = refreshed_state
    return status, refreshed_state


def _ensure_dependencies(
    backend: str, parser: argparse.ArgumentParser, required: set[str]
) -> None:
    failed = [
        check
        for check in check_dependencies(backend)
        if check.name in required and not check.ok
    ]
    if not failed:
        return

    summary = ", ".join(check.name for check in failed)
    parser.exit(status=4, message=f"Dependency error: missing {summary}\n")


def _record_failure(name: str, backend: str, log_path, error_summary: str) -> None:
    append_tunnel_log(name, f"[{_timestamp()}] error: {error_summary}")
    existing_state = load_runtime_state().get(name)
    update_tunnel_state(
        TunnelRuntimeState(
            name=name,
            status=RuntimeStatus.FAILED,
            desired_state=(
                existing_state.desired_state
                if existing_state is not None
                else DesiredTunnelState.RUNNING
            ),
            backend=backend,
            last_health_check_at=_timestamp(),
            log_path=str(log_path),
            error_summary=error_summary,
        )
    )


def _status_summary(runtime_state: TunnelRuntimeState | None) -> str:
    if runtime_state is None:
        return "-"
    if runtime_state.error_summary:
        return runtime_state.error_summary
    return summarize_tunnel_log(runtime_state.name) or "-"


def _build_tunnel_summary_row(
    tunnel: EffectiveTunnel,
    status: RuntimeStatus,
    runtime_state: TunnelRuntimeState | None,
) -> tuple[str, str, str, str, str]:
    enabled = "enabled" if tunnel.enabled else "disabled"
    summary = _status_summary(runtime_state)
    return (tunnel.name, status.value, enabled, str(tunnel.local_port), summary)


def _should_restart_tunnel(runtime_state: TunnelRuntimeState | None) -> bool:
    return (
        runtime_state is not None
        and runtime_state.desired_state is DesiredTunnelState.RUNNING
    )


def _build_status_filters(
    *, running: bool, stopped: bool, enabled: bool, disabled: bool
) -> tuple[set[RuntimeStatus], set[bool]]:
    runtime_filters: set[RuntimeStatus] = set()
    enabled_filters: set[bool] = set()

    if running:
        runtime_filters.add(RuntimeStatus.RUNNING)
    if stopped:
        runtime_filters.add(RuntimeStatus.STOPPED)
    if enabled:
        enabled_filters.add(True)
    if disabled:
        enabled_filters.add(False)

    return runtime_filters, enabled_filters


def _matches_status_filters(
    tunnel: EffectiveTunnel,
    status: RuntimeStatus,
    *,
    runtime_filters: set[RuntimeStatus],
    enabled_filters: set[bool],
) -> bool:
    if runtime_filters and status not in runtime_filters:
        return False
    if enabled_filters and tunnel.enabled not in enabled_filters:
        return False
    return True


def _print_tunnel_summary_table(rows: list[tuple[str, str, str, str, str]]) -> None:
    if not rows:
        return

    headers = ("name", "status", "enabled", "local port", "summary")
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    formatted_rows = [headers, *rows]
    for row in formatted_rows:
        print("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)))


def _normalize_argv(argv: list[str] | None) -> list[str]:
    normalized = list(argv or [])
    if not normalized:
        return ["status"]
    if "--version" in normalized:
        return normalized

    index = 0
    while index < len(normalized):
        token = normalized[index]
        if token == "--config":
            index += 2
            continue
        if token.startswith("--config="):
            index += 1
            continue
        if not token.startswith("-"):
            return normalized
        index += 1

    return [*normalized, "status"]


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
