"""A reproduction test's failure is recognised in each runner's real output (issue 264).

Every transcript under ``fixtures/reproduction_output`` was captured from the real runner (cargo
test, cargo nextest, pytest, unittest, Vitest, Jest, go test, dart test, swift test), one failing
test, one other failing test and one passing test in each, with local directories made inert.
The tests re-run a recorded failure against a later run of the same code, as ``finish`` does.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "reproduction_output"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


M = _load("reproduction_match")


def _text(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


def _matches(rerun: str, recorded: str, test: str, code: int = 1) -> bool:
    return M.matches(code, _text(rerun), _text(recorded), test)


CARGO = "crates/demo/tests/repro_test.rs::adds_two_numbers"

# (re-run transcript, recorded transcript, cited test) that must match.
MATCHING = [
    # cargo test: thread ids differ between the two runs, and the test ran alone the second time
    ("cargo_one_failure", "cargo_two_failures", CARGO),
    ("cargo_two_failures", "cargo_one_failure", CARGO),
    ("cargo_colour", "cargo_two_failures", CARGO),
    ("cargo_nextest", "cargo_two_failures", CARGO),
    ("cargo_one_failure", "cargo_nextest", CARGO),
    ("cargo_one_failure", "cargo_two_failures", "tests/repro_test.rs::repro_test::adds_two_numbers"),
    ("cargo_unit_modules", "cargo_unit_modules", "src/lib.rs::tests::inner::nested_add"),
    ("cargo_unit_modules", "cargo_unit_modules", "src/lib.rs::nested_add"),
    ("cargo_unit_modules", "cargo_unit_modules", "src/lib.rs::tests::unit_add"),
    # pytest, with and without the progress and summary the default report adds
    ("pytest_quiet", "pytest_default", "tests/test_demo.py::test_add"),
    ("pytest_default", "pytest_quiet", "test_demo.py::test_add"),
    ("pytest_default", "pytest_default", "test_demo.py::TestK::test_method"),
    ("pytest_default", "pytest_default", "test_demo.py::test_param"),
    ("pytest_default", "pytest_default", "test_demo.py::test_param[2]"),
    ("pytest_default", "pytest_default", "test_demo.py"),
    ("unittest", "unittest", "test_u.py::K::test_add"),
    ("unittest", "unittest", "test_u.py::K.test_add"),
    # Vitest and Jest
    ("vitest_filtered", "vitest_default", "add.test.js::math adds"),
    ("vitest_default", "vitest_verbose", "src/add.test.js::math > adds"),
    ("vitest_verbose", "vitest_filtered", "add.test.js::math adds"),
    ("jest_filtered", "jest", "add.test.js::math adds"),
    ("jest", "jest_filtered", "add.test.js::math › adds"),
    # go test
    ("go_one", "go", "pkg/add_test.go::TestAdd"),
    ("go", "go_verbose", "add_test.go::TestOther"),
    ("go_one", "go_verbose", "add_test.go::TestAdd"),
    # dart test
    ("dart_filtered", "dart", "test/add_test.dart::math adds"),
    ("dart", "dart", "test/add_test.dart::math other"),
    # swift test, XCTest and Swift Testing
    ("swift_xctest", "swift_xctest", "Tests/DemoTests/DemoTests.swift::DemoTests/testAdds"),
    ("swift_xctest", "swift_xctest", "Tests/DemoTests/DemoTests.swift::OtherTests.testBroken"),
    ("swift_testing", "swift_testing", "Tests/DemoTests/DemoTests.swift::adds"),
]

# The cited test did not fail in the re-run, or failed in a different file.
NOT_MATCHING = [
    ("cargo_one_failure", "cargo_two_failures", "crates/demo/tests/repro_test.rs::other_failure"),
    ("cargo_two_failures", "cargo_two_failures", "crates/demo/tests/repro_test.rs::passes"),
    ("cargo_two_failures", "cargo_two_failures", "crates/demo/tests/other_test.rs::adds_two_numbers"),
    ("cargo_unit_modules", "cargo_unit_modules", "src/lib.rs::tests::missing"),
    ("pytest_quiet", "pytest_default", "test_demo.py::test_other"),
    ("pytest_default", "pytest_default", "test_demo.py::test_ok"),
    ("pytest_default", "pytest_default", "tests/test_other.py::test_add"),
    ("unittest", "unittest", "test_u.py::K::test_ok"),
    ("vitest_filtered", "vitest_default", "add.test.js::math other"),
    ("vitest_default", "vitest_default", "add.test.js::math ok"),
    ("jest_filtered", "jest", "add.test.js::math other"),
    ("go_one", "go", "add_test.go::TestOther"),
    ("go", "go", "add_test.go::TestOk"),
    ("dart_filtered", "dart", "test/add_test.dart::math other"),
    ("dart", "dart", "test/add_test.dart::math ok"),
    ("swift_xctest", "swift_xctest", "Tests/DemoTests/DemoTests.swift::DemoTests/testOk"),
    ("swift_testing", "swift_testing", "Tests/DemoTests/DemoTests.swift::ok"),
]


@pytest.mark.parametrize(("rerun", "recorded", "test"), MATCHING)
def test_a_cited_test_that_failed_again_matches(rerun: str, recorded: str, test: str) -> None:
    assert _matches(rerun, recorded, test)


@pytest.mark.parametrize(("rerun", "recorded", "test"), NOT_MATCHING)
def test_a_cited_test_that_did_not_fail_does_not_match(
    rerun: str, recorded: str, test: str,
) -> None:
    assert not _matches(rerun, recorded, test)


@pytest.mark.parametrize(
    ("rerun", "test"),
    [
        ("cargo_pass_only", CARGO),
        ("pytest_pass", "test_demo.py::test_ok"),
        ("swift_xctest_pass", "Tests/DemoTests/DemoTests.swift::DemoTests/testOk"),
    ],
)
def test_a_passing_run_never_matches(rerun: str, test: str) -> None:
    recorded = {"cargo_pass_only": "cargo_one_failure", "pytest_pass": "pytest_default"}.get(
        rerun, "swift_xctest",
    )
    assert not M.matches(0, _text(rerun), _text(recorded), test)
    # A non-zero exit with nothing failing in the output is not the recorded failure either.
    assert not M.matches(101, _text(rerun), _text(recorded), test)


def test_a_cited_test_that_passes_while_another_fails_does_not_match() -> None:
    # `passes` ran and passed in the run where `adds_two_numbers` and `other_failure` failed.
    assert not _matches("cargo_two_failures", "cargo_two_failures", "tests/repro_test.rs::passes")
    # The same test cited by its bare name, as a reviewer sometimes does.
    assert not _matches("cargo_two_failures", "cargo_two_failures", "tests/repro_test.rs::pass")


def test_the_recorded_failure_must_be_the_one_the_rerun_shows() -> None:
    """The cited test fails again, but for another reason: it is not that reproduction."""
    changed = _text("cargo_one_failure").replace("right: 5", "right: 9")
    assert not M.matches(101, changed, _text("cargo_two_failures"), CARGO)
    changed_pytest = _text("pytest_quiet").replace("-1", "-2")
    assert not M.matches(1, changed_pytest, _text("pytest_default"), "test_demo.py::test_add")


def test_another_tests_failure_line_does_not_stand_in_for_the_cited_one() -> None:
    """`other_failure` prints 'other broke'; a record of that line under another test's name."""
    recorded = "---- adds_two_numbers stdout ----\n\nthread 'adds_two_numbers' panicked\nother broke\n"
    assert not M.matches(101, _text("cargo_two_failures"), recorded, CARGO)
    # the same line recorded under the test that does print it is that test's reproduction
    own = "---- other_failure stdout ----\n\nthread 'other_failure' panicked\nother broke\n"
    other = "crates/demo/tests/repro_test.rs::other_failure"
    assert M.matches(101, _text("cargo_two_failures"), own, other)


