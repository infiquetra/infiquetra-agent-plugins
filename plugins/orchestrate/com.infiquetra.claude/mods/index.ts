// Orchestrate's one hooks module, named from `../hooks/hooks.json` under `modules`.
//
// The engine loads exactly one module per plugin, so every orchestrate mod
// registers from here: each mod lives in its own file beside this one and
// exports a function this `register` calls. Orchestrate's mods read state
// through orchestrate.py's own read-only commands (`orchestrate-script.ts`),
// never through saga's files: each plugin's scripts own that plugin's state, and
// a plugin's module can import only files inside its own folder. No mod
// launches, lands or closes anything; those stay with the script.

//
// The engine allows one `session.start` hook per plugin without a matcher, and
// refuses `$` passed into a function imported from another file, so the one
// start hook lives here and registers what each mod declares as plain data.

import type { Register } from 'claude-code'
import { FLEET_COMMAND_SPEC, registerFleetView } from './fleet-view.tsx'
import { APPROVAL_TOOL_SPEC, registerLaunchApproval } from './launch-approval.tsx'

export const register: Register = (on) => {
  on('session.start', async ($, e, next) => {
    await $.command.register(FLEET_COMMAND_SPEC)
    await $.tool.register(APPROVAL_TOOL_SPEC)
    return next(e)
  })
  registerFleetView(on)
  registerLaunchApproval(on)
}
