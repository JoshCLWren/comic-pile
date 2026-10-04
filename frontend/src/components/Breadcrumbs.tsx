import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  BREADCRUMB_STRUCTURED_DATA_SCRIPT_ID,
  removeStructuredDataScript,
  upsertStructuredDataScript,
} from '../seo/structuredData'

export interface BreadcrumbItem {
  /** Visible label; for the last item also the accessible current-page name. */
  label: string
  /** Route for ancestor items. Omit on the current page. */
  to?: string
}

interface BreadcrumbListNode {
  '@context': string
  '@type': 'BreadcrumbList'
  itemListElement: ListItemNode[]
}

interface ListItemNode {
  '@type': 'ListItem'
  position: number
  name: string
  item?: string
}

function buildBreadcrumbList(items: BreadcrumbItem[], origin: string): BreadcrumbListNode {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((item, index) => {
      const node: ListItemNode = {
        '@type': 'ListItem',
        position: index + 1,
        name: item.label,
      }
      if (item.to) {
        node.item = `${origin}${item.to}`
      }
      return node
    }),
  }
}

/**
 * Visible breadcrumb trail plus the matching BreadcrumbList JSON-LD. The
 * schema is generated from the same items as the rendered nav, so the two
 * can never disagree. The last item is the current page: it is not linked
 * and carries `aria-current="page"`.
 */
export default function Breadcrumbs({ items }: { items: BreadcrumbItem[] }) {
  const itemsKey = JSON.stringify(items)

  useEffect(() => {
    const parsed: BreadcrumbItem[] = JSON.parse(itemsKey) as BreadcrumbItem[]
    upsertStructuredDataScript(
      BREADCRUMB_STRUCTURED_DATA_SCRIPT_ID,
      buildBreadcrumbList(parsed, window.location.origin),
    )
    return () => removeStructuredDataScript(BREADCRUMB_STRUCTURED_DATA_SCRIPT_ID)
  }, [itemsKey])

  return (
    <nav aria-label="Breadcrumb" className="mb-1">
      <ol className="flex flex-wrap items-center gap-1 text-xs text-[var(--theme-text-muted)]">
        {items.map((item, index) => {
          const isLast = index === items.length - 1
          return (
            <li key={`${item.to ?? 'current'}-${index}`} className="flex min-w-0 items-center gap-1">
              {index > 0 && (
                <span aria-hidden="true" className="text-[var(--theme-text-dim)]">
                  ›
                </span>
              )}
              {isLast || !item.to ? (
                <span aria-current="page" className="truncate text-[var(--theme-text-dim)]">
                  {item.label}
                </span>
              ) : (
                <Link
                  to={item.to}
                  className="truncate transition-colors hover:text-[var(--theme-text-primary)]"
                >
                  {item.label}
                </Link>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
