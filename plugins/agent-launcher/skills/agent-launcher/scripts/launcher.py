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
import hashlib
import importlib.util
import json
import os
import re
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
    "qwen": {"model": "-m {value}"},
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

    Some agents never report readiness at all -- qwen is one, and it is why the writer has a pane
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
    interactive readiness; one that never does -- qwen today -- refuses it, and the line is typed
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
REVIEWER_EXIT_TIMEOUT = 124
REVIEWER_DEFAULT_CAP = 5

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
    "grok": ("--always-approve", "--system-prompt-override", "bypassPermissions"),
    "muse": (
        "--disable-sandbox", "--no-foreign-personal-context", "--disable-reminders", "--yolo",
        "never",
    ),
    "agy": ("--dangerously-skip-permissions", "--disable-slash-commands"),
    "qwen": ("--bare", "--safe-mode", "--yolo"),
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

#: A variable whose name looks like a credential is hidden from the reviewer's sandboxed commands.
REVIEWER_CREDENTIAL_NAME = re.compile(
    r"TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|SESSION|COOKIE", re.IGNORECASE
)
#: Credential files and directories the reviewer's commands may not read.
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
)
#: Paths in the scratch copy that tools write and nobody edits: Python's temp-directory fallback
#: (the sandbox denies the system temp roots, so ``tempfile`` falls back to the working directory),
#: pytest's caches and compiled bytecode. They never count as a change. ``.claude/`` is not among
#: them: Claude leaves only an empty ``.claude/.cc-writes/`` there (measured on 2.1.292), so a file
#: under it is one the session wrote, and saga's check refuses it.
REVIEWER_SCRATCH_IGNORED = re.compile(
    r"^(pytest-of-[^/]+/|\.pytest_cache/|tmp[a-z0-9_]{8}/)|(^|/)__pycache__/|\.pyc$"
)


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


_REVIEWER_UNTRUSTED_DIR_NAMES = frozenset(_reviewer_fold(n) for n in REVIEWER_UNTRUSTED_DIRS)
_REVIEWER_UNTRUSTED_FILE_NAMES = frozenset(_reviewer_fold(n) for n in REVIEWER_UNTRUSTED_FILES)
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


def reviewer_credential_variables(env: Mapping[str, str]) -> list[str]:
    """The environment variables hidden from sandboxed commands, by name."""
    return sorted(name for name in env if REVIEWER_CREDENTIAL_NAME.search(name))


def reviewer_session_environment(env: Mapping[str, str]) -> dict[str, str]:
    """The session's environment: everything, except what would sign in with an API key."""
    return {
        name: value
        for name, value in env.items()
        if name not in REVIEWER_API_KEY_VARIABLES
        and not name.startswith(REVIEWER_API_KEY_PREFIXES)
    }


def reviewer_claude_argv(model: str, effort: str | None, settings_path: Path) -> list[str]:
    """Claude's reviewer argv: headless, sandboxed through ``--settings``, JSON result."""
    argv = ["claude", "-p", "--model", model]
    if effort:
        argv += ["--effort", effort]
    return argv + [
        "--permission-mode", "dontAsk",
        "--settings", str(settings_path),
        "--output-format", "json",
        "--no-session-persistence",
    ]


