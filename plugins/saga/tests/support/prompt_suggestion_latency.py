#!/usr/bin/env python3
"""Measure whether a `UserPromptSubmit` hook can suggest a saga command fast enough.

Issue 1038, an exploration. The plan is
`docs/plans/2026-09-19-issue-1038-prompt-suggestion-latency-plan.md`; the deliverable it
feeds is `docs/analysis/2026-09-19-prompt-suggestion-latency.md`.

The question is not "how fast is the API" -- that was already measured at roughly a third
of a second. It is whether the *hook*, which pays a process start and whatever the client
costs on top, can stay inside 400 milliseconds at the 95th percentile, and which shape of
persistent local client changes that answer.

Six shapes are timed, plus a floor:

* ``floor`` -- a process that starts, prints nothing and exits. The irreducible cost of
  having a hook at all. If this exceeds the target, no client design can rescue it.
* ``s0`` / ``s1`` -- a cold process making one, then two sequential API requests.
* ``s2`` / ``s3`` -- the same two request counts against a resident process.
* ``s4`` -- a resident process serving an answer from the client's own cache: no network.
* ``s5`` -- a resident process that answers from the *previous* prompt and computes this
  one in the background. The only shape with no blocking call on the critical path.

Everything is timed the way Claude Code pays for it (plan R4): wall clock around a
subprocess spawn, its output read, and its exit -- never an in-process figure.

Three properties this module exists to keep honest:

* **The key is never touched here.** Only `typesafe_client` reads ``TYPESAFE_API_KEY``, at
  request-build time, into one header. This file never reads it, prints it or stores it.
* **Only synthetic prompts are sent.** The corpus is hand-written for this exploration.
  No operator prompt, no transcript, no issue body (plan R3).
* **Nothing is left running.** The resident process is started and stopped by this harness
  in a ``finally``, and its identifier is reported so a caller can confirm it is gone.

Run the measurement::

    python3 tools/prompt_suggestion_latency.py measure --trials 30 --out results.json

Tests drive the pieces directly with a fake client and touch no network.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import select
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# This file lives at plugins/saga/tests/support/. parents[4] is the catalog root.
REPO_ROOT = Path(__file__).resolve().parents[4]
INPUTS_DIR = Path(__file__).resolve().parents[1] / "data" / "prompt-suggestion-latency"
SAGA_COMMANDS = (
    Path(__file__).resolve().parents[2] / "com.infiquetra.claude" / "commands"
)
CORPUS_PATH = INPUTS_DIR / "corpus.json"
QUESTIONS_PATH = INPUTS_DIR / "questions.json"

# The ceiling on how many candidates the verification pass re-checks.
#
# A known and deliberate deviation from the vendor cookbook, recorded here because the
# measured numbers depend on it. The cookbook re-ranks the top THREE candidates; the
# choice primitive returns one winner, and building a genuine top-three would mean reading
# the answer's `probabilities` map. This harness verifies only the single winner, so the
# cap below is a ceiling the shortlist never reaches. The call count -- and therefore every
# latency figure -- is identical either way, because both variants make exactly one
# verification request; only the two-request shapes' ACCURACY could differ under a real
# three-candidate shortlist. Named as a limitation in the deliverable rather than changed
# after the fact, so the shipped code is the code that produced the reported numbers.
SHORTLIST_SIZE = 3

# The hard client-side deadline a hook gives the resident process before it gives up and
# prints nothing (plan KTD6). Generous next to the 400 ms target and still far below any
# delay an operator would attribute to the hook rather than to the model.
CLIENT_DEADLINE_SECONDS = 0.5

# What the *measurement* allows, which is a different thing entirely. The operator-grade
# deadline above is a policy: past it a hook gives up and says nothing. Timing a shape
# against that policy measures the policy -- every trial returns at the deadline and the
# recorded number is the deadline, not the work. Worse, the empty answer that comes back
# looks exactly like a shape that decided to stay quiet. So the measurement waits long
# enough for every shape to finish, records the real service time, and reports separately
# how much of that distribution would fall foul of the operator-grade deadline.
MEASUREMENT_DEADLINE_SECONDS = 15.0

# Owner-only, on both the socket and the directory holding it (plan KTD3). The resident
# process holds a live credential and answers whatever connects to it.
SOCKET_MODE = 0o600
SOCKET_DIR_MODE = 0o700

# A Unix domain socket path is bounded by the platform's `sockaddr_un.sun_path`, which is
# 104 bytes on macOS and 108 on Linux. This is not a detail that can be left to chance
# here: the session scratch directory this harness is told to write into is itself well
# over that limit, so a socket placed beside the results would fail to bind with an error
# that names the length and nothing else. The socket therefore gets its own short
# directory, and the limit is checked with a message that says what to do about it.
SUN_PATH_MAX = 100

SHAPE_NAMES = ("floor", "s0", "s1", "s2", "s3", "s4", "s5")
WARM_SHAPES = frozenset({"s2", "s3", "s4", "s5"})
COLD_SHAPES = frozenset({"s0", "s1"})

NO_SUGGESTION = "none"

# The line the resident process prints once it is listening. Defined here and imported by
# the daemon so the writer and the reader cannot drift apart.
READY_PREFIX = "READY "


class HarnessError(RuntimeError):
    """A measurement could not be set up. Never carries a credential."""


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Prompt:
    """One synthetic operator prompt and the command it ought to draw."""

    id: str
    text: str
    expected: str
    why: str = ""

    @property
    def wants_command(self) -> bool:
        return self.expected != NO_SUGGESTION


def load_corpus(path: Path = CORPUS_PATH) -> list[Prompt]:
    """Read the synthetic prompt corpus."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = raw.get("prompts")
    if not isinstance(entries, list) or not entries:
        raise HarnessError(f"{path} carries no prompts")
    prompts = []
    for entry in entries:
        missing = [key for key in ("id", "text", "expected") if not entry.get(key)]
        if missing:
            raise HarnessError(f"{path}: an entry is missing {', '.join(missing)}")
        prompts.append(
            Prompt(
                id=str(entry["id"]),
                text=str(entry["text"]),
                expected=str(entry["expected"]),
                why=str(entry.get("why", "")),
            )
        )
    return prompts


