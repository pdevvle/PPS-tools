// Settings → Staffing: positions, locations, skills and shift templates; scheduling
// rules (overtime, rest, approvals, pay periods, time clock).

import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch } from '../../lib/hooks.js';
import { useStore, can, loadBootstrap } from '../../lib/store.js';
import {
  Button, Chip, ColorDot, Empty, Field, IconButton, Input, Section, Select, Toggle, cx,
} from '../../ui/components.js';
import { Modal, confirmDialog, openModal, promptDialog, toast, toastError } from '../../ui/overlay.js';
import { pickColor } from '../../ui/pickers.js';
import * as S from './shared.js';

async function saveRef(table, id, patch) {
  try {
    if (id) await api.patch(`/${table}/${id}`, patch);
    else await api.post(`/${table}`, patch);
    await loadBootstrap();
  } catch (err) { toastError(err); }
}

async function removeRef(table, item, what) {
  if (!(await confirmDialog({ title: `Delete ${item.name}?`, message: what, danger: true, confirmLabel: 'Delete' }))) return;
  try { await api.del(`/${table}/${item.id}`); await loadBootstrap(); } catch (err) { toastError(err); }
}

async function rename(table, item, label) {
  const name = await promptDialog({ title: `Rename ${label}`, value: item ? item.name : '', confirmLabel: item ? 'Save' : 'Add' });
  if (name && name.trim()) await saveRef(table, item?.id, { name: name.trim() });
}

function RateInput({ position }) {
  const [value, setValue] = useState(position.default_rate ?? '');
  const commit = () => {
    const next = value === '' ? null : Number(value);
    if (next !== position.default_rate) saveRef('positions', position.id, { default_rate: next });
  };
  return html`<div class="st-rate"><span class="muted">$</span>
    <input class="input input-sm" type="number" min="0" step="0.25" value=${value} placeholder="—" aria-label="Default hourly rate"
      onInput=${(e) => setValue(e.currentTarget.value)} onBlur=${commit} onKeyDown=${(e) => e.key === 'Enter' && e.currentTarget.blur()} />
    <span class="muted text-sm">/h</span></div>`;
}

