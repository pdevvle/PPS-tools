// Event editor modal, the "which events?" question for recurring series, and the
// event popover.

import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { navigate } from '../../lib/router.js';
import { useStore, user as lookupUser } from '../../lib/store.js';
import { dateKey, fromDateKey, timeKey, addDays } from '../../lib/dates.js';
import { fmtDateLong, fmtDate, fmtTime } from '../../lib/format.js';
import { Avatar, Button, Field, Icon, IconButton, Input, Select, TextArea, Toggle, cx } from '../../ui/components.js';
import { Modal, confirmDialog, openModal, toast, toastError } from '../../ui/overlay.js';
import { pickUsers } from '../../ui/pickers.js';
import {
  RRULE_DAYS, buildRule, describeRule, parseRule, presetFor, repeatPresets, untilToDateKey,
} from './util.js';

export const REMINDERS = [
  { value: '', label: 'No reminder' }, { value: '0', label: 'At start time' }, { value: '5', label: '5 minutes before' },
  { value: '10', label: '10 minutes before' }, { value: '15', label: '15 minutes before' }, { value: '30', label: '30 minutes before' },
  { value: '60', label: '1 hour before' }, { value: '120', label: '2 hours before' }, { value: '1440', label: '1 day before' },
];

const KIND_ICONS = { shift: 'clock', job_due: 'square-kanban', operation: 'factory', timeoff: 'plane', event: 'calendar' };
export function kindIcon(kind) {
  return KIND_ICONS[kind] || 'calendar';
}

// Resolves 'one' | 'following' | 'all', or null when cancelled.
export function askScope(verb = 'Change') {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v, close) => { if (!done) { done = true; resolve(v); } close(); };
    openModal((close) => html`<${Modal} title=${`${verb} recurring event`} size="sm" onClose=${() => finish(null, close)}>
      <div class="scope-choices">
        <${Button} onClick=${() => finish('one', close)} autoFocus>This event</${Button}>
        <${Button} onClick=${() => finish('following', close)}>This and following events</${Button}>
        <${Button} onClick=${() => finish('all', close)}>All events in the series</${Button}>
      </div>
    </${Modal}>`, { size: 'sm', onClose: () => { if (!done) { done = true; resolve(null); } } });
  });
}

export function whenText(it) {
  const s = it.s || new Date(it.start);
  const e = it.e || new Date(it.end);
  if (it.all_day) {
    const a = fromDateKey(it.start_date || dateKey(s));
    const b = fromDateKey(it.end_date || dateKey(s));
    return dateKey(a) === dateKey(b) ? `${fmtDateLong(a)} · All day` : `${fmtDate(a, { weekday: true })} – ${fmtDate(b, { weekday: true })} · All day`;
  }
  if (dateKey(s) === dateKey(e) || +e - +s <= 0) return `${fmtDateLong(s)} · ${fmtTime(s)} – ${fmtTime(e)}`;
  return `${fmtDate(s, { weekday: true })} ${fmtTime(s)} – ${fmtDate(e, { weekday: true })} ${fmtTime(e)}`;
}

export async function deleteItem(it, onDone) {
  let scope = 'all';
  if (it.recurring) {
    scope = await askScope('Delete');
    if (!scope) return;
  } else if (!(await confirmDialog({ title: `Delete “${it.title}”?`, confirmLabel: 'Delete', danger: true }))) return;
  try {
    const q = new URLSearchParams({ scope });
    if (it.recurring) q.set('original_start', it.original_start);
    await api.del(`/calendar/events/${it.event_id}?${q.toString()}`);
    toast('Event deleted');
    onDone && onDone();
  } catch (err) { toastError(err); }
}

