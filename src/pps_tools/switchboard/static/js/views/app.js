// App shell: sign-in gate, the left rail, the module outlet and global behaviour
// (shortcuts, notifications, theme, connection status).

import { html, useEffect, useState } from '../lib/preact.js';
import { api, setUnauthorizedHandler } from '../lib/api.js';
import { connect, disconnect, onStatus } from '../lib/events.js';
import { loadBootstrap, reloadBadgesSoon, setState, useStore, can, getState } from '../lib/store.js';
import { navigate, useRoute } from '../lib/router.js';
import { useHotkeys, keyLabel } from '../lib/shortcuts.js';
import { MODULES, BOTTOM_MODULES, ALL_MODULES, homePath } from '../modules.js';
import { Avatar, Button, Empty, Icon, IconButton, Kbd, Loading, cx } from '../ui/components.js';
import { OverlayHost, openModal, Modal, showMenu, showPopover, toastError } from '../ui/overlay.js';
import { openPalette, registerCommands } from '../ui/palette.js';
import { NotificationsPanel, startDesktopNotifications, DesktopNotificationsPrompt } from './notifications.js';
import { AuthGate } from './auth.js';

// -- theme --------------------------------------------------------------------------

export function applyTheme(theme) {
  try { localStorage.setItem('sb.theme', theme); } catch { /* ignore */ }
  const dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}

matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  const t = localStorage.getItem('sb.theme') || 'system';
  if (t === 'system') applyTheme('system');
});

export function setTheme(theme) {
  applyTheme(theme);
  api.patch('/me/prefs', { theme }).catch(() => {});
}

// -- module loading -----------------------------------------------------------------

const loaded = new Map();

function useModule(mod) {
  const [state, setLoaded] = useState(() => (mod && loaded.has(mod.id) ? { component: loaded.get(mod.id) } : { loading: true }));
  useEffect(() => {
    if (!mod) return;
    if (loaded.has(mod.id)) { setLoaded({ component: loaded.get(mod.id) }); return; }
    let alive = true;
    setLoaded({ loading: true });
    mod.load()
      .then((m) => {
        loaded.set(mod.id, m.default);
        if (alive) setLoaded({ component: m.default });
      })
      .catch((error) => {
        console.error(error);
        if (alive) setLoaded({ error });
      });
    return () => { alive = false; };
  }, [mod && mod.id]);
  return state;
}

