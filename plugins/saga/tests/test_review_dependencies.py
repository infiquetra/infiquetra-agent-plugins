"""The head's dependencies, fetched once in prepare for an offline reviewer (issue 262)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
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


class _Cargo:
    """git answers for real; cargo is recorded, and ``vendor`` writes one crate."""

    def __init__(self, *, vendor_code: int = 0) -> None:
        self.vendor_code = vendor_code
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int,
                 shell: bool) -> Any:
        assert shell is False
        if argv[0] == "git":
            proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                                  check=False)
            return _Result(proc.returncode, proc.stdout, proc.stderr)
        self.calls.append({
            "argv": list(argv), "cwd": Path(cwd), "env": dict(env),
            "listing": sorted(p.relative_to(cwd).as_posix() for p in Path(cwd).rglob("*")),
        })
        if argv[1] == "vendor" and self.vendor_code == 0:
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


def test_without_a_lock_the_lock_is_generated_first_then_checked(tmp_path: Path) -> None:
    class _Generates(_Cargo):
        def __call__(self, argv: list[str], **kwargs: Any) -> Any:
            if argv[1] == "generate-lockfile":
                (kwargs["cwd"] / "Cargo.lock").write_text(_lock(CRATES_IO), encoding="utf-8")
            return super().__call__(argv, **kwargs)

    record, cargo, _packet = _fetch(tmp_path, {"Cargo.toml": _ONE_DEP, "src/lib.rs": ""},
                                    _Generates())
    assert [call["argv"][1] for call in cargo.calls] == ["generate-lockfile", "vendor"]
    assert record["state"] == "fetched"


def test_a_lock_with_no_registry_package_fetches_nothing(tmp_path: Path) -> None:
    record, cargo, packet = _fetch(tmp_path, {"Cargo.toml": _MANIFEST, "Cargo.lock": _lock()})
    assert record == {"state": "no-dependencies"}
    assert cargo.calls == [] and not (packet / "dependencies").exists()


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
            if argv[0] == "cargo":
                self.calls.append(list(argv))
                argv = [*argv, "--offline"] if argv[1] == "generate-lockfile" else argv
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
    import tomllib  # noqa: PLC0415

    vendor = tmp_path / 'odd "name"'
    home = D.write_cargo_home(tmp_path / "home", vendor)
    config = home / "config.toml"
    parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    assert parsed["source"]["crates-io"] == {"replace-with": D.VENDORED_SOURCE}
    assert parsed["source"][D.VENDORED_SOURCE] == {"directory": str(vendor)}
    assert parsed["net"] == {"offline": True}
    assert not os.access(config, os.W_OK)
    assert tomllib.loads(D.cargo_config(None)) == {"net": {"offline": True}}
