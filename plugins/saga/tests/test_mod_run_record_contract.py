"""The Claude Code mods' run-record reader agrees with ``run_record.py show`` itself.

``com.infiquetra.claude/mods/run-record.ts`` reads saga state only by running
``run_record.py show <issue>`` and parsing what it prints. Its tests under
``claude plugin test`` feed the parser, and the guarded reader
``readRunRecordWith``, hand-written process results; a mod's hook can be driven
there too by stubbing the engine's process runner (``on('process.run', ...)``).
Either way the process result is written by hand, so it could drift from what the script really prints
and exits with. This module closes that gap from the Python side, by running the
real script against a throwaway store and checking each fact the TypeScript
parser keys on: the record version, the no-record message prefix, and the exit
codes. It also ties the failure reasons the parser returns to the state
contract's ``SagaRunReadFailure`` union, and the record's field names to
``TOP_LEVEL_KEYS``, because nothing type-checks the
adapter's TypeScript in continuous integration (DECISIONS.md, 2026-10-04).

Every store here is a ``tmp_path``; nothing touches the primary checkout's
``.claude/saga/`` store.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "plugins" / "saga" / "scripts" / "run_record.py"
RUN_STATUS = REPO_ROOT / "plugins" / "saga" / "scripts" / "run_status.py"
REVIEW_STATE = REPO_ROOT / "plugins" / "saga" / "scripts" / "review_state.py"
SETUP_SCRIPT = REPO_ROOT / "plugins" / "saga" / "scripts" / "saga_setup.py"
READER = REPO_ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "mods" / "run-record.ts"
CONTRACT = REPO_ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "types" / "index.d.ts"
STATE_FIXTURES = REPO_ROOT / "plugins" / "saga" / "tests" / "fixtures" / "review_state"


def _ts_constant(name: str) -> str:
    """The literal a top-level ``const`` in the reader is set to."""
    match = re.search(
        rf"^(?:export )?const {name}(?:: \w+)? = (?:'([^']*)'|(\d+))$",
        READER.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, f"run-record.ts no longer declares {name} as a literal"
    return match.group(1) if match.group(1) is not None else match.group(2)


def _show(store: Path, issue: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--store-root", str(store), "show", str(issue)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


def _write_record(store: Path, issue: int, **fields: object) -> None:
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import run_record  # noqa: PLC0415  (loaded from the script directory on purpose)
    finally:
        sys.path.remove(str(SCRIPT.parent))
    run_record.set_next_step(store, issue, "plan")
    if fields:
        path = run_record.record_path(store, issue)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.update(fields)
        path.write_text(json.dumps(payload), encoding="utf-8")


def test_the_reader_knows_the_version_the_script_writes(store: Path) -> None:
    _write_record(store, 7)
    ran = _show(store, 7)
    assert ran.returncode == 0, ran.stderr
    record = json.loads(ran.stdout)
    assert isinstance(record, dict)
    assert record["schema"] == _ts_constant("KNOWN_SCHEMA")
    assert f"'{record['schema']}'" in CONTRACT.read_text(encoding="utf-8")
    assert record["issue"] == 7
    assert record["next_step"] == "plan"


def test_a_missing_record_exits_with_the_code_and_prefix_the_reader_expects(store: Path) -> None:
    ran = _show(store, 8)
    assert ran.returncode == int(_ts_constant("EXIT_RECORD_ERROR"))
    assert ran.stderr.strip().startswith(_ts_constant("NO_RECORD_PREFIX"))


def test_an_unknown_record_version_exits_with_the_code_the_reader_expects(store: Path) -> None:
    _write_record(store, 9, schema="run_record.v999")
    ran = _show(store, 9)
    assert ran.returncode == int(_ts_constant("EXIT_UNKNOWN_VERSION"))
    assert not ran.stderr.strip().startswith(_ts_constant("NO_RECORD_PREFIX"))


def test_a_corrupt_record_is_an_error_not_a_missing_record(store: Path) -> None:
    (store / "issue-10.json").write_text("{not json", encoding="utf-8")
    ran = _show(store, 10)
    assert ran.returncode == int(_ts_constant("EXIT_RECORD_ERROR"))
    assert not ran.stderr.strip().startswith(_ts_constant("NO_RECORD_PREFIX"))


def test_every_failure_reason_the_reader_returns_is_in_the_contract() -> None:
    returned = set(re.findall(r"reason: '([a-z-]+)'", READER.read_text(encoding="utf-8")))
    union = re.search(
        r"export type SagaRunReadFailure =(.*?)\n\n", CONTRACT.read_text(encoding="utf-8"), re.S
    )
    assert union, "the contract no longer declares SagaRunReadFailure"
    declared = set(re.findall(r"\| '([a-z-]+)'", union.group(1)))
    assert returned, "run-record.ts returns no failure reason, so this check finds nothing"
    assert returned == declared, f"reader returns {sorted(returned)}, contract declares {sorted(declared)}"


def _stage_state_record(store: Path, issue: int) -> None:
    raw = json.loads((STATE_FIXTURES / "record.json").read_text(encoding="utf-8"))
    raw["issue"] = issue
    (store / f"issue-{issue}.json").write_text(json.dumps(raw), encoding="utf-8")


def _review(store: Path, issue: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(RUN_STATUS),
            "--store-root",
            str(store),
            "--repo-root",
            str(store),
            "review",
            "--issue",
            str(issue),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_state_reader_knows_the_document_version_the_script_writes(store: Path) -> None:
    _stage_state_record(store, 7)
    rendered = subprocess.run(
        [
            sys.executable,
            str(REVIEW_STATE),
            "render",
            "--record",
            str(store / "issue-7.json"),
            "--envelope",
            str(STATE_FIXTURES / "envelope.json"),
            "--render",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rendered.returncode == 0, rendered.stderr
    assert json.loads(rendered.stdout)["schema"] == _ts_constant("KNOWN_REVIEW_STATE_SCHEMA")
    assert f"'{json.loads(rendered.stdout)['schema']}'" in CONTRACT.read_text(encoding="utf-8")


def test_the_state_review_view_carries_the_token_the_reader_requires(store: Path) -> None:
    _stage_state_record(store, 7)
    ran = _review(store, 7)
    assert ran.returncode == 0, ran.stderr
    view = json.loads(ran.stdout)
    assert view["schema"] == _ts_constant("KNOWN_REVIEW_VIEW_SCHEMA")
    review = view["review"]
    assert review["state_schema"] == _ts_constant("KNOWN_REVIEW_STATE_SCHEMA")
    assert review["state"]["schema"] == _ts_constant("KNOWN_REVIEW_STATE_SCHEMA")
    assert isinstance(review["lenses"], list) and review["lenses"]


def test_a_state_review_with_an_unknown_record_version_exits_3(store: Path) -> None:
    (store / "issue-9.json").write_text(json.dumps({"schema": "run_record.v999", "issue": 9}))
    ran = _review(store, 9)
    assert ran.returncode == int(_ts_constant("EXIT_UNKNOWN_VERSION"))


def test_a_corrupt_record_is_an_error_for_the_review_view(store: Path) -> None:
    (store / "issue-10.json").write_text("{not json", encoding="utf-8")
    ran = _review(store, 10)
    assert ran.returncode == int(_ts_constant("EXIT_RECORD_ERROR"))


SETUP_TOOLS = """\
schema: review_tools.v1
tools:
  - id: probe-install
    tool: saga-probe-missing-binary
    languages: ["*"]
    lens: testing
    default_version: "1.0.0"
    version_mode: exact
    install: "Run the installer."
    install_argv: ["saga-probe-installer"]
  - id: probe-missing
    tool: saga-probe-missing-binary
    languages: ["*"]
    lens: testing
    default_version: "1.0.0"
    version_mode: exact
    install: null
    install_argv: null
