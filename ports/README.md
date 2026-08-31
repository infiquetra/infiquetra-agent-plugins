# Port descriptors

One JSON file per portable package, named for the package. It is the only place
package identity, custody, and assessment settings live, and three tools read it:

| Tool | What it takes from the descriptor |
|---|---|
| [`scripts/sync_vendor_source.py`](../scripts/sync_vendor_source.py) | The upstream repository and path, the custody table, and the provenance notes it writes into `PROVENANCE.json` |
| [`scripts/check_compatibility_matrix.py`](../scripts/check_compatibility_matrix.py) | The package root a matrix fingerprint must identify, and the scripts and mutating operations its safety rule is scoped by |
| [`scripts/assess_clients.py`](../scripts/assess_clients.py) | The entrypoints and skill units the assessment invokes, and the credential variable prefixes it strips |

`scripts/port_config.py` is the single authority for the format. There is no
second schema file: a rule written twice is a rule that can disagree with
itself, and [`tests/test_port_config.py`](../tests/test_port_config.py) derives
its expectations from that module rather than restating them.

## Why these live outside `plugins/`

A compatibility matrix binds itself to a fingerprint of the package tree. A
descriptor stored inside the tree it describes would move that fingerprint every
time the tooling's own configuration changed, and invalidate assessment evidence
that is still perfectly true.

## Fields

```jsonc
{
  "schema_version": "3",              // refused rather than read with assumed defaults
  "package": "unifi",                 // must equal the file name
  "package_root": "plugins/unifi",    // must be plugins/<package>
  "package_manifest": "plugin.json",  // optional; this is the default

  "source": {
    "repository": "https://github.com/...",   // required
    "package_path": "plugins/unifi",          // required; path inside the upstream repo
    "manifest_path": ".claude-plugin/plugin.json",  // optional; input to relocate-claude-manifest
    "client_extension_dir": "com.infiquetra.claude" // required by client_byte_copies and by manifest_path
  },

  // Every upstream path falls in exactly one class. A path in two is refused,
  // and a path in none stops a synchronization rather than being dropped.
  "custody": {
    "byte_copies": [],                 // identical to source; digest must match exactly
    "entrypoint_transforms": [         // rewritten by a versioned rule; keeps its path
      { "path": "scripts/example.py", "rule": "resolve-bundled-fleet-module" }
    ],
    "client_byte_copies": [],          // byte copies under the client extension directory
    "superseded_by_target_owned": [],  // upstream path this package replaces; never copied
    "dropped_from_source": []          // not carried; needs provenance.dropped_reason
  },

  // Closed against unknown keys, like every object here. Each safety field
  // must be stated: absent, every one of them fails open.
  "assessment": {
    "credential_prefixes": [],   // variables stripped from every assessment subprocess
    "package_scripts": [],       // scopes the mutating-operation rule to this package
    "mutating_operations": [],   // the package's own classification of what writes
    "entrypoints": [],           // executables the assessment invokes (see below)
    "skill_units": [],           // unit directories skill-scoped clients install
    "declared_none": []          // safety fields this package deliberately leaves empty
  },

  "provenance": {
    "notes": [],           // written verbatim into PROVENANCE.json
    "dropped_reason": ""   // recorded against every dropped_from_source path
  }
}
```

## Why every object is closed, and every safety field is stated

An unknown key in a descriptor is not a syntax error. It is a setting that
silently did not take effect, and the cost is asymmetric: `credential_prefix`
instead of `credential_prefixes` reads as "strip nothing", and the run that finds
out is the one that hands the operator's real credentials to ten clients. So
every object refuses keys it does not define.

The four fields under `assessment` marked as safety declarations fail *open* when
absent, each in its own way:

| Field | What an empty value means |
|---|---|
| `credential_prefixes` | no variable is stripped from any assessment subprocess |
| `package_scripts` | the mutating-operation rule matches no command, so every command passes |
| `mutating_operations` | the same rule has no verbs to match |
| `entrypoints` | the assessment invokes nothing, and a package can be called compatible without any executable having run |

Every path in `entrypoints` must name a file the package actually carries.
`scripts/check_repo.py` and the harness both refuse one that does not: left to
run, the interpreter exits non-zero on a missing file and the row is graded as a
package failure — charging a descriptor typo to the package.

Each must be stated. A package for which one is genuinely empty names it in
`declared_none` — a decision a reader can see, and one a typo cannot produce.

## Transform-rule selection is explicit (schema version 3)

Schema version 2 carried `custody.entrypoint_transforms` as bare path strings:
the synchronization tool had one rewriting rule and applied it to every one of
them. With more than one rule in play that stops being a selection — it is a
default. Version 3 makes every entry an object stating both fields:

```jsonc
{ "path": "scripts/example.py", "rule": "resolve-bundled-fleet-module" }
```

`path` keeps its upstream-relative path through synchronization; `rule` names
the versioned rule the synchronization tool applies to it. Both fields are
required and the entry object is closed like every other object here: a bare
path string is the version-2 shape, an entry with no rule name would be read
with an assumed default, and both are refused. The names a descriptor may use
are the synchronization tool's `TRANSFORM_RULES` registry —
`relocate-claude-manifest` is never selected this way (the client manifest
always relocates under it); the selectable rules are the
`resolve-bundled-fleet-module` family (`resolve-bundled-fleet-module`,
`resolve-bundled-fleet-module-split`, `resolve-bundled-fleet-module-guarded`),
`normalize-skill-frontmatter`, and `resolve-package-root-marker` — whose
per-file site-count table is keyed by package name, so a second package that
selects it extends the table with its own slice rather than editing
mission-control's. A name the tool does not implement is
refused at synchronization, never matched by a fallback. Version 2 is not
accepted: both descriptors migrated in the same commit that bumped the
version. Selection lives in the descriptor rather than a script-internal
registry because AGENTS.md places porting-tool package configuration in the
descriptor, never as a constant inside a script.

## Entrypoints are declared, not inferred from custody

`assessment.entrypoints` lists the package's executables, package-relative, and
is deliberately independent of the `custody` table. What makes a file executable
is that the package says it is; how its bytes were obtained is a separate
question. Reading entrypoints out of `custody.entrypoint_transforms` meant a
package whose executable is an upstream byte copy or target-owned source had no
assessable entrypoint at all — the harness only ever worked for one custody
layout.

## Adding a package

```bash
$EDITOR ports/<package>.json
python3 scripts/check_repo.py                 # validates every descriptor
python3 scripts/sync_vendor_source.py --package <package> --source PATH --commit SHA --check
python3 scripts/assess_clients.py --package <package>          # prints the plan, runs nothing
```
