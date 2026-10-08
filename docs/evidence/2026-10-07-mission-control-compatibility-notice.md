<!-- matrix-status: notice -->

# Mission Control compatibility evidence — versions 2.21.3 and 2.21.4 have no client assessment yet

The package moved from 2.21.2 to 2.21.3 on 2026-10-07 in the release that re-tiers
the fleet's Claude staffing defaults for Haiku 5.5 and the Sonnet 5.5 cache-read
price cut (infiquetra-agent-plugins pull request 209). The last client
assessment, [2026-10-04-mission-control-compatibility-matrix.md, superseded 2026-10-07](2026-10-04-mission-control-compatibility-matrix.md), describes 2.21.2 and is superseded because the version
moved.

Later the same day the package moved to 2.21.4 when the operator moved Haiku's efforts up one
rung (fleet-core 0.33.2). No nine-client run has been performed for 2.21.3 or 2.21.4. This notice is not an
assessment and does not carry any stage result forward. The compatibility
matrix is not a release gate; the next assessment of this package replaces this
notice as the end of the supersession chain.

```json
{"notice": "no client assessment has been run against mission-control 2.21.3 or 2.21.4", "last_assessed": "2026-10-04-mission-control-compatibility-matrix.md"}
```
