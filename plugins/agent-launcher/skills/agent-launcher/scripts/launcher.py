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
import dataclasses
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _load_composer_module() -> Any:
    """Load the sibling parser from this compiled launcher's own source directory.

    Any exception while executing composer.py becomes the same named ``SystemExit`` in both
    entry modes -- standalone and ingested by Orchestrate -- carrying the exception type and
    message. The synthetic module name is the digest of the resolved source path (sha256,
    first 16 hex characters), so it is stable across processes. Identity comparisons on
    ``ComposerState`` members and ``StagedInputError`` are valid only inside one load: two
    loads produce distinct classes even from the same file.
    """
    source = Path(_load_composer_module.__code__.co_filename).resolve()
    path = source.with_name("composer.py")
    if not path.is_file():
        raise SystemExit(f"cannot load agent-launcher composer parser from {path}: file is missing")
    module_name = f"_agent_launcher_composer_{hashlib.sha256(str(path).encode()).hexdigest()[:16]}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load agent-launcher composer parser from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise SystemExit(
            f"cannot load agent-launcher composer parser from {path}: {type(exc).__name__}: {exc}"
        ) from None
    return module


_COMPOSER = _load_composer_module()
COMPOSER_GLYPH_BY_VENDOR = _COMPOSER.COMPOSER_GLYPH_BY_VENDOR
COMPOSER_MARKERS = _COMPOSER.COMPOSER_MARKERS
ComposerInspection = _COMPOSER.ComposerInspection
ComposerState = _COMPOSER.ComposerState
composer_staged_text = _COMPOSER.composer_staged_text
inspect_composer = _COMPOSER.inspect_composer

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
    # launch_receipt_shape is the single owner of this dict; it reads the attributes just set.
    receipt = launch_receipt_shape(unit)
    unit.launch_receipt = receipt
    return receipt


def launch_receipt_shape(unit: Any) -> dict[str, Any]:
    """The single owning shape for a launch receipt, completed in place as proof arrives."""
    return {
        "unit_name": unit.name,
        "vendor": unit.vendor,
        "tab_id": getattr(unit, "tab_id", None),
        "pane": getattr(unit, "pane_id", None),
        "agent_name": getattr(unit, "agent_name", None),
        "reused": wrapper_reused(getattr(unit, "reused", False)),
        # The unit attribute, never session_owned(): that predicate prefers the receipt this
        # dict is about to replace, so it would read the previous launch's answer (cycle 2, F58).
        "owned": getattr(unit, "owned", False) is True,
        "permission": getattr(unit, "permission", None),
        "verified": False,
        "prompt_delivered": None,
    }


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
    # opencode wants the model as `provider/model`, e.g. `deepseek/deepseek-v4-pro`; a bare name is
    # rejected at startup with "Invalid model format".
    "opencode": {"model": "-m {value}"},
}

SUPPORTED_VENDORS = frozenset(VENDOR_FLAGS)

if set(COMPOSER_GLYPH_BY_VENDOR) != SUPPORTED_VENDORS:
    missing = sorted(SUPPORTED_VENDORS - set(COMPOSER_GLYPH_BY_VENDOR))
    extra = sorted(set(COMPOSER_GLYPH_BY_VENDOR) - SUPPORTED_VENDORS)
    raise RuntimeError(f"composer vendor roster drift: missing={missing}, extra={extra}")

# Where a tool has no launch flag for something, the session is told after it starts. Every agent
# here takes slash commands, so tier is always settable -- through the command line where one
# exists, and through the session where one does not.
# What is worth knowing about a vendor that no other table has room for.
#
# Every one of these was learned by a run going wrong, and each was re-learned at least once because
# it lived nowhere. `roster` prints them, so the interview reads how a vendor behaves rather than
# recalling it -- which is the failure this is for: an orchestrator that guesses, plausibly, and is
# only found out a phase later.
# Herdr's name for a vendor's agent, where it differs from the vendor key. Muse Code is the agent
# Herdr detects as `maki`: the two names are one agent, so a `muse` launch accepts either.
HERDR_KIND_ALIASES: dict[str, frozenset[str]] = {"muse": frozenset({"muse", "maki"})}


def accepted_herdr_kinds(vendor: str) -> frozenset[str]:
    """The agent kinds Herdr may report for a session launched as ``vendor``."""
    key = str(vendor).lower()
    return HERDR_KIND_ALIASES.get(key, frozenset({key}))


VENDOR_NOTES: dict[str, str] = {
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
}

if set(VENDOR_PERMISSION) != SUPPORTED_VENDORS:
    raise RuntimeError("permission vendor roster drift from VENDOR_FLAGS")


def resolve_permission(vendor: str, permission: str) -> list[str]:
    """The flags this vendor takes for this posture, or a stop naming what was asked for.

    A vendor absent from the table has no permission ladder and legitimately emits nothing.
    A posture absent from a vendor that HAS a ladder is a typo or a spelling from another
    vendor, and quietly handing it the auto flag set is how a run comes up in a posture it
    did not declare.
    """
    modes = VENDOR_PERMISSION.get(vendor)
    if modes is None:
        return []
    if permission not in modes:
        raise SystemExit(
            f"unknown permission {permission!r} for vendor {vendor!r}; "
            f"expected one of {sorted(modes)}"
        )
    return list(modes[permission])


def _extend_permission_argv(argv: list[str], vendor: str, permission: str) -> None:
    """Append only a successfully resolved permission posture to ``argv``."""
    argv.extend(resolve_permission(vendor, permission))


class AccountMismatchError(SystemExit):
    """A worker launched under an account that does not match the requested plan account."""


class StagedInputError(SystemExit):
    """An unowned or resend-target pane contains operator-staged input."""


class TimedOutProcess(subprocess.CompletedProcess[str]):
    """A process result synthesized specifically from ``subprocess.TimeoutExpired``."""


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
    except subprocess.TimeoutExpired as exc:
        if check:
            raise SystemExit(f"timed out after {timeout}s while running {cmd[0]!r}") from None
        stdout = (
            exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout
        )
        stderr = (
            exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
        )
        return TimedOutProcess(
            cmd,
            returncode=124,
            stdout=stdout or "",
            stderr=stderr or f"timed out after {timeout}s while running {cmd[0]!r}",
        )
    except OSError as exc:
        if check:
            raise SystemExit(f"cannot run {cmd[0]!r}: {exc}") from None
        # 127 is the shell's own "command not found", so a caller reading returncode sees the
        # ordinary shape of a failure rather than a special case.
        return subprocess.CompletedProcess(cmd, returncode=127, stdout="", stderr=str(exc))
    if check and proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"command failed ({proc.returncode}) while running {cmd[0]!r}\n{err}")
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
    _extend_permission_argv(argv, unit.vendor, unit.permission)
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


# How long to give the wrapper to create the session. Larger than every other deadline on
# purpose: this one call may reach another machine over SSH and cold-start a vendor CLI, where
# the dry run it follows (timeout=20 in cli_main) only echoes a command line.
LAUNCH_CREATE_SECONDS = 120.0

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
    "trusting this unit -- it may have been prompted while still booting. If it is idle and "
    "never took the task, redeliver it (Orchestrate: redrive --unit NAME, standalone: "
    "launcher.py redeliver --receipt-json)."
)

# How long to give one pane read before the input-box inspection gives up. A pane read is a
# local socket round trip, so this is a bound on a wedged herdr rather than a wait for work.
PANE_INPUT_READ_SECONDS = 5.0
TAB_CLOSE_SECONDS = 10.0
# The most rows of a pane read handed to the composer parser, taken from the tail: the live box
# is the last block positionally, so the head of an oversized viewport is scrollback the parse
# never needed. Rows, not bytes: a byte cut can land inside the marker row itself and turn a
# staged draft into `not_found`, which the guard treats as inconclusive and prompts through
# (issue 907 terminal review cycle 2, F45). A row is never split, so the box survives the cut.
# The parser's own regex is linear (cycle 1, F12); this keeps a pathological viewport from
# turning one inspection into seconds through any other path.
PANE_INSPECT_MAX_LINES = 4000
# Bytes as well as rows (issue 1002 F130). The row cap stopped a mid-row cut; without a byte
# cap a 100-row viewport of huge lines is still unbounded. 131072 admits the measured ~68 KB
# bordered draft (F45) while still bounding pathological width.
PANE_INSPECT_MAX_CHARS = 131072
# How long to give one pane write. The two calls that put a line into a session were the only
# Herdr calls with no bound, so a wedged daemon hung go and land mid-delivery, after the guard
# had inspected the composer and before any status was written. A write is a local socket round
# trip carrying at most a pane-typed line or a prompt handle, so this bounds a wedge, not work.
PANE_WRITE_SECONDS = 30.0

# A transcript written during the create is legitimate evidence; one left by an earlier run is
# minutes or hours old. One second absorbs filesystem mtime granularity without admitting a
# stale file, and a same-instant write is a real case: the cmd_go account test plants its
# transcript inside the wrapper call itself.
TRANSCRIPT_MTIME_SLACK_SECONDS = 1.0


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

    Some agents never report readiness at all, and that is why the writer has a pane
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


# The Herdr statuses under which a session has not started anything. ``took_the_task`` and the
# retry door's liveness gate read the same set. ``done`` is started: Herdr reports it after a
# session took its task and finished (issue 1002 F103/F118). ``unknown`` and a missing row are
# still not evidence of work.
NEVER_STARTED_STATUSES = (None, "idle", "unknown")


def session_has_started(row: dict | None) -> bool:
    """Whether a Herdr row shows a session that took something: any status outside the
    never-started set. A missing row is not evidence of starting."""
    return row is not None and row.get("agent_status") not in NEVER_STARTED_STATUSES


