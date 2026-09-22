#!/usr/bin/env python3
"""The roster helper — stand up and tear down one herdr session per staffed role (#1024).

``roster.py up`` reads an issue's run record, resolves every role its staffing plan names to a
vendor, a model, an effort and a prompt from the roles library, and creates one named herdr pane
per role. ``roster.py wait`` waits for those panes to settle. ``roster.py down`` closes exactly the
panes the record says this helper created, and nothing else.

Four rules shape the whole file, and each one is a plan decision with a test behind it:

**Panes are created through the launcher, never through raw herdr calls** (plan KTD1). The launcher
beside this file already owns the single door into a pane, the staged-input stop, and a launch
receipt whose ``owned`` field is computed from a pre-launch tab snapshot. Teardown proves ownership
from that receipt. There is no ``herdr agent close`` subcommand at all — closing is a tab operation
that the launcher performs — so re-implementing creation here would mean re-implementing the
ownership proof too, weakly.

**The record is the only authority on what may be closed** (plan R4). ``down`` never reads
``herdr agent list`` to decide. A live pane that this helper did not record is invisible to it.

**The wait always carries a timeout, and a blocked agent is reported rather than answered**
(plan R6, R7). ``herdr agent wait`` without ``--timeout`` waits forever, and without ``--until``
matches herdr's own settled set of idle, done and blocked — which is exactly the settled-state
default this helper wants.

**Every command refuses outside a herdr pane** (plan R8), with one line and exit 4.

Exit codes extend the run record's table (plan KTD6) rather than inventing a parallel one:

===== ======================================================================
 code  meaning
===== ======================================================================
  0    success
  1    an unexpected internal error
  2    a refusal: usage, an unreadable record, an unstaffable role, a failed
       launch or close
  3    the record carries a version this saga does not know
  4    this process is not running inside a herdr pane
  5    a role is blocked, or its wait timed out
===== ======================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- constants

#: This file lives at ``plugins/agent-launcher/skills/agent-launcher/scripts/roster.py``; the roles
#: library is ``plugins/agent-launcher/roles/``. Resolved from ``__file__`` so a session launched in
#: any working directory is briefed from an absolute path (plan KTD4).
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
ROLES_DIR = PLUGIN_ROOT / "roles"
ROLES_INDEX = ROLES_DIR / "index.json"
LAUNCHER = Path(__file__).resolve().parent / "launcher.py"

#: The row this helper writes into the run record's ``roster`` array.
ROSTER_ENTRY_SCHEMA = "roster_entry.v1"

#: Written to every row's ``created_by``. ``down`` acts on no other value.
CREATED_BY = "roster.py"

#: The staffing registry names roles in kebab case; the roles library names them by a snake-case
#: ``role_id``. They are neither the same spelling nor the same set, so the mapping is explicit
#: here and guarded by a drift test against both live registries (plan KTD2).
#:
#: ``merging-worker`` is deliberately absent: the staffing registry has a row for it, the lifecycle
#: role catalogue names no such role, and the roles library therefore ships no prompt. Inventing a
#: briefing for it is the drift the roles library forbids, so it is a named refusal (plan KTD3).
STAFFING_ROLE_TO_ROLE_ID: dict[str, str] = {
    "planner": "planner",
    "plan-reviewer": "plan_reviewer",
    "worker": "implementer",
    "lens-reviewer": "lens_reviewer",
    "functional-tester": "functional_tester",
    "release-worker": "release_worker",
}

#: The staffing role whose seats are multiplied by the run's applicable lenses.
LENS_ROLE = "lens-reviewer"

#: States a roster row moves through. ``down`` skips ``closed``.
STATE_CREATED = "created"
STATE_PROMPTED = "prompted"
STATE_SETTLED = "settled"
STATE_BLOCKED = "blocked"
STATE_CLOSED = "closed"

#: herdr reports these when an agent has finished its turn.
SETTLED_STATUSES = frozenset({"idle", "done"})

#: Default caller timeout for one wait, in milliseconds. Always sent; herdr waits forever without
#: one.
DEFAULT_WAIT_TIMEOUT_MS = 600_000

#: Seconds allowed for one launcher or herdr invocation before it is treated as no answer.
LAUNCH_TIMEOUT_SECONDS = 420.0
HERDR_TIMEOUT_SECONDS = 30.0

#: How many lines of a blocked pane's output are quoted in the report.
BLOCKED_TAIL_LINES = 40

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_REFUSED = 2
EXIT_UNKNOWN_VERSION = 3
EXIT_NOT_IN_PANE = 4
EXIT_BLOCKED = 5


# --------------------------------------------------------------------------- errors


class RosterError(RuntimeError):
    """A refusal this module owns. The command line maps it to exit 2."""


class NotInHerdrPaneError(RosterError):
    """This process is not running inside a herdr pane. Exit 4, one line."""


class UnknownRecordVersionError(RosterError):
    """The run record carries a version this saga does not know. Exit 3, one line."""


class RoleBlockedError(RosterError):
    """A role is blocked, or its wait timed out. Exit 5 — reported, never answered."""


# --------------------------------------------------------------------------- the runner


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def run(
    cmd: Sequence[str],
    *,
    check: bool = False,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and return its result, mirroring ``launcher.run``'s signature (plan KTD7).

    ``check=False`` means every failure — including a program that is not installed — comes back as
    a result rather than an exception, so a machine without herdr gets a refusal, not a traceback.
    """
    try:
        proc = subprocess.run(  # noqa: S603 - argv is built here, never shell-interpolated
            list(cmd), capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(list(cmd), 127, "", str(exc))
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(list(cmd), 124, "", f"timed out after {timeout}s")
    if check and proc.returncode != 0:
        raise RosterError(f"{' '.join(cmd)} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc


# --------------------------------------------------------------------------- preconditions


def require_herdr_pane(env: Mapping[str, str] | None = None) -> str:
    """Return this session's pane id, or refuse (plan R8).

    The card's own verification line tests ``HERDR_ENV``; the pane id is what makes the session
    identifiable, and R14 needs it to refuse closing the pane the helper runs in.
    """
    environ = os.environ if env is None else env
    if environ.get("HERDR_ENV") != "1" or not environ.get("HERDR_PANE_ID"):
        raise NotInHerdrPaneError(
            "roster: this command controls herdr sessions and must run inside a herdr pane; "
            "HERDR_ENV=1 and HERDR_PANE_ID are not both set"
        )
    return str(environ["HERDR_PANE_ID"])


# --------------------------------------------------------------------------- the run record


def _run_record_module() -> Any:
    """Import saga's ``run_record`` from the sibling plugin, by path (plan KTD8).

    The two plugins are installed side by side and neither is importable as a package, so the
    module is loaded from its file. A missing sibling is a refusal naming the path, never a
    traceback out of an import statement.
    """
    import importlib.util

    path = PLUGIN_ROOT.parent / "saga" / "scripts" / "run_record.py"
    if not path.is_file():
        raise RosterError(
            f"roster: the run record module is not at {path}; the saga plugin must be installed "
            "beside agent-launcher"
        )
    spec = importlib.util.spec_from_file_location("run_record", path)
    if spec is None or spec.loader is None:
        raise RosterError(f"roster: cannot load the run record module at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("run_record", module)
    spec.loader.exec_module(module)
    return module


def resolve_record_location(
    *,
    record: str | None = None,
    issue: int | None = None,
    store_root: str | None = None,
) -> tuple[Path, int]:
    """Return ``(store root, issue number)`` from ``--record`` or ``--issue`` (plan KTD10).

    The card writes the flag as ``--record <path>``; the run record module's own interface is a
    store root plus an issue number. Rather than break one of the two, ``--record`` takes the
    record file and the store root and issue are derived from it, and ``--issue`` resolves the
    store root the way every other saga consumer does. Passing both, or neither, is a refusal.
    """
    if record and issue is not None:
        raise RosterError("roster: pass --record or --issue, not both")
    if record:
        path = Path(record).expanduser().resolve()
        match = re.fullmatch(r"issue-(\d+)", path.stem)
        if match is None:
            raise RosterError(
                f"roster: {path} is not a run record path; expected a file named issue-<N>.json"
            )
        return path.parent, int(match.group(1))
    if issue is None:
        raise RosterError("roster: pass --record <path> or --issue <N>")
    if store_root:
        return Path(store_root).expanduser().resolve(), int(issue)
    module = _run_record_module()
    return Path(module.resolve_store_root()), int(issue)


def load_record(store_root: Path, issue: int) -> Any:
    """Load the record, mapping an unknown version onto this module's own exit-3 error."""
    module = _run_record_module()
    try:
        record = module.load(store_root, issue)
    except module.UnknownRecordVersionError as exc:
        raise UnknownRecordVersionError(str(exc)) from None
    except module.RunRecordError as exc:
        raise RosterError(f"roster: {exc}") from None
    if record is None:
        raise RosterError(
            f"roster: there is no run record for issue {issue} in {store_root}; "
            "run the admission step first"
        )
    return record


def save_record(store_root: Path, record: Any, roster_rows: list[dict[str, Any]]) -> Path:
    """Write *roster_rows* onto the record's ``roster`` array, and nothing else (plan R11)."""
    module = _run_record_module()
    updated = module.RunRecord(**{**record.__dict__, "roster": roster_rows})
    return Path(module.save(store_root, updated))


# --------------------------------------------------------------------------- the roles library


def load_roles_index(path: Path | None = None) -> dict[str, Any]:
    """Read the roles library index, which publishes the file per role and the lens slicing rule."""
    index_path = path or ROLES_INDEX
    if not index_path.is_file():
        raise RosterError(f"roster: the roles library index is not at {index_path}")
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RosterError(f"roster: {index_path} does not hold a JSON object")
    return data


def role_file_name(index: Mapping[str, Any], role_id: str) -> str:
    """Return the prompt file for *role_id*, or refuse naming it (plan R9)."""
    for row in index.get("roles", []):
        if isinstance(row, Mapping) and row.get("role_id") == role_id:
            return str(row["file"])
    raise RosterError(
        f"roster: the roles library has no prompt for role_id {role_id!r}; "
        "it cannot be staffed without one"
    )


def lens_ids(index: Mapping[str, Any]) -> tuple[str, ...]:
    """The lens identifiers the Lens Reviewer prompt carries a section for."""
    block = index.get("lens_reviewer")
    if not isinstance(block, Mapping):
        return ()
    return tuple(str(x) for x in block.get("lens_ids", []))


def lens_section(text: str, index: Mapping[str, Any], lens: str) -> str:
    """Cut the Lens Reviewer prompt down to its shared half plus *lens*'s own section (plan R5).

    The slicing rule comes from ``index.json`` — the heading prefix, the terminator pattern, and
    where the shared half ends — because the roles library publishes it precisely so a consumer
    does not keep a second copy that can drift from the file it cuts.
    """
    block = index.get("lens_reviewer")
    if not isinstance(block, Mapping):
        raise RosterError("roster: the roles library index carries no lens_reviewer slicing rule")
    marker = str(block["shared_half_ends_before"])
    prefix = str(block["section_heading_prefix"])
    terminator = re.compile(str(block["section_terminator_pattern"]), re.MULTILINE)

    head, sep, tail = text.partition(marker)
    if not sep:
        raise RosterError(
            f"roster: the Lens Reviewer prompt has no {marker!r} marker, so it cannot be sliced"
        )
    start = tail.find(f"{prefix}{lens}\n")
    if start < 0:
        raise RosterError(
            f"roster: the Lens Reviewer prompt carries no section for lens {lens!r}; "
            f"it has {', '.join(lens_ids(index)) or 'none'}"
        )
    rest = tail[start + len(prefix) + len(lens) :]
    end_match = terminator.search(rest)
    end = start + len(prefix) + len(lens) + (end_match.start() if end_match else len(rest))
    return head + tail[start:end].rstrip() + "\n"


# --------------------------------------------------------------------------- seats


@dataclass(frozen=True)
class Seat:
    """One role session to create: who it is, what it runs on, and what it is called."""

    role: str
    role_id: str
    prompt_file: str
    vendor: str
    model: str
    effort: str
    pane_name: str
    lens: str | None = None
    account: str | None = None

    @property
    def prompt_path(self) -> Path:
        return ROLES_DIR / self.prompt_file


def _parameter(record: Any, name: str) -> Any:
    entry = record.run_configuration.get(name)
    if isinstance(entry, Mapping):
        return entry.get("value")
    return entry


def plan_seats(
    record: Any,
    *,
    index: Mapping[str, Any] | None = None,
    name_prefix: str | None = None,
    account: str | None = None,
) -> list[Seat]:
    """Turn the record's staffing plan into one seat per role, refusing anything unstaffable."""
    roles_index = index if index is not None else load_roles_index()
    staffing = _parameter(record, "staffing_models_and_efforts")
    if not isinstance(staffing, Mapping) or not staffing:
        raise RosterError(
            f"roster: issue {record.issue} has no staffing plan; "
            "run_configuration.staffing_models_and_efforts is unset"
        )
    lenses = _parameter(record, "applicable_lenses")
    declared_lenses = [str(x) for x in lenses] if isinstance(lenses, Sequence) else []
    prefix = name_prefix if name_prefix is not None else f"issue-{record.issue}-"

    seats: list[Seat] = []
    for role in sorted(staffing):
        row = staffing[role]
        if not isinstance(row, Mapping):
            raise RosterError(f"roster: the staffing plan's entry for {role!r} is not an object")
        role_id = STAFFING_ROLE_TO_ROLE_ID.get(str(role))
        if role_id is None:
            raise RosterError(
                f"roster: the staffing plan names role {role!r}, which has no prompt in the roles "
                f"library; staffable roles are {', '.join(sorted(STAFFING_ROLE_TO_ROLE_ID))}"
            )
        prompt_file = role_file_name(roles_index, role_id)
        vendor = str(row.get("vendor") or "")
        model = str(row.get("model") or "")
        effort = str(row.get("effort") or "")
        if not vendor or not model or not effort:
            raise RosterError(
                f"roster: the staffing plan's entry for {role!r} is missing a vendor, model or "
                "effort, so the session cannot be launched"
            )
        # The account a session runs under is not a tier, so the staffing component does not carry
        # one today. Without it the wrapper falls back to its own default, which is the personal
        # account — so the caller names the account once for the roster, and a staffing row may
        # override it per role if that registry ever grows the field.
        seat_account = str(row.get("account") or "") or account
        if role == LENS_ROLE:
            if not declared_lenses:
                raise RosterError(
                    "roster: the staffing plan staffs a lens reviewer but the run declares no "
                    "applicable lenses; a lens reviewer with no lens has nothing to review"
                )
            for lens in declared_lenses:
                seats.append(
                    Seat(
                        role=str(role),
                        role_id=role_id,
                        prompt_file=prompt_file,
                        vendor=vendor,
                        model=model,
                        effort=effort,
                        pane_name=f"{prefix}lens-{lens}",
                        lens=lens,
                        account=seat_account,
                    )
                )
        else:
            seats.append(
                Seat(
                    role=str(role),
                    role_id=role_id,
                    prompt_file=prompt_file,
                    vendor=vendor,
                    model=model,
                    effort=effort,
                    pane_name=f"{prefix}{role}",
                    account=seat_account,
                )
            )

    names = [seat.pane_name for seat in seats]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise RosterError(
            f"roster: two seats resolve to the same pane name ({', '.join(duplicates)}); "
            "the launcher splits a pane inside an existing tab rather than failing on a duplicate "
            "label, so this is refused before any launch"
        )
    return seats


def dispatch_brief(seat: Seat, record: Any, record_path: Path) -> str:
    """The text one session is sent: what it is, where its briefing is, where the run state is.

    The role prompt is named by absolute path rather than pasted (plan KTD4): a lens reviewer's
    prompt is 15 KB, and a composer write is the riskiest thing this helper does.
    """
    lines = [
        f"You are the {seat.role_id.replace('_', ' ')} for "
        f"{record.repo or 'this repository'} issue {record.issue}.",
        f"Read your role briefing first: {seat.prompt_path}",
    ]
    if seat.lens:
        lines.append(f"Your lens is {seat.lens}; apply only that lens's section of the briefing.")
    lines += [
        f"The run record holding this run's state is {record_path}.",
        "Follow the briefing's stop rule and post the output contract it names. "
        "Do not start any other role's work.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- roster rows


def _now() -> str:
    return datetime.now(UTC).isoformat()


def workspace_of(receipt: Mapping[str, Any]) -> str | None:
    """The workspace a launch landed in, taken from its identifiers.

    The launcher's receipt (``launch_receipt_shape``) carries ``tab_id`` and ``pane`` but **no**
    ``workspace_id`` field, so reading one off the receipt records ``null`` forever. herdr's
    identifiers are ``<workspace>:<object>``, which is how the launcher itself recovers a workspace
    when a close fails (``launcher.py``: ``str(unit.tab_id).partition(":")[0]``). Same rule here,
    so the roster row names the workspace an operator would have to look in.
    """
    for key in ("workspace_id", "tab_id", "pane"):
        value = receipt.get(key)
        if not value:
            continue
        head = str(value).partition(":")[0]
        if head:
            return head
    return None


def new_row(
    seat: Seat, receipt: Mapping[str, Any], receipt_path: Path, state: str
) -> dict[str, Any]:
    """Build the ``roster_entry.v1`` row recorded for one created pane (plan R3)."""
    return {
        "schema": ROSTER_ENTRY_SCHEMA,
        "role": seat.role,
        "role_id": seat.role_id,
        "lens": seat.lens,
        "prompt_file": seat.prompt_file,
        "vendor": seat.vendor,
        "model": seat.model,
        "effort": seat.effort,
        "agent_name": receipt.get("agent_name") or seat.pane_name,
        "pane_name": seat.pane_name,
        "pane_id": receipt.get("pane"),
        "tab_id": receipt.get("tab_id"),
        "workspace_id": workspace_of(receipt),
        "receipt_path": str(receipt_path),
        "created_by": CREATED_BY,
        "created_at": _now(),
        "state": state,
        "closed_at": None,
    }


def receipts_dir(store_root: Path, issue: int) -> Path:
    """Where launch receipts live: beside the run record, outside every worktree (plan KTD9).

    A receipt written into a unit's worktree disappears when that worktree is removed, and teardown
    then cannot prove ownership — so the panes leak.
    """
    return store_root / "receipts" / f"issue-{issue}"


def _live_row(rows: Sequence[Mapping[str, Any]], pane_name: str) -> Mapping[str, Any] | None:
    """The recorded row for *pane_name* that is not yet closed, if there is one (plan R12)."""
    for row in rows:
        if row.get("pane_name") == pane_name and row.get("state") != STATE_CLOSED:
            return row
    return None


# --------------------------------------------------------------------------- up


def render_dry_run(seats: Sequence[Seat], record: Any, record_path: Path) -> str:
    """What ``up --dry-run`` prints: the panes, kinds, models, efforts and prompts (plan R2)."""
    out = [f"roster: issue {record.issue} would create {len(seats)} pane(s); nothing was created."]
    for seat in seats:
        out.append("")
        out.append(f"pane   {seat.pane_name}")
        out.append(f"  kind   {seat.vendor}")
        out.append(f"  model  {seat.model}")
        out.append(f"  effort {seat.effort}")
        out.append(f"  role   {seat.role} ({seat.role_id})")
        if seat.lens:
            out.append(f"  lens   {seat.lens}")
        out.append(f"  brief  {seat.prompt_path}")
        for line in dispatch_brief(seat, record, record_path).splitlines():
            out.append(f"    | {line}")
    return "\n".join(out)


def up(
    store_root: Path,
    issue: int,
    *,
    runner: Runner = run,
    dry_run: bool = False,
    cwd: Path | None = None,
    name_prefix: str | None = None,
    account: str | None = None,
    env: Mapping[str, str] | None = None,
    index: Mapping[str, Any] | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """Create one named pane per staffed role, recording each before doing anything else."""
    require_herdr_pane(env)
    record = load_record(store_root, issue)
    module = _run_record_module()
    record_path = Path(module.record_path(store_root, issue))
    seats = plan_seats(record, index=index, name_prefix=name_prefix, account=account)

    if dry_run:
        out(render_dry_run(seats, record, record_path))
        return EXIT_OK

    allocation = _parameter(record, "concurrency_allocation")
    if isinstance(allocation, int) and len(seats) > allocation:
        raise RosterError(
            f"roster: the staffing plan needs {len(seats)} panes but the run's concurrency "
            f"allocation is {allocation}; a role session is long-lived, so there is no later turn "
            "in which the rest would start"
        )

    rows: list[dict[str, Any]] = [dict(row) for row in record.roster]
    directory = receipts_dir(store_root, issue)
    directory.mkdir(parents=True, exist_ok=True)
    failures = 0

    for seat in seats:
        existing = _live_row(rows, seat.pane_name)
        if existing is not None:
            out(
                f"roster: {seat.pane_name} is already recorded as {existing.get('state')}; "
                "skipping (up is idempotent per role)"
            )
            continue
        receipt_path = directory / f"{seat.pane_name}.json"
        argv = [
            sys.executable,
            str(LAUNCHER),
            "launch",
            "--vendor",
            seat.vendor,
            "--task",
            seat.pane_name,
            "--cwd",
            str(cwd or Path.cwd()),
            "--model",
            seat.model,
            "--effort",
            seat.effort,
            "--prompt",
            dispatch_brief(seat, record, record_path),
        ]
        if seat.account:
            argv += ["--account", seat.account]
        proc = runner(argv, check=False, timeout=LAUNCH_TIMEOUT_SECONDS)
        receipt = _parse_receipt(proc.stdout)
        if receipt is None:
            failures += 1
            out(
                f"roster: launching {seat.pane_name} produced no receipt "
                f"(exit {proc.returncode}): {(proc.stderr or '').strip()}"
            )
            break
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", "utf-8")
        delivered = receipt.get("prompt_delivered") is not False
        rows.append(
            new_row(
                seat,
                receipt,
                receipt_path,
                STATE_PROMPTED if delivered else STATE_CREATED,
            )
        )
        save_record(store_root, record, rows)
        if not delivered:
            failures += 1
            out(
                f"roster: {seat.pane_name} was created but its prompt was not delivered; "
                "the session is recorded and left alone — clear the composer and use "
                "`launcher.py redeliver` by hand, never a second launch"
            )
            continue
        if proc.returncode != 0:
            failures += 1
            out(f"roster: launching {seat.pane_name} exited {proc.returncode}")
            break
        out(f"roster: created {seat.pane_name} ({seat.vendor} {seat.model}/{seat.effort})")

    save_record(store_root, record, rows)
    return EXIT_REFUSED if failures else EXIT_OK


def _parse_receipt(stdout: str | None) -> dict[str, Any] | None:
    """The launcher prints one JSON receipt on stdout; anything else is no receipt."""
    if not stdout or not stdout.strip():
        return None
    try:
        loaded = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


# --------------------------------------------------------------------------- wait


def wait(
    store_root: Path,
    issue: int,
    *,
    runner: Runner = run,
    timeout_ms: int = DEFAULT_WAIT_TIMEOUT_MS,
    env: Mapping[str, str] | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """Wait for every recorded pane to settle, under a caller timeout (plan R6, R7)."""
    require_herdr_pane(env)
    record = load_record(store_root, issue)
    rows: list[dict[str, Any]] = [dict(row) for row in record.roster]
    unsettled: list[str] = []

    for row in rows:
        if row.get("created_by") != CREATED_BY or row.get("state") in (
            STATE_CLOSED,
            STATE_SETTLED,
        ):
            continue
        target = str(row.get("agent_name") or row.get("pane_name") or "")
        if not target:
            continue
        # No --until: herdr's own default matches idle, done or blocked, which is the settled-state
        # set this helper wants. --timeout is never omitted; herdr waits forever without one.
        proc = runner(
            ["herdr", "agent", "wait", target, "--timeout", str(timeout_ms)],
            check=False,
            timeout=(timeout_ms / 1000.0) + HERDR_TIMEOUT_SECONDS,
        )
        if proc.returncode != 0:
            unsettled.append(f"{row.get('pane_name')} (wait did not settle within {timeout_ms}ms)")
            out(
                f"roster: {row.get('pane_name')} did not settle within {timeout_ms}ms: "
                f"{(proc.stderr or proc.stdout or '').strip()}"
            )
            continue
        status = _agent_status(runner, target)
        if status == STATE_BLOCKED:
            row["state"] = STATE_BLOCKED
            unsettled.append(f"{row.get('pane_name')} (blocked)")
            out(
                f"roster: {row.get('pane_name')} is BLOCKED on pane {row.get('pane_id')}; "
                "reporting it, not answering it:"
            )
            out(_agent_tail(runner, target))
            continue
        if status in SETTLED_STATUSES:
            row["state"] = STATE_SETTLED
            out(f"roster: {row.get('pane_name')} settled ({status})")
            continue
        unsettled.append(f"{row.get('pane_name')} (status {status})")
        out(f"roster: {row.get('pane_name')} reports status {status}")

    save_record(store_root, record, rows)
    if unsettled:
        raise RoleBlockedError("roster: these roles did not settle: " + "; ".join(unsettled))
    return EXIT_OK


def _agent_status(runner: Runner, target: str) -> str:
    proc = runner(["herdr", "agent", "get", target], check=False, timeout=HERDR_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        return "unknown"
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return "unknown"
    result = payload.get("result") if isinstance(payload, dict) else None
    row = result.get("agent") if isinstance(result, dict) else None
    if not isinstance(row, dict):
        row = result if isinstance(result, dict) else {}
    return str(row.get("agent_status") or "unknown")


def _agent_tail(runner: Runner, target: str) -> str:
    proc = runner(
        [
            "herdr",
            "agent",
            "read",
            target,
            "--source",
            "recent",
            "--lines",
            str(BLOCKED_TAIL_LINES),
        ],
        check=False,
        timeout=HERDR_TIMEOUT_SECONDS,
    )
    return (proc.stdout or proc.stderr or "").rstrip()


# --------------------------------------------------------------------------- down


def down(
    store_root: Path,
    issue: int,
    *,
    runner: Runner = run,
    env: Mapping[str, str] | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """Close exactly the panes the record says this helper created (plan R4, R14)."""
    own_pane = require_herdr_pane(env)
    record = load_record(store_root, issue)
    rows: list[dict[str, Any]] = [dict(row) for row in record.roster]
    closed = 0
    failures = 0

    for row in rows:
        name = row.get("pane_name") or row.get("agent_name")
        reason = _skip_reason(row, own_pane)
        if reason is not None:
            out(f"roster: leaving {name} alone — {reason}")
            continue
        receipt_path = str(row["receipt_path"])
        proc = runner(
            [sys.executable, str(LAUNCHER), "close", "--receipt-json", receipt_path],
            check=False,
            timeout=HERDR_TIMEOUT_SECONDS,
        )
        if proc.returncode != 0:
            failures += 1
            out(
                f"roster: closing {name} failed (exit {proc.returncode}): "
                f"{(proc.stderr or proc.stdout or '').strip()}"
            )
            continue
        row["state"] = STATE_CLOSED
        row["closed_at"] = _now()
        closed += 1
        out(f"roster: closed {name}")

    save_record(store_root, record, rows)
    out(f"roster: closed {closed} pane(s) this helper created")
    return EXIT_REFUSED if failures else EXIT_OK


def _skip_reason(row: Mapping[str, Any], own_pane: str) -> str | None:
    """Why this recorded row must not be closed, or ``None`` when it may be."""
    if row.get("created_by") != CREATED_BY:
        return f"its created_by is {row.get('created_by')!r}, not {CREATED_BY!r}"
    if row.get("state") == STATE_CLOSED:
        return "it is already closed"
    if row.get("pane_id") and str(row.get("pane_id")) == own_pane:
        return "it is the pane this command is running in"
    receipt_path = row.get("receipt_path")
    if not receipt_path:
        return "it records no ownership receipt"
    if not Path(str(receipt_path)).is_file():
        return f"its ownership receipt {receipt_path} is missing"
    return None


# --------------------------------------------------------------------------- command line


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="roster.py",
        description="Stand up and tear down one herdr session per staffed role.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in (
        ("up", "Create one named pane per staffed role"),
        ("wait", "Wait for every recorded pane to settle"),
        ("down", "Close exactly the panes this helper created"),
    ):
        child = sub.add_parser(name, help=help_text)
        child.add_argument("--record", default=None, help="Absolute path of the run record")
        child.add_argument("--issue", type=int, default=None, help="Issue number")
        child.add_argument("--store-root", default=None, help="Override the run record store root")
        if name == "up":
            child.add_argument(
                "--dry-run",
                action="store_true",
                help="Print the panes, kinds, models and prompts; create nothing",
            )
            child.add_argument("--cwd", default=None, help="Working directory for each session")
            child.add_argument(
                "--name-prefix",
                default=None,
                help="Override the issue-<N>- pane-name prefix",
            )
            child.add_argument(
                "--account",
                default=None,
                choices=("company", "personal"),
                help="Account each session launches under; without it the wrapper's own "
                "default applies, which is the personal account",
            )
        if name == "wait":
            child.add_argument(
                "--timeout",
                type=int,
                default=DEFAULT_WAIT_TIMEOUT_MS,
                help="Caller timeout for each wait, in milliseconds",
            )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store_root, issue = resolve_record_location(
            record=args.record, issue=args.issue, store_root=args.store_root
        )
        if args.cmd == "up":
            return up(
                store_root,
                issue,
                dry_run=args.dry_run,
                cwd=Path(args.cwd).resolve() if args.cwd else None,
                name_prefix=args.name_prefix,
                account=args.account,
            )
        if args.cmd == "wait":
            return wait(store_root, issue, timeout_ms=args.timeout)
        return down(store_root, issue)
    except NotInHerdrPaneError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_NOT_IN_PANE
    except UnknownRecordVersionError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_UNKNOWN_VERSION
    except RoleBlockedError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BLOCKED
    except RosterError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
