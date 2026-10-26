// Kiosk: a full-screen time clock for the shared shop tablet. The tablet stays signed
// in as a manager; each person punches in or out with their PIN.

import { html, useEffect, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch, useInterval } from '../../lib/hooks.js';
import { navigate } from '../../lib/router.js';
import { fmtDuration } from '../../lib/format.js';
import { Avatar, Icon, cx } from '../../ui/components.js';
import { useHotkeys } from '../../lib/shortcuts.js';
import * as S from './shared.js';

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'clear', '0', 'back'];
const RESET_MS = 4500;

export function Kiosk() {
  const [now, setNow] = useState(() => new Date());
  const [pin, setPin] = useState('');
  const [result, setResult] = useState(null);   // {name, action, at, ...}
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);
  const live = useFetch('/timeclock/live', { refetchOn: ['timeclock.changed'], interval: 60000 });
  useInterval(() => setNow(new Date()), 1000);

  const reset = () => { setPin(''); setResult(null); setError(null); };
  const later = (fn, ms = RESET_MS) => { clearTimeout(timer.current); timer.current = setTimeout(fn, ms); };
  useEffect(() => () => clearTimeout(timer.current), []);

  const submit = async (value = pin) => {
    if (busy || value.length < 4) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post('/kiosk/punch', { pin: value });
      setResult(res);
      setPin('');
      later(reset);
    } catch (err) {
      setError(err.status === 429 ? err.message : err.code === 'wrong_pin' ? 'PIN not recognized' : err.message);
      setPin('');
      later(() => setError(null), 2500);
    } finally {
      setBusy(false);
    }
  };
  const press = (key) => {
    if (result) reset();
    if (key === 'clear') { setPin(''); return; }
    if (key === 'back') { setPin((p) => p.slice(0, -1)); return; }
    setError(null);
    setPin((p) => (p.length >= 8 ? p : p + key));
  };
  useHotkeys(Object.fromEntries([
    ...'0123456789'.split('').map((d) => [d, () => press(d)]),
    ['backspace', () => press('back')],
    ['enter', () => submit()],
    ['escape', () => (pin || result ? reset() : navigate('/schedule'))],
  ]), { allowInInputs: true });

  const fullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen?.();
    else document.documentElement.requestFullscreen?.().catch(() => {});
  };
  const clockedIn = live.data?.items || [];
  const time = S.orgTime(now);
  const seconds = String(now.getSeconds()).padStart(2, '0');

  return html`<div class="kiosk" role="application" aria-label="Time clock kiosk">
    <div class="kiosk-top">
      <span class="kiosk-brand"><span class="logo-mark"></span> Time clock</span>
      <span class="grow"></span>
      <button type="button" class="kiosk-ghost" onClick=${fullscreen} aria-label="Full screen"><${Icon} name="maximize-2" size=${16} /><span>Full screen</span></button>
      <button type="button" class="kiosk-ghost" onClick=${() => navigate('/schedule')} aria-label="Exit kiosk"><${Icon} name="x" size=${16} /><span>Exit</span></button>
    </div>
    <div class="kiosk-body">
      <div class="kiosk-clock">
        <div class="kiosk-time">${time}<span class="kiosk-seconds">${seconds}</span></div>
        <div class="kiosk-date">${S.orgDateLong(now)}</div>
        ${result ? html`<div class=${cx('kiosk-result', result.action === 'in' ? 'is-in' : 'is-out')} role="status">
          <${Avatar} user=${{ id: result.user_id, name: result.name, color: result.color }} size=${64} />
          <div class="kiosk-result-text">
            <strong>${result.name}</strong>
            <span>${result.action === 'in' ? 'clocked in' : 'clocked out'} at ${S.orgTime(result.at)}</span>
            ${result.action === 'out' && result.worked_minutes ? html`<span class="kiosk-result-sub">${fmtDuration(result.worked_minutes)} on this punch — have a good one!</span>` : null}
            ${result.action === 'in' && result.shift ? html`<span class="kiosk-result-sub">Shift ${S.shiftRange(result.shift)} · ${S.positionOf(result.shift.position_id)?.name || ''}</span>` : null}
          </div>
        </div>` : html`<div class="kiosk-prompt">${error ? html`<span class="kiosk-error">${error}</span>` : 'Enter your PIN to clock in or out'}</div>`}
      </div>
      <div class=${cx('kiosk-pad', error && 'is-error')}>
        <div class="kiosk-dots" aria-label=${`${pin.length} digits entered`}>
          ${Array.from({ length: Math.max(4, pin.length) }, (_, i) => html`<span key=${i} class=${cx('kiosk-dot', i < pin.length && 'is-filled')}></span>`)}
        </div>
        <div class="kiosk-keys">
          ${KEYS.map((k) => html`<button type="button" key=${k} class=${cx('kiosk-key', (k === 'clear' || k === 'back') && 'is-fn')}
            onClick=${() => press(k)} aria-label=${k === 'back' ? 'Delete' : k === 'clear' ? 'Clear' : k}>
            ${k === 'back' ? html`<${Icon} name="arrow-left" size=${22} />` : k === 'clear' ? 'Clear' : k}
          </button>`)}
        </div>
        <button type="button" class="kiosk-go" disabled=${pin.length < 4 || busy} onClick=${() => submit()}>
          ${busy ? 'Checking…' : 'Clock in / out'}
        </button>
      </div>
    </div>
    <div class="kiosk-live">
      <span class="kiosk-live-label">On the clock</span>
      ${clockedIn.length ? clockedIn.map((e) => html`<span class="kiosk-live-person" key=${e.id} title=${`since ${S.orgTime(e.clock_in)}`}>
        <${Avatar} user=${e.user_id} size=${24} /><span>${e.on_break ? 'break' : S.orgTime(e.clock_in)}</span>
      </span>`) : html`<span class="kiosk-live-empty">Nobody yet</span>`}
    </div>
  </div>`;
}
