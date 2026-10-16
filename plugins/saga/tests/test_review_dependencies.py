"""The head's dependencies, fetched once in prepare for an offline reviewer (issue 262)."""

from __future__ import annotations

import importlib.util
import json
import os
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
    assert D._bytes([tmp_path]) == 500
    assert D._bytes([tmp_path], limit=150) < 500
    assert D._bytes([tmp_path], deadline=time.monotonic() - 1) < 500


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
    assert calls == [["git", "cat-file", "-e", "HEAD:Cargo.toml"]]


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
