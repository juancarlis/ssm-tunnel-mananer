from __future__ import annotations

import textwrap

import pytest

from ssm_tunnel_manager.config import ConfigError, load_config
from ssm_tunnel_manager.paths import default_config_path, packaged_template_config_text


def write_config(tmp_path, content: str):
    config_path = tmp_path / "tunnels.yaml"
    config_path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    return config_path


def test_loads_valid_config_with_effective_aws_overrides(tmp_path):
    config_path = write_config(
        tmp_path,
        """
        version: 1
        defaults:
          aws:
            region: us-east-1
            target: i-default
            profile: team-profile
            document: AWS-StartPortForwardingSessionToRemoteHost
        tunnels:
          - name: mysql
            remote_host: db.internal
            remote_port: 3306
            local_port: 13306
          - name: mysql-alt
            remote_host: db.internal
            remote_port: 3306
            local_port: 23306
            aws:
              profile: other-profile
              target: i-override
        """,
    )

    config = load_config(config_path)

    assert [tunnel.name for tunnel in config.effective_tunnels] == [
        "mysql",
        "mysql-alt",
    ]
    assert config.defaults.backend == "tmux"
    assert config.get_tunnel("mysql").aws.profile == "team-profile"
    assert config.get_tunnel("mysql-alt").aws.profile == "other-profile"
    assert config.get_tunnel("mysql-alt").aws.target == "i-override"
    assert config.get_tunnel("mysql-alt").aws.region == "us-east-1"


def test_rejects_duplicate_tunnel_names(tmp_path):
    config_path = write_config(
        tmp_path,
        """
        defaults:
          aws:
            region: us-east-1
            target: i-default
            profile: team-profile
            document: AWS-StartPortForwardingSessionToRemoteHost
        tunnels:
          - name: mysql
            remote_host: db-1.internal
            remote_port: 3306
            local_port: 13306
          - name: mysql
            remote_host: db-2.internal
            remote_port: 3306
            local_port: 23306
        """,
    )

    with pytest.raises(ConfigError, match="Duplicate tunnel name: mysql"):
        load_config(config_path)


def test_rejects_conflicting_enabled_local_ports(tmp_path):
    config_path = write_config(
        tmp_path,
        """
        defaults:
          aws:
            region: us-east-1
            target: i-default
            profile: team-profile
            document: AWS-StartPortForwardingSessionToRemoteHost
        tunnels:
          - name: mysql
            remote_host: db-1.internal
            remote_port: 3306
            local_port: 13306
          - name: mysql-shadow
            remote_host: db-2.internal
            remote_port: 3306
            local_port: 13306
        """,
    )

    with pytest.raises(ConfigError, match="both use local_port 13306"):
        load_config(config_path)


def test_rejects_missing_required_effective_aws_fields(tmp_path):
    config_path = write_config(
        tmp_path,
        """
        defaults:
          aws:
            region: us-east-1
            profile: team-profile
            document: AWS-StartPortForwardingSessionToRemoteHost
        tunnels:
          - name: mysql
            remote_host: db.internal
            remote_port: 3306
            local_port: 13306
        """,
    )

    with pytest.raises(
        ConfigError, match="missing required AWS settings after merge: target"
    ):
        load_config(config_path)


@pytest.mark.parametrize("port", [0, 65536])
def test_rejects_invalid_port_ranges(tmp_path, port):
    config_path = write_config(
        tmp_path,
        f"""
        defaults:
          aws:
            region: us-east-1
            target: i-default
            profile: team-profile
            document: AWS-StartPortForwardingSessionToRemoteHost
        tunnels:
          - name: mysql
            remote_host: db.internal
            remote_port: 3306
            local_port: {port}
        """,
    )

    with pytest.raises(ConfigError, match=rf"invalid local_port: {port}"):
        load_config(config_path)


def test_load_config_uses_user_managed_default_path(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    config_path = default_config_path(runtime_root)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        textwrap.dedent(
            """
            version: 1
            defaults:
              aws:
                region: us-east-1
                target: i-default
                profile: team-profile
                document: AWS-StartPortForwardingSessionToRemoteHost
            tunnels: []
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "ssm_tunnel_manager.paths.default_data_dir", lambda: runtime_root
    )

    config = load_config()

    assert config.version == 1
    assert config.effective_tunnels == []


def test_packaged_template_is_generic_and_valid_yaml_shape():
    template = packaged_template_config_text()

    assert "i-your-ssm-target" in template
    assert "your-aws-profile" in template
    assert "tunnels: []" in template
    assert "BackEnd-692642197054" not in template
    assert "prd-mysql-aurora-adcap" not in template
