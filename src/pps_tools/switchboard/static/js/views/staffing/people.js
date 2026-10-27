// People: the staff directory and each person's profile (employment, positions & skills,
// weekly availability, upcoming shifts, time off and recent punches).

import { html, useEffect, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch } from '../../lib/hooks.js';
import { navigate } from '../../lib/router.js';
import { useStore, can } from '../../lib/store.js';
import { fmtDate, fmtDuration, fmtMoney } from '../../lib/format.js';
import {
  Avatar, Button, Card, Checkbox, Chip, Empty, ErrorBox, Field, Icon, IconButton, Input, KeyValue, Loading, PageHeader,
  SearchInput, Select, TextArea, Toggle, cx,
} from '../../ui/components.js';
import { SidebarButton } from '../../ui/layout.js';
import { Modal, openModal, toast, toastError } from '../../ui/overlay.js';
import * as S from './shared.js';

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const KIND_LABEL = { available: 'Available', preferred: 'Preferred', unavailable: 'Unavailable' };
const TYPE_LABEL = { full_time: 'Full time', part_time: 'Part time', contractor: 'Contractor', seasonal: 'Seasonal' };
const LEVELS = { 1: 'Trainee', 2: 'Competent', 3: 'Expert' };

function SkillChip({ skill }) {
  const s = S.skillOf(skill.skill_id);
  if (!s) return null;
  return html`<span class="st-skill" title=${LEVELS[skill.level]}>${s.name}<span class="st-skill-level">${'●'.repeat(skill.level)}${'○'.repeat(3 - skill.level)}</span></span>`;
}

export function PeopleList() {
  const { data, loading, error, reload } = useFetch('/staff', { refetchOn: ['staff.changed', 'timeclock.changed', 'schedule.changed'] });
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('all');
  const items = (data?.items || [])
    .filter((p) => !q || `${p.user.name} ${p.user.title || ''} ${p.user.email}`.toLowerCase().includes(q.toLowerCase()))
    .filter((p) => status === 'all' || (status === 'working' ? ['clocked_in', 'on_break', 'on_shift'].includes(p.status) : p.status === status));
  const working = (data?.items || []).filter((p) => ['clocked_in', 'on_break'].includes(p.status)).length;
  return html`<${PageHeader} leading=${html`<${SidebarButton} />`} title="People" icon="users"
      subtitle=${data ? `${data.items.length} people · ${working} on the clock now` : null} />
    <div class="toolbar">
      <${SearchInput} value=${q} onValue=${setQ} placeholder="Search people" class="grow" />
      <select class="input input-sm st-filter" value=${status} onChange=${(e) => setStatus(e.currentTarget.value)} aria-label="Status">
        <option value="all">Everyone</option><option value="working">Working now</option><option value="on_leave">On leave</option><option value="off">Off</option>
      </select>
    </div>
    <div class="page-body">
      ${error && html`<${ErrorBox} error=${error} retry=${reload} />`}
      ${loading && !data ? html`<${Loading} />` : html`<div class="table-wrap"><table class="table st-people">
        <thead><tr><th>Name</th><th>Positions</th><th class="hide-mobile">Skills</th><th>Now</th><th class="num hide-mobile">This week</th></tr></thead>
        <tbody>
          ${items.map((p) => html`<tr key=${p.user.id} class="is-clickable" onClick=${() => navigate(`/schedule/people/${p.user.id}`)}>
            <td><div class="row"><${Avatar} user=${p.user} size=${30} online="auto" />
              <div class="stack-0"><a class="strong" href=${`/schedule/people/${p.user.id}`} onClick=${(e) => e.stopPropagation()}>${p.user.name}</a>
              <span class="muted text-sm">${p.user.title || p.user.email}</span></div></div></td>
            <td><div class="row row-wrap gap-1">${p.position_ids.map((id) => html`<${S.PositionChip} key=${id} id=${id} />`)}</div></td>
            <td class="hide-mobile"><div class="row row-wrap gap-1">${p.skills.slice(0, 3).map((sk) => html`<${SkillChip} key=${sk.skill_id} skill=${sk} />`)}
              ${p.skills.length > 3 ? html`<span class="muted text-sm">+${p.skills.length - 3}</span>` : null}</div></td>
            <td><${S.StatusChip} status=${p.status} /></td>
            <td class="num hide-mobile nowrap">${S.hours(p.week_minutes)}${p.profile.target_hours_week ? html`<span class="muted"> / ${p.profile.target_hours_week}h</span>` : null}</td>
          </tr>`)}
        </tbody>
      </table></div>`}
      ${data && !items.length && html`<${Empty} icon="users" title="No one matches" compact />`}
    </div>`;
}

