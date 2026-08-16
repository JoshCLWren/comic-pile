import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const queuePagePath = resolve(__dirname, '../pages/QueuePage/QueuePage.tsx')
const source = readFileSync(queuePagePath, 'utf-8')

describe('QueuePage composition boundaries', () => {
  it('does not own inline modal JSX or collection compatibility branches', () => {
    // After decomposition the page must not embed raw create/edit/reactivate
    // modal markup. Composing the QueueModals module is the only entry point.
    expect(source).not.toMatch(/<Modal[^>]*isOpen=\{isCreateOpen\}/)
    expect(source).not.toMatch(/<Modal[^>]*isOpen=\{isEditOpen\}/)
    expect(source).not.toMatch(/<Modal[^>]*isOpen=\{isReactivateOpen\}/)
    expect(source).not.toMatch(/<Modal[^>]*isOpen=\{isDependencyBuilderOpen\}/)
    expect(source).not.toMatch(/<DependencyBuilder/)
    expect(source).not.toMatch(/<MigrationDialog/)
    expect(source).not.toMatch(/<PositionSlider/)
    expect(source).not.toMatch(/(?:const |let |useState\(.*)\s*issuePreview\b/)
    expect(source).not.toMatch(/(?:const |let |useState\(.*)\s*issueParseError\b/)
    expect(source).not.toMatch(/(?:const |let |useState\(.*)\s*createForm\b/)
    expect(source).not.toMatch(/(?:const |let |useState\(.*)\s*editForm\b/)
    expect(source).not.toMatch(/(?:const |let |useState\(.*)\s*reactivateThreadId\b/)
    expect(source).not.toMatch(/(?:const |let |useState\(.*)\s*repositioningThread\b/)
    expect(source).not.toMatch(/setRestoreAction|clearRestoreAction/)
    // The page should not locally define these handlers — they live in
    // focused feature modules or hooks and are referenced via `actions.`
    // or `modals.` rather than declared as top-level consts.
    expect(source).not.toMatch(/const\s+handleDelete\b/)
    expect(source).not.toMatch(/const\s+handleMoveToFront\b/)
    expect(source).not.toMatch(/const\s+handleMoveToBack\b/)
    expect(source).not.toMatch(/const\s+handleShuffle\b/)
    expect(source).not.toMatch(/const\s+handleCreateSubmit\b/)
    expect(source).not.toMatch(/const\s+handleEditSubmit\b/)
    expect(source).not.toMatch(/const\s+handleReactivateSubmit\b/)
    expect(source).not.toMatch(/const\s+handleMigrationComplete\b/)
    expect(source).not.toMatch(/const\s+handleMigrationSkip\b/)
    // Collection-only state should never have lived here and must stay gone.
    expect(source).not.toMatch(/collection|Collection/i)
  })

  it('composes the focused feature modules', () => {
    expect(source).toMatch(/import \{ QueueControls \}/)
    expect(source).toMatch(/import \{ QueueList \}/)
    expect(source).toMatch(/import \{ QueueModals \}/)
    expect(source).toMatch(/import CompletedThreadsSection/)
    expect(source).toMatch(/import \{ useQueueFilters/)
    expect(source).toMatch(/import \{ useQueueThreadActions \}/)
  })

  it('wires bounded Queue pagination into a visible incremental control', () => {
    expect(source).toMatch(/nextPageToken/)
    expect(source).toMatch(/loadMore/)
    expect(source).toMatch(/data-testid="queue-load-more"/)
    expect(source).toMatch(/onClick=\{\(\) => void loadMore\(\)\.catch/)
    expect(source).toMatch(/isPending && threads === null/)
    expect(source).toMatch(/Load more threads/)
  })

  it('stays under 350 lines so it remains a thin route composition', () => {
    const lineCount = source.split('\n').length
    expect(lineCount).toBeLessThan(350)
  })
})