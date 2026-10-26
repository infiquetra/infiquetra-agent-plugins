#!/usr/bin/env python3
"""Does a re-run of a reproduction test fail the way the reviewer recorded (issue 264)?

``finish`` re-runs a reviewer's reproduction in a confined copy of the head and asks whether it
failed with the recorded failure. A test id such as ``tests/test_x.py::test_y`` is a pytest
spelling. Every other runner prints its failures its own way: cargo prints ``test name ...
FAILED`` and a ``---- name stdout ----`` block, Vitest prints ``FAIL file > suite > name``, Go
prints ``--- FAIL: TestName``. So the test is looked for in each runner's own failure lines, and
the recorded failure line is looked for in that test's own failure block.

Both sides are compared after ignoring runner metadata that changes between runs. Assertion
values, including numbers, durations and placeholders, remain part of the failure cause.

The matcher recognises these runners. All but bun test were read from output captured from the
real runner: cargo test and cargo nextest, pytest, unittest, Vitest, Jest, go test, dart test, and
swift test (XCTest and Swift Testing). bun test is read from its documented ``(fail) suite > name``
lines and the error block printed before each. Output it does not recognise falls back to the
older rule: the recorded failure line has to appear in the re-run, and a test id written as
``file::name`` has to appear word for word. Both sides of that comparison drop the directories
of an absolute ``/dir/file.ext:line`` location anywhere in a line, and bun's trailing ``[0.85ms]``
on a ``(fail)`` or ``(pass)`` line.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

_ANSI = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\([A-Za-z0-9]|\][^\x07\x1b]{0,256}(?:\x07|\x1b\\))")
_THREAD_ID = re.compile(r"(thread '[^']*') \(\d+\)")
_DART_CLOCK = re.compile(r"^\d+:\d\d(?::\d\d)? [+~-]\d+(?: [+~-]\d+)*: ")
_ABSOLUTE_LOCATION = re.compile(r"^(?:/[\w.+@~-]+)+/([\w.+@~-]+:\d+(?::\d+)?:)")
# An absolute path that ends in a source location (``/dir/file.ts:12:5``), anywhere in a line: the
# directories are scratch space that differs between runs, so only ``file:line[:column]`` is kept.
# A path with no line number (``/srv/data/out.csv``) may be part of an assertion value and is left
# alone. A leading word character, colon, dot, slash, tilde or dash means this is not the start of
# a path (a URL, a relative path).
_ABSOLUTE_FILE = re.compile(
    r"(?<![\w:./~-])(?:/[\w.+@~-]+)+/([\w+@~-][\w.+@~-]*\.\w+(?::\d+){1,2})"
)
# bun's run time, ``[0.85ms]``, at the end of a ``(fail)`` or ``(pass)`` result line only.
_BUN_DURATION = re.compile(r"\[\d+(?:\.\d+)?(?:ms|s|m|us|\u00b5s|ns)\]$")
_BUN_RESULT_LINE = ("(fail) ", "(pass) ")
_PID_FILENAME = re.compile(r"(\b[\w.-]+-test-)(?:\d{5,}|<pid>)(?=[\"'/\s])")
_BLANKS = re.compile(r"\s+")
_DOTTED = re.compile(r"\w+(?:\.\w+)+")
_SEPARATORS = re.compile(r"::|/| > |›|>")
_CAPTURE_LIMIT = 400_000
_LINE_COUNT_LIMIT = 20_000
_FAILURE_LIMIT = 10_000
_BODY_LINE_LIMIT = 40_000

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
    # bun test
    "bun test v", "(pass) ", "(skip) ", "(todo) ",
    # Vitest and Jest
    "Test Files", "Tests ", "Tests:", "Test Suites:", "Snapshots:", "Time:", "Duration",
    "Start at", "RUN ", "Ran all test suites",
    # go test
    "FAIL\t", "ok  \t", "=== ",
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
    re.compile(r"^\d+ (?:pass|fail|skip|todo|expect\(\) calls)$"),
    re.compile(r"^\d+ tests? failed:$"),
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


def _without_bun_duration(text: str) -> str:
    """Drop a trailing ``[0.85ms]`` (a number and a time unit); keep any other bracket."""
    text = text.rstrip()
    found = _BUN_DURATION.search(text)
    return text[: found.start()].rstrip() if found else text


def normalise(line: str) -> str:
    """Remove identified metadata, preserving values in the assertion itself."""
    line = _THREAD_ID.sub(r"\1", line)
    # Temporary test filenames with a PID suffix occur in reviewer summaries as <pid> too.
    line = _PID_FILENAME.sub(r"\1<pid>", line)
    line = re.sub(r"(object at )0x[0-9a-fA-F]+", r"\g<1>0xADDR", line)
    line = _DART_CLOCK.sub("", line.strip())
    line = _ABSOLUTE_LOCATION.sub(r"\1", line)
    line = _ABSOLUTE_FILE.sub(r"\1", line)
    if line.startswith(_BUN_RESULT_LINE):
        line = _without_bun_duration(line)
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


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(part for part in path.replace("\\", "/").split("/") if part not in {"", "."})


def _paths_fit(first: str, second: str) -> bool:
    """Accept an omitted leading root, but keep every explicit directory component."""
    left, right = _path_parts(first), _path_parts(second)
    width = min(len(left), len(right))
    return bool(width and left[-width:] == right[-width:])


def _fits(failure: Failure, file: str, name: str) -> bool:
    if failure.file and file and not _paths_fit(failure.file, file):
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
    return text[:_CAPTURE_LIMIT].splitlines()[:_LINE_COUNT_LIMIT]


class _ParseLimit(ValueError):
    """The output cannot be attributed within the parser's storage/work budget."""


