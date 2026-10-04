import { describe, expect, test } from 'claude-code/testing'

import {
  MARKDOWN_LIMIT,
  MAX_LINKS,
  PAGE_LIMIT,
  discussPromptText,
  linkifyRefs,
  pageText,
  parseRef,
  planSavePath,
  quoteBlock,
  refFromHref,
  refPromptText,
  splitSections,
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
