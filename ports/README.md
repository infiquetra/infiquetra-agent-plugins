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
  "schema_version": "1",              // refused rather than read with assumed defaults
  "package": "unifi",                 // must equal the file name
  "package_root": "plugins/unifi",    // must be plugins/<package>
  "package_manifest": "plugin.json",  // optional; this is the default

  "source": {
    "repository": "https://github.com/...",   // required
    "package_path": "plugins/unifi",          // required; path inside the upstream repo
    "manifest_path": ".claude-plugin/plugin.json",  // optional; input to relocate-claude-manifest
    "client_extension_dir": "com.infiquetra.claude" // optional; required by client_byte_copies
  },

  // Every upstream path falls in exactly one class. A path in two is refused,
  // and a path in none stops a synchronization rather than being dropped.
  "custody": {
    "byte_copies": [],                 // identical to source; digest must match exactly
    "entrypoint_transforms": [],       // rewritten by a versioned rule; keeps its path
    "client_byte_copies": [],          // byte copies under the client extension directory
    "superseded_by_target_owned": [],  // upstream path this package replaces; never copied
    "dropped_from_source": []          // not carried; needs provenance.dropped_reason
  },

  "assessment": {
    "package_scripts": [],       // scopes the mutating-operation rule to this package
    "mutating_operations": [],   // the package's own classification of what writes
    "credential_prefixes": [],   // variables stripped from every assessment subprocess
    "skill_units": []            // unit directories skill-scoped clients install
  },

  "provenance": {
    "notes": [],           // written verbatim into PROVENANCE.json
    "dropped_reason": ""   // recorded against every dropped_from_source path
  }
}
```

`assessment.package_scripts` and `assessment.mutating_operations` are load
bearing rather than descriptive. Together they are what scopes the safety rule
that refuses a recorded — or about-to-run — command naming a write. An empty
`package_scripts` scopes that rule to nothing, so every command passes;
`tests/test_port_config.py` asserts the shipped list names files the package
actually carries.

## Adding a package

```bash
$EDITOR ports/<package>.json
python3 scripts/check_repo.py                 # validates every descriptor
python3 scripts/sync_vendor_source.py --package <package> --source PATH --commit SHA --check
python3 scripts/assess_clients.py --package <package>          # prints the plan, runs nothing
```
