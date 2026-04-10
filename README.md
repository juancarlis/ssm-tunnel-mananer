# ssm-tunnel-manager

Archived MVP for managing AWS SSM port-forwarding tunnels from the terminal. It reads tunnel definitions from a user-managed config file, starts `aws ssm start-session` in detached `tmux` sessions, and keeps simple runtime state and logs on disk.

## Requirements

- Python 3.11+
- `tmux`
- AWS CLI (`aws`)
- `session-manager-plugin`
- Python runtime dependencies from this package, including `prompt_toolkit` for the interactive `tui` command

The CLI checks these binaries at runtime. `login` requires `aws`. `start` requires `aws`, `session-manager-plugin`, and `tmux`. `stop` only requires `tmux`. `tui` runs as an in-process selector, so it no longer depends on an external picker binary in `PATH`.

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

For an upgrade from the public GitHub repository, use `uv tool install --reinstall git+https://github.com/juancarlis/ssm-tunnel-mananer.git`.

To remove the supported packaged CLI again, run:

```bash
uv tool uninstall ssm-tunnel-manager
```

This package-install step makes the `ssm-tunnel` command available.

For a remote bootstrap flow, use the raw GitHub URL for `scripts/install.sh`:

```bash
curl -fsSL <installer-url> | sh
```

Concretely for this repository:

```bash
curl -fsSL https://raw.githubusercontent.com/juancarlis/ssm-tunnel-mananer/main/scripts/install.sh | sh
```

That script stays intentionally thin: it installs the package with `uv tool install` or `uv tool install --reinstall`, then delegates runtime/config bootstrap to `ssm-tunnel upgrade` with the self-install guard enabled.

Use this remote bootstrap flow:

```bash
export SSM_TUNNEL_PACKAGE_SPEC="git+https://github.com/juancarlis/ssm-tunnel-mananer.git"
curl -fsSL https://raw.githubusercontent.com/juancarlis/ssm-tunnel-mananer/main/scripts/install.sh | sh
```

Use the raw `raw.githubusercontent.com` script URL, not the GitHub page URL, and use the repository URL for `SSM_TUNNEL_PACKAGE_SPEC`.

## Configuration

By default the CLI reads `~/.local/share/ssm-tunnels/config/tunnels.yaml`. You can override that with `--config /path/to/tunnels.yaml`.

`uv run ssm-tunnel upgrade` updates the packaged CLI from the public GitHub repository, creates the runtime directories under `~/.local/share/ssm-tunnels/`, and writes the packaged generic template config only if it does not already exist.

Seed or re-check the user-managed config path with:

```bash
uv run ssm-tunnel upgrade
```

Re-running `upgrade` is safe: it preserves any existing user config instead of overwriting it. The self-install loop guard `SSM_TUNNEL_SKIP_SELF_INSTALL=1` still skips the `uv tool install --reinstall ...` step so installer bootstrap does not recurse forever.

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

Upgrade the packaged CLI and bootstrap the user-managed config path if you have not done so yet:

```bash
uv run ssm-tunnel upgrade
```

Remove the supported packaged CLI without deleting config, logs, or runtime state:

```bash
uv run ssm-tunnel uninstall
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
- `uv run ssm-tunnel upgrade` updates the packaged CLI with `uv tool install --reinstall git+https://github.com/juancarlis/ssm-tunnel-mananer.git` before bootstrapping runtime/config state
- When `SSM_TUNNEL_SKIP_SELF_INSTALL=1` is already set, `upgrade` skips the reinstall step and just re-checks runtime/config state
- `uninstall` runs `uv tool uninstall ssm-tunnel-manager` for the supported packaged install path and leaves `~/.local/share/ssm-tunnels/` untouched
- `upgrade` seeds only the packaged generic template; it never copies the repo's real config into your user-managed path
- `scripts/install.sh` is the `curl ... | sh` entry point and defaults to installing from `git+https://github.com/juancarlis/ssm-tunnel-mananer.git`
- `scripts/install.sh` uses `uv tool install` for first install, `uv tool install --reinstall` for upgrades, and then runs `ssm-tunnel upgrade` with `SSM_TUNNEL_SKIP_SELF_INSTALL=1`
- `start`, `stop`, and `restart` accept multiple tunnel names in one command
- `--all` is supported for `start`, `stop`, and `restart`
- `start` marks the selected tunnels as desired `running`; `stop` marks them as desired `stopped`
- `restart` only restarts selected tunnels whose desired state is `running`, including tunnels whose last known runtime status has fallen back to `stopped` after the SSM session died on its own
- Enabled tunnels that were never started are still skipped by `restart --all`
- `logs` remains single-tunnel only
- `help` prints the command usage without loading tunnel config first
- `tui` keeps the interactive flow action first, then prompts for action-specific tunnel selection
- `tui` is powered by `prompt_toolkit` as an in-process selector, so action and tunnel selection stay inside the Python process
- In `tui`, arrow keys move through the list, `j` / `k` also move, `Enter` confirms the current selection, and `Esc` cancels cleanly (`Ctrl-C` also cancels)
- In multi-select flows, `Space` toggles checkbox-style selections before `Enter` confirms; if nothing is checked yet, `Enter` still confirms the currently highlighted tunnel
- In `tui`, `upgrade`, `login`, and `uninstall` are action-only flows that dispatch the shared CLI paths without any tunnel prompt, `status` offers `all` or one tunnel, `start` / `stop` / `restart` expose an explicit `all` choice alongside multi-select tunnel picking, `logs` remains single-tunnel only, and `help` / `quit` are action-only flows

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

- `config/tunnels.yaml`: user-managed tunnel definitions seeded by `upgrade` from a packaged generic template
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
- `restart` performs `stop` first, then `start`, for tunnels whose persisted desired state is still `running`; if the tunnel already died and now resolves to `stopped`, restart goes straight to `start`
- If `stop` succeeds but `start` fails, the tunnel remains stopped
- `stop` depends on the saved `tmux` session reference; if that reference is missing, stop fails even if a matching process still exists

## Archived MVP Notes

- This project is intentionally small and terminal-first; the guided `tui` flow now uses a lightweight in-process `prompt_toolkit` selector instead of shelling out to an external picker