// -- profile ----------------------------------------------------------------------------

function EmploymentForm({ person, close }) {
  const positions = S.usePositions();
  const locations = S.useLocations();
  const p = person.profile;
  const manager = S.isManager();
  const [form, setForm] = useState(() => ({
    employee_number: p.employee_number || '', employment_type: p.employment_type || 'full_time',
    hourly_rate: p.hourly_rate ?? '', hire_date: p.hire_date || '', target_hours_week: p.target_hours_week ?? '',
    max_hours_week: p.max_hours_week ?? '', default_position_id: p.default_position_id || '',
    default_location_id: p.default_location_id || '', pto_hours_per_year: p.pto_hours_per_year ?? '',
    emergency_contact: p.emergency_contact || '', notes: p.notes || '', is_schedulable: p.is_schedulable,
  }));
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const submit = async (e) => {
    e.preventDefault();
    const payload = manager ? { ...form } : { emergency_contact: form.emergency_contact };
    if (manager && !can('view_pay')) delete payload.hourly_rate;
    try {
      await api.patch(`/staff/${person.user.id}`, payload);
      toast('Saved');
      close();
    } catch (err) { toastError(err); }
  };
  return html`<${Modal} title=${manager ? `Employment — ${person.user.name}` : 'Emergency contact'} onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="emp-form">Save</${Button}>`}>
    <form id="emp-form" class="stack" onSubmit=${submit}>
      ${manager && html`<div class="form-grid">
        <${Field} label="Employee number"><${Input} value=${form.employee_number} onValue=${set('employee_number')} /></${Field}>
        <${Field} label="Employment"><${Select} value=${form.employment_type} onValue=${set('employment_type')}
          options=${Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }))} /></${Field}>
        ${can('view_pay') && html`<${Field} label="Hourly rate ($)"><${Input} type="number" step="0.25" min="0" value=${form.hourly_rate} onValue=${set('hourly_rate')} /></${Field}>`}
        <${Field} label="Hire date"><${Input} type="date" value=${form.hire_date} onValue=${set('hire_date')} /></${Field}>
        <${Field} label="Target hours / week"><${Input} type="number" min="0" value=${form.target_hours_week} onValue=${set('target_hours_week')} /></${Field}>
        <${Field} label="Max hours / week"><${Input} type="number" min="0" value=${form.max_hours_week} onValue=${set('max_hours_week')} /></${Field}>
        <${Field} label="Usual position"><${Select} value=${String(form.default_position_id)} onValue=${set('default_position_id')} placeholder="—"
          options=${positions.map((x) => ({ value: String(x.id), label: x.name }))} /></${Field}>
        <${Field} label="Usual location"><${Select} value=${String(form.default_location_id)} onValue=${set('default_location_id')} placeholder="—"
          options=${locations.map((x) => ({ value: String(x.id), label: x.name }))} /></${Field}>
        <${Field} label="Paid time off (hours / year)"><${Input} type="number" min="0" value=${form.pto_hours_per_year} onValue=${set('pto_hours_per_year')} /></${Field}>
      </div>`}
      <${Field} label="Emergency contact"><${Input} value=${form.emergency_contact} onValue=${set('emergency_contact')} placeholder="Name (relationship) · phone" /></${Field}>
      ${manager && html`<${Field} label="Manager notes" hint="Only managers see these"><${TextArea} rows="3" value=${form.notes} onValue=${set('notes')} /></${Field}>`}
      ${manager && html`<${Toggle} checked=${!!form.is_schedulable} onChange=${set('is_schedulable')} label="Show on the schedule" hint="Turn off for people who never work shifts" />`}
    </form>
  </${Modal}>`;
}

function SkillsForm({ person, close }) {
  const positions = S.usePositions();
  const skills = S.useSkills();
  const [posIds, setPosIds] = useState(person.position_ids);
  const [levels, setLevels] = useState(() => Object.fromEntries(person.skills.map((s) => [s.skill_id, s.level])));
  const submit = async (e) => {
    e.preventDefault();
    try {
      await api.put(`/staff/${person.user.id}/positions`, { position_ids: posIds });
      await api.put(`/staff/${person.user.id}/skills`, {
        skills: Object.entries(levels).filter(([, l]) => Number(l) > 0).map(([id, l]) => ({ skill_id: Number(id), level: Number(l) })),
      });
      toast('Saved');
      close();
    } catch (err) { toastError(err); }
  };
  return html`<${Modal} title=${`Positions & skills — ${person.user.name}`} onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="skills-form">Save</${Button}>`}>
    <form id="skills-form" class="stack" onSubmit=${submit}>
      <${Field} label="Can work as">
        <div class="row row-wrap gap-3">
          ${positions.map((p) => html`<${Checkbox} key=${p.id} label=${p.name} checked=${posIds.includes(p.id)}
            onChange=${(on) => setPosIds(on ? [...posIds, p.id] : posIds.filter((x) => x !== p.id))} />`)}
        </div>
      </${Field}>
      <${Field} label="Skills">
        <div class="st-skill-grid">
          ${skills.map((s) => html`<label key=${s.id} class="st-skill-row"><span>${s.name}</span>
            <select class="input input-sm" value=${String(levels[s.id] || 0)} onChange=${(e) => setLevels({ ...levels, [s.id]: Number(e.currentTarget.value) })}>
              <option value="0">—</option><option value="1">Trainee</option><option value="2">Competent</option><option value="3">Expert</option>
            </select></label>`)}
          ${!skills.length && html`<span class="muted">Add skills in Settings → Positions & locations.</span>`}
        </div>
      </${Field}>
    </form>
  </${Modal}>`;
}

