// The weekly schedule: people down the side, days across, shifts in the cells.
// Managers build it (click a cell to add, click a shift to edit, drag to move, Alt/Option-drag
// to copy) and publish it; everyone else sees the published week and can ask to swap,
// drop or pick up shifts. Phones get a one-day list instead of the grid.

import { html, useMemo, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch, useIsMobile, useLocalStorage } from '../../lib/hooks.js';
import { navigate, setQuery } from '../../lib/router.js';
import { useStore, user as lookupUser, getState } from '../../lib/store.js';
import {
  Avatar, Banner, Button, Chip, Empty, ErrorBox, Field, Icon, IconButton, Input, Loading, PageHeader, Segmented,
  Select, TextArea, cx,
} from '../../ui/components.js';
import { SidebarButton } from '../../ui/layout.js';
import { Modal, confirmDialog, openModal, promptDialog, showMenu, showPopover, toast, toastError } from '../../ui/overlay.js';
import * as S from './shared.js';

const BREAKS = [0, 15, 30, 45, 60];

function groupKey(person, groupBy) {
  if (groupBy === 'location') return person.profile.default_location_id || 0;
  return person.profile.default_position_id || person.position_ids[0] || 0;
}

// Availability rows use Monday = 0; JS dates use Sunday = 0.
const pyWeekday = (key) => (new Date(key + 'T00:00').getDay() + 6) % 7;

function unavailability(rows, day) {
  if (!rows || !rows.length) return null;
  const wd = pyWeekday(day);
  const blocked = rows.filter((r) => r.weekday === wd && r.kind === 'unavailable');
  if (blocked.length) {
    const r = blocked[0];
    if (r.end_time === '24:00' || r.end_time === '23:59') return `Unavailable after ${S.fmtHHMM(r.start_time)}`;
    if (r.start_time === '00:00') return `Unavailable until ${S.fmtHHMM(r.end_time)}`;
    return `Unavailable ${S.fmtHHMM(r.start_time, { compact: true })}–${S.fmtHHMM(r.end_time, { compact: true })}`;
  }
  const hasWindows = rows.some((r) => r.kind !== 'unavailable');
  if (hasWindows && !rows.some((r) => r.weekday === wd && r.kind !== 'unavailable')) return 'Not available';
  return null;
}

function availabilityHint(rows, day) {
  if (!rows) return null;
  const wd = pyWeekday(day);
  const windows = rows.filter((r) => r.weekday === wd && r.kind !== 'unavailable');
  if (!windows.length) return null;
  return 'Available ' + windows.map((r) => `${S.fmtHHMM(r.start_time, { compact: true })}–${S.fmtHHMM(r.end_time, { compact: true })}`).join(', ');
}

// -- shift form (quick add & edit) --------------------------------------------------------