def took_the_task(unit: Any, seconds: float = DELIVERY_CHECK_SECONDS) -> bool:
    """Did the session actually take the task? One that did stops being idle.

    Not a guarantee -- an agent that answers instantly is idle again quickly. It is a check on the
    failure that has actually happened, which is a session that never started at all.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if session_has_started(agent_row(unit)):
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
                and token.lower() in OPENCODE_VARIANT_RANKS
                and not any(token.lower() == o.lower() for o in options)
            ):
                options.append(token)
            continue
        # Token matches for common variant names
        for word in re.findall(
            r"\b(?:Default|minimal|low|medium|high|xhigh|max|maximum)\b", line, re.IGNORECASE
        ):
            if word.lower() in OPENCODE_VARIANT_RANKS and not any(
                word.lower() == o.lower() for o in options
            ):
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

    # The count, never the option tokens: they were scraped from the pane, and this stop becomes
    # the unit note and the run record (cycle 2, F74) -- the same redaction discipline the
    # composer guard follows.
    raise SystemExit(
        f"requested variant {requested!r} is not among the {len(available_options)} options "
        "the live picker offered"
    )


def read_pane(pane_id: str, lines: int = 120) -> str:
    """This pane's recent output, falling back to what is on screen when there is no scrollback."""
    proc = run(
        ["herdr", "pane", "read", pane_id, "--source", "recent-unwrapped", "--lines", str(lines)],
        check=False,
        timeout=PANE_INPUT_READ_SECONDS,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout
    proc = run(
        ["herdr", "pane", "read", pane_id, "--source", "visible"],
        check=False,
        timeout=PANE_INPUT_READ_SECONDS,
    )
    return proc.stdout if proc.returncode == 0 else ""


def pane_input_inspection(pane_id: str, *, vendor: str) -> Any:
    """Classify the visible input box while preserving distinct read and parse failures."""
    proc = run(
        ["herdr", "pane", "read", pane_id, "--source", "visible", "--format", "ansi"],
        check=False,
        timeout=PANE_INPUT_READ_SECONDS,
    )
    if isinstance(proc, TimedOutProcess):
        return ComposerInspection(ComposerState.READ_TIMEOUT)
    if proc.returncode != 0:
        return ComposerInspection(ComposerState.READ_FAILED)
    return inspect_composer(tail_inspect_window(proc.stdout), vendor=vendor)


def tail_rows(text: str, rows: int) -> str:
    """The last ``rows`` physical rows of ``text``, never cutting a row in half."""
    lines = text.split("\n")
    if len(lines) <= rows:
        return text
    return "\n".join(lines[-rows:])


def tail_inspect_window(text: str) -> str:
    """The tail of a pane dump handed to the composer, bounded by rows and bytes.

    Trim whole rows from the head so the live box at the tail survives both caps
    (issue 1002 F130).
    """
    window = tail_rows(text, PANE_INSPECT_MAX_LINES)
    if len(window) <= PANE_INSPECT_MAX_CHARS:
        return window
    lines = window.split("\n")
    while len(lines) > 1 and len("\n".join(lines)) > PANE_INSPECT_MAX_CHARS:
        lines.pop(0)
    trimmed = "\n".join(lines)
    if len(trimmed) <= PANE_INSPECT_MAX_CHARS:
        return trimmed
    return trimmed[-PANE_INSPECT_MAX_CHARS:]


def should_guard_pane_write(unit: Any, *, wrote_before: bool) -> bool:
    """The one rule for whether a pane must be inspected before the write about to happen.

    Two halves, both needed (KTD4). Ownership says who created the tab: a pane this launcher
    did not create may hold text somebody staged earlier. ``wrote_before`` says whether this
    launcher has already put anything into the session, through either door -- ``herdr agent
    prompt`` or pane typing -- because once it has, a person may have typed since, and the
    door the first write used says nothing about that. The only write that skips inspection
    is the first write into a pane this launcher created seconds earlier: an empty fresh pane
    is its own starting state. Orchestrate's later senders call this too, always with
    ``wrote_before`` true, since every unit they reach was prompted by its launch.
    """
    return wrote_before or not session_owned(unit)


def guard_pane_before_write(unit: Any, pane_id: str) -> None:
    """Inspect a pane before a write that could concatenate with staged input.

    A tab the launcher did not create may hold text somebody staged earlier, and a prompt sent
    behind it concatenates onto that text and can submit it. Staged text is therefore a stop:
    the box is proved non-empty by a characterisation -- its length -- never by its content. An
    input box holds whatever a person last typed and did not submit, so the text itself reaches
    no receipt, no note, no stop message, and no run record those feed; nothing is cleared,
    which is the strongest reading of "never silently discarded". Every inconclusive cause is
    recorded distinctly and prompted under the documented accepted trade, never claimed empty.
    """
    inspection = pane_input_inspection(pane_id, vendor=unit.vendor)
    receipt = unit.launch_receipt if isinstance(unit.launch_receipt, dict) else None
    if inspection.state in (ComposerState.READ_FAILED, ComposerState.READ_TIMEOUT):
        state = inspection.state.value
        if receipt is not None:
            receipt["input_box"] = state
        note = f"input box {state}, refusing to prompt without an observation"
        if note not in unit.note.split("; "):
            append_unit_note(unit, note)
        raise SystemExit(
            f"{unit.name}: pane {pane_id} input box {state}; refusing to prompt so an "
            "unobserved composer cannot be treated as empty"
        )
    if inspection.state not in (ComposerState.EMPTY, ComposerState.STAGED):
        state = inspection.state.value
        inconclusive_note = f"input box {state}, prompted without a conclusive inspection"
        # One line per cause, however many writes it authorises: the picker path inspects
        # with the picker on screen, and every one of those reads is inconclusive.
        if inconclusive_note not in unit.note.split("; "):
            append_unit_note(unit, inconclusive_note)
        if receipt is not None:
            receipt["input_box"] = state
        return
    if inspection.state is ComposerState.EMPTY:
        if receipt is not None:
            receipt["input_box"] = "empty"
            receipt.pop("input_box_text_chars", None)
        return
    staged = inspection.text or ""
    if receipt is not None:
        receipt["input_box"] = "staged"
        receipt["input_box_text_chars"] = len(staged)
    withheld_note = f"staged input withheld: {len(staged)} chars, not cleared"
    # A repeated stop with the same count must not stack a duplicate line on the note. The
    # membership test is a substring, not a split on the separator: the stop message itself
    # contains the separator, so a split can never match it.
    if withheld_note not in unit.note:
        append_unit_note(unit, withheld_note)
    raise StagedInputError(
        f"{unit.name}: pane {pane_id} already holds staged input ({len(staged)} chars, "
        "withheld from the record); refusing to prompt so the dispatched task cannot be "
        "concatenated onto it"
    )


# Compatibility for existing external imports. New call sites use the ownership-accurate name.
guard_unowned_pane = guard_pane_before_write
guard_reused_pane = guard_pane_before_write


OPENCODE_MENU_ROW_RE = re.compile(r"^(?:[>*\-•#]\s*|\d+[\.\)]\s*|\[[\s*xX]?\]\s*)")


def confirm_opencode_variant_selected(unit: Any, pane_id: str, selected: str) -> str:
    """Read the pane back and require the chosen variant to be reflected in it.

    Typing a label into a picker is a request, not an outcome. A picker that closed on the value it
    already held leaves the session at a variant nobody asked for, and submitting work into it is
    exactly the silent substitution this unit's stop conditions forbid. The echo the interface
    leaves behind is the only evidence of the selection available from outside it, so a selection
    that cannot be found there is a loud stop rather than an assumption.

    Returns where the token was seen, and that is recorded rather than upgraded (cycle 2, F75):
    ``"session"`` when it appears on a row that is not a picker menu row -- the picker closed and
    the session itself shows the variant -- and ``"picker_menu_only"`` when the only rows carrying
    it are menu rows, which is the same menu the token was scraped from and proves nothing about
    the selection. The preflight lists the variant as confirmed only in the first case.
    """
    clean = strip_ansi(read_pane(pane_id, lines=40))
    token = re.compile(rf"\b{re.escape(selected)}\b", re.IGNORECASE)
    rows = [row.strip() for row in clean.splitlines() if token.search(row)]
    if not rows:
        raise SystemExit(
            f"{unit.name}: the selected variant was sent to the picker but the session does not "
            "report it; refusing to submit the task at an unverified variant"
        )
    # The launcher's own echo of the typed token is a row whose stripped text is exactly that
    # token (issue 1002 F115). Menu rows and that echo prove nothing about the session.
    session_rows = [
        row
        for row in rows
        if not OPENCODE_MENU_ROW_RE.match(row) and row.lower() != selected.strip().lower()
    ]
    if session_rows:
        return "session"
    return "picker_menu_only"


def drive_opencode_variant_selection(
    unit: Any, pane_id: str, *, writer: PaneWriter, timeout: float = 10.0
) -> tuple[str, bool]:
    """Drive OpenCode's `/variants` picker in Herdr and verify the selection took.

    Returns the variant now in force and whether the session reported itself ready afterwards.
    Both of the picker's writes go through ``writer`` -- they are pane writes like any other,
    and the writer is the only door (``PaneWriter``); this function has no way to type into the
    pane on its own.

    A pane holds the session's whole recent output, not only its picker, so a parse that finds
    nothing the variant ladder recognises is read as "the picker has not drawn yet" and polled
    again rather than taken as the option list. Accepting a boot banner as the choices either
    refuses a perfectly available exact variant or types one of the banner's own words into the
    session; only once the window closes is an unrecognised set accepted, and an empty one stops.
    """
    # Open the picker
    writer.write("/variants", door="pane")

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
    writer.write(selected, door="pane")

    # Wait until session returns to task-ready, then confirm the picker actually moved
    ready = await_ready(unit)
    seen_in = confirm_opencode_variant_selected(unit, pane_id, selected)
    if isinstance(unit.launch_receipt, dict):
        unit.launch_receipt["variant_confirmed_from"] = seen_in

    unit.variant = selected
    if seen_in == "session":
        append_unit_note(unit, "variant verified")
    return selected, ready


def close_run_session(unit: Any) -> subprocess.CompletedProcess[str] | None:
    """Close only the tab this launch created, leaving every other session alone.

    Returns the close result, or None when there was nothing owned to close. This low-level helper
    records failures so unwind callers retain their original stop; the explicit close command
    turns that recorded result into its own named stop.
    """
    if not session_owned(unit):
        return None
    if not unit.tab_id:
        return None
    proc = run(
        ["herdr", "tab", "close", unit.tab_id],
        check=False,
        timeout=TAB_CLOSE_SECONDS,
    )
    if proc.returncode != 0:
        workspace_id = str(unit.tab_id).partition(":")[0] or None
        remaining = list_tab_ids(workspace_id)
        if remaining is not None and unit.tab_id not in remaining:
            return subprocess.CompletedProcess(proc.args, 0, proc.stdout, proc.stderr)
        err = (proc.stderr or proc.stdout or "").strip()
        failure = tab_close_failure(unit.tab_id, proc.returncode, err)
        # Membership is a substring, never a split on the separator: the failure message
        # itself carries the separator whenever Herdr's stderr does, so a split can never
        # match it and a repeated failure would stack copies on the note.
        if failure not in unit.note:
            append_unit_note(unit, failure)
    return proc


def tab_close_failure(tab_id: str, returncode: int, detail: str) -> str:
    """One stable error shape shared by cleanup notes and the explicit close command."""
    return f"tab close failed ({returncode}) for {tab_id}: {detail}"


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
    proc = run(["herdr", "workspace", "list"], check=False, timeout=20)
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

    Every separator and dot becomes a dash: ``/home/example/my.project`` is stored as
    ``-home-example-my-project``, which is where the dot belongs in this class -- a worktree whose
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


def transcript_account(unit: Any, *, since: float | None = None) -> str | None:
    """Which account's transcript root holds this worker's session, when either one does.

    Both roots can hold a transcript for the same worktree -- a relaunch after a wrong-account
    launch leaves the earlier one in place -- so the newer file decides. Returns ``None`` while
    neither root has one, which is the ordinary state at preflight: Claude writes
    ``projects/<slug>/<id>.jsonl`` when the first prompt arrives, and preflight runs before the
    task is sent. When ``since`` is given, a file older than that floor -- minus one second of
    mtime granularity slack -- is ignored: a transcript that predates the launch cannot certify
    it, and without the floor this fallback once certified exactly that.
    """
    personal_root, company_root = claude_transcript_roots()
    newest: list[tuple[float, str]] = []
    for label, root in (("personal", personal_root), ("company", company_root)):
        files = find_claude_transcripts(root, unit.worktree)
        mtimes: list[float] = []
        for file in files:
            try:
                mtime = file.stat().st_mtime
            except OSError:
                # A transcript can be rotated between glob and stat; that is no evidence rather
                # than an exceptional launch failure.
                continue
            if since is None or mtime >= since - TRANSCRIPT_MTIME_SLACK_SECONDS:
                mtimes.append(mtime)
        if mtimes:
            newest.append((max(mtimes), label))
    if not newest:
        return None
    return max(newest)[1]


def pane_account_label(pane_id: str | None) -> str | None:
    """The account this session's own statusline reports, or None while it does not say.

    The wrapper exports ``CLAUDE_ACCOUNT_LABEL`` into the pane before the tool starts and the
    statusline renders it beside the user -- ``operator [company]:`` against a plain ``operator:`` on
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
    proc = run(
        ["herdr", "pane", "read", pane_id, "--source", "visible"],
        check=False,
        timeout=PANE_INPUT_READ_SECONDS,
    )
    if proc.returncode != 0:
        return None
    text = strip_ansi(proc.stdout)
    tail = "\n".join(text.splitlines()[-3:])
    last = None
    for match in re.finditer(rf"\b{re.escape(user)}\s*(?:\[(\w+)\])?:", tail):
        last = match
    if last is None:
        return None
    return (last.group(1) or "personal").lower()


def observed_account(
    unit: Any, pane_id: str | None, seconds: float, *, since: float | None = None
) -> tuple[str | None, str]:
    """The account the launched session is actually on, and where the answer came from.

    The statusline answers first because it is painted at startup. At the production preflight,
    the transcript root can answer only when the wrapper writes a same-instant create-time file;
    ordinary transcripts start after the first prompt and are intentionally too late. Neither
    source is instant, so the window is spent before the question is given up on. The evidence is ``"statusline"``,
    ``"transcript"`` or ``"none"`` -- the receipt records which, because the two proofs are not
    equal: a transcript only certifies this launch when its recency is tied to it.
    """
    deadline = time.monotonic() + seconds
    while True:
        from_pane = pane_account_label(pane_id)
        if from_pane:
            return from_pane, "statusline"
        from_transcript = transcript_account(unit, since=since)
        if from_transcript:
            return from_transcript, "transcript"
        if time.monotonic() >= deadline:
            return None, "none"
        time.sleep(1.0)


def check_unit_account(
    unit: Any,
    pane_id: str | None = None,
    seconds: float = ACCOUNT_SETTLE_SECONDS,
    *,
    since: float | None = None,
    evidence_out: list[str] | None = None,
) -> tuple[bool | None, str | None]:
    """Check whether a launched Claude unit is on the account the plan asked for.

    Returns:
        (True, None) when the session reports the requested account.
        (False, error_msg) when it reports a different one, when the plan named an account this
        script does not know, or when no account could be read at all -- an unverified account is
        a stop, not a pass, because the failure being guarded against is invisible by nature.
        (None, None) when no account was requested, or the vendor has no account to check.

    ``since`` bounds the transcript fallback to files written at or after the launch; ``evidence_out``
    receives one string naming where the observed account came from, when anything was observed.
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

    observed, evidence = observed_account(unit, pane_id, seconds, since=since)
    if evidence_out is not None:
        evidence_out.append(evidence)
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


def verify_unit_account(
    unit: Any, pane_id: str | None = None, *, since: float | None = None
) -> tuple[bool | None, str]:
    """Verify the account for a launched unit, closing the session and raising on mismatch.

    Returns the confirmation together with the evidence it came from -- ``"statusline"``,
    ``"transcript"`` or ``"none"`` -- so the receipt can record which proof was accepted.
    """
    evidence_out: list[str] = []
    confirmed, error = check_unit_account(unit, pane_id, since=since, evidence_out=evidence_out)
    if error:
        close_run_session(unit)
        unit.status = ACCOUNT_MISMATCH
        append_unit_note(unit, error)
        raise AccountMismatchError(f"{unit.name}: {error}")
    evidence = evidence_out[0] if evidence_out else "none"
    return confirmed, evidence


def verify_unit_identity(
    unit: Any, pane_id: str | None, *, ready: bool | None = None
) -> tuple[list[str], list[str], str, bool]:
    """Verify the Herdr identity before any guard or picker diagnostic can mask a mismatch."""
    if not pane_id:
        raise SystemExit(f"{unit.name}: session was not assigned a valid pane_id")

    confirmed = ["pane"]
    unconfirmed = ["model", "permission"]
    row = agent_row(unit)
    if row is None:
        raise SystemExit(f"{unit.name}: herdr did not list the session; cannot verify agent kind")

    reported_kind = row.get("agent") or row.get("kind")
    if not reported_kind:
        raise SystemExit(f"{unit.name}: herdr did not report agent kind; refusing to prompt")
    if str(reported_kind).lower() not in accepted_herdr_kinds(unit.vendor):
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
    return confirmed, unconfirmed, str(reported_kind), observed_ready


def verify_unit_preflight(
    unit: Any,
    pane_id: str | None,
    *,
    ready: bool | None = None,
    argv: list[str] | None = None,
    since: float | None = None,
    identity: tuple[list[str], list[str], str, bool] | None = None,
) -> dict[str, Any]:
    """Verify the session against herdr before the task is submitted, and record what was checked.

    Only what herdr publishes can be checked. A row in ``herdr agent list`` carries ``cwd``,
    ``workspace_id`` and ``interactive_ready``; it carries no model at all, and its workspace is an
    id where the plan holds a name. So the receipt separates what was confirmed against herdr from
    what is only the request the unit was launched with. A single ``verified: true`` covering both
    would be a claim this script is not in a position to make, and a run record that says a model
    was verified when nothing could read it is worse than one that says it was not.
    """
    confirmed, unconfirmed, reported_kind, observed_ready = identity or verify_unit_identity(
        unit, pane_id, ready=ready
    )
    if ready is not None:
        observed_ready = bool(ready)

    # Herdr publishes no permission, so the launch argv is the only outside witness that the
    # session came up in the posture it declared: the declared mode's tokens must appear in it
    # as a contiguous run. This stays out of ``confirmed`` -- that list is what Herdr published.
    permission_tokens = resolve_permission(unit.vendor, unit.permission)
    if argv is not None and permission_tokens:
        width = len(permission_tokens)
        carried = any(
            argv[index : index + width] == permission_tokens
            for index in range(len(argv) - width + 1)
        )
        if not carried:
            close_run_session(unit)
            raise SystemExit(
                f"{unit.name}: declared permission {unit.permission!r} resolves to "
                f"{permission_tokens} but the launch argv does not carry it"
            )

    # A Claude unit that names an account either confirms it or raises: an account that could not
    # be read is the failure this check exists for, wearing the same face as one that was never
    # checked. Every other vendor has no account to read, so a unit that names one anyway is
    # recorded as having asked rather than as having been confirmed.
    account_confirmed, account_evidence = verify_unit_account(unit, pane_id, since=since)
    confirmed_outside_herdr: list[str] = []
    if unit.account:
        if account_confirmed:
            if account_evidence == "statusline":
                confirmed.append("account")
            else:
                confirmed_outside_herdr.append("account")
        else:
            unconfirmed.append("account")

    effective_provider = (
        unit.model.split("/")[0] if (unit.model and "/" in unit.model) else unit.vendor
    )
    effective_variant = unit.variant or unit.effort
    if unit.vendor == "opencode" and not effective_variant:
        effective_variant = "Default"
    # An OpenCode variant is confirmed only when it was read back from the session itself, not
    # from the picker menu it was scraped out of (cycle 2, F75).
    existing = getattr(unit, "launch_receipt", None)
    variant_seen_in = existing.get("variant_confirmed_from") if isinstance(existing, dict) else None
    if unit.vendor == "opencode" and unit.variant and variant_seen_in == "session":
        confirmed.append("variant")
    else:
        unconfirmed.append("variant")

    existing_receipt = getattr(unit, "launch_receipt", None)
    receipt = existing_receipt if isinstance(existing_receipt, dict) else launch_receipt_shape(unit)
    receipt.update(
        {
            "unit_name": unit.name,
            "vendor": unit.vendor,
            "provider": effective_provider,
            "model": unit.model,
            "variant": effective_variant,
            "account": unit.account,
            # The requested-versus-resolved shape applied to the account: ``account`` above stays the
            # requested selection, and this records which proof confirmed it -- "statusline",
            # "transcript", or "none" when no account was asked for or nothing could be read.
            "account_evidence": account_evidence,
            "permission": getattr(unit, "permission", None),
            # The requested-versus-resolved shape: ``permission`` above stays what was asked for,
            # and this records what the launch actually carried. Herdr publishes neither, so an
            # argv-derived fact lives in its own channel, never inside ``confirmed_against_herdr``.
            "permission_resolved": {
                "mode": getattr(unit, "permission", None),
                "tokens": permission_tokens,
                "confirmed_from": "launch_argv" if argv is not None and permission_tokens else None,
            },
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
            "confirmed_outside_herdr": confirmed_outside_herdr,
            "requested_only": unconfirmed,
            # True by construction: every check that can fail raises above this point, so it reads
            # "preflight passed", and ``confirmed_against_herdr`` is what that passing actually covered.
            "verified": True,
            "prompt_delivered": receipt.get("prompt_delivered"),
        }
    )
    unit.launch_receipt = receipt
    return receipt


def _receipt_from_output(stdout: str) -> dict[str, Any] | None:
    """Return a wrapper receipt from its last output line, if one was completed."""
    try:
        loaded = json.loads(stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _record_create_timeout(
    unit: Any,
    *,
    preexisting: frozenset[str] | None,
    workspace_id: str | None,
) -> str:
    """Reconcile tabs after an expired wrapper call and retain any recoverable identity."""
    current = list_tab_ids(workspace_id)
    if preexisting is None or current is None:
        return "the target workspace tab set could not be reconciled"
    created = sorted(current - preexisting)
    if not created:
        return "no new target-workspace tab was found"
    unit.tab_id = created[0] if len(created) == 1 else None
    unit.owned = len(created) == 1
    unit.launch_receipt = launch_receipt_shape(unit)
    unit.launch_receipt["create_timeout_new_tabs"] = created
    unit.launch_receipt["workspace_id"] = workspace_id
    if len(created) == 1:
        unit.launch_receipt["tab_id"] = created[0]
        return f"new tab {created[0]} was retained in the receipt for explicit cleanup"
    return f"new tabs after the create attempt: {created}"


def _deliver(
    unit: Any,
    pane_id: str,
    backend: str,
    *,
    review_elsewhere: bool,
    argv: list[str],
    since: float | None,
    wrote_before: bool,
) -> None:
    """Deliver the task into an existing pane: preflight, then every write through one door.

    Every collaborator is reached through this module's globals, so every existing stub still
    applies. ``since`` floors the transcript account fallback -- the create instant on a
    fresh launch, None on a redelivery, which trades away the recency floor the receipt
    cannot supply (the receipt records no creation time). ``wrote_before`` seeds the one
    ``PaneWriter`` this delivery uses: false before a fresh launch's first write, true from
    the start of a redelivery, because the stop that made the redelivery necessary was an
    inspection that found text. Nothing here decides whether to inspect; the writer does,
    before each write it makes, and there is no other way to write.
    """
    writer = PaneWriter(unit, pane_id, wrote_before=wrote_before)
    ready = await_ready(unit)
    identity = None
    if not session_owned(unit):
        identity = verify_unit_identity(unit, pane_id, ready=ready)
    if unit.vendor == "opencode":
        # The picker's two writes are the first writes of an OpenCode delivery; the writer
        # inspects each under the same rule as every other write.
        _, ready = drive_opencode_variant_selection(unit, pane_id, writer=writer)
    verify_unit_preflight(unit, pane_id, ready=ready, argv=argv, since=since, identity=identity)
    # The send comes after the preflight, so the inspection that authorises its first write is
    # taken immediately before that write: the declared bounds between an earlier read and the
    # send sum to about fifty seconds, and a person typing inside that window defeats the guard.
    send(unit, writer, backend, review_elsewhere=review_elsewhere)
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
            # The writer has written by now, so every write of a resend is inspected.
            send(unit, writer, backend, review_elsewhere=review_elsewhere)
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


def launch(unit: Any, backend: str = "inline", *, review_elsewhere: bool = False) -> None:
    """Create the session, then deliver the task with each pane write inspected at its own door.

    Every line that enters the session goes through one ``PaneWriter``, which inspects the
    composer before each write under ``should_guard_pane_write``: an unowned session is
    inspected before its first write and every session is inspected before every later write.
    The one write that skips inspection is the first write into a tab this launcher created
    seconds earlier -- an empty fresh pane is its own starting state. On OpenCode that first
    write is the picker opening, so an owned OpenCode launch inspects before the variant
    selection and before the task; an unowned one inspects before all three. A read taken
    while the picker is on screen classifies the picker, not a draft, and is recorded as an
    inconclusive inspection under the documented trade -- it is taken, not skipped.
    """
    target_workspace_id = workspace_id_for_name(unit.workspace) if unit.workspace else None
    preexisting = (
        list_tab_ids(target_workspace_id) if target_workspace_id or not unit.workspace else None
    )
    # Wall clock, not time.monotonic: it is compared against transcript filesystem mtimes as the
    # recency floor that keeps a stale transcript from certifying this launch.
    created_at = time.time()
    argv = agent_argv(unit)
    proc = run(argv, check=False, timeout=LAUNCH_CREATE_SECONDS)
    if isinstance(proc, TimedOutProcess):
        reconciliation = _record_create_timeout(
            unit, preexisting=preexisting, workspace_id=target_workspace_id
        )
        raise SystemExit(
            f"{unit.name}: session create timed out after {LAUNCH_CREATE_SECONDS}s; "
            f"{reconciliation}"
        )
    if proc.returncode != 0:
        failure_receipt = _receipt_from_output(proc.stdout)
        if failure_receipt is not None:
            record_wrapper_identity(unit, failure_receipt, preexisting=preexisting)
        err = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(
            f"command failed ({proc.returncode}) while running {argv[0]!r} with "
            f"{len(argv) - 1} argument(s)\n{err}"
        )
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
    _deliver(
        unit,
        pane_id,
        backend,
        review_elsewhere=review_elsewhere,
        argv=argv,
        since=created_at,
        wrote_before=False,
    )


def redeliver(unit: Any, backend: str = "inline", *, review_elsewhere: bool = False) -> None:
    """Re-deliver the task into the pane a staged-input stop kept on the unit.

    A staged-input stop is retryable: the unit keeps its tab, pane and receipt, and once the
    operator clears the composer the retry prompts the same pane. This entry never runs the
    wrapper create -- calling launch() again would create a second session and overwrite the
    first owned tab (the prior validation artifact's REL-03 rebuilt through the retry door) --
    and it seeds ``wrote_before`` true, so ``should_guard_pane_write`` inspects the first write
    whatever the ownership: the stop that made this retry necessary was an inspection that
    found text.

    It inherits the resend loop's own precondition, too. A staged-input stop can be raised
    from inside that loop, after a first send already went out; if the session has since
    started -- working, blocked, gone, or done -- it may already hold the task, and the
    resend loop refuses exactly that resend. So a row that is anything but idle or unknown
    gets nothing: the unit is recorded sent-but-unobserved, which closes the retry route and
    hands the tab to the operator rather than risking a second delivery.
    """
    pane_id = getattr(unit, "pane_id", None)
    if not pane_id:
        raise SystemExit(
            f"{unit.name}: cannot redeliver without the pane a staged-input stop recorded; "
            "clear the composer and relaunch the unit instead"
        )
    row = agent_row(unit)
    if session_has_started(row):
        # The same vocabulary as took_the_task: a session that visibly started -- including
        # done -- is refused. idle, unknown, or a missing row has not started; a missing row
        # is then the preflight's named stop, not a silent close of the retry route.
        status = row.get("agent_status") if row is not None else None
        append_unit_note(
            unit,
            f"redelivery withheld: the session was {status}, so it may already hold the task; "
            "check the tab before prompting it again",
        )
        unit.status = PROMPT_UNDELIVERED
        append_unit_note(unit, DELIVERY_WARNING)
        if isinstance(unit.launch_receipt, dict):
            unit.launch_receipt["prompt_delivered"] = False
        return
    _deliver(
        unit,
        pane_id,
        backend,
        review_elsewhere=review_elsewhere,
        argv=agent_argv(unit),
        since=None,
        wrote_before=True,
    )


# How long a line may be before typing it into a pane stops delivering it as an instruction.
#
# Measured 2026-10 against the since-retired Qwen Code CLI (0.21.13) through `herdr pane run`:
# 859 characters arrive as typed text, 1660 arrive as `[Pasted Content N chars]`. The paste is
# submitted and the agent knows its size -- it simply does not treat it as the instruction. Its own
# words, verbatim, to a 6402-character task: "I can see you've pasted some content (6402
# characters), but I'm not sure what you'd like me to do with it."
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
    base = TASK_DIR.resolve()
    path = (TASK_DIR / f"{unit.name}.md").resolve()
    if path != base and base not in path.parents:
        raise SystemExit(f"task file {unit.name!r} resolves outside {TASK_DIR}: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n")
    lead = text.split(" ", 1)[0] if re.match(r"^\s*[/$]", text) else ""
    append_unit_note(unit, f"task handed over as a file, too long to type: {path}")
    return (
        f"{lead} Your full task is in {path} -- read that file in full and carry it out exactly. "
        "It is the complete instruction; nothing else is coming."
    ).strip()


class PaneWriter:
    """The only door through which a line enters a session, and the owner of the inspection.

    Both raw doors -- ``herdr agent prompt`` and ``herdr pane run`` -- exist only as nested
    functions inside ``write``. They are not methods, so a caller cannot open either without
    going through the inspection ``write`` owns (issue 1002 F104). The structural test is a
    net for the enumerated AST shapes, not a proof that every dynamic Python call is
    impossible (issue 1002 F121). Before each write, ``write`` asks ``should_guard_pane_write``
    whether the composer must be inspected first, using its own record of whether it has
    already written into this session (``wrote``).

    ``wrote_before`` seeds the record: false for a fresh launch, whose first write into a tab
    this launcher created seconds earlier is the one write the rule exempts; true for a
    redelivery and for Orchestrate's later senders, where a person may have typed since.

    Doors. ``door="prompt"`` is ``herdr agent prompt``, the right door for an agent that reports
    interactive readiness; one that never does refuses it, and the line is typed
    into the pane instead, as the operator would by hand, up to the length a pane still carries
    as an instruction (``pane_text``). ``door="pane"`` types verbatim: the OpenCode picker is
    driven with keystrokes, not prompts. Both are bounded by ``PANE_WRITE_SECONDS``; a write
    that times out on either door is a named stop saying the line may or may not have reached
    the session, and the prompt door never falls through to the pane behind a timeout -- that
    would be the second delivery every guard in this file exists to prevent. A writer with no
    pane can only prompt through the agent handle and has nothing to inspect.
    """

    def __init__(self, unit: Any, pane_id: str | None, *, wrote_before: bool) -> None:
        self.unit = unit
        self.pane_id = pane_id
        self.wrote = wrote_before

    def write(self, text: str, *, door: str = "prompt") -> None:
        """Inspect if the rule requires it, then put ``text`` into the session."""
        unit = self.unit
        pane_id = self.pane_id

        def type_into_pane(line: str) -> None:
            if not pane_id:
                raise SystemExit(f"{unit.name}: no pane to type into")
            typed = run(
                ["herdr", "pane", "run", str(pane_id), line],
                check=False,
                timeout=PANE_WRITE_SECONDS,
            )
            if isinstance(typed, TimedOutProcess):
                raise SystemExit(
                    f"{unit.name}: herdr pane run into {pane_id} did not return within "
                    f"{PANE_WRITE_SECONDS}s; the line may or may not have reached the session -- "
                    "check the tab before prompting it again"
                )
            if typed.returncode != 0:
                err = (typed.stderr or typed.stdout or "").strip()
                raise SystemExit(
                    f"{unit.name}: command failed ({typed.returncode}) while typing into pane "
                    f"{pane_id}\n{err}"
                )

        def open_door(line: str, *, via: str) -> None:
            if via == "pane":
                type_into_pane(line)
                return
            if via != "prompt":
                raise SystemExit(f"{unit.name}: unknown pane-write door {via!r}")
            handle = unit.agent_name or unit.name
            attempt = run(
                ["herdr", "agent", "prompt", handle, line],
                check=False,
                timeout=PANE_WRITE_SECONDS,
            )
            if isinstance(attempt, TimedOutProcess):
                raise SystemExit(
                    f"{unit.name}: herdr agent prompt did not return within {PANE_WRITE_SECONDS}s; "
                    "the line may or may not have reached the session -- check the tab before "
                    "prompting it again"
                )
            if attempt.returncode == 0:
                return
            if not pane_id:
                raise SystemExit(f"{unit.name}: agent prompt refused and no pane to fall back to")
            type_into_pane(pane_text(unit, line))
            fallback_note = (
                "prompted through its pane; this agent does not report interactive readiness"
            )
            if fallback_note not in unit.note.split("; "):
                append_unit_note(unit, fallback_note)

        if pane_id and should_guard_pane_write(unit, wrote_before=self.wrote):
            guard_pane_before_write(unit, pane_id)
        open_door(text, via=door)
        self.wrote = True


def send(
    unit: Any, writer: PaneWriter, backend: str = "inline", *, review_elsewhere: bool = False
) -> None:
    """Set the session up, then give it its task -- each line one inspected write.

    Setup goes first and separately: a tier has to be in force before the work starts, and a slash
    command bundled into the same message as the task is just text the agent reads. Each setup
    line and the task are separate writes, each inspected by the writer before it goes: one
    inspection before the first of them would leave the task landing up to a minute past its
    guard (terminal review cycle 2, F41).
    """
    for line in unit.setup:
        writer.write(line)
    writer.write(normalize_task(unit.vendor, unit.task, backend, review_elsewhere=review_elsewhere))


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
    proc = close_run_session(unit)
    if proc is not None and proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(tab_close_failure(unit.tab_id, proc.returncode, err))


class RetryReceiptRefused(SystemExit):
    """A receipt the retry door will not act on. Exits 2, distinct from an undelivered retry."""


def _adopt_retry_receipt(unit: LaunchRequest, receipt: dict[str, Any]) -> None:
    """Take the session identifiers a stop recorded onto a fresh request.

    The standalone retry door. The receipt is the only thing that knows which tab and pane
    the stop left behind and whether this launcher owns them, so those come from it; the
    task text and launch settings come from the flags, exactly as ``launch`` took them. Two
    shapes are retryable: a staged-input stop (``input_box`` is ``staged``) and a prompt that
    was sent but never observed to be taken (``prompt_delivered`` is false) -- the second is
    the undelivered bucket, which had no door of its own (cycle 2, F76). Four refusals keep
    this from becoming a second delivery: no prompt to deliver, a receipt for a different task
    name, a receipt that records neither retryable stop (a delivered prompt must not be sent
    twice), and a receipt with no pane. Each exits 2 (cycle 2, F63/F64).
    """
    if not unit.task.strip():
        raise RetryReceiptRefused(
            "cannot redeliver: --prompt is empty; a retry with nothing to deliver cannot succeed"
        )
    recorded_name = receipt.get("unit_name")
    if not recorded_name:
        raise RetryReceiptRefused(
            "cannot redeliver: the receipt records no unit_name; clear the composer and launch "
            "again under a new task name"
        )
    if recorded_name != unit.name:
        raise RetryReceiptRefused(
            f"cannot redeliver: receipt was written for task {recorded_name!r}, not {unit.name!r}"
        )
    if receipt.get("prompt_delivered") is True:
        raise RetryReceiptRefused(
            "cannot redeliver: the receipt records a prompt that was already delivered; "
            "a prompt that was delivered must not be sent twice"
        )
    staged = receipt.get("input_box") == ComposerState.STAGED.value
    undelivered = receipt.get("prompt_delivered") is False
    if not (staged or undelivered):
        raise RetryReceiptRefused(
            "cannot redeliver: the receipt records neither a staged-input stop (input_box is "
            f"{receipt.get('input_box')!r}) nor an undelivered prompt (prompt_delivered is "
            f"{receipt.get('prompt_delivered')!r}); a prompt that was delivered must not be "
            "sent twice, and anything else is a new launch under a new task name"
        )
    # Only the canonical spelling: the shape writes ``pane`` and nothing writes ``pane_id``
    # into a receipt (cycle 2, F61).
    pane_id = receipt.get("pane")
    if not pane_id:
        raise RetryReceiptRefused(
            "cannot redeliver: the receipt records no pane; clear the composer and launch "
            "again under a new task name"
        )
    tab_id = receipt.get("tab_id")
    if not tab_id:
        raise RetryReceiptRefused(
            "cannot redeliver: the receipt records no tab_id; clear the composer and launch "
            "again under a new task name"
        )
    if "owned" not in receipt:
        raise RetryReceiptRefused(
            "cannot redeliver: the receipt records no owned key; clear the composer and launch "
            "again under a new task name"
        )
    agent_name = receipt.get("agent_name")
    if not agent_name:
        raise RetryReceiptRefused(
            "cannot redeliver: the receipt records no agent_name; clear the composer and launch "
            "again under a new task name"
        )
    unit.tab_id = tab_id
    unit.pane_id = str(pane_id)
    unit.agent_name = str(agent_name)
    unit.reused = wrapper_reused(receipt.get("reused"))
    unit.owned = receipt.get("owned") is True
    unit.launch_receipt = receipt


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


# --------------------------------------------------------------------------- the targeted reviewer
#
# Issue #158. Saga's targeted reviewer runs headless, never in a Herdr pane: one session per
# review, on a staffed vendor, with that vendor's normal configuration (instruction files, plugins,
# hooks, the subscription sign-in), in a sandbox that keeps its commands to a scratch copy of the
# head commit with no network and no credentials. ``launcher.py review`` starts it and returns its
# answer and a result; ``launcher.py reviewer-probe`` runs the same recipe live and checks every
# denial from outside the session. Orchestrate execs this file into its own namespace, so every
# name below carries ``reviewer``.

REVIEWER_RESULT_SCHEMA = "targeted_reviewer_launch.v1"
REVIEWER_PROMPT_ID = "targeted-reviewer-prompt"
REVIEWER_TIMEOUT_SECONDS = 3600
REVIEWER_EXIT_REFUSED = 2
REVIEWER_EXIT_NO_ANSWER = 3
#: Issue #248: the most of an unreadable final message the launcher keeps beside result.json.
REVIEWER_FINAL_MESSAGE_LIMIT = 64 * 1024
REVIEWER_EXIT_TIMEOUT = 124
REVIEWER_DEFAULT_CAP = 5
#: Issue #223. The dollar ceiling the probe's own Claude launch carries. One shell command on a
#: small model never comes near it, and it still bounds a runaway.
REVIEWER_PROBE_CEILING_USD = "1.00"
#: A ceiling is a positive decimal with at most two places, written as the operator typed it.
_REVIEWER_CEILING = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?")

#: Every launcher vendor's flags that turn off instruction files, plugins, hooks or skills, or
#: remove its sandbox or approvals, read from each vendor's own ``--help`` on 2026-10-06. No
#: reviewer launch may pass one; a test keeps the keys equal to ``VENDOR_FLAGS``.
REVIEWER_FORBIDDEN_FLAGS: dict[str, tuple[str, ...]] = {
    "claude": (
        "--bare", "--safe-mode", "--restricted", "--disable-slash-commands",
        "--strict-mcp-config", "--setting-sources", "--dangerously-skip-permissions",
        "bypassPermissions",
    ),
    "codex": (
        "--ignore-user-config", "--ignore-rules", "--disable",
        "--dangerously-bypass-approvals-and-sandbox",
    ),
    # Issue #223 added ``--trust`` (trusts the folder, so the reviewed change's own hooks load) and
    # the ``--sandbox`` values ``off`` and ``devbox``, read from grok 1.0.50's help and sandbox guide.
    "grok": (
        "--always-approve", "--system-prompt-override", "bypassPermissions", "--trust", "off",
        "devbox",
    ),
    # Issue #223 added ``--disable-approval`` and ``--trust-workspace`` (loads the reviewed
    # change's own rules and skills), read from muse 1.4.6's ``exec --help``.
    "muse": (
        "--disable-sandbox", "--no-foreign-personal-context", "--disable-reminders", "--yolo",
        "never", "--disable-approval", "--trust-workspace",
    ),
    "agy": ("--dangerously-skip-permissions", "--disable-slash-commands"),
    "opencode": ("--auto",),
}

#: Variables that make a vendor sign in with an API key instead of the subscription. The launch
#: removes them from the session's environment.
REVIEWER_API_KEY_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_PROFILE",
)
REVIEWER_API_KEY_PREFIXES = ("CLAUDE_CODE_USE_",)

#: A variable whose name looks like a credential never reaches the reviewer's sandboxed commands,
#: even if it is added to the allow-list below.
REVIEWER_CREDENTIAL_NAME = re.compile(
    r"TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|SESSION|COOKIE", re.IGNORECASE
)
#: The only launch-environment variables the reviewer's sandboxed commands receive (issue #189).
#: Every other name is denied, whatever it is called. Measured on Claude Code 2.1.292: a Python
#: test and git run with exactly these. The sandbox adds its own proxy and runtime variables, which
#: are not in the launch environment.
REVIEWER_ENVIRONMENT_ALLOWED = (
    "PATH",  # finds the toolchain
    "HOME",  # tools resolve ``~`` against it; the sandbox blocks reads under it
    "USER",  # some tools look up the current user
    "LOGNAME",  # the same, by its older name
    "SHELL",  # the shell commands run in
    "TERM",  # terminal-aware output
    "LANG",  # text encoding
    "LC_ALL",  # text encoding, when set
    "LC_CTYPE",  # text encoding, when set
    "TZ",  # time zone
    "TMPDIR",  # where temp files go; the sandbox sets its own
    "GIT_CONFIG_GLOBAL",  # points git at /dev/null, because home is unreadable
    "CARGO_HOME",  # issue #262: the launcher's read-only cargo home beside the copy
    "CARGO_NET_OFFLINE",  # issue #262: cargo never tries the network it is denied
    "RUSTUP_HOME",  # issue #262: a rustup proxy finds its toolchains
    "RUSTUP_TOOLCHAIN",  # issue #262: the operator's toolchain choice, when set
)
#: Credential files and directories. The sandbox blocks the whole home directory, so this list no
#: longer feeds ``denyRead``. It feeds the permission layer's ``Read`` deny rules, and the check
#: that a path allowed back re-opens none of these.
REVIEWER_CREDENTIAL_PATHS = (
    "~/.ssh",
    "~/.aws",
    "~/.config/gh",
    "~/.gnupg",
    "~/.netrc",
    "~/.docker/config.json",
    "~/.kube",
    "~/.config/gcloud",
    "~/.azure",
    "~/.claude/.credentials.json",
    "~/.codex/auth.json",
    "~/.git-credentials",
    "~/.pypirc",
    "~/.cargo/credentials",
    "~/.cargo/credentials.toml",
    "~/.terraform.d",
    "~/.vault-token",
    "~/.config/hub",
    "~/.local/share/keyrings",
    "~/.npmrc",
)
#: Directories under home that hold many tools' state; allowing one back would re-open them all.
REVIEWER_SHARED_ROOTS = ("~/.config", "~/.local", "~/.local/share", "~/.cache", "~/Library")
#: Interpreters a reviewed repository's tests run on. When one on the session's ``PATH`` lives
#: under home, its install is allowed back: a binary under a blocked home runs but cannot read its
#: own files (measured on Claude Code 2.1.292).
REVIEWER_TOOLCHAIN_COMMANDS = (
    ("python3", "python3 on the session PATH resolves here; its standard library and packages"),
    ("node", "node on the session PATH resolves here; its bundled libraries"),
    # Issue #262. A rustup proxy under ``~/.cargo``: that prefix holds cargo's credentials file,
    # so only its ``bin`` comes back, with rustup's toolchains (``reviewer_rustup_paths``). A
    # Homebrew or system cargo sits outside home and needs nothing.
    ("cargo", "cargo on the session PATH resolves here; its executables and libraries"),
    ("rustc", "rustc on the session PATH resolves here; its executables and libraries"),
)
#: The parts of a toolchain install allowed back, never the whole install.
REVIEWER_TOOLCHAIN_PARTS = (
    ("bin", "its executables"),
    ("lib", "its standard library and packages"),
    ("pyvenv.cfg", "the marker a virtual environment's interpreter reads at start"),
)
#: Paths in the scratch copy that tools write and nobody edits: Python's temp-directory fallback
#: (the sandbox denies the system temp roots, so ``tempfile`` falls back to the working directory),
#: pytest's caches and compiled bytecode; since issue #262 cargo's ``target/`` and a ``Cargo.lock``
#: that a build writes where the head has none. They never count as a change. ``.claude/`` is not among
#: them: Claude leaves only an empty ``.claude/.cc-writes/`` there (measured on 2.1.292), so a file
#: under it is one the session wrote, and saga's check refuses it.
REVIEWER_SCRATCH_IGNORED = re.compile(
    r"^(pytest-of-[^/]+/|\.pytest_cache/|tmp[a-z0-9_]{8}/|target/)|(^|/)__pycache__/|\.pyc$"
    r"|(^|/)Cargo\.lock$"
)
#: Issue #262: saga's prepare vendors the head's crates.io dependencies into the packet and
#: names them in this file. The schema and directory rules match saga's ``review_dependencies``.
REVIEWER_DEPENDENCIES_FILE = "dependencies.json"
REVIEWER_DEPENDENCIES_SCHEMA = "saga.review_dependencies.v1"
#: The start of the name the cargo home gives the vendored sources. Each launch adds a random
#: suffix, so a commit's own cargo configuration cannot name the source to redefine or chain it.
REVIEWER_VENDORED_SOURCE = "saga-vendored"


#: The change under review is untrusted. Claude acts on a project's ``.claude/`` directory (settings
#: with hooks, ``apiKeyHelper`` and environment; rules; skills and agents, whose frontmatter can
#: carry hooks) and its ``.mcp.json`` without a trust prompt in ``-p``, and hooks and MCP servers
#: run outside the command sandbox. So every one of them, at any depth, is withheld from the copy.
#: The operator's own user-level configuration is what "normal configuration" means, and it loads.
REVIEWER_UNTRUSTED_DIRS = (".claude",)
REVIEWER_UNTRUSTED_FILES = (".mcp.json",)
#: Instruction files Claude loads from the working directory and, on demand, from subdirectories.
REVIEWER_INSTRUCTION_NAMES = ("CLAUDE.md", "CLAUDE.local.md")
def _reviewer_fold(name: str) -> str:
    """A name as a forgiving file system may match it: compatibility-normalised and casefolded.

    A case-insensitive file system loads ``.CLAUDE`` as ``.claude``; folding more than any file
    system does only withholds more, never less.
    """
    return unicodedata.normalize("NFKC", name).casefold()


_REVIEWER_INSTRUCTION_NAMES = frozenset(_reviewer_fold(n) for n in REVIEWER_INSTRUCTION_NAMES)
#: How deep Claude follows ``@`` imports.
REVIEWER_IMPORT_DEPTH = 5
#: A deliberately wider net than Claude's own import parser: any ``@`` followed by text up to ASCII
#: whitespace, inside code spans or not, is treated as an import, so no import Claude follows can
#: be missed. A token is safe only when it is a plain relative path: then every reading of it,
#: whatever Claude's parser takes as its end, stays inside the copy.
_REVIEWER_ANY_IMPORT = re.compile(r"@([^ \t\n\r\f\v]+)")
_REVIEWER_IMPORT_TRAILING = "`'\")]}>.,;:!?*"
_REVIEWER_RISKY_IMPORT = re.compile(r"\.\.|~|\$|%|\\|^/|[^\x21-\x7e]")


class ReviewerRefused(Exception):
    """A reviewer launch refused before any session started."""


def reviewer_temp_roots(platform: str | None = None) -> tuple[str, ...]:
    """The system temp roots the reviewer's commands may not write to."""
    if (platform or sys.platform) == "darwin":
        return ("/tmp", "/private/tmp", "/var/folders")
    return ("/tmp", "/var/tmp")


def reviewer_denied_variables(env: Mapping[str, str]) -> list[str]:
    """The environment variables hidden from sandboxed commands: every name off the allow-list."""
    return sorted(
        name for name in env
        if name not in REVIEWER_ENVIRONMENT_ALLOWED or REVIEWER_CREDENTIAL_NAME.search(name)
    )


def reviewer_session_environment(
    env: Mapping[str, str],
    variables: Sequence[str] = REVIEWER_API_KEY_VARIABLES,
    prefixes: Sequence[str] = REVIEWER_API_KEY_PREFIXES,
) -> dict[str, str]:
    """The session's environment: everything, except what would sign in with an API key.

    *variables* and *prefixes* are the vendor's API-key names; Claude's are the defaults. Git fails
    outright when it cannot read its global configuration, and the sandbox makes the home
    directory unreadable, so git is pointed at ``/dev/null`` instead (measured on 2.1.292).
    """
    kept = {
        name: value
        for name, value in env.items()
        if name not in variables and not name.startswith(tuple(prefixes))
    }
    kept["GIT_CONFIG_GLOBAL"] = os.devnull
    return kept


def _reviewer_home(env: Mapping[str, str]) -> Path:
    return Path(env.get("HOME") or Path.home())


def _reviewer_expand(path: str, home: Path) -> Path:
    if path == "~":
        return home
    return home / path[2:] if path.startswith("~/") else Path(path)


def _reviewer_forms(path: Path) -> set[Path]:
    """*path* as written, with ``..`` collapsed, and resolved through every symlink."""
    written = Path(os.path.normpath(path))
    try:
        return {written, written.resolve()}
    except (OSError, RuntimeError):
        return {written}


def reviewer_allowed_read_problem(path: Path, home: Path) -> str | None:
    """Why allowing *path* back inside the blocked home would re-open too much, or ``None``.

    A path fails when, as written or resolved, it is the home directory or above it, is a shared
    root such as ``~/.config``, or is equal to, inside, or above a credential path. Being inside
    home is not a failure: the scratch copy lives under ``~/.cache``.
    """
    forms = _reviewer_forms(home / path)
    homes = _reviewer_forms(home)
    for form in forms:
        if any(form == h or h.is_relative_to(form) for h in homes):
            return f"{path} is the home directory or above it"
        for root in REVIEWER_SHARED_ROOTS:
            if any(form == r for h in homes for r in _reviewer_forms(_reviewer_expand(root, h))):
                return f"{path} is the shared root {root}"
        for credential in REVIEWER_CREDENTIAL_PATHS:
            for h in homes:
                for c in _reviewer_forms(_reviewer_expand(credential, h)):
                    if form == c or form.is_relative_to(c) or c.is_relative_to(form):
                        return f"{path} is, is inside, or holds the credential path {credential}"
    return None


def reviewer_toolchain_paths(
    env: Mapping[str, str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """The toolchain installs under home to allow back, and the candidates dropped, with reasons.

    For each interpreter on the session's ``PATH``, two candidates: the prefix as found (a virtual
    environment's directory) and the prefix it resolves to (the real install). A candidate outside
    home needs no allow-back; one that would re-open too much is dropped. Of a candidate kept, only
    the parts in ``REVIEWER_TOOLCHAIN_PARTS`` that exist are allowed back.
    """
    home = _reviewer_home(env)
    homes = _reviewer_forms(home)
    allowed: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    seen: set[str] = set()
    rust_under_home = False
    for command, reason in REVIEWER_TOOLCHAIN_COMMANDS:
        found = shutil.which(command, path=env.get("PATH", ""))
        if not found:
            continue
        binary = Path(os.path.normpath(Path(found).absolute()))
        if command in ("cargo", "rustc") and any(binary.is_relative_to(h) for h in homes):
            rust_under_home = True
        for candidate in (binary.parent.parent, binary.resolve().parent.parent):
            if str(candidate) in seen or not any(candidate.is_relative_to(h) for h in homes):
                continue
            seen.add(str(candidate))
            problem = reviewer_allowed_read_problem(candidate, home)
            if problem:
                dropped.append({"path": str(candidate), "reason": problem})
                # Issue #262: rustup's ``~/.cargo`` holds cargo's credentials beside ``bin/``.
                # For cargo and rustc only, the folder holding the binary comes back on its own
                # when it passes the check; any other interpreter there is still dropped.
                folder = binary.parent
                if (command in ("cargo", "rustc") and "credential path" in problem
                        and str(folder) not in seen
                        and folder.is_relative_to(candidate)
                        and reviewer_allowed_read_problem(folder, home) is None):
                    seen.add(str(folder))
                    allowed.append({"path": str(folder), "reason": f"{reason}; its executables, "
                                    "without the prefix that holds a credential path"})
                continue
            # Only the parts an interpreter reads, never the prefix itself: a prefix such as
            # ``~/.sometool`` can hold that tool's own ``.env`` beside ``bin/`` (measured: a uv
            # interpreter runs a real test with just ``bin`` and ``lib`` allowed back).
            for part, why in REVIEWER_TOOLCHAIN_PARTS:
                path = candidate / part
                if (path.exists() or path.is_symlink()) and str(path) not in seen:
                    seen.add(str(path))
                    trouble = reviewer_allowed_read_problem(path, home)
                    entry = {"path": str(path), "reason": trouble or f"{reason}; {why}"}
                    (dropped if trouble else allowed).append(entry)
    if rust_under_home:
        for path, why in reviewer_rustup_paths(env):
            if str(path) in seen:
                continue
            seen.add(str(path))
            trouble = reviewer_allowed_read_problem(path, home)
            entry = {"path": str(path), "reason": trouble or why}
            (dropped if trouble else allowed).append(entry)
    return sorted(allowed, key=lambda i: i["path"]), sorted(dropped, key=lambda i: i["path"])


def reviewer_rustup_home(env: Mapping[str, str]) -> Path:
    """The rustup home: ``RUSTUP_HOME``, or ``.rustup`` in the session's home."""
    given = env.get("RUSTUP_HOME")
    return Path(given) if given else _reviewer_home(env) / ".rustup"


def reviewer_rustup_paths(env: Mapping[str, str]) -> list[tuple[Path, str]]:
    """What a rustup proxy under home reads to run a toolchain (issue #262), when it exists.

    Only ``toolchains`` and ``settings.toml``; never the rustup home itself, which also keeps
    downloads and update state.
    """
    rustup = reviewer_rustup_home(env)
    homes = _reviewer_forms(_reviewer_home(env))
    if not any(rustup.absolute().is_relative_to(h) for h in homes):
        return []
    return [
        (rustup / part, f"rustup's {why}, which a rustup cargo or rustc runs (issue #262)")
        for part, why in (("toolchains", "installed toolchains"),
                          ("settings.toml", "default toolchain"))
        if (rustup / part).exists()
    ]


def reviewer_ceiling_problem(amount: str | None) -> str | None:
    """Why *amount* is not a dollar ceiling, or ``None``: a positive decimal, two places at most."""
    if amount is None:
        return "no --max-budget-usd was given"
    if not _REVIEWER_CEILING.fullmatch(amount) or float(amount) <= 0:
        return f"--max-budget-usd {amount!r} is not a positive dollar amount with two places at most"
    return None


#: Schema keys Claude Code 2.1.301 cannot take in ``--json-schema``. Measured: a schema declaring
#: ``"$schema": "https://json-schema.org/draft/2020-12/schema"`` is refused before the session
#: starts (``--json-schema is not a valid JSON Schema: no schema with key or ref ...``). Neither key
#: changes what the schema accepts.
REVIEWER_CLAUDE_SCHEMA_DROPPED = ("$schema", "$id")


def reviewer_claude_schema_text(answer_schema: str) -> str:
    """The answer schema as compact JSON without the keys Claude's validator cannot resolve."""
    schema = json.loads(answer_schema)
    for key in REVIEWER_CLAUDE_SCHEMA_DROPPED:
        schema.pop(key, None)
    return json.dumps(schema, separators=(",", ":"), ensure_ascii=False)


def reviewer_claude_argv(
    model: str,
    effort: str | None,
    settings_path: Path,
    *,
    max_budget_usd: str | None = None,
    executable: Path | None = None,
    prompt_path: Path | None = None,
    answer_schema: str | None = None,
) -> list[str]:
    """Claude's reviewer argv: headless, sandboxed through ``--settings``, JSON result, a ceiling.

    Issue #223: every Claude reviewer launch carries ``--max-budget-usd``; there is no default, so a
    caller that forgets one is refused. Claude runs as ``claude`` from ``PATH`` and reads its prompt
    on standard input, so *executable* and *prompt_path* are unused here.

    Issue #248: *answer_schema*, the answer schema as compact JSON text, becomes ``--json-schema``,
    so Claude validates the answer and returns it in the result's ``structured_output`` field
    instead of leaving it to a prompt line. Grok and Muse take the keyword and ignore it.
    """
    problem = reviewer_ceiling_problem(max_budget_usd)
    if problem:
        raise ReviewerRefused(f"a Claude reviewer launch needs a spending ceiling: {problem}")
    argv = ["claude", "-p", "--model", model]
    if effort:
        argv += ["--effort", effort]
    argv += [
        "--permission-mode", "dontAsk",
        "--settings", str(settings_path),
        "--output-format", "json",
        "--no-session-persistence",
    ]
    if answer_schema:
        argv += ["--json-schema", reviewer_claude_schema_text(answer_schema)]
    return argv + ["--max-budget-usd", str(max_budget_usd)]


#: Issue #225: Claude runs every Bash command, hook and MCP server as ``<prefix> '<command>'``
#: when ``CLAUDE_CODE_SHELL_PREFIX`` names a file, and only after the shell around it has read its
#: start-up files. Measured on Claude Code 2.1.296: a variable a ``BASH_ENV`` file exports reaches a
#: sandboxed command, because ``credentials.envVars`` denies only names the launch environment
#: had. The reviewer's prefix rebuilds a sandboxed command's environment from the allow-list after
#: start-up, in a bash that reads no start-up file. It lives beside the copy, never inside it.
REVIEWER_SHELL_PREFIX = "CLAUDE_CODE_SHELL_PREFIX"


def reviewer_claude_shell_paths(copy: Path) -> tuple[Path, Path]:
    """The reviewer's shell prefix and its sentinel, both beside *copy* in the launch root.

    Sandboxed commands may read the prefix's directory but not the sentinel; the prefix reads the
    sentinel to tell a hook or an MCP server, which run outside the sandbox, from a command.
    """
    root = copy.resolve().parent
    return root / "shell" / "reviewer-shell.sh", root / "unsandboxed"


def reviewer_claude_temp_dir(copy: Path) -> Path:
    """The reviewer's own temp folder, beside *copy* in the launch root and never inside it.

    The sandbox denies writes to every system temp root, and Claude's own temp directory for
    sandboxed commands sits under one of them, so without this folder a reviewer's test that
    writes a temp file fails for a reason the replay, which gives each test a writable
    ``TMPDIR``, does not share. Outside the copy, so the scratch-change comparison never sees it.
    """
    return copy.resolve().parent / "tmp"


def reviewer_claude_shell_script(sentinel: Path, token: str, temp: Path | None = None) -> str:
    """The prefix: outside the sandbox it runs the command as given; inside, on the allow-list.

    The sentinel holds *token*. Only a process outside the sandbox can read it, so anything else,
    a denied read or a missing file included, filters: the check fails closed. With *temp*, a
    sandboxed command's ``TMPDIR`` is that folder, whatever the sandbox set.
    Sandboxed commands also run under ``umask 022``, as saga's replay does; it is never reached
    outside the sandbox.
    """
    names = [n for n in REVIEWER_ENVIRONMENT_ALLOWED if not REVIEWER_CREDENTIAL_NAME.search(n)]
    for name in names:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"{name!r} is not a variable name")
    kept = " ".join(f'${{{n}+"{n}=${n}"}}' for n in names)
    if temp is not None:
        # Last, so it wins over the TMPDIR the allow-list passed on.
        kept += f" TMPDIR={shlex.quote(str(temp))}"
    read = f"/bin/cat {shlex.quote(str(sentinel))} 2>/dev/null"
    return (
        "#!/bin/sh\n"
        "# agent-launcher's reviewer shell (issue #225), written for one Claude reviewer launch.\n"
        "# Claude runs each command as: <this file> '<command>'. Outside the sandbox (a hook\n"
        "# or an MCP server) the sentinel is readable and the command runs as it would without\n"
        "# this file. Inside it, the command runs with only the reviewer's allowed variables,\n"
        "# in a bash that reads no start-up file, so nothing a start-up file exported reaches it.\n"
        f'if [ "$({read})" = {shlex.quote(token)} ]; then\n'
        '  exec /bin/sh -c "$1"\n'
        "fi\n"
        'case "${SHELL-}" in\n'
        '  */bash) reviewer_bash=$SHELL ;;\n'
        "  *) reviewer_bash=/bin/bash ;;\n"
        "esac\n"
        "# Same file-creation mask as saga's replay (RERUN_UMASK, 022), so a file the reviewer's\n"
        "# test creates gets the mode the replay gives it, not one from the launching harness.\n"
        "umask 022 || exit 1\n"
        f'exec /usr/bin/env -i {kept} "$reviewer_bash" --noprofile --norc -c "$1"\n'
    )


def reviewer_claude_materialize(
    settings: Mapping[str, Any], root: Path, copy: Path
) -> tuple[Path, dict[str, str]]:
    """Write the settings, shell prefix, sentinel and temp folder beside the copy; name the prefix."""
    path, _ = reviewer_settings_materialize(settings, root, copy)
    prefix, sentinel = reviewer_claude_shell_paths(copy)
    temp = reviewer_claude_temp_dir(copy)
    token = os.urandom(16).hex()
    sentinel.write_text(token, "utf-8")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    temp.mkdir(exist_ok=True)
    temp.chmod(0o700)
    prefix.write_text(reviewer_claude_shell_script(sentinel, token, temp), "utf-8")
    prefix.chmod(0o755)
    return path, {REVIEWER_SHELL_PREFIX: str(prefix)}


def reviewer_packet_vendor(packet: Path) -> Path | None:
    """The packet's vendored Rust sources (issue #262), or ``None`` when there are none to trust.

    The entry counts only when it says ``fetched`` and names a relative directory inside the
    packet that exists, with no symlink anywhere along the way. Anything else is ignored and the
    reviewer runs without it.
    """
    try:
        data = json.loads((packet / REVIEWER_DEPENDENCIES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != REVIEWER_DEPENDENCIES_SCHEMA:
        return None
    entry = data.get("rust")
    if not isinstance(entry, dict) or entry.get("state") != "fetched":
        return None
    relative = entry.get("directory")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None
    parts = Path(relative).parts
    if any(part in ("", ".", "..") for part in parts) or packet.is_symlink():
        return None
    cursor = packet
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return None
    if not cursor.is_dir() or not _reviewer_inside(cursor, packet):
        return None
    return cursor.resolve()


def reviewer_cargo_config(vendor: Path | None, source: str = REVIEWER_VENDORED_SOURCE) -> str:
    """The reviewer's cargo ``config.toml``: offline, and crates.io replaced by *vendor* if given.

    Measured on cargo 1.98.1 (issue #262): ``CARGO_SOURCE_*`` variables alone do not replace a
    source, a ``config.toml`` in ``CARGO_HOME`` does, and cargo builds offline from a directory
    source with that home and the vendored tree both read-only.
    """
    lines = ["# Written by agent-launcher for an offline review (issue #262).", ""]
    if vendor is not None:
        lines += [
            "[source.crates-io]",
            f"replace-with = {json.dumps(source)}",
            "",
            f"[source.{json.dumps(source)}]",
            f"directory = {json.dumps(str(vendor))}",
            "",
        ]
    return "\n".join(lines + ["[net]", "offline = true", ""])


def reviewer_cargo_shim(cargo: str, config: Path) -> str:
    """A ``cargo`` that runs *cargo* with *config* passed as ``--config`` (issue #262).

    Measured on cargo 1.98.1: a commit's own ``.cargo/config.toml`` that replaces crates.io
    outranks both the ``CARGO_HOME`` configuration and ``CARGO_SOURCE_*`` variables, and only
    ``--config`` outranks it. A rustup ``+toolchain`` argument has to stay first.
    """
    real, given = shlex.quote(cargo), shlex.quote(str(config))
    return (
        "#!/bin/sh\n"
        "# Written by agent-launcher for an offline review (issue #262): this cargo home's\n"
        "# configuration outranks the commit's own.\n"
        'case "${1-}" in\n'
        f'  +*) toolchain=$1; shift; exec {real} "$toolchain" --config {given} "$@" ;;\n'
        "esac\n"
        f'exec {real} --config {given} "$@"\n'
    )


def reviewer_cargo_home(
    root: Path, vendor: Path | None, env: Mapping[str, str] | None = None
) -> Path:
    """Write the reviewer's cargo home beside the copy, never in it, with a read-only config.

    It is made even without vendored sources, so the reviewer's cargo never looks for the
    operator's ``~/.cargo``. When *env*'s ``PATH`` finds a cargo, ``bin/cargo`` is a
    :func:`reviewer_cargo_shim` around it.
    """
    home = root / "cargo-home"
    home.mkdir(parents=True, exist_ok=True)
    config = home / "config.toml"
    source = f"{REVIEWER_VENDORED_SOURCE}-{os.urandom(8).hex()}"
    config.write_text(reviewer_cargo_config(vendor, source), "utf-8")
    config.chmod(0o444)
    found = shutil.which("cargo", path=env.get("PATH", "")) if env is not None else None
    if found:
        shim = home / "bin" / "cargo"
        shim.parent.mkdir(exist_ok=True)
        shim.write_text(reviewer_cargo_shim(str(Path(found).absolute()), config), "utf-8")
        shim.chmod(0o555)
    return home


def reviewer_offline_cargo(session_env: dict[str, str], cargo_home: Path) -> None:
    """Point the session's cargo at *cargo_home*, offline, with its shim first on ``PATH``.

    Both cargo values replace the operator's, whatever they were.
    """
    session_env["CARGO_HOME"] = str(cargo_home)
    session_env["CARGO_NET_OFFLINE"] = "true"
    # A rustup proxy picks its toolchain from here; the shell prefix passes both names.
    session_env["RUSTUP_HOME"] = str(reviewer_rustup_home(session_env))
    shim = cargo_home / "bin" / "cargo"
    if shim.is_file():
        session_env["PATH"] = os.pathsep.join(
            [str(shim.parent)] + ([session_env["PATH"]] if session_env.get("PATH") else [])
        )


def reviewer_claude_settings(
    copy: Path,
    packet: Path,
    env: Mapping[str, str],
    *,
    toolchain: Sequence[Mapping[str, str]] | None = None,
    extra_deny_read: Sequence[str] = (),
    platform: str | None = None,
    read_only: Sequence[str] = (),
) -> dict[str, Any]:
    """The per-launch settings that turn on Claude's command sandbox and confine the session.

    Measured on Claude Code 2.1.292 on 2026-10-06: under ``dontAsk`` Bash is denied unless allowed,
    even with ``autoAllowBashIfSandboxed``; the sandbox's own temp directory stays writable until a
    ``denyWrite`` names its root; any variable reaches sandboxed commands until
    ``credentials.envVars`` denies it by name. Issue #189 measured that ``denyRead: ["~"]`` blocks
    the whole home directory and ``allowRead`` re-opens a path inside it, so commands read only the
    copy, the packet and the toolchain *toolchain* names (derived from *env* when not given). The
    settings set no ``apiKeyHelper``, plugins or hooks, so the user's own configuration is what
    loads.

    Issue #225: commands run through the reviewer's shell prefix, whose directory is readable and
    whose sentinel is denied by name, so the prefix filters even when the launch root is outside
    the home directory. The prefix is named in ``env`` as well, which outranks the user's settings.

    The one write allowed beyond the copy is the reviewer's own temp folder
    (:func:`reviewer_claude_temp_dir`), read back as well and under no denied temp root. Claude's
    file Write and Edit tools may write there too, through their own permission rule, because the
    launch message names it as the reviewer's draft folder: its answer draft and saved run outputs
    belong outside the copy, where the scratch-change comparison never sees them.

    Issue #262: *read_only* (the cargo home and the vendored dependencies) is allowed back for
    reading and named in ``denyWrite``, so read-only is stated rather than implied.
    """
    if toolchain is None:
        toolchain = reviewer_toolchain_paths(env)[0]
    prefix, sentinel = reviewer_claude_shell_paths(copy)
    temp = reviewer_claude_temp_dir(copy)
    allow_read = [str(copy.resolve()), str(packet.resolve()), str(prefix.parent)]
    allow_read += [item["path"] for item in toolchain if item["path"] not in allow_read]
    allow_read += [path for path in read_only if path not in allow_read]
    allow_read.append(str(temp))
    return {
        "env": {REVIEWER_SHELL_PREFIX: str(prefix)},
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "filesystem": {
                "denyWrite": list(reviewer_temp_roots(platform)) + list(read_only),
                "denyRead": ["~"] + list(extra_deny_read) + [str(sentinel)],
                "allowRead": allow_read,
                "allowWrite": [str(temp)],
            },
            "network": {"strictAllowlist": True, "allowedDomains": []},
            "credentials": {
                "envVars": [
                    {"name": name, "mode": "deny"} for name in reviewer_denied_variables(env)
                ]
            },
        },
        "permissions": {
            # ``//`` starts an absolute path in a permission rule; ``/`` is relative to the settings
            # file. ``packet.resolve()`` begins with ``/``, so this reads ``Read(//<packet>/**)``.
            # The temp folder is written the same way, so file Write and Edit may use it.
            "allow": [
                "Bash", "Edit(./**)", f"Edit(/{temp}/**)", f"Read(/{packet.resolve()}/**)",
            ],
            "deny": ["WebFetch", "WebSearch", "mcp__*"]
            + [f"Read({path})" for path in list(REVIEWER_CREDENTIAL_PATHS) + list(extra_deny_read)],
        },
    }


def reviewer_parse_claude_result(stdout: str) -> dict[str, Any]:
    """Usage, resolved models and the final message from ``claude -p --output-format json``."""
    try:
        data = json.loads(stdout)
    except (TypeError, ValueError):
        return {"usage": None, "resolved": [], "final": None, "is_error": True,
                "error": "the session printed no JSON result"}
    if not isinstance(data, dict):
        return {"usage": None, "resolved": [], "final": None, "is_error": True,
                "error": "the session's result is not a JSON object"}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    duration = data.get("duration_ms")
    model_usage = data.get("modelUsage")
    return {
        "usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "cost_usd": data.get("total_cost_usd"),
            "seconds": duration / 1000 if isinstance(duration, (int, float)) else None,
            "turns": data.get("num_turns"),
            "session_id": data.get("session_id"),
        },
        "resolved": sorted(model_usage) if isinstance(model_usage, dict) else [],
        "final": data.get("result") if isinstance(data.get("result"), str) else None,
        # Issue #248: with ``--json-schema`` the validated answer is this object. Measured on
        # Claude Code 2.1.301: a model that never satisfied the schema leaves the key out and
        # still reports ``subtype: success``, so only the key's absence says there is none.
        "structured": (
            data["structured_output"] if isinstance(data.get("structured_output"), dict) else None
        ),
        "is_error": bool(data.get("is_error")),
        "error": None if not data.get("is_error") else str(data.get("subtype") or "error"),
    }


def _reviewer_read(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def _reviewer_inside(path: Path, copy: Path) -> bool:
    try:
        return path.resolve().is_relative_to(copy.resolve())
    except (OSError, RuntimeError):
        return False


def _reviewer_risky_imports(content: bytes) -> list[str]:
    """``@`` tokens that are not plain relative paths: each could name a file outside the copy."""
    tokens = _REVIEWER_ANY_IMPORT.findall(content.decode("utf-8", "replace"))
    return [token for token in tokens if _REVIEWER_RISKY_IMPORT.search(token)]


def _reviewer_import_targets(content: bytes, parent: Path) -> list[tuple[str, Path]]:
    """Every ``@`` token in *content* that could be an import, with the path it would name."""
    found: list[tuple[str, Path]] = []
    for raw in _REVIEWER_ANY_IMPORT.findall(content.decode("utf-8", "replace")):
        token = raw.rstrip(_REVIEWER_IMPORT_TRAILING)
        if not token:
            continue
        target = Path(token).expanduser() if token.startswith("~") else parent / token
        found.append((token, target))
    return found


def _reviewer_imports_leave(start: Path, copy: Path) -> bool:
    """Whether *start*'s possible imports, followed as Claude follows them, can leave *copy*."""
    frontier, seen = [start], set()
    for _ in range(REVIEWER_IMPORT_DEPTH + 1):
        following: list[Path] = []
        for path in frontier:
            if path in seen:
                continue
            seen.add(path)
            if path.is_symlink() and not _reviewer_inside(path, copy):
                return True
            content = _reviewer_read(path) if _reviewer_inside(path, copy) else None
            if content is None:
                continue
            if _reviewer_risky_imports(content):
                return True
            for _token, target in _reviewer_import_targets(content, path.parent):
                if not _reviewer_inside(target, copy):
                    return True
                following.append(target)
        frontier = following
    return False


def reviewer_withhold_untrusted(
    copy: Path,
    dirs: Sequence[str] = REVIEWER_UNTRUSTED_DIRS,
    files: Sequence[str] = REVIEWER_UNTRUSTED_FILES,
    instructions: Sequence[str] = REVIEWER_INSTRUCTION_NAMES,
) -> list[str]:
    """Remove what the reviewed change could use to run or read outside the sandbox.

    *dirs*, *files* and *instructions* are the vendor's untrusted names; Claude's are the defaults.

    Every ``.claude/`` directory and ``.mcp.json`` at any depth (Claude acts on them outside the
    command sandbox), every symlink that leaves the copy, and every instruction file whose possible
    ``@`` imports can leave the copy (Claude would load the imported file, a credential for example,
    into the reviewer's context). Returns each withheld path with the reason; the reviewer still
    sees them in the packet's diff.
    """
    withheld: list[str] = []
    dir_names = frozenset(_reviewer_fold(n) for n in dirs)
    file_names = frozenset(_reviewer_fold(n) for n in files)
    instruction_names = frozenset(_reviewer_fold(n) for n in instructions)

    def drop(path: Path, why: str) -> None:
        withheld.append(f"{path.relative_to(copy).as_posix()} ({why})")
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()

    for path in sorted(copy.rglob("*")):
        if not (path.exists() or path.is_symlink()):
            continue  # inside a directory already withheld
        name = _reviewer_fold(path.name)
        if name in dir_names and (path.is_dir() or path.is_symlink()):
            drop(path, "Claude would act on it outside the sandbox")
        elif name in file_names:
            drop(path, "Claude would act on it outside the sandbox")
        elif path.is_symlink() and not _reviewer_inside(path, copy):
            drop(path, "a symlink out of the copy")
    for path in sorted(copy.rglob("*")):
        if _reviewer_fold(path.name) in instruction_names and path.is_file() and (
            _reviewer_imports_leave(path, copy)
        ):
            drop(path, "it can import a file outside the copy")
    return withheld


def reviewer_claude_widening(env: Mapping[str, str]) -> list[str]:
    """Settings outside the copy that would widen the reviewer's sandbox.

    ``--settings`` overrides scalar keys, but list keys merge across levels, and managed settings
    outrank it. So a user, local or managed setting that excludes commands from the sandbox, allows
    a domain, a write or a read, adds a working directory, or turns the sandbox off would carry into
    the session; the launch refuses rather than run a review it cannot confine.
    """
    home = Path(env.get("HOME") or Path.home())
    base = Path(env["CLAUDE_CONFIG_DIR"]) if env.get("CLAUDE_CONFIG_DIR") else home / ".claude"
    files = [
        base / "settings.json",
        base / "settings.local.json",
        Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
        Path("/etc/claude-code/managed-settings.json"),
    ]
    problems: list[str] = []
    for path in files:
        if not path.exists():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Claude may read a file this strict parser cannot (comments, trailing commas); a
            # setting unchecked could widen the sandbox, so an unreadable file refuses the launch.
            problems.append(f"{path} cannot be read as JSON to check it")
            continue
        if not isinstance(loaded, dict):
            problems.append(f"{path} is not a JSON object")
            continue
        sandbox = loaded.get("sandbox") if isinstance(loaded.get("sandbox"), dict) else {}
        network = sandbox.get("network") if isinstance(sandbox.get("network"), dict) else {}
        filesystem = (
            sandbox.get("filesystem") if isinstance(sandbox.get("filesystem"), dict) else {}
        )
        permissions = (
            loaded.get("permissions") if isinstance(loaded.get("permissions"), dict) else {}
        )
        widening = {
            "sandbox.excludedCommands": sandbox.get("excludedCommands"),
            "sandbox.network.allowedDomains": network.get("allowedDomains"),
            "sandbox.filesystem.allowWrite": filesystem.get("allowWrite"),
            "sandbox.filesystem.allowRead": filesystem.get("allowRead"),
            "permissions.additionalDirectories": permissions.get("additionalDirectories"),
        }
        for key, value in widening.items():
            if value:
                problems.append(f"{path.name} sets {key}")
        if sandbox.get("enabled") is False and "managed" in path.name:
            problems.append(f"{path.name} turns the sandbox off")
        if filesystem.get("disabled") is True:
            problems.append(f"{path.name} sets sandbox.filesystem.disabled")
        # Issue #225: managed settings outrank ``--settings``, so a shell prefix set there would
        # replace the one that keeps start-up exports out of sandboxed commands.
        environment = loaded.get("env") if isinstance(loaded.get("env"), dict) else {}
        if REVIEWER_SHELL_PREFIX in environment:
            problems.append(f"{path.name} sets env.{REVIEWER_SHELL_PREFIX}")
    return problems


def reviewer_claude_config_sources(
    copy: Path, env: Mapping[str, str]
) -> list[tuple[str, bytes | None]]:
    """What Claude's normal configuration loads, as ``(label, content)`` pairs.

    The user's and the project's instruction files, each file they import with ``@path`` one level
    deep, and the enabled plugins with their installed versions. A missing file is recorded as
    absent, so creating one changes the fingerprint. Labels never carry an absolute path.
    """
    home = Path(env.get("HOME") or Path.home())
    base = Path(env["CLAUDE_CONFIG_DIR"]) if env.get("CLAUDE_CONFIG_DIR") else home / ".claude"
    files = [
        ("user:CLAUDE.md", base / "CLAUDE.md"),
        ("project:CLAUDE.md", copy / "CLAUDE.md"),
    ] + [
        (f"project:{path.relative_to(copy).as_posix()}", path)
        for path in sorted(copy.rglob("*"))
        if _reviewer_fold(path.name) in _REVIEWER_INSTRUCTION_NAMES and path != copy / "CLAUDE.md"
    ]
    sources: list[tuple[str, bytes | None]] = []
    for label, path in files:
        content = _reviewer_read(path)
        sources.append((label, content))
        if content is None:
            continue
        for token, target in sorted(set(_reviewer_import_targets(content, path.parent))):
            if label.startswith("project:") and not _reviewer_inside(target, copy):
                # Never read a file the reviewed change points at outside the copy.
                sources.append((f"import:{label}:{token}", b"outside the copy"))
                continue
            sources.append((f"import:{label}:{token}", _reviewer_read(target)))

    enabled: set[str] = set()
    for settings in (base / "settings.json", copy / ".claude" / "settings.json"):
        try:
            loaded = json.loads(settings.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        plugins = loaded.get("enabledPlugins") if isinstance(loaded, dict) else None
        if isinstance(plugins, dict):
            enabled |= {str(name) for name, on in plugins.items() if on is True}
    try:
        installed = json.loads((base / "plugins" / "installed_plugins.json").read_text("utf-8"))
    except (OSError, ValueError):
        installed = {}
    entries = installed.get("plugins", {}) if isinstance(installed, dict) else {}
    for name in sorted(enabled):
        rows = entries.get(name) if isinstance(entries, dict) else None
        versions = sorted(
            f"{row.get('version')}@{row.get('gitCommitSha') or ''}"
            for row in (rows or [])
            if isinstance(row, dict)
        )
        sources.append((f"plugin:{name}", ",".join(versions).encode("utf-8")))
    return sources


def reviewer_configuration_fingerprint(
    sources: Sequence[tuple[str, bytes | None]],
) -> dict[str, Any]:
    """SHA-256 over the sorted ``(label, content digest)`` pairs, and the labels that went in.

    ``source_digests`` names the digest that went into each label, so two runs whose
    fingerprint differs can be told apart by the source that changed. It reuses the
    sorted pairs the fingerprint itself is computed from, so it carries the same order
    and the same tie-breaking as ``sources``. A source that was absent contributes the
    literal ``absent``. Only digests are kept, never the content they came from.
    """
    pairs = sorted(
        (label, hashlib.sha256(content).hexdigest() if content is not None else "absent")
        for label, content in sources
    )
    digest = hashlib.sha256(json.dumps(pairs, separators=(",", ":")).encode("utf-8"))
    return {
        "fingerprint": digest.hexdigest(),
        "sources": [label for label, _ in pairs],
        "source_digests": [{"label": label, "sha256": sha256} for label, sha256 in pairs],
    }


#: The first bytes of a native executable (Mach-O, thin or fat, either byte order; ELF). A
#: reviewer whose executable is bound to a probe record must be one of these, never a script that
#: picks another binary at run time.
_REVIEWER_NATIVE_MAGIC = (
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\x7fELF",
)


def reviewer_is_native(path: Path) -> bool:
    """Whether *path* is a regular file that starts like a native executable."""
    try:
        with path.open("rb") as handle:
            return path.is_file() and handle.read(4) in _REVIEWER_NATIVE_MAGIC
    except OSError:
        return False


def _reviewer_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def reviewer_executable_file(path: Path) -> dict[str, str]:
    """The file's name and SHA-256, read as bytes; nothing runs it.

    The name is the file name only, never a path, because records are committed to a public
    repository.
    """
    return {"name": path.name, "sha256": _reviewer_sha256(path)}


def reviewer_executable_identity(path: Path, env: Mapping[str, str]) -> dict[str, str]:
    """The identity a probe record binds: the file's name, its SHA-256 and what it reports.

    It runs *path* with ``--version``, outside any sandbox, so a bound recipe calls it only on the
    pinned copy whose bytes were already compared (issue #223's review, finding 2).
    """
    version = _reviewer_vendor_version(str(path), env) or ""
    return {**reviewer_executable_file(path), "version": version}


def reviewer_grok_executable(env: Mapping[str, str]) -> Path:
    """Grok's own native executable, never a wrapper script in front of it.

    Grok installs itself under its home directory (``bin/grok``, a link into ``downloads/``); a
    ``grok`` on ``PATH`` may be a local wrapper that adds flags such as ``--trust``.
    """
    grok_home = Path(env["GROK_HOME"]) if env.get("GROK_HOME") else _reviewer_home(env) / ".grok"
    candidates = [grok_home / "bin" / "grok"]
    found = shutil.which("grok", path=env.get("PATH", ""))
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate
        if reviewer_is_native(resolved):
            return resolved
    raise ReviewerRefused("no native grok executable was found to bind to a probe record")


def reviewer_muse_executable(env: Mapping[str, str]) -> Path:
    """Muse's versioned native binary, never the ``muse`` launcher script that updates it.

    The launcher script keeps the active version in ``.muse-version`` beside itself and runs
    ``muse-bin-<version>``; running that binary directly means no update happens mid-review.
    """
    found = shutil.which("muse", path=env.get("PATH", ""))
    if not found:
        raise ReviewerRefused("muse is not on PATH")
    resolved = Path(found).resolve()
    if reviewer_is_native(resolved):
        return resolved
    marker = resolved.parent / ".muse-version"
    try:
        version = marker.read_text(encoding="utf-8").strip()
    except OSError:
        version = ""
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-R[0-9]+(\.[0-9]+)?", version):
        binary = resolved.parent / f"muse-bin-{version}"
        if reviewer_is_native(binary):
            return binary
    raise ReviewerRefused("no native muse binary was found beside the muse launcher script")


def _reviewer_user_files(
    env: Mapping[str, str], files: Sequence[tuple[str, str]]
) -> list[tuple[str, bytes | None]]:
    home = _reviewer_home(env)
    return [(label, _reviewer_read(_reviewer_expand(path, home))) for label, path in files]


def reviewer_grok_profile_name(settings_path: Path) -> str:
    """A per-launch sandbox profile name, so no user profile of the same name can shadow it."""
    return "reviewer-" + hashlib.sha256(str(settings_path).encode("utf-8")).hexdigest()[:16]


def reviewer_grok_argv(
    model: str,
    effort: str | None,
    settings_path: Path,
    *,
    max_budget_usd: str | None = None,
    executable: Path | None = None,
    prompt_path: Path | None = None,
    answer_schema: str | None = None,
) -> list[str]:
    """Grok's reviewer argv, from grok 1.0.50's ``--help`` and headless guide.

    Headless mode does not read standard input, so the message goes by ``--prompt-file``. Plan
    mode is off, Bash is allowed by rule under ``dontAsk`` (never ``--always-approve``), and the
    sandbox is the per-launch profile written into the copy's ``.grok/sandbox.toml``.
    """
    if max_budget_usd is not None:
        raise ReviewerRefused("grok has no dollar ceiling; --max-budget-usd cannot be honoured")
    if executable is None or prompt_path is None:
        raise ReviewerRefused("a grok reviewer launch needs its verified executable and prompt")
    argv = [str(executable), "--prompt-file", str(prompt_path), "-m", model]
    if effort:
        argv += ["--reasoning-effort", effort]
    return argv + [
        "--sandbox", reviewer_grok_profile_name(settings_path),
        "--no-plan",
        "--permission-mode", "dontAsk",
        "--allow", "Bash",
        "--disable-web-search",
        "--output-format", "json",
    ]


def reviewer_grok_settings(
    copy: Path,
    packet: Path,
    env: Mapping[str, str],
    *,
    toolchain: Sequence[Mapping[str, str]] | None = None,
    extra_deny_read: Sequence[str] = (),
    platform: str | None = None,
    read_only: Sequence[str] = (),
) -> dict[str, Any]:
    """Grok's per-launch sandbox profile and the environment overlay for its commands.

    The profile extends ``strict`` (reads the working directory, system paths and the Grok home;
    writes the working directory, ``~/.grok/sessions`` and temp), blocks child network, grants
    the packet, the prompt and the toolchain read-only, and denies the temp roots, Grok's sign-in
    file and anything *extra_deny_read* names. The overlay keeps only the allow-listed variables
    in Grok's tool commands.
    """
    if toolchain is None:
        toolchain = reviewer_toolchain_paths(env)[0]
    home = _reviewer_home(env)
    granted = [str(packet.resolve()), str((copy.parent / "prompt").resolve())]
    granted += [item["path"] for item in toolchain if item["path"] not in granted]
    granted += [path for path in read_only if path not in granted]
    deny = list(reviewer_temp_roots(platform)) + [
        str(_reviewer_expand(path, home)) for path in REVIEWER_GROK_CREDENTIAL_FILES
    ] + list(extra_deny_read)
    return {
        "profile": {
            "extends": "strict",
            "restrict_network": True,
            "read_only": granted,
            "deny": deny,
        },
        "overlay": {
            "shell_environment_policy": {
                "inherit": "all",
                "ignore_default_excludes": False,
                "include_only": list(REVIEWER_ENVIRONMENT_ALLOWED),
            }
        },
    }


def _reviewer_toml_string(value: str) -> str:
    return json.dumps(value)  # a JSON string is a valid TOML basic string


def reviewer_grok_materialize(
    settings: Mapping[str, Any], root: Path, copy: Path
) -> tuple[Path, dict[str, str]]:
    """Write the profile into the copy's ``.grok/sandbox.toml``; return it and the overlay.

    Grok reads custom profiles only from a user or project ``sandbox.toml``, and the reviewed
    change's own ``.grok/`` has already been withheld, so this file is the launcher's.
    """
    path = copy / ".grok" / "sandbox.toml"
    profile = settings["profile"]
    lines = [f"[profiles.{reviewer_grok_profile_name(path)}]"]
    lines.append(f"extends = {_reviewer_toml_string(profile['extends'])}")
    lines.append(f"restrict_network = {'true' if profile['restrict_network'] else 'false'}")
    for key in ("read_only", "deny"):
        items = ", ".join(_reviewer_toml_string(item) for item in profile[key])
        lines.append(f"{key} = [{items}]")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", "utf-8")
    return path, {"GROK_CONFIG": json.dumps(settings["overlay"], separators=(",", ":"))}


def reviewer_grok_widening(env: Mapping[str, str]) -> list[str]:
    """Grok configuration that would sign the review in with an API key, or widen it.

    Grok's authentication guide ranks a per-model ``api_key`` or ``env_key`` in ``config.toml``
    above the signed-in session; with one set, removing ``XAI_API_KEY`` does not make the review
    use the subscription.
    """
    import tomllib

    grok_home = Path(env["GROK_HOME"]) if env.get("GROK_HOME") else _reviewer_home(env) / ".grok"
    path = grok_home / "config.toml"
    if not path.exists():
        return []
    try:
        loaded = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"{path.name} cannot be read as TOML to check it"]
    models = loaded.get("model") if isinstance(loaded.get("model"), dict) else {}
    return [
        f"config.toml sets {key} for model {name}"
        for name, table in sorted(models.items())
        if isinstance(table, dict)
        for key in ("api_key", "env_key")
        if table.get(key)
    ]


def reviewer_parse_grok_result(stdout: str) -> dict[str, Any]:
    """Usage, resolved models and the final message from ``grok --output-format json``."""
    try:
        data = json.loads(stdout)
    except (TypeError, ValueError):
        return {"usage": None, "resolved": [], "final": None, "is_error": True,
                "error": "the session printed no JSON result"}
    if not isinstance(data, dict):
        return {"usage": None, "resolved": [], "final": None, "is_error": True,
                "error": "the session's result is not a JSON object"}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    model_usage = data.get("modelUsage")
    stop = data.get("stopReason")
    final = data.get("text") if isinstance(data.get("text"), str) else None
    is_error = stop != "end_turn"
    return {
        "usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "cost_usd": data.get("total_cost_usd"),
            "seconds": None,
            "turns": data.get("num_turns"),
            "session_id": data.get("sessionId"),
        },
        "resolved": sorted(model_usage) if isinstance(model_usage, dict) else [],
        "final": final,
        "is_error": is_error,
        "error": f"the session stopped with {stop!r}" if is_error else None,
    }


def reviewer_grok_config_sources(
    copy: Path, env: Mapping[str, str]
) -> list[tuple[str, bytes | None]]:
    """Grok's user configuration: its settings and its own sandbox profiles."""
    return _reviewer_user_files(
        env, [("user:config.toml", "~/.grok/config.toml"), ("user:sandbox.toml",
                                                             "~/.grok/sandbox.toml")]
    )


def reviewer_muse_argv(
    model: str,
    effort: str | None,
    settings_path: Path,
    *,
    max_budget_usd: str | None = None,
    executable: Path | None = None,
    prompt_path: Path | None = None,
    answer_schema: str | None = None,
) -> list[str]:
    """Muse's reviewer argv, from muse 1.4.6's ``exec --help``.

    The sandbox and approvals stay on (their defaults); the network sandbox is ``restricted``,
    web tools are off and no session log is written. ``--permission-profile`` cannot be combined
    with ``--sandbox-network`` (measured), so the network setting is the one passed.
    """
    if max_budget_usd is not None:
        raise ReviewerRefused("muse has no dollar ceiling; --max-budget-usd cannot be honoured")
    if executable is None or prompt_path is None:
        raise ReviewerRefused("a muse reviewer launch needs its verified executable and prompt")
    argv = [str(executable), "exec", "--model", model]
    if effort:
        argv += ["--reasoning-effort", effort]
    return argv + [
        "--json",
        "--prompt-file", str(prompt_path),
        "--sandbox-network", "restricted",
        "--disable-web-tools",
        "--no-session-log",
    ]


def reviewer_muse_settings(
    copy: Path,
    packet: Path,
    env: Mapping[str, str],
    *,
    toolchain: Sequence[Mapping[str, str]] | None = None,
    extra_deny_read: Sequence[str] = (),
    platform: str | None = None,
    read_only: Sequence[str] = (),
) -> dict[str, Any]:
    """What the Muse launch asks of its sandbox, for the record: Muse takes it as flags."""
    return {"sandbox": "default (on)", "sandbox_network": "restricted", "web_tools": "disabled"}


def reviewer_parse_muse_result(stdout: str) -> dict[str, Any]:
    """The final message and model from ``muse exec --json``; Muse reports no usage there."""
    final: str | None = None
    terminal: str | None = None
    reason: Any = None
    resolved: set[str] = set()
    for line in (stdout or "").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        kind = record.get("payload_type")
        try:
            payload = record.get("payload")
            payload = json.loads(payload) if isinstance(payload, str) else payload
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        if kind == "run.model.configured" and isinstance(payload.get("model_id"), str):
            resolved.add(payload["model_id"])
        elif kind is not None and str(kind).startswith("run.terminal."):
            terminal = payload.get("terminal") if isinstance(payload.get("terminal"), str) else None
            final = payload.get("text") if isinstance(payload.get("text"), str) else None
            reason = payload.get("reason")
    if terminal is None:
        return {"usage": None, "resolved": sorted(resolved), "final": None, "is_error": True,
                "error": "the session printed no terminal event"}
    is_error = terminal != "completed"
    return {
        "usage": None,
        "resolved": sorted(resolved),
        "final": final,
        "is_error": is_error,
        "error": f"the run ended {terminal}: {reason}" if is_error else None,
    }


def reviewer_muse_config_sources(
    copy: Path, env: Mapping[str, str]
) -> list[tuple[str, bytes | None]]:
    """Muse's user configuration: its settings and its approval policy."""
    return _reviewer_user_files(
        env, [("user:settings.json", "~/.config/muse/settings.json"),
              ("user:approval-policy.json", "~/.config/muse/approval-policy.json")]
    )


def reviewer_settings_materialize(
    settings: Mapping[str, Any], root: Path, copy: Path
) -> tuple[Path, dict[str, str]]:
    """Write the settings beside the copy, never inside it; no extra environment."""
    path = root / "settings.json"
    path.write_text(json.dumps(settings, indent=2) + "\n", "utf-8")
    return path, {}


#: Grok's own sign-in and configuration files (its authentication guide: ``auth.json`` holds the
#: session token and ``config.toml`` may hold a per-model ``api_key``).
REVIEWER_GROK_CREDENTIAL_FILES = ("~/.grok/auth.json", "~/.grok/config.toml")


@dataclass(frozen=True)
class ReviewerRecipe:
    """How one vendor runs the targeted reviewer: argv, sandbox settings, result, configuration.

    Issue #223 moved what differs between vendors into fields, so the launch never branches on a
    vendor's name. Every default but ``materialize`` is Claude's (issue #225 gave Claude its own).
    """

    binary: str
    argv: Any
    settings: Any
    parse: Any
    config_sources: Any
    #: Variables that would sign the session in with an API key; removed from its environment.
    api_key_variables: tuple[str, ...] = REVIEWER_API_KEY_VARIABLES
    api_key_prefixes: tuple[str, ...] = REVIEWER_API_KEY_PREFIXES
    #: Project names the vendor would act on outside its sandbox; withheld from the copy.
    untrusted_dirs: tuple[str, ...] = REVIEWER_UNTRUSTED_DIRS
    untrusted_files: tuple[str, ...] = REVIEWER_UNTRUSTED_FILES
    instruction_names: tuple[str, ...] = REVIEWER_INSTRUCTION_NAMES
    #: ``stdin``, or ``file`` when the vendor reads its prompt from a file it is given.
    prompt_via: str = "stdin"
    #: The vendor's own sign-in files, which a sandboxed command must not read.
    credential_files: tuple[str, ...] = ()
    #: The vendor's own state directory, where the probe plants a read canary.
    vendor_home: str | None = None
    #: A directory under it that the probe tries to write.
    vendor_writable: str | None = None
    #: The model ``reviewer-probe`` uses when none is given.
    probe_model: str = "haiku"
    #: The platforms a live probe passed on; ``None`` for any (Claude's recipe predates records).
    platforms: tuple[str, ...] | None = None
    #: Whether the vendor takes a dollar ceiling; one is then required on every launch.
    takes_ceiling: bool = False
    #: Configuration outside the copy that would widen the sandbox or change the sign-in.
    widening: Any = None
    #: Writes the settings and returns the path the argv names, plus environment to add.
    materialize: Any = reviewer_settings_materialize
    #: Resolves the native executable a probe record binds; ``None`` runs ``binary`` from PATH.
    executable: Any = None
    #: Maps the copy to the temp folder the sandbox leaves writable; ``None`` leaves none, and the
    #: probe then proves a write to ``TMPDIR`` is denied.
    temp_dir: Any = None


REVIEWER_CLAUDE_RECIPE = ReviewerRecipe(
    binary="claude",
    argv=reviewer_claude_argv,
    settings=reviewer_claude_settings,
    parse=reviewer_parse_claude_result,
    config_sources=reviewer_claude_config_sources,
    credential_files=("~/.claude/.credentials.json",),
    vendor_home="~/.claude",
    vendor_writable="~/.claude",
    takes_ceiling=True,
    widening=reviewer_claude_widening,
    # Issue #225: commands run through the shell prefix that keeps start-up exports out.
    materialize=reviewer_claude_materialize,
    # The replay gives each test a writable TMPDIR; the reviewer gets one beside its copy.
    temp_dir=reviewer_claude_temp_dir,
)

#: Recipes ``reviewer-probe`` may run but ``review`` never does (issue #223, plan KTD1). A
#: candidate reviews only once a committed probe record for its executable and platform admits it.
REVIEWER_CANDIDATES: dict[str, ReviewerRecipe] = {
    "grok": ReviewerRecipe(
        binary="grok",
        argv=reviewer_grok_argv,
        settings=reviewer_grok_settings,
        parse=reviewer_parse_grok_result,
        config_sources=reviewer_grok_config_sources,
        api_key_variables=("XAI_API_KEY", "GROK_DEPLOYMENT_KEY"),
        api_key_prefixes=(),
        # In an untrusted directory grok 1.0.50 loads no project instructions, MCP servers or
        # hooks (measured with ``grok inspect``); withholding them as well costs nothing.
        untrusted_dirs=(".grok", ".claude", ".cursor"),
        untrusted_files=(".mcp.json",),
        instruction_names=("AGENTS.md", "CLAUDE.md", "CLAUDE.local.md"),
        prompt_via="file",
        credential_files=REVIEWER_GROK_CREDENTIAL_FILES,
        vendor_home="~/.grok",
        vendor_writable="~/.grok/sessions",
        probe_model="grok-4.7",
        widening=reviewer_grok_widening,
        materialize=reviewer_grok_materialize,
        executable=reviewer_grok_executable,
    ),
    "muse": ReviewerRecipe(
        binary="muse",
        argv=reviewer_muse_argv,
        settings=reviewer_muse_settings,
        parse=reviewer_parse_muse_result,
        config_sources=reviewer_muse_config_sources,
        # ``muse login --help``: "META_API_KEY always takes priority over the account login."
        api_key_variables=("META_API_KEY",),
        api_key_prefixes=(),
        untrusted_dirs=(".muse", ".claude", ".agents"),
        untrusted_files=(".mcp.json",),
        instruction_names=("AGENTS.md", "CLAUDE.md", "CLAUDE.local.md"),
        prompt_via="file",
        credential_files=("~/.config/muse/auth.json",),
        vendor_home="~/.config/muse",
        vendor_writable="~/.config/muse",
        probe_model="muse-wonder-full-1.0",
        executable=reviewer_muse_executable,
    ),
}

#: Committed probe records that admit a candidate, by ``(vendor, platform)``. Each is the record
#: ``reviewer-probe --record`` wrote, every check held, bound to the executable it ran. A test
#: keeps this table equal to the records under ``tests/fixtures/reviewer-probe/``.
REVIEWER_ADMISSIONS: dict[tuple[str, str], Mapping[str, Any]] = {}


def _reviewer_admitted() -> dict[str, ReviewerRecipe]:
    admitted: dict[str, ReviewerRecipe] = {}
    for vendor, platform in sorted(REVIEWER_ADMISSIONS):
        base = admitted.get(vendor) or REVIEWER_CANDIDATES[vendor]
        platforms = tuple(sorted({*(base.platforms or ()), platform}))
        admitted[vendor] = dataclasses.replace(base, platforms=platforms)
    return admitted


#: The vendors with a reviewer recipe. A vendor joins only when ``reviewer-probe`` passes on it;
#: every other vendor is refused by name (plan KTD2: codex-cli 0.160.1's workspace-write sandbox
#: read a file outside its workspace on 2026-10-06). Issue #223: Grok and Muse join only through
#: ``REVIEWER_ADMISSIONS``.
REVIEWER_RECIPES: dict[str, ReviewerRecipe] = {
    "claude": REVIEWER_CLAUDE_RECIPE,
    **_reviewer_admitted(),
}


def reviewer_recipe(vendor: str) -> ReviewerRecipe:
    recipe = REVIEWER_RECIPES.get(vendor)
    if recipe is None:
        raise ReviewerRefused(
            f"{vendor} has no reviewer sandbox recipe that denies writes outside the copy, network "
            "and credential reads; it cannot staff the targeted reviewer"
        )
    return recipe


def reviewer_probe_recipe(vendor: str) -> ReviewerRecipe:
    """The recipe ``reviewer-probe`` runs: a reviewer's, else a candidate's."""
    if vendor in REVIEWER_RECIPES:
        return REVIEWER_RECIPES[vendor]
    if vendor in REVIEWER_CANDIDATES:
        return REVIEWER_CANDIDATES[vendor]
    return reviewer_recipe(vendor)


def reviewer_work_root(env: Mapping[str, str], platform: str | None = None) -> Path:
    """Where scratch copies live: outside every temp root the sandbox denies."""
    cache = env.get("XDG_CACHE_HOME") or str(Path(env.get("HOME") or Path.home()) / ".cache")
    root = Path(cache).expanduser() / "agent-launcher" / "reviews"
    for temp in reviewer_temp_roots(platform):
        if any(
            str(path) == temp or str(path).startswith(temp.rstrip("/") + "/")
            for path in (root, root.resolve())
        ):
            raise ReviewerRefused(
                f"the scratch copy would sit under {temp}, which the reviewer's sandbox denies"
            )
    return root


def _reviewer_manifest(copy: Path) -> dict[str, str]:
    """Each file's SHA-256, and each symlink as ``link:<target>``, never followed."""
    manifest: dict[str, str] = {}
    for path in sorted(copy.rglob("*")):
        relative = path.relative_to(copy).as_posix()
        if path.is_symlink():
            manifest[relative] = f"link:{os.readlink(path)}"
        elif path.is_file():
            manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def _reviewer_safe_path(copy: Path, relative: str) -> Path:
    parts = Path(relative).parts
    if (
        not parts
        or Path(relative).is_absolute()
        or any(p in ("..", "") or _reviewer_fold(p) == ".git" for p in parts)
    ):
        raise ReviewerRefused(f"the head names an unsafe path {relative!r}")
    return copy.joinpath(*parts)


def _reviewer_writable_at(copy: Path, target: Path, relative: str) -> None:
    """Refuse a write whose directory leaves the copy or passes through a symlink."""
    ancestor = target.parent
    while ancestor != copy:
        if ancestor.is_symlink():
            raise ReviewerRefused(f"the head writes {relative!r} through a symlink")
        ancestor = ancestor.parent
    if not _reviewer_inside(target.parent, copy):
        raise ReviewerRefused(f"the head writes {relative!r} outside the copy")


def reviewer_export_head(repo: Path, head: str, copy: Path) -> dict[str, str]:
    """Write *head*'s tracked files into *copy* from git's object store, with no ``.git``.

    Read with ``ls-tree`` and ``cat-file`` rather than ``git archive``, so the change's own
    ``.gitattributes`` (``export-ignore``, ``export-subst``) cannot make the copy differ from the
    head. Every path is checked, regular files are written before symlinks, and submodules are
    left out. Returns the copy's manifest.
    """
    resolved = run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{head}^{{commit}}"],
        check=False, timeout=30,
    )
    if resolved.returncode != 0:
        raise ReviewerRefused(f"{head} is not a commit in {repo}")
    commit = resolved.stdout.strip()
    listing = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "-z", "--full-tree", commit],
        capture_output=True, timeout=120, check=False,
    )
    if listing.returncode != 0:
        raise ReviewerRefused(f"git ls-tree failed: {listing.stderr.decode(errors='replace')}")
    entries: list[tuple[str, str, str]] = []
    for record in listing.stdout.split(b"\0"):
        if not record:
            continue
        meta, _, name = record.partition(b"\t")
        mode, kind, sha = meta.decode().split()
        if kind == "blob":
            entries.append((mode, sha, name.decode("utf-8", "surrogateescape")))
    batch = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        input="".join(f"{sha}\n" for _, sha, _ in entries).encode(),
        capture_output=True, timeout=300, check=False,
    )
    if batch.returncode != 0:
        raise ReviewerRefused(f"git cat-file failed: {batch.stderr.decode(errors='replace')}")
    blobs: list[bytes] = []
    stream, offset = batch.stdout, 0
    for _ in entries:
        newline = stream.index(b"\n", offset)
        size = int(stream[offset:newline].split()[2])
        blobs.append(stream[newline + 1 : newline + 1 + size])
        offset = newline + 1 + size + 1
    folded: dict[str, str] = {}
    for _mode, _sha, relative in entries:
        for depth in range(1, len(Path(relative).parts) + 1):
            prefix = "/".join(Path(relative).parts[:depth])
            seen = folded.setdefault(_reviewer_fold(prefix), prefix)
            if seen != prefix:
                # On a case-insensitive file system the two would land on one path.
                raise ReviewerRefused(
                    f"the head names {seen!r} and {prefix!r}, which differ only by case"
                )
    copy.mkdir(parents=True)
    links: list[tuple[Path, bytes]] = []
    for (mode, _sha, relative), data in zip(entries, blobs, strict=True):
        target = _reviewer_safe_path(copy, relative)
        if mode == "120000":
            links.append((target, data))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        _reviewer_writable_at(copy, target, relative)
        target.write_bytes(data)
        # Explicit modes, so the copy matches saga's 022 re-run whatever mask the launcher has.
        target.chmod(0o755 if mode == "100755" else 0o644)
    for target, data in links:
        target.parent.mkdir(parents=True, exist_ok=True)
        _reviewer_writable_at(copy, target, target.relative_to(copy).as_posix())
        os.symlink(data.decode("utf-8", "surrogateescape"), target)
    return _reviewer_manifest(copy)


