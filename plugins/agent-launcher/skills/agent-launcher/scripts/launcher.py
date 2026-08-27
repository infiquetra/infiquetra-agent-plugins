#!/usr/bin/env python3
"""Shared single-session launch contract.

Create a coding-agent session through the installed ``agents`` wrapper, verify it
through Herdr, deliver a prompt, and close only a session this process opened.
Orchestrate consumes this module; an ordinary session uses the same file as a
CLI. This is an extraction of the launch seam, not a second implementation.

After creation, every interaction goes through Herdr. This module does not
duplicate the canonical ``herdr`` skill.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TASK_DIR = Path(".orchestrate/tasks")

# Status strings written by launch / account verification. Orchestrate's run-ledger
# uses the same values; ingest into orchestrate.py overwrites with identical literals.
RUNNING = "running"
PROMPT_UNDELIVERED = "prompt_undelivered"
ACCOUNT_MISMATCH = "account_mismatch"


def assert_safe_path_component(value: str, label: str) -> None:
    """Refuse a value that is not one safe path component.

    Unchecked, a name is a write anywhere on disk: ``TASK_DIR / f"{name}.md"`` follows
    ``..`` and an absolute right-hand operand discards the left. Mirrors orchestrate's
    contract of the same name.
    """
    if not value:
        raise SystemExit(f"{label} must not be empty")
    if Path(value).is_absolute():
        raise SystemExit(f"{label} {value!r} must not be an absolute path")
    if "/" in value or "\\" in value:
        raise SystemExit(f"{label} {value!r} must not contain a path separator")
    if value in (".", ".."):
        raise SystemExit(f"{label} {value!r} is a path traversal")


def wrapper_reused(value: Any) -> bool:
    """Whether the wrapper said the *workspace* already existed.

    This is not tab ownership. The wrapper sets it when it joins the current
    Herdr workspace, which is the common case. Tab ownership is derived
    launcher-side by ``list_tab_ids`` / ``tab_was_created``.
    """
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower() in {"true", "1", "yes"}


def list_tab_ids(workspace_id: str | None = None) -> frozenset[str] | None:
    """Tab ids in a Herdr workspace, or None if the list cannot be read."""
    ws = workspace_id or current_herdr_workspace_id()
    if not ws:
        return None
    proc = run(["herdr", "tab", "list", "--workspace", ws], check=False, timeout=20)
    if proc.returncode != 0:
        return None
    try:
        tabs = json.loads(proc.stdout)["result"]["tabs"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(tabs, list):
        return None
    ids = {str(tab["tab_id"]) for tab in tabs if isinstance(tab, dict) and tab.get("tab_id")}
    return frozenset(ids)


def tab_was_created(tab_id: str | None, preexisting: frozenset[str] | None) -> bool:
    """True only when the receipt tab was absent from the pre-launch snapshot."""
    if not tab_id or preexisting is None:
        return False
    return tab_id not in preexisting


def session_owned(unit: Any, receipt: dict[str, Any] | None = None) -> bool:
    """Whether the launcher proved it created this tab."""
    proof = receipt if receipt is not None else getattr(unit, "launch_receipt", {}) or {}
    if isinstance(proof, dict) and "owned" in proof:
        return proof.get("owned") is True
    return getattr(unit, "owned", False) is True


def record_wrapper_identity(
    unit: Any,
    info: dict[str, Any],
    *,
    preexisting: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Persist the wrapper receipt before any later step can fail."""
    unit.tab_id = info.get("tab_id")
    unit.agent_name = info.get("agent_name", unit.name)
    unit.pane_id = info.get("pane_id")
    reused = wrapper_reused(info.get("reused"))
    unit.reused = reused
    owned = tab_was_created(unit.tab_id, preexisting)
    unit.owned = owned
    receipt: dict[str, Any] = {
        "unit_name": unit.name,
        "vendor": unit.vendor,
        "tab_id": unit.tab_id,
        "pane": unit.pane_id,
        "agent_name": unit.agent_name,
        "reused": reused,
        "owned": owned,
        "permission": getattr(unit, "permission", None),
        "verified": False,
        "prompt_delivered": None,
    }
    unit.launch_receipt = receipt
    return receipt


def normalize_task(
    vendor: str, task: str, backend: str = "inline", *, review_elsewhere: bool = False
) -> str:
    """Identity default. Orchestrate replaces this with saga-command rewriting."""
    return task


# How each agent takes a model and a reasoning effort on its own command line, read from each
# tool's own `--help`. Anything not listed launches with no tier flags -- see SETUP_HINT for how a
# unit still sets its tier in that case.
#
# Verify with `roster --probe` after an agent updates. This table went stale once: claude and agy
# both grew an --effort flag, muse arrived with one, and opencode's -m turned out to belong to its
# `run` subcommand rather than the interactive session orchestrate launches. Every one of those was
# silent -- the tier was simply not applied.
VENDOR_FLAGS: dict[str, dict[str, str]] = {
    "claude": {"model": "--model {value}", "effort": "--effort {value}"},
    "codex": {"model": "--model {value}", "effort": "-c model_reasoning_effort={value}"},
    "grok": {"model": "-m {value}", "effort": "--reasoning-effort {value}"},
    "muse": {"model": "--model {value}", "effort": "--reasoning-effort {value}"},
    "agy": {"model": "--model {value}", "effort": "--effort {value}"},
    "qwen": {"model": "-m {value}"},
    # opencode wants the model as `provider/model`, e.g. `deepseek/deepseek-v4-pro`; a bare name is
    # rejected at startup with "Invalid model format".
    "opencode": {"model": "-m {value}"},
}

# Where a tool has no launch flag for something, the session is told after it starts. Every agent
# here takes slash commands, so tier is always settable -- through the command line where one
# exists, and through the session where one does not.
# What is worth knowing about a vendor that no other table has room for.
#
# Every one of these was learned by a run going wrong, and each was re-learned at least once because
# it lived nowhere. `roster` prints them, so the interview reads how a vendor behaves rather than
# recalling it -- which is the failure this is for: an orchestrator that guesses, plausibly, and is
# only found out a phase later.
VENDOR_NOTES: dict[str, str] = {
    "qwen": (
        "never reports interactive readiness, so its task is typed into the pane rather than "
        "prompted, and a task over the typing limit is handed over as a file. `--yolo` is real and "
        "absent from `--help`. NEVER pass `--safe-mode`: it reads like the opposite of `--yolo` and "
        "disables every customization, including the extensions saga loads."
    ),
    "muse": (
        "approval and the sandbox are ON by default. `--yolo` disables BOTH and is bypass, not "
        "auto; the ladder is `--approval-mode untrusted|on-request|never`."
    ),
    "opencode": (
        "effort is a variant -- Default, minimal, low, medium, high, xhigh, max -- chosen "
        "through `/variants`. Orchestrate drives the interactive picker post-launch inside the "
        "Herdr session, resolves exact or maximum available variants from the live picker choices, "
        "verifies the effective model and variant before task submission, and records the verified "
        "state. Its model wants `provider/model`; a bare name is rejected at startup."
    ),
    "agy": (
        "its saga plugin is a symlink into the operator's own checkout under the Gemini config "
        "directory, not a fetched cache -- so a search for directories named `saga` finds only the "
        "saga state and concludes it has none."
    ),
    "codex": "saga ships as skills under the `saga` namespace with no command directory, and "
    "prefixes with `$` rather than `/`.",
}

