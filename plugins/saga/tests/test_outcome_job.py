"""The review-outcome job: linking, queueing, filing, addressed rates and the schedule.

Issue 167, card C16. No test reaches the network: git runs against fixture clones with a
local origin, `gh` and mission-control are injected runners, and Langfuse is an injected
transport. The module fixture refuses new connections besides.
"""

from __future__ import annotations

import copy
import importlib.util
import io
import plistlib
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


OJ = _load("outcome_job")
RS = _load("review_state")
RT = _load("review_trace")

PUBLIC = "pk-lf-SENTINEL-public"
SECRET = "[REDACTED]"  # noqa: S105 - a test fixture, not a credential
HOST = "https://langfuse.example.test"
NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("no network in tests")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def _public_resolve(*_args: Any, **_kwargs: Any) -> list[Any]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]


def _lf_env() -> dict[str, str]:
    return {"SAGA_LANGFUSE_PUBLIC_KEY": PUBLIC, "SAGA_LANGFUSE_SECRET_KEY": SECRET,
            "SAGA_LANGFUSE_HOST": HOST}


# ---------------------------------------------------------------------------
# Fixture git histories (real git, local origin only)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    completed = subprocess.run(
        ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null",
         "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True, check=False, timeout=60, env=run_env,
    )
    assert completed.returncode == 0, (args, completed.stderr[-500:])
    return completed.stdout.strip()


_COMMIT_TICK = 0


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    """Commit with a fixed, distinct timestamp, so window comparisons never depend on now."""
    global _COMMIT_TICK
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    stamp = datetime(2026, 10, 8, 11, 0, 0, tzinfo=UTC) + timedelta(seconds=_COMMIT_TICK)
    _COMMIT_TICK += 1
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message, "--quiet",
         env={"GIT_AUTHOR_DATE": stamp.isoformat(), "GIT_COMMITTER_DATE": stamp.isoformat()})
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def origin(tmp_path: Path) -> Path:
    """A bare origin the fixture checkouts clone, so fetch works with no network."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)],
                   capture_output=True, text=True, check=True, timeout=60)
    return bare


@pytest.fixture()
def checkout(tmp_path: Path, origin: Path) -> Path:
    """A clone on main with an initial commit, pushed, identity configured."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", str(origin), str(repo)],
                   capture_output=True, text=True, check=True, timeout=60)
    _git(repo, "config", "user.email", "test@example.test")
    _git(repo, "config", "user.name", "Test")
    _commit(repo, {"widget.py": "VALUE = 1\n"}, "initial")
    _git(repo, "push", "origin", "main", "--quiet")
    return repo


def _squash(repo: Path, branch: str, message: str) -> str:
    _git(repo, "checkout", "--quiet", "main")
    _git(repo, "merge", "--squash", "--quiet", branch)
    sha = _commit(repo, {}, message)
    _git(repo, "branch", "-D", branch, "--quiet")
    _git(repo, "push", "origin", "main", "--quiet")
    return sha


def _history(checkout: Path) -> dict[str, str]:
    """The shared defect history. Returns the commit shas the tests wire into fakes."""
    shas: dict[str, str] = {}
    _git(checkout, "checkout", "--quiet", "-b", "pr100")
    _commit(checkout, {"merge.py": "A = 1\nB = 1\n"}, "add merge base")
    shas["s100"] = _squash(checkout, "pr100", "add merge base (#100)")
    _git(checkout, "checkout", "--quiet", "-b", "pr101")
    _commit(checkout, {"widget.py": "VALUE = 3\n"}, "add widget feature")
    shas["h101"] = _git(checkout, "rev-parse", "HEAD")
    shas["s101"] = _squash(checkout, "pr101", "add widget (#101)")
    _git(checkout, "checkout", "--quiet", "-b", "pr102")
    _commit(checkout, {"gadget.py": "X = 1\nY = 1\n"}, "add gadget")
    shas["h102"] = _git(checkout, "rev-parse", "HEAD")
    shas["s102"] = _squash(checkout, "pr102", "add gadget (#102)")
    shas["direct"] = _commit(checkout, {"direct.py": "Y = 1\n"}, "hotfix something live")
    _git(checkout, "push", "origin", "main", "--quiet")
    _git(checkout, "checkout", "--quiet", "-b", "pr202")
    _commit(checkout, {"widget.py": "VALUE = 30\n"}, "fix widget")
    shas["h202"] = _git(checkout, "rev-parse", "HEAD")
    shas["s202"] = _squash(checkout, "pr202", "fix widget (#202)")
    _git(checkout, "revert", "--no-commit", "--quiet", shas["s202"])
    shas["v209"] = _commit(checkout, {}, 'Revert "fix widget (#202)"')
    _git(checkout, "push", "origin", "main", "--quiet")
    _git(checkout, "checkout", "--quiet", "-b", "pr203")
    _commit(checkout, {"widget.py": "VALUE = 31\n", "gadget.py": "X = 11\nY = 1\n"},
            "fix both")
    shas["s203"] = _squash(checkout, "pr203", "fix both (#203)")
    _git(checkout, "checkout", "--quiet", "-b", "pr204")
    _commit(checkout, {"newfile.py": "FRESH = True\n"}, "add missing file")
    shas["s204"] = _squash(checkout, "pr204", "add missing file (#204)")
    _git(checkout, "checkout", "--quiet", "-b", "pr205")
    _commit(checkout, {"direct.py": "Y = 2\n"}, "fix direct")
    shas["s205"] = _squash(checkout, "pr205", "fix direct (#205)")
    shas["r210"] = _commit(checkout, {"gadget.py": "X = 11\nY = 2\n"}, "fix gadget rebase")
    _git(checkout, "push", "origin", "main", "--quiet")
    _git(checkout, "checkout", "--quiet", "-b", "pr206")
    _commit(checkout, {"merge.py": "A = 2\nB = 1\n"}, "tune A")
    shas["t206a"] = _git(checkout, "rev-parse", "HEAD")
    _commit(checkout, {"merge.py": "A = 2\nB = 2\n"}, "tune B")
    shas["t206b"] = _git(checkout, "rev-parse", "HEAD")
    _git(checkout, "checkout", "--quiet", "main")
    _git(checkout, "merge", "--no-ff", "--no-commit", "--quiet", "pr206")
    shas["m206"] = _commit(checkout, {}, "Merge pull request #206 from o/pr206")
    _git(checkout, "branch", "-D", "pr206", "--quiet")
    _git(checkout, "push", "origin", "main", "--quiet")
    _git(checkout, "checkout", "--quiet", "-b", "pr207")
    _commit(checkout, {"merge.py": "A = 3\nB = 2\n"}, "tune A again")
    shas["t207a"] = _git(checkout, "rev-parse", "HEAD")
    _commit(checkout, {"widget.py": "VALUE = 32\n"}, "tune widget")
    shas["t207b"] = _git(checkout, "rev-parse", "HEAD")
    _git(checkout, "checkout", "--quiet", "main")
    _git(checkout, "merge", "--no-ff", "--no-commit", "--quiet", "pr207")
    shas["m207"] = _commit(checkout, {}, "Merge pull request #207 from o/pr207")
    _git(checkout, "branch", "-D", "pr207", "--quiet")
    _git(checkout, "push", "origin", "main", "--quiet")
    _git(checkout, "checkout", "--quiet", "-b", "pr208")
    _commit(checkout, {"merge.py": "A = 4\nB = 2\n"}, "tune A once more")
    shas["t208a"] = _git(checkout, "rev-parse", "HEAD")
    _commit(checkout, {"newfile2.py": "EXTRA = True\n"}, "add extra file")
    shas["t208b"] = _git(checkout, "rev-parse", "HEAD")
    _git(checkout, "checkout", "--quiet", "main")
    _git(checkout, "merge", "--no-ff", "--no-commit", "--quiet", "pr208")
    shas["m208"] = _commit(checkout, {}, "Merge pull request #208 from o/pr208")
    _git(checkout, "branch", "-D", "pr208", "--quiet")
    _git(checkout, "push", "origin", "main", "--quiet")
    _git(checkout, "checkout", "--quiet", "-b", "pr212")
    _commit(checkout, {"only1.py": "ONE = 1\n"}, "add only file one")
    _commit(checkout, {"only2.py": "TWO = 2\n"}, "add only file two")
    _git(checkout, "checkout", "--quiet", "main")
    _git(checkout, "merge", "--no-ff", "--no-commit", "--quiet", "pr212")
    shas["m212"] = _commit(checkout, {}, "Merge pull request #212 from o/pr212")
    _git(checkout, "branch", "-D", "pr212", "--quiet")
    _git(checkout, "push", "origin", "main", "--quiet")
    return shas


# ---------------------------------------------------------------------------
# Fake GitHub, Langfuse and run records
# ---------------------------------------------------------------------------


def _result(code: int, stdout: str) -> SimpleNamespace:
    return SimpleNamespace(returncode=code, stdout=stdout, stderr="")


class _Gh:
    """Routes `gh` argv to scripted (code, stdout) pairs. Anything unrouted fails the test."""

    def __init__(self) -> None:
        self.routes: list[Any] = []
        self.calls: list[dict[str, Any]] = []

    def when(self, predicate: Any, code: int, stdout: str) -> _Gh:
        self.routes.append((predicate, (code, stdout)))
        return self

    def __call__(self, argv: list[str], *, cwd: Any = None, env: Any = None,
                 timeout: int = 60) -> SimpleNamespace:
        self.calls.append({"argv": list(argv), "env": dict(env or {})})
        for predicate, (code, stdout) in self.routes:
            if predicate(argv):
                if callable(stdout):
                    stdout = stdout(argv)
                return _result(code, stdout)
        raise AssertionError(f"unexpected gh call: {argv}")


def _closed_defects(*numbers: int, updated: str = "2026-10-08T11:00:00Z") -> str:
    return json.dumps([{"number": number, "updated_at": updated, "closed_at": updated}
                       for number in numbers])


def _closed_by(*numbers: int) -> str:
    return json.dumps({"closedByPullRequestsReferences":
                       [{"number": number} for number in numbers]})


def _is_defect_list(argv: list[str], repo: str = "o/r") -> bool:
    return (len(argv) > 2 and argv[1] == "api"
            and argv[2].startswith(f"repos/{repo}/issues?"))


def _defect_page_number(argv: list[str]) -> int:
    match = re.search(r"[?&]page=(\d+)", argv[2])
    return int(match.group(1)) if match else 1


def _is_issue_view(argv: list[str], number: int) -> bool:
    return argv[1:4] == ["issue", "view", str(number)]


def _is_pr_view(argv: list[str], number: int, fields: str) -> bool:
    return (argv[1:4] == ["pr", "view", str(number)]
            and "--json" in argv and argv[argv.index("--json") + 1] == fields)


def _is_pr_search(argv: list[str], sha: str) -> bool:
    return argv[1:3] == ["pr", "list"] and sha in argv


def _is_comments(argv: list[str], repo: str, pr: int) -> bool:
    return argv[1:3] == ["api", f"repos/{repo}/issues/{pr}/comments"]


def _final_comment(head: str) -> str:
    """A final review comment rendered by C13's own renderer, so a format change fails here."""
    return RS.render_comment({"round": 2, "head": head, "lens_grades": [], "findings": []},
                             [], final=True)


def _comments_body(*bodies: str, login: str = "reviewer") -> str:
    return json.dumps([{"id": 1000 + position, "body": body, "user": {"login": login}}
                       for position, body in enumerate(bodies)])


def _comment_as(comment_id: int, body: str, login: str) -> dict[str, Any]:
    return {"id": comment_id, "body": body, "user": {"login": login}}


