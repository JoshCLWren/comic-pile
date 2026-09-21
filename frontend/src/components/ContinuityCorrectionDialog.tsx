import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import Modal from './Modal';
import {
  dependencyGroupsApi,
  type DependencyGroup,
  type DependencyGroupMember,
  type DependencyGroupMemberTarget,
} from '../services/api-dependency-groups';
import { threadsApi } from '../services/api-threads';
import { getApiErrorDetail } from '../utils/apiError';
import type { ConnectedThreadInfo, Thread } from '../types';
import { queryKeys } from '../query/queryKeys';

export interface ContinuityCorrectionGroupsApi {
  list: () => Promise<DependencyGroup[]>;
  create: (name: string) => Promise<DependencyGroup>;
  addMember: (
    groupId: number,
    target: DependencyGroupMemberTarget,
  ) => Promise<DependencyGroupMember>;
}

export interface ContinuityCorrectionThreadsApi {
  get: (id: number) => Promise<Thread>;
}

export interface ContinuityCorrectionDialogProps {
  isOpen: boolean;
  threadId: number;
  issueId: number | null | undefined;
  issueNumber: string | null | undefined;
  threadTitle: string;
  connectedThreads: ConnectedThreadInfo[];
  onClose: () => void;
  onSuccess: () => void;
  /** Injectable reading-order groups API; defaults to the production dependency groups service. */
  groupsApi?: ContinuityCorrectionGroupsApi;
  /** Injectable thread API; defaults to the production threads service. */
  threadsApi?: ContinuityCorrectionThreadsApi;
}

type CrossoverMode = 'none' | 'existing' | 'new';

interface ResolvedThread {
  id: number;
  title: string;
}