SETUP_HINT = "no {what} flag on the command line; set it with a slash command in `setup`"

# Vendors that can be asked which models they have. The rest cannot answer, so their model name
# comes from the operator rather than from anyone's recollection.
MODEL_LIST: dict[str, list[str]] = {
    "grok": ["models"],
    "agy": ["models"],
    "opencode": ["models"],
}

# What each vendor needs in order to actually do work in the worktree it was handed.
#
# Without this, every unit runs at its vendor's default -- read-only, or ask-first in a tab nobody
# is watching. Two competing plans were once produced at xhigh over twelve minutes and both were
# lost, because neither session could save a file: codex answered "I can't write", claude sat in
# plan mode. A worktree a unit cannot write to is not isolation, it is theatre.
#
# Two levels. ``auto`` is the default and means "get on with the task without asking" -- claude and
# grok share that exact vocabulary. ``bypass`` is the operator's everyday mode, granted per unit
# when the work needs it. Either way the worktree is the blast radius: a unit reaches its own tree
# and nothing else. A vendor with an empty list already behaves that way unflagged.
# Which flags in ``VENDOR_PERMISSION`` take a value. Anything not named here must stand alone.
#
# This exists because a value-less switch followed by a bare permission word does not fail: the word
# lands in the vendor's positional PROMPT slot. `grok --always-approve auto` sent every unit the word
# `auto` as its first prompt and its real task only afterwards, and nothing reported it. The rule the
# table must obey is structural -- a bare enum is only ever a value -- so it is stated here and
# enforced by tests rather than left to whoever edits the table next.
PERMISSION_FLAGS_TAKING_A_VALUE = frozenset({"--permission-mode", "--sandbox", "--approval-mode"})

VENDOR_PERMISSION: dict[str, dict[str, list[str]]] = {
    "claude": {
        "auto": ["--permission-mode", "auto"],
        "bypass": ["--permission-mode", "bypassPermissions"],
    },
    # `--always-approve` is a value-less switch and grok's usage is `grok [OPTIONS] [PROMPT]`, so
    # `--always-approve auto` put the bare word `auto` in the PROMPT position: every grok unit spent
    # its first turn on a permission enum and only got its real task afterwards. Verified against
    # grok 1.0.5, whose `--permission-mode <MODE>` accepts both of these values.
    "grok": {
        "auto": ["--permission-mode", "auto"],
        "bypass": ["--permission-mode", "bypassPermissions"],
    },
    "codex": {
        "auto": ["--sandbox", "workspace-write"],
        "bypass": ["--dangerously-bypass-approvals-and-sandbox"],
    },
    "agy": {"auto": [], "bypass": ["--dangerously-skip-permissions"]},
    # opencode has one switch and no ladder, so both modes are the same flag. Recorded as it is
    # rather than papered over: asking for `auto` here genuinely gets you `bypass`.
    "opencode": {"auto": ["--auto"], "bypass": ["--auto"]},
    # muse's own help: approval and the sandbox are ON by default, `--approval-mode` takes
    # untrusted|on-request|never, and `--yolo` means "disable approval and sandboxing and trust
    # this workspace". Both modes were once `--yolo`, so asking for the constrained mode handed the
    # unit full bypass -- a safety claim backwards. `never` is the honest `auto`: it stops asking
    # without dropping the sandbox.
    "muse": {"auto": ["--approval-mode", "never"], "bypass": ["--yolo"]},
    # `--yolo` is absent from `qwen --help` and works anyway -- verified by running it, against a
    # control showing qwen rejects an unknown flag with "Unknown arguments". Its own warning names
    # the equivalent: "running headless with --yolo / approval-mode=yolo and no sandbox".
    #
    # Do NOT reach for `--safe-mode` here. It reads like the opposite of `--yolo` and is not a
    # permission flag at all: it disables all customizations -- context files, hooks, extensions --
    # which is exactly what saga needs loaded.
    "qwen": {"auto": [], "bypass": ["--yolo"]},
}


