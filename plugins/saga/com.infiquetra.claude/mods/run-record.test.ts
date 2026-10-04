import { describe, expect, test } from 'claude-code/testing'
import {
  KNOWN_SCHEMA,
  parseRunRecordShow,
  runRecordRunFailed,
  runRecordShowArgv,
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
