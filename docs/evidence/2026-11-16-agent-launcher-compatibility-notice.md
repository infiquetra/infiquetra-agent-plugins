<!-- matrix-status: notice -->

# Agent Launcher compatibility evidence — version 2.0.0 has no client assessment yet

The package moved from 1.7.3 to 2.0.0 in the 2026-11-16 catalog release
(part of infiquetra-agent-plugins issue 147).
Session control uses herdr core and the Herdr app. The roles library is pinned to lifecycle revision 1d2e33e and retires per-lens staffing.

The last client assessment,
[2026-10-04-agent-launcher-compatibility-matrix.md, historical and superseded](2026-10-04-agent-launcher-compatibility-matrix.md),
describes an earlier package version. The preceding release notice is
[2026-10-14-agent-launcher-compatibility-notice.md, historical](2026-10-14-agent-launcher-compatibility-notice.md).

No fresh client assessment has been run for 2.0.0. This notice is not an assessment
and carries no stage result forward. Repository tests and native manifest validation
are release checks, not a replacement for the multi-client assessment. The next
assessment of this package replaces this notice. The compatibility matrix is not
a release gate. Release changes are listed in [the changelog](../../plugins/agent-launcher/CHANGELOG.md).

```json
{"notice": "no client assessment has been run against agent-launcher 2.0.0", "last_assessed": "2026-10-04-agent-launcher-compatibility-matrix.md"}
```
