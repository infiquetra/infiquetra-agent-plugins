import { describe, expect, test } from 'claude-code/testing'

import { GOLDEN_PAGE, GOLDEN_STACKED, WIDE_TABLE_PLAN } from './fixtures/wide-table-plan.fixture.ts'
import {
  MARKDOWN_LIMIT,
  MAX_LINKS,
  PAGE_LIMIT,
  discussPromptText,
  displayWidth,
  fitTables,
  linkifyRefs,
  pageText,
  parseRef,
  planSavePath,
  quoteBlock,
  refFromHref,
  refPromptText,
  splitSections,
  tableWidth,
} from './plan-sections.ts'

const ROOT = '/Users/operator/repo'

/** True when every fence a page opens, it closes. */
function fencesBalance(page: string): boolean {
  let open: string | null = null
  for (const line of page.split('\n')) {
    const mark = /^ {0,3}(`{3,}|~{3,})/.exec(line)?.[1]
    if (mark === undefined) continue
    if (open === null) open = mark
    else if (mark[0] === open[0] && mark.length >= open.length) open = null
  }
  return open === null
}

describe('splitSections', () => {
  test('frontmatter becomes its own section and is not a heading', async () => {
    const sections = splitSections('---\ntitle: x\n---\n# Plan\n\nBody.')
    expect(sections.map((s) => [s.level, s.title])).toEqual([
      [0, 'Frontmatter'],
      [1, 'Plan'],
    ])
    expect(sections[0]?.text).toBe('---\ntitle: x\n---')
  })

  test('a heading line inside a fenced code block is not a section', async () => {
    const sections = splitSections('## Real\n\n```bash\n## not a heading\n```\n\n~~~\n# nor this\n~~~\n## Also real')
    expect(sections.map((s) => s.title)).toEqual(['Real', 'Also real'])
    expect(sections[0]?.text).toContain('## not a heading')
  })

  test('a section holds its subsections, which are listed again beneath it', async () => {
    const sections = splitSections('## Units\n\nIntro.\n\n### U1\n\nOne.\n\n### U2\n\nTwo.\n\n## Risks\n\nNone.')
    expect(sections.map((s) => [s.level, s.title])).toEqual([
      [2, 'Units'],
      [3, 'U1'],
      [3, 'U2'],
      [2, 'Risks'],
    ])
    expect(sections[0]?.text).toBe('## Units\n\nIntro.\n\n### U1\n\nOne.\n\n### U2\n\nTwo.')
    expect(sections[1]?.text).toBe('### U1\n\nOne.')
  })

  test('text before the first heading is kept; level-4 headings stay in their section', async () => {
    const sections = splitSections('Preface.\n\n## A\n\n#### deep\n\ntext')
    expect(sections.map((s) => s.title)).toEqual(['Before the first heading', 'A'])
    expect(sections[1]?.text).toContain('#### deep')
  })

  test('closing hashes and CRLF line ends are dropped; control characters are removed', async () => {
    const sections = splitSections('## Title ##\r\n\r\nBody\u0007 text.')
    expect(sections).toEqual([{ level: 2, title: 'Title', text: '## Title ##\n\nBody text.' }])
  })

  test('a plan with no headings has no heading sections', async () => {
    expect(splitSections('')).toEqual([])
    expect(splitSections('just text').map((s) => s.level)).toEqual([0])
  })
})