class _LfResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def read(self) -> bytes:
        return self.payload

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> _LfResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _LfOpener:
    """Scripts Langfuse list pages per path and captures every POST body."""

    def __init__(self) -> None:
        self.requests: list[Any] = []
        self.trace_pages: list[list[dict[str, Any]]] = []
        self.score_pages: list[list[dict[str, Any]]] = []
        self.posts: list[Any] = []
        self.fail_with: BaseException | None = None
        self.fail_posts_with: BaseException | None = None

    def __call__(self, request: Any, timeout: float | None = None) -> _LfResponse:
        self.requests.append(request)
        if self.fail_with is not None:
            raise self.fail_with
        url = request.full_url
        if request.get_method() == "POST":
            if self.fail_posts_with is not None:
                raise self.fail_posts_with
            self.posts.append(json.loads(request.data.decode()))
            return _LfResponse(b"{}")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        page = int(query.get("page", ["1"])[0])
        if url.startswith(HOST + "/api/public/traces"):
            data = self.trace_pages[page - 1] if page - 1 < len(self.trace_pages) else []
            return _LfResponse(json.dumps({"data": data, "meta": {"page": page}}).encode())
        if url.startswith(HOST + "/api/public/v2/scores"):
            data = self.score_pages[page - 1] if page - 1 < len(self.score_pages) else []
            return _LfResponse(json.dumps({"data": data}).encode())
        raise AssertionError(f"unexpected langfuse url: {url}")


def _transport(opener: _LfOpener) -> dict[str, Any]:
    env = _lf_env()
    return {"getenv": lambda name: env.get(name), "urlopen": opener,
            "resolve": _public_resolve}


def _trace(trace_id: str, *, repo: str, head: str, card: int, round_no: int = 2) -> dict[str, Any]:
    return {"id": trace_id, "timestamp": "2026-10-08T10:00:00Z",
            "metadata": {"repo": repo, "base": "a" * 40, "head": head, "card": card,
                         "round": round_no}}


def _write_record(checkout: Path, card: int, release: dict[str, Any] | None) -> Path:
    store = checkout / ".claude" / "saga" / "runs"
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"issue-{card}.json"
    path.write_text(json.dumps({"issue": card, "repo": "o/r", "release": release,
                                "review_cycles": []}), encoding="utf-8")
    return path


def _write_repos(home: Path, entries: dict[str, Path]) -> None:
    OJ.save_repos(OJ.state_dir(home),
                  {slug: {"checkout": str(path), "added": "2026-10-08T00:00:00Z"}
                   for slug, path in entries.items()})


def _run(home: Path, queue: Path, gh: _Gh, opener: _LfOpener,
         mc: Path | None = None, **overrides: Any) -> tuple[int, str]:
    out = io.StringIO()
    seams: dict[str, Any] = {"git_runner": None, "gh_runner": gh, "clock": lambda: NOW,
                             "out": out, **_transport(opener)}
    seams.update(overrides)
    argv = ["run", "--home", str(home), "--queue", str(queue)]
    if mc is not None:
        argv += ["--mission-control", str(mc)]
    code = OJ.main(argv, **seams)
    return code, out.getvalue()


