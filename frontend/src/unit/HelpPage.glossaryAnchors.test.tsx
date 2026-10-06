import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MockInstance } from 'vitest'
import HelpPage from '../pages/HelpPage'
import { GLOSSARY_ANCHORS, GLOSSARY_TERMS, slugifyGlossaryTerm } from '../utils/glossaryTerms'

/**
 * Issue #3146 acceptance contract.
 *
 * Before the fix, six of the twenty glossary cards carried a hand-maintained
 * anchor id that disagreed with the displayed term, so `/glossary#series` and
 * friends did nothing while the stale `/glossary#thread` was the only fragment
 * that scrolled. Nothing on a card exposed the real anchor, so deep links could
 * not even be discovered.
 *
 * The contract is now:
 *  1. every card's anchor id is the slug of the term the reader actually sees;
 *  2. retired ids stay resolvable inside the same card;
 *  3. every card exposes a visible, copyable permalink for its canonical id;
 *  4. a `/glossary#<id>` deep link scrolls that definition, new or retired;
 *  5. in-app glossary cross-links point at canonical ids, not retired ones.
 */

/** Retired anchor id → the term it must keep resolving to. */
const LEGACY_ANCHORS: Array<[string, string]> = [
  ['thread', 'Series'],
  ['ladder-mode', 'Auto-adjust'],
  ['die-ladder', 'Die size'],
  ['autoladder', 'Auto'],
  ['position', 'Pos'],
  ['dependency', 'Dependency rule'],
  ['readiness', 'Blocked'],
]

/** Deep links that were reported as broken because the ids had drifted. */
const REPORTED_DEEP_LINKS: Array<[string, string]> = [
  ['series', 'Series'],
  ['auto-adjust', 'Auto-adjust'],
  ['auto', 'Auto'],
  ['pos', 'Pos'],
  ['dependency-rule', 'Dependency rule'],
  ['blocked', 'Blocked'],
  ['die-size', 'Die size'],
]

function renderGlossary(path = '/glossary') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <HelpPage />
    </MemoryRouter>,
  )
}

const SRC_DIR = resolve(__dirname, '..')

function productionSourceFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    if (entry === 'unit' || entry === 'test' || entry === 'devtools') continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      files.push(...productionSourceFiles(full))
    } else if (/\.tsx?$/.test(entry)) {
      files.push(full)
    }
  }
  return files
}

function requireAnchor(id: string): HTMLElement {
  const target = document.getElementById(id)
  expect(target, `expected a glossary anchor for #${id}`).not.toBeNull()
  // SAFETY: expect above asserted non-null, so the cast is safe.
  return target as HTMLElement
}

/**
 * The definition card that owns an anchor. A retired alias is an sr-only span
 * inside its card, so walk up until the element contains the definition body.
 */
function cardForAnchor(id: string): HTMLElement {
  return cardForElement(requireAnchor(id))
}

/** The definition card that owns a rendered anchor element. */
function cardForElement(anchor: HTMLElement): HTMLElement {
  let node: HTMLElement | null = anchor
  while (node && !node.querySelector('[data-testid="glossary-definition"]')) {
    node = node.parentElement
  }
  expect(node, `expected #${anchor.id} to sit on a definition card`).not.toBeNull()
  // SAFETY: expect above asserted non-null, so the cast is safe.
  return node as HTMLElement
}

function termForAnchor(id: string): string {
  return cardForAnchor(id).querySelector('[data-testid="glossary-term"]')?.textContent ?? ''
}

