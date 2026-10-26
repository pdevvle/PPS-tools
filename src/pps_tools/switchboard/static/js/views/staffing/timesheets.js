// Timesheets: hours worked per person per day for a pay period, with overtime split
// out, manager corrections, approval and a payroll CSV.

import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch } from '../../lib/hooks.js';
import { navigate } from '../../lib/router.js';
import { useStore, user as lookupUser, getState } from '../../lib/store.js';
import { fmtDuration } from '../../lib/format.js';
import {
  Avatar, Banner, Button, Chip, Empty, ErrorBox, Field, Icon, IconButton, Input, Loading, PageHeader, Select, TextArea, cx,
} from '../../ui/components.js';
import { SidebarButton } from '../../ui/layout.js';
import { Modal, confirmDialog, openModal, toast, toastError } from '../../ui/overlay.js';
import * as S from './shared.js';

// minutes -> decimal hours: 480 -> '8', 450 -> '7.5', 505 -> '8.42'
const h = (m) => (m ? String(Math.round((m / 60) * 100) / 100) : '');

function EntryForm({ entry, userId, day, close }) {
  const people = getState().users.filter((u) => u.is_active);
  const start = entry ? S.toOrgInput(entry.clock_in) : `${day || S.todayKey()}T08:00`;
  const end = entry ? (entry.clock_out ? S.toOrgInput(entry.clock_out) : '') : `${day || S.todayKey()}T16:30`;
  const [form, setForm] = useState({
    user_id: String(entry ? entry.user_id : userId || ''), clock_in: start, clock_out: end,
    break_minutes: entry ? Math.round(entry.break_minutes) : 30, notes: entry ? entry.notes || '' : '', job_id: entry?.job_id || '',
  });
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const submit = async (e) => {
    e.preventDefault();
    const payload = {
      clock_in: S.fromOrgInput(form.clock_in), clock_out: form.clock_out ? S.fromOrgInput(form.clock_out) : null,
      break_minutes: Number(form.break_minutes) || 0, notes: form.notes, job_id: form.job_id ? Number(form.job_id) : null,
    };
    try {
      if (entry) await api.patch(`/time-entries/${entry.id}`, payload);
      else await api.post('/time-entries', { ...payload, user_id: Number(form.user_id) });
      toast(entry ? 'Entry updated' : 'Entry added');
      close();
    } catch (err) { toastError(err); }
  };
  return html`<${Modal} title=${entry ? 'Edit time entry' : 'Add time entry'} icon="clock" onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="entry-form">Save</${Button}>`}>
    <form id="entry-form" class="stack" onSubmit=${submit}>
      ${entry?.flag && html`<${Banner} tone="warn">This entry was closed automatically because nobody clocked out. Set the real clock-out time.</${Banner}>`}
      ${!entry && html`<${Field} label="Person"><${Select} value=${form.user_id} onValue=${set('user_id')} placeholder="Choose…"
        options=${people.map((u) => ({ value: String(u.id), label: u.name }))} required /></${Field}>`}
      <div class="form-grid">
        <${Field} label="Clocked in"><${Input} type="datetime-local" value=${form.clock_in} onValue=${set('clock_in')} required /></${Field}>
        <${Field} label="Clocked out"><${Input} type="datetime-local" value=${form.clock_out} onValue=${set('clock_out')} required=${!entry} /></${Field}>
        <${Field} label="Break (minutes)"><${Input} type="number" min="0" value=${form.break_minutes} onValue=${set('break_minutes')} /></${Field}>
        <${Field} label="Job # (optional)"><${Input} type="number" min="1" value=${form.job_id} onValue=${set('job_id')} /></${Field}>
      </div>
      <${Field} label="Note"><${TextArea} rows="2" value=${form.notes} onValue=${set('notes')} placeholder="Why it was changed" /></${Field}>
    </form>
  </${Modal}>`;
}

function editEntry(entry) {
  openModal((close) => html`<${EntryForm} entry=${entry} close=${close} />`);
}

async function deleteEntry(entry) {
  if (!(await confirmDialog({ title: 'Delete this time entry?', message: 'The hours come off the timesheet.', danger: true, confirmLabel: 'Delete' }))) return;
  try { await api.del(`/time-entries/${entry.id}`); toast('Deleted'); } catch (err) { toastError(err); }
}

function Entries({ person, manager }) {
  if (!person.entries.length) return html`<div class="ts-entries-empty muted text-sm">No punches in this period.</div>`;
  return html`<table class="ts-entries">
    <thead><tr><th>Day</th><th>In</th><th>Out</th><th class="num">Break</th><th class="num">Worked</th><th class="num">OT</th><th>Source</th><th>Note</th>${manager && html`<th></th>`}</tr></thead>
    <tbody>${person.entries.map((e) => html`<tr key=${e.id} class=${cx(e.flag && 'is-flagged')}>
      <td>${S.dayLabel(e.date)}</td>
      <td class="tabular">${S.orgTime(e.clock_in)}</td>
      <td class="tabular">${e.clock_out ? S.orgTime(e.clock_out) : html`<${Chip} tone="ok" size="sm">on the clock</${Chip}>`}
        ${e.flag && html` <${Chip} tone="warn" size="sm" icon="triangle-alert">Auto clock-out</${Chip}>`}</td>
      <td class="num tabular">${e.break_minutes ? `${Math.round(e.break_minutes)}m` : '—'}</td>
      <td class="num tabular">${fmtDuration(e.worked_minutes)}</td>
      <td class="num tabular ${e.overtime_minutes ? 'ts-ot' : ''}">${e.overtime_minutes ? fmtDuration(e.overtime_minutes) : '—'}</td>
      <td><span class="muted text-sm">${e.source}${e.job_id ? html` · <a href=${`/jobs/${e.job_id}`}>Job #${e.job_id}</a>` : ''}</span></td>
      <td class="ts-note">${e.notes || ''}</td>
      ${manager && html`<td class="ts-entry-actions">
        <${IconButton} icon="pencil" size="sm" label="Edit" onClick=${() => editEntry(e)} />
        <${IconButton} icon="trash" size="sm" label="Delete" onClick=${() => deleteEntry(e)} />
      </td>`}
    </tr>`)}</tbody>
  </table>`;
}

export function TimesheetsPage({ route }) {
  const manager = S.isManager();
  const me = useStore((s) => s.me);
  const settings = useStore((s) => s.settings);
  const { data, loading, error, reload } = useFetch('/timesheets', {
    query: { start: route.query.start, end: route.query.end }, refetchOn: ['timeclock.changed', 'schedule.changed'],
  });
  const [expanded, setExpanded] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const go = (range) => navigate('/schedule/timesheets', { query: range });
  const toggle = (id) => {
    const next = new Set(expanded);
    next.has(id) ? next.delete(id) : next.add(id);
    setExpanded(next);
  };
  const approve = async (ids) => {
    setBusy(true);
    try {
      const res = await api.post('/timesheets/approve', { start: data.start, end: data.end, user_ids: ids });
      toast(`Approved ${res.approved_entries} entr${res.approved_entries === 1 ? 'y' : 'ies'}`);
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  const header = html`<${PageHeader} leading=${html`<${SidebarButton} />`} title="Timesheets" icon="clock"
    subtitle=${data ? `${S.rangeLabel(data.start, data.end)} · ${data.pay_period === 'biweekly' ? 'two-week' : 'weekly'} pay period` : null}
    actions=${data && html`
      <div class="btn-group">
        <${Button} size="sm" icon="chevron-left" aria-label="Previous period" onClick=${() => go(data.prev)} />
        <${Button} size="sm" icon="calendar-check" onClick=${() => navigate('/schedule/timesheets')}>Current</${Button}>
        <${Button} size="sm" icon="chevron-right" aria-label="Next period" onClick=${() => go(data.next)} />
      </div>
      ${manager && html`<${Button} size="sm" icon="plus" onClick=${() => openModal((close) => html`<${EntryForm} close=${close} />`)}>Add entry</${Button}>`}
      <a class="btn btn-secondary btn-sm" href=${`/api/timesheets/export.csv?start=${data.start}&end=${data.end}`} download data-native>
        <${Icon} name="file-spreadsheet" size=${14} /><span class="btn-label">Export CSV</span></a>
    `} />`;
  if (error) return html`${header}<${ErrorBox} error=${error} retry=${reload} />`;
  if (loading && !data) return html`${header}<${Loading} />`;
  const people = data.people.filter((p) => p.entries.length || p.totals.scheduled || !manager);
  const toApprove = people.filter((p) => !p.approved && p.entries.some((e) => e.clock_out));
  const totals = people.reduce((acc, p) => {
    for (const k of ['worked', 'regular', 'overtime', 'scheduled']) acc[k] += p.totals[k];
    return acc;
  }, { worked: 0, regular: 0, overtime: 0, scheduled: 0 });
  const flagged = people.reduce((n, p) => n + p.flagged, 0);
  const isExpanded = (p) => expanded.has(p.user_id) || (!manager && p.user_id === me.id);
  return html`${header}
    <div class="page-body">
      ${flagged > 0 && manager && html`<${Banner} tone="warn" class="mb-3">${flagged} entr${flagged === 1 ? 'y needs' : 'ies need'} review — someone was clocked out automatically.</${Banner}>`}
      <div class="ts-summary">
        <div><span class="muted text-sm">Worked</span><strong>${h(totals.worked) || 0}h</strong></div>
        <div><span class="muted text-sm">Regular</span><strong>${h(totals.regular) || 0}h</strong></div>
        <div class=${cx(totals.overtime > 0 && 'is-ot')}><span class="muted text-sm">Overtime</span><strong>${h(totals.overtime) || 0}h</strong></div>
        <div><span class="muted text-sm">Scheduled</span><strong>${h(totals.scheduled) || 0}h</strong></div>
        ${manager && html`<div class="ts-summary-action"><${Button} variant="primary" size="sm" icon="badge-check" loading=${busy} disabled=${!toApprove.length}
          onClick=${() => approve(toApprove.map((p) => p.user_id))}>Approve ${toApprove.length ? `all (${toApprove.length})` : 'all'}</${Button}></div>`}
      </div>
      <div class="table-wrap ts-wrap"><table class="table ts-table">
        <thead><tr>
          <th class="ts-person">Person</th>
          ${data.days.map((d) => html`<th key=${d} class="num ts-day">${S.weekdayShort(d)}<br /><span class="muted">${Number(d.slice(8))}</span></th>`)}
          <th class="num">Total</th><th class="num">OT</th><th class="num hide-mobile">Sched.</th><th class="num hide-mobile">+/−</th><th>Status</th>
        </tr></thead>
        <tbody>
          ${people.map((p) => html`
            <tr key=${p.user_id} class=${cx('ts-row', isExpanded(p) && 'is-open')}>
              <td class="ts-person">
                <button type="button" class="ts-person-btn" onClick=${() => toggle(p.user_id)} aria-expanded=${isExpanded(p)}>
                  <${Icon} name="chevron-right" size=${12} class="ts-chevron" />
                  <${Avatar} user=${p.user_id} size=${24} />
                  <span class="truncate">${lookupUser(p.user_id).name}</span>
                  ${p.flagged ? html`<${Icon} name="triangle-alert" size=${13} class="st-flag" />` : null}
                  ${p.open_entries ? html`<span class="sg-live is-clocked_in" title="On the clock"></span>` : null}
                </button>
              </td>
              ${p.days.map((d) => html`<td key=${d.date} class=${cx('num tabular ts-day', d.overtime && 'ts-ot')}
                title=${d.scheduled ? `Scheduled ${fmtDuration(d.scheduled)}` : undefined}>${h(d.worked) || html`<span class="muted">·</span>`}</td>`)}
              <td class="num tabular strong">${h(p.totals.worked) || '0'}</td>
              <td class=${cx('num tabular', p.totals.overtime && 'ts-ot')}>${h(p.totals.overtime) || '—'}</td>
              <td class="num tabular hide-mobile muted">${h(p.totals.scheduled) || '—'}</td>
              <td class=${cx('num tabular hide-mobile', p.totals.variance < -30 && 'ts-under', p.totals.variance > 30 && 'ts-over')}>
                ${p.totals.variance ? `${p.totals.variance > 0 ? '+' : '−'}${h(Math.abs(p.totals.variance))}` : '—'}</td>
              <td>${p.approved ? html`<${Chip} tone="ok" size="sm" icon="badge-check">Approved</${Chip}>`
    : manager && p.entries.some((e) => e.clock_out) ? html`<${Button} size="sm" onClick=${() => approve([p.user_id])}>Approve</${Button}>`
      : html`<span class="muted text-sm">${p.entries.length ? 'Open' : '—'}</span>`}</td>
            </tr>
            ${isExpanded(p) && html`<tr class="ts-detail"><td colspan=${data.days.length + 6}><${Entries} person=${p} manager=${manager} /></td></tr>`}
          `)}
        </tbody>
      </table></div>
      ${!people.length && html`<${Empty} icon="clock" title="No hours yet">Punches from the time clock and kiosk show up here.</${Empty}>`}
      <p class="muted text-sm mt-3">Hours in decimal. Overtime counts after ${settings['staffing.overtime_weekly_hours'] || 40}h a week${settings['staffing.overtime_daily_hours'] ? ` or ${settings['staffing.overtime_daily_hours']}h a day` : ''}.</p>
    </div>`;
}
