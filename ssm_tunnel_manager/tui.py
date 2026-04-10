from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ssm_tunnel_manager.cli import _resolve_tunnel_status
from ssm_tunnel_manager.models import AppConfig
from ssm_tunnel_manager.models import RuntimeStatus
from ssm_tunnel_manager.state import load_runtime_state


_TITLE = "ssm tunnel manager"
_MOTIF = "◎────◎"


class SelectorError(RuntimeError):
    """Raised when the selector cannot be launched."""


class SelectionCancelled(RuntimeError):
    """Raised when the user exits the selector without a choice."""


class SelectionBack(RuntimeError):
    """Raised when the user goes back to the previous selector screen."""


@dataclass(frozen=True)
class SelectorOption:
    label: str
    value: str | None


@dataclass
class _SelectionState:
    options: Sequence[SelectorOption]
    multi: bool
    cursor: int = 0
    selected_values: set[str | None] | None = None

    def __post_init__(self) -> None:
        self.selected_values = set() if self.multi else None

    def move(self, offset: int) -> None:
        if not self.options:
            return
        self.cursor = (self.cursor + offset) % len(self.options)

    def toggle_current(self) -> None:
        if not self.multi or self.selected_values is None:
            return

        current_value = self.current_option.value
        if current_value == _MULTI_ALL_SENTINEL:
            if current_value in self.selected_values:
                self.selected_values.remove(current_value)
            else:
                self.selected_values = {current_value}
            return

        self.selected_values.discard(_MULTI_ALL_SENTINEL)
        if current_value in self.selected_values:
            self.selected_values.remove(current_value)
        else:
            self.selected_values.add(current_value)

    @property
    def current_option(self) -> SelectorOption:
        return self.options[self.cursor]

    def submit(self) -> list[str | None]:
        if not self.multi:
            return [self.current_option.value]

        assert self.selected_values is not None
        if not self.selected_values:
            return [self.current_option.value]

        return [
            option.value
            for option in self.options
            if option.value in self.selected_values
        ]

    def render_lines(
        self,
        *,
        prompt: str,
        header: str,
        context_lines: Sequence[str] = (),
        allow_back: bool = False,
    ) -> list[str]:
        lines = [_TITLE, _MOTIF, "", prompt.rstrip(), header, ""]
        if context_lines:
            lines.extend([*context_lines, ""])
        for index, option in enumerate(self.options):
            cursor_marker = "›" if index == self.cursor else " "
            if self.multi and self.selected_values is not None:
                checked = "x" if option.value in self.selected_values else " "
                label = f"[{checked}] {option.label}"
            else:
                label = option.label
            lines.append(f"{cursor_marker} {label}")

        lines.extend(
            [
                "",
                self._instructions(allow_back=allow_back),
            ]
        )
        return lines

    def render_fragments(
        self,
        *,
        prompt: str,
        header: str,
        context_lines: Sequence[str] = (),
        allow_back: bool = False,
    ) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        for line in self.render_lines(
            prompt=prompt,
            header=header,
            context_lines=context_lines,
            allow_back=allow_back,
        ):
            fragments.extend(self._line_fragments(line))
            fragments.append(("", "\n"))
        if fragments:
            fragments.pop()
        return fragments

    def _instructions(self, *, allow_back: bool) -> str:
        exit_hint = (
            "esc goes back • q/c-c cancels" if allow_back else "q/esc/c-c cancels"
        )
        if self.multi:
            return f"↑/↓ or j/k move • space toggles • enter confirms • {exit_hint}"
        return f"↑/↓ or j/k move • enter confirms • {exit_hint}"

    def _line_fragments(self, line: str) -> list[tuple[str, str]]:
        if line == _TITLE:
            return [("class:title", line)]
        if line == _MOTIF:
            return [("class:motif", line)]
        if line.endswith(">"):
            return [("class:prompt", line)]
        if line.startswith("↑/↓ or j/k move"):
            return [("class:instructions", line)]
        if line.startswith("› "):
            return [("class:cursor", "›"), ("", line[1:])]
        if line.startswith("  "):
            return [("class:muted", " "), ("", line[1:])]
        if not line:
            return [("", line)]
        return [("class:header", line)]


