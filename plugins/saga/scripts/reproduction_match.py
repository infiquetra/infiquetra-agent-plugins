#!/usr/bin/env python3
"""Does a re-run of a reproduction test fail the way the reviewer recorded (issue 264)?

``finish`` re-runs a reviewer's reproduction in a confined copy of the head and asks whether it
failed with the recorded failure. A test id such as ``tests/test_x.py::test_y`` is a pytest
spelling. Every other runner prints its failures its own way: cargo prints ``test name ...
FAILED`` and a ``---- name stdout ----`` block, Vitest prints ``FAIL file > suite > name``, Go
prints ``--- FAIL: TestName``. So the test is looked for in each runner's own failure lines, and
the recorded failure line is looked for in that test's own failure block.

Both sides are compared after ignoring what changes between two runs of the same failure: colour
codes, thread ids, timings, memory addresses, time stamps and the directory a path sits in.

The matcher recognises these runners, each from output captured from the real runner: cargo test
and cargo nextest, pytest, unittest, Vitest, Jest, go test, dart test, and swift test (XCTest and
Swift Testing). Output it does not recognise falls back to the older rule: the recorded failure
line has to appear in the re-run, and a test id written as ``file::name`` has to appear word for
word.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

_ANSI = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\([A-Za-z0-9]|\][^\x07\x1b]{0,256}(?:\x07|\x1b\\))")
_THREAD_ID = re.compile(r"(thread '[^']*') \(\d+\)")
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{4,}")
_STAMP = re.compile(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:\.\d+)?")
_DART_CLOCK = re.compile(r"^\d+:\d\d(?::\d\d)? [+~-]\d+(?: [+~-]\d+)*: ")
_DURATION = re.compile(r"(?<![\w.])\d+(?:\.\d+)?\s?(?:ms|µs|us|ns|seconds?|secs?|s)\b")
_ABSOLUTE_DIRECTORY = re.compile(r"(?<![\w./~-])(?:/[\w.+@~-]+)+/(?=[\w.+@~-])")
_PLACEHOLDER = re.compile(r"<[A-Za-z][\w -]{0,15}>")
_LONG_NUMBER = re.compile(r"\d{5,}")
_BLANKS = re.compile(r"\s+")
_DOTTED = re.compile(r"\w+(?:\.\w+)+")
_SEPARATORS = re.compile(r"::|/| > |›|>")
_CAPTURE_LIMIT = 400_000
_LINE_COUNT_LIMIT = 20_000
_LINE_LIMIT = 200

_GENERIC_PREFIXES = (
    "Traceback (most recent call last):",
    "During handling of the above exception, another exception occurred:",
    "The above exception was the direct cause of the following exception:",
    "INTERNALERROR",
    "====", "----", "++++",
    # cargo test and cargo nextest
    "test result:", "error: test failed", "error: could not", "running ", "failures:",
    "note: run with", "Finished ", "Compiling ", "Running ", "Doc-tests", "Blocking ",
    "Nextest run ID", "Starting ", "Summary [", "FAIL [", "PASS [", "SLOW [", "Cancelling",
    "stdout ", "stderr ",
    # pytest and unittest
    "collected ", "rootdir:", "platform ", "plugins:", "configfile:", "Ran ", "FAILED (",
    # Vitest and Jest
    "Test Files", "Tests ", "Tests:", "Test Suites:", "Snapshots:", "Time:", "Duration",
    "Start at", "RUN ", "Ran all test suites",
    # go test
    "FAIL\t", "ok  \t",
    # dart test
    "Failing tests:", "Some tests failed", "Consider enabling", "For example, 'dart",
    # swift test
    "Test Suite ", "Executed ", "Build complete", "Building for", "Test run ", "Note: Some",
    "◇", "✔", "↳ Testing Library", "↳ Target Platform",
)
_GENERIC_EXACT = frozenset({"FAIL", "PASSED", "FAILED"})
_GENERIC_PATTERNS = (
    re.compile(r"^\d+ (?:failed|passed|errors?|skipped|xfailed|xpassed|warnings?|deselected)\b"),
    re.compile(r"^test .* \.\.\. (?:ok|FAILED|ignored)\b"),
    re.compile(r"^--- (?:FAIL|PASS|SKIP): "),
    re.compile(r"^Test Case '.*' (?:started|passed|failed)"),
    re.compile(r"^(?:FAILED|ERROR) \S+::"),
    re.compile(r"^[\w./-]+\.(?:py|rs)\s+[.FEsxX]+(?: +\[ *\d+%\])?$"),
)


@dataclass(frozen=True)
class Failure:
    """One test that failed in a run: where it lives, its name, and its own failure lines."""

    file: str | None
    name: str
    body: tuple[str, ...] = ()
    loose: bool = False


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def normalise(line: str) -> str:
    """One output line with what changes between two runs of the same failure taken out."""
    line = _THREAD_ID.sub(r"\1", line)
    line = _PLACEHOLDER.sub("#", line)
    line = _ADDRESS.sub("0xADDR", line)
    line = _STAMP.sub("<time>", line)
    line = _DART_CLOCK.sub("", line.strip())
    line = _DURATION.sub("<time>", line)
    line = _ABSOLUTE_DIRECTORY.sub("", line)
    line = _LONG_NUMBER.sub("#", line)
    return _BLANKS.sub(" ", line).strip()


def _generic(line: str) -> bool:
    if line in _GENERIC_EXACT or line.startswith(_GENERIC_PREFIXES):
        return True
    if line.strip("=+-_⎯─ ") == "" or re.fullmatch(r"[\W_]*\d+/\d+[\W_]*", line):
        return True
    return any(pattern.search(line) for pattern in _GENERIC_PATTERNS)


def canonical(name: str) -> str:
    """A test name with every runner's separators read as one space."""
    name = name.strip().strip("\"'")
    name = re.sub(r"\(.*?\)\s*$", "", name) if re.search(r"\w\(.*\)\s*$", name) else name
    if _DOTTED.fullmatch(name):
        name = name.replace(".", " ")
    return _BLANKS.sub(" ", _SEPARATORS.sub(" ", name)).strip()