def _queue_lines(queue: Path) -> list[dict[str, Any]]:
    if not queue.exists():
        return []
    return [json.loads(line) for line in queue.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _release(pr: int, head: str, merge: str, status: str = "merged") -> dict[str, Any]:
    """A release block in the shape the release step stores (see `release_step.py`)."""
    return {"status": status, "repo": "o/r", "pull_request": pr,
            "url": f"https://github.example.test/o/r/pull/{pr}",
            "reviewed_head": head, "landed_commit": merge,
            "merge_method": "squash", "merge_state": "clean",
            "review_run_id": f"trace-for-{pr}", "review_run_reason": None}


def _defect_routes(gh: _Gh, defect: int, closing: int, merge: str, introducer: int,
                   head: str, comment_head: str | None = None, no_marker: bool = False,
                   search: dict[str, str] | None = None, commits: list[str] | None = None,
                   issue_state: str = "MERGED",
                   updated: str = "2026-10-08T11:00:00Z") -> _Gh:
    """Wire the whole read path for one defect: listing, closing PR, and head sources."""
    gh.when(_is_defect_list, 0, _closed_defects(defect, updated=updated))
    gh.when(lambda argv: _is_issue_view(argv, defect), 0, _closed_by(closing))
    base = {"state": issue_state, "mergeCommit": {"oid": merge} if merge else None}
    gh.when(lambda argv: _is_pr_view(argv, closing, "state,mergeCommit"), 0, json.dumps(base))
    if commits is not None:
        gh.when(lambda argv: _is_pr_view(argv, closing, "commits"), 0,
                json.dumps({"commits": [{"oid": oid} for oid in commits]}))
    for sha, digits in (search or {}).items():
        gh.when(lambda argv, sha=sha: _is_pr_search(argv, sha), 0, digits)
    if no_marker:
        comments = _comments_body("a drive-by comment with no review marker")
    else:
        comments = _comments_body(_final_comment(comment_head or head))
    gh.when(lambda argv: _is_comments(argv, "o/r", introducer), 0, comments)
    # The same pass also scans main for reverts; anything it finds here has no marker.
    gh.when(lambda argv: argv[1] == "api" and "/comments" in argv[2], 0, "[]")
    return gh


def _setup_run(tmp_path: Path, checkout: Path, card: int, release: dict[str, Any] | None,
               trace_head: str, trace_id: str) -> tuple[Path, Path, _LfOpener]:
    """A home with one registered repo, one run record, and a one-trace index listing."""
    home = tmp_path / "home"
    queue = home / "queued-candidates.jsonl"
    _write_repos(home, {"o/r": checkout})
    if release is not None:
        _write_record(checkout, card, release)
    opener = _LfOpener()
    opener.trace_pages = [[_trace(trace_id, repo="o/r", head=trace_head, card=card)]]
    opener.score_pages = [[]]
    return home, queue, opener


def test_defect_links_posts_and_queues(tmp_path: Path, checkout: Path) -> None:
    """A defect closed by a merged squash fix is traced, scored, and queued."""
    shas = _history(checkout)
    head = shas["h101"]
    home, queue, opener = _setup_run(tmp_path, checkout, 21,
                                     _release(101, head, shas["s101"]), head, "trace-101")
    gh = _defect_routes(_Gh(), 7, 202, shas["s202"], 101, head)
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    assert "defects_linked=1" in summary
    assert len(opener.posts) == 1
    assert opener.posts[0]["traceId"] == "trace-101"
    assert opener.posts[0]["name"] == "review-miss"
    assert opener.posts[0]["value"] == "found-after-merge"
    assert opener.posts[0]["metadata"]["source"] == "defect issue"
    lines = _queue_lines(queue)
    assert len(lines) == 1
    assert lines[0] == {"source": "defect issue", "repository": "o/r",
                        "review_run_id": "trace-101", "fixing_pr": 202,
                        "fixing_commit": shas["s202"]}
    state = OJ.load_state(OJ.state_dir(home))
    assert "o/r#7" in state["processed_defects"]
    # The same pass scans main, finds the revert of the fix, and has no head for it.
    assert "skipped 1 (no-reviewed-head)" in summary


def test_revert_links_posts_and_queues(tmp_path: Path, checkout: Path) -> None:
    """A lone revert of the fix is traced to the fix's own review as `reverted`."""
    shas = _history(checkout)
    home, queue, opener = _setup_run(tmp_path, checkout, 23,
                                     _release(202, shas["h202"], shas["s202"]),
                                     shas["h202"], "trace-202")
    gh = _Gh()
    gh.when(_is_defect_list, 0, _closed_defects())
    gh.when(lambda argv: _is_comments(argv, "o/r", 202), 0,
            _comments_body(_final_comment(shas["h202"])))
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    assert "reverts_linked=1" in summary
    assert [post["value"] for post in opener.posts] == ["reverted"]
    assert opener.posts[0]["traceId"] == "trace-202"
    lines = _queue_lines(queue)
    assert len(lines) == 1
    assert lines[0] == {"source": "revert", "repository": "o/r",
                        "review_run_id": "trace-202", "fixing_commit": shas["v209"]}
    state = OJ.load_state(OJ.state_dir(home))
    assert f"o/r:{shas['v209']}" in state["processed_reverts"]


def test_defect_merge_fix_links_when_commits_agree(tmp_path: Path, checkout: Path) -> None:
    """A merge-commit fix whose branch rows all blame pull request 100 links to it."""
    shas = _history(checkout)
    head = "b" * 40
    home, queue, opener = _setup_run(tmp_path, checkout, 20,
                                     _release(100, head, shas["s100"]), head, "trace-100")
    gh = _defect_routes(_Gh(), 11, 206, shas["m206"], 100, head)
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    assert "defects_linked=1" in summary
    assert opener.posts[0]["traceId"] == "trace-100"
    lines = _queue_lines(queue)
    assert len(lines) == 1
    # A merge fix queues with the closing pull request number only.
    assert lines[0] == {"source": "defect issue", "repository": "o/r",
                        "review_run_id": "trace-100", "fixing_pr": 206}
    assert "skipped 1 (no-reviewed-head)" in summary  # the revert scan, as in the defect test


def test_defect_merge_fix_links_past_add_only_commit(tmp_path: Path, checkout: Path) -> None:
    """An add-only branch row casts no vote; the tracing rows still link the fix."""
    shas = _history(checkout)
    head = "f" * 40
    home, queue, opener = _setup_run(tmp_path, checkout, 27,
                                     _release(207, head, shas["m207"]), head, "trace-207")
    gh = _defect_routes(_Gh(), 13, 208, shas["m208"], 207, head,
                        search={shas["t207a"]: "207"})
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    assert "defects_linked=1" in summary
    assert opener.posts[0]["traceId"] == "trace-207"
    lines = _queue_lines(queue)
    assert len(lines) == 1
    assert lines[0] == {"source": "defect issue", "repository": "o/r",
                        "review_run_id": "trace-207", "fixing_pr": 208}
    assert "skipped 1 (no-reviewed-head)" in summary  # the revert scan


def test_defect_merge_fix_skips_when_nothing_traced(tmp_path: Path, checkout: Path) -> None:
    """A merge fix whose every commit only adds lines skips as add-only."""
    shas = _history(checkout)
    head = "b" * 40
    home, queue, opener = _setup_run(tmp_path, checkout, 20,
                                     _release(100, head, shas["s100"]), head, "trace-100")
    gh = _defect_routes(_Gh(), 16, 212, shas["m212"], 100, head)
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    assert "skipped 1 (add-only)" in summary
    assert "skipped 1 (no-reviewed-head)" in summary  # the revert scan
    assert opener.posts == []
    assert _queue_lines(queue) == []


def test_defect_rebase_fix_links_when_commits_resolve(tmp_path: Path, checkout: Path) -> None:
    """A plain-tip fix resolves through the pull request's own commits."""
    shas = _history(checkout)
    head = shas["h102"]
    home, queue, opener = _setup_run(tmp_path, checkout, 22,
                                     _release(102, head, shas["s102"]), head, "trace-102")
    gh = _defect_routes(_Gh(), 14, 210, shas["r210"], 102, head,
                        commits=[shas["r210"]])
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    assert "defects_linked=1" in summary
    assert opener.posts[0]["traceId"] == "trace-102"
    assert "skipped 1 (no-reviewed-head)" in summary  # the revert scan


def test_defect_skips_partially_visible_fix(tmp_path: Path, checkout: Path) -> None:
    """A tip whose pull-request commits are not all local is skipped, not guessed."""
    shas = _history(checkout)
    head = shas["h102"]
    home, queue, opener = _setup_run(tmp_path, checkout, 22,
                                     _release(102, head, shas["s102"]), head, "trace-102")
    gh = _defect_routes(_Gh(), 15, 211, shas["r210"], 102, head,
                        commits=[shas["r210"], "d" * 40])
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    assert "skipped 1 (fix-partially-visible)" in summary
    assert "skipped 1 (no-reviewed-head)" in summary  # the revert scan
    assert opener.posts == []
    assert _queue_lines(queue) == []


def test_linking_prefers_record_head_and_cross_checks_comment(
        tmp_path: Path, checkout: Path) -> None:
    """The stored head links; the marker comment cross-checks it, then stands in for it."""
    shas = _history(checkout)
    head = shas["h101"]
    other = "c" * 40

    def attempt(name: str, *, comment_head: str | None = None,
                no_marker: bool = False) -> tuple[int, str, _LfOpener, Path]:
        home = tmp_path / name
        queue = home / "queued-candidates.jsonl"
        _write_repos(home, {"o/r": checkout})
        opener = _LfOpener()
        opener.trace_pages = [[_trace("trace-101", repo="o/r", head=head, card=21)]]
        opener.score_pages = [[]]
        gh = _defect_routes(_Gh(), 7, 202, shas["s202"], 101, head,
                            comment_head=comment_head, no_marker=no_marker)
        return *_run(home, queue, gh, opener), opener, queue

    # Stored and marker heads agree: the defect links.
    _write_record(checkout, 21, _release(101, head, shas["s101"]))
    code, summary, opener, queue = attempt("agree")
    assert code == 0, summary
    assert "defects_linked=1" in summary
    assert opener.posts[0]["traceId"] == "trace-101"
    # No stored run: the marker comment alone never links.
    (checkout / ".claude" / "saga" / "runs" / "issue-21.json").unlink()
    code, summary, opener, queue = attempt("comment-only")
    assert code == 0, summary
    assert "skipped 2 (no-reviewed-head)" in summary
    assert opener.posts == []
    assert _queue_lines(queue) == []
    # No marker: the stored head alone still links.
    _write_record(checkout, 21, _release(101, head, shas["s101"]))
    code, summary, opener, queue = attempt("record-only", no_marker=True)
    assert code == 0, summary
    assert "defects_linked=1" in summary
    # Stored and marker heads disagree: the defect skips rather than misattributes.
    code, summary, opener, queue = attempt("mismatch", comment_head=other)
    assert code == 0, summary
    assert "skipped 1 (head-mismatch)" in summary
    assert opener.posts == []
    assert _queue_lines(queue) == []
    # Two stored runs name the pull request: the defect skips as ambiguous.
    _write_record(checkout, 22, _release(101, head, shas["s101"]))
    code, summary, opener, queue = attempt("ambiguous")
    assert code == 0, summary
    assert "skipped 1 (ambiguous-release)" in summary
    assert opener.posts == []
    assert _queue_lines(queue) == []


def _defect_seven_routes(shas: dict[str, str], comments: str) -> _Gh:
    """Defect 7's full read path with a caller-built comment list on pull request 101."""
    gh = _Gh()
    gh.when(_is_defect_list, 0, _closed_defects(7))
    gh.when(lambda argv: _is_issue_view(argv, 7), 0, _closed_by(202))
    gh.when(lambda argv: _is_pr_view(argv, 202, "state,mergeCommit"), 0,
            json.dumps({"state": "MERGED", "mergeCommit": {"oid": shas["s202"]}}))
    gh.when(lambda argv: _is_comments(argv, "o/r", 101), 0, comments)
    gh.when(lambda argv: argv[1] == "api" and "/comments" in argv[2], 0, "[]")
    return gh


def test_linking_ignores_spoofed_marker_comment(tmp_path: Path, checkout: Path) -> None:
    """A later marker comment from another author is ignored on the head path."""
    shas = _history(checkout)
    head = shas["h101"]
    home, queue, opener = _setup_run(tmp_path, checkout, 21,
                                     _release(101, head, shas["s101"]), head, "trace-101")
    real = _final_comment(head)
    spoof = _final_comment("e" * 40)
    gh = _defect_seven_routes(shas, json.dumps([_comment_as(1000, real, "reviewer"),
                                                _comment_as(1001, spoof, "mallory")]))
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    assert "defects_linked=1" in summary
    assert opener.posts[0]["traceId"] == "trace-101"


def test_linking_prefers_newest_review_account_checklist(tmp_path: Path, checkout: Path) -> None:
    """Among the review account's marker comments, the newest one cross-checks."""
    shas = _history(checkout)
    head = shas["h101"]
    home, queue, opener = _setup_run(tmp_path, checkout, 21,
                                     _release(101, head, shas["s101"]), head, "trace-101")
    stale = _final_comment("e" * 40)
    current = _final_comment(head)
    gh = _defect_seven_routes(shas, json.dumps([_comment_as(1000, stale, "reviewer"),
                                                _comment_as(1001, current, "reviewer")]))
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    assert "defects_linked=1" in summary
    assert opener.posts[0]["traceId"] == "trace-101"


def test_state_save_survives_failed_replace(tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed state write leaves the previous journal byte-identical with no residue."""
    home = tmp_path / "home"
    directory = OJ.state_dir(home)
    state = OJ.default_state()
    state["last_pass"] = "2026-10-08T12:00:00Z"
    OJ.save_state(directory, state)
    before = (directory / "state.json").read_bytes()
    seen: dict[str, str] = {}

    def failing_replace(src: str, dst: str) -> None:
        seen["tmp"] = src
        raise OSError("disk on fire")

    monkeypatch.setattr(os, "replace", failing_replace)
    state["last_pass"] = "2026-10-09T12:00:00Z"
    with pytest.raises(OSError, match="disk on fire"):
        OJ.save_state(directory, state)
    assert (directory / "state.json").read_bytes() == before
    assert (directory / "state.json").stat().st_mode & 0o777 == 0o600
    assert [path.name for path in directory.iterdir()] == ["state.json"]
    assert Path(seen["tmp"]).parent == directory


def test_queue_line_matches_reader_shape(tmp_path: Path) -> None:
    """Validation mirrors K1's reader, and the line is canonical key order."""
    good = {"source": "defect issue", "repository": "o/r", "review_run_id": "trace-101",
            "fixing_pr": 202, "fixing_commit": "a" * 40}
    assert OJ.validate_queue_record(good) is None
    assert OJ.validate_queue_record({**good, "source": "/qa",
                                     "fixing_commit": None}) is None
    assert OJ.validate_queue_record({**good, "source": "revert", "fixing_pr": None}) is None
    assert OJ.validate_queue_record(["not", "an", "object"]) == "record-must-be-an-object"
    assert OJ.validate_queue_record({**good, "source": "defect"}) == "bad-source"
    assert OJ.validate_queue_record({**good, "repository": ""}) == "bad-repository"
    assert OJ.validate_queue_record({**good, "review_run_id": ""}) == "review-run-unnamed"
    assert OJ.validate_queue_record({**good, "fixing_pr": True}) == "bad-fixing-pr"
    assert OJ.validate_queue_record({**good, "fixing_pr": "202"}) == "bad-fixing-pr"
    assert OJ.validate_queue_record({**good, "fixing_commit": 7}) == "bad-fixing-commit"
    assert OJ.validate_queue_record({k: v for k, v in good.items()
                                     if k not in ("fixing_pr", "fixing_commit")}) == "fix-unnamed"
    assert OJ.canonical_queue_line(good) == json.dumps(good, separators=(",", ":"),
                                                            sort_keys=True)
    assert OJ.queue_contains(tmp_path / "missing.jsonl", "whatever") is False


def test_queueing_skips_identical_line(tmp_path: Path) -> None:
    """The second identical append reports `duplicate`, and an invalid record never lands."""
    queue = tmp_path / "queued-candidates.jsonl"
    record = {"source": "revert", "repository": "o/r", "review_run_id": "trace-9",
              "fixing_commit": "b" * 40}
    assert OJ.append_queue_record(queue, record) == "appended"
    assert OJ.append_queue_record(queue, record) == "duplicate"
    assert len(queue.read_text(encoding="utf-8").splitlines()) == 1
    with pytest.raises(OJ.OutcomeJobError):
        OJ.append_queue_record(queue, {"source": "bogus"})
    assert len(queue.read_text(encoding="utf-8").splitlines()) == 1


def test_git_argv_disables_hooks(tmp_path: Path, checkout: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Every git call disables hooks, and no secret-bearing variable reaches any child."""
    monkeypatch.setenv("GIT_EVIL", "1")
    monkeypatch.setenv("SAGA_LANGFUSE_HOST", HOST)
    monkeypatch.setenv("TYPESAFE_API_KEY", "sekrit")
    shas = _history(checkout)
    head = shas["h101"]
    home, queue, opener = _setup_run(tmp_path, checkout, 21,
                                     _release(101, head, shas["s101"]), head, "trace-101")
    gh = _defect_routes(_Gh(), 7, 202, shas["s202"], 101, head)
    seen: list[tuple[list[str], dict[str, str]]] = []

    def recording(argv: Any, **kwargs: Any) -> Any:
        seen.append((list(argv), dict(kwargs.get("env") or {})))
        return OJ.production_runner(argv, **kwargs)

    code, summary = _run(home, queue, gh, opener, git_runner=recording)
    assert code == 0, summary
    assert seen
    for argv, env in seen:
        assert argv[:5] == ["git", "-C", str(checkout), "-c", "core.hooksPath=/dev/null"], argv
        for key in env:
            assert not key.startswith(("GIT_", "SAGA_LANGFUSE_", "LANGFUSE_", "TYPESAFE_")), key
    for call in gh.calls:
        for key in call["env"]:
            assert not key.startswith(("GIT_", "SAGA_LANGFUSE_", "LANGFUSE_", "TYPESAFE_")), key


def test_run_works_from_state_directory(tmp_path: Path, checkout: Path) -> None:
    """The pass runs from the state directory and restores the caller's directory after."""
    shas = _history(checkout)
    head = shas["h101"]
    home, queue, opener = _setup_run(tmp_path, checkout, 21,
                                     _release(101, head, shas["s101"]), head, "trace-101")
    gh = _defect_routes(_Gh(), 7, 202, shas["s202"], 101, head)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.chdir(elsewhere)
    directories: list[str] = []

    def recording(argv: Any, **kwargs: Any) -> Any:
        directories.append(os.getcwd())
        return OJ.production_runner(argv, **kwargs)

    try:
        code, summary = _run(home, queue, gh, opener, git_runner=recording)
    finally:
        os.chdir(REPO_ROOT)
    assert code == 0, summary
    assert directories
    assert set(directories) == {str(OJ.state_dir(home))}
    assert os.getcwd() == str(REPO_ROOT)


def test_linking_blocks_window_on_listing_failure(tmp_path: Path, checkout: Path) -> None:
    """A failed defect listing blocks the window loudly and advances nothing."""
    _history(checkout)
    home = tmp_path / "home"
    queue = home / "queued-candidates.jsonl"
    _write_repos(home, {"o/r": checkout})
    opener = _LfOpener()
    opener.trace_pages = [[_trace("trace-101", repo="o/r", head="a" * 40, card=21)]]
    opener.score_pages = [[]]
    gh = _Gh().when(_is_defect_list, 1, "")
    gh.when(lambda argv: argv[1] == "api" and "/comments" in argv[2], 0, "[]")
    code, summary = _run(home, queue, gh, opener)
    assert code == 1, summary
    assert "failed defects:o/r (defect-list-failed)" in summary
    assert "window-advanced=no" in summary
    state = OJ.load_state(OJ.state_dir(home))
    assert state["last_pass"] is None


def test_linking_blocks_window_on_fetch_failure(tmp_path: Path, checkout: Path,
                                                origin: Path) -> None:
    """A checkout that no longer fetches pins the window, after the healthy repo links."""
    shas = _history(checkout)
    broken = tmp_path / "broken"
    subprocess.run(["git", "clone", str(origin), str(broken)],
                   capture_output=True, text=True, check=True, timeout=60)
    _git(broken, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    head = shas["h101"]
    home = tmp_path / "home"
    queue = home / "queued-candidates.jsonl"
    _write_repos(home, {"o/r": checkout, "o/broken": broken})
    _write_record(checkout, 21, _release(101, head, shas["s101"]))
    opener = _LfOpener()
    opener.trace_pages = [[_trace("trace-101", repo="o/r", head=head, card=21)]]
    opener.score_pages = [[]]
    gh = _defect_routes(_Gh(), 7, 202, shas["s202"], 101, head)
    code, summary = _run(home, queue, gh, opener)
    assert code == 1, summary
    assert "defects_linked=1" in summary
    assert "failed fetch:o/broken (fetch-failed)" in summary
    assert "window-advanced=no" in summary
    state = OJ.load_state(OJ.state_dir(home))
    assert state["last_pass"] is None


def test_linking_completes_when_post_queues(tmp_path: Path, checkout: Path) -> None:
    """A down Langfuse queues the miss locally; the link and the queue entry still land."""
    shas = _history(checkout)
    head = shas["h101"]
    home, queue, opener = _setup_run(tmp_path, checkout, 21,
                                     _release(101, head, shas["s101"]), head, "trace-101")
    opener.fail_posts_with = urllib.error.URLError("langfuse down")
    gh = _defect_routes(_Gh(), 7, 202, shas["s202"], 101, head)
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    assert "defects_linked=1" in summary
    assert "misses_queued_locally=1" in summary
    assert "queued=1" in summary
    assert opener.posts == []
    assert len(_queue_lines(queue)) == 1
    assert len(list((home / ".saga" / "langfuse-queue").glob("*.json"))) == 1


def test_run_refused_while_state_locked(tmp_path: Path) -> None:
    """A second pass refuses with exit 2 while the state lock is held."""
    import fcntl

    home = tmp_path / "home"
    directory = OJ.state_dir(home)
    fd = os.open(directory / "state.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        code = OJ.main(["run", "--home", str(home),
                        "--queue", str(home / "queued-candidates.jsonl")],
                       out=io.StringIO())
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert code == 2


def _qa_score(trace_id: str, revision: str) -> dict[str, Any]:
    return {"id": "score-1", "traceId": trace_id, "name": "review-miss",
            "value": "found-by-qa",
            "comment": f"found-by-qa deterministic at {revision}",
            "metadata": {"strategy": "deterministic", "tested_revision": revision},
            "timestamp": "2026-10-08T10:30:00Z"}


def _qa_record(card: int, revision: str, release: dict[str, Any]) -> dict[str, Any]:
    return {"issue": card, "repo": "o/r", "release": release,
            "qa": {"environment": {"revision": revision}}}


def _waiting(pr: int, head: str) -> dict[str, Any]:
    return {"status": "waiting", "repo": "o/r", "pull_request": pr,
            "url": f"https://github.example.test/o/r/pull/{pr}",
            "reviewed_head": head, "merge_state": "BLOCKED", "reason": "checks pending"}


def test_qa_miss_pending_until_repair_then_queued(tmp_path: Path, checkout: Path) -> None:
    """A `/qa` miss pends until the merged release descends from it, whatever /qa ran since."""
    shas = _history(checkout)
    revision = shas["t206b"]
    home = tmp_path / "home"
    queue = home / "queued-candidates.jsonl"
    _write_repos(home, {"o/r": checkout})
    store = checkout / ".claude" / "saga" / "runs"
    store.mkdir(parents=True, exist_ok=True)
    record_path = store / "issue-26.json"
    record_path.write_text(json.dumps(_qa_record(26, revision, _waiting(206, revision))),
                           encoding="utf-8")

    def attempt(name: str) -> tuple[int, str, _LfOpener]:
        opener = _LfOpener()
        opener.trace_pages = [[_trace("trace-206", repo="o/r", head=revision, card=26)]]
        opener.score_pages = [[_qa_score("trace-206", revision)]]
        gh = _Gh()
        gh.when(_is_defect_list, 0, _closed_defects())
        gh.when(lambda argv: argv[1] == "api" and "/comments" in argv[2], 0, "[]")
        return *_run(tmp_path / name, queue, gh, opener), opener

    # The repair has not landed: the miss pends, silently.
    home1 = tmp_path / "home"
    code, summary, opener = attempt("home")
    assert code == 0, summary
    assert "queued=0" in summary
    assert opener.posts == []
    assert _queue_lines(queue) == []
    state = OJ.load_state(OJ.state_dir(home1))
    assert len(state["pending_qa"]) == 1
    assert state["pending_qa"][0]["trace"] == "trace-206"
    assert state["pending_qa"][0]["revision"] == revision
    # The merge release lands the tested revision, and a follow-up /qa run rewrites the
    # qa block to the release it just tested: the next pass queues the miss anyway.
    record_path.write_text(json.dumps(_qa_record(
        26, shas["m206"], _release(206, revision, shas["m206"]))), encoding="utf-8")
    later = NOW + timedelta(hours=1)
    out = io.StringIO()
    opener2 = _LfOpener()
    opener2.trace_pages = [[_trace("trace-206", repo="o/r", head=revision, card=26)]]
    opener2.score_pages = [[_qa_score("trace-206", revision)]]
    gh2 = _Gh()
    gh2.when(_is_defect_list, 0, _closed_defects())
    gh2.when(lambda argv: argv[1] == "api" and "/comments" in argv[2], 0, "[]")
    code = OJ.main(["run", "--home", str(home1), "--queue", str(queue)],
                   git_runner=None, gh_runner=gh2, clock=lambda: later, out=out,
                   **_transport(opener2))
    summary = out.getvalue()
    assert code == 0, summary
    assert "queued=1" in summary
    lines = _queue_lines(queue)
    assert len(lines) == 1
    assert lines[0] == {"source": "/qa", "repository": "o/r",
                        "review_run_id": "trace-206", "fixing_pr": 206}
    state = OJ.load_state(OJ.state_dir(home1))
    assert state["pending_qa"] == []
    assert f"trace-206:{revision}" in state["queued_qa"]


def _second_pass_gh(defect: int) -> _Gh:
    """The relisting fake: the listing only, so any deeper read fails the test loudly."""
    gh = _Gh()
    gh.when(_is_defect_list, 0, _closed_defects(defect))
    gh.when(lambda argv: argv[1] == "api" and "/comments" in argv[2], 0, "[]")
    return gh


def _second_pass_opener(trace_id: str, head: str, card: int) -> _LfOpener:
    opener = _LfOpener()
    opener.trace_pages = [[_trace(trace_id, repo="o/r", head=head, card=card)]]
    opener.score_pages = [[]]
    return opener


def test_queueing_second_pass_appends_nothing(tmp_path: Path, checkout: Path) -> None:
    """A second pass relists the defect, links nothing new, and leaves the queue byte-identical."""
    shas = _history(checkout)
    head = shas["h101"]
    home, queue, opener = _setup_run(tmp_path, checkout, 21,
                                     _release(101, head, shas["s101"]), head, "trace-101")
    gh = _defect_routes(_Gh(), 7, 202, shas["s202"], 101, head)
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    before = queue.read_bytes()
    assert len(opener.posts) == 1
    opener2 = _second_pass_opener("trace-101", head, 21)
    code, summary = _run(home, queue, _second_pass_gh(7), opener2)
    assert code == 0, summary
    assert "defects_linked=0" in summary
    assert opener2.posts == []
    assert queue.read_bytes() == before
    state = OJ.load_state(OJ.state_dir(home))
    assert state["last_pass"] == "2026-10-08T12:00:00Z"


def test_overlap_window_dedupes_relisted_defect(tmp_path: Path, checkout: Path) -> None:
    """Past the 24 hours, the overlap relists the defect and the processed set dedupes it."""
    shas = _history(checkout)
    head = shas["h101"]
    home, queue, opener = _setup_run(tmp_path, checkout, 21,
                                     _release(101, head, shas["s101"]), head, "trace-101")
    gh = _defect_routes(_Gh(), 7, 202, shas["s202"], 101, head)
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    before = queue.read_bytes()
    later = NOW + timedelta(hours=23)
    out = io.StringIO()
    opener2 = _second_pass_opener("trace-101", head, 21)
    code = OJ.main(["run", "--home", str(home), "--queue", str(queue)],
                   git_runner=None, gh_runner=_second_pass_gh(7), clock=lambda: later,
                   out=out, **_transport(opener2))
    summary = out.getvalue()
    assert code == 0, summary
    assert "defects_linked=0" in summary
    assert opener2.posts == []
    assert queue.read_bytes() == before
    state = OJ.load_state(OJ.state_dir(home))
    assert state["last_pass"] == "2026-10-09T11:00:00Z"


def _api_defects(numbers: list[int], updated: str = "2026-10-08T11:00:00Z") -> str:
    return json.dumps([{"number": number, "updated_at": updated, "closed_at": updated}
                       for number in numbers])


def test_linking_pages_past_two_hundred_defects(tmp_path: Path, checkout: Path) -> None:
    """Two hundred fifty closed defects across three pages all resolve without stalling."""
    shas = _history(checkout)
    head = shas["h101"]
    home, queue, opener = _setup_run(tmp_path, checkout, 21,
                                     _release(101, head, shas["s101"]), head, "trace-101")
    numbers = [7] + [1000 + position for position in range(249)]
    pages = {1: numbers[0:100], 2: numbers[100:200], 3: numbers[200:250]}

    def serve(argv: list[str]) -> str:
        items = json.loads(_api_defects(pages[_defect_page_number(argv)]))
        if _defect_page_number(argv) == 1:
            items.append({"number": 999, "updated_at": "2026-10-08T11:00:00Z",
                          "closed_at": "2026-10-08T11:00:00Z", "pull_request": {}})
        return json.dumps(items)

    gh = _Gh()
    gh.when(_is_defect_list, 0, serve)
    gh.when(lambda argv: _is_issue_view(argv, 7), 0, _closed_by(202))
    gh.when(lambda argv: argv[1:3] == ["issue", "view"], 0, _closed_by())
    gh.when(lambda argv: _is_pr_view(argv, 202, "state,mergeCommit"), 0,
            json.dumps({"state": "MERGED", "mergeCommit": {"oid": shas["s202"]}}))
    gh.when(lambda argv: _is_comments(argv, "o/r", 101), 0,
            _comments_body(_final_comment(head)))
    gh.when(lambda argv: argv[1] == "api" and "/comments" in argv[2], 0, "[]")
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    assert "defects_linked=1" in summary
    assert "skipped 249 (closed-without-pr)" in summary
    fetched = sorted({_defect_page_number(call["argv"]) for call in gh.calls
                       if _is_defect_list(call["argv"])})
    assert fetched == [1, 2, 3]
    assert not any("999" in call["argv"] for call in gh.calls)


def test_linking_stops_paging_before_window(tmp_path: Path, checkout: Path) -> None:
    """Paging stops at the first item older than the window without fetching more."""
    shas = _history(checkout)
    head = shas["h101"]
    home, queue, opener = _setup_run(tmp_path, checkout, 21,
                                     _release(101, head, shas["s101"]), head, "trace-101")
    state = OJ.load_state(OJ.state_dir(home))
    state["last_pass"] = "2026-10-08T12:00:00Z"
    OJ.save_state(OJ.state_dir(home), state)

    def serve(argv: list[str]) -> str:
        assert _defect_page_number(argv) == 1, argv
        return json.dumps([
            {"number": 7, "updated_at": "2026-10-08T11:00:00Z",
             "closed_at": "2026-10-08T11:00:00Z"},
            {"number": 8, "updated_at": "2026-10-01T10:00:00Z",
             "closed_at": "2026-10-01T10:00:00Z"},
        ])

    gh = _Gh()
    gh.when(_is_defect_list, 0, serve)
    gh.when(lambda argv: _is_issue_view(argv, 7), 0, _closed_by(202))
    gh.when(lambda argv: _is_pr_view(argv, 202, "state,mergeCommit"), 0,
            json.dumps({"state": "MERGED", "mergeCommit": {"oid": shas["s202"]}}))
    gh.when(lambda argv: _is_comments(argv, "o/r", 101), 0,
            _comments_body(_final_comment(head)))
    gh.when(lambda argv: argv[1] == "api" and "/comments" in argv[2], 0, "[]")
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    assert "defects_linked=1" in summary
    fetched = [_defect_page_number(call["argv"]) for call in gh.calls
               if _is_defect_list(call["argv"])]
    assert fetched == [1]


def test_linking_blocks_window_on_defect_page_failure(tmp_path: Path, checkout: Path) -> None:
    """A failed second page fails the listing and holds the window."""
    _history(checkout)
    home = tmp_path / "home"
    queue = home / "queued-candidates.jsonl"
    _write_repos(home, {"o/r": checkout})
    opener = _LfOpener()
    opener.trace_pages = [[_trace("trace-101", repo="o/r", head="a" * 40, card=21)]]
    opener.score_pages = [[]]
    gh = _Gh()
    gh.when(lambda argv: _is_defect_list(argv) and _defect_page_number(argv) == 2, 1, "")
    gh.when(lambda argv: _is_defect_list(argv) and _defect_page_number(argv) == 1, 0,
            _api_defects(list(range(1, 101))))
    gh.when(lambda argv: argv[1] == "api" and "/comments" in argv[2], 0, "[]")
    code, summary = _run(home, queue, gh, opener)
    assert code == 1, summary
    assert "failed defects:o/r (defect-list-failed)" in summary
    assert "window-advanced=no" in summary
    state = OJ.load_state(OJ.state_dir(home))
    assert state["last_pass"] is None


def test_unlinked_defect_reasons(tmp_path: Path, checkout: Path) -> None:
    """Every routine attribution outcome skips with its reason and queues nothing."""
    shas = _history(checkout)
    head = shas["h101"]
    other = "e" * 40

    def attempt(home_name: str, defect: int, closing: int, merge: str, introducer: int,
                *, comment_head: str | None = None, no_marker: bool = False,
                search: dict[str, str] | None = None, issue_state: str = "MERGED",
                trace_head: str = head) -> tuple[str, _LfOpener, Path]:
        home = tmp_path / home_name
        queue = home / "queued-candidates.jsonl"
        _write_repos(home, {"o/r": checkout})
        opener = _LfOpener()
        opener.trace_pages = [[_trace("trace-101", repo="o/r", head=trace_head, card=21)]]
        opener.score_pages = [[]]
        gh = _defect_routes(_Gh(), defect, closing, merge, introducer, head,
                            comment_head=comment_head, no_marker=no_marker, search=search,
                            issue_state=issue_state)
        code, summary = _run(home, queue, gh, opener)
        assert code == 0, summary
        assert opener.posts == [], summary
        assert _queue_lines(queue) == [], summary
        return summary, opener, queue

    def check(summary: str, *skips: str) -> None:
        for skip in skips:
            assert f"skipped 1 ({skip})" in summary, summary

    # Closed with no closing pull request at all.
    home = tmp_path / "u-closed-without-pr"
    queue = home / "queued-candidates.jsonl"
    _write_repos(home, {"o/r": checkout})
    opener = _LfOpener()
    opener.trace_pages = [[_trace("trace-101", repo="o/r", head=head, card=21)]]
    opener.score_pages = [[]]
    gh = _Gh()
    gh.when(_is_defect_list, 0, _closed_defects(30))
    gh.when(lambda argv: _is_issue_view(argv, 30), 0, _closed_by())
    gh.when(lambda argv: argv[1] == "api" and "/comments" in argv[2], 0, "[]")
    code, summary = _run(home, queue, gh, opener)
    assert code == 0, summary
    check(summary, "closed-without-pr", "no-reviewed-head")
    # Closed by a pull request that never merged.
    summary, _, _ = attempt("u-unmerged", 31, 299, "", 101, issue_state="OPEN")
    check(summary, "closing-pr-unmerged", "no-reviewed-head")
    # The fix only adds lines, so there is nothing to blame.
    summary, _, _ = attempt("u-add-only", 9, 204, shas["s204"], 101)
    check(summary, "add-only", "no-reviewed-head")
    # The fix touches lines from two pull requests.
    summary, _, _ = attempt("u-spans", 8, 203, shas["s203"], 101)
    check(summary, "spans-pull-requests", "no-reviewed-head")
    # The blamed commit names no pull request anywhere.
    summary, _, _ = attempt("u-pr-unknown", 10, 205, shas["s205"], 101,
                            search={shas["direct"]: ""})
    check(summary, "pr-unknown", "no-reviewed-head")
    # The blamed commit belongs to the closing pull request itself.
    summary, _, _ = attempt("u-in-pr-repair", 10, 205, shas["s205"], 101,
                            search={shas["direct"]: "205"})
    check(summary, "in-pr-repair", "no-reviewed-head")
    # Neither a stored run nor a marker comment names a reviewed head.
    summary, _, _ = attempt("u-no-reviewed-head", 7, 202, shas["s202"], 101,
                            no_marker=True)
    assert "skipped 2 (no-reviewed-head)" in summary, summary
    # The two head sources disagree.
    _write_record(checkout, 21, _release(101, head, shas["s101"]))
    summary, _, _ = attempt("u-head-mismatch", 7, 202, shas["s202"], 101,
                            comment_head=other)
    check(summary, "head-mismatch", "no-reviewed-head")
    # The agreed head matches no indexed trace.
    summary, _, _ = attempt("u-no-matching-trace", 7, 202, shas["s202"], 101,
                            trace_head="d" * 40)
    check(summary, "no-matching-trace", "no-reviewed-head")
    # Two stored runs name the introducing pull request.
    _write_record(checkout, 22, _release(101, head, shas["s101"]))
    summary, _, _ = attempt("u-ambiguous", 7, 202, shas["s202"], 101)
    check(summary, "ambiguous-release", "no-reviewed-head")


# ---------------------------------------------------------------------------
# Filing ticked boxes and posting addressed rates
# ---------------------------------------------------------------------------


FIXTURE_RECORD = (REPO_ROOT / "plugins" / "saga" / "tests" / "fixtures"
                  / "review_state" / "record.json")
FAKE_MC = Path("fake-mc-for-tests")


class _Mc:
    """Mission-control's prepare/create protocol, after C13's fake.

    Success paths write real drafts and sidecars under the given working directory, so the
    stage fill-in and the sidecar re-read execute for real. Every filing's title, body and
    risk is captured for the shape comparison.
    """

    def __init__(self, number: int = 412, refusals: int = 0) -> None:
        self.number = number
        self.calls: list[tuple[list[str], Any]] = []
        self.filings: list[dict[str, str]] = []
        self._refusals = refusals

    def __call__(self, argv: Any, cwd: Any = None) -> SimpleNamespace:
        argv = list(argv)
        self.calls.append((argv, cwd))
        if "prepare" in argv:
            return self._prepare(argv, cwd)
        return self._create(argv, cwd)

    def _prepare(self, argv: list[str], cwd: Any) -> SimpleNamespace:
        title = argv[argv.index("--title") + 1]
        risk = argv[argv.index("--risk") + 1]
        body = (Path(cwd) / "body.md").read_text(encoding="utf-8")
        self.filings.append({"title": title, "body": body, "risk": risk})
        if self._refusals > 0:
            self._refusals -= 1
            return SimpleNamespace(returncode=1, stdout="", stderr="prepare refused: bad source")
        target = Path(cwd) / "docs" / "sdlc-issue-drafts"
        target.mkdir(parents=True, exist_ok=True)
        slug = "".join(c if c.isalnum() else "-" for c in title.lower())[:40]
        draft = target / f"2000-01-01-{slug}.md"
        draft.write_text(
            "---\ntitle: canned\nrepo: r\ntype: defect\nteam: asgard\n"
            "project: operations\nstatus: Discovering\n---\n\n# canned\n",
            encoding="utf-8",
        )
        draft.with_suffix(".json").write_text(
            json.dumps({"state": "blocked", "approval_state": None}), encoding="utf-8")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"draft": str(draft.relative_to(cwd)),
                               "sidecar": str(draft.with_suffix(".json").relative_to(cwd)),
                               "readiness": {"passed": False}}),
            stderr="")

    def _create(self, argv: list[str], cwd: Any) -> SimpleNamespace:
        draft = Path(argv[argv.index("create-prepared") + 1])
        sidecar = draft.with_suffix(".json")
        payload = {"state": "created", "created_issue_number": self.number,
                   "created_issue_url": f"https://example.invalid/i/{self.number}"}
        sidecar.write_text(json.dumps(payload), encoding="utf-8")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"created": True, "number": self.number,
                               "url": payload["created_issue_url"], "mapping_pr_url": None}),
            stderr="")