_ACTION_OPTIONS = (
    SelectorOption("status", "status"),
    SelectorOption("upgrade", "upgrade"),
    SelectorOption("login", "login"),
    SelectorOption("start", "start"),
    SelectorOption("stop", "stop"),
    SelectorOption("restart", "restart"),
    SelectorOption("logs", "logs"),
    SelectorOption("help", "help"),
    SelectorOption("uninstall", "uninstall"),
    SelectorOption("quit", "quit"),
)

_ALL_TUNNELS_OPTION = SelectorOption("all", None)
_MULTI_ALL_SENTINEL = "all"


def launch(
    config: AppConfig | None,
    *,
    selector: Selector | None = None,
    action: str | None = None,
) -> argparse.Namespace | None:
    active_selector = selector or Selector()

    try:
        selected_action = action
        while True:
            if selected_action is None:
                selected_action = _select_action(
                    active_selector,
                    context_lines=(
                        _running_tunnel_summary_lines(config)
                        if config is not None
                        else ()
                    ),
                )
            if selected_action == "quit":
                return None
            if selected_action == "help":
                return argparse.Namespace(command="help")
            if selected_action == "upgrade":
                return argparse.Namespace(command="upgrade")
            if selected_action == "login":
                return argparse.Namespace(command="login")
            if selected_action == "uninstall":
                return argparse.Namespace(command="uninstall")

            if config is None:
                return argparse.Namespace(command="tui", action=selected_action)

            tunnel_names = [tunnel.name for tunnel in config.effective_tunnels]
            try:
                if selected_action == "status":
                    selection = active_selector.select_one(
                        [
                            _ALL_TUNNELS_OPTION,
                            *[SelectorOption(name, name) for name in tunnel_names],
                        ],
                        prompt="status > ",
                        header="Choose a tunnel or all.",
                        allow_back=True,
                    )
                    return argparse.Namespace(command="status", name=selection)

                if not tunnel_names:
                    raise SelectorError(
                        f"The '{selected_action}' action requires at least one configured tunnel."
                    )

                if selected_action == "logs":
                    name = active_selector.select_one(
                        [SelectorOption(name, name) for name in tunnel_names],
                        prompt="logs > ",
                        header="Choose one tunnel.",
                        allow_back=True,
                    )
                    return argparse.Namespace(command="logs", name=name)

                if selected_action in {"start", "stop", "restart"}:
                    names = active_selector.select_many(
                        [
                            _multi_all_option(),
                            *[SelectorOption(name, name) for name in tunnel_names],
                        ],
                        prompt=f"{selected_action} > ",
                        header=f"Choose one or more tunnels to {selected_action}, or select all.",
                        allow_back=True,
                        context_lines=_running_tunnel_summary_lines(config),
                    )
                    if _MULTI_ALL_SENTINEL in names:
                        return argparse.Namespace(
                            command=selected_action, names=[], all=True
                        )
                    return argparse.Namespace(
                        command=selected_action, names=names, all=False
                    )

                names = active_selector.select_many(
                    [SelectorOption(name, name) for name in tunnel_names],
                    prompt=f"{selected_action} > ",
                    header=f"Choose one or more tunnels to {selected_action}.",
                    allow_back=True,
                )
                return argparse.Namespace(
                    command=selected_action, names=names, all=False
                )
            except SelectionBack:
                selected_action = None
    except SelectionCancelled:
        return None


