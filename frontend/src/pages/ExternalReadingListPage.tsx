import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { cblApi } from '../services/api-cbl'
// We'll need to import other UI components, but let's start with basic ones.
// We'll use shadcn-ui or similar if available, but for now we'll use basic HTML and Tailwind.

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
    loadSources()
  }, [])

  const loadSources = async () => {
    try {
      const data = await cblApi.listSources()
      setSources(data)
    } catch (err) {
      console.error('Failed to load CBL sources:', err)
      // TODO: show error to user
    }
  }

  // Handle file upload
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null
    setUploadedFile(file)
    if (file) {
      parseUploadedFile(file)
    }
  }

  const parseUploadedFile = async (file: File) => {
    try {
      setIsPreviewLoading(true)
      await cblApi.uploadCblFile(file)
      // Optionally, auto-preview after upload
      // await handlePreview()
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
    try {
      let data: DerivedCrossoverTemplatePreview | null = null
      if (sourceType === 'persisted') {
        if (!selectedSourceId || !selectedListId) {
          throw new Error('Please select a source and list')
        }
        data = await cblApi.previewSourceListsTemplate([selectedListId], targetStoryArcId)
      } else {
        if (!uploadedFile) {
          throw new Error('Please upload a file')
        }
        data = await cblApi.previewUploadedCblTemplate(uploadedFile, targetStoryArcId)
      }
      setPreview(data)
    } catch (err) {
      console.error('Failed to preview template:', err)
      setPreviewError('Failed to generate preview')
    } finally {
      setIsPreviewLoading(false)
    }
  }, [sourceType, selectedSourceId, selectedListId, uploadedFile, targetStoryArcId])

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
        const response = await cblApi.adoptSourceListsTemplate(
          [selectedListId],
          planName,
          'lane-1',
          laneName,
          orderingMode,
          targetStoryArcId
        )
        planId = response.id
      } else {
        if (!uploadedFile) {
          throw new Error('Please upload a file')
        }
        const response = await cblApi.adoptUploadedCblTemplate(
          uploadedFile,
          planName,
          'lane-1',
          laneName,
          orderingMode,
          targetStoryArcId
        )
        planId = response.id
      }
      setAdoptedPlanId(planId)
      // Navigate to the newly created plan
      navigate(`/continuity-plans/${planId}`)
    } catch (err) {
      console.error('Failed to adopt template:', err)
      setAdoptError('Failed to adopt the reading list')
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
              <label className="mb-2 block text-sm font-medium">Source</label>
              <select
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
                <label className="mt-4 mb-2 block text-sm font-medium">List</label>
                <select
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
              <label className="mb-2 block text-sm font-medium">Upload CBL File</label>
              <input
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
        <div className="flex items-center gap-3 mb-4">
          <input
            type="text"
            placeholder="Target Story Arc ID (optional)"
            value={targetStoryArcId ?? ''}
            onChange={(e) => setTargetStoryArcId(e.target.value)}
            className="flex-1 p-2 border rounded"
          />
          <button
            className="px-4 py-2 bg-primary text-primary-foreground rounded"
            onClick={handlePreview}
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
                  {preview.items.map((item, index) => (
                    <li key={item.issue_id} className="p-3 border rounded">
                      <div className="flex justify-between">
                        <div>
                          <strong>#{item.suggested_position}</strong>:
                          Issue {item.issue_id} ({item.role})
                        </div>
                        <span className="text-xs">
                          Confidence: {item.confidence}
                        </span>
                      </div>
                      <p className="text-sm text-muted-foreground mt-1">
                        {item.explanation}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {preview.unresolved && preview.unresolved.length > 0 && (
              <div className="mb-4">
                <h3 className="text-lg font-semibold mb-2">Unresolved Entries ({preview.unresolved.length})</h3>
                <ul className="space-y-2">
                  {preview.unresolved.map((entry, _index) => (
                    <li key={_index} className="p-3 border rounded">
                      <div className="flex justify-between">
                        <div>
                          <strong>Position {entry.position}</strong>:
                          {entry.series_name} #{entry.issue_number}
                        </div>
                        <button
                          className="px-3 py-1 bg-primary text-primary-foreground rounded text-xs"
                          onClick={() => {
                            // TODO: Open a dialog to map this entry to an issue
                            alert('Mapping not implemented yet')
                          }}
                        >
                          Map to Issue
                        </button>
                        <button
                          className="px-3 py-1 bg-secondary text-secondary-foreground rounded text-xs ml-2"
                          onClick={() => {
                            // TODO: Mark as skipped
                            alert('Skip not implemented yet')
                          }}
                        >
                          Skip
                        </button>
                      </div>
                      <p className="text-sm text-muted-foreground mt-1">
                        Reason: {entry.reason}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {preview.conflicts && preview.conflicts.length > 0 && (
              <div className="mb-4">
                <h3 className="text-lg font-semibold mb-2">Conflicts ({preview.conflicts.length})</h3>
                <p className="text-sm text-muted-foreground">
                  These pairs have conflicting order in different sources.
                </p>
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

      {/* Step 3: Reconcile (placeholder) */}
      <section className="border rounded-xl p-4">
        <h2 className="text-lg font-semibold mb-4">Reconcile</h2>
        <p className="text-muted-foreground">
          Reconciliation (mapping unresolved entries to issues or skipping them)
          is not yet implemented in this preview.
        </p>
      </section>

      {/* Step 4: Adoption */}
      <section className="border rounded-xl p-4">
        <h2 className="text-lg font-semibold mb-4">Adopt as Reading Plan</h2>
        <form onSubmit={(e) => {
          e.preventDefault()
          handleAdopt()
        }} className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Plan Name</label>
            <input
              type="text"
              value={planName}
              onChange={(e) => setPlanName(e.target.value)}
              className="w-full p-2 border rounded"
              required
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Lane Name</label>
            <input
              type="text"
              value={laneName}
              onChange={(e) => setLaneName(e.target.value)}
              className="w-full p-2 border rounded"
              required
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Ordering Mode</label>
            <select
              value={orderingMode}
              onChange={(e) => setOrderingMode(e.target.value as any)}
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