// The plan viewer's text handling: split a plan into sections, page a long
// section under the engine's Markdown limit, turn backticked `path:line`
// references into links a press can answer, and quote a page for the prompt.
//
// Pure functions with no `$`, so `plan-viewer.tsx` and its tests share them and
// later mods can reuse them; nothing here reads a file or draws.

import type { SagaPlanSection } from '../types/index.d.ts'

/** The most characters one `Markdown` element draws (`MarkdownProps.text`). */
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
 * string, so every page draws as the block it came from. A single line longer
 * than a page is cut by characters.
 */
function splitBlock(block: string, limit: number): string[] {
  const pages: string[] = []
  const fence = new FenceState()
  let current: string[] = []
  // The page's length once joined, plus one: each line counts its newline.
  let size = 0
  let hasContent = false

  const flush = () => {
    const open = fence.open
    pages.push((open !== null ? [...current, fence.closer] : current).join('\n'))
    current = open !== null ? [open] : []
    size = open !== null ? open.length + 1 : 0
    hasContent = false
  }
  const add = (text: string) => {
    current.push(text)
    size += text.length + 1
    hasContent = true
  }

  for (const line of block.split('\n')) {
    // Room for the fence that closes this page, before and after this line.
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
    fence.feed(line)
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
