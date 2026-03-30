import { useState, useEffect, useCallback, useContext, useMemo } from 'react';
import axios from 'axios';
import { threadsApi } from '../services/api';
import type { ReactivateThreadPayload, Thread, ThreadCreatePayload, ThreadListResponse, ThreadQueryParams, ThreadUpdatePayload } from '../types';
import { CacheContext } from '../contexts/CacheContext';

type UseThreadsOptions = {
  searchTerm?: string;
  collectionId?: number | null;
};

export function useThreads(searchTermOrOptions?: string | UseThreadsOptions, collectionId?: number | null) {
  const [data, setData] = useState<Thread[] | null>(null);
  const [isPending, setIsPending] = useState(true);
  const [isError, setIsError] = useState(false);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const cache = useContext(CacheContext);
  const invalidateQueries = useMemo(() => cache?.invalidateQueries ?? (() => {}), [cache]);

  // Support both calling conventions:
  // useThreads('', collectionId) or useThreads({ searchTerm: '', collectionId })
  const options: UseThreadsOptions = typeof searchTermOrOptions === 'string'
    ? { searchTerm: searchTermOrOptions, collectionId }
    : { ...searchTermOrOptions };

  const { searchTerm = '', collectionId: cid = null } = options;

  const fetchData = useCallback(async (pageToken?: string) => {
    setIsPending(true);
    setIsError(false);
    let cancelled = false;

    try {
      const baseParams: ThreadQueryParams = {};
      if (searchTerm?.trim()) {
        baseParams.search = searchTerm.trim();
      }
      if (cid !== null) {
        baseParams.collection_id = cid;
      }
      // For initial load (no pageToken), fetch all pages with large page_size
      if (!pageToken) {
        baseParams.page_size = 200; // max allowed by backend
      }

      let allThreads: Thread[] = [];
      let currentToken: string | undefined = pageToken;
      let nextToken: string | null = null;

      do {
        const result: ThreadListResponse = await threadsApi.list(
          Object.keys(baseParams).length > 0 ? baseParams : undefined,
          currentToken
        );
        allThreads = allThreads.concat(result.threads);
        nextToken = result.next_page_token;
        // If we are fetching all pages (no initial pageToken), continue with next token
        if (!pageToken && nextToken) {
          currentToken = nextToken;
        } else {
          // If we were called with a specific pageToken, stop after one page
          break;
        }
      } while (!pageToken && nextToken);

      if (!cancelled) {
        setData(allThreads);
        setNextPageToken(nextToken);
        invalidateQueries(['threads']);
      }
    } catch (_err) {
      if (!cancelled) {
        setIsError(true);
      }
    } finally {
      if (!cancelled) {
        setIsPending(false);
      }
    }
  }, [searchTerm, cid, invalidateQueries]);

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchTerm, cid]);

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
  };

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
  const invalidateQueries = useMemo(() => cache?.invalidateQueries ?? (() => {}), [cache]);
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
  const invalidateQueries = useMemo(() => cache?.invalidateQueries ?? (() => {}), [cache]);
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
  const invalidateQueries = useMemo(() => cache?.invalidateQueries ?? (() => {}), [cache]);
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
  const invalidateQueries = useMemo(() => cache?.invalidateQueries ?? (() => {}), [cache]);
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
