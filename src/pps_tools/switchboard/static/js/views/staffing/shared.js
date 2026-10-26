// Helpers shared by the Schedule module's screens and its My Day widgets.
//
// Dates here are 'YYYY-MM-DD' keys in the shop's local time (the server converts with
// the org timezone), and shift times are local 'HH:MM' strings.

import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { getState, useStore, user as lookupUser, can } from '../../lib/store.js';
import { useFetch } from '../../lib/hooks.js';
import { fromDateKey, dateKey, addDays } from '../../lib/dates.js';
import { Button, Chip, Field, Input, Select, TextArea, Toggle, cx } from '../../ui/components.js';
import { Modal, openModal, toast, toastError } from '../../ui/overlay.js';

export const TIME_OFF_KINDS = {
  vacation: { label: 'Vacation', icon: 'plane', color: '#1971c2' },
  sick: { label: 'Sick', icon: 'stethoscope', color: '#e03131' },
  personal: { label: 'Personal', icon: 'user', color: '#7048e8' },
  unpaid: { label: 'Unpaid', icon: 'wallet', color: '#868e96' },
  other: { label: 'Other', icon: 'calendar-off', color: '#0c8599' },
};

export const STATUS = {
  clocked_in: { label: 'Clocked in', tone: 'ok' },
  on_break: { label: 'On break', tone: 'warn' },
  on_shift: { label: 'On shift', tone: 'info' },
  on_leave: { label: 'On leave', tone: 'purple' },
  off: { label: 'Off', tone: 'muted' },
};

export const REFETCH = ['schedule.changed', 'staff.changed', 'timeclock.changed', 'settings.changed'];

// -- reference data --------------------------------------------------------------------

export function usePositions() {
  return useStore((s) => s.boot.positions || []);
}

export function useLocations() {
  return useStore((s) => s.boot.locations || []);
}

export function useSkills() {
  return useStore((s) => s.boot.skills || []);
}

export function positionOf(id) {
  return (getState().boot.positions || []).find((p) => p.id === id) || null;
}

export function locationOf(id) {
  return (getState().boot.locations || []).find((l) => l.id === id) || null;
}

export function skillOf(id) {
  return (getState().boot.skills || []).find((s) => s.id === id) || null;
}

export function isManager() {
  return can('manage_staff');
}

// -- dates & times ---------------------------------------------------------------------

export function addDaysKey(key, n) {
  return dateKey(addDays(fromDateKey(key), n));
}

export function weekStartKey(key, weekStart = 0) {
  const d = fromDateKey(key);
  const diff = (d.getDay() - weekStart + 7) % 7;
  return dateKey(addDays(d, -diff));
}

// Today's date in the shop's timezone (matches the server's idea of "today").
export function todayKey() {
  const p = orgParts(Date.now());
  return `${p.year}-${p.month}-${p.day}`;
}

const dayFmt = new Intl.DateTimeFormat(undefined, { weekday: 'short' });
const monthDayFmt = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });
const longFmt = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' });

export function weekdayShort(key) {
  return dayFmt.format(fromDateKey(key));
}

export function monthDay(key) {
  return monthDayFmt.format(fromDateKey(key));
}

export function dayLabel(key) {
  return `${weekdayShort(key)} ${monthDay(key)}`;
}

export function dayLong(key) {
  return longFmt.format(fromDateKey(key));
}

export function rangeLabel(startKey, endKeyExclusive) {
  const last = addDaysKey(endKeyExclusive, -1);
  const a = fromDateKey(startKey);
  const b = fromDateKey(last);
  if (startKey === last) return monthDay(startKey);
  const year = b.getFullYear() !== new Date().getFullYear() ? `, ${b.getFullYear()}` : '';
  if (a.getMonth() === b.getMonth()) return `${monthDay(startKey)} – ${b.getDate()}${year}`;
  return `${monthDay(startKey)} – ${monthDay(last)}${year}`;
}

// '06:30' -> '6:30 AM'; compact: '6:30a', '3p'
export function fmtHHMM(hhmm, { compact = false } = {}) {
  if (!hhmm) return '';
  let [h, m] = hhmm.split(':').map(Number);
  h %= 24;
  const suffix = h < 12 ? (compact ? 'a' : ' AM') : (compact ? 'p' : ' PM');
  const hour = h % 12 || 12;
  return m ? `${hour}:${String(m).padStart(2, '0')}${suffix}` : `${hour}${suffix}`;
}

