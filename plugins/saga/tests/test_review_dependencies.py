"""The head's dependencies, fetched once in prepare for an offline reviewer (issue 262)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
CRATES_IO = "registry+https://github.com/rust-lang/crates.io-index"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


D = _load("review_dependencies")


class _Result:
    def __init__(self, code: int, stdout: str = "", stderr: str = "") -> None:
        self.code, self.stdout, self.stderr = code, stdout, stderr


def _unwrap(argv: list[str]) -> list[str]:
    """The cargo command inside the fetch watcher's argument vector."""
    assert argv[:3] == [sys.executable, "-I", str(SCRIPTS / "review_dependencies.py")], argv
    return argv[argv.index("--") + 1:]


class _Cargo:
    """git answers for real; cargo is recorded, and ``vendor`` writes one crate."""

    def __init__(self, *, vendor_code: int = 0, writes: bool = True) -> None:
        self.vendor_code = vendor_code
        self.writes = writes
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int,
                 shell: bool) -> Any:
        assert shell is False
        if argv[0] == "git":
            proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                                  check=False)
            return _Result(proc.returncode, proc.stdout, proc.stderr)
        raw, argv = list(argv), _unwrap(list(argv))
        self.calls.append({
            "argv": argv, "raw": raw, "cwd": Path(cwd), "env": dict(env), "timeout": timeout,
            "listing": sorted(p.relative_to(cwd).as_posix() for p in Path(cwd).rglob("*")),
        })
        if argv[1] == "vendor" and self.vendor_code == 0 and self.writes:
            crate = Path(argv[-1]) / "itoa"
            crate.mkdir(parents=True)
            (crate / "Cargo.toml").write_text('[package]\nname = "itoa"\n', encoding="utf-8")
        return _Result(self.vendor_code, "", "error: example failure\n" if self.vendor_code else "")


def _export_from(tree: dict[str, str]) -> Any:
    def export(dest: Path) -> bool:
        for relative, text in tree.items():
            path = dest / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return True

    return export


def _lock(*sources: str) -> str:
    text = 'version = 4\n\n[[package]]\nname = "example"\nversion = "0.1.0"\n'
    for index, source in enumerate(sources):
        text += (f'\n[[package]]\nname = "dep{index}"\nversion = "1.0.0"\n'
                 f'source = "{source}"\nchecksum = "{"ab" * 32}"\n')
    return text


_MANIFEST = '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n'
_ONE_DEP = _MANIFEST + '\n[dependencies]\nitoa = "1"\n'
_HOSTILE = {
    ".cargo/config.toml": '[source.crates-io]\nreplace-with = "evil"\n'
                          '[source.evil]\nregistry = "https://example.com/index"\n',
    "rust-toolchain.toml": '[toolchain]\npath = "./evil-toolchain"\n',
    "build.rs": 'fn main() { println!("cargo:rerun-if-changed=build.rs"); }\n',
    "src/lib.rs": "pub fn one() -> i32 { 1 }\n",
}


def _fetch(
    tmp_path: Path, tree: dict[str, str], runner: Any | None = None,
) -> tuple[dict[str, Any], Any, Path]:
    packet = tmp_path / "packet"
    packet.mkdir(exist_ok=True)
    cargo = runner or _Cargo()
    return D._fetch_rust(cargo, packet, _export_from(tree)), cargo, packet


# --- the fetch ----------------------------------------------------------------------------------


def test_the_vendor_runs_on_a_sanitised_export_with_a_fresh_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CARGO_REGISTRIES_EXAMPLE_TOKEN", "inert-example")
    monkeypatch.setenv("RUSTC_WRAPPER", "/bin/example-wrapper")
    monkeypatch.setenv("CARGO_HOME", str(tmp_path / "operator-cargo"))
    tree = {"Cargo.toml": _ONE_DEP, "Cargo.lock": _lock(CRATES_IO), **_HOSTILE}
    record, cargo, packet = _fetch(tmp_path, tree)
    assert record == {"state": "fetched", "directory": "dependencies/rust", "crates": 1}
    assert [call["argv"][:3] for call in cargo.calls] == [["cargo", "vendor", "--locked"]]
    call = cargo.calls[0]
    assert call["argv"][-1] == str(packet / "dependencies" / "rust")
    # The commit's cargo configuration and toolchain file were gone before cargo ran.
    assert ".cargo/config.toml" not in call["listing"] and ".cargo" not in call["listing"]
    assert "rust-toolchain.toml" not in call["listing"]
    assert {"Cargo.toml", "Cargo.lock", "build.rs"} <= set(call["listing"])
    env = call["env"]
    assert set(env) <= {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "HOME", "TMPDIR",
                        "CARGO_HOME", "CARGO_NET_GIT_FETCH_WITH_CLI", "RUSTUP_HOME",
                        "RUSTUP_TOOLCHAIN"}
    assert env["CARGO_NET_GIT_FETCH_WITH_CLI"] == "false"
    for name in ("HOME", "TMPDIR", "CARGO_HOME"):
        assert Path(env[name]).parent == call["cwd"].parent
        assert not Path(env[name]).exists(), "the fetch's own folders are removed afterwards"
    assert not call["cwd"].exists()
    # cargo runs under the watcher, with the byte and time limits and every folder it writes.
    raw = call["raw"]
    assert raw[raw.index("--limit") + 1] == str(D.FETCH_MAX_BYTES)
    assert raw[raw.index("--seconds") + 1] == str(D.FETCH_TIMEOUT)
    watched = [raw[i + 1] for i, part in enumerate(raw) if part == "--watch"]
    assert watched == [str(packet / "dependencies" / "rust"), env["HOME"], env["TMPDIR"],
                       env["CARGO_HOME"]]
    assert call["timeout"] > D.FETCH_TIMEOUT, "the watcher's own deadline comes first"


def test_without_a_lock_the_lock_is_generated_first_then_checked(tmp_path: Path) -> None:
    class _Generates(_Cargo):
        def __call__(self, argv: list[str], **kwargs: Any) -> Any:
            if _unwrap(argv)[1] == "generate-lockfile":
                (kwargs["cwd"] / "Cargo.lock").write_text(_lock(CRATES_IO), encoding="utf-8")
            return super().__call__(argv, **kwargs)

    record, cargo, _packet = _fetch(tmp_path, {"Cargo.toml": _ONE_DEP, "src/lib.rs": ""},
                                    _Generates())
    assert [call["argv"][1] for call in cargo.calls] == ["generate-lockfile", "vendor"]
    assert record["state"] == "fetched"


@pytest.mark.parametrize(
    "manifest",
    [
        _MANIFEST,
        _MANIFEST + '\n[dependencies]\nhelper = { path = "helper" }\n',
        _MANIFEST + '\n[dependencies]\nhelper = { path = "helper", version = "0.1" }\n',
        _MANIFEST + '\n[patch.crates-io]\nitoa = { path = "itoa" }\n',
    ],
)
def test_a_lock_with_no_registry_package_fetches_nothing(tmp_path: Path, manifest: str) -> None:
    record, cargo, packet = _fetch(tmp_path, {"Cargo.toml": manifest, "Cargo.lock": _lock()})
    assert record == {"state": "no-dependencies"}
    assert cargo.calls == [] and not (packet / "dependencies").exists()


_WORKSPACE_PATH = ('[workspace]\nmembers = ["app"]\n[workspace.dependencies]\n'
                   'helper = { path = "helper" }\n')


@pytest.mark.parametrize(
    ("tree", "declares"),
    [
        ({"Cargo.toml": _ONE_DEP}, True),
        ({"Cargo.toml": _MANIFEST + '\n[dev-dependencies]\nitoa = { version = "1" }\n'}, True),
        ({"Cargo.toml": _MANIFEST + "\n[target.'cfg(unix)'.dependencies]\nlibc = \"0.2\"\n"},
         True),
        ({"Cargo.toml": '[workspace]\nmembers = ["app"]\n[workspace.dependencies]\nitoa = "1"\n',
          "app/Cargo.toml": _MANIFEST + "\n[dependencies]\nitoa = { workspace = true }\n"}, True),
        ({"Cargo.toml": _WORKSPACE_PATH,
          "app/Cargo.toml": _MANIFEST + "\n[dependencies]\nhelper = { workspace = true }\n"},
         False),
        ({"Cargo.toml": _MANIFEST + '\n[dependencies]\nhelper = { path = "helper" }\n'}, False),
        ({"Cargo.toml": _MANIFEST + '\n[replace]\n"itoa:1.0.0" = { path = "itoa" }\n'}, False),
    ],
)
def test_a_dependency_that_is_not_a_path_is_one_crates_io_must_supply(
    tmp_path: Path, tree: dict[str, str], declares: bool,
) -> None:
    _export_from(tree)(tmp_path)
    assert D._declares_registry_dependency(tmp_path) is declares


