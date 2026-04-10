# SSM Tunnel Manager - Technical Specification

## 1. Purpose

This document specifies a lightweight terminal-based tool for managing multiple AWS SSM port-forwarding tunnels from a single control surface.

The main goal is to replace the current workflow of manually opening multiple `tmux` sessions and running one shell script per tunnel with a simpler and more centralized operator experience.

The tool should allow users to:

- Start a tunnel from a predefined configuration
- Stop a running tunnel
- Restart a tunnel
- View current tunnel status
- Inspect logs or recent errors
- Manage tunnel definitions from a configuration file
- Override AWS session parameters when their environment differs from the default setup

This specification is intentionally focused on a small and maintainable MVP.

---

## 2. Problem Statement

The current implementation is a Bash script with hardcoded AWS session parameters and hardcoded tunnel definitions.

Example of the current static AWS parameters:

- `REGION="us-east-1"`
- `TARGET="i-0f275e6df0854958e"`
- `PROFILE="BackEnd-692642197054"`
- `DOC="AWS-StartPortForwardingSessionToRemoteHost"`

Example of the current static host mapping:

- tunnel name
- remote host
- remote port
- local port

This approach works, but it creates several operational issues:

1. Users must manually open separate terminal sessions or `tmux` panes for each tunnel.
2. Tunnel configuration is hardcoded in the script.
3. Adding or removing tunnels requires editing code.
4. There is no centralized state view for running tunnels.
5. There is no simple way to support users with different AWS profiles, targets, regions, or documents.

---

## 3. Design Goals

### 3.1 Primary Goals

- Keep the solution simple
- Make the tool fully terminal-friendly
- Support multiple concurrent tunnels
- Centralize tunnel lifecycle management
- Move configuration out of code and into a YAML file
- Allow users to customize AWS parameters without changing the source code
- Make future UI and CRUD extensions possible without reworking the core design

### 3.2 Non-Goals for MVP

The first version should **not** include:

- Full in-app CRUD/ABM for tunnel definitions
- Complex auto-reconnect logic
- Multi-user coordination
- Cloud sync of configuration
- Secret management beyond the existing AWS CLI/profile mechanism
- Dynamic discovery of hosts from AWS
- Desktop GUI

---

## 4. High-Level Architecture

The solution should be split into two layers:

### 4.1 Tunnel Management Layer

Responsible for:

- Reading the YAML configuration
- Starting tunnel processes
- Stopping tunnel processes
- Restarting tunnel processes
- Persisting process metadata and runtime state
- Validating health
- Exposing tunnel status to the UI

### 4.2 Terminal UI Layer

Responsible for:

- Displaying configured tunnels
- Displaying running/stopped status
- Showing local and remote port mappings
- Showing recent logs or errors
- Triggering start/stop/restart actions

This separation is important because the lifecycle and reliability of the tunnel processes matter more than the visual layer.

---

## 5. Recommended MVP Strategy

### 5.1 Recommended Implementation Order

#### Phase 1 - Core CLI + Config + Process Management

Implement a command-line backend that:

- loads configuration from YAML
- starts and stops tunnels
- stores PID/log/state files
- reports current status

#### Phase 2 - Interactive Terminal Launcher

Add a terminal-driven interface using an in-process selector such as `prompt_toolkit` for quick selection and actions.

#### Phase 3 - Persistent TUI Dashboard

Optionally add a richer TUI using Textual (Python) or Bubble Tea (Go).

### 5.2 Recommended Technology for MVP

Preferred MVP stack:

- Config: YAML
- Core process management: shell or Python
- Interactive UI: `prompt_toolkit`
- Optional backend runtime: `tmux`

### 5.3 Why This Is Recommended

This approach keeps the system small and practical.

Using `tmux` as the process runtime is acceptable for MVP because:

- the current workflow already depends on terminal multiplexing
- `aws ssm start-session` is not always ideal to daemonize like a normal background service
- `tmux` makes inspection and debugging easier
- the implementation cost is lower than introducing a full service supervisor

---

## 6. Configuration Model

The tool must move all environment-specific and tunnel-specific data into a YAML file.

### 6.1 Configuration Requirements

The configuration must support:

1. Global defaults for AWS session parameters
2. A list of named tunnel definitions
3. Optional per-tunnel overrides for AWS settings
4. Easy manual editing for users

### 6.2 Proposed YAML Structure

