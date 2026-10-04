import { describe, expect, test } from 'claude-code/testing'
import { driftLine, matchesTier, parseRoleAgentTypes, roleAgentTypesArgv } from './agent-types.ts'

// The engine beneath the plugin, stubbed: `role_agent_types.py` answers what a
// test sets in `answer`, and every registration, toast and transcript line
// the mod makes is captured.

type TypeRow = { role: string; model: string; effort: string }

function typesAnswer(types: TypeRow[], extra: Record<string, unknown> = {}) {
  return {
    schema: 'saga_role_agent_types.v1',
    active: true,
    issue: 123,
    skipped: [{ role: 'merging-worker', reason: 'no role prompt in the roles library' }],
    fingerprint: JSON.stringify(types),
    types: types.map((t) => ({
      ...t,
      role_id: t.role === 'worker' ? 'implementer' : t.role.replace('-', '_'),
      readable_role: t.role,
      prompt_path: `/roles/${t.role}.md`,
      prompt: `# Hosting\n\nprompt for ${t.role}`,
      source: 'run-record',
      description: `Saga run role ${t.role}, staffed at ${t.model}/${t.effort}.`,
    })),
    ...extra,
  }
}

const INACTIVE = { schema: 'saga_role_agent_types.v1', active: false, issue: null, types: [], skipped: [], fingerprint: 'none' }

const FULL: TypeRow[] = [
  { role: 'functional-tester', model: 'opus', effort: 'high' },
  { role: 'plan-reviewer', model: 'opus', effort: 'high' },
  { role: 'planner', model: 'opus', effort: 'high' },
  { role: 'release-worker', model: 'sonnet', effort: 'medium' },
  { role: 'worker', model: 'opus', effort: 'medium' },
]

function engine(on: any, answer: { current: unknown; exitCode?: number; stdout?: string }) {
  const seen = {
    argv: [] as string[][],
    registered: [] as any[],
    toasts: [] as string[],
    logs: [] as string[],
    listCalls: 0,
    steps: [] as any[],
    agents: [] as { id: string; type: string }[],
  }
  on('process.run', async (_$: any, e: any) => {
    seen.argv.push([...e.argv])
    return {
      value: {
        exitCode: answer.exitCode ?? 0,
        stdout: answer.stdout ?? JSON.stringify(answer.current),
        stderr: answer.exitCode ? 'Traceback (most recent call last)' : '',
        isStdoutTruncated: false,
        isStderrTruncated: false,
      },
    }
  })
  on('agent.register', async (_$: any, e: any) => {
    seen.registered.push(e)
    return { value: { agent: `saga:${e.name}` } }
  })
  on('agent.list', async () => {
    seen.listCalls += 1
    return { value: seen.agents.map((a) => ({ ...a, description: 'unit', status: 'running' })) }
  })
  on('ui.toast', async (_$: any, e: any) => {
    seen.toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.log', async (_$: any, e: any) => {
    seen.logs.push(e.text)
    return { value: undefined }
  })
  on('session.cwd', async () => ({ value: '/work/repo' }))
  on('session.start', async (_$: any, e: any) => ({ cwd: e.cwd }))
  on('turn.complete', async () => ({ text: '' }))
  on('turn.step', async function* (_$: any, e: any) {
    seen.steps.push({ model: e.model, effort: e.effort, agentId: e.agentId })
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'end_turn', usage: null }
  })
  return seen
}

async function start($: any) {
  await $.session.start({ cwd: '/work/repo', surface: 'terminal', isInteractive: true })
}

async function step($: any, agentId: string | undefined, model: string, effort?: string) {
  const stream = $.turn.step({ turnId: 't1', index: 0, model, effort, messageCount: 3, agentId })
  for await (const _chunk of stream) {
    // drain
  }
}

async function completeMainTurn($: any) {
  await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
}

