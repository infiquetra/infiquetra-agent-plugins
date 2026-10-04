// Orchestrate's one hooks module, named from `../hooks/hooks.json` under `modules`.
//
// Empty until the fleet pane lands. Orchestrate's mods read state through
// orchestrate.py's own commands, never through saga's files: each plugin's
// scripts own that plugin's state, and a plugin's module can import only files
// inside its own folder.

import type { Register } from 'claude-code'

export const register: Register = () => {}