```yaml
version: 1

defaults:
  aws:
    region: us-east-1
    target: i-0f275e6df0854958e
    profile: BackEnd-692642197054
    document: AWS-StartPortForwardingSessionToRemoteHost
    log_dir: ~/.local/share/ssm-tunnels/logs
    runtime_dir: ~/.local/share/ssm-tunnels/run

  ui:
    refresh_interval_seconds: 2
    backend: tmux

tunnels:
  - name: mysql
    remote_host: prd-mysql-aurora-adcap.cluster-cwkafroskh9b.us-east-1.rds.amazonaws.com
    remote_port: 3306
    local_port: 13306
    tags: [mysql, prod]

  - name: mssql
    remote_host: basebolsa.prd.adcap.internal
    remote_port: 1433
    local_port: 13305
    tags: [mssql, prod]

  - name: postgresql
    remote_host: postgres.prd.adcap.internal
    remote_port: 5432
    local_port: 13307
    tags: [postgres, prod]

  - name: escoapi
    remote_host: escoapi.prd.adcap.internal
    remote_port: 6003
    local_port: 13308
    tags: [internal-api, prod]

  - name: docdb
    remote_host: adcap-docdb-prd.cluster-cwkafroskh9b.us-east-1.docdb.amazonaws.com
    remote_port: 27017
    local_port: 13309
    tags: [docdb, prod]

  - name: apibroker
    remote_host: apibroker-rds-prd-cluster.cluster-cwkafroskh9b.us-east-1.rds.amazonaws.com
    remote_port: 3306
    local_port: 13310
    tags: [mysql, prod]
```

---

## 7. Support for User-Specific AWS Parameters

This is a core requirement.

Different users may need different values for:

- `region`
- `target`
- `profile`
- `document`

Therefore, the system must not hardcode these values in the source code.

### 7.1 Rules

- Global AWS parameters should live under `defaults.aws`
- Each tunnel may optionally override any AWS parameter
- If a tunnel does not define an override, it inherits the global default

### 7.2 Example with Per-Tunnel Override

```yaml
version: 1

defaults:
  aws:
    region: us-east-1
    target: i-0f275e6df0854958e
    profile: BackEnd-692642197054
    document: AWS-StartPortForwardingSessionToRemoteHost

tunnels:
  - name: mysql
    remote_host: prd-mysql-aurora-adcap.cluster-cwkafroskh9b.us-east-1.rds.amazonaws.com
    remote_port: 3306
    local_port: 13306

  - name: mysql-alt-profile
    remote_host: prd-mysql-aurora-adcap.cluster-cwkafroskh9b.us-east-1.rds.amazonaws.com
    remote_port: 3306
    local_port: 23306
    aws:
      profile: AnotherProfile
      target: i-0123456789abcdef0
```

### 7.3 Effective Resolution Logic

For each tunnel, the effective configuration should be resolved as:

1. Start from `defaults.aws`
2. Apply the tunnel-level `aws` overrides if present
3. Use the resulting merged values to build the AWS SSM command

---

## 8. Tunnel Definition Model

Each tunnel entry must minimally contain:

- `name`
- `remote_host`
- `remote_port`
- `local_port`

Optional fields may include:

- `aws` overrides
- `tags`
- `description`
- `enabled`

### 8.1 Proposed Schema

```yaml
- name: string
  remote_host: string
  remote_port: integer
  local_port: integer
  enabled: boolean
  description: string
  tags: [string]
  aws:
    region: string
    target: string
    profile: string
    document: string
```

### 8.2 Validation Rules

The loader should validate:

- `name` is unique
- `remote_host` is present
- `remote_port` is a valid TCP port
- `local_port` is a valid TCP port
- no two enabled tunnels share the same `local_port`
- required global AWS values exist after merge

---

## 9. Command Construction

The effective AWS command should be built dynamically from configuration.

### 9.1 Canonical Command Shape

```bash
aws ssm start-session \
  --region "$REGION" \
  --target "$TARGET" \
  --document-name "$DOC" \
  --parameters "host=$REMOTE_HOST,portNumber=$REMOTE_PORT,localPortNumber=$LOCAL_PORT" \
  --profile "$PROFILE"
```

### 9.2 Command Inputs

The tool should derive:

- `REGION` from effective AWS config
- `TARGET` from effective AWS config
- `PROFILE` from effective AWS config
- `DOC` from effective AWS config
- `REMOTE_HOST` from tunnel config
- `REMOTE_PORT` from tunnel config
- `LOCAL_PORT` from tunnel config