class _Patch:
    """Comment edits: records each replacement body, then answers `{}`."""

    def __init__(self) -> None:
        self.bodies: list[str] = []
        self.calls: list[list[str]] = []

    def capture(self, argv: list[str]) -> str:
        self.calls.append(list(argv))
        self.bodies.append(argv[argv.index("-f") + 1][len("body="):])
        return "{}"

    @staticmethod
    def is_patch(argv: list[str]) -> bool:
        return (argv[1] == "api" and "/issues/comments/" in argv[2] and "--method" in argv)

    def route(self, gh: _Gh) -> _Gh:
        return gh.when(_Patch.is_patch, 0, self.capture)


def _fixture_run() -> dict[str, Any]:
    """C13's fixture record, newest run only: a known-valid run with fix-later findings."""
    record = json.loads(FIXTURE_RECORD.read_text(encoding="utf-8"))
    runs = [entry for entry in record["review_cycles"] if entry.get("kind") == "review_run"]
    return copy.deepcopy(runs[-1])


def _fix_later_ids(run: Mapping[str, Any]) -> list[str]:
    return [str(finding.get("id")) for finding in run.get("findings") or []
            if isinstance(finding, Mapping) and finding.get("severity") == "fix-later"]


def _set_outcomes(run: dict[str, Any], outcomes: Mapping[str, Any]) -> dict[str, Any]:
    for finding in run.get("findings") or []:
        if finding.get("id") in outcomes:
            finding["merge_outcome"] = outcomes[finding["id"]]
    return run


