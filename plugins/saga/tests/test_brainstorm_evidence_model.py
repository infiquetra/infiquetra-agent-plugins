"""Layer 1 — deterministic boundary and evidence-model checks (R17, R23).

Proves mechanically that no deterministic test asserts a question, its
wording, or the order of the creative dialogue, and that the six named
areas each have coverage.

Scope: the check collects question-shaped string constants module-wide,
walking every string literal outside docstrings, including module-level
Assign targets, Return values, and parametrize decorator arguments, and
keeps the assert-node rule as an additional signal.
"""

from __future__ import annotations

import ast
import importlib.util
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

_GUARD_MODULE_NAME = "test_brainstorm_evidence_model.py"

# exercises real production code, not just fakes.

# ---------------------------------------------------------------------------
# Deterministic coverage — six named areas
# ---------------------------------------------------------------------------

_REQUIRED_AREAS = (
    "artifact metadata",
    "resume lookup",
    "declared gate",
    "scope-confirmation state",
    "terminal routing",
    "helper ceilings",
)

_AREA_KEYWORDS = {
    "artifact metadata": ["capability", "activity", "maturity", "provenance"],
    "resume lookup": ["resume", "Exact match", "Tier 1"],
    "declared gate": ["brainstorm-scope-confirmation", "gate-record"],
    "scope-confirmation state": ["pending-confirmation", "requirements-ready"],
    "terminal routing": ["Plan it with", "Handoff", "Done for now"],
    "helper ceilings": ["grounding scout", "claim verifier", "distinct evidence question"],
}


def check_deterministic_coverage(texts: dict[str, str]) -> list[str]:
    violations: list[str] = []
    # Strip comments and docstrings: parse each file and collect string literals
    # that are inside assert nodes or function bodies, so a stub file containing
    # only a comment with keywords does not satisfy coverage.
    collected: list[str] = []
    for source in texts.values():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                for child in ast.walk(node.test):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str):
                        collected.append(child.value)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str):
                        # Exclude docstrings: first Expr(Constant) in function body
                        is_docstring = False
                        if (
                            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and node.body
                            and isinstance(node.body[0], ast.Expr)
                            and node.body[0].value is child
                        ):
                            is_docstring = True
                        if not is_docstring:
                            collected.append(child.value)
    combined = "\n".join(collected).lower()
    # Fallback: also consider raw text lower for areas whose keywords appear as code identifiers
    # but not as string literals (e.g., "grounding scout" as part of a larger string)
    raw_combined = "\n".join(texts.values()).lower()
    for area in _REQUIRED_AREAS:
        keywords = _AREA_KEYWORDS[area]
        if not any(kw.lower() in combined for kw in keywords):
            # No keyword reached `collected`, which holds only assert and function-body
            # string literals. A file carrying the keyword solely in a comment or docstring
            # therefore fails here rather than passing on raw text alone.
            if any(kw.lower() in raw_combined for kw in keywords):
                violations.append(
                    f"missing coverage for {area!r} (keyword only in comments/docstrings)"
                )
            else:
                violations.append(f"missing coverage for {area!r}")
    return violations


# ---------------------------------------------------------------------------
# No dialogue assertions — AST walk over tests/test_brainstorm_*.py
# ---------------------------------------------------------------------------

_INTERROGATIVES = ("what", "how", "why", "who", "when", "which", "can you", "could you")


def _is_question_shaped(literal: str) -> bool:
    stripped = literal.strip()
    if not stripped:
        return False
    if stripped.endswith("?"):
        return True
    lower = stripped.lower().lstrip()
    return any(lower.startswith(prefix) for prefix in _INTERROGATIVES)


