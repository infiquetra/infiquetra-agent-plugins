import { describe, expect, test } from 'claude-code/testing'
import { launchTableArgs, orchestrateArgv, parseJsonRun, readJsonWith, statusArgs } from './orchestrate-script.ts'

const ran = (exitCode: number, stdout: string, stderr = '', isStdoutTruncated = false) => ({
  exitCode,
  stdout,
  stderr,
  isStdoutTruncated,
})
const SCHEMA = 'orchestrate.status.v1'

describe('orchestrateArgv', () => {
  test('runs the driver under the plugin root with the arguments unquoted', async () => {
    expect(orchestrateArgv('/root', ['status', '--issue', '7', '--json'])).toEqual([
      'python3',
      '/root/skills/orchestrate/scripts/orchestrate.py',
      'status',
      '--issue',
      '7',
      '--json',
    ])
  })

  test('refuses every subcommand that is not read-only', async () => {
    for (const sub of ['start', 'go', 'expand', 'merge', 'settle', 'clean', 'wait', 'adopt', 'review-result', '']) {
      expect(() => orchestrateArgv('/root', [sub])).toThrow()
    }
  })
})

describe('argument builders', () => {
  test('statusArgs takes a positive whole issue number only', async () => {
    expect(statusArgs(7)).toEqual(['status', '--issue', '7', '--json'])
    for (const bad of [0, -1, 1.5, Number.NaN]) expect(() => statusArgs(bad)).toThrow()
  })

  test('launchTableArgs names the plan, and the issue when expanding', async () => {
    expect(launchTableArgs('/p.json')).toEqual(['launch-table', '--plan', '/p.json', '--json'])
    expect(launchTableArgs('/p.json', 4)).toEqual(['launch-table', '--plan', '/p.json', '--issue', '4', '--json'])
    expect(() => launchTableArgs('  ')).toThrow()
    expect(() => launchTableArgs('/p.json', 0)).toThrow()
  })
})

describe('parseJsonRun', () => {
  test('parses the named schema at exit 0', async () => {
    expect(parseJsonRun(ran(0, JSON.stringify({ schema: SCHEMA, units: [] })), SCHEMA)).toEqual({
      ok: true,
      value: { schema: SCHEMA, units: [] },
    })
  })

  test('a non-zero exit carries the last stderr line, the refusal', async () => {
    expect(parseJsonRun(ran(2, '', 'a notice\nthe refusal\n'), SCHEMA)).toEqual({ ok: false, error: 'the refusal' })
    const silent = parseJsonRun(ran(1, ''), SCHEMA)
    expect(silent.ok).toBe(false)
    if (!silent.ok) expect(silent.error).toContain('exited 1')
  })

  test('refuses prose, a non-object, another schema and cut-off output', async () => {
    for (const stdout of ['run r1', '[]', 'null', JSON.stringify({ schema: 'orchestrate.status.v2' })]) {
      expect(parseJsonRun(ran(0, stdout), SCHEMA).ok).toBe(false)
    }
    expect(parseJsonRun(ran(0, '{"schema"', '', true), SCHEMA).ok).toBe(false)
  })
})

describe('readJsonWith', () => {
  test('never rejects: a runner that throws becomes an error', async () => {
    const read = await readJsonWith(
      async () => {
        throw new Error('spawn python3 ENOENT')
      },
      '/root',
      () => statusArgs(7),
      SCHEMA,
    )
    expect(read).toEqual({ ok: false, error: 'orchestrate.py did not run: spawn python3 ENOENT' })
  })

  test('bad arguments become an error without running anything', async () => {
    let calls = 0
    const read = await readJsonWith(
      async () => {
        calls += 1
        return ran(0, '{}')
      },
      '/root',
      () => statusArgs(0),
      SCHEMA,
    )
    expect(calls).toBe(0)
    expect(read.ok).toBe(false)
  })
})