function ShiftForm({ shift, person, day, people, templates, close, mode }) {
  const positions = S.usePositions().filter((p) => p.is_active || (shift && p.id === shift.position_id));
  const locations = S.useLocations().filter((l) => l.is_active || (shift && l.id === shift.location_id));
  const defaultPos = shift ? shift.position_id : person ? (person.profile.default_position_id || person.position_ids[0] || '') : '';
  const defaultLoc = shift ? shift.location_id : person ? (person.profile.default_location_id || locations[0]?.id || '') : (locations[0]?.id || '');
  const [form, setForm] = useState(() => ({
    user_id: shift ? (shift.user_id || '') : person ? person.user.id : '',
    date: shift ? shift.date : day,
    start_time: shift ? shift.start_time : '08:00',
    end_time: shift ? shift.end_time : '16:30',
    break_minutes: shift ? shift.break_minutes : 30,
    position_id: defaultPos || '',
    location_id: defaultLoc || '',
    notes: shift ? shift.notes || '' : '',
  }));
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const payload = (extra = {}) => ({
    user_id: form.user_id ? Number(form.user_id) : null,
    date: form.date, start_time: form.start_time, end_time: form.end_time,
    break_minutes: Number(form.break_minutes) || 0,
    position_id: form.position_id ? Number(form.position_id) : null,
    location_id: form.location_id ? Number(form.location_id) : null,
    notes: form.notes, ...extra,
  });
  const run = async (fn, message) => {
    setBusy(true);
    try {
      const res = await fn();
      const created = res && (res.item || (res.items && res.items[0]));
      const warn = created && (created.conflicts || []).filter((c) => c.severity === 'error');
      if (warn && warn.length) toast(warn[0].message, { tone: 'danger', icon: 'triangle-alert' });
      else if (message) toast(message);
      close();
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  };
  const create = (extra) => run(() => api.post('/shifts', payload({ status: 'draft', ...extra })), null);
  const save = (e) => {
    e && e.preventDefault();
    if (mode === 'edit') {
      const notifies = shift.status === 'published' && (shift.user_id || form.user_id);
      return run(() => api.patch(`/shifts/${shift.id}`, payload()), notifies ? 'Saved — they were notified' : 'Saved');
    }
    return create();
  };
  const remove = async () => {
    const published = shift.status === 'published' && shift.user_id;
    if (!(await confirmDialog({
      title: 'Delete this shift?',
      message: published ? `${lookupUser(shift.user_id).name} will be told it was removed.` : undefined,
      confirmLabel: 'Delete', danger: true,
    }))) return;
    run(() => api.del(`/shifts/${shift.id}`), 'Shift deleted');
  };
  const useTemplate = (t) => create({
    start_time: t.start_time, end_time: t.end_time, break_minutes: t.break_minutes,
    position_id: t.position_id || (form.position_id ? Number(form.position_id) : null),
    location_id: t.location_id || (form.location_id ? Number(form.location_id) : null),
  });
  const who = form.user_id ? lookupUser(Number(form.user_id)).name : 'Open shift';
  const conflicts = shift ? shift.conflicts || [] : [];
  return html`<form class="sg-form" onSubmit=${save}>
    <div class="sg-form-head">
      ${form.user_id ? html`<${Avatar} user=${Number(form.user_id)} size=${26} />` : html`<span class="sg-open-avatar"><${Icon} name="user-plus" size=${14} /></span>`}
      <div class="stack-0"><strong>${who}</strong><span class="muted text-sm">${S.dayLong(form.date)}</span></div>
      ${shift && html`<${Chip} tone=${shift.status === 'published' ? 'ok' : 'muted'} size="sm">${shift.status === 'published' ? 'Published' : 'Draft'}</${Chip}>`}
    </div>
    ${conflicts.length > 0 && html`<ul class="sg-conflicts">
      ${conflicts.map((c) => html`<li class=${cx('sg-conflict', `is-${c.severity}`)}><${Icon} name=${c.severity === 'error' ? 'octagon-alert' : 'triangle-alert'} size=${13} />${c.message}</li>`)}
    </ul>`}
    ${mode === 'add' && templates && templates.length > 0 && html`<div class="sg-templates">
      ${templates.map((t) => html`<button type="button" key=${t.id} class="sg-template" disabled=${busy} onClick=${() => useTemplate(t)}>
        <span class="strong">${t.name}</span><span class="muted text-sm">${S.fmtHHMM(t.start_time)}–${S.fmtHHMM(t.end_time)}${t.break_minutes ? ` · ${t.break_minutes}m break` : ''}</span>
      </button>`)}
    </div>`}
    ${(mode === 'edit' || people) && html`<div class="form-grid">
      <${Field} label="Person">
        <${Select} value=${String(form.user_id)} onValue=${set('user_id')}
          options=${[{ value: '', label: 'Open shift (anyone can pick up)' }, ...(people || []).map((p) => ({ value: String(p.user.id), label: p.user.name }))]} />
      </${Field}>
      <${Field} label="Date"><${Input} type="date" value=${form.date} onValue=${set('date')} required /></${Field}>
    </div>`}
    <div class="sg-form-times">
      <${Field} label="Start"><${Input} type="time" step="900" value=${form.start_time} onValue=${set('start_time')} required /></${Field}>
      <${Field} label="End"><${Input} type="time" step="900" value=${form.end_time} onValue=${set('end_time')} required /></${Field}>
      <${Field} label="Break">
        <${Select} value=${String(form.break_minutes)} onValue=${set('break_minutes')}
          options=${[...new Set([...BREAKS, Number(form.break_minutes) || 0])].sort((a, b) => a - b).map((b) => ({ value: String(b), label: b ? `${b} min` : 'None' }))} />
      </${Field}>
    </div>
    <div class="form-grid">
      <${Field} label="Position">
        <${Select} value=${String(form.position_id)} onValue=${set('position_id')} placeholder="Any position"
          options=${positions.map((p) => ({ value: String(p.id), label: p.name }))} />
      </${Field}>
      <${Field} label="Location">
        <${Select} value=${String(form.location_id)} onValue=${set('location_id')} placeholder="—"
          options=${locations.map((l) => ({ value: String(l.id), label: l.name }))} />
      </${Field}>
    </div>
    <${Field} label="Notes"><${TextArea} rows="2" value=${form.notes} onValue=${set('notes')} placeholder="e.g. Run the Saguaro cards first" /></${Field}>
    ${shift && shift.job_id && html`<a class="sg-job-link" href=${`/jobs/${shift.job_id}`}><${Icon} name="square-kanban" size=${14} /> Job #${shift.job_id}</a>`}
    <div class="sg-form-actions">
      ${mode === 'edit' && html`<${IconButton} icon="trash" label="Delete shift" onClick=${remove} />`}
      ${mode === 'edit' && shift.status === 'draft' && html`<${Button} size="sm" icon="send" onClick=${() => run(() => api.patch(`/shifts/${shift.id}`, payload({ status: 'published' })), 'Published')}>Publish</${Button}>`}
      <span class="grow"></span>
      <${Button} size="sm" onClick=${close}>Cancel</${Button}>
      <${Button} size="sm" variant="primary" type="submit" loading=${busy}>${mode === 'edit' ? 'Save' : 'Add shift'}</${Button}>
    </div>
  </form>`;
}

function openShiftForm(anchor, props) {
  if (!anchor) {
    openModal((close) => html`<${Modal} title=${props.mode === 'edit' ? 'Edit shift' : 'Add shift'} onClose=${close}>
      <${ShiftForm} ...${props} close=${close} />
    </${Modal}>`);
    return;
  }
  showPopover(anchor, (close) => html`<${ShiftForm} ...${props} close=${close} />`, { width: 380, placement: 'right-start', class: 'sg-popover' });
}

// -- staff self-service ---------------------------------------------------------------------

function SwapForm({ shift, close }) {
  const me = getState().me;
  const coworkers = getState().users.filter((u) => u.is_active && u.id !== me.id);
  const [target, setTarget] = useState('');
  const [theirShift, setTheirShift] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const theirs = useFetch(target ? '/shifts' : null, {
    query: { user_id: target, start: S.todayKey(), end: S.addDaysKey(S.todayKey(), 28), status: 'published' },
  });
  const upcoming = ((theirs.data && theirs.data.items) || []).filter((s) => s.user_id === Number(target) && s.start_at > new Date().toISOString());
  const submit = async (e) => {
    e.preventDefault();
    if (!target) return;
    setBusy(true);
    try {
      await api.post('/shift-requests', { kind: 'swap', shift_id: shift.id, target_user_id: Number(target),
        target_shift_id: theirShift ? Number(theirShift) : null, note });
      toast(`Asked ${lookupUser(Number(target)).name}`);
      close();
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  return html`<${Modal} title="Ask to swap" icon="arrow-right-left" onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="swap-form" loading=${busy} disabled=${!target}>Send request</${Button}>`}>
    <form id="swap-form" class="stack" onSubmit=${submit}>
      <div class="sg-swap-shift"><${Icon} name="calendar-clock" size=${16} /><span><strong>Your shift:</strong> ${S.dayLabel(shift.date)}, ${S.shiftRange(shift)}</span></div>
      <${Field} label="Who should take it?">
        <${Select} value=${target} onValue=${(v) => { setTarget(v); setTheirShift(''); }} placeholder="Choose a coworker"
          options=${coworkers.map((u) => ({ value: String(u.id), label: u.name }))} />
      </${Field}>
      ${target && html`<${Field} label="In exchange for" hint="Or leave it as a favor — they just take your shift">
        <${Select} value=${theirShift} onValue=${setTheirShift} placeholder="Nothing — they just take my shift"
          options=${upcoming.map((s) => ({ value: String(s.id), label: `${S.dayLabel(s.date)}, ${S.shiftRange(s)}` }))} />
      </${Field}>`}
      <${Field} label="Note"><${TextArea} rows="2" value=${note} onValue=${setNote} placeholder="e.g. Doctor's appointment" /></${Field}>
    </form>
  </${Modal}>`;
}

async function requestDrop(shift) {
  const note = await promptDialog({ title: 'Ask to drop this shift', label: `Why can't you work ${S.dayLabel(shift.date)}, ${S.shiftRange(shift)}?`,
    placeholder: 'A manager has to approve; the shift becomes open for others.', confirmLabel: 'Send request', multiline: true });
  if (note === null) return;
  try {
    await api.post('/shift-requests', { kind: 'drop', shift_id: shift.id, note });
    toast('Request sent to your managers');
  } catch (err) { toastError(err); }
}

async function pickUp(shift) {
  try {
    const res = await api.post(`/shifts/${shift.id}/pickup`);
    toast(res.request.status === 'approved' ? "It's yours!" : 'Pickup requested — a manager will confirm');
  } catch (err) { toastError(err); }
}

function staffShiftMenu(anchor, shift, me, pending) {
  const future = shift.start_at > new Date().toISOString();
  const items = [{ header: `${S.dayLabel(shift.date)} · ${S.shiftRange(shift)}` }];
  if (!future) items.push({ label: 'This shift has started', icon: 'clock', disabled: true });
  else if (pending) items.push({ label: 'You have a request open — see Requests', icon: 'arrow-right-left', onSelect: () => navigate('/schedule/requests') });
  else if (shift.user_id === me.id) {
    items.push({ label: 'Ask someone to swap…', icon: 'arrow-right-left', onSelect: () => openModal((close) => html`<${SwapForm} shift=${shift} close=${close} />`) });
    items.push({ label: 'Ask to drop this shift…', icon: 'calendar-x', onSelect: () => requestDrop(shift) });
  } else if (!shift.user_id) {
    items.push({ label: 'Pick up this shift', icon: 'user-plus', onSelect: () => pickUp(shift) });
  }
  if (shift.notes) items.push({ divider: true }, { label: shift.notes, icon: 'sticky-note', disabled: true });
  showMenu(anchor, items, { width: 260 });
}

// -- grid pieces -------------------------------------------------------------------------------

function ShiftChip({ shift, manager, me, pendingIds, onOpen, onDragStart }) {
  const pos = S.positionOf(shift.position_id);
  const errors = (shift.conflicts || []).filter((c) => c.severity === 'error');
  const warnings = (shift.conflicts || []).filter((c) => c.severity !== 'error');
  const tip = (shift.conflicts || []).map((c) => c.message).join('\n');
  return html`<div
    class=${cx('sg-shift', shift.status === 'draft' && 'is-draft', errors.length && 'has-error', !errors.length && warnings.length && 'has-warning',
    shift.user_id === me.id && 'is-mine', !shift.user_id && 'is-open')}
    style=${{ '--pos': pos ? pos.color : 'var(--text-3)' }}
    draggable=${manager ? 'true' : 'false'}
    onDragStart=${(e) => onDragStart(e, shift)}
    onClick=${(e) => { e.stopPropagation(); onOpen(e.currentTarget, shift); }}
    title=${tip || undefined}
    role="button"
    tabIndex="0"
    onKeyDown=${(e) => { if (e.key === 'Enter') { e.preventDefault(); onOpen(e.currentTarget, shift); } }}
  >
    <div class="sg-shift-time">
      <span>${S.shiftRange(shift, true)}</span>
      ${(errors.length || warnings.length) ? html`<${Icon} name=${errors.length ? 'octagon-alert' : 'triangle-alert'} size=${12} class="sg-shift-alert" />` : null}
      ${pendingIds.has(shift.id) && html`<${Icon} name="arrow-right-left" size=${12} class="sg-shift-swap" />`}
    </div>
    <div class="sg-shift-meta">
      <span class="truncate">${pos ? pos.name : 'Shift'}</span>
      ${shift.break_minutes ? html`<span>· ${shift.break_minutes}m</span>` : null}
      ${shift.job_id ? html`<span class="sg-shift-job">#${shift.job_id}</span>` : null}
    </div>
  </div>`;
}

function TimeOffBlock({ r }) {
  const kind = S.TIME_OFF_KINDS[r.kind] || S.TIME_OFF_KINDS.other;
  const partial = r.start_time && r.end_time ? ` ${S.fmtHHMM(r.start_time, { compact: true })}–${S.fmtHHMM(r.end_time, { compact: true })}` : '';
  return html`<div class=${cx('sg-timeoff', r.status === 'pending' && 'is-pending')} style=${{ '--kind': kind.color }}
    title=${r.status === 'pending' ? 'Requested, not approved yet' : 'Approved time off'}>
    <${Icon} name=${kind.icon} size=${12} />${r.status === 'pending' ? 'Requested: ' : ''}${kind.label}${partial}
  </div>`;
}

// -- the week -----------------------------------------------------------------------------------

export function WeekGrid({ route }) {
  const me = useStore((s) => s.me);
  const weekStart = useStore((s) => s.settings['org.week_start']) || 0;
  const manager = S.isManager();
  const isMobile = useIsMobile();
  const [groupBy, setGroupBy] = useLocalStorage('sb.schedule.group', 'position');
  // Any date in the week works in the URL (e.g. from a notification); show its whole week.
  const week = route.query.week ? S.weekStartKey(route.query.week, weekStart) : null;
  const positionFilter = route.query.position ? Number(route.query.position) : null;
  const locationFilter = route.query.location ? Number(route.query.location) : null;

  const shiftsRes = useFetch('/shifts', { query: { start: week }, refetchOn: S.REFETCH });
  const staffRes = useFetch('/staff', { query: { week }, refetchOn: ['staff.changed', 'timeclock.changed', 'schedule.changed'] });
  const templatesRes = useFetch(manager ? '/shift-templates' : null, { refetchOn: ['schedule.changed'] });
  const last = useRef({});
  if (shiftsRes.data) last.current.shifts = shiftsRes.data;
  if (staffRes.data) last.current.staff = staffRes.data;
  const data = shiftsRes.data || last.current.shifts;
  const staff = staffRes.data || last.current.staff;
  const dragRef = useRef(null);
  const [dropKey, setDropKey] = useState(null);
  const [mobileDay, setMobileDay] = useState(null);

  const model = useMemo(() => {
    if (!data || !staff) return null;
    let items = data.items;
    if (positionFilter) items = items.filter((s) => s.position_id === positionFilter);
    if (locationFilter) items = items.filter((s) => s.location_id === locationFilter);
    const cells = new Map();
    const open = new Map();
    for (const s of items) {
      if (!s.user_id) {
        if (!open.has(s.date)) open.set(s.date, []);
        open.get(s.date).push(s);
      } else {
        const k = `${s.user_id}|${s.date}`;
        if (!cells.has(k)) cells.set(k, []);
        cells.get(k).push(s);
      }
    }
    const withShifts = new Set(items.filter((s) => s.user_id).map((s) => s.user_id));
    let people = staff.items.filter((p) => p.user.is_active && (p.profile.is_schedulable || withShifts.has(p.user.id)));
    if (positionFilter) people = people.filter((p) => p.position_ids.includes(positionFilter) || withShifts.has(p.user.id));
    if (locationFilter) people = people.filter((p) => p.profile.default_location_id === locationFilter || withShifts.has(p.user.id));
    const refs = groupBy === 'location' ? (getState().boot.locations || []) : (getState().boot.positions || []);
    const groups = new Map();
    for (const p of people) {
      const key = groupKey(p, groupBy);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(p);
    }
    const ordered = [...groups.entries()]
      .map(([key, list]) => ({
        key,
        ref: refs.find((r) => r.id === key) || null,
        people: list.sort((a, b) => a.user.name.localeCompare(b.user.name)),
      }))
      .sort((a, b) => (a.ref ? refs.indexOf(a.ref) : 999) - (b.ref ? refs.indexOf(b.ref) : 999));
    const timeOff = new Map();
    for (const r of data.time_off) {
      if (!timeOff.has(r.user_id)) timeOff.set(r.user_id, []);
      timeOff.get(r.user_id).push(r);
    }
    const pending = new Set();
    for (const r of data.requests || []) { pending.add(r.shift_id); if (r.target_shift_id) pending.add(r.target_shift_id); }
    return { cells, open, groups: ordered, timeOff, pending, staffById: new Map(staff.items.map((p) => [p.user.id, p])) };
  }, [data, staff, groupBy, positionFilter, locationFilter]);

  if (!data && (shiftsRes.error || staffRes.error)) {
    return html`<${PageHeader} leading=${html`<${SidebarButton} />`} title="Schedule" /><${ErrorBox} error=${shiftsRes.error || staffRes.error} retry=${() => { shiftsRes.reload(); staffRes.reload(); }} />`;
  }
  if (!data || !staff || !model) return html`<${PageHeader} leading=${html`<${SidebarButton} />`} title="Schedule" /><${Loading} />`;

  const days = data.days;
  const goWeek = (delta) => setQuery({ week: S.addDaysKey(data.start, delta * 7) }, { replace: false });
  const isThisWeek = days.includes(data.today);
  const people = model.groups.flatMap((g) => g.people);
  const loading = shiftsRes.loading || staffRes.loading;

  const openShift = (anchor, shift) => {
    if (manager) {
      openShiftForm(isMobile ? null : anchor, { shift, mode: 'edit', people, templates: [] });
    } else {
      staffShiftMenu(anchor, shift, me, model.pending.has(shift.id));
    }
  };
  const addAt = (anchor, person, day) => {
    if (!manager) return;
    openShiftForm(isMobile ? null : anchor, { person, day, mode: 'add', templates: templatesRes.data?.items || [], people: isMobile ? people : null });
  };
  const onDragStart = (e, shift) => {
    if (!manager) { e.preventDefault(); return; }
    dragRef.current = shift;
    e.dataTransfer.effectAllowed = 'copyMove';
    e.dataTransfer.setData('text/plain', String(shift.id));
  };
  const onDragOver = (e, key) => {
    if (!dragRef.current) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = e.altKey ? 'copy' : 'move';
    if (dropKey !== key) setDropKey(key);
  };
  const onDrop = async (e, userId, day) => {
    e.preventDefault();
    const s = dragRef.current;
    dragRef.current = null;
    setDropKey(null);
    if (!s) return;
    const copy = e.altKey;
    if (!copy && (s.user_id || null) === (userId || null) && s.date === day) return;
    try {
      if (copy) {
        await api.post('/shifts', {
          user_id: userId || null, date: day, start_time: s.start_time, end_time: s.end_time, break_minutes: s.break_minutes,
          position_id: s.position_id, location_id: s.location_id, notes: s.notes, status: 'draft',
        });
        toast('Shift copied');
      } else {
        await api.patch(`/shifts/${s.id}`, { user_id: userId || null, date: day });
      }
      shiftsRes.reload({ quiet: true });
    } catch (err) { toastError(err); }
  };

  const publish = async () => {
    const n = data.drafts;
    if (!(await confirmDialog({
      title: `Publish ${n} shift${n === 1 ? '' : 's'}?`,
      message: `Everyone scheduled for ${S.rangeLabel(data.start, data.end)} gets a notification, and the shifts become visible to staff.`,
      confirmLabel: 'Publish',
    }))) return;
    try {
      const res = await api.post('/shifts/publish', { start: data.start, end: data.end });
      toast(`Published ${res.published} shifts · ${res.people} people notified`, { tone: 'success' });
    } catch (err) { toastError(err); }
  };
  const copyLastWeek = async () => {
    const from = S.addDaysKey(data.start, -7);
    if (!(await confirmDialog({
      title: 'Copy last week?',
      message: `Shifts from ${S.rangeLabel(from, data.start)} are added to this week as drafts. People who are already booked at those times are skipped.`,
      confirmLabel: 'Copy shifts',
    }))) return;
    try {
      const res = await api.post('/shifts/copy-week', { from_week: from, to_week: data.start });
      toast(`Copied ${res.created} shift${res.created === 1 ? '' : 's'}${res.skipped ? ` · ${res.skipped} skipped` : ''}`);
    } catch (err) { toastError(err); }
  };

  const myTotal = data.totals[me.id];
  const subtitle = [
    S.rangeLabel(data.start, data.end),
    manager && data.drafts ? `${data.drafts} draft${data.drafts === 1 ? '' : 's'}` : null,
    !manager && myTotal ? `you: ${S.hours(myTotal.minutes)}` : null,
  ].filter(Boolean).join(' · ');

  const header = html`<${PageHeader} leading=${html`<${SidebarButton} />`} title="Schedule" subtitle=${subtitle}
    actions=${html`
      <div class="btn-group">
        <${Button} size="sm" icon="chevron-left" onClick=${() => goWeek(-1)} aria-label="Previous week" />
        <${Button} size="sm" icon="calendar-check" onClick=${() => setQuery({ week: null }, { replace: false })} disabled=${isThisWeek}>Today</${Button}>
        <${Button} size="sm" icon="chevron-right" onClick=${() => goWeek(1)} aria-label="Next week" />
      </div>
      ${!isMobile && html`<${Segmented} size="sm" value=${groupBy} onChange=${setGroupBy}
        options=${[{ value: 'position', label: 'By position' }, { value: 'location', label: 'By location' }]} />`}
      ${manager && !isMobile && html`<${Button} size="sm" icon="copy" onClick=${copyLastWeek}>Copy last week</${Button}>`}
      ${!isMobile && html`<${IconButton} icon="printer" label="Print" onClick=${() => window.print()} />`}
      ${manager && html`<${Button} size="sm" variant="primary" icon="send" disabled=${!data.drafts} onClick=${publish}>
        Publish${data.drafts ? ` (${data.drafts})` : ''}</${Button}>`}
    `} />`;

  const banner = manager && data.drafts > 0 ? html`<${Banner} tone="warn" icon="eye-off" class="sg-banner">
    ${data.drafts} draft shift${data.drafts === 1 ? ' isn’t' : 's aren’t'} visible to the team yet. Publish when the week looks right.
  </${Banner}>` : null;

  if (isMobile) {
    const day = mobileDay && days.includes(mobileDay) ? mobileDay : (isThisWeek ? data.today : days[0]);
    return html`${header}
      <div class="sg-mobile">
        ${banner}
        <div class="sg-day-tabs" role="tablist">
          ${days.map((d) => html`<button type="button" key=${d} role="tab" class=${cx('sg-day-tab', d === day && 'is-active', d === data.today && 'is-today')}
            onClick=${() => setMobileDay(d)}>
            <span>${S.weekdayShort(d)}</span><strong>${Number(d.slice(8))}</strong>
            ${data.day_totals[d] ? html`<span class="sg-day-tab-count">${data.day_totals[d].shifts}</span>` : null}
          </button>`)}
        </div>
        <${DayList} day=${day} data=${data} model=${model} me=${me} manager=${manager} onOpen=${openShift}
          onAdd=${() => addAt(null, null, day)} />
      </div>`;
  }

  const cols = `minmax(176px, 210px) repeat(${days.length}, minmax(104px, 1fr))`;
  const renderCell = (person, day) => {
    const uid = person ? person.user.id : null;
    const key = `${uid || 'open'}|${day}`;
    const list = person ? (model.cells.get(`${uid}|${day}`) || []) : (model.open.get(day) || []);
    const off = person ? (model.timeOff.get(uid) || []).filter((r) => r.start_date <= day && r.end_date >= day) : [];
    const unavailable = person ? unavailability(data.availability[String(uid)], day) : null;
    const hint = person && !list.length ? availabilityHint(data.availability[String(uid)], day) : null;
    return html`<div
      key=${key}
      class=${cx('sg-cell', day === data.today && 'is-today', unavailable && 'is-unavailable', dropKey === key && 'is-drop',
      manager && 'is-editable', !person && 'sg-cell-open')}
      onClick=${(e) => addAt(e.currentTarget, person, day)}
      onDragOver=${(e) => onDragOver(e, key)}
      onDragLeave=${() => dropKey === key && setDropKey(null)}
      onDrop=${(e) => onDrop(e, uid, day)}
      title=${manager && !list.length ? 'Click to add a shift' : undefined}
    >
      ${off.map((r) => html`<${TimeOffBlock} key=${'off' + r.id} r=${r} />`)}
      ${unavailable && html`<div class="sg-unavailable">${unavailable}</div>`}
      ${list.map((s) => html`<${ShiftChip} key=${s.id} shift=${s} manager=${manager} me=${me} pendingIds=${model.pending}
        onOpen=${openShift} onDragStart=${onDragStart} />`)}
      ${manager && !list.length && !off.length && html`<span class="sg-cell-add">${hint ? html`<span class="sg-cell-hint">${hint}</span>` : html`<${Icon} name="plus" size=${14} />`}</span>`}
    </div>`;
  };

  const ot = data.overtime_weekly_hours || 40;
  return html`${header}
    <div class=${cx('sg-wrap', loading && 'is-loading')}>
      ${banner}
      <div class="sg-scroll">
        <div class="sg-grid" style=${{ gridTemplateColumns: cols }} onDragEnd=${() => { dragRef.current = null; setDropKey(null); }}>
          <div class="sg-corner">
            <span class="muted text-sm">${people.length} people</span>
          </div>
          ${days.map((d) => html`<div key=${'h' + d} class=${cx('sg-dayhead', d === data.today && 'is-today')}>
            <span class="sg-dayhead-name">${S.weekdayShort(d)}</span>
            <span class="sg-dayhead-date">${S.monthDay(d)}</span>
          </div>`)}

          <div class="sg-rowhead sg-rowhead-open">
            <span class="sg-open-avatar"><${Icon} name="user-plus" size=${14} /></span>
            <div class="stack-0"><strong>Open shifts</strong><span class="muted text-xs">${manager ? 'Anyone qualified can pick these up' : 'Tap one to pick it up'}</span></div>
          </div>
          ${days.map((d) => renderCell(null, d))}

          ${model.groups.map((g) => html`
            <div class="sg-group" key=${'g' + g.key} style=${{ gridColumn: `1 / span ${days.length + 1}` }}>
              <div class="sg-group-label">
                ${g.ref && g.ref.color && html`<span class="sg-group-dot" style=${{ background: g.ref.color }}></span>`}
                <span>${g.ref ? g.ref.name : groupBy === 'location' ? 'No location' : 'Other'}</span>
                <span class="muted">${g.people.length}</span>
              </div>
            </div>
            ${g.people.map((p) => {
    const t = data.totals[String(p.user.id)];
    const over = t && t.overtime_minutes > 0;
    const target = p.profile.target_hours_week;
    return html`
                <div key=${'r' + p.user.id} class=${cx('sg-rowhead', p.user.id === me.id && 'is-me')}>
                  <${Avatar} user=${p.user} size=${28} />
                  <div class="sg-rowhead-text">
                    <a class="sg-person" href=${`/schedule/people/${p.user.id}`} onClick=${(e) => e.stopPropagation()}>${p.user.name}</a>
                    <span class="sg-person-stats">
                      <span class=${cx(over && 'is-over')} title=${over ? `${S.hours(t.overtime_minutes)} over ${ot}h` : undefined}>
                        ${S.hours(t ? t.minutes : 0)}${target ? html`<span class="muted"> / ${target}h</span>` : null}
                      </span>
                      ${over && html`<${Chip} tone="warn" size="sm">${S.hours(t.overtime_minutes)} OT</${Chip}>`}
                      ${data.can_view_pay && t && t.cost ? html`<span class="muted">${S.money(t.cost)}</span>` : null}
                    </span>
                  </div>
                  ${p.status !== 'off' && html`<span class=${cx('sg-live', `is-${p.status}`)} title=${S.STATUS[p.status]?.label}></span>`}
                </div>
                ${days.map((d) => renderCell(p, d))}
              `;
  })}
          `)}

          <div class="sg-foot sg-foot-label">Totals</div>
          ${days.map((d) => {
    const t = data.day_totals[d];
    return html`<div key=${'f' + d} class="sg-foot sg-foot-day">
              ${t ? html`<strong>${S.hours(t.minutes)}</strong><span class="muted">${t.shifts} shift${t.shifts === 1 ? '' : 's'}${t.open ? ` · ${t.open} open` : ''}</span>
                ${data.can_view_pay && t.cost ? html`<span class="muted">${S.money(t.cost)}</span>` : null}` : html`<span class="muted">—</span>`}
            </div>`;
  })}
        </div>
      </div>
      ${!people.length && html`<${Empty} icon="users" title="Nobody to schedule"
        action=${manager ? html`<${Button} onClick=${() => navigate('/settings/people')}>Invite your team</${Button}>` : null}>
        ${positionFilter || locationFilter ? 'Nobody matches these filters.' : 'Add people in Settings → People & roles.'}
      </${Empty}>`}
      ${manager && html`<p class="sg-hint muted text-sm"><${Icon} name="info" size=${13} /> Click a cell to add a shift · drag to move · hold ${navigator.platform.includes('Mac') ? 'Option' : 'Alt'} while dropping to copy</p>`}
    </div>`;
}

function DayList({ day, data, model, me, manager, onOpen, onAdd }) {
  const openShifts = model.open.get(day) || [];
  const rows = [];
  for (const g of model.groups) {
    for (const p of g.people) {
      for (const s of model.cells.get(`${p.user.id}|${day}`) || []) rows.push({ p, s });
    }
  }
  rows.sort((a, b) => a.s.start_at.localeCompare(b.s.start_at));
  const off = data.time_off.filter((r) => r.start_date <= day && r.end_date >= day);
  const total = data.day_totals[day];
  return html`<div class="sg-daylist">
    <div class="sg-daylist-head">
      <div><strong>${S.dayLong(day)}</strong>${total && total.shifts ? html`<div class="muted text-sm">${S.hours(total.minutes)} · ${total.shifts} ${total.shifts === 1 ? 'shift' : 'shifts'}</div>` : null}</div>
      ${manager && html`<${Button} size="sm" icon="plus" onClick=${onAdd}>Add shift</${Button}>`}
    </div>
    ${openShifts.length > 0 && html`<div class="sg-daylist-section">Open shifts</div>`}
    ${openShifts.map((s) => html`<button type="button" key=${s.id} class="sg-dayrow is-open" onClick=${(e) => onOpen(e.currentTarget, s)}>
      <span class="sg-open-avatar"><${Icon} name="user-plus" size=${14} /></span>
      <span class="sg-dayrow-main"><strong>${S.shiftRange(s)}</strong><span class="muted text-sm">${S.positionOf(s.position_id)?.name || 'Shift'}${s.notes ? ` · ${s.notes}` : ''}</span></span>
      ${!manager && html`<${Chip} tone="accent" size="sm">Pick up</${Chip}>`}
    </button>`)}
    ${rows.length > 0 && html`<div class="sg-daylist-section">Working</div>`}
    ${rows.map(({ p, s }) => html`<button type="button" key=${s.id} class=${cx('sg-dayrow', s.user_id === me.id && 'is-mine', s.status === 'draft' && 'is-draft')}
      style=${{ '--pos': S.positionOf(s.position_id)?.color || 'var(--text-3)' }} onClick=${(e) => onOpen(e.currentTarget, s)}>
      <${Avatar} user=${p.user} size=${30} />
      <span class="sg-dayrow-main">
        <strong>${p.user.name}</strong>
        <span class="muted text-sm">${S.shiftRange(s)} · ${S.positionOf(s.position_id)?.name || 'Shift'}${s.status === 'draft' ? ' · draft' : ''}</span>
        ${(s.conflicts || []).slice(0, 2).map((c) => html`<span class=${cx('sg-dayrow-conflict', `is-${c.severity}`)}><${Icon} name="triangle-alert" size=${11} /> ${c.message}</span>`)}
      </span>
      ${model.pending.has(s.id) && html`<${Icon} name="arrow-right-left" size=${14} class="muted" />`}
    </button>`)}
    ${off.length > 0 && html`<div class="sg-daylist-section">Off</div>`}
    ${off.map((r) => html`<div class="sg-dayrow is-off" key=${'o' + r.id}>
      <${Avatar} user=${r.user_id} size=${30} />
      <span class="sg-dayrow-main"><strong>${lookupUser(r.user_id).name}</strong><span class="muted text-sm">${S.TIME_OFF_KINDS[r.kind]?.label || 'Time off'}${r.status === 'pending' ? ' (requested)' : ''}</span></span>
    </div>`)}
    ${!rows.length && !openShifts.length && !off.length && html`<${Empty} icon="calendar-days" compact title="No shifts">Nothing scheduled this day.</${Empty}>`}
  </div>`;
}