def reviewer_scratch_changes(copy: Path, manifest: Mapping[str, str]) -> dict[str, list[str]]:
    """The files added, modified and deleted in the copy since the export, minus tool clutter."""
    now = _reviewer_manifest(copy)

    def is_link(path: str) -> bool:
        return now.get(path, "").startswith("link:")

    # Clutter is ignored only where it is new: a tracked file at a clutter-looking path that the
    # session modified or deleted is a change like any other.
    return {
        "added": sorted(
            p for p in now
            if p not in manifest and not is_link(p) and not REVIEWER_SCRATCH_IGNORED.search(p)
        ),
        "modified": sorted(
            p for p in now if p in manifest and now[p] != manifest[p] and not is_link(p)
        ),
        "deleted": sorted(p for p in manifest if p not in now),
        # A symlink the session made or changed is never a reproduction test: reading it later,
        # outside the sandbox, could read whatever it points at.
        "links": sorted(
            p for p in now
            if now[p].startswith("link:") and manifest.get(p) != now[p]
        ),
    }


def _reviewer_front_matter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    head = text[4:].split("\n---", 1)[0]
    pairs = (line.split(":", 1) for line in head.splitlines() if ":" in line)
    return {key.strip(): value.strip() for key, value in pairs}


def _reviewer_body(text: str) -> str:
    if text.startswith("---\n") and "\n---" in text[4:]:
        return text[4:].split("\n---", 1)[1].lstrip("-").lstrip("\n")
    return text