class Selector:
    def select_one(
        self,
        options: Sequence[SelectorOption],
        *,
        prompt: str,
        header: str,
        allow_back: bool = False,
        context_lines: Sequence[str] = (),
    ) -> str | None:
        selection = self._run(
            options,
            prompt=prompt,
            header=header,
            multi=False,
            allow_back=allow_back,
            context_lines=context_lines,
        )
        if len(selection) != 1:
            raise SelectorError(
                "Expected a single selection from the interactive selector."
            )
        return selection[0]

    def select_many(
        self,
        options: Sequence[SelectorOption],
        *,
        prompt: str,
        header: str,
        allow_back: bool = False,
        context_lines: Sequence[str] = (),
    ) -> list[str]:
        selection = self._run(
            options,
            prompt=prompt,
            header=header,
            multi=True,
            allow_back=allow_back,
            context_lines=context_lines,
        )
        if not selection:
            raise SelectorError(
                "Expected at least one selection from the interactive selector."
            )
        return selection

    def _run(
        self,
        options: Sequence[SelectorOption],
        *,
        prompt: str,
        header: str,
        multi: bool,
        allow_back: bool,
        context_lines: Sequence[str],
    ) -> list[str | None]:
        if not options:
            raise SelectorError("No options available for selection.")

        state = _SelectionState(options=options, multi=multi)
        app = self._build_application(
            state,
            prompt=prompt,
            header=header,
            allow_back=allow_back,
            context_lines=context_lines,
        )
        try:
            result = app.run()
        except KeyboardInterrupt as exc:
            raise SelectionCancelled() from exc

        if result is _BACK_SENTINEL:
            raise SelectionBack()
        if result is None:
            raise SelectionCancelled()
        return result

    def _build_application(
        self,
        state: _SelectionState,
        *,
        prompt: str,
        header: str,
        allow_back: bool = False,
        context_lines: Sequence[str] = (),
    ) -> Any:
        try:
            from prompt_toolkit.application import Application
            from prompt_toolkit.styles import Style
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.layout import HSplit, Layout, Window
            from prompt_toolkit.layout.controls import FormattedTextControl
        except ImportError as exc:
            raise SelectorError(
                "prompt_toolkit is required for `ssm-tunnel tui`. Reinstall the package "
                "with runtime dependencies to use the interactive selector."
            ) from exc

        bindings = KeyBindings()

        @bindings.add("up")
        @bindings.add("k")
        def _move_up(event) -> None:
            state.move(-1)
            event.app.invalidate()

        @bindings.add("down")
        @bindings.add("j")
        def _move_down(event) -> None:
            state.move(1)
            event.app.invalidate()

        @bindings.add("enter")
        def _submit(event) -> None:
            event.app.exit(result=state.submit())

        @bindings.add("q")
        @bindings.add("c-c")
        def _cancel(event) -> None:
            event.app.exit(result=None)

        if allow_back:

            @bindings.add("escape")
            def _go_back(event) -> None:
                event.app.exit(result=_BACK_SENTINEL)

        else:

            @bindings.add("escape")
            def _cancel_escape(event) -> None:
                event.app.exit(result=None)

        if state.multi:

            @bindings.add("space")
            def _toggle(event) -> None:
                state.toggle_current()
                event.app.invalidate()

        style = Style.from_dict(
            {
                "title": "bold ansicyan",
                "motif": "ansiblue",
                "prompt": "bold ansigreen",
                "header": "ansiyellow",
                "instructions": "ansibrightblack",
                "cursor": "bold ansimagenta",
                "muted": "ansibrightblack",
            }
        )

        def _get_text() -> list[tuple[str, str]]:
            return state.render_fragments(
                prompt=prompt,
                header=header,
                context_lines=context_lines,
                allow_back=allow_back,
            )

        body = Window(
            content=FormattedTextControl(_get_text),
            always_hide_cursor=True,
        )

        return Application(
            layout=Layout(HSplit([body])),
            key_bindings=bindings,
            style=style,
            full_screen=True,
            erase_when_done=True,
            mouse_support=False,
        )


def _select_action(selector: Selector, *, context_lines: Sequence[str] = ()) -> str:
    action = selector.select_one(
        _ACTION_OPTIONS,
        prompt="action > ",
        header="Choose an action.",
        context_lines=context_lines,
    )
    assert action is not None
    return action


def _multi_all_option() -> SelectorOption:
    return SelectorOption("all", _MULTI_ALL_SENTINEL)


_BACK_SENTINEL = object()


def _running_tunnel_summary_lines(config: AppConfig) -> list[str]:
    runtime_states = load_runtime_state()
    running_entries: list[str] = []

    for tunnel in config.effective_tunnels:
        status, _ = _resolve_tunnel_status(config, tunnel, runtime_states)
        if status is not RuntimeStatus.RUNNING:
            continue
        running_entries.append(
            f"• {tunnel.name}  localhost:{tunnel.local_port} → {tunnel.remote_host}:{tunnel.remote_port}"
        )

    if not running_entries:
        return ["Running now", "• none"]

    return ["Running now", *running_entries]
