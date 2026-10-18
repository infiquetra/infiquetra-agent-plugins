"""Finite, local-only parent/child fixture for tool lifetime regression tests."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def wait_for(path: Path) -> None:
    deadline = time.monotonic() + 10
    while not path.exists():
        if time.monotonic() > deadline:
            raise RuntimeError("fixture handshake timed out")
        time.sleep(0.01)


mode, directory = sys.argv[1:3]
root = Path(directory)
if mode == "child":
    def terminated(_signal: int, _frame: object) -> None:
        if sys.argv[3] in {"verbose", "invalid"}:
            sys.stdout.write("cleanup stdout\n" * 80000)
            sys.stdout.flush()
            sys.stderr.write("cleanup stderr\n" * 80000)
            sys.stderr.flush()
            if sys.argv[3] == "invalid":
                os.write(sys.stdout.fileno(), b"\xff")
                os.write(sys.stderr.fileno(), b"\xff")
        home = os.environ.get("CARGO_HOME")
        (root / "terminated.json").write_text(json.dumps({
            "home_exists": home is not None and Path(home).is_dir(),
        }))
        raise SystemExit(0)

    if sys.argv[3] == "stubborn":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    else:
        signal.signal(signal.SIGTERM, terminated)
    (root / "child-ready").write_text(str(os.getpid()))
    wait_for(root / "release-child")
    (root / "post-return-write").write_text("child ran")
elif mode in {"parent", "background"}:
    output = None if sys.argv[3] in {"verbose", "invalid"} else subprocess.DEVNULL
    subprocess.Popen(
        [sys.executable, __file__, "child", directory, sys.argv[3]],
        stdin=subprocess.DEVNULL, stdout=output, stderr=output,
    )
    wait_for(root / "child-ready")
    (root / "parent-ready").write_text(str(os.getpid()))
    print("partial stdout", flush=True)
    print("partial stderr", file=sys.stderr, flush=True)
    if mode == "parent":
        wait_for(root / "release-parent")
elif mode == "independent":
    (root / "independent-ready").touch()
    wait_for(root / "release-independent")
    print("independent completed")
elif mode == "prepare":
    # Exercise the production CLI boundary and runner with a synthetic operation,
    # without creating a real review, running Cargo, or calling a model.
    import shutil
    from types import SimpleNamespace

    sys.path.insert(0, sys.argv[3])
    import review_command as command

    def prepare(_args: object, **_kwargs: object) -> None:
        home = root / "prepare-home"
        home.mkdir()
        adapter = SimpleNamespace(id="fixture", local_bins=(), narrow_env=False,
                                  ambient_env=False, tool="fixture")

        def cargo(_argv: list[str], **kwargs: object) -> object:
            (root / "cargo-home-path").write_text(str(kwargs["env"]["CARGO_HOME"]))
            return command.review_tools.subprocess_runner(
                [sys.executable, __file__, "parent", directory, "stubborn"], **kwargs,
            )

        try:
            command.review_tools._execute(
                adapter, ["cargo-fixture"], root, cargo, dict(os.environ), 10,
            )
        finally:
            shutil.rmtree(home)
            (root / "prepare-cleaned").touch()

    command._prepare = prepare
    raise SystemExit(command._cli([
        "prepare", "--repo", directory, "--base", "base", "--head", "head",
        "--profile", "profile", "--builder-record", "builder", "--out", "out",
    ]))
