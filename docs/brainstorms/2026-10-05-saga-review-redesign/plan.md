---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# Saga review redesign: the decided plan

This is the source brief for the issue cards in `cards/`. It restates the plan the operator settled on
4 and 5 October 2026. The working page is private to the operator; the evidence behind each decision
(prior-art research, our review experiments, measurements) stays in the operator's private notes and is
left out here because some of it concerns private repositories.

## Decisions added when the plan became issues (5 October 2026)

- **A second reviewer on high-risk cards.** On a card whose risk is high (money, security, data
  deletion, concurrency), the gate runs a second targeted reviewer, from a different vendor where one
  is staffed, on the same packet, without seeing the first reviewer's findings. Findings are merged;
  blocking still needs reproduction. The harness measures what the second reviewer adds on high-risk
  corpus cases.
- **The earlier enhancement plan (4 October 2026).** Its must-fix Jev call, points score, separate
  calibration card and plan-review checklist are replaced by this plan. Its status band (second
  version), per-turn step reminder with an issue-update cadence, budget at admission, and cost by step
  and role in the cost report are filed as their own cards. Backstop gates stay deferred, as the
  operator decided then.

## Decisions added while the cards were drafted (5 October 2026)

- **Code sent to the classifier.** The fleet's TypeSafe data rule also allows code from the files a
  change touches (the changed function, or the changed block with about 20 lines around it), after
  redaction. The sweep only points the reviewer at places and never blocks or clears anything, so it is
  not screening.
- **Tool findings the lens tables do not name.** A linter or checker finding at the tool's own error
  level blocks; warnings are fix later; style and information messages are notes. Broken links are fix
  later; spelling and Markdown style are notes. Type checkers compare the whole project before and after
  the change, so a type error the change causes in an untouched file still blocks; Swift's
  strict-concurrency diagnostics count as type errors. Findings from a tool that gives no severity are
  fix later, except rule IDs on a curated list the operator reviews. A dependency vulnerability with no
  score counts as high. Medium and low dependency, workflow and infrastructure findings are fix later.
- **How the reviewer runs.** Real reviews always run with instruction files such as CLAUDE.md and
  AGENTS.md and the operator's plugins, and the reviewer may come from any vendor. So the reviewer runs
  with its normal configuration and the subscription sign-in, started through agent-launcher, in real
  reviews and in the harness alike. The harness turns a component off only where it can be turned off
  selectively and a comparison shows it has no effect on review results, and it can run trials on other
  vendors. The calibration file records the configuration it measured; a review whose configuration
  differs says so, and the next drift run measures it. Every reproduction test runs in a sandbox (the
  scratch copy only, no network, no credentials), and the review command re-runs each one before a
  finding counts as reproduced.
- **Pattern checks.** Each blocks unless the builder records a reason, with the harm it encodes: a
  release sharing a cleanup block is two holders of one exclusive thing; a swallowed error, a silent
  skip and a naive time comparison are a wrong result reported as success; a write that skips the
  shared update path is data lost or corrupted; money stored as floating point is money wrongly moved.
- **CI** runs the same pinned tools with the same outcomes as review, on what the change introduces.
  Saga's pinned versions become the standard's, and the standard becomes required.
- **Langfuse HTTPS** uses a publicly trusted certificate, so no client needs a new trust root. Every
  client moves to the HTTPS name, and plain HTTP closes to the network.
- **The outcome job** runs once a day on the operator's Mac.
- **The operator and held-out cases.** The operator may confirm held-out cases and review question
  wording. Nothing changes because of an individual held-out result, tuning agents never see held-out
  cases, and examples shown in question reviews come from the tuning half.
- **Unattended runs.** "Unattended" is the run mode the run's intent envelope already records. The
  30-minute fallback applies only where the asking screen can time out. An unattended merge follows the
  envelope's merge setting, and fix-later choices never hold a merge.
- **The builder record.** One per unit, in the same format as a corpus case's: the declarations
  against the policy questions and every reason the builder gives. The question-bank card publishes the
  policy's 30 questions.
- **Labels for corpus cases.** The defect is always proven by running. Its lens, question and defect
  kind are proposed independently by Jev and a model from a second vendor. Agreements form a recommended
  list, with disagreements and low-confidence labels at its top, and the operator approves the list in
  one review rather than case by case.
- **Starting the corpus.** Public sets and planted defects fill the tuning half and get the harness
  running, so labelling our history is not a prerequisite for starting. Every history case goes to the
  held-out half, which stays history plus planted because public sets sit in models' training data: at
  most about 200 history defects. The held-out minimums are checked before the harness's first full run.

## The plan

