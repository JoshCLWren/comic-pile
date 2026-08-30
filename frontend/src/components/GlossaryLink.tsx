import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'

interface GlossaryLinkProps {
  /**
   * Anchor id of the definition card on the canonical /glossary page
   * (for example `crossover`, `lane`, or `projection`).
   */
  id: string
  children: ReactNode
}

/**
 * Inline cross-link to a definition on the canonical glossary page.
 *
 * Surfaces that use a reader-facing term (planner header, crossover empty
 * state, projection modal, Roll dice controls) render the term through this
 * component so a reader can jump straight to the explanation (issue #1642).
 */
export default function GlossaryLink({ id, children }: GlossaryLinkProps) {
  return (
    <Link
      to={`/glossary#${id}`}
      className="font-bold text-amber-400 underline underline-offset-2 hover:text-amber-300"
    >
      {children}
    </Link>
  )
}