@dataclass
class _Budget:
    body_lines: int = _BODY_LINE_LIMIT

    def retain(self, count: int) -> None:
        self.body_lines -= count
        if self.body_lines < 0:
            raise _ParseLimit("too many retained failure lines")


def _until(
    lines: list[str], start: int, stop: Callable[[str], bool], budget: _Budget,
    *, end: int | None = None,
) -> tuple[str, ...]:
    body = []
    # Do not slice the entire remaining transcript for every header, even for an empty block.
    for index in range(start, len(lines) if end is None else end):
        line = lines[index]
        if stop(line):
            break
        budget.retain(1)
        body.append(line)
    return tuple(body)


def _cargo(lines: list[str], budget: _Budget) -> list[Failure]:
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
                budget,
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
                budget,
            )
            if not recap:
                found[nextest.group(2)] = Failure(None, nextest.group(2), body, loose=True)
    return list(found.values())


def _pytest(lines: list[str], budget: _Budget) -> list[Failure]:
    entries: dict[str, Failure] = {}
    for raw in lines:
        match = re.match(r"(?:FAILED|ERROR) (\S+?::.+?)(?: - (.*))?$", raw) or re.match(
            r"(\S+?::.+?) (?:FAILED|ERROR)\b", raw,
        )
        if match:
            file, _, name = match.group(1).partition("::")
            summary = match.group(2) if match.lastindex == 2 else None
            body: tuple[str, ...] = (summary,) if summary else ()
            budget.retain(len(body))
            previous = entries.get(match.group(1))
            if previous is None or body:
                entries[match.group(1)] = Failure(file, name, body)
    sections: list[Failure] = []
    for index, raw in enumerate(lines):
        header = re.match(r"_{2,} (.+?) _{2,}$", raw)
        if header:
            body = _until(
                lines, index + 1, lambda line: bool(re.match(r"(?:_{2,} .+ _{2,}|={2,}.*)$", line)),
                budget,
            )
            locations = [
                match.group(1) for line in body
                if (match := re.match(r"(\S+\.py):\d+: (?:\w*Error|\w*Exception)\b", line))
            ]
            sections.append(Failure(locations[-1] if locations else None, header.group(1), body))
    failures: list[Failure] = []
    by_name: dict[str, list[Failure]] = {}
    by_location: dict[tuple[str, tuple[str, ...]], list[Failure]] = {}
    entry_counts: dict[str, int] = {}
    for entry in entries.values():
        key = canonical(entry.name)
        entry_counts[key] = entry_counts.get(key, 0) + 1
    for section in sections:
        key = canonical(section.name)
        by_name.setdefault(key, []).append(section)
        if section.file:
            by_location.setdefault((key, _path_parts(section.file)), []).append(section)
    for entry in entries.values():
        key = canonical(entry.name)
        candidates = by_name.get(key, [])
        located = by_location.get((key, _path_parts(entry.file or "")), [])
        selected = located[0] if len(located) == 1 else None
        if selected is None and len(candidates) == 1:
            part = candidates[0]
            if part.file and _paths_fit(part.file, entry.file or ""):
                selected = part
            elif part.file is None and entry_counts[key] == 1:
                selected = candidates[0]
        if selected:
            failures.append(Failure(entry.file, entry.name, selected.body))
        elif candidates:
            # A duplicate name with no unique location must not borrow a section or summary.
            failures.append(Failure(entry.file, entry.name))
        else:
            failures.append(entry)
    if not entries:
        failures.extend(
            part if part.file or len(by_name[canonical(part.name)]) == 1 else Failure(None, part.name)
            for part in sections
        )
    return failures