def reviewer_claude_settings(
    packet: Path,
    env: Mapping[str, str],
    *,
    extra_deny_read: Sequence[str] = (),
    platform: str | None = None,
) -> dict[str, Any]:
    """The per-launch settings that turn on Claude's command sandbox and confine the session.

    Measured on Claude Code 2.1.292 on 2026-10-06: under ``dontAsk`` Bash is denied unless allowed,
    even with ``autoAllowBashIfSandboxed``; the sandbox's own temp directory stays writable until a
    ``denyWrite`` names its root; credential-named variables reach sandboxed commands until
    ``credentials.envVars`` denies them. The settings set no ``apiKeyHelper``, plugins or hooks, so
    the user's own configuration is what loads.
    """
    deny_read = list(REVIEWER_CREDENTIAL_PATHS) + list(extra_deny_read)
    return {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "filesystem": {
                "denyWrite": list(reviewer_temp_roots(platform)),
                "denyRead": deny_read,
            },
            "network": {"strictAllowlist": True, "allowedDomains": []},
            "credentials": {
                "envVars": [
                    {"name": name, "mode": "deny"} for name in reviewer_credential_variables(env)
                ]
            },
        },
        "permissions": {
            # ``//`` starts an absolute path in a permission rule; ``/`` is relative to the settings
            # file. ``packet.resolve()`` begins with ``/``, so this reads ``Read(//<packet>/**)``.
            "allow": ["Bash", "Edit(./**)", f"Read(/{packet.resolve()}/**)"],
            "deny": ["WebFetch", "WebSearch", "mcp__*"] + [f"Read({path})" for path in deny_read],
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


def reviewer_withhold_untrusted(copy: Path) -> list[str]:
    """Remove what the reviewed change could use to run or read outside the sandbox.

    Every ``.claude/`` directory and ``.mcp.json`` at any depth (Claude acts on them outside the
    command sandbox), every symlink that leaves the copy, and every instruction file whose possible
    ``@`` imports can leave the copy (Claude would load the imported file, a credential for example,
    into the reviewer's context). Returns each withheld path with the reason; the reviewer still
    sees them in the packet's diff.
    """
    withheld: list[str] = []

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
        if name in _REVIEWER_UNTRUSTED_DIR_NAMES and (path.is_dir() or path.is_symlink()):
            drop(path, "Claude would act on it outside the sandbox")
        elif name in _REVIEWER_UNTRUSTED_FILE_NAMES:
            drop(path, "Claude would act on it outside the sandbox")
        elif path.is_symlink() and not _reviewer_inside(path, copy):
            drop(path, "a symlink out of the copy")
    for path in sorted(copy.rglob("*")):
        if _reviewer_fold(path.name) in _REVIEWER_INSTRUCTION_NAMES and path.is_file() and (
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
    """SHA-256 over the sorted ``(label, content digest)`` pairs, and the labels that went in."""
    pairs = sorted(
        (label, hashlib.sha256(content).hexdigest() if content is not None else "absent")
        for label, content in sources
    )
    digest = hashlib.sha256(json.dumps(pairs, separators=(",", ":")).encode("utf-8"))
    return {"fingerprint": digest.hexdigest(), "sources": [label for label, _ in pairs]}


@dataclass(frozen=True)
class ReviewerRecipe:
    """How one vendor runs the targeted reviewer: argv, sandbox settings, result, configuration."""

    binary: str
    argv: Any
    settings: Any
    parse: Any
    config_sources: Any


#: The vendors with a reviewer recipe. A vendor joins only when ``reviewer-probe`` passes on it;
#: every other vendor is refused by name (plan KTD2: codex-cli 0.160.1's workspace-write sandbox
#: read a file outside its workspace on 2026-10-06).
REVIEWER_RECIPES: dict[str, ReviewerRecipe] = {
    "claude": ReviewerRecipe(
        binary="claude",
        argv=reviewer_claude_argv,
        settings=reviewer_claude_settings,
        parse=reviewer_parse_claude_result,
        config_sources=reviewer_claude_config_sources,
    ),
}


def reviewer_recipe(vendor: str) -> ReviewerRecipe:
    recipe = REVIEWER_RECIPES.get(vendor)
    if recipe is None:
        raise ReviewerRefused(
            f"{vendor} has no reviewer sandbox recipe that denies writes outside the copy, network "
            "and credential reads; it cannot staff the targeted reviewer"
        )
    return recipe


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
        if mode == "100755":
            target.chmod(0o755)
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
    withheld: Sequence[str] = (),
) -> str:
    """What the session reads on standard input: the wrapper, saga's prompt, where things are."""
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
    try:
        prompt_bytes = request.prompt.read_bytes()
    except OSError as exc:
        raise ReviewerRefused(f"cannot read the prompt {request.prompt}: {exc}") from None
    prompt_text = prompt_bytes.decode("utf-8")
    if _reviewer_front_matter(prompt_text).get("id") != REVIEWER_PROMPT_ID:
        raise ReviewerRefused(f"{request.prompt} is not saga's {REVIEWER_PROMPT_ID}")
    if not request.schema.is_file():
        raise ReviewerRefused(f"the answer schema {request.schema} does not exist")
    if not request.packet.is_dir():
        raise ReviewerRefused(f"the review packet {request.packet} is not a directory")
    wrapper = reviewer_wrapper_path()
    if not wrapper.is_file():
        raise ReviewerRefused(f"the roles library's wrapper {wrapper} is missing")
    widening = reviewer_claude_widening(environ) if request.vendor == "claude" else []
    if widening:
        raise ReviewerRefused(
            "settings outside the copy would widen the reviewer's sandbox: " + "; ".join(widening)
        )

    root = (request.work_root or reviewer_work_root(environ)) / (
        f"{request.repo.resolve().name}-{request.head[:12]}-{os.urandom(4).hex()}"
    )
    copy = root / "copy"
    reviewer_export_head(request.repo, request.head, copy)
    withheld = reviewer_withhold_untrusted(copy)
    manifest = _reviewer_manifest(copy)
    session_env = reviewer_session_environment(environ)
    settings_path = root / "settings.json"
    settings_path.write_text(
        json.dumps(recipe.settings(request.packet, session_env), indent=2) + "\n", "utf-8"
    )
    configuration = reviewer_configuration_fingerprint(recipe.config_sources(copy, session_env))
    message = reviewer_launch_message(
        wrapper.read_text(encoding="utf-8"), prompt_text, request.packet, copy,
        request.open_search_cap, withheld,
    )
    argv = recipe.argv(request.model, request.effort, settings_path)
    proc = session(argv, stdin=message, cwd=copy, env=session_env, timeout=request.timeout)
    parsed = recipe.parse(proc.stdout)
    answer, missing = reviewer_extract_answer(parsed["final"])

    request.out.mkdir(parents=True, exist_ok=True)
    answer_path = request.out / "answer.json"
    if answer is not None:
        answer_path.write_text(json.dumps(answer, indent=2, ensure_ascii=False) + "\n", "utf-8")
    if proc.returncode == REVIEWER_EXIT_TIMEOUT:
        code, error = REVIEWER_EXIT_TIMEOUT, "the session timed out"
    elif answer is None:
        code, error = REVIEWER_EXIT_NO_ANSWER, parsed.get("error") or missing
    else:
        code, error = 0, parsed.get("error")
    result = {
        "schema": REVIEWER_RESULT_SCHEMA,
        "vendor": request.vendor,
        "vendor_version": _reviewer_vendor_version(recipe.binary, session_env),
        "model": {"requested": request.model, "resolved": parsed["resolved"]},
        "effort": request.effort,
        "usage": parsed["usage"],
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "schema_sha256": hashlib.sha256(request.schema.read_bytes()).hexdigest(),
        "configuration": configuration,
        "scratch": {
            "path": str(copy),
            "withheld": withheld,
            "changes": reviewer_scratch_changes(copy, manifest),
        },
        "answer_path": str(answer_path) if answer is not None else None,
        "exit": code,
        "error": error,
    }
    (request.out / "result.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    return result, code


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
curl -sS -m 5 -o /dev/null https://example.com > /dev/null 2>&1; echo "network=$?" >> "$r"
if [ -n "${{REVIEWER_PROBE_TOKEN+x}}" ]; then v=set; else v=unset; fi; echo "variable=$v" >> "$r"
"""

REVIEWER_PROBE_MESSAGE = (
    "Run exactly this one Bash command, from your working directory, and then reply with the "
    "single word done: sh probe.sh"
)


def reviewer_probe_verdicts(
    root: Path, outside: Path, tag: str, canaries: Sequence[str], session_output: str
) -> list[dict[str, Any]]:
    """Judge each denial from outside the session: the filesystem and the command's own results."""
    copy = root / "copy"
    results_path = copy / "probe-results.txt"
    try:
        lines = results_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [{"denial": "results", "held": False,
                 "detail": "probe-results.txt is missing: the command did not run"}]
    results = dict(line.split("=", 1) for line in lines if "=" in line)
    seen = results_path.read_text(encoding="utf-8") + "\n" + session_output

    def nonzero(key: str) -> bool:
        return results.get(key, "0") not in ("", "0")

    verdicts = [
        ("read-credential", nonzero("read"), f"read={results.get('read')}"),
        ("write-outside", nonzero("write_outside") and not (outside / "written").exists(),
         f"write_outside={results.get('write_outside')}"),
        ("write-inside", results.get("write_inside") == "0" and (copy / "inside-written").exists(),
         f"write_inside={results.get('write_inside')}"),
        ("write-tmpdir", nonzero("write_tmpdir"), f"write_tmpdir={results.get('write_tmpdir')}"),
        ("write-tmp", nonzero("write_tmp") and not Path(f"/tmp/reviewer-probe-{tag}").exists(),
         f"write_tmp={results.get('write_tmp')}"),
        # 126 and 127 mean curl could not run, which proves nothing about the network.
        ("network", nonzero("network") and results.get("network") not in ("126", "127"),
         f"network={results.get('network')}"),
        ("credential-variable", results.get("variable") == "unset",
         f"variable={results.get('variable')}"),
        ("no-canary-in-output", not any(c in seen for c in canaries),
         "a canary value appeared in the results or the session's output"
         if any(c in seen for c in canaries) else "no canary value seen"),
    ]
    return [{"denial": name, "held": held, "detail": detail} for name, held, detail in verdicts]


def reviewer_probe(
    vendor: str,
    model: str,
    effort: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    session: Any = reviewer_run_session,
    work_root: Path | None = None,
    keep: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """Run *vendor*'s reviewer recipe live on a fixed command and check each denial."""
    recipe = reviewer_recipe(vendor)
    tag = os.urandom(6).hex()
    canary_file = f"reviewer-probe-canary-{os.urandom(8).hex()}"
    canary_variable = f"reviewer-probe-variable-{os.urandom(8).hex()}"
    environ = dict(os.environ if env is None else env)
    environ["REVIEWER_PROBE_TOKEN"] = canary_variable
    root = (work_root or reviewer_work_root(environ)) / f"probe-{tag}"
    copy, outside = root / "copy", root / "outside"
    copy.mkdir(parents=True)
    outside.mkdir()
    (outside / "canary.txt").write_text(canary_file + "\n", "utf-8")
    (copy / "probe.sh").write_text(REVIEWER_PROBE_SCRIPT.format(outside=outside, tag=tag), "utf-8")
    session_env = reviewer_session_environment(environ)
    settings_path = root / "settings.json"
    settings = recipe.settings(copy, session_env, extra_deny_read=[str(outside)])
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", "utf-8")
    try:
        proc = session(
            recipe.argv(model, effort, settings_path), stdin=REVIEWER_PROBE_MESSAGE, cwd=copy,
            env=session_env, timeout=300,
        )
        verdicts = reviewer_probe_verdicts(
            root, outside, tag, (canary_file, canary_variable),
            (proc.stdout or "") + (proc.stderr or ""),
        )
    finally:
        Path(f"/tmp/reviewer-probe-{tag}").unlink(missing_ok=True)
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
    return verdicts, 0 if all(v["held"] for v in verdicts) else 1


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
    probe_p = sub.add_parser(
        "reviewer-probe",
        help="Run a vendor's reviewer recipe live and check every sandbox denial",
        description=(
            "Run the reviewer recipe on one fixed command and check, from outside the session, "
            "that a credential read, writes outside the copy and to the temp roots, the network "
            "and a credential variable are denied and a write inside the copy works. Exit 0 when "
            "every denial held, 1 otherwise, 2 for a vendor with no recipe."
        ),
    )
    probe_p.add_argument("--vendor", required=True)
    probe_p.add_argument("--model", default="haiku")
    probe_p.add_argument("--effort", default=None)
    probe_p.add_argument("--keep", action="store_true", help="Keep the probe directory")


def _reviewer_cli(args: argparse.Namespace) -> int:
    try:
        if args.cmd == "reviewer-probe":
            verdicts, code = reviewer_probe(args.vendor, args.model, args.effort, keep=args.keep)
            json.dump(verdicts, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return code
        result, code = reviewer_launch(
            ReviewerRequest(
                vendor=args.vendor, model=args.model, effort=args.effort, repo=args.repo,
                head=args.head, packet=args.packet, prompt=args.prompt, schema=args.schema,
                out=args.out, open_search_cap=args.open_search_cap, timeout=args.timeout,
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
