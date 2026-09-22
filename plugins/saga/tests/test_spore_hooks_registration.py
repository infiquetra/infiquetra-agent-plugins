"""U4 registration guard (issue #281): both ends of the spore are wired in hooks.json.

A spore writer with no reader (or vice-versa) is the dead-wiring failure mode KD2 calls out, so this
asserts (a) a PreCompact matcher covering auto+manual -> precompact_spore_hook.py, (b) a SessionStart
entry matched ``compact`` -> compact_spore_session_hook.py, and (c) the existing startup|resume
stale-main entry is unchanged (no regression to the proven path). JSON validity is implied by load."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

HOOKS_JSON = Path(__file__).resolve().parents[3] / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "hooks.json"


def _events() -> dict[str, list[dict]]:
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    return cast("dict[str, list[dict]]", data["hooks"])


def _commands_for(entries: list[dict], matcher: str) -> list[str]:
    """All hook commands registered under the entry whose matcher equals ``matcher``."""
    cmds: list[str] = []
    for entry in entries:
        if entry.get("matcher") == matcher:
            cmds.extend(h.get("command", "") for h in entry.get("hooks", []))
    return cmds


def test_precompact_hook_registered_for_auto_and_manual() -> None:
    events = _events()
    assert "PreCompact" in events, "PreCompact event not registered"
    precompact = events["PreCompact"]
    # A single matcher must cover BOTH auto and manual compaction (R6).
    covering = [
        e
        for e in precompact
        if "auto" in (e.get("matcher") or "") and "manual" in (e.get("matcher") or "")
    ]
    assert covering, "no PreCompact matcher covers both auto and manual"
    cmds = [h.get("command", "") for e in covering for h in e.get("hooks", [])]
    assert any("precompact_spore_hook.py" in c for c in cmds)


def test_sessionstart_compact_hook_registered() -> None:
    events = _events()
    cmds = _commands_for(events["SessionStart"], "compact")
    assert any("compact_spore_session_hook.py" in c for c in cmds), (
        "SessionStart(compact) not wired to compact_spore_session_hook.py"
    )


def test_stale_main_startup_resume_entry_unchanged() -> None:
    # KTD1: the new compact hook is a SEPARATE entry; the proven startup|resume path must be intact.
    events = _events()
    cmds = _commands_for(events["SessionStart"], "startup|resume")
    assert any("stale_main_session_hook.py" in c for c in cmds)
    # And the spore hook must NOT have leaked into the stale-main entry.
    assert not any("compact_spore_session_hook.py" in c for c in cmds)


def _all_commands(entries: list[dict]) -> list[str]:
    """All hook commands under an event, regardless of matcher (Stop entries have none)."""
    return [h.get("command", "") for e in entries for h in e.get("hooks", [])]


def test_validate_json_pretooluse_entry_unchanged() -> None:
    # The pre-existing validate_json entry must be untouched by the new registration.
    events = _events()
    cmds = _commands_for(events["PreToolUse"], "Edit|Write|MultiEdit")
    assert any("validate_json_hook.py" in c for c in cmds)
    assert not any("delegation_tripwire_hook.py" in c for c in cmds)


# --------------------------------------------------------------------------------------------
# Issue #1029: the continuation hooks, registered BESIDE everything already here.
# --------------------------------------------------------------------------------------------

#: Every hook script registered before issue #1029 added its two. A registration that dropped one
#: of these would be a silently disabled hook, which is the failure mode this list exists to catch.
#:
#: ``ship_teardown.py`` was a member until issue #1027 removed the ship ceremony: its SessionStart
#: entry ran ``ship_teardown.py reclaim --if-idle 24h --quiet``, and the entry was deleted in the
#: same change as the module it invoked. That is a DELIBERATE removal, not the silent displacement
#: this list guards against, and the distinction is the reason the list is edited by hand: a guard
#: that quietly followed the manifest could not tell one from the other.
# Issue 1030 removed four of these (team_teardown_hook.py, team_spawn_residency_hook.py,
# delegation_tripwire_hook.py, delegation_stop_audit_hook.py) with the machinery they served. The
# list shrinks with them; tests/test_saga_hooks.py owns the re-add guard that keeps them out.
PRE_EXISTING_HOOK_SCRIPTS = (
    "stale_main_session_hook.py",
    "compact_spore_session_hook.py",
    "precompact_spore_hook.py",
    "validate_json_hook.py",
    "pre_push_gate_hook.py",
    "journal_nudge_hook.py",
)


def test_next_step_session_hook_registered_for_startup_and_resume() -> None:
    # #1029: the cold-start reader of the run record. `compact` is the spore hook's, which carries
    # the record in its frozen block already, so announcing it there too would be noise.
    events = _events()
    cmds = _commands_for(events["SessionStart"], "startup|resume")
    assert any("next_step_session_hook.py" in c for c in cmds), (
        "SessionStart(startup|resume) not wired to next_step_session_hook.py"
    )
    compact_cmds = _commands_for(events["SessionStart"], "compact")
    assert not any("next_step_session_hook.py" in c for c in compact_cmds)


def test_prompt_suggestion_hook_registered_for_user_prompt_submit() -> None:
    # #1029: the local-only suggestion. It matches every prompt, so it carries no matcher.
    events = _events()
    assert "UserPromptSubmit" in events, "UserPromptSubmit event not registered"
    cmds = _all_commands(events["UserPromptSubmit"])
    assert any("prompt_suggestion_hook.py" in c for c in cmds), (
        "UserPromptSubmit not wired to prompt_suggestion_hook.py"
    )


def test_the_new_registrations_displaced_nothing() -> None:
    # The two #1029 entries coexist with every hook that was registered before them, including
    # whatever a sibling card adds later: this asserts presence, never an exact set.
    events = _events()
    registered = "\n".join(c for entries in events.values() for c in _all_commands(entries))
    missing = [s for s in PRE_EXISTING_HOOK_SCRIPTS if s not in registered]
    assert not missing, f"registration lost: {missing}"