def test_a_lock_missing_a_declared_dependency_is_not_recorded_as_none(tmp_path: Path) -> None:
    """The lock lists only the root package, but the manifest needs itoa: cargo decides."""
    record, cargo, packet = _fetch(
        tmp_path, {"Cargo.toml": _ONE_DEP, "Cargo.lock": _lock()}, _Cargo(vendor_code=101),
    )
    assert [call["argv"][:3] for call in cargo.calls] == [["cargo", "vendor", "--locked"]]
    assert record == {"state": "not-fetched",
                      "reason": "cargo vendor exited 101: error: example failure"}
    assert not (packet / "dependencies" / "rust").exists()


def test_a_declared_dependency_cargo_vendor_finds_nothing_for_is_none(tmp_path: Path) -> None:
    """An unused ``workspace.dependencies`` entry: cargo agrees there is nothing to fetch."""
    tree = {"Cargo.toml": '[workspace]\nmembers = ["app"]\n[workspace.dependencies]\nitoa = "1"\n',
            "app/Cargo.toml": _MANIFEST, "Cargo.lock": _lock()}
    record, cargo, packet = _fetch(tmp_path, tree, _Cargo(writes=False))
    assert [call["argv"][1] for call in cargo.calls] == ["vendor"]
    assert record == {"state": "no-dependencies"}
    assert not (packet / "dependencies").exists()


@pytest.mark.parametrize(
    ("tree", "reason"),
    [
        ({"Cargo.toml": _MANIFEST + '\n[dependencies]\nx = { git = "https://example.com/x" }\n'},
         "dependencies.x names git"),
        ({"Cargo.toml": _MANIFEST + '\n[dev-dependencies]\nx = { version = "1", registry = "corp" }\n'},
         "dev-dependencies.x names registry"),
        ({"Cargo.toml": _MANIFEST + '\n[target.\'cfg(unix)\'.build-dependencies]\n'
                                    'x = { git = "ssh://example.com/x" }\n'},
         "build-dependencies.x names git"),
        ({"Cargo.toml": '[workspace]\nmembers = ["a"]\n[workspace.dependencies]\n'
                        'x = { git = "file:///Users/example/private" }\n',
          "a/Cargo.toml": _MANIFEST}, "workspace.dependencies.x names git"),
        ({"Cargo.toml": _MANIFEST + '\n[patch."https://example.com/index"]\nx = { path = "x" }\n'},
         "patches https://example.com/index"),
        ({"Cargo.toml": _MANIFEST + '\n[patch.crates-io]\nx = { git = "https://example.com/x" }\n'},
         "patch.crates-io.x names git"),
        ({"Cargo.toml": _MANIFEST + '\n[dependencies]\nx = { path = "../../outside" }\n'},
         "points outside the head"),
        ({"Cargo.toml": _MANIFEST + '\n[dependencies]\nx = { path = "/Users/example/x" }\n'},
         "points outside the head"),
        ({"Cargo.toml": '[workspace]\nmembers = ["../elsewhere/*"]\n'}, "workspace.members"),
        ({"Cargo.toml": '[package]\nname = "a"\nversion = "0.1.0"\nworkspace = "../.."\n'},
         "package.workspace points outside"),
        ({"Cargo.toml": "[package\n"}, "Cargo.toml does not parse"),
        ({"Cargo.toml": _ONE_DEP, "Cargo.lock": _lock("git+https://example.com/x#abc")},
         "Cargo.lock names the source git+https://example.com/x"),
        ({"Cargo.toml": _ONE_DEP, "Cargo.lock": _lock("registry+https://example.com/index")},
         "only crates.io is fetched"),
    ],
)
def test_a_source_other_than_crates_io_or_a_path_outside_the_head_is_never_fetched(
    tmp_path: Path, tree: dict[str, str], reason: str,
) -> None:
    record, cargo, packet = _fetch(tmp_path, tree)
    assert record["state"] == "not-fetched"
    assert reason in record["reason"]
    assert cargo.calls == [], "no cargo command runs on a refused manifest or lock"
    assert not (packet / "dependencies").exists()


def test_configuration_above_the_fetch_folder_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    planted = tmp_path / "temp-root"
    (planted / ".cargo").mkdir(parents=True)
    (planted / ".cargo" / "config.toml").write_text('[build]\nrustc = "/bin/false"\n')
    monkeypatch.setattr(D.tempfile, "tempdir", str(planted))
    record, cargo, _packet = _fetch(tmp_path, {"Cargo.toml": _ONE_DEP, "Cargo.lock": _lock(CRATES_IO)})
    assert record["state"] == "not-fetched" and "would configure the fetch" in record["reason"]
    assert cargo.calls == []


def test_a_failed_vendor_leaves_no_directory_and_says_why(tmp_path: Path) -> None:
    record, _cargo, packet = _fetch(
        tmp_path, {"Cargo.toml": _ONE_DEP, "Cargo.lock": _lock(CRATES_IO)}, _Cargo(vendor_code=101),
    )
    assert record == {"state": "not-fetched",
                      "reason": "cargo vendor exited 101: error: example failure"}
    assert not (packet / "dependencies" / "rust").exists()


def test_a_missing_cargo_is_a_reason_not_a_crash(tmp_path: Path) -> None:
    def missing(argv: list[str], **_kwargs: Any) -> Any:
        raise FileNotFoundError(argv[0])

    record, _cargo, _packet = _fetch(
        tmp_path, {"Cargo.toml": _ONE_DEP, "Cargo.lock": _lock(CRATES_IO)}, missing,
    )
    assert record == {"state": "not-fetched", "reason": "cargo is not installed"}


def test_a_cargo_the_watcher_cannot_find_is_the_same_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    record, _cargo, _packet = _fetch(
        tmp_path, {"Cargo.toml": _ONE_DEP, "Cargo.lock": _lock(CRATES_IO)}, _live_runner(),
    )
    assert record == {"state": "not-fetched", "reason": "cargo is not installed"}


def _writer(target: str, size: int, then_sleep: float) -> list[str]:
    """A child that writes *size* bytes under *target* in 256 KiB files, then sleeps."""
    code = (
        "import os, sys, time\n"
        "target, size, pause = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])\n"
        "os.makedirs(os.path.join(target, 'crate'), exist_ok=True)\n"
        "for index in range(0, size, 262144):\n"
        "    with open(os.path.join(target, 'crate', f'{index}.rs'), 'wb') as handle:\n"
        "        handle.write(b'x' * min(262144, size - index))\n"
        "print(os.getpid(), flush=True)\n"
        "time.sleep(pause)\n"
    )
    return [sys.executable, "-c", code, target, str(size), str(then_sleep)]


