// The plan viewer's text handling: split a plan into sections, page a long
// section under the mod's page budget, turn backticked `path:line` references
// into links a press can answer, stack a table that does not fit the pane, and
// quote a page for the prompt.
//
// Pure functions with no `$`, so `plan-viewer.tsx` and its tests share them and
// later mods can reuse them; nothing here reads a file or draws.

import type { SagaPlanSection } from '../types/index.d.ts'

/** The mod's own page budget, in characters, for one `Markdown` element. */
export const MARKDOWN_LIMIT = 10_000

/**
 * The most characters a page holds before its references become links. Links
 * are added only while the page stays within `MARKDOWN_LIMIT`, so the margin
 * buys room for them; it never decides whether a page fits.
 */
export const PAGE_LIMIT = 9_000

/** `MarkdownProps.pressableLinks`: at most 256 links of at most 2048 characters. */
export const MAX_LINKS = 256
export const MAX_HREF = 2048

const FENCE = /^ {0,3}(`{3,}|~{3,})(.*)$/
const HEADING = /^ {0,3}(#{1,3})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$/
// Every control character but tab and newline, which a Markdown text refuses.
const CONTROL = /[\u0000-\u0008\u000B-\u001F\u007F]/g

/** Tracks whether a line sits inside a fenced code block. */
class FenceState {
  private opener: { mark: string; line: string } | null = null

  /** The fence line that opened the block the next line sits in, or null. */
  get open(): string | null {
    return this.opener?.line ?? null
  }

  /** The line that closes the open block. */
  get closer(): string {
    return this.opener?.mark ?? '```'
  }

  /** The characters a page ending here needs to close the open block. */
  get reserve(): number {
    return this.opener === null ? 0 : this.opener.mark.length + 1
  }

  clone(): FenceState {
    const copy = new FenceState()
    copy.opener = this.opener
    return copy
  }

  /** Feed one line; true when the line is itself a fence line. */
  feed(line: string): boolean {
    const fence = FENCE.exec(line)
    if (fence === null) return false
    const mark = fence[1] ?? ''
    const info = fence[2] ?? ''
    if (this.opener === null) {
      // A backtick fence's info string may not hold a backtick.
      if (mark.startsWith('`') && info.includes('`')) return false
      this.opener = { mark, line }
      return true
    }
    if (mark[0] === this.opener.mark[0] && mark.length >= this.opener.mark.length && info.trim() === '') {
      this.opener = null
      return true
    }
    return false
  }
}

/** The plan's text as a Markdown element accepts it: LF line ends, no other control characters. */
export function normalizePlanText(markdown: string): string {
  return markdown.replace(/\r\n?/g, '\n').replace(CONTROL, '')
}

/**
 * Split a plan into the sections the pane lists, in document order.
 *
 * Leading frontmatter (between `---` lines) is a section of its own, as is any
 * text before the first heading. Headings of level 1 to 3 start a section; a
 * `#` line inside a fenced code block is not a heading. A section's text runs
 * to the next heading of the same or a higher level, so a `##` section holds
 * its `###` subsections, which are listed again on their own beneath it.
 */
export function splitSections(markdown: string): SagaPlanSection[] {
  const lines = normalizePlanText(markdown).split('\n')
  const sections: SagaPlanSection[] = []
  let start = 0

  if (lines[0] === '---') {
    const end = lines.findIndex((line, i) => i > 0 && (line === '---' || line === '...'))
    if (end > 0) {
      sections.push({ level: 0, title: 'Frontmatter', text: lines.slice(0, end + 1).join('\n') })
      start = end + 1
    }
  }

  const headings: { line: number; level: 1 | 2 | 3; title: string }[] = []
  const fence = new FenceState()
  lines.forEach((line, i) => {
    if (i < start || fence.feed(line) || fence.open !== null) return
    const heading = HEADING.exec(line)
    if (heading === null) return
    const title = (heading[2] ?? '').trim()
    const level = (heading[1] ?? '#').length as 1 | 2 | 3
    headings.push({ line: i, level, title: title === '' ? '(untitled)' : title })
  })

  const firstHeading = headings[0]?.line ?? lines.length
  const preamble = lines.slice(start, firstHeading).join('\n')
  if (preamble.trim() !== '') {
    sections.push({ level: 0, title: 'Before the first heading', text: preamble.trim() })
  }

  headings.forEach((heading, k) => {
    const next = headings.slice(k + 1).find((later) => later.level <= heading.level)
    const end = next === undefined ? lines.length : next.line
    sections.push({
      level: heading.level,
      title: heading.title,
      text: lines.slice(heading.line, end).join('\n').trimEnd(),
    })
  })
  return sections
}

