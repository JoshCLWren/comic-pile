import { Fragment, useCallback, useEffect, useState } from 'react'

type Block =
  | { type: 'heading'; level: number; text: string }
  | { type: 'list'; items: string[] }
  | { type: 'paragraph'; text: string }

const CHANGELOG_ASSET = '/changelog.md'

function renderInline(text: string) {
  const pattern = /(`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)]+\))/g
  return text.split(pattern).map((part, index) => {
    const code = part.match(/^`([^`]+)`$/)
    if (code) return <code key={index} className="rounded bg-stone-800 px-1.5 py-0.5 text-amber-200">{code[1]}</code>
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/)
    if (link) {
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

export default function WhatsNewPage() {
  const [markdown, setMarkdown] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

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
          {parseChangelog(markdown).map((block, index) => {
            if (block.type === 'heading') {
              const Tag = block.level <= 2 ? 'h2' : 'h3'
              return <Tag key={index} className={block.level <= 2 ? 'border-b border-stone-800 pb-2 pt-4 text-2xl font-black text-stone-100 first:pt-0' : 'pt-3 text-lg font-bold text-amber-200'}>{renderInline(block.text)}</Tag>
            }
            if (block.type === 'list') return <ul key={index} className="list-disc space-y-2 pl-6 leading-7">{block.items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item)}</li>)}</ul>
            return <p key={index} className="leading-7">{renderInline(block.text)}</p>
          })}
        </article>
      )}
    </section>
  )
}
