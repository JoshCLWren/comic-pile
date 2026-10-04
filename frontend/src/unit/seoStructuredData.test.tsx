import { cleanup, render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, test } from 'vitest'
import Seo from '../seo/Seo'
import LandingPage from '../pages/LandingPage'
import {
  buildLandingStructuredData,
  LANDING_FEATURES,
  SITE_DESCRIPTION,
  SITE_NAME,
  STRUCTURED_DATA_SCRIPT_ID,
} from '../seo/structuredData'

interface JsonLdNode {
  '@type': string
  name?: string
  url?: string
  description?: string
  featureList?: string[]
}

interface JsonLdGraph {
  '@context': string
  '@graph': JsonLdNode[]
}

function structuredDataScript(): HTMLScriptElement | null {
  return document.head.querySelector<HTMLScriptElement>(`script#${STRUCTURED_DATA_SCRIPT_ID}`)
}

function renderSeoAt(path: string): void {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Seo />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  cleanup()
  document.head.querySelectorAll('script[type="application/ld+json"]').forEach(tag => tag.remove())
})

test('landing route injects valid JSON-LD with WebSite and SoftwareApplication', () => {
  renderSeoAt('/')

  const script = structuredDataScript()
  expect(script).not.toBeNull()
  expect(script?.type).toBe('application/ld+json')

  const data = JSON.parse(script?.textContent ?? '') as JsonLdGraph
  expect(data['@context']).toBe('https://schema.org')
  const types = data['@graph'].map(node => node['@type'])
  expect(types).toContain('WebSite')
  expect(types).toContain('SoftwareApplication')
})

test('structured data claims match the visible landing page', () => {
  render(
    <MemoryRouter initialEntries={['/']}>
      <Seo />
      <LandingPage />
    </MemoryRouter>,
  )

  const data = JSON.parse(structuredDataScript()?.textContent ?? '') as JsonLdGraph
  const [website, application] = data['@graph']

  expect(website.name).toBe(SITE_NAME)
  expect(website.description).toBe(SITE_DESCRIPTION)
  expect(application.name).toBe(SITE_NAME)
  expect(application.description).toBe(SITE_DESCRIPTION)

  // The site name is the document identity shown in the title element.
  expect(document.title).toContain(SITE_NAME)

  // Every feature claim must be literally visible on the rendered page.
  const pageText = document.body.textContent ?? ''
  for (const feature of LANDING_FEATURES) {
    expect(pageText).toContain(feature)
  }
})

test('non-indexable routes remove the structured data script', () => {
  renderSeoAt('/')
  expect(structuredDataScript()).not.toBeNull()

  cleanup()
  renderSeoAt('/login')
  expect(structuredDataScript()).toBeNull()

  cleanup()
  renderSeoAt('/queue')
  expect(structuredDataScript()).toBeNull()
})

test('no route emits FAQ schema', () => {
  for (const path of ['/', '/login', '/register', '/forgot-password', '/reset-password', '/demo', '/queue']) {
    cleanup()
    renderSeoAt(path)
    const scripts = Array.from(document.head.querySelectorAll('script[type="application/ld+json"]'))
    for (const script of scripts) {
      expect(script.textContent).not.toContain('FAQPage')
    }
  }
})

test('runtime structured data matches the static prerendered graph', () => {
  renderSeoAt('/')
  const runtime = JSON.parse(structuredDataScript()?.textContent ?? '') as JsonLdGraph
  const expected = buildLandingStructuredData(window.location.origin)
  expect(runtime).toEqual(expected)
})