def test_the_vendor_past_its_byte_limit_is_stopped_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real watcher, with cargo vendor replaced by a child that writes too much."""
    monkeypatch.setattr(D, "FETCH_MAX_BYTES", 1_000_000)
    pids: list[int] = []

    def runner(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int,
               shell: bool) -> Any:
        inner = _unwrap(argv)
        command = argv[: argv.index("--") + 1] + _writer(inner[-1], 3_000_000, 60)
        start = time.monotonic()
        proc = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=timeout, check=False)
        assert time.monotonic() - start < 30, "the watcher stopped the child, not its sleep"
        pids.extend(int(line) for line in proc.stdout.split() if line.isdigit())
        return _Result(proc.returncode, proc.stdout, proc.stderr)

    record, _cargo, packet = _fetch(
        tmp_path, {"Cargo.toml": _ONE_DEP, "Cargo.lock": _lock(CRATES_IO)}, runner,
    )
    assert record == {"state": "not-fetched",
                      "reason": "cargo vendor passed the 1000000 byte limit"}
    assert not (packet / "dependencies" / "rust").exists(), "the partial tree is deleted"
    for pid in pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_the_watcher_counts_a_command_that_ends_inside_one_interval(tmp_path: Path) -> None:
    code = D.watch(_writer(str(tmp_path / "v"), 2_000_000, 0), [tmp_path / "v"], 1_000_000, 60)
    assert code == D.LIMIT_EXIT


def test_the_watcher_counts_every_watched_folder_together(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "archive.crate").write_bytes(b"x" * 600_000)
    code = D.watch(_writer(str(tmp_path / "v"), 600_000, 0),
                   [tmp_path / "v", tmp_path / "home", tmp_path / "absent"], 1_000_000, 60)
    assert code == D.LIMIT_EXIT


def test_the_watcher_passes_the_command_s_own_exit_code_under_the_limit(tmp_path: Path) -> None:
    code = D.watch([sys.executable, "-c", "raise SystemExit(3)"], [tmp_path], 1_000_000, 60)
    assert code == 3


def test_the_watcher_stops_a_command_past_its_deadline(tmp_path: Path) -> None:
    start = time.monotonic()
    code = D.watch([sys.executable, "-c", "import time; time.sleep(60)"], [tmp_path], 10**9, 1)
    assert code == D.TIMEOUT_EXIT and time.monotonic() - start < 30


def test_the_watcher_script_marks_what_it_reports(tmp_path: Path) -> None:
    script = [sys.executable, "-I", str(SCRIPTS / "review_dependencies.py")]
    missing = subprocess.run(
        [*script, "--limit", "10", "--seconds", "5", "--", str(tmp_path / "no-such-cargo")],
        capture_output=True, text=True, check=False,
    )
    assert missing.returncode == D.MISSING_EXIT
    assert missing.stderr.rstrip().endswith(D._WATCHER_MARK)
    over = subprocess.run(
        [*script, "--limit", "1000", "--seconds", "30", "--watch", str(tmp_path / "v"), "--",
         *_writer(str(tmp_path / "v"), 5000, 0)],
        capture_output=True, text=True, check=False,
    )
    assert over.returncode == D.LIMIT_EXIT
    assert over.stderr.rstrip().endswith(D._WATCHER_MARK)


@pytest.mark.parametrize("sig", ["SIGTERM", "SIGINT", "SIGHUP"])
def test_a_watcher_that_is_stopped_takes_the_command_with_it(tmp_path: Path, sig: str) -> None:
    """The command runs in its own session, so only the watcher can stop it."""
    target = tmp_path / "v"
    watcher = subprocess.Popen(
        [sys.executable, "-I", str(SCRIPTS / "review_dependencies.py"), "--limit", str(10**9),
         "--seconds", "120", "--watch", str(target), "--", *_writer(str(target), 1000, 120)],
        stdout=subprocess.PIPE, text=True,
    )
    assert watcher.stdout is not None
    child = int(watcher.stdout.readline())
    watcher.send_signal(getattr(signal, sig))
    assert watcher.wait(timeout=30) == D.TIMEOUT_EXIT
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


def test_one_size_walk_stops_at_the_limit_or_the_deadline(tmp_path: Path) -> None:
    for index in range(5):
        folder = tmp_path / f"d{index}"
        folder.mkdir()
        (folder / "f").write_bytes(b"x" * 100)
    assert D._bytes([tmp_path]) == (500, True)
    over, complete = D._bytes([tmp_path], limit=150)
    assert 150 < over < 500 and complete, "past the limit is a complete answer"
    cut, complete = D._bytes([tmp_path], deadline=time.monotonic() - 1)
    assert cut < 500 and not complete


def test_a_count_cut_short_never_passes_the_command_s_success_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed: cargo finished, but the walk ran out of time before it saw everything."""
    monkeypatch.setattr(D, "_bytes", lambda *_args: (0, False))
    code = D.watch([sys.executable, "-c", "pass"], [tmp_path], 10**9, 60)
    assert code == D.TIMEOUT_EXIT


def test_a_cargo_exit_code_that_matches_the_watcher_s_is_still_cargo_s(tmp_path: Path) -> None:
    """Without the watcher's mark, 125 is cargo's own failure, reported as such."""
    record, _cargo, _packet = _fetch(
        tmp_path, {"Cargo.toml": _ONE_DEP, "Cargo.lock": _lock(CRATES_IO)},
        _Cargo(vendor_code=D.LIMIT_EXIT),
    )
    assert record == {"state": "not-fetched",
                      "reason": "cargo vendor exited 125: error: example failure"}


def test_a_head_without_a_root_manifest_records_no_rust_entry(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(argv: list[str], **_kwargs: Any) -> Any:
        calls.append(argv)
        return _Result(128)

    record = D.fetch(runner, tmp_path, "HEAD", tmp_path / "packet", _export_from({}))
    assert record == {"schema": D.SCHEMA}
    assert calls == [["git", "cat-file", "-e", "HEAD:Cargo.toml"], ["git", "ls-tree", "HEAD"],
                     ["git", "ls-tree", "-r", "HEAD"]]


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo is not installed")
def test_live_cargo_resolves_and_vendors_without_running_a_build_script(tmp_path: Path) -> None:
    """Real cargo, no network: path-only crates whose build scripts would leave a marker."""
    marker = tmp_path / "build-script-ran"
    build = f'fn main() {{ std::fs::write({json.dumps(str(marker))}, "x").unwrap(); }}\n'
    tree = {
        "Cargo.toml": '[workspace]\nmembers = ["app", "helper"]\nresolver = "2"\n',
        "app/Cargo.toml": '[package]\nname = "app"\nversion = "0.1.0"\nedition = "2021"\n'
                          '\n[dependencies]\nhelper = { path = "../helper" }\n',
        "app/build.rs": build, "app/src/lib.rs": "",
        "helper/Cargo.toml": '[package]\nname = "helper"\nversion = "0.1.0"\nedition = "2021"\n',
        "helper/build.rs": build, "helper/src/lib.rs": "",
    }
    runner = _live_runner()
    record = D._fetch_rust(runner, tmp_path / "packet", _export_from(tree))
    assert record == {"state": "no-dependencies"}, record
    assert [argv[1] for argv in runner.calls] == ["generate-lockfile"]
    # cargo vendor itself, on the same tree with its lock: still no build script.
    work = tmp_path / "work"
    _export_from(tree)(work)
    env = {**D._cargo_env(_fresh(tmp_path / "env")), "CARGO_NET_OFFLINE": "true"}
    subprocess.run(["cargo", "generate-lockfile", "--offline"], cwd=work, env=env, check=True,
                   capture_output=True)
    vendored = subprocess.run(["cargo", "vendor", "--locked", "--offline", str(tmp_path / "v")],
                              cwd=work, env=env, capture_output=True, text=True, check=False)
    assert vendored.returncode == 0, vendored.stderr
    assert not marker.exists()
    # The marker is real: compiling the same tree runs the build scripts and writes it.
    built = subprocess.run(["cargo", "build", "--offline", "--quiet"], cwd=work, env=env,
                           capture_output=True, text=True, check=False)
    assert built.returncode == 0, built.stderr
    assert marker.exists()


def _fresh(path: Path) -> Path:
    path.mkdir()
    return path


def _live_runner() -> Any:
    class _Live:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def __call__(self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int,
                     shell: bool) -> Any:
            assert shell is False
            if argv[0] == sys.executable:
                inner = _unwrap(argv)
                self.calls.append(inner)
                if inner[1] == "generate-lockfile":
                    argv = [*argv, "--offline"]
            proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                                  timeout=timeout, check=False)
            return _Result(proc.returncode, proc.stdout, proc.stderr)

    return _Live()


# --- reading it back ----------------------------------------------------------------------------


def _packet(tmp_path: Path, entry: Any, *, make: str | None = "dependencies/rust") -> Path:
    packet = tmp_path / "packet"
    packet.mkdir()
    if make is not None:
        (packet / make).mkdir(parents=True)
    (packet / D.FILE).write_text(json.dumps({"schema": D.SCHEMA, "rust": entry}), encoding="utf-8")
    return packet


def test_a_fetched_entry_names_the_vendored_directory(tmp_path: Path) -> None:
    packet = _packet(tmp_path, {"state": "fetched", "directory": "dependencies/rust"})
    assert D.rust_vendor(packet) == (packet / "dependencies" / "rust").resolve()


