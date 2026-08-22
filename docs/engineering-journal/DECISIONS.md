# Decisions - infiquetra-agent-plugins

## 2026-08-22

### The ported test's pytest guard raises SkipTest instead of binding pytest to None

**Author.** Jeff Cox and Claude

**Decision.** The `guard-pytest-import` deterministic transform over
`tests/test_retry_backoff.py` moves to version 2. Where version 1 bound the name
`pytest` to `None` when the dependency was absent, version 2 raises
`unittest.SkipTest`. Everything else about the rule is unchanged: the upstream
module docstring is still replaced with one recording the port, and every line
from `class RateError(Exception):` to end of file is still copied byte for byte.

**Rejected alternatives.** Keeping version 1, because Fleet Core 0.25.1 brought
two tests carrying `@pytest.mark.parametrize` and a decorator is evaluated when
the module is imported: against `None` it raises `AttributeError`, so the
dependency-free baseline job would fail on a module it never intended to run.
Substituting a hand-written stub object exposing `mark.parametrize` and
`raises`, because a fake that silently absorbs whatever the upstream suite
reaches for is a lie in a file whose entire purpose is to be a faithful copy,
and it would need extending every time upstream uses one more pytest feature.
Dropping the ported test from the hermetic job by renaming it out of the
`test*.py` pattern, because the discovery pattern is not this package's to
redefine and a test nothing collects is a test nobody notices breaking.

**Rationale.** `unittest` catches `SkipTest` raised during module import and
records the module as one skipped test, so the baseline job stays green, exits
0, and says out loud why it collected nothing there — verified directly rather
than assumed. The plugin job, where pytest is installed, runs all eighteen test
functions unchanged, which pytest expands to twenty-five cases. The guard also
stops being a maintenance liability: it no longer has to be revisited each time
upstream reaches for another pytest feature at module scope.

**Revisit when.** The hermetic baseline job gains pytest, which would make the
guard dead code, or upstream splits its suite so the ported half no longer needs
pytest at all.

**Refs.** [`plugins/fleet-core/PROVENANCE.json`](../../plugins/fleet-core/PROVENANCE.json),
[the 0.25.1 changelog entry](../../plugins/fleet-core/CHANGELOG.md)

### A re-synchronization does not renumber the evidence it invalidates

**Author.** Jeff Cox and Claude

**Decision.** The Fleet Core 0.25.1 re-synchronization left
[`docs/evidence/2026-08-22-unifi-compatibility-matrix.md`](../evidence/2026-08-22-unifi-compatibility-matrix.md)
and
[`docs/evidence/2026-08-22-unifi-post-activation-readback.md`](../evidence/2026-08-22-unifi-post-activation-readback.md)
untouched, and shipped with the eight binding tests over them failing. The
recorded fingerprints still name the tree those assessments actually ran
against.

**Rejected alternatives.** Writing the new tree digest into both documents,
because the matrix states the rule in its own text — "Refreshing the numbers
without re-running the assessment is precisely the failure this binding exists
to catch" — and doing it by hand rather than by a flag does not make it a
different act. It would turn forty observed stage results and ten client
readbacks into claims about bytes nobody ran. Marking the current matrix
superseded, because the supersession contract requires a named successor that is
itself current, and no successor exists until someone re-runs the ten clients.
Reverting the bundle regeneration to keep the digest still, because a consumer
carrying a stale copy of a repaired rate-limit primitive is the actual defect
this whole re-synchronization exists to remove.

**Rationale.** The binding is not misfiring. Bundling puts a stamped Fleet Core
module inside the UniFi package, so a Fleet Core release necessarily changes the
UniFi tree digest, and the document correctly reports that it no longer
describes what ships. Red is the accurate state, and a red check that names real
work still owed is worth more than a green one bought by editing the number
under comparison.

**Revisit when.** The operator authorizes the ten-client re-run and the
post-activation readback; the new matrix is published as current and the present
one is marked superseded by it, which is the only path that clears these eight
tests honestly.

