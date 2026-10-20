import { createElement, type FormEvent, type ReactNode } from 'react'
import { act, renderHook } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { validateIssueRangeForStaging } from '../utils/issueParser'
import { useQueueModals } from '../pages/QueuePage/useQueueModals'
import { DEFAULT_CREATE_STATE } from '../pages/QueuePage/types'
import { BugReportRestoreContext } from '../contexts/BugReportRestoreContextValue'

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    migrateThread: vi.fn(async () => undefined),
    create: vi.fn(async () => ({ issues: [] })),
    bulkMarkRead: vi.fn(async () => undefined),
  },
}))

describe('#3631 Add Series save enforcement (focus)', () => {
  it('rejects unparseable token "abc" so save cannot proceed (#3631)', () => {
    const result = validateIssueRangeForStaging('abc')
    expect(result.valid).toBe(false)
    expect(result.invalidTokens).toContain('abc')
  })

  it('accepts valid range "1-3"', () => {
    const result = validateIssueRangeForStaging('1-3')
    expect(result.valid).toBe(true)
    expect(result.issues).toEqual(['1', '2', '3'])
  })

  it('accepts recognized literal "Annual 1"', () => {
    const result = validateIssueRangeForStaging('Annual 1')
    expect(result.valid).toBe(true)
  })
})

/**
 * Save-path regression coverage for #3631. The tests above only exercise the
 * validator in isolation; these exercise `handleCreateSubmit` itself, which is
 * the code that decides whether `submitCreate` runs.
 */
describe('#3631 Add Series save enforcement (handleCreateSubmit)', () => {
  let alertSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    alertSpy = vi.fn()
    vi.stubGlobal('alert', alertSpy)
  })

  function makeWrapper() {
    return function Wrapper({ children }: { children: ReactNode }) {
      return createElement(
        MemoryRouter,
        null,
        createElement(
          BugReportRestoreContext.Provider,
          {
            value: {
              setRestoreAction: vi.fn(),
              clearRestoreAction: vi.fn(),
              restoreLastView: vi.fn(),
            },
          },
          children,
        ),
      )
    }
  }

  function setup() {
    const submitCreate = vi.fn(async () => ({ id: 1 }))
    const params = {
      threads: [],
      onCreated: vi.fn(async () => undefined),
      onUpdated: vi.fn(async () => undefined),
      onReactivated: vi.fn(async () => undefined),
      refetchSession: vi.fn(async () => undefined),
      submitCreate,
      submitEdit: vi.fn(),
      submitReactivate: vi.fn(),
      isPendingCreate: false,
      isPendingEdit: false,
      showRollNudge: false,
      onDismissRollNudge: vi.fn(),
      onRollNudgeNavigate: vi.fn(),
    }
    const rendered = renderHook(() => useQueueModals(params), { wrapper: makeWrapper() })
    return { ...rendered, submitCreate }
  }

  async function submitIssues(rendered: ReturnType<typeof setup>, issues: string) {
    act(() => {
      rendered.result.current.setCreateForm({ ...DEFAULT_CREATE_STATE, issues })
    })
    const event = { preventDefault: vi.fn() } as unknown as FormEvent
    await act(async () => {
      await rendered.result.current.handleCreateSubmit(event)
    })
  }

  it('blocks save for unparseable garbage so no phantom issue is created (#3631)', async () => {
    const rendered = setup()
    await submitIssues(rendered, 'abc')

    expect(rendered.submitCreate).not.toHaveBeenCalled()
    expect(alertSpy).toHaveBeenCalledWith(
      expect.stringContaining("'abc' is not a valid issue number"),
    )
  })

  it('blocks save when a valid range is mixed with garbage (#3631)', async () => {
    const rendered = setup()
    await submitIssues(rendered, '1-3, abc')

    expect(rendered.submitCreate).not.toHaveBeenCalled()
    expect(alertSpy).toHaveBeenCalled()
  })

  it('still saves a fully valid range (#3631)', async () => {
    const rendered = setup()
    await submitIssues(rendered, '1-3')

    expect(rendered.submitCreate).toHaveBeenCalledTimes(1)
    expect(rendered.submitCreate).toHaveBeenCalledWith(
      expect.objectContaining({ issues_remaining: 3 }),
    )
    expect(alertSpy).not.toHaveBeenCalled()
  })

  it('still saves numbered labels that carry an issue number, despite preview warnings (#3631)', async () => {
    for (const issues of ['2b', '1.5', '1-Annual']) {
      const rendered = setup()
      await submitIssues(rendered, issues)

      expect(rendered.submitCreate, `${issues} should still save`).toHaveBeenCalledTimes(1)
    }
  })
})