describe('glossary anchors (issue #3146)', () => {
  it('derives every card anchor id from the term the reader sees', () => {
    renderGlossary()
    const cards = screen.getAllByTestId('glossary-term')
    expect(cards).toHaveLength(GLOSSARY_TERMS.length)
    for (const termEl of cards) {
      // SAFETY: closest on a rendered term returns its card container.
      const card = termEl.closest('[id]') as HTMLElement
      const slug = slugifyGlossaryTerm(termEl.textContent ?? '')
      expect(slug).not.toBe('')
      expect(card.id).toBe(slug)
    }
  })

  it('keeps every anchor unique in the document', () => {
    renderGlossary()
    const ids = Array.from(document.querySelectorAll('[id]')).map((element) => element.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('publishes exactly the canonical and retired anchors on the page', () => {
    renderGlossary()
    const rendered = Array.from(document.querySelectorAll('[id]'))
      .map((element) => element.id)
      .filter((id) => GLOSSARY_ANCHORS.includes(id))
      .sort()
    expect(rendered).toEqual([...new Set(GLOSSARY_ANCHORS)].sort())
  })

  it('never reuses a canonical id as a retired alias', () => {
    const canonicalIds = new Set(GLOSSARY_TERMS.map((term) => term.id))
    expect(canonicalIds.size).toBe(GLOSSARY_TERMS.length)
    for (const term of GLOSSARY_TERMS) {
      for (const alias of term.aliases ?? []) {
        expect(canonicalIds.has(alias)).toBe(false)
      }
    }
  })

  it.each(REPORTED_DEEP_LINKS)('resolves the reported #%s deep link', (id, term) => {
    renderGlossary()
    expect(termForAnchor(id)).toBe(term)
  })

  it.each(LEGACY_ANCHORS)('keeps the retired #%s link on the same card', (legacyId, term) => {
    renderGlossary()
    expect(termForAnchor(legacyId)).toBe(term)
  })

  it('keeps every in-app glossary cross-link pointed at a canonical id', () => {
    const canonicalIds = new Set(GLOSSARY_TERMS.map((term) => term.id))
    const referenced: Array<[string, string]> = []
    for (const file of productionSourceFiles(SRC_DIR)) {
      const source = readFileSync(file, 'utf-8')
      for (const match of source.matchAll(/<GlossaryLink\b[^>]*?\bid="([^"]+)"/g)) {
        referenced.push([match[1], file.slice(SRC_DIR.length + 1)])
      }
    }

    expect(referenced.length).toBeGreaterThan(0)
    for (const [id, file] of referenced) {
      expect(
        canonicalIds.has(id),
        `${file} links to /glossary#${id}, which is not a canonical definition anchor`,
      ).toBe(true)
    }
  })
})

describe('glossary permalinks (issue #3146)', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('exposes one copyable permalink per definition, pointed at its canonical id', () => {
    renderGlossary()
    const permalinks = screen.getAllByTestId('glossary-permalink')
    expect(permalinks).toHaveLength(GLOSSARY_TERMS.length)

    for (const permalink of permalinks) {
      const href = permalink.getAttribute('href') ?? ''
      const id = href.slice(href.indexOf('#') + 1)
      expect(href).toBe(`/glossary#${id}`)
      expect(document.getElementById(id), `#${id} must exist on the page`).not.toBeNull()

      const term = termForAnchor(id)
      expect(permalink).toHaveAttribute('aria-label', `Copy link to ${term} definition`)
      expect(permalink).toHaveAttribute('title', `Copy link to ${term} definition`)
    }
  })

  it('copies the absolute deep link when the permalink is activated', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)
    renderGlossary()

    const permalink = screen.getByRole('link', { name: 'Copy link to Series definition' })
    await user.click(permalink)

    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/glossary#series`),
    )
    await waitFor(() => expect(permalink).toHaveAttribute('data-status', 'copied'))
    expect(await screen.findByText('Link to Series copied to clipboard.')).toBeInTheDocument()
  })

  it('keeps the permalink usable and explains a failed copy', async () => {
    const user = userEvent.setup()
    const writeText = vi
      .spyOn(navigator.clipboard, 'writeText')
      .mockRejectedValue(new Error('clipboard denied'))
    renderGlossary()

    const permalink = screen.getByRole('link', { name: 'Copy link to Blocked definition' })
    await user.click(permalink)

    await waitFor(() => expect(permalink).toHaveAttribute('data-status', 'failed'))
    expect(
      screen.getByText('Could not copy the Blocked link. Copy it from the address bar instead.'),
    ).toBeInTheDocument()
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/glossary#blocked`)
  })
})

describe('glossary deep-link scrolling (issue #3146)', () => {
  let scrollIntoView: MockInstance<Element['scrollIntoView']>

  beforeEach(() => {
    scrollIntoView = vi
      .spyOn(Element.prototype, 'scrollIntoView')
      .mockImplementation(() => undefined)
  })

  afterEach(() => {
    scrollIntoView.mockRestore()
  })

  async function scrolledTermFor(path: string): Promise<string> {
    renderGlossary(path)
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled())
    // SAFETY: scrollIntoView mock was called with the card element.
    const target = scrollIntoView.mock.contexts[0] as HTMLElement
    return cardForElement(target).querySelector('[data-testid="glossary-term"]')?.textContent ?? ''
  }

  it.each(REPORTED_DEEP_LINKS)('scrolls the reported #%s deep link to its definition', async (id, term) => {
    expect(await scrolledTermFor(`/glossary#${id}`)).toBe(term)
  })

  it.each(LEGACY_ANCHORS)('scrolls the retired #%s deep link to its definition', async (legacyId, term) => {
    expect(await scrolledTermFor(`/glossary#${legacyId}`)).toBe(term)
  })

  it('does not scroll when the fragment is empty', async () => {
    renderGlossary('/glossary')
    await waitFor(() => expect(screen.getAllByTestId('glossary-term').length).toBeGreaterThan(0))
    expect(scrollIntoView).not.toHaveBeenCalled()
  })
})