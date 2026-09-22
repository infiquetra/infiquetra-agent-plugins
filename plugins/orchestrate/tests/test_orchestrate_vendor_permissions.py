"""Permission tokens must reach a vendor as flags and values, never as prompt text.

`grok --always-approve auto` did not fail. `--always-approve` is a value-less switch and grok's
usage is `grok [OPTIONS] [PROMPT]`, so the bare word `auto` bound to the positional prompt: every
dispatched grok session spent its first turn on a permission enum and received its real task only
afterwards. Nothing errored and nothing reported it, which is why this file asserts the exact
command line rather than the presence of a flag.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "orchestrate"
    / "skills"
    / "orchestrate"
    / "scripts"
    / "orchestrate.py"
)

# Every value `--permission-mode` accepts, plus the words the other vendors' modes use. A token from
# this set standing alone in a permission list is the defect: the vendor reads it as a prompt.
PERMISSION_ENUMS = frozenset(
    {
        "default",
        "acceptEdits",
        "auto",
        "dontAsk",
        "bypassPermissions",
        "plan",
        "never",
        "on-request",
        "untrusted",
        "workspace-write",
        "read-only",
        "danger-full-access",
    }
)


@pytest.fixture(scope="module")
def orchestrate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_orchestrate_vendor_permissions", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def launcher_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`agent_argv` resolves the wrapper for real, so give it one rather than stubbing the lookup."""
    (tmp_path / "agents").write_text("#!/bin/sh\n")
    (tmp_path / "agents").chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)


def _vendor_tail(orchestrate: ModuleType, unit: Any) -> list[str]:
    """The arguments the vendor itself receives: everything after the vendor token."""
    argv: list[str] = list(orchestrate.agent_argv(unit))
    return argv[argv.index(unit.vendor) :]


@pytest.mark.usefixtures("launcher_on_path")
class TestGrokReceivesItsPermissionAsAFlagAndValue:
    """The exact command line, both modes. A flag-presence assertion would have passed while broken."""

    def test_auto_emits_permission_mode_auto(self, orchestrate: ModuleType) -> None:
        unit = orchestrate.Unit(
            name="reviewer",
            vendor="grok",
            task="review the diff",
            model="grok-4.6",
            effort="xhigh",
            permission="auto",
        )
        assert _vendor_tail(orchestrate, unit) == [
            "grok",
            "--permission-mode",
            "auto",
            "-m",
            "grok-4.6",
            "--reasoning-effort",
            "xhigh",
        ]

    def test_bypass_emits_permission_mode_bypass_permissions(self, orchestrate: ModuleType) -> None:
        unit = orchestrate.Unit(
            name="builder",
            vendor="grok",
            task="build it",
            model="grok-4.6",
            effort="xhigh",
            permission="bypass",
        )
        assert _vendor_tail(orchestrate, unit) == [
            "grok",
            "--permission-mode",
            "bypassPermissions",
            "-m",
            "grok-4.6",
            "--reasoning-effort",
            "xhigh",
        ]

    def test_the_value_less_switch_is_gone(self, orchestrate: ModuleType) -> None:
        """`--always-approve` takes no value, so it can never carry a mode."""
        for mode in orchestrate.VENDOR_PERMISSION["grok"].values():
            assert "--always-approve" not in mode

    def test_native_passthrough_still_comes_last_and_verbatim(
        self, orchestrate: ModuleType
    ) -> None:
        """The wrapper's own arguments are untouched by this: they still follow everything else."""
        unit = orchestrate.Unit(
            name="reviewer",
            vendor="grok",
            task="x",
            model="grok-4.6",
            permission="auto",
            launch_args=["--not-a-real-flag", "value"],
        )
        tail = _vendor_tail(orchestrate, unit)
        assert tail[-2:] == ["--not-a-real-flag", "value"]
        assert tail.index("--permission-mode") < tail.index("--not-a-real-flag")


