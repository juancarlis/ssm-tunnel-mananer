from __future__ import annotations

import sys
import types

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
    _SelectionState,
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


def test_tui_multi_select_space_keeps_checkbox_state_in_option_order():
    state = _SelectionState(
        options=[
            SelectorOption("all", "all"),
            SelectorOption("mysql", "mysql"),
            SelectorOption("redis", "redis"),
        ],
        multi=True,
    )

    state.move(1)
    state.toggle_current()
    state.move(1)
    state.toggle_current()

    assert state.submit() == ["mysql", "redis"]


def test_tui_multi_select_all_clears_individual_checkbox_selection():
    state = _SelectionState(
        options=[
            SelectorOption("all", "all"),
            SelectorOption("mysql", "mysql"),
            SelectorOption("redis", "redis"),
        ],
        multi=True,
    )

    state.move(1)
    state.toggle_current()
    state.move(-1)
    state.toggle_current()

    assert state.submit() == ["all"]


def test_tui_multi_select_enter_defaults_to_current_option_when_nothing_is_checked():
    state = _SelectionState(
        options=[
            SelectorOption("all", "all"),
            SelectorOption("mysql", "mysql"),
            SelectorOption("redis", "redis"),
        ],
        multi=True,
    )

    state.move(2)

    assert state.submit() == ["redis"]


def test_tui_instructions_include_q_cancel_shortcut():
    single = _SelectionState(
        options=[SelectorOption("mysql", "mysql")],
        multi=False,
    )
    multi = _SelectionState(
        options=[SelectorOption("mysql", "mysql")],
        multi=True,
    )

    assert single.render_lines(prompt="action > ", header="Choose an action.")[-1] == (
        "↑/↓ or j/k move • enter confirms • q/esc/c-c cancels"
    )
    assert multi.render_lines(prompt="start > ", header="Choose tunnels.")[-1] == (
        "↑/↓ or j/k move • space toggles • enter confirms • q/esc/c-c cancels"
    )


def test_tui_render_lines_include_title_and_tunnel_motif():
    state = _SelectionState(
        options=[SelectorOption("mysql", "mysql")],
        multi=False,
    )

    lines = state.render_lines(prompt="action > ", header="Choose an action.")

    assert lines[:5] == [
        "ssm tunnel manager",
        "◎────◎",
        "",
        "action >",
        "Choose an action.",
    ]


def test_tui_reports_missing_prompt_toolkit_dependency(monkeypatch):
    selector = Selector()

    def fake_builder(*args, **kwargs):
        raise SelectorError("prompt_toolkit is required for `ssm-tunnel tui`.")

    monkeypatch.setattr(selector, "_build_application", fake_builder)

    with pytest.raises(SelectorError, match="prompt_toolkit is required"):
        selector.select_one(
            [SelectorOption("status", "status")],
            prompt="action > ",
            header="Choose an action.",
        )


def test_tui_selector_runs_in_process_application(monkeypatch):
    recorded = {}

    class FakeApplication:
        def run(self):
            return ["redis", "mysql"]

    def fake_builder(state, *, prompt: str, header: str):
        recorded["prompt"] = prompt
        recorded["header"] = header
        recorded["multi"] = state.multi
        recorded["options"] = [option.label for option in state.options]
        return FakeApplication()

    selector = Selector()
    monkeypatch.setattr(selector, "_build_application", fake_builder)

    selection = selector.select_many(
        [
            SelectorOption("mysql", "mysql"),
            SelectorOption("redis", "redis"),
        ],
        prompt="start > ",
        header="Choose one or more tunnels to start.",
    )

    assert selection == ["redis", "mysql"]
    assert recorded == {
        "prompt": "start > ",
        "header": "Choose one or more tunnels to start.",
        "multi": True,
        "options": ["mysql", "redis"],
    }


def test_tui_selector_uses_full_screen_app_and_q_cancel_binding(monkeypatch):
    recorded = {}

    class FakeApplication:
        def __init__(self, **kwargs):
            self.layout = kwargs["layout"]
            self.key_bindings = kwargs["key_bindings"]
            self.style = kwargs["style"]
            self.full_screen = kwargs["full_screen"]
            self.erase_when_done = kwargs["erase_when_done"]
            self.mouse_support = kwargs["mouse_support"]

    class FakeKeyBindings:
        def __init__(self):
            self.bindings = []

        def add(self, *keys):
            def decorator(handler):
                self.bindings.append((keys, handler.__name__))
                return handler

            return decorator

    def fake_hsplit(children):
        recorded["hsplit_children"] = children
        return ("hsplit", children)

    def fake_layout(container):
        recorded["layout_container"] = container
        return ("layout", container)

    class FakeWindow:
        def __init__(self, *, content, always_hide_cursor):
            self.content = content
            self.always_hide_cursor = always_hide_cursor

    class FakeFormattedTextControl:
        def __init__(self, text):
            self.text = text

    prompt_toolkit_module = types.ModuleType("prompt_toolkit")
    application_module = types.ModuleType("prompt_toolkit.application")
    application_module.Application = FakeApplication
    key_binding_module = types.ModuleType("prompt_toolkit.key_binding")
    key_binding_module.KeyBindings = FakeKeyBindings
    layout_module = types.ModuleType("prompt_toolkit.layout")
    layout_module.HSplit = fake_hsplit
    layout_module.Layout = fake_layout
    layout_module.Window = FakeWindow
    controls_module = types.ModuleType("prompt_toolkit.layout.controls")
    controls_module.FormattedTextControl = FakeFormattedTextControl

    monkeypatch.setitem(sys.modules, "prompt_toolkit", prompt_toolkit_module)
    monkeypatch.setitem(sys.modules, "prompt_toolkit.application", application_module)
    monkeypatch.setitem(sys.modules, "prompt_toolkit.key_binding", key_binding_module)
    monkeypatch.setitem(sys.modules, "prompt_toolkit.layout", layout_module)
    monkeypatch.setitem(sys.modules, "prompt_toolkit.layout.controls", controls_module)

    styles_module = types.ModuleType("prompt_toolkit.styles")

    class FakeStyle:
        @classmethod
        def from_dict(cls, style_map):
            return style_map

    styles_module.Style = FakeStyle
    monkeypatch.setitem(sys.modules, "prompt_toolkit.styles", styles_module)

    selector = Selector()
    app = selector._build_application(
        _SelectionState(
            options=[SelectorOption("status", "status")],
            multi=False,
        ),
        prompt="action > ",
        header="Choose an action.",
    )

    assert app.full_screen is True
    assert app.erase_when_done is True
    assert app.mouse_support is False
    assert app.style["title"] == "bold ansicyan"
    assert (("q",), "_cancel") in app.key_bindings.bindings
    assert (("escape",), "_cancel") in app.key_bindings.bindings
    assert (("c-c",), "_cancel") in app.key_bindings.bindings

    control = recorded["hsplit_children"][0].content
    fragments = control.text()
    assert ("class:title", "ssm tunnel manager") in fragments
    assert ("class:motif", "◎────◎") in fragments
