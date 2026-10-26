// Notification center (the bell) and desktop notifications.

import { html, useEffect, useState } from '../lib/preact.js';
import { api } from '../lib/api.js';
import { on } from '../lib/events.js';
import { navigate } from '../lib/router.js';
import { setState, getState, user } from '../lib/store.js';
import { useFetch } from '../lib/hooks.js';
import { Avatar, Button, Empty, Icon, IconButton, Loading, RelTime, cx } from '../ui/components.js';

const TYPE_ICONS = {
  mention: 'at-sign', assigned: 'user-check', message: 'mail', comment: 'message-square', reminder: 'alarm-clock',
  snooze: 'clock', task: 'square-check-big', job: 'square-kanban', shift: 'calendar-clock', timeoff: 'plane',
  swap: 'arrow-right-left', chat: 'messages-square', system: 'info',
};

export function NotificationsPanel({ close }) {
  const [filter, setFilter] = useState('all');
  const { data, loading, reload, setData } = useFetch('/notifications', {
    query: { unread: filter === 'unread', limit: 60 },
    refetchOn: ['notification', 'notifications.read'],
  });
  const items = data?.items || [];

  const open = async (n) => {
    if (!n.read_at) {
      setData((d) => d && { ...d, items: d.items.map((x) => (x.id === n.id ? { ...x, read_at: new Date().toISOString() } : x)) });
      api.post('/notifications/read', { ids: [n.id] }).then((r) => setState({ unreadNotifications: r.unread_count })).catch(() => {});
    }
    if (n.link) {
      close && close();
      navigate(n.link);
    }
  };
  const markAll = async () => {
    const r = await api.post('/notifications/read', {});
    setState({ unreadNotifications: r.unread_count });
    reload();
  };

  return html`<div class="notif-panel">
    <header class="notif-header">
      <h2>Notifications</h2>
      <div class="segmented segmented-sm">
        ${['all', 'unread'].map((f) => html`<button type="button" class=${cx('segmented-item', filter === f && 'is-active')} onClick=${() => setFilter(f)}>${f === 'all' ? 'All' : 'Unread'}</button>`)}
      </div>
      <${IconButton} icon="check-check" label="Mark all as read" onClick=${markAll} />
      ${close && html`<${IconButton} icon="x" label="Close" onClick=${close} />`}
    </header>
    <div class="notif-list">
      ${loading && !data ? html`<${Loading} />` : null}
      ${data && !items.length && html`<${Empty} icon="bell" title="You're all caught up" compact>Mentions, assignments and schedule changes show up here.</${Empty}>`}
      ${items.map((n) => html`<button type="button" key=${n.id} class=${cx('notif-item', !n.read_at && 'is-unread')} onClick=${() => open(n)}>
        <span class="notif-avatar">
          ${n.actor_id ? html`<${Avatar} user=${n.actor_id} size=${30} />` : html`<span class="notif-type-icon"><${Icon} name=${TYPE_ICONS[n.type] || 'bell'} size=${15} /></span>`}
          ${n.actor_id && html`<span class="notif-type-badge"><${Icon} name=${TYPE_ICONS[n.type] || 'bell'} size=${10} /></span>`}
        </span>
        <span class="notif-text">
          <span class="notif-title">${n.title}</span>
          ${n.body && html`<span class="notif-body">${n.body}</span>`}
          <${RelTime} value=${n.created_at} mode="ago" class="notif-time" />
        </span>
        ${!n.read_at && html`<span class="notif-unread-dot"></span>`}
      </button>`)}
    </div>
  </div>`;
}

// -- desktop notifications ------------------------------------------------------------

let audioCtx = null;
function ping() {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const o = audioCtx.createOscillator();
    const g = audioCtx.createGain();
    o.type = 'sine';
    o.frequency.setValueAtTime(880, audioCtx.currentTime);
    o.frequency.exponentialRampToValueAtTime(660, audioCtx.currentTime + 0.12);
    g.gain.setValueAtTime(0.0001, audioCtx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.08, audioCtx.currentTime + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.25);
    o.connect(g).connect(audioCtx.destination);
    o.start();
    o.stop(audioCtx.currentTime + 0.3);
  } catch { /* audio unavailable */ }
}

export function startDesktopNotifications() {
  return on('notification', (n) => {
    const prefs = getState().me?.prefs || {};
    if (prefs.sound !== false) ping();
    if (prefs.desktop === false || !('Notification' in window) || Notification.permission !== 'granted') return;
    if (document.visibilityState === 'visible' && document.hasFocus()) return;
    const actor = n.actor_id ? user(n.actor_id) : null;
    const note = new Notification(n.title, {
      body: n.body || (actor ? actor.name : ''),
      tag: `sb-${n.entity_type || 'n'}-${n.entity_id || n.id}`,
      icon: '/static/icon.svg',
    });
    note.onclick = () => {
      window.focus();
      if (n.link) navigate(n.link);
      note.close();
    };
  });
}

export function DesktopNotificationsPrompt() {
  const [perm, setPerm] = useState(() => ('Notification' in window ? Notification.permission : 'unsupported'));
  const [dismissed, setDismissed] = useState(() => localStorage.getItem('sb.notif-prompt') === 'dismissed');
  useEffect(() => {}, []);
  if (perm !== 'default' || dismissed) return null;
  const enable = async () => setPerm(await Notification.requestPermission());
  const dismiss = () => { localStorage.setItem('sb.notif-prompt', 'dismissed'); setDismissed(true); };
  return html`<div class="desktop-prompt">
    <${Icon} name="bell-ring" size=${16} />
    <span>Get a desktop alert when someone mentions you or assigns you work.</span>
    <${Button} size="sm" variant="primary" onClick=${enable}>Enable</${Button}>
    <${IconButton} icon="x" size="sm" label="Not now" onClick=${dismiss} />
  </div>`;
}
