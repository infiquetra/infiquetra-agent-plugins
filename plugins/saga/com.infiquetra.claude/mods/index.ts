// Saga's one hooks module, named from `../hooks/hooks.json` under `modules`.
//
// The engine loads exactly one module per plugin, so every saga mod registers
// from here: each mod lives in its own file beside this one and exports a
// function this `register` calls. Mods display saga state and collect answers;
// saga's scripts own that state and enforce every policy (see `run-record.ts`).

import type { Register } from 'claude-code'

import { registerPlanViewer } from './plan-viewer.tsx'

export const register: Register = (on) => {
  registerPlanViewer(on)
}