def _write_review_record(checkout: Path, card: int, run: Mapping[str, Any],
                         release: dict[str, Any] | None) -> Path:
    """C13's fixture record rehomed: the card, the repo, one run and the release move."""
    record = json.loads(FIXTURE_RECORD.read_text(encoding="utf-8"))
    record["issue"] = card
    record["repo"] = "o/r"
    record["release"] = release
    record["review_cycles"] = [dict(run)]
    store = checkout / ".claude" / "saga" / "runs"
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"issue-{card}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _read_findings(checkout: Path, card: int) -> dict[str, Any]:
    store = checkout / ".claude" / "saga" / "runs"
    record = json.loads((store / f"issue-{card}.json").read_text(encoding="utf-8"))
    return {finding["id"]: finding for finding in record["review_cycles"][-1]["findings"]}


def _tick(body: str, finding_id: str) -> str:
    ticked = body.replace(f"- [ ] {finding_id}", f"- [x] {finding_id}", 1)
    assert ticked != body, finding_id
    return ticked


def _render_final(run: Mapping[str, Any]) -> str:
    return RS.render_comment(dict(run), [dict(run)], final=True)


def _filing_setup(tmp_path: Path, checkout: Path, card: int, run: Mapping[str, Any],
                  pr: int, head: str, trace_round: int = 2,
                  ) -> tuple[Path, Path, _LfOpener, str]:
    """A home, queue, one-trace index and the record: filing tests start here."""
    home = tmp_path / "home"
    queue = home / "queued-candidates.jsonl"
    _write_repos(home, {"o/r": checkout})
    _write_review_record(checkout, card, run, _release(pr, head, "0" * 40))
    opener = _LfOpener()
    opener.trace_pages = [[_trace(f"trace-{pr}", repo="o/r", head=head, card=card,
                                  round_no=trace_round)]]
    opener.score_pages = [[]]
    return home, queue, opener, f"trace-{pr}"