export default function ContinuityCorrectionDialog({
  isOpen,
  threadId,
  issueId,
  issueNumber,
  threadTitle,
  connectedThreads,
  onClose,
  onSuccess,
  groupsApi = dependencyGroupsApi,
  threadsApi: threadsService = threadsApi,
}: ContinuityCorrectionDialogProps) {
  const [mode, setMode] = useState<CrossoverMode>('none');
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [newName, setNewName] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  // React Query for reading-order groups
  const {
    data: groupsData,
    isPending: isLoadingGroups,
    error: groupsError,
  } = useQuery({
    queryKey: queryKeys.continuityCorrection.groups(),
    queryFn: () => groupsApi.list(),
    retry: false,
  });

  // React Query for resolved connected threads
  const {
    data: resolvedConnectedData,
    isPending: isLoadingConnected,
    error: connectedError,
  } = useQuery({
    queryKey: ['continuityConnectedThreads', threadId],
    queryFn: async () => {
      if (connectedThreads.length === 0) return [];
      const resolved = await Promise.all(
        connectedThreads.map(async (connected) => {
          try {
            const thread: Thread = await threadsService.get(connected.thread_id);
            return { id: thread.id, title: thread.title };
          } catch {
            return { id: connected.thread_id, title: connected.title };
          }
        })
      );
      return resolved.filter((entry): entry is ResolvedThread => entry !== null);
    },
    retry: false,
  });

  const isResolvingConnected = connectedThreads.length > 0 && (isLoadingConnected || resolvedConnectedData === undefined);

  const canSaveCurrentIssue = issueId != null;
  const canSaveConnected = (resolvedConnectedData?.length ?? 0) > 0;
  const hasSomethingToAdd = mode !== 'none' && (canSaveCurrentIssue || canSaveConnected);

  async function handleSaveMemberships() {
    setError(null);
    setResult(null);

    if (mode === 'existing' && selectedGroupId == null) {
      setError('Select an existing crossover.');
      return;
    }
    const normalizedName = newName.trim();
    if (mode === 'new' && !normalizedName) {
      setError('Enter a crossover name.');
      return;
    }

    setIsSaving(true);
    const addedLabels: string[] = [];
    let createdGroup: DependencyGroup | null = null;

    try {
      let targetGroup: DependencyGroup | undefined;
      if (mode === 'new') {
        const created = await groupsApi.create(normalizedName);
        targetGroup = created;
        createdGroup = created;
      } else {
        targetGroup = groupsData?.find((candidate) => candidate.id === selectedGroupId);
      }

      if (!targetGroup) {
        setError('Select a crossover before saving.');
        return;
      }

      if (canSaveCurrentIssue) {
        await groupsApi.addMember(targetGroup.id, { issue_id: issueId as number });
        addedLabels.push(`issue ${issueNumber ?? '?'}`);
      }
      for (const connected of resolvedConnectedData ?? []) {
        await groupsApi.addMember(targetGroup.id, { thread_id: connected.id });
        addedLabels.push(connected.title);
      }

      setResult(`${addedLabels.join(', ')} added to ${targetGroup.name}.`);
      onSuccess();
    } catch (saveError: unknown) {
      const detail = getApiErrorDetail(saveError);
      if (createdGroup) {
        setError(`Created ${createdGroup.name}, but membership failed: ${detail}`);
      } else {
        setError(detail);
      }
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      title="Correct Continuity"
      onClose={onClose}
      data-testid="continuity-correction-dialog"
      overlayClassName="bg-black/70 backdrop-blur-sm"
    >
      <section aria-labelledby="continuity-current-heading" className="rounded-2xl border border-white/10 bg-white/[0.04] p-3">
        <h3 id="continuity-current-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
          Current Comic
        </h3>
        <p className="mt-1 text-sm text-stone-200">
          {threadTitle}
          {issueNumber != null ? <span className="text-amber-400"> #{issueNumber}</span> : null}
        </p>
      </section>

      {connectedThreads.length > 0 ? (
        <section aria-labelledby="continuity-connections-heading" className="rounded-2xl border border-blue-800/30 bg-blue-950/15 p-3">
          <h3 id="continuity-connections-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-blue-400">
            Verified connections
          </h3>
          {isResolvingConnected ? (
            <p className="mt-2 text-[11px] text-stone-400" role="status">
              Resolving connected series…
            </p>
          ) : resolvedConnectedData?.length === 0 ? (
            <p className="mt-2 text-[11px] text-stone-400" role="status">
              No connected series found.
            </p>
          ) : (
            <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Connected threads">
              {resolvedConnectedData?.map((connected) => (
                <li
                  key={connected.id}
                  className="rounded-full border border-blue-800/40 bg-blue-900/20 px-2.5 py-1 text-[10px] font-bold text-blue-200"
                >
                  {connected.title}
                </li>
              ))}
            </ul>
          )}
          {!isResolvingConnected && resolvedConnectedData && resolvedConnectedData.length > 0 && (
            <p className="mt-2 text-[10px] font-bold text-stone-500">
              These will be added to the chosen crossover without re-searching.
            </p>
          )}
        </section>
      ) : null}

      <fieldset className="space-y-3" disabled={isSaving}>
        <legend className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">Crossover membership</legend>
        <div className="flex gap-2">
          {(['none', 'existing', 'new'] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setMode(option)}
              className={`flex-1 rounded-lg border py-2 text-[10px] font-black uppercase tracking-wider transition-colors ${
                mode === option
                  ? 'border-amber-600 bg-amber-600/20 text-amber-200'
                  : 'border-white/10 bg-white/5 text-stone-400'
              }`}
              aria-pressed={mode === option}
            >
              {option === 'none' ? 'Skip' : option === 'existing' ? 'Existing' : 'Create New'}
            </button>
          ))}

          {mode === 'existing' ? (
            <label className="block">
              <span className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">Existing crossover</span>
              <select
                value={selectedGroupId ?? ''}
                onChange={(event) => setSelectedGroupId(event.target.value ? Number(event.target.value) : null)}
                className="mt-1 w-full rounded-xl px-3 py-2 text-sm form-control disabled:opacity-50"
                disabled={isLoadingGroups || isSaving}
              >
                <option value="">{isLoadingGroups ? 'Loading crossovers…' : 'Select a crossover'}</option>
                {groupsData?.map((group) => (
                  <option key={group.id} value={group.id}>
                    {group.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          {mode === 'new' ? (
            <label className="block">
              <span className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">Crossover name</span>
              <input
                type="text"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                maxLength={200}
                placeholder="e.g. Ultimate Universe"
                className="mt-1 w-full rounded-xl px-3 py-2 text-sm form-control disabled:opacity-50"
                disabled={isSaving}
              />
            </label>
          ) : null}

          <p className="text-[11px] font-bold text-stone-500">
            {canSaveCurrentIssue
              ? `Adds issue ${issueNumber ?? '?'} to the chosen crossover.`
              : 'No specific issue is available to add.'}
            {canSaveConnected ? ' Connected series will also be added.' : null}
          </p>
        </div>
      </fieldset>

      {(groupsError || connectedError) && (
        <p className="text-[11px] text-rose-300" role="alert">
          {groupsError
            ? getApiErrorDetail(groupsError)
            : getApiErrorDetail(connectedError)}
        </p>
      )}
      {error ? (
        <p className="text-[11px] text-rose-300" role="alert">
          {error}
        </p>
      ) : null}
      {result ? (
        <p className="text-[11px] text-emerald-300" role="status">
          {result}
        </p>
      ) : null}

        <div className="flex gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            className="flex-1 rounded-xl border border-white/10 bg-white/5 py-3 text-xs font-black uppercase tracking-wider text-stone-300 transition hover:bg-white/10 focus:ring-2 focus:ring-amber-500"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSaveMemberships}
            disabled={isSaving || !hasSomethingToAdd}
            className="flex-1 rounded-xl border border-amber-600/50 bg-amber-600/20 py-3 text-xs font-black uppercase tracking-wider text-amber-200 transition hover:bg-amber-600/30 focus:outline-none focus:ring-2 focus:ring-amber-500 disabled:opacity-50"
          >
            {isSaving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </Modal>
  )
}