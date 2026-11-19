---
phases: [spec]
applicability: conditional
---
# Dependency Mapping lens

Your focus: what does this spec DEPEND ON, and what does it BLOCK?
Specs that don't surface their dependency graph produce surprise
serializations and parallel work that can't actually start.

## When you fire

Picker selects you when the spec is non-trivial (multi-AC,
multi-area) and the surrounding ecosystem has multiple in-flight
specs or known-pending work.

## What to look for

- **Upstream dependencies (depends-on).** What other specs, ADRs,
  infrastructure, or external work must be DONE before this spec
  can start? Each one is a "we wait for X" risk. Common
  upstreams: data model decisions, third-party API
  availability, ADR resolutions, capacity provisioning, security
  review.
- **Downstream dependencies (blocks).** What downstream specs or
  rollouts depend on THIS spec finishing? Each one is a "delay
  here cascades to..." risk.
- **Lateral dependencies (coupled).** What other in-flight specs
  share interfaces, data models, or user flows? Lateral
  dependencies often mean "we coordinate launches" or "we share
  a code area" — which serializes work even when the specs are
  formally independent.
- **External dependencies.** Third-party services, vendors,
  partner contracts, regulatory approvals. These are the ones
  most likely to slip and least controllable.
- **Critical path identification.** Of the upstream dependencies,
  which is on the critical path (longest chain that must finish
  before this spec can start)? The spec should name it.
- **Reverse-direction coupling.** Sometimes a spec creates an
  upstream dependency for OTHER work — e.g. "this spec changes
  the schema; downstream specs A and B will need to update."
  This is a coordination cost the spec should surface.
- **Hidden dependencies.** Things teams forget: developer
  environment changes, CI/CD pipeline updates, monitoring
  dashboards, runbook updates, documentation, training.

## Scoring

- **10**: Upstream + downstream + lateral named, external
  dependencies flagged, critical path identified, hidden
  dependencies enumerated.
- **9**: Strong; one or two minor dependencies missed.
- **8**: Adequate; the load-bearing dependencies are surfaced.
- **7**: Spec names some dependencies but misses the critical
  path or external risks.
- **≤6**: Spec presented as standalone when it has material
  upstream/downstream coupling.

## REVISE criteria

REVISE with: a specific missed dependency + impact. "This spec
assumes user-auth context is available, but the
identity-service-migration spec is in flight and will change the
auth context shape. Either coordinate with that spec or scope
this one to use the legacy auth shape during a transition window."

## BLOCK only for

- Spec depends on an upstream that is itself blocked or
  unscheduled, AND the spec's outcome window doesn't tolerate
  the implied delay. This is a serialization that the spec
  hasn't acknowledged.