**Refs.** [Queued evidence re-run](QUEUED.md#re-run-the-ten-client-matrix-and-the-readback-against-the-resynced-package),
[the learning](LEARNINGS.md#regenerating-a-build-artifact-retires-the-observational-evidence-bound-to-it)

### The portable UniFi README is target-owned, rewritten site-neutral

**Author.** Jeff Cox

**Decision.** `plugins/unifi/README.md` is target-owned portable source. It
describes this package: the Agent Plugins 1.0 layout, the
`com.infiquetra.claude/` client extension directory, the Fleet Core bundle,
site-profile resolution, and commands that run in this repository. It is not
an upstream byte copy of the Claude plugin README, and it is not produced by a
deterministic transform of that file.

**Rejected alternatives.** Keeping the file as `upstream-byte-copy`, because
that is the classification that shipped Cursor F-07: a consumer opening the
portable package's own documentation was told it was a Claude Code plugin and
was given pytest paths this repository does not contain. Authoring a
`portable-readme` transform in `scripts/sync_vendor_source.py`, because that
script is owned by the concurrent C8 repair (path-safety) and a transform
would still be defined over a Claude-specific source document whose subject is
the wrong package. Repairing the upstream README so a byte copy becomes
portable, because this run must not edit another repository.

**Rationale.** The pilot plan already assigned the README "portable core,
rewritten site-neutral". Claude-only installation belongs in the adapter
directory. A later `synchronize()` that still lists `README.md` in
`PORTABLE_BYTE_COPIES` would restore the Claude lede; `tests/test_unifi_readme.py`
fails closed on that restoration (lede identity, absent test modules, and the
provenance classification). Dropping the path from the sync table is queued
rather than taken here, because that tuple lives in a file this unit does not
own.

**Revisit when.** The next UniFi synchronization is authorized, or the C8 unit
(or a follow-up) removes `README.md` from `PORTABLE_BYTE_COPIES` so a
deliberate resync preserves the portable README instead of fighting the test.

**Refs.** [Queued sync-table residual](QUEUED.md#drop-readme-from-the-unifi-byte-copy-table-so-a-resync-keeps-the-portable-docs),
[byte-copy README learning](LEARNINGS.md#a-byte-copied-readme-describes-the-source-package-not-the-derived-one),
[pilot plan custody table](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)

---

### Pause the pilot at the compatibility matrix and take no client-specific remediation

**Author.** Jeff Cox and Claude

**Decision.** The portability pilot stops at the completed ten-client compatibility
matrix. Two clients did not consume the portable package: OpenAI Codex is recorded as
works through an adapter, and Cursor Agent is recorded as failed. Neither is repaired
here. Whether a given client warrants a repair, an adapter, a different distribution path,
or an explicitly unsupported status is one operator decision per client, and each is taken
separately from this work. The package-side defect that leaves the assembled package with
no working entrypoint is recorded in the same way and is likewise not repaired here.

**Rejected alternatives.** Building the Codex marketplace manifest immediately, because
the matrix would then be reporting on a package that had been changed to make it pass, and
the assessment exists to say what was true of the package as assembled. Dropping the two
non-consuming clients from the matrix, because coverage was the deliverable and a client
recorded as unsupported or failed with its reason is a result, not a gap. Repairing the
missing bundle inside this unit, because a defect found by an assessment is scope the
assessment discovered, not scope it was granted.

**Rationale.** Implementation scope that expands itself the moment it finds a problem
stops being a scope. The matrix was built to inform a decision, and taking the decision
inside the same unit that produced the evidence removes the operator from a choice that is
theirs. Coverage was mandatory and passing was not, which is only true if failures end in
a pause rather than in a repair.

**Revisit when.** The operator has taken the per-client decisions, or the package
entrypoint defect is separately authorized for repair.

**Refs.** [Compatibility matrix](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[per-client queued decision](QUEUED.md#decide-per-client-what-follows-the-compatibility-matrix),
[queued entrypoint repair](QUEUED.md#emit-the-declared-fleet-core-bundle-so-the-package-has-a-working-entrypoint)

---

### Leave the portable profile resolution order at two rungs and close the Infiquetra gap in deployment

**Author.** Jeff Cox and Claude

**Decision.** The portable site-profile contract keeps resolving exactly two rungs, the
`UNIFI_SITE_PROFILE` environment variable and then the path remembered in `config.json`,
followed by no profile at all. The documented deployed runtime default,
`${XDG_CONFIG_HOME:-~/.config}/infiquetra/unifi/site-profile.json`, is not added as a
third rung by this work. The Infiquetra instance closes its own gap in the private
`home-lab` repository, where the Ansible deployment now also writes `config.json` so the
remembered rung resolves the file it just deployed. The general fix stays queued.

**Rejected alternatives.** Adding the default path as a final rung inside this pilot,
because it changes what an already-deployed host resolves and therefore touches the
portable contract, both consumers of it, and the Claude adapter's loader with their tests
— a contract change that deserves its own unit rather than a fix smuggled into a
documentation unit. Making the environment variable mandatory, which would delete the
optional-profile promise the contract exists to keep. Documenting the trap and leaving it
at that, because a documented trap is still a trap.

**Rationale.** The portable contract and the Infiquetra custody instance are separable on
purpose. This repository's normative documentation never presents the private `home-lab`
plus Ansible arrangement as required; it is one operator's deployment of an optional
profile. That separation is exactly what allows the operator's own gap to be closed in
their deployment today while the portable question stays open for a decision that affects
every other operator.

**Revisit when.** A second operator deploys a site profile on a host this repository does
not control, or the queued contract change is authorized.

**Refs.** [Queued contract change](QUEUED.md#the-documented-default-site-profile-runtime-path-is-never-read),
[seam learning](LEARNINGS.md#every-unit-passed-its-own-tests-and-the-defect-lived-in-the-seam-between-two-correct-units),
[site profile reference](../../plugins/unifi/references/site-profile.md)

---

### Keep a generated file's stamp outside the bytes it hashes

**Author.** Jeff Cox and Claude

**Decision.** A generated Fleet Core bundle carries two independent digests. The
source-payload digest covers the upstream module and detects a stale bundle whose source
has moved. The generated-output digest covers the generated file with its own stamp block
excluded, and detects a hand-edited output. `scripts/check_repo.py` reports the two as
different, deterministic failures.

**Rejected alternatives.** One digest over the whole generated file, which is
self-referential and cannot be computed, since the digest would have to appear inside the
bytes it covers. One digest over the source only, which would leave a hand-edited
generated file undetectable — the exact degradation that turns a generated artifact into
an unmaintained copy-paste fork.

**Rationale.** Stale source and tampered output are different problems with different
repairs. Collapsing them into one mismatch tells a maintainer that something is wrong
without telling them which thing, and a signal that needs investigation before it can be
acted on is a weak signal.

**Revisit when.** A second consumer bundles a Fleet Core module and the two-domain scheme
proves awkward, or a generated artifact appears that has no stable stamp location.

**Refs.** [Bundle declaration schema](../../schemas/fleet-bundle.schema.json),
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)

---

### Keep repository validation standard-library-only and give the ported plugin tests their own job

**Author.** Jeff Cox and Claude

**Decision.** Continuous integration runs two jobs. The repository validation job installs
nothing and runs `python3 scripts/check_repo.py`, the unittest suite, and `git diff
--check`, so the repository's own baseline uses the standard library alone. A second job
installs Python 3.10 with `requests`, `urllib3`, and `pytest`, and runs the ported plugin
tests. Neither job ever contacts a UniFi controller, and the compatibility matrix is
produced by an operator-run assessment rather than by continuous integration.

**Rejected alternatives.** Rewriting the existing pytest tests into unittest so a single
job could run everything, which would discard proven upstream coverage for no behavioral
gain. Installing dependencies in the one existing job, which would make a package index
outage able to break validation of documentation-only changes.

**Rationale.** The repository's fast hermetic baseline is worth protecting as its own
guarantee: it answers whether this repository is internally consistent, using nothing it
has to download. The ported plugin tests answer a different question and legitimately need
third-party packages, so they get a job whose failures mean what they say.

**Revisit when.** The ported packages acquire a dependency the second job cannot install,
or the repository grows a project file that makes a single job hermetic again.

**Refs.** [Pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[deferred Fleet Core inventory](../../plugins/fleet-core/DEFERRED.md)

---

### Reclassify both UniFi clients as a deterministic transform rather than a byte copy

**Author.** Jeff Cox and Claude

**Decision.** The two client scripts,
`skills/unifi-network/scripts/unifi_network_client.py` and
`skills/unifi-protect/scripts/unifi_protect_client.py`, move from **upstream byte copy**
to **deterministic transform** under requirement R4's three-way path classification. The
rule is `resolve-bundled-fleet-module`, version 1: it matches the single upstream block
that puts the client's own directory on `sys.path`, imports `fleet_commons_shim`, and
calls `fleet_commons_shim.load(NAME)`, and re-emits it as an insertion of the `_bundled/`
directory beside the client followed by a direct `import NAME`. The rule reads the module
name and the binding out of the source rather than assuming them, changes no other byte,
and raises rather than proceeding when the block is absent or appears more than once.
`plugins/unifi/fleet-bundle.json` declares a destination beside each client, which is
where the pilot plan's assembled-package tree already put the generated bundle.

**Rationale.** The portable package drops both `fleet_commons_shim.py` copies, because
their resolution ladder is Claude-specific runtime discovery the portable package must
not retain. A byte copy of a client that imports a module the package does not carry
aborts at module scope, so the package had no working entrypoint on any client. The
byte-copy rule is not a rule about bytes for their own sake: it exists so a downstream
edit cannot become an unrecorded second source. A versioned rule over the pinned upstream
bytes, with the source digest, the output digest, and the rule text in the provenance
manifest, satisfies that purpose exactly -- the output is reproducible from the source
alone, and re-synchronization re-applies the rule rather than silently restoring the
broken import.

**Rejected alternatives.**

- *Repair it upstream first, as the pilot does for every other divergence.* Upstream is
  a Claude package where `fleet_commons_shim` is present and correct. There is no
  upstream defect to repair, so this would mean degrading the Claude package to suit the
  portable one.
- *Copy `fleet_commons_shim.py` into the portable package.* Prohibited: the operator's
  Fleet Core amendment forbids retaining Claude-specific runtime discovery.
- *Require a `FLEET_COMMONS_ROOT` environment variable, or an Agent Plugins dependency
  field.* Both prohibited by the same amendment. The artifact must be complete at install
  time, with no separate Fleet Core installation.
- *Leave the clients as byte copies and document them as not executable.* This is what
  the package already did. A portable package with no runnable entrypoint is not a
  portability result.

**Revisit when.** Upstream stops importing `fleet_commons_shim` at module scope, or moves
to a mechanism the portable package can carry unchanged. The transform then has no input
to match and refuses to synchronize, which is the deliberate signal to revisit rather
than a failure to work around.

### Guard the join between the bundler and the synchronization in the validator, not only in tests

**Author.** Jeff Cox and Claude

**Decision.** `scripts/check_repo.py` gains `check_fleet_bundle_outputs`, which rejects a
module a consumer's `fleet-bundle.json` declares but no generated bundle carries, and any
file under a `_bundled/` directory that no declaration accounts for. The presence half of
`scripts/bundle_fleet_module.py --check` is factored into `presence_errors` so both
commands report the same two conditions from one implementation. Alongside it,
`tests/test_client_entrypoints.py` runs each shipped client's `--help` in a subprocess,
with third-party transport stubbed and every `UNIFI_*` variable removed, and separately
asserts that deleting the generated bundle from a copy of the package breaks every
entrypoint.

**Rationale.** `check_bundled_files` reads bundles that exist, so a bundle that was never
generated is invisible to it. That is how the repository reported success while shipping
two clients importing a module nothing had written. A validator that only inspects
present files cannot catch an absent one; the declaration is the statement of what should
be present, so comparing the two is the missing assertion. The subprocess test is the
independent signal: it fails whether the cause is the declaration, the transform, or the
bundler.

**Rejected alternatives.**

- *Reuse `check_consumer` wholesale inside `check_repo`.* It also re-checks the stamps,
  which `check_bundled_files` already owns, so one tampered bundle would be reported
  twice in different vocabulary.
- *Rely on the entrypoint test alone.* A test proves the shipped tree works today; the
  validator states the invariant, and continuous integration runs it in the hermetic
  standard-library-only job.

**Revisit when.** A consumer needs a generated bundle outside a `_bundled/` directory,
which would make the directory name the wrong discriminator.

### Detect credentials by value with two narrow families, and never by bare entropy

**Author.** Jeff Cox and Claude

**Decision.** `scripts/check_repo.py` now rejects a credential written as a *value*
anywhere under `plugins/`, using exactly two detection families. The first is a list of
literal credential formats — AWS access key ids, GitHub and Slack and Stripe tokens,
Google and Anthropic and OpenAI API keys, JSON web tokens, private key blocks, and
credentials embedded in a URL — matched in every text file of a package including source,
because a real key committed into source is a leak whatever the surrounding code does with
it. The second is a credential-shaped key (`password`, `secret`, `token`, `api_key`,
`bearer`, `client_secret`, and their near neighbours) assigned a value of at least six
characters that clears 2.5 bits of entropy per character and is not a placeholder or a
reference to where the secret actually lives. The second family runs only on data and
documentation files, never on source.

**Rationale.** The reviewers' finding is that every existing guard — the site profile
loader, its schema, and the compatibility matrix redaction check — inspects field *names*,
so a password pasted into an allowed `notes`, `description`, or `ownership` value passes
all of them. Closing that needs value inspection, and value inspection is worth having
only if it is quiet enough to stay switched on. Measured against the live package tree,
this rule produces zero false positives while still reporting the reviewer's own example,
`notes: "controller password=hunter2"`.

**Rejected alternatives.** A third family scanning for bare high-entropy strings, which is
the usual approach and is unusable here: a provenance manifest is nothing but sha256
digests, so it would fire on every package in the catalog and the gate would be turned off
within a day. Running the credential-assignment family on source as well, which was
measured before being rejected — it produced five false positives on the shipped package,
every one of them credential-*handling* code such as `api_key = (api_key or "").strip()`
and `"X-Api-Key": self.api_key`, and none of them a secret. Scanning the whole repository
rather than `plugins/`, which would make `docs/reviews/` a continuous integration failure
surface; those two reviewer reports are immutable evidence with recorded digests, they
quote credential-shaped text on purpose, and a gate no one is allowed to satisfy is a gate
that gets deleted. `plugins/` is also the scope every other package check here already
uses, and it is the tree that actually leaves this repository.

**Accepted limits.** A short, low-entropy secret in a free-text value still passes:
`password: secret` is six characters of 2.25 bits and is below the floor by design. So
does a secret in a package file that is neither text nor a recognised data suffix. This
check is defense in depth against an accident, not a proof of absence, and the operator
guarantee should be worded as such.

**Revisit when.** A credential format in use by the fleet is not on the list, a real
credential reaches a package and this check does not report it, or the false-positive rate
stops being zero on the live tree.

**Scope note.** This closes the repository gate only. The same finding also implicates
`plugins/unifi/scripts/site_profile.py`, whose `validate_profile` accepts a credential in
a `notes` value at runtime, and `scripts/check_compatibility_matrix.py`, whose redaction
check is name-shaped. Neither file is owned by this unit and neither is changed here.

### Bind a current matrix to the tree it assessed, and make supersession the only exemption

**Author.** Jeff Cox

**Decision.** `scripts/check_compatibility_matrix.py` recomputes the fingerprint of
`plugins/unifi/` on every run — package name, version, file count, and a tree digest over
the sorted per-file digests *with their relative paths* — and fails when the record does
not match. A document may exempt itself only by declaring `<!-- matrix-status: superseded -->`
alongside a `superseded-by` naming an existing current matrix and a `superseded-reason`.
A superseded document whose fingerprint still identifies the shipped tree is rejected.
`matrix-status` defaults to `current`, so the binding is fail-closed. The no-argument run
validates every matrix document in `docs/evidence/`, superseded ones included.

**Rejected alternatives.** *Refreshing the numbers only*, because that leaves the identical
trap armed for the next package change and the review named this explicitly. *Adding a
`superseded` field to the record*, because `schemas/compatibility-matrix.schema.json` is
closed and owned by no unit in this run; HTML comment directives carry document-level
metadata without a schema change. *Dropping the JSON fence in the retired document so the
validator skips it*, because retiring a document withdraws its claim about the current
package, not the coverage and redaction rules it was published under. *Overwriting the
original matrix in place*, because the assessment happened and its record is evidence.
*A `--update` flag that rewrites the record from the tree*, because a one-keystroke refresh
would let a stale matrix pass by editing the evidence to match; there is a read-only
`--print-fingerprint` and nothing that writes. A test asserts no such flag is added.

**Rationale.** Hashing the per-file digests alone would leave a pure rename invisible, and
a rename is exactly the drift a binding exists to catch, so relative paths are inside the
hashed text. Checkout noise — `__pycache__`, `.pyc`, `.DS_Store` — is excluded, because a
fingerprint that moved when the test suite ran would be abandoned within a week. The digest
is defined in prose in the matrix itself so a third party can reproduce it from published
bytes.

**Consequence to expect.** Any future change under `plugins/unifi/` fails
`python3 scripts/check_compatibility_matrix.py` and the test suite until the assessment is
re-run and the record refreshed. That is the intended cost: the check is meant to be
noticed, and re-running forty credential-free stages is roughly an hour.

**Revisit when.** `schemas/public-evidence.schema.json` lands and can carry document status
as a schema field, or a second package joins the catalog and the single `PACKAGE_ROOT`
constant needs to become per-record.

**Refs.** [Digest learning](LEARNINGS.md#a-digest-in-an-evidence-record-proves-nothing-until-something-recomputes-it),
`scripts/check_compatibility_matrix.py`, `tests/test_check_compatibility_matrix.py`.

## 2026-08-21

### Choose UniFi plus a portable Fleet Core slice as the first portability pilot

**Author.** Jeff Cox and Claude

**Decision.** Port the Claude `unifi` plugin into a portable Agent Plugins 1.0 package
in this repository, together with a new portable Fleet Core source carrying only the
`retry_backoff` module. The Claude repository is repaired first, released second, and
synchronized from third. Custody does not move.

The load-bearing choices, each recorded in full in the
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md):

- The portable copy is derived and digest-verified, never a second writable source.
- The authoritative source is repaired before the port consumes it; downstream-only
  correction and intentional target divergence are both rejected.
- Extract means relocate, not delete: the embedded lab topology moves into an operator
  site profile, and the repaired release is gated on that replacement path being
  verified so the Claude agent never loses site context.
- Fleet Core becomes a first-class portable source, but only one vertical slice is
  ported; the required module is bundled into consuming artifacts at build time, since
  Agent Plugins 1.0 has no dependency mechanism.
- Compatibility coverage across all ten installed clients is mandatory; passing is not.
  The matrix is a deliverable ending in an operator pause, not a release gate.

**Rejected alternatives.** A hand-port with no drift detection; a subtree or submodule of
the vendor repository; porting the documentation defect verbatim; inlining the retry
primitive and reversing the fleet-wide shared-primitive decision; inventing an Agent
Plugins dependency field; and requiring an environment variable that would resolve to
nothing on a non-Claude host.

**Rationale.** UniFi is small enough to finish and real enough to exercise the actual
architecture boundary. Investigation found three problems the file listing could not
show — an undeclared cross-plugin dependency resolved through Claude-specific discovery,
documentation describing capabilities removed five months earlier, and one operator's
controller address hard-coded as a universal default — and each of them is exactly the
kind of thing a pilot exists to surface before a larger port inherits it.

**Revisit when.** The ten-client compatibility matrix is complete and the operator has
made the per-client decisions that follow it, or evidence shows the build-time bundling
model does not generalize to a second consumer.

**Refs.** [Pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[architecture brief](../cross-vendor-plugin-architecture-brief.md),
[superseded parity decision](ARCHIVE.md#void-parity-baseline-recorded-in-error),
[archived pilot item](ARCHIVE.md#choose-the-first-portability-pilot-and-custody-gate)

---

### Establish a public cross-vendor plugin source repository

**Author.** Jeff Cox and Codex

**Decision.** Use `infiquetra-agent-plugins` as the public repository for the
portable architecture, future shared plugin sources, and explicit vendor
adapters. Existing vendor repositories remain authoritative until a pilot is
proven and custody is moved by a later decision.

**Rejected alternatives.** `infiquetra-plugins` was too broad to distinguish
coding-agent capabilities from other plugin systems. Immediately replacing the
vendor repositories would create an unproved big-bang migration.

**Rationale.** The name identifies the domain, while the staged custody rule
allows shared sources to be proven without breaking current clients.

**Revisit when.** The first portable plugin passes its agreed compatibility
gate, or evidence shows the proposed repository boundary is wrong.

**Refs.** [Architecture brief](../cross-vendor-plugin-architecture-brief.md),
[archived pilot decision](ARCHIVE.md#choose-the-first-portability-pilot-and-custody-gate)

---

Keep newest entries first. When a decision is superseded, preserve the old text
in [ARCHIVE.md](ARCHIVE.md) and link the replacement.
