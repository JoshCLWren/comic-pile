import { useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { Link } from 'react-router-dom'
import { useDependencyGroups } from '../../../hooks/useDependencyGroups'
import { useRollBootstrap } from '../../../hooks/useRollBootstrap'
import { CrossoverTags } from '../components/CrossoverTags'
import type { DependencyGroupSummary } from '../../../services/api-dependency-groups'
import type { Issue } from '../../../services/api-issues'
import { fetchAllIssues } from '../services/api-issues'
import { getApiErrorDetail } from '../utils/apiError'
import type { PositionedIssue } from '../types'

interface CrossoverDetailPageProps {
  groups: DependencyGroupSummary[]
  threadId: number | null
}

export default function CrossoverDetailPage() {
  const { group } = useParams<{ group: string }>()
  const groupId = parseInt(groups, 10)
  const [members, setMembers] = useState<PositionedIssue[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [thread, setThread] = useState<Issue | null>(null)
  const navigate = useNavigate()

  const { groups: dependencyGroups, isLoading: groupsLoading, error: groupsError } = useDependencyGroups(groupId)
  const { data: bootstrap, isPending: isBootstrapLoading, error: bootstrapError } = useRollBootstrap()

  const loadMembers = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const thread = await fetchAllIssues(groupId)
      setThread(thread[0] || null)
      setMembers(thread)
    } catch (err) {
      setError(getApiErrorDetail(err))
    } finally {
      setIsLoading(false)
    }
  }, [groupId, navigate])

  useEffect(() => {
    loadMembers()
  }, [loadMembers])

  if (isLoading) {
    return (
      <div className="p-6">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-bold text-stone-100">Crossover Detail</h1>
          <Link to="/crossovers" className="text-sm text-stone-400">
            ← Back to Crossovers
          </Link>
        </div>
        <div className="text-center text-stone-400">
          <div className="flex items-center gap-2">
            <div className="text-sm font-semibold text-stone-500">Loading members…</div>
            <div className="text-sm text-stone-400">Loading crossover data</div>
          </div>
        </div>
      </div>
    )
  }

  if (groupsError) {
    return (
      <div className="p-6">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-bold text-stone-100">Crossover Detail</h1>
          <Link to="/crossovers" className="text-sm text-stone-400">
            ← Back to Crossovers
          </Link>
        </div>
        <div className="text-center text-red-500">
          <p className="text-lg font-medium">Error loading crossover data</p>
          <p className="mt-1 text-sm">{groupsError}</p>
        </div>
      </div>
    )
  )

  return (
    <div className="space-y-6 md:space-y-8 px-4">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-stone-100">Crossover Detail</h1>
        <Link to="/crossovers" className="text-sm text-stone-400">
          ← Back to Crossovers
        </Link>
      </div>

      <div className="flex justify-between items-center">
        <div className="text-sm text-stone-500">
          <span className="font-bold">{groupId}</span> – {dependencyGroups.find(g => g.id === groupId)?.name || 'Unknown'} 
        </div>
        <div className="text-sm text-stone-400">
          Members: {members.length}
        </div>
      </div>

      {isError && (
        <div className="p-6 border border-red-300 bg-red-50">
          <div className="flex justify-between items-center">
            <h2 className="text-xl font-bold text-red-600">Error Loading Data</h2>
          </div>
          <div className="mt-2 text-sm text-red-600">{error}</div>
        </div>
      )

      <div className="flex justify-between items-center">
        <div className="text-sm text-stone-500">
          Reading Order:
        </div>
        <div className="text-sm text-stone-400">
          {isLoading ? 'Loading...' : members.length > 0 ? 'Loaded' : 'No members'}
        </div>
      </div>

      <div className="flex justify-between items-center">
        <div className="text-sm text-stone-500">
          Progress:
        </div>
        <div className="text-sm text-stone-400">
          {isLoading ? 'Loading...' : 'Complete'}
        </div>
      </div>

      <div className="flex justify-between items-center">
        <div className="text-sm text-stone-500">
          Roles:
        </div>
        <div className="text-sm text-stone-400">
          {isLoading ? 'Loading...' : 'Varies by member'}
        </div>
      </div>

      <div className="flex justify-between items-center">
        <div className="text-sm text-stone-500">
          Status:
        </div>
        <div className="text-sm text-stone-400">
          {isLoading ? 'Loading...' : 'Active'}
        </div>
      </div>

      <div className="flex justify-between items-center">
        <div className="text-sm text-stone-500">
          Source:
        </div>
        <div className="text-sm text-stone-400">
          {isLoading ? 'Loading...' : 'Community-defined'}
        </div>
      </div>

      <div className="flex justify-between items-center">
        <div className="text-sm text-stone-500">
          Actions:
        </div>
        <div className="text-sm text-stone-400">
          {isLoading ? 'Loading...' : 'View/edit reading plan'}
        </div>
      </div>

      {members.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {members.map((member, index) => (
            <div key={member.id} className="rounded-lg border border-stone-700 bg-stone-900/50 p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-stone-300">
                  {member.position > 0 ? `${member.position}. ` : ''}
                </span>
                <span className="text-sm text-stone-300">
                  {member.issue_id !== null ? (
                    <Link 
                      href={`/issues/${member.issue_id}`} 
                      className="text-amber-400 hover:text-amber-500"
                    >
                      Issue {member.issue_id}
                    </Link>
                  ) : (
                    <span>Thread {member.thread_id}</span>
                  )}
                </span>
              </div>
              <div className="mt-1 text-[9px] text-stone-500">
                {member.notes ? member.notes : 'No notes'}
              </div>
            </div>
          ))}
        </div>
      )

      {error && (
        <div className="p-6 border border-red-300 bg-red-50">
          <div className="flex justify-between items-center">
            <h2 className="text-xl font-bold text-red-600">Error Loading Data</h2>
          </div>
          <div className="mt-2 text-sm text-red-600">{error}</div>
        </div>
      )}
    </div>
  )
}