/**
 * Split one oversize block line by line. A page that ends inside a fenced code
 * block closes the fence, and the next page opens it again with the same info
 * string, so every page draws as the block it came from. A page that ends
 * inside a table starts the next page with that table's header and delimiter.
 * Their length is reserved the same way as the reopened fence, so no page
 * passes `limit`. A single line longer than a page is cut by characters.
 */
function splitBlock(block: string, limit: number): string[] {
  const pages: string[] = []
  const fence = new FenceState()
  const flow = new FlowState()
  const lines = block.split('\n')
  let table: { header: string; delimiter: string } | null = null
  let current: string[] = []
  // The page's length once joined, plus one: each line counts its newline.
  let size = 0
  let hasContent = false

  const flush = () => {
    const open = fence.open
    pages.push((open !== null ? [...current, fence.closer] : current).join('\n'))
    if (open !== null) {
      current = [open]
      size = open.length + 1
    } else if (table !== null) {
      current = [table.header, table.delimiter]
      size = table.header.length + 1 + table.delimiter.length + 1
    } else {
      current = []
      size = 0
    }
    hasContent = false
  }
  const add = (text: string) => {
    current.push(text)
    size += text.length + 1
    hasContent = true
  }
  const fits = (from: number, text: string, reserve: number): boolean => from + text.length + reserve <= limit
  const note = (line: string) => {
    const wasFence = fence.open !== null
    const isFence = fence.feed(line)
    flow.feed(line, wasFence || isFence || fence.open !== null)
  }

  for (let index = 0; index < lines.length; index++) {
    const line = lines[index] ?? ''
    const next = lines[index + 1]
    if (table !== null && flow.endsTable(line, fence.open !== null)) table = null

    // A header and its delimiter stay on one page. Splitting them is what
    // leaves the next page with no header, which the engine then draws as raw pipes.
    if (table === null && next !== undefined && flow.canOpenTable(line, next, fence.open !== null)) {
      const delimiter = next
      const after = fence.clone()
      after.feed(line)
      after.feed(delimiter)
      const reserve = Math.max(fence.reserve, after.reserve)
      let from = size
      if (hasContent && !fits(from, line, reserve)) {
        flush()
        from = size
      }
      if (fits(from, line, reserve) && fits(from + line.length + 1, delimiter, reserve)) {
        add(line)
        add(delimiter)
        note(line)
        note(delimiter)
        table = { header: line, delimiter }
        index += 1
        continue
      }
    }

    const after = fence.clone()
    after.feed(line)
    const reserve = Math.max(fence.reserve, after.reserve)
    let rest = line
    if (hasContent && size + rest.length + reserve > limit) flush()
    while (size + rest.length + reserve > limit) {
      const take = Math.max(1, limit - reserve - size)
      add(rest.slice(0, take))
      rest = rest.slice(take)
      flush()
    }
    add(rest)
    note(line)
  }
  if (hasContent) {
    const open = fence.open
    pages.push((open !== null ? [...current, fence.closer] : current).join('\n'))
  }
  return pages
}

/**
 * Page a section so that no page is longer than `limit` characters.
 *
 * Pages break at blank lines outside fenced code blocks where they can; a
 * block too long for one page is split by `splitBlock`. Text that fits is one page.
 */