class AccountMismatchError(SystemExit):
    """A worker launched under an account that does not match the requested plan account."""


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command. Pass ``timeout`` for anything that asks a vendor a question.

    A vendor's own subcommand can reach the network and hang; without a bound that becomes an
    interview frozen on a question the operator cannot see, which is the failure this plugin keeps
    having to fix. A timeout is reported as a non-zero result, so callers handle it as "no answer"
    rather than as a crash.

    ``check=False`` means every failure comes back as a result, and a command that is not installed
    is a failure like any other. It was not, once: ``subprocess.run`` raises rather than returning
    when the program does not exist, so a machine without herdr got a traceback out of a read-only
    command that had already decided herdr was optional.
    """
    try:
        proc = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        if check:
            raise SystemExit(f"timed out after {timeout}s: {' '.join(cmd)}") from None
        return subprocess.CompletedProcess(cmd, returncode=124, stdout="", stderr="timed out")
    except OSError as exc:
        if check:
            raise SystemExit(f"cannot run {cmd[0]!r}: {exc}") from None
        # 127 is the shell's own "command not found", so a caller reading returncode sees the
        # ordinary shape of a failure rather than a special case.
        return subprocess.CompletedProcess(cmd, returncode=127, stdout="", stderr=str(exc))
    if check and proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{err}")
    return proc


def launcher() -> str:
    """The local wrapper that creates an agent session.

    Called ``agents`` rather than ``agent`` because ``agent`` was taken over by another tool on this
    machine. That is why this is resolved instead of hardcoded: a stale name does not fail cleanly,
    it launches somebody else's binary with flags it has never heard of. Checking first turns a
    confusing wrong-program run into one clear sentence.
    """
    name = os.environ.get("ORCHESTRATE_AGENT_LAUNCHER", "agents")
    if not shutil.which(name):
        raise SystemExit(
            f"no {name!r} on PATH -- that is the wrapper that creates agent sessions. "
            f"If it is called something else here, set ORCHESTRATE_AGENT_LAUNCHER."
        )
    return name


def launchable() -> list[str]:
    """Everything the wrapper says it can launch on this machine, asked every time.

    The ``Tools:`` section of the wrapper's own help. Two things this is deliberately not:

    - **Not ``--crews``.** A crew is the operator's saved workspace layout and has nothing to do with
      orchestration. Offering it drops available agents silently, which is the quiet kind of wrong
      answer worth spending code on rather than instructions.
    - **Not a ``PATH`` check.** Several entries are modes of one wrapper rather than binaries of
      their own, so looking for a file by that name reports them missing when they work fine. The
      wrapper is the authority on what the wrapper can launch.
    """
    out = run([launcher(), "--help"], check=False, timeout=20).stdout
    names: list[str] = []
    in_tools = False
    for line in out.splitlines():
        if line.startswith("Tools:"):
            in_tools = True
            continue
        if in_tools:
            if not line.strip():
                break
            # a tool line is "  name   description"; continuation lines are indented further
            if re.match(r"^ {2}\S", line):
                names.append(line.split()[0])
    return names


def roster() -> list[tuple[str, str]]:
    """The vendors this run may use: ones orchestrate knows how to drive, that are available here.

    Both halves matter. ``VENDOR_FLAGS`` is what this plugin understands well enough to hand a model
    and an effort to; the wrapper's tool list is what this particular machine can actually start.
    Offering anything outside the intersection is a promise orchestrate cannot keep -- a Hermes
    profile or a provider variant is launchable but is not a vendor this plugin knows how to tier,
    and a vendor it knows is useless on a machine that does not have it.

    Returns ``(name, flags)``, where ``flags`` says what tier control the command line gives.
    """
    here = set(launchable())
    return [(n, ",".join(f) or "none") for n, f in VENDOR_FLAGS.items() if n in here]


FAVOURITES_PATH = Path("~/.config/orchestrate/models.json").expanduser()


def favourites(vendor: str) -> list[str]:
    """The models the operator actually uses for this vendor, in their order of preference.

    Asking a vendor what it has is a fact; deciding which of them matters is a preference, and a
    preference belongs in a file the operator owns rather than in anyone's guess. opencode fronts
    164 models across eight providers, so offering four of them is noise -- three rounds running,
    the suggestions were wrong.

    Absent or unreadable, this returns nothing and the interview falls back to asking. It is a
    convenience, never a constraint: a model not listed here is still perfectly usable.
    """
    try:
        raw = json.loads(FAVOURITES_PATH.read_text())
    except (OSError, ValueError):
        return []
    got = raw.get(vendor, [])
    return [str(m) for m in got] if isinstance(got, list) else []


def models(name: str) -> list[str]:
    """Ask one vendor which models it actually has.

    Model names are the last thing in this plugin still taken from memory, and memory is exactly
    what got the crew list and the flag table wrong. A recalled name that has since been renamed
    does not fail politely -- the session starts on some default tier and nobody is told.

    Only three vendors can answer today. The rest return nothing, and the operator supplies the
    name -- which is honest, and better than inventing one.
    """
    sub = MODEL_LIST.get(name)
    if not sub:
        return []
    # generous: a cold vendor can take most of a minute to answer, and an inconsistent
    # answer run-to-run is worse than a slow one for a command the operator invoked
    got = run([name, *sub], check=False, timeout=60)
    if got.returncode != 0:
        return []
    return [ln.strip() for ln in got.stdout.splitlines() if ln.strip()]


def workspace_for(unit: Any, default: str | None = None) -> str | None:
    """The workspace name this unit launches into.

    The unit's own field wins; otherwise the run default. Absent both, the wrapper inherits
    the caller's workspace -- today's behaviour. No other precedence.
    """
    return unit.workspace or default


def is_company_account(account: str | None) -> bool:
    """Whether an account selection specifies the company account."""
    if not account:
        return False
    return account.lower() in ("company", "company-account", "--company-account")


def is_personal_account(account: str | None) -> bool:
    """Whether an account selection specifies the personal account."""
    if not account:
        return False
    return account.lower() in ("personal", "personal-account", "--personal-account")


def account_for(unit: Any, default: str | None = None) -> str | None:
    """The account this unit launches under.

    The unit's own field wins; otherwise the run default. Absent both, no account flag is
    emitted -- inheriting the environment default.
    """
    return unit.account or default


def agent_argv(
    unit: Any,
    default_workspace: str | None = None,
    default_account: str | None = None,
) -> list[str]:
    argv = [
        launcher(),
        "--no-focus",
        "--current",
        "--herdr",
        "--herdr-control-only",
        "--task",
        unit.name,
        "--cwd",
        unit.worktree or ".",
    ]
    workspace = workspace_for(unit, default_workspace)
    if workspace:
        argv.extend(["--workspace", workspace])
    argv.append(unit.vendor)
    modes = VENDOR_PERMISSION.get(unit.vendor, {})
    argv.extend(modes.get(unit.permission, modes.get("auto", [])))
    flags = VENDOR_FLAGS.get(unit.vendor, {})
    for key, value in (("model", unit.model), ("effort", unit.effort)):
        template = flags.get(key)
        if value and template:
            argv.extend(template.format(value=value).split(" "))
    effective_account = account_for(unit, default_account)
    if (
        unit.vendor == "claude"
        and is_company_account(effective_account)
        and "--company-account" not in unit.launch_args
    ):
        argv.append("--company-account")
    # Last, and verbatim. Arguments after the vendor token reach the vendor, except for the
    # few the wrapper intercepts from that position. A launcher flag that must precede the
    # vendor token cannot be expressed here -- see ``workspace``.
    argv.extend(unit.launch_args)
    return argv


# How long to give a new session to become able to read a prompt, and how long to give it after
# being sent to show that it took one.
#
# The wrapper returns when the tab exists, which is earlier than the agent being able to read
# anything, and sending into that gap does not fail: `herdr agent prompt` reports success, the agent
# finishes booting, and the prompt is gone. Observed three times across two vendors on one live run,
# always the same tell -- a unit idle immediately after launch, having consumed nothing. That idle
# used to be recorded as RUNNING, which `settle` then read as done and only `land` noticed, a phase
# later, that it had committed nothing. A send whose acceptance is never observed is now recorded
# as PROMPT_UNDELIVERED instead, which no phase reads as work.
LAUNCH_SETTLE_SECONDS = 30.0
DELIVERY_CHECK_SECONDS = 15.0
DELIVERY_RESENDS = 2

# How long to give a new session to say which account it is on. A session that is interactive has
# painted its statusline, so this is a short grace for the paint rather than a wait for the tool:
# the other answer, a transcript under one of the two roots, does not arrive until the first prompt
# does, which is after this check.
ACCOUNT_SETTLE_SECONDS = 10.0
DELIVERY_WARNING = (
    "SENT BUT NEVER STARTED: idle after being given its task. Check the tab before "
    "trusting this unit -- it may have been prompted while still booting."
)


def append_unit_note(unit: Any, note: str) -> None:
    """Add one fact without erasing a note recorded by an earlier delivery step."""
    unit.note = f"{unit.note}; {note}" if unit.note else note


def has_delivery_warning(unit: Any) -> bool:
    """Whether the unit still carries the exact warning written by ``launch``."""
    return DELIVERY_WARNING in unit.note.split("; ")


def clear_delivery_warning(unit: Any) -> None:
    """Remove only the delivery warning, preserving every other semicolon-delimited note."""
    unit.note = "; ".join(note for note in unit.note.split("; ") if note != DELIVERY_WARNING)


def agent_row(unit: Any, agents: list[dict] | None = None) -> dict | None:
    """This unit's row in herdr's agent list, matched on the pane it was given."""
    for a in live_agents() if agents is None else agents:
        if unit.pane_id and a.get("pane_id") == unit.pane_id:
            return a
    return None


def await_ready(unit: Any, seconds: float = LAUNCH_SETTLE_SECONDS) -> bool:
    """Wait until this session will actually take a prompt. True if it said so.

    Some agents never report readiness at all -- qwen is one, and it is why `say` has a pane
    fallback. There is nothing to wait for there, so the window is spent and the send goes ahead,
    which is still later than sending the instant the tab appears.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        row = agent_row(unit)
        if row is not None and row.get("interactive_ready"):
            return True
        time.sleep(1.0)
    return False