def _split_cited(test: str) -> tuple[str, str]:
    file, _, name = test.partition("::")
    return file.strip(), canonical(name)


def _base(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _fits(failure: Failure, file: str, name: str) -> bool:
    if failure.file and file and _base(failure.file) != _base(file):
        return False
    if not name:
        return bool(file and failure.file)
    printed = canonical(failure.name)
    if "[" not in name:
        printed = printed.split("[", 1)[0].strip()
    if printed == name or printed.endswith(" " + name):
        return True
    return failure.loose and name.endswith(" " + printed)


def _lines(text: str) -> list[str]:
    return text.splitlines()[:_LINE_COUNT_LIMIT]


def _until(lines: list[str], start: int, stop: Callable[[str], bool]) -> tuple[str, ...]:
    body = []
    for line in lines[start:]:
        if stop(line):
            break
        body.append(line)
    return tuple(body)


def _cargo(lines: list[str]) -> list[Failure]:
    found: dict[str, Failure] = {}
    target: str | None = None
    recap = False
    for index, raw in enumerate(lines):
        recap = recap or bool(re.match(r"\s*Summary \[", raw))
        running = re.match(r"\s*Running (unittests )?(\S+)", raw)
        if running:
            target = None if running.group(1) else running.group(2)
            continue
        failed = re.match(r"test (.+?) \.\.\. FAILED", raw)
        if failed:
            found.setdefault(failed.group(1), Failure(target, failed.group(1), loose=True))
            continue
        block = re.match(r"---- (.+?) stdout ----$", raw)
        if block:
            body = _until(
                lines, index + 1,
                lambda line: line.startswith(("---- ", "failures:", "test result:")),
            )
            previous = found.get(block.group(1))
            found[block.group(1)] = Failure(
                previous.file if previous else target, block.group(1), body, loose=True,
            )
            continue
        nextest = re.match(r"\s*FAIL \[[^\]]*\] (?:\(\s*\d+/\s*\d+\) )?(\S+) (.+?)\s*$", raw)
        if nextest:
            body = _until(
                lines, index + 1,
                lambda line: bool(re.match(
                    r"\s*(?:FAIL|PASS|SLOW|SKIP|Summary|Cancelling|─{3,})", line,
                )),
            )
            if not recap:
                found[nextest.group(2)] = Failure(None, nextest.group(2), body, loose=True)
    return list(found.values())


def _pytest(lines: list[str]) -> list[Failure]:
    entries: dict[str, str] = {}
    for raw in lines:
        match = re.match(r"(?:FAILED|ERROR) (\S+?::.+?)(?: - .*)?$", raw) or re.match(
            r"(\S+?::.+?) (?:FAILED|ERROR)\b", raw,
        )
        if match:
            entries.setdefault(canonical(match.group(1).partition("::")[2]), match.group(1))
    sections: dict[str, tuple[str, ...]] = {}
    for index, raw in enumerate(lines):
        header = re.match(r"_{2,} (.+?) _{2,}$", raw)
        if header:
            sections[canonical(header.group(1))] = _until(
                lines, index + 1, lambda line: bool(re.match(r"(?:_{2,} .+ _{2,}|={2,}.*)$", line)),
            )
    failures = []
    for key, full in entries.items():
        file, _, name = full.partition("::")
        failures.append(Failure(file, name, sections.pop(key, ())))
    for key, body in sections.items():
        failures.append(Failure(None, key, body))
    return failures


def _unittest(lines: list[str]) -> list[Failure]:
    failures = []
    for index, raw in enumerate(lines):
        match = re.match(r"(?:FAIL|ERROR): (\w+) \(([\w.]+)\)", raw)
        if match:
            dotted = match.group(2)
            if not dotted.endswith("." + match.group(1)):
                dotted = f"{dotted}.{match.group(1)}"
            body = _until(lines, index + 1, lambda line: line.startswith("====="))
            failures.append(Failure(None, dotted, body))
    return failures


def _vitest(lines: list[str]) -> list[Failure]:
    failures = []
    for index, raw in enumerate(lines):
        header = re.match(r"\s*FAIL\s+(\S+\.\w+) > (.+?)\s*$", raw)
        if header:
            body = _until(
                lines, index + 1,
                lambda line: bool(re.match(r"\s*FAIL\s", line)) or line.lstrip().startswith("⎯"),
            )
            failures.append(Failure(header.group(1), header.group(2), body))
            continue
        verbose = re.match(r"\s*[×✗✕] (\S+\.\w+) > (.+?)(?:\s+\d+(?:\.\d+)?ms)?\s*$", raw)
        if verbose:
            body = _until(lines, index + 1, lambda line: not line.lstrip().startswith("→"))
            failures.append(Failure(verbose.group(1), verbose.group(2), body))
    return failures


def _jest(lines: list[str]) -> list[Failure]:
    failures = []
    file: str | None = None
    for index, raw in enumerate(lines):
        suite = re.match(r"\s*FAIL\s+(\S+)\s*$", raw)
        if suite:
            file = suite.group(1)
            continue
        case = re.match(r"\s+● (.+?)\s*$", raw)
        if case and not case.group(1).startswith(("Console", "Test suite failed")):
            body = _until(
                lines, index + 1,
                lambda line: bool(re.match(r"\s+● ", line)) or line.startswith("Test Suites:"),
            )
            failures.append(Failure(file, case.group(1), body))
    return failures


def _go(lines: list[str]) -> list[Failure]:
    failures = []
    for index, raw in enumerate(lines):
        match = re.match(r"\s*--- FAIL: (\S+) \(", raw)
        if not match:
            continue
        name = match.group(1)
        before = []
        for earlier in range(index - 1, -1, -1):
            if re.match(rf"\s*=== RUN\s+{re.escape(name)}\s*$", lines[earlier]):
                before = [
                    line for line in lines[earlier + 1:index] if not line.startswith("=== ")
                ]
                break
        after = _until(lines, index + 1, lambda line: not line[:1].isspace())
        failures.append(Failure(None, name, tuple(before) + after))
    return failures


def _dart(lines: list[str]) -> list[Failure]:
    failures = []
    for index, raw in enumerate(lines):
        match = re.match(r"\d+:\d\d(?::\d\d)? [+~-]\d+(?: [+~-]\d+)*: (.+?) \[E\]\s*$", raw)
        if not match:
            continue
        file, _, name = match.group(1).partition(": ")
        body = _until(lines, index + 1, lambda line: bool(_DART_CLOCK.match(line)))
        failures.append(Failure(file, name, body))
    return failures


def _swift(lines: list[str]) -> list[Failure]:
    failures = []
    for raw in lines:
        xctest = re.match(r"(.*?):\d+: error: -\[([\w.]+) (\w+)\] : ", raw)
        if xctest:
            name = " ".join([*xctest.group(2).split("."), xctest.group(3)])
            failures.append(Failure(xctest.group(1), name, (raw,)))
            continue
        testing = re.match(r"✘ Test (.+?) failed after ", raw)
        if testing and not testing.group(1).startswith(("run with", "Suite ")):
            name = testing.group(1)
            body: list[str] = []
            where = None
            for position, line in enumerate(lines):
                if line.startswith(f"✘ Test {name} recorded an issue"):
                    body.append(line)
                    body.extend(_until(lines, position + 1, lambda text: not text.startswith("↳")))
                    where = where or re.search(r"recorded an issue at (\S+?):\d+:\d+", line)
            failures.append(Failure(where.group(1) if where else None, name, tuple(body)))
    return failures


_RUNNERS: tuple[Callable[[list[str]], list[Failure]], ...] = (
    _cargo, _pytest, _unittest, _vitest, _jest, _go, _dart, _swift,
)


def failed_tests(text: str) -> list[Failure]:
    """Every test the runners' output says failed, from output already stripped of colour."""
    lines = _lines(text)
    found: list[Failure] = []
    for runner in _RUNNERS:
        found.extend(runner(lines))
    return found


def _specific_line(lines: list[str], test: str) -> str | None:
    """The last line that names this failure, rather than a header, a total or a test id."""
    file = test.split("::", 1)[0] if test else ""
    chosen = ""
    # pytest marks the failure message itself with a leading "E"; its last line is the message,
    # where the location line after it only names the exception class.
    messages = [raw for raw in lines if re.match(r"E {2,}\S", raw)]
    for raw in messages[-1:] or lines:
        line = normalise(raw)[:_LINE_LIMIT]
        if not line or _generic(line) or (test and line == test) or (file and line == file):
            continue
        chosen = line
    return chosen or None


def _own(failure: Failure) -> str | None:
    body = "\n".join(normalise(line) for line in failure.body)
    return body if body.strip() else None


_FRAME = re.compile(r"^(?:[>❯]\s|\d+\s*[|:]|[|^~\s-]+$|at |thread '.*' panicked at \S+:\d+:\d+:$)")
_MESSAGE_FLOOR = 12


def _message_lines(failure: Failure) -> list[str]:
    """The lines of a failure that say what went wrong, without source frames and locations."""
    pytest_messages = [line for line in failure.body if re.match(r"E {2,}\S", line)]
    chosen = []
    for raw in pytest_messages or failure.body:
        line = normalise(raw)[:_LINE_LIMIT]
        if line and not _generic(line) and not _FRAME.match(line):
            chosen.append(line)
    return chosen


def matches(code: int, captured: str, recorded: str, test: str = "") -> bool:
    """True when a re-run that exited *code* failed with the recorded failure of *test*.

    A cited test matches only when that test failed in the re-run, never because it passed or
    because a different test failed. The failure then has to be the recorded one, read either way
    round: the recorded failure line appears in the failing test's own failure lines, or the
    failing test's own message appears in the recorded output. The second reading is for a
    reviewer who recorded a failure on one line instead of pasting the runner's block.
    """
    if code == 0:
        return False
    text = strip_ansi(captured[:_CAPTURE_LIMIT])
    recorded_text = strip_ansi(recorded[:_CAPTURE_LIMIT])
    file, name = _split_cited(test) if test else ("", "")
    failures = failed_tests(text)
    whole = "\n".join(normalise(raw) for raw in _lines(text))
    if not failures or not (file or name):
        line = _specific_line(_lines(recorded_text), test)
        if line is None or line not in whole:
            return False
        return not ("::" in test and test not in text)
    hits = [item for item in failures if _fits(item, file, name)]
    recorded_hits = [
        item for item in failed_tests(recorded_text) if _fits(item, file, name) and item.body
    ]
    source = recorded_hits[-1].body if recorded_hits else tuple(_lines(recorded_text))
    line = _specific_line(list(source), test) or _specific_line(_lines(recorded_text), test)
    flat = " ".join(filter(None, (normalise(raw) for raw in _lines(recorded_text))))
    for item in hits:
        if line is not None and line in (_own(item) or whole):
            return True
        message = _message_lines(item)
        if message and sum(map(len, message)) >= _MESSAGE_FLOOR and all(
            part in flat for part in message
        ):
            return True
    return False
