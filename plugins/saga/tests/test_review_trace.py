"""Review traces in Langfuse: layout, visibility, the local queue, outcomes and the rounds view.

Issue 166, card C15. No test reaches the network: every post goes to an injected opener, and the
module fixture refuses new connections besides. Keys are sentinels that cannot match the
``(sk|pk)-lf-<8 hex>`` shape, and every queue lives under a temporary home.
"""

from __future__ import annotations

import copy
import email.message
import importlib.util
import io
import json
import os
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "review_records" / "valid"

PUBLIC = "pk-lf-SENTINEL-public"
SECRET = "sk-lf-SENTINEL-secret"  # noqa: S105 - a test fixture, not a credential
HOST = "https://langfuse.example.test"
ENV = {"SAGA_LANGFUSE_PUBLIC_KEY": PUBLIC, "SAGA_LANGFUSE_SECRET_KEY": SECRET, "SAGA_LANGFUSE_HOST": HOST}
FAKE_TOKEN = "ghp_" + "Ab1" * 12


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RT = _load("review_trace")
R = RT.review_records
LF = RT.lf


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("review trace tests must make no network call")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def _getenv(values: dict[str, str] | None = None) -> Any:
    values = ENV if values is None else values
    return lambda name: values.get(name)


class _Response:
    def __init__(self, body: bytes = b"{}", status: int = 200) -> None:
        self._body, self.status = body, status

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _Opener:
    def __init__(self, *results: Any) -> None:
        self.results = list(results) or [_Response()]
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float | None = None) -> Any:
        self.requests.append(request)
        result = self.results[0] if len(self.results) == 1 else self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def bodies(self) -> list[Any]:
        return [json.loads(request.data.decode()) for request in self.requests if request.data]

    def text(self) -> str:
        return "\n".join(request.data.decode() for request in self.requests if request.data)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(HOST, code, "error", email.message.Message(), io.BytesIO(b""))


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _repo(tmp: Path, *, base_profile: dict[str, Any] | None, head_profile: dict[str, Any] | None,
          head_file: str | None = None) -> tuple[Path, str, str]:
    repo = tmp / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "trace@example.com")
    _git(repo, "config", "user.name", "trace")
    _git(repo, "remote", "add", "origin", "git@github.com:example/repo.git")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("one\n", encoding="utf-8")
    if base_profile is not None:
        (repo / ".saga-profile.json").write_text(json.dumps(base_profile), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    if head_profile is not None:
        (repo / ".saga-profile.json").write_text(json.dumps(head_profile), encoding="utf-8")
    if head_file is not None:
        (repo / "src" / "app.py").write_text(head_file, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "head")
    return repo, base, _git(repo, "rev-parse", "HEAD")


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _with_id(finding: dict[str, Any]) -> dict[str, Any]:
    finding["id"] = R.finding_identity(finding["lens"], finding["rule"], finding["location"])
    return finding


def _location(start: int, end: int, anchor: str) -> dict[str, Any]:
    return {"scope": "lines", "file": "src/app.py", "lines": {"start": start, "end": end},
            "function": None, "anchor": anchor}


def _run(*, round_: int = 1, findings: list[dict[str, Any]] | None = None,
         base: str = "a" * 40, head: str = "b" * 40) -> dict[str, Any]:
    run = _fixture("review_run")
    run.update({"round": round_, "base": base, "head": head, "repo": "/Users/operator/work/repo",
                "tool_versions": {"ruff": "0.6.0", "gitleaks": "8.18.0"}})
    if findings is not None:
        run["findings"] = findings
    return run


def _layout_findings() -> list[dict[str, Any]]:
    llm = copy.deepcopy(_fixture("finding"))
    llm.update({"location": _location(2, 4, "llm anchor")})
    ruff = copy.deepcopy(_fixture("finding"))
    ruff.update({
        "rule": {"row": "correctness.lint-error", "ref": "ruff:F401"},
        "source": {"kind": "tool", "name": "ruff", "version": "0.6.0"},
        "location": _location(1, 1, "ruff anchor"), "evidence": "tool-result",
        "proof": {"raw_output": "1" * 64}, "consequence": None, "trigger": None,
    })
    secret = copy.deepcopy(_fixture("finding-secret"))
    secret["location"] = _location(3, 3, "generic-api-key src/app.py")
    return [_with_id(llm), _with_id(ruff), _with_id(secret)]


def _result(vendor: str, role: str, seconds: float) -> dict[str, Any]:
    return {
        "vendor": vendor, "model": "example-model-1", "effort": "high", "role": role,
        "prompt_sha256": "a" * 64, "configuration": {"fingerprint": "c" * 64},
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 5,
                  "cache_creation_input_tokens": 7, "cost_usd": 0.25, "seconds": seconds},
    }