export function pageText(text: string, limit: number = PAGE_LIMIT): string[] {
  if (text.length <= limit) return [text]

  const blocks: string[] = []
  const fence = new FenceState()
  let current: string[] = []
  for (const line of text.split('\n')) {
    const isFenceLine = fence.feed(line)
    if (!isFenceLine && fence.open === null && line.trim() === '') {
      if (current.length > 0) blocks.push(current.join('\n'))
      current = []
      continue
    }
    current.push(line)
  }
  if (current.length > 0) blocks.push(current.join('\n'))

  const pages: string[] = []
  let page = ''
  for (const block of blocks) {
    if (block.length > limit) {
      if (page !== '') pages.push(page)
      page = ''
      pages.push(...splitBlock(block, limit))
      continue
    }
    const joined = page === '' ? block : `${page}\n\n${block}`
    if (joined.length > limit) {
      pages.push(page)
      page = block
    } else {
      page = joined
    }
  }
  if (page !== '') pages.push(page)
  return pages
}

// Display width follows the ranges measured against the engine. A code point
// that is not listed counts as one, and a listed wide character counts as two,
// so a table judged to fit is never wider on screen than this count.
const WIDE_CODE_POINTS: ReadonlyArray<readonly [number, number]> = [
  [0x1100, 0x115f],
  [0x231a, 0x231b],
  [0x23e9, 0x23ec],
  [0x23f0, 0x23f0],
  [0x23f3, 0x23f3],
  [0x25fd, 0x25fe],
  [0x2600, 0x27bf],
  [0x2b1b, 0x2b1c],
  [0x2b50, 0x2b50],
  [0x2b55, 0x2b55],
  [0x2e80, 0x303e],
  [0x3041, 0x33ff],
  [0x3400, 0x4dbf],
  [0x4e00, 0x9fff],
  [0xa000, 0xa4cf],
  [0xac00, 0xd7a3],
  [0xf900, 0xfaff],
  [0xfe30, 0xfe4f],
  [0xff00, 0xff60],
  [0xffe0, 0xffe6],
  [0x1f000, 0x1faff],
  [0x20000, 0x3fffd],
]
const ZERO_WIDTH_CODE_POINTS: ReadonlyArray<readonly [number, number]> = [
  [0x0300, 0x036f],
  [0x200b, 0x200f],
  [0xfe00, 0xfe0f],
  [0xe0100, 0xe01ef],
]

function inCodePointRanges(codePoint: number, ranges: ReadonlyArray<readonly [number, number]>): boolean {
  for (const [start, end] of ranges) {
    if (codePoint < start) return false
    if (codePoint <= end) return true
  }
  return false
}

function widthOf(codePoint: number): number {
  if (codePoint === 0x09) return 8
  if (inCodePointRanges(codePoint, ZERO_WIDTH_CODE_POINTS)) return 0
  if (inCodePointRanges(codePoint, WIDE_CODE_POINTS)) return 2
  return 1
}

/** How many terminal cells `text` occupies. Markup counts; this never under-counts the engine. */
export function displayWidth(text: string): number {
  let width = 0
  for (const character of text) width += widthOf(character.codePointAt(0) ?? 0)
  return width
}

const LIST_ITEM = /^ {0,3}(?:[-+*]|\d{1,9}[.)])\s+/
const BLOCKQUOTE_LINE = /^ {0,3}>/
const HEADING_LINE = /^ {0,3}#{1,6}(?:[ \t]|$)/
const DELIMITER_CELL = /^:?-{3,}:?$/
const EMPTY_CELL = '—'

function leadingSpaces(line: string): number {
  return /^ */.exec(line)?.[0].length ?? 0
}

/**
 * Split one row on `|` that is neither escaped nor inside a backtick code span.
 * One leading and one trailing `|` are dropped, and each cell is trimmed.
 */
function splitCells(line: string): { cells: string[]; separators: number } {
  const raw: string[] = []
  let buffer = ''
  let separators = 0
  let inCode = false
  let codeLength = 0
  for (let index = 0; index < line.length; ) {
    const character = line[index] ?? ''
    if (!inCode && character === '\\' && index + 1 < line.length) {
      buffer += character + (line[index + 1] ?? '')
      index += 2
      continue
    }
    if (character === '`') {
      let run = 0
      while (line[index + run] === '`') run += 1
      buffer += '`'.repeat(run)
      if (!inCode) {
        inCode = true
        codeLength = run
      } else if (run === codeLength) {
        inCode = false
      }
      index += run
      continue
    }
    if (!inCode && character === '|') {
      raw.push(buffer)
      buffer = ''
      separators += 1
      index += 1
      continue
    }
    buffer += character
    index += 1
  }
  raw.push(buffer)
  let start = 0
  let end = raw.length
  const trimmed = line.trim()
  if (trimmed.startsWith('|')) start += 1
  if (trimmed.endsWith('|') && end > start) end -= 1
  return { cells: raw.slice(start, end).map((cell) => cell.trim()), separators }
}