HIDDEN = "crates/ignore/tests/single_dot_hidden_test.rs::single_dot_file_is_hidden_by_default"


def test_a_failure_recorded_on_one_line_matches_the_runners_own_message() -> None:
    """The live reviewer (issue 264) wrote its cargo failure as one line, with its own pid."""
    one_line = _text("recorded_one_line")
    assert "single-dot-test-36207" in one_line and "\n" not in one_line.strip()
    assert _matches("cargo_custom_message", "recorded_one_line", HIDDEN)
    # a placeholder where the reviewer left out a process id is the same failure
    placeholder = one_line.replace("36207", "<pid>")
    assert M.matches(101, _text("cargo_custom_message"), placeholder, HIDDEN)


def test_a_one_line_record_of_another_failure_does_not_match() -> None:
    other = "thread 'single_dot_file_is_hidden_by_default' panicked: left: 1 right: 2. FAILED"
    assert not M.matches(101, _text("cargo_custom_message"), other, HIDDEN)
    # the right message under a test that did not fail in this run
    assert not _matches(
        "cargo_custom_message", "recorded_one_line",
        "crates/ignore/tests/single_dot_hidden_test.rs::another_test",
    )
    # a record that only says the run failed says nothing about this failure
    assert not M.matches(101, _text("cargo_custom_message"), "test result: FAILED. 0 passed", HIDDEN)