def _unittest(lines: list[str], budget: _Budget) -> list[Failure]:
    failures = []
    for index, raw in enumerate(lines):
        match = re.match(r"(?:FAIL|ERROR): (\w+) \(([\w.]+)\)", raw)
        if match:
            dotted = match.group(2)
            if not dotted.endswith("." + match.group(1)):
                dotted = f"{dotted}.{match.group(1)}"
            body = _until(
                lines, index + 1,
                lambda line: line.startswith(("=====", "FAIL: ", "ERROR: ")), budget,
            )
            failures.append(Failure(None, dotted, body))
    return failures


def _vitest(lines: list[str], budget: _Budget) -> list[Failure]:
    failures = []
    for index, raw in enumerate(lines):
        header = re.match(r"\s*FAIL\s+(\S+\.\w+) > (.+?)\s*$", raw)
        if header:
            body = _until(
                lines, index + 1,
                lambda line: bool(re.match(r"\s*FAIL\s", line)) or line.lstrip().startswith("⎯"),
                budget,
            )
            failures.append(Failure(header.group(1), header.group(2), body))
            continue
        verbose = re.match(r"\s*[×✗✕] (\S+\.\w+) > (.+?)(?:\s+\d+(?:\.\d+)?ms)?\s*$", raw)
        if verbose:
            body = _until(lines, index + 1, lambda line: not line.lstrip().startswith("→"), budget)
            failures.append(Failure(verbose.group(1), verbose.group(2), body))
    return failures


_BUN_TEST_PATH = r"[^()\s]+[._](?:test|spec)\.[cm]?[jt]sx?"
_BUN_FILE_HEADER = re.compile(rf"({_BUN_TEST_PATH}):$")
_BUN_PAREN_FRAME = re.compile(rf"\(({_BUN_TEST_PATH}):\d+:\d+\)$")
_BUN_BARE_FRAME = re.compile(rf"at ({_BUN_TEST_PATH}):\d+:\d+$")
_BUN_EXCERPT = re.compile(r"\s*\d+ \| ")
_BUN_LINE_LIMIT = 2_000


def _bun_frame_file(line: str) -> str | None:
    """The test file in a stack frame such as ``at <anonymous> (/dir/a.test.ts:12:5)``."""
    text = line.strip()
    if len(text) > _BUN_LINE_LIMIT or not text.startswith("at "):
        return None
    found = _BUN_PAREN_FRAME.search(text) or _BUN_BARE_FRAME.match(text)
    return found.group(1) if found else None