def _spans(bodies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [span for body in bodies for resource in body["resourceSpans"]
            for scope in resource["scopeSpans"] for span in scope["spans"]]


def _attrs(span: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for attr in span["attributes"]:
        value = attr["value"]
        out[attr["key"]] = next(iter(value.values()))
    return out


# --- the trace layout --------------------------------------------------------------------------


def test_trace_layout_fixture_run() -> None:
    run = _run(findings=_layout_findings())
    run["where_to_look"] = [copy.deepcopy(run["where_to_look"][0]) for _ in range(3)]
    run["where_to_look"][1]["classifier"]["model"] = "example-classifier-2"
    results = [_result("anthropic", "targeted-reviewer", 4.0), _result("openai", "external-reviewer", 2.5)]
    bodies, scores = RT.build_review_trace(run, results, slug="example/repo", visibility="public",
                                           earlier_runs=[], now_ns=10**18)
    spans = _spans(bodies)
    names = [span["name"] for span in spans]
    assert names.count("review-run") == 1
    assert {"tool:ruff", "tool:gitleaks", "tool:coverage.py", "jev-sweep", "llm:targeted-reviewer",
            "llm:external-reviewer", "formula"} <= set(names)
    assert names.count("finding") == 3
    trace = RT.review_trace_id(run, "example/repo")
    assert {span["traceId"] for span in spans} == {trace}
    root = _attrs(next(span for span in spans if span["name"] == "review-run"))
    assert root["langfuse.trace.metadata.repo"] == "example/repo"
    assert root["langfuse.trace.metadata.base"] == "a" * 40
    assert root["langfuse.trace.metadata.head"] == "b" * 40
    assert root["langfuse.trace.metadata.card"] == "148"
    assert root["langfuse.trace.metadata.round"] == "1"
    assert root["langfuse.trace.metadata.saga_version"] == "1.3.0"
    assert json.loads(root["langfuse.trace.metadata.tool_versions"])["ruff"] == "0.6.0"
    sweep = _attrs(next(span for span in spans if span["name"] == "jev-sweep"))
    assert json.loads(sweep["langfuse.observation.metadata.models"]) == [
        "example-classifier-1", "example-classifier-2"]
    llm = next(span for span in spans if span["name"] == "llm:targeted-reviewer")
    attrs = _attrs(llm)
    assert attrs["langfuse.observation.type"] == "generation"
    assert attrs["langfuse.observation.metadata.vendor"] == "anthropic"
    assert attrs["langfuse.observation.model.name"] == "example-model-1"
    assert attrs["langfuse.observation.metadata.configuration_fingerprint"] == "c" * 64
    assert json.loads(attrs["langfuse.observation.usage_details"]) == {
        "input": 100, "output": 20, "cache_read": 5, "cache_write": 7}
    assert json.loads(attrs["langfuse.observation.cost_details"]) == {"total": 0.25}
    assert int(llm["endTimeUnixNano"]) - int(llm["startTimeUnixNano"]) == 4_000_000_000
    for finding in run["findings"]:
        assert RT.span_id(trace, f"finding:{finding['id']}") in {span["spanId"] for span in spans}
    assert [score["name"] for score in scores] == ["round"]
    assert "/Users/operator" not in json.dumps(bodies)


def test_trace_ids_are_stable() -> None:
    run = _run(findings=_layout_findings())
    first, _ = RT.build_review_trace(run, [], slug="example/repo", visibility=None, earlier_runs=None, now_ns=1)
    second, _ = RT.build_review_trace(run, [], slug="example/repo", visibility=None, earlier_runs=None, now_ns=1)
    assert json.dumps(first) == json.dumps(second)
    assert RT.review_trace_id(_run(round_=2), "example/repo") != RT.review_trace_id(_run(), "example/repo")
    assert len(RT.review_trace_id(run, "x/y")) == 32 and len(RT.span_id("t", "k")) == 16


def test_raw_output_leaves_as_fingerprint() -> None:
    run = _run(findings=_layout_findings())
    run["raw_outputs"] = [
        {"tool": "ruff", "path": "/Users/operator/.saga/review-output/" + "2" * 64, "sha256": "2" * 64},
        {"tool": "ruff", "path": "/Users/operator/x", "sha256": "RAW-TOOL-OUTPUT-SENTINEL"},
    ]
    bodies, _ = RT.build_review_trace(run, [], slug="example/repo", visibility=None, earlier_runs=None)
    text = json.dumps(bodies)
    assert "2" * 64 in text
    assert "RAW-TOOL-OUTPUT-SENTINEL" not in text
    assert "/Users/operator" not in text and "review-output" not in text
    root = _attrs(next(span for span in _spans(bodies) if span["name"] == "review-run"))
    assert root["langfuse.trace.metadata.raw_outputs_withheld"] == "1"
    run["raw_outputs"] = []
    bodies, _ = RT.build_review_trace(run, [], slug="example/repo", visibility=None, earlier_runs=None)
    ruff = _attrs(next(span for span in _spans(bodies) if span["name"] == "tool:ruff"))
    assert json.loads(ruff["langfuse.observation.metadata.raw_outputs"]) == ["1" * 64]


def test_scanner_finding_sends_location_only(tmp_path: Path) -> None:
    head_file = f"line one\nline two\ntoken = \"{FAKE_TOKEN}\"\nline four\nline five\n"
    repo, base, head = _repo(tmp_path, base_profile={"visibility": "public"}, head_profile=None,
                             head_file=head_file)
    run = _run(findings=_layout_findings(), base=base, head=head)
    opener = _Opener()
    RT.post_review_run(run, [], repo=repo, record=None, home=tmp_path / "home",
                       getenv=_getenv(), urlopen=opener)
    text = opener.text()
    assert FAKE_TOKEN not in text
    spans = _spans([body for body in opener.bodies() if "resourceSpans" in body])
    by_id = {_attrs(span).get("langfuse.observation.metadata.finding_id"): _attrs(span)
             for span in spans if span["name"] == "finding"}
    secret_id = run["findings"][2]["id"]
    assert "langfuse.observation.output" not in by_id[secret_id]
    assert json.loads(by_id[secret_id]["langfuse.observation.input"])["location"]["lines"] == {"start": 3, "end": 3}
    llm_excerpt = json.loads(by_id[run["findings"][0]["id"]]["langfuse.observation.output"])["excerpt"]
    assert llm_excerpt.splitlines()[2] == RT.SECRET_WITHHELD
    assert llm_excerpt.splitlines()[0] == "line one"
    assert "example/repo" in text


# --- visibility --------------------------------------------------------------------------------


def test_visibility_from_base_profile(tmp_path: Path) -> None:
    cases = [
        ({"visibility": "public"}, {"visibility": "private"}, "public"),
        ({"visibility": "private"}, {"visibility": "public"}, "private"),
        (None, {"visibility": "public"}, None),
        ({"visibility": "internal"}, None, None),
        ({"schema": "repository_profile.v1"}, None, None),
    ]
    for index, (base_profile, head_profile, expected) in enumerate(cases):
        repo, base, head = _repo(tmp_path / str(index), base_profile=base_profile, head_profile=head_profile)
        assert RT.visibility(repo, base) == expected, (base_profile, head_profile)
    assert RT.visibility(repo, "--output=/tmp/x") is None
    assert RT.visibility(None, "abc") is None


def test_visibility_unrecorded_on_http_queues_naming_x3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, base, head = _repo(tmp_path, base_profile=None, head_profile={"visibility": "public"})
    assert head != base
    home = tmp_path / "home"
    opener = _Opener()
    summary = RT.post_review_run(_run(base=base, head=head), [], repo=repo, record=None, home=home,
                                 getenv=_getenv({**ENV, "SAGA_LANGFUSE_HOST": "http://langfuse.example.test"}),
                                 urlopen=opener)
    assert opener.requests == []
    assert summary["queued"] >= 1 and set(summary["reasons"]) == {"plain-http-private"}
    assert RT.main(["status", "--home", str(home)]) == 0
    assert "X3" in capsys.readouterr().out


# --- the queue ---------------------------------------------------------------------------------


def _items(count: int = 1) -> list[tuple[str, Any, Any]]:
    return [("scores", {"id": f"s{index}", "name": "round", "value": 1, "traceId": "t"}, "private")
            for index in range(count)]


def test_unreachable_queues_owner_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    summary = RT.post(_items(), home=home, getenv=_getenv(),
                      urlopen=_Opener(urllib.error.URLError("down")))
    assert summary["queued"] == 1 and summary["reasons"] == ["unreachable"]
    directory = home / ".saga" / "langfuse-queue"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    [queued] = list(directory.iterdir())
    assert stat.S_IMODE(queued.stat().st_mode) == 0o600
    text = queued.read_text()
    assert json.loads(text)["reason"] == "unreachable"
    for needle in (PUBLIC, SECRET, "langfuse.example.test"):
        assert needle not in text


def test_queue_drains_oldest_first_when_reason_clears(tmp_path: Path) -> None:
    home = tmp_path / "home"
    down = _Opener(urllib.error.URLError("down"))
    for index in range(3):
        RT.post([("scores", {"id": f"old{index}", "name": "n", "value": index}, "private")],
                home=home, getenv=_getenv(), urlopen=down)
    up = _Opener()
    summary = RT.post([("scores", {"id": "new", "name": "n", "value": 9}, "private")],
                      home=home, getenv=_getenv(), urlopen=up)
    assert [body["id"] for body in up.bodies()] == ["old0", "old1", "old2", "new"]
    assert summary["sent"] == 4 and summary["waiting"] == 0
    assert list((home / ".saga" / "langfuse-queue").iterdir()) == []


def test_refusal_clears_when_keys_arrive(tmp_path: Path) -> None:
    home = tmp_path / "home"
    opener = _Opener()
    RT.post(_items(), home=home, getenv=_getenv({"SAGA_LANGFUSE_HOST": HOST}), urlopen=opener)
    assert opener.requests == [] and RT.queue_status(home) == {"waiting": 1, "reasons": {"missing-keys": 1}}
    summary = RT.post([], home=home, getenv=_getenv(), urlopen=opener)
    assert summary["sent"] == 1 and RT.queue_status(home)["waiting"] == 0


def test_rejected_post_is_kept(tmp_path: Path) -> None:
    home = tmp_path / "home"
    items = [("scores", {"id": f"c{code}", "name": "n", "value": 1}, "private") for code in (400, 401, 403)]
    RT.post(items, home=home, getenv=_getenv(),
            urlopen=_Opener(_http_error(400), _http_error(401), _http_error(403)))
    assert RT.queue_status(home) == {
        "waiting": 3, "reasons": {"http-400": 1, "http-401": 1, "http-403": 1}}
    summary = RT.post([], home=home, getenv=_getenv(), urlopen=_Opener())
    assert summary["sent"] == 3 and RT.queue_status(home)["waiting"] == 0


def test_requeue_updates_reason_in_place(tmp_path: Path) -> None:
    home = tmp_path / "home"
    directory = home / ".saga" / "langfuse-queue"
    RT.post(_items(), home=home, getenv=_getenv(), urlopen=_Opener(urllib.error.URLError("down")))
    [queued] = list(directory.iterdir())
    RT.post([], home=home, getenv=_getenv(), urlopen=_Opener(_http_error(400)))
    assert [p.name for p in directory.iterdir()] == [queued.name]
    stored = json.loads(queued.read_text())
    assert stored["reason"] == "http-400" and stored["attempts"] == 2
    assert stat.S_IMODE(queued.stat().st_mode) == 0o600


def test_failed_requeue_keeps_the_post(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    directory = home / ".saga" / "langfuse-queue"
    RT.post(_items(), home=home, getenv=_getenv(), urlopen=_Opener(_http_error(400)))
    [queued] = list(directory.iterdir())
    before = queued.read_text()

    real_open = os.open

    def full_disk(path: Any, *args: Any, **kwargs: Any) -> int:
        if Path(path).parent == directory:
            raise OSError(28, "No space left on device")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", full_disk)
    opener = _Opener(_http_error(400), _Response())
    summary = RT.post([("scores", {"id": "new", "name": "n", "value": 2}, "private")],
                      home=home, getenv=_getenv(), urlopen=opener)
    assert [p.name for p in directory.iterdir()] == [queued.name]
    assert queued.read_text() == before
    assert summary["sent"] == 1 and [body["id"] for body in opener.bodies()] == ["s0", "new"]


def test_stale_claim_is_retaken(tmp_path: Path) -> None:
    home = tmp_path / "home"
    RT.post(_items(2), home=home, getenv=_getenv(), urlopen=_Opener(urllib.error.URLError("down")))
    directory = home / ".saga" / "langfuse-queue"
    first, second = sorted(directory.glob("*.json"))
    stale = first.with_name(first.name + ".claimed.99999")
    fresh = second.with_name(second.name + ".claimed.99998")
    first.rename(stale)
    second.rename(fresh)
    old = time.time() - 11 * 60
    os.utime(stale, (old, old))
    opener = _Opener()
    summary = RT.post([], home=home, getenv=_getenv(), urlopen=opener)
    assert summary["sent"] == 1
    assert [p.name for p in directory.iterdir()] == [fresh.name]
    assert RT.queue_status(home)["waiting"] == 1


def test_client_fault_queues_and_never_raises(tmp_path: Path) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("socket refused by a fixture")

    summary = RT.post(_items(), home=tmp_path / "home", getenv=_getenv(), urlopen=broken)
    assert summary["queued"] == 1 and summary["reasons"] == ["client-error"]


# --- rounds ------------------------------------------------------------------------------------


def _finding_with(anchor: str, severity: str = "fix-later") -> dict[str, Any]:
    finding = copy.deepcopy(_fixture("finding"))
    finding["location"] = _location(1, 1, anchor)
    finding = _with_id(finding)
    finding["severity"] = severity
    return finding


def test_rounds_scores() -> None:
    a, b, c = _finding_with("a"), _finding_with("b"), _finding_with("c", "blocks")
    first = _run(round_=1, findings=[a, b])
    second = _run(round_=2, findings=[b, c])
    _, scores = RT.build_review_trace(second, [], slug="x/y", visibility=None, earlier_runs=[first])
    values = {score["name"]: (score["value"], score["dataType"]) for score in scores}
    assert values == {
        "round": (2, "NUMERIC"),
        "round-2-found-new": (1, "BOOLEAN"),
        "round-new-findings": (1, "NUMERIC"),
        "round-new-blocking": (1, "NUMERIC"),
        "round-cleared": (1, "NUMERIC"),
    }
    quiet = _run(round_=2, findings=[b])
    _, scores = RT.build_review_trace(quiet, [], slug="x/y", visibility=None, earlier_runs=[first])
    assert {s["name"]: s["value"] for s in scores}["round-2-found-new"] == 0


def test_rounds_view_reads_metrics(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    body = {"data": [
        {"name": "round-2-found-new", "avg_value": 0.25, "count_count": 8},
        {"name": "round-3-found-new", "avg_value": 0.0, "count_count": "2"},
    ]}
    opener = _Opener(_Response(json.dumps(body).encode()))
    code = RT.main(["rounds", "--repo", str(tmp_path)], urlopen=opener, getenv=_getenv())
    assert code == 0
    out = capsys.readouterr().out
    assert "round 2 found something new in 25% of 8 runs" in out
    assert "round 3 found something new in 0% of 2 runs" in out
    [request] = opener.requests
    assert request.get_method() == "GET"
    query = json.loads(urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)["query"][0])
    assert query["view"] == "scores-boolean"
    assert "/api/public/v2/metrics" in request.full_url


def test_probe_prints_the_project_and_no_key(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    opener = _Opener(_Response(json.dumps({"data": [{"id": "p1", "name": "Saga Reviews"}]}).encode()))
    assert RT.main(["probe", "--repo", str(tmp_path)], urlopen=opener, getenv=_getenv()) == 0
    out = capsys.readouterr()
    assert out.out.strip() == "Saga Reviews ok"
    for needle in (PUBLIC, SECRET, "langfuse.example.test"):
        assert needle not in out.out + out.err
    other = _Opener(_Response(b'{"data": [{"name": "Tracing"}]}'))
    assert RT.main(["probe", "--repo", str(tmp_path)], urlopen=other, getenv=_getenv()) == 1


def test_no_delete_path() -> None:
    for name in ("review_trace.py", "review_dataset.py"):
        path = SCRIPTS / name
        if path.exists():
            source = path.read_text(encoding="utf-8")
            assert '"DELETE"' not in source and "'DELETE'" not in source
    source = (SCRIPTS / "review_trace.py").read_text(encoding="utf-8")
    assert source.count("claimed.unlink(missing_ok=True)") == 2


# --- outcomes at merge -------------------------------------------------------------------------


def _stored(run: dict[str, Any]) -> dict[str, Any]:
    return {**run, "loop": R.STORED_LOOP}


def test_outcome_attaches_after_line_shift() -> None:
    x1 = _finding_with("x")
    x1["location"]["lines"] = {"start": 10, "end": 12}
    x2 = copy.deepcopy(x1)
    x2["location"]["lines"] = {"start": 14, "end": 16}
    assert x1["id"] == x2["id"]
    x2["merge_outcome"] = {"outcome": "dismissed", "reason": "false positive"}
    y = _finding_with("y")
    y["merge_outcome"] = {"outcome": "filed", "issue": 812}
    z = _finding_with("z")
    record = {"repo": "example/repo", "review_cycles": [
        _stored(_run(round_=1, findings=[x1])),
        _stored(_run(round_=2, findings=[x2, y, z])),
    ]}
    pairs, unrecorded = RT.outcome_scores(record, "example/repo")
    assert unrecorded == 1
    by_value = {score["value"]: score for _, score in pairs}
    round_two = RT.review_trace_id(_run(round_=2), "example/repo")
    dismissed = by_value["dismissed"]
    assert dismissed["traceId"] == round_two
    assert dismissed["observationId"] == RT.span_id(round_two, f"finding:{x1['id']}")
    assert (dismissed["name"], dismissed["dataType"], dismissed["comment"]) == (
        "merge-outcome", "CATEGORICAL", "false positive")
    filed = by_value["filed"]
    assert filed["comment"] == "issue #812" and filed["metadata"] == {"issue": 812}


def test_outcome_score_ids_repeat(tmp_path: Path) -> None:
    y = _finding_with("y")
    y["merge_outcome"] = {"outcome": "left"}
    record = {"repo": "example/repo", "review_cycles": [_stored(_run(findings=[y]))]}
    first = _Opener()
    second = _Opener()
    for opener in (first, second):
        summary = RT.post_outcomes(record, repo=None, home=tmp_path / "home",
                                   getenv=_getenv(), urlopen=opener)
        assert summary["outcomes"] == 1 and summary["sent"] == 1
    assert [b["id"] for b in first.bodies()] == [b["id"] for b in second.bodies()]


# --- the tree --------------------------------------------------------------------------------


def test_no_langfuse_key_in_tree() -> None:
    result = subprocess.run(
        ["git", "grep", "-nE", "(sk|pk)-lf-[0-9a-f]{8}"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1, result.stdout[:500]
