import { cleanup, render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, test } from 'vitest'
import Seo from '../seo/Seo'

function resetHead(): void {
  document.head
    .querySelectorAll('meta[name="robots"], meta[name="description"], link[rel="canonical"]')
    .forEach(tag => tag.remove())
}

function renderSeoAt(path: string): void {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Seo />
    </MemoryRouter>,
  )
}

function robotsContent(): string | null {
  return document.head.querySelector('meta[name="robots"]')?.getAttribute('content') ?? null
}

function canonicalHrefs(): string[] {
  return Array.from(document.head.querySelectorAll('link[rel="canonical"]')).map(
    tag => tag.getAttribute('href') ?? '',
  )
}

beforeEach(() => {
  cleanup()
  resetHead()
})

test('indexable landing page emits exactly one stable canonical URL', () => {
  renderSeoAt('/')

  expect(document.title).toContain('ComicPile')
  expect(robotsContent()).toBe('index, follow')
  const hrefs = canonicalHrefs()
  expect(hrefs).toHaveLength(1)
  expect(hrefs[0]?.endsWith('/')).toBe(true)
  expect(document.head.querySelector('meta[name="description"]')?.getAttribute('content')).toContain(
    'dice-driven reading queue',
  )
})

test('login page is not indexable and emits no canonical', () => {
  renderSeoAt('/login')

  expect(robotsContent()).toBe('noindex, nofollow')
  expect(canonicalHrefs()).toHaveLength(0)
})

test('password-reset utility pages are not indexable', () => {
  renderSeoAt('/forgot-password')
  expect(robotsContent()).toBe('noindex, nofollow')
  expect(canonicalHrefs()).toHaveLength(0)

  cleanup()
  renderSeoAt('/reset-password')
  expect(robotsContent()).toBe('noindex, nofollow')
  expect(canonicalHrefs()).toHaveLength(0)
})

test('authenticated routes are not indexable and emit no canonical', () => {
  renderSeoAt('/queue')
  expect(robotsContent()).toBe('noindex, nofollow')
  expect(canonicalHrefs()).toHaveLength(0)

  cleanup()
  renderSeoAt('/thread/42')
  expect(robotsContent()).toBe('noindex, nofollow')
  expect(canonicalHrefs()).toHaveLength(0)
})

test('leaving the landing page removes its canonical URL', () => {
  renderSeoAt('/')
  expect(canonicalHrefs()).toHaveLength(1)

  cleanup()
  renderSeoAt('/queue')
  expect(canonicalHrefs()).toHaveLength(0)
  expect(robotsContent()).toBe('noindex, nofollow')
})