def _bun_block(lines: list[str], start: int, end: int) -> tuple[str, ...]:
    """A failure's block: from its code excerpt, or else its ``error:`` line, up to its result.

    Output a passing test printed before the block is not part of it. bun hides ``(pass)`` lines
    when it runs for an agent, so a block cannot be told from earlier output by the result line
    before it.
    """
    for first in range(start, end):
        if _BUN_EXCERPT.match(lines[first]):
            return tuple(lines[first:end])
    for first in range(start, end):
        if lines[first].lstrip().startswith("error:"):
            return tuple(lines[first:end])
    return tuple(lines[start:end])


def _bun(lines: list[str], budget: _Budget) -> list[Failure]:
    """bun test prints a failure's error block first, then its ``(fail) suite > name [time]`` line.

    The block starts at the failure's code excerpt (see ``_bun_block``). Newer bun repeats the
    failing ``(fail)`` lines in a recap after ``N tests failed:``; the recap has no block, so it
    is skipped. Bun prints a file header only before a file's first result, and a recording may
    start after it, so a failure with no header takes its file from the test file named in its own
    stack frame (``at <anonymous> (/dir/file.test.ts:12:5)``).
    """
    failures = []
    file: str | None = None
    start = 0
    recap = False
    for index, raw in enumerate(lines):
        recap = recap or bool(re.match(r"\s*\d+ tests? failed:\s*$", raw))
        header = _BUN_FILE_HEADER.match(raw.rstrip()) if len(raw) <= _BUN_LINE_LIMIT else None
        if header:
            file, start = header.group(1), index + 1
            continue
        if raw.startswith(("(pass) ", "(skip) ", "(todo) ")):
            start = index + 1
            continue
        if raw.startswith("(fail) "):
            if not recap:
                body = _bun_block(lines, start, index)
                budget.retain(len(body))
                where = file
                if where is None:
                    where = next((f for f in map(_bun_frame_file, body) if f), None)
                failures.append(Failure(where, _without_bun_duration(raw[7:]), body))
            start = index + 1
    return failures


def _jest(lines: list[str], budget: _Budget) -> list[Failure]:
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
                budget,
            )
            failures.append(Failure(file, case.group(1), body))
    return failures


def _go(lines: list[str], budget: _Budget | None = None) -> list[Failure]:
    budget = budget or _Budget()
    failures = []
    runs: dict[str, int] = {}
    for index, raw in enumerate(lines):
        running = re.match(r"\s*=== RUN\s+(\S+)\s*$", raw)
        if running:
            runs[running.group(1)] = index
            continue
        match = re.match(r"\s*--- FAIL: (\S+) \(", raw)
        if not match:
            continue
        name = match.group(1)
        earlier = runs.pop(name, None)
        before = () if earlier is None else _until(
            lines, earlier + 1, lambda line: False, budget, end=index,
        )
        after = _until(lines, index + 1, lambda line: not line[:1].isspace(), budget)
        failures.append(Failure(None, name, before + after))
    return failures


def _dart(lines: list[str], budget: _Budget) -> list[Failure]:
    failures = []
    for index, raw in enumerate(lines):
        match = re.match(r"\d+:\d\d(?::\d\d)? [+~-]\d+(?: [+~-]\d+)*: (.+?) \[E\]\s*$", raw)
        if not match:
            continue
        file, _, name = match.group(1).partition(": ")
        body = _until(lines, index + 1, lambda line: bool(_DART_CLOCK.match(line)), budget)
        failures.append(Failure(file, name, body))
    return failures


def _swift(lines: list[str], budget: _Budget) -> list[Failure]:
    failures = []
    issues: dict[str, tuple[str | None, list[str]]] = {}
    failed: list[str] = []
    for index, raw in enumerate(lines):
        xctest = re.match(r"(.*?):\d+: error: -\[([\w.]+) (\w+)\] : ", raw)
        if xctest:
            name = " ".join([*xctest.group(2).split("."), xctest.group(3)])
            budget.retain(1)
            failures.append(Failure(xctest.group(1), name, (raw,)))
            continue
        issue = re.match(r"✘ Test (.+?) recorded an issue at (\S+?):\d+:\d+", raw)
        if issue:
            budget.retain(1)
            where, body = issues.setdefault(issue.group(1), (issue.group(2), []))
            body.append(raw)
            body.extend(_until(lines, index + 1, lambda text: not text.startswith("↳"), budget))
        testing = re.match(r"✘ Test (.+?) failed after ", raw)
        if testing and not testing.group(1).startswith(("run with", "Suite ")):
            failed.append(testing.group(1))
    for name in dict.fromkeys(failed):
        where, body = issues.pop(name, (None, []))
        failures.append(Failure(where, name, tuple(body)))
    return failures


