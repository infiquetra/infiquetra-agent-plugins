"""Verify Universal Ctags, or provision it through signed apt within CI budgets.

The caller also applies a 270s outer timeout and a five minute step deadline.
Each apt operation is capped at 90s, with one acquisition retry, 15s network
timeouts and a 15s lock wait. Failures remain fatal; there is no fallback binary.
The hard deadline kills the owned apt process group, including a TERM-resistant
child even when its parent exits first. Deliberately detached processes are
outside this contract; actual privileged-host qualification is separate.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SOURCES = {
    "Rust": ("rs", "fn ci_probe() {}\n"),
    "TypeScript": ("ts", "function ci_probe() {}\n"),
    "Sh": ("sh", "ci_probe() {\n  echo example\n}\n"),
}


def probe() -> bool:
    try:
        version = subprocess.run(
            ["ctags", "--options=NONE", "--version"],
            check=True, capture_output=True, text=True, timeout=5,
        ).stdout
        print(version, end="", flush=True)
        if not version.startswith("Universal Ctags "):
            raise ValueError("ctags is not Universal Ctags")
        # Exercise the same JSON/field/parser interface the real suite uses.
        # An identity string alone cannot prove a usable binary.
        with tempfile.TemporaryDirectory(prefix="ci-ctags-") as temporary:
            for language, (suffix, source) in SOURCES.items():
                path = Path(temporary) / f"probe.{suffix}"
                path.write_text(source, encoding="utf-8")
                output = subprocess.run(
                    ["ctags", "--options=NONE", "--output-format=json", "--fields=+ne",
                     f"--language-force={language}", "-o", "-", str(path)],
                    check=True, capture_output=True, text=True, timeout=5,
                ).stdout
                tags = [json.loads(line) for line in output.splitlines() if line.strip()]
                if any(not isinstance(tag, dict) for tag in tags):
                    raise ValueError(f"ctags {language} JSON records must be objects")
                if not any(tag.get("_type") == "tag" and tag.get("name") == "ci_probe"
                           and tag.get("line") == 1 for tag in tags):
                    raise ValueError(f"ctags {language} JSON/line probe failed")
        return True
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"Universal Ctags probe failed: {error}", file=sys.stderr, flush=True)
        return False


def main() -> int:
    if probe():
        return 0
    options = [
        "-o", "Acquire::Retries=1",
        "-o", "Acquire::http::Timeout=15",
        "-o", "Acquire::https::Timeout=15",
        "-o", "DPkg::Lock::Timeout=15",
        "-o", "Acquire::AllowInsecureRepositories=false",
        "-o", "APT::Get::AllowUnauthenticated=false",
    ]
    try:
        for operation in (["update", "--error-on=any"], ["install", "-y", "universal-ctags"]):
            # timeout runs under sudo too, so it can terminate apt and its
            # privileged descendants. Python's timeout is a second bound.
            subprocess.run(
                ["sudo", "-n", "timeout", "--signal=KILL", "90s",
                 "apt-get", *options, *operation], check=True, timeout=100,
            )
    except (OSError, subprocess.SubprocessError) as error:
        print(f"Universal Ctags provisioning failed: {error}", file=sys.stderr)
        return 1
    if not probe():
        print("Installed Universal Ctags did not pass the required feature probe", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
