// Saga's one hooks module, named from `../hooks/hooks.json` under `modules`.
//
// The engine loads exactly one module per plugin, so every saga mod registers
// from here: each mod lives in its own file beside this one and exports a
// function this `register` calls. Mods display saga state and collect answers;
// saga's scripts own that state and enforce every policy (see `run-record.ts`).

import type { Register } from 'claude-code'
import { registerAdmissionReview } from './admission-review.tsx'
import { registerAgentTypes } from './agent-types.ts'
import { registerMergeConfirmation } from './merge-confirmation.tsx'
import { registerPlanViewer } from './plan-viewer.tsx'
import { registerReviewPane } from './review-pane.tsx'
import { registerSetupPane } from './setup-pane.tsx'
import { registerUsageCapture } from './usage-capture.ts'
import { registerRunBand } from './run-band.tsx'

export const register: Register = (on) => {
  registerPlanViewer(on)
  registerAdmissionReview(on)
  registerMergeConfirmation(on)
  registerReviewPane(on)
  registerSetupPane(on)
  registerUsageCapture(on)
  registerRunBand(on)
  registerAgentTypes(on)
}