def took_the_task(unit: Any, seconds: float = DELIVERY_CHECK_SECONDS) -> bool:
    """Did the session actually take the task? One that did stops being idle.

    Not a guarantee -- an agent that answers instantly is idle again quickly. It is a check on the
    failure that has actually happened, which is a session that never started at all.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        row = agent_row(unit)
        if row is not None and row.get("agent_status") not in (None, "idle", "done", "unknown"):
            return True
        time.sleep(1.0)
    return False


OPENCODE_VARIANT_RANKS: dict[str, int] = {
    "default": 0,
    "minimal": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "xhigh": 5,
    "max": 6,
    "maximum": 6,
}
OPENCODE_MAX_VARIANTS = {"max", "maximum", "maximum available", "max available", "highest"}


def strip_ansi(text: str) -> str:
    """Terminal output with its colour and cursor escapes removed."""
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def parse_opencode_variants(text: str) -> list[str]:
    """Extract variant choices presented in OpenCode's interactive /variants picker.

    Handles ANSI escape codes, menu formatting (> Option, 1. Option, * Option), and token lists.
    """
    clean = strip_ansi(text)
    options: list[str] = []
    ignored = {"select", "choose", "variant", "variants", "options", "option", "model", "effort"}
    for line in clean.splitlines():
        line = line.strip()
        if not line:
            continue
        # Menu lines: > Option, - Option, * Option, 1. Option, 1) Option, [ ] Option
        m = re.match(r"^(?:[>*\-•#]\s*|\d+[\.\)]\s*|\[[\s*xX]?\]\s*)([A-Za-z0-9_\-]+)", line)
        if m:
            token = m.group(1).strip()
            if (
                token
                and token.lower() not in ignored
                and not any(token.lower() == o.lower() for o in options)
            ):
                options.append(token)
            continue
        # Token matches for common variant names
        for word in re.findall(
            r"\b(?:Default|minimal|low|medium|high|xhigh|max|maximum)\b", line, re.IGNORECASE
        ):
            if not any(word.lower() == o.lower() for o in options):
                options.append(word)
    return options


def resolve_opencode_variant(requested: str | None, available_options: Sequence[str]) -> str:
    """Select the requested exact variant or highest actually offered variant."""
    if not available_options:
        raise SystemExit("no variant choices presented in OpenCode live picker")

    if requested is None or requested.strip().lower() in OPENCODE_MAX_VARIANTS:
        # Highest actually offered variant from presented choices
        return max(
            available_options,
            key=lambda opt: (
                OPENCODE_VARIANT_RANKS.get(opt.lower(), 0),
                available_options.index(opt),
            ),
        )

    req_clean = requested.strip().lower()
    for opt in available_options:
        if opt.strip().lower() == req_clean:
            return opt

    raise SystemExit(
        f"requested variant {requested!r} is not available in live picker options: {list(available_options)}"
    )


def read_pane(pane_id: str, lines: int = 120) -> str:
    """This pane's recent output, falling back to what is on screen when there is no scrollback."""
    proc = run(
        ["herdr", "pane", "read", pane_id, "--source", "recent-unwrapped", "--lines", str(lines)],
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout
    proc = run(["herdr", "pane", "read", pane_id, "--source", "visible"], check=False)
    return proc.stdout if proc.returncode == 0 else ""


def confirm_opencode_variant_selected(unit: Any, pane_id: str, selected: str) -> None:
    """Read the pane back and require the chosen variant to be reflected in it.

    Typing a label into a picker is a request, not an outcome. A picker that closed on the value it
    already held leaves the session at a variant nobody asked for, and submitting work into it is
    exactly the silent substitution this unit's stop conditions forbid. The echo the interface
    leaves behind is the only evidence of the selection available from outside it, so a selection
    that cannot be found there is a loud stop rather than an assumption.
    """
    clean = strip_ansi(read_pane(pane_id, lines=40))
    if not re.search(rf"\b{re.escape(selected)}\b", clean, re.IGNORECASE):
        raise SystemExit(
            f"{unit.name}: variant {selected!r} was sent to the picker but the session does not "
            "report it; refusing to submit the task at an unverified variant"
        )


def drive_opencode_variant_selection(
    unit: Any, pane_id: str, *, timeout: float = 10.0
) -> tuple[str, bool]:
    """Drive OpenCode's `/variants` picker in Herdr and verify the selection took.

    Returns the variant now in force and whether the session reported itself ready afterwards.

    A pane holds the session's whole recent output, not only its picker, so a parse that finds
    nothing the variant ladder recognises is read as "the picker has not drawn yet" and polled
    again rather than taken as the option list. Accepting a boot banner as the choices either
    refuses a perfectly available exact variant or types one of the banner's own words into the
    session; only once the window closes is an unrecognised set accepted, and an empty one stops.
    """
    # Open the picker
    run(["herdr", "pane", "run", pane_id, "/variants"])

    # Read the live picker options from the pane
    deadline = time.monotonic() + timeout
    available_options: list[str] = []
    while time.monotonic() < deadline:
        parsed = parse_opencode_variants(read_pane(pane_id))
        if parsed:
            available_options = parsed
            if any(option.lower() in OPENCODE_VARIANT_RANKS for option in parsed):
                break
        time.sleep(0.5)

    if not available_options:
        raise SystemExit(f"{unit.name}: unable to read live picker options from OpenCode /variants")

    # Select requested exact variant or highest offered
    requested = unit.variant or unit.effort
    selected = resolve_opencode_variant(requested, available_options)

    # Send selected variant into the pane
    run(["herdr", "pane", "run", pane_id, selected])

    # Wait until session returns to task-ready, then confirm the picker actually moved
    ready = await_ready(unit)
    confirm_opencode_variant_selected(unit, pane_id, selected)

    unit.variant = selected
    append_unit_note(unit, f"variant {selected} verified")
    return selected, ready


def close_run_session(unit: Any) -> None:
    """Close only the tab this launch created, leaving every other session alone."""
    if not session_owned(unit):
        return
    if unit.tab_id:
        run(["herdr", "tab", "close", unit.tab_id], check=False)


def same_directory(reported: str, expected: str) -> bool:
    """Whether two paths name the same directory, deciding on the literal strings if they cannot.

    ``resolve`` reads the filesystem and can fail on a path that has since gone. A comparison that
    could not be made must not read as a match, so an unusable path falls back to the strings
    rather than the check being skipped.
    """
    try:
        return Path(reported).resolve() == Path(expected).resolve()
    except OSError:
        return reported == expected


def workspace_id_for_name(name: str | None) -> str | None:
    """The id herdr gave the workspace with this label, or None when no workspace carries it.

    The wrapper's ``--workspace`` takes a name and ``herdr agent list`` reports only a
    ``workspace_id``, so the two are joined through the workspace list rather than compared
    directly -- a name held against an id never matches, which reads as a mismatch that is not one.
    """
    if not name:
        return None
    proc = run(["herdr", "workspace", "list"], check=False)
    try:
        workspaces = json.loads(proc.stdout)["result"]["workspaces"]
    except (ValueError, KeyError, TypeError):
        return None
    for workspace in workspaces:
        if isinstance(workspace, dict) and workspace.get("label") == name:
            found = workspace.get("workspace_id")
            return str(found) if found else None
    return None


def claude_transcript_roots() -> tuple[Path, Path]:
    """The personal and company Claude transcript root directories."""
    personal = Path(
        os.environ.get("CLAUDE_PERSONAL_PROJECTS", Path.home() / ".claude" / "projects")
    )
    company = Path(
        os.environ.get("CLAUDE_COMPANY_PROJECTS", Path.home() / ".claude-company" / "projects")
    )
    return personal, company


def claude_project_slug(worktree: str | Path) -> str:
    """The project directory slug Claude generates for a given worktree path.

    Every separator and dot becomes a dash: ``/Users/jefcox/.claude`` is stored as
    ``-Users-jefcox--claude``, which is where the dot belongs in this class -- a worktree whose
    name carries one would otherwise be looked for under a directory that does not exist.
    """
    resolved = Path(worktree).resolve().as_posix()
    return re.sub(r"[/\\:.]", "-", resolved)


def find_claude_transcripts(root: Path, worktree: str | None) -> list[Path]:
    """Find transcript files (.jsonl) for a given worktree under a Claude projects root."""
    if not root.is_dir() or not worktree:
        return []
    slug = claude_project_slug(worktree)
    proj_dir = root / slug
    if proj_dir.is_dir():
        return list(proj_dir.glob("*.jsonl"))
    leaf = Path(worktree).name
    matches = list(root.glob(f"*{leaf}*/*.jsonl"))
    return matches


def transcript_account(unit: Any) -> str | None:
    """Which account's transcript root holds this worker's session, when either one does.

    Both roots can hold a transcript for the same worktree -- a relaunch after a wrong-account
    launch leaves the earlier one in place -- so the newer file decides. Returns ``None`` while
    neither root has one, which is the ordinary state at preflight: Claude writes
    ``projects/<slug>/<id>.jsonl`` when the first prompt arrives, and preflight runs before the
    task is sent.
    """
    personal_root, company_root = claude_transcript_roots()
    newest: list[tuple[float, str]] = []
    for label, root in (("personal", personal_root), ("company", company_root)):
        files = find_claude_transcripts(root, unit.worktree)
        if files:
            newest.append((max(f.stat().st_mtime for f in files), label))
    if not newest:
        return None
    return max(newest)[1]


def pane_account_label(pane_id: str | None) -> str | None:
    """The account this session's own statusline reports, or None while it does not say.

    The wrapper exports ``CLAUDE_ACCOUNT_LABEL`` into the pane before the tool starts and the
    statusline renders it beside the user -- ``jefcox [company]:`` against a plain ``jefcox:`` on
    the personal account. That row is on screen as soon as the session is interactive, which is
    exactly where the transcript is not, so it is the evidence a launch-time check can actually
    read. Only what is on screen now is considered: scrollback carries the task text, and a task
    that happens to name the operator is not a statusline.
    """
    if not pane_id:
        return None
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if not user:
        return None
    proc = run(["herdr", "pane", "read", pane_id, "--source", "visible"], check=False)
    if proc.returncode != 0:
        return None
    text = strip_ansi(proc.stdout)
    last = None
    for match in re.finditer(rf"\b{re.escape(user)}\s*(?:\[(\w+)\])?:", text):
        last = match
    if last is None:
        return None
    return (last.group(1) or "personal").lower()


def observed_account(unit: Any, pane_id: str | None, seconds: float) -> str | None:
    """The account the launched session is actually on, waiting briefly for it to say.

    The statusline answers first because it is painted at startup; the transcript root answers
    for a session whose statusline this machine does not print. Neither is instant, so the window
    is spent before the question is given up on.
    """
    deadline = time.monotonic() + seconds
    while True:
        from_pane = pane_account_label(pane_id)
        if from_pane:
            return from_pane
        from_transcript = transcript_account(unit)
        if from_transcript:
            return from_transcript
        if time.monotonic() >= deadline:
            return None
        time.sleep(1.0)


def check_unit_account(
    unit: Any, pane_id: str | None = None, seconds: float = ACCOUNT_SETTLE_SECONDS
) -> tuple[bool | None, str | None]:
    """Check whether a launched Claude unit is on the account the plan asked for.

    Returns:
        (True, None) when the session reports the requested account.
        (False, error_msg) when it reports a different one, when the plan named an account this
        script does not know, or when no account could be read at all -- an unverified account is
        a stop, not a pass, because the failure being guarded against is invisible by nature.
        (None, None) when no account was requested, or the vendor has no account to check.
    """
    if unit.vendor != "claude" or not unit.account:
        return None, None

    if is_company_account(unit.account):
        requested = "company"
    elif is_personal_account(unit.account):
        requested = "personal"
    else:
        return (
            False,
            f"unknown account selection {unit.account!r}; expected 'company' or 'personal'",
        )

    observed = observed_account(unit, pane_id, seconds)
    if observed is None:
        return (
            False,
            f"account unverified: the session reported no account in its statusline and neither "
            f"transcript root holds its session, so {requested!r} could not be confirmed",
        )
    if observed != requested:
        return (
            False,
            f"account mismatch: worker is on the {observed} account when {requested} was required",
        )
    return True, None


def verify_unit_account(unit: Any, pane_id: str | None = None) -> bool | None:
    """Verify the account for a launched unit, closing the session and raising on mismatch."""
    confirmed, error = check_unit_account(unit, pane_id)
    if error:
        close_run_session(unit)
        unit.status = ACCOUNT_MISMATCH
        append_unit_note(unit, error)
        raise AccountMismatchError(f"{unit.name}: {error}")
    return confirmed


def verify_unit_preflight(
    unit: Any, pane_id: str | None, *, ready: bool | None = None
) -> dict[str, Any]:
    """Verify the session against herdr before the task is submitted, and record what was checked.

    Only what herdr publishes can be checked. A row in ``herdr agent list`` carries ``cwd``,
    ``workspace_id`` and ``interactive_ready``; it carries no model at all, and its workspace is an
    id where the plan holds a name. So the receipt separates what was confirmed against herdr from
    what is only the request the unit was launched with. A single ``verified: true`` covering both
    would be a claim this script is not in a position to make, and a run record that says a model
    was verified when nothing could read it is worse than one that says it was not.
    """
    if not pane_id:
        raise SystemExit(f"{unit.name}: session was not assigned a valid pane_id")

    confirmed: list[str] = ["pane"]
    unconfirmed: list[str] = ["model", "permission"]  # herdr publishes neither
    row = agent_row(unit)

    if row is None:
        raise SystemExit(f"{unit.name}: herdr did not list the session; cannot verify agent kind")

    reported_kind = row.get("agent") or row.get("kind")
    if not reported_kind:
        raise SystemExit(f"{unit.name}: herdr did not report agent kind; refusing to prompt")
    if str(reported_kind).lower() != str(unit.vendor).lower():
        close_run_session(unit)
        raise SystemExit(
            f"{unit.name}: herdr reports agent {reported_kind!r}, requested {unit.vendor!r}"
        )
    confirmed.append("kind")

    reported_cwd = row.get("cwd") or row.get("foreground_cwd")
    if reported_cwd and unit.worktree:
        if not same_directory(reported_cwd, unit.worktree):
            close_run_session(unit)
            raise SystemExit(
                f"{unit.name}: working directory {reported_cwd!r} differs from unit "
                f"worktree {unit.worktree!r}"
            )
        confirmed.append("working_directory")
    else:
        unconfirmed.append("working_directory")

    expected_workspace = workspace_id_for_name(unit.workspace)
    reported_workspace = row.get("workspace_id")
    if expected_workspace and reported_workspace:
        if reported_workspace != expected_workspace:
            close_run_session(unit)
            raise SystemExit(
                f"{unit.name}: session workspace {reported_workspace!r} does not match "
                f"requested workspace {unit.workspace!r} ({expected_workspace})"
            )
        confirmed.append("workspace")
    elif unit.workspace:
        unconfirmed.append("workspace")

    observed_ready = bool(row.get("interactive_ready")) if ready is None else bool(ready)
    confirmed.append("readiness")

    # A Claude unit that names an account either confirms it or raises: an account that could not
    # be read is the failure this check exists for, wearing the same face as one that was never
    # checked. Every other vendor has no account to read, so a unit that names one anyway is
    # recorded as having asked rather than as having been confirmed.
    account_confirmed = verify_unit_account(unit, pane_id)
    if unit.account:
        if account_confirmed:
            confirmed.append("account")
        else:
            unconfirmed.append("account")

    effective_provider = (
        unit.model.split("/")[0] if (unit.model and "/" in unit.model) else unit.vendor
    )
    effective_variant = unit.variant or unit.effort
    if unit.vendor == "opencode" and not effective_variant:
        effective_variant = "Default"
    # An OpenCode variant is the one tier value that was read back out of the session holding it.
    if unit.vendor == "opencode" and unit.variant:
        confirmed.append("variant")
    else:
        unconfirmed.append("variant")

    receipt: dict[str, Any] = {
        "unit_name": unit.name,
        "vendor": unit.vendor,
        "provider": effective_provider,
        "model": unit.model,
        "variant": effective_variant,
        "account": unit.account,
        "permission": getattr(unit, "permission", None),
        "kind": str(reported_kind),
        "agent_name": getattr(unit, "agent_name", None),
        "reused": wrapper_reused(getattr(unit, "reused", False)),
        "owned": session_owned(unit),
        "working_directory": unit.worktree,
        "worktree": unit.worktree,
        "workspace": unit.workspace,
        "pane": pane_id,
        "tab_id": unit.tab_id,
        "readiness": observed_ready,
        "confirmed_against_herdr": confirmed,
        "requested_only": unconfirmed,
        # True by construction: every check that can fail raises above this point, so it reads
        # "preflight passed", and ``confirmed_against_herdr`` is what that passing actually covered.
        "verified": True,
        "prompt_delivered": (getattr(unit, "launch_receipt", {}) or {}).get("prompt_delivered"),
    }
    unit.launch_receipt = receipt
    return receipt


def launch(unit: Any, backend: str = "inline", *, review_elsewhere: bool = False) -> None:
    preexisting = list_tab_ids()
    proc = run(agent_argv(unit))
    pane_id = None
    try:
        info = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        unit.note = "launched, but the wrapper's JSON could not be read"
        raise SystemExit(
            f"{unit.name}: launched, but the wrapper's JSON could not be read"
        ) from None
    record_wrapper_identity(unit, info, preexisting=preexisting)
    pane_id = unit.pane_id
    if not pane_id:
        raise SystemExit(f"{unit.name}: launcher did not return a pane_id")

    ready = await_ready(unit)
    if unit.vendor == "opencode":
        _, ready = drive_opencode_variant_selection(unit, pane_id)
    verify_unit_preflight(unit, pane_id, ready=ready)

    send(unit, pane_id, backend, review_elsewhere=review_elsewhere)
    accepted = took_the_task(unit)
    if not accepted:
        # Resend only into a session that has still never left idle. A resend risks giving a unit
        # its task twice, and the one reading that rules that out is a session which has not
        # started anything: a swallowed prompt leaves it exactly there. Anything else -- working,
        # blocked, or gone -- means it took something, so the send stands and the loop stops.
        for _ in range(DELIVERY_RESENDS):
            row = agent_row(unit)
            if row is None or row.get("agent_status") != "idle":
                break
            send(unit, pane_id, backend, review_elsewhere=review_elsewhere)
            accepted = took_the_task(unit)
            if accepted:
                break
    if accepted:
        unit.status = RUNNING
        if isinstance(unit.launch_receipt, dict):
            unit.launch_receipt["prompt_delivered"] = True
    else:
        unit.status = PROMPT_UNDELIVERED
        append_unit_note(unit, DELIVERY_WARNING)
        if isinstance(unit.launch_receipt, dict):
            unit.launch_receipt["prompt_delivered"] = False


# How long a line may be before typing it into a pane stops delivering it as an instruction.
#
# Measured against qwen 0.21.13 through `herdr pane run`: 859 characters arrive as typed text, 1660
# arrive as `[Pasted Content N chars]`. The paste is submitted and the agent knows its size -- it
# simply does not treat it as the instruction. Its own words, verbatim, to a 6402-character task:
# "I can see you've pasted some content (6402 characters), but I'm not sure what you'd like me to do
# with it."
#
# That is the whole failure: the unit launches, the keystrokes are delivered, orchestrate records
# success, and the session sits waiting for an instruction it thinks it has not been given. It goes
# idle, `settle` marks it done, and only `land` -- a phase later -- reports that it committed
# nothing. A real task is routinely well past this, so the door this plugin uses for any vendor that
# will not take `herdr agent prompt` was quietly unusable for real work.
PANE_TYPING_LIMIT = 800


def pane_text(unit: Any, text: str) -> str:
    """The line to type, which is the task itself only when the task is short enough to survive.

    Past the limit the task goes to a file and the typed line points at it. The leading saga command
    stays typed: it is what makes the vendor load the skill, and inside a file it is just prose.
    """
    if len(text) <= PANE_TYPING_LIMIT:
        return text
    assert_safe_path_component(unit.name, "task name")
    path = (TASK_DIR / f"{unit.name}.md").resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n")
    lead = text.split(" ", 1)[0] if re.match(r"^\s*[/$]", text) else ""
    append_unit_note(unit, f"task handed over as a file, too long to type: {path}")
    return (
        f"{lead} Your full task is in {path} -- read that file in full and carry it out exactly. "
        "It is the complete instruction; nothing else is coming."
    ).strip()


def say(unit: Any, pane_id: str | None, text: str) -> None:
    """Put one line into the session.

    ``herdr agent prompt`` is the right door, but it refuses any agent that never reports
    ``interactive_ready`` -- qwen is one today. For those, type into the pane instead, which is what
    the operator would do by hand -- but only up to the length a pane will still carry as an
    instruction rather than as an attachment. See ``pane_text``.
    """
    handle = unit.agent_name or unit.name
    attempt = run(["herdr", "agent", "prompt", handle, text], check=False)
    if attempt.returncode == 0:
        return
    if not pane_id:
        raise SystemExit(f"{unit.name}: agent prompt refused and no pane to fall back to")
    typed = pane_text(unit, text)
    run(["herdr", "pane", "run", pane_id, typed])
    fallback_note = "prompted through its pane; this agent does not report interactive readiness"
    if fallback_note not in unit.note.split("; "):
        append_unit_note(unit, fallback_note)


def send(
    unit: Any, pane_id: str | None, backend: str = "inline", *, review_elsewhere: bool = False
) -> None:
    """Set the session up, then give it its task.

    Setup goes first and separately: a tier has to be in force before the work starts, and a slash
    command bundled into the same message as the task is just text the agent reads.
    """
    for line in unit.setup:
        say(unit, pane_id, line)
    say(
        unit,
        pane_id,
        normalize_task(unit.vendor, unit.task, backend, review_elsewhere=review_elsewhere),
    )


def live_agents(*, timeout: float = 20) -> list[dict[str, Any]]:
    """The sessions herdr is tracking right now.

    herdr is the truth a run file only mirrors, so it is asked, never remembered. A missing or
    failing herdr is not an error here: it means there is nothing to match a worktree or a session
    against, and the caller degrades -- to "no live agent" when adopting, to "gone" when polling.
    """
    proc = run(["herdr", "agent", "list"], check=False, timeout=timeout)
    try:
        agents = json.loads(proc.stdout)["result"]["agents"]
    except (ValueError, KeyError):
        return []
    return [a for a in agents if isinstance(a, dict)]


@dataclass
class LaunchRequest:
    """Launch fields an ordinary session can construct without Orchestrate's Unit."""

    name: str
    vendor: str
    task: str = ""
    model: str | None = None
    effort: str | None = None
    account: str | None = None
    permission: str = "auto"
    setup: list[str] = field(default_factory=list)
    launch_args: list[str] = field(default_factory=list)
    workspace: str | None = None
    worktree: str | None = None
    tab_id: str | None = None
    pane_id: str | None = None
    agent_name: str | None = None
    status: str = "pending"
    note: str = ""
    variant: str | None = None
    reused: bool = False
    owned: bool = False
    launch_receipt: dict[str, Any] = field(default_factory=dict)


def preview_argv(
    unit: Any,
    default_workspace: str | None = None,
    default_account: str | None = None,
) -> list[str]:
    """The launch argv with ``--dry-run`` in the launcher-flag position."""
    argv = agent_argv(unit, default_workspace, default_account)
    return [argv[0], "--dry-run", *argv[1:]]


def parse_dry_run(stdout: str) -> dict[str, str]:
    """Parse the wrapper's ``key=value`` dry-run preview into a dict."""
    parsed: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        parsed[key.strip()] = value.strip()
    return parsed


def current_herdr_workspace_id() -> str | None:
    """The calling pane's workspace id from ``herdr pane current --current``."""
    proc = run(["herdr", "pane", "current", "--current"], check=False, timeout=20)
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout)
        workspace_id = payload["result"]["pane"]["workspace_id"]
    except (ValueError, KeyError, TypeError):
        return None
    return str(workspace_id) if workspace_id else None