function isTableHeaderLine(line: string): boolean {
  if (leadingSpaces(line) > 3) return false
  if (BLOCKQUOTE_LINE.test(line) || LIST_ITEM.test(line) || HEADING_LINE.test(line) || FENCE.test(line)) return false
  return splitCells(line).separators >= 1
}

function isDelimiterLine(line: string, columns: number): boolean {
  if (columns < 1 || leadingSpaces(line) > 3) return false
  if (BLOCKQUOTE_LINE.test(line) || LIST_ITEM.test(line)) return false
  const { cells, separators } = splitCells(line)
  if (separators < 1 || cells.length !== columns) return false
  return cells.every((cell) => DELIMITER_CELL.test(cell))
}

/** Whether the walker is inside a list item or a blockquote, where a table is left as written. */
class FlowState {
  private listIndent: number | null = null
  private listBlank = false
  private quote = false
  private quoteBlank = false

  private inList(line: string): boolean {
    if (this.listIndent === null) return false
    if (line.trim() === '') return true
    return !(this.listBlank && leadingSpaces(line) < this.listIndent && LIST_ITEM.exec(line) === null)
  }

  private inQuote(line: string): boolean {
    if (!this.quote) return false
    if (line.trim() === '') return true
    return !(this.quoteBlank && !BLOCKQUOTE_LINE.test(line))
  }

  /** True when `line` followed by `next` opens a top-level table. */
  canOpenTable(line: string, next: string, inFence: boolean): boolean {
    if (inFence || this.inList(line) || this.inQuote(line)) return false
    if (!isTableHeaderLine(line)) return false
    return isDelimiterLine(next, splitCells(line).cells.length)
  }

  /** True when `line` ends the body of the table currently being read. */
  endsTable(line: string, inFence: boolean): boolean {
    if (inFence) return false
    if (line.trim() === '') return true
    return BLOCKQUOTE_LINE.test(line) || HEADING_LINE.test(line) || FENCE.test(line)
  }

  feed(line: string, inFence: boolean): void {
    if (inFence) return
    if (line.trim() === '') {
      if (this.listIndent !== null) this.listBlank = true
      if (this.quote) this.quoteBlank = true
      return
    }
    const marker = LIST_ITEM.exec(line)
    if (marker !== null) {
      this.listIndent = marker[0].length
      this.listBlank = false
    } else if (this.listIndent !== null) {
      if (this.listBlank && leadingSpaces(line) < this.listIndent) {
        this.listIndent = null
        this.listBlank = false
      } else {
        this.listBlank = false
      }
    }
    if (BLOCKQUOTE_LINE.test(line)) {
      this.quote = true
      this.quoteBlank = false
    } else if (this.quote && this.quoteBlank) {
      this.quote = false
      this.quoteBlank = false
    }
  }
}

function padRow(cells: readonly string[], columns: number): string[] {
  return Array.from({ length: columns }, (_, index) => cells[index] ?? '')
}

/**
 * The width the engine draws for `rows`: the widest cell of each column, plus
 * three cells of grid per column, plus one. `rows[0]` is the header. A short
 * row counts as empty cells; cells past the header do not count.
 */
export function tableWidth(rows: readonly (readonly string[])[]): number {
  const header = rows[0]
  if (header === undefined || header.length === 0) return 0
  const columns = header.length
  let sum = 0
  for (let column = 0; column < columns; column++) {
    let widest = 0
    for (const row of rows) widest = Math.max(widest, displayWidth(row[column] ?? ''))
    sum += widest
  }
  return sum + 3 * columns + 1
}

function columnLabel(header: string, index: number): string {
  const name = header.trim() === '' ? `Column ${index + 1}` : header
  // A header that is already marked up would nest a second bold around it.
  return name.includes('*') ? `${name}:` : `**${name}:**`
}