export function AvailabilityEditor({ uid, rows, canEdit }) {
  const [items, setItems] = useState(rows);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!editing) setItems(rows); }, [rows]);
  const update = (i, patch) => setItems(items.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const add = (weekday) => setItems([...items, { weekday, start_time: '08:00', end_time: '17:00', kind: 'available' }]);
  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/staff/${uid}/availability`, { items });
      toast('Availability saved');
      setEditing(false);
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  return html`<${Card} title="Weekly availability" icon="calendar-range"
    subtitle=${items.length ? null : 'No limits set — can be scheduled any time'}
    actions=${canEdit && (editing
    ? html`<${Button} size="sm" onClick=${() => { setItems(rows); setEditing(false); }}>Cancel</${Button}><${Button} size="sm" variant="primary" loading=${busy} onClick=${save}>Save</${Button}>`
    : html`<${Button} size="sm" icon="pencil" onClick=${() => setEditing(true)}>Edit</${Button}>`)}>
    <div class="st-avail">
      ${WEEKDAYS.map((name, wd) => {
    const mine = items.map((r, i) => ({ ...r, i })).filter((r) => r.weekday === wd);
    return html`<div class="st-avail-row" key=${wd}>
          <span class="st-avail-day">${name.slice(0, 3)}</span>
          <div class="st-avail-windows">
            ${!mine.length && !editing && html`<span class="muted text-sm">—</span>`}
            ${mine.map((r) => (editing
      ? html`<div class="st-avail-edit" key=${r.i}>
                  <select class="input input-sm" value=${r.kind} onChange=${(e) => update(r.i, { kind: e.currentTarget.value })}>
                    ${Object.entries(KIND_LABEL).map(([k, l]) => html`<option value=${k}>${l}</option>`)}
                  </select>
                  <input type="time" class="input input-sm" value=${r.start_time} onInput=${(e) => update(r.i, { start_time: e.currentTarget.value })} />
                  <span class="muted">–</span>
                  <input type="time" class="input input-sm" value=${r.end_time === '24:00' ? '23:59' : r.end_time}
                    onInput=${(e) => update(r.i, { end_time: e.currentTarget.value === '23:59' ? '24:00' : e.currentTarget.value })} />
                  <${IconButton} icon="x" size="sm" label="Remove" onClick=${() => setItems(items.filter((_, j) => j !== r.i))} />
                </div>`
      : html`<span key=${r.i} class=${cx('st-avail-window', `is-${r.kind}`)} title=${r.note || undefined}>
                  ${KIND_LABEL[r.kind]} ${S.fmtHHMM(r.start_time, { compact: true })}–${r.end_time === '24:00' ? 'close' : S.fmtHHMM(r.end_time, { compact: true })}
                </span>`))}
            ${editing && html`<${IconButton} icon="plus" size="sm" label=${`Add a window on ${name}`} onClick=${() => add(wd)} />`}
          </div>
        </div>`;
  })}
    </div>
  </${Card}>`;
}

export function PersonProfile({ id }) {
  const { data, loading, error, reload } = useFetch(`/staff/${id}`, { refetchOn: ['staff.changed', 'schedule.changed', 'timeclock.changed'] });
  const weekStart = useStoreWeekStart();
  if (error) return html`<${PageHeader} leading=${html`<${SidebarButton} />`} title="Person" /><${ErrorBox} error=${error} retry=${reload} />`;
  if (!data) return html`<${PageHeader} leading=${html`<${SidebarButton} />`} title="Person" /><${Loading} />`;
  const p = data.profile;
  const manager = data.can_edit;
  const position = (pid) => S.positionOf(pid)?.name;
  const location = (lid) => S.locationOf(lid)?.name;
  const edit = () => openModal((close) => html`<${EmploymentForm} person=${data} close=${close} />`);
  const editSkills = () => openModal((close) => html`<${SkillsForm} person=${data} close=${close} />`);
  return html`<${PageHeader} leading=${html`<${SidebarButton} /><${IconButton} icon="arrow-left" label="All people" onClick=${() => navigate('/schedule/people')} />`}
      title=${data.user.name} subtitle=${[data.user.title, S.STATUS[data.status]?.label].filter(Boolean).join(' · ')}
      actions=${html`
        ${!data.is_me && html`<${Button} size="sm" icon="messages-square" onClick=${() => navigate(`/chat/dm/${id}`)}>Message</${Button}>`}
        ${(data.is_me || manager) && html`<${Button} size="sm" icon="plane" onClick=${() => S.requestTimeOff({ userId: Number(id) })}>Time off</${Button}>`}
        ${(manager || data.is_me) && html`<${Button} size="sm" icon="pencil" onClick=${edit}>${manager ? 'Edit' : 'Emergency contact'}</${Button}>`}
      `} />
    <div class="page-body">
      <div class="st-profile">
        <div class="st-profile-main">
          <${Card} title="Employment" icon="briefcase">
            <div class="row gap-3 mb-3"><${Avatar} user=${data.user} size=${48} online="auto" />
              <div class="stack-0"><strong>${data.user.name}</strong><span class="muted text-sm">${data.user.email}${data.user.phone ? ` · ${data.user.phone}` : ''}</span>
              <span class="mt-1"><${S.StatusChip} status=${data.status} /></span></div></div>
            <${KeyValue} items=${[
    ['Employee #', p.employee_number || '—'],
    ['Type', TYPE_LABEL[p.employment_type] || '—'],
    p.hire_date && ['Hired', fmtDate(p.hire_date + 'T12:00:00', { year: true })],
    p.hourly_rate !== null && p.hourly_rate !== undefined && ['Hourly rate', fmtMoney(p.hourly_rate)],
    ['Hours / week', [p.target_hours_week && `target ${p.target_hours_week}h`, p.max_hours_week && `max ${p.max_hours_week}h`].filter(Boolean).join(', ') || '—'],
    ['This week', S.hours(data.week_minutes)],
    ['Usual position', position(p.default_position_id) || '—'],
    ['Usual location', location(p.default_location_id) || '—'],
    p.pto_hours_per_year !== null && p.pto_hours_per_year !== undefined && ['Paid time off', `${p.pto_hours_per_year}h / year`],
    p.emergency_contact && ['Emergency contact', p.emergency_contact],
    p.notes && ['Notes', p.notes],
  ]} />
          </${Card}>
          <${Card} title="Positions & skills" icon="award" actions=${manager && html`<${Button} size="sm" icon="pencil" onClick=${editSkills}>Edit</${Button}>`}>
            <div class="row row-wrap gap-1 mb-2">${data.position_ids.length ? data.position_ids.map((pid) => html`<${S.PositionChip} key=${pid} id=${pid} />`) : html`<span class="muted text-sm">No positions yet</span>`}</div>
            <div class="row row-wrap gap-1">${data.skills.map((sk) => html`<${SkillChip} key=${sk.skill_id} skill=${sk} />`)}</div>
          </${Card}>
          <${AvailabilityEditor} uid=${Number(id)} rows=${data.availability} canEdit=${manager || data.is_me} />
        </div>
        <div class="st-profile-side">
          <${Card} title="Upcoming shifts" icon="calendar-clock" pad=${false}>
            ${data.upcoming_shifts.length ? html`<div class="list">${data.upcoming_shifts.map((s) => html`<a key=${s.id} class="list-row is-clickable st-link-row"
              href=${`/schedule?week=${S.weekStartKey(s.date, weekStart)}`}>
              <span class="st-day-badge"><span>${S.weekdayShort(s.date)}</span><strong>${Number(s.date.slice(8))}</strong></span>
              <span class="grow stack-0"><strong>${S.shiftRange(s)}</strong><span class="muted text-sm">${position(s.position_id) || 'Shift'}${s.location_id ? ` · ${location(s.location_id)}` : ''}</span></span>
              ${s.status === 'draft' && html`<${Chip} size="sm" tone="muted">Draft</${Chip}>`}
            </a>`)}</div>` : html`<${Empty} icon="calendar-clock" compact>No shifts in the next three weeks.</${Empty}>`}
          </${Card}>
          ${(data.is_me || manager) && html`<${Card} title="Time off" icon="plane" pad=${false}>
            ${data.time_off.length ? html`<div class="list">${data.time_off.slice(0, 8).map((r) => html`<div key=${r.id} class="list-row">
              <${S.KindChip} kind=${r.kind} /><span class="grow text-sm">${S.timeOffSpan(r)}</span><${S.RequestStatus} status=${r.status} />
            </div>`)}</div>` : html`<${Empty} icon="plane" compact>No time off yet.</${Empty}>`}
          </${Card}>`}
          ${(data.is_me || manager) && html`<${Card} title="Recent punches" icon="clock" pad=${false}>
            ${data.time_entries.length ? html`<div class="list">${data.time_entries.slice(0, 10).map((e) => html`<div key=${e.id} class="list-row text-sm">
              <span class="st-entry-date">${S.dayLabel(e.date)}</span>
              <span class="grow">${S.orgTime(e.clock_in)} – ${e.clock_out ? S.orgTime(e.clock_out) : html`<${Chip} tone="ok" size="sm">on the clock</${Chip}>`}</span>
              ${e.flag && html`<${Icon} name="triangle-alert" size=${13} class="st-flag" title="Needs review" />`}
              <span class="tabular">${fmtDuration(e.worked_minutes)}</span>
            </div>`)}</div>` : html`<${Empty} icon="clock" compact>No punches in the last two weeks.</${Empty}>`}
          </${Card}>`}
        </div>
      </div>
    </div>`;
}

function useStoreWeekStart() {
  return Number(useStore((s) => s.settings['org.week_start']) || 0);
}
