import { describe, expect, test } from 'claude-code/testing'
import {
  KNOWN_RUN_STATUS_SCHEMA,
  KNOWN_SCHEMA,
  parseRunRecordShow,
  parseRunStatusSummary,
  readRunRecordWith,
  readRunStatusWith,
  runRecordRunFailed,
  runRecordShowArgv,
  runStatusSummaryArgv,
  sagaScriptArgv,
} from './run-record.ts'

const ran = (exitCode: number, stdout: string, stderr = '', isStdoutTruncated = false) => ({
  exitCode,
  stdout,
  stderr,
  isStdoutTruncated,
})
const record = { schema: KNOWN_SCHEMA, issue: 7, next_step: 'plan', units: [] }

describe('parseRunRecordShow', () => {
  test('parses a run_record.v1 record printed at exit 0', async () => {
    expect(parseRunRecordShow(ran(0, JSON.stringify(record, null, 2)))).toEqual({ ok: true, record })
  })

  test('refuses a record version it does not know, even at exit 0', async () => {
    const read = parseRunRecordShow(ran(0, JSON.stringify({ ...record, schema: 'run_record.v2' })))
    expect(read.ok).toBe(false)
    if (!read.ok) expect(read.reason).toBe('unknown-version')
  })

  test('refuses a record with no version as unknown-version', async () => {
    const read = parseRunRecordShow(ran(0, JSON.stringify({ issue: 7, next_step: 'plan' })))
    expect(read.ok).toBe(false)
    if (!read.ok) expect(read.reason).toBe('unknown-version')
  })

  test("maps exit 3, the script's unknown-version refusal, to unknown-version", async () => {
    expect(parseRunRecordShow(ran(3, '', 'run_record: unknown record version run_record.v9\n'))).toEqual({
      ok: false,
      reason: 'unknown-version',
      detail: 'run_record: unknown record version run_record.v9',
    })
  })

  test('maps exit 2 with the no-record message to no-record', async () => {
    const stderr = 'run_record: no record for issue 7 at /repo/.claude/saga/runs/7.json\n'
    const read = parseRunRecordShow(ran(2, '', stderr))
    expect(read).toEqual({ ok: false, reason: 'no-record', detail: stderr.trim() })
  })

  test('maps exit 2 with any other message to error, not no-record', async () => {
    const read = parseRunRecordShow(ran(2, '', 'run_record: git rev-parse --git-common-dir failed\n'))
    expect(read.ok).toBe(false)
    if (!read.ok) expect(read.reason).toBe('error')
  })

  test('maps any other non-zero exit to error', async () => {
    const read = parseRunRecordShow(ran(1, '', 'Traceback ...'))
    expect(read.ok).toBe(false)
    if (!read.ok) expect(read.reason).toBe('error')
  })

  test('maps standard output the engine cut off to unreadable, naming the truncation', async () => {
    const whole = JSON.stringify(record)
    const read = parseRunRecordShow(ran(0, whole.slice(0, whole.length - 3), '', true))
    expect(read.ok).toBe(false)
    if (!read.ok) {
      expect(read.reason).toBe('unreadable')
      expect(read.detail).toContain('cut off')
    }
  })

  test('maps output that is not one JSON object to unreadable', async () => {
    for (const stdout of ['not json', '[]', 'null', '7']) {
      const read = parseRunRecordShow(ran(0, stdout))
      expect(read.ok).toBe(false)
      if (!read.ok) expect(read.reason).toBe('unreadable')
    }
  })
})

describe('readRunRecordWith', () => {
  test('runs show for the issue from the plugin root and parses what it printed', async () => {
    const seen: string[][] = []
    const read = await readRunRecordWith(
      async (argv) => {
        seen.push(argv)
        return ran(0, JSON.stringify(record))
      },
      '/root',
      7,
    )
    expect(seen).toEqual([['python3', '/root/scripts/run_record.py', 'show', '7']])
    expect(read).toEqual({ ok: true, record })
  })

  test('passes a failing exit through the parser', async () => {
    const stderr = 'run_record: no record for issue 7 at /repo/.claude/saga/runs/7.json\n'
    const read = await readRunRecordWith(async () => ran(2, '', stderr), '/root', 7)
    expect(read).toEqual({ ok: false, reason: 'no-record', detail: stderr.trim() })
  })

  test('resolves to error, not a rejection, when the runner rejects', async () => {
    const read = await readRunRecordWith(
      async () => {
        throw new Error('spawn python3 ENOENT')
      },
      '/root',
      7,
    )
    expect(read).toEqual({ ok: false, reason: 'error', detail: 'run_record show did not run: spawn python3 ENOENT' })
  })

  test('resolves to error without running anything for an issue number that is not one', async () => {
    let calls = 0
    const read = await readRunRecordWith(
      async () => {
        calls += 1
        return ran(0, JSON.stringify(record))
      },
      '/root',
      0,
    )
    expect(calls).toBe(0)
    expect(read.ok).toBe(false)
    if (!read.ok) expect(read.reason).toBe('error')
  })
})