describe('registration', () => {
  test('registers the builder (saga:worker) with opus and medium when the resolver says so', async ($: any, on: any) => {
    const seen = engine(on, { current: typesAnswer(FULL) })
    await start($)

    const worker = seen.registered.find((spec) => spec.name === 'worker')
    expect(worker).toEqual({
      name: 'worker',
      description: 'Saga run role worker, staffed at opus/medium.',
      prompt: '# Hosting\n\nprompt for worker',
      model: 'opus',
      effort: 'medium',
    })
    expect(seen.argv.length).toBe(1)
    const [python, script, ...args] = seen.argv[0]
    expect(python).toBe('python3')
    expect(script.endsWith('/scripts/role_agent_types.py')).toBe(true)
    expect(args).toEqual(['--cwd', '/work/repo', '--json'])
  })

  test('registers every reported role at its own tier with the prompt the script returned, unmodified', async ($: any, on: any) => {
    const answer = typesAnswer(FULL)
    const seen = engine(on, { current: answer })
    await start($)

    expect(seen.registered.map((s) => [s.name, s.model, s.effort])).toEqual(FULL.map((t) => [t.role, t.model, t.effort]))
    expect(seen.registered.map((s) => s.prompt)).toEqual(answer.types.map((t) => t.prompt))
    for (const spec of seen.registered) {
      expect(spec.tools).toBeUndefined()
      expect(spec.permissionMode).toBeUndefined()
    }
  })

  test('with no active run, registers nothing', async ($: any, on: any) => {
    const seen = engine(on, { current: INACTIVE })
    await start($)
    await completeMainTurn($)
    expect(seen.registered).toEqual([])
    expect(seen.logs).toEqual([])
  })

  test('a script that fails, prints no JSON, or names an error registers nothing and logs one line', async ($: any, on: any) => {
    const answer: { current: unknown; exitCode?: number; stdout?: string } = { current: null, exitCode: 1 }
    const seen = engine(on, answer)
    await start($)
    answer.exitCode = 0
    answer.stdout = 'not json'
    await completeMainTurn($)
    answer.stdout = undefined
    answer.current = { ...INACTIVE, active: true, issue: 123, error: 'the roles library was not found' }
    await completeMainTurn($)

    expect(seen.registered).toEqual([])
    expect(seen.logs.length).toBe(3)
    expect(seen.logs[0]).toContain('role_agent_types exited 1')
    expect(seen.logs[1]).toContain('printed no JSON')
    expect(seen.logs[2]).toContain('the roles library was not found')
  })

  test('re-registers after the staffing changes', async ($: any, on: any) => {
    const answer = { current: typesAnswer([{ role: 'worker', model: 'sonnet', effort: 'medium' }]) as unknown }
    const seen = engine(on, answer)
    await start($)
    answer.current = typesAnswer([{ role: 'worker', model: 'opus', effort: 'medium' }])
    await completeMainTurn($)

    expect(seen.registered.map((s) => [s.name, s.model, s.effort])).toEqual([
      ['worker', 'sonnet', 'medium'],
      ['worker', 'opus', 'medium'],
    ])
  })

  test('an unchanged answer is not registered again', async ($: any, on: any) => {
    const seen = engine(on, { current: typesAnswer(FULL) })
    await start($)
    await completeMainTurn($)
    expect(seen.registered.length).toBe(FULL.length)
    expect(seen.argv.length).toBe(2)
  })

  test("a subagent's turn does not refresh", async ($: any, on: any) => {
    const seen = engine(on, { current: typesAnswer(FULL) })
    await start($)
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't2', reason: 'answer', agentId: 'a1' })
    expect(seen.argv.length).toBe(1)
  })
})

describe('offering', () => {
  test('offers a registered type while the run is active and hides it once the run closed', async ($: any, on: any) => {
    const answer = { current: typesAnswer(FULL) as unknown }
    engine(on, answer)
    on('agent.offer', async () => ({ isOffered: true }))
    await start($)
    const offer = { agent: 'saga:worker', description: 'd', source: 'plugin', provider: { plugin: 'saga', tier: 'user' } }

    expect(await $.agent.offer(offer)).toEqual({ isOffered: true })
    answer.current = INACTIVE
    await completeMainTurn($)
    expect(await $.agent.offer(offer)).toEqual({ isOffered: false })
    expect(await $.agent.offer({ ...offer, agent: 'Explore', source: 'built-in' })).toEqual({ isOffered: true })
  })

  test('hides a type the current answer no longer names', async ($: any, on: any) => {
    const answer = { current: typesAnswer(FULL) as unknown }
    engine(on, answer)
    on('agent.offer', async () => ({ isOffered: true }))
    await start($)
    answer.current = typesAnswer(FULL.filter((t) => t.role !== 'worker'))
    await completeMainTurn($)
    const offer = { agent: 'saga:worker', description: 'd', source: 'plugin', provider: { plugin: 'saga', tier: 'user' } }
    expect(await $.agent.offer(offer)).toEqual({ isOffered: false })
    expect(await $.agent.offer({ ...offer, agent: 'saga:planner' })).toEqual({ isOffered: true })
  })
})