def load_questions(path: Path = QUESTIONS_PATH) -> dict[str, Any]:
    """Read the question wording and thresholds."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("wide", "verify", "thresholds"):
        if key not in raw:
            raise HarnessError(f"{path} is missing the {key!r} section")
    return raw


def load_roster(commands_dir: Path) -> dict[str, str]:
    """Map each installed saga command to the first line of its description.

    The roster is read rather than hard-coded so the measurement ranks what is actually
    installed. Its size is part of the finding: a 24-command roster is an order of
    magnitude smaller than the 182-skill roster the vendor cookbook reports.
    """
    directory = Path(commands_dir)
    if not directory.is_dir():
        raise HarnessError(f"no command directory at {directory}")
    roster: dict[str, str] = {}
    for path in sorted(directory.glob("*.md")):
        roster[path.stem] = _first_description_line(path)
    if not roster:
        raise HarnessError(f"no commands found under {directory}")
    return roster


def _first_description_line(path: Path) -> str:
    """The command's own description, from frontmatter or its first prose line."""
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("description:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "-", "`", "---")):
            return stripped
    return path.stem


# --------------------------------------------------------------------------- #
# Statistics -- ordinary arithmetic, never a model call
# --------------------------------------------------------------------------- #


def percentile(values: Sequence[float], fraction: float) -> float:
    """The nearest-rank percentile of ``values``.

    Nearest-rank rather than interpolated: with thirty samples an interpolated 95th
    percentile invents a value between two observations, and every figure this harness
    reports should be one it actually measured.
    """
    if not values:
        raise HarnessError("a percentile needs at least one value")
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def summarize(values: Sequence[float]) -> dict[str, Any]:
    """The five figures requirement R6 names, with the count beside the percentiles."""
    if not values:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "min_ms": None, "max_ms": None}
    return {
        "count": len(values),
        "p50_ms": round(percentile(values, 0.50), 1),
        "p95_ms": round(percentile(values, 0.95), 1),
        "min_ms": round(min(values), 1),
        "max_ms": round(max(values), 1),
    }


# --------------------------------------------------------------------------- #
# The suggestion itself
# --------------------------------------------------------------------------- #


@dataclass
class Suggestion:
    """What one suggestion attempt produced, and what it cost."""

    command: str = NO_SUGGESTION
    calls: int = 0
    gate: float | None = None
    fits: float | None = None
    usage: dict[str, int] = field(default_factory=dict)
    statuses: list[str] = field(default_factory=list)
    transports: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.statuses) and all(status == "ok" for status in self.statuses)

    @property
    def live_calls(self) -> int:
        """Calls that actually reached the vendor.

        The client reports ``cache`` as the transport when it served an answer from disk,
        and a cached answer costs nothing. Counting it would inflate the spend report,
        which is the one number a budget is checked against.
        """
        return sum(1 for transport in self.transports if transport != "cache")


def build_wide_request(
    prompt: str, roster: Mapping[str, str], questions: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The wide pass: rank the whole roster and ask the three orientation questions."""
    wide = questions["wide"]
    state = {"prompt": prompt, "commands": dict(roster)}
    criteria = dict(roster)
    criteria[NO_SUGGESTION] = "No command fits; the operator is not asking for lifecycle work."
    asked: dict[str, Any] = {
        "rank": {
            "type": "choice",
            "instructions": wide["rank"]["instructions"],
            "criteria": criteria,
        }
    }
    for key in ("needs_command", "is_substantial", "is_unambiguous"):
        asked[key] = {"type": "noul", "instructions": wide[key]["instructions"]}
    return state, asked


def build_verify_request(
    prompt: str,
    candidates: Sequence[str],
    roster: Mapping[str, str],
    questions: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The verification pass: one yes-or-no per shortlisted candidate."""
    template = questions["verify"]["instructions_template"]
    state = {
        "prompt": prompt,
        "candidates": {name: roster.get(name, name) for name in candidates},
    }
    asked = {
        name: {"type": "noul", "instructions": template.format(key=name)} for name in candidates
    }
    return state, asked


def read_wide(answers: Mapping[str, Any], client: Any) -> tuple[list[str], float]:
    """The shortlist and the gate score, from the wide pass's answers.

    The shortlist holds at most ONE entry -- the choice primitive's winner. See
    ``SHORTLIST_SIZE`` for why that is a deviation from the cookbook and what it does and
    does not affect.
    """
    chosen = client.answer_value(answers.get("rank", {}))
    gates = []
    for key in ("needs_command", "is_substantial", "is_unambiguous"):
        value = client.answer_value(answers.get(key, {}))
        if isinstance(value, (int, float)):
            gates.append(float(value))
    gate = sum(gates) / len(gates) if gates else 0.0
    shortlist = [str(chosen)] if isinstance(chosen, str) and chosen != NO_SUGGESTION else []
    return shortlist, gate


def suggest(
    prompt: str,
    roster: Mapping[str, str],
    questions: Mapping[str, Any],
    ask: Callable[..., Any],
    client: Any,
    *,
    deep_check: bool = True,
) -> Suggestion:
    """Run the cookbook pattern against one prompt.

    ``ask`` and ``client`` are injected so a test can drive this with a fake and reach no
    network. Code owns the control flow throughout: the model returns probabilities and
    this function compares them to thresholds, exactly as the house rules require.
    """
    thresholds = questions["thresholds"]
    result = Suggestion()

    state, asked = build_wide_request(prompt, roster, questions)
    wide = ask(state, asked)
    result.calls += 1
    result.statuses.append(wide.status)
    result.transports.append(getattr(wide, "transport", ""))
    _accumulate_usage(result.usage, wide.usage)
    if not wide.ok:
        return result

    shortlist, gate = read_wide(wide.answers, client)
    result.gate = gate
    if gate < float(thresholds["gate"]) or not shortlist:
        return result

    if not deep_check:
        result.command = shortlist[0]
        return result

    candidates = shortlist[:SHORTLIST_SIZE]
    state, asked = build_verify_request(prompt, candidates, roster, questions)
    verify = ask(state, asked)
    result.calls += 1
    result.statuses.append(verify.status)
    result.transports.append(getattr(verify, "transport", ""))
    _accumulate_usage(result.usage, verify.usage)
    if not verify.ok:
        return result

    best, fits = _best_candidate(verify.answers, candidates, client)
    result.fits = fits
    if best is not None and fits >= float(thresholds["fits"]):
        result.command = best
    return result


def _best_candidate(
    answers: Mapping[str, Any], candidates: Sequence[str], client: Any
) -> tuple[str | None, float]:
    best: str | None = None
    best_score = 0.0
    for name in candidates:
        value = client.answer_value(answers.get(name, {}))
        score = float(value) if isinstance(value, (int, float)) else 0.0
        if score > best_score:
            best, best_score = name, score
    return best, best_score


def _merged_usage(*sources: Mapping[str, Any]) -> dict[str, int]:
    """Token totals across every source that spent them."""
    total: dict[str, int] = {}
    for source in sources:
        _accumulate_usage(total, source)
    return total


def _accumulate_usage(total: dict[str, int], usage: Mapping[str, Any]) -> None:
    for key, value in (usage or {}).items():
        if isinstance(value, int):
            total[key] = total.get(key, 0) + value


def scores(prompts: Sequence[Prompt], suggested: Mapping[str, str]) -> dict[str, Any]:
    """Accuracy against the plan's two pre-committed bars.

    Positive entries are scored on naming the expected command; negative entries on
    staying quiet. They are reported separately because a single blended number hides
    exactly the failure that matters -- a suggester that fires on everything.
    """
    positive_total = positive_hit = negative_total = negative_hit = 0
    misses = []
    for prompt in prompts:
        got = suggested.get(prompt.id, NO_SUGGESTION)
        if prompt.wants_command:
            positive_total += 1
            if got == prompt.expected:
                positive_hit += 1
            else:
                misses.append({"id": prompt.id, "expected": prompt.expected, "got": got})
        else:
            negative_total += 1
            if got == NO_SUGGESTION:
                negative_hit += 1
            else:
                misses.append({"id": prompt.id, "expected": NO_SUGGESTION, "got": got})
    return {
        "positive": {
            "hit": positive_hit,
            "total": positive_total,
            "rate": round(positive_hit / positive_total, 3) if positive_total else None,
            "bar": 0.70,
        },
        "negative": {
            "hit": negative_hit,
            "total": negative_total,
            "rate": round(negative_hit / negative_total, 3) if negative_total else None,
            "bar": 0.80,
        },
        "misses": misses,
    }


# --------------------------------------------------------------------------- #
# Timing -- what Claude Code actually pays
# --------------------------------------------------------------------------- #


@dataclass
class Trial:
    """One timed hook invocation."""

    shape: str
    elapsed_ms: float
    ok: bool
    payload: dict[str, Any] = field(default_factory=dict)
    note: str = ""


def time_process(argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> tuple[float, str]:
    """Wall clock around a spawn, its full output read, and its exit.

    This is the figure Claude Code pays, which is why it is measured out here rather than
    inside the child: an in-process number omits interpreter start, which for a cold hook
    is most of the cost.
    """
    started = time.perf_counter()
    completed = subprocess.run(  # noqa: S603 - argv is built here, never from input
        list(argv),
        capture_output=True,
        text=True,
        env=dict(env) if env is not None else None,
        check=False,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return elapsed_ms, completed.stdout


def classify_trial(shape: str, payload: Mapping[str, Any]) -> tuple[bool, str]:
    """Did this trial produce a real answer, and if not, why not?

    Extracted and tested on its own because getting it wrong is not a visible failure: a
    trial that produced no answer and a trial that answered "no command fits" are the same
    bytes, and scoring the first as the second enters a deadline into the latency figures
    and a timeout into the accuracy figures. That mistake already happened once here.
    """
    if shape == "floor":
        return True, ""
    if not payload:
        note = (
            "no answer within the client deadline"
            if shape in WARM_SHAPES
            else "the hook produced no answer"
        )
        return False, note
    if payload.get("error"):
        return False, f"the resident process raised {payload['error']}"
    statuses = payload.get("statuses") or []
    if not statuses:
        return False, "the answer carried no request status"
    if not all(status == "ok" for status in statuses):
        return False, "|".join(sorted(set(statuses)))
    return True, ""


def rotation_order(shape_names: Sequence[str], trials: int) -> list[str]:
    """One trial of each shape in rotation, ``trials`` times over.

    Interleaved rather than blocked (plan R7): this machine is shared, and a load spike
    during a per-shape block would land entirely on one shape and be indistinguishable
    from that shape being slow.
    """
    order = []
    for _ in range(trials):
        order.extend(shape_names)
    return order


def run_interleaved(
    shape_names: Sequence[str],
    trials: int,
    run_one: Callable[[str, int], Trial],
) -> dict[str, list[Trial]]:
    """Run every shape in rotation, recording a raising shape rather than aborting."""
    results: dict[str, list[Trial]] = {name: [] for name in shape_names}
    counters = dict.fromkeys(shape_names, 0)
    for shape in rotation_order(shape_names, trials):
        index = counters[shape]
        counters[shape] = index + 1
        try:
            trial = run_one(shape, index)
        except Exception as exc:  # noqa: BLE001 - a failed trial is data, not an abort
            trial = Trial(shape=shape, elapsed_ms=0.0, ok=False, note=f"{type(exc).__name__}")
        results[shape].append(trial)
    return results


def share_within(values: Sequence[float], budget_ms: float) -> float | None:
    """The fraction of trials that finished inside ``budget_ms``.

    This is what a latency target means operationally. A hook that beats 400 milliseconds
    half the time is not a hook that meets a 400-millisecond target, and the percentile
    alone does not say which side of the line the rest of the distribution sits on.
    """
    if not values:
        return None
    return round(sum(1 for value in values if value <= budget_ms) / len(values), 3)


def collect(
    results: Mapping[str, Sequence[Trial]], budgets_ms: Sequence[float] = (400.0, 500.0)
) -> dict[str, Any]:
    """Per-shape statistics over the successful trials, with failures counted apart.

    A trial whose request did not return ``ok`` is excluded from the latency figures and
    counted separately, so a slow retry is never averaged into the tail as though it were
    the shape's ordinary cost.
    """
    summary: dict[str, Any] = {}
    for shape, trials in results.items():
        good = [trial.elapsed_ms for trial in trials if trial.ok]
        stats = summarize(good)
        stats["failed"] = sum(1 for trial in trials if not trial.ok)
        stats["notes"] = sorted({trial.note for trial in trials if trial.note})
        stats["within"] = {f"{int(budget)}ms": share_within(good, budget) for budget in budgets_ms}
        summary[shape] = stats
    return summary


# --------------------------------------------------------------------------- #
# The thin client -- what the hook itself would be
# --------------------------------------------------------------------------- #


def client_request(
    socket_path: str, payload: Mapping[str, Any], deadline: float = CLIENT_DEADLINE_SECONDS
) -> dict[str, Any] | None:
    """Ask the resident process, failing open silently on any trouble.

    Returns ``None`` rather than raising for every failure mode -- no process listening, a
    process that accepts and never answers, a malformed reply. A hook that fires on every
    prompt must never block the prompt and must never complain, so silence is the whole
    contract (plan KTD6).
    """
    try:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(deadline)
        with connection:
            connection.connect(socket_path)
            connection.sendall(json.dumps(payload).encode("utf-8") + b"\n")
            chunks = []
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if chunks[-1].endswith(b"\n"):
                    break
        body = b"".join(chunks).decode("utf-8").strip()
        return json.loads(body) if body else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #


def _load_client() -> Any:
    """Load the shipped fleet-core client from the catalog's fleet-core package.

    The old discovery shim is not part of this package. The client module loads
    its siblings from the directory that holds it, which is where fleet-core
    keeps them.
    """
    scripts = REPO_ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import typesafe_client

    return typesafe_client


def cmd_hook(args: argparse.Namespace) -> int:
    """One hook invocation: the thing whose cost is being measured.

    ``floor`` does nothing at all, which is the point of it. The cold shapes build the
    client here, in this process, so the measured cost includes the import. The warm
    shapes only talk to the resident process over its socket.
    """
    if args.shape == "floor":
        return 0

    if args.shape in WARM_SHAPES:
        answer = client_request(
            args.socket,
            {"shape": args.shape, "prompt": args.prompt},
            deadline=args.deadline,
        )
        if answer is not None:
            print(json.dumps(answer))
        return 0

    client = _load_client()
    roster = load_roster(Path(args.commands_dir))
    questions = load_questions()

    def ask(state: Any, asked: Mapping[str, Any]) -> Any:
        return client.ask(state, asked, transport=args.transport or None)

    result = suggest(args.prompt, roster, questions, ask, client, deep_check=(args.shape == "s1"))
    # `statuses` must travel with the answer. Without it the caller cannot tell a request
    # that failed from one that succeeded and had nothing to suggest -- both arrive as an
    # answer of `none` -- so a failed cold trial would be recorded as a fast silent
    # success, which is the same class of mistake the warm timeout produced.
    print(
        json.dumps(
            {
                "command": result.command,
                "calls": result.calls,
                "live_calls": result.live_calls,
                "usage": result.usage,
                "statuses": result.statuses,
            }
        )
    )
    return 0


def make_socket_dir() -> Path:
    """A short, owner-only directory to hold the socket.

    `mkdtemp` creates at mode 0700 already; the mode is set again rather than assumed,
    because the guarantee this directory carries is the only thing standing between a
    resident credential and any other account on the machine.
    """
    directory = Path(tempfile.mkdtemp(prefix="psl-"))
    os.chmod(directory, SOCKET_DIR_MODE)
    return directory


def check_socket_path(path: Path) -> None:
    """Refuse a socket path the platform cannot bind, with a message that explains it."""
    encoded = len(str(path).encode("utf-8"))
    if encoded > SUN_PATH_MAX:
        raise HarnessError(
            f"the socket path is {encoded} bytes, over the {SUN_PATH_MAX}-byte limit a "
            f"Unix domain socket allows: {path}. Put the socket in a short directory "
            f"(see make_socket_dir) rather than beside the results."
        )


@dataclass
class DaemonHandle:
    """The resident process this harness started, and therefore owns."""

    process: subprocess.Popen[str]
    pid: int
    socket_path: Path


def start_daemon(
    socket_path: Path, cache_dir: Path, commands_dir: Path, transport: str = ""
) -> DaemonHandle:
    """Start the resident process and wait for it to say it is listening."""
    check_socket_path(socket_path)
    argv = [
        sys.executable,
        str(Path(__file__).resolve().parent / "prompt_suggestion_daemon.py"),
        "--socket",
        str(socket_path),
        "--cache-dir",
        str(cache_dir),
        "--commands-dir",
        str(commands_dir),
    ]
    if transport:
        argv += ["--transport", transport]
    process = subprocess.Popen(  # noqa: S603 - argv is built here
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    assert process.stdout is not None
    # A blocking readline cannot be interrupted by the deadline below, so a process that
    # starts and then says nothing would hang this call forever rather than time out.
    # Waiting on the file descriptor instead keeps the deadline real.
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr else ""
            raise HarnessError(f"the resident process exited before listening: {stderr.strip()}")
        ready, _, _ = select.select([process.stdout], [], [], 0.25)
        if not ready:
            continue
        line = process.stdout.readline()
        if not line:
            continue
        if line.startswith(READY_PREFIX):
            return DaemonHandle(process=process, pid=process.pid, socket_path=socket_path)
    process.terminate()
    process.wait(timeout=10)
    raise HarnessError("the resident process did not report listening within 30 seconds")


def stop_daemon(handle: DaemonHandle) -> None:
    """Stop the process this harness started. Never touches any other process."""
    if handle.process.poll() is None:
        handle.process.terminate()
        try:
            handle.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            handle.process.kill()
            handle.process.wait(timeout=10)
    handle.socket_path.unlink(missing_ok=True)


def survival_probe(socket_path: Path, prompt: str, invocations: int = 30) -> dict[str, Any]:
    """Do separate hook processes all reach the same resident instance?

    Uses the cache-served shape so the probe spends no API calls. Distinct process
    identifiers across the run would mean the process did not survive, which is reported
    as a failure rather than quietly passing.
    """
    pids: set[int] = set()
    uptimes: list[float] = []
    answered = 0
    for _ in range(invocations):
        answer = client_request(str(socket_path), {"shape": "s4", "prompt": prompt})
        if not answer:
            continue
        answered += 1
        if isinstance(answer.get("pid"), int):
            pids.add(int(answer["pid"]))
        if isinstance(answer.get("uptime_s"), (int, float)):
            uptimes.append(float(answer["uptime_s"]))
    survived = answered == invocations and len(pids) == 1
    return {
        "invocations": invocations,
        "answered": answered,
        "distinct_pids": sorted(pids),
        "survived": survived,
        "uptime_grew": bool(len(uptimes) > 1 and uptimes[-1] > uptimes[0]),
        "first_uptime_s": uptimes[0] if uptimes else None,
        "last_uptime_s": uptimes[-1] if uptimes else None,
    }


def resolution_probe(tree_roots: Sequence[Path]) -> list[dict[str, Any]]:
    """Which rung of the fleet-core resolution ladder wins in each installed tree?

    Read-only: it imports each tree's own copy of the shim with the shim's own debug flag
    set and records what the shim itself reports. Nothing in either tree is modified. An
    absent debug line is recorded as unknown rather than guessed at.
    """
    observed = []
    for root in tree_roots:
        entry: dict[str, Any] = {"tree": str(root), "rung": "unknown", "root": ""}
        versions = sorted(
            (path for path in (Path(root) / "fleet-core").glob("*") if path.is_dir()),
            key=lambda path: [int(part) for part in path.name.split(".") if part.isdigit()],
        )
        if not versions:
            entry["rung"] = "no fleet-core installed in this tree"
            observed.append(entry)
            continue
        scripts = versions[-1] / "scripts"
        entry["version"] = versions[-1].name
        env = dict(os.environ)
        env["FLEET_COMMONS_DEBUG"] = "1"
        env.pop("FLEET_COMMONS_ROOT", None)
        code = (
            f"import sys; sys.path.insert(0, {str(scripts)!r}); "
            "import fleet_commons_shim; fleet_commons_shim.load('typesafe_client')"
        )
        completed = subprocess.run(  # noqa: S603 - argv is built here
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(Path(root)),
            check=False,
        )
        for line in completed.stderr.splitlines():
            if line.startswith("fleet-commons: rung="):
                entry["rung"] = line.split("fleet-commons: ", 1)[1].strip()
                break
        observed.append(entry)
    return observed


def cmd_measure(args: argparse.Namespace) -> int:
    """Run every shape interleaved, then the two probes, and write the results."""
    corpus = load_corpus()
    load_questions()  # fail fast here rather than inside the first spawned hook
    commands_dir = Path(args.commands_dir)
    roster = load_roster(commands_dir)

    scratch = Path(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    cache_dir = scratch / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    socket_dir = make_socket_dir()
    socket_path = socket_dir / "s.sock"

    hook_argv_base = [sys.executable, str(Path(__file__).resolve())]
    suggestions: dict[str, dict[str, str]] = {name: {} for name in SHAPE_NAMES}
    calls = {"count": 0}
    usage_total: dict[str, int] = {}

    def run_one(shape: str, index: int) -> Trial:
        prompt = corpus[index % len(corpus)]
        argv = hook_argv_base + [
            "hook",
            "--shape",
            shape,
            "--prompt",
            prompt.text,
            "--socket",
            str(socket_path),
            "--commands-dir",
            str(commands_dir),
        ]
        if shape in COLD_SHAPES and args.transport:
            argv += ["--transport", args.transport]
        if shape in WARM_SHAPES:
            argv += ["--deadline", str(args.client_deadline)]
        elapsed_ms, stdout = time_process(argv)
        payload: dict[str, Any] = {}
        if stdout.strip():
            try:
                payload = json.loads(stdout.strip().splitlines()[-1])
            except json.JSONDecodeError:
                payload = {}
        ok, note = classify_trial(shape, payload)
        if shape != "floor":
            # Only the cold shapes are tallied here; the resident process reports its own
            # spend, which includes the primed and backgrounded calls no hook ever sees.
            if shape in COLD_SHAPES:
                calls["count"] += int(payload.get("calls") or 0)
                _accumulate_usage(usage_total, payload.get("usage") or {})
            if ok:
                suggestions[shape][prompt.id] = str(payload.get("command") or NO_SUGGESTION)
        return Trial(shape=shape, elapsed_ms=elapsed_ms, ok=ok, payload=payload, note=note)

    handle = start_daemon(socket_path, cache_dir, commands_dir, args.transport)
    started_pid = handle.pid
    try:
        # Prime the two shapes whose first request is definitionally different: the cache
        # has nothing to serve until something populates it, and the stale shape has no
        # previous answer to give. Priming is not measured.
        for prompt in corpus:
            client_request(str(socket_path), {"shape": "s4", "prompt": prompt.text})
        client_request(str(socket_path), {"shape": "s5", "prompt": corpus[0].text})
        time.sleep(2.0)

        chosen_shapes = (
            tuple(name.strip() for name in args.shapes.split(",") if name.strip()) or SHAPE_NAMES
        )
        unknown = set(chosen_shapes) - set(SHAPE_NAMES)
        if unknown:
            raise HarnessError(f"unknown shape(s): {', '.join(sorted(unknown))}")
        results = run_interleaved(chosen_shapes, args.trials, run_one)
        free = tuple(name for name in ("floor", "s4") if name in chosen_shapes)
        if free:
            extra = run_interleaved(free, args.free_trials, run_one)
            for shape in free:
                results[shape].extend(extra[shape])

        survival = survival_probe(socket_path, corpus[0].text)
        daemon_stats = client_request(str(socket_path), {"shape": "stats", "prompt": ""}) or {}
    finally:
        stop_daemon(handle)
        if not any(socket_dir.iterdir()):
            socket_dir.rmdir()

    trees = [
        Path.home() / ".claude" / "plugins" / "cache" / "infiquetra-plugins",
        Path.home() / ".claude-company" / "plugins" / "cache" / "infiquetra-plugins",
    ]
    report = {
        "schema": "prompt_suggestion_results.v1",
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "roster_size": len(roster),
        "corpus_size": len(corpus),
        "trials": args.trials,
        "free_trials": args.free_trials,
        "transport": args.transport or "client default",
        "shapes": list(chosen_shapes),
        "measurement_deadline_s": args.client_deadline,
        "operator_deadline_s": CLIENT_DEADLINE_SECONDS,
        "latency": collect(results),
        # Scored over the prompts each shape actually saw. A run with fewer trials than
        # the corpus holds leaves later prompts unattempted, and counting those as silence
        # would report a suggester that was never asked as one that correctly stayed quiet.
        "accuracy": {
            shape: scores(
                [prompt for prompt in corpus if prompt.id in suggestions[shape]],
                suggestions[shape],
            )
            for shape in chosen_shapes
            if shape != "floor"
        },
        "live_calls": calls["count"] + int(daemon_stats.get("calls") or 0),
        "live_calls_cold": calls["count"],
        "live_calls_resident": int(daemon_stats.get("calls") or 0),
        "usage": _merged_usage(usage_total, daemon_stats.get("usage") or {}),
        "survival": survival,
        "resolution": resolution_probe(trees),
        "daemon_pid": started_pid,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["latency"], indent=2, sort_keys=True))
    print(
        f"live API calls: {report['live_calls']} "
        f"(cold {report['live_calls_cold']}, resident {report['live_calls_resident']})  "
        f"usage: {report['usage']}",
        file=sys.stderr,
    )
    print(f"resident process {started_pid} stopped; results at {out}", file=sys.stderr)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    hook = sub.add_parser("hook", help="one hook invocation (the timed unit)")
    hook.add_argument("--shape", required=True, choices=SHAPE_NAMES)
    hook.add_argument("--prompt", default="")
    hook.add_argument("--socket", default="")
    hook.add_argument("--transport", default="")
    hook.add_argument("--deadline", type=float, default=CLIENT_DEADLINE_SECONDS)
    hook.add_argument("--commands-dir", default=str(SAGA_COMMANDS))
    hook.set_defaults(func=cmd_hook)

    measure = sub.add_parser("measure", help="run every shape interleaved and write results")
    measure.add_argument("--trials", type=int, default=20)
    measure.add_argument(
        "--free-trials",
        type=int,
        default=30,
        help="extra trials for the shapes that spend no API call",
    )
    measure.add_argument("--transport", default="")
    measure.add_argument(
        "--client-deadline",
        type=float,
        default=MEASUREMENT_DEADLINE_SECONDS,
        help=(
            "how long a timed hook waits for the resident process. Deliberately generous: "
            "a deadline shorter than a shape's service time measures the deadline, not the shape"
        ),
    )
    measure.add_argument(
        "--shapes",
        default="",
        help="comma-separated subset of shapes to run; all of them when omitted",
    )
    measure.add_argument("--out", required=True)
    measure.add_argument("--scratch", required=True)
    measure.add_argument("--commands-dir", default=str(SAGA_COMMANDS))
    measure.set_defaults(func=cmd_measure)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except HarnessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
