// Saga's roles as Claude Code agent types that carry a real model and effort (issue #106).
//
// The Agent tool takes a model per call but no effort, so a plain subagent can
// only be asked to try harder in its prompt (the effort rider, a labeled proxy;
// `plugins/fleet-core/references/staffing.md`). An agent type registered here
// carries both. For each role of this checkout's active saga run the mod
// registers `saga:<role>` (`saga:worker`, `saga:planner`, ...) with the role's
// prompt and the model and effort the run is staffed at.
//
// What to register is the script's answer, never the mod's:
// `scripts/role_agent_types.py --json` decides whether a run is active, reads
// each role's tier (the run record's staffing, completed by the staffing
// resolver) and reads each prompt from the roles library file at that moment.
// The mod registers what it printed, when it printed something new.
//
// With no active run the script answers no types and nothing is registered, so
// a session with no saga run sees no new agent type. A type cannot be
// unregistered, so once a run closes the mod hides its types from the model.
//
// A subagent of a registered type is checked on every request it makes: when
// the model or effort actually sent is not the type's resolved tier, the mod
// shows a toast and writes a `tiering-drift[claude-agent-type]` line into the
// transcript (`$.ui.log`, drawn as a notice the model never reads). It never
// rewrites the request: the mod reports, and policy stays in the scripts.

import type { EngineInterface, On, ProcessRunResult } from 'claude-code'
import type { SagaAgentTypesState, SagaRegisteredAgentType, SagaRoleAgentTypes } from '../types/index.d.ts'
import { sagaScriptArgv } from './run-record.ts'

/** The spawn kind `fleet_commons.effort_rider` names this route by; it leads every drift line. */
export const SPAWN_KIND = 'claude-agent-type'

/** How long the script may take before the mod gives up on this refresh. */
const REFRESH_TIMEOUT_MS = 30_000

/** How long a drift toast stays up. */
const DRIFT_TOAST_MS = 8_000

const AGENT_TYPES = { plugin: 'saga', key: 'agentTypes' } as const

/** The argv that prints this checkout's role agent types. */
export function roleAgentTypesArgv(pluginRoot: string, cwd: string): string[] {
  return sagaScriptArgv(pluginRoot, 'role_agent_types.py', ['--cwd', cwd, '--json'])
}

export type RoleAgentTypesRead = { ok: true; answer: SagaRoleAgentTypes } | { ok: false; detail: string }

/** Turn what `role_agent_types.py` did into its answer, or the reason there is none. */
export function parseRoleAgentTypes(ran: Pick<ProcessRunResult, 'exitCode' | 'stdout' | 'stderr'>): RoleAgentTypesRead {
  if (ran.exitCode !== 0) {
    return { ok: false, detail: `role_agent_types exited ${ran.exitCode}: ${ran.stderr.trim()}` }
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(ran.stdout)
  } catch (err) {
    return { ok: false, detail: `role_agent_types printed no JSON: ${String(err)}` }
  }
  const answer = parsed as Partial<SagaRoleAgentTypes> | null
  if (!answer || answer.schema !== 'saga_role_agent_types.v1' || !Array.isArray(answer.types)) {
    return { ok: false, detail: 'role_agent_types printed an answer this mod does not know' }
  }
  if (answer.error) return { ok: false, detail: answer.error }
  return { ok: true, answer: answer as SagaRoleAgentTypes }
}

/**
 * Whether a request's model and effort are a registered type's resolved tier.
 * A request names a resolved model id (`claude-opus-5-5`) and a type an alias
 * (`opus`), so the model matches when the id carries the alias. A request that
 * sends no effort does not match.
 */
export function matchesTier(resolved: SagaRegisteredAgentType, model: string, effort: string | number | undefined): boolean {
  return model.toLowerCase().includes(resolved.model.toLowerCase()) && effort === resolved.effort
}

/** The drift line: the same `tiering-drift[<spawn kind>]` name `effort_rider.reconcile_effort` uses. */
export function driftLine(
  type: string,
  resolved: SagaRegisteredAgentType,
  model: string,
  effort: string | number | undefined,
  agentId: string,
): string {
  const sent = `${model}/${effort === undefined ? 'no effort sent' : String(effort)}`
  return `tiering-drift[${SPAWN_KIND}]: ${type} resolved ${resolved.model}/${resolved.effort}, request sent ${sent} (agent ${agentId})`
}