def _vary(text: str) -> str:
    """The same run another time: thread ids, timings, addresses, time stamps and directories."""
    text = re.sub(r"\((\d{6,})\)", lambda m: f"({int(m.group(1)) + 17})", text)
    text = re.sub(r"(\d+)\.(\d+)s\b", lambda m: f"{int(m.group(1)) + 3}.{m.group(2)}9s", text)
    text = re.sub(r"(\d+)\.(\d+) seconds", r"\1.\2 seconds".replace("seconds", "sec"), text)
    text = re.sub(r"0x[0-9a-f]+", "0x7f00deadbeef", text)
    text = re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+", "2031-01-02 03:04:05.678", text)
    text = re.sub(r" (\d+)ms\b", r" 9\1ms", text)
    text = text.replace("/work/", "/elsewhere/deeper/")
    return text


def _coloured(text: str) -> str:
    return "\n".join(f"\x1b[1;31m{line}\x1b[0m" if line else line for line in text.split("\n"))


@pytest.mark.parametrize(("rerun", "recorded", "test"), MATCHING)
def test_timings_ids_addresses_and_colour_do_not_change_the_answer(
    rerun: str, recorded: str, test: str,
) -> None:
    changed = _coloured(_vary(_text(rerun)))
    assert M.matches(1, changed, _text(recorded), test)
    assert M.matches(1, _text(rerun), _coloured(_vary(_text(recorded))), test)


def test_the_cargo_thread_id_is_the_only_difference_between_the_two_cargo_runs() -> None:
    first = re.findall(r"thread '\w+' \((\d+)\)", _text("cargo_one_failure"))
    second = re.findall(r"thread '\w+' \((\d+)\)", _text("cargo_two_failures"))
    assert first and second and first[0] != second[-1]


def test_failed_tests_reads_the_name_and_file_each_runner_prints() -> None:
    def names(fixture: str) -> list[tuple[str | None, str]]:
        return [(item.file, item.name) for item in M.failed_tests(_text(fixture))]

    assert ("tests/repro_test.rs", "adds_two_numbers") in names("cargo_one_failure")
    assert (None, "tests::inner::nested_add") in names("cargo_unit_modules")
    assert ("test_demo.py", "TestK::test_method") in names("pytest_default")
    assert ("add.test.js", "math > adds") in names("vitest_default")
    assert (None, "TestOther") in names("go")
    assert ("test/add_test.dart", "math adds") in names("dart")
    assert ("DemoTests.swift", "adds()") in names("swift_testing")
    assert names("cargo_pass_only") == []
    assert names("pytest_pass") == []
    assert names("swift_xctest_pass") == []


def test_output_from_no_known_runner_keeps_the_older_rule() -> None:
    crash = "Traceback (most recent call last):\n  File \"x.py\", line 1\nAssertionError: add returned 0\n"
    recorded = "AssertionError: add returned 0\n"
    assert M.matches(1, crash, recorded, "")
    # a `file::name` id that never appears word for word is not found by the older rule
    assert not M.matches(1, crash, recorded, "tests/test_app.py::test_add")
    assert M.matches(1, crash + "tests/test_app.py::test_add\n", recorded, "tests/test_app.py::test_add")
    assert not M.matches(1, "Traceback (most recent call last):\nValueError: other\n", recorded, "")
    assert not M.matches(0, crash, recorded, "")


