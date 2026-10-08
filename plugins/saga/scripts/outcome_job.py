"""The review-outcome job: link later defects to the reviews that passed them.

Runs daily from launchd. Lists review runs from Langfuse traces, links closed defect
issues and reverts to the runs that passed their lines, posts the misses, queues the
defects where the corpus screening reads, files fix-later boxes ticked after review,
and posts each completed run's addressed rate.

The job never runs from a repository under review: it changes to its state directory
first and reaches every checkout through explicit paths. Keys come only from the
process environment, and the Mac's stored GitHub sign-in authenticates `gh`.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import plistlib
import re
import shutil
import subprocess  # nosec B404 - runners only, fixed argument vectors
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# No sibling imports at module scope: --help answers with the standard library alone.
# run_record, review_trace and review_state load lazily inside the verbs that need them.

Runner = Callable[..., Any]

STATE_SCHEMA = "outcome_job_state.v1"
REPOS_SCHEMA = "outcome_job_repos.v1"
QUEUE_SOURCES = ("/qa", "defect issue", "revert")

#: Every listing window reaches this far back past the last pass, so Langfuse read lag and
#: ordering skew cannot strand a defect. Processed sets dedupe the overlap.
OVERLAP = timedelta(hours=24)

FETCH_TIMEOUT = 180
GIT_TIMEOUT = 60
GH_TIMEOUT = 60
TRACE_PAGE_SIZE = 50
SCORE_PAGE_SIZE = 50

SUBJECT_PR_RE = re.compile(r"\(#(\d+)\)")
REVERT_RE = re.compile(r"^revert", re.IGNORECASE)
TICKED_RE = re.compile(r"^-\s+\[[xX]\]\s+(rf:[0-9a-f]+)\b")
LINKED_RE = re.compile(r"→\s*#(\d+)\s*$")
REVISION_RE = re.compile(r"\*\*Reviewed revision\.\*\* `([0-9a-f]{40})`")

SCHEDULE_LABEL = "com.infiquetra.saga.outcome-job"
SCHEDULE_HOUR = 6
SCHEDULE_MINUTE = 17

#: The plist's fixed shell body. Paths arrive as positional parameters, never interpolated
#: into shell text: `$1` the keychain helper, `$2` the interpreter, `$3` this script,
#: `$4` the home. `emit` prints shell exports; the job runs with whatever it provides, so
#: a keyless machine fails loudly in the job's own summary rather than silently here.
SCHEDULE_BODY = 'eval "$("$1" emit --quiet)"; exec "$2" "$3" run --home "$4"'


class OutcomeJobError(Exception):
    """A refusal this module owns. The command line maps it to exit 2."""


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------


def production_runner(
    argv: Sequence[str], *, cwd: Path | None = None, env: Mapping[str, str] | None = None,
    timeout: int = GH_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """One subprocess, shell false. Every seam in this module matches this shape."""
    return subprocess.run(  # nosec B603 - argument vector, shell false
        [str(part) for part in argv],
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def scrub_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """The C15 shape: no `GIT_*`, Langfuse or TypeSafe variable reaches the child."""
    source = env if env is not None else os.environ
    return {
        key: value
        for key, value in source.items()
        if not (
            key.startswith("GIT_")
            or key.startswith("SAGA_LANGFUSE_")
            or key.startswith("LANGFUSE_")
            or key.startswith("TYPESAFE_")
        )
    }


def _git(
    runner: Runner | None, checkout: Path, *args: str, timeout: int = GIT_TIMEOUT,
) -> Any:
    """`git` in *checkout* with hooks disabled. The branch under review cannot hook us."""
    call = runner if runner is not None else production_runner
    return call(
        ["git", "-C", str(checkout), "-c", "core.hooksPath=/dev/null", *args],
        cwd=None,
        env=scrub_env(),
        timeout=timeout,
    )


def _gh(
    runner: Runner | None, *args: str, cwd: Path | None = None, timeout: int = GH_TIMEOUT,
) -> Any:
    """`gh` with the scrubbed environment, on the Mac's stored sign-in."""
    call = runner if runner is not None else production_runner
    return call(["gh", *args], cwd=cwd, env=scrub_env(), timeout=timeout)


def _ok(result: Any) -> bool:
    return getattr(result, "returncode", 1) == 0


def _out(result: Any) -> str:
    return str(getattr(result, "stdout", "") or "").strip()


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def state_dir(home: Path) -> Path:
    """`<home>/.saga/outcome-job`, created owner-only."""
    path = Path(home) / ".saga" / "outcome-job"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def default_queue_path() -> Path:
    """Where K1's screening reads queued candidates (KTD13). Tests override with `--queue`."""
    return Path.home() / ".local" / "share" / "saga-review-corpus" / "queued-candidates.jsonl"


