// History-API router.
//
//   navigate('/inbox/assigned');           navigate(path, { replace: true })
//   const route = useRoute();              // { path, segments, query }
//   matchPath('/jobs/:id', route.path)     // { id: '12' } or null
//   <a href="/jobs/12">                    // plain links are intercepted (no reload)
//
// Add data-native to an <a> (or target=_blank) to let the browser handle it.

import { useEffect, useReducer } from './preact.js';

const listeners = new Set();
let current = parse();

function parse() {
  const { pathname, search } = window.location;
  const query = Object.fromEntries(new URLSearchParams(search));
  const path = pathname.replace(/\/+$/, '') || '/';
  return { path, segments: path.split('/').filter(Boolean), query, search };
}

function notify() {
  current = parse();
  listeners.forEach((fn) => fn(current));
}

const guards = new Set();

// A guard can veto navigation (e.g. unsaved changes); return false to block.
export function addNavigationGuard(fn) {
  guards.add(fn);
  return () => guards.delete(fn);
}

export function navigate(to, { replace = false, query } = {}) {
  let url = to;
  if (query) {
    const qs = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== ''));
    const s = qs.toString();
    url = to.split('?')[0] + (s ? '?' + s : '');
  }
  if (url === window.location.pathname + window.location.search) return;
  for (const g of guards) if (g(url) === false) return;
  window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
  notify();
}

export function setQuery(patch, { replace = true } = {}) {
  const q = { ...current.query, ...patch };
  navigate(current.path, { replace, query: q });
}

export function getRoute() {
  return current;
}

export function useRoute() {
  const [, force] = useReducer((x) => x + 1, 0);
  useEffect(() => {
    listeners.add(force);
    return () => listeners.delete(force);
  }, []);
  return current;
}

export function matchPath(pattern, path) {
  const p = pattern.split('/').filter(Boolean);
  const s = path.split('/').filter(Boolean);
  const params = {};
  for (let i = 0; i < p.length; i++) {
    const part = p[i];
    if (part === '*') {
      params['*'] = s.slice(i).join('/');
      return params;
    }
    if (i >= s.length) return part.endsWith('?') ? params : null;
    if (part.startsWith(':')) {
      params[part.slice(1).replace(/\?$/, '')] = decodeURIComponent(s[i]);
    } else if (part !== s[i]) {
      return null;
    }
  }
  return s.length > p.length ? null : params;
}

window.addEventListener('popstate', notify);

document.addEventListener('click', (e) => {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const a = e.target.closest && e.target.closest('a[href]');
  if (!a || a.hasAttribute('data-native') || a.target === '_blank' || a.hasAttribute('download')) return;
  const href = a.getAttribute('href');
  if (!href || !href.startsWith('/') || href.startsWith('//')) return;
  if (href.startsWith('/api/') || href.startsWith('/public/') || href.startsWith('/static/') || href.startsWith('/feeds/')) return;
  e.preventDefault();
  navigate(href);
});