// Details popover; `onEdit(item)` opens the editor.
export function EventPopover({ it, calendars, close, onEdit, onChanged }) {
  const cal = calendars.find((c) => c.id === it.calendar_id);
  const attendees = (it.attendees || []).filter((a) => a.user_id).map((a) => a.user_id);
  return html`<div class="ev-pop">
    <div class="ev-pop-head">
      <span class="ev-pop-swatch" style=${{ background: it.color || 'var(--accent)' }}></span>
      <div class="ev-pop-title">${it.title}${it.done ? ' ✓' : ''}</div>
      ${it.can_edit && html`<${IconButton} icon="pencil" size="sm" label="Edit" onClick=${() => { close(); onEdit(it); }} />`}
      ${it.can_edit && html`<${IconButton} icon="trash" size="sm" label="Delete" onClick=${() => { close(); deleteItem(it, onChanged); }} />`}
      <${IconButton} icon="x" size="sm" label="Close" onClick=${close} />
    </div>
    <div class="ev-pop-row"><${Icon} name="clock" size=${14} /><span>${whenText(it)}</span></div>
    ${it.rrule && html`<div class="ev-pop-row"><${Icon} name="repeat" size=${14} /><span>${describeRule(it.rrule, new Date(it.start))}</span></div>`}
    ${it.location && html`<div class="ev-pop-row"><${Icon} name="map-pin" size=${14} /><span>${it.location}</span></div>`}
    ${it.subtitle && html`<div class="ev-pop-row"><${Icon} name=${kindIcon(it.kind)} size=${14} /><span>${it.subtitle}</span></div>`}
    ${cal && html`<div class="ev-pop-row"><${Icon} name="calendar" size=${14} /><span>${cal.name}</span></div>`}
    ${it.reminder_minutes !== null && it.reminder_minutes !== undefined && html`<div class="ev-pop-row"><${Icon} name="bell" size=${14} />
      <span>${REMINDERS.find((r) => r.value === String(it.reminder_minutes))?.label || `${it.reminder_minutes} minutes before`}</span></div>`}
    ${attendees.length > 0 && html`<div class="ev-pop-row ev-pop-people"><${Icon} name="users" size=${14} />
      <div class="ev-pop-people-list">${attendees.map((id) => html`<span key=${id} class="ev-pop-person"><${Avatar} user=${id} size=${18} />${lookupUser(id).name}</span>`)}</div></div>`}
    ${it.description && html`<div class="ev-pop-desc">${it.description}</div>`}
    ${it.read_only && it.url && html`<div class="ev-pop-actions"><${Button} size="sm" iconRight="arrow-right" onClick=${() => { close(); navigate(it.url); }}>
      ${{ shift: 'Open schedule', timeoff: 'Open time off', job_due: 'Open job', operation: 'Open job' }[it.kind] || 'Open'}</${Button}></div>`}
    ${it.created_by && it.kind === 'event' && html`<div class="ev-pop-foot">Added by ${lookupUser(it.created_by).name}</div>`}
  </div>`;
}

function CustomRepeat({ value, onChange, start }) {
  const toggle = (code) => onChange({ ...value, byday: value.byday.includes(code) ? value.byday.filter((c) => c !== code) : [...value.byday, code] });
  const letters = RRULE_DAYS.map((code, i) => [code, new Intl.DateTimeFormat(undefined, { weekday: 'narrow' }).format(new Date(2026, 0, 4 + i))]);
  return html`<div class="custom-repeat">
    <div class="row gap-2">
      <span>Every</span>
      <${Input} type="number" min="1" max="99" class="input-sm repeat-interval" value=${value.interval}
        onValue=${(v) => onChange({ ...value, interval: Math.max(1, Number(v) || 1) })} />
      <${Select} class="input-sm" value=${value.freq} onValue=${(freq) => onChange({ ...value, freq, byday: freq === 'WEEKLY' ? [RRULE_DAYS[start.getDay()]] : [] })}
        options=${[{ value: 'DAILY', label: value.interval > 1 ? 'days' : 'day' }, { value: 'WEEKLY', label: value.interval > 1 ? 'weeks' : 'week' },
    { value: 'MONTHLY', label: value.interval > 1 ? 'months' : 'month' }, { value: 'YEARLY', label: value.interval > 1 ? 'years' : 'year' }]} />
    </div>
    ${value.freq === 'WEEKLY' && html`<div class="weekday-toggles" role="group" aria-label="Repeat on">
      ${letters.map(([code, letter]) => html`<button type="button" key=${code} aria-pressed=${value.byday.includes(code)}
        class=${cx('weekday-toggle', value.byday.includes(code) && 'is-on')} onClick=${() => toggle(code)}>${letter}</button>`)}
    </div>`}
    <div class="repeat-ends">
      <label class="row gap-2"><input type="radio" name="ends" checked=${value.ends === 'never'} onChange=${() => onChange({ ...value, ends: 'never' })} /> Never ends</label>
      <label class="row gap-2"><input type="radio" name="ends" checked=${value.ends === 'on'} onChange=${() => onChange({ ...value, ends: 'on', until: value.until || dateKey(addDays(start, 60)) })} /> Ends on
        <${Input} type="date" class="input-sm" value=${value.until || ''} disabled=${value.ends !== 'on'} onValue=${(until) => onChange({ ...value, until })} /></label>
      <label class="row gap-2"><input type="radio" name="ends" checked=${value.ends === 'after'} onChange=${() => onChange({ ...value, ends: 'after', count: value.count || 10 })} /> Ends after
        <${Input} type="number" min="1" max="999" class="input-sm repeat-interval" value=${value.count || ''} disabled=${value.ends !== 'after'}
          onValue=${(v) => onChange({ ...value, count: Number(v) || 1 })} /> times</label>
    </div>
  </div>`;
}