describe('drift', () => {
  test('a drifted subagent request produces one toast and one tiering-drift line', async ($: any, on: any) => {
    const seen = engine(on, { current: typesAnswer(FULL) })
    seen.agents.push({ id: 'a1', type: 'saga:worker' })
    await start($)
    await step($, 'a1', 'claude-sonnet-5-5', 'high')

    const line = 'tiering-drift[claude-agent-type]: saga:worker resolved opus/medium, request sent claude-sonnet-5-5/high (agent a1)'
    expect(seen.toasts).toEqual([line])
    expect(seen.logs).toEqual([line])
  })

  test('a matching request produces neither', async ($: any, on: any) => {
    const seen = engine(on, { current: typesAnswer(FULL) })
    seen.agents.push({ id: 'a1', type: 'saga:worker' })
    await start($)
    await step($, 'a1', 'claude-opus-5-5', 'medium')

    expect(seen.toasts).toEqual([])
    expect(seen.logs).toEqual([])
  })

  test('a request that sends no effort is a drift', async ($: any, on: any) => {
    const seen = engine(on, { current: typesAnswer(FULL) })
    seen.agents.push({ id: 'a1', type: 'saga:worker' })
    await start($)
    await step($, 'a1', 'claude-opus-5-5', undefined)
    expect(seen.toasts.length).toBe(1)
    expect(seen.toasts[0]).toContain('request sent claude-opus-5-5/no effort sent')
  })

  test('the request is never rewritten, on a drift or a match', async ($: any, on: any) => {
    const seen = engine(on, { current: typesAnswer(FULL) })
    seen.agents.push({ id: 'a1', type: 'saga:worker' }, { id: 'a2', type: 'saga:worker' })
    await start($)
    await step($, 'a1', 'claude-sonnet-5-5', 'high')
    await step($, 'a2', 'claude-opus-5-5', 'medium')
    expect(seen.steps).toEqual([
      { model: 'claude-sonnet-5-5', effort: 'high', agentId: 'a1' },
      { model: 'claude-opus-5-5', effort: 'medium', agentId: 'a2' },
    ])
  })

  test('two drifted requests from one subagent raise one toast', async ($: any, on: any) => {
    const seen = engine(on, { current: typesAnswer(FULL) })
    seen.agents.push({ id: 'a1', type: 'saga:worker' })
    await start($)
    await step($, 'a1', 'claude-sonnet-5-5', 'high')
    await step($, 'a1', 'claude-sonnet-5-5', 'high')
    expect(seen.toasts.length).toBe(1)
    expect(seen.logs.length).toBe(1)
  })

  test('a subagent of another type and a main-loop request are not checked', async ($: any, on: any) => {
    const seen = engine(on, { current: typesAnswer(FULL) })
    seen.agents.push({ id: 'g1', type: 'general-purpose' })
    await start($)
    await step($, undefined, 'claude-haiku-4-5', 'low')
    expect(seen.listCalls).toBe(0)
    await step($, 'g1', 'claude-haiku-4-5', 'low')
    await step($, 'g1', 'claude-haiku-4-5', 'low')
    expect(seen.listCalls).toBe(1)
    expect(seen.toasts).toEqual([])
  })

  test('with nothing registered, a subagent request is not looked up at all', async ($: any, on: any) => {
    const seen = engine(on, { current: INACTIVE })
    seen.agents.push({ id: 'a1', type: 'saga:worker' })
    await start($)
    await step($, 'a1', 'claude-sonnet-5-5', 'high')
    expect(seen.listCalls).toBe(0)
    expect(seen.toasts).toEqual([])
  })
})

describe('the pure parts', () => {
  test('parseRoleAgentTypes refuses an answer of another schema', async () => {
    const read = parseRoleAgentTypes({ exitCode: 0, stdout: JSON.stringify({ schema: 'v9', types: [] }), stderr: '' })
    expect(read.ok).toBe(false)
  })

  test('matchesTier compares the alias inside the resolved id and the effort exactly', async () => {
    const tier = { role: 'worker', model: 'opus', effort: 'medium' }
    expect(matchesTier(tier, 'claude-opus-5-5', 'medium')).toBe(true)
    expect(matchesTier(tier, 'claude-opus-5-5[1m]', 'medium')).toBe(true)
    expect(matchesTier(tier, 'claude-opus-5-5', 'high')).toBe(false)
    expect(matchesTier(tier, 'claude-sonnet-5-5', 'medium')).toBe(false)
    expect(matchesTier(tier, 'claude-opus-5-5', 2048)).toBe(false)
  })

  test('driftLine leads with the effort_rider name for this route', async () => {
    const line = driftLine('saga:worker', { role: 'worker', model: 'opus', effort: 'medium' }, 'claude-opus-5-5', 'high', 'a9')
    expect(line.startsWith('tiering-drift[claude-agent-type]: ')).toBe(true)
  })

  test('roleAgentTypesArgv runs the script from the plugin root', async () => {
    expect(roleAgentTypesArgv('/root', '/repo')).toEqual(['python3', '/root/scripts/role_agent_types.py', '--cwd', '/repo', '--json'])
  })
})