_RUNNERS: tuple[Callable[[list[str], _Budget], list[Failure]], ...] = (
    _cargo, _pytest, _unittest, _vitest, _bun, _jest, _go, _dart, _swift,
)


def failed_tests(text: str) -> list[Failure]:
    """Read runner failures, raising _ParseLimit when attribution exceeds the shared budget."""
    lines = _lines(text)
    found: list[Failure] = []
    budget = _Budget()
    for runner in _RUNNERS:
        found.extend(runner(lines, budget))
        if len(found) > _FAILURE_LIMIT:
            raise _ParseLimit("too many failed tests")
    return found


def _specific_line(lines: list[str], test: str) -> str | None:
    """The last line that names this failure, rather than a header, a total or a test id."""
    file = test.split("::", 1)[0] if test else ""
    chosen = ""
    # pytest marks the failure message itself with a leading "E"; its last line is the message,
    # where the location line after it only names the exception class.
    messages = [raw for raw in lines if re.match(r"E {2,}\S", raw)]
    for raw in messages[-1:] or lines:
        line = normalise(raw)
        if not line or _generic(line) or (test and line == test) or (file and line == file):
            continue
        chosen = line
    return chosen or None


_FRAME = re.compile(r"^(?:[>❯]\s|\d+\s*[|:]|[|^~\s-]+$|at |File \"|thread '.*' panicked at \S+:\d+:\d+:$)")
_MESSAGE_FLOOR = 12


def _message_lines(failure: Failure) -> list[str]:
    """The lines of a failure that say what went wrong, without source frames and locations."""
    pytest_messages = [line for line in failure.body if re.match(r"E {2,}\S", line)]
    chosen = []
    for raw in pytest_messages or failure.body:
        line = normalise(raw)
        line = re.sub(r"^E\s+", "", line)
        line = re.sub(r"^thread '[^']*' panicked(?: at \S+:\d+:\d+)?:?\s*", "", line)
        if line == failure.name:
            continue
        if line and not _generic(line) and not _FRAME.match(line):
            chosen.append(line)
    return chosen


def _matches(code: int, captured: str, recorded: str, test: str = "") -> bool:
    """True when a re-run that exited *code* failed with the recorded failure of *test*.

    A cited test must fail with the complete recorded substantive message. A reviewer summary
    on one line must contain that test's complete message, rather than one shared trailing line.
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
    recorded_failures = failed_tests(recorded_text)
    recorded_hits = [
        item for item in recorded_failures if _fits(item, file, name) and item.body
    ]
    if recorded_failures and not recorded_hits:
        return False
    flat = " ".join(_message_lines(Failure(None, "", tuple(_lines(recorded_text)))))
    for item in hits:
        message = _message_lines(item)
        if not message:
            continue
        if recorded_hits:
            for source in recorded_hits:
                if not _fits(source, file, canonical(item.name)):
                    continue
                recorded_message = _message_lines(source)
                own = " ".join(message)
                expected = " ".join(recorded_message)
                if recorded_message and all(part in own for part in recorded_message) and all(
                    part in expected for part in message
                ):
                    return True
        elif sum(map(len, message)) >= _MESSAGE_FLOOR and all(part in flat for part in message):
            return True
    return False


def matches(code: int, captured: str, recorded: str, test: str = "") -> bool:
    """Match within bounded parser work/storage; oversized ambiguous output fails closed."""
    try:
        return _matches(code, captured, recorded, test)
    except _ParseLimit:
        return False
