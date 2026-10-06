import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const queuePagePath = resolve(__dirname, '../pages/QueuePage/QueuePage.tsx')
const queuePageSource = readFileSync(queuePagePath, 'utf-8')
const queueModalsPath = resolve(__dirname, '../pages/QueuePage/QueueModals.tsx')
const queueModalsSource = readFileSync(queueModalsPath, 'utf-8')

describe('QueuePage composition boundaries', () => {
  it('does not own inline modal JSX or collection compatibility branches', () => {
    // After decomposition the page must not embed raw create/edit/reactivate
    // modal markup. Composing the QueueModals module is the only entry point.
    expect(queuePageSource).not.toMatch(/<Modal[^>]*isOpen=\{isCreateOpen\}/)
    expect(queuePageSource).not.toMatch(/<Modal[^>]*isOpen=\{isEditOpen\}/)
    expect(queuePageSource).not.toMatch(/<Modal[^>]*isOpen=\{isReactivateOpen\}/)
    expect(queuePageSource).not.toMatch(/<Modal[^>]*isOpen=\{isDependencyBuilderOpen\}/)
    expect(queuePageSource).not.toMatch(/<DependencyBuilder/)
    expect(queuePageSource).not.toMatch(/<MigrationDialog/)
    expect(queuePageSource).not.toMatch(/<PositionSlider/)
    expect(queuePageSource).not.toMatch(/(?:const |let |useState\(.*)\s*issuePreview\b/)
    expect(queuePageSource).not.toMatch(/(?:const |let |useState\(.*)\s*issueParseError\b/)
    expect(queuePageSource).not.toMatch(/(?:const |let |useState\(.*)\s*createForm\b/)
    // The Create Series button lives in QueueModals and must be disabled when
    // issueParseError is set, preventing series creation when the issue range
    // is invalid.
    expect(queueModalsSource).toMatch(/disabled=\{isPendingCreate \|\| issueParseError !== null\}/)
    expect(queueModalsSource).not.toMatch(/disabled=\{isPendingCreate\}/)
    expect(queuePageSource).not.toMatch(/(?:const |let |useState\(.*)\s*editForm\b/)
    expect(queuePageSource).not.toMatch(/(?:const |let |useState\(.*)\s*reactivateThreadId\b/)
    expect(queuePageSource).not.toMatch(/(?:const |let |useState\(.*)\s*repositioningThread\b/)
    expect(queuePageSource).not.toMatch(/setRestoreAction|clearRestoreAction/)
    // The page should not locally define these handlers — they live in
    // focused feature modules or hooks and are referenced via `actions.`
    // or `modals.` rather than declared as top-level consts.
    expect(queuePageSource).not.toMatch(/const\s+handleDelete\b/)
    expect(queuePageSource).not.toMatch(/const\s+handleMoveToFront\b/)
    expect(queuePageSource).not.toMatch(/const\s+handleMoveToBack\b/)
    expect(queuePageSource).not.toMatch(/const\s+handleShuffle\b/)
    expect(queuePageSource).not.toMatch(/const\s+handleCreateSubmit\b/)
    expect(queuePageSource).not.toMatch(/const\s+handleEditSubmit\b/)
    expect(queuePageSource).not.toMatch(/const\s+handleReactivateSubmit\b/)
    expect(queuePageSource).not.toMatch(/const\s+handleMigrationComplete\b/)
    expect(queuePageSource).not.toMatch(/const\s+handleMigrationSkip\b/)
    // Collection-only state should never have lived here and must stay gone.
    expect(queuePageSource).not.toMatch(/collection|Collection/i)
  })

  it('composes the focused feature modules', () => {
    expect(queuePageSource).toMatch(/import \{ QueueControls \}/)
    expect(queuePageSource).toMatch(/import \{ QueueList \}/)
    expect(queuePageSource).toMatch(/import \{ QueueModals \}/)
    expect(queuePageSource).toMatch(/import CompletedThreadsSection/)
    expect(queuePageSource).toMatch(/import \{ useQueueFilters/)
    expect(queuePageSource).toMatch(/import \{ useQueueThreadActions \}/)
  })

  it('wires bounded Queue pagination into an infinite scroll control', () => {
    expect(queuePageSource).toMatch(/nextPageToken/)
    expect(queuePageSource).toMatch(/loadMore/)
    expect(queuePageSource).toMatch(/useInfiniteScroll/)
    expect(queuePageSource).toMatch(/isPending && !threads\?\.length/)
    expect(queuePageSource).not.toMatch(/data-testid="queue-load-more"/)
    expect(queuePageSource).not.toMatch(/Load more threads/)
  })

  it('stays under 350 lines so it remains a thin route composition', () => {
    const lineCount = queuePageSource.split('\n').length
    expect(lineCount).toBeLessThan(350)
  })
})
