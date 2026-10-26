// Global app state: who I am, teammates, teams, settings, presence, badges, and any
// reference data modules put in /api/bootstrap (labels, channels, positions, stages...).
//
//   const users = useStore((s) => s.users);
//   const labels = useStore((s) => s.boot.labels || []);
//   user(12).name, can('admin'), setting('org.timezone')

import { useEffect, useReducer, useRef } from './preact.js';
import { api } from './api.js';
import { on } from './events.js';

const state = {
  ready: false,
  boot: {},
  me: null,
  users: [],
  usersById: {},
  teams: [],
  teamsById: {},
  settings: {},
  online: new Set(),
  presence: {},
  badges: {},
  unreadNotifications: 0,
};

const listeners = new Set();

export function getState() {
  return state;
}

export function setState(patch) {
  Object.assign(state, typeof patch === 'function' ? patch(state) : patch);
  listeners.forEach((fn) => fn(state));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function shallowEqual(a, b) {
  if (Object.is(a, b)) return true;
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  return ka.every((k) => Object.is(a[k], b[k]));
}

export function useStore(selector) {
  const [, force] = useReducer((x) => x + 1, 0);
  const selRef = useRef(selector);
  selRef.current = selector;
  const value = selector(state);
  const valRef = useRef(value);
  valRef.current = value;
  useEffect(() => subscribe(() => {
    const next = selRef.current(state);
    if (!shallowEqual(next, valRef.current)) force();
  }), []);
  return value;
}

function indexBy(list) {
  const out = {};
  for (const item of list || []) out[item.id] = item;
  return out;
}

export function applyBootstrap(boot) {
  setState({
    ready: true,
    boot,
    me: boot.me,
    users: boot.users || [],
    usersById: indexBy(boot.users),
    teams: boot.teams || [],
    teamsById: indexBy(boot.teams),
    settings: boot.settings || {},
    online: new Set(boot.online || []),
    presence: boot.presence || state.presence,
    unreadNotifications: boot.unread_notifications ?? state.unreadNotifications,
  });
}

export async function loadBootstrap() {
  const boot = await api.get('/bootstrap');
  applyBootstrap(boot);
  return boot;
}

let bootTimer = null;
export function reloadBootstrapSoon(delay = 300) {
  clearTimeout(bootTimer);
  bootTimer = setTimeout(() => loadBootstrap().catch(() => {}), delay);
}

let badgeTimer = null;
export function reloadBadgesSoon(delay = 400) {
  clearTimeout(badgeTimer);
  badgeTimer = setTimeout(async () => {
    try {
      const res = await api.get('/badges');
      setState({ badges: res.badges || {} });
    } catch { /* offline; next event retries */ }
  }, delay);
}

// -- lookups ------------------------------------------------------------------------

const UNKNOWN = { id: 0, name: 'Unknown', email: '', color: '#868e96', role: 'staff', is_active: false };

export function user(id) {
  return state.usersById[id] || { ...UNKNOWN, id };
}

export function team(id) {
  return state.teamsById[id] || null;
}

export function me() {
  return state.me;
}

export function can(perm) {
  return !!state.me && (state.me.permissions || []).includes(perm);
}

// Whether a server module (api/<name>.py) is running; see SWITCHBOARD_MODULES.
export function hasModule(name) {
  const mods = state.boot && state.boot.modules;
  return !name || !mods || mods.includes(name);
}

export function setting(key, fallback) {
  const v = state.settings[key];
  return v === undefined ? fallback : v;
}

export function isOnline(id) {
  return state.online.has(id);
}

export function boot(key, fallback = []) {
  const v = state.boot[key];
  return v === undefined ? fallback : v;
}

// Keep shared state in sync with the server.
on('hello', (data) => setState({ online: new Set(data.online || []), presence: data.presence || {} }));
on('user.online', ({ user_id, online }) => {
  const next = new Set(state.online);
  online ? next.add(user_id) : next.delete(user_id);
  setState({ online: next });
});
on('presence', ({ target, viewers }) => setState({ presence: { ...state.presence, [target]: viewers } }));
on('settings.changed', () => reloadBootstrapSoon());
on('badges.changed', () => reloadBadgesSoon());
on('reconnected', () => { reloadBootstrapSoon(50); reloadBadgesSoon(50); });
on('notification', () => setState({ unreadNotifications: state.unreadNotifications + 1 }));