def confirm_preview(preview: dict[str, str], cwd: str, workspace_id: str | None) -> None:
    """Stop before launch when the dry-run does not resolve cwd and workspace."""
    reported_cwd = preview.get("cwd", "")
    if not reported_cwd or not same_directory(reported_cwd, cwd):
        raise SystemExit(
            f"dry-run cwd {reported_cwd!r} does not resolve to requested {cwd!r}; not launching"
        )
    herdr_workspace = preview.get("herdr_workspace", "")
    if not herdr_workspace:
        raise SystemExit("dry-run did not resolve herdr_workspace; not launching")
    if workspace_id and workspace_id not in herdr_workspace:
        raise SystemExit(
            f"dry-run herdr_workspace {herdr_workspace!r} does not contain current "
            f"workspace {workspace_id!r}; not launching"
        )


def close_owned_session(unit: Any, *, receipt: dict[str, Any] | None = None) -> None:
    """Close only a tab this launch created.

    Ownership is launcher-side: the receipt tab_id was not in the Herdr workspace
    tab set snapshotted immediately before the wrapper ran.
    """
    proof = receipt if receipt is not None else getattr(unit, "launch_receipt", {}) or {}
    if not isinstance(proof, dict):
        raise SystemExit("cannot close: launch receipt is not an object, ownership unproven")
    if "owned" not in proof:
        raise SystemExit("cannot close: receipt does not prove tab ownership")
    if proof.get("owned") is not True:
        raise SystemExit(
            "cannot close: tab existed before this launch; this process does not own it"
        )
    tab_id = getattr(unit, "tab_id", None) or proof.get("tab_id")
    recorded = proof.get("tab_id")
    if not tab_id:
        raise SystemExit("cannot close: no tab_id on the session, ownership unproven")
    if not recorded:
        raise SystemExit("cannot close: launch receipt has no tab_id, ownership unproven")
    if recorded != tab_id:
        raise SystemExit(
            f"cannot close: tab_id {tab_id!r} does not match launch receipt {recorded!r}"
        )
    unit.tab_id = tab_id
    unit.owned = True
    if not isinstance(getattr(unit, "launch_receipt", None), dict):
        unit.launch_receipt = dict(proof)
    else:
        unit.launch_receipt["owned"] = True
    close_run_session(unit)