function EventEditor({ item, defaults, calendars, close, onSaved }) {
  const me = useStore((s) => s.me);
  const writable = calendars.filter((c) => c.can_write);
  const start0 = item ? new Date(item.start) : defaults.start;
  const end0 = item ? new Date(item.end) : defaults.end;
  const allDay0 = item ? item.all_day : !!defaults.all_day;
  const parsed = parseRule(item?.rrule);
  const [form, setForm] = useState(() => ({
    title: item?.title || '',
    calendar_id: item?.calendar_id || defaults.calendar_id || (writable.find((c) => c.kind === 'personal' && c.is_mine) || writable[0] || {}).id,
    all_day: allDay0,
    startDate: allDay0 && item?.start_date ? item.start_date : dateKey(start0),
    startTime: timeKey(start0),
    endDate: allDay0 && item?.end_date ? item.end_date : dateKey(allDay0 ? addDays(end0, -1) : end0),
    endTime: timeKey(end0),
    repeat: presetFor(item?.rrule, start0),
    custom: {
      freq: parsed.freq, interval: parsed.interval, byday: parsed.byday.length ? parsed.byday : [RRULE_DAYS[start0.getDay()]],
      bymonthday: parsed.bymonthday, ends: parsed.count ? 'after' : parsed.until ? 'on' : 'never',
      until: untilToDateKey(parsed.until), count: parsed.count,
    },
    location: item?.location || '',
    description: item?.description || '',
    attendees: (item?.attendees || defaults.attendees || []).filter((a) => a.user_id).map((a) => a.user_id),
    reminder: item?.reminder_minutes === null || item?.reminder_minutes === undefined ? (item ? '' : '10') : String(item.reminder_minutes),
  }));
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const startDate = fromDateKey(form.startDate || dateKey(new Date()));
  const presets = repeatPresets(startDate);

  const rule = () => {
    if (form.repeat === 'none') return null;
    if (form.repeat === 'custom') return buildRule(form.custom);
    return presets.find((p) => p.id === form.repeat)?.rule || null;
  };

  const submit = async (e) => {
    e.preventDefault();
    const payload = {
      title: form.title.trim(),
      calendar_id: Number(form.calendar_id),
      all_day: form.all_day,
      location: form.location,
      description: form.description,
      attendees: form.attendees.map((id) => ({ user_id: id })),
      reminder_minutes: form.reminder === '' ? null : Number(form.reminder),
    };
    if (form.all_day) {
      payload.start_date = form.startDate;
      payload.end_date = form.endDate < form.startDate ? form.startDate : form.endDate;
    } else {
      const s = new Date(`${form.startDate}T${form.startTime || '09:00'}`);
      let en = new Date(`${form.endDate || form.startDate}T${form.endTime || '10:00'}`);
      if (en <= s) en = new Date(s.getTime() + 60 * 60000);
      payload.start_at = s.toISOString();
      payload.end_at = en.toISOString();
    }
    let scope = 'all';
    if (item?.recurring) {
      scope = await askScope('Save');
      if (!scope) return;
    }
    if (scope !== 'one') payload.rrule = rule();
    setBusy(true);
    try {
      let res;
      if (item) {
        const q = new URLSearchParams({ scope });
        // For scope=all the server shifts the whole series by how far this occurrence moved.
        if (item.recurring) q.set('original_start', item.original_start);
        res = await api.patch(`/calendar/events/${item.event_id}?${q.toString()}`, payload);
      } else {
        res = await api.post('/calendar/events', payload);
      }
      close();
      toast(item ? 'Event updated' : 'Event added');
      onSaved && onSaved(res.event);
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };

  const addPeople = (e) => pickUsers(e.currentTarget, { selected: form.attendees, multi: true, onChange: set('attendees'), title: 'Invite teammates' });
  return html`<${Modal} title=${item ? 'Edit event' : 'New event'} icon="calendar" onClose=${close} size="lg"
    footer=${html`${item?.can_edit && html`<${Button} variant="ghost" icon="trash" onClick=${() => { close(); deleteItem(item, onSaved); }}>Delete</${Button}>`}
      <span class="grow"></span>
      <${Button} onClick=${close}>Cancel</${Button}>
      <${Button} variant="primary" type="submit" form="event-form" loading=${busy}>${item ? 'Save' : 'Add event'}</${Button}>`}>
    <form id="event-form" class="stack event-form" onSubmit=${submit}>
      <input class="event-title-input" value=${form.title} placeholder="Add a title" aria-label="Title" required autoFocus
        onInput=${(e) => set('title')(e.currentTarget.value)} />
      <div class="event-when">
        <${Toggle} checked=${form.all_day} onChange=${set('all_day')} label="All day" />
        <div class="event-when-row">
          <${Input} type="date" class="input-sm" value=${form.startDate} aria-label="Start date" required
            onValue=${(v) => setForm((f) => ({ ...f, startDate: v, endDate: f.endDate < v ? v : f.endDate }))} />
          ${!form.all_day && html`<${Input} type="time" step="900" class="input-sm" value=${form.startTime} aria-label="Start time"
            onValue=${(v) => setForm((f) => {
    const s = new Date(`${f.startDate}T${f.startTime}`);
    const en = new Date(`${f.endDate}T${f.endTime}`);
    const dur = Math.max(15, (en - s) / 60000 || 60);
    const ns = new Date(`${f.startDate}T${v}`);
    const ne = new Date(ns.getTime() + dur * 60000);
    return { ...f, startTime: v, endDate: dateKey(ne), endTime: timeKey(ne) };
  })} />`}
          <span class="muted">to</span>
          ${!form.all_day && html`<${Input} type="time" step="900" class="input-sm" value=${form.endTime} aria-label="End time" onValue=${set('endTime')} />`}
          <${Input} type="date" class="input-sm" value=${form.endDate} min=${form.startDate} aria-label="End date" onValue=${set('endDate')} />
        </div>
      </div>
      <div class="form-grid">
        <${Field} label="Repeat">
          <${Select} value=${form.repeat} onValue=${set('repeat')} options=${presets.map((p) => ({ value: p.id, label: p.label }))} />
        </${Field}>
        <${Field} label="Calendar">
          <${Select} value=${String(form.calendar_id || '')} onValue=${(v) => set('calendar_id')(Number(v))}
            options=${writable.map((c) => ({ value: String(c.id), label: c.kind === 'personal' ? `${c.name} (only you)` : c.name }))} />
        </${Field}>
      </div>
      ${form.repeat === 'custom' && html`<${CustomRepeat} value=${form.custom} onChange=${set('custom')} start=${startDate} />`}
      <div class="form-grid">
        <${Field} label="Location"><${Input} value=${form.location} onValue=${set('location')} placeholder="Press room, Van 1, customer address…" /></${Field}>
        <${Field} label="Reminder"><${Select} value=${form.reminder} onValue=${set('reminder')} options=${REMINDERS} /></${Field}>
      </div>
      <${Field} label="People">
        <div class="row row-wrap gap-2">
          ${form.attendees.map((id) => html`<span class="attendee-chip" key=${id}><${Avatar} user=${id} size=${18} />${lookupUser(id).name}${id === me.id ? ' (you)' : ''}
            <button type="button" aria-label=${`Remove ${lookupUser(id).name}`} onClick=${() => set('attendees')(form.attendees.filter((x) => x !== id))}><${Icon} name="x" size=${12} /></button></span>`)}
          <${Button} size="sm" icon="user-plus" onClick=${addPeople}>Invite</${Button}>
        </div>
      </${Field}>
      <${Field} label="Notes"><${TextArea} value=${form.description} onValue=${set('description')} rows="3" placeholder="Agenda, what to bring, links…" /></${Field}>
    </form>
  </${Modal}>`;
}

export function openEditor({ item = null, defaults = {}, calendars, onSaved }) {
  openModal((close) => html`<${EventEditor} item=${item} defaults=${defaults} calendars=${calendars} close=${close} onSaved=${onSaved} />`, { size: 'lg' });
}

