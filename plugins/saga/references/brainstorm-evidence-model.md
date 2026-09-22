# Brainstorm Evidence Model — Three Layers for Issue 915 (B3)

How the suite proves the behaviour B1 and B2 shipped without turning a
conversational judgment into a unit-test fact. Prior art reviewed, shape
reused, and what this suite explicitly does **not** prove.

## Prior art — reviewed and recorded

Four candidates already in the repository were reviewed before designing
this model. Each verdict is a fit decision, not a reimplementation.

| Candidate | Location | Verdict | Reason |
|---|---|---|---|
| Data-file case suite + injectable runner + deterministic graders | the engine benchmark suite, whose header stated that graders are never model-graded (removed with the engine family by issue 1030; the shape is recorded here, not the file) | **Reuse the shape** | Cases as data, runner injectable, grading deterministic and never LLM-judged; live grading opt-in behind env var, never in CI (R23, KTD5) |
| Markdown rubrics with narrative scoring bands | `plugins/saga/references/rubrics/` + `plugins/saga/scripts/lifecycle_review.py` | **Reuse the dimension vocabulary, decline the Markdown carrier** | R19 needs per-dimension reporting with rubric as data, not inlined prose assertions; Markdown would require parsing and would hide the rubric from the grader's structured input |
| Standalone AST visitor + fixtures + whole-suite invariant | `scripts/lint_test_shape.py` + `tests/test_lint_test_shape.py` | **Reuse the mechanism** | `ast.NodeVisitor` plus dataclass report plus whole-suite invariant for R17's mechanical dialogue-assertion check |
| In-memory string surgery feeding a pure analyzer | `tests/test_concurrency_conformance.py::_mutate_source` | **Reuse the mechanism** | Mutation proof via `text.replace(needle, "", 1)` feeding the same `check_*(text)` predicate (KTD3) |

## Layer 1 — Deterministic contract boundary, mechanically enforced

`tests/test_brainstorm_evidence_model.py` walks the AST of every
`tests/test_brainstorm_*.py` module. Scope: the check collects every question-shaped string
constant **module-wide** — module-level `Assign` targets, helper-function return values,
`parametrize` decorator arguments, literals inside `assert` statements, and any other string
literal — so the earlier escape hatches (a question held in a module constant, returned by a
helper predicate, or fed through `parametrize`) are detected, not missed. Docstrings are the
one deliberate exclusion (the visitor proves a node is a docstring by parent shape before
skipping it), plus the guard module's own definition of question-shapedness (the `_INTERROGATIVES`
tuple and `_is_question_shaped`, exempted only when the parsed module is the guard's own
`test_brainstorm_evidence_model.py` — any other module defining those names is still flagged). The remaining blind spot is deliberate: JSON data files
(such as `tests/data/brainstorm/`) are not Python source, so the walk does not see them —
those cases are authored design data, not test assertions. The check fails on:

- any question-shaped string constant outside a docstring — one that ends with `?` or opens
  with an interrogative (`what`, `how`, `why`, `who`, `when`, `which`, `can you`, `could you`)
  — wherever it appears in the module;
- any `assert` whose comparison involves an ordered sequence (list/tuple literal) of
  two or more such question-shaped literals.

The walk is `ast.NodeVisitor` only; no substring search over the file.
This proves R17 over the test sources rather than by reviewer promise:
no deterministic test asserts which question is asked, its wording, or
the order of the creative dialogue.

Deterministic coverage is also asserted: a keyword-presence scan over the test sources against a
hardcoded `_AREA_KEYWORDS` list checks that artifact metadata, resume
lookup, the declared `brainstorm-scope-confirmation` gate,
scope-confirmation state, terminal routing, and helper ceilings are mentioned; it does not prove an
assertion executed.

## Layer 2 — Scenario evaluations scored per dimension

`tests/data/brainstorm/scenarios.json` holds the case set. Each case
carries `id`, `idea_seed`, `product_size` and `consequence` as
**independent** fields, `material_dimensions`, `authored_verdicts` per dimension,
and `transcript` (`captured` or `none`). The set varies both variables
independently (not collinear) and includes at minimum the four required
failure-mode kinds: `premature-convergence`, `missed-material-gap`,
`consequence-calibration`, `checklist-overengineering`.

`tests/data/brainstorm/rubric.json` holds dimensions and their band
descriptions as data, never inlined in assertions.

Scenario data stores `authored_verdicts` per dimension as authored design input; no `grade()` function exists yet and no live runner is wired. A top-level `grading_status` field discloses that no grader reads the verdict values yet. Layer 2 proves the data shape and per-dimension structure, not that any transcript was graded.

