import { useQuery } from "@tanstack/react-query";
import { sessionApi as defaultSessionApi } from "../services/api-sessions";
import type {
  SessionDetails,
  SessionSnapshotsResponse,
} from "../types";
import { queryKeys } from "../query/queryKeys";

function normalizeQueryError(error: unknown, fallbackMessage: string): Error | null {
  if (error == null) return null;
  if (error instanceof Error) return error;
  return new Error(fallbackMessage);
}

export function useSessionDetails(id: number | string | null | undefined) {
  const { data, isPending, fetchStatus, isError, error, refetch } = useQuery({
    queryKey: id ? queryKeys.session.detail(Number(id)) : [],
    queryFn: () => defaultSessionApi.getDetails(id!),
    enabled: !!id,
  });

  return {
    data,
    isPending: isPending && fetchStatus !== 'idle',
    isError,
    error: normalizeQueryError(error, 'Failed to fetch session details'),
    refetch,
  };
}

export function useSessionSnapshots(id: number | string | null | undefined) {
  const { data, isPending, fetchStatus, isError, error, refetch } = useQuery({
    queryKey: id ? queryKeys.session.snapshots(id) : [],
    queryFn: () => defaultSessionApi.getSnapshots(id!),
    enabled: !!id,
  });

  return {
    data,
    isPending: isPending && fetchStatus !== 'idle',
    isError,
    error: normalizeQueryError(error, 'Failed to fetch session snapshots'),
    refetch,
  };
}