def test_an_empty_or_header_only_recorded_output_never_matches() -> None:
    assert not M.matches(101, _text("cargo_one_failure"), "", CARGO)
    assert not M.matches(101, _text("cargo_one_failure"), "test result: FAILED\n", CARGO)
    assert not M.matches(1, _text("pytest_quiet"), "============\n", "test_demo.py::test_add")


def test_hostile_output_is_bounded_before_it_is_parsed() -> None:
    """A run that prints a huge unterminated escape sequence must not make the match slow."""
    import time

    hostile = "\x1b]" * 200_000 + "x" * 1_000_000
    start = time.monotonic()
    assert not M.matches(1, hostile, _text("cargo_one_failure"), CARGO)
    assert not M.matches(1, _text("cargo_one_failure"), hostile, CARGO)
    assert time.monotonic() - start < 5


@pytest.mark.parametrize(
    ("fixture", "test", "before", "after"),
    [
        ("cargo_one_failure", CARGO, "left: -1", "left: -2"),
        ("cargo_one_failure", CARGO, "right: 5", "right: 6"),
        ("pytest_quiet", "test_demo.py::test_add", "== 5", "== 6"),
        ("pytest_quiet", "test_demo.py::test_add", "assert -1", "assert -2"),
    ],
)
def test_every_assertion_operand_must_agree(
    fixture: str, test: str, before: str, after: str,
) -> None:
    recorded = _text(fixture)
    changed = recorded.replace(before, after)
    assert changed != recorded
    assert not M.matches(1, changed, recorded, test)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("10000", "20000"), ("<expected>", "<actual>"), ("100ms", "900ms"),
        ("0x12345", "0x67890"), ("/expected/value", "/actual/value"),
        ("2030-01-01 00:00:00", "2031-01-01 00:00:00"),
    ],
)
def test_assertion_values_are_not_volatile_metadata(before: str, after: str) -> None:
    recorded = f"---- repro stdout ----\nassertion failed: actual {before}\n"
    assert M.matches(1, recorded, recorded, "test.rs::repro")
    assert not M.matches(1, recorded.replace(before, after), recorded, "test.rs::repro")


def test_terse_pytest_summary_keeps_each_tests_own_cause() -> None:
    captured = (
        "FAILED test_alpha.py::test_a - AssertionError: original cause\n"
        "FAILED test_beta.py::test_b - AssertionError: different cause\n"
    )
    assert not M.matches(1, captured, "different cause", "test_alpha.py::test_a")
    assert M.matches(1, captured, "AssertionError: original cause", "test_alpha.py::test_a")
    assert M.matches(1, captured, "AssertionError: different cause", "test_beta.py::test_b")
    missing = "FAILED test_alpha.py::test_a\n" + captured.splitlines()[1]
    assert not M.matches(1, missing, "different cause", "test_alpha.py::test_a")


def test_explicit_relative_directories_must_be_compatible() -> None:
    captured = _text("cargo_one_failure")
    assert not M.matches(1, captured, captured, "unrelated/repro_test.rs::adds_two_numbers")
    assert M.matches(1, captured, captured, "repro_test.rs::adds_two_numbers")
    assert M.matches(1, captured, captured, "./tests/repro_test.rs::adds_two_numbers")


def test_pytest_duplicate_names_keep_their_file_and_message() -> None:
    captured = (
        "________________ test_same ________________\n"
        "E       assert 1 == 9\n"
        "test_alpha.py:1: AssertionError\n"
        "________________ test_same ________________\n"
        "E       assert 2 == 9\n"
        "test_beta.py:1: AssertionError\n"
        "================ short test summary info ================\n"
        "FAILED test_alpha.py::test_same - assert 1 == 9\n"
        "FAILED test_beta.py::test_same - assert 2 == 9\n"
    )
    assert M.matches(1, captured, "E       assert 1 == 9", "test_alpha.py::test_same")
    assert M.matches(1, captured, "E       assert 2 == 9", "test_beta.py::test_same")
    assert not M.matches(1, captured, "E       assert 2 == 9", "test_alpha.py::test_same")
    assert not M.matches(1, captured, "E       assert 1 == 9", "test_beta.py::test_same")
    # Without a location, duplicate section headings do not identify either node.
    ambiguous = re.sub(r"test_(?:alpha|beta).py:1: AssertionError\n", "", captured)
    assert not M.matches(1, ambiguous, "E       assert 2 == 9", "test_alpha.py::test_same")


