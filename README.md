# ssm-tunnel-manager

Archived MVP for managing AWS SSM port-forwarding tunnels from the terminal. It reads tunnel definitions from a user-managed config file, starts `aws ssm start-session` in detached `tmux` sessions, and keeps simple runtime state and logs on disk.

## Requirements

- Python 3.11+
- `tmux`
- AWS CLI (`aws`)
- `session-manager-plugin`
- `fzf` for the interactive `tui` command

The CLI checks these binaries at runtime. `login` requires `aws`. `start` requires `aws`, `session-manager-plugin`, and `tmux`. `stop` only requires `tmux`. `tui` requires `fzf` and reports a clear runtime error if it is unavailable in `PATH`.

## Setup

Use `uv` as the supported local workflow. From a clean checkout:

```bash
uv sync
```

That creates or updates the local `.venv` and installs the project in editable mode, including the `ssm-tunnel` command inside that project environment.

If you want the test and build tools as well:

```bash
uv sync --extra test
```

The documented workflow does not require activating the virtualenv manually. Run project commands through `uv run ...`.

## Global Install

If you want `ssm-tunnel` available outside a source checkout, install the packaged CLI separately:

```bash
uv tool install ssm-tunnel-manager
```

For an upgrade from the package index, use `uv tool install --reinstall ssm-tunnel-manager`.

This package-install step makes the `ssm-tunnel` command available.

For a remote bootstrap flow, publish `scripts/install.sh` somewhere stable and run it as:

```bash
curl -fsSL <installer-url> | sh
```

That script stays intentionally thin: it installs the published package from the configured Python package index with `uv tool install` or `uv tool install --reinstall`, then delegates runtime/config bootstrap to `ssm-tunnel install` with the self-install guard enabled. If you need to pin or override the package source, set `SSM_TUNNEL_PACKAGE_SPEC` before invoking the script.

## Configuration

By default the CLI reads `~/.local/share/ssm-tunnels/config/tunnels.yaml`. You can override that with `--config /path/to/tunnels.yaml`.

From a repo checkout, `uv run ssm-tunnel install` now detects that checkout context and runs the reinstall step for you before it bootstraps runtime/config state. When you are already running from the globally installed command, `install` skips the reinstall step and stays a bootstrap check.

Seed or re-check the user-managed config path with:

```bash
uv run ssm-tunnel install
```

`install` creates the runtime directories under `~/.local/share/ssm-tunnels/` and writes the packaged generic template config only if it does not already exist. Re-running `install` is safe: it preserves any existing user config instead of overwriting it.

Expected shape:

```yaml
version: 1

defaults:
  aws:
    region: us-east-1
    target: i-xxxxxxxxxxxxxxxxx
    profile: your-aws-profile
    document: AWS-StartPortForwardingSessionToRemoteHost
  ui:
    backend: tmux

tunnels:
  - name: mysql
    remote_host: db.internal
    remote_port: 3306
    local_port: 13306
    tags: [mysql, prod]
```

Notes:

- Required AWS settings after defaults and per-tunnel overrides are merged: `region`, `target`, `profile`, `document`
- Enabled tunnels must use unique `local_port` values
- `enabled: false` keeps a tunnel in the config but prevents `start`
- Per-tunnel `aws` values override `defaults.aws`

## Commands

Show command usage explicitly:

```bash
uv run ssm-tunnel help
```

Show the default status summary for all configured tunnels:

```bash
uv run ssm-tunnel
```

Bootstrap the user-managed config path if you have not done so yet:

```bash
uv run ssm-tunnel install
```

Refresh AWS SSO credentials for the configured default profile:

```bash
uv run ssm-tunnel login
```

List configured tunnels:

```bash
uv run ssm-tunnel list
```

Start one or more named tunnels:

```bash
uv run ssm-tunnel start mysql
uv run ssm-tunnel start mysql redis
```

Start every configured tunnel explicitly:

```bash
uv run ssm-tunnel start --all
```

Stop one or more named tunnels:

```bash
uv run ssm-tunnel stop mysql
uv run ssm-tunnel stop mysql redis
```

Stop every configured tunnel explicitly:

```bash
uv run ssm-tunnel stop --all
```

Restart one or more named tunnels:

```bash
uv run ssm-tunnel restart mysql
uv run ssm-tunnel restart mysql redis
```

Restart every configured tunnel explicitly:

```bash
uv run ssm-tunnel restart --all
```

Show status for all configured tunnels:

```bash
uv run ssm-tunnel status
```

Filter the global status summary:

```bash
uv run ssm-tunnel status --running
uv run ssm-tunnel status --stopped --enabled
uv run ssm-tunnel status --disabled
```

Show status for one tunnel:

```bash
uv run ssm-tunnel status mysql
```

Show logs:

```bash
uv run ssm-tunnel logs mysql
```

Launch the guided terminal picker:

```bash
uv run ssm-tunnel tui
```

Notes:

- Bare `ssm-tunnel` defaults to the same global summary as `ssm-tunnel status`
- `status` with no name prints a summary for every configured tunnel
- The summary view is an aligned five-column table with `name`, `status`, `enabled`, `local port`, and `summary`
- `status <name>` prints the detailed single-tunnel view
- `status` also supports `--running`, `--stopped`, `--enabled`, and `--disabled` for the global summary view
- `status <name>` rejects filter flags so the single-tunnel detail contract stays unambiguous
- `login` runs `aws sso login --profile <defaults.aws.profile>` in the foreground, so the normal AWS CLI browser or device-code flow stays interactive in your terminal
- `uv run ssm-tunnel install` from a repo checkout reinstalls the CLI globally with `uv tool install --reinstall /path/to/ssm-tunnel-manager` before bootstrapping runtime/config state
- When already running from the globally installed command, `install` skips the reinstall step and just re-checks runtime/config state
- `install` seeds only the packaged generic template; it never copies the repo's real config into your user-managed path
- `scripts/install.sh` is the `curl ... | sh` entry point and defaults to installing the published package from the configured Python package index as `ssm-tunnel-manager`
- `scripts/install.sh` uses `uv tool install` for first install, `uv tool install --reinstall` for upgrades, and then runs `ssm-tunnel install` with `SSM_TUNNEL_SKIP_SELF_INSTALL=1`
- `start`, `stop`, and `restart` accept multiple tunnel names in one command
- `--all` is supported for `start`, `stop`, and `restart`
- `restart` only restarts selected tunnels that are currently `running` or `degraded`; stopped tunnels are reported as skipped and left unchanged
- `logs` remains single-tunnel only
- `help` prints the command usage without loading tunnel config first
- `tui` keeps the interactive flow action first, then prompts for action-specific tunnel selection
- `tui` is powered by `fzf`, so action and tunnel selection use normal `fzf` behavior: arrow keys move through the list, typing filters matches, and `Enter` confirms the current selection
- In `tui`, `login` is an action-only flow that dispatches the same shared `ssm-tunnel login` path without any tunnel prompt, `status` offers `all` or one tunnel, `stop` also exposes an explicit `all` choice alongside multi-select tunnel picking, `logs` remains single-tunnel only, `help` and `quit` are action-only flows, and lifecycle actions use `Tab` to mark multiple tunnels before confirming with `Enter`

Using a non-default config file:

```bash
uv run ssm-tunnel --config ./config/tunnels.yaml list
```

Run the test suite:

```bash
uv run pytest
```

Build distributable artifacts:

```bash
uv run python -m build
```

## Runtime Files

The MVP stores runtime data under `~/.local/share/ssm-tunnels/`:

- `config/tunnels.yaml`: user-managed tunnel definitions seeded by `install` from a packaged generic template
- `logs/<tunnel>.log`: tunnel log output and lifecycle messages
- `run/state.json`: persisted runtime state for all tunnels

The `status` command also reports the current log path, PID, and tracked backend session name.

## tmux Backend Note

The only implemented backend is `tmux`. Starting a tunnel creates a detached session named `ssm-tunnel-<name>` and runs:

```bash
aws ssm start-session ...
```

with stdout/stderr appended to the tunnel log file.

Current MVP behavior to be aware of:

- Tunnel health is inferred from the stored PID, the tracked `tmux` session, and whether the local port is listening
- `restart` performs `stop` first, then `start`, but only for selected tunnels that are already `running` or `degraded`
- If `stop` succeeds but `start` fails, the tunnel remains stopped
- `stop` depends on the saved `tmux` session reference; if that reference is missing, stop fails even if a matching process still exists

## Archived MVP Notes

- This project is intentionally small and terminal-first; the guided `tui` flow shells out to `fzf` instead of carrying a heavier in-process UI framework