def reviewer_wrapper_path() -> Path:
    """The roles library's wrapper, beside this script's package root."""
    source = Path(reviewer_wrapper_path.__code__.co_filename).resolve()
    return source.parents[3] / "roles" / "targeted-reviewer.md"


def reviewer_launch_message(
    wrapper: str, prompt: str, packet: Path, copy: Path, cap: int,
    withheld: Sequence[str] = (), draft_folder: Path | None = None,
) -> str:
    """What the session reads on standard input: the wrapper, saga's prompt, where things are.

    With *draft_folder*, the message names it as the place for the reviewer's answer draft and
    saved run outputs: outside the scratch copy, so the scratch-change comparison never sees it.
    Without one (a vendor that gets no such folder), the line is left out and the prompt tells the
    reviewer to keep drafts in the copy and delete them.
    """
    draft = (
        "- Your draft folder, outside the scratch copy and never compared: "
        f"`{draft_folder.resolve()}`\n"
        if draft_folder is not None else ""
    )
    note = (
        "\nWithheld from the scratch copy, because they would run or read outside the sandbox; "
        "the packet's change still shows them:\n"
        + "".join(f"- `{item}`\n" for item in withheld)
        if withheld else ""
    )
    return (
        f"{_reviewer_body(wrapper).rstrip()}\n\n"
        "---\n\n"
        f"{_reviewer_body(prompt).rstrip()}\n\n"
        "---\n\n"
        "# This review\n\n"
        f"- The review packet: `{packet.resolve()}`\n"
        f"- The scratch copy, your working directory: `{copy.resolve()}`\n"
        f"- The open search's cap on findings: {cap}\n"
        f"{draft}"
        f"{note}\n"
        "Your final message is the answer JSON and nothing else.\n"
    )