function stackTable(headers: readonly string[], body: readonly (readonly string[])[]): string[] {
  const labels = headers.map((header, index) => columnLabel(header, index))
  const lines: string[] = []
  body.forEach((row, rowIndex) => {
    if (rowIndex > 0) lines.push('', '* * *', '')
    headers.forEach((_, column) => {
      if (column > 0) lines.push('')
      const cell = row[column] ?? ''
      lines.push(`${labels[column]} ${cell.trim() === '' ? EMPTY_CELL : cell}`)
    })
  })
  return lines
}

/**
 * Rewrite every top-level table wider than `columns` into labeled paragraphs.
 * A table that fits, a table with no body, and anything that is not a table
 * come back as the same string. Fitting measures the text it is given, markup
 * included, so a caller links references first.
 */
export function fitTables(markdown: string, columns: number): string {
  if (!Number.isFinite(columns)) return markdown
  const lines = markdown.split('\n')
  const fence = new FenceState()
  const flow = new FlowState()
  const replacements: { start: number; end: number; lines: string[] }[] = []

  let index = 0
  while (index < lines.length) {
    const line = lines[index] ?? ''
    const next = lines[index + 1]
    const inFence = fence.open !== null
    if (next !== undefined && flow.canOpenTable(line, next, inFence)) {
      const header = splitCells(line).cells
      let end = index + 2
      while (end < lines.length && !flow.endsTable(lines[end] ?? '', false)) end += 1
      const bodyLines = lines.slice(index + 2, end)
      if (bodyLines.length > 0) {
        const body = bodyLines.map((row) => padRow(splitCells(row).cells, header.length))
        if (tableWidth([header, ...body]) > columns) {
          replacements.push({ start: index, end, lines: stackTable(header, body) })
        }
      }
      for (let cursor = index; cursor < end; cursor++) {
        const consumed = lines[cursor] ?? ''
        const wasFence = fence.open !== null
        const isFence = fence.feed(consumed)
        flow.feed(consumed, wasFence || isFence || fence.open !== null)
      }
      index = end
      continue
    }
    const wasFence = inFence
    const isFence = fence.feed(line)
    flow.feed(line, wasFence || isFence || fence.open !== null)
    index += 1
  }

  if (replacements.length === 0) return markdown
  const out = lines.slice()
  for (let rep = replacements.length - 1; rep >= 0; rep--) {
    const one = replacements[rep]
    if (one === undefined) continue
    const insert = one.lines.slice()
    // One blank line on each side, and only where the source had a neighbour
    // that was not already blank. The table's own lines are what get replaced.
    if (one.start > 0 && out[one.start - 1] !== '') insert.unshift('')
    if (one.end < out.length && out[one.end] !== '') insert.push('')
    out.splice(one.start, one.end - one.start, ...insert)
  }
  const joined = out.join('\n')
  return joined === markdown ? markdown : joined
}

/** A file reference found in a plan: what a press on it quotes into the prompt. */
export type PlanRef = {
  /** The `file:` link drawn for it. */
  href: string
  /** `path` or `path:line`, as the plan wrote it. */
  label: string
  path: string
  line?: number
}

