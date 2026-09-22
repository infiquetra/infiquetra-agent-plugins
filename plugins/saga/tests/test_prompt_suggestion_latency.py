"""Tests for the issue-1038 prompt-suggestion latency harness.

Every test drives the harness with a fake client and reaches no network (plan R11). The
fakes are passed as parameters rather than monkeypatched, because `suggest()` takes its
`ask` and `client` as arguments precisely so a test can do this.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_HERE = Path(__file__).resolve().parent
HARNESS_PATH = _HERE / "support" / "prompt_suggestion_latency.py"
DAEMON_PATH = _HERE / "support" / "prompt_suggestion_daemon.py"
INPUTS = _HERE / "data" / "prompt-suggestion-latency"
SAGA_COMMANDS = _HERE.parent / "com.infiquetra.claude" / "commands"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


harness = _load(HARNESS_PATH, "prompt_suggestion_latency")


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeResult:
    """The shape `typesafe_client.ask` returns, with nothing behind it."""

    def __init__(
        self,
        answers: dict[str, Any] | None = None,
        status: str = "ok",
        usage: dict[str, int] | None = None,
        transport: str = "",
    ) -> None:
        self.answers = answers or {}
        self.status = status
        self.usage = usage or {}
        # The real result carries this; the harness reads it to tell a cached answer from
        # one that cost a request, so the fake must carry it too.
        self.transport = transport

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class FakeClient:
    """Stands in for the fleet-core client module's two reader helpers."""

    @staticmethod
    def answer_value(answer: dict[str, Any]) -> Any:
        kind = answer.get("type")
        if kind == "noul":
            return answer.get("noul")
        if kind == "choice":
            return answer.get("choice")
        return None


class RecordingAsk:
    """Records every call and replays canned results in order."""

    def __init__(self, *results: FakeResult) -> None:
        self._results = list(results)
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, state: Any, questions: dict[str, Any], **kwargs: Any) -> FakeResult:
        self.calls.append((state, questions))
        if not self._results:
            raise AssertionError("the harness asked more questions than the test canned")
        return self._results.pop(0)


def _noul(value: float) -> dict[str, Any]:
    return {"type": "noul", "noul": value}


def _choice(value: str) -> dict[str, Any]:
    return {"type": "choice", "choice": value}


def _wide(command: str, gate: float = 0.9) -> FakeResult:
    return FakeResult(
        {
            "rank": _choice(command),
            "needs_command": _noul(gate),
            "is_substantial": _noul(gate),
            "is_unambiguous": _noul(gate),
        },
        usage={"input_tokens": 100, "output_tokens": 10},
    )


@pytest.fixture
def questions() -> dict[str, Any]:
    loaded: dict[str, Any] = harness.load_questions()
    return loaded


@pytest.fixture
def roster() -> dict[str, str]:
    return {"plan": "make a plan", "work": "build it", "investigate": "find the cause"}