@pytest.mark.parametrize(
    "entry",
    [
        {"state": "not-fetched", "directory": "dependencies/rust"},
        {"state": "fetched", "directory": "/etc"},
        {"state": "fetched", "directory": "../outside"},
        {"state": "fetched", "directory": "dependencies/../dependencies/rust"},
        {"state": "fetched", "directory": ""},
        {"state": "fetched"},
        "fetched",
    ],
)
def test_an_entry_that_is_not_a_plain_folder_inside_the_packet_is_ignored(
    tmp_path: Path, entry: Any,
) -> None:
    assert D.rust_vendor(_packet(tmp_path, entry)) is None


def test_a_symlinked_dependency_folder_is_ignored(tmp_path: Path) -> None:
    packet = _packet(tmp_path, {"state": "fetched", "directory": "dependencies/rust"}, make=None)
    (packet / "dependencies").mkdir()
    (packet / "dependencies" / "rust").symlink_to(tmp_path)
    assert D.rust_vendor(packet) is None


def test_a_missing_or_unreadable_file_is_ignored(tmp_path: Path) -> None:
    assert D.rust_vendor(tmp_path) is None
    (tmp_path / D.FILE).write_text("{not json", encoding="utf-8")
    assert D.rust_vendor(tmp_path) is None


def test_the_cargo_home_is_offline_and_replaces_crates_io_with_the_vendored_tree(
    tmp_path: Path,
) -> None:
    vendor = tmp_path / 'odd "name"'
    assert D.write_cargo_home(tmp_path / "home", vendor) is None, "no shim without a cargo"
    config = tmp_path / "home" / "config.toml"
    parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    name = parsed["source"]["crates-io"]["replace-with"]
    assert name.startswith(D.VENDORED_SOURCE + "-") and len(name) == len(D.VENDORED_SOURCE) + 17
    assert parsed["source"][name] == {"directory": str(vendor)}
    assert parsed["net"] == {"offline": True}
    assert not os.access(config, os.W_OK)
    assert tomllib.loads(D.cargo_config(None)) == {"net": {"offline": True}}
    D.write_cargo_home(tmp_path / "other", vendor)
    other = tomllib.loads((tmp_path / "other" / "config.toml").read_text(encoding="utf-8"))
    assert other["source"]["crates-io"]["replace-with"] != name, "each home names it afresh"


def test_the_shim_passes_the_home_s_configuration_as_config(tmp_path: Path) -> None:
    fake = tmp_path / "bin with space" / "cargo"
    fake.parent.mkdir()
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    fake.chmod(0o755)
    shim = D.write_cargo_home(tmp_path / "home", tmp_path / "vendor", str(fake))
    assert shim == tmp_path / "home" / "bin" / "cargo"
    assert not os.access(shim, os.W_OK) and os.access(shim, os.X_OK)
    config = str(tmp_path / "home" / "config.toml")
    plain = subprocess.run([str(shim), "test", "-q", "it's"], capture_output=True, text=True,
                           check=True)
    assert plain.stdout.splitlines() == ["--config", config, "test", "-q", "it's"]
    toolchain = subprocess.run([str(shim), "+nightly", "test"], capture_output=True, text=True,
                               check=True)
    assert toolchain.stdout.splitlines() == ["+nightly", "--config", config, "test"]


