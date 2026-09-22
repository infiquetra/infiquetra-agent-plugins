<!-- matrix-status: notice -->

# Mission Control compatibility evidence — where the current run lives

The ten-client assessments dated 2026-08-25 and 2026-08-30 describe the derived
package at version 2.15.2. Custody of mission-control moved into this
repository on 2026-09-22. The package version is now 2.21.1, imported from
infiquetra-claude-plugins at acc99fe7 (upstream 2.21.0) and maintained here.

Those records are superseded. When this notice was written, no ten-client run
had been performed for 2.21.1; one was performed on 2026-09-22 and is recorded
in
[2026-09-22-mission-control-compatibility-matrix.md](2026-09-22-mission-control-compatibility-matrix.md),
which is the current matrix for the package that ships. This notice is still
the end of the supersession chain. It is not an assessment, and it does not
invent stage results.

The version-bound rule does not require a live matrix for an authored package
until a release assessment exists. That assessment now exists and names the
version it actually assessed. This notice keeps its status, because a notice
carries no supersession directives of its own and the records that name it as
their successor still resolve through it.

```json
{"notice": "the mission-control 2.15.2 client results were not renumbered onto 2.21.1", "current_matrix": "2026-09-22-mission-control-compatibility-matrix.md"}
```
