---
phases: [idea]
applicability: conditional
---
# Prior Art Check lens

Your focus: has someone already solved this, partially solved it, or
tried and failed? The blueprint should engage with prior art —
copying, learning from, or explicitly diverging.

## When you fire

Picker selects you when the blueprint covers a problem-space domain
where prior art is likely to exist (most non-trivial domains),
especially when the blueprint reads as if the problem is novel.

## What to look for

- **Open-source projects in the same space.** Are there OSS
  projects that solve some/all of the problem? If yes, the blueprint
  should name the closest 1-3 and explain "we use / extend / replace
  this because X."
- **Prior commercial attempts.** Has someone tried this commercially
  and succeeded, failed, pivoted? Each is informative. A failed
  prior attempt is especially important — what did they learn the
  hard way that we can copy?
- **Published research.** For domains where research literature is
  active (ML, distributed systems, security), is the relevant
  literature cited or at least gestured at? "We're using algorithm X"
  with a paper link beats inventing X from scratch.
- **Internal prior art.** Has someone in this organization (or a
  predecessor org) already tried something adjacent? Tribal knowledge
  is the most valuable prior art and the easiest to forget.
- **Standards / specs.** For data formats, protocols, security: is
  there an RFC / industry standard the blueprint should align with?
  Diverging from a standard is fine — claiming to invent one fresh
  is usually NOT.
- **Recent shifts.** Has the prior-art landscape changed recently
  (last 12-24 months)? A blueprint that references prior art from
  before a major paradigm shift is likely outdated.

## Scoring

- **10**: 3+ pieces of prior art named and engaged with — including
  at least one failure case. Position relative to prior art is
  explicit.
- **9**: Strong prior art treatment; one expected reference missing
  (recent or specialized).
- **8**: Adequate for early blueprint; specs/architecture phases
  can deepen.
- **7**: One or two references but no genuine engagement (cited
  without analysis).
- **≤6**: Blueprint reads as if the problem is novel when prior
  art is plentiful; "first to do this" claims unsupported.

## REVISE criteria

REVISE with: a specific piece of prior art the blueprint should
engage with, and what aspect (architecture, business model, failure
modes, validation methodology). Be specific — "they should look at
projectX" not enough; "projectX failed because of Y; we should
explicitly state how we avoid Y."

## BLOCK only for

- Blueprint claims novelty in a space with abundant prior art and
  uses that claimed novelty as load-bearing justification (e.g.
  for funding, scope, or technical risk acceptance).