function ModuleOutlet({ route }) {
  const me = useStore((s) => s.me);
  const id = route.segments[0];
  const mod = ALL_MODULES.find((m) => m.id === id);
  const allowed = mod && (!mod.perm || (me.permissions || []).includes(mod.perm));
  const { component: Component, loading, error } = useModule(allowed ? mod : null);
  if (!mod || !allowed) {
    return html`<div class="module-placeholder"><${Empty} icon="search" title="Nothing here"
      action=${html`<${Button} variant="primary" onClick=${() => navigate(homePath(me))}>Go home</${Button}>`}>
      ${mod ? "You don't have access to this area." : "This page doesn't exist."}</${Empty}></div>`;
  }
  if (error) {
    return html`<div class="module-placeholder"><${Empty} icon="triangle-alert" title=${`${mod.label} couldn't load`}
      action=${html`<${Button} onClick=${() => window.location.reload()}>Reload</${Button}>`}>${String(error.message || error)}</${Empty}></div>`;
  }
  if (loading || !Component) return html`<div class="module-placeholder"><${Loading} /></div>`;
  return html`<${Component} route=${route} />`;
}

// -- rail ---------------------------------------------------------------------------

function RailItem({ mod, active, badge }) {
  return html`<a href=${'/' + mod.id} class=${cx('rail-item', active && 'is-active')} aria-label=${mod.label}
    data-tip=${`${mod.label}${mod.shortcut ? '  ' + keyLabel(mod.shortcut) : ''}`} data-tip-pos="right" aria-current=${active ? 'page' : undefined}>
    <${Icon} name=${mod.icon} size=${20} strokeWidth=${1.8} />
    <span class="rail-label">${mod.label}</span>
    ${badge ? html`<span class="rail-badge">${badge > 99 ? '99+' : badge}</span>` : null}
  </a>`;
}

function UserMenu(anchor) {
  const me = getState().me;
  const theme = localStorage.getItem('sb.theme') || 'system';
  showMenu(anchor, [
    { header: me.name },
    { label: 'Profile & preferences', icon: 'user', onSelect: () => navigate('/settings/profile') },
    { label: 'My day', icon: 'house', onSelect: () => navigate('/me') },
    { divider: true },
    { label: 'Light', icon: 'sun', checked: theme === 'light', onSelect: () => setTheme('light') },
    { label: 'Dark', icon: 'moon', checked: theme === 'dark', onSelect: () => setTheme('dark') },
    { label: 'System theme', icon: 'monitor', checked: theme === 'system', onSelect: () => setTheme('system') },
    { divider: true },
    { label: 'Keyboard shortcuts', icon: 'keyboard', shortcut: '?', onSelect: showShortcuts },
    { label: 'Sign out', icon: 'log-out', onSelect: signOut },
  ], { placement: 'right-end', width: 230 });
}

async function signOut() {
  try { await api.post('/auth/logout'); } catch { /* ignore */ }
  disconnect();
  window.location.href = '/login';
}

function Rail({ route }) {
  const me = useStore((s) => s.me);
  const badges = useStore((s) => s.badges);
  const unread = useStore((s) => s.unreadNotifications);
  const active = route.segments[0];
  const visible = (m) => !m.perm || (me.permissions || []).includes(m.perm);
  const openNotifications = (e) => {
    showPopover(e.currentTarget, (close) => html`<${NotificationsPanel} close=${close} />`, { placement: 'right-end', width: 380, class: 'popover-flush' });
  };
  return html`<nav class="rail" aria-label="Main">
    <a href=${homePath(me)} class="rail-logo" aria-label="Switchboard home"><span class="logo-mark"></span></a>
    <div class="rail-items">
      ${MODULES.filter(visible).map((m) => html`<${RailItem} key=${m.id} mod=${m} active=${active === m.id} badge=${badges[m.id]} />`)}
    </div>
    <div class="rail-bottom">
      ${BOTTOM_MODULES.filter(visible).map((m) => html`<${RailItem} key=${m.id} mod=${m} active=${active === m.id} badge=${badges[m.id]} />`)}
      <button type="button" class="rail-item" aria-label="Notifications" data-tip="Notifications" data-tip-pos="right" onClick=${openNotifications}>
        <${Icon} name="bell" size=${20} strokeWidth=${1.8} />
        <span class="rail-label">Alerts</span>
        ${unread ? html`<span class="rail-badge">${unread > 99 ? '99+' : unread}</span>` : null}
      </button>
      <button type="button" class="rail-avatar" aria-label="Account menu" onClick=${(e) => UserMenu(e.currentTarget)}>
        <${Avatar} user=${me} size=${30} online=${true} title=${me.name} />
      </button>
    </div>
  </nav>`;
}

// -- shortcuts help -----------------------------------------------------------------

export const SHORTCUT_HELP = [
  ['Anywhere', [
    ['mod+k', 'Command palette & search'], ['?', 'Keyboard shortcuts'], ['c', 'Compose a message'],
    ...ALL_MODULES.filter((m) => m.shortcut).map((m) => [m.shortcut, `Go to ${m.label}`]),
  ]],
  ['Conversation list', [
    ['j', 'Next conversation'], ['k', 'Previous conversation'], ['x', 'Select'], ['enter', 'Open'],
    ['e', 'Close / reopen'], ['s', 'Star'], ['h', 'Snooze'], ['a', 'Assign'], ['l', 'Label'],
    ['#', 'Move to trash'], ['!', 'Mark as spam'], ['shift+u', 'Mark unread'], ['/', 'Search'],
  ]],
  ['Conversation', [
    ['r', 'Reply'], ['shift+r', 'Reply all'], ['f', 'Forward'], ['m', 'Comment'], ['mod+enter', 'Send'],
    ['escape', 'Back to list'],
  ]],
];

export function showShortcuts() {
  openModal((close) => html`<${Modal} title="Keyboard shortcuts" icon="keyboard" onClose=${close} size="lg">
    <div class="shortcut-grid">
      ${SHORTCUT_HELP.map(([group, rows]) => html`<div class="shortcut-group">
        <h3>${group}</h3>
        ${rows.map(([combo, label]) => html`<div class="shortcut-row"><span>${label}</span><span class="shortcut-keys">${combo.split(' ').map((k) => html`<${Kbd}>${keyLabel(k)}</${Kbd}>`)}</span></div>`)}
      </div>`)}
    </div>
  </${Modal}>`);
}

// -- shell --------------------------------------------------------------------------

function ConnectionBanner() {
  const [status, setStatus] = useState('open');
  useEffect(() => onStatus(setStatus), []);
  if (status !== 'reconnecting' && status !== 'closed') return null;
  return html`<div class="connection-banner"><span class="spinner" style="width:12px;height:12px"></span> Reconnecting… changes from teammates will appear when you're back online.</div>`;
}

function Shell() {
  const route = useRoute();
  const me = useStore((s) => s.me);

  useEffect(() => {
    if (route.path === '/' || route.path === '/login' || route.path === '/setup') navigate(homePath(me), { replace: true });
  }, [route.path]);

  useEffect(() => {
    connect();
    reloadBadgesSoon(0);
    const stop = startDesktopNotifications();
    applyTheme(me.prefs?.theme || localStorage.getItem('sb.theme') || 'system');
    const offs = [
      registerCommands(() => ALL_MODULES
        .filter((m) => !m.perm || can(m.perm))
        .map((m) => ({ id: 'go-' + m.id, label: `Go to ${m.label}`, icon: m.icon, group: 'Navigate', shortcut: m.shortcut && keyLabel(m.shortcut), run: () => navigate('/' + m.id) }))),
      registerCommands(() => [
        { id: 'theme-dark', label: 'Switch to dark theme', icon: 'moon', run: () => setTheme('dark') },
        { id: 'theme-light', label: 'Switch to light theme', icon: 'sun', run: () => setTheme('light') },
        { id: 'shortcuts', label: 'Keyboard shortcuts', icon: 'keyboard', run: showShortcuts },
        { id: 'signout', label: 'Sign out', icon: 'log-out', run: signOut },
      ]),
    ];
    return () => { stop(); offs.forEach((off) => off()); };
  }, []);

  // Tab title shows unread inbox count.
  const badges = useStore((s) => s.badges);
  useEffect(() => {
    const n = badges.inbox || 0;
    const org = getState().settings['org.name'] || 'Switchboard';
    document.title = n ? `(${n}) ${org}` : org;
  }, [badges.inbox]);

  const go = (path) => () => navigate(path);
  const shortcuts = {
    'mod+k': openPalette,
    '?': showShortcuts,
  };
  for (const m of ALL_MODULES) if (m.shortcut && (!m.perm || can(m.perm))) shortcuts[m.shortcut] = go('/' + m.id);
  useHotkeys(shortcuts);

  return html`<div class="app">
    <${Rail} route=${route} />
    <main class="app-main">
      <${ConnectionBanner} />
      <${DesktopNotificationsPrompt} />
      <div class="app-outlet"><${ModuleOutlet} route=${route} /></div>
    </main>
    <${OverlayHost} />
  </div>`;
}

export function App() {
  const [phase, setPhase] = useState('checking'); // checking | gate | ready
  const [authState, setAuthState] = useState(null);

  const boot = async () => {
    try {
      await loadBootstrap();
      setPhase('ready');
    } catch (err) {
      toastError(err);
      setPhase('gate');
    }
  };

  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (getState().me) window.location.href = '/login';
    });
    api.get('/auth/state').then((s) => {
      setAuthState(s);
      if (s.user) boot();
      else setPhase('gate');
    }).catch(() => {
      setAuthState({ setup_required: false, user: null, offline: true });
      setPhase('gate');
    });
  }, []);

  if (phase === 'checking') return html`<div class="boot-splash"><div class="boot-logo"></div></div>`;
  if (phase === 'gate') {
    return html`<${AuthGate} state=${authState} onSignedIn=${(me) => { setState({ me }); setPhase('checking'); boot(); }} />
      <${OverlayHost} />`;
  }
  return html`<${Shell} />`;
}