def _request_from_args(args: argparse.Namespace) -> LaunchRequest:
    assert_safe_path_component(args.task, "task name")
    cwd = str(Path(args.cwd).resolve()) if args.cwd else str(Path.cwd().resolve())
    return LaunchRequest(
        name=args.task,
        vendor=args.vendor,
        task=args.prompt or "",
        model=args.model,
        effort=args.effort,
        account=args.account,
        permission=args.permission,
        launch_args=list(args.launch_arg or []),
        workspace=args.workspace,
        worktree=cwd,
        variant=args.variant,
    )


def _add_launch_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--task", required=True, help="Herdr tab label and agent name")
    parser.add_argument("--cwd", default=None, help="Working directory (default: cwd)")
    parser.add_argument("--model", default=None)
    parser.add_argument("--effort", default=None)
    parser.add_argument("--permission", default="auto", choices=("auto", "bypass"))
    parser.add_argument("--account", default=None, choices=("company", "personal"))
    parser.add_argument("--workspace", default=None, help="Herdr workspace NAME, not an id")
    parser.add_argument("--variant", default=None)
    parser.add_argument("--prompt", default="", help="Optional first prompt after verification")
    parser.add_argument(
        "--launch-arg",
        action="append",
        default=[],
        help="Passthrough after the vendor token",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create one verified agent session through the agents wrapper and Herdr."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    _add_launch_flags(sub.add_parser("argv", help="Print the launch argv"))
    _add_launch_flags(sub.add_parser("preview", help="Dry-run and check cwd/workspace"))
    launch_p = sub.add_parser("launch", help="Preview, create, verify, optionally prompt")
    _add_launch_flags(launch_p)
    launch_p.add_argument(
        "--skip-preview",
        action="store_true",
        help="Rejected if set: launch always previews first",
    )
    close_p = sub.add_parser("close", help="Close a session this process owns")
    close_p.add_argument(
        "--tab-id",
        default=None,
        help="Optional when the receipt already carries tab_id",
    )
    close_p.add_argument("--receipt-json", required=True, help="Launch receipt proving ownership")
    sub.add_parser("roster", help="Vendors this machine can launch that this plugin can drive")
    return parser


def _load_receipt(raw: str) -> dict[str, Any]:
    path = Path(raw)
    text = path.read_text(encoding="utf-8") if path.is_file() else raw
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise SystemExit("receipt must be a JSON object")
    return loaded


def cli_main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "roster":
        for name, flags in roster():
            print(f"{name}\t{flags}")
        return 0
    if args.cmd == "close":
        receipt = _load_receipt(args.receipt_json)
        tab_id = args.tab_id or receipt.get("tab_id")
        if not tab_id:
            raise SystemExit("cannot close: no tab_id on --tab-id or the receipt")
        unit = LaunchRequest(
            name="owned",
            vendor="unknown",
            tab_id=str(tab_id),
            reused=wrapper_reused(receipt.get("reused")),
            owned=receipt.get("owned") is True,
            launch_receipt=receipt,
        )
        close_owned_session(unit, receipt=receipt)
        return 0
    unit = _request_from_args(args)
    if args.cmd == "argv":
        print(" ".join(agent_argv(unit)))
        return 0
    if args.cmd == "preview":
        preview = parse_dry_run(run(preview_argv(unit), timeout=20).stdout)
        confirm_preview(preview, unit.worktree or ".", current_herdr_workspace_id())
        json.dump(preview, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    if args.cmd == "launch":
        if args.skip_preview:
            raise SystemExit("refusing to launch without a dry-run preview")
        preview = parse_dry_run(run(preview_argv(unit), timeout=20).stdout)
        confirm_preview(preview, unit.worktree or ".", current_herdr_workspace_id())
        try:
            launch(unit)
        except SystemExit:
            if unit.launch_receipt:
                json.dump(unit.launch_receipt, sys.stdout, indent=2, sort_keys=True)
                sys.stdout.write("\n")
            raise
        json.dump(unit.launch_receipt, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        if (
            unit.status == PROMPT_UNDELIVERED
            or unit.launch_receipt.get("prompt_delivered") is False
        ):
            return 1
        return 0
    raise SystemExit(f"unknown command {args.cmd}")


if __name__ == "__main__" and not globals().get("_AGENT_LAUNCHER_INGESTING"):
    raise SystemExit(cli_main())