@pytest.fixture
def short_dir() -> Any:
    """A socket-length-safe directory.

    pytest's own `tmp_path` is far longer than the ~104 bytes a Unix domain socket path
    may occupy on this platform, so a test that binds one cannot use it.
    """
    directory = Path(tempfile.mkdtemp(prefix="psl-t-"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# --------------------------------------------------------------------------- #
# U1 — the corpus and question set
# --------------------------------------------------------------------------- #


def test_every_corpus_entry_carries_a_prompt_expectation_and_reason() -> None:
    prompts = harness.load_corpus()
    assert len(prompts) >= 15
    for prompt in prompts:
        assert prompt.id and prompt.text and prompt.expected
        assert prompt.why, f"{prompt.id} has no stated reason"


def test_every_expected_command_is_none_or_an_installed_saga_command() -> None:
    installed = {path.stem for path in SAGA_COMMANDS.glob("*.md")}
    assert installed, "no saga commands found to validate against"
    for prompt in harness.load_corpus():
        if prompt.expected == harness.NO_SUGGESTION:
            continue
        assert prompt.expected in installed, f"{prompt.id} expects an uninstalled command"


def test_the_corpus_holds_enough_negative_cases_to_measure_silence() -> None:
    prompts = harness.load_corpus()
    negatives = [prompt for prompt in prompts if not prompt.wants_command]
    assert len(negatives) >= 3


def test_no_corpus_entry_looks_like_real_operator_text() -> None:
    """A cheap mechanical guard that the corpus really is synthetic (plan R3)."""
    raw = (INPUTS / "corpus.json").read_text(encoding="utf-8")
    for prompt in harness.load_corpus():
        assert "@" not in prompt.text
        assert "/Users/" not in prompt.text
        assert not any(len(word) > 30 for word in prompt.text.split())
    assert "TYPESAFE_API_KEY" not in raw


def test_the_question_file_carries_both_cookbook_thresholds(questions: dict[str, Any]) -> None:
    assert questions["thresholds"]["gate"] == pytest.approx(0.30)
    assert questions["thresholds"]["fits"] == pytest.approx(0.30)


def test_the_roster_reads_the_installed_commands() -> None:
    roster = harness.load_roster(SAGA_COMMANDS)
    assert "plan" in roster and "work" in roster
    assert all(description for description in roster.values())


def test_a_missing_command_directory_is_a_named_failure(tmp_path: Path) -> None:
    with pytest.raises(harness.HarnessError, match="no command directory"):
        harness.load_roster(tmp_path / "absent")


# --------------------------------------------------------------------------- #
# U2 — statistics, rotation, the runner
# --------------------------------------------------------------------------- #


def test_the_percentiles_of_a_known_series_are_the_known_values() -> None:
    values = list(range(1, 51))  # 1..50
    assert harness.percentile(values, 0.50) == 25
    assert harness.percentile(values, 0.95) == 48


def test_a_percentile_is_always_a_value_that_was_measured() -> None:
    """Nearest-rank, so the reported figure is an observation, not an interpolation."""
    values = [10.0, 20.0, 400.0]
    assert harness.percentile(values, 0.95) in values


def test_an_empty_series_is_a_named_failure_not_a_zero() -> None:
    with pytest.raises(harness.HarnessError):
        harness.percentile([], 0.95)


def test_the_summary_reports_the_count_beside_every_percentile() -> None:
    stats = harness.summarize([1.0, 2.0, 3.0])
    assert stats["count"] == 3
    for key in ("p50_ms", "p95_ms", "min_ms", "max_ms"):
        assert stats[key] is not None


def test_the_runner_rotates_through_shapes_rather_than_blocking() -> None:
    order = harness.rotation_order(["a", "b", "c"], 3)
    assert order == ["a", "b", "c", "a", "b", "c", "a", "b", "c"]


def test_the_runner_calls_each_shape_in_rotation() -> None:
    seen: list[str] = []

    def run_one(shape: str, index: int) -> Any:
        seen.append(shape)
        return harness.Trial(shape=shape, elapsed_ms=1.0, ok=True)

    harness.run_interleaved(["a", "b"], 3, run_one)
    assert seen == ["a", "b", "a", "b", "a", "b"]


def test_a_raising_shape_is_recorded_as_a_failed_trial_and_does_not_abort_the_run() -> None:
    def run_one(shape: str, index: int) -> Any:
        if shape == "bad":
            raise ValueError("boom")
        return harness.Trial(shape=shape, elapsed_ms=5.0, ok=True)

    results = harness.run_interleaved(["good", "bad"], 2, run_one)
    assert len(results["good"]) == 2
    assert len(results["bad"]) == 2
    assert all(not trial.ok for trial in results["bad"])
    assert all(trial.note == "ValueError" for trial in results["bad"])


def test_the_within_budget_share_says_which_side_of_the_target_the_run_sits_on() -> None:
    assert harness.share_within([100.0, 200.0, 900.0, 1000.0], 400.0) == 0.5
    assert harness.share_within([100.0, 200.0], 400.0) == 1.0
    assert harness.share_within([900.0], 400.0) == 0.0
    assert harness.share_within([], 400.0) is None


def test_the_measurement_deadline_is_longer_than_the_operator_deadline() -> None:
    """A deadline shorter than a shape's service time measures the deadline, not the shape.

    This is not a style preference: measuring the warm two-request shape against the
    half-second fail-open policy returned the policy as the latency and an empty answer
    that scored as a deliberate silence.
    """
    assert harness.MEASUREMENT_DEADLINE_SECONDS > harness.CLIENT_DEADLINE_SECONDS


def test_a_warm_trial_with_no_answer_is_a_timeout_not_a_silent_success() -> None:
    """The regression that corrupted the first measurement run, pinned.

    An empty answer from a timeout and an empty answer from a suggester that chose to stay
    quiet are the same bytes. Scoring the first as the second put the deadline into the
    latency figures and a timeout into the accuracy figures.
    """
    ok, note = harness.classify_trial("s2", {})
    assert ok is False
    assert "deadline" in note


def test_a_cold_trial_with_no_answer_is_also_a_failure() -> None:
    ok, note = harness.classify_trial("s0", {})
    assert ok is False
    assert note


def test_an_answer_without_a_request_status_is_not_trusted() -> None:
    """A payload carrying no status cannot prove its request succeeded."""
    ok, note = harness.classify_trial("s0", {"command": "plan", "calls": 1})
    assert ok is False
    assert "status" in note


def test_a_failed_request_status_is_a_failed_trial() -> None:
    ok, note = harness.classify_trial("s1", {"command": "none", "statuses": ["ok", "timeout"]})
    assert ok is False
    assert "timeout" in note


def test_the_resident_process_raising_is_a_failed_trial() -> None:
    ok, note = harness.classify_trial("s2", {"error": "ValueError"})
    assert ok is False
    assert "ValueError" in note


def test_a_good_answer_is_a_good_trial() -> None:
    ok, note = harness.classify_trial("s3", {"command": "plan", "statuses": ["ok"]})
    assert ok is True
    assert note == ""


def test_the_floor_needs_no_answer_to_count() -> None:
    """The floor shape prints nothing by design; that is what it measures."""
    ok, note = harness.classify_trial("floor", {})
    assert ok is True
    assert note == ""


def test_the_ready_marker_has_one_definition_shared_by_writer_and_reader() -> None:
    """The daemon must take the marker from the harness, not restate the literal.

    Asserting the two are equal would pass even if the daemon hard-coded its own copy,
    because equal string literals are often the same interned object. Asserting the
    daemon's source contains no literal assignment is what actually pins the property.
    """
    daemon_module = _load(DAEMON_PATH, "prompt_suggestion_daemon_test")
    assert daemon_module.READY_PREFIX is harness.READY_PREFIX
    source = DAEMON_PATH.read_text(encoding="utf-8")
    assert 'READY_PREFIX = "' not in source, (
        "the daemon restates the marker instead of importing it"
    )


def test_a_cold_hook_reports_the_status_of_every_request_it_made(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without a status the caller cannot tell a failed request from an empty answer.

    This is the cold-side counterpart of the warm timeout: both arrive as a suggestion of
    `none`, and only the status distinguishes them.
    """
    import argparse as _argparse

    served = _wide("plan")
    served.status = "error"
    monkeypatch.setattr(harness, "_load_client", lambda: FakeClient())
    monkeypatch.setattr(harness, "load_roster", lambda _dir: {"plan": "make a plan"})
    monkeypatch.setattr(FakeClient, "ask", staticmethod(lambda *a, **k: served), raising=False)

    args = _argparse.Namespace(
        shape="s0", prompt="x", socket="", transport="", commands_dir=str(SAGA_COMMANDS)
    )
    assert harness.cmd_hook(args) == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["statuses"] == ["error"]
    # And the harness must read that status as a failed trial rather than a quiet success.
    ok, _ = harness.classify_trial("s0", payload)
    assert ok is False


def test_a_failed_trial_is_counted_apart_and_never_averaged_into_the_tail() -> None:
    trials = [
        harness.Trial(shape="s0", elapsed_ms=100.0, ok=True),
        harness.Trial(shape="s0", elapsed_ms=9000.0, ok=False, note="timeout"),
    ]
    summary = harness.collect({"s0": trials})
    assert summary["s0"]["count"] == 1
    assert summary["s0"]["failed"] == 1
    assert summary["s0"]["max_ms"] == 100.0


# --------------------------------------------------------------------------- #
# The suggestion logic
# --------------------------------------------------------------------------- #


def test_the_wide_pass_offers_a_no_match_option_so_silence_is_reachable(
    roster: dict[str, str], questions: dict[str, Any]
) -> None:
    _, asked = harness.build_wide_request("do a thing", roster, questions)
    assert harness.NO_SUGGESTION in asked["rank"]["criteria"]


def test_the_wide_pass_sends_the_prompt_and_the_roster_as_state(
    roster: dict[str, str], questions: dict[str, Any]
) -> None:
    state, _ = harness.build_wide_request("do a thing", roster, questions)
    assert state["prompt"] == "do a thing"
    assert set(state["commands"]) == set(roster)


def test_one_request_is_made_when_the_verification_pass_is_skipped(
    roster: dict[str, str], questions: dict[str, Any]
) -> None:
    ask = RecordingAsk(_wide("plan"))
    result = harness.suggest("x", roster, questions, ask, FakeClient(), deep_check=False)
    assert len(ask.calls) == 1
    assert result.calls == 1
    assert result.command == "plan"


def test_two_requests_are_made_in_sequence_when_the_verification_pass_runs(
    roster: dict[str, str], questions: dict[str, Any]
) -> None:
    ask = RecordingAsk(_wide("plan"), FakeResult({"plan": _noul(0.9)}))
    result = harness.suggest("x", roster, questions, ask, FakeClient(), deep_check=True)
    assert len(ask.calls) == 2
    assert result.calls == 2
    assert result.command == "plan"
    # The second request must carry the shortlist, which only the first could produce.
    assert "plan" in ask.calls[1][0]["candidates"]


def test_a_low_gate_score_suggests_nothing_and_never_asks_a_second_question(
    roster: dict[str, str], questions: dict[str, Any]
) -> None:
    ask = RecordingAsk(_wide("plan", gate=0.05))
    result = harness.suggest("x", roster, questions, ask, FakeClient(), deep_check=True)
    assert result.command == harness.NO_SUGGESTION
    assert len(ask.calls) == 1


def test_a_low_fits_score_suggests_nothing_although_the_wide_pass_ranked_one(
    roster: dict[str, str], questions: dict[str, Any]
) -> None:
    ask = RecordingAsk(_wide("plan"), FakeResult({"plan": _noul(0.05)}))
    result = harness.suggest("x", roster, questions, ask, FakeClient(), deep_check=True)
    assert result.command == harness.NO_SUGGESTION


def test_a_no_match_ranking_suggests_nothing(
    roster: dict[str, str], questions: dict[str, Any]
) -> None:
    ask = RecordingAsk(_wide(harness.NO_SUGGESTION))
    result = harness.suggest("x", roster, questions, ask, FakeClient(), deep_check=True)
    assert result.command == harness.NO_SUGGESTION
    assert len(ask.calls) == 1


def test_a_failed_request_suggests_nothing_and_reports_its_status(
    roster: dict[str, str], questions: dict[str, Any]
) -> None:
    ask = RecordingAsk(FakeResult(status="timeout"))
    result = harness.suggest("x", roster, questions, ask, FakeClient(), deep_check=True)
    assert result.command == harness.NO_SUGGESTION
    assert result.statuses == ["timeout"]
    assert not result.ok


def test_a_cached_answer_is_not_counted_against_the_live_call_budget(
    roster: dict[str, str], questions: dict[str, Any]
) -> None:
    """The client reports `cache` as its transport; a cached answer costs nothing."""
    cached = _wide("plan")
    cached.transport = "cache"
    ask = RecordingAsk(cached)
    result = harness.suggest("x", roster, questions, ask, FakeClient(), deep_check=False)
    assert result.calls == 1
    assert result.live_calls == 0


def test_a_network_answer_is_counted_against_the_live_call_budget(
    roster: dict[str, str], questions: dict[str, Any]
) -> None:
    served = _wide("plan")
    served.transport = "sdk"
    ask = RecordingAsk(served)
    result = harness.suggest("x", roster, questions, ask, FakeClient(), deep_check=False)
    assert result.live_calls == 1


def test_usage_accumulates_across_both_requests(
    roster: dict[str, str], questions: dict[str, Any]
) -> None:
    ask = RecordingAsk(
        _wide("plan"),
        FakeResult({"plan": _noul(0.9)}, usage={"input_tokens": 50, "output_tokens": 5}),
    )
    result = harness.suggest("x", roster, questions, ask, FakeClient(), deep_check=True)
    assert result.usage["input_tokens"] == 150
    assert result.usage["output_tokens"] == 15


# --------------------------------------------------------------------------- #
# Accuracy scoring
# --------------------------------------------------------------------------- #


def test_positive_and_negative_accuracy_are_reported_separately() -> None:
    prompts = [
        harness.Prompt(id="a", text="", expected="plan", why="w"),
        harness.Prompt(id="b", text="", expected="work", why="w"),
        harness.Prompt(id="c", text="", expected="none", why="w"),
    ]
    got = {"a": "plan", "b": "investigate", "c": "none"}
    result = harness.scores(prompts, got)
    assert result["positive"] == {"hit": 1, "total": 2, "rate": 0.5, "bar": 0.70}
    assert result["negative"] == {"hit": 1, "total": 1, "rate": 1.0, "bar": 0.80}


def test_a_suggester_that_fires_on_a_negative_case_is_scored_as_a_miss() -> None:
    prompts = [harness.Prompt(id="c", text="", expected="none", why="w")]
    result = harness.scores(prompts, {"c": "plan"})
    assert result["negative"]["hit"] == 0
    assert result["misses"] == [{"id": "c", "expected": "none", "got": "plan"}]


def test_a_prompt_with_no_recorded_answer_counts_as_silence() -> None:
    prompts = [harness.Prompt(id="a", text="", expected="plan", why="w")]
    result = harness.scores(prompts, {})
    assert result["positive"]["hit"] == 0


# --------------------------------------------------------------------------- #
# U4 — the thin client's fail-open contract
# --------------------------------------------------------------------------- #


def test_the_thin_client_returns_nothing_when_no_process_is_listening(tmp_path: Path) -> None:
    assert harness.client_request(str(tmp_path / "absent.sock"), {"shape": "s2"}) is None


def test_the_thin_client_gives_up_on_a_process_that_never_answers(short_dir: Path) -> None:
    """Accepts the connection, then says nothing. The client must not hang."""
    path = short_dir / "silent.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    accepted: list[Any] = []

    def accept_and_stall() -> None:
        connection, _ = server.accept()
        accepted.append(connection)

    thread = threading.Thread(target=accept_and_stall, daemon=True)
    thread.start()
    try:
        assert harness.client_request(str(path), {"shape": "s2"}, deadline=0.2) is None
    finally:
        thread.join(timeout=2)
        for connection in accepted:
            connection.close()
        server.close()


def test_the_thin_client_returns_nothing_on_a_malformed_reply(short_dir: Path) -> None:
    path = short_dir / "garbage.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)

    def answer_garbage() -> None:
        connection, _ = server.accept()
        with connection:
            connection.recv(4096)
            connection.sendall(b"not json at all\n")

    thread = threading.Thread(target=answer_garbage, daemon=True)
    thread.start()
    try:
        assert harness.client_request(str(path), {"shape": "s2"}, deadline=1.0) is None
    finally:
        thread.join(timeout=2)
        server.close()


# --------------------------------------------------------------------------- #
# U4 — the resident process
# --------------------------------------------------------------------------- #


def test_the_resident_process_binds_an_owner_only_socket(short_dir: Path) -> None:
    """The positive half of the credential guard: what a successful bind produces."""
    daemon_module = _load(DAEMON_PATH, "prompt_suggestion_daemon_test")
    instance = object.__new__(daemon_module.Daemon)
    instance.socket_path = short_dir / "owned.sock"
    server = daemon_module.Daemon._bind(instance)
    try:
        assert stat.S_IMODE(instance.socket_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(short_dir.stat().st_mode) == 0o700
    finally:
        server.close()
        instance.socket_path.unlink(missing_ok=True)


def test_the_resident_process_refuses_a_directory_it_cannot_make_owner_only(
    short_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It holds a live credential, so a home it cannot lock down is refused, not used."""
    daemon_module = _load(DAEMON_PATH, "prompt_suggestion_daemon_test")

    def chmod_that_does_nothing(path: Any, mode: int, **kwargs: Any) -> None:
        return None

    wide = short_dir / "wide"
    wide.mkdir()
    wide.chmod(0o755)
    monkeypatch.setattr(daemon_module.os, "chmod", chmod_that_does_nothing)

    instance = object.__new__(daemon_module.Daemon)
    instance.socket_path = wide / "s.sock"
    # Matched on the directory guard's own wording, not the shared phrase "owner-only":
    # the socket guard further down refuses with a message that also contains it, so a
    # loose match passes whether or not the directory is ever checked.
    with pytest.raises(harness.HarnessError, match="refusing to hold a credential"):
        daemon_module.Daemon._bind(instance)


def test_the_resident_process_refuses_a_socket_it_cannot_make_owner_only(
    short_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second half of the guard: the socket's own permissions, checked separately."""
    daemon_module = _load(DAEMON_PATH, "prompt_suggestion_daemon_test")
    real_chmod = daemon_module.os.chmod

    def chmod_the_directory_only(path: Any, mode: int, **kwargs: Any) -> None:
        if Path(path).is_dir():
            real_chmod(path, mode, **kwargs)

    monkeypatch.setattr(daemon_module.os, "chmod", chmod_the_directory_only)
    instance = object.__new__(daemon_module.Daemon)
    instance.socket_path = short_dir / "s.sock"
    with pytest.raises(harness.HarnessError, match="refusing to serve"):
        daemon_module.Daemon._bind(instance)
    instance.socket_path.unlink(missing_ok=True)


def test_a_socket_path_the_platform_cannot_bind_is_refused_with_an_explanation() -> None:
    """The scratch directory this harness writes into is itself over the limit."""
    too_long = Path("/tmp") / ("x" * 200) / "s.sock"
    with pytest.raises(harness.HarnessError, match="Unix domain socket"):
        harness.check_socket_path(too_long)


def test_a_short_socket_path_is_accepted(short_dir: Path) -> None:
    harness.check_socket_path(short_dir / "s.sock")


def test_the_socket_directory_the_harness_makes_is_owner_only() -> None:
    directory = harness.make_socket_dir()
    try:
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_the_harness_stops_the_process_it_started_even_when_a_shape_raises(
    tmp_path: Path,
) -> None:
    """The stop is in a finally, so a mid-run failure still reclaims the process."""
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    handle = harness.DaemonHandle(
        process=process, pid=process.pid, socket_path=tmp_path / "unused.sock"
    )
    try:
        raise RuntimeError("a shape failed mid-run")
    except RuntimeError:
        harness.stop_daemon(handle)
    assert process.poll() is not None


def test_stopping_an_already_dead_process_is_not_an_error(tmp_path: Path) -> None:
    process = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
    process.wait(timeout=10)
    handle = harness.DaemonHandle(
        process=process, pid=process.pid, socket_path=tmp_path / "unused.sock"
    )
    harness.stop_daemon(handle)


# --------------------------------------------------------------------------- #
# U5 — the survival and resolution probes
# --------------------------------------------------------------------------- #


def test_the_survival_probe_reports_failure_when_the_process_identifier_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pids = iter([111, 222, 333])
    monkeypatch.setattr(
        harness,
        "client_request",
        lambda *a, **k: {"pid": next(pids), "uptime_s": 1.0},
    )
    result = harness.survival_probe(tmp_path / "s.sock", "x", invocations=3)
    assert result["survived"] is False
    assert result["distinct_pids"] == [111, 222, 333]


def test_the_survival_probe_passes_when_every_invocation_reaches_one_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uptimes = iter([1.0, 2.0, 3.0])
    monkeypatch.setattr(
        harness,
        "client_request",
        lambda *a, **k: {"pid": 4242, "uptime_s": next(uptimes)},
    )
    result = harness.survival_probe(tmp_path / "s.sock", "x", invocations=3)
    assert result["survived"] is True
    assert result["distinct_pids"] == [4242]
    assert result["uptime_grew"] is True


def test_an_unanswered_invocation_fails_the_survival_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "client_request", lambda *a, **k: None)
    result = harness.survival_probe(tmp_path / "s.sock", "x", invocations=3)
    assert result["survived"] is False
    assert result["answered"] == 0


def test_the_resolution_probe_records_unknown_rather_than_guessing(tmp_path: Path) -> None:
    observed = harness.resolution_probe([tmp_path])
    assert observed[0]["rung"] == "no fleet-core installed in this tree"


# --------------------------------------------------------------------------- #
# The results file must never carry a credential
# --------------------------------------------------------------------------- #


def test_no_results_key_is_named_like_a_secret() -> None:
    """The harness never reads the key; this guards the shape of what it writes."""
    report = {
        "latency": {"s0": {"count": 1}},
        "usage": {"input_tokens": 10},
        "live_calls": 1,
    }
    serialized = json.dumps(report).lower()
    for forbidden in ("api_key", "secret", "token=", "password", "authorization"):
        assert forbidden not in serialized


def test_the_harness_source_never_reads_the_credential() -> None:
    """Only the fleet-core client may read TYPESAFE_API_KEY (plan R2).

    Naming the variable in a docstring is fine and is how the rule gets documented; what
    must not exist is a line that actually reads it out of the environment.
    """
    for path in (HARNESS_PATH, DAEMON_PATH):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "TYPESAFE_API_KEY" not in line:
                continue
            reads_it = "environ" in line or "getenv" in line
            assert not reads_it, f"{path.name}:{number} reads the credential: {line.strip()}"


def test_the_floor_shape_makes_no_request_at_all() -> None:
    """The floor is the cost of having a hook; it must not call anything."""
    import argparse as _argparse

    args = _argparse.Namespace(
        shape="floor", prompt="x", socket="", transport="", commands_dir=str(SAGA_COMMANDS)
    )
    assert harness.cmd_hook(args) == 0
