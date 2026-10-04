// The fleet pane: `/fleet-view <issue>` shows every unit of one orchestrate run.
//
// It reads `orchestrate.py status --issue <N> --json` when opened, every
// fifteen seconds while it stays open (a timer the command starts and closing
// the pane stops), and when the operator presses Refresh. The command itself is
// registered at session start by `index.ts`, which holds the plugin's one
// `session.start` hook.
// It holds no launch, settle, merge or clean action: the only script it runs is
// `status`, through `orchestrate-script.ts`, which refuses anything else.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, On, Timer } from 'claude-code'
import type { OrchestrateStatus, OrchestrateStatusUnit } from '../types/index.d.ts'
import { readJsonWith, statusArgs } from './orchestrate-script.ts'

export const FLEET_PANE = 'orchestrate-fleet'
export const FLEET_COMMAND = 'fleet-view'
export const REFRESH_MS = 15_000
const STATUS_SCHEMA = 'orchestrate.status.v1'
/** `status` asks git and herdr; a slow herdr costs its own timeout once, so allow for it. */
const STATUS_TIMEOUT_MS = 60_000

const fleetIssue = atom({ plugin: 'orchestrate', key: 'fleetIssue' } as const, null)
const fleet = atom({ plugin: 'orchestrate', key: 'fleet' } as const, null)
const fleetRefreshedAt = atom({ plugin: 'orchestrate', key: 'fleetRefreshedAt' } as const, null)
const fleetBusy = atom({ plugin: 'orchestrate', key: 'fleetBusy' } as const, false)

/** `7` or `#7` to 7; anything else to null. */
export function parseIssue(args: string): number | null {
  const found = /^#?(\d+)$/.exec(args.trim())
  if (found === null) return null
  const issue = Number(found[1])
  return Number.isSafeInteger(issue) && issue > 0 ? issue : null
}

const COLUMNS = ['unit', 'vendor', 'model', 'effort', 'state', 'herdr', 'branch', 'commits', 'landed', 'waits on'] as const

function cells(unit: OrchestrateStatusUnit): string[] {
  return [
    unit.name,
    unit.vendor,
    unit.model ?? '-',
    unit.effort ?? '-',
    unit.state,
    unit.herdr ?? '-',
    unit.branch ?? '-',
    unit.commits === null ? (unit.landed === null ? '-' : '?') : String(unit.commits),
    unit.landed ?? '-',
    unit.waits_on || '-',
  ]
}

/** The unit table as fixed-width lines, each cut to the pane's width. */
export function fleetLines(status: OrchestrateStatus, width: number): string[] {
  const rows = status.units.map(cells)
  const widths = COLUMNS.map((head, index) => Math.max(head.length, ...rows.map((row) => row[index].length)))
  const line = (values: readonly string[]) =>
    values.map((value, index) => value.padEnd(widths[index])).join(' ').trimEnd()
  const fit = (text: string) => (text.length > width ? `${text.slice(0, Math.max(0, width - 1))}…` : text)
  return [line(COLUMNS), '-'.repeat(widths.reduce((sum, w) => sum + w, 0) + widths.length - 1), ...rows.map(line)].map(fit)
}

async function refresh($: EngineInterface, issue: number): Promise<void> {
  if (await read($, fleetBusy)) return
  await update($, fleetBusy, () => true)
  try {
    const value = await readJsonWith<OrchestrateStatus>(
      (argv) => $.process.run(argv, { timeoutMs: STATUS_TIMEOUT_MS }),
      $.plugin.root,
      () => statusArgs(issue),
      STATUS_SCHEMA,
    )
    // The pane may have closed, or moved to another issue, while the script ran.
    if ((await read($, fleetIssue)) !== issue) return
    await update($, fleet, () => value)
    const now = await $.clock.now()
    await update($, fleetRefreshedAt, () => now)
  } finally {
    await update($, fleetBusy, () => false)
  }
}

async function tick($: EngineInterface): Promise<void> {
  const issue = await read($, fleetIssue)
  if (issue === null) return
  const isOpen = (await $.ui.panes()).some((pane) => pane.id === FLEET_PANE)
  if (!isOpen) return
  await refresh($, issue)
}

/** What `index.ts` registers at session start, so the command is listed from turn one. */
export const FLEET_COMMAND_SPEC = {
  name: FLEET_COMMAND,
  description: 'Show an orchestrate run in a pane (read-only; refreshes every 15 seconds while open)',
  argumentHint: '<issue>',
}

/**
 * The refresh timer while the pane is open. A handle, not drawn state: a module
 * reload drops the engine's timers and this variable together, and the next
 * `/fleet-view` starts a new one.
 */
let timer: Timer | null = null

export function registerFleetView(on: On): void {
  on('command.run', { command: FLEET_COMMAND }, async ($, e) => {
    const issue = parseIssue(e.args)
    if (issue === null) return { text: 'Usage: /fleet-view <issue>' }
    await update($, fleetIssue, () => issue)
    await update($, fleet, () => null)
    await refresh($, issue)
    await $.ui.open({ id: FLEET_PANE, title: `orchestrate #${issue}` })
    timer ??= $.clock.every(REFRESH_MS, () => {
      void tick($)
    })
    return { text: `Showing orchestrate run for #${issue}; it refreshes every ${REFRESH_MS / 1000} seconds.` }
  })

  on('ui.close', { id: FLEET_PANE }, async ($, e, next) => {
    timer?.cancel()
    timer = null
    await update($, fleetIssue, () => null)
    await update($, fleet, () => null)
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: FLEET_PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const issue = await read($, fleetIssue)
    const reading = await read($, fleet)
    const refreshedAt = await read($, fleetRefreshedAt)
    const width = Math.max(20, e.props.bodyColumns)
    const header: string[] = []
    let body: string[] = []
    let error: string | null = null
    if (reading === null) {
      header.push(issue === null ? 'No run is shown. /fleet-view <issue> opens one.' : `Reading run #${issue}...`)
    } else if (!reading.ok) {
      error = reading.error
    } else {
      const status = reading.value
      header.push(`run ${status.run_id}   branch ${status.branch || '-'}   #${status.issue}`)
      if (status.unresolvable_branch) header.push(`run branch ${status.unresolvable_branch} does not resolve`)
      body = fleetLines(status, width)
      body.push(...status.unrecorded.map((found) => `UNRECORDED ${found.name} -- branch ${found.branch}`))
      body.push(
        ...status.operator_actions.map(
          (action) => `OPERATOR ACTION: ${action.owner} owns fix ${action.fix_id} for ${action.touched_paths.join(', ')}`,
        ),
      )
    }
    const refreshed = refreshedAt === null ? '' : `refreshed at ${new Date(refreshedAt).toISOString().slice(11, 19)} UTC`
    return (
      <Box flexDirection="column">
        {header.map((line, index) => (
          <Text key={`header-${index}`} bold={index === 0}>
            {line}
          </Text>
        ))}
        {error === null ? null : (
          <Text key="error" color="red">
            {error}
          </Text>
        )}
        {body.map((line, index) => (
          <Text key={`row-${index}`}>{line}</Text>
        ))}
        <Text key="refreshed" dimColor>
          {refreshed}
        </Text>
        <Box flexDirection="row">
          <Button
            key="refresh"
            label="Refresh"
            onPress={async () => {
              const current = await read($, fleetIssue)
              if (current !== null) await refresh($, current)
            }}
          />
          <Button key="close" label="Close" role="dismiss" onPress={() => $.ui.close({ id: FLEET_PANE })} />
        </Box>
      </Box>
    )
  })
}
