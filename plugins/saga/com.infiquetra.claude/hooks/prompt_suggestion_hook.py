#!/usr/bin/env python3
"""UserPromptSubmit hook: name the saga command the operator's text is about. Locally. Advisory.

Issue #1029.

**Local only, and that is a data-governance constraint rather than a preference.** This hook makes
no network call, imports no client, and sends nothing off the machine. Issue #1038 measured a
typed-judgment version of this suggestion at 93 percent accuracy and still recommended *defer*, for
two separate reasons: no shape that makes a blocking call reaches the 400 millisecond target, and
whether the operator's live prompt text may be sent to a third-party vendor is an **open operator
decision** (``docs/analysis/2026-09-19-prompt-suggestion-latency.md``, sections 6 and 7). Until
that decision is made, the operator's prompt text is read in this process, matched against local
strings, and discarded. It is never logged, never written to a file, and never transmitted.

**Conservative by design.** The matcher claims only the high-precision case: the operator names a
command, or names the step the run record already says is next. One match suggests; no match and an
ambiguous match are both silence. A keyword table over a dozen commands cannot approach a typed
judgment's recall, and a hook that guesses is a hook the operator learns to ignore.

Properties, all by design:
  - ADVISORY: it prints at most one line of context; it never blocks and never rewrites a prompt.
  - QUIET on every error, and silent whenever the match is not clean.
  - Exit code: 0, always.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

#: A word-boundary match on the command name, with or without its leading slash. ``/plan`` and
#: "run plan" both match ``plan``; "planning" does not, and neither does "replan".
_WORD = r"(?<![\w/-])/?{name}(?![\w-])"

#: The longest run of word characters and hyphens — how a command file's stem is shaped.
_COMMAND_STEM_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def commands_root() -> Path:
    """The installed plugin's ``commands/`` directory.

    Read from ``CLAUDE_PLUGIN_ROOT`` when the harness sets it, so the suggestion names commands the
    *installed* saga actually has, and never a command a working tree has but the installed plugin
    does not. Falls back to this file's own plugin directory.
    """
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        # Commands moved under the Claude adapter. CLAUDE_PLUGIN_ROOT is the
        # package root, so the directory is one level below that root.
        return Path(root) / "com.infiquetra.claude" / "commands"
    return Path(__file__).resolve().parent.parent / "commands"


def known_commands(root: Path | None = None) -> list[str]:
    """Every command name the installed plugin carries, sorted. Empty on any failure."""
    directory = commands_root() if root is None else Path(root)
    try:
        entries = sorted(directory.glob("*.md"))
    except Exception:  # noqa: BLE001
        return []
    return sorted({e.stem for e in entries if _COMMAND_STEM_RE.match(e.stem)})


def _mentions(text: str, name: str) -> bool:
    return re.search(_WORD.format(name=re.escape(name)), text, re.IGNORECASE) is not None


def suggest(text: str, commands: list[str], next_step: str = "") -> str | None:
    """The one command *text* is about, or ``None``.

    Two sources, in order. First the operator's own words: exactly one known command named in the
    text wins, and two or more is ambiguity, which is silence. Then, when the text names none, the
    run record's ``next_step`` — but only when the text looks like a request to get on with it,
    because a prompt about something else entirely should not be answered with the run's next step.
    """
    if not text or not text.strip() or not commands:
        return None
    named = [name for name in commands if _mentions(text, name)]
    if len(named) == 1:
        return named[0]
    if named:
        return None  # two or more: ambiguous, so silent
    step = (next_step or "").strip()
    if not step:
        return None
    if not _CONTINUATION_RE.search(text):
        return None
    return command_in_step(step, commands)


def command_in_step(step: str, commands: list[str]) -> str | None:
    """The one command a recorded ``next_step`` names, or ``None``.

    **The slash form is read first, and it has to be.** A recorded step is ordinarily written like
    "run /work on the plan", which names `/work` as the command and `plan` only as part of the
    noun "the plan". Matching bare words over the whole sentence finds both and calls it ambiguous,
    which would make the record's own next step unusable in almost every real case. So: exactly one
    distinct slash-prefixed command wins; failing that, exactly one bare-word command wins; two of
    either is ambiguity, which is silence.
    """
    slashed = {name for name in commands if re.search(rf"/{re.escape(name)}(?![\w-])", step)}
    if len(slashed) == 1:
        return next(iter(slashed))
    if slashed:
        return None
    bare = [name for name in commands if _mentions(step, name)]
    return bare[0] if len(bare) == 1 else None


#: What "get on with the run" looks like in an operator's words. Deliberately short: a wider
#: pattern would answer unrelated prompts with the run's next step, which is the noise this hook
#: is built to avoid.
_CONTINUATION_RE = re.compile(
    r"\b(next step|what(?:'s| is) next|carry on|continue|keep going|pick(?: this)? up"
    r"|where (?:were|was) (?:we|i)|resume)\b",
    re.IGNORECASE,
)


def _recorded_next_step(cwd: str) -> str:
    """This repository's recorded next step, or the empty string. Never raises."""
    try:
        import next_step_context  # noqa: PLC0415  (lazy: a prompt that matches a command never pays)

        announcement = next_step_context.next_step_for(Path(cwd))
    except Exception:  # noqa: BLE001
        return ""
    return "" if announcement is None else str(announcement.get("next_step") or "")


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:  # noqa: BLE001
        sys.exit(0)
    if not isinstance(payload, dict):
        sys.exit(0)

    text = payload.get("prompt")
    if not isinstance(text, str) or not text.strip():
        sys.exit(0)

    commands = known_commands()
    if not commands:
        sys.exit(0)

    cwd = payload.get("cwd")
    next_step = _recorded_next_step(cwd) if isinstance(cwd, str) and cwd else ""

    try:
        name = suggest(text, commands, next_step)
    except Exception:  # noqa: BLE001
        sys.exit(0)

    if name is None:
        sys.exit(0)

    with contextlib.suppress(Exception):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": (
                            f"[saga] `/{name}` is the command for this. "
                            "This is a suggestion, not an instruction — ignore it when it is wrong."
                        ),
                    }
                }
            )
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
