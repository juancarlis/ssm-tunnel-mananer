from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = ROOT / "scripts" / "install.sh"


def make_executable(path: Path, content: str) -> Path:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)
    return path


def write_uv_stub(bin_dir: Path) -> None:
    make_executable(
        bin_dir / "uv",
        """
        #!/bin/sh
        set -eu
        printf 'uv %s\n' "$*" >>"$TEST_LOG"
        if [ "${CREATE_SSM_TUNNEL_AFTER_UV:-0}" = "1" ]; then
            mv "$TEST_BIN_DIR/ssm-tunnel-installed" "$TEST_BIN_DIR/ssm-tunnel"
        fi
        exit "${UV_EXIT_CODE:-0}"
        """,
    )


def write_ssm_tunnel_stub(bin_dir: Path, name: str = "ssm-tunnel") -> None:
    make_executable(
        bin_dir / name,
        """
        #!/bin/sh
        set -eu
        printf 'ssm-tunnel %s\n' "$*" >>"$TEST_LOG"
        printf 'skip=%s\n' "${SSM_TUNNEL_SKIP_SELF_INSTALL:-}" >>"$TEST_ENV_LOG"
        """,
    )


def run_installer(
    tmp_path: Path,
    extra_env: dict[str, str] | None = None,
    *,
    include_system_path: bool = True,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log_path = tmp_path / "commands.log"
    env_log_path = tmp_path / "env.log"
    path_suffix = os.environ["PATH"] if include_system_path else "/usr/bin:/bin"

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{path_suffix}",
            "TEST_BIN_DIR": str(bin_dir),
            "TEST_LOG": str(log_path),
            "TEST_ENV_LOG": str(env_log_path),
            "TMPDIR": str(tmp_path),
        }
    )
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        ["/bin/sh", str(INSTALLER_PATH)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_installer_uses_plain_uv_install_for_first_install(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_uv_stub(bin_dir)
    write_ssm_tunnel_stub(bin_dir, name="ssm-tunnel-installed")

    result = run_installer(
        tmp_path,
        {
            "CREATE_SSM_TUNNEL_AFTER_UV": "1",
            "SSM_TUNNEL_PACKAGE_SPEC": "ssm-tunnel-manager==0.1.0",
        },
        include_system_path=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert (tmp_path / "commands.log").read_text(encoding="utf-8").splitlines() == [
        "uv tool install ssm-tunnel-manager==0.1.0",
        "ssm-tunnel install",
    ]
    assert (tmp_path / "env.log").read_text(encoding="utf-8").splitlines() == ["skip=1"]
    assert list(tmp_path.glob("ssm-tunnel-install.*")) == []


def test_installer_uses_reinstall_when_command_already_exists(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_uv_stub(bin_dir)
    write_ssm_tunnel_stub(bin_dir)

    result = run_installer(tmp_path, include_system_path=False)

    assert result.returncode == 0
    assert result.stderr == ""
    assert (tmp_path / "commands.log").read_text(encoding="utf-8").splitlines() == [
        "uv tool install --reinstall ssm-tunnel-manager",
        "ssm-tunnel install",
    ]
    assert (tmp_path / "env.log").read_text(encoding="utf-8").splitlines() == ["skip=1"]


def test_installer_reports_missing_uv_clearly(tmp_path):
    result = run_installer(tmp_path, include_system_path=False)

    assert result.returncode != 0
    assert (
        result.stderr
        == "Install error: 'uv' is required in PATH to install ssm-tunnel-manager.\n"
    )


def test_installer_cleans_up_temp_file_after_failure(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_uv_stub(bin_dir)

    result = run_installer(tmp_path, {"UV_EXIT_CODE": "9"}, include_system_path=False)

    assert result.returncode != 0
    assert "Install error: uv tool install ssm-tunnel-manager failed." in result.stderr
    assert list(tmp_path.glob("ssm-tunnel-install.*")) == []