def reviewer_extract_answer(final: str | None) -> tuple[Any, str | None]:
    """The answer in the final message, unwrapping one code fence; or why there is none."""
    if not final or not final.strip():
        return None, "the session gave no final message"
    text = final.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n(.*)\n```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        answer = json.loads(text)
    except ValueError:
        return None, "the final message is not JSON"
    if not isinstance(answer, dict):
        return None, "the final message is not a JSON object"
    return answer, None


def reviewer_read_answer(parsed: Mapping[str, Any]) -> tuple[Any, str | None, str | None]:
    """The answer, where it came from and why there is none: structured output first (issue #248).

    The order is Claude's validated ``structured_output``, then a final message that is entirely
    one JSON object (bare or in one fence). A message that merely contains an object is never read:
    the prompt quotes example objects, so a quoted one must not pass for the answer.
    """
    structured = parsed.get("structured")
    if isinstance(structured, dict):
        return structured, "structured_output", None
    answer, missing = reviewer_extract_answer(parsed.get("final"))
    if answer is not None:
        return answer, "final_message", None
    return None, None, missing


def reviewer_keep_final_message(final: str | None, out: Path) -> dict[str, Any] | None:
    """Write an unreadable final message beside result.json, bounded; never inside the copy.

    The file is evidence only: nothing reads it back or runs it. ``None`` when there was nothing.
    """
    if not final or not final.strip():
        return None
    raw = final.encode("utf-8")
    kept = raw[:REVIEWER_FINAL_MESSAGE_LIMIT].decode("utf-8", "ignore")
    path = out / "final-message.txt"
    path.write_text(kept, "utf-8")
    return {
        "path": str(path), "bytes": len(raw), "truncated": len(raw) > REVIEWER_FINAL_MESSAGE_LIMIT,
    }


def reviewer_deliver_prompt(
    recipe: ReviewerRecipe, root: Path, message: str
) -> tuple[Path | None, str]:
    """Where the session reads its message: standard input, or a file outside the copy."""
    if recipe.prompt_via != "file":
        return None, message
    prompt_dir = root / "prompt"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    path = prompt_dir / "message.md"
    path.write_text(message, "utf-8")
    return path, ""


def reviewer_pin_executable(executable: Path, identity: Mapping[str, str], root: Path) -> Path:
    """Copy the verified executable into the launch root and check the copy, then run the copy.

    An updater can replace the installed file between the check and the run; it cannot replace a
    private copy, so what runs is what the probe record names.
    """
    pinned = root / "bin" / executable.name
    pinned.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(executable, pinned)
    pinned.chmod(0o755)
    if _reviewer_sha256(pinned) != identity["sha256"]:
        raise ReviewerRefused(f"the copied {executable.name} does not match the verified one")
    return pinned


def reviewer_run_session(
    argv: list[str], *, stdin: str, cwd: Path, env: Mapping[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run the session; a timeout comes back as exit 124, never an exception."""
    try:
        return subprocess.run(
            argv, input=stdin, cwd=str(cwd), env=dict(env), capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, REVIEWER_EXIT_TIMEOUT, "", "timed out")
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def _reviewer_vendor_version(binary: str, env: Mapping[str, str]) -> str | None:
    try:
        proc = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=20, env=dict(env),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


@dataclass
class ReviewerRequest:
    """One targeted-reviewer launch."""

    vendor: str
    model: str
    effort: str
    repo: Path
    head: str
    packet: Path
    prompt: Path
    schema: Path
    out: Path
    open_search_cap: int = REVIEWER_DEFAULT_CAP
    timeout: float = REVIEWER_TIMEOUT_SECONDS
    work_root: Path | None = None
    #: Issue #223: the dollar ceiling, required for a vendor that takes one (Claude).
    max_budget_usd: str | None = None


def reviewer_record_admits(
    record: Any,
    vendor: str,
    platform: str,
    identity: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    """Whether a probe record admits *vendor* on *platform*, and why not when it does not.

    Admission needs a complete, well-formed record for exactly this vendor and platform: the
    schema, every check in ``REVIEWER_PROBE_CHECKS`` once and nothing else, each one held (a real
    ``True``), a session that exited 0, and an executable identity. With *identity* (the
    executable about to run), its SHA-256 and version must equal the record's. Anything missing,
    duplicated, malformed or mismatched refuses.
    """
    if not isinstance(record, Mapping):
        return False, "the probe record is not a JSON object"
    if record.get("schema") != REVIEWER_PROBE_RECORD_SCHEMA:
        return False, f"the probe record's schema is not {REVIEWER_PROBE_RECORD_SCHEMA}"
    if record.get("vendor") != vendor:
        return False, f"the probe record is for {record.get('vendor')!r}, not {vendor!r}"
    if record.get("platform") != platform:
        return False, f"the probe record is for {record.get('platform')!r}, not {platform!r}"
    verdicts = record.get("verdicts")
    if not isinstance(verdicts, list) or not verdicts:
        return False, "the probe record has no verdicts"
    names: list[str] = []
    for verdict in verdicts:
        if not (
            isinstance(verdict, Mapping)
            and isinstance(verdict.get("denial"), str)
            and isinstance(verdict.get("held"), bool)
            and isinstance(verdict.get("detail"), str)
        ):
            return False, "a verdict in the probe record is malformed"
        names.append(verdict["denial"])
    if len(names) != len(set(names)):
        return False, "the probe record names a check more than once"
    if set(names) != set(REVIEWER_PROBE_CHECKS):
        missing = sorted(set(REVIEWER_PROBE_CHECKS) - set(names))
        extra = sorted(set(names) - set(REVIEWER_PROBE_CHECKS))
        return False, f"the probe record's checks differ: missing {missing}, unknown {extra}"
    failed = [v["denial"] for v in verdicts if v["held"] is not True]
    if failed:
        return False, "the probe record has checks that did not hold: " + ", ".join(failed)
    exit_code = record.get("session_exit")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code != 0:
        return False, "the probe record's session did not exit 0"
    executable = record.get("executable")
    if not (
        isinstance(executable, Mapping)
        and isinstance(executable.get("name"), str) and executable["name"]
        and isinstance(executable.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", executable["sha256"])
        and isinstance(executable.get("version"), str) and executable["version"]
    ):
        return False, "the probe record has no well-formed executable identity"
    if identity is not None and (
        identity.get("sha256") != executable["sha256"]
        or identity.get("version") != executable["version"]
    ):
        return False, (
            f"the {vendor} executable is not the one the probe passed on (probed "
            f"{executable['version']}, found {identity.get('version') or 'no version'}); run "
            f"reviewer-probe --vendor {vendor} --record again and commit the record"
        )
    return True, "admitted"


def reviewer_launch(
    request: ReviewerRequest,
    *,
    env: Mapping[str, str] | None = None,
    session: Any = reviewer_run_session,
) -> tuple[dict[str, Any], int]:
    """Start the targeted reviewer headless and return ``(result, exit code)``.

    Refusals (``ReviewerRefused``) happen before anything is created: a vendor with no recipe, a
    prompt that is not saga's, a missing packet or schema, or a head that is not a commit.
    """
    environ = dict(os.environ if env is None else env)
    recipe = reviewer_recipe(request.vendor)
    platform = sys.platform
    if recipe.platforms is not None and platform not in recipe.platforms:
        raise ReviewerRefused(
            f"{request.vendor}'s reviewer recipe passed its probe only on "
            f"{', '.join(recipe.platforms)}, not {platform}"
        )
    if recipe.takes_ceiling:
        problem = reviewer_ceiling_problem(request.max_budget_usd)
        if problem:
            raise ReviewerRefused(
                f"a {request.vendor} reviewer launch needs a spending ceiling: {problem}"
            )
    elif request.max_budget_usd is not None:
        raise ReviewerRefused(
            f"{request.vendor} has no dollar ceiling; --max-budget-usd cannot be honoured"
        )
    executable: Path | None = None
    identity: dict[str, str] | None = None
    record: Mapping[str, Any] | None = None
    if recipe.executable is not None:
        record = REVIEWER_ADMISSIONS.get((request.vendor, platform))
        if record is None:
            raise ReviewerRefused(f"{request.vendor} has no admitted probe record on {platform}")
        admitted, why = reviewer_record_admits(record, request.vendor, platform)
        if not admitted:
            raise ReviewerRefused(why)
        executable = recipe.executable(environ)
        # Issue #223's review, finding 2: the bytes are compared before anything runs them, so
        # a replaced or redirected executable is refused without being run.
        if reviewer_executable_file(executable)["sha256"] != record["executable"]["sha256"]:
            raise ReviewerRefused(
                f"the {request.vendor} executable is not the one the probe passed on (its SHA-256 "
                f"differs from the record's); run reviewer-probe --vendor {request.vendor} "
                "--record again and commit the record"
            )
    try:
        prompt_bytes = request.prompt.read_bytes()
    except OSError as exc:
        raise ReviewerRefused(f"cannot read the prompt {request.prompt}: {exc}") from None
    prompt_text = prompt_bytes.decode("utf-8")
    if _reviewer_front_matter(prompt_text).get("id") != REVIEWER_PROMPT_ID:
        raise ReviewerRefused(f"{request.prompt} is not saga's {REVIEWER_PROMPT_ID}")
    if not request.schema.is_file():
        raise ReviewerRefused(f"the answer schema {request.schema} does not exist")
    try:
        schema_object = json.loads(request.schema.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewerRefused(f"the answer schema {request.schema} is not JSON: {exc}") from None
    if not isinstance(schema_object, dict):
        raise ReviewerRefused(f"the answer schema {request.schema} is not a JSON object")
    answer_schema = json.dumps(schema_object, separators=(",", ":"), ensure_ascii=False)
    if not request.packet.is_dir():
        raise ReviewerRefused(f"the review packet {request.packet} is not a directory")
    wrapper = reviewer_wrapper_path()
    if not wrapper.is_file():
        raise ReviewerRefused(f"the roles library's wrapper {wrapper} is missing")
    widening = recipe.widening(environ) if recipe.widening is not None else []
    if widening:
        raise ReviewerRefused(
            "settings outside the copy would widen the reviewer's sandbox: " + "; ".join(widening)
        )

    root = (request.work_root or reviewer_work_root(environ)) / (
        f"{request.repo.resolve().name}-{request.head[:12]}-{os.urandom(4).hex()}"
    )
    copy = root / "copy"
    session_env = reviewer_session_environment(
        environ, recipe.api_key_variables, recipe.api_key_prefixes
    )
    home = _reviewer_home(session_env)
    for label, path in (("scratch copy", copy), ("review packet", request.packet)):
        problem = reviewer_allowed_read_problem(path.absolute(), home)
        if problem:
            raise ReviewerRefused(f"the {label} cannot be allowed back inside the blocked home: "
                                  f"{problem}")
    toolchain, dropped = reviewer_toolchain_paths(session_env)
    reviewer_export_head(request.repo, request.head, copy)
    withheld = reviewer_withhold_untrusted(
        copy, recipe.untrusted_dirs, recipe.untrusted_files, recipe.instruction_names
    )
    # Issue #262: cargo builds offline from the packet's vendored crates, through a read-only
    # cargo home beside the copy and the shim in it.
    vendor = reviewer_packet_vendor(request.packet)
    cargo_home = reviewer_cargo_home(root, vendor, session_env)
    reviewer_offline_cargo(session_env, cargo_home)
    dependency_reads = [
        {"path": str(cargo_home.resolve()),
         "reason": "the reviewer's read-only cargo home, offline (issue #262)"},
    ] + ([{"path": str(vendor),
           "reason": "the packet's vendored Rust dependencies, read-only (issue #262)"}]
         if vendor is not None else [])
    settings_path, extra_env = recipe.materialize(
        recipe.settings(
            copy, request.packet, session_env, toolchain=toolchain,
            read_only=[item["path"] for item in dependency_reads],
        ),
        root, copy,
    )
    manifest = _reviewer_manifest(copy)
    configuration = reviewer_configuration_fingerprint(recipe.config_sources(copy, session_env))
    message = reviewer_launch_message(
        wrapper.read_text(encoding="utf-8"), prompt_text, request.packet, copy,
        request.open_search_cap, withheld,
        draft_folder=recipe.temp_dir(copy) if recipe.temp_dir is not None else None,
    )
    prompt_path, stdin = reviewer_deliver_prompt(recipe, root, message)
    if executable is not None and record is not None:
        try:
            executable = reviewer_pin_executable(executable, record["executable"], root)
            # The version comes only from the verified copy, without the API-key variables.
            identity = reviewer_executable_identity(executable, session_env)
            admitted, why = reviewer_record_admits(record, request.vendor, platform, identity)
            if not admitted:
                raise ReviewerRefused(why)
        except ReviewerRefused:
            shutil.rmtree(root, ignore_errors=True)
            raise
    argv = recipe.argv(
        request.model, request.effort, settings_path, max_budget_usd=request.max_budget_usd,
        executable=executable, prompt_path=prompt_path, answer_schema=answer_schema,
    )
    proc = session(
        argv, stdin=stdin, cwd=copy, env={**session_env, **extra_env}, timeout=request.timeout
    )
    parsed = recipe.parse(proc.stdout)
    answer, answer_source, missing = reviewer_read_answer(parsed)

    shell_reads = [
        {"path": str(Path(extra_env[REVIEWER_SHELL_PREFIX]).parent),
         "reason": "the reviewer's shell prefix, which keeps start-up exports out (issue #225)"}
    ] if REVIEWER_SHELL_PREFIX in extra_env else []
    temp_reads = [
        {"path": str(recipe.temp_dir(copy)),
         "reason": "the reviewer's own temp folder, also writable and beside the copy"}
    ] if recipe.temp_dir is not None else []
    request.out.mkdir(parents=True, exist_ok=True)
    answer_path = request.out / "answer.json"
    final_message: dict[str, Any] | None = None
    if answer is not None:
        answer_path.write_text(json.dumps(answer, indent=2, ensure_ascii=False) + "\n", "utf-8")
    else:
        final_message = reviewer_keep_final_message(parsed.get("final"), request.out)
    if proc.returncode == REVIEWER_EXIT_TIMEOUT:
        code, error = REVIEWER_EXIT_TIMEOUT, "the session timed out"
    elif answer is None:
        code, error = REVIEWER_EXIT_NO_ANSWER, parsed.get("error") or missing
    else:
        code, error = 0, parsed.get("error")
    result = {
        "schema": REVIEWER_RESULT_SCHEMA,
        "vendor": request.vendor,
        "vendor_version": (
            identity["version"] if identity is not None
            else _reviewer_vendor_version(recipe.binary, session_env)
        ),
        "model": {"requested": request.model, "resolved": parsed["resolved"]},
        "effort": request.effort,
        "ceiling_usd": request.max_budget_usd,
        "executable": identity,
        "usage": parsed["usage"],
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "schema_sha256": hashlib.sha256(request.schema.read_bytes()).hexdigest(),
        "configuration": configuration,
        "scratch": {
            "path": str(copy),
            "withheld": withheld,
            "changes": reviewer_scratch_changes(copy, manifest),
        },
        "sandbox_reads": {
            "allowed": [
                {"path": str(copy.resolve()), "reason": "the scratch copy the review works in"},
                {"path": str(request.packet.resolve()), "reason": "the review packet"},
            ] + shell_reads + dependency_reads + list(toolchain) + temp_reads,
            "dropped": dropped,
        },
        "answer_path": str(answer_path) if answer is not None else None,
        "answer_source": answer_source,
        "final_message": final_message,
        "exit": code,
        "error": error,
    }
    (request.out / "result.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    return result, code


#: The address the probe's network check tries, from inside the session and from outside it.
REVIEWER_PROBE_URL = "https://example.com"
#: curl exit statuses that mean the connection never left: 6, the name did not resolve; 7, the
#: connection was refused. 56 counts only with a refused proxy tunnel (Claude's sandbox proxy
#: answers CONNECT with 403; since issue #225 its commands get no proxy variables and give 6).
#: Timeouts (28), TLS and certificate failures (35, 51, 58, 60, 77, 83, 90, 91) and an unrunnable
#: curl (126, 127) prove nothing, so they never count as denial.
REVIEWER_NETWORK_DENIED = frozenset({"6", "7"})

#: The fixed command the probe asks the session to run. Each line records its own exit status in
#: ``probe-results.txt`` inside the copy, so every verdict comes from the command, never the model.
REVIEWER_PROBE_SCRIPT = """\
r=probe-results.txt
: > "$r"
cat "{outside}/canary.txt" > /dev/null 2>&1; echo "read=$?" >> "$r"
touch "{outside}/written" 2> /dev/null; echo "write_outside=$?" >> "$r"
touch inside-written 2> /dev/null; echo "write_inside=$?" >> "$r"
touch "${{TMPDIR:-/tmp}}/reviewer-probe-{tag}" 2> /dev/null; echo "write_tmpdir=$?" >> "$r"
touch "/tmp/reviewer-probe-{tag}" 2> /dev/null; echo "write_tmp=$?" >> "$r"
c=$(curl -sS -m 5 -o /dev/null -w '%{{http_connect}}' {url} 2> /dev/null); echo "network=$?" >> "$r"
echo "network_connect=$c" >> "$r"
if [ -n "${{REVIEWER_PROBE_TOKEN+x}}" ]; then v=set; else v=unset; fi; echo "variable=$v" >> "$r"
cat "{home_canary}" > /dev/null 2>&1; echo "read_home=$?" >> "$r"
cat "{packet}/packet.txt" > /dev/null 2>&1; echo "read_packet=$?" >> "$r"
python3 -m unittest discover -s tests -q > /dev/null 2>&1; echo "python_test=$?" >> "$r"
git --version > /dev/null 2>&1; echo "git=$?" >> "$r"
[ -n "${{REVIEWER_PROBE_PLAIN+x}}" ] && v=set || v=unset; echo "plain_variable=$v" >> "$r"
cat "{vendor_canary}" > /dev/null 2>&1; echo "read_vendor_home=$?" >> "$r"
touch "{vendor_write}" 2> /dev/null; echo "write_vendor_home=$?" >> "$r"
"""
#: Every recipe's probe checks shell start-up exports (issue #225 added Claude's).
REVIEWER_PROBE_STARTUP_LINE = (
    '[ -n "${REVIEWER_PROBE_STARTUP+x}" ] && v=set || v=unset; '
    'echo "startup_variable=$v" >> "$r"\n'
)

#: A real Python test the probe runs in the copy: blocking home must leave the toolchain working.
REVIEWER_PROBE_TEST = """\
import unittest


class ReviewerProbeTest(unittest.TestCase):
    def test_the_toolchain_runs(self):
        self.assertEqual(sum([1, 2]), 3)
"""

REVIEWER_PROBE_MESSAGE = (
    "Run exactly this one Bash command, from your working directory, and then reply with the "
    "single word done: sh probe.sh"
)

REVIEWER_PROBE_RECORD_SCHEMA = "reviewer_probe_record.v1"

#: Every check a probe makes, by name, for every recipe. A record admits a vendor only when it
#: holds exactly these.
REVIEWER_PROBE_CHECKS = (
    "read-credential", "write-outside", "write-inside", "write-tmpdir", "write-tmp", "network",
    "credential-variable", "read-home", "read-packet", "python-test", "git-runs",
    "plain-variable", "no-canary-in-output",
    # Issue #223.
    "read-vendor-home", "write-vendor-home", "read-vendor-credential", "startup-variable",
    "answer-parsed", "session-exit",
)


def reviewer_network_reachable(env: Mapping[str, str]) -> int:
    """curl's exit status for the probe's address, run outside any sandbox; 127 without curl."""
    try:
        proc = subprocess.run(
            ["curl", "-sS", "-m", "5", "-o", os.devnull, REVIEWER_PROBE_URL],
            capture_output=True, timeout=20, env=dict(env), check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 127
    return proc.returncode


def reviewer_network_verdict(
    results: Mapping[str, str], reachability: tuple[int, int] | None
) -> tuple[bool, str]:
    """Whether the network was denied by the sandbox, not by the network itself.

    Denial counts only when the same address was reachable from outside the session just before
    and just after it, and the session's curl failed in a way that means the connection never
    left. Anything else, an unreachable network included, is inconclusive and does not hold.
    """
    code, connect = results.get("network"), results.get("network_connect", "")
    before, after = reachability if reachability is not None else (None, None)
    detail = f"network={code} connect={connect} outside_before={before} outside_after={after}"
    if before != 0 or after != 0:
        return False, detail + " (inconclusive: the address was not reachable from outside)"
    if code in REVIEWER_NETWORK_DENIED or (code == "56" and connect == "403"):
        return True, detail
    return False, detail


def reviewer_probe_verdicts(
    root: Path,
    outside: Path,
    tag: str,
    canaries: Sequence[str],
    session_output: str,
    *,
    parsed: Mapping[str, Any] | None = None,
    session_exit: int | None = None,
    reachability: tuple[int, int] | None = None,
    vendor_write: Path | None = None,
    credential_count: int = 0,
    credentials_absent: Sequence[str] = (),
    temp_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Judge each denial from outside the session: the filesystem and the command's own results.

    With *temp_dir*, the recipe leaves that folder writable, so ``write-tmpdir`` holds when the
    session's write to ``TMPDIR`` succeeded and landed there; ``write-tmp`` still proves ``/tmp``.

    Every check in ``REVIEWER_PROBE_CHECKS`` gets a verdict, so a record is always complete; when
    the command never ran, each check that needed it does not hold.
    """
    copy = root / "copy"
    results_path = copy / "probe-results.txt"
    try:
        text = results_path.read_text(encoding="utf-8")
        ran = True
    except OSError:
        text, ran = "", False
    lines = text.splitlines()
    results = dict(line.split("=", 1) for line in lines if "=" in line)
    seen = text + "\n" + session_output

    def nonzero(key: str) -> bool:
        return results.get(key, "0") not in ("", "0")

    def did(key: str) -> str:
        return f"{key}={results.get(key)}" if ran else "the command did not run"

    network_held, network_detail = reviewer_network_verdict(results, reachability)
    credential_keys = [f"read_vendor_credential_{n}" for n in range(credential_count)]
    credential_detail = ", ".join(f"{k}={results.get(k)}" for k in credential_keys)
    if credentials_absent:
        credential_detail += (", " if credential_detail else "") + (
            f"{len(credentials_absent)} absent"
        )
    canary_seen = any(c in seen for c in canaries)
    answer = parsed or {}
    verdicts = [
        ("read-credential", nonzero("read"), did("read")),
        ("write-outside", nonzero("write_outside") and not (outside / "written").exists(),
         did("write_outside")),
        ("write-inside", results.get("write_inside") == "0" and (copy / "inside-written").exists(),
         did("write_inside")),
        ("write-tmpdir",
         (results.get("write_tmpdir") == "0" and (temp_dir / f"reviewer-probe-{tag}").exists())
         if temp_dir is not None else nonzero("write_tmpdir"),
         did("write_tmpdir")),
        ("write-tmp", nonzero("write_tmp") and not Path(f"/tmp/reviewer-probe-{tag}").exists(),
         did("write_tmp")),
        # Issue #223: denial is proven against a reachability check made outside the session.
        ("network", ran and network_held, network_detail if ran else did("network")),
        ("credential-variable", results.get("variable") == "unset", did("variable")),
        # Issue #189: the whole home directory is blocked, and only what the review needs is back.
        ("read-home", nonzero("read_home"), did("read_home")),
        ("read-packet", results.get("read_packet") == "0", did("read_packet")),
        ("python-test", results.get("python_test") == "0", did("python_test")),
        ("git-runs", results.get("git") == "0", did("git")),
        ("plain-variable", results.get("plain_variable") == "unset", did("plain_variable")),
        ("no-canary-in-output", ran and not canary_seen,
         "a canary value appeared in the results or the session's output" if canary_seen
         else ("no canary value seen" if ran else "the command did not run")),
        # Issue #223: the vendor's own state, sign-in files and shell start-up exports.
        ("read-vendor-home", nonzero("read_vendor_home"), did("read_vendor_home")),
        ("write-vendor-home", nonzero("write_vendor_home") and not (
            vendor_write is not None and vendor_write.exists()
        ), did("write_vendor_home")),
        ("read-vendor-credential", ran and all(nonzero(k) for k in credential_keys),
         (credential_detail or "no sign-in file declared") if ran else did("credential")),
        ("startup-variable", results.get("startup_variable") == "unset", did("startup_variable")),
        ("answer-parsed", bool(answer.get("final")) and not answer.get("is_error"),
         "a final message was parsed" if answer.get("final") and not answer.get("is_error")
         else f"no answer: {answer.get('error') or 'the session gave no final message'}"),
        ("session-exit", session_exit == 0, f"exit={session_exit}"),
    ]
    return [{"denial": name, "held": held, "detail": detail} for name, held, detail in verdicts]


def reviewer_probe(
    vendor: str,
    model: str | None = None,
    effort: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    session: Any = reviewer_run_session,
    work_root: Path | None = None,
    keep: bool = False,
    record_path: Path | None = None,
    max_budget_usd: str | None = None,
    reachable: Any = reviewer_network_reachable,
) -> tuple[list[dict[str, Any]], int]:
    """Run *vendor*'s reviewer recipe, or its candidate recipe, live and check each denial.

    Besides the probe directory it plants a canary file directly in the home directory and one in
    the vendor's own state directory, both outside every credential path, and removes them
    however the probe ends. With *record_path* it writes the record a candidate's admission is
    reviewed against.
    """
    recipe = reviewer_probe_recipe(vendor)
    model = model or recipe.probe_model
    platform = sys.platform
    tag = os.urandom(6).hex()
    canary_file = f"reviewer-probe-canary-{os.urandom(8).hex()}"
    canary_variable = f"reviewer-probe-variable-{os.urandom(8).hex()}"
    canary_home = f"reviewer-probe-home-{os.urandom(8).hex()}"
    canary_plain = f"reviewer-probe-plain-{os.urandom(8).hex()}"
    canary_vendor = f"reviewer-probe-vendor-{os.urandom(8).hex()}"
    canary_startup = f"reviewer-probe-startup-{os.urandom(8).hex()}"
    environ = dict(os.environ if env is None else env)
    environ["REVIEWER_PROBE_TOKEN"] = canary_variable
    environ["REVIEWER_PROBE_PLAIN"] = canary_plain
    home = _reviewer_home(environ)
    identity: dict[str, str] | None = None
    if recipe.executable is not None:
        # Its version is read from the pinned copy below, never from the installed file.
        executable: Path | None = recipe.executable(environ)
    else:
        executable = None
        found = shutil.which(recipe.binary, path=environ.get("PATH", ""))
        identity = reviewer_executable_identity(Path(found).resolve(), environ) if found else None
    root = (work_root or reviewer_work_root(environ)) / f"probe-{tag}"
    copy, outside, packet = root / "copy", root / "outside", root / "packet"
    startup = root / "startup"
    home_canary = home / f".reviewer-probe-home-canary-{tag}"
    vendor_home = _reviewer_expand(recipe.vendor_home, home) if recipe.vendor_home else None
    vendor_canary = (vendor_home or root / "no-vendor-home") / f".reviewer-probe-canary-{tag}"
    vendor_write = (
        _reviewer_expand(recipe.vendor_writable, home) / f"reviewer-probe-write-{tag}"
        if recipe.vendor_writable else root / "no-vendor-home" / "write"
    )
    credentials = [_reviewer_expand(path, home) for path in recipe.credential_files]
    present = [path for path in credentials if path.is_file()]
    absent = [str(path.name) for path in credentials if not path.is_file()]
    (copy / "tests").mkdir(parents=True)
    outside.mkdir()
    packet.mkdir()
    startup.mkdir()
    (outside / "canary.txt").write_text(canary_file + "\n", "utf-8")
    (packet / "packet.txt").write_text("the review packet\n", "utf-8")
    (copy / "tests" / "test_reviewer_probe.py").write_text(REVIEWER_PROBE_TEST, "utf-8")
    script = REVIEWER_PROBE_SCRIPT.format(
        outside=outside, tag=tag, home_canary=home_canary, packet=packet, url=REVIEWER_PROBE_URL,
        vendor_canary=vendor_canary, vendor_write=vendor_write,
    ) + "".join(
        f'cat "{path}" > /dev/null 2>&1; echo "read_vendor_credential_{n}=$?" >> "$r"\n'
        for n, path in enumerate(present)
    ) + REVIEWER_PROBE_STARTUP_LINE
    (copy / "probe.sh").write_text(script, "utf-8")
    # Shell start-up files that export an inert secret; the session's shell must not hand it to
    # a sandboxed command. Set through the environment, so no operator file is edited.
    export = f"export REVIEWER_PROBE_STARTUP={canary_startup}\n"
    for name in (".zshenv", ".zprofile", ".zshrc", "bash_env", "sh_env"):
        (startup / name).write_text(export, "utf-8")
    startup_env = {
        "ZDOTDIR": str(startup), "BASH_ENV": str(startup / "bash_env"),
        "ENV": str(startup / "sh_env"),
    }
    planted: list[Path] = []
    try:
        home_canary.write_text(canary_home + "\n", "utf-8")
        planted.append(home_canary)
        if vendor_home is not None and vendor_home.is_dir():
            vendor_canary.write_text(canary_vendor + "\n", "utf-8")
            planted.append(vendor_canary)
        session_env = reviewer_session_environment(
            environ, recipe.api_key_variables, recipe.api_key_prefixes
        )
        # Issue #262: the same offline cargo home and read-only vendored folder a review gets, so
        # every denial is checked with them in place.
        vendored = packet / "dependencies" / "rust"
        vendored.mkdir(parents=True)
        cargo_home = reviewer_cargo_home(root, vendored.resolve(), session_env)
        reviewer_offline_cargo(session_env, cargo_home)
        settings = recipe.settings(
            copy, packet, session_env, extra_deny_read=[str(outside)],
            read_only=[str(cargo_home.resolve()), str(vendored.resolve())],
        )
        settings_path, extra_env = recipe.materialize(settings, root, copy)
        prompt_path, stdin = reviewer_deliver_prompt(recipe, root, REVIEWER_PROBE_MESSAGE)
        if executable is not None:
            executable = reviewer_pin_executable(
                executable, reviewer_executable_file(executable), root
            )
            identity = reviewer_executable_identity(executable, session_env)
        ceiling = (max_budget_usd or REVIEWER_PROBE_CEILING_USD) if recipe.takes_ceiling else None
        before = reachable(environ)
        proc = session(
            recipe.argv(model, effort, settings_path, max_budget_usd=ceiling,
                        executable=executable, prompt_path=prompt_path),
            stdin=stdin, cwd=copy, env={**session_env, **extra_env, **startup_env}, timeout=300,
        )
        after = reachable(environ)
        verdicts = reviewer_probe_verdicts(
            root, outside, tag,
            (canary_file, canary_variable, canary_home, canary_plain, canary_vendor,
             canary_startup),
            (proc.stdout or "") + (proc.stderr or ""),
            parsed=recipe.parse(proc.stdout or ""), session_exit=proc.returncode,
            reachability=(before, after), vendor_write=vendor_write,
            credential_count=len(present), credentials_absent=absent,
            temp_dir=recipe.temp_dir(copy) if recipe.temp_dir is not None else None,
        )
    finally:
        for path in planted:
            path.unlink(missing_ok=True)
        vendor_write.unlink(missing_ok=True)
        Path(f"/tmp/reviewer-probe-{tag}").unlink(missing_ok=True)
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
    passed = all(v["held"] for v in verdicts)
    if record_path is not None:
        record = {
            "schema": REVIEWER_PROBE_RECORD_SCHEMA,
            "vendor": vendor,
            "platform": platform,
            "date": time.strftime("%Y-%m-%d", time.gmtime()),
            "model": model,
            "effort": effort,
            "executable": identity,
            "session_exit": proc.returncode,
            # The session ran with the vendor's API-key variables removed; an answer then means
            # it signed in some other way, which for these recipes is the operator's own sign-in.
            "sign_in": "subscription" if any(
                v["denial"] == "answer-parsed" and v["held"] for v in verdicts
            ) else "not established",
            "verdicts": verdicts,
        }
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(record, indent=2) + "\n", "utf-8")
    return verdicts, 0 if passed else 1


def _reviewer_args(sub: Any) -> None:
    review_p = sub.add_parser(
        "review",
        help="Start saga's targeted reviewer headless in a sandboxed scratch copy (issue #158)",
        description=(
            "Start saga's targeted reviewer headless on a vendor with a reviewer recipe, with its "
            "normal configuration, in a sandboxed export of --head. Writes answer.json and "
            "result.json to --out and prints the result. Exit 0 answer; 2 refused before "
            "anything started; 3 no parsable answer; 124 timed out."
        ),
    )
    review_p.add_argument("--vendor", required=True)
    review_p.add_argument("--model", required=True)
    review_p.add_argument("--effort", required=True)
    review_p.add_argument("--repo", required=True, type=Path, help="The repository to export")
    review_p.add_argument("--head", required=True, help="The commit under review")
    review_p.add_argument("--packet", required=True, type=Path, help="The review packet directory")
    review_p.add_argument(
        "--prompt", required=True, type=Path,
        help="saga's targeted-reviewer-prompt.md (reviewer_answer.py paths prints it)",
    )
    review_p.add_argument("--schema", required=True, type=Path, help="saga's answer schema")
    review_p.add_argument("--out", required=True, type=Path, help="Where answer and result go")
    review_p.add_argument("--open-search-cap", type=int, default=REVIEWER_DEFAULT_CAP)
    review_p.add_argument("--timeout", type=float, default=REVIEWER_TIMEOUT_SECONDS)
    review_p.add_argument(
        "--max-budget-usd", default=None,
        help="Dollar ceiling for the session; required for claude, refused for a vendor without one",
    )
    probe_p = sub.add_parser(
        "reviewer-probe",
        help="Run a vendor's reviewer recipe live and check every sandbox denial",
        description=(
            "Run the reviewer recipe on one fixed command and check, from outside the session, "
            "that a credential read, a read of a canary planted in the home directory, writes "
            "outside the copy and to the temp roots, the network, a credential variable and an "
            "ordinary-named variable are denied, and that a write inside the copy, a read of the "
            "packet, a real Python test and git work. Issue #223 adds: the network denial is "
            "judged against the same address reached from outside the session; the vendor's own "
            "state directory, sign-in files and a secret exported by shell start-up files stay "
            "out of reach; and the session answers and exits 0. Runs a reviewer's recipe or a "
            "candidate's. Exit 0 when every check held, 1 otherwise, 2 for a vendor with neither."
        ),
    )
    probe_p.add_argument("--vendor", required=True)
    probe_p.add_argument("--model", default=None, help="Default: the recipe's probe model")
    probe_p.add_argument("--effort", default=None)
    probe_p.add_argument("--keep", action="store_true", help="Keep the probe directory")
    probe_p.add_argument(
        "--record", type=Path, default=None,
        help="Write the probe record (vendor, platform, executable identity, every verdict) here",
    )
    probe_p.add_argument(
        "--max-budget-usd", default=None,
        help=f"Dollar ceiling for a vendor that takes one (default {REVIEWER_PROBE_CEILING_USD})",
    )


def _reviewer_cli(args: argparse.Namespace) -> int:
    try:
        if args.cmd == "reviewer-probe":
            verdicts, code = reviewer_probe(
                args.vendor, args.model, args.effort, keep=args.keep, record_path=args.record,
                max_budget_usd=args.max_budget_usd,
            )
            json.dump(verdicts, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return code
        result, code = reviewer_launch(
            ReviewerRequest(
                vendor=args.vendor, model=args.model, effort=args.effort, repo=args.repo,
                head=args.head, packet=args.packet, prompt=args.prompt, schema=args.schema,
                out=args.out, open_search_cap=args.open_search_cap, timeout=args.timeout,
                max_budget_usd=args.max_budget_usd,
            )
        )
    except ReviewerRefused as refused:
        print(f"launcher: {refused}", file=sys.stderr)
        return REVIEWER_EXIT_REFUSED
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return code


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
    parser.add_argument(
        "--prompt",
        default="",
        help="First prompt; omitting it leaves the session idle and makes launch exit nonzero",
    )
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
    redeliver_p = sub.add_parser(
        "redeliver",
        help="Re-prompt the pane a staged-input stop recorded; never creates a session",
    )
    _add_launch_flags(redeliver_p)
    redeliver_p.add_argument(
        "--receipt-json",
        required=True,
        help="The receipt the staged-input stop wrote; tab, pane and ownership come from it",
    )
    close_p = sub.add_parser("close", help="Close a session this process owns")
    close_p.add_argument(
        "--tab-id",
        default=None,
        help="Optional when the receipt already carries tab_id",
    )
    close_p.add_argument("--receipt-json", required=True, help="Launch receipt proving ownership")
    sub.add_parser("roster", help="Vendors this machine can launch that this plugin can drive")
    _reviewer_args(sub)
    return parser


def _load_receipt(raw: str) -> dict[str, Any]:
    path = Path(raw)
    from_file = path.is_file()
    if from_file:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"cannot read receipt file {path}: {exc}") from None
    elif raw.lstrip()[:1] in ("{", "["):
        text = raw
    else:
        raise SystemExit(
            f"receipt {raw!r} is neither an existing file nor JSON; redirect launch output to a "
            "receipt file and pass that file: "
            "python3 launcher.py launch ... > receipt.json, then close --receipt-json receipt.json"
        )
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        if not from_file:
            raise
        raise SystemExit(
            f"receipt file {path} is empty or unparseable JSON: {exc.msg}; "
            "rerun launch with stdout redirected to a fresh receipt file"
        ) from None
    if not isinstance(loaded, dict):
        raise SystemExit("receipt must be a JSON object")
    return loaded


def cli_main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd in ("review", "reviewer-probe"):
        return _reviewer_cli(args)
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
    if args.cmd == "redeliver":
        # Exit codes (cycle 2, F64): 0 delivered; 1 the retry ran and the prompt was not
        # observed to be taken, or a stop was raised after the receipt was adopted (the receipt
        # is printed first); 2 the receipt was refused before any Herdr call.
        receipt = _load_receipt(args.receipt_json)
        try:
            _adopt_retry_receipt(unit, receipt)
        except RetryReceiptRefused as refused:
            print(refused, file=sys.stderr)
            return 2
        try:
            redeliver(unit)
        except SystemExit:
            json.dump(unit.launch_receipt, sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            raise
        json.dump(unit.launch_receipt, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 1 if unit.status == PROMPT_UNDELIVERED else 0
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