def test_rustup_s_home_and_choice_reach_cargo_whatever_home_it_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On CI cargo is a rustup proxy; under a fresh HOME it found no toolchain (issue 262)."""
    monkeypatch.setenv("HOME", str(tmp_path / "operator"))
    monkeypatch.delenv("RUSTUP_HOME", raising=False)
    monkeypatch.delenv("RUSTUP_TOOLCHAIN", raising=False)
    assert D.rustup_env() == {"RUSTUP_HOME": str(tmp_path / "operator" / ".rustup")}
    monkeypatch.setenv("RUSTUP_HOME", "/opt/example/rustup")
    monkeypatch.setenv("RUSTUP_TOOLCHAIN", "1.98.1")
    assert D.rustup_env() == {"RUSTUP_HOME": "/opt/example/rustup", "RUSTUP_TOOLCHAIN": "1.98.1"}
    assert {"RUSTUP_HOME": "/opt/example/rustup", "RUSTUP_TOOLCHAIN": "1.98.1"}.items() <= (
        D._cargo_env(_fresh(tmp_path / "work")).items()
    )


def test_a_rustup_cargo_needs_its_bin_and_the_toolchains_never_the_cargo_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "operator"
    (home / ".cargo" / "bin").mkdir(parents=True)
    (home / ".cargo" / "credentials.toml").write_text("[registry]\ntoken = \"inert-example\"\n")
    (home / ".rustup" / "toolchains" / "stable" / "bin").mkdir(parents=True)
    (home / ".rustup" / "settings.toml").write_text('default_toolchain = "stable"\n')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("RUSTUP_HOME", raising=False)
    paths = D.toolchain_paths(str(home / ".cargo" / "bin" / "cargo"))
    assert paths == (home / ".cargo" / "bin", home / ".rustup" / "toolchains",
                     home / ".rustup" / "settings.toml")
    assert home / ".cargo" not in paths
    assert D.toolchain_paths(None) == ()
    # A cargo in home itself or a credential folder gives nothing of that folder back.
    for folder in (home, home / ".ssh", home / ".cargo"):
        assert folder not in D.toolchain_paths(str(folder / "cargo"))
    assert D.read_problem(home / ".config", home) is not None
    assert D.read_problem(home / ".cargo" / "bin", home) is None


def test_the_credential_paths_match_agent_launcher_s() -> None:
    launcher = REPO_ROOT / "plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py"
    spec = importlib.util.spec_from_file_location("launcher_for_saga_test", launcher)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["launcher_for_saga_test"] = module
    spec.loader.exec_module(module)
    assert D.CREDENTIAL_PATHS == module.REVIEWER_CREDENTIAL_PATHS
    assert D.SHARED_ROOTS == module.REVIEWER_SHARED_ROOTS
    assert D.toolchain_paths("/opt/homebrew/bin/cargo")[0] == Path("/opt/homebrew/bin")


def _vendored_crate(root: Path, value: int) -> None:
    crate = root / "inertdep"
    (crate / "src").mkdir(parents=True)
    (crate / "Cargo.toml").write_text(
        '[package]\nname = "inertdep"\nversion = "0.1.0"\nedition = "2021"\n', encoding="utf-8",
    )
    (crate / "src" / "lib.rs").write_text(f"pub fn two() -> i32 {{ {value} }}\n", encoding="utf-8")
    (crate / ".cargo-checksum.json").write_text(
        json.dumps({"files": {}, "package": "ab" * 32}), encoding="utf-8",
    )


def hostile_project(root: Path) -> Path:
    """A crate whose own ``.cargo/config.toml`` replaces crates.io with its own ``inertdep``."""
    project = root / "project"
    (project / "src").mkdir(parents=True)
    (project / ".cargo").mkdir()
    (project / "Cargo.toml").write_text(
        '[package]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n'
        '\n[dependencies]\ninertdep = "0.1"\n', encoding="utf-8",
    )
    (project / "Cargo.lock").write_text(
        'version = 4\n\n[[package]]\nname = "example"\nversion = "0.1.0"\n'
        'dependencies = ["inertdep"]\n'
        f'\n[[package]]\nname = "inertdep"\nversion = "0.1.0"\nsource = "{CRATES_IO}"\n'
        f'checksum = "{"ab" * 32}"\n', encoding="utf-8",
    )
    (project / ".cargo" / "config.toml").write_text(
        '[source.crates-io]\nreplace-with = "planted"\n\n[source.planted]\ndirectory = "planted"\n',
        encoding="utf-8",
    )
    _vendored_crate(project / "planted", 99)
    (project / "src" / "main.rs").write_text(
        'fn main() { println!("VALUE {}", inertdep::two()); }\n', encoding="utf-8",
    )
    return project


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo is not installed")
def test_live_the_shim_outranks_a_commit_s_own_source_replacement(tmp_path: Path) -> None:
    """Real cargo, offline: the commit replaces crates.io; the vendored crate still wins."""
    vendor = tmp_path / "vendor"
    _vendored_crate(vendor, 2)
    project = hostile_project(tmp_path)
    home = tmp_path / "home"
    shim = D.write_cargo_home(home, vendor, shutil.which("cargo"))
    assert shim is not None
    # A fresh HOME, as finish gives its re-run: rustup's toolchain comes from rustup_env().
    env = {"PATH": os.environ["PATH"], "HOME": str(_fresh(tmp_path / "h")),
           "CARGO_HOME": str(home), "CARGO_NET_OFFLINE": "true",
           "CARGO_TARGET_DIR": str(tmp_path / "target"), **D.rustup_env()}
    through = subprocess.run([str(shim), "run", "-q", "--offline"], cwd=project, env=env,
                             capture_output=True, text=True, timeout=300, check=False)
    assert through.stdout.strip() == "VALUE 2", through.stderr
    # The control: plain cargo with the same home takes the commit's replacement.
    plain = subprocess.run(["cargo", "run", "-q", "--offline"], cwd=project, env=env,
                           capture_output=True, text=True, timeout=300, check=False)
    assert plain.stdout.strip() == "VALUE 99", plain.stderr


# --- Python: packages in the packet, an environment saga writes ----------------------------------


def _load_support(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"saga_tests_{name}", Path(__file__).resolve().parent / "support" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_FAKE = _load_support("fake_uv")
FakeUv = _FAKE.FakeUv
_HASH_A = _FAKE.HASH_A
_EXPORTED = _FAKE.EXPORTED
_PYTEST = _FAKE.PYTEST
_LOCKED = {"pyproject.toml": '[project]\nname = "example"\nversion = "0.1.0"\n',
           "uv.lock": "version = 1\n"}


def _python(tmp_path: Path, uv: Any, tree: dict[str, str],
            symlinked: tuple[str, ...] = ()) -> tuple[dict[str, Any], Path]:
    packet = tmp_path / "packet"
    packet.mkdir(parents=True, exist_ok=True)
    uv.names = tuple(sorted(tree)) + tuple(f"{name}@" for name in symlinked)
    record = D.fetch(uv, tmp_path, "HEAD", packet, _export_from(tree))
    (packet / D.FILE).write_text(json.dumps(record), encoding="utf-8")
    return record, packet


def _packet_contents(packet: Path) -> dict[str, Any]:
    return {
        path.relative_to(packet).as_posix(): (
            os.readlink(path) if path.is_symlink() else path.read_bytes()
        )
        for path in sorted(packet.rglob("*")) if path.is_symlink() or path.is_file()
    }


def test_a_locked_head_gets_its_packages_and_pytest_and_no_interpreter_or_scripts(
    tmp_path: Path,
) -> None:
    uv = FakeUv(exported=_EXPORTED, compiled=_PYTEST)
    record, packet = _python(tmp_path, uv, _LOCKED)
    entry = record["python"]
    assert entry["state"] == "installed" and entry["missing"] == []
    assert entry["directory"] == "dependencies/python/site-packages"
    assert entry["source"] == "uv.lock" and entry["pytest"] == "added"
    assert [item["name"] for item in entry["packages"]] == ["inertdep", "otherdep", "pytest"]
    assert entry["interpreter"] == {
        "version": D.interpreter_version(str(shutil.which("python3")))}
    export = next(call["argv"] for call in uv.calls if call["argv"][1] == "export")
    assert {"--frozen", "--all-packages", "--all-groups", "--all-extras",
            "--no-emit-project"} <= set(export)
    site = packet / "dependencies" / "python" / "site-packages"
    assert not (site / ".lock").exists() and not (site / "bin").exists()
    assert not (packet / "dependencies" / "python" / "bin").exists()
    assert not list(packet.rglob("pyvenv.cfg")), "the packet holds no environment of its own"
    deps = D.python_environment(packet)
    assert deps is not None and deps.site == site.resolve()
    text = json.dumps(record)
    assert str(tmp_path) not in text
    for call in uv.calls:
        assert call["argv"][1] != "venv"
        if call["argv"][1:3] in (["pip", "install"], ["pip", "compile"]):
            python = call["argv"][call["argv"].index("--python") + 1]
            assert not Path(python).is_relative_to(packet), "never the packet's interpreter"
        assert Path(call["env"]["HOME"]).name == "home"
        assert call["env"]["UV_PYTHON_DOWNLOADS"] == "never"
    install = next(call["argv"] for call in uv.calls if call["argv"][1:3] == ["pip", "install"])
    expected = "clone" if sys.platform == "darwin" else "copy"
    assert install[install.index("--link-mode") + 1] == expected


def _shared_install(tmp_path: Path, reverse: bool) -> tuple[dict[str, Any], Path]:
    uv = FakeUv(exported=_EXPORTED, compiled=_PYTEST,
                shared=frozenset({"inertdep", "otherdep"}), reverse=reverse)
    return _python(tmp_path / ("reverse" if reverse else "forward"), uv, _LOCKED)


def test_a_file_two_wheels_ship_is_the_same_whatever_order_they_install_in(
    tmp_path: Path,
) -> None:
    forward, forward_packet = _shared_install(tmp_path, reverse=False)
    backward, backward_packet = _shared_install(tmp_path, reverse=True)
    assert _packet_contents(forward_packet) == _packet_contents(backward_packet)
    shared = forward_packet / D.PYTHON_DIRECTORY / "sharedpkg" / "__init__.py"
    # The distribution whose name sorts last keeps its copy.
    assert shared.read_text(encoding="utf-8") == "SHIPPED_BY = 'otherdep'\n"
    note = [{"names": ["inertdep", "otherdep"], "kept": "otherdep", "rule": "name-sorts-last",
             "files": 1}]
    assert forward["python"]["overlaps"] == backward["python"]["overlaps"] == note
    assert forward["python"]["state"] == "installed"
    assert str(tmp_path) not in json.dumps(forward) and "sharedpkg" not in json.dumps(forward)


def test_without_the_overlap_rule_the_two_orders_differ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control: the fake really does leave the last installed copy behind."""
    monkeypatch.setattr(D, "_resolve_overlaps", lambda *args: [])
    _record, forward = _shared_install(tmp_path, reverse=False)
    _record, backward = _shared_install(tmp_path, reverse=True)
    assert _packet_contents(forward) != _packet_contents(backward)


def test_a_head_whose_wheels_share_no_file_gets_no_overlap_note(tmp_path: Path) -> None:
    uv = FakeUv(exported=_EXPORTED, compiled=_PYTEST)
    record, _packet = _python(tmp_path, uv, _LOCKED)
    assert "overlaps" not in record["python"]
    installs = [call for call in uv.calls if call["argv"][1:3] == ["pip", "install"]]
    assert len(installs) == 1


def test_an_overlap_the_kept_distribution_does_not_ship_alone_stops_the_install(
    tmp_path: Path,
) -> None:
    class Lying(FakeUv):
        def _install(self, command: list[str]) -> Any:
            result = super()._install(command)
            target = Path(command[command.index("--target") + 1])
            if target.name == "overlap":
                (target / "sharedpkg" / "__init__.py").unlink()
            return result

    uv = Lying(exported=_EXPORTED, compiled=_PYTEST, shared=frozenset({"inertdep", "otherdep"}))
    record, packet = _python(tmp_path, uv, _LOCKED)
    assert record["python"] == {"state": "not-installed", "reason": "overlap-unresolved"}
    assert not (packet / D.PYTHON_DIRECTORY).exists()


def test_a_malformed_record_row_is_skipped_never_an_error(tmp_path: Path) -> None:
    site = tmp_path / "site"
    for name in ("alpha", "zeta"):
        info = site / f"{name}-1.0.dist-info"
        info.mkdir(parents=True)
        (info / "RECORD").write_text(
            '"",,\n.,,\n./,,\n/etc/passwd,,\n../outside,,\nbin/tool,,\na/../b,,\n'
            'back\\slash,,\n\n,\n'
            f"{name}-1.0.dist-info/METADATA,,\nshared/x.py,sha256=abc,1\n", "utf-8")
    broken = site / "broken-1.0.dist-info"
    broken.mkdir()
    (broken / "RECORD").write_bytes(b"\xff\xfe not text\nshared/x.py,,\n")
    assert D._claims(site) == {"shared/x.py": D._Overlap(("shared/x.py",), ("alpha", "zeta"))}
    for row in ([], [""], ["."], ["a\0b"], [None], ["x.dist-info/RECORD"]):
        assert D._record_path(row) is None
    # Only the step that tells uv's own folders from shipped ones reads .dist-info rows.
    assert D._record_path(["x.dist-info/RECORD"], dist_info=True) == "x.dist-info/RECORD"