export function shiftRange(s, compact = false) {
  return `${fmtHHMM(s.start_time, { compact })}–${fmtHHMM(s.end_time, { compact })}`;
}

export function hours(minutes, digits = 1) {
  if (!minutes) return '0h';
  const h = minutes / 60;
  return `${Number.isInteger(h) ? h : h.toFixed(digits).replace(/\.0$/, '')}h`;
}

export function money(n) {
  if (n === null || n === undefined) return '';
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);
}

export function minutesOf(hhmm) {
  const [h, m] = (hhmm || '0:0').split(':').map(Number);
  return h * 60 + (m || 0);
}

export function timeOffSpan(r) {
  const days = r.start_date === r.end_date ? dayLabel(r.start_date) : `${dayLabel(r.start_date)} – ${dayLabel(r.end_date)}`;
  if (r.start_time && r.end_time) return `${days} · ${fmtHHMM(r.start_time)}–${fmtHHMM(r.end_time)}`;
  return days;
}

export function personName(id) {
  return id ? lookupUser(id).name : 'Open shift';
}

// -- the shop's timezone ----------------------------------------------------------------
//
// Punch times and the kiosk clock show the shop's wall-clock time (org.timezone), the
// same as the schedule, whatever timezone the viewer's device is set to.

const orgFormatters = new Map();
function orgFormatter(opts) {
  const tz = getState().settings['org.timezone'];
  const key = tz + JSON.stringify(opts);
  if (!orgFormatters.has(key)) {
    let f;
    try { f = new Intl.DateTimeFormat(undefined, { ...opts, timeZone: tz || undefined }); } catch { f = new Intl.DateTimeFormat(undefined, opts); }
    orgFormatters.set(key, f);
  }
  return orgFormatters.get(key);
}

export function orgTime(value) {
  if (!value) return '';
  return orgFormatter({ hour: 'numeric', minute: '2-digit' }).format(new Date(value));
}

export function orgDateLong(value = new Date()) {
  return orgFormatter({ weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }).format(new Date(value));
}

function orgParts(ts) {
  const parts = {};
  for (const p of orgFormatter({ year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(ts))) {
    parts[p.type] = p.value;
  }
  return parts;
}

// Instant -> 'YYYY-MM-DDTHH:MM' wall time in the shop's timezone (for datetime-local inputs).
export function toOrgInput(value) {
  if (!value) return '';
  const p = orgParts(new Date(value).getTime());
  return `${p.year}-${p.month}-${p.day}T${p.hour === '24' ? '00' : p.hour}:${p.minute}`;
}

// Shop wall time 'YYYY-MM-DDTHH:MM' -> ISO instant.
export function fromOrgInput(value) {
  if (!value) return null;
  const [d, t] = value.split('T');
  const [y, m, day] = d.split('-').map(Number);
  const [hh, mm] = t.split(':').map(Number);
  const wall = Date.UTC(y, m - 1, day, hh, mm);
  const offsetAt = (ts) => {
    const p = orgParts(ts);
    return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute) - Math.floor(ts / 60000) * 60000;
  };
  let ts = wall - offsetAt(wall);
  const again = wall - offsetAt(ts);
  if (again !== ts) ts = again;
  return new Date(ts).toISOString();
}

export function untilLabel(value) {
  const mins = Math.round((new Date(value).getTime() - Date.now()) / 60000);
  if (mins <= 0) return 'now';
  if (mins < 60) return `in ${mins}m`;
  const hrs = Math.round(mins / 60);
  if (hrs < 36) return `in ${hrs}h`;
  return `in ${Math.round(hrs / 24)} days`;
}

// -- small components ------------------------------------------------------------------

export function StatusChip({ status }) {
  const s = STATUS[status] || STATUS.off;
  return html`<${Chip} tone=${s.tone} size="sm">${s.label}</${Chip}>`;
}

export function PositionChip({ id, size = 'sm' }) {
  const p = positionOf(id);
  if (!p) return null;
  return html`<${Chip} color=${p.color} size=${size}>${p.name}</${Chip}>`;
}