/**
 * What this load of the module knows. A reload starts it afresh, and also
 * unloads the plugin's types while the session's state keeps the last answer,
 * so `registered` (not the state) says whether the types are in place.
 */
const loaded = {
  /** The answer this load registered, as `<active>:<fingerprint>`. */
  registered: null as string | null,
  /** Every type this load registered; one the current answer no longer names is hidden. */
  everRegistered: new Set<string>(),
  /** A listed subagent's registered type, looked up once; null for one of no saga type. */
  typeOfAgent: new Map<string, string | null>(),
  /** Agents already reported, so a drifted subagent raises one toast, not one per request. */
  reported: new Set<string>(),
}

/** Register what the script answers for `cwd`, when it answers something this load has not. */
async function refresh($: EngineInterface, cwd: string): Promise<void> {
  let read: RoleAgentTypesRead
  try {
    read = parseRoleAgentTypes(
      await $.process.run(roleAgentTypesArgv($.plugin.root, cwd), { timeoutMs: REFRESH_TIMEOUT_MS }),
    )
  } catch (err) {
    read = { ok: false, detail: `role_agent_types did not run: ${err instanceof Error ? err.message : String(err)}` }
  }
  if (!read.ok) {
    $.ui.log(`saga agent types: none registered; ${read.detail}`)
    return
  }
  const { answer } = read
  const answerKey = `${answer.active}:${answer.fingerprint}`
  if (loaded.registered === answerKey) return

  // A closed run keeps its types' tiers, so a subagent still running is still checked.
  const { value: held } = await $.state.get(AGENT_TYPES)
  const byType: Record<string, SagaRegisteredAgentType> = answer.active ? {} : { ...held?.byType }
  for (const t of answer.active ? answer.types : []) {
    try {
      const { agent } = await $.agent.register({
        name: t.role,
        description: t.description,
        prompt: t.prompt,
        model: t.model,
        effort: t.effort,
      })
      byType[agent] = { role: t.role, model: t.model, effort: t.effort }
      loaded.everRegistered.add(agent)
    } catch (err) {
      $.ui.log(`saga agent types: saga:${t.role} not registered; ${err instanceof Error ? err.message : String(err)}`)
    }
  }
  const state: SagaAgentTypesState = {
    active: answer.active,
    issue: answer.issue,
    fingerprint: answer.fingerprint,
    byType,
  }
  await $.state.set(AGENT_TYPES, state)
  loaded.registered = answerKey
}

export function registerAgentTypes(on: On): void {
  on('session.start', async ($, e, next) => {
    await refresh($, e.cwd)
    return next(e)
  })

  // The run record's staffing changes between turns (admission, an operator's
  // answer); a registered type takes effect from the next turn on, so the end
  // of each main-loop turn is the earliest a change can matter.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (!e.agentId) await refresh($, await $.session.cwd())
    return result
  })

  // A type cannot be unregistered, so one the current answer does not name (the
  // run closed, or the role is no longer staffed on this vendor) is kept from the model.
  on('agent.offer', async ($, e, next) => {
    if (!loaded.everRegistered.has(e.agent)) return next(e)
    const { value: held } = await $.state.get(AGENT_TYPES)
    if (held?.active && held.byType[e.agent]) return next(e)
    return { isOffered: false }
  })

  on('turn.step', async function* ($, e, next) {
    if (e.agentId && !loaded.reported.has(e.agentId)) {
      const { value: held } = await $.state.get(AGENT_TYPES)
      if (held && Object.keys(held.byType).length > 0) {
        let type = loaded.typeOfAgent.get(e.agentId)
        if (type === undefined) {
          const agents = await $.agent.list()
          const found = agents.find((a) => a.id === e.agentId)?.type
          type = found !== undefined && held.byType[found] ? found : null
          // An agent not listed yet is looked up again on its next request.
          if (found !== undefined) loaded.typeOfAgent.set(e.agentId, type)
        }
        const resolved = type ? held.byType[type] : undefined
        if (type && resolved && !matchesTier(resolved, e.model, e.effort)) {
          loaded.reported.add(e.agentId)
          const line = driftLine(type, resolved, e.model, e.effort, e.agentId)
          $.ui.toast(line, { timeoutMs: DRIFT_TOAST_MS })
          // A transcript line drawn as a notice: the model never reads it, and a
          // headless host receives it as `ui_log`.
          $.ui.log(line)
        }
      }
    }
    return yield* next(e)
  })
}
