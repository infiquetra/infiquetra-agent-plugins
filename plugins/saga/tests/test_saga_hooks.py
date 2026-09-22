"""Hook-manifest contracts for Saga: what is registered, and what must never come back.

This module was written after the lease retirement (#356, #677/U5) to pin two things: that no lease
registration survives anywhere in `hooks.json`, and that the hooks sharing the deleted hook's matcher
blocks were still armed afterwards -- the guard against a manifest edit taking a neighbour with it.

Issue 1030 removed four more hooks (the delegation tripwire, the delegation stop audit, the
team-spawn residency check, and the team teardown), and the five teardown-behaviour cases that lived
here retired with the hook whose behaviour they described. Both original contracts survive, with the
neighbour list updated to hooks that still exist: a manifest edit that removes four registrations is
exactly the moment the neighbour guard earns its keep.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOKS_JSON = REPO_ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "hooks.json"

#: The eight hook files that survive issue 1030, by filename.
SURVIVING_HOOKS: frozenset[str] = frozenset(
    {
        "compact_spore_session_hook.py",
        "journal_nudge_hook.py",
        "next_step_session_hook.py",
        "pre_push_gate_hook.py",
        "precompact_spore_hook.py",
        "prompt_suggestion_hook.py",
        "stale_main_session_hook.py",
        "validate_json_hook.py",
    }
)

#: Every hook issue 1030 removed, plus the two lease hooks removed before it. None may return.
RETIRED_HOOKS: frozenset[str] = frozenset(
    {
        "lease_lifecycle_hook.py",
        "lease_mutation_hook.py",
        "delegation_tripwire_hook.py",
        "delegation_stop_audit_hook.py",
        "team_spawn_residency_hook.py",
        "team_teardown_hook.py",
    }
)


def _events() -> dict[str, Any]:
    events: dict[str, Any] = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
    return events


def _commands(entries: list[dict[str, Any]], matcher: str | None = None) -> list[str]:
    result: list[str] = []
    for entry in entries:
        if matcher is not None and entry.get("matcher") != matcher:
            continue
        result.extend(hook["command"] for hook in entry.get("hooks", []))
    return result


def _all_commands() -> list[str]:
    return [command for entries in _events().values() for command in _commands(entries)]


def test_no_retired_hook_is_registered_anywhere_in_the_manifest() -> None:
    """The re-add guard. It names each retired hook by filename, so a restored registration fails
    on the name rather than on a count that a differently-named replacement would satisfy."""
    commands = _all_commands()
    for retired in sorted(RETIRED_HOOKS):
        offenders = [command for command in commands if retired in command]
        assert not offenders, f"{retired} is registered again: {offenders}"


def test_the_manifest_registers_exactly_the_surviving_hooks() -> None:
    """The other half: a manifest edit that removes four registrations must not take a fifth.

    Asserting the set rather than a count is the point -- an edit that dropped the journal nudge
    and added something else would keep any count intact.
    """
    registered = {
        command.rsplit("/", 1)[-1].rstrip('"') for command in _all_commands() if ".py" in command
    }
    assert registered == SURVIVING_HOOKS


def test_every_registered_hook_file_exists_on_disk() -> None:
    """A registration pointing at a deleted file fails silently at session start, which is the
    failure mode that makes hook removal worth guarding at all."""
    hooks_dir = HOOKS_JSON.parent
    for name in sorted(SURVIVING_HOOKS):
        assert (hooks_dir / name).is_file(), f"{name} is registered but not on disk"


def test_no_hook_file_on_disk_is_left_unregistered() -> None:
    """The inverse: a surviving file nobody registers is dead code that reads as live."""
    on_disk = {p.name for p in HOOKS_JSON.parent.glob("*.py")}
    assert on_disk == SURVIVING_HOOKS


def test_the_events_that_lost_their_only_hook_are_gone_from_the_manifest() -> None:
    """`SessionEnd`, `Stop` and `SubagentStop` each carried exactly one hook, all removed by issue
    1030. An event key left behind with an empty list is a manifest that claims a seam it no longer
    uses."""
    events = _events()
    for event in ("SessionEnd", "Stop", "SubagentStop"):
        assert event not in events, f"{event} is still declared with no hook behind it"
    for event, entries in events.items():
        assert _commands(entries), f"{event} is declared with no command behind it"


def test_the_surviving_neighbours_of_the_edited_blocks_are_still_armed() -> None:
    """The original contract of this module, retargeted. The four removals touched `PreToolUse`
    (two matcher blocks), `SessionStart` (one), and three whole events; these are the registrations
    that shared those blocks and had to come through unharmed."""
    events = _events()
    assert any(
        "validate_json_hook.py" in command
        for command in _commands(events["PreToolUse"], "Edit|Write|MultiEdit")
    )
    assert any(
        "pre_push_gate_hook.py" in command for command in _commands(events["PreToolUse"], "Bash")
    )
    assert any(
        "journal_nudge_hook.py" in command for command in _commands(events["PostToolUse"], "Bash")
    )
    assert any(
        "next_step_session_hook.py" in command
        for command in _commands(events["SessionStart"], "startup|resume")
    )
    assert any(
        "stale_main_session_hook.py" in command
        for command in _commands(events["SessionStart"], "startup|resume")
    )
