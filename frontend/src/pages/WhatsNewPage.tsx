import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'

type Block =
  | { type: 'heading'; level: number; text: string }
  | { type: 'list'; items: string[] }
  | { type: 'paragraph'; text: string }

type ChangelogDay = {
  type: 'day'
  sourceDateTime: string
  label: string
  summary: string
  blocks: Block[]
}

type ChangelogViewItem = Block | ChangelogDay

const CHANGELOG_ASSET = '/changelog.md'
const SOURCE_DATE = /^\d{4}-\d{2}-\d{2}$/
const SOURCE_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?(?:Z|[+-]\d{2}:\d{2})$/

export function isPublicChangelogLink(url: string) {
  try {
    const hostname = new URL(url).hostname.toLowerCase().replace(/\.$/, '')
    return hostname !== 'github.com' && !hostname.endsWith('.github.com')
  } catch {
    return false
  }
}

export function publicChangelogText(text: string) {
  return text
    .replace(/\s+\b(?:in|via)\s+\[#\d+\]\(https?:\/\/github\.com\/[^)]+\/pull\/\d+\)/gi, '')
    .replace(/\[#\d+\]\(https?:\/\/github\.com\/[^)]+\/pull\/\d+\)\s*/gi, '')
    .replace(/\bPR\s+#\d+\b:?\s*/gi, '')
    .trim()
}

function renderInline(text: string) {
  const publicText = publicChangelogText(text)
  const pattern = /(`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)]+\))/g
  return publicText.split(pattern).map((part, index) => {
    const code = part.match(/^`([^`]+)`$/)
    if (code) return <code key={index} className="rounded bg-stone-800 px-1.5 py-0.5 text-amber-200">{code[1]}</code>
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/)
    if (link) {
      if (!isPublicChangelogLink(link[2])) return <Fragment key={index}>{link[1]}</Fragment>
      return <a key={index} href={link[2]} target="_blank" rel="noreferrer" className="font-semibold text-amber-300 underline decoration-amber-500/50 underline-offset-4">{link[1]} <span aria-label="opens in a new tab">↗</span></a>
    }
    return <Fragment key={index}>{part}</Fragment>
  })
}

export function parseChangelog(markdown: string): Block[] {
  const blocks: Block[] = []
  let list: string[] = []
  const flushList = () => {
    if (list.length) blocks.push({ type: 'list', items: list })
    list = []
  }

  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line) {
      flushList()
      continue
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/)
    if (heading) {
      flushList()
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2] })
      continue
    }
    const item = line.match(/^[-*]\s+(.+)$/)
    if (item) {
      list.push(item[1])
      continue
    }
    flushList()
    blocks.push({ type: 'paragraph', text: line })
  }
  flushList()
  return blocks
}

function isSourceDateTime(value: string) {
  if (SOURCE_DATE.test(value)) return true
  if (!SOURCE_TIMESTAMP.test(value)) return false
  return !Number.isNaN(Date.parse(value))
}

function formatSourceDateTime(value: string, timeZone?: string) {
  if (SOURCE_DATE.test(value)) {
    const [year, month, day] = value.split('-').map(Number)
    return new Intl.DateTimeFormat(undefined, {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      timeZone: 'UTC',
    }).format(new Date(Date.UTC(year, month - 1, day)))
  }

  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone,
    timeZoneName: 'short',
  }).format(new Date(value))
}

function summarizeDay(blocks: Block[]) {
  const areas = blocks
    .filter((block): block is Extract<Block, { type: 'heading' }> => block.type === 'heading' && block.level >= 3)
    .map(block => publicChangelogText(block.text))
    .filter(Boolean)
  const updateCount = blocks.reduce((count, block) => {
    if (block.type === 'list') return count + block.items.length
    if (block.type === 'paragraph') return count + 1
    return count
  }, 0)
  const effectiveUpdateCount = updateCount || 1
  const countText = `${effectiveUpdateCount} ${effectiveUpdateCount === 1 ? 'update' : 'updates'}`
  const uniqueAreas = [...new Set(areas)]

  if (uniqueAreas.length === 0) return `${countText} published this day.`
  if (uniqueAreas.length === 1) return `${countText} for ${uniqueAreas[0]}.`
  if (uniqueAreas.length === 2) return `${countText} across ${uniqueAreas[0]} and ${uniqueAreas[1]}.`
  return `${countText} across ${uniqueAreas.slice(0, 2).join(', ')}, and more.`
}

