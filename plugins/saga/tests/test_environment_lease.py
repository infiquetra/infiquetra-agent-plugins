"""Tests for the shared-environment lease, kept as a reference on a git remote (issue #99).

Every test drives real git against a bare repository under ``tmp_path``, which stands in for the
remote every deploying host pushes to. Nothing here touches the network or any real remote, and
two clones of the same bare repository stand in for two hosts.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


L = _load("environment_lease")
FE = _load("functional_environment")

REF = "refs/saga/leases/shared-nonprod"


def _git(*argv: str) -> str:
    result = subprocess.run(["git", *argv], capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def hosts(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A bare remote and two clones of it, one per host."""
    remote = tmp_path / "remote.git"
    _git("init", "-q", "--bare", str(remote))
    clones = []
    for name in ("host-a", "host-b"):
        clone = tmp_path / name
        _git("init", "-q", str(clone))
        _git("-C", str(clone), "remote", "add", "origin", str(remote))
        clones.append(clone)
    return remote, clones[0], clones[1]


def _holder(issue: int = 1, *, repo: str = "infiquetra/example", **overrides: object) -> object:
    fields: dict[str, object] = {
        "repo": repo,
        "issue": issue,
        "revision": "c" * 40,
        "host": "builder-1",
        "started_at": "2026-10-04T00:00:00Z",
        "bound_seconds": 600,
    }
    fields.update(overrides)
    return L.LeaseHolder(**fields)


def _remote_ref(remote: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(remote), "rev-parse", "--verify", "--quiet", REF],
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_acquire_on_a_free_remote_creates_the_ref_and_the_payload_reads_back(
    hosts: tuple[Path, Path, Path],
) -> None:
    remote, host_a, _ = hosts
    backend = L.GitRefLeaseBackend(host_a)
    holder = _holder()
    result = backend.acquire("shared-nonprod", holder)
    assert result.status == L.ACQUIRED and result.acquired
    assert _remote_ref(remote) == result.token
    state = backend.read("shared-nonprod")
    assert state.held and state.token == result.token
    assert state.holder == holder


def test_a_second_run_on_another_host_finds_it_held_and_the_ref_unchanged(
    hosts: tuple[Path, Path, Path],
) -> None:
    remote, host_a, host_b = hosts
    first = L.GitRefLeaseBackend(host_a).acquire("shared-nonprod", _holder(1))
    second = L.GitRefLeaseBackend(host_b).acquire("shared-nonprod", _holder(2, host="builder-2"))
    assert second.status == L.HELD and not second.acquired
    assert second.holder.issue == 1
    assert second.token == first.token
    assert _remote_ref(remote) == first.token


def test_the_holder_releases_and_the_ref_is_gone(hosts: tuple[Path, Path, Path]) -> None:
    remote, host_a, host_b = hosts
    token = L.GitRefLeaseBackend(host_a).acquire("shared-nonprod", _holder()).token
    released = L.GitRefLeaseBackend(host_b).release("shared-nonprod", token)
    assert released.status == L.RELEASED
    assert _remote_ref(remote) == ""
    assert L.GitRefLeaseBackend(host_b).acquire("shared-nonprod", _holder(2)).acquired


def test_a_release_with_the_wrong_token_deletes_nothing(hosts: tuple[Path, Path, Path]) -> None:
    remote, host_a, host_b = hosts
    token = L.GitRefLeaseBackend(host_a).acquire("shared-nonprod", _holder()).token
    refused = L.GitRefLeaseBackend(host_b).release("shared-nonprod", "0" * 40)
    assert refused.status == L.NOT_HELD
    assert _remote_ref(remote) == token


def test_the_same_run_re_acquires_its_own_lease_after_a_crash(
    hosts: tuple[Path, Path, Path],
) -> None:
    remote, host_a, host_b = hosts
    L.GitRefLeaseBackend(host_a).acquire("shared-nonprod", _holder(7))
    again = L.GitRefLeaseBackend(host_b).acquire(
        "shared-nonprod", _holder(7, started_at="2026-10-04T01:00:00Z", pass_number=2)
    )
    assert again.status == L.REACQUIRED
    assert _remote_ref(remote) == again.token


