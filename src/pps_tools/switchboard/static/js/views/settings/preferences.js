import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useStore, setState, getState } from '../../lib/store.js';
import { Section, Segmented, Toggle, Button } from '../../ui/components.js';
import { toastError } from '../../ui/overlay.js';
import { setTheme } from '../app.js';
import { setShortcutsEnabled } from '../../lib/shortcuts.js';

const TYPES = [
  ['mention', 'Mentions', 'Someone @mentions you in a comment or chat'],
  ['assigned', 'Assignments', 'A conversation, task or job is assigned to you'],
  ['message', 'New messages', 'Replies in conversations you follow or own'],
  ['comment', 'Comments', 'New comments in conversations you follow'],
  ['chat', 'Chat messages', 'Direct messages and rooms you are in'],
  ['reminder', 'Reminders & snoozes', 'Follow-up reminders and snoozed conversations waking up'],
  ['shift', 'Schedule', 'Shifts published or changed, shift reminders'],
  ['timeoff', 'Time off', 'Requests and decisions'],
  ['swap', 'Shift swaps', 'Swap, drop and pickup requests'],
  ['job', 'Jobs', 'Jobs you are on change stage, are due, or get comments'],
  ['task', 'Tasks', 'Tasks assigned to you or due'],
];

export default function Preferences() {
  const me = useStore((s) => s.me);
  const prefs = me.prefs || {};
  const [theme, setThemeState] = useState(localStorage.getItem('sb.theme') || 'system');
  const update = async (patch) => {
    try {
      const res = await api.patch('/me/prefs', patch);
      setState({ me: { ...getState().me, prefs: res.prefs } });
    } catch (err) { toastError(err); }
  };
  const notify = prefs.notify || {};
  const perm = 'Notification' in window ? Notification.permission : 'unsupported';

  return html`<div>
    <${Section} title="Appearance">
      <${Segmented} value=${theme} onChange=${(t) => { setThemeState(t); setTheme(t); }}
        options=${[{ value: 'light', label: 'Light', icon: 'sun' }, { value: 'dark', label: 'Dark', icon: 'moon' }, { value: 'system', label: 'System', icon: 'monitor' }]} />
    </${Section}>
    <${Section} title="Alerts" description="In-app notifications always appear under the bell. These control the extras.">
      <div class="stack">
        <${Toggle} checked=${prefs.desktop !== false} onChange=${(v) => update({ desktop: v })} label="Desktop notifications"
          hint=${perm === 'granted' ? 'Shown when Switchboard is in the background' : perm === 'denied' ? 'Blocked in your browser settings' : 'Your browser will ask for permission'} />
        ${perm === 'default' && html`<div><${Button} size="sm" onClick=${() => Notification.requestPermission()}>Allow desktop notifications</${Button}></div>`}
        <${Toggle} checked=${prefs.sound !== false} onChange=${(v) => update({ sound: v })} label="Play a sound" />
        <${Toggle} checked=${prefs.shortcuts !== false} onChange=${(v) => { setShortcutsEnabled(v); update({ shortcuts: v }); }} label="Keyboard shortcuts" hint="Press ? anywhere to see them" />
      </div>
    </${Section}>
    <${Section} title="Notify me about">
      <div class="stack">
        ${TYPES.map(([type, label, hint]) => html`<${Toggle} key=${type} checked=${notify[type] !== false}
          onChange=${(v) => update({ notify: { [type]: v } })} label=${label} hint=${hint} />`)}
      </div>
    </${Section}>
  </div>`;
}
