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
    subprocess.Popen(
        [sys.executable, __file__, "child", directory, sys.argv[3]],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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
