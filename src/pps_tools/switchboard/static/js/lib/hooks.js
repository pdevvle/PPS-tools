// Shared hooks.

import { useCallback, useEffect, useRef, useState } from './preact.js';
import { api } from './api.js';
import { on } from './events.js';

// Load JSON and keep it fresh.
//
//   const { data, loading, error, reload, setData } = useFetch('/jobs', {
//     query: { stage: 3 },
//     refetchOn: ['job.changed'],          // server events that may affect this data
//     filter: (evt, type) => evt.id === jobId,   // optional: only refetch for matching events
//   });
//
// Pass path = null to skip loading. Stale responses (after the key changed) are ignored.
export function useFetch(path, { query, refetchOn = [], filter, interval, deps = [] } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: !!path });
  const seq = useRef(0);
  const key = path ? path + '?' + JSON.stringify(query || {}) : null;
  const keyRef = useRef(key);
  keyRef.current = key;
  const queryRef = useRef(query);
  queryRef.current = query;

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!path) return;
    const id = ++seq.current;
    if (!quiet) setState((s) => ({ ...s, loading: true }));
    try {
      const data = await api.get(path, queryRef.current);
      if (id === seq.current) setState({ data, error: null, loading: false });
    } catch (error) {
      if (id === seq.current) setState((s) => ({ ...s, error, loading: false }));
    }
  }, [key, ...deps]);

  useEffect(() => {
    if (!path) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    setState((s) => ({ ...s, data: null, loading: true }));
    load();
  }, [load]);

  const filterRef = useRef(filter);
  filterRef.current = filter;
  useEffect(() => {
    if (!path) return undefined;
    let timer = null;
    const schedule = () => {
      clearTimeout(timer);
      timer = setTimeout(() => load({ quiet: true }), 150);
    };
    const offs = [...refetchOn, 'reconnected'].map((type) => on(type, (data) => {
      if (type !== 'reconnected' && filterRef.current && !filterRef.current(data || {}, type)) return;
      schedule();
    }));
    let poll = null;
    if (interval) poll = setInterval(() => load({ quiet: true }), interval);
    return () => {
      offs.forEach((off) => off());
      clearTimeout(timer);
      if (poll) clearInterval(poll);
    };
  }, [load, refetchOn.join(',')]);

  const setData = useCallback((updater) => {
    setState((s) => ({ ...s, data: typeof updater === 'function' ? updater(s.data) : updater }));
  }, []);

  return { ...state, reload: (opts) => load(opts), setData };
}

// Subscribe to a server/local event for the component's lifetime.
export function useEvent(type, handler, deps = []) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => on(type, (data) => ref.current(data)), [type, ...deps]);
}

export function useDebounced(value, ms = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function useInterval(fn, ms) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    if (!ms) return undefined;
    const t = setInterval(() => ref.current(), ms);
    return () => clearInterval(t);
  }, [ms]);
}

// Re-render every `ms` (for "5m ago" labels and running timers).
export function useNow(ms = 30000) {
  const [now, setNow] = useState(() => Date.now());
  useInterval(() => setNow(Date.now()), ms);
  return now;
}

export function useClickOutside(ref, fn, active = true) {
  const cb = useRef(fn);
  cb.current = fn;
  useEffect(() => {
    if (!active) return undefined;
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) cb.current(e);
    };
    document.addEventListener('mousedown', handler, true);
    return () => document.removeEventListener('mousedown', handler, true);
  }, [active]);
}

export function useLocalStorage(key, initial) {
  const [value, setValue] = useState(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : JSON.parse(raw);
    } catch {
      return initial;
    }
  });
  const set = useCallback((next) => {
    setValue((prev) => {
      const v = typeof next === 'function' ? next(prev) : next;
      try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* private mode */ }
      return v;
    });
  }, [key]);
  return [value, set];
}

export function useMediaQuery(query) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const fn = () => setMatches(mq.matches);
    mq.addEventListener('change', fn);
    return () => mq.removeEventListener('change', fn);
  }, [query]);
  return matches;
}

export const useIsMobile = () => useMediaQuery('(max-width: 760px)');

// Tell teammates what I have open: usePresence('conversation:12', 'composing').
export function usePresence(target, state = 'viewing', draftId = null) {
  useEffect(() => {
    if (!target) return undefined;
    const send = () => api.post('/presence', { target, state, draft_id: draftId }).catch(() => {});
    send();
    const t = setInterval(send, 20000);
    const onVisible = () => { if (document.visibilityState === 'visible') send(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(t);
      document.removeEventListener('visibilitychange', onVisible);
      api.post('/presence', { target: null }).catch(() => {});
    };
  }, [target, state, draftId]);
}

// Async action with a busy flag: const [run, busy] = useAction(async () => ...);
export function useAction(fn) {
  const [busy, setBusy] = useState(false);
  const ref = useRef(fn);
  ref.current = fn;
  const run = useCallback(async (...args) => {
    setBusy(true);
    try {
      return await ref.current(...args);
    } finally {
      setBusy(false);
    }
  }, []);
  return [run, busy];
}
