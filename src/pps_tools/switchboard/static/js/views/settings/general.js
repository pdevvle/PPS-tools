import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useStore, loadBootstrap } from '../../lib/store.js';
import { Button, Field, Input, Section, Select, Toggle, IconButton } from '../../ui/components.js';
import { toast, toastError } from '../../ui/overlay.js';

const DAYS = [['mon', 'Monday'], ['tue', 'Tuesday'], ['wed', 'Wednesday'], ['thu', 'Thursday'], ['fri', 'Friday'], ['sat', 'Saturday'], ['sun', 'Sunday']];
const ZONES = (Intl.supportedValuesOf ? Intl.supportedValuesOf('timeZone') : ['America/Phoenix', 'America/Los_Angeles', 'America/Denver', 'America/Chicago', 'America/New_York', 'UTC']);

function HoursEditor({ value, onChange }) {
  const setDay = (day, ranges) => onChange({ ...value, [day]: ranges });
  return html`<div class="hours-editor">
    ${DAYS.map(([key, label]) => {
    const ranges = value[key] || [];
    return html`<div class="hours-row" key=${key}>
        <${Toggle} checked=${ranges.length > 0} onChange=${(on) => setDay(key, on ? [['08:00', '17:00']] : [])} label=${label} />
        <div class="hours-ranges">
          ${ranges.length === 0 && html`<span class="muted text-sm">Closed</span>`}
          ${ranges.map((r, i) => html`<div class="row gap-1" key=${i}>
            <input type="time" class="input input-sm" value=${r[0]} onInput=${(e) => setDay(key, ranges.map((x, j) => (j === i ? [e.currentTarget.value, x[1]] : x)))} />
            <span class="muted">–</span>
            <input type="time" class="input input-sm" value=${r[1]} onInput=${(e) => setDay(key, ranges.map((x, j) => (j === i ? [x[0], e.currentTarget.value] : x)))} />
            ${ranges.length > 1 && html`<${IconButton} icon="x" size="sm" label="Remove" onClick=${() => setDay(key, ranges.filter((_, j) => j !== i))} />`}
          </div>`)}
          ${ranges.length > 0 && ranges.length < 3 && html`<${IconButton} icon="plus" size="sm" label="Add hours" onClick=${() => setDay(key, [...ranges, ['13:00', '17:00']])} />`}
        </div>
      </div>`;
  })}
  </div>`;
}

export default function General() {
  const settings = useStore((s) => s.settings);
  const [form, setForm] = useState(() => ({
    'org.name': settings['org.name'],
    'org.timezone': settings['org.timezone'],
    'org.week_start': settings['org.week_start'],
    'org.business_hours': settings['org.business_hours'],
    'inbox.undo_send_seconds': settings['inbox.undo_send_seconds'],
    'inbox.block_remote_images': settings['inbox.block_remote_images'],
    'inbox.sla_first_response_minutes': settings['inbox.sla_first_response_minutes'],
  }));
  const [saving, setSaving] = useState(false);
  const set = (k) => (v) => setForm({ ...form, [k]: v });
  const save = async () => {
    setSaving(true);
    try {
      await api.patch('/settings', {
        ...form,
        'org.week_start': Number(form['org.week_start']),
        'inbox.undo_send_seconds': Number(form['inbox.undo_send_seconds']),
        'inbox.sla_first_response_minutes': Number(form['inbox.sla_first_response_minutes']),
      });
      await loadBootstrap();
      toast('Settings saved');
    } catch (err) { toastError(err); } finally { setSaving(false); }
  };
  return html`<div>
    <${Section} title="Business">
      <div class="form-grid" style="max-width:620px">
        <${Field} label="Business name"><${Input} value=${form['org.name']} onValue=${set('org.name')} /></${Field}>
        <${Field} label="Timezone" hint="Used for business hours, schedules and reports"><${Select} value=${form['org.timezone']} onValue=${set('org.timezone')} options=${ZONES} /></${Field}>
        <${Field} label="Week starts on"><${Select} value=${String(form['org.week_start'])} onValue=${set('org.week_start')} options=${[{ value: '0', label: 'Sunday' }, { value: '1', label: 'Monday' }]} /></${Field}>
      </div>
    </${Section}>
    <${Section} title="Business hours" description="Rules can act differently outside these hours (e.g. send an after-hours auto-reply), and response-time reports only count open hours.">
      <${HoursEditor} value=${form['org.business_hours'] || {}} onChange=${set('org.business_hours')} />
    </${Section}>
    <${Section} title="Inbox">
      <div class="stack" style="max-width:620px">
        <div class="form-grid">
          <${Field} label="Undo send window (seconds)" hint="Messages wait this long before sending so you can take them back"><${Input} type="number" min="0" max="60" value=${form['inbox.undo_send_seconds']} onValue=${set('inbox.undo_send_seconds')} /></${Field}>
          <${Field} label="First response target (minutes)" hint="Conversations waiting longer are flagged as overdue"><${Input} type="number" min="0" value=${form['inbox.sla_first_response_minutes']} onValue=${set('inbox.sla_first_response_minutes')} /></${Field}>
        </div>
        <${Toggle} checked=${!!form['inbox.block_remote_images']} onChange=${set('inbox.block_remote_images')} label="Block remote images in email" hint="Stops senders from seeing when an email was opened" />
      </div>
    </${Section}>
    <div class="settings-footer"><${Button} variant="primary" loading=${saving} onClick=${save}>Save changes</${Button}></div>
  </div>`;
}
