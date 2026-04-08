from __future__ import annotations

import argparse
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

from ssm_tunnel_manager.models import AppConfig


class SelectorError(RuntimeError):
    """Raised when the selector cannot be launched."""


class SelectionCancelled(RuntimeError):
    """Raised when the user exits the selector without a choice."""


@dataclass(frozen=True)
class SelectorOption:
    label: str
    value: str | None


_ACTION_OPTIONS = (
    SelectorOption("status", "status"),
    SelectorOption("login", "login"),
    SelectorOption("start", "start"),
    SelectorOption("stop", "stop"),
    SelectorOption("restart", "restart"),
    SelectorOption("logs", "logs"),
    SelectorOption("help", "help"),
    SelectorOption("quit", "quit"),
)

_ALL_TUNNELS_OPTION = SelectorOption("all", None)
_MULTI_ALL_SENTINEL = "all"


def launch(
    config: AppConfig,
    *,
    selector: Selector | None = None,
) -> argparse.Namespace | None:
    active_selector = selector or Selector()

    try:
        action = _select_action(active_selector)
        if action == "quit":
            return None
        if action == "help":
            return argparse.Namespace(command="help")
        if action == "login":
            return argparse.Namespace(command="login")

        tunnel_names = [tunnel.name for tunnel in config.effective_tunnels]
        if action == "status":
            selection = active_selector.select_one(
                [
                    _ALL_TUNNELS_OPTION,
                    *[SelectorOption(name, name) for name in tunnel_names],
                ],
                prompt="status > ",
                header="Choose a tunnel or all.",
            )
            return argparse.Namespace(command="status", name=selection)

        if not tunnel_names:
            raise SelectorError(
                f"The '{action}' action requires at least one configured tunnel."
            )

        if action == "logs":
            name = active_selector.select_one(
                [SelectorOption(name, name) for name in tunnel_names],
                prompt="logs > ",
                header="Choose one tunnel.",
            )
            return argparse.Namespace(command="logs", name=name)

        if action == "stop":
            names = active_selector.select_many(
                [
                    _stop_all_option(),
                    *[SelectorOption(name, name) for name in tunnel_names],
                ],
                prompt="stop > ",
                header="Choose one or more tunnels to stop, or select all.",
            )
            if _MULTI_ALL_SENTINEL in names:
                return argparse.Namespace(command="stop", names=[], all=True)
            return argparse.Namespace(command="stop", names=names, all=False)

        names = active_selector.select_many(
            [SelectorOption(name, name) for name in tunnel_names],
            prompt=f"{action} > ",
            header=f"Choose one or more tunnels to {action}.",
        )
        return argparse.Namespace(command=action, names=names, all=False)
    except SelectionCancelled:
        return None


class Selector:
    def __init__(self, executable: str = "fzf") -> None:
        self.executable = executable

    def select_one(
        self,
        options: Sequence[SelectorOption],
        *,
        prompt: str,
        header: str,
    ) -> str | None:
        selection = self._run(options, prompt=prompt, header=header, multi=False)
        if len(selection) != 1:
            raise SelectorError("Expected a single selection from fzf.")
        return selection[0]

    def select_many(
        self,
        options: Sequence[SelectorOption],
        *,
        prompt: str,
        header: str,
    ) -> list[str]:
        selection = self._run(options, prompt=prompt, header=header, multi=True)
        if not selection:
            raise SelectorError("Expected at least one selection from fzf.")
        return selection

    def _run(
        self,
        options: Sequence[SelectorOption],
        *,
        prompt: str,
        header: str,
        multi: bool,
    ) -> list[str | None]:
        if not options:
            raise SelectorError("No options available for selection.")

        executable = shutil.which(self.executable)
        if executable is None:
            raise SelectorError(
                "fzf is required for `ssm-tunnel tui` but was not found in PATH. "
                "Install `fzf` to use the interactive selector."
            )

        labels = [option.label for option in options]
        by_label = {option.label: option.value for option in options}
        command = [
            executable,
            "--prompt",
            prompt,
            "--header",
            header,
            "--height",
            "40%",
            "--layout",
            "reverse",
            "--border",
        ]
        if multi:
            command.append("--multi")

        result = subprocess.run(
            command,
            input="\n".join(labels) + "\n",
            text=True,
            capture_output=True,
            check=False,
        )

        if result.returncode == 0:
            selected_labels = [line for line in result.stdout.splitlines() if line]
            return [by_label[label] for label in selected_labels]
        if result.returncode == 130:
            raise SelectionCancelled()
        raise SelectorError(result.stderr.strip() or "fzf exited unexpectedly.")


def _select_action(selector: Selector) -> str:
    action = selector.select_one(
        _ACTION_OPTIONS,
        prompt="action > ",
        header="Choose an action.",
    )
    assert action is not None
    return action


def _stop_all_option() -> SelectorOption:
    return SelectorOption("all", _MULTI_ALL_SENTINEL)