describe('pageText', () => {
  test('text that fits is one page', async () => {
    expect(pageText('short')).toEqual(['short'])
  })

  test('a 23,000-character section pages into 3 pages of at most 9,000, rejoining to the whole', async () => {
    const paragraph = 'word '.repeat(199) + 'end.'
    const text = Array.from({ length: 23 }, () => paragraph).join('\n\n')
    expect(text.length).toBeGreaterThan(23_000)
    const pages = pageText(text)
    expect(pages).toHaveLength(3)
    for (const page of pages) expect(page.length).toBeLessThanOrEqual(PAGE_LIMIT)
    expect(pages.join('\n\n')).toBe(text)
  })

  test('a fenced block longer than a page is closed and reopened with its info string', async () => {
    const code = Array.from({ length: 1500 }, (_, i) => `line ${i} of the listing`).join('\n')
    const text = `## Listing\n\n\`\`\`python\n${code}\n\`\`\`\n\nAfter.`
    const pages = pageText(text)
    expect(pages.length).toBeGreaterThan(3)
    for (const page of pages) {
      expect(page.length).toBeLessThanOrEqual(PAGE_LIMIT)
      expect(fencesBalance(page)).toBe(true)
    }
    for (const page of pages.slice(1, -1)) expect(page.startsWith('```python\n')).toBe(true)
    expect(pages.at(-1)?.endsWith('After.')).toBe(true)
  })

  test('a blank line inside a fence is not a page break', async () => {
    const block = `\`\`\`\n${'x'.repeat(50)}\n\n${'y'.repeat(50)}\n\`\`\``
    const pages = pageText(`${'a'.repeat(60)}\n\n${block}`, 120)
    expect(pages).toEqual(['a'.repeat(60), block])
  })

  test('a single line longer than a page is cut by characters', async () => {
    const pages = pageText('z'.repeat(25), 10)
    expect(pages.join('')).toBe('z'.repeat(25))
    for (const page of pages) expect(page.length).toBeLessThanOrEqual(10)
  })
})

describe('file references', () => {
  test('a backticked path and line becomes a file link and a reference', async () => {
    const { text, refs } = linkifyRefs('See `plugins/x.py:12` and `True`.', ROOT)
    const href = 'file:///Users/operator/repo/plugins/x.py#L12'
    expect(text).toBe(`See [\`plugins/x.py:12\`](${href}) and \`True\`.`)
    expect(refs).toEqual([{ href, label: 'plugins/x.py:12', path: 'plugins/x.py', line: 12 }])
  })

  test('what counts as a file reference', async () => {
    expect(parseRef('plugins/saga/README.md', ROOT)?.href).toBe('file:///Users/operator/repo/plugins/saga/README.md')
    expect(parseRef('saga.py:221', ROOT)?.label).toBe('saga.py:221')
    expect(parseRef('./docs/x.md:3-9', ROOT)?.label).toBe('docs/x.md:3')
    expect(parseRef('/etc/hosts:1', ROOT)?.href).toBe('file:///etc/hosts#L1')
    for (const span of ['True', 'run_record.v1', 'saga.py', 'issue/104', '../x.py:1', 'a b.py', 'https://x.io/a.md']) {
      expect(parseRef(span, ROOT)).toBeNull()
    }
  })

  test('references inside a fenced block are left alone', async () => {
    const { text, refs } = linkifyRefs('```\n`plugins/x.py:1`\n```', ROOT)
    expect(text).toBe('```\n`plugins/x.py:1`\n```')
    expect(refs).toEqual([])
  })

  test('links stop at 256 distinct references', async () => {
    const many = Array.from({ length: 300 }, (_, i) => `\`p/f${i}.py:1\``).join(' ')
    const { refs } = linkifyRefs(many, ROOT, 1_000_000)
    expect(refs).toHaveLength(MAX_LINKS)
  })

  test('a page never grows past the Markdown limit by linking', async () => {
    const page = Array.from({ length: 200 }, (_, i) => `\`plugins/saga/scripts/file${i}.py:${i + 1}\``).join(' ')
    expect(page.length).toBeLessThanOrEqual(PAGE_LIMIT)
    const { text, refs } = linkifyRefs(page, ROOT)
    expect(text.length).toBeLessThanOrEqual(MARKDOWN_LIMIT)
    // The room ran out before the references did; the rest stay inline code.
    expect(refs.length).toBeGreaterThan(0)
    expect(refs.length).toBeLessThan(200)
  })

  test('a pressed href is read back to its reference', async () => {
    const known = linkifyRefs('`plugins/x.py:12`', ROOT).refs
    const [first] = known
    expect(refFromHref(first?.href ?? '', ROOT, known)).toBe(first)
    expect(refFromHref('file:///Users/operator/repo/a/b.ts#L3', ROOT, [])?.label).toBe('a/b.ts:3')
    expect(refFromHref('https://example.com', ROOT, [])).toBeNull()
  })

  test('a reference goes into the prompt as inline code', async () => {
    expect(refPromptText({ href: '', label: 'a/b.ts:3', path: 'a/b.ts', line: 3 })).toBe('`a/b.ts:3` ')
  })
})