Settled with the operator on 4 and 5 October 2026, after prior-art research and our own review experiments (kept in the operator's private notes). It replaces the earlier enhancement plan for code review. It is one full set of ten changes, built in the Order of work, with no try-it-and-come-back steps.

Review becomes mostly deterministic: tools, checks and narrow questions produce outputs, and a formula turns them into a grade.

Not finding everything is accepted; a senior engineer's review never found everything either. When the tools and questions come back clean, the change passes. LLM review stays, but as specific findings that count in the formula, never as the only reason to block or to run another round.

### Design rules

- **Every lens is a formula over outputs.** Tool results, check results and question answers each map to a condition: blocks merge, fix later, or note. The A–F table turns the conditions into the grade, and merge needs every lens at C or better. An average alone is not enough, because an average hides a blocker.
- **LLM findings are weighted inputs that cannot block alone.** A lens can have several questions the LLM answers, and they count. An LLM finding blocks only when it is reproduced: the LLM writes a test in a scratch copy of the code and runs it, and the test shows the problem, which makes it a deterministic signal. A finding the LLM only traced is fix-later and never starts another round. This applies to every lens.
- **The builder declares which questions apply.** For each question, the builder says whether it applies and names the test that proves it is handled; code checks those tests exist and pass. When the LLM disputes a "doesn't apply", the operator sees it when confirming the merge.
- **Every source emits the same records,** and code validates them. Tools, Jev and the LLM all produce them (change 1).
- **A lens blocks only after it clears its pass mark on the corpus.** Until then it runs and reports, but it cannot block.
- **A missing tool degrades the review; it doesn't stop it.** Saga's setup step finds what is installed and offers to install the rest. Without a tool, Jev or the LLM answers that question instead, the record marks the answer degraded, and a degraded answer cannot block on its own.
- **Everything is measured.** Every review run is recorded in Langfuse, and every change to the review is checked against the corpus before it ships.

### What we will build (ten changes)

#### Change 1: One finding record and one measurement record

Every source writes the same five records, and code validates each one and sends back anything malformed.

- **Finding:** lens; the question or tool rule that produced it; the source (tool and version, classifier and model, or LLM and model); location (file, lines, function); a one-sentence statement; consequence, trigger and evidence from the fixed lists; proof (the failing test or command output when reproduced, the file-and-line steps when traced); whether this change introduced it; whether it is degraded; and the severity, which code computes and the reviewer never writes.
- **Measurement:** one per number a tool produces, such as changed-line branch coverage or mutation score, with its threshold and the condition it maps to.
- **Where-to-look item:** one per classifier hit, with the questions that fired, their probabilities, the classifier and model, and the LLM's answer: a finding, or cleared with a reason.
- **Lens grade:** the conditions counted, the A–F grade, the degraded inputs, and whether the lens may block.
- **Review run:** all of the above for one review, plus the change reviewed (repository, base and head commit), tool versions, tokens, cost and time. Saga posts it to Langfuse as one trace; outcomes attach to findings later as scores.

#### Change 2: A saga setup step for tools

A step of its own, never part of a run. It checks the machine and the repository for everything saga needs, not only what review needs; shows what is installed, missing or at the wrong version; asks before installing anything; and records the result. A run never asks setup questions: a missing tool marks its inputs as degraded, and saga says so.

**When it runs**
When the operator runs `/saga:setup`, or the same script from any harness. Claude Code gives plugins no install event (the nearest mod event is session start), so on the first session after install a mod notices setup has never run and offers it once. Other harnesses print a one-line suggestion on saga's first run.

**What it covers**

- **The machine:** the command-line tools saga uses (GitHub's `gh`, signed in; Python and uv; and the like), each language's review tools, and the parser the Jev sweep needs; and whether the TypeSafe and Langfuse keys are present, checked without ever printing them.
- **The repository:** the languages detected, the pinned tool versions and rule sets, the functional-test environment and the `/qa` strategies, all in `.saga-profile.json`.

**During runs**
No setup questions. A missing tool makes its checks degraded: the review's LLM answers them instead, and those answers cannot block on their own. Saga says so once per run in the status line, the run status, the review summary and the pull request comment, naming the missing tools and `/saga:setup`. Admission asks only for what a run needs that setup has not recorded, such as the functional-test environment.

**Screens**
In Claude Code, a setup pane lists each tool with its status, the lens it serves and a checkbox, and an Install button shows live progress. Elsewhere the script prints the same table and installs what the operator names.

**Languages**
Python, including AWS CDK code; TypeScript; Dart; Rust; Swift; Markdown; plus the shell scripts and GitHub workflow files these repositories carry.

**Default tools**

| Language | Security | Correctness | Testing | Architecture |
|---|---|---|---|---|
| Every language | Semgrep, gitleaks, osv-scanner | Semgrep (our own checks) | — | jscpd, lizard |
| Python | bandit, pip-audit | mypy, ruff | coverage.py branches, cosmic-ray, pytest-randomly, pytest-socket | ruff format, vulture, import-linter |
| TypeScript | npm audit | tsc strict, ESLint with typescript-eslint | Vitest or Jest coverage, StrykerJS | Prettier, knip, dependency-cruiser |
| Dart | osv-scanner on `pubspec.lock` | `dart analyze` with recommended lints | `package:coverage`, mutate4dart | `dart format` |
| Rust | cargo-deny | clippy, warnings as errors | cargo-llvm-cov, cargo-mutants, nextest | rustfmt, cargo-machete |
| Swift | — (gap) | strict concurrency, SwiftLint | llvm-cov, Muter | swift-format |
| Markdown | — | markdownlint-cli2 | — | lychee, cspell |
| Shell scripts | — | ShellCheck | — | shfmt |
| GitHub workflows | zizmor | actionlint | — | — |
| CloudFormation and CDK | Checkov, cdk-nag | cfn-lint | — | — |
 The operator reviews the set lens by lens. Known gaps run degraded: Swift dependency vulnerabilities, Flutter branch coverage (upstream issue 171580), Muter (macOS only, last release 2023), and blocking the network in tests outside Python.

**How the tools run**

- **Only what the change introduces:** saga filters every tool's findings to the changed lines itself, and compares base and head runs for whole-project results such as vulnerable dependencies and duplication. One implementation serves every tool.
- **Changed-line coverage:** one small adapter reads each language's standard coverage report (LCOV, Cobertura, coverage.py JSON) and matches it against the diff.
- **Pinned versions:** the repository profile records each tool's exact version and rule set; changing either is a change to the review and must pass the corpus first.
- **The same checks in CI:** the standard is set in infiquetra-context-library (`docs/delivery/ci-cd-standards.md` and `docs/testing/quality-gates.md`, which cover docs, Python/CDK and Flutter repositories today). They gain the pinned set for every language, and each repository's CI runs it as a required check.

#### Change 3: Tools per lens, reporting only what the change introduces

Security: pattern scanners with our own rules, secret scanning, dependency audits, workflow and infrastructure checks. Testing: changed-line branch coverage, mutation testing, test runs in random order and without network. Correctness: type checks, the tests and functional run, and a search for every reader of a changed name. Architecture and maintainability: repository rules, duplication, complexity. They run in the build loop, so the builder fixes what they report before review. The exact tool for each language comes from the setup step's survey.

#### Change 4: Our own checks for the bugs we keep hitting

Pattern rules and small scripts for the defects our reviews keep finding: a lock or lease not released on every exit path, success reported after a failure, an item dropped without a trace, a reader of a changed name left behind. Each rule comes with seeded positive and negative cases in the corpus.

#### Change 5: A Jev sweep that says where to look

Split the change into small pieces and ask each piece a bank of yes/no and multiple-choice questions for each lens: common bugs, security mistakes, our own recurring defects. The piece size (lines, a changed block, a function, a file) and the question bank are tuned on the corpus until the "yes" answers are useful. The output is a where-to-look list: each location with the questions that fired. Every reviewer gets the same list, so they look in the same places.

**Where it lives**
In fleet-core, as `jev sweep` beside the other Jev commands, with saga calling it. The classifier is a swappable part: TypeSafe Jev today, a local model later if we want one. Every classifier is scored on the same corpus, so a swap is measured.

**Questions**
The starting bank draws on three sources: the policy's 30 questions where no tool can answer them, the defects we keep hitting, and public lists of common mistakes where the corpus shows a gap. Each lens starts with about 10–20 questions, and the operator reviews each lens's set before it is used.

**How it runs**

- **Pieces:** the whole changed function by default, found by a parser for each language; the corpus may pick the changed block with about 20 lines around it, or a small whole file, for particular questions.
- **Classifier contract:** every classifier takes the question, its options with definitions, the piece, its path and language, and returns a probability per option plus its name, model, cost and time. Answers are cached. A new classifier replaces Jev only if it scores at least as well on the corpus. Code goes through fleet-core's client, which removes secrets first.
- **Thresholds and caps:** each question's threshold is set on the corpus to catch at least 9 in 10 of the planted defects it targets. The where-to-look list is capped at 30 items per review, highest probability first, and the sweep at $1 per review; until the corpus has set a question's threshold, the sweep takes its 30 most likely items; whatever a cap cuts is listed in the record as degraded.
- **Order check:** multiple-choice questions are asked in two option orders and averaged, because Jev leans toward the first option; yes/no questions are asked once.
- **When:** in the build loop, so the builder sees the list first and fixes or explains each item; the review's LLM confirms or clears what is left.

#### Change 6: Targeted LLM review, plus one capped open search

The LLM answers every item on the where-to-look list, either confirming it with a specific finding or clearing it with a reason, and code checks that it skipped none. When it believes a finding, it tries to reproduce it with a test in a scratch copy of the code. Then it runs one open search with a cap on findings. A finding must give a location, the closed-list labels, and a trace or a reproduction. Once Langfuse holds enough data, an evaluation re-runs full reviews on past changes to show what this shape missed, and whether `/qa` or later work caught it.

**High-risk cards**
On a card whose risk is high (money, security, deleting data, concurrency), the gate runs a second targeted reviewer, from a different vendor where one is staffed, on the same packet and blind to the first reviewer's findings. The findings are merged, and blocking still needs reproduction. The harness measures what the second reviewer adds on high-risk corpus cases. Decided 4 October and carried into this design on 5 October.

#### Change 7: The formula

For each lens, every input maps to a condition: blocks merge, fix later, or note. The A–F table turns the conditions into the grade, and merge needs every lens at C or better. Questions the LLM answers are inputs with a weight; none can block alone while the deterministic inputs pass. Degraded inputs are marked in the grade.

#### Change 8: The lifecycle

Code review is replaced in one change. `/code-review` becomes the single review command; the lens roster, the consensus scoring, the verification step, both result formats, the unused Jev checks and the lens-reviewer role are deleted, with no old version kept behind a switch. Saga switches over as soon as the review command exists. Every lens reports until the calibration file shows it cleared its marks.

**Rounds**

- Every lens at C or better: stop and go to merge confirmation.
- A repair round that leaves the same blocking items: stop early. Round 3: stop.
- At an early stop or the limit, the operator either merges with a recorded reason, which files the blocking items as linked defect issues through mission-control, or stops the card.
- A later round re-checks only the code the repair changed. The two escalation rounds and the admission question that set round limits are gone. Jev keeps the sweep and helps choose a reproduced finding's consequence.

**Watched**
The operator doubts that later rounds are worth their cost. Most of the prior art reviews again on each push, usually only the new changes, but it advises; none holds the merge for a loop. Each review run records the rounds it used and what each later round added (new blocking items, items cleared, cost and time). A Langfuse view shows how often round 2 or 3 finds anything new, and that number decides whether to move to one round.

**While a lens only reports**
The one block saga has today stays: reproduced data loss or a reproduced security exposure blocks merge.

**Build loop**

- Each unit's build loop runs the tools, our checks and the sweep on that unit's changes. A unit cannot hand off until every policy question has a declaration and every proving test it names exists and passes.
- The combined-branch pass reruns the tools on the whole branch. A blocking tool finding there fails the gate before the LLM step, so no model spend goes on a known block.
- fleet-core uses Python's standard library only, which can find a changed function only in Python. The parser for other languages is a tool from the setup step; without it the sweep falls back to the changed block plus about 20 lines, marked degraded.

**Optional lenses**

- The 11 optional lenses become questions inside the four, asked only when the change touches the matching kind of code: reliability, API contracts and performance in correctness; attacker-minded review and privacy in security; deployment and infrastructure in security and architecture; documentation and agent usability in architecture. They are tuned on the corpus like every other question.
- "Previous comments" becomes a merge check: unresolved review threads on the pull request block merge.
- Accessibility and user experience leave code review. Their home is `/qa`'s app-interface strategy, which has no driver today; building one is outside this plan.
- Admission stops asking the operator to declare lenses.

**Plan review**

- One reviewer (the plan reviewer, Opus at high effort, as today), one pass. Its findings use the finding record and go to Langfuse.
- The plan's author fixes every finding, or rejects one believed wrong with a reason. Code checks that none is left unanswered, and rejections are listed for the operator.
- The check that every acceptance criterion maps to a check stays and keeps blocking; the correctness lens relies on it.
- No Jev re-ranking: it failed that test on a past plan review, calling most findings blocking where the final rankings kept few.

**After merge**
`/qa` records which review run passed the code it tests, and its failures post to Langfuse as that review's misses. The release step writes the merged commit to the run record; nothing does today, so `/qa`'s recorded revision can be empty.

#### Change 9: Langfuse as the measurement system

A dedicated Langfuse project for review data. Saga posts one structured record per review run: tool outputs, Jev answers, LLM findings, the formula's inputs and the grade. Outcomes attach to each finding later: fixed before merge, found by `/qa`, found after merge, reverted. The corpus lives there as a dataset, and evaluators compute hit rates per lens and per question on every run. We own the configuration and change it as needed, including size limits, sampling and retention.

**Project and keys**
A "Saga Reviews" project. The operator creates it and its key pair in the Langfuse web interface. The keys live in keychain-env, like the TypeSafe key; saga reads them from the environment and never prints them.

**What a review run looks like**

- **One trace per review run,** carrying the repository, base and head commits, card, saga version and tool versions.
- **Under it, one entry per step:** each tool run, the Jev sweep, each LLM step, and the formula.
- **One entry per finding,** so outcomes attach to the finding itself.

**What goes in, and what stays out**

- **In:** the five records (findings, measurements, where-to-look items, lens grades, and the review run with its cost and time), plus the code excerpt at each finding's location.
- **Out:** raw tool output stays on the machine, referenced by a fingerprint of its content.
- **Secrets** are removed before anything is sent. A secret-scanner finding carries its location, never the secret.
- **HTTPS first:** the server runs plain HTTP today. It gets HTTPS, with a publicly trusted certificate, before any CAMPPS code excerpt is sent (a home-lab change).

**Who records outcomes, and when**

- **At merge,** saga records each finding's fate: fixed (its lines changed and its reproducing test now passes) or dismissed, with the reason.
- **When `/qa` runs,** each problem it finds in merged code is recorded as missed by the review that passed that code.
- **On a schedule,** a job links new defect issues and reverts to the review runs that passed the code they touch, matched by file and line.

**Datasets, evaluators and retention**

- **The corpus is one dataset,** its cases split into tuning and held-out. Each harness run over it is recorded against that dataset.
- **Evaluators are plain code first.** They compute the agreed numbers: per-lens hits and false blocks, per-question precision, grade stability, and cost. LLM-based evaluators come in only after they are checked against hand labels.
- **Nothing is deleted automatically.** The records are small, and future tuning depends on them.

#### Change 10: What the operator sees and chooses

One script writes the review's state and the pending choices as a single structured document. Every screen reads it, and every answer goes back through the script, the way today's admission pane works.

**Claude Code**

- **A live review pane,** replacing `/review-view`: each lens's grade with its blocking and fix-later counts, the where-to-look list with each item's state, which tools ran or were missing, the round and the cost so far, and a round-by-round view of what each round found that the one before did not.
- **A merge-confirmation pane:** the grades; any blocking items, with an override box that needs a reason; disputed "doesn't apply" declarations; the fix-later list, where each item can be fixed now, filed as an issue, or left; degraded inputs; and the cost.
- **During a run,** a one-line band above the prompt and a status-line entry for missing tools; and the setup pane (change 2).

**Other harnesses**
The skill prints the same document as Markdown and asks the same choices as numbered questions. Answers go through the same script.

**GitHub**
The pull request comment carries the same summary, with the fix-later list as a checklist: the one screen every harness, and a phone, can share.

**Fix-later items**

- They never hold up a run or a merge. Every review posts its fix-later list as a checklist on the pull request and records it in Langfuse.
- **Attended:** merge confirmation offers three choices for each item. **Fix now** sends it to a repair round before merge, like a blocking item; that round does not count toward the 3-round limit, because the operator chose it. **File as issue** files it at once through mission-control. **Leave** keeps it on the checklist.
- **Security guard:** a harm the security lens's LLM traced but could not reproduce is always filed as an issue, attended or not, unless it is fixed now.
- **Unattended** (marked so at the start, or a question unanswered for 30 minutes, the admission pane's wait today): nothing is filed then. A box ticked later, from any harness or from GitHub, is filed by the scheduled outcome job on its next pass, which links the new issue back into the comment.
- A repository may set a different unattended default in its profile, such as one follow-up issue per pull request listing all its items.

### Lens by lens

Each lens's inputs, what answers them, and the result each one maps to. Settled one lens at a time with the operator.

#### Testing: would the tests that come with the change catch it being wrong?

| Input | Answered by | Result |
|---|---|---|
| A changed branch no test runs | coverage tool, changed lines only | Blocks, unless the builder recorded it as unreachable, with a reason |
| A deliberate change the tests let through (a surviving mutant) | mutation tool, changed lines only | Blocks, unless recorded as making no real difference, with a reason |
| A new test that passes on the code before the change, or a regression test that passes before its fix | two test runs | Blocks |
| A new test CI skipped or never collected, with no reason | CI log | Blocks |
| A test that fails in random order or with the network blocked | test runs | Fix later |
| A test that fakes the code under test | classifier, then the LLM | Fix later; a defect it hides is blocked by the mutation tool |
| A test that writes to a live or shared system | classifier, then the LLM | Fix later, unless reproduced |

Every gap blocks unless the builder records a reason; gaps are not graded by the harm they might cause, because that needs a judgment. The tools run in the build loop, so most gaps are fixed before review. Recorded reasons are listed in every review record and checked by the LLM, which cannot block on them. Mutation testing has a 15-minute cap per review; anything unfinished is recorded as degraded.

#### Security: can the change be made to do something for someone who shouldn't be able to?

| Input | Answered by | Result |
|---|---|---|
| A scanner finding the change introduces, rated high or critical | pattern scanners for each language | Blocks, unless the builder records it as a false positive, with a reason |
| A scanner finding rated medium or low | the same scanners | Fix later |
| A secret in the diff | secret scanner | Blocks |
| A new dependency with a known high or critical vulnerability | dependency audit | Blocks, unless a reason is recorded |
| A high-rated workflow or infrastructure finding (an unpinned action in a publishing workflow, a wildcard IAM policy, public storage) | workflow and infrastructure checkers | Blocks |
| A required security test missing where the builder said the question applies: another caller refused on a record that isn't theirs, hostile input treated as plain data, redaction on each new outbound path | code check | Blocks |
| An LLM finding the LLM reproduced with a test | the LLM writes and runs the test | Blocks |
| An LLM finding it couldn't reproduce | the LLM | Fix later |
| The LLM disputes the builder's "doesn't apply" | the LLM | Fix later, and shown to the operator at merge confirmation |

The draft's seven questions stay: who may act on what, outside text treated as instructions, file permissions, secrets, data leaving, what the change brings in, and permissions granted. High and critical scanner findings block; medium and low are fix later.

#### Architecture and maintainability: does the change fit the system it lands in?

| Input | Answered by | Result |
|---|---|---|
| A repository structural check fails (for example `check_repo.py`, the packaging tests, import rules) | the repository's own checks | Blocks |
| A rule written only in prose (AGENTS.md, CLAUDE.md, recorded decisions) that the LLM says is broken | the LLM | Fix later; blocks only if the LLM writes a check that fails |
| The tests fail when run from a different working directory and home directory | one extra test run in the build loop | Blocks |
| A machine-specific value (absolute path, home directory, user name, hostname, account ID, URL) that doesn't come from configuration | search script, then the LLM judges each hit | Fix later, unless the relocated test run fails |
| A departure from an established pattern with no decision record | builder declaration, then the LLM | Note |
| A second copy of a value, list or rule (copies that disagree are a correctness problem) | duplicate-code tool and search | Note |
| Complexity, dead code, naming | tools | Note |

A structural rule can block only if it exists as a check, so a reviewer's structural taste never blocks a merge. Every change gets a test run from a different working directory and home directory in the build loop. The formatter fixes formatting in the build loop, so review never sees it.

#### Correctness: does the change do what was asked, and keep doing it under retries, interrupts, concurrency, old data and other callers?

| Input | Answered by | Result |
|---|---|---|
| An acceptance criterion with no check asserting its stated output | functional-checks map | Blocks |
| A type error the change introduces | type checker | Blocks |
| One of our pattern checks fires (a release sharing a cleanup block, a swallowed error, a silent skip, a write that skips the shared update path, a naive time comparison, money stored as floating point) | our checks | The result fixed when the check was written: blocks or fix later |
| A question the builder said applies has no proving test, or the test fails | code check | Blocks |
| A mention from the changed-name search the builder neither updated nor marked "unaffected" | search script | Blocks |
| A workflow state with no way out, where the workflow is data | graph check | Blocks |
| A supported build fails in CI's version matrix | CI | Blocks |
| An LLM finding it reproduced with a test | the LLM | By its consequence: harm blocks, misleading output is fix later |
| An LLM finding it couldn't reproduce | the LLM | Fix later |
| The LLM disputes the builder's "doesn't apply" or "unaffected" | the LLM | Fix later, and shown to the operator at merge confirmation |

The draft's 15 questions stay, in five groups: what was asked, shared state and timing, data crossing boundaries, failures and resources, callers and readers. Each pattern check carries its own consequence, so review never decides it. A reproduced LLM finding's consequence is picked separately by the LLM and by Jev from the fixed list; when they disagree, the lower one applies and the operator sees it at merge confirmation. Every mention outside the diff from the changed-name search must be updated or marked "unaffected"; documents and agent instructions are included, and a stale document is fix later at most. The proving test the draft names for each question is required wherever the builder says the question applies.

### Block, fix later and note

**The rule in one sentence:** only what is shown can block, meaning a tool or check result, a failing test, or a missing piece the builder had to provide; whatever a reviewer can only argue is fix later; and upkeep is a note.

**The three outcomes**

- **Blocks:** the lens drops to D (one) or F (two or more). Merge waits for a repair round; at the round limit the operator decides.
- **Fix later:** the lens drops to B (one or two) or C (three or more), never lower. It never starts a round on its own and never stops a merge. It goes on the pull request checklist and into Langfuse. At merge confirmation the operator can still fix any of them now, in a repair round that does not count toward the limit.
- **Note:** recorded only; the grade does not move.
- **Merge** needs every lens at C or better, which means no blocking item. The grade counts items rather than taking a percentage, so the same defect gets the same grade in a large change as in a small one.

**Fixed rules**
Most inputs have their outcome written down in advance: every row of the four lens tables above, and each of our pattern checks. A tool or check result is shown by its nature, so it can block where its row says so.

**Judged findings**
 A finding from the LLM states three facts from closed lists, and code computes the outcome:

| Consequence | When | Shown how | Outcome |
|---|---|---|---|
| Harm: data lost or corrupted, money or resources wrongly moved, a security boundary crossed, two holders of one exclusive thing, a wrong result reported as success, required behaviour missing, or a break in supported use | Normal use, or a specific legitimate condition such as a retry, an interrupt or two runs at once | Reproduced: the LLM's test fails in a scratch copy | Blocks |
| Harm, as above | Normal use or a legitimate condition | Traced or suspected only | Fix later |
| Harm | Misuse only | Any | Fix later |
| Visible: fails loudly and recoverably, or misleads a person while the work itself is right | Any | Any | Fix later |
| Upkeep: costs future work only, or style | Any | Any | Note |
 The LLM and Jev each pick the consequence; when they disagree the lower one applies and the operator sees it at merge confirmation.

**What changes an outcome**

- **Degraded:** a check answered by the LLM because its tool is missing cannot block on its own.
- **Report-only lens:** a lens that has not cleared its marks reports blocking items without stopping the merge, except reproduced data loss or a reproduced security exposure, which blocks regardless.
- **Disputes:** the LLM saying a builder's "doesn't apply" or "unaffected" is wrong is fix later, and shown at merge confirmation.
- **Jev never blocks.** It only says where to look.
- **Security guard:** a harm the security lens's LLM traced but could not reproduce is still fix later, but it is always filed as an issue, never left only on the checklist.
- **Confirmed with the operator:** fix-later items never add up to a block, however many there are; "misleads a person" stays fix later; medium and low scanner findings stay fix later, and the corpus shows whether any rating deserves promotion.
- **Replaced from the policy draft:** a missing tool no longer makes a lens "Incomplete"; its checks are answered by the LLM and marked degraded. A traced LLM finding no longer blocks; only a reproduced one does.

**Example: blocks**
A change wraps a card charge in a retry. The sweep flags the retry ("is this safe to repeat?"). The LLM writes a test where the first attempt charges and then times out, and the retry charges again; the test fails. Money wrongly moved, on a retry, reproduced: correctness drops to D. The builder adds an idempotency key and keeps the test; round 2 re-checks only the changed lines; correctness returns to A, and the change goes to merge confirmation.

**Example: passes with fix-later items**
A change adds a staff report. Semgrep reports one medium finding. The LLM traces a path where an empty filter could return other tenants' rows, but its test cannot make it happen. And a README section about the report was not updated. Security is B (two fix-later items), correctness is B (the stale document), and the change can merge. The tenant item is filed as an issue automatically (the security guard). At merge confirmation the operator might choose to fix the README now and leave the scanner finding on the checklist.

**Example: degraded**
A Swift change on a machine without Muter, the Swift mutation tool; Swift dependency audits have no tool at all. Coverage runs. For the mutation question the LLM answers instead and says two changed lines look untested, which as a degraded answer cannot block, so it shows as a degraded fix-later item. Testing is B, degraded; security is A, degraded. The change can merge, and the summary says which tools were missing and to run `/saga:setup`.

### Order of work

1. **Before saga switches over:** the review command and the five records (changes 1 and 7), the setup step (2), the tools, our checks and the sweep in the build loop (3 to 5), the targeted LLM review (6), the screens (10), and the Langfuse project, with HTTPS on its server before any CAMPPS code is sent (9). Every lens starts report-only.
2. **Built alongside:** the corpus, in a new private repository since it will hold CAMPPS code, and the harness. Both are set out below.
3. **Then** each lens starts blocking as the calibration file shows it cleared its marks. The pass marks are already set (see How we'll know it works).
4. **During the build,** each lens's question bank is written, and the operator reviews it one lens at a time before it is used.

### The corpus

Code with known defects, each with a clean twin, where the answer comes from a test, a tool or the operator, never from an LLM verdict alone. It lives in a new private repository, `infiquetra/saga-review-corpus`.

**What each source is for**

| Use | Source |
|---|---|
| Held-out cases, which decide pass marks | Our own cases only: our history and planted defects. |
| Tuning | Our planted defects first; history cases go only to the held-out half. Public sets of real bugs where they match a question's defect kind: BugsInPy and SWE-bench for Python; BugsJS and Multi-SWE-bench for JavaScript, TypeScript and Rust; RustMizan for Rust; CVEfixes for security. |
| Wiring checks | The rule test suites of Semgrep, ESLint, Clippy, SwiftLint, Dart's lints, markdownlint, KICS and cdk-nag: each tool runs, the changed-line filter works, severities map correctly. |
| Outside comparison | The Python and TypeScript pull requests in Martian's and Greptile's benchmarks. Never counts toward a pass mark. |

**Cases from our history**

- **Candidates:** our repositories' default branches carry thousands of commits titled as fixes or reverts over the past year, most in Python and Markdown, hundreds in TypeScript and Dart, few in shell and workflows, almost none in Swift and none in Rust. Some repositories keep branch commits when they merge, so part of this count is repairs made before merge. They are candidates, not cases.
- **Proof:** the fix's test fails on the version that introduced the defect and passes with the fix applied, checked by running both; or a pinned tool flags the defect version and not the fixed one.
- **The change to review** is the pull request that introduced the defect, traced from the lines the fix changed. Its clean twin is that pull request with the fix applied.
- **No LLM labels:** an LLM verdict alone never labels a case. That includes the findings past reviews confirmed with an LLM verifier; they count only when a test or tool reproduces them or the operator confirms them.
- **Old against new:** where today's saga reviewed the introducing pull request, its old findings give a before-and-after comparison on the same case.

**Planted defects**

- They fill every lens and language that history cannot: certainly Swift, Rust and shell, and probably Dart and much of security.
- They are planted into merged changes that no later fix touched; the original change is the clean twin.
- What to plant comes from the policy's questions and the defect kinds our history shows. Codex or Grok plants them, not Claude, so the reviewing model is not hunting defects written in its own style.
- Each needs a proof: a test that fails on it and passes on the twin, or a pinned tool that flags only the defect version. The operator confirms the ones no test or tool can show, plus 1 in 10 of the rest as a realism check.
- Defects from mutation tools count only for the testing lens.

**Size and split**

- **Held-out half:** at least 50 blocking defects per lens, at least 10 per lens for each language in use where the lens applies, and 100 ordinary clean changes. The tuning half is the same size: roughly 600 to 800 cases in all.
- **Why 50:** a lens that catches 45 of 50 could truly be anywhere from 79% to 96%. Halving that uncertainty takes four times the cases.
- **Per-language guard:** a lens that clears its marks overall but, in one language, catches fewer than 7 of 10 defects or blocks more than 2 of 10 clean changes only reports for that language. With 10 cases it trips 1% of the time for a lens truly at 9 in 10, and 62% of the time for one at 6 in 10.
- **The split** is fixed when a case is created and chosen by no one: history cases go to the held-out half, public-set cases to the tuning half, and planted cases by a hash of their pull request, so a defect and its twin land together. Whoever tunes questions, thresholds or the formula never sees held-out cases; the harness reports only totals for them.

**Relabelling**
When the review blocks a clean case or finds a defect nobody planted, a reproduction by test or tool plus the operator's confirmation relabels the case, and its twin stops counting as clean. Without a reproduction it counts as a false block.

**Format**
One folder per case, with a `case.json` record: source, language, lens, the question it targets, defect kind, location, proof and how to run it, split, licence and origin. Code is referenced, not copied: repository and commit IDs, with each planted defect or fix stored as a patch. Public sets come in as download scripts with pinned versions. A repository the corpus references is archived, never deleted.

**Drift check**
Every corpus run reports the share of cases from our history against planted ones, so a corpus drifting toward model-written defects shows.

### The harness

It runs the review on every corpus case and scores it, and it decides, through one file, which lenses may block.

**One review command**
`/code-review` keeps its name, but one script does the work: it takes the repository, the base and head commits, the repository profile and the builder's record; runs the tools, our checks and the Jev sweep; writes the packet for the LLM reviewer; checks what comes back; applies the formula; and writes the five records. The LLM reviewer is one agent with a fixed prompt file and output shape. In saga, orchestrate starts it through agent-launcher; in the harness, the harness starts it through agent-launcher too, with the same prompt, model, effort, tools and normal configuration (for Claude, `claude -p`), in a scratch copy of the change, and every test it writes runs sandboxed. The harness lives in the corpus repository and pins the saga and fleet-core versions it tests.

**Builder records**
Corpus cases have no builder, so each carries the record one would have written: the plan unit's acceptance criteria and their checks, the per-question declarations, and the reason for any coverage gap or surviving mutant. It is written once, shared by the defect version and its twin, and the twin is built to pass every rule about what the builder must provide. A block on a twin can then only come from a claimed defect. The rules about missing declarations are checked by ordinary tests in saga.

**Caching and cost**

- Each step's output is stored under a fingerprint of its inputs: case, step, tool or model version, rules, questions and prompt. A run redoes only the steps whose inputs changed.
- The operator sets a spending cap per run. The harness estimates the cost first, from the steps it must redo and their past costs, and does not start over the cap. The first full run's estimate comes from 20 cases.

**Repeat runs**
The deterministic part runs twice on every case and must match exactly. The LLM step runs twice on a fixed 1 in 10 of the cases. A lens that flips between blocking and passing on more than 1 in 10 of those repeated cases only reports.

**The calibration file**

- A file in saga holds a fingerprint of every review component (question banks, our checks, the formula, the default tool versions, the reviewer's prompt and model), the corpus version, each lens's held-out results overall and per language, the repeat-run result, the cost and the Langfuse run ID. It holds numbers only, so it can live in the public repository.
- The repository check fails when the fingerprint does not match the current components, so nothing that changes the review merges without a fresh corpus run.
- At review time saga reads the same file: a lens blocks, language by language, only where the file shows it cleared its marks under the current fingerprint. A repository whose profile pins different tool versions gets report-only for the lenses those tools serve.

**Held-out cases and drift**

- Opening a held-out case, for example to diagnose a miss, moves it to the tuning half; the harness refills the held-out half from new cases.
- Monthly, and whenever Jev reports a different model, the harness reruns the model steps without the cache on a sample of held-out cases. If a lens falls below its marks, it prepares a one-line change to the calibration file setting that lens to report-only, for the operator to merge.

**Where it runs**
On this Mac (Swift and Muter need macOS), as a background command running a few cases at a time. Each run goes to Langfuse, with a local summary that sets this run's table beside the previous one.

### How we'll know it works

- **A corpus run on every change** to tools, questions, rules or the formula. Per lens it measures:

  - known blocking defects found and blocked;
  - clean changes blocked;
  - the grade given to the same input twice (the deterministic part must match exactly, and the LLM part may flip a lens between blocking and passing on at most 1 in 10 repeated cases);
  - cost and time per review.

- **Pass marks fixed in advance, different for each lens,** measured on corpus cases we never tuned on:

| Lens | Must block, of known blocking defects | May block, of clean changes |
|---|---|---|
| Security | at least 9 in 10 | at most 1 in 10 |
| Testing | at least 9 in 10 | at most 1 in 10 |
| Correctness | at least 8 in 10 | at most 1 in 10 |
| Architecture and maintainability | at least 6 in 10 | at most 1 in 20 |
 The deterministic part must also give the same grade every time it sees the same input. A lens below its marks runs and reports, but cannot block until it clears them.
- **Rounds:** each review run records the rounds it used and what each later round added. If round 2 or 3 rarely finds anything new, we move to one round.
- **In use:** outcome scores in Langfuse per finding and per question. Anything found later by `/qa` or after merge is traced to the question or tool that should have caught it, then added to the corpus.

### Where the plan stands

1. Every design decision is settled: the four lenses, the Jev sweep, the setup step, the Langfuse project, the corpus, the harness, the lifecycle and the screens.
2. The walk-through of block, fix later and note is done, and the operator is on board (see Block, fix later and note), with two additions: a "fix now" choice for fix-later items, and the security guard.
3. The plan is becoming issues on the Operations board under the objective improve-agent-plugins: a parent card with its children, plus four cards carried over from the 4 October enhancement plan (the status band's second version, a per-turn step reminder, budget at admission, and cost by step and role). That plan's must-fix Jev call, points score, separate calibration card and plan-review checklist are replaced by this plan; backstop gates stay deferred.

### Stop doing

- **Trying to find everything.** The review looks for defined things; clean results pass.
- **Agreement re-runs as the main yardstick.** Four reviewers can agree and be wrong; the corpus is the yardstick.
- **Voting across runs to decide merge.** A vote drops whatever only one or two runs find. Bugbot launched with an 8-pass vote and moved to an agentic finder with a validator.
- **Expecting a fixed output format alone to make reviews agree.** The record is required (change 1), but agreement comes from every reviewer getting the same where-to-look list (change 5).
- **Asking Jev to grade a change or to review it whole.** Its job is narrow questions over small pieces.

### The most likely way this plan fails

The corpus doesn't look like real changes. Seeded defects are easier to spot than real ones, and public bug sets are likely in the models' training data, so the measured numbers look better than real reviews will be. The guards: pass marks come only from the held-out half, which holds our real defect history and planted defects and never public sets; that half stays out of all tuning; and every defect found later by `/qa` or after merge is added.

Or the corpus slips, report-only becomes permanent, and report-only results get skimmed at merge. The calibration file shows progress lens by lens, and the merge screen shows every lens's report.