def test_repeated_unittest_headers_do_not_retain_overlapping_bodies() -> None:
    failures = M.failed_tests("FAIL: t (K.t)\n" * 2_000)
    assert len(failures) == 2_000
    assert sum(len(item.body) for item in failures) == 0


def test_nonverbose_go_failure_parsing_does_linear_work(monkeypatch: pytest.MonkeyPatch) -> None:
    # Count inspected regex inputs instead of depending on machine timing. Old parsing scans
    # every preceding line again looking for a verbose-only RUN marker.
    real_match = M.re.match
    inspected = 0

    def counted_match(pattern: str, string: str, *args: object, **kwargs: object) -> object:
        nonlocal inspected
        inspected += 1
        if inspected > 40_000:
            pytest.fail("Go parser repeatedly rescanned earlier output")
        return real_match(pattern, string, *args, **kwargs)

    monkeypatch.setattr(M.re, "match", counted_match)
    lines = [f"--- FAIL: Test{number} (0.00s)" for number in range(8_000)]
    assert len(M._go(lines)) == len(lines)
    assert inspected <= len(lines) * 5


def test_overlapping_go_blocks_stop_at_the_shared_body_budget() -> None:
    # Nested/repeated verbose RUN ranges can overlap even with a one-pass RUN index.
    captured = "\n".join(
        [f"=== RUN Test{number}" for number in range(300)]
        + [f"--- FAIL: Test{number} (0.00s)" for number in range(300)]
    )
    with pytest.raises(M._ParseLimit, match="retained failure lines"):
        M.failed_tests(captured)
    assert not M.matches(1, captured, "assertion failed: original", "test.go::Test299")


def test_excess_failure_count_fails_closed() -> None:
    captured = "".join(f"FAILED test.py::test_{number}\n" for number in range(10_001))
    with pytest.raises(M._ParseLimit, match="too many failed tests"):
        M.failed_tests(captured)
    assert not M.matches(1, captured, "assertion failed: original", "test.py::test_0")


def test_assertion_values_after_long_common_prefix_must_agree() -> None:
    recorded = "---- repro stdout ----\nassertion failed: " + "x" * 250 + " expected 10000\n"
    assert not M.matches(1, recorded.replace("10000", "20000"), recorded, "test.rs::repro")


# bun test. These transcripts are synthetic: written to bun's documented output (an error block,
# then a ``(fail) suite > name [time]`` line, then a recap), with no real project content.
BUN = "tests/add.test.ts::math adds"


def _bun_vary(text: str) -> str:
    """The same run again: every duration and every scratch directory is different."""
    text = re.sub(r"\[(\d+)\.(\d+)ms\]", lambda m: f"[{int(m[1]) + 7}.{m[2]}3ms]", text)
    text = re.sub(r"\[(\d+)\.00ms\]", "[999.00ms]", text)
    text = text.replace("/tmp/scratch-8f3a1c/", "/private/var/folders/aa/bb/T/scratch-77d2/")
    return text.replace("/private/var/folders/qz/tmp.Xk29Ab/", "/home/runner/work/other/")


@pytest.mark.parametrize(
    ("rerun", "recorded"),
    [
        ("bun_two_failures", "bun_two_failures"),
        ("bun_one_failure", "bun_two_failures"),
        ("bun_two_failures", "bun_one_failure"),
    ],
)
def test_bun_failing_the_same_way_matches(rerun: str, recorded: str) -> None:
    assert _matches(rerun, recorded, BUN)
    assert _matches(rerun, recorded, "tests/add.test.ts::math > adds")
    assert _matches(rerun, recorded, "add.test.ts::math adds")


def test_bun_reads_the_failing_tests_and_their_assertion_blocks() -> None:
    found = {(item.file, item.name): item for item in M.failed_tests(_text("bun_two_failures"))}
    assert set(found) == {
        ("tests/add.test.ts", "math > adds"),
        ("tests/add.test.ts", "math > other"),
    }
    adds = found[("tests/add.test.ts", "math > adds")]
    assert any(line.startswith("error: expect(received).toBe(expected)") for line in adds.body)
    assert "Expected: 5" in adds.body and "Received: -1" in adds.body
    assert not any("other broke" in line for line in adds.body)
    assert M.failed_tests(_text("bun_pass")) == []