### 9.3 Behavior

The command must be generated at runtime rather than hardcoded per tunnel.

This makes host creation and removal a configuration concern instead of a code concern.

---

## 10. Runtime State Model

The tool should persist runtime state locally.

### 10.1 Runtime Data to Track

For each tunnel, the system should track:

- tunnel name
- current status
- PID or backend process identifier
- start time
- last health check time
- last known exit code
- log file path
- backend session reference if using `tmux`

### 10.2 Suggested Runtime Layout

```text
~/.local/share/ssm-tunnels/
  config/
    tunnels.yaml
  logs/
    mysql.log
    mssql.log
  run/
    mysql.pid
    mssql.pid
    state.json
```

### 10.3 Suggested Status Values

- `running`
- `stopped`
- `failed`
- `degraded`
- `unknown`

### 10.4 Status Semantics

- `running`: process exists and local port appears active
- `stopped`: tunnel is not active
- `failed`: start attempt failed
- `degraded`: process exists but local port is not listening or health is inconsistent
- `unknown`: runtime state cannot be verified

---

## 11. Health Check Strategy

The tool should not trust only a PID file.

### 11.1 Recommended Checks

A tunnel should be considered healthy only if the following checks pass:

1. The tracked process still exists
2. The process command matches the expected tunnel runtime
3. The local port is listening

### 11.2 Example Checks

Possible validation methods:

- `kill -0 <pid>`
- inspect `/proc/<pid>/cmdline` or `ps`
- inspect `ss -ltnp` output for the local port

### 11.3 Why This Matters

PID files alone are not reliable enough for long-running process management.

---

## 12. Logging and Error Visibility

The tool must expose useful failures to the user.

### 12.1 Typical Failure Modes

Expected operational failures include:

- AWS credentials expired
- profile missing or invalid
- Session Manager Plugin missing
- target instance unreachable
- remote host resolution failure
- local port already in use
- tunnel process exited unexpectedly

### 12.2 Requirements

The system should:

- capture stdout/stderr to per-tunnel log files
- preserve recent failure information
- show last known error in list view when possible
- allow log inspection per tunnel

### 12.3 MVP Error Display

An MVP display should at minimum expose:

- name
- status
- local port
- short error summary

Example:

```text
mysql      failed     13306    AWS credentials expired
mssql      running    13305    -
docdb      failed     13309    local port already in use
```

---

## 13. Process Runtime Options

There are two valid runtime models.

### 13.1 Option A - Direct Background Process Management

The manager starts `aws ssm start-session` directly as a child/background process and tracks it.

#### Pros

- cleaner architecture
- no dependency on `tmux`
- easier to move to a richer TUI later

#### Cons

- `aws ssm start-session` may not always behave like a normal daemonized process
- can be trickier to debug interactively

### 13.2 Option B - `tmux` as Runtime Backend

The manager creates one `tmux` session/window/pane per tunnel and runs the AWS command there.

#### Pros

- operationally robust for terminal-first users
- easy to inspect and debug
- close to the current workflow
- lower risk for MVP

#### Cons

- backend depends on `tmux`
- state model includes terminal session references

### 13.3 MVP Recommendation

Use `tmux` as the default backend for MVP if direct process management proves unreliable during implementation.

This should remain configurable through:

```yaml
defaults:
  ui:
    backend: tmux
```

Future values could include:

- `tmux`
- `process`

---

## 14. CLI Contract

Even if a richer TUI is introduced later, the project should expose a stable CLI.

### 14.1 Required Commands

```text
ssm-tunnel list
ssm-tunnel start <name>
ssm-tunnel stop <name>
ssm-tunnel restart <name>
ssm-tunnel status <name>
ssm-tunnel logs <name>
```

### 14.2 Optional Commands

```text
ssm-tunnel start-all
ssm-tunnel stop-all
ssm-tunnel reload-config
ssm-tunnel doctor
```

### 14.3 Expected Behavior

- `list`: show all configured tunnels with current status
- `start <name>`: start the selected tunnel if valid and not already running
- `stop <name>`: stop the selected tunnel if running
- `restart <name>`: stop and then start the selected tunnel
- `status <name>`: show expanded tunnel detail
- `logs <name>`: show or tail logs for the selected tunnel
- `doctor`: validate dependencies and config

---

## 15. TUI / Interactive UX