class TestNoBarePermissionEnumCanBecomePromptText:
    """The class guard. One vendor was wrong; nothing stopped the next one being wrong the same way."""

    def test_every_bare_enum_is_the_value_of_a_flag_that_takes_one(
        self, orchestrate: ModuleType
    ) -> None:
        for vendor, modes in orchestrate.VENDOR_PERMISSION.items():
            for mode, tokens in modes.items():
                for index, token in enumerate(tokens):
                    if token.startswith("-"):
                        continue
                    assert index > 0, (
                        f"{vendor}/{mode}: {token!r} leads the permission tokens, so the vendor "
                        "reads it as prompt text"
                    )
                    preceding = tokens[index - 1]
                    assert preceding in orchestrate.PERMISSION_FLAGS_TAKING_A_VALUE, (
                        f"{vendor}/{mode}: {preceding!r} does not take a value, so {token!r} "
                        "becomes positional prompt text"
                    )

    def test_a_flag_that_takes_a_value_always_has_one(self, orchestrate: ModuleType) -> None:
        for vendor, modes in orchestrate.VENDOR_PERMISSION.items():
            for mode, tokens in modes.items():
                for index, token in enumerate(tokens):
                    if token not in orchestrate.PERMISSION_FLAGS_TAKING_A_VALUE:
                        continue
                    assert index + 1 < len(tokens), f"{vendor}/{mode}: {token!r} has no value"
                    assert not tokens[index + 1].startswith("-"), (
                        f"{vendor}/{mode}: {token!r} is followed by another flag, not a value"
                    )

    def test_the_declared_set_names_only_flags_the_table_uses(
        self, orchestrate: ModuleType
    ) -> None:
        """A stale entry in the declared set is a guard that has quietly stopped guarding."""
        used = {
            token
            for modes in orchestrate.VENDOR_PERMISSION.values()
            for tokens in modes.values()
            for token in tokens
            if token.startswith("-")
        }
        assert used >= orchestrate.PERMISSION_FLAGS_TAKING_A_VALUE

    def test_the_enum_vocabulary_this_file_guards_against_is_actually_in_use(
        self, orchestrate: ModuleType
    ) -> None:
        """Keeps PERMISSION_ENUMS honest: if no mode uses these words, the guard proves nothing."""
        emitted = {
            token
            for modes in orchestrate.VENDOR_PERMISSION.values()
            for tokens in modes.values()
            for token in tokens
            if not token.startswith("-")
        }
        assert emitted
        assert emitted <= PERMISSION_ENUMS


# Today's bypass tails, pinned literally: a test that re-derives its expectation from the table
# would pass a mutation that changes the flags while keeping the guard green.
BYPASS_TAILS = {
    "agy": ["--dangerously-skip-permissions"],
    "claude": ["--permission-mode", "bypassPermissions"],
    "codex": ["--dangerously-bypass-approvals-and-sandbox"],
    "grok": ["--permission-mode", "bypassPermissions"],
    "muse": ["--yolo"],
    "opencode": ["--auto"],
    "qwen": ["--yolo"],
}


@pytest.mark.usefixtures("launcher_on_path")
class TestADeclaredPermissionIsHonouredNotSilentlyDowngraded:
    """A value outside the vendor's map is a named stop, never a silent auto (#896)."""

    def test_unknown_permission_is_a_named_stop(self, orchestrate: ModuleType) -> None:
        unit = orchestrate.Unit(name="u", vendor="claude", task="x", permission="bypasss")
        with pytest.raises(SystemExit, match="unknown permission"):
            orchestrate.agent_argv(unit)

    def test_unknown_permission_does_not_receive_the_auto_flag_set(
        self, orchestrate: ModuleType
    ) -> None:
        """A typo must stop before any automatic-permission flags enter the command."""
        auto_flag_set = ["--permission-mode", "auto"]
        recorded: list[str] = []

        with pytest.raises(SystemExit, match="unknown permission"):
            orchestrate._extend_permission_argv(recorded, "claude", "bypasss")

        assert recorded == [], f"permission flags entered argv before the stop: {recorded}"
        assert auto_flag_set not in [
            recorded[index : index + 2] for index in range(len(recorded) - 1)
        ]

    @pytest.mark.parametrize("vendor", sorted(BYPASS_TAILS))
    def test_every_vendor_bypass_still_emits_its_documented_flag(
        self, orchestrate: ModuleType, vendor: str
    ) -> None:
        assert set(orchestrate.VENDOR_PERMISSION) == set(BYPASS_TAILS)
        unit = orchestrate.Unit(name="u", vendor=vendor, task="x", permission="bypass")
        assert _vendor_tail(orchestrate, unit) == [vendor] + BYPASS_TAILS[vendor]

    def test_auto_and_omitted_permission_are_unchanged(self, orchestrate: ModuleType) -> None:
        declared = orchestrate.Unit(name="u", vendor="claude", task="x", permission="auto")
        omitted = orchestrate.Unit(name="u", vendor="claude", task="x")
        assert _vendor_tail(orchestrate, declared) == ["claude", "--permission-mode", "auto"]
        assert _vendor_tail(orchestrate, omitted) == _vendor_tail(orchestrate, declared)

    def test_a_vendor_absent_from_the_table_emits_nothing(self, orchestrate: ModuleType) -> None:
        assert orchestrate.resolve_permission("nosuchvendor", "bypass") == []