"""


def test_the_setup_reader_knows_the_survey_version_the_script_writes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = tmp_path / "tools.yaml"
    tools.write_text(SETUP_TOOLS, encoding="utf-8")
    ran = subprocess.run(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "survey",
            "--repo",
            str(repo),
            "--home",
            str(home),
            "--tools",
            str(tools),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    document = json.loads(ran.stdout)
    assert document["schema"] == _ts_constant("KNOWN_SETUP_SURVEY_SCHEMA")
    assert f"'{document['schema']}'" in CONTRACT.read_text(encoding="utf-8")
    by_id = {row["id"]: row for row in document["tools"]}
    assert by_id["probe-install"]["has_install"] is True
    assert by_id["probe-install"]["install"] == "Run the installer."
    assert by_id["probe-missing"]["has_install"] is False
    assert by_id["probe-missing"]["install"] is None


def test_the_offer_reader_knows_the_record_version_the_script_writes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    def verb(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SETUP_SCRIPT), *args, "--home", str(home)],
            capture_output=True,
            text=True,
            check=False,
        )

    first = verb("offer-status")
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["schema"] == _ts_constant("KNOWN_MACHINE_RECORD_SCHEMA")
    assert f"'{json.loads(first.stdout)['schema']}'" in CONTRACT.read_text(encoding="utf-8")
    recorded = verb("record-offer")
    assert recorded.returncode == 0, recorded.stderr
    body = json.loads(verb("offer-status").stdout)
    assert (body["ran"], body["offered"]) == (False, True)


def test_the_contract_declares_exactly_the_keys_the_script_writes() -> None:
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import run_record  # noqa: PLC0415  (loaded from the script directory on purpose)
    finally:
        sys.path.remove(str(SCRIPT.parent))
    body = re.search(
        r"export type SagaRunRecord = \{(.*?)\n\}", CONTRACT.read_text(encoding="utf-8"), re.S
    )
    assert body, "the contract no longer declares SagaRunRecord"
    fields = re.findall(r"^\s+(\w+)(\??):", body.group(1), re.MULTILINE)
    declared = {name for name, _ in fields}
    assert declared == set(run_record.TOP_LEVEL_KEYS), (
        f"contract declares {sorted(declared)}, run_record.py writes {sorted(run_record.TOP_LEVEL_KEYS)}"
    )
    optional = sorted(name for name, mark in fields if mark)
    assert optional == [], f"to_dict always writes these, so they must be required: {optional}"