describe('quoting', () => {
  test('quoteBlock quotes every line, blank lines included', async () => {
    expect(quoteBlock('a\n\nb')).toBe('> a\n>\n> b')
  })

  test('discussPromptText names the plan, the section and the page', async () => {
    const section = { level: 2 as const, title: 'Units', text: '## Units\n\nBody.' }
    expect(discussPromptText('docs/plans/p.md', section, 0, 1)).toBe(
      'From the plan docs/plans/p.md, section "Units":\n\n> ## Units\n>\n> Body.\n\n',
    )
  })
})

describe('planSavePath', () => {
  test("reads the plan path from /plan's save of a plan tick", async () => {
    const base = 'python3 plugins/saga/scripts/saga.py save --kind issue --id 7 --lifecycle-phase plan'
    expect(planSavePath(`${base} --plan-path 'docs/plans/a-plan.md'`)).toBe('docs/plans/a-plan.md')
    expect(planSavePath(`${base} --plan-path="docs/plans/b plan.md"`)).toBe('docs/plans/b plan.md')
    expect(planSavePath(`${base} --plan-path docs/plans/c.md --destination pr`)).toBe('docs/plans/c.md')
  })

  test('ignores other phases, other commands and a save with no plan path', async () => {
    expect(planSavePath('python3 saga.py save --lifecycle-phase work --plan-path docs/p.md')).toBeNull()
    expect(planSavePath('python3 saga.py restore --saga-id issue-7 --lifecycle-phase plan --plan-path x.md')).toBeNull()
    expect(planSavePath('python3 saga.py save --lifecycle-phase plan')).toBeNull()
    expect(planSavePath("echo '--lifecycle-phase plan --plan-path x.md'")).toBeNull()
  })
})

/** The next whole word `token` in `text`, not a match inside a longer word. */
function findToken(text: string, token: string, from: number): number {
  let at = from
  while (at < text.length) {
    const found = text.indexOf(token, at)
    if (found < 0) return -1
    const before = found === 0 ? '' : (text[found - 1] ?? '')
    const after = text[found + token.length] ?? ''
    const boundary = (character: string) => character === '' || /[^A-Za-z0-9]/.test(character)
    if (boundary(before) && boundary(after)) return found
    at = found + 1
  }
  return -1
}