def _filing_gh(comment_body: str, pr: int = 101) -> _Gh:
    gh = _Gh()
    gh.when(_is_defect_list, 0, _closed_defects())
    gh.when(lambda argv: _is_comments(argv, "o/r", pr), 0, _comments_body(comment_body))
    gh.when(lambda argv: (argv[1] == "api" and "/comments" in argv[2]
                          and "--method" not in argv), 0, "[]")
    return gh


def _outcome_post(posts: list[Any], name: str) -> dict[str, Any]:
    matching = [post for post in posts if post.get("name") == name]
    assert len(matching) == 1, [post.get("name") for post in posts]
    return matching[0]


HEAD_F = "1" * 40


def _filing_run(head: str = HEAD_F) -> tuple[dict[str, Any], list[str]]:
    run = _fixture_run()
    run["head"] = head
    run["card"] = 21
    run["repo"] = "o/r"
    return run, _fix_later_ids(run)


def test_filing_files_links_and_flips_ticked_box(tmp_path: Path, checkout: Path) -> None:
    """A ticked box with no issue is filed, linked from the comment, and flipped in the record."""
    run, ids = _filing_run()
    target = ids[0]
    _set_outcomes(run, {target: {"outcome": "left"}})
    home, queue, opener, _ = _filing_setup(tmp_path, checkout, 21, run, 101, HEAD_F)
    comment = _tick(_render_final(run), target)
    patch = _Patch()
    gh = patch.route(_filing_gh(comment))
    mc = _Mc()
    code, summary = _run(home, queue, gh, opener, mc=FAKE_MC, mc_runner=mc)
    assert code == 0, summary
    assert "boxes_filed=1" in summary
    assert len(mc.filings) == 1
    assert len(patch.bodies) == 1
    linked = [line for line in patch.bodies[0].splitlines() if target in line]
    assert len(linked) == 1 and linked[0].rstrip().endswith("→ #412")
    findings = _read_findings(checkout, 21)
    assert findings[target]["merge_outcome"] == {"outcome": "filed", "issue": 412}
    assert all(findings[fid].get("merge_outcome") is None for fid in ids[1:])
    assert len(opener.posts) == 1
    post = opener.posts[0]
    assert post["name"] == "merge-outcome" and post["value"] == "filed"
    assert post["traceId"] == RT.review_trace_id(run, "o/r")
    assert post["comment"] == "issue #412"
    assert post["metadata"] == {"issue": 412}
    assert not queue.exists()
    state = OJ.load_state(OJ.state_dir(home))
    assert state["filed"] == {f"o/r#21:{target}": 412}
    assert state["claimed"] == {}


def test_filing_matches_c13_issue_shape(tmp_path: Path, checkout: Path) -> None:
    """The filed title, body and risk equal what C13's filer produces for the same finding."""
    run, ids = _filing_run()
    target = ids[0]
    _set_outcomes(run, {target: {"outcome": "left"}})
    finding = next(f for f in run["findings"] if f["id"] == target)
    home, queue, opener, _ = _filing_setup(tmp_path, checkout, 21, run, 101, HEAD_F)
    patch = _Patch()
    gh = patch.route(_filing_gh(_tick(_render_final(run), target)))
    mc = _Mc()
    code, summary = _run(home, queue, gh, opener, mc=FAKE_MC, mc_runner=mc)
    assert code == 0, summary
    title, body = RS.defect_body([finding], repo="o/r", card=21, revision=HEAD_F)
    risk = RS.RISK_BY_GROUP[RS.consequence_group(finding)]
    assert mc.filings == [{"title": title, "body": body, "risk": risk}]
    prepare = next(call for call, _ in mc.calls if "prepare" in call)
    for flag, value in (("--type", "defect"), ("--team", "asgard"),
                        ("--project", "operations"), ("--status", "Discovering")):
        assert prepare[prepare.index(flag) + 1] == value
    assert any("create-prepared" in call for call, _ in mc.calls)


def test_filing_leaves_others_alone(tmp_path: Path, checkout: Path) -> None:
    """An unticked box, a linked box and filed findings are each left alone."""
    run, ids = _filing_run()
    unticked, linked, filed = ids[0], ids[1], ids[2]
    _set_outcomes(run, {unticked: {"outcome": "left"},
                         linked: {"outcome": "filed", "issue": 400},
                         filed: {"outcome": "filed", "issue": 401}})
    body = _render_final(run)
    ticked_linked = _tick(body, linked)
    lines = [line if linked not in line else f"{line} → #400"
             for line in ticked_linked.splitlines()]
    home, queue, opener, _ = _filing_setup(tmp_path, checkout, 21, run, 101, HEAD_F)
    patch = _Patch()
    gh = patch.route(_filing_gh("\n".join(lines)))
    mc = _Mc()
    code, summary = _run(home, queue, gh, opener, mc=FAKE_MC, mc_runner=mc)
    assert code == 0, summary
    assert "boxes_filed=0" in summary
    assert mc.calls == []
    assert patch.bodies == []
    assert opener.posts == []
    findings = _read_findings(checkout, 21)
    assert findings[unticked]["merge_outcome"] == {"outcome": "left"}
    assert findings[linked]["merge_outcome"] == {"outcome": "filed", "issue": 400}
    assert findings[filed]["merge_outcome"] == {"outcome": "filed", "issue": 401}


def test_filing_second_pass_changes_nothing(tmp_path: Path, checkout: Path) -> None:
    """After a filing, the next pass files nothing even with a stale comment read."""
    run, ids = _filing_run()
    target = ids[0]
    _set_outcomes(run, {target: {"outcome": "left"}})
    home, queue, opener, _ = _filing_setup(tmp_path, checkout, 21, run, 101, HEAD_F)
    comment = _tick(_render_final(run), target)
    patch = _Patch()
    code, summary = _run(home, queue, patch.route(_filing_gh(comment)), opener,
                         mc=FAKE_MC, mc_runner=_Mc())
    assert code == 0, summary
    assert "boxes_filed=1" in summary
    opener2 = _LfOpener()
    opener2.trace_pages = [[_trace("trace-101", repo="o/r", head=HEAD_F, card=21)]]
    opener2.score_pages = [[]]
    patch2 = _Patch()
    mc2 = _Mc()
    code, summary = _run(home, queue, patch2.route(_filing_gh(comment)), opener2,
                         mc=FAKE_MC, mc_runner=mc2)
    assert code == 0, summary
    assert "boxes_filed=0" in summary
    assert mc2.calls == []
    assert patch2.bodies == []
    assert opener2.posts == []


def test_filing_adopts_linked_box_without_refiling(tmp_path: Path, checkout: Path) -> None:
    """A linked box on a still-left finding flips and posts without calling mission-control."""
    run, ids = _filing_run()
    target = ids[0]
    _set_outcomes(run, {target: {"outcome": "left"}})
    lines = [line if target not in line else f"{line} → #415"
             for line in _tick(_render_final(run), target).splitlines()]
    home, queue, opener, _ = _filing_setup(tmp_path, checkout, 21, run, 101, HEAD_F)
    patch = _Patch()
    gh = patch.route(_filing_gh("\n".join(lines)))
    mc = _Mc()
    code, summary = _run(home, queue, gh, opener, mc=FAKE_MC, mc_runner=mc)
    assert code == 0, summary
    assert "boxes_filed=0" in summary
    assert mc.calls == []
    assert patch.bodies == []
    findings = _read_findings(checkout, 21)
    assert findings[target]["merge_outcome"] == {"outcome": "filed", "issue": 415}
    post = _outcome_post(opener.posts, "merge-outcome")
    assert post["value"] == "filed" and post["metadata"] == {"issue": 415}
    state = OJ.load_state(OJ.state_dir(home))
    assert state["filed"] == {f"o/r#21:{target}": 415}


def test_filing_resumes_journalled_finding(tmp_path: Path, checkout: Path) -> None:
    """A crash between filing and flipping resumes from the journal without refiling."""
    run, ids = _filing_run()
    target = ids[0]
    _set_outcomes(run, {target: {"outcome": "left"}})
    home, queue, opener, _ = _filing_setup(tmp_path, checkout, 21, run, 101, HEAD_F)
    state = OJ.default_state()
    state["filed"] = {f"o/r#21:{target}": 412}
    OJ.save_state(OJ.state_dir(home), state)
    patch = _Patch()
    gh = patch.route(_filing_gh(_tick(_render_final(run), target)))
    mc = _Mc()
    code, summary = _run(home, queue, gh, opener, mc=FAKE_MC, mc_runner=mc)
    assert code == 0, summary
    assert "boxes_filed=0" in summary
    assert mc.calls == []
    assert len(patch.bodies) == 1
    linked = [line for line in patch.bodies[0].splitlines() if target in line]
    assert linked[0].rstrip().endswith("→ #412")
    findings = _read_findings(checkout, 21)
    assert findings[target]["merge_outcome"] == {"outcome": "filed", "issue": 412}
    post = _outcome_post(opener.posts, "merge-outcome")
    assert post["value"] == "filed" and post["metadata"] == {"issue": 412}


def test_filing_ignores_spoofed_marker_comment(tmp_path: Path, checkout: Path) -> None:
    """A spoofed ticked box from another author files nothing."""
    run, ids = _filing_run()
    target = ids[0]
    _set_outcomes(run, {target: {"outcome": "left"}})
    home, queue, opener, _ = _filing_setup(tmp_path, checkout, 21, run, 101, HEAD_F)
    real = _render_final(run)
    spoof = _tick(_render_final(run), target)
    body = json.dumps([_comment_as(1000, real, "reviewer"),
                       _comment_as(1001, spoof, "mallory")])
    gh = _Gh()
    gh.when(_is_defect_list, 0, _closed_defects())
    gh.when(lambda argv: _is_comments(argv, "o/r", 101), 0, body)
    gh.when(lambda argv: (argv[1] == "api" and "/comments" in argv[2]
                          and "--method" not in argv), 0, "[]")
    mc = _Mc()
    code, summary = _run(home, queue, gh, opener, mc=FAKE_MC, mc_runner=mc)
    assert code == 0, summary
    assert "boxes_filed=0" in summary
    assert mc.calls == []
    findings = _read_findings(checkout, 21)
    assert findings[target]["merge_outcome"] == {"outcome": "left"}


def _is_claim_search(argv: list[str]) -> bool:
    return (argv[1:3] == ["issue", "list"] and "--search" in argv
            and "--label" not in argv)