// `path`, `path:12` or `path:12-20`; a relative path is taken from the checkout.
const REF = /^(\/?[A-Za-z0-9_.@-][A-Za-z0-9_.@+-]*(?:\/[A-Za-z0-9_.@+-]+)*)(?::(\d+)(?:-\d+)?)?$/
const CODE_SPAN = /(?<![`[])`([^`\n]+)`(?![`\]])/g
const EXTENSION = /\.[A-Za-z0-9]+$/

/** The reference a backticked span names, or null when it does not look like a file. */
export function parseRef(span: string, repoRoot: string): PlanRef | null {
  const match = REF.exec(span.trim())
  if (match === null) return null
  const path = (match[1] ?? '').replace(/^\.\//, '')
  const line = match[2] === undefined ? undefined : Number(match[2])
  const hasSlash = path.replace(/^\//, '').includes('/')
  const hasExtension = EXTENSION.test(path)
  // `plugins/x.py`, `plugins/x:12` and `x.py:12` are files; `True`, `run_record.v1` are not.
  if (!(hasSlash ? hasExtension || line !== undefined : hasExtension && line !== undefined)) return null
  if (path.split('/').some((part) => part === '..')) return null
  const absolute = path.startsWith('/') ? path : `${repoRoot.replace(/\/+$/, '')}/${path}`
  const href = `file://${encodeURI(absolute)}${line === undefined ? '' : `#L${line}`}`
  if (href.length > MAX_HREF) return null
  return { href, label: line === undefined ? path : `${path}:${line}`, path, ...(line === undefined ? {} : { line }) }
}

/**
 * Rewrite the backticked file references in `text` into `file:` links and
 * list them, outside fenced code blocks only.
 *
 * Stops linking at `MAX_LINKS` distinct links, and never lets the text grow
 * past `maxLength`: a reference that would is left as code, so a page cut to
 * `PAGE_LIMIT` always draws.
 */
export function linkifyRefs(
  text: string,
  repoRoot: string,
  maxLength: number = MARKDOWN_LIMIT,
): { text: string; refs: PlanRef[] } {
  const refs = new Map<string, PlanRef>()
  const fence = new FenceState()
  let length = text.length
  const lines = text.split('\n').map((line) => {
    if (fence.feed(line) || fence.open !== null) return line
    return line.replace(CODE_SPAN, (whole: string, span: string) => {
      const ref = parseRef(span, repoRoot)
      if (ref === null) return whole
      if (!refs.has(ref.href) && refs.size >= MAX_LINKS) return whole
      const link = `[${whole}](${ref.href})`
      if (length + link.length - whole.length > maxLength) return whole
      length += link.length - whole.length
      if (!refs.has(ref.href)) refs.set(ref.href, ref)
      return link
    })
  })
  return { text: lines.join('\n'), refs: [...refs.values()] }
}

/** The reference a pressed `file:` link names, read back from its href. */
export function refFromHref(href: string, repoRoot: string, known: readonly PlanRef[]): PlanRef | null {
  const listed = known.find((ref) => ref.href === href)
  if (listed !== undefined) return listed
  const match = /^file:\/\/([^#?]+)(?:#L(\d+))?$/.exec(href)
  if (match === null) return null
  let absolute: string
  try {
    absolute = decodeURI(match[1] ?? '')
  } catch {
    return null
  }
  const root = `${repoRoot.replace(/\/+$/, '')}/`
  const path = absolute.startsWith(root) ? absolute.slice(root.length) : absolute
  const line = match[2] === undefined ? undefined : Number(match[2])
  return { href, label: line === undefined ? path : `${path}:${line}`, path, ...(line === undefined ? {} : { line }) }
}

/** What a press on a reference puts in the prompt: the reference as inline code. */
export function refPromptText(ref: PlanRef): string {
  return `\`${ref.label}\` `
}

/** Every line of `text` as a Markdown quote. */
export function quoteBlock(text: string): string {
  return text
    .split('\n')
    .map((line) => (line === '' ? '>' : `> ${line}`))
    .join('\n')
}

/** What "discuss this" puts in the prompt: where the text is from, then the text quoted. */
export function discussPromptText(path: string, section: SagaPlanSection, page: number, pages: number): string {
  const where = pages > 1 ? ` (page ${page + 1} of ${pages})` : ''
  const shown = pageText(section.text)[page] ?? section.text
  return `From the plan ${path}, section "${section.title}"${where}:\n\n${quoteBlock(shown)}\n\n`
}

const PLAN_SAVE = /\bsaga\.py['"]?\s+save\b/
const PLAN_PHASE = /--lifecycle-phase(?:=|\s+)['"]?plan(?=['"]?(?:\s|$))/
const PLAN_PATH = /--plan-path(?:=|\s+)(?:'([^']*)'|"([^"]*)"|([^\s'"]+))/

/**
 * The plan path a shell command saved, when the command is `/plan`'s save of
 * a plan tick (`saga.py save --lifecycle-phase plan --plan-path <path>`); else null.
 */
export function planSavePath(command: string): string | null {
  if (!PLAN_SAVE.test(command) || !PLAN_PHASE.test(command)) return null
  const match = PLAN_PATH.exec(command)
  if (match === null) return null
  const path = (match[1] ?? match[2] ?? match[3] ?? '').trim()
  return path === '' ? null : path
}
