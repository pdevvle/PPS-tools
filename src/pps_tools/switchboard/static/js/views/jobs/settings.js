// Jobs settings: stages (board columns), spec fields, equipment and job templates.

import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { boot, loadBootstrap, useStore } from '../../lib/store.js';
import { useFetch } from '../../lib/hooks.js';
import { fmtDuration } from '../../lib/format.js';
import {
  Button, ColorDot, Empty, Field, IconButton, Input, Loading, Section, Select, TextArea, Toggle, cx,
} from '../../ui/components.js';
import { Modal, confirmDialog, openModal, toast, toastError } from '../../ui/overlay.js';
import { pickColor } from '../../ui/pickers.js';
import { SpecFields } from './new.js';

async function refresh() {
  try { await loadBootstrap(); } catch { /* the settings.changed event retries */ }
}

async function run(fn, success) {
  try {
    await fn();
    await refresh();
    if (success) toast(success);
    return true;
  } catch (err) {
    toastError(err);
    return false;
  }
}

function moveIds(list, index, delta) {
  const ids = list.map((x) => x.id);
  const [moved] = ids.splice(index, 1);
  ids.splice(index + delta, 0, moved);
  return ids;
}

function OrderButtons({ index, count, onMove }) {
  return html`<div class="order-buttons">
    <${IconButton} icon="chevron-up" size="sm" label="Move up" disabled=${index === 0} onClick=${() => onMove(index, -1)} />
    <${IconButton} icon="chevron-down" size="sm" label="Move down" disabled=${index === count - 1} onClick=${() => onMove(index, 1)} />
  </div>`;
}

// -- stages -------------------------------------------------------------------------