def _site_with_records(site: Path, records: dict[str, str]) -> Path:
    for folder, text in records.items():
        (site / folder).mkdir(parents=True)
        (site / folder / "RECORD").write_text(text, "utf-8")
    return site


def test_two_spellings_of_one_path_are_one_overlap(tmp_path: Path) -> None:
    nfd = "cafe\u0301/x.py"
    site = _site_with_records(tmp_path / "site", {
        "alpha-1.0.dist-info": f"Foo/x.py,,\n{nfd},,\n",
        "zeta-1.0.dist-info": "foo/x.py,,\ncaf\u00e9/x.py,,\n",
    })
    assert D._claims(site) == {
        "caf\u00e9/x.py": D._Overlap(tuple(sorted(["caf\u00e9/x.py", nfd])), ("alpha", "zeta")),
        "foo/x.py": D._Overlap(("Foo/x.py", "foo/x.py"), ("alpha", "zeta")),
    }


@pytest.mark.parametrize("reverse", [False, True])
def test_wheels_that_ship_one_path_in_two_cases_stop_the_install_in_either_order(
    tmp_path: Path, reverse: bool,
) -> None:
    uv = FakeUv(exported=_EXPORTED, compiled=_PYTEST, reverse=reverse,
                ships={"inertdep": {"Shared/x.py": "A = 1\n"},
                       "otherdep": {"shared/x.py": "B = 1\n"}})
    record, packet = _python(tmp_path, uv, _LOCKED)
    assert record["python"] == {"state": "not-installed", "reason": "overlap-unresolved"}
    assert not (packet / D.PYTHON_DIRECTORY).exists()


def test_a_dist_info_folder_a_wheel_ships_cannot_claim_a_file(tmp_path: Path) -> None:
    fake = "inertdep/__init__.py,,\nsharedpkg/__init__.py,,\n"
    uv = FakeUv(exported=_EXPORTED, compiled=_PYTEST, ships={"inertdep": {
        # Named for an installed distribution, and for one that is not installed at all.
        "otherdep-9.0.dist-info/RECORD": fake, "zzz_injected-1.0.dist-info/RECORD": fake,
    }})
    record, packet = _python(tmp_path, uv, _LOCKED)
    assert record["python"]["state"] == "installed"
    assert "overlaps" not in record["python"]
    site = packet / D.PYTHON_DIRECTORY
    assert (site / "zzz_injected-1.0.dist-info" / "RECORD").is_file()
    assert D._claims(site) == {}


def test_the_overlap_install_counts_toward_the_byte_limit(tmp_path: Path) -> None:
    uv = FakeUv(exported=_EXPORTED, compiled=_PYTEST, shared=frozenset({"inertdep", "otherdep"}))
    record, _packet = _python(tmp_path, uv, _LOCKED)
    assert record["python"]["overlaps"]
    installs = [argv for argv in uv.raw if argv[argv.index("--") + 1:][1:3] == ["pip", "install"]]
    overlap = next(argv for argv in installs
                   if Path(argv[argv.index("--target") + 1]).name == "overlap")
    watched = [Path(argv) for flag, argv in zip(overlap, overlap[1:]) if flag == "--watch"]
    assert Path(overlap[overlap.index("--target") + 1]) in watched
    assert any(path.as_posix().endswith(D.PYTHON_DIRECTORY) for path in watched)


class _Reshaped(FakeUv):
    """After the main install, turns the shared file into *shape*, or fails the copy."""

    shape = "directory"

    def _install(self, command: list[str]) -> Any:
        result = super()._install(command)
        target = Path(command[command.index("--target") + 1])
        shared = target / "sharedpkg" / "__init__.py"
        if target.name != "overlap" and shared.exists():
            shared.unlink()
            if self.shape == "directory":
                shared.mkdir()
                (shared / "inside").write_text("x\n", "utf-8")
            elif self.shape == "symlink":
                shared.symlink_to(target.parent / "elsewhere")
            elif self.shape == "linked-folder":
                # A folder above the file is a link to another folder inside the install.
                shared.write_text("loser\n", "utf-8")
                (target / "sharedpkg").rename(target / "sharedpkg_real")
                (target / "sharedpkg").symlink_to(target / "sharedpkg_real")
        return result


@pytest.mark.parametrize("shape", ["directory", "symlink", "linked-folder"])
def test_an_overlap_whose_destination_is_not_a_plain_file_stops_the_install(
    tmp_path: Path, shape: str,
) -> None:
    uv = _Reshaped(exported=_EXPORTED, compiled=_PYTEST,
                   shared=frozenset({"inertdep", "otherdep"}))
    uv.shape = shape
    elsewhere = tmp_path / "packet" / "dependencies" / "python" / "elsewhere"
    record, packet = _python(tmp_path, uv, _LOCKED)
    assert record["python"] == {"state": "not-installed", "reason": "overlap-unresolved"}
    assert not (packet / D.PYTHON_DIRECTORY).exists() and not elsewhere.exists()


def test_an_error_while_copying_an_overlap_stops_the_install_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(D.shutil, "copyfile", broken)
    uv = FakeUv(exported=_EXPORTED, compiled=_PYTEST, shared=frozenset({"inertdep", "otherdep"}))
    record, packet = _python(tmp_path, uv, _LOCKED)
    assert record["python"] == {"state": "not-installed", "reason": "overlap-unresolved"}
    assert not (packet / D.PYTHON_DIRECTORY).exists()