def test_filing_reconciles_stale_claim(tmp_path: Path, checkout: Path) -> None:
    """A stale claim adopts its issue, refiles on a clean miss, and holds on search failure."""
    run, ids = _filing_run()
    target = ids[0]
    finding = next(f for f in run["findings"] if f["id"] == target)
    title, defect = RS.defect_body([finding], repo="o/r", card=21, revision=HEAD_F)
    comment = _tick(_render_final(run), target)

    def attempt(name: str, search_stdout: str, search_code: int = 0,
                card: int = 21) -> tuple[int, str, _Mc, _Patch, _LfOpener, Path, Path]:
        run_copy = copy.deepcopy(run)
        run_copy["card"] = card
        _set_outcomes(run_copy, {target: {"outcome": "left"}})
        home = tmp_path / name
        queue = home / "queued-candidates.jsonl"
        _write_repos(home, {"o/r": checkout})
        _write_review_record(checkout, card, run_copy, _release(101, HEAD_F, "0" * 40))
        state = OJ.default_state()
        state["claimed"] = {f"o/r#{card}:{target}":
                            {"title": title, "repo": "o/r", "card": card, "finding": target}}
        OJ.save_state(OJ.state_dir(home), state)
        opener = _LfOpener()
        opener.trace_pages = [[_trace("trace-101", repo="o/r", head=HEAD_F, card=card)]]
        opener.score_pages = [[]]
        gh = _filing_gh(comment)
        gh.when(_is_claim_search, search_code, search_stdout)
        patch = _Patch()
        mc = _Mc()
        code, summary = _run(home, queue, patch.route(gh), opener,
                             mc=FAKE_MC, mc_runner=mc)
        return code, summary, mc, patch, opener, home, queue

    # The crashed pass did file: the search hit is adopted, never refiled.
    hit = json.dumps([{"number": 413, "title": title, "body": defect}])
    code, summary, mc, patch, opener, home, _ = attempt("adopt", hit)
    assert code == 0, summary
    assert mc.calls == []
    assert len(patch.bodies) == 1
    adopted = [line for line in patch.bodies[0].splitlines() if target in line]
    assert len(adopted) == 1 and adopted[0].rstrip().endswith("→ #413")
    findings = _read_findings(checkout, 21)
    assert findings[target]["merge_outcome"] == {"outcome": "filed", "issue": 413}
    state = OJ.load_state(OJ.state_dir(home))
    assert state["filed"] == {f"o/r#21:{target}": 413}
    assert state["claimed"] == {}
    # A clean miss means the filing never landed: the finding files fresh.
    code, summary, mc, patch, opener, home, _ = attempt("miss", "[]", card=22)
    assert code == 0, summary
    assert "boxes_filed=1" in summary
    assert len(mc.filings) == 1
    findings = _read_findings(checkout, 22)
    assert findings[target]["merge_outcome"] == {"outcome": "filed", "issue": 412}
    state = OJ.load_state(OJ.state_dir(home))
    assert state["filed"] == {f"o/r#22:{target}": 412}
    assert state["claimed"] == {}
    # A failed search holds the finding for the pass and keeps the claim.
    code, summary, mc, patch, opener, home, _ = attempt("held", "", search_code=1, card=23)
    assert code == 0, summary
    assert "skipped 1 (claim-search-failed)" in summary
    assert mc.calls == []
    assert patch.bodies == []
    findings = _read_findings(checkout, 23)
    assert findings[target]["merge_outcome"] == {"outcome": "left"}
    state = OJ.load_state(OJ.state_dir(home))
    assert state["filed"] == {}
    assert list(state["claimed"]) == [f"o/r#23:{target}"]


def test_filing_refusal_records_nothing(tmp_path: Path, checkout: Path) -> None:
    """A refused filing records nothing, the next box still files, and the run exits 1."""
    run, ids = _filing_run()
    refused, filed = ids[0], ids[1]
    _set_outcomes(run, {refused: {"outcome": "left"}, filed: {"outcome": "left"}})
    comment = _tick(_tick(_render_final(run), refused), filed)
    home, queue, opener, _ = _filing_setup(tmp_path, checkout, 21, run, 101, HEAD_F)
    patch = _Patch()
    gh = patch.route(_filing_gh(comment))
    mc = _Mc(refusals=1)
    code, summary = _run(home, queue, gh, opener, mc=FAKE_MC, mc_runner=mc)
    assert code == 1, summary
    assert f"failed filing:o/r#21:{refused} (mission-control prepare refused" in summary
    assert "boxes_filed=1" in summary
    findings = _read_findings(checkout, 21)
    assert findings[refused]["merge_outcome"] == {"outcome": "left"}
    assert findings[filed]["merge_outcome"] == {"outcome": "filed", "issue": 412}
    assert len(patch.bodies) == 1
    refused_lines = [line for line in patch.bodies[0].splitlines() if refused in line]
    filed_lines = [line for line in patch.bodies[0].splitlines() if filed in line]
    assert "→ #" not in refused_lines[0]
    assert filed_lines[0].rstrip().endswith("→ #412")
    state = OJ.load_state(OJ.state_dir(home))
    assert state["filed"] == {f"o/r#21:{filed}": 412}
    assert state["claimed"] == {}


def _addressed_run(card: int, outcomes: Mapping[str, Any]) -> dict[str, Any]:
    run = _fixture_run()
    run["head"] = HEAD_F
    run["card"] = card
    run["repo"] = "o/r"
    return _set_outcomes(run, outcomes)


def test_addressed_rate_posted_once(tmp_path: Path, checkout: Path) -> None:
    """A completed run gets one rate; an incomplete run and an empty run get none."""
    complete_run = _fixture_run()
    complete_run["head"] = HEAD_F
    complete_run["card"] = 21
    complete_run["repo"] = "o/r"
    fix_later = _fix_later_ids(complete_run)
    blocks = [str(f["id"]) for f in complete_run["findings"]
              if f.get("severity") == "blocks"]
    _set_outcomes(complete_run, {
        fix_later[0]: {"outcome": "fixed"},
        fix_later[1]: {"outcome": "fixed-now"},
        fix_later[2]: {"outcome": "filed", "issue": 400},
        fix_later[3]: {"outcome": "dismissed", "reason": "not worth it"},
        fix_later[4]: {"outcome": "left"},
        blocks[0]: {"outcome": "fixed"},
        blocks[1]: {"outcome": "left"},
    })
    incomplete_run = _addressed_run(22, {fix_later[0]: {"outcome": "fixed"}})
    empty_run = _addressed_run(23, {})
    empty_run["findings"] = []
    home = tmp_path / "home"
    queue = home / "queued-candidates.jsonl"
    _write_repos(home, {"o/r": checkout})
    _write_review_record(checkout, 21, complete_run, _release(101, HEAD_F, "0" * 40))
    _write_review_record(checkout, 22, incomplete_run, _release(102, HEAD_F, "0" * 40))
    _write_review_record(checkout, 23, empty_run, _release(103, HEAD_F, "0" * 40))
    opener = _LfOpener()
    opener.trace_pages = [[
        _trace("trace-101", repo="o/r", head=HEAD_F, card=21, round_no=3),
        _trace("trace-102", repo="o/r", head=HEAD_F, card=22, round_no=3),
        _trace("trace-103", repo="o/r", head=HEAD_F, card=23, round_no=3),
    ]]
    opener.score_pages = [[]]
    gh = _Gh()
    gh.when(_is_defect_list, 0, _closed_defects())
    gh.when(lambda argv: _is_comments(argv, "o/r", 101), 0,
            _comments_body(_render_final(complete_run)))
    gh.when(lambda argv: _is_comments(argv, "o/r", 102), 0,
            _comments_body(_render_final(incomplete_run)))
    gh.when(lambda argv: (argv[1] == "api" and "/comments" in argv[2]
                          and "--method" not in argv), 0, "[]")
    code, summary = _run(home, queue, gh, opener, mc=FAKE_MC, mc_runner=_Mc())
    assert code == 0, summary
    assert "addressed_rates_posted=1" in summary
    assert "boxes_filed=0" in summary
    post = _outcome_post(opener.posts, "addressed-rate")
    assert post["traceId"] == "trace-101"
    assert post["dataType"] == "NUMERIC"
    assert post["value"] == 0.5714
    assert post["metadata"] == {"dismissed": 1, "filed": 1, "fixed": 2, "fixed-now": 1,
                                "left": 2, "total": 7}
    state = OJ.load_state(OJ.state_dir(home))
    assert state["addressed_posted"] == {"trace-101"}
    opener2 = _LfOpener()
    opener2.trace_pages = [[
        _trace("trace-101", repo="o/r", head=HEAD_F, card=21, round_no=3),
        _trace("trace-102", repo="o/r", head=HEAD_F, card=22, round_no=3),
        _trace("trace-103", repo="o/r", head=HEAD_F, card=23, round_no=3),
    ]]
    opener2.score_pages = [[]]
    gh2 = _Gh()
    gh2.when(_is_defect_list, 0, _closed_defects())
    gh2.when(lambda argv: argv[1] == "api" and "/comments" in argv[2]
             and "--method" not in argv, 0, _comments_body("no marker here"))
    code, summary = _run(home, queue, gh2, opener2, mc=FAKE_MC, mc_runner=_Mc())
    assert code == 0, summary
    assert opener2.posts == []


def test_addressed_rate_reposted_after_filing(tmp_path: Path, checkout: Path) -> None:
    """A filing on the newest run reposts its rate under the same identifier."""
    run = _fixture_run()
    run["head"] = HEAD_F
    run["card"] = 21
    run["repo"] = "o/r"
    fix_later = _fix_later_ids(run)
    blocks = [str(f["id"]) for f in run["findings"] if f.get("severity") == "blocks"]
    target = fix_later[4]
    _set_outcomes(run, {
        fix_later[0]: {"outcome": "fixed"},
        fix_later[1]: {"outcome": "fixed"},
        fix_later[2]: {"outcome": "fixed-now"},
        fix_later[3]: {"outcome": "filed", "issue": 400},
        target: {"outcome": "left"},
        blocks[0]: {"outcome": "fixed"},
        blocks[1]: {"outcome": "dismissed", "reason": "not worth it"},
    })
    home, queue, opener, _ = _filing_setup(tmp_path, checkout, 21, run, 101, HEAD_F,
                                           trace_round=3)
    gh = _filing_gh(_render_final(run))
    code, summary = _run(home, queue, gh, opener, mc=FAKE_MC, mc_runner=_Mc())
    assert code == 0, summary
    first = _outcome_post(opener.posts, "addressed-rate")
    assert first["value"] == 0.7143
    opener2 = _LfOpener()
    opener2.trace_pages = [[_trace("trace-101", repo="o/r", head=HEAD_F, card=21, round_no=3)]]
    opener2.score_pages = [[]]
    patch = _Patch()
    gh2 = patch.route(_filing_gh(_tick(_render_final(run), target)))
    later = NOW + timedelta(hours=1)
    out = io.StringIO()
    code = OJ.main(["run", "--home", str(home), "--queue", str(queue),
                    "--mission-control", str(FAKE_MC)],
                   git_runner=None, gh_runner=gh2, clock=lambda: later, out=out,
                   mc_runner=_Mc(), **_transport(opener2))
    summary = out.getvalue()
    assert code == 0, summary
    assert "boxes_filed=1" in summary
    second = _outcome_post(opener2.posts, "addressed-rate")
    assert second["id"] == first["id"]
    assert second["value"] == 0.8571
    assert len(patch.bodies) == 1


def test_addressed_rate_read_by_no_grade() -> None:
    """`addressed-rate` feeds no grade, formula or calibration reader anywhere in saga."""
    scripts = REPO_ROOT / "plugins" / "saga" / "scripts"
    holders = sorted(path.name for path in scripts.glob("*.py")
                     if "addressed-rate" in path.read_text(encoding="utf-8"))
    assert holders == ["outcome_job.py", "review_trace.py"]
    for name in ("review_formula.py", "review_calibration.py", "review_records.py"):
        text = (scripts / name).read_text(encoding="utf-8")
        assert "addressed-rate" not in text and "addressed_rate" not in text, name


# ---------------------------------------------------------------------------
# The schedule, the checkout map and the status line
# ---------------------------------------------------------------------------


def _verb(argv: list[str], **seams: Any) -> tuple[int, str]:
    out = io.StringIO()
    code = OJ.main(argv, out=out, **seams)
    return code, out.getvalue()


def _stub(path: Path) -> Path:
    """An executable stub: enough for `which`, never executed through the fake runner."""
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