def test_a_repository_pre_push_hook_does_not_run_for_a_lease_push(
    hosts: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    _, host_a, _ = hosts
    marker = tmp_path / "hook-ran"
    hook = host_a / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    hook.chmod(0o755)
    backend = L.GitRefLeaseBackend(host_a)
    result = backend.acquire("shared-nonprod", _holder())
    assert result.acquired
    assert backend.release("shared-nonprod", result.token).status == L.RELEASED
    assert not marker.exists()


def test_a_host_with_no_git_identity_still_acquires(
    hosts: tuple[Path, Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, host_a, _ = hosts
    home = tmp_path / "empty-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    assert L.GitRefLeaseBackend(host_a).acquire("shared-nonprod", _holder()).acquired


def test_an_unreachable_remote_could_not_execute_and_is_never_held(tmp_path: Path) -> None:
    clone = tmp_path / "lonely"
    _git("init", "-q", str(clone))
    _git("-C", str(clone), "remote", "add", "origin", str(tmp_path / "no-such-remote.git"))
    result = L.GitRefLeaseBackend(clone).acquire("shared-nonprod", _holder())
    assert result.status == L.COULD_NOT_EXECUTE and not result.acquired
    assert result.detail


def test_a_missing_remote_is_named_before_anything_runs(tmp_path: Path) -> None:
    clone = tmp_path / "no-remote"
    _git("init", "-q", str(clone))
    problem = L.GitRefLeaseBackend(clone, remote="origin").check_remote()
    assert problem is not None and "'origin' is not configured" in problem
    assert L.GitRefLeaseBackend(clone, remote="https://example.invalid/r.git").check_remote() is None


@pytest.mark.parametrize("name", ["", "Shared", "a/b", "-x", "x" * 64, "refs/heads/main"])
def test_an_invalid_lease_name_is_refused(name: str) -> None:
    with pytest.raises(L.LeaseError):
        L.ref_for(name)


def test_an_unparseable_payload_is_held_and_never_released_by_another_run(
    hosts: tuple[Path, Path, Path],
) -> None:
    remote, host_a, host_b = hosts
    tree = _git("-C", str(host_a), "mktree")
    env = {**os.environ, "GIT_AUTHOR_NAME": "x", "GIT_AUTHOR_EMAIL": "x@example.invalid",
           "GIT_COMMITTER_NAME": "x", "GIT_COMMITTER_EMAIL": "x@example.invalid"}
    oid = subprocess.run(
        ["git", "-C", str(host_a), "commit-tree", tree, "-m", "not json"],
        capture_output=True, text=True, check=True, env=env, input="",
    ).stdout.strip()
    _git("-C", str(host_a), "push", "-q", "origin", f"{oid}:{REF}")

    backend = L.GitRefLeaseBackend(host_b)
    result = backend.acquire("shared-nonprod", _holder())
    assert result.status == L.HELD
    assert result.holder == {"unparseable": True, "raw": "not json"}
    state = backend.read("shared-nonprod")
    line = L.describe(state, datetime(2026, 10, 4, tzinfo=UTC))
    assert "cannot read" in line and f"--expect {oid}" in line
    assert _remote_ref(remote) == oid


def test_staleness_is_judged_against_the_holder_s_own_bound() -> None:
    holder = _holder(started_at="2026-10-04T00:00:00Z", bound_seconds=600)
    assert not L.is_stale(holder, datetime(2026, 10, 4, 0, 9, tzinfo=UTC))
    assert L.is_stale(holder, datetime(2026, 10, 4, 0, 11, tzinfo=UTC))
    state = L.LeaseState(name="shared-nonprod", held=True, token="f" * 40, holder=holder)
    line = L.describe(state, datetime(2026, 10, 4, 1, 0, tzinfo=UTC), remote="origin")
    assert "infiquetra/example#1" in line and "builder-1" in line
    assert "STALE" in line
    assert "environment_lease.py --repo-root . --remote origin release --name shared-nonprod" in line
    fresh = L.describe(state, datetime(2026, 10, 4, 0, 1, tzinfo=UTC))
    assert "STALE" not in fresh


def test_the_cli_reports_status_and_releases_only_the_expected_object(
    hosts: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    remote, host_a, host_b = hosts
    token = L.GitRefLeaseBackend(host_a).acquire("shared-nonprod", _holder()).token
    base = ["--repo-root", str(host_b), "--remote", "origin"]

    def later() -> datetime:
        return datetime(2026, 10, 5, tzinfo=UTC)

    assert L.main([*base, "status", "--name", "shared-nonprod"], now=later) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["held"] is True and status["token"] == token
    assert status["holder"]["issue"] == 1 and status["stale"] is True

    assert L.main([*base, "release", "--name", "shared-nonprod", "--expect", "0" * 40]) == 2
    assert "not-held" in capsys.readouterr().err
    assert _remote_ref(remote) == token

    assert L.main([*base, "release", "--name", "shared-nonprod", "--expect", token]) == 0
    assert _remote_ref(remote) == ""
    assert L.main([*base, "status", "--name", "shared-nonprod"]) == 0
    assert json.loads(capsys.readouterr().out.split("\n", 1)[1])["held"] is False


def test_the_host_label_is_short_or_the_operator_s_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAGA_LEASE_HOLDER", "ci-runner-3")
    assert L.host_label() == "ci-runner-3"
    monkeypatch.delenv("SAGA_LEASE_HOLDER")
    assert "." not in L.host_label()


# ---------------------------------------------------------------------------
# The declaration's lease block (functional_environment.py).
# ---------------------------------------------------------------------------

_SHARED_BLOCK = {
    "kind": "shared-nonprod",
    "deploy_command": "scripts/deploy.sh",
    "test_command": "scripts/test.sh",
}


def test_a_shared_declaration_defaults_its_lease_to_origin_and_shared_nonprod() -> None:
    resolved = FE.resolve({"functional_test_environment": _SHARED_BLOCK})
    assert FE.lease_of(resolved) == {"remote": "origin", "name": "shared-nonprod"}
    assert "lease" not in resolved
    assert any("refs/saga/leases/shared-nonprod on origin" in line for line in FE.describe(resolved))


def test_a_declared_lease_block_is_kept_and_written_back() -> None:
    block = {**_SHARED_BLOCK, "lease": {"remote": "https://example.invalid/s.git", "name": "stack-a"}}
    resolved = FE.resolve({"functional_test_environment": block})
    assert FE.lease_of(resolved) == {"remote": "https://example.invalid/s.git", "name": "stack-a"}
    key, value = FE.profile_entry(resolved)
    assert key == "functional_test_environment" and value["lease"]["name"] == "stack-a"


def test_a_private_environment_needs_no_lease_and_refuses_one() -> None:
    private = {"kind": "local", "test_command": "pytest", "scope": "private"}
    assert FE.lease_of(FE.resolve({"functional_test_environment": private})) is None
    with pytest.raises(FE.DeclarationError, match="only to a shared environment"):
        FE.resolve({"functional_test_environment": {**private, "lease": {"name": "x"}}})


@pytest.mark.parametrize("lease", [{"name": "Bad/Name"}, {"other": "x"}, "origin"])
def test_a_malformed_lease_block_is_refused(lease: object) -> None:
    with pytest.raises(FE.DeclarationError):
        FE.resolve({"functional_test_environment": {**_SHARED_BLOCK, "lease": lease}})


def test_the_declaration_and_the_lease_module_agree_on_a_lease_name() -> None:
    assert FE.LEASE_NAME_PATTERN == L.NAME_RE.pattern
    assert FE.DEFAULT_LEASE == {"remote": L.DEFAULT_REMOTE, "name": L.DEFAULT_NAME}
