import { useState, useEffect, useCallback, useContext } from 'react';
import axios from 'axios';
import { threadsApi } from '../services/api';
import type { ReactivateThreadPayload, Thread, ThreadCreatePayload, ThreadQueryParams, ThreadUpdatePayload } from '../types';
import { CacheContext } from '../../contexts/CacheContext';

export function useThreads(options = { searchTerm: '', collectionId: null }) {
  const [data, setData] = useState<Thread[] | null>(null);
  const [isPending, setIsPending] = useState(true);
  const [isError, setIsError] = useState(false);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const { invalidateQueries } = useContext(CacheContext) || {};

  const { searchTerm, collectionId } = options;

  const fetchData = useCallback(async (pageToken?: string) => {
    setIsPending(true);
    setIsError(false);
    let cancelled = false;

    try {
      const params: ThreadQueryParams = {};
      if (searchTerm?.trim()) {
        params.search = searchTerm.trim();
      }
      if (collectionId !== null) {
        params.collection_id = collectionId;
      }
      if (pageToken) {
        params.page_token = pageToken;
      }

      const result = await threadsApi.list(Object.keys(params).length > 0 ? params : undefined);

      if (!cancelled) {
        setData((result as any).threads ?? []);
        setNextPageToken((result as any).next_page_token ?? null);
        invalidateQueries?.(['threads']);
      }
    } catch (err) {
      if (!cancelled) {
        setIsError(true);
      }
    } finally {
      if (!cancelled) {
        setIsPending(false);
      }
    }
  }, [searchTerm, collectionId, invalidateQueries]);

  useEffect(() => {
    fetchData();
  }, [searchTerm, collectionId]);

  const refetch = useCallback((pageToken?: string) => {
    fetchData(pageToken);
  }, [fetchData]);

  return { data, isPending, isError, refetch, nextPageToken };
}

export function useThread(id?: number | null) {
  const [data, setData] = useState<Thread | null>(null);
  const [isPending, setIsPending] = useState(true);
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    if (!id) {
      setData(null);
      setIsError(false);
      setIsPending(false);
      return;
    }

    let isMounted = true;

    const fetchData = async () => {
      setIsPending(true);
      setIsError(false);

      try {
        const result = await threadsApi.get(id);
        if (isMounted) {
          setData(result);
        }
      } catch {
        if (isMounted) {
          setIsError(true);
        }
      } finally {
        if (isMounted) {
          setIsPending(false);
        }
      }
    ];

    fetchData();

    return () => {
      isMounted = false;
    };
  }, [id]);

  return { data, isPending, isError };
}

export function useStaleThreads(days?: number) {
  const [data, setData] = useState<Thread[] | null>(null);
  const [isPending, setIsPending] = useState(true);
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    let isMounted = true;

    const fetchData = async () => {
      setIsPending(true);
      setIsError(false);

      try {
        const result = await threadsApi.listStale(days);
        if (isMounted) {
          setData(result);
        }
      } catch {
        if (isMounted) {
          setIsError(true);
        }
      } finally {
        if (isMounted) {
          setIsPending(false);
        }
      }
    };

    fetchData();

    return () => {
      isMounted = false;
    };
  }, [days]);

  return { data, isPending, isError };
}

export function useCreateThread() {
  const cache = useContext(CacheContext);
  const invalidateQueries = cache?.invalidateQueries ?? (() => {});
  const [isPending, setIsPending] = useState(false);
  const [isError, setIsError] = useState(false);

  const mutate = useCallback(
    async (data: ThreadCreatePayload) => {
      setIsPending(true);
      setIsError(false);

      try {
        const result = await threadsApi.create(data);
        invalidateQueries(['threads']);
        return result;
      } catch (error: unknown) {
        const detail = axios.isAxiosError<{ detail?: string }>(error)
          ? error.response?.data?.detail || error.message
          : error instanceof Error ? error.message : 'Unknown error';
        console.error('Failed to create thread:', detail);
        setIsError(true);
        throw error;
      } finally {
        setIsPending(false);
      }
    },
    [invalidateQueries]
  );

  return { mutate, isPending, isError };
}

export function useUpdateThread() {
  const cache = useContext(CacheContext);
  const invalidateQueries = cache?.invalidateQueries ?? (() => {});
  const [isPending, setIsPending] = useState(false);
  const [isError, setIsError] = useState(false);

  const mutate = useCallback(
    async ({ id, data }: { id: number; data: ThreadUpdatePayload }) => {
      setIsPending(true);
      setIsError(false);

      try {
        const result = await threadsApi.update(id, data);
        invalidateQueries(['threads']);
        return result;
      } catch (error: unknown) {
        const detail = axios.isAxiosError<{ detail?: string }>(error)
          ? error.response?.data?.detail || error.message
          : error instanceof Error ? error.message : 'Unknown error';
        console.error('Failed to update thread:', detail);
        setIsError(true);
        throw error;
      } finally {
        setIsPending(false);
      }
    },
    [invalidateQueries]
  );

  return { mutate, isPending, isError };
}

export function useDeleteThread() {
  const cache = useContext(CacheContext);
  const invalidateQueries = cache?.invalidateQueries ?? (() => {});
  const [isPending, setIsPending] = useState(false);
  const [isError, setIsError] = useState(false);

  const mutate = useCallback(
    async (id: number) => {
      setIsPending(true);
      setIsError(false);

      try {
        const result = await threadsApi.delete(id);
        invalidateQueries(['threads']);
        return result;
      } catch (error: unknown) {
        const detail = axios.isAxiosError<{ detail?: string }>(error)
          ? error.response?.data?.detail || error.message
          : error instanceof Error ? error.message : 'Unknown error';
        console.error('Failed to delete thread:', detail);
        setIsError(true);
        throw error;
      } finally {
        setIsPending(false);
      }
    },
    [invalidateQueries]
  );

  return { mutate, isPending, isError };
}

export function useReactivateThread() {
  const cache = useContext(CacheContext);
  const invalidateQueries = cache?.invalidateQueries ?? (() => {});
  const [isPending, setIsPending] = useState(false);
  const [isError, setIsError] = useState(false);

  const mutate = useCallback(
    async (data: ReactivateThreadPayload) => {
      setIsPending(true);
      setIsError(false);

      try {
        const result = await threadsApi.reactivate(data);
        invalidateQueries(['threads']);
        return result;
      } catch (error: unknown) {
        const detail = axios.isAxiosError<{ detail?: string }>(error)
          ? error.response?.data?.detail || error.message
          : error instanceof Error ? error.message : 'Unknown error';
        console.error('Failed to reactivate thread:', detail);
        setIsError(true);
        throw error;
      } finally {
        setIsPending(false);
      }
    },
    [invalidateQueries]
  );

  return { mutate, isPending, isError };
}