describe('runRecordRunFailed', () => {
  test('maps a rejected process run to error, keeping its message', async () => {
    const read = runRecordRunFailed(new Error('spawn python3 ENOENT'))
    expect(read).toEqual({ ok: false, reason: 'error', detail: 'run_record show did not run: spawn python3 ENOENT' })
  })

  test('maps a rejection that is not an Error to error as well', async () => {
    const read = runRecordRunFailed('timed out')
    expect(read.ok).toBe(false)
    if (!read.ok) expect(read.reason).toBe('error')
  })
})

describe('argv builders', () => {
  test('runRecordShowArgv runs show for one issue from the plugin root', async () => {
    expect(runRecordShowArgv('/root', 5)).toEqual(['python3', '/root/scripts/run_record.py', 'show', '5'])
  })

  test('runRecordShowArgv refuses anything that is not a positive whole issue number', async () => {
    for (const issue of [0, -1, 1.5, Number.NaN]) {
      expect(() => runRecordShowArgv('/root', issue)).toThrow()
    }
  })

  test('sagaScriptArgv passes arguments through unquoted', async () => {
    expect(sagaScriptArgv('/root', 'admission.py', ['answer', '--issue', '5', 'a b'])).toEqual([
      'python3',
      '/root/scripts/admission.py',
      'answer',
      '--issue',
      '5',
      'a b',
    ])
  })

  test('sagaScriptArgv refuses a script name that could leave scripts/', async () => {
    for (const script of ['../x.py', 'sub/x.py', '..py', 'x.sh', '']) {
      expect(() => sagaScriptArgv('/root', script, [])).toThrow()
    }
  })
})

describe('run_status summary', () => {
  const view = { schema: KNOWN_RUN_STATUS_SCHEMA, repo_root: '/repo', runs: [{ issue: 7, plan_path: 'docs/p.md' }] }

  test('runStatusSummaryArgv names the checkout and asks for JSON', async () => {
    expect(runStatusSummaryArgv('/root', { repoRoot: '/repo' })).toEqual([
      'python3',
      '/root/scripts/run_status.py',
      '--repo-root',
      '/repo',
      'summary',
      '--json',
    ])
    expect(runStatusSummaryArgv('/root', { repoRoot: '/repo', issue: 7, allActive: true })).toEqual([
      'python3',
      '/root/scripts/run_status.py',
      '--repo-root',
      '/repo',
      'summary',
      '--issue',
      '7',
      '--all-active',
      '--json',
    ])
    expect(() => runStatusSummaryArgv('/root', { repoRoot: '/repo', issue: 0 })).toThrow()
  })

  test('parses a run_status.v1 view printed at exit 0', async () => {
    expect(parseRunStatusSummary(ran(0, JSON.stringify(view)))).toEqual({ ok: true, view })
  })

  test('refuses another view version, exit 3, a failed run, cut output and a view with no runs', async () => {
    const cases: [ReturnType<typeof ran>, string][] = [
      [ran(0, JSON.stringify({ ...view, schema: 'run_status.v2' })), 'unknown-version'],
      [ran(3, '', 'run_status: unknown record version'), 'unknown-version'],
      [ran(2, '', 'run_status: git failed'), 'error'],
      [ran(0, JSON.stringify(view), '', true), 'unreadable'],
      [ran(0, 'not json'), 'unreadable'],
      [ran(0, '[]'), 'unreadable'],
      [ran(0, JSON.stringify({ schema: KNOWN_RUN_STATUS_SCHEMA })), 'unreadable'],
    ]
    for (const [result, reason] of cases) {
      const read = parseRunStatusSummary(result)
      expect(read.ok).toBe(false)
      if (!read.ok) expect(read.reason).toBe(reason)
    }
  })

  test('readRunStatusWith resolves to error, not a rejection, when the runner rejects', async () => {
    const read = await readRunStatusWith(
      async () => {
        throw new Error('spawn python3 ENOENT')
      },
      '/root',
      { repoRoot: '/repo' },
    )
    expect(read).toEqual({ ok: false, reason: 'error', detail: 'run_status summary did not run: spawn python3 ENOENT' })
  })
})