def test_an_overlap_origin_outside_the_lone_install_is_refused(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    (source / "pkg").mkdir(parents=True)
    (target / "pkg").mkdir(parents=True)
    (tmp_path / "secret").write_text("secret\n", "utf-8")
    (source / "pkg" / "x.py").symlink_to(tmp_path / "secret")
    (target / "pkg" / "x.py").write_text("kept\n", "utf-8")
    with pytest.raises(D._PythonFailure, match="overlap-unresolved"):
        D._replace_file(source, source / "pkg" / "x.py", target, target / "pkg" / "x.py")
    with pytest.raises(D._PythonFailure, match="overlap-unresolved"):
        D._replace_file(source, tmp_path / "secret", target, target / "pkg" / "x.py")
    assert (target / "pkg" / "x.py").read_text(encoding="utf-8") == "kept\n"


def test_a_lock_that_declares_pytest_installs_no_second_one(tmp_path: Path) -> None:
    uv = FakeUv(exported=_EXPORTED + _PYTEST)
    record, _packet = _python(tmp_path, uv, _LOCKED)
    assert record["python"]["pytest"] == "declared"
    assert not any(call["argv"][1:3] == ["pip", "compile"] for call in uv.calls)


def test_an_sdist_only_dependency_is_missing_with_a_fixed_reason_and_nothing_builds(
    tmp_path: Path,
) -> None:
    exported = _EXPORTED + f"docopt==0.6.2 \\\n    {_HASH_A}\n"
    uv = FakeUv(exported=exported, compiled=_PYTEST, sdist_only=frozenset({"docopt"}))
    record, packet = _python(tmp_path, uv, _LOCKED)
    entry = record["python"]
    assert entry["state"] == "partial"
    assert entry["missing"] == [{"name": "docopt", "reason": "no-wheel"}]
    assert [item["name"] for item in entry["packages"]] == ["inertdep", "otherdep", "pytest"]
    assert D.python_environment(packet) is not None, "partial packages are still used"
    for call in uv.calls:
        if call["argv"][1:3] in (["pip", "install"], ["pip", "compile"]):
            assert "--no-build" in call["argv"]


def test_a_network_failure_is_not_installed_not_a_missing_package(tmp_path: Path) -> None:
    uv = FakeUv(exported=_EXPORTED, compiled=_PYTEST,
                fail_install="error: Failed to fetch: `https://pypi.org/simple/inertdep/`\n")
    record, packet = _python(tmp_path, uv, _LOCKED)
    assert record["python"] == {"state": "not-installed", "reason": "network"}
    assert not (packet / "dependencies").exists() or not any(
        (packet / "dependencies").rglob("*.dist-info"))


def test_requirements_reach_uv_only_as_plain_lines(tmp_path: Path) -> None:
    """An index option and a -r of an operator file would send that file's text to a server."""
    secret = tmp_path / "operator-token"
    secret.write_text("inert-example-token\n", encoding="utf-8")
    tree = {
        "requirements.txt": (
            "--index-url http://127.0.0.1:9/simple\n"
            f"-r {secret}\n-c {secret}\n--extra-index-url=http://127.0.0.1:9/x\n-e .\n"
            "evil @ https://127.0.0.1:9/evil.whl\nlocal @ file:///etc/passwd\n./folder\n"
            "inertdep>=1.0 ; python_version >= '3.8'  # a comment\n"
            "otherdep[extra]==2.0\n"
            "six ; python_version > '3' -r token\n"
            "six2 ; python_version > '3' --index-url evil\n"
        ),
    }
    compiled = (f"inertdep==1.0.0 \\\n    {_HASH_A}\notherdep==2.0.0 \\\n    {_HASH_A}\n"
                + _PYTEST)
    uv = FakeUv(compiled=compiled)
    record, _packet = _python(tmp_path, uv, tree)
    entry = record["python"]
    assert entry["state"] == "installed"
    assert entry["dropped"] == {"options": 5, "references": 3, "unparsed": 2}
    given = "".join(uv.inputs)
    for word in ("127.0.0.1", str(secret), "inert-example-token", "file:", "-r", "--index"):
        assert word not in given, word
    assert "inertdep>=1.0 ; python_version >= '3.8'" in given
    assert "six" not in given and "evil" not in given
    assert "otherdep[extra]==2.0" in given
    for call in uv.calls:
        assert not any(str(secret) in part for part in call["argv"])


def test_an_exported_lock_s_index_and_url_lines_are_dropped(tmp_path: Path) -> None:
    exported = ("--index-url http://127.0.0.1:9/simple\n" + _EXPORTED
                + "evil @ https://127.0.0.1:9/evil.whl \\\n    " + _HASH_A + "\n")
    uv = FakeUv(exported=exported, compiled=_PYTEST)
    record, _packet = _python(tmp_path, uv, _LOCKED)
    assert record["python"]["dropped"] == {"options": 1, "references": 1}
    assert "127.0.0.1" not in "".join(uv.inputs)


def test_uv_s_own_words_never_reach_the_record(tmp_path: Path) -> None:
    uv = FakeUv(exported=_EXPORTED, compiled=_PYTEST,
                fail_install="error: inert-example-token is not a valid package\n")
    record, _packet = _python(tmp_path, uv, _LOCKED)
    assert "inert-example-token" not in json.dumps(record)
    assert record["python"]["reason"] in D.REASONS


def test_an_unlocked_head_resolves_as_of_its_commit_and_sets_aside_an_sdist(
    tmp_path: Path,
) -> None:
    tree = {
        "pyproject.toml": '[project]\nname = "example"\nversion = "0.1.0"\n'
                          'dependencies = ["inertdep", "docopt"]\n'
                          '[dependency-groups]\ntest = ["pytest"]\ndev = ["otherdep"]\n',
        "requirements-dev.txt": "-e .\notherdep\n",
    }
    compiled = (f"inertdep==1.0.0 \\\n    {_HASH_A}\ndocopt==0.6.2 \\\n    {_HASH_A}\n"
                + _PYTEST)
    uv = FakeUv(compiled=compiled, sdist_only=frozenset({"docopt"}))
    record, _packet = _python(tmp_path, uv, tree)
    entry = record["python"]
    assert entry["source"] == "pyproject.toml requirements-dev.txt"
    assert entry["pytest"] == "declared"
    assert entry["state"] == "partial"
    assert entry["missing"] == [{"name": "docopt", "reason": "no-wheel"}]
    compiles = [call["argv"] for call in uv.calls if call["argv"][1:3] == ["pip", "compile"]]
    assert len(compiles) == 2 and "--overrides" in compiles[1]
    assert not any(part.endswith("pyproject.toml") for part in compiles[0]), "saga reads it"


def test_dynamic_dependencies_fall_back_to_the_requirements_files(tmp_path: Path) -> None:
    tree = {
        "pyproject.toml": '[project]\nname = "example"\nversion = "0.1.0"\n'
                          'dynamic = ["dependencies"]\n',
        "requirements.txt": "inertdep\n",
    }
    uv = FakeUv(compiled=f"inertdep==1.0.0 \\\n    {_HASH_A}\n" + _PYTEST)
    record, _packet = _python(tmp_path, uv, tree)
    assert record["python"]["source"] == "requirements.txt"
    assert record["python"]["dropped"] == {"dynamic": 1}
    assert "inertdep" in uv.inputs[0]


@pytest.mark.parametrize(("tree", "symlinked", "reason"), [
    ({"uv.lock": "version = 1\n"}, (), "lock-without-pyproject"),
    ({"pyproject.toml": "[project]\n"}, ("requirements.txt",), "symlinked-input"),
])
def test_an_unusable_python_head_is_recorded_not_installed(
    tmp_path: Path, tree: dict[str, str], symlinked: tuple[str, ...], reason: str,
) -> None:
    uv = FakeUv()
    record, _packet = _python(tmp_path, uv, tree, symlinked)
    assert record["python"] == {"state": "not-installed", "reason": reason}
    assert uv.calls == []


def test_a_python_project_only_in_a_subfolder_is_recorded(tmp_path: Path) -> None:
    uv = FakeUv()
    record, _packet = _python(tmp_path, uv, {"README.md": "x\n", "tools/pyproject.toml": "x"})
    assert record["python"] == {"state": "not-installed", "reason": "subfolder-project",
                                "projects": ["tools"]}
    assert uv.calls == []


@pytest.mark.parametrize("line", [
    "six ; python_version > '3' -r token",
    "six2 ; python_version > '3' --index-url evil",
    "six3 ; os_name == 'posix' -c /etc/passwd",
    "six4 ; unknown_variable == '1'",
    "six5 ;",
])
def test_a_marker_that_is_not_marker_grammar_drops_the_line(line: str) -> None:
    dropped: dict[str, int] = {}
    assert D._plain(line, dropped, hashes=False) is None
    assert sum(dropped.values()) == 1, dropped


@pytest.mark.parametrize("line", [
    "inertdep>=1.0 ; python_version >= '3.8'",
    "a==1 ; (sys_platform == 'linux' and extra == \"x\") or python_full_version < '3.10'",
    "b[x,y]~=2.1 ; platform_machine not in 'arm64 aarch64'",
])
def test_a_real_marker_keeps_the_line(line: str) -> None:
    assert D._plain(line, {}, hashes=False) is not None


def test_only_safe_subfolder_names_reach_the_record(tmp_path: Path) -> None:
    """Folder names come from the reviewed repository; one with a newline or a control
    character is left out, and the list is capped."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    names = ["tools", "evil\nline", "bell\x07name", "esc\x1b[31m", "quote\"d",
             *[f"pkg{n:02d}" for n in range(30)]]
    for name in names:
        (repo / name).mkdir()
        (repo / name / "pyproject.toml").write_text("[project]\n", "utf-8")
    (repo / "README.md").write_text("x\n", "utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "head"], cwd=repo, check=True)

    def runner(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
               umask: int | None = None) -> Any:
        proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=timeout, check=False)
        return _Result(proc.returncode, proc.stdout, proc.stderr)

    packet = tmp_path / "packet"
    packet.mkdir()
    entry = D._python_entry(runner, repo, "HEAD", packet, _export_from({}))
    assert entry is not None and entry["reason"] == "subfolder-project"
    projects = entry["projects"]
    assert len(projects) == 20
    assert projects[0] == "pkg00" and "tools" not in projects[:19]
    for name in projects:
        assert re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", name), name
    text = json.dumps(entry)
    for bad in ("evil", "bell", "esc", "quote"):
        assert bad not in text


def test_only_unsafe_subfolder_names_still_record_a_subfolder_project(tmp_path: Path) -> None:
    uv = FakeUv()
    record, _packet = _python(tmp_path, uv, {"README.md": "x\n", "bell\x07/pyproject.toml": "x"})
    assert record["python"] == {"state": "not-installed", "reason": "subfolder-project",
                                "projects": []}


def test_a_head_without_python_files_gets_no_python_entry(tmp_path: Path) -> None:
    uv = FakeUv()
    record, packet = _python(tmp_path, uv, {"README.md": "x\n", "src/app.py": "x = 1\n"})
    assert record == {"schema": D.SCHEMA}
    assert uv.calls == [] and not (packet / "dependencies").exists()


def test_two_installs_of_one_head_write_the_same_bytes(tmp_path: Path) -> None:
    trees = []
    for attempt in (1, 2):
        uv = FakeUv(exported=_EXPORTED, compiled=_PYTEST)
        record, packet = _python(tmp_path / str(attempt), uv, _LOCKED)
        trees.append((record, _packet_contents(packet)))
    assert trees[0] == trees[1]


@pytest.mark.parametrize("entry", [
    {"state": "not-installed", "reason": "network"},
    {"state": "installed", "directory": "/etc", "interpreter": {"version": "3.12.0"}},
    {"state": "installed", "directory": "../elsewhere", "interpreter": {"version": "3.12.0"}},
    {"state": "installed", "directory": "dependencies/missing",
     "interpreter": {"version": "3.12.0"}},
    {"state": "installed", "directory": "dependencies/python/site-packages"},
])
def test_an_untrustworthy_python_entry_is_ignored(tmp_path: Path, entry: Any) -> None:
    packet = tmp_path / "packet"
    (packet / "dependencies" / "python" / "site-packages").mkdir(parents=True)
    (packet / D.FILE).write_text(json.dumps({"schema": D.SCHEMA, "python": entry}), "utf-8")
    assert D.python_environment(packet) is None


def test_a_symlinked_site_packages_is_ignored(tmp_path: Path) -> None:
    packet = tmp_path / "packet"
    (packet / "dependencies" / "python").mkdir(parents=True)
    (packet / "dependencies" / "python" / "site-packages").symlink_to(tmp_path)
    (packet / D.FILE).write_text(json.dumps({"schema": D.SCHEMA, "python": {
        "state": "installed", "directory": "dependencies/python/site-packages",
        "interpreter": {"version": "3.12.0"}}}), "utf-8")
    assert D.python_environment(packet) is None


def test_the_shim_holds_only_python_and_imports_the_packet_s_packages(tmp_path: Path) -> None:
    site = tmp_path / "packet" / "site-packages"
    (site / "inertdep").mkdir(parents=True)
    (site / "inertdep" / "__init__.py").write_text("def two():\n    return 2\n", "utf-8")
    (site / "bin").mkdir()
    (site / "bin" / "git").write_text("#!/bin/sh\necho planted\n", "utf-8")
    python = str(shutil.which("python3"))
    version = D.interpreter_version(python)
    assert version is not None
    deps = D.PythonDependencies(site=site, version=version)
    shim = D.write_python_shim(tmp_path / "shim", deps, python)
    assert shim is not None
    assert sorted(item.name for item in (shim / "bin").iterdir()) == ["python", "python3"]
    env = {**D.python_shim_env(shim, "/usr/bin:/bin"), "HOME": str(tmp_path)}
    assert shutil.which("git", path=env["PATH"]) != str(site / "bin" / "git")
    ran = subprocess.run(["python3", "-c", "import sys, inertdep; print(inertdep.two(), "
                          "sys.prefix)"], env=env, capture_output=True, text=True, check=False)
    assert ran.stdout.split() == ["2", str(shim)], ran.stderr
    wrong = D.PythonDependencies(site=site, version="2.7.18")
    assert D.write_python_shim(tmp_path / "other", wrong, python) is None


def test_the_interpreter_install_under_a_credential_path_is_not_given_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    install = home / ".aws" / "python"
    (install / "bin").mkdir(parents=True)
    (install / "lib").mkdir()
    (install / "bin" / "python3.12").write_text("", "utf-8")
    monkeypatch.setenv("HOME", str(home))
    shim, site = tmp_path / "shim", tmp_path / "site"
    (shim / "bin").mkdir(parents=True)
    site.mkdir()
    deps = D.PythonDependencies(site=site, version="3.12.0")
    (shim / "bin" / "python3").symlink_to(install / "bin" / "python3.12")
    assert D.python_toolchain(shim, deps) == (shim, site.resolve())


def _wheel(folder: Path, name: str, files: dict[str, str]) -> tuple[Path, str]:
    """A hand-written wheel, so the test needs no network and builds nothing."""
    import base64  # noqa: PLC0415
    import hashlib  # noqa: PLC0415
    import zipfile  # noqa: PLC0415

    info = f"{name}-1.0.dist-info"
    files = {
        **files,
        f"{info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n",
        f"{info}/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
                         "Tag: py3-none-any\n",
    }
    record = ""
    for path, text in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()).rstrip(b"=")
        record += f"{path},sha256={digest.decode()},{len(text.encode())}\n"
    files[f"{info}/RECORD"] = record + f"{info}/RECORD,,\n"
    wheel = folder / f"{name}-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, text in files.items():
            archive.writestr(path, text)
    return wheel, hashlib.sha256(wheel.read_bytes()).hexdigest()


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_live_no_pth_file_runs_during_prepare_even_without_uv_s_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wheel's .pth runs when an interpreter starts over its folder; prepare starts none.

    The retry path runs too: a second package is not in the local index, so the one
    transaction fails and each package is tried on its own.
    """
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    marker = tmp_path / "pth-ran"
    _wheel_path, digest = _wheel(wheels, "markerpkg", {
        "markerpkg/__init__.py": "VALUE = 2\n",
        "markerpkg.pth": f"import pathlib; pathlib.Path({str(marker)!r}).write_text('ran')\n",
    })
    monkeypatch.setitem(D._PYTHON_ENV_FLAGS, "UV_NO_CACHE", "1")
    monkeypatch.setitem(D._PYTHON_ENV_FLAGS, "UV_NO_INDEX", "1")
    monkeypatch.setitem(D._PYTHON_ENV_FLAGS, "UV_FIND_LINKS", str(wheels))
    work = tmp_path / "work"
    work.mkdir()

    def runner(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
               umask: int | None = None) -> Any:
        proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=timeout, check=False)
        return _Result(proc.returncode, proc.stdout, proc.stderr)

    env = D._uv_env(work)
    target = tmp_path / "packet" / "site-packages"
    uv = D._Uv(runner, work, env, [target], time.monotonic() + 300)
    entries = {"markerpkg": f"markerpkg==1.0 --hash=sha256:{digest}",
               "absentpkg": f"absentpkg==1.0 --hash=sha256:{'cd' * 32}"}
    missing = D._install_set(uv, str(shutil.which("python3")), target, entries, work)
    assert [item["name"] for item in missing] == ["absentpkg"]
    assert missing[0]["reason"] in D.REASONS
    assert (target / "markerpkg.pth").is_file() and (target / "markerpkg").is_dir()
    assert not marker.exists(), "no interpreter started over the installed packages"