class _Ctl:
    """The install runner: `launchctl` unloads and loads, `git` answers or fails."""

    def __init__(self, origin_url: str | None = None) -> None:
        self.origin_url = origin_url
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], *, cwd: Any = None, env: Any = None,
                 timeout: int = 60) -> SimpleNamespace:
        self.calls.append(list(argv))
        if argv[0] == "launchctl":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "get-url" in argv and self.origin_url is not None:
            return SimpleNamespace(returncode=0, stdout=self.origin_url + "\n", stderr="")
        if "rev-parse" in argv and self.origin_url is not None:
            return SimpleNamespace(returncode=0, stdout=str(cwd) + "\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="not here")


def _path_with(monkeypatch: pytest.MonkeyPatch, directory: Path, *tools: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for tool in tools:
        _stub(directory / tool)
    monkeypatch.setenv("PATH", str(directory))
    return directory


def _launchctl_calls(runner: _Ctl) -> list[list[str]]:
    return [call for call in runner.calls if call[0] == "launchctl"]


def test_install_schedule_writes_keyless_plist(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """The plist carries the label, the hour, the fixed body and absolute paths, but no key."""
    monkeypatch.setenv("SAGA_LANGFUSE_PUBLIC_KEY", "sentinel-public-value")
    monkeypatch.setenv("SAGA_LANGFUSE_SECRET_KEY", "sentinel-secret-value")
    home = tmp_path / "home"
    bin_dir = _path_with(monkeypatch, tmp_path / "bin", "launchctl", "keychain-env")
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    runner = _Ctl()
    code, summary = _verb(["install-schedule", "--home", str(home)], runner=runner)
    assert code == 0, summary
    plist = home / "Library" / "LaunchAgents" / "com.infiquetra.saga.outcome-job.plist"
    raw = plist.read_bytes()
    assert b"sentinel-public-value" not in raw
    assert b"sentinel-secret-value" not in raw
    agent = plistlib.loads(raw)
    assert agent["Label"] == "com.infiquetra.saga.outcome-job"
    assert agent["StartCalendarInterval"] == {"Hour": 6, "Minute": 17}
    shell, dash_c, body, dollar_zero, kc, python, script, arg_home = agent["ProgramArguments"]
    assert (shell, dash_c, body) == ("/bin/sh", "-c", OJ.SCHEDULE_BODY)
    assert dollar_zero == "sh"
    assert kc == str((bin_dir / "keychain-env").resolve())
    assert python == str(Path(sys.executable).resolve())
    assert script == str((SCRIPTS / "outcome_job.py").resolve())
    assert arg_home == str(home.resolve())
    for path in (kc, python, script, arg_home, agent["WorkingDirectory"],
                 agent["StandardOutPath"], agent["StandardErrorPath"]):
        assert os.path.isabs(path), path
    state = (home / ".saga" / "outcome-job").resolve()
    assert agent["WorkingDirectory"] == str(state)
    assert agent["StandardOutPath"] == str(state / "launchd-stdout.log")
    assert agent["StandardErrorPath"] == str(state / "launchd-stderr.log")
    domain = f"gui/{os.getuid()}"
    assert _launchctl_calls(runner) == [
        ["launchctl", "bootout", f"{domain}/com.infiquetra.saga.outcome-job"],
        ["launchctl", "bootstrap", domain, str(plist)],
    ]
    assert f"installed {plist}" in summary
    assert "no repository registered (not a git checkout)" in summary


def test_install_schedule_argv_survives_spaces(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixed body evaluates exports and delivers space-containing paths intact."""
    home = tmp_path / "my home"
    _path_with(monkeypatch, tmp_path / "bin", "launchctl", "keychain-env")
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    code, summary = _verb(["install-schedule", "--home", str(home)], runner=_Ctl())
    assert code == 0, summary
    plist = home / "Library" / "LaunchAgents" / "com.infiquetra.saga.outcome-job.plist"
    body = plistlib.loads(plist.read_bytes())["ProgramArguments"][2]
    capture = tmp_path / "captured.txt"
    kc_dir = tmp_path / "my bin"
    kc_dir.mkdir()
    kc_stub = kc_dir / "emit-stub.sh"
    kc_stub.write_text("#!/bin/sh\necho 'export OJ_SPACE_MARKER=\"marked value\"'\n",
                       encoding="utf-8")
    kc_stub.chmod(0o755)
    py_stub = kc_dir / "echo-stub.sh"
    py_stub.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" \"$OJ_SPACE_MARKER\" > {capture}\n",
                       encoding="utf-8")
    py_stub.chmod(0o755)
    script = "/tmp/dir with spaces/outcome_job.py"
    completed = subprocess.run(
        ["/bin/sh", "-c", body, "sh", str(kc_stub), str(py_stub), script,
         str(home.resolve())],
        capture_output=True, text=True, check=False, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert capture.read_text(encoding="utf-8").splitlines() == [
        script, "run", "--home", str(home.resolve()), "marked value"]


def test_install_schedule_is_idempotent(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """Installing twice replaces the plist and reloads the label, with no duplicate."""
    home = tmp_path / "home"
    _path_with(monkeypatch, tmp_path / "bin", "launchctl", "keychain-env")
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    runner = _Ctl()
    code, _ = _verb(["install-schedule", "--home", str(home)], runner=runner)
    assert code == 0
    plist = home / "Library" / "LaunchAgents" / "com.infiquetra.saga.outcome-job.plist"
    first = plist.read_bytes()
    code, _ = _verb(["install-schedule", "--home", str(home)], runner=runner)
    assert code == 0
    assert plist.read_bytes() == first
    domain = f"gui/{os.getuid()}"
    unload = ["launchctl", "bootout", f"{domain}/com.infiquetra.saga.outcome-job"]
    load = ["launchctl", "bootstrap", domain, str(plist)]
    assert _launchctl_calls(runner) == [unload, load, unload, load]


def test_install_schedule_registers_checkout(tmp_path: Path, checkout: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """Installing from a checkout registers it; from a plain directory it notes the skip."""
    _git(checkout, "remote", "set-url", "origin", "https://github.com/o/r.git")
    home = tmp_path / "home"
    _path_with(monkeypatch, tmp_path / "bin", "launchctl", "keychain-env")
    monkeypatch.chdir(checkout)
    runner = _Ctl(origin_url="https://github.com/o/r.git")
    code, summary = _verb(["install-schedule", "--home", str(home)], runner=runner)
    assert code == 0, summary
    assert f"registered o/r at {checkout.resolve()}" in summary
    assert OJ.load_repos(OJ.state_dir(home))["o/r"]["checkout"] == str(checkout.resolve())
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    home2 = tmp_path / "home2"
    runner2 = _Ctl()
    code, summary = _verb(["install-schedule", "--home", str(home2)], runner=runner2)
    assert code == 0, summary
    assert "no repository registered (not a git checkout)" in summary
    assert OJ.load_repos(OJ.state_dir(home2)) == {}


def test_install_schedule_refuses_without_prerequisites(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Without `launchctl` or `keychain-env` the installer names which and writes nothing."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    home = tmp_path / "home"
    code, _ = _verb(["install-schedule", "--home", str(home)], runner=_Ctl())
    assert code == 2
    err = capsys.readouterr().err
    assert "launchctl" in err and "keychain-env" in err
    assert not (home / ".saga").exists()
    only_kc = tmp_path / "only-kc"
    _path_with(monkeypatch, only_kc, "keychain-env")
    home2 = tmp_path / "home2"
    code, _ = _verb(["install-schedule", "--home", str(home2)], runner=_Ctl())
    assert code == 2
    err = capsys.readouterr().err
    assert "launchctl" in err and "keychain-env" not in err
    assert not (home2 / ".saga").exists()
    only_ctl = tmp_path / "only-ctl"
    _path_with(monkeypatch, only_ctl, "launchctl")
    home3 = tmp_path / "home3"
    code, _ = _verb(["install-schedule", "--home", str(home3)], runner=_Ctl())
    assert code == 2
    err = capsys.readouterr().err
    assert "keychain-env" in err and "launchctl" not in err
    assert not (home3 / ".saga").exists()


def test_register_maps_and_updates_checkout(tmp_path: Path, checkout: Path) -> None:
    """`register` maps a checkout to its slug, and updates the mapping after a move."""
    _git(checkout, "remote", "set-url", "origin", "https://github.com/o/r.git")
    home = tmp_path / "home"
    code, summary = _verb(["register", "--home", str(home), "--repo-root", str(checkout)])
    assert code == 0, summary
    assert f"registered o/r at {checkout.resolve()}" in summary
    repos = OJ.load_repos(OJ.state_dir(home))
    assert repos == {"o/r": {"checkout": str(checkout.resolve()), "added": repos["o/r"]["added"]}}
    added = repos["o/r"]["added"]
    assert added
    moved = tmp_path / "moved"
    checkout.rename(moved)
    code, summary = _verb(["register", "--home", str(home), "--repo-root", str(moved)])
    assert code == 0, summary
    assert f"updated o/r at {moved.resolve()}" in summary
    repos = OJ.load_repos(OJ.state_dir(home))
    assert repos["o/r"] == {"checkout": str(moved.resolve()), "added": added}


def test_register_refuses_non_repository(tmp_path: Path, checkout: Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    """A plain directory and a checkout without a GitHub origin each exit 2 with a reason."""
    home = tmp_path / "home"
    plain = tmp_path / "plain"
    plain.mkdir()
    code, _ = _verb(["register", "--home", str(home), "--repo-root", str(plain)])
    assert code == 2
    assert "not a git checkout" in capsys.readouterr().err
    code, _ = _verb(["register", "--home", str(home), "--repo-root", str(checkout)])
    assert code == 2
    assert "no GitHub owner/name origin" in capsys.readouterr().err
    assert OJ.load_repos(OJ.state_dir(home)) == {}


def test_register_removes_mapping(tmp_path: Path, checkout: Path,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    """`register --remove` drops the checkout's mapping so it stops pinning the window."""
    home = tmp_path / "home"
    other = tmp_path / "other"
    other.mkdir()
    OJ.save_repos(OJ.state_dir(home), {
        "o/r": {"checkout": str(checkout.resolve()), "added": "2026-10-08T00:00:00Z"},
        "o/other": {"checkout": str(other.resolve()), "added": "2026-10-08T00:00:00Z"},
    })
    code, summary = _verb(["register", "--home", str(home),
                           "--repo-root", str(checkout), "--remove"])
    assert code == 0, summary
    assert f"removed o/r at {checkout.resolve()}" in summary
    repos = OJ.load_repos(OJ.state_dir(home))
    assert list(repos) == ["o/other"]
    code, _ = _verb(["register", "--home", str(home),
                     "--repo-root", str(checkout), "--remove"])
    assert code == 2
    assert "no registered checkout" in capsys.readouterr().err


def test_job_status_prints_counts(tmp_path: Path) -> None:
    """`status` prints repositories, passes and journals from state, touching nothing."""
    home = tmp_path / "home"
    OJ.save_repos(OJ.state_dir(home), {
        "o/r": {"checkout": "/tmp/repo", "added": "2026-10-08T00:00:00Z"},
        "o/other": {"checkout": "/tmp/other", "added": "2026-10-08T00:00:00Z"},
    })
    state = OJ.default_state()
    state["last_pass"] = "2026-10-08T12:00:00Z"
    state["index"] = {"t1": {}, "t2": {}, "t3": {}}
    state["pending_qa"] = [{"trace": "t1"}]
    state["filed"] = {"a": 1, "b": 2}
    state["addressed_posted"] = ["t1"]
    state["failures"] = {"x": "y"}
    OJ.save_state(OJ.state_dir(home), state)
    code, summary = _verb(["status", "--home", str(home)])
    assert code == 0, summary
    assert "repositories=2" in summary
    assert "last-pass=2026-10-08T12:00:00Z" in summary
    assert "traces=3" in summary
    assert "pending-qa=1" in summary
    assert "filed=2" in summary
    assert "addressed-posted=1" in summary
    assert "failures=1" in summary
    assert "repo o/other at /tmp/other" in summary
    assert "repo o/r at /tmp/repo" in summary
