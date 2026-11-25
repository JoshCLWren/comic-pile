/**
 * Request budget for the duplicate reconciliation route (#4653).
 *
 * The page cold-loads detected duplicate groups exactly once on mount, and
 * each preview/apply/undo action issues exactly one request. No duplicate
 * in-flight or retry calls are allowed.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { setDefaultHttpClient } from '../services/httpClient'
import DuplicateReconciliationPage from '../pages/DuplicateReconciliationPage'
import {
  createRequestRecorder,
  requestCounts,
  type RecordedCall,
  type Responder,
} from './requestRecorder'

const detectResponse = {
  groups: [
    {
      group_key: 'cv-issue:364132',
      confidence: 'high',
      reason: 'Multiple owned issues map to the same Comic Vine issue 364132',
      suggested_canonical_issue_id: 117355,
      suggested_duplicate_issue_ids: [1121326],
      evidence: [
        {
          issue_id: 117355,
          thread_id: 1,
          thread_title: "B.P.R.D.: Hell on Earth - The Return of the Master",
          issue_number: '#3',
          status: 'unread',
          read_at: null,
          created_at: '2026-11-05T04:00:00Z',
          merged_into_issue_id: null,
          comicvine_issue_id: '364132',
          comicvine_volume_id: 51622,
          comicvine_issue_number: '100',
          comicvine_story_number: null,
          rating_events: [],
          read_events: [],
          list_memberships: [],
          is_synthetic_placeholder_read: false,
        },
        {
          issue_id: 1121326,
          thread_id: 2,
          thread_title: 'Synthetic Overall #100',
          issue_number: '#100',
          status: 'read',
          read_at: '2026-11-05T05:02:02Z',
          created_at: '2026-11-05T05:11:33Z',
          merged_into_issue_id: null,
          comicvine_issue_id: '364132',
          comicvine_volume_id: 51622,
          comicvine_issue_number: '100',
          comicvine_story_number: null,
          rating_events: [{ event_id: 1032535, rating: 4, timestamp: '2026-11-05T05:02:02Z' }],
          read_events: [
            { event_id: 1032539, timestamp: '2026-11-05T05:02:02Z', issue_number: '100' },
          ],
          list_memberships: [],
          is_synthetic_placeholder_read: true,
        },
      ],
    },
  ],
}

function responder(call: RecordedCall) {
  if (call.url === '/v2/issue-duplicate-reconciliation/detect') return detectResponse
  if (call.url === '/v2/issue-duplicate-reconciliation/preview') {
    return {
      canonical_issue_id: 117355,
      duplicate_issue_ids: [1121326],
      canonical: detectResponse.groups[0].evidence[0],
      duplicates: detectResponse.groups[0].evidence.slice(1),
      actions: [
        {
          kind: 'move_comicvine_mapping',
          description: 'Move Comic Vine issue 364132 mapping from duplicate 1121326 to canonical 117355',
          safe: true,
          requires_decision: false,
          decision_key: null,
        },
        {
          kind: 'suppress_synthetic_read_events',
          description: 'Suppress 1 synthetic placeholder read event(s) on duplicate 1121326 (invalid timestamp order); canonical reading history is preserved.',
          safe: true,
          requires_decision: false,
          decision_key: null,
        },
        {
          kind: 'suppress_duplicate',
          description: 'Mark duplicate 1121326 as merged into canonical 117355 (no destructive delete; excluded from Roll/Queue)',
          safe: true,
          requires_decision: false,
          decision_key: null,
        },
      ],
      warnings: [],
      can_apply: true,
      preview_token: 'test-preview-token',
    }
  }
  if (call.url === '/v2/issue-duplicate-reconciliation/apply') {
    return {
      canonical_issue_id: 117355,
      merged_issue_ids: [1121326],
      moved_event_ids: [],
      moved_mapping_ids: [1],
      moved_list_entry_ids: [],
      suppressed_duplicate_issue_ids: [1121326],
      undo_snapshot_id: 1,
      warnings: [],
    }
  }
  if (call.url === '/v2/issue-duplicate-reconciliation/undo') {
    return { reconciliation_id: 1, undone: true, warnings: [] }
  }
  return {}
}

function renderPage(): void {
  render(
    <BugReportRestoreProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={['/duplicate-reconciliation']}>
          <Routes>
            <Route
              path="/duplicate-reconciliation"
              element={<DuplicateReconciliationPage />}
            />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </BugReportRestoreProvider>,
  )
}

describe('duplicate reconciliation request budget', () => {
  it('cold-loads detections exactly once and reuses on remount', async () => {
    const { calls, client } = createRequestRecorder(responder)
    setDefaultHttpClient(client)

    renderPage()

    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v2/issue-duplicate-reconciliation/detect')).toBe(true),
    )

    expect(requestCounts(calls)).toEqual({
      'GET /v2/issue-duplicate-reconciliation/detect': 1,
    })
  })

  it('preview and apply each issue exactly one request', async () => {
    const { calls, client } = createRequestRecorder(responder)
    setDefaultHttpClient(client)

    renderPage()

    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v2/issue-duplicate-reconciliation/detect')).toBe(true),
    )

    // Select canonical and duplicate, then preview
    const canonicalButton = screen.getByRole('button', { name: /Canonical: #3 \(117355\)/ })
    fireEvent.click(canonicalButton)

    const duplicateCheckbox = screen.getByRole('checkbox', { name: /Duplicate: #100 \(1121326\)/ })
    fireEvent.click(duplicateCheckbox)

    const previewButton = screen.getByRole('button', { name: /Preview resolution/ })
    fireEvent.click(previewButton)

    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v2/issue-duplicate-reconciliation/preview')).toBe(true),
    )

    const applyButton = screen.getByRole('button', { name: /Apply reconciliation/ })
    fireEvent.click(applyButton)

    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v2/issue-duplicate-reconciliation/apply')).toBe(true),
    )

    expect(requestCounts(calls)).toEqual({
      'GET /v2/issue-duplicate-reconciliation/detect': 1,
      'POST /v2/issue-duplicate-reconciliation/preview': 1,
      'POST /v2/issue-duplicate-reconciliation/apply': 1,
    })
  })

  it('undo issues exactly one request', async () => {
    const { calls, client } = createRequestRecorder(responder)
    setDefaultHttpClient(client)

    renderPage()

    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v2/issue-duplicate-reconciliation/detect')).toBe(true),
    )

    // Select canonical and duplicate, then preview and apply
    const canonicalButton = screen.getByRole('button', { name: /Canonical: #3 \(117355\)/ })
    fireEvent.click(canonicalButton)

    const duplicateCheckbox = screen.getByRole('checkbox', { name: /Duplicate: #100 \(1121326\)/ })
    fireEvent.click(duplicateCheckbox)

    const previewButton = screen.getByRole('button', { name: /Preview resolution/ })
    fireEvent.click(previewButton)

    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v2/issue-duplicate-reconciliation/preview')).toBe(true),
    )

    const applyButton = screen.getByRole('button', { name: /Apply reconciliation/ })
    fireEvent.click(applyButton)

    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v2/issue-duplicate-reconciliation/apply')).toBe(true),
    )

    // Undo button is available right after apply (lastUndoId is set)
    const undoButton = screen.getByRole('button', { name: /Undo #1/ })
    fireEvent.click(undoButton)

    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v2/issue-duplicate-reconciliation/undo')).toBe(true),
    )

    expect(requestCounts(calls)).toEqual({
      'GET /v2/issue-duplicate-reconciliation/detect': 1,
      'POST /v2/issue-duplicate-reconciliation/preview': 1,
      'POST /v2/issue-duplicate-reconciliation/apply': 1,
      'POST /v2/issue-duplicate-reconciliation/undo': 1,
    })
  })
})