@pytest.mark.skipif(
    os.environ.get("SAGA_TEST_LIVE_UV") != "1" or shutil.which("uv") is None,
    reason="opt-in (SAGA_TEST_LIVE_UV=1): needs uv and the network",
)
def test_live_uv_installs_a_lock_twice_identically_and_sets_aside_an_sdist(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n'
        'dependencies = ["iniconfig==2.0.0", "docopt==0.6.2"]\n', encoding="utf-8")
    subprocess.run(["uv", "lock", "-q"], cwd=repo, check=True, timeout=300)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "head"], cwd=repo, check=True)

    def runner(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
               umask: int | None = None) -> Any:
        proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=timeout, check=False)
        return _Result(proc.returncode, proc.stdout, proc.stderr)

    def export(dest: Path) -> bool:
        archive = subprocess.run(["git", "archive", "HEAD"], cwd=repo, check=True,
                                 capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)
        return True

    packets = []
    for attempt in (1, 2):
        packet = tmp_path / f"packet-{attempt}"
        packet.mkdir()
        record = D.fetch(runner, repo, "HEAD", packet, export)
        packets.append((record, _packet_contents(packet)))
    assert packets[0] == packets[1]
    entry = packets[0][0]["python"]
    assert entry["state"] == "partial"
    assert entry["missing"] == [{"name": "docopt", "reason": "no-wheel"}]
    names = {item["name"] for item in entry["packages"]}
    assert {"iniconfig", "pytest"} <= names
    assert not any(str(tmp_path).encode() in value
                   for value in packets[0][1].values() if isinstance(value, bytes))
    assert not any(name.endswith("pyvenv.cfg") or "/bin/" in name for name in packets[0][1])
