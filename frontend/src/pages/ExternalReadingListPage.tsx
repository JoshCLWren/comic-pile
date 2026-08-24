import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { cblApi, type CBLReconciliationDecision, type CBLSourceWithListsResponse, type DerivedCrossoverTemplatePreview } from '../services/api-cbl'

export default function ExternalReadingListPage() {
  const navigate = useNavigate()

  // Step 1: Source selection
  const [sourceType, setSourceType] = useState<'persisted' | 'uploaded'>('persisted')
  const [sources, setSources] = useState<CBLSourceWithListsResponse[]>([])
  const [selectedSourceId, setSelectedSourceId] = useState<number | null>(null)
  const [selectedListId, setSelectedListId] = useState<number | null>(null)
  const [uploadedFile, setUploadedFile] = useState<File | null>(null)

  // Step 2: Preview
  const [preview, setPreview] = useState<DerivedCrossoverTemplatePreview | null>(null)
  const [targetStoryArcId, setTargetStoryArcId] = useState<string | null>(null)
  const [isPreviewLoading, setIsPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)

  // Reconciliation state
  const [reconciliations, setReconciliations] = useState<CBLReconciliationDecision[]>([])
  const [skippedIssueIds, setSkippedIssueIds] = useState<number[]>([])
  const [mapInputs, setMapInputs] = useState<Record<string, string>>({})

  // Step 4: Adoption
  const [planName, setPlanName] = useState('Imported reading list')
  const [laneName, setLaneName] = useState('Reading order')
  const [orderingMode, setOrderingMode] = useState<'strict_sequential' | 'informational'>(
    'informational'
  )
  const [isAdopting, setIsAdopting] = useState(false)
  const [adoptError, setAdoptError] = useState<string | null>(null)
  const [adoptedPlanId, setAdoptedPlanId] = useState<number | null>(null)

  // Load persistent sources on mount
  useEffect(() => {
    void loadSources()
  }, [])

  const loadSources = async () => {
    try {
      const response = await cblApi.listSources()
      // cblApi.listSources returns AxiosResponse; extract data if wrapped, otherwise raw array
      const data = (response as unknown as { data: CBLSourceWithListsResponse[] }).data ?? (response as unknown as CBLSourceWithListsResponse[])
      setSources(Array.isArray(data) ? data : [])
    } catch (err) {
      console.error('Failed to load CBL sources:', err)
    }
  }

  // Handle file upload
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null
    setUploadedFile(file)
    if (file) {
      void parseUploadedFile(file)
    }
  }

  const parseUploadedFile = async (file: File) => {
    try {
      setIsPreviewLoading(true)
      await cblApi.uploadCblFile(file)
    } catch (err) {
      console.error('Failed to upload and parse CBL file:', err)
      setPreviewError('Failed to parse the uploaded file')
    } finally {
      setIsPreviewLoading(false)
    }
  }

  // Handle preview
  const handlePreview = useCallback(async () => {
    setIsPreviewLoading(true)
    setPreviewError(null)
    setReconciliations([])
    setSkippedIssueIds([])
    setMapInputs({})
    try {
      let raw: unknown = null
      if (sourceType === 'persisted') {
        if (!selectedSourceId || !selectedListId) {
          throw new Error('Please select a source and list')
        }
        raw = await cblApi.previewSourceListsTemplate([selectedListId], targetStoryArcId)
      } else {
        if (!uploadedFile) {
          throw new Error('Please upload a file')
        }
        raw = await cblApi.previewUploadedCblTemplate(uploadedFile, targetStoryArcId)
      }
      const data = (raw as { data: DerivedCrossoverTemplatePreview }).data ?? (raw as DerivedCrossoverTemplatePreview)
      setPreview(data)
    } catch (err) {
      console.error('Failed to preview template:', err)
      setPreviewError('Failed to generate preview')
    } finally {
      setIsPreviewLoading(false)
    }
  }, [sourceType, selectedSourceId, selectedListId, uploadedFile, targetStoryArcId])

  const handleToggleSkipItem = (issueId: number) => {
    setSkippedIssueIds((prev) => (prev.includes(issueId) ? prev.filter((id) => id !== issueId) : [...prev, issueId]))
  }

  const handleMapUnresolved = (sourcePath: string, position: number) => {
    const key = `${sourcePath}:${position}`
    const raw = mapInputs[key]?.trim()
    const issueId = raw ? Number.parseInt(raw, 10) : NaN
    if (!Number.isFinite(issueId) || issueId <= 0) {
      setAdoptError('Enter a valid issue ID to map')
      return
    }
    setAdoptError(null)
    setReconciliations((prev) => {
      const filtered = prev.filter((d) => !(d.source_path === sourcePath && d.position === position))
      return [...filtered, { source_path: sourcePath, position, action: 'map', issue_id: issueId }]
    })
  }

  const handleSkipUnresolved = (sourcePath: string, position: number) => {
    setAdoptError(null)
    setReconciliations((prev) => {
      const filtered = prev.filter((d) => !(d.source_path === sourcePath && d.position === position))
      return [...filtered, { source_path: sourcePath, position, action: 'skip' }]
    })
  }

  const unresolvedDecisionFor = (sourcePath: string, position: number) =>
    reconciliations.find((d) => d.source_path === sourcePath && d.position === position)

  // Handle adoption
  const handleAdopt = useCallback(async () => {
    setIsAdopting(true)
    setAdoptError(null)
    try {
      let planId: number | null = null
      if (sourceType === 'persisted') {
        if (!selectedSourceId || !selectedListId) {
          throw new Error('Please select a source and list')
        }
        if (!preview) {
          throw new Error('Please generate a preview first')
        }
        const raw = await cblApi.adoptSourceListsTemplate(
          [selectedListId],
          planName,
          'lane-1',
          laneName,
          orderingMode,
          targetStoryArcId,
          reconciliations,
          skippedIssueIds,
        )
        planId = raw.id
      } else {
        if (!uploadedFile) {
          throw new Error('Please upload a file')
        }
        const raw = await cblApi.adoptUploadedCblTemplate(
          uploadedFile,
          planName,
          'lane-1',
          laneName,
          orderingMode,
          targetStoryArcId,
          reconciliations,
          skippedIssueIds,
        )
        planId = raw.id
      }
      setAdoptedPlanId(planId)
      navigate(`/continuity-plans/${planId}`)
    } catch (err) {
      console.error('Failed to adopt template:', err)
      const message = err instanceof Error && err.message ? err.message : 'Failed to adopt the reading list'
      // Surface API detail if available
      const axiosDetail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      if (axiosDetail && typeof axiosDetail === 'object' && axiosDetail !== null && 'code' in axiosDetail) {
        setAdoptError(String((axiosDetail as { code: string }).code))
      } else if (typeof axiosDetail === 'string') {
        setAdoptError(axiosDetail)
      } else {
        setAdoptError(message)
      }
    } finally {
      setIsAdopting(false)
    }
  }, [
    sourceType,
    selectedSourceId,
    selectedListId,
    uploadedFile,
    preview,
    planName,
    laneName,
    orderingMode,
    targetStoryArcId,
    reconciliations,
    skippedIssueIds,
    navigate
  ])

  // Render the page
  return (
    <div className="space-y-6">
      <header className="flex flex-col items-center gap-2">
        <h1 className="text-2xl font-bold">External Reading List</h1>
        <p className="text-sm text-muted-foreground">
          Browse, upload, preview, and adopt external reading lists.
        </p>
      </header>

      {/* Step 1: Source Selection */}
      <section className="border rounded-xl p-4">
        <h2 className="text-lg font-semibold mb-4">Select Source</h2>
        <div className="flex gap-4">
          <button
            className={`flex-1 px-4 py-2 rounded ${
              sourceType === 'persisted' ? 'bg-primary text-primary-foreground' : 'bg-muted'
            }`}
            onClick={() => setSourceType('persisted')}
          >
            Persistent Lists
          </button>
          <button
            className={`flex-1 px-4 py-2 rounded ${
              sourceType === 'uploaded' ? 'bg-primary text-primary-foreground' : 'bg-muted'
            }`}
            onClick={() => setSourceType('uploaded')}
          >
            Upload File
          </button>
        </div>

        {sourceType === 'persisted' ? (
          <>
            <div className="mt-4">
              <label className="mb-2 block text-sm font-medium" htmlFor="cbl-source-select">Source</label>
              <select
                id="cbl-source-select"
                className="w-full p-2 border rounded"
                value={selectedSourceId ?? ''}
                onChange={(e) => {
                  const id = e.target.value ? parseInt(e.target.value, 10) : null
                  setSelectedSourceId(id)
                  setSelectedListId(null) // Reset list selection when source changes
                }}
              >
                <option value="">Select a source</option>
                {sources.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.repository}
                  </option>
                ))}
              </select>
            </div>

            {selectedSourceId !== null && (
              <>
                <label className="mt-4 mb-2 block text-sm font-medium" htmlFor="cbl-list-select">List</label>
                <select
                  id="cbl-list-select"
                  className="w-full p-2 border rounded"
                  value={selectedListId ?? ''}
                  onChange={(e) => {
                    const id = e.target.value ? parseInt(e.target.value, 10) : null
                    setSelectedListId(id)
                  }}
                >
                  <option value="">Select a list</option>
                  {sources
                    .find((s) => s.id === selectedSourceId)
                    ?.lists.map((list) => (
                      <option key={list.id} value={list.id}>
                        {list.name}
                      </option>
                    ))}
                </select>
              </>
            )}
          </>
        ) : (
          <>
            <div className="mt-4">
              <label className="mb-2 block text-sm font-medium" htmlFor="cbl-upload">Upload CBL File</label>
              <input
                id="cbl-upload"
                type="file"
                accept=".cbl"
                className="w-full p-2 border rounded"
                onChange={handleFileChange}
              />
              {uploadedFile && (
                <p className="mt-2 text-sm text-muted-foreground">
                  Selected file: {uploadedFile.name}
                </p>
              )}
            </div>
          </>
        )}
      </section>

      {/* Step 2: Preview */}
      <section className="border rounded-xl p-4">
        <h2 className="text-lg font-semibold mb-4">Preview</h2>
        <p className="text-sm text-muted-foreground mb-3">
          Source order is advisory and preserved independently. No hard continuity rules are created until adoption in strict mode.
        </p>
        <div className="flex items-center gap-3 mb-4">
          <input
            type="text"
            placeholder="Target Story Arc ID (optional)"
            value={targetStoryArcId ?? ''}
            onChange={(e) => setTargetStoryArcId(e.target.value || null)}
            className="flex-1 p-2 border rounded"
          />
          <button
            className="px-4 py-2 bg-primary text-primary-foreground rounded"
            onClick={() => void handlePreview()}
            disabled={isPreviewLoading}
          >
            {isPreviewLoading ? 'Previewing...' : 'Generate Preview'}
          </button>
        </div>

        {previewError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded">
            <p className="text-red-700">{previewError}</p>
          </div>
        )}

        {!isPreviewLoading && preview && (
          <>
            <div className="mb-4">
              <h3 className="text-lg font-semibold mb-2">Template Items ({preview.items.length})</h3>
              {preview.items.length === 0 ? (
                <p className="text-muted-foreground">No items found.</p>
              ) : (
                <ul className="space-y-2">
                  {preview.items.map((item) => {
                    const isSkipped = skippedIssueIds.includes(item.issue_id)
                    return (
                      <li key={item.issue_id} className={`p-3 border rounded ${isSkipped ? 'opacity-50' : ''}`}>
                        <div className="flex justify-between items-center">
                          <div>
                            <strong>#{item.suggested_position}</strong>:
                            Issue {item.issue_id} ({item.role})
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs">
                              Confidence: {item.confidence}
                            </span>
                            <button
                              className={`px-3 py-1 rounded text-xs ${isSkipped ? 'bg-secondary text-secondary-foreground' : 'bg-muted'}`}
                              onClick={() => handleToggleSkipItem(item.issue_id)}
                              aria-label={isSkipped ? `Undo skip Issue ${item.issue_id}` : `Skip Issue ${item.issue_id}`}
                            >
                              {isSkipped ? 'Undo skip' : 'Skip'}
                            </button>
                          </div>
                        </div>
                        <p className="text-sm text-muted-foreground mt-1">
                          {item.explanation}
                        </p>
                        {item.source_paths.length > 0 && (
                          <p className="text-xs text-muted-foreground mt-1">Source: {item.source_paths.join(', ')}</p>
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>

            {preview.unresolved && preview.unresolved.length > 0 && (
              <div className="mb-4">
                <h3 className="text-lg font-semibold mb-2">Unresolved Entries ({preview.unresolved.length})</h3>
                <p className="text-sm text-muted-foreground mb-2">Each unresolved entry must be mapped to an existing issue or explicitly skipped before adoption.</p>
                <ul className="space-y-2">
                  {preview.unresolved.map((entry) => {
                    const key = `${entry.source_path}:${entry.position}`
                    const decision = unresolvedDecisionFor(entry.source_path, entry.position)
                    return (
                      <li key={key} className="p-3 border rounded">
                        <div className="flex justify-between items-start gap-2">
                          <div className="flex-1">
                            <div>
                              <strong>Position {entry.position}</strong>:
                              {entry.series_name} #{entry.issue_number}
                            </div>
                            <p className="text-sm text-muted-foreground mt-1">
                              Reason: {entry.reason}
                            </p>
                            <p className="text-xs text-muted-foreground mt-1">Source: {entry.source_path}</p>
                            {decision && (
                              <p className="text-xs font-medium mt-1">
                                Decision: {decision.action === 'map' ? `Map to Issue ${decision.issue_id}` : 'Skipped'}
                              </p>
                            )}
                          </div>
                          <div className="flex flex-col gap-2 min-w-[220px]">
                            <div className="flex gap-2">
                              <input
                                type="number"
                                placeholder="Issue ID"
                                value={mapInputs[key] ?? ''}
                                onChange={(e) => setMapInputs((prev) => ({ ...prev, [key]: e.target.value }))}
                                className="flex-1 p-1 border rounded text-sm"
                                aria-label={`Map issue ID for ${entry.series_name} ${entry.issue_number}`}
                              />
                              <button
                                className="px-3 py-1 bg-primary text-primary-foreground rounded text-xs"
                                onClick={() => handleMapUnresolved(entry.source_path, entry.position)}
                              >
                                Map to Issue
                              </button>
                            </div>
                            <button
                              className={`px-3 py-1 rounded text-xs ${decision?.action === 'skip' ? 'bg-secondary' : 'bg-muted'}`}
                              onClick={() => handleSkipUnresolved(entry.source_path, entry.position)}
                            >
                              Skip
                            </button>
                          </div>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}

            {preview.conflicts && preview.conflicts.length > 0 && (
              <div className="mb-4">
                <h3 className="text-lg font-semibold mb-2">Conflicts ({preview.conflicts.length})</h3>
                <p className="text-sm text-muted-foreground">
                  These pairs have conflicting order in different sources. They will become parallel candidates, not hard rules.
                </p>
                <ul className="space-y-1 mt-2">
                  {preview.conflicts.map((c) => (
                    <li key={`${c.first_issue_id}-${c.second_issue_id}`} className="text-sm">
                      Issue {c.first_issue_id} vs {c.second_issue_id} — sources: {c.source_paths.join(', ')}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {preview.parallel_candidates && preview.parallel_candidates.length > 0 && (
              <div className="mb-4">
                <h3 className="text-lg font-semibold mb-2">Parallel Suggestions ({preview.parallel_candidates.length})</h3>
                <p className="text-sm text-muted-foreground">Advisory parallel branches where source order disagrees.</p>
              </div>
            )}

            {preview.intersections && preview.intersections.length > 0 && (
              <div className="mb-4">
                <h3 className="text-lg font-semibold mb-2">Intersections ({preview.intersections.length})</h3>
                <p className="text-sm text-muted-foreground">
                  Consistent cross-thread ordering observations.
                </p>
              </div>
            )}
          </>
        )}
      </section>

      {/* Step 4: Adoption */}
      <section className="border rounded-xl p-4">
        <h2 className="text-lg font-semibold mb-4">Adopt as Reading Plan</h2>
        <p className="text-sm text-muted-foreground mb-3">Adoption defaults to informational mode with zero hard rules. Source evidence is preserved independently.</p>
        <form onSubmit={(e) => {
          e.preventDefault()
          void handleAdopt()
        }} className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="plan-name">Plan Name</label>
            <input
              id="plan-name"
              type="text"
              value={planName}
              onChange={(e) => setPlanName(e.target.value)}
              className="w-full p-2 border rounded"
              required
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="lane-name">Lane Name</label>
            <input
              id="lane-name"
              type="text"
              value={laneName}
              onChange={(e) => setLaneName(e.target.value)}
              className="w-full p-2 border rounded"
              required
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="ordering-mode">Ordering Mode</label>
            <select
              id="ordering-mode"
              value={orderingMode}
              onChange={(e) => setOrderingMode(e.target.value as 'strict_sequential' | 'informational')}
              className="w-full p-2 border rounded"
            >
              <option value="informational">Informational (no hard rules)</option>
              <option value="strict_sequential">Strict Sequential (hard rules)</option>
            </select>
          </div>
          <div className="flex justify-end">
            <button
              type="submit"
              className="px-4 py-2 bg-primary text-primary-foreground rounded disabled:opacity-50"
              disabled={isAdopting}
            >
              {isAdopting ? 'Adopting...' : 'Adopt Plan'}
            </button>
          </div>
        </form>

        {adoptError && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded">
            <p className="text-red-700">{adoptError}</p>
          </div>
        )}

        {adoptedPlanId !== null && (
          <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded">
            <p className="text-green-700">
              Successfully adopted plan ID: {adoptedPlanId}
            </p>
          </div>
        )}
      </section>
    </div>
  )
}
