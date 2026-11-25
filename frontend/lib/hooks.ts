"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { pollDelay, startedAtMs } from "./processing";
import type { ResumeDetail, ResumeProcessing } from "./types";

export interface Resource<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  reload: () => Promise<void>;
  setData: React.Dispatch<React.SetStateAction<T | undefined>>;
}

function asApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, "unknown", e instanceof Error ? e.message : "Something went wrong.");
}

/** Minimal data loader: fetches on mount and when `key` changes. */
export function useResource<T>(fetcher: () => Promise<T>, key: unknown[] = []): Resource<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const keyStr = JSON.stringify(key);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetcherRef.current());
      setError(null);
    } catch (e) {
      setError(asApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload, keyStr]);

  return { data, error, loading, reload, setData };
}

export { asApiError };

/**
 * Calls `tick` repeatedly while `active`: every 2 s, then every 5 s once `startedAt` is 30 s old.
 * `tick` returns whether to keep polling (a rejection counts as "yes", so a blip does not stop it).
 * Pauses while the tab is hidden, and stops on unmount or when `active` turns false.
 */
export function usePoll(tick: (signal: AbortSignal) => Promise<boolean>, active: boolean, startedAt: number) {
  const tickRef = useRef(tick);
  tickRef.current = tick;
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ctrl = new AbortController();
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        document.removeEventListener("visibilitychange", onVisible);
        void run();
      }
    };
    const schedule = () => {
      timer = setTimeout(() => void run(), pollDelay(Date.now() - startedAt));
    };
    const run = async () => {
      if (stopped) return;
      if (document.visibilityState !== "visible") {
        document.addEventListener("visibilitychange", onVisible);
        return;
      }
      let more = true;
      try {
        more = await tickRef.current(ctrl.signal);
      } catch {
        /* transient failure: try again on the next beat */
      }
      if (!stopped && more) schedule();
    };
    schedule();
    return () => {
      stopped = true;
      ctrl.abort();
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [active, startedAt]);
}

/**
 * Follows one resume that is being read in the background: polls `GET /resumes/{id}`, calls `onReady` once
 * it has a version, and exposes `retry` for a failed read. Unmounting just stops the polling.
 */
export function useResumeProcessing(resumeId: string, initial: ResumeProcessing, onReady: (detail: ResumeDetail) => void) {
  const [processing, setProcessing] = useState<ResumeProcessing>(initial);
  const [startedAt, setStartedAt] = useState(() => startedAtMs(initial));
  const [retrying, setRetrying] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [gone, setGone] = useState(false);
  const readyRef = useRef(onReady);
  readyRef.current = onReady;
  const done = useRef(false);

  const apply = useCallback((d: ResumeDetail) => {
    if (d.processing) {
      setProcessing(d.processing);
      return d.processing.status === "processing";
    }
    if (!done.current) {
      done.current = true;
      readyRef.current(d);
    }
    return false;
  }, []);

  const active = processing.status === "processing" && !gone;
  usePoll(
    async (signal) => {
      try {
        return apply(await api.resume(resumeId, signal));
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          setGone(true);
          return false;
        }
        throw e;
      }
    },
    active,
    startedAt,
  );

  const retry = useCallback(async () => {
    setRetrying(true);
    setProblem(null);
    try {
      const d = await api.retryResumeProcessing(resumeId);
      if (d.processing?.status === "processing") setStartedAt(Date.now());
      apply(d);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // Not retryable (already running or finished): follow whatever state it is in now.
        try {
          const d = await api.resume(resumeId);
          if (d.processing?.status === "processing") setStartedAt(Date.now());
          apply(d);
        } catch (e2) {
          setProblem(e2 instanceof Error ? e2.message : "Something went wrong.");
        }
      } else {
        setProblem(e instanceof Error ? e.message : "Something went wrong.");
      }
    } finally {
      setRetrying(false);
    }
  }, [resumeId, apply]);

  return { processing, startedAt, retrying, retry, problem, gone };
}
