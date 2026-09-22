# Import house-style as an authored, Claude-only package

Date: 2026-09-22
Author: house-style import (unit U3)
Related entries:

- [Custody move plan](../../plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md)

## Context

`house-style` is one output style plus two reference documents, and no code.
Upstream (`infiquetra-claude-plugins` at `acc99fe7`, version 0.1.0) shipped the
style at the plugin root under `output-styles/` and omitted the `outputStyles`
manifest key, on the grounds that Claude discovers that directory by itself.
This catalog forbids that directory at a package root. The import had to keep
the style loadable after moving it.

## Narrative

**Evidence.** The Claude Code plugins reference, read on 2026-09-22 at
<https://code.claude.com/docs/en/plugins-reference>, gives the default location
as `output-styles/` and the manifest key as `outputStyles`. The component-path
table says `outputStyles` replaces the default `output-styles/` scan. The same
page's directory sketch shows `output-styles/` at the plugin root. Upstream's
README and `tests/test_house_style_contract.py` both assert the key is absent,
which is correct only while the style occupies that default directory.

`scripts/import_vendor_package.py` already encodes the same fact: it moves
`output-styles/` to `com.infiquetra.claude/output-styles/` and writes
`outputStyles` into the generated root Claude manifest. The dry run classified
the style and the upstream manifest as the adapter, the two reference documents
plus README and CHANGELOG as portable core, and generated the two root
manifests. Nothing was dropped and nothing imported `fleet_commons_shim`.

**Mechanism.** After the move, Claude's default scan looks at
`plugins/house-style/output-styles/`, which this package must not have, and
finds nothing. The root manifest's `outputStyles` value
`./com.infiquetra.claude/output-styles/` is what makes the style load, because
that key replaces the default rather than supplementing it. The relocated
adapter manifest does not repeat the key. Claude reads
`.claude-plugin/plugin.json` at the installed package root, and a second
declaration would be a path resolved from the extension directory.

**Design calls.**

1. The reference documents stayed at `references/`. They are text other
   packages copy, including the subagent preamble, and the importer classifies
   `references/` as portable core. The portable runtime is empty: no scripts,
   no skills, no executable. The README says so. A skill was not authored. The
   recipe asks for one only where a package had commands and no skill, and the
   package notes say this package has no skills.
2. The contract test was rewritten, not dropped. The frontmatter, placard,
   tell, keyword cap, and coherence assertions still guard the style bytes.
   The two assertions whose premise was the upstream layout now require the
   adapter path and the `outputStyles` declaration. No test was dropped.
3. `tools/output_style_scorer.py` was left upstream. The repo-wide triage marks
   it as a maintainer transcript tool with an uncertain home, not as a test
   this package must carry, and importing it would put code into a package
   whose runtime core is empty. The style's own sentence naming that tool was
   left as upstream wrote it.
4. The version is 0.1.1 on the portable manifest, the root Claude manifest, the
   adapter manifest, and the generated marketplace entry. The adapter manifest
   otherwise keeps the relocated upstream bytes, including its `repository`
   URL. The marketplace reads `repository` from the root manifest, which names
   this repository.
5. The port descriptor is authored (schema version 4, no `source`, no
   `custody`). Every safety field is empty and named in `declared_none`,
   because an assessment that invoked an entrypoint this package does not have
   would fail the package for a descriptor typo.

**Generalizable rule.** When a Claude component key replaces its default
directory, moving that directory under `com.infiquetra.claude/` is incomplete
until the root Claude manifest sets the key. Omitting the key, which is right
for a style that still sits at the default location, means the style does not
load.

## Outcome

`plugins/house-style/` is authored here at 0.1.1. The style loads through
`outputStyles`. The reference documents stay at the package root. No Fleet
Core bundle, no skill, no provenance manifest.

## References

- Upstream pin `acc99fe71e25ad8a898eace7033051a7f1c3079e`
- <https://code.claude.com/docs/en/plugins-reference>
- <https://code.claude.com/docs/en/output-styles>
- [`plugins/house-style/README.md`](../../../plugins/house-style/README.md)
- [`plugins/house-style/tests/test_house_style_contract.py`](../../../plugins/house-style/tests/test_house_style_contract.py)
