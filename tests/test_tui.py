from __future__ import annotations

import subprocess

import pytest

from ssm_tunnel_manager.models import (
    AppConfig,
    AwsSettings,
    DefaultsConfig,
    EffectiveTunnel,
)
from ssm_tunnel_manager.tui import (
    SelectionCancelled,
    Selector,
    SelectorError,
    SelectorOption,
    launch,
)


def build_config(*names: str) -> AppConfig:
    tunnels = [
        EffectiveTunnel(
            name=name,
            remote_host=f"{name}.internal",
            remote_port=3306,
            local_port=13000 + index,
            description=None,
            tags=[],
            enabled=True,
            aws=AwsSettings(
                region="us-east-1",
                target="i-default",
                profile="team-profile",
                document="AWS-StartPortForwardingSessionToRemoteHost",
            ),
        )
        for index, name in enumerate(names, start=1)
    ]
    return AppConfig(
        version=1,
        defaults=DefaultsConfig(backend="tmux"),
        tunnels=[],
        effective_tunnels=tunnels,
    )


class FakeSelector:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = []

    def select_one(self, options, *, prompt: str, header: str):
        self.calls.append(("one", [option.label for option in options], prompt, header))
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response

    def select_many(self, options, *, prompt: str, header: str):
        self.calls.append(
            ("many", [option.label for option in options], prompt, header)
        )
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_tui_prompts_for_action_first_and_quit_exits_cleanly():
    selector = FakeSelector(["quit"])

    selection = launch(build_config("mysql", "redis"), selector=selector)

    assert selection is None
    assert selector.calls == [
        (
            "one",
            [
                "status",
                "upgrade",
                "login",
                "start",
                "stop",
                "restart",
                "logs",
                "help",
                "uninstall",
                "quit",
            ],
            "action > ",
            "Choose an action.",
        )
    ]


def test_tui_status_supports_all_tunnels_after_action_selection():
    selector = FakeSelector(["status", None])

    selection = launch(build_config("mysql", "redis"), selector=selector)

    assert selection.command == "status"
    assert selection.name is None
    assert selector.calls == [
        (
            "one",
            [
                "status",
                "upgrade",
                "login",
                "start",
                "stop",
                "restart",
                "logs",
                "help",
                "uninstall",
                "quit",
            ],
            "action > ",
            "Choose an action.",
        ),
        (
            "one",
            ["all", "mysql", "redis"],
            "status > ",
            "Choose a tunnel or all.",
        ),
    ]


def test_tui_logs_keeps_single_tunnel_selection():
    selector = FakeSelector(["logs", "redis"])

    selection = launch(build_config("mysql", "redis"), selector=selector)

    assert selection.command == "logs"
    assert selection.name == "redis"
    assert not hasattr(selection, "names")
    assert selector.calls[-1] == (
        "one",
        ["mysql", "redis"],
        "logs > ",
        "Choose one tunnel.",
    )


def test_tui_start_offers_explicit_all_option_and_maps_to_cli_all_flag():
    selector = FakeSelector(["start", ["all"]])

    selection = launch(build_config("mysql", "redis", "admin"), selector=selector)

    assert selection.command == "start"
    assert selection.names == []
    assert selection.all is True
    assert selector.calls[-1] == (
        "many",
        ["all", "mysql", "redis", "admin"],
        "start > ",
        "Choose one or more tunnels to start, or select all.",
    )


def test_tui_start_keeps_multi_select_for_specific_tunnels():
    selector = FakeSelector(["start", ["admin", "mysql"]])

    selection = launch(build_config("mysql", "redis", "admin"), selector=selector)

    assert selection.command == "start"
    assert selection.names == ["admin", "mysql"]
    assert selection.all is False
    assert selector.calls[-1] == (
        "many",
        ["all", "mysql", "redis", "admin"],
        "start > ",
        "Choose one or more tunnels to start, or select all.",
    )