describe('fitting tables to the pane', () => {
  test('keeps the golden page at 90 columns and stacks it at 89', async () => {
    expect(fitTables(GOLDEN_PAGE, 90)).toBe(GOLDEN_PAGE)
    expect(fitTables(GOLDEN_PAGE, 89)).toBe(GOLDEN_STACKED)
  })

  test('measures the live 71-column table and stacks it one column narrower', async () => {
    const left = `${'a'.repeat(31)}Z`
    const right = `${'b'.repeat(31)}Y`
    const rows = [
      ['A', 'B'],
      [left, right],
      ['1', '2'],
    ]
    expect(tableWidth(rows)).toBe(71)
    const table = ['| A | B |', '| --- | --- |', `| ${left} | ${right} |`, '| 1 | 2 |'].join('\n')
    expect(fitTables(table, 71)).toBe(table)
    const stacked = fitTables(table, 70)
    expect(stacked).toBe(['**A:** ' + left, '', '**B:** ' + right, '', '* * *', '', '**A:** 1', '', '**B:** 2'].join('\n'))
  })

  test('counts wide characters, a tab, and a checkmark plus letters', async () => {
    expect(displayWidth('✅')).toBe(2)
    expect(displayWidth('漢')).toBe(2)
    expect(displayWidth('→')).toBe(1)
    expect(displayWidth('é')).toBe(1)
    expect(displayWidth('\t')).toBe(8)
    expect(displayWidth(`✅${'n'.repeat(31)}`)).toBe(33)
  })

  test('keeps a pipe inside a code span in one cell and an escaped pipe as written', async () => {
    const coded = ['| Left | Right |', '| --- | --- |', '| `x|y` | z |'].join('\n')
    const codedStacked = fitTables(coded, 10)
    expect(codedStacked).toContain('**Left:** `x|y`')
    expect(codedStacked).toContain('**Right:** z')
    expect(codedStacked).not.toContain('**Column')

    const escaped = ['| Left | Right |', '| --- | --- |', '| esc \\| pipe | w |'].join('\n')
    const escapedStacked = fitTables(escaped, 10)
    expect(escapedStacked).toContain('**Left:** esc \\| pipe')
    expect(escapedStacked).toContain('**Right:** w')
    expect(escapedStacked.match(/\*\*Left:\*\*/g)).toHaveLength(1)
  })

  test('leaves fences, indents, quotes, lists, and non-tables unchanged at 10 columns', async () => {
    const body = '| this cell is wider than ten | x |'
    const samples = [
      `\`\`\`\n| A | B |\n| --- | --- |\n${body}\n\`\`\``,
      `~~~\n| A | B |\n| --- | --- |\n${body}\n~~~`,
      `    | A | B |\n    | --- | --- |\n    ${body}`,
      `> | A | B |\n> | --- | --- |\n> ${body}`,
      `- item\n\n  | A | B |\n  | --- | --- |\n  ${body}`,
      '| A | B |\n| not a delimiter |',
      '| A | B | C |\n| --- | --- |\n| 1 | 2 | 3 |',
      '| A very long header that exceeds ten | B |\n| --- | --- |',
    ]
    for (const sample of samples) expect(fitTables(sample, 10)).toBe(sample)
  })

  test('fills a short row with em dashes and drops extra cells', async () => {
    const table = ['| A | B | C |', '| --- | --- | --- |', '| only |', '| a | b | c | d | extra |'].join('\n')
    const stacked = fitTables(table, 10)
    expect(stacked).toContain('**A:** only')
    expect(stacked).toContain('**B:** —')
    expect(stacked).toContain('**C:** —')
    expect(stacked).toContain('**A:** a')
    expect(stacked).toContain('**B:** b')
    expect(stacked).toContain('**C:** c')
    expect(stacked).not.toContain('extra')
    expect(stacked).not.toContain('| d |')
  })

  test('labels an empty header Column 2 and does not re-bold a header that has a star', async () => {
    const table = ['| Item |  | **Cost** |', '| --- | --- | --- |', '| widget |  | 9 |'].join('\n')
    const stacked = fitTables(table, 10)
    expect(stacked).toContain('**Item:** widget')
    expect(stacked).toContain('**Column 2:** —')
    expect(stacked).toContain('**Cost**: 9')
    expect(stacked).not.toContain('****')
  })

  test('stacks only the table that is wider than the width', async () => {
    const before = 'Before.\n\n'
    const small = '| A | B |\n| --- | --- |\n| 1 | 2 |'
    const between = '\n\nBetween here.\n\n'
    const wide = '| Left | Right |\n| --- | --- |\n| this cell is definitely wider than twenty | x |'
    const after = '\n\nAfter.'
    const page = before + small + between + wide + after
    const fitted = fitTables(page, 20)
    expect(fitted.startsWith(before + small + between)).toBe(true)
    expect(fitted.endsWith(after)).toBe(true)
    expect(fitted).toContain('**Left:** this cell is definitely wider than twenty')
    expect(fitted).not.toContain('| Left | Right |')
  })

  test('keeps every word of the Decisions table in row order', async () => {
    const section = splitSections(WIDE_TABLE_PLAN).find((one) => one.title === 'Decisions')
    expect(section).toBeDefined()
    const lines = (section?.text ?? '').split('\n').filter((line) => line.startsWith('|'))
    const cellsOf = (line: string) => line.split('|').slice(1, -1).map((cell) => cell.trim())
    const header = cellsOf(lines[0] ?? '')
    const body = lines.slice(2).map(cellsOf)
    const stacked = fitTables(section?.text ?? '', 71)
    expect(stacked).not.toBe(section?.text)
    // A stacked row is "**Header:** cell" per column, so the header words sit
    // beside that column's cell rather than in a header row of their own.
    const words: string[] = []
    for (const row of body) {
      header.forEach((label, index) => {
        words.push(...label.split(/\s+/).filter((word) => word !== ''))
        words.push(...(row[index] ?? '').split(/\s+/).filter((word) => word !== ''))
      })
    }
    let at = 0
    for (const word of words) {
      const found = findToken(stacked, word, at)
      expect(found).toBeGreaterThanOrEqual(at)
      at = found + word.length
    }
    expect(tableWidth([header, ...body])).toBe(80)
    const linked = linkifyRefs(section?.text ?? '', ROOT)
    expect(fitTables(linked.text, 150)).toBe(linked.text)
    expect(fitTables(linked.text, 149)).not.toBe(linked.text)
  })

  test('keeps a linked file reference when the golden page is stacked', async () => {
    const linked = linkifyRefs(GOLDEN_PAGE, ROOT)
    const again = linkifyRefs(GOLDEN_PAGE, ROOT)
    const fitted = fitTables(linked.text, 89)
    const href = linked.refs[0]?.href
    expect(href).toContain('review_roster.py')
    expect(fitted).toContain(`[\`plugins/saga/scripts/review_roster.py\`](${href})`)
    expect(linked.refs).toEqual(again.refs)
  })

  test("repeats a long table's header on every continuation page", async () => {
    const header = '| id | body |'
    const delimiter = '| --- | --- |'
    const rows = Array.from({ length: 200 }, (_, index) => `| ${String(index).padStart(4, '0')} | ${'x'.repeat(40)} |`)
    const table = [header, delimiter, ...rows].join('\n')
    expect(table.length).toBeGreaterThan(PAGE_LIMIT)
    const pages = pageText(table)
    expect(pages.length).toBeGreaterThan(1)
    for (const page of pages) expect(page.length).toBeLessThanOrEqual(PAGE_LIMIT)
    for (const page of pages.slice(1)) expect(page.startsWith(`${header}\n${delimiter}\n`)).toBe(true)
    const joined = pages.join('\n')
    for (const row of rows) expect(joined.split(row).length - 1).toBe(1)
  })

  test('stacks a wide one-dash delimiter at 10 columns and keeps a short one at 200', async () => {
    const wide = ['| Left | Right | Tail |', '|-|:-|-:|', '| this cell is wider than ten | y | z |'].join('\n')
    const stacked = fitTables(wide, 10)
    expect(stacked).toContain('**Left:** this cell is wider than ten')
    expect(stacked).toContain('**Right:** y')
    expect(stacked).toContain('**Tail:** z')
    expect(stacked).not.toContain('|-|')

    const short = ['| A | B | C |', '|-|:-|-:|', '| a | b | c |'].join('\n')
    expect(fitTables(short, 200)).toBe(short)
  })

  test('returns a stacked page longer than 10,000 characters whole', async () => {
    const cell = 'word '.repeat(600).trim()
    const table = ['| A | B | C | D |', '| --- | --- | --- | --- |', `| ${cell} | ${cell} | ${cell} | ${cell} |`].join('\n')
    const stacked = fitTables(table, 10)
    expect(stacked.length).toBeGreaterThan(MARKDOWN_LIMIT)
    expect(stacked.split(cell).length - 1).toBe(4)
  })
})