export function KindChip({ kind }) {
  const k = TIME_OFF_KINDS[kind] || TIME_OFF_KINDS.other;
  return html`<${Chip} color=${k.color} icon=${k.icon} size="sm">${k.label}</${Chip}>`;
}

export function RequestStatus({ status }) {
  const tone = { pending: 'warn', accepted: 'info', approved: 'ok', denied: 'danger', cancelled: 'muted' }[status] || 'muted';
  const label = { accepted: 'Awaiting manager' }[status] || status[0].toUpperCase() + status.slice(1);
  return html`<${Chip} tone=${tone} size="sm">${label}</${Chip}>`;
}

export function useStaffCounts() {
  return useFetch('/staffing/counts', { refetchOn: ['schedule.changed', 'badges.changed', 'timeclock.changed'] });
}

// -- time-off request form ----------------------------------------------------------------

function TimeOffForm({ close, userId, onDone }) {
  const me = getState().me;
  const manager = isManager();
  const people = getState().users.filter((u) => u.is_active);
  const today = todayKey();
  const [form, setForm] = useState({
    user_id: userId || me.id, kind: 'vacation', start_date: today, end_date: today, partial: false,
    start_time: '13:00', end_time: '17:00', reason: '',
  });
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setForm((f) => {
    const next = { ...f, [k]: v };
    if (k === 'start_date' && next.end_date < v) next.end_date = v;
    if (next.start_date !== next.end_date) next.partial = false;
    return next;
  });
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const payload = {
        user_id: Number(form.user_id), kind: form.kind, start_date: form.start_date, end_date: form.end_date,
        reason: form.reason,
      };
      if (form.partial) Object.assign(payload, { start_time: form.start_time, end_time: form.end_time });
      const res = await api.post('/time-off', payload);
      toast(res.item.status === 'approved' ? 'Time off added' : 'Request sent to your managers');
      onDone && onDone(res.item);
      close();
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  };
  const sameDay = form.start_date === form.end_date;
  return html`<${Modal} title="Request time off" icon="plane" onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}>
      <${Button} variant="primary" type="submit" form="timeoff-form" loading=${busy}>${manager && Number(form.user_id) !== me.id ? 'Add time off' : 'Send request'}</${Button}>`}>
    <form id="timeoff-form" class="stack" onSubmit=${submit}>
      ${manager && html`<${Field} label="Person">
        <${Select} value=${String(form.user_id)} onValue=${set('user_id')} options=${people.map((u) => ({ value: String(u.id), label: u.name }))} />
      </${Field}>`}
      <${Field} label="Type">
        <div class="st-kind-choices">
          ${Object.entries(TIME_OFF_KINDS).map(([k, v]) => html`<button type="button" key=${k}
            class=${cx('st-kind-choice', form.kind === k && 'is-active')} style=${{ '--kind': v.color }} onClick=${() => set('kind')(k)}>
            ${v.label}</button>`)}
        </div>
      </${Field}>
      <div class="form-grid">
        <${Field} label="First day"><${Input} type="date" value=${form.start_date} onValue=${set('start_date')} required /></${Field}>
        <${Field} label="Last day"><${Input} type="date" value=${form.end_date} min=${form.start_date} onValue=${set('end_date')} required /></${Field}>
      </div>
      ${sameDay && html`<${Toggle} checked=${form.partial} onChange=${set('partial')} label="Part of the day" />`}
      ${sameDay && form.partial && html`<div class="form-grid">
        <${Field} label="From"><${Input} type="time" value=${form.start_time} onValue=${set('start_time')} /></${Field}>
        <${Field} label="Until"><${Input} type="time" value=${form.end_time} onValue=${set('end_time')} /></${Field}>
      </div>`}
      <${Field} label="Note for your manager" hint="Optional">
        <${TextArea} value=${form.reason} onValue=${set('reason')} rows="2" placeholder="e.g. Family trip" />
      </${Field}>
    </form>
  </${Modal}>`;
}

export function requestTimeOff({ userId, onDone } = {}) {
  openModal((close) => html`<${TimeOffForm} close=${close} userId=${userId} onDone=${onDone} />`);
}