def test_tui_stop_offers_explicit_all_option_and_maps_to_cli_all_flag():
    selector = FakeSelector(["stop", ["all"]])

    selection = launch(build_config("mysql", "redis"), selector=selector)

    assert selection.command == "stop"
    assert selection.names == []
    assert selection.all is True
    assert selector.calls[-1] == (
        "many",
        ["all", "mysql", "redis"],
        "stop > ",
        "Choose one or more tunnels to stop, or select all.",
    )


def test_tui_restart_offers_explicit_all_option_and_maps_to_cli_all_flag():
    selector = FakeSelector(["restart", ["all"]])

    selection = launch(build_config("mysql", "redis"), selector=selector)

    assert selection.command == "restart"
    assert selection.names == []
    assert selection.all is True
    assert selector.calls[-1] == (
        "many",
        ["all", "mysql", "redis"],
        "restart > ",
        "Choose one or more tunnels to restart, or select all.",
    )


def test_tui_help_returns_help_command_without_tunnel_prompt():
    selector = FakeSelector(["help"])

    selection = launch(build_config("mysql"), selector=selector)

    assert selection.command == "help"
    assert len(selector.calls) == 1


def test_tui_upgrade_returns_command_without_tunnel_prompt():
    selector = FakeSelector(["upgrade"])

    selection = launch(build_config("mysql"), selector=selector)

    assert selection.command == "upgrade"
    assert len(selector.calls) == 1


def test_tui_login_returns_login_command_without_tunnel_prompt():
    selector = FakeSelector(["login"])

    selection = launch(build_config(), selector=selector)

    assert selection.command == "login"
    assert len(selector.calls) == 1


def test_tui_uninstall_returns_command_without_tunnel_prompt():
    selector = FakeSelector(["uninstall"])

    selection = launch(None, selector=selector)

    assert selection.command == "uninstall"
    assert len(selector.calls) == 1


def test_tui_returns_selected_action_when_config_is_needed_later():
    selector = FakeSelector(["start"])

    selection = launch(None, selector=selector)

    assert selection.command == "tui"
    assert selection.action == "start"
    assert len(selector.calls) == 1


def test_tui_cancellation_exits_without_selection():
    selector = FakeSelector([SelectionCancelled()])

    assert launch(build_config("mysql"), selector=selector) is None


def test_tui_reports_missing_fzf_binary(monkeypatch):
    selector = Selector()
    monkeypatch.setattr("ssm_tunnel_manager.tui.shutil.which", lambda _: None)

    with pytest.raises(SelectorError, match="fzf is required"):
        selector.select_one(
            [SelectorOption("status", "status")],
            prompt="action > ",
            header="Choose an action.",
        )


def test_tui_selector_uses_fzf_multi_for_lifecycle_actions(monkeypatch):
    recorded = {}

    def fake_run(command, *, input, text, capture_output, check):
        recorded["command"] = command
        recorded["input"] = input
        recorded["text"] = text
        recorded["capture_output"] = capture_output
        recorded["check"] = check
        return subprocess.CompletedProcess(
            command, 0, stdout="redis\nmysql\n", stderr=""
        )

    monkeypatch.setattr("ssm_tunnel_manager.tui.shutil.which", lambda _: "/usr/bin/fzf")
    monkeypatch.setattr("ssm_tunnel_manager.tui.subprocess.run", fake_run)

    selection = Selector().select_many(
        [
            SelectorOption("mysql", "mysql"),
            SelectorOption("redis", "redis"),
        ],
        prompt="start > ",
        header="Choose one or more tunnels to start.",
    )

    assert selection == ["redis", "mysql"]
    assert recorded["command"] == [
        "/usr/bin/fzf",
        "--prompt",
        "start > ",
        "--header",
        "Choose one or more tunnels to start.",
        "--height",
        "40%",
        "--layout",
        "reverse",
        "--border",
        "--multi",
    ]
    assert recorded["input"] == "mysql\nredis\n"
    assert recorded["text"] is True
    assert recorded["capture_output"] is True
    assert recorded["check"] is False