function TemplateForm({ template, close }) {
  const positions = S.usePositions();
  const locations = S.useLocations();
  const [form, setForm] = useState(() => ({
    name: template?.name || '', start_time: template?.start_time || '08:00', end_time: template?.end_time || '16:30',
    break_minutes: template?.break_minutes ?? 30, position_id: template?.position_id || '', location_id: template?.location_id || '',
  }));
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const submit = async (e) => {
    e.preventDefault();
    const payload = { ...form, break_minutes: Number(form.break_minutes) || 0,
      position_id: form.position_id ? Number(form.position_id) : null, location_id: form.location_id ? Number(form.location_id) : null };
    try {
      if (template) await api.patch(`/shift-templates/${template.id}`, payload);
      else await api.post('/shift-templates', payload);
      close();
    } catch (err) { toastError(err); }
  };
  return html`<${Modal} title=${template ? 'Edit template' : 'New shift template'} onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="tpl-form">Save</${Button}>`}>
    <form id="tpl-form" class="stack" onSubmit=${submit}>
      <${Field} label="Name"><${Input} value=${form.name} onValue=${set('name')} placeholder="Opening press (6:30–3)" required autoFocus /></${Field}>
      <div class="form-grid">
        <${Field} label="Start"><${Input} type="time" value=${form.start_time} onValue=${set('start_time')} required /></${Field}>
        <${Field} label="End"><${Input} type="time" value=${form.end_time} onValue=${set('end_time')} required /></${Field}>
        <${Field} label="Break (minutes)"><${Input} type="number" min="0" value=${form.break_minutes} onValue=${set('break_minutes')} /></${Field}>
        <${Field} label="Position"><${Select} value=${String(form.position_id)} onValue=${set('position_id')} placeholder="Person's usual position"
          options=${positions.map((p) => ({ value: String(p.id), label: p.name }))} /></${Field}>
        <${Field} label="Location"><${Select} value=${String(form.location_id)} onValue=${set('location_id')} placeholder="Person's usual location"
          options=${locations.map((l) => ({ value: String(l.id), label: l.name }))} /></${Field}>
      </div>
    </form>
  </${Modal}>`;
}

export function PositionsSettings() {
  const positions = S.usePositions();
  const locations = S.useLocations();
  const skills = S.useSkills();
  const pay = can('view_pay');
  const templates = useFetch('/shift-templates', { refetchOn: ['schedule.changed'] });
  const [skillName, setSkillName] = useState('');
  const addSkill = async (e) => {
    e.preventDefault();
    if (!skillName.trim()) return;
    await saveRef('skills', null, { name: skillName.trim() });
    setSkillName('');
  };
  const editTemplate = (t) => openModal((close) => html`<${TemplateForm} template=${t} close=${() => { close(); templates.reload(); }} />`);
  const deleteTemplate = async (t) => {
    if (!(await confirmDialog({ title: `Delete “${t.name}”?`, danger: true, confirmLabel: 'Delete' }))) return;
    try { await api.del(`/shift-templates/${t.id}`); templates.reload(); } catch (err) { toastError(err); }
  };
  return html`<div>
    <${Section} title="Positions" description="The roles you schedule people into. Each shift has a position, and people list the positions they can work."
      actions=${html`<${Button} icon="plus" onClick=${() => rename('positions', null, 'position')}>Add position</${Button}>`}>
      <div class="settings-list">
        ${positions.map((p) => html`<div class=${cx('settings-list-row', !p.is_active && 'is-inactive')} key=${p.id}>
          <button type="button" class="st-color-btn" aria-label="Change color" onClick=${(e) => pickColor(e.currentTarget, { value: p.color, onChange: (color) => saveRef('positions', p.id, { color }) })}>
            <${ColorDot} color=${p.color} size=${14} /></button>
          <span class="grow strong">${p.name}</span>
          ${!p.is_active && html`<${Chip} size="sm" tone="muted">Hidden</${Chip}>`}
          ${pay && html`<${RateInput} key=${'rate' + p.id + (p.default_rate ?? '')} position=${p} />`}
          <${Toggle} checked=${p.is_active} onChange=${(on) => saveRef('positions', p.id, { is_active: on })} label="" />
          <${IconButton} icon="pencil" size="sm" label="Rename" onClick=${() => rename('positions', p, 'position')} />
          <${IconButton} icon="trash" size="sm" label="Delete" onClick=${() => removeRef('positions', p, 'Shifts keep their times but lose this position.')} />
        </div>`)}
        ${!positions.length && html`<${Empty} compact icon="briefcase">No positions yet.</${Empty}>`}
      </div>
      ${pay && html`<p class="muted text-sm mt-2">Default rates estimate labor cost for people without their own hourly rate.</p>`}
    </${Section}>
    <${Section} title="Locations" description="Where shifts happen — the shop floor, a warehouse, an install site."
      actions=${html`<${Button} icon="plus" onClick=${() => rename('locations', null, 'location')}>Add location</${Button}>`}>
      <div class="settings-list">
        ${locations.map((l) => html`<div class="settings-list-row" key=${l.id}>
          <button type="button" class="st-color-btn" aria-label="Change color" onClick=${(e) => pickColor(e.currentTarget, { value: l.color, onChange: (color) => saveRef('locations', l.id, { color }) })}>
            <${ColorDot} color=${l.color} size=${14} /></button>
          <div class="grow stack-0"><span class="strong">${l.name}</span>${l.address && html`<span class="muted text-sm">${l.address}</span>`}</div>
          <${IconButton} icon="map-pin" size="sm" label="Set address" onClick=${async () => {
    const address = await promptDialog({ title: `Address for ${l.name}`, value: l.address || '' });
    if (address !== null) saveRef('locations', l.id, { address });
  }} />
          <${IconButton} icon="pencil" size="sm" label="Rename" onClick=${() => rename('locations', l, 'location')} />
          <${IconButton} icon="trash" size="sm" label="Delete" onClick=${() => removeRef('locations', l, 'Shifts here keep their times but lose the location.')} />
        </div>`)}
      </div>
    </${Section}>
    <${Section} title="Skills" description="Equipment and abilities — used on profiles and to match people to job operations.">
      <div class="row row-wrap gap-2 mb-3">
        ${skills.map((s) => html`<${Chip} key=${s.id} onRemove=${() => removeRef('skills', s, 'It comes off everyone who has it.')}>${s.name}</${Chip}>`)}
        ${!skills.length && html`<span class="muted text-sm">No skills yet.</span>`}
      </div>
      <form class="row" onSubmit=${addSkill} style="max-width:420px">
        <${Input} value=${skillName} onValue=${setSkillName} placeholder="e.g. Guillotine cutter" />
        <${Button} type="submit" icon="plus">Add</${Button}>
      </form>
    </${Section}>
    <${Section} title="Shift templates" description="One-click shifts in the schedule's quick-add menu."
      actions=${html`<${Button} icon="plus" onClick=${() => editTemplate(null)}>New template</${Button}>`}>
      <div class="settings-list">
        ${(templates.data?.items || []).map((t) => html`<div class="settings-list-row" key=${t.id}>
          <div class="grow stack-0"><span class="strong">${t.name}</span>
            <span class="muted text-sm">${S.fmtHHMM(t.start_time)}–${S.fmtHHMM(t.end_time)}${t.break_minutes ? ` · ${t.break_minutes} min break` : ''}${t.position_id ? ` · ${S.positionOf(t.position_id)?.name || ''}` : ''}</span></div>
          <${IconButton} icon="pencil" size="sm" label="Edit" onClick=${() => editTemplate(t)} />
          <${IconButton} icon="trash" size="sm" label="Delete" onClick=${() => deleteTemplate(t)} />
        </div>`)}
        ${templates.data && !templates.data.items.length && html`<${Empty} compact icon="layers">No templates yet.</${Empty}>`}
      </div>
    </${Section}>
  </div>`;
}

const POLICY_KEYS = [
  'staffing.overtime_weekly_hours', 'staffing.overtime_daily_hours', 'staffing.min_rest_hours', 'staffing.max_shift_hours',
  'staffing.pickup_requires_approval', 'staffing.swap_requires_approval', 'staffing.pay_period', 'staffing.pay_period_anchor',
  'staffing.shift_reminder_minutes', 'staffing.clock_rounding_minutes', 'staffing.early_clock_in_minutes',
  'staffing.auto_clock_out_hours',
];

export function PolicySettings() {
  const settings = useStore((s) => s.settings);
  const [form, setForm] = useState(() => Object.fromEntries(POLICY_KEYS.map((k) => [k, settings[k]])));
  const [saving, setSaving] = useState(false);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const num = (v, allowNull = false) => (v === '' || v === null || v === undefined ? (allowNull ? null : 0) : Number(v));
  const save = async () => {
    setSaving(true);
    try {
      await api.patch('/settings', {
        ...form,
        'staffing.overtime_weekly_hours': num(form['staffing.overtime_weekly_hours']),
        'staffing.overtime_daily_hours': num(form['staffing.overtime_daily_hours'], true),
        'staffing.min_rest_hours': num(form['staffing.min_rest_hours']),
        'staffing.max_shift_hours': num(form['staffing.max_shift_hours']),
        'staffing.shift_reminder_minutes': num(form['staffing.shift_reminder_minutes']),
        'staffing.clock_rounding_minutes': num(form['staffing.clock_rounding_minutes']),
        'staffing.early_clock_in_minutes': num(form['staffing.early_clock_in_minutes']),
        'staffing.auto_clock_out_hours': num(form['staffing.auto_clock_out_hours']),
      });
      await loadBootstrap();
      toast('Scheduling rules saved');
    } catch (err) { toastError(err); } finally { setSaving(false); }
  };
  const numberField = (key, label, hint, attrs = {}) => html`<${Field} label=${label} hint=${hint}>
    <${Input} type="number" min="0" value=${form[key] ?? ''} onValue=${set(key)} ...${attrs} /></${Field}>`;
  return html`<div>
    <${Section} title="Overtime & fatigue" description="The schedule warns before a shift breaks these rules; timesheets split overtime out for payroll.">
      <div class="form-grid" style="max-width:640px">
        ${numberField('staffing.overtime_weekly_hours', 'Weekly overtime after (hours)', 'Federal rule: 40')}
        ${numberField('staffing.overtime_daily_hours', 'Daily overtime after (hours)', 'Leave empty unless your state requires it (Arizona doesn’t)', { placeholder: 'None' })}
        ${numberField('staffing.min_rest_hours', 'Minimum rest between shifts (hours)', 'Warn when shifts are closer than this')}
        ${numberField('staffing.max_shift_hours', 'Longest shift (hours)', 'Warn on longer shifts')}
      </div>
    </${Section}>
    <${Section} title="Swaps & open shifts">
      <div class="stack">
        <${Toggle} checked=${!!form['staffing.swap_requires_approval']} onChange=${set('staffing.swap_requires_approval')}
          label="Swaps need a manager's OK" hint="After the coworker accepts. Off: the swap happens as soon as they accept." />
        <${Toggle} checked=${!!form['staffing.pickup_requires_approval']} onChange=${set('staffing.pickup_requires_approval')}
          label="Picking up an open shift needs a manager's OK" hint="Off: the first qualified person to tap it gets it." />
      </div>
    </${Section}>
    <${Section} title="Time clock & pay periods">
      <div class="form-grid" style="max-width:640px">
        <${Field} label="Pay period"><${Select} value=${form['staffing.pay_period']} onValue=${set('staffing.pay_period')}
          options=${[{ value: 'weekly', label: 'Weekly' }, { value: 'biweekly', label: 'Every two weeks' }]} /></${Field}>
        ${form['staffing.pay_period'] === 'biweekly' && html`<${Field} label="A pay period started on" hint="Any past period start">
          <${Input} type="date" value=${form['staffing.pay_period_anchor']} onValue=${set('staffing.pay_period_anchor')} /></${Field}>`}
        <${Field} label="Round punches to" hint="Nearest N minutes when totaling hours (raw punches are kept)">
          <${Select} value=${String(form['staffing.clock_rounding_minutes'] || 0)} onValue=${set('staffing.clock_rounding_minutes')}
            options=${[0, 5, 6, 10, 15].map((m) => ({ value: String(m), label: m ? `${m} minutes` : 'No rounding' }))} /></${Field}>
        ${numberField('staffing.early_clock_in_minutes', 'Early clock-in window (minutes)', 'Punches this early count toward the upcoming shift')}
        ${numberField('staffing.auto_clock_out_hours', 'Auto clock-out after (hours)', 'Closes forgotten punches and flags them for review; 0 = never')}
        ${numberField('staffing.shift_reminder_minutes', 'Shift reminder (minutes before)', '0 = no reminders')}
      </div>
    </${Section}>
    <div class="settings-footer"><${Button} variant="primary" loading=${saving} onClick=${save}>Save rules</${Button}></div>
  </div>`;
}