**Authored case data is expected and permitted.** `scenarios.json`,
`rubric.json`, and `calibration.json` are authored by this unit: they
define the idea seed, the two independent variables, the material
dimensions, and the `authored_verdicts` outcome per dimension. That is design input,
not evidence.

**Captured transcripts are optional and additive.** Where a parked-checkpoint run
transcript exists, a future `grade()` would run against it and the case would record
`transcript: captured`. Where none exists, the case records
`transcript: none` and the offline suite proves only what it can honestly prove today — shape, coverage, per-dimension reporting, no-aggregate, and gating. Calibration agreement will be proven when a grader exists; until then the offline suite proves the calibration data shape only. A missing failure-mode transcript never
blocks U3.

**The one thing that stays forbidden is mislabelling.** No case may
carry a synthesized transcript labelled `captured`. That is the
harness-substitution failure this constraint prevents.

No aggregate number is computed, stored, or reported. The data files expose no
`score`, `total`, `aggregate`, `overall`, or `quality` key at any level and no consumer
computes one — an AST walk over the test sources proves no assignment target with a banned
name — and reporting is per dimension only.

## Layer 3 — Evaluator trust and safeguard-phrase drift guard

*Audience: maintainer of tests and contract files. Version: 0.156.0.*

**Evaluator-trust rule (R20).** `is_blocking(finding, *, reproducible,
second_grader_agrees, operator_adjudicated) -> bool` returns `True`
unconditionally for a deterministic contract failure, and for a
model-judged finding returns `True` only when the scenario is
reproducible **and** either a second independent grader agrees or an
operator adjudication is recorded. The deterministic case plus the four decisive model-judged combinations are asserted directly.

**This rule is specified, not implemented.** No Saga script defines or calls `is_blocking`; the predicate lives in `tests/test_brainstorm_scenarios.py` and the two tests that exercise it are *specification* tests, fixing the intended rule so a future implementation has something to satisfy. They prove the rule's shape, not that anything Saga ships behaves this way. A similarly named `is_blocking_finding` lived in the second-opinion module that issue 938 removed; it was a different rule with a different signature (severity, status, pre-existing) and did not implement R20.

**Calibration (R21).** `tests/data/brainstorm/calibration.json` holds a
small fixed set of cases with expected grades and a `drift_floor` key that today has no consumer. No grader exists yet; the test asserts only that the calibration data has the expected shape (three cases, each with `id` and `expected` per rubric dimension) and that no aggregate target exists. Drift will be surfaced when a grader is built; until then the floor is data only.

**Safeguard-phrase drift guard (R22).** `tests/test_brainstorm_predicate_wiring.py`
carries one case per safeguard U1 and U2 declared critical — eight in
total: the ambiguity stop, the fresh-confirmation rule, the route-gating
on declared readiness, the no-deferred-save rule, the helper ceiling,
the map-privacy rule, the no-named-assurance-level rule, and the helper
read-only capability rule. Each case reads the real file, removes the
rule's text in memory, calls the same `check_*` predicate the contract
test calls, asserts violation, then asserts the unmutated text reports
none. These prove the safeguard sentence is present and its predicate is wired — not that the safeguard's behaviour holds. A meta-assertion requires every safeguard named in the
declared-critical list to have a case, so adding a safeguard without a
drift-guard case fails.

## What this suite does not prove

The suite proves the deterministic boundary, the data shape and per-dimension structure, and the gating machinery. It does **not** prove the evaluator-trust rule (R20) is enforced anywhere: that predicate is specified in the test module and has no production implementation or caller, so those assertions would pass unchanged if every other part of this evidence work were deleted. It does **not** prove that any
given brainstorm was good and it does not prove any transcript was graded — Layer 2 has no grader yet and the drift check is deferred. Layer 3's eight cases prove a safeguard sentence is present and its predicate is wired, not that the safeguard's behaviour holds — a file edited to instruct the opposite of a safeguard while keeping its sentence would still pass the string check. Formal completeness and contradiction review
stay after the confirmed artifact, in Document Review or a narrow
post-write validator, never in the live dialogue. A green scenario run
without a captured transcript proves the case set's shape, not the quality of a conversation that was never
captured. The AST check's scope is as described in Layer 1: question-shaped string constants are
detected module-wide across the brainstorm test modules, each module parsed separately with
violations reported as `<path>:<line>`; docstrings, the guard module's own
definitions, and non-Python data files stay outside it.

## Offline and side-effect-free (R23)

The harness runs offline, writes nothing under `docs/brainstorms/`,
mutates no path under `.claude/saga/`, and opens no socket.