export function buildChangelogView(markdown: string, timeZone?: string): ChangelogViewItem[] {
  const blocks = parseChangelog(markdown)
  const view: ChangelogViewItem[] = []

  for (let index = 0; index < blocks.length; index += 1) {
    const block = blocks[index]
    if (block.type !== 'heading' || block.level !== 2 || !isSourceDateTime(block.text)) {
      view.push(block)
      continue
    }

    const dayBlocks: Block[] = []
    let cursor = index + 1
    while (cursor < blocks.length) {
      const next = blocks[cursor]
      if (next.type === 'heading' && next.level === 2 && isSourceDateTime(next.text)) {
        if (next.text === block.text) {
          cursor += 1
          continue
        }
        break
      }
      dayBlocks.push(next)
      cursor += 1
    }

    view.push({
      type: 'day',
      sourceDateTime: block.text,
      label: formatSourceDateTime(block.text, timeZone),
      summary: summarizeDay(dayBlocks),
      blocks: dayBlocks,
    })
    index = cursor - 1
  }

  return view
}

function BlockContent({ block }: { block: Block }) {
  if (block.type === 'heading') {
    const Tag = block.level <= 2 ? 'h2' : 'h3'
    return <Tag className={block.level <= 2 ? 'border-b border-stone-800 pb-2 pt-4 text-2xl font-black text-stone-100 first:pt-0' : 'pt-3 text-lg font-bold text-amber-200'}>{renderInline(block.text)}</Tag>
  }
  if (block.type === 'list') return <ul className="list-disc space-y-2 pl-6 leading-7">{block.items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item)}</li>)}</ul>
  return <p className="leading-7">{renderInline(block.text)}</p>
}

export default function WhatsNewPage() {
  const [markdown, setMarkdown] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const view = useMemo(() => (markdown ? buildChangelogView(markdown) : []), [markdown])

  const load = useCallback(async () => {
    setMarkdown(null)
    setError(null)
    try {
      const response = await fetch(CHANGELOG_ASSET, { cache: 'no-cache' })
      if (!response.ok) throw new Error(response.status === 404 ? 'The changelog file is missing.' : 'The changelog could not be loaded.')
      const body = await response.text()
      if (!body.trim()) throw new Error('The changelog file is empty.')
      setMarkdown(body)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'The changelog could not be loaded.')
    }
  }, [])

  useEffect(() => { void load() }, [load, attempt])

  return (
    <section aria-labelledby="whats-new-title" className="mx-auto max-w-3xl pb-8">
      <header className="mb-6 rounded-2xl border border-amber-500/20 bg-stone-950/70 p-5 shadow-lg">
        <p className="text-xs font-bold uppercase tracking-[0.22em] text-amber-400">ComicPile release notes</p>
        <h1 id="whats-new-title" className="mt-2 text-3xl font-black text-stone-100">What’s New</h1>
        <p className="mt-2 text-sm leading-6 text-stone-400">Recent improvements, fixes, and new ways to manage your reading pile.</p>
      </header>

      {!markdown && !error && <div role="status" className="rounded-xl border border-stone-800 bg-stone-950/60 p-6 text-stone-400">Loading release notes…</div>}

      {error && (
        <div role="alert" className="rounded-xl border border-red-900/60 bg-red-950/30 p-6">
          <h2 className="text-lg font-bold text-red-200">Release notes unavailable</h2>
          <p className="mt-2 text-sm text-red-100/80">{error}</p>
          <button type="button" onClick={() => setAttempt(value => value + 1)} className="mt-4 min-h-11 rounded-lg bg-amber-400 px-4 py-2 font-bold text-stone-950">Try again</button>
        </div>
      )}

      {markdown && (
        <article className="space-y-4 rounded-2xl border border-stone-800 bg-stone-950/60 p-5 text-stone-300">
          {view.map((item, index) => {
            if (item.type !== 'day') return <BlockContent key={index} block={item} />
            return (
              <section key={`${item.sourceDateTime}-${index}`} aria-labelledby={`release-day-${index}`} className="border-t border-stone-800 pt-5 first:border-t-0 first:pt-0">
                <h2 id={`release-day-${index}`} className="text-2xl font-black text-stone-100">
                  <time dateTime={item.sourceDateTime}>{item.label}</time>
                </h2>
                <p className="mt-1 text-sm text-stone-400">{item.summary}</p>
                <div className="mt-3 space-y-3">
                  {item.blocks.map((block, blockIndex) => <BlockContent key={blockIndex} block={block} />)}
                </div>
              </section>
            )
          })}
        </article>
      )}
    </section>
  )
}