The terminal UI should be intentionally simple.

### 15.1 MVP Interaction Model

The first interactive layer may be built with `prompt_toolkit`.

Example actions:

- select a tunnel from a list
- press a key to start
- press a key to stop
- press a key to restart
- press a key to view logs

### 15.2 Future Persistent TUI

A richer TUI may later present:

- a table of configured tunnels
- color-coded status
- a detail pane
- a recent log pane
- keyboard shortcuts
- auto-refresh

### 15.3 Suggested Main Screen Layout

```text
SSM Tunnel Control

Name        Status    Local    Remote Host                          Remote Port   PID
mysql       UP        13306    prd-mysql-aurora...                  3306          12345
mssql       DOWN      13305    basebolsa.prd.adcap.internal         1433          -
postgres    UP        13307    postgres.prd.adcap.internal          5432          12387

[Enter] Details   [s] Start   [k] Stop   [r] Restart   [l] Logs   [q] Quit
```

---

## 16. Dependency Checks

The system should provide a lightweight health check command.

### 16.1 Required Dependencies

At minimum, the tool should validate the presence of:

- `aws`
- AWS Session Manager Plugin
- `tmux` if configured as backend
- in-process selector support if interactive mode is enabled

### 16.2 Configuration Checks

The tool should also validate:

- YAML syntax is correct
- tunnel names are unique
- local ports do not collide
- required effective AWS fields are present

### 16.3 Example Doctor Output

```text
[OK] aws CLI found
[OK] session-manager-plugin found
[OK] tmux found
[OK] config loaded
[OK] no duplicated tunnel names
[OK] no local port conflicts
```

---

## 17. Extensibility Plan

The design should explicitly support later enhancements without redesigning the core.

### 17.1 Planned Future Enhancements

Possible future work:

- in-app ABM/CRUD for tunnels
- form-based editing of YAML data
- persistent dashboard with richer TUI widgets
- filtering by tags
- multiple configuration profiles
- auto-reconnect policies
- notifications when a tunnel drops
- import/export of tunnel definitions

### 17.2 Important Constraint

For the first version, tunnel definitions should be edited directly in YAML.

This is the correct tradeoff for MVP because:

- it minimizes implementation complexity
- users can already manage entries manually
- it avoids building a half-baked configuration editor too early

---

## 18. Suggested Project Structure

### 18.1 Shell-Oriented Layout

```text
ssm-tunnel-manager/
  bin/
    ssm-tunnel
    ssm-tunnel-ui
  lib/
    config.sh
    state.sh
    runtime.sh
    health.sh
    tmux_backend.sh
  config/
    tunnels.yaml
  data/
    logs/
    run/
```

### 18.2 Python-Oriented Layout

```text
ssm_tunnel_manager/
  cli.py
  config.py
  models.py
  runtime.py
  health.py
  tui.py
config/
  tunnels.yaml
```

---

## 19. Implementation Recommendation

### 19.1 Short Recommendation

The recommended implementation path is:

1. externalize all configuration to YAML
2. implement a stable CLI backend
3. validate direct-process execution
4. fall back to `tmux` backend if process management is unreliable
5. add an in-process Python selector as the first interactive UI
6. only later build a richer persistent TUI if the tool proves useful in daily workflow

### 19.2 Why This Is the Best Tradeoff

This path optimizes for:

- simplicity
- maintainability
- fast delivery
- terminal-native operation
- low architectural risk

---

## 20. Acceptance Criteria for MVP

The MVP should be considered complete when all of the following are true:

1. A user can define global AWS defaults in YAML
2. A user can add or remove tunnels by editing YAML
3. A user can optionally override AWS parameters per tunnel
4. A user can start a tunnel by name
5. A user can stop a tunnel by name
6. A user can restart a tunnel by name
7. A user can list all configured tunnels with status
8. A user can inspect logs for a tunnel
9. The system detects common misconfiguration and dependency errors
10. The system works fully from the terminal without requiring manual `tmux` management by the user

---

## 21. Final Notes

This project is technically feasible and reasonably scoped if kept small.

The main risk is not the UI itself, but the reliability of process lifecycle management around `aws ssm start-session`.

Because of that, the implementation should prioritize:

- configuration design
- process/runtime management
- state tracking
- observability

The visual dashboard is a secondary concern and should be built only after the runtime model is stable.

For MVP, YAML-based configuration plus a terminal-first control flow is the right design direction.