class _DialogueVisitor(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.violations: list[str] = []
        self._parent_stack: list[ast.AST] = []
        self._filename = filename
        self._own_module = Path(filename).name == _GUARD_MODULE_NAME

    def visit(self, node: ast.AST) -> None:
        self._parent_stack.append(node)
        super().visit(node)
        self._parent_stack.pop()

    def _is_docstring(self, node: ast.Constant) -> bool:
        # Docstring is the first Expr(Constant) in a Module/ClassDef/FunctionDef
        # visit() pushes the current node, so stack is [..., parent, node]
        if len(self._parent_stack) < 2:
            return False
        parent = self._parent_stack[-2]
        if not isinstance(parent, ast.Expr):
            return False
        if len(self._parent_stack) < 3:
            return False
        grandparent = self._parent_stack[-3]
        return (
            isinstance(
                grandparent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and grandparent.body is not None
            and len(grandparent.body) > 0
            and grandparent.body[0] is parent
        )

    def _is_own_definition(self) -> bool:
        # The guard module's own definition of what a question-shaped string
        # is: the _INTERROGATIVES tuple and the "?" literal inside
        # _is_question_shaped. Scoped to the guard's own module path, so no
        # other module can claim the exempt names to bypass the check.
        if not self._own_module:
            return False
        for parent in self._parent_stack:
            if isinstance(parent, ast.Assign):
                for target in parent.targets:
                    if isinstance(target, ast.Name) and target.id == "_INTERROGATIVES":
                        return True
            if (
                isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
                and parent.name == "_is_question_shaped"
            ):
                return True
        return False

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and _is_question_shaped(node.value):
            if self._is_docstring(node):
                return
            if not self._is_own_definition():
                # Collect question-shaped constants module-wide: Assign targets, Return values,
                # parametrize args, and any other string literal that is question-shaped.
                # This catches module constants, helper return values, and ordered dialogue lists.
                self.violations.append(
                    f"{self._filename}:{node.lineno}: "
                    f"question-shaped string constant: {node.value!r}"
                )
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        literals: list[str] = []
        for child in ast.walk(node.test):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                literals.append(child.value)
        for lit in literals:
            if _is_question_shaped(lit):
                self.violations.append(
                    f"{self._filename}:{node.lineno}: question-shaped literal in assert: {lit!r}"
                )
        # Ordered sequence comparison: assert <list/tuple of 2+ question literals>
        # Detect when the assert's test is a Compare whose one side is a List/Tuple
        # holding 2+ question-shaped strings, or a bare List/Tuple with 2+ such strings.
        if isinstance(node.test, ast.Compare):
            for comp in [node.test.left, *node.test.comparators]:
                if isinstance(comp, (ast.List, ast.Tuple)) and len(comp.elts) >= 2:
                    seq_lits = [
                        e.value
                        for e in comp.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ]
                    if (
                        len(seq_lits) >= 2
                        and sum(1 for lit in seq_lits if _is_question_shaped(lit)) >= 2
                    ):
                        self.violations.append(
                            f"{self._filename}:{node.lineno}: "
                            "ordered question sequence in assert compare"
                        )
        if isinstance(node.test, (ast.List, ast.Tuple)) and len(node.test.elts) >= 2:
            seq_lits = [
                e.value
                for e in node.test.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
            if len(seq_lits) >= 2 and sum(1 for lit in seq_lits if _is_question_shaped(lit)) >= 2:
                self.violations.append(
                    f"{self._filename}:{node.lineno}: ordered question sequence in assert"
                )
        # Also detect ordered dialogue list in a module constant (e.g., DIALOGUE_ORDER = ["What ...?", "How ...?"])
        # This is already covered by visit_Constant for each element, but we also check for list constants
        # that contain 2+ question-shaped strings, even outside assert.
        self.generic_visit(node)

    def visit_List(self, node: ast.List) -> None:
        # Skip the guard module's own _INTERROGATIVES definition only
        if self._own_module:
            for parent in self._parent_stack:
                if isinstance(parent, ast.Assign):
                    for target in parent.targets:
                        if isinstance(target, ast.Name) and target.id == "_INTERROGATIVES":
                            self.generic_visit(node)
                            return
        # Detect ordered dialogue list in a constant (e.g., DIALOGUE_ORDER = ["What ...?", "How ...?"])
        # This catches non-assert ordered lists.
        lits = [
            e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        if len(lits) >= 2 and sum(1 for lit in lits if _is_question_shaped(lit)) >= 2:
            # Only report if this list is not already inside an assert (which already reported)
            in_assert = any(isinstance(p, ast.Assert) for p in self._parent_stack)
            if not in_assert:
                self.violations.append(
                    f"{self._filename}:{node.lineno}: ordered question sequence list: {lits!r}"
                )
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        if self._own_module:
            for parent in self._parent_stack:
                if isinstance(parent, ast.Assign):
                    for target in parent.targets:
                        if isinstance(target, ast.Name) and target.id == "_INTERROGATIVES":
                            self.generic_visit(node)
                            return
        lits = [
            e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        if len(lits) >= 2 and sum(1 for lit in lits if _is_question_shaped(lit)) >= 2:
            in_assert = any(isinstance(p, ast.Assert) for p in self._parent_stack)
            if not in_assert:
                self.violations.append(
                    f"{self._filename}:{node.lineno}: ordered question sequence tuple: {lits!r}"
                )
        self.generic_visit(node)


def check_no_dialogue_assertions(source: str, filename: str = "<unknown>") -> list[str]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [f"{filename}: unparseable: {exc}"]
    visitor = _DialogueVisitor(filename)
    visitor.visit(tree)
    return visitor.violations


def find_dialogue_assertions(paths: Iterable[Path]) -> list[str]:
    """Scan each module separately and report `<path>:<line>` violations.

    The `_INTERROGATIVES` / `_is_question_shaped` exemption applies only to
    the guard's own module, so a renamed constant in any other module is
    still flagged.
    """
    violations: list[str] = []
    for path in sorted(paths):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            violations.append(f"{path}: unreadable: {exc}")
            continue
        violations.extend(check_no_dialogue_assertions(source, filename=str(path)))
    return violations


def test_deterministic_coverage_positive() -> None:
    texts: dict[str, str] = {}
    for path in sorted(Path(__file__).resolve().parent.glob("test_brainstorm_*.py")):
        texts[path.name] = path.read_text(encoding="utf-8")
    violations = check_deterministic_coverage(texts)
    assert violations == [], f"deterministic coverage gaps: {violations}"
    # Seeded gap must be found — remove all keywords for one area
    mutated = dict(texts)
    for name in list(mutated.keys()):
        for kw in _AREA_KEYWORDS["scope-confirmation state"]:
            mutated[name] = mutated[name].replace(kw, "")
    assert check_deterministic_coverage(mutated) != []


def test_no_dialogue_assertions_negative_load_bearing() -> None:
    sources = sorted(Path(__file__).resolve().parent.glob("test_brainstorm_*.py"))
    assert sources, "no Brainstorm test modules discovered"
    violations = find_dialogue_assertions(sources)
    assert violations == [], f"dialogue assertions found: {violations}"
    # Seeded question-shaped literal must be found
    seeded = 'def test_seeded():\n    assert "What is the best approach?" in text\n'
    assert check_no_dialogue_assertions(seeded) != []
    seeded_seq = 'def test_seeded():\n    assert ["What is X?", "How to Y?"] == expected\n'
    assert check_no_dialogue_assertions(seeded_seq) != []


def test_find_dialogue_assertions_flags_control_question(tmp_path: Path) -> None:
    mod = tmp_path / "synthetic_control.py"
    mod.write_text('QUESTION = "What is the best approach?"\n', encoding="utf-8")
    violations = find_dialogue_assertions([mod])
    assert violations != [], "control question-shaped constant was not flagged"
    assert any(v.startswith(f"{mod}:1:") for v in violations), violations


def test_find_dialogue_assertions_flags_renamed_interrogatives_escape(
    tmp_path: Path,
) -> None:
    mod = tmp_path / "synthetic_escape.py"
    mod.write_text('_INTERROGATIVES = ("What is X?", "How is Y?")\n', encoding="utf-8")
    violations = find_dialogue_assertions([mod])
    assert violations != [], (
        "a renamed _INTERROGATIVES tuple outside the guard module must be flagged"
    )
    assert all(str(mod) in v for v in violations), violations


def test_find_dialogue_assertions_exempts_guard_own_module(tmp_path: Path) -> None:
    mod = tmp_path / "test_brainstorm_evidence_model.py"
    mod.write_text('_INTERROGATIVES = ("What is X?", "How is Y?")\n', encoding="utf-8")
    assert find_dialogue_assertions([mod]) == []


def test_offline_and_side_effect_free_negative() -> None:
    # Harness must not write under docs/brainstorms or .claude/saga and must not open sockets.
    # Check #1: run does not create new files in those trees.
    brainstorms = ROOT / "docs/brainstorms"
    saga_state = ROOT / ".claude/saga"
    before_brainstorms = set(brainstorms.rglob("*")) if brainstorms.exists() else set()
    before_saga = set(saga_state.rglob("*")) if saga_state.exists() else set()
    # Import and exercise the grade path (pure, no I/O) — should not touch those trees.
    spec = importlib.util.spec_from_file_location(
        "scenarios_grade_check", Path(__file__).resolve().parent / "test_brainstorm_scenarios.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    after_brainstorms = set(brainstorms.rglob("*")) if brainstorms.exists() else set()
    after_saga = set(saga_state.rglob("*")) if saga_state.exists() else set()
    assert before_brainstorms == after_brainstorms, "harness wrote under docs/brainstorms"
    assert before_saga == after_saga, "harness touched .claude/saga"
    # Check #2: no socket import in the evidence modules (check via AST, not substring)
    for mod_name in (
        "test_brainstorm_evidence_model",
        "test_brainstorm_scenarios",
        "test_brainstorm_predicate_wiring",
    ):
        path = ROOT / f"tests/{mod_name}.py"
        if path.exists():
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name != "socket", f"{mod_name} imports socket"
                if isinstance(node, ast.ImportFrom) and node.module == "socket":
                    raise AssertionError(f"{mod_name} imports from socket")
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == "socket"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "socket"
                ):
                    raise AssertionError(f"{mod_name} opens socket.socket")