function DeleteStage({ stage, close }) {
  const others = boot('job_stages').filter((s) => s.id !== stage.id);
  const [target, setTarget] = useState(others[0] ? others[0].id : '');
  const remove = async () => {
    if (await run(() => api.del(`/job-stages/${stage.id}?move_to=${target}`), `${stage.name} deleted`)) close();
  };
  return html`<${Modal} title=${`Delete “${stage.name}”`} size="sm" onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="danger" onClick=${remove}>Delete stage</${Button}>`}>
    <p class="dialog-message">Jobs in this stage move to:</p>
    <${Select} value=${target} onValue=${(v) => setTarget(Number(v))} options=${others.map((s) => ({ value: s.id, label: s.name }))} />
  </${Modal}>`;
}

export function StagesSettings() {
  const stages = useStore((s) => s.boot.job_stages || []);
  const [name, setName] = useState('');
  const save = (stage, fields) => run(() => api.patch(`/job-stages/${stage.id}`, fields));
  const add = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    if (await run(() => api.post('/job-stages', { name: name.trim() }))) setName('');
  };
  const remove = async (stage) => {
    try {
      await api.del(`/job-stages/${stage.id}`);
      await refresh();
    } catch (err) {
      if (err.code === 'stage_in_use') openModal((close) => html`<${DeleteStage} stage=${stage} close=${close} />`, { size: 'sm' });
      else toastError(err);
    }
  };
  const move = (index, delta) => run(() => api.post('/job-stages/reorder', { ids: moveIds(stages, index, delta) }));
  return html`<${Section} title="Stages" description="The columns on the jobs board, in the order work flows through the shop. Jobs in a “finished” stage count as done.">
    <div class="settings-list">
      ${stages.map((s, i) => html`<div class="settings-list-row" key=${s.id}>
        <${OrderButtons} index=${i} count=${stages.length} onMove=${move} />
        <button type="button" class="color-swatch-btn" aria-label="Color" onClick=${(e) => pickColor(e.currentTarget, { value: s.color, onChange: (c) => save(s, { color: c }) })}>
          <${ColorDot} color=${s.color} size=${14} /></button>
        <input class="input input-sm grow" value=${s.name} aria-label="Stage name"
          onBlur=${(e) => { const v = e.currentTarget.value.trim(); if (v && v !== s.name) save(s, { name: v }); }} />
        <label class="row gap-1 text-sm nowrap" title="Limit how many jobs can sit in this stage">WIP
          <input class="input input-sm wip-input" type="number" min="0" value=${s.wip_limit || ''} placeholder="—"
            onBlur=${(e) => { const v = e.currentTarget.value === '' ? null : Number(e.currentTarget.value); if (v !== (s.wip_limit || null)) save(s, { wip_limit: v }); }} /></label>
        <${Toggle} checked=${s.is_done} onChange=${(v) => save(s, { is_done: v })} label="Finished" />
        <${IconButton} icon="trash" size="sm" label="Delete stage" onClick=${() => remove(s)} />
      </div>`)}
    </div>
    <form class="row mt-3" onSubmit=${add} style="max-width:420px">
      <${Input} value=${name} onValue=${setName} placeholder="New stage, e.g. Waiting on customer" />
      <${Button} type="submit" icon="plus">Add stage</${Button}>
    </form>
  </${Section}>`;
}

// -- spec fields --------------------------------------------------------------------

const FIELD_TYPES = [
  { value: 'text', label: 'Text' }, { value: 'textarea', label: 'Long text' }, { value: 'number', label: 'Number' },
  { value: 'select', label: 'Choice' }, { value: 'checkbox', label: 'Yes / no' }, { value: 'date', label: 'Date' },
];

function OptionsEditor({ field, close }) {
  const [text, setText] = useState((field.options || []).join('\n'));
  const save = async () => {
    if (await run(() => api.patch(`/job-fields/${field.id}`, { options: text.split('\n') }), 'Choices saved')) close();
  };
  return html`<${Modal} title=${`Choices for “${field.label}”`} size="sm" onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" onClick=${save}>Save</${Button}>`}>
    <${Field} label="One choice per line"><${TextArea} rows="8" value=${text} onValue=${setText} autoFocus /></${Field}>
  </${Modal}>`;
}

export function FieldsSettings() {
  const fields = useStore((s) => s.boot.job_fields || []);
  const [label, setLabel] = useState('');
  const [type, setType] = useState('text');
  const save = (f, values) => run(() => api.patch(`/job-fields/${f.id}`, values));
  const add = async (e) => {
    e.preventDefault();
    if (!label.trim()) return;
    if (await run(() => api.post('/job-fields', { label: label.trim(), type }))) setLabel('');
  };
  const remove = async (f) => {
    if (!(await confirmDialog({ title: `Remove “${f.label}”?`, message: 'Existing jobs keep the value they have, but it stops showing as a field.', danger: true, confirmLabel: 'Remove' }))) return;
    run(() => api.del(`/job-fields/${f.id}`));
  };
  const move = (index, delta) => run(() => api.post('/job-fields/reorder', { ids: moveIds(fields, index, delta) }));
  return html`<${Section} title="Spec fields" description="The details every job tracks — stock, size, ink, finishing. They show on the job and in the new-job form.">
    ${!fields.length && html`<${Empty} icon="sliders-horizontal" compact title="No spec fields">Add the details your shop needs on every job.</${Empty}>`}
    <div class="settings-list">
      ${fields.map((f, i) => html`<div class="settings-list-row" key=${f.id}>
        <${OrderButtons} index=${i} count=${fields.length} onMove=${move} />
        <input class="input input-sm grow" value=${f.label} aria-label="Field label"
          onBlur=${(e) => { const v = e.currentTarget.value.trim(); if (v && v !== f.label) save(f, { label: v }); }} />
        <${Select} class="input-sm field-type-select" value=${f.type} options=${FIELD_TYPES} onValue=${(v) => save(f, { type: v })} />
        <span class="field-choices">${f.type === 'select' && html`<${Button} size="sm" onClick=${() => openModal((close) => html`<${OptionsEditor} field=${f} close=${close} />`, { size: 'sm' })}>
          ${f.options.length} choice${f.options.length === 1 ? '' : 's'}</${Button}>`}</span>
        <span class="muted text-xs mono hide-mobile field-key" title=${f.key}>${f.key}</span>
        <${IconButton} icon="trash" size="sm" label="Remove field" onClick=${() => remove(f)} />
      </div>`)}
    </div>
    <form class="row mt-3" onSubmit=${add} style="max-width:520px">
      <${Input} value=${label} onValue=${setLabel} placeholder="Field label, e.g. Coating" />
      <${Select} value=${type} options=${FIELD_TYPES} onValue=${setType} style="width:140px" />
      <${Button} type="submit" icon="plus">Add</${Button}>
    </form>
  </${Section}>`;
}

// -- equipment ----------------------------------------------------------------------

export function ResourcesSettings() {
  const resources = useStore((s) => s.boot.resources || []);
  const locations = useStore((s) => s.boot.resource_locations || []);
  const [name, setName] = useState('');
  const [kind, setKind] = useState('');
  const save = (r, values) => run(() => api.patch(`/resources/${r.id}`, values));
  const add = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    if (await run(() => api.post('/resources', { name: name.trim(), kind: kind.trim() || null }))) { setName(''); setKind(''); }
  };
  const remove = async (r) => {
    if (!(await confirmDialog({ title: `Delete ${r.name}?`, message: 'Scheduled steps on it keep their times but lose their equipment. To keep history, switch it off instead.', danger: true, confirmLabel: 'Delete' }))) return;
    run(() => api.del(`/resources/${r.id}`));
  };
  const move = (index, delta) => run(() => api.post('/resources/reorder', { ids: moveIds(resources, index, delta) }));
  return html`<${Section} title="Equipment" description="Presses, cutters, vans — anything a job step books time on. Each gets its own row on the production schedule.">
    ${!resources.length && html`<${Empty} icon="factory" compact title="No equipment yet">Add your presses and finishing gear.</${Empty}>`}
    <div class="settings-list">
      ${resources.map((r, i) => html`<div class=${cx('settings-list-row', 'resource-row', !r.is_active && 'is-inactive')} key=${r.id}>
        <${OrderButtons} index=${i} count=${resources.length} onMove=${move} />
        <button type="button" class="color-swatch-btn" aria-label="Color" onClick=${(e) => pickColor(e.currentTarget, { value: r.color, onChange: (c) => save(r, { color: c }) })}>
          <${ColorDot} color=${r.color} size=${14} /></button>
        <input class="input input-sm grow" value=${r.name} aria-label="Name"
          onBlur=${(e) => { const v = e.currentTarget.value.trim(); if (v && v !== r.name) save(r, { name: v }); }} />
        <input class="input input-sm resource-kind" value=${r.kind || ''} placeholder="Kind" aria-label="Kind"
          onBlur=${(e) => { const v = e.currentTarget.value.trim(); if (v !== (r.kind || '')) save(r, { kind: v || null }); }} />
        ${locations.length > 0 && html`<${Select} class="input-sm hide-mobile" value=${r.location_id || ''} placeholder="Any location"
          options=${locations.map((l) => ({ value: l.id, label: l.name }))} onValue=${(v) => save(r, { location_id: v ? Number(v) : null })} />`}
        <label class="row gap-1 text-sm nowrap hide-mobile" title="Running cost per hour, for job costing">$/h
          <input class="input input-sm cost-input" type="number" min="0" step="0.01" value=${r.hourly_cost ?? ''}
            onBlur=${(e) => { const v = e.currentTarget.value === '' ? null : Number(e.currentTarget.value); if (v !== (r.hourly_cost ?? null)) save(r, { hourly_cost: v }); }} /></label>
        <${Toggle} checked=${r.is_active} onChange=${(v) => save(r, { is_active: v })} label="In use" />
        <${IconButton} icon="trash" size="sm" label="Delete" onClick=${() => remove(r)} />
      </div>`)}
    </div>
    <form class="row mt-3" onSubmit=${add} style="max-width:560px">
      <${Input} value=${name} onValue=${setName} placeholder="Name, e.g. Digital Press 3" />
      <${Input} value=${kind} onValue=${setKind} placeholder="Kind (press, cutter…)" style="max-width:180px" />
      <${Button} type="submit" icon="plus">Add</${Button}>
    </form>
  </${Section}>`;
}

// -- templates ----------------------------------------------------------------------

function TemplateEditor({ template, close, onSaved }) {
  const resources = boot('resources');
  const skills = boot('job_skills');
  const [form, setForm] = useState(() => ({
    name: template ? template.name : '',
    description: template ? template.description || '' : '',
    operations: template ? template.operations.map((o) => ({ ...o })) : [{ name: 'Prepress', duration_minutes: 30 }, { name: 'Print', duration_minutes: 60 }],
    checklist: template ? template.checklist.join('\n') : 'Files received\nProof approved\nQuality check',
    specs: template ? template.specs : {},
  }));
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const setOp = (i, k, v) => setForm((f) => ({ ...f, operations: f.operations.map((o, j) => (j === i ? { ...o, [k]: v } : o)) }));
  const moveOp = (i, d) => setForm((f) => {
    const ops = [...f.operations];
    const [x] = ops.splice(i, 1);
    ops.splice(i + d, 0, x);
    return { ...f, operations: ops };
  });
  const total = form.operations.reduce((n, o) => n + (Number(o.duration_minutes) || 0), 0);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    const payload = {
      name: form.name, description: form.description, specs: form.specs,
      operations: form.operations.filter((o) => (o.name || '').trim()),
      checklist: form.checklist.split('\n').map((x) => x.trim()).filter(Boolean),
    };
    try {
      if (template) await api.patch(`/job-templates/${template.id}`, payload);
      else await api.post('/job-templates', payload);
      await refresh();
      toast('Template saved');
      onSaved();
      close();
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  return html`<${Modal} title=${template ? `Edit “${template.name}”` : 'New job template'} icon="layers" size="lg" onClose=${close}
    footer=${html`<span class="muted text-sm grow">${form.operations.length} steps · ${fmtDuration(total)}</span>
      <${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="tmpl-form" loading=${busy}>Save template</${Button}>`}>
    <form id="tmpl-form" class="stack" onSubmit=${submit}>
      <div class="form-grid">
        <${Field} label="Name"><${Input} value=${form.name} onValue=${set('name')} required autoFocus placeholder="e.g. Postcards" /></${Field}>
        <${Field} label="Description"><${Input} value=${form.description} onValue=${set('description')} placeholder="When to use it" /></${Field}>
      </div>
      <${Field} label="Steps">
        <div class="tmpl-steps">
          ${form.operations.map((o, i) => html`<div class="tmpl-step" key=${i}>
            <${OrderButtons} index=${i} count=${form.operations.length} onMove=${moveOp} />
            <input class="input input-sm grow" value=${o.name} placeholder="Step name" onInput=${(e) => setOp(i, 'name', e.currentTarget.value)} />
            <select class="input input-sm select" value=${o.resource_id || ''} onChange=${(e) => setOp(i, 'resource_id', e.currentTarget.value ? Number(e.currentTarget.value) : null)} aria-label="Equipment">
              <option value="">No equipment</option>
              ${resources.map((r) => html`<option value=${r.id}>${r.name}</option>`)}
            </select>
            <select class="input input-sm select" value=${o.skill_id || ''} onChange=${(e) => setOp(i, 'skill_id', e.currentTarget.value ? Number(e.currentTarget.value) : null)} aria-label="Skill">
              <option value="">Any skill</option>
              ${skills.map((s) => html`<option value=${s.id}>${s.name}</option>`)}
            </select>
            <label class="op-duration"><input class="input input-sm" type="number" min="5" step="5" value=${o.duration_minutes || 60}
              onInput=${(e) => setOp(i, 'duration_minutes', Number(e.currentTarget.value))} aria-label="Minutes" /><span class="muted text-xs">min</span></label>
            <${IconButton} icon="x" size="sm" label="Remove step" onClick=${() => set('operations')(form.operations.filter((_, j) => j !== i))} />
          </div>`)}
          <div><${Button} size="sm" variant="ghost" icon="plus" onClick=${() => set('operations')([...form.operations, { name: '', duration_minutes: 30 }])}>Add step</${Button}></div>
        </div>
      </${Field}>
      <${Field} label="Checklist" hint="One item per line"><${TextArea} rows="4" autoSize value=${form.checklist} onValue=${set('checklist')} /></${Field}>
      <details class="new-job-specs"><summary>Default specs</summary><${SpecFields} value=${form.specs} onChange=${set('specs')} /></details>
    </form>
  </${Modal}>`;
}

export function TemplatesSettings() {
  const { data, loading, reload } = useFetch('/job-templates', { refetchOn: ['settings.changed'] });
  const open = (template) => openModal((close) => html`<${TemplateEditor} template=${template} close=${close} onSaved=${reload} />`, { size: 'lg' });
  const remove = async (t) => {
    if (!(await confirmDialog({ title: `Delete “${t.name}”?`, message: 'Jobs already created from it are not affected.', danger: true, confirmLabel: 'Delete' }))) return;
    if (await run(() => api.del(`/job-templates/${t.id}`))) reload();
  };
  const items = data ? data.items : [];
  return html`<${Section} title="Job templates" description="Recipes for the work you do most. A new job from a template gets its steps, checklist and default specs."
    actions=${html`<${Button} variant="primary" icon="plus" onClick=${() => open(null)}>New template</${Button}>`}>
    ${loading && !data && html`<${Loading} />`}
    ${data && !items.length && html`<${Empty} icon="layers" compact title="No templates yet">Create one, or use “Save as template” on any job.</${Empty}>`}
    <div class="settings-list">
      ${items.map((t) => html`<div class="settings-list-row" key=${t.id}>
        <div class="grow">
          <div class="strong">${t.name}</div>
          <div class="muted text-sm truncate">${t.description || ''}${t.description ? ' · ' : ''}${t.operations.length} steps · ${fmtDuration(t.operations.reduce((n, o) => n + (o.duration_minutes || 0), 0))} · ${t.checklist.length} checklist items</div>
        </div>
        <${Button} size="sm" icon="pencil" onClick=${() => open(t)}>Edit</${Button}>
        <${IconButton} icon="trash" size="sm" label="Delete template" onClick=${() => remove(t)} />
      </div>`)}
    </div>
  </${Section}>`;
}