def _write_0600_atomic(path: Path, content: str) -> None:
    """Write *content* atomically, owner-only. The reader never sees a torn file."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        data = content.encode("utf-8")
        while data:
            written = os.write(fd, data)
            data = data[written:]
    finally:
        os.close(fd)


def _read_json(path: Path, schema: str, kind: str) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise OutcomeJobError(f"the job {kind} at {path} is unreadable: {exc}") from exc
    if not isinstance(raw, dict):
        raise OutcomeJobError(f"the job {kind} at {path} does not hold an object")
    if raw.get("schema") not in (None, schema):
        raise OutcomeJobError(f"the job {kind} at {path} has schema {raw.get('schema')!r}")
    return raw


def default_state() -> dict[str, Any]:
    """The empty pass state. Sets are sorted lists on disk; the run keeps them as sets."""
    return {
        "schema": STATE_SCHEMA,
        "last_pass": None,
        "index": {},
        "processed_defects": [],
        "processed_reverts": [],
        "queued_qa": [],
        "pending_qa": [],
        "claimed": {},
        "filed": {},
        "addressed_posted": [],
        "failures": {},
    }


def load_state(directory: Path) -> dict[str, Any]:
    """The pass state with set-valued keys as sets. Missing file reads as empty."""
    raw = _read_json(Path(directory) / "state.json", STATE_SCHEMA, "state")
    if not raw:
        raw = default_state()
    state = {**default_state(), **raw}
    for key in ("processed_defects", "processed_reverts", "queued_qa", "addressed_posted"):
        state[key] = set(state.get(key) or [])
    if not isinstance(state.get("index"), dict):
        state["index"] = {}
    if not isinstance(state.get("pending_qa"), list):
        state["pending_qa"] = []
    if not isinstance(state.get("claimed"), dict):
        state["claimed"] = {}
    if not isinstance(state.get("filed"), dict):
        state["filed"] = {}
    if not isinstance(state.get("failures"), dict):
        state["failures"] = {}
    return state


def save_state(directory: Path, state: Mapping[str, Any]) -> Path:
    """Persist the full in-memory state atomically, owner-only. Call after each side effect."""
    path = Path(directory) / "state.json"
    payload = dict(state)
    for key in ("processed_defects", "processed_reverts", "queued_qa", "addressed_posted"):
        payload[key] = sorted(payload.get(key) or [])
    _write_0600_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def load_repos(directory: Path) -> dict[str, dict[str, str]]:
    """The checkout map: slug to `checkout` and `added`. Missing file reads as empty."""
    raw = _read_json(Path(directory) / "repos.json", REPOS_SCHEMA, "checkout map")
    repos = raw.get("repos") if raw else {}
    if not isinstance(repos, dict):
        return {}
    return {
        str(slug): {"checkout": str(entry.get("checkout") or ""),
                    "added": str(entry.get("added") or "")}
        for slug, entry in repos.items()
        if isinstance(entry, Mapping)
    }


def save_repos(directory: Path, repos: Mapping[str, Mapping[str, str]]) -> Path:
    """Persist the checkout map atomically, owner-only."""
    path = Path(directory) / "repos.json"
    payload = {"schema": REPOS_SCHEMA,
               "repos": {slug: dict(entry) for slug, entry in repos.items()}}
    _write_0600_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _now_zulu() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_zulu(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


# ---------------------------------------------------------------------------
# Tracing a fix to the pull request that introduced its lines
# ---------------------------------------------------------------------------


def parse_diff_lines(diff: str) -> tuple[list[int], bool]:
    """Parent-side removed lines and whether the diff adds lines.

    The hunk walk mirrors K1's removed-line path: `deleted` blames directly, `added` marks
    a purely additive file this card leaves to corpus screening. Binary and empty diffs yield
    neither, and are skipped by the caller as K1 skips them per file.
    """
    deleted: list[int] = []
    added = False
    parent_line = 0
    for line in diff.splitlines():
        if line.startswith("@@"):
            match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+\d+", line)
            if not match:
                continue
            parent_line = int(match.group(1))
            continue
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-"):
            deleted.append(parent_line)
            parent_line += 1
        elif line.startswith("+"):
            added = True
        elif line.startswith(" "):
            parent_line += 1
    return deleted, added


def blame_lines(
    git_runner: Runner | None, checkout: Path, parent: str, path: str,
    lines: Sequence[int],
) -> tuple[dict[int, str], bool]:
    """Map parent-side line numbers to their introducing commits, K1's rule.

    Returns (blamed, process_failed): lines git refused are skipped like K1 skips them, but
    when every call fails at the process level the checkout itself is broken, which the
    caller must treat as infrastructure, not as an unblameable fix.
    """
    blamed: dict[int, str] = {}
    process_failed = False
    for number in lines:
        result = _git(git_runner, checkout, "blame", "--porcelain", "-L",
                      f"{number},{number}", parent, "--", path)
        if not _ok(result):
            process_failed = True
            continue
        first = _out(result).splitlines()[0] if _out(result) else ""
        sha = first.split(" ", 1)[0]
        if len(sha) == 40 and all(char in "0123456789abcdef" for char in sha):
            blamed[number] = sha
    return blamed, process_failed


def pr_from_subject(subject: str) -> int | None:
    """The `(#N)` suffix of a squash-merge subject, else None. Mirrors K1."""
    match = SUBJECT_PR_RE.search(subject or "")
    return int(match.group(1)) if match else None


def own_pr_from_subject(subject: str) -> int | None:
    """The pull request a squash subject carries for itself: the trailing `(#N)`, else None.

    A revert subject's first group names the reverted pull request, not its own, so the own
    check reads only the trailing group GitHub appends at squash time.
    """
    match = re.search(r"\(#(\d+)\)$", (subject or "").strip())
    return int(match.group(1)) if match else None


def pr_for_commit(
    git_runner: Runner | None, gh_runner: Runner | None, checkout: Path, sha: str,
) -> tuple[int | None, str | None]:
    """The merged pull request holding *sha*: (number, None), or (None, reason).

    Subject first, then the `gh` search, mirroring K1. A failed search is
    `pr-lookup-failed` (infrastructure: GitHub may be down), distinct from `pr-unknown`
    (the search ran and found nothing, e.g. a direct push with no review to link).
    """
    subject = _git(git_runner, checkout, "log", "-1", "--format=%s", sha)
    found = pr_from_subject(_out(subject)) if _ok(subject) else None
    if found is not None:
        return found, None
    result = _gh(gh_runner, "pr", "list", "--search", sha, "--state", "merged",
                 "--json", "number", "--jq", ".[0].number", cwd=checkout)
    if not _ok(result):
        return None, "pr-lookup-failed"
    text = _out(result)
    if not text.isdigit():
        return None, "pr-unknown"
    return int(text), None


def _is_merge(git_runner: Runner | None, checkout: Path, sha: str) -> bool:
    return _ok(_git(git_runner, checkout, "rev-parse", "--verify", f"{sha}^2"))


def _commit_subject(git_runner: Runner | None, checkout: Path, sha: str) -> str:
    result = _git(git_runner, checkout, "log", "-1", "--format=%s", sha)
    return _out(result) if _ok(result) else ""


def _rev_parse(git_runner: Runner | None, checkout: Path, revision: str) -> str | None:
    result = _git(git_runner, checkout, "rev-parse", "--verify", revision)
    return _out(result) if _ok(result) and _out(result) else None


def _cat_exists(git_runner: Runner | None, checkout: Path, sha: str) -> bool:
    return _ok(_git(git_runner, checkout, "cat-file", "-e", sha))


def trace_single(
    git_runner: Runner | None, gh_runner: Runner | None, checkout: Path, fix: str,
) -> tuple[dict[int, list[str]] | None, str | None]:
    """Blame one non-merge commit's removed lines: ({pr: [shas]}, None) or (None, reason).

    Reasons speak K1's edge-case vocabulary: `no-parent`, `nothing-to-trace`, `trace-error`,
    `pr-unknown` and `add-only` (purely additive, this card's scope cut).
    """
    parent = _rev_parse(git_runner, checkout, f"{fix}^")
    if parent is None:
        if not _cat_exists(git_runner, checkout, fix):
            return None, "fix-not-local"
        return None, "no-parent"
    changed = _git(git_runner, checkout, "show", "--format=", "--name-only", fix)
    if not _ok(changed):
        return None, "trace-error: cannot read the fix"
    per_file: dict[str, list[int]] = {}
    any_added = False
    for path in [line for line in _out(changed).splitlines() if line]:
        text = _git(git_runner, checkout, "show", "--format=", "-U3", fix, "--", path)
        body = _out(text) if _ok(text) else ""
        if not body or "Binary files " in body:
            continue
        removed, added = parse_diff_lines(body)
        any_added = any_added or added
        if removed:
            per_file[path] = removed
    if not per_file:
        if any_added:
            return None, "add-only"
        return None, "nothing-to-trace"
    blamed: dict[str, list[str]] = {}
    blame_failed = False
    for path, numbers in per_file.items():
        lines, failed = blame_lines(git_runner, checkout, parent, path, numbers)
        blame_failed = blame_failed or failed
        for lineno, sha in lines.items():
            blamed.setdefault(sha, []).append(f"{path}:{lineno}")
    if not blamed:
        if blame_failed:
            return None, "blame-failed"
        return None, "trace-error: blame found no introducing commit"
    by_pr: dict[int, list[str]] = {}
    for sha in blamed:
        number, reason = pr_for_commit(git_runner, gh_runner, checkout, sha)
        if reason is not None:
            return None, reason
        assert number is not None
        by_pr.setdefault(number, []).append(sha)
    return by_pr, None


def trace_fix_commits(
    git_runner: Runner | None, gh_runner: Runner | None, checkout: Path,
    commits: Sequence[str],
) -> tuple[int | None, str | None]:
    """The one introducing pull request every commit agrees on, or (None, reason)."""
    votes: dict[int, int] = {}
    for commit in commits:
        by_pr, reason = trace_single(git_runner, gh_runner, checkout, commit)
        if reason is not None:
            if reason == "nothing-to-trace":
                continue
            return None, reason
        assert by_pr is not None
        if len(by_pr) > 1:
            return None, "spans-pull-requests"
        (number,) = by_pr
        votes[number] = votes.get(number, 0) + 1
    if not votes:
        return None, "nothing-to-trace"
    if len(votes) > 1:
        return None, "spans-pull-requests"
    (number,) = votes
    return number, None


def fix_commits_for_pr(
    git_runner: Runner | None, gh_runner: Runner | None, checkout: Path, repo: str,
    closing_pr: int, merge_sha: str,
) -> tuple[list[str] | None, str | None]:
    """The non-merge commits whose lines the closing pull request brought in.

    A merge commit resolves to its branch range (GitHub always puts the base first, so the
    range runs first parent to second parent). A squash commit is the fix on its own, told by
    its `(#N)` subject. Anything else reads the pull request's commits from `gh` and needs
    every one resolvable locally, or the fix is only partly visible and skips.
    """
    if _is_merge(git_runner, checkout, merge_sha):
        first = _rev_parse(git_runner, checkout, f"{merge_sha}^1")
        second = _rev_parse(git_runner, checkout, f"{merge_sha}^2")
        if first is None or second is None:
            return None, "trace-error: cannot read the merge parents"
        listed = _git(git_runner, checkout, "rev-list", f"{first}..{second}", "--no-merges")
        if not _ok(listed):
            return None, "trace-error: cannot list the merge range"
        commits = [line for line in _out(listed).splitlines() if line]
        if not commits:
            return None, "nothing-to-trace"
        return commits, None
    if own_pr_from_subject(_commit_subject(git_runner, checkout, merge_sha)) == closing_pr:
        return [merge_sha], None
    listed = _gh(gh_runner, "pr", "view", str(closing_pr), "--repo", repo,
                 "--json", "commits", cwd=checkout)
    if not _ok(listed):
        return None, "trace-error: cannot list the pull request commits"
    try:
        oids = [str(entry.get("oid") or "") for entry in
                json.loads(_out(listed) or "{}").get("commits") or []]
    except json.JSONDecodeError:
        return None, "trace-error: cannot parse the pull request commits"
    oids = [oid for oid in oids if oid]
    if not oids:
        return [merge_sha], None
    if not _cat_exists(git_runner, checkout, merge_sha):
        return None, "fix-not-local"
    missing = [oid for oid in oids if not _cat_exists(git_runner, checkout, oid)]
    if missing:
        return None, "fix-partially-visible"
    for oid in oids:
        if _is_merge(git_runner, checkout, oid):
            return None, "nested-merge"
    commits = [merge_sha] + [oid for oid in oids if oid != merge_sha]
    return commits, None


# ---------------------------------------------------------------------------
# The candidate queue
# ---------------------------------------------------------------------------


def validate_queue_record(record: Any) -> str | None:
    """The mirrored read rules: None when K1's screening accepts the line, else the reason.

    Mirrored from the landed reader (closed source set, non-empty string repository,
    integer-or-absent fixing pull request, string-or-absent fixing commit, at least one fix
    present), stricter in two writer-controlled places: the review run is always named, and
    a boolean pull-request number is rejected.
    """
    if not isinstance(record, dict):
        return "record-must-be-an-object"
    if record.get("source") not in QUEUE_SOURCES:
        return "bad-source"
    if not isinstance(record.get("repository"), str) or not record.get("repository"):
        return "bad-repository"
    review_run = record.get("review_run_id")
    if not isinstance(review_run, str) or not review_run:
        return "review-run-unnamed"
    fixing_pr = record.get("fixing_pr")
    fixing_commit = record.get("fixing_commit")
    if isinstance(fixing_pr, bool) or (fixing_pr is not None and not isinstance(fixing_pr, int)):
        return "bad-fixing-pr"
    if fixing_commit is not None and not isinstance(fixing_commit, str):
        return "bad-fixing-commit"
    if fixing_pr is None and fixing_commit is None:
        return "fix-unnamed"
    return None


def canonical_queue_line(record: Mapping[str, Any]) -> str:
    """The one line the queue holds for *record*, in canonical key order."""
    ordered = {
        "source": record.get("source"),
        "repository": record.get("repository"),
        "review_run_id": record.get("review_run_id"),
    }
    if record.get("fixing_pr") is not None:
        ordered["fixing_pr"] = record.get("fixing_pr")
    if record.get("fixing_commit") is not None:
        ordered["fixing_commit"] = record.get("fixing_commit")
    return json.dumps(ordered, separators=(",", ":"), sort_keys=True)


def queue_contains(path: Path, line: str) -> bool:
    """True when the queue already holds *line*. A missing file holds nothing."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return line in {entry for entry in text.splitlines() if entry.strip()}


def append_queue_record(path: Path, record: Mapping[str, Any]) -> str:
    """Validate, check for an identical line, and append. Returns `appended` or `duplicate`.

    Raises `OutcomeJobError` on an invalid record: an invalid line never touches the file,
    because one bad line aborts K1's whole screening read.
    """
    problem = validate_queue_record(record)
    if problem is not None:
        raise OutcomeJobError(f"refusing to queue an invalid candidate: {problem}")
    line = canonical_queue_line(record)
    if queue_contains(path, line):
        return "duplicate"
    target = Path(path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, (line + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    return "appended"


# ---------------------------------------------------------------------------
# GitHub reads
# ---------------------------------------------------------------------------


def _gh_json(gh_runner: Runner | None, *args: str, cwd: Path | None = None) -> Any:
    """Parsed `gh` JSON output, or None when the call or the parse fails."""
    result = _gh(gh_runner, *args, cwd=cwd)
    if not _ok(result):
        return None
    try:
        return json.loads(_out(result) or "null")
    except json.JSONDecodeError:
        return None


def list_closed_defects(
    gh_runner: Runner | None, repo: str, since: datetime | None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Closed `defect` issues updated in the window, newest first: (issues, None) or (None, reason)."""
    issues = _gh_json(
        gh_runner, "issue", "list", "--repo", repo, "--state", "closed",
        "--label", "defect", "--search", "sort:updated-desc", "--limit", "200",
        "--json", "number,updatedAt,closedAt",
    )
    if not isinstance(issues, list):
        return None, "defect-list-failed"
    if len(issues) >= 200:
        oldest = min((str(item.get("updatedAt") or "") for item in issues
                      if isinstance(item, dict)), default="")
        moment = _parse_zulu(oldest) if oldest else None
        if since is None or (moment is not None and moment >= since):
            return None, "defect-list-truncated"
    kept = []
    for item in issues:
        if not isinstance(item, dict):
            continue
        moment = _parse_zulu(str(item.get("updatedAt") or ""))
        if since is not None and (moment is None or moment < since):
            continue
        kept.append(item)
    return kept, None


def closing_pull_requests(
    gh_runner: Runner | None, repo: str, issue: int,
) -> tuple[list[int] | None, str | None]:
    """The pull requests that closed *issue*: (numbers, None) or (None, reason)."""
    refs = _gh_json(gh_runner, "issue", "view", str(issue), "--repo", repo,
                    "--json", "closedByPullRequestsReferences")
    if not isinstance(refs, dict) or not isinstance(
            refs.get("closedByPullRequestsReferences"), list):
        return None, "closing-prs-unreadable"
    return [int(ref.get("number")) for ref in refs["closedByPullRequestsReferences"]
            if isinstance(ref, dict) and isinstance(ref.get("number"), int)], None


def merged_fix_commit(
    gh_runner: Runner | None, repo: str, number: int,
) -> tuple[str | None, str | None]:
    """The merge commit when pull request *number* merged: (sha, None) or (None, reason)."""
    info = _gh_json(gh_runner, "pr", "view", str(number), "--repo", repo,
                    "--json", "state,mergeCommit")
    if not isinstance(info, dict):
        return None, "pr-unreadable"
    if info.get("state") != "MERGED":
        return None, "closing-pr-unmerged"
    merge = info.get("mergeCommit") if isinstance(info.get("mergeCommit"), dict) else {}
    sha = str(merge.get("oid") or "")
    if not sha:
        return None, "fix-unresolved"
    return sha, None


def revert_commits(
    git_runner: Runner | None, checkout: Path, branch: str, since: datetime | None,
) -> tuple[list[tuple[str, str]] | None, str | None]:
    """`[(sha, subject)]` of revert commits on *branch* in the window: else (None, reason)."""
    args = ["log", branch, "--no-merges", "--format=%H %s"]
    if since is not None:
        args.append(f"--since={since.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    result = _git(git_runner, checkout, *args)
    if not _ok(result):
        return None, "revert-log-failed"
    found = []
    for line in _out(result).splitlines():
        sha, _, subject = line.partition(" ")
        if len(sha) == 40 and REVERT_RE.match(subject.strip()):
            found.append((sha, subject.strip()))
    return found, None


def default_branch(git_runner: Runner | None, checkout: Path) -> str | None:
    """The checkout's default branch: `origin/HEAD`, else `main`, else `master`."""
    head = _git(git_runner, checkout, "symbolic-ref", "refs/remotes/origin/HEAD")
    if _ok(head):
        ref = _out(head)
        if ref.startswith("refs/remotes/origin/") and len(ref) > len("refs/remotes/origin/"):
            return ref[len("refs/remotes/origin/"):]
    for name in ("main", "master"):
        if _ok(_git(git_runner, checkout, "rev-parse", "--verify", name)):
            return name
    return None


def marker_comment(
    gh_runner: Runner | None, repo: str, pr: int,
) -> tuple[dict[str, Any] | None, str | None]:
    """The newest final-checklist comment on pull request *pr*: (comment, None) or (None, reason).

    A comment needs C13's marker constant, so the review-state module loads here rather than
    at module scope.
    """
    import review_state  # noqa: PLC0415 - lazy: --help answers without siblings

    comments = _gh_json(gh_runner, "api", f"repos/{repo}/issues/{pr}/comments",
                        "--paginate")
    if not isinstance(comments, list):
        return None, "comments-unreadable"
    marker = review_state.CHECKLIST_MARKER
    matches = [comment for comment in comments
               if isinstance(comment, dict)
               and str(comment.get("body") or "").startswith(marker)]
    if not matches:
        return None, "no-marker-comment"
    return matches[-1], None


def marker_head(comment: Mapping[str, Any]) -> str | None:
    """The `Reviewed revision` the final comment names, else None."""
    match = REVISION_RE.search(str(comment.get("body") or ""))
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Run records behind the checkout map
# ---------------------------------------------------------------------------


def record_head_for_pr(
    checkout: Path, pr: int,
) -> tuple[str | None, str | None, int | None]:
    """The stored reviewed head for pull request *pr*: (head, reason, card).

    Exactly one run record whose release names the pull request gives the head, found through
    the store resolver rather than a hand-built path, so linked worktrees resolve to the
    primary checkout's store.
    """
    import run_record  # noqa: PLC0415 - lazy: --help answers without siblings

    try:
        store = run_record.resolve_store_root(Path(checkout))
    except Exception:  # noqa: BLE001 - any resolution fault reads as unavailable
        return None, "store-unresolvable", None
    matches: list[tuple[int, dict[str, Any]]] = []
    try:
        paths = sorted(Path(store).glob("issue-*.json"))
    except OSError:
        return None, "store-unreadable", None
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        release = raw.get("release")
        if isinstance(release, dict) and release.get("pull_request") == pr:
            card = raw.get("issue")
            matches.append((card if isinstance(card, int) else -1, raw))
    if len(matches) > 1:
        return None, "ambiguous-release", None
    if not matches:
        return None, "no-record", None
    card, raw = matches[0]
    release = raw.get("release")
    head = str(release.get("reviewed_head") or "") if isinstance(release, dict) else ""
    if not head:
        return None, "no-recorded-head", card if card != -1 else None
    return head, None, card if card != -1 else None


def reviewed_head_for_pr(
    gh_runner: Runner | None, repo: str, checkout: Path, pr: int,
) -> tuple[str | None, str | None]:
    """The introducing pull request's reviewed head: (head, None) or (None, reason).

    The stored review run is the trusted source; the marker comment cross-checks it. A
    comment-only head still links, because pruned checkouts are common and forging a head
    needs write access plus intent.
    """
    record_head, record_reason, _ = record_head_for_pr(checkout, pr)
    if record_reason == "ambiguous-release":
        return None, "ambiguous-release"
    if record_reason in ("store-unresolvable", "store-unreadable"):
        return None, str(record_reason)
    comment, comment_reason = marker_comment(gh_runner, repo, pr)
    found = marker_head(comment) if comment is not None else None
    if record_head is not None and found is not None:
        if record_head != found:
            return None, "head-mismatch"
        return record_head, None
    if record_head is not None:
        return record_head, None
    if found is not None:
        return found, None
    if comment_reason == "comments-unreadable":
        return None, "comments-unreadable"
    return None, "no-reviewed-head"


# ---------------------------------------------------------------------------
# Langfuse reads and posts
# ---------------------------------------------------------------------------


def _trace_transport(getenv: Any, urlopen: Any, resolve: Any) -> dict[str, Any]:
    transport: dict[str, Any] = {"getenv": getenv, "urlopen": urlopen}
    if resolve is not None:
        transport["resolve"] = resolve
    return transport


def refresh_index(
    state: dict[str, Any], since: str | None, *, getenv: Any, urlopen: Any, resolve: Any,
) -> tuple[int, str | None]:
    """Merge listed traces into the accumulated index. Returns (added, None) or (0, reason)."""
    import review_trace  # noqa: PLC0415 - lazy: --help answers without siblings

    transport = _trace_transport(getenv, urlopen, resolve)
    traces, info = review_trace.list_traces(since, page_size=TRACE_PAGE_SIZE, **transport)
    if info.get("error") is not None:
        return 0, str(info["error"])
    if info.get("capped"):
        return 0, "trace-pages-capped"
    if info.get("listed", 0) > 0 and info.get("parsed", 0) == 0:
        return 0, "trace-list-unparsed"
    index = state.setdefault("index", {})
    added = 0
    for trace in traces:
        metadata = trace.get("metadata") or {}
        entry = {
            "repo": str(metadata.get("repo") or ""),
            "base": str(metadata.get("base") or ""),
            "head": str(metadata.get("head") or ""),
            "card": metadata.get("card"),
            "round": metadata.get("round"),
            "timestamp": str(trace.get("timestamp") or ""),
        }
        if trace["id"] not in index:
            added += 1
        index[trace["id"]] = entry
    return added, None


def is_review_run(entry: Mapping[str, Any]) -> bool:
    """True when an index entry carries a code review's identity (repo, head, card, round)."""
    return (
        bool(entry.get("repo")) and bool(entry.get("head"))
        and isinstance(entry.get("card"), int) and isinstance(entry.get("round"), int)
    )


def match_trace(index: Mapping[str, Any], repo: str, head: str) -> str | None:
    """The highest-round trace identifier for (*repo*, *head*), else None."""
    candidates = [
        (trace_id, entry) for trace_id, entry in index.items()
        if isinstance(entry, Mapping) and is_review_run(entry)
        and entry.get("repo") == repo and entry.get("head") == head
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (int(item[1].get("round") or 0), str(item[0])))
    return str(candidates[-1][0])


def post_miss(
    trace_id: str, key: str, value: str, comment: str, metadata: Mapping[str, Any], *,
    home: Path, getenv: Any, urlopen: Any, resolve: Any,
) -> str | None:
    """Post one `review-miss` score. Returns None, or the reason it stayed local."""
    import review_trace  # noqa: PLC0415 - lazy: --help answers without siblings

    transport = _trace_transport(getenv, urlopen, resolve)
    try:
        summary = review_trace.post(
            [("scores", review_trace.miss_score(trace_id, key, value, comment=comment,
                                                metadata=dict(metadata)), None)],
            home=home, **transport)
    except Exception as exc:  # noqa: BLE001 - a Langfuse problem never fails the pass
        return f"miss-unpostable: {exc.__class__.__name__}"
    if summary.get("queued", 0) > 0 and summary.get("sent", 0) == 0:
        reasons = summary.get("reasons") or ["queued"]
        return f"miss-queued: {reasons[0]}"
    return None


def qa_miss_scores(
    trace_id: str, since: str | None, *, getenv: Any, urlopen: Any, resolve: Any,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """The `/qa` miss scores on *trace_id* in the window: (scores, None) or (None, reason)."""
    import review_trace  # noqa: PLC0415 - lazy: --help answers without siblings

    transport = _trace_transport(getenv, urlopen, resolve)
    try:
        scores, info = review_trace.trace_scores(
            trace_id, "review-miss", "found-by-qa", since=since,
            page_size=SCORE_PAGE_SIZE, **transport)
    except Exception as exc:  # noqa: BLE001 - a read problem is data, not a crash
        return None, f"scores-unreadable: {exc.__class__.__name__}"
    if info.get("error") is not None:
        return None, str(info["error"])
    if info.get("capped"):
        return None, "score-pages-capped"
    return scores, None


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


#: Reasons that block the window: infrastructure the next pass must retry, never routine
#: attribution outcomes. A permanently failing repository pins the window until the operator
#: drops it with `register --remove`, loudly (exit 1 every pass) rather than silently.
INFRA_REASONS = frozenset({
    "defect-list-failed",
    "defect-list-truncated",
    "closing-prs-unreadable",
    "pr-unreadable",
    "comments-unreadable",
    "fix-not-local",
    "trace-error: cannot read the fix",
    "trace-error: cannot read the merge parents",
    "trace-error: cannot list the merge range",
    "trace-error: cannot list the pull request commits",
    "trace-error: cannot parse the pull request commits",
    "blame-failed",
    "pr-lookup-failed",
    "revert-log-failed",
    "fetch-failed",
    "default-branch-unknown",
    "store-unresolvable",
    "store-unreadable",
})


def _is_infra(reason: str | None) -> bool:
    return reason in INFRA_REASONS


class Pass:
    """One daily pass: shared state, runners, window, counts and failures."""

    def __init__(
        self, *, home: Path, directory: Path, state: dict[str, Any],
        repos: dict[str, dict[str, str]], queue: Path, started: datetime,
        git_runner: Runner | None = None, gh_runner: Runner | None = None,
        getenv: Any = None, urlopen: Any = None, resolve: Any = None,
        mission_control: Path | None = None, mc_runner: Any = None,
    ) -> None:
        self.home = home
        self.directory = directory
        self.state = state
        self.repos = repos
        self.queue = queue
        self.started = started
        self.git_runner = git_runner
        self.gh_runner = gh_runner
        self.getenv = getenv if getenv is not None else os.environ.get
        self.urlopen = urlopen
        self.resolve = resolve
        self.mission_control = mission_control
        self.mc_runner = mc_runner if mc_runner is not None else default_mc_runner
        last = _parse_zulu(str(state.get("last_pass") or "")) if state.get("last_pass") else None
        self.window_start = last - OVERLAP if last is not None else None
        self.branches: dict[str, str] = {}
        self.counts = {"traces_indexed": 0, "defects_linked": 0, "reverts_linked": 0,
                       "queued": 0, "misses_queued_locally": 0, "boxes_filed": 0,
                       "addressed_rates_posted": 0}
        self.skip_claims: set[str] = set()
        self.filed_rounds: set[tuple[str, int, int]] = set()
        self.skips: dict[str, int] = {}
        self.failures: dict[str, str] = {}
        self.listings_ok = True

    def persist(self) -> None:
        save_state(self.directory, self.state)

    def skip(self, reason: str) -> None:
        self.skips[reason] = self.skips.get(reason, 0) + 1

    def fail(self, key: str, reason: str, *, blocks_window: bool) -> None:
        self.failures[key] = reason
        if blocks_window:
            self.listings_ok = False

    def transport(self) -> dict[str, Any]:
        return _trace_transport(self.getenv, self.urlopen, self.resolve)

    def window_iso(self) -> str | None:
        if self.window_start is None:
            return None
        return self.window_start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # -- fetch ------------------------------------------------------------

    def fetch_all(self) -> None:
        """Fetch each mapped checkout's default branch. A failure skips that repository."""
        for slug in sorted(self.repos):
            checkout = Path(self.repos[slug]["checkout"])
            branch = default_branch(self.git_runner, checkout)
            if branch is None:
                self.fail(f"fetch:{slug}", "default-branch-unknown", blocks_window=True)
                continue
            result = _git(self.git_runner, checkout, "fetch", "origin", branch,
                          timeout=FETCH_TIMEOUT)
            if not _ok(result):
                self.fail(f"fetch:{slug}", "fetch-failed", blocks_window=True)
                continue
            self.branches[slug] = branch

    # -- defects ----------------------------------------------------------

    def link_defect(self, repo: str, checkout: Path, number: int) -> None:
        """Link one closed defect to its review run, or record why not."""
        key = f"{repo}#{number}"
        if key in self.state["processed_defects"]:
            return
        closing, reason = closing_pull_requests(self.gh_runner, repo, number)
        if closing is None:
            assert reason is not None
            self.fail(f"defect:{key}", reason, blocks_window=_is_infra(reason))
            return
        if not closing:
            self.skip("closed-without-pr")
            return
        for closing_pr in closing:
            if self._link_defect_fix(repo, checkout, number, key, closing_pr):
                return

    def _link_defect_fix(self, repo: str, checkout: Path, number: int, key: str,
                         closing_pr: int) -> bool:
        """Link through one closing pull request. True when linked (first traceable wins)."""
        merge_sha, reason = merged_fix_commit(self.gh_runner, repo, closing_pr)
        if merge_sha is None:
            assert reason is not None
            if _is_infra(reason):
                self.fail(f"defect:{key}", reason, blocks_window=True)
            else:
                self.skip(reason)
            return False
        commits, reason = fix_commits_for_pr(
            self.git_runner, self.gh_runner, checkout, repo, closing_pr, merge_sha)
        if commits is None:
            assert reason is not None
            if _is_infra(reason):
                self.fail(f"defect:{key}", reason, blocks_window=True)
            else:
                self.skip(reason)
            return False
        introducing, reason = trace_fix_commits(
            self.git_runner, self.gh_runner, checkout, commits)
        if introducing is None:
            assert reason is not None
            if _is_infra(reason):
                self.fail(f"defect:{key}", reason, blocks_window=True)
            else:
                self.skip(reason)
            return False
        if introducing == closing_pr:
            self.skip("in-pr-repair")
            return False
        head, reason = reviewed_head_for_pr(self.gh_runner, repo, checkout, introducing)
        if head is None:
            assert reason is not None
            if _is_infra(reason):
                self.fail(f"defect:{key}", reason, blocks_window=True)
            else:
                self.skip(reason)
            return False
        trace_id = match_trace(self.state.get("index") or {}, repo, head)
        if trace_id is None:
            self.skip("no-matching-trace")
            return False
        queued = post_miss(
            trace_id, f"miss:defect:{number}", "found-after-merge",
            comment=f"found-after-merge defect #{number} via pull request #{closing_pr}",
            metadata={"source": "defect issue", "issue": number, "fixing_pr": closing_pr,
                      "introducing_pr": introducing},
            home=self.home, getenv=self.getenv, urlopen=self.urlopen, resolve=self.resolve,
        )
        if queued is not None:
            self.counts["misses_queued_locally"] += 1
        record: dict[str, Any] = {"source": "defect issue", "repository": repo,
                                  "review_run_id": trace_id, "fixing_pr": closing_pr}
        if not _is_merge(self.git_runner, checkout, merge_sha):
            record["fixing_commit"] = merge_sha
        try:
            outcome = append_queue_record(self.queue, record)
        except OutcomeJobError as exc:
            self.fail(f"defect:{key}", f"queue-refused: {exc}", blocks_window=False)
            return False
        if outcome == "appended":
            self.counts["queued"] += 1
        self.counts["defects_linked"] += 1
        self.state["processed_defects"].add(key)
        self.persist()
        return True

    def link_defects(self) -> None:
        """Link every closed defect updated in the window, per mapped repository."""
        for slug in sorted(self.repos):
            if slug not in self.branches:
                continue
            issues, reason = list_closed_defects(self.gh_runner, slug, self.window_start)
            if issues is None:
                assert reason is not None
                self.fail(f"defects:{slug}", reason, blocks_window=True)
                continue
            checkout = Path(self.repos[slug]["checkout"])
            for item in issues:
                number = item.get("number")
                if not isinstance(number, int):
                    continue
                self.link_defect(slug, checkout, number)

    # -- reverts ----------------------------------------------------------

    def link_revert(self, repo: str, checkout: Path, sha: str, subject: str) -> None:
        """Link one revert commit to its review run, or record why not."""
        key = f"{repo}:{sha}"
        if key in self.state["processed_reverts"]:
            return
        by_pr, reason = trace_single(self.git_runner, self.gh_runner, checkout, sha)
        if by_pr is None:
            assert reason is not None
            if _is_infra(reason):
                self.fail(f"revert:{key}", reason, blocks_window=True)
            else:
                self.skip(reason)
            return
        if len(by_pr) > 1:
            self.skip("spans-pull-requests")
            return
        (introducing,) = by_pr
        own_pr = own_pr_from_subject(subject)
        if own_pr is not None and own_pr == introducing:
            self.skip("in-pr-repair")
            return
        head, reason = reviewed_head_for_pr(self.gh_runner, repo, checkout, introducing)
        if head is None:
            assert reason is not None
            if _is_infra(reason):
                self.fail(f"revert:{key}", reason, blocks_window=True)
            else:
                self.skip(reason)
            return
        trace_id = match_trace(self.state.get("index") or {}, repo, head)
        if trace_id is None:
            self.skip("no-matching-trace")
            return
        queued = post_miss(
            trace_id, f"miss:revert:{sha[:12]}", "reverted",
            comment=f"reverted {sha[:12]} from pull request #{introducing}",
            metadata={"source": "revert", "revert_sha": sha,
                      "introducing_pr": introducing},
            home=self.home, getenv=self.getenv, urlopen=self.urlopen, resolve=self.resolve,
        )
        if queued is not None:
            self.counts["misses_queued_locally"] += 1
        record: dict[str, Any] = {"source": "revert", "repository": repo,
                                  "review_run_id": trace_id, "fixing_commit": sha}
        if own_pr is not None:
            record["fixing_pr"] = own_pr
        try:
            outcome = append_queue_record(self.queue, record)
        except OutcomeJobError as exc:
            self.fail(f"revert:{key}", reason=f"queue-refused: {exc}", blocks_window=False)
            return
        if outcome == "appended":
            self.counts["queued"] += 1
        self.counts["reverts_linked"] += 1
        self.state["processed_reverts"].add(key)
        self.persist()

    def link_reverts(self) -> None:
        """Link every revert on each mapped default branch in the window."""
        for slug in sorted(self.repos):
            branch = self.branches.get(slug)
            if branch is None:
                continue
            checkout = Path(self.repos[slug]["checkout"])
            found, reason = revert_commits(self.git_runner, checkout, branch, self.window_start)
            if found is None:
                assert reason is not None
                self.fail(f"reverts:{slug}", reason, blocks_window=True)
                continue
            for sha, subject in found:
                self.link_revert(slug, checkout, sha, subject)

    # -- /qa misses --------------------------------------------------------

    def read_qa_misses(self) -> None:
        """Hold every new `/qa` miss score as pending until its repair lands."""
        index = self.state.get("index") or {}
        for trace_id in sorted(index):
            entry = index[trace_id]
            if not isinstance(entry, Mapping) or not is_review_run(entry):
                continue
            scores, reason = qa_miss_scores(trace_id, self.window_iso(), **self.transport())
            if scores is None:
                assert reason is not None
                self.fail(f"scores:{trace_id}", reason, blocks_window=True)
                continue
            for score in scores:
                self.hold_qa_miss(trace_id, entry, score)

    def hold_qa_miss(self, trace_id: str, entry: Mapping[str, Any],
                     score: Mapping[str, Any]) -> None:
        """Pend one miss score for repair matching, unless already queued or pending."""
        metadata = score.get("metadata") if isinstance(score.get("metadata"), dict) else {}
        strategy = str(metadata.get("strategy") or "")
        revision = str(metadata.get("tested_revision") or "")
        if not strategy or not revision:
            match = re.match(r"found-by-qa (\S+) at (\S+)", str(score.get("comment") or ""))
            if match:
                strategy = strategy or match.group(1)
                revision = revision or match.group(2)
        if not revision:
            self.skip("miss-without-revision")
            return
        repo = str(entry.get("repo") or "")
        if f"{trace_id}:{revision}" in self.state["queued_qa"]:
            return
        for pending in self.state["pending_qa"]:
            if pending.get("trace") == trace_id and pending.get("revision") == revision:
                return
        self.state["pending_qa"].append({
            "trace": trace_id, "repo": repo, "card": entry.get("card"),
            "strategy": strategy, "revision": revision, "seen": _now_zulu(),
        })
        self.persist()

    def resolve_qa_misses(self) -> None:
        """Queue each pending miss whose run record shows the repair landed."""
        still_pending = []
        for pending in self.state["pending_qa"]:
            if not self._resolve_one_qa_miss(pending):
                still_pending.append(pending)
        self.state["pending_qa"] = still_pending
        self.persist()

    def _resolve_one_qa_miss(self, pending: Mapping[str, Any]) -> bool:
        """Queue one pending miss when its repair has landed. True when done."""
        trace_id = str(pending.get("trace") or "")
        repo = str(pending.get("repo") or "")
        card = pending.get("card")
        tested = str(pending.get("revision") or "")
        mapping = self.repos.get(repo)
        if mapping is None or not isinstance(card, int):
            return False
        record = self._record_for(repo, card)
        if record is None:
            return False
        qa = record.get("qa") if isinstance(record.get("qa"), dict) else {}
        environment = qa.get("environment") if isinstance(qa.get("environment"), dict) else {}
        if str(environment.get("revision") or "") != tested:
            return False
        release = record.get("release") if isinstance(record.get("release"), dict) else {}
        if release.get("status") != "merged":
            return False
        landed = str(release.get("landed_commit") or "")
        fixing_pr = release.get("pull_request")
        if not landed or landed == tested:
            return False
        checkout = Path(mapping["checkout"])
        ancestor = _git(self.git_runner, checkout, "merge-base", "--is-ancestor", tested, landed)
        if not _ok(ancestor):
            return False
        record_line: dict[str, Any] = {"source": "/qa", "repository": repo,
                                       "review_run_id": trace_id}
        if isinstance(fixing_pr, int) and not isinstance(fixing_pr, bool):
            record_line["fixing_pr"] = fixing_pr
        if not _is_merge(self.git_runner, checkout, landed):
            record_line["fixing_commit"] = landed
        if record_line.get("fixing_pr") is None and record_line.get("fixing_commit") is None:
            self.fail(f"qa:{trace_id}", "repair-unqueueable", blocks_window=False)
            return False
        try:
            outcome = append_queue_record(self.queue, record_line)
        except OutcomeJobError as exc:
            self.fail(f"qa:{trace_id}", f"queue-refused: {exc}", blocks_window=False)
            return False
        if outcome == "appended":
            self.counts["queued"] += 1
        self.state["queued_qa"].add(f"{trace_id}:{tested}")
        self.persist()
        return True

    def reconcile_claims(self) -> None:
        """Adopt, release or hold every claim journalled by an earlier pass (KTD8)."""
        claimed = self.state.get("claimed") or {}
        for key in sorted(claimed):
            entry = claimed.get(key)
            if not isinstance(entry, Mapping):
                del claimed[key]
                self.persist()
                continue
            repo = str(entry.get("repo") or "")
            card = entry.get("card")
            finding_id = str(entry.get("finding") or "")
            title = str(entry.get("title") or "")
            record = self._record_for(repo, card) if isinstance(card, int) else None
            if repo not in self.repos or record is None:
                continue
            run = newest_stored_run(record)
            if run is None:
                continue
            if not self._still_left(run, finding_id):
                del claimed[key]
                self.persist()
                continue
            if not title or not finding_id:
                del claimed[key]
                self.persist()
                continue
            hits, reason = search_issue_by_title(self.gh_runner, repo, title)
            if hits is None:
                assert reason is not None
                self.skip(reason)
                self.skip_claims.add(key)
                continue
            number = adopted_issue(hits, title, finding_id)
            filed = self.state.setdefault("filed", {})
            if number is not None:
                filed[key] = number
            del claimed[key]
            self.persist()

    @staticmethod
    def _still_left(run: Mapping[str, Any], finding_id: str) -> bool:
        for finding in run.get("findings") or []:
            if (isinstance(finding, Mapping) and finding.get("id") == finding_id
                    and str(finding.get("severity") or "") == "fix-later"):
                return _finding_outcome(finding) == "left"
        return False

    def file_fix_laters(self) -> None:
        """File every ticked box that is still `left`, once per record (KTD8)."""
        self.reconcile_claims()
        seen: set[tuple[str, int]] = set()
        index = self.state.get("index") or {}
        for trace_id in sorted(index):
            entry = index[trace_id]
            if not isinstance(entry, Mapping) or not is_review_run(entry):
                continue
            repo = str(entry.get("repo") or "")
            card = entry.get("card")
            if not isinstance(card, int) or (repo, card) in seen:
                continue
            seen.add((repo, card))
            if repo not in self.repos:
                self.skip("repo-unmapped")
                continue
            record = self._record_for(repo, card)
            if record is None:
                continue
            self._file_card(repo, card, record)

    def _file_card(self, repo: str, card: int, record: Mapping[str, Any]) -> None:
        release = record.get("release") if isinstance(record.get("release"), dict) else {}
        pr = release.get("pull_request")
        if not isinstance(pr, int) or isinstance(pr, bool):
            run = newest_stored_run(record)
            if run is not None and self._left_fix_laters(run):
                self.skip("unreleased-card")
            return
        run = newest_stored_run(record)
        if run is None:
            return
        findings = self._left_fix_laters(run)
        if not findings:
            return
        checkout = Path(self.repos[repo]["checkout"])
        comment, reason = marker_comment(self.gh_runner, repo, pr)
        if comment is None:
            assert reason is not None
            if reason == "comments-unreadable":
                self.fail(f"filing:{repo}#{card}", reason, blocks_window=True)
            else:
                self.skip(reason)
            return
        body = {"text": str(comment.get("body") or ""), "id": comment.get("id")}
        boxes = parse_boxes(body["text"])
        for finding in findings:
            self._file_finding(repo, card, checkout, run, finding, boxes, body)

    @staticmethod
    def _left_fix_laters(run: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [finding for finding in run.get("findings") or []
                if isinstance(finding, Mapping)
                and str(finding.get("severity") or "") == "fix-later"
                and _finding_outcome(finding) == "left"]

    def _file_finding(self, repo: str, card: int, checkout: Path, run: Mapping[str, Any],
                      finding: Mapping[str, Any], boxes: Mapping[str, Any],
                      body: dict[str, Any]) -> None:
        import review_state  # noqa: PLC0415 - lazy: --help answers without siblings

        finding_id = str(finding.get("id") or "")
        key = f"{repo}#{card}:{finding_id}"
        if key in self.skip_claims:
            return
        filed = self.state.setdefault("filed", {})
        if key in filed and isinstance(filed[key], int):
            self._flip_post_link(repo, card, checkout, key, finding_id, int(filed[key]), body)
            return
        box = boxes.get(finding_id) if isinstance(boxes.get(finding_id), Mapping) else {}
        if isinstance(box.get("linked"), int) and not isinstance(box.get("linked"), bool):
            filed[key] = int(box["linked"])
            self.persist()
            self._flip_post_link(repo, card, checkout, key, finding_id, int(box["linked"]), body)
            return
        if not box.get("ticked"):
            return
        try:
            title, defect = review_state.defect_body(
                [finding], repo=repo, card=card, revision=str(run.get("head") or ""))
            risk = review_state.RISK_BY_GROUP[review_state.consequence_group(finding)]
        except Exception as exc:  # noqa: BLE001 - an unshapable finding is data, not a crash
            self.fail(f"filing:{key}", f"finding-unshapable: {exc.__class__.__name__}",
                      blocks_window=False)
            return
        claimed = self.state.setdefault("claimed", {})
        claimed[key] = {"title": title, "repo": repo, "card": card, "finding": finding_id}
        self.persist()
        try:
            number = review_state.file_issue(
                self.mission_control, self.mc_runner, repo=repo, card=card,
                revision=str(run.get("head") or ""), title=title, body=defect, risk=risk)
        except review_state.ReviewStateError as exc:
            del claimed[key]
            self.persist()
            self.fail(f"filing:{key}", str(exc), blocks_window=False)
            return
        filed[key] = number
        del claimed[key]
        self.persist()
        self.counts["boxes_filed"] += 1
        if isinstance(run.get("round"), int):
            self.filed_rounds.add((repo, card, int(run["round"])))
        self._flip_post_link(repo, card, checkout, key, finding_id, number, body)

    def _flip_post_link(self, repo: str, card: int, checkout: Path, key: str,
                        finding_id: str, number: int, body: dict[str, Any]) -> None:
        flipped, reason = flip_finding_to_filed(checkout, card, finding_id, number)
        if flipped is None:
            assert reason is not None
            self.fail(f"filing:{key}", reason, blocks_window=False)
            return
        if not self._post_flip_score(repo, card, checkout, key, finding_id):
            return
        linked = link_box_line(body["text"], finding_id, number)
        if linked is None:
            return
        reason = edit_comment_body(self.gh_runner, repo, body["id"], linked)
        if reason is not None:
            self.fail(f"filing:{key}", reason, blocks_window=False)
            return
        body["text"] = linked

    def _post_flip_score(self, repo: str, card: int, checkout: Path, key: str,
                         finding_id: str) -> bool:
        import review_trace  # noqa: PLC0415 - lazy: --help answers without siblings

        record = self._record_for(repo, card)
        if record is None:
            self.fail(f"filing:{key}", "record-unreadable", blocks_window=False)
            return False
        slug = review_trace.repository_slug(checkout, recorded=record.get("repo"))
        pairs, _ = review_trace.outcome_scores(record, slug)
        run = newest_stored_run(record)
        if run is None:
            self.fail(f"filing:{key}", "run-unreadable", blocks_window=False)
            return False
        trace = review_trace.review_trace_id(run, slug)
        wanted = review_trace.score_id(
            trace, review_trace.finding_key(finding_id), "merge-outcome")
        score = next((entry for _, entry in pairs if entry.get("id") == wanted), None)
        if score is None:
            self.fail(f"filing:{key}", "outcome-unscored", blocks_window=False)
            return False
        visible = review_trace.visibility(checkout, str(run.get("base") or ""))
        review_trace.post([("scores", score, visible)], home=self.home, **self.transport())
        return True

    def post_addressed_rates(self) -> None:
        """One addressed-rate score per completed round-trace, reposted on filing (R13)."""
        import review_trace  # noqa: PLC0415 - lazy: --help answers without siblings

        index = self.state.get("index") or {}
        for trace_id in sorted(index):
            entry = index[trace_id]
            if not isinstance(entry, Mapping) or not is_review_run(entry):
                continue
            repo = str(entry.get("repo") or "")
            card = entry.get("card")
            round_no = entry.get("round")
            if repo not in self.repos or not isinstance(card, int):
                continue
            record = self._record_for(repo, card)
            if record is None:
                continue
            runs = stored_runs(record)
            run = next((entry for entry in runs if entry.get("round") == round_no), None)
            if run is None:
                continue
            counts = addressed_counts(run)
            if counts is None:
                continue
            newest = max((int(entry.get("round") or 0) for entry in runs), default=0)
            posted = self.state.get("addressed_posted") or set()
            repost = (round_no == newest and (repo, card, round_no) in self.filed_rounds)
            if trace_id in posted and not repost:
                continue
            value = (counts["fixed"] + counts["fixed-now"] + counts["filed"]) / counts["total"]
            checkout = Path(self.repos[repo]["checkout"])
            visible = review_trace.visibility(checkout, str(run.get("base") or ""))
            score = review_trace.addressed_rate_score(trace_id, value, counts)
            review_trace.post([("scores", score, visible)], home=self.home, **self.transport())
            posted.add(trace_id)
            self.state["addressed_posted"] = posted
            self.counts["addressed_rates_posted"] += 1
            self.persist()

    def _record_for(self, repo: str, card: int) -> dict[str, Any] | None:
        """The run record for (*repo*, *card*) through the checkout map, else None."""
        import run_record  # noqa: PLC0415 - lazy: --help answers without siblings

        mapping = self.repos.get(repo)
        if mapping is None:
            return None
        try:
            store = run_record.resolve_store_root(Path(mapping["checkout"]))
            raw = json.loads(run_record.record_path(store, card).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - any read fault reads as unavailable
            return None
        return raw if isinstance(raw, dict) else None


# ---------------------------------------------------------------------------
# Filing ticked fix-later boxes
# ---------------------------------------------------------------------------


BOX_RE = re.compile(r"^-\s+\[([ xX])\]\s+(rf:[0-9a-f]+)\b")


def _finding_outcome(finding: Mapping[str, Any]) -> str | None:
    """The finding's recorded merge outcome, or None when it carries none."""
    outcome = finding.get("merge_outcome")
    if not isinstance(outcome, Mapping):
        return None
    value = outcome.get("outcome")
    return str(value) if value is not None else None


def stored_runs(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every stored C1 review run, oldest first. The flip and the scores agree on this."""
    import review_records  # noqa: PLC0415 - lazy: --help answers without siblings
    import review_state  # noqa: PLC0415 - lazy: --help answers without siblings

    return [entry for entry in review_state.review_runs(record)
            if entry.get("loop") == review_records.STORED_LOOP]


def newest_stored_run(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """The newest stored run, or None when the record holds none."""
    runs = stored_runs(record)
    return runs[-1] if runs else None


def parse_boxes(body: str) -> dict[str, dict[str, Any]]:
    """Each checklist box by finding id: `ticked` and the linked issue number or None."""
    boxes: dict[str, dict[str, Any]] = {}
    for line in str(body or "").splitlines():
        box = BOX_RE.match(line.strip())
        if not box:
            continue
        linked = LINKED_RE.search(line.strip())
        boxes[box.group(2)] = {
            "ticked": box.group(1) in ("x", "X"),
            "linked": int(linked.group(1)) if linked else None,
        }
    return boxes


def link_box_line(body: str, finding_id: str, number: int) -> str | None:
    """The comment with ` → #<n>` on the finding's box line, else None when already linked."""
    lines = str(body or "").splitlines()
    for position, line in enumerate(lines):
        box = BOX_RE.match(line.strip())
        if box and box.group(2) == finding_id and not LINKED_RE.search(line.strip()):
            lines[position] = f"{line.rstrip()} → #{number}"
            return "\n".join(lines)
    return None


def search_issue_by_title(
    gh_runner: Runner | None, repo: str, title: str,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Issues matching the claim title: (hits, None) or (None, reason)."""
    quoted = f'"{str(title).replace(chr(34), "")}"'
    hits = _gh_json(gh_runner, "issue", "list", "--repo", repo, "--search", quoted,
                    "--state", "all", "--limit", "20", "--json", "number,title,body")
    if not isinstance(hits, list):
        return None, "claim-search-failed"
    return [hit for hit in hits if isinstance(hit, dict)], None


def adopted_issue(hits: Sequence[Mapping[str, Any]], title: str, finding_id: str) -> int | None:
    """The hit with exactly the claim title whose body carries the finding, else None."""
    for hit in hits:
        number = hit.get("number")
        if (str(hit.get("title") or "") == title and finding_id in str(hit.get("body") or "")
                and isinstance(number, int) and not isinstance(number, bool)):
            return number
    return None


def edit_comment_body(
    gh_runner: Runner | None, repo: str, comment_id: Any, body: str,
) -> str | None:
    """Replace the comment's body. None, or the reason it failed."""
    result = _gh(gh_runner, "api", f"repos/{repo}/issues/comments/{comment_id}",
                 "--method", "PATCH", "-f", f"body={body}")
    if not _ok(result):
        return "comment-edit-failed"
    return None


def default_mc_runner(argv: Sequence[str], cwd: Any = None) -> Any:
    """Mission-control through one subprocess: fixed vector, scrubbed environment."""
    return production_runner([str(part) for part in argv],
                             cwd=Path(cwd) if cwd is not None else None,
                             env=scrub_env(), timeout=GH_TIMEOUT)


def flip_finding_to_filed(
    checkout: Path, card: int, finding_id: str, number: int,
) -> tuple[bool | None, str | None]:
    """Stamp the finding `filed` under the record lock: (flipped, None) or (None, reason).

    False means the record already carried `filed` (a crash won the race); anything recorded
    under another outcome refuses rather than overwrite a decision made elsewhere.
    """
    import review_state  # noqa: PLC0415 - lazy: --help answers without siblings
    import run_record  # noqa: PLC0415 - lazy: --help answers without siblings

    try:
        store = run_record.resolve_store_root(Path(checkout))
    except Exception:  # noqa: BLE001 - any resolution fault reads as unavailable
        return None, "store-unresolvable"
    box: dict[str, Any] = {}

    def change(existing: Any) -> Any:
        if existing is None:
            raise review_state.ReviewStateError(f"no record for issue {card}")
        runs = [entry for entry in existing.review_cycles
                if isinstance(entry, dict)
                and entry.get("kind") == review_state.KIND_REVIEW_RUN]
        if not runs:
            raise review_state.ReviewStateError("no review run is recorded yet")
        run = runs[-1]
        finding = next((entry for entry in run.get("findings") or []
                        if isinstance(entry, dict) and entry.get("id") == finding_id), None)
        if finding is None:
            raise review_state.ReviewStateError(f"no stored finding {finding_id!r}")
        current = _finding_outcome(finding)
        if current == "filed":
            box["flipped"] = False
            return existing
        if current != "left":
            raise review_state.ReviewStateError(
                f"{finding_id} is already recorded {current}, not left")
        review_state.stamp_fix_later(run, finding_id, {"outcome": "filed", "issue": number})
        box["flipped"] = True
        return existing

    try:
        run_record.update(store, card, change)
    except (review_state.ReviewStateError, run_record.RunRecordError) as exc:
        return None, f"flip-failed: {exc}"
    return bool(box.get("flipped")), None


def addressed_counts(run: Mapping[str, Any]) -> dict[str, int] | None:
    """Per-outcome counts when every finding carries one, else None (KTD10, KTD15)."""
    findings = [entry for entry in run.get("findings") or [] if isinstance(entry, Mapping)]
    if not findings:
        return None
    counts = {"fixed": 0, "fixed-now": 0, "filed": 0, "dismissed": 0, "left": 0}
    for finding in findings:
        outcome = _finding_outcome(finding)
        if outcome is None or outcome not in counts:
            return None
        counts[outcome] += 1
    return {**counts, "total": len(findings)}


# ---------------------------------------------------------------------------
# The schedule, the checkout map and the status line
# ---------------------------------------------------------------------------


def schedule_plist_path(home: Path) -> Path:
    """The launchd agent path under *home*."""
    return Path(home) / "Library" / "LaunchAgents" / f"{SCHEDULE_LABEL}.plist"


def render_plist(*, keychain_env: str, python: str, script: str, home: str,
                 state: str, out_log: str, err_log: str) -> bytes:
    """The agent property list. Paths ride as arguments; the body is fixed (KTD12)."""
    return plistlib.dumps({
        "Label": SCHEDULE_LABEL,
        "ProgramArguments": ["/bin/sh", "-c", SCHEDULE_BODY, "sh",
                             keychain_env, python, script, home],
        "WorkingDirectory": state,
        "StandardOutPath": out_log,
        "StandardErrorPath": err_log,
        "StartCalendarInterval": {"Hour": SCHEDULE_HOUR, "Minute": SCHEDULE_MINUTE},
    })


def _tool_runner(runner: Runner | None) -> Any:
    """The injected runner behind the review-tools call shape, for slug resolution."""

    def run(argv: Any, *, cwd: Any, env: Any, timeout: int, shell: bool) -> Any:
        assert not shell
        call = runner if runner is not None else production_runner
        completed = call(argv, cwd=cwd, env=env, timeout=timeout)
        return SimpleNamespace(code=completed.returncode, stdout=completed.stdout)

    return run


def checkout_slug(runner: Runner | None, checkout: Path) -> tuple[str | None, str | None]:
    """The checkout's `owner/name` origin: (slug, None) or (None, reason).

    Only GitHub remotes qualify: the job drives them through `gh`, and a local path would
    parse as a bogus slug that poisons the window until removed.
    """
    import review_trace  # noqa: PLC0415 - lazy: --help answers without siblings

    try:
        toplevel = _git(runner, checkout, "rev-parse", "--show-toplevel")
        url = _git(runner, checkout, "remote", "get-url", "origin")
    except OSError:
        return None, "git is not available"
    if not _ok(toplevel):
        return None, "not a git checkout"
    if not _ok(url) or not re.search(r"github\.com[:/][^/\s]+/[^/\s]+", _out(url)):
        return None, "no GitHub owner/name origin"
    slug = review_trace.repository_slug(Path(checkout), runner=_tool_runner(runner))
    if slug == "unknown":
        return None, "no GitHub owner/name origin"
    return slug, None


def install_schedule(*, home: Path, runner: Runner | None = None, out: Any = None) -> int:
    """Install (or replace) the daily launchd agent. Refusals raise `OutcomeJobError`."""
    stream = out if out is not None else sys.stdout
    call = runner if runner is not None else production_runner
    missing = [name for name in ("launchctl", "keychain-env") if shutil.which(name) is None]
    if missing:
        raise OutcomeJobError(f"install-schedule needs {' and '.join(missing)} on PATH")
    directory = state_dir(home).resolve()
    resolved = str(Path(home).resolve())
    plist = schedule_plist_path(Path(resolved))
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(render_plist(
        keychain_env=str(Path(str(shutil.which("keychain-env"))).resolve()),
        python=str(Path(sys.executable).resolve()),
        script=str(Path(__file__).resolve()),
        home=resolved,
        state=str(directory),
        out_log=str(directory / "launchd-stdout.log"),
        err_log=str(directory / "launchd-stderr.log"),
    ))
    domain = f"gui/{os.getuid()}"
    call(["launchctl", "bootout", f"{domain}/{SCHEDULE_LABEL}"],
         cwd=None, env=scrub_env(), timeout=GH_TIMEOUT)
    loaded = call(["launchctl", "bootstrap", domain, str(plist)],
                  cwd=None, env=scrub_env(), timeout=GH_TIMEOUT)
    if getattr(loaded, "returncode", 1) != 0:
        raise OutcomeJobError(
            f"launchctl bootstrap refused {plist}: {str(getattr(loaded, 'stderr', ''))[-200:]}")
    print(f"outcome-job: installed {plist}", file=stream)
    here = Path.cwd()
    slug, reason = checkout_slug(runner, here)
    if slug is None:
        print(f"outcome-job: no repository registered ({reason})", file=stream)
        return 0
    repos = load_repos(directory)
    repos[slug] = {"checkout": str(here.resolve()), "added": _now_zulu()}
    save_repos(directory, repos)
    print(f"outcome-job: registered {slug} at {here.resolve()}", file=stream)
    return 0


def register_checkout(*, home: Path, repo_root: Path, remove: bool,
                      runner: Runner | None = None, out: Any = None) -> int:
    """Map a checkout to its slug, or drop the mapping. Refusals raise `OutcomeJobError`."""
    stream = out if out is not None else sys.stdout
    directory = state_dir(home)
    repos = load_repos(directory)
    root = str(Path(repo_root).expanduser().resolve())
    if remove:
        for slug, entry in repos.items():
            if entry.get("checkout") == root:
                del repos[slug]
                save_repos(directory, repos)
                print(f"outcome-job: removed {slug} at {root}", file=stream)
                return 0
        raise OutcomeJobError(f"no registered checkout at {root}")
    slug, reason = checkout_slug(runner, Path(root))
    if slug is None:
        raise OutcomeJobError(f"cannot register {root}: {reason}")
    previous = repos.get(slug)
    repos[slug] = {"checkout": root,
                   "added": previous.get("added") if isinstance(previous, dict)
                   and previous.get("added") else _now_zulu()}
    save_repos(directory, repos)
    moved = isinstance(previous, dict) and previous.get("checkout") not in (None, root)
    print(f"outcome-job: {'updated' if moved else 'registered'} {slug} at {root}",
          file=stream)
    return 0


def show_status(*, home: Path, out: Any = None) -> int:
    """The job's state on one counts line plus one line per repository. No network."""
    stream = out if out is not None else sys.stdout
    directory = state_dir(home)
    state = load_state(directory)
    repos = load_repos(directory)
    print(
        "outcome-job:"
        f" repositories={len(repos)}"
        f" last-pass={state.get('last_pass') or 'never'}"
        f" traces={len(state.get('index') or {})}"
        f" pending-qa={len(state.get('pending_qa') or [])}"
        f" filed={len(state.get('filed') or {})}"
        f" addressed-posted={len(state.get('addressed_posted') or [])}"
        f" failures={len(state.get('failures') or {})}",
        file=stream,
    )
    for slug in sorted(repos):
        print(f"outcome-job: repo {slug} at {repos[slug].get('checkout')}", file=stream)
    return 0


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _work_from(directory: Path) -> Iterator[None]:
    """Run the pass from the state directory, restoring the caller's directory after."""
    previous = os.getcwd()
    os.chdir(directory)
    try:
        yield
    finally:
        os.chdir(previous)


@contextlib.contextmanager
def _state_locked(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive non-blocking lock; refuse when another pass holds it."""
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise OutcomeJobError(
                "another outcome-job pass holds the state lock") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def build_parser() -> argparse.ArgumentParser:
    """The job's verbs. `run` lands first; `register`, `install-schedule` and `status` follow."""
    parser = argparse.ArgumentParser(
        prog="outcome_job",
        description="Link later defects to the reviews that passed them, and queue them.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    running = sub.add_parser("run", help="Run one daily pass.")
    running.add_argument("--home", default=None, help="Home directory (default: the user's).")
    running.add_argument("--queue", default=None, help="Candidate queue path (default: K1's).")
    running.add_argument("--mission-control", default=None,
                         help="Mission-control script for filing (default: resolve at run time).")
    install = sub.add_parser("install-schedule", help="Install the daily launchd agent.")
    install.add_argument("--home", default=None, help="Home directory (default: the user's).")
    register = sub.add_parser("register", help="Map a checkout to its slug, or drop it.")
    register.add_argument("--home", default=None, help="Home directory (default: the user's).")
    register.add_argument("--repo-root", required=True, help="The checkout to map or drop.")
    register.add_argument("--remove", action="store_true",
                          help="Drop the checkout's mapping instead of mapping it.")
    status = sub.add_parser("status", help="Print the job's state without touching anything.")
    status.add_argument("--home", default=None, help="Home directory (default: the user's).")
    return parser


def _print_summary(pass_: Pass, stream: Any = None) -> None:
    out = stream if stream is not None else sys.stdout
    counts = " ".join(f"{name}={value}" for name, value in sorted(pass_.counts.items()))
    print(f"outcome-job: {counts}", file=out)
    for reason in sorted(pass_.skips):
        print(f"outcome-job: skipped {pass_.skips[reason]} ({reason})", file=out)
    for key in sorted(pass_.failures):
        print(f"outcome-job: failed {key} ({pass_.failures[key]})", file=out)
    print(f"outcome-job: window-advanced={'yes' if pass_.listings_ok else 'no'}", file=out)


def run_pass(
    *, home: Path, queue: Path | None = None,
    git_runner: Runner | None = None, gh_runner: Runner | None = None,
    getenv: Any = None, urlopen: Any = None, resolve: Any = None,
    clock: Callable[[], datetime] | None = None, out: Any = None,
    mission_control: Path | None = None, mc_runner: Any = None,
) -> int:
    """One daily pass. Returns 0 clean, 1 when the window held or anything failed, 2 on refusal."""
    stream = out if out is not None else sys.stdout
    directory = state_dir(home)
    try:
        with _work_from(directory), _state_locked(directory / "state.lock"):
            state = load_state(directory)
            repos = load_repos(directory)
            started = clock() if clock is not None else datetime.now(UTC)
            pass_ = Pass(
                home=home, directory=directory, state=state, repos=repos,
                queue=queue if queue is not None else default_queue_path(), started=started,
                git_runner=git_runner, gh_runner=gh_runner,
                getenv=getenv, urlopen=urlopen, resolve=resolve,
                mission_control=mission_control, mc_runner=mc_runner,
            )
            pass_.fetch_all()
            added, reason = refresh_index(
                state, pass_.window_iso(), getenv=pass_.getenv, urlopen=pass_.urlopen,
                resolve=pass_.resolve)
            if reason is not None:
                pass_.fail("traces", reason, blocks_window=True)
            else:
                pass_.counts["traces_indexed"] = added
            pass_.link_defects()
            pass_.link_reverts()
            pass_.read_qa_misses()
            pass_.resolve_qa_misses()
            pass_.file_fix_laters()
            pass_.post_addressed_rates()
            if pass_.listings_ok:
                state["last_pass"] = started.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            state["failures"] = dict(pass_.failures)
            pass_.persist()
            _print_summary(pass_, stream)
            return 0 if pass_.listings_ok and not pass_.failures else 1
    except OutcomeJobError as exc:
        print(f"outcome-job: {exc}", file=sys.stderr)
        return 2


def main(argv: Sequence[str] | None = None, **seams: Any) -> int:
    """The command line. Seams (`git_runner`, `gh_runner`, `getenv`, `urlopen`, `resolve`,
    `clock`, `out`, `mc_runner`, `runner`) arrive as keywords the parser never sees."""
    args = build_parser().parse_args(argv)
    home = Path(args.home).expanduser() if args.home else Path.home()
    queue = Path(args.queue).expanduser() if getattr(args, "queue", None) else None
    out = seams.get("out") or sys.stdout
    runner = seams.get("runner")
    try:
        if args.command == "run":
            mc = Path(args.mission_control).expanduser() if args.mission_control else None
            run_seams = {key: value for key, value in seams.items() if key != "runner"}
            return run_pass(home=home, queue=queue, mission_control=mc, **run_seams)
        if args.command == "install-schedule":
            return install_schedule(home=home, runner=runner, out=out)
        if args.command == "register":
            return register_checkout(home=home, repo_root=Path(args.repo_root),
                                     remove=args.remove, runner=runner, out=out)
        if args.command == "status":
            return show_status(home=home, out=out)
    except OutcomeJobError as exc:
        print(f"outcome-job: {exc}", file=sys.stderr)
        return 2
    raise OutcomeJobError(f"unknown command {args.command!r}")


if __name__ == "__main__":
    sys.exit(main())
