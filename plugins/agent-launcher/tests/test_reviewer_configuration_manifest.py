"""Per-source configuration digests for the targeted reviewer (provenance contract).

The legacy ``reviewer_configuration_fingerprint`` keeps only the overall
SHA-256 and the sorted source labels, so two runs with identical labels
cannot reveal which source content differed. The frozen contract adds
``configuration.source_digests``: the already-sorted ``(label, sha256)``
pairs as ``{label, sha256}`` objects, where ``sha256`` is the content hex
digest or the literal ``"absent"``. Sorted-pairs order is kept exactly,
including duplicate labels. The legacy ``fingerprint`` and ``sources``
stay byte-identical, raw contents are never retained, and the field rides
the existing ``reviewer_launch`` ``result.json`` writer.

These tests are independent and inert: synthetic sources only, the stubbed
reviewer session, an isolated temp HOME, and no network, provider, model,
or case calls. Baseline literals below were captured from the unchanged
84abd6f code by direct call before these tests were written.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
LAUNCHER = (
    REPO / "plugins" / "agent-launcher" / "skills" / "agent-launcher" / "scripts" / "launcher.py"
)
SAGA_PROMPT = REPO / "plugins" / "saga" / "references" / "targeted-reviewer-prompt.md"
SAGA_SCHEMA = REPO / "plugins" / "saga" / "references" / "targeted-reviewer-answer.schema.json"
SAGA_FIXTURES = REPO / "plugins" / "saga" / "tests" / "fixtures" / "reviewer_answer"

#: Fixed inert sources, deliberately unsorted on the way in.
BASE_SOURCES: list[tuple[str, bytes | None]] = [
    ("user:CLAUDE.md", b"User rules.\n"),
    ("project:CLAUDE.md", None),
    ("plugin:saga@example", b"1.3.0@abc"),
    ("project:EMPTY.md", b""),
]

#: Literals captured from unchanged 84abd6f for ``BASE_SOURCES``.
BASELINE_FINGERPRINT = "5d9aaaf2d39cfae8efa4eff255bffbc9c5a14fdf9bc0f412cf44c31f354501cd"
BASELINE_SOURCES = [
    "plugin:saga@example",
    "project:CLAUDE.md",
    "project:EMPTY.md",
    "user:CLAUDE.md",
]
BASELINE_MANIFEST = [
    {
        "label": "plugin:saga@example",
        "sha256": "184b7188e45e0336de7a27ba26222e56a9a96167ed4bfd6b5c7ff11374d84c89",
    },
    {"label": "project:CLAUDE.md", "sha256": "absent"},
    {
        "label": "project:EMPTY.md",
        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    },
    {
        "label": "user:CLAUDE.md",
        "sha256": "bef3d8fa0bb760341214428a36e6c1efdfc0fa804de3b86bd17a5218b5979ff9",
    },
]

#: Duplicate-label fixture: tie-break is by digest, a-content sorts first.
DUP_SOURCES: list[tuple[str, bytes | None]] = [
    ("dup:label", b"b-content"),
    ("dup:label", b"a-content"),
    ("aaa:first", b"x"),
]
DUP_FINGERPRINT = "e04ac735c11bd906219b1229d933176feb357769f7900aa411cdf9543495311c"
DUP_MANIFEST = [
    {
        "label": "aaa:first",
        "sha256": "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",
    },
    {
        "label": "dup:label",
        "sha256": "42fb0de209d11edcf5f7a7a478349824317accf0217cb25af4247e16fb1d9d90",
    },
    {
        "label": "dup:label",
        "sha256": "62f93e8a9ad9d93768ea6f3393237a0d2067758bde0a02013879c45f2924e21c",
    },
]

_HEX_OR_ABSENT = re.compile(r"\A([0-9a-f]{64}|absent)\Z")


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def launcher() -> ModuleType:
    return _load(LAUNCHER, "_agent_launcher_manifest")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("manifest tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _manifest(configuration: dict[str, Any]) -> list[dict[str, str]]:
    digests = configuration["source_digests"]
    assert isinstance(digests, list) and digests
    for entry in digests:
        assert set(entry) == {"label", "sha256"}, entry
    return digests


def test_legacy_fingerprint_and_sources_are_exact(
    launcher: ModuleType,
) -> None:
    """The frozen baseline: the contract must not move the legacy values."""
    configuration = launcher.reviewer_configuration_fingerprint(BASE_SOURCES)
    assert configuration["fingerprint"] == BASELINE_FINGERPRINT
    assert configuration["sources"] == BASELINE_SOURCES


def test_manifest_lists_sorted_per_source_digests(
    launcher: ModuleType,
) -> None:
    configuration = launcher.reviewer_configuration_fingerprint(BASE_SOURCES)
    assert _manifest(configuration) == BASELINE_MANIFEST


def test_manifest_distinguishes_absent_from_empty(
    launcher: ModuleType,
) -> None:
    configuration = launcher.reviewer_configuration_fingerprint(BASE_SOURCES)
    by_label = {entry["label"]: entry["sha256"] for entry in _manifest(configuration)}
    assert by_label["project:CLAUDE.md"] == "absent"
    assert by_label["project:EMPTY.md"] == hashlib.sha256(b"").hexdigest()
    assert by_label["project:CLAUDE.md"] != by_label["project:EMPTY.md"]


def test_manifest_changes_exactly_one_entry_on_single_source_change(
    launcher: ModuleType,
) -> None:
    before = launcher.reviewer_configuration_fingerprint(BASE_SOURCES)
    edited = [
        (label, b"User rules, edited.\n" if label == "user:CLAUDE.md" else content)
        for label, content in BASE_SOURCES
    ]
    after = launcher.reviewer_configuration_fingerprint(edited)
    assert after["fingerprint"] != BASELINE_FINGERPRINT
    assert after["sources"] == BASELINE_SOURCES
    old = _manifest(before)
    new = _manifest(after)
    assert [entry["label"] for entry in new] == [entry["label"] for entry in old]
    changed = [
        label
        for old_entry, new_entry in zip(old, new, strict=True)
        for label in (new_entry["label"],)
        if old_entry != new_entry
    ]
    assert changed == ["user:CLAUDE.md"]


def test_manifest_keeps_sorted_order_including_duplicate_labels(
    launcher: ModuleType,
) -> None:
    configuration = launcher.reviewer_configuration_fingerprint(DUP_SOURCES)
    assert configuration["fingerprint"] == DUP_FINGERPRINT
    assert configuration["sources"] == ["aaa:first", "dup:label", "dup:label"]
    assert _manifest(configuration) == DUP_MANIFEST


def test_manifest_exposes_no_raw_values_or_paths(
    launcher: ModuleType, tmp_path: Path
) -> None:
    raw = b"inert-sensitive-content-9f3c\n"
    sources = [("user:CLAUDE.md", raw), ("project:CLAUDE.md", None)]
    configuration = launcher.reviewer_configuration_fingerprint(sources)
    digests = _manifest(configuration)
    for entry in digests:
        assert _HEX_OR_ABSENT.fullmatch(entry["sha256"]), entry
        assert str(tmp_path) not in entry["label"]
        assert os.path.expanduser("~") not in entry["label"]
    serialised = json.dumps(digests)
    assert raw.decode("utf-8").strip() not in serialised
    assert str(tmp_path) not in serialised


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _claude_result(final: str) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 6154,
            "num_turns": 2,
            "result": final,
            "session_id": "00000000-0000-4000-8000-000000000000",
            "total_cost_usd": 0.0705,
            "usage": {
                "input_tokens": 18,
                "output_tokens": 835,
                "cache_read_input_tokens": 49907,
                "cache_creation_input_tokens": 14292,
            },
            "modelUsage": {"claude-example-model": {"inputTokens": 18, "outputTokens": 835}},
            "permission_denials": [],
        }
    )


class _StubSession:
    """Stands in for the vendor session: records input, prints a canned result."""

    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, argv: list[str], *, stdin: str, cwd: Path, env: Any, timeout: float
    ) -> Any:
        self.calls.append({"argv": argv, "stdin": stdin, "cwd": cwd, "env": dict(env)})
        return subprocess.CompletedProcess(argv, 0, self.stdout, "")


def test_manifest_propagates_through_stubbed_launch_result_json(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actual writer carries the manifest into result.json (all native calls stubbed)."""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "CLAUDE.md").write_text("Project rules.\n")
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", ".")
    _git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "base")
    head = _git(repo, "rev-parse", "HEAD")

    home = tmp_path / "home"
    claude = home / ".claude"
    (claude / "plugins").mkdir(parents=True)
    (claude / "CLAUDE.md").write_text("User rules.\n")
    (claude / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"saga@example": True}})
    )
    (claude / "plugins" / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "saga@example": [
                        {"scope": "user", "version": "1.3.0", "gitCommitSha": "abc"}
                    ]
                },
            }
        )
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(
        launcher, "_reviewer_vendor_version", lambda _binary, _env: "9.9.9 (Stubbed Reviewer)"
    )
    answer = json.loads((SAGA_FIXTURES / "answer.json").read_text(encoding="utf-8"))
    session = _StubSession(_claude_result(json.dumps(answer)))
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"}
    packet = tmp_path / "packet"
    packet.mkdir()
    request = launcher.ReviewerRequest(
        vendor="claude",
        model="opus",
        effort="high",
        repo=repo,
        head=head,
        packet=packet,
        prompt=SAGA_PROMPT,
        schema=SAGA_SCHEMA,
        out=tmp_path / "out",
        work_root=tmp_path / "reviews",
        max_budget_usd="5",
    )

    result, code = launcher.reviewer_launch(request, env=env, session=session)

    assert code == 0
    assert len(session.calls) == 1
    configuration = result["configuration"]
    assert len(configuration["fingerprint"]) == 64
    digests = _manifest(configuration)
    assert [entry["label"] for entry in digests] == configuration["sources"]
    assert len(digests) == len(configuration["sources"])
    for entry in digests:
        assert _HEX_OR_ABSENT.fullmatch(entry["sha256"]), entry
    assert "plugin:saga@example" in configuration["sources"]
    stored = json.loads((tmp_path / "out" / "result.json").read_text(encoding="utf-8"))
    assert stored == result
    assert stored["configuration"]["source_digests"] == digests


def test_manifest_marks_outside_copy_import_without_reading_it(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An outside-the-copy import is a marker digest; the file is never read."""
    copy = tmp_path / "copy"
    copy.mkdir()
    secret = tmp_path / "outside-secret"
    secret.write_text("inert-example-secret\n")
    (copy / "CLAUDE.md").write_text(f"Rules.\n@{secret}\n")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    read: list[Path] = []
    real = launcher._reviewer_read
    monkeypatch.setattr(launcher, "_reviewer_read", lambda p: read.append(p) or real(p))

    sources = launcher.reviewer_claude_config_sources(copy, {"HOME": str(home)})
    configuration = launcher.reviewer_configuration_fingerprint(sources)

    assert secret not in read
    label = f"import:project:CLAUDE.md:{secret}"
    assert dict(sources)[label] == b"outside the copy"
    digests = _manifest(configuration)
    marked = [entry for entry in digests if entry["label"] == label]
    assert len(marked) == 1
    assert marked[0]["sha256"] == hashlib.sha256(b"outside the copy").hexdigest()
    assert "inert-example-secret" not in json.dumps(digests)