def test_bun_durations_and_scratch_paths_do_not_change_the_answer() -> None:
    for fixture in ("bun_two_failures", "bun_one_failure"):
        changed = _bun_vary(_text(fixture))
        assert changed != _text(fixture)
        assert M.matches(1, changed, _text("bun_two_failures"), BUN)
        assert M.matches(1, _text("bun_two_failures"), changed, BUN)
        assert M.matches(1, _coloured(changed), _text(fixture), BUN)


def test_bun_a_different_failing_test_does_not_match() -> None:
    assert not _matches("bun_two_failures", "bun_two_failures", "tests/add.test.ts::math ok")
    assert not _matches("bun_one_failure", "bun_two_failures", "tests/add.test.ts::math other")
    # the cited test passes in the re-run while another test fails
    passing_cited = _text("bun_two_failures").replace("(fail) math > adds", "(pass) math > adds")
    assert not M.matches(1, passing_cited, _text("bun_two_failures"), BUN)
    # the re-run fails a different test than the one recorded
    assert not M.matches(1, _text("bun_two_failures"), _text("bun_one_failure"),
                         "tests/add.test.ts::math other")


@pytest.mark.parametrize(
    ("before", "after"),
    [("Expected: 5", "Expected: 6"), ("Received: -1", "Received: -2"),
     ("toBe(expected)", "toEqual(expected)")],
)
def test_bun_a_different_assertion_does_not_match(before: str, after: str) -> None:
    changed = _text("bun_one_failure").replace(before, after)
    assert changed != _text("bun_one_failure")
    assert not M.matches(1, changed, _text("bun_two_failures"), BUN)
    assert not M.matches(1, _text("bun_two_failures"), changed, BUN)


def test_bun_a_passing_run_does_not_match() -> None:
    assert not M.matches(0, _text("bun_pass"), _text("bun_two_failures"), BUN)
    # a non-zero exit with nothing failing in the output is not the recorded failure either
    assert not M.matches(1, _text("bun_pass"), _text("bun_two_failures"), BUN)


def test_fallback_ignores_trailing_durations_and_absolute_path_directories() -> None:
    recorded = (
        "(fail) math > adds [0.85ms]\n"
        "      at <anonymous> (/tmp/scratch-8f3a1c/tests/add.test.ts:5:24)\n"
    )
    rerun = recorded.replace("0.85ms", "1.40ms").replace("/tmp/scratch-8f3a1c", "/var/other/dir")
    # no known runner's failure format and no test cited: the last specific line decides
    assert M.matches(1, rerun, recorded, "")
    assert M.matches(1, rerun, "(fail) math > adds [0.85ms]\n", "")
    assert M.matches(1, "(fail) math > adds [2.50s]\n", "(fail) math > adds [0.85ms]\n", "")
    # a different failing test or a different line is still a mismatch
    assert not M.matches(1, "(fail) math > other [0.85ms]\n", "(fail) math > adds [0.85ms]\n", "")
    assert not M.matches(1, rerun, "(fail) math > adds [0.85ms]\n      at <anonymous> (x.ts:6:24)\n", "")


def test_normalise_is_narrow_about_paths_and_durations() -> None:
    assert M.normalise("at /a/b/file.ts:12:5") == "at file.ts:12:5"
    assert M.normalise("at fn (/a/b/file.ts:12:5)") == "at fn (file.ts:12:5)"
    assert M.normalise("(fail) math > adds [0.85ms]") == "(fail) math > adds"
    # relative paths, URLs and values inside the assertion keep what they say
    assert M.normalise("see ./a/b.ts and src/c.ts") == "see ./a/b.ts and src/c.ts"
    assert M.normalise("GET http://host/a/b.ts") == "GET http://host/a/b.ts"
    assert M.normalise("Expected: 5 [3ms] more") == "Expected: 5 [3ms] more"
    assert M.normalise("Received: [1, 2]") == "Received: [1, 2]"
