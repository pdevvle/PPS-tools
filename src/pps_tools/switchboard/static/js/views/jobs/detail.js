// A single job: details, specs, steps (operations), checklist, files & proofs, activity.

import { html, useEffect, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { boot, can, me, useStore, user as lookupUser } from '../../lib/store.js';
import { navigate } from '../../lib/router.js';
import { useFetch, usePresence } from '../../lib/hooks.js';
import { fmtBytes, fmtDateTime, fmtDuration, fmtMoney, fmtTimeShort, fmtDate } from '../../lib/format.js';
import {
  Avatar, AvatarStack, Banner, Button, Card, Checkbox, Chip, Empty, ErrorBox, Field, Icon, IconButton, Input, Loading,
  PageHeader, ProgressBar, RelTime, Select, SidePanel, TextArea, cx,
} from '../../ui/components.js';
import { SidebarButton } from '../../ui/layout.js';
import { confirmDialog, promptDialog, showMenu, toast, toastError } from '../../ui/overlay.js';
import { DateTimeButton, pickEmoji, pickFromList, pickUsers } from '../../ui/pickers.js';
import { RichEditor, RichText, isEditorEmpty } from '../../ui/editor.js';
import {
  DueChip, PRIORITIES, PriorityChip, ProofChip, STATUS_LABEL, customerOf, moveJob, resourceOf, stageOf, stages,
} from './common.js';
import { CustomerField, SpecFields } from './new.js';

const STATUS_ICON = { pending: 'circle', in_progress: 'circle-play', done: 'circle-check' };
const NEXT_STATUS = { pending: 'in_progress', in_progress: 'done', done: 'pending' };

function useJob(id) {
  return useFetch(`/jobs/${id}`, {
    refetchOn: ['job.changed', 'reaction.changed', 'settings.changed'],
    filter: (e, type) => (type === 'job.changed' ? !e.id || e.id === id : type === 'reaction.changed' ? e.target_type === 'job_activity' : true),
  });
}

// -- header -------------------------------------------------------------------------

function TitleEditor({ job, onSave, editable }) {
  const [value, setValue] = useState(job.title);
  useEffect(() => setValue(job.title), [job.title]);
  if (!editable) return html`<h1 class="job-title-static">${job.title}</h1>`;
  const save = () => { if (value.trim() && value !== job.title) onSave({ title: value.trim() }); else setValue(job.title); };
  return html`<input class="job-title-input" value=${value} aria-label="Job title" maxLength="200"
    onInput=${(e) => setValue(e.currentTarget.value)} onBlur=${save}
    onKeyDown=${(e) => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') { setValue(job.title); e.currentTarget.blur(); } }} />`;
}

function stageMenu(anchor, job, reload) {
  showMenu(anchor, stages().map((st) => ({
    label: st.name, color: st.color, checked: st.id === job.stage_id,
    hint: st.is_done ? 'Counts as finished' : undefined,
    onSelect: async () => { try { await moveJob(job, st.id); reload(); } catch (err) { toastError(err); } },
  })), { width: 230 });
}

function Viewers({ id }) {
  const viewers = useStore((s) => s.presence[`job:${id}`] || []);
  const others = viewers.filter((v) => v.user_id !== me().id);
  if (!others.length) return null;
  return html`<span class="job-viewers" title=${others.map((v) => lookupUser(v.user_id).name).join(', ') + ' also viewing'}>
    <${AvatarStack} users=${others.map((v) => v.user_id)} size=${22} max=${3} /></span>`;
}

// -- summary & specs ----------------------------------------------------------------

function SummaryCard({ job, patch, manage }) {
  const [desc, setDesc] = useState(job.description || '');
  useEffect(() => setDesc(job.description || ''), [job.description]);
  const contact = job.contact ? { id: job.contact.id, name: job.contact.display_name, hint: job.contact.email || job.contact.phone } : null;
  const numberField = (key, label, step) => html`<${Field} label=${label}>
    <${Input} type="number" min="0" step=${step} disabled=${!manage} value=${job[key] ?? ''}
      onBlur=${(e) => { const v = e.currentTarget.value; const n = v === '' ? null : Number(v); if (n !== job[key]) patch({ [key]: n }); }} />
  </${Field}>`;
  const textField = (key, label, placeholder) => html`<${Field} label=${label}>
    <${Input} disabled=${!manage} value=${job[key] || ''} placeholder=${placeholder}
      onBlur=${(e) => { const v = e.currentTarget.value.trim(); if (v !== (job[key] || '')) patch({ [key]: v || null }); }} />
  </${Field}>`;
  return html`<${Card} title="Details" icon="clipboard-list">
    <div class="form-grid">
      <${Field} label="Customer" class="span-2">
        ${manage ? html`<${CustomerField} contact=${contact} onChange=${(c) => patch({ contact_id: c ? c.id : null, organization_id: null })} />`
    : html`<span>${customerOf(job) || '—'}</span>`}
        ${job.contact && html`<a class="text-sm" href=${`/contacts/${job.contact.id}`}>View contact</a>`}
      </${Field}>
      <${Field} label="Due">${manage
    ? html`<${DateTimeButton} value=${job.due_at} onChange=${(v) => patch({ due_at: v })} placeholder="No due date" title="Due" />`
    : html`<span>${job.due_at ? fmtDateTime(job.due_at) : '—'}</span>`}</${Field}>
      <${Field} label="Priority">${manage
    ? html`<${Select} value=${job.priority} onValue=${(v) => patch({ priority: v })} options=${PRIORITIES} />`
    : html`<${PriorityChip} priority=${job.priority} showNormal />`}</${Field}>
      ${numberField('quantity', 'Quantity', '1')}
      ${numberField('quote_amount', 'Quote ($)', '0.01')}
      ${textField('po_number', 'PO number', 'Customer PO')}
      ${numberField('estimated_minutes', 'Estimate (minutes)', '5')}
      ${textField('address', 'Delivery / install address', 'Pickup at the shop')}
      <${Field} label="Tags">
        <${Input} disabled=${!manage} value=${(job.tags || []).join(', ')} placeholder="Comma separated"
          onBlur=${(e) => { const tags = e.currentTarget.value.split(',').map((t) => t.trim()).filter(Boolean); if (tags.join(',') !== (job.tags || []).join(',')) patch({ tags }); }} />
      </${Field}>
      <${Field} label="Notes" class="span-2">
        <${TextArea} rows="3" autoSize disabled=${!manage} value=${desc} onValue=${setDesc}
          placeholder="Stock, special instructions, delivery details…"
          onBlur=${() => { if (desc !== (job.description || '')) patch({ description: desc }); }} />
      </${Field}>
    </div>
  </${Card}>`;
}

function SpecsCard({ job, patch, manage }) {
  const [specs, setSpecs] = useState(job.specs || {});
  const timer = useRef(null);
  useEffect(() => setSpecs(job.specs || {}), [JSON.stringify(job.specs || {})]);
  const onChange = (next) => {
    setSpecs(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => patch({ specs: next }), 700);
  };
  const fields = boot('job_fields');
  const extra = Object.entries(specs).filter(([k, v]) => !fields.some((f) => f.key === k) && v !== null && v !== '');
  return html`<${Card} title="Specs" icon="sliders-horizontal">
    ${manage ? html`<${SpecFields} value=${specs} onChange=${onChange} />` : html`<dl class="kv">
      ${fields.filter((f) => specs[f.key] !== undefined && specs[f.key] !== null && specs[f.key] !== '').map((f) => html`<div class="kv-row"><dt>${f.label}</dt>
        <dd>${f.type === 'checkbox' ? (specs[f.key] ? 'Yes' : 'No') : String(specs[f.key])}</dd></div>`)}
    </dl>`}
    ${extra.length > 0 && html`<dl class="kv mt-3">${extra.map(([k, v]) => html`<div class="kv-row"><dt>${k.replace(/_/g, ' ')}</dt><dd>${String(v)}</dd></div>`)}</dl>`}
  </${Card}>`;
}

// -- operations ---------------------------------------------------------------------

function OperationRow({ op, index, count, manage, canWork, onChanged, onMove, job }) {
  const resources = boot('resources');
  const skills = boot('job_skills');
  const save = async (fields) => {
    try { await api.patch(`/operations/${op.id}`, fields); onChanged(); } catch (err) { toastError(err); }
  };
  const res = resourceOf(op.resource_id);
  const statusBtn = html`<button type="button" class=${cx('op-status', `is-${op.status}`)} disabled=${!canWork}
    title=${`${STATUS_LABEL[op.status]}${canWork ? ' — click to change' : ''}`}
    onClick=${() => save({ status: NEXT_STATUS[op.status] })}><${Icon} name=${STATUS_ICON[op.status]} size=${18} /></button>`;
  const menu = (e) => showMenu(e.currentTarget, [
    { label: 'Move up', icon: 'arrow-up', disabled: index === 0, onSelect: () => onMove(index, -1) },
    { label: 'Move down', icon: 'arrow-down', disabled: index === count - 1, onSelect: () => onMove(index, 1) },
    { divider: true },
    { label: 'Mark not started', icon: 'circle', disabled: op.status === 'pending', onSelect: () => save({ status: 'pending' }) },
    { label: 'Unschedule', icon: 'calendar-x', disabled: !op.start_at, onSelect: () => save({ start_at: null }) },
    { label: 'Open in schedule', icon: 'chart-gantt', disabled: !op.start_at, onSelect: () => navigate(`/jobs/schedule?date=${op.start_at.slice(0, 10)}&focus=${op.id}`) },
    { divider: true },
    { label: 'Delete step', icon: 'trash', danger: true, onSelect: async () => {
      if (!(await confirmDialog({ title: `Delete “${op.name}”?`, danger: true, confirmLabel: 'Delete' }))) return;
      try { await api.del(`/operations/${op.id}`); onChanged(); } catch (err) { toastError(err); }
    } },
  ], { width: 220 });
  if (!manage) {
    return html`<div class=${cx('op-row', 'op-row-readonly', `is-${op.status}`)}>
      ${statusBtn}
      <div class="op-main">
        <div class="op-name">${op.name}</div>
        <div class="op-sub muted text-sm">${[res && res.name, op.user_id && lookupUser(op.user_id).name, fmtDuration(op.duration_minutes)].filter(Boolean).join(' · ')}</div>
      </div>
      <div class="op-when text-sm">${op.start_at ? `${fmtDate(op.start_at, { weekday: true })} ${fmtTimeShort(op.start_at)}–${fmtTimeShort(op.end_at)}` : html`<span class="muted">Not scheduled</span>`}</div>
    </div>`;
  }
  return html`<div class=${cx('op-row', `is-${op.status}`)}>
    ${statusBtn}
    <div class="op-fields">
      <input class="input input-sm op-name-input" value=${op.name} aria-label="Step name"
        onBlur=${(e) => { const v = e.currentTarget.value.trim(); if (v && v !== op.name) save({ name: v }); }} />
      <select class="input input-sm select" aria-label="Equipment" value=${op.resource_id || ''}
        onChange=${(e) => save({ resource_id: e.currentTarget.value ? Number(e.currentTarget.value) : null })}>
        <option value="">No equipment</option>
        ${resources.filter((r) => r.is_active || r.id === op.resource_id).map((r) => html`<option value=${r.id}>${r.name}</option>`)}
      </select>
      <button type="button" class="op-person" title="Who does this step"
        onClick=${(e) => pickUsers(e.currentTarget, { multi: false, selected: op.user_id ? [op.user_id] : [], title: 'Who does this step?',
    extra: op.user_id ? [{ id: 0, label: 'Nobody yet', icon: 'user-x' }] : [],
    onChange: (id) => save({ user_id: id || null }) })}>
        ${op.user_id ? html`<${Avatar} user=${op.user_id} size=${20} /><span class="truncate">${lookupUser(op.user_id).name}</span>`
    : html`<${Icon} name="user-plus" size=${15} /><span class="muted">Assign</span>`}
      </button>
      <select class="input input-sm select" aria-label="Skill needed" value=${op.skill_id || ''}
        onChange=${(e) => save({ skill_id: e.currentTarget.value ? Number(e.currentTarget.value) : null })}>
        <option value="">Any skill</option>
        ${skills.map((s) => html`<option value=${s.id}>${s.name}</option>`)}
      </select>
      <label class="op-duration"><input class="input input-sm" type="number" min="5" step="5" value=${op.duration_minutes} aria-label="Minutes"
        onBlur=${(e) => { const v = Number(e.currentTarget.value); if (v >= 5 && v !== op.duration_minutes) save({ duration_minutes: v }); }} /><span class="muted text-xs">min</span></label>
      <${DateTimeButton} value=${op.start_at} placeholder="Schedule" icon="calendar-clock" showPresets=${false}
        title=${`Start “${op.name}”`} onChange=${(v) => save({ start_at: v })} class="op-schedule" />
    </div>
    <${IconButton} icon="ellipsis-vertical" label="Step actions" size="sm" onClick=${menu} />
  </div>`;
}

function OperationsCard({ data, reload, manage }) {
  const { job, operations } = data;
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const myId = me().id;
  const canWork = (op) => manage || op.user_id === myId || job.assignee_ids.includes(myId);
  const move = async (index, delta) => {
    const ids = operations.map((o) => o.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(index + delta, 0, moved);
    try { await api.post(`/jobs/${job.id}/operations/reorder`, { ids }); reload(); } catch (err) { toastError(err); }
  };
  const add = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      await api.post(`/jobs/${job.id}/operations`, { name: name.trim(), duration_minutes: 60 });
      setName('');
      reload();
    } catch (err) { toastError(err); }
  };
  const fromTemplate = (e) => showMenu(e.currentTarget, boot('job_templates').map((t) => ({
    label: t.name, icon: 'layers', hint: t.description,
    onSelect: async () => { try { await api.post(`/jobs/${job.id}/operations/from-template`, { template_id: t.id }); reload(); } catch (err) { toastError(err); } },
  })), { width: 260 });
  const done = operations.filter((o) => o.status === 'done').length;
  return html`<${Card} title="Steps" icon="chart-gantt" subtitle=${operations.length ? `${done} of ${operations.length} done` : 'Break the job into steps to schedule them'}
    actions=${html`
      <${Button} size="sm" variant="ghost" icon="chart-gantt" onClick=${() => navigate('/jobs/schedule')}>Schedule</${Button}>
      ${manage && html`<${Button} size="sm" icon="layers" onClick=${fromTemplate}>From template</${Button}>`}`} pad=${false}>
    ${operations.length > 0 && html`<${ProgressBar} value=${done} max=${operations.length} tone=${job.is_done ? 'ok' : 'accent'} class="op-progress" />`}
    <div class="op-list">
      ${operations.map((op, i) => html`<${OperationRow} key=${op.id} op=${op} index=${i} count=${operations.length} manage=${manage}
        canWork=${canWork(op)} onChanged=${reload} onMove=${move} job=${job} />`)}
      ${!operations.length && html`<div class="op-empty muted">No steps yet.</div>`}
    </div>
    ${manage && (adding
    ? html`<form class="op-add" onSubmit=${add}>
          <${Input} value=${name} onValue=${setName} placeholder="Step name, e.g. Laminate" autoFocus class="input-sm" />
          <${Button} size="sm" variant="primary" type="submit">Add</${Button}>
          <${Button} size="sm" variant="ghost" onClick=${() => setAdding(false)}>Done</${Button}>
        </form>`
    : html`<div class="op-add"><${Button} size="sm" variant="ghost" icon="plus" onClick=${() => setAdding(true)}>Add step</${Button}></div>`)}
  </${Card}>`;
}

// -- checklist ----------------------------------------------------------------------

function ChecklistCard({ data, reload, manage }) {
  const { job, checklist } = data;
  const [title, setTitle] = useState('');
  const myId = me().id;
  const onJob = manage || job.assignee_ids.includes(myId) || data.operations.some((o) => o.user_id === myId);
  const toggle = async (item, value) => {
    try { await api.patch(`/job-checklist/${item.id}`, { is_done: value }); reload(); } catch (err) { toastError(err); }
  };
  const add = async (e) => {
    e.preventDefault();
    if (!title.trim()) return;
    try { await api.post(`/jobs/${job.id}/checklist`, { title: title.trim() }); setTitle(''); reload(); } catch (err) { toastError(err); }
  };
  const done = checklist.filter((c) => c.is_done).length;
  return html`<${Card} title="Checklist" icon="list-checks" subtitle=${checklist.length ? `${done}/${checklist.length}` : ''}>
    <div class="checklist">
      ${checklist.map((item) => html`<div key=${item.id} class=${cx('checklist-item', item.is_done && 'is-done')}>
        <${Checkbox} checked=${item.is_done} disabled=${!onJob} onChange=${(v) => toggle(item, v)} label=${item.title} />
        ${item.is_done && item.done_by && html`<span class="muted text-xs checklist-by" title=${item.done_at ? fmtDateTime(item.done_at) : ''}>${lookupUser(item.done_by).name.split(' ')[0]}</span>`}
        ${manage && html`<${IconButton} icon="x" size="sm" label="Remove" class="checklist-remove"
          onClick=${async () => { try { await api.del(`/job-checklist/${item.id}`); reload(); } catch (err) { toastError(err); } }} />`}
      </div>`)}
      ${!checklist.length && html`<p class="muted text-sm">Nothing to check off yet.</p>`}
    </div>
    ${manage && html`<form class="checklist-add" onSubmit=${add}>
      <${Input} value=${title} onValue=${setTitle} placeholder="Add an item" class="input-sm" />
      <${Button} size="sm" type="submit" icon="plus">Add</${Button}>
    </form>`}
  </${Card}>`;
}

// -- files --------------------------------------------------------------------------

function FilesCard({ data, reload, manage }) {
  const { job, files } = data;
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const myId = me().id;
  const onJob = manage || job.assignee_ids.includes(myId) || data.operations.some((o) => o.user_id === myId);
  const upload = async (list, proof = false) => {
    if (!list || !list.length) return;
    setBusy(true);
    try {
      const uploaded = await api.upload([...list]);
      await api.post(`/jobs/${job.id}/files`, { attachment_ids: uploaded.map((f) => f.id), is_proof: proof });
      toast(proof ? 'Proof added' : `${uploaded.length} file${uploaded.length === 1 ? '' : 's'} added`);
      reload();
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  const pick = (proof) => { input.current.dataset.proof = proof ? '1' : ''; input.current.click(); };
  return html`<${Card} title="Files & proofs" icon="paperclip" class=${cx(over && 'is-drop-target')}
    actions=${onJob && html`<${Button} size="sm" icon="upload" loading=${busy} onClick=${() => pick(false)}>Upload</${Button}>
      ${manage && html`<${Button} size="sm" icon="eye" onClick=${() => pick(true)}>Add proof</${Button}>`}`}>
    <input type="file" multiple hidden ref=${input} onChange=${(e) => { upload(e.currentTarget.files, e.currentTarget.dataset.proof === '1'); e.currentTarget.value = ''; }} />
    <div class="job-files" onDragOver=${(e) => { if (onJob) { e.preventDefault(); setOver(true); } }} onDragLeave=${() => setOver(false)}
      onDrop=${(e) => { e.preventDefault(); setOver(false); if (onJob) upload(e.dataTransfer.files); }}>
      ${files.map((f) => html`<div key=${f.id} class=${cx('job-file', f.is_proof && 'is-proof')}>
        <a class="job-file-thumb" href=${f.url} target="_blank" rel="noopener">
          ${f.is_image ? html`<img src=${f.url} alt="" loading="lazy" />` : html`<${Icon} name=${f.content_type === 'application/pdf' ? 'file-text' : 'file'} size=${22} />`}
        </a>
        <div class="job-file-info">
          <a class="job-file-name truncate" href=${f.url} target="_blank" rel="noopener" title=${f.filename}>${f.filename}</a>
          <div class="muted text-xs">${fmtBytes(f.size)}${f.uploaded_by ? ` · ${lookupUser(f.uploaded_by).name.split(' ')[0]}` : ''}</div>
        </div>
        ${manage ? html`<button type="button" class=${cx('proof-toggle', f.is_proof && 'is-on')} title="Show on the customer proof page"
          onClick=${async () => { try { await api.patch(`/jobs/${job.id}/files/${f.id}`, { is_proof: !f.is_proof }); reload(); } catch (err) { toastError(err); } }}>
          <${Icon} name="eye" size=${13} />${f.is_proof ? 'Proof' : 'Make proof'}</button>`
    : f.is_proof && html`<${Chip} tone="purple" size="sm">Proof</${Chip}>`}
        ${(manage || f.uploaded_by === myId) && html`<${IconButton} icon="trash" size="sm" label="Remove file" onClick=${async () => {
      if (!(await confirmDialog({ title: `Remove ${f.filename}?`, danger: true, confirmLabel: 'Remove' }))) return;
      try { await api.del(`/jobs/${job.id}/files/${f.id}`); reload(); } catch (err) { toastError(err); }
    }} />`}
      </div>`)}
      ${!files.length && html`<div class="job-files-empty muted text-sm">${onJob ? 'Drop artwork, proofs or photos here.' : 'No files yet.'}</div>`}
    </div>
  </${Card}>`;
}

// -- activity -----------------------------------------------------------------------

function names(ids) {
  return (ids || []).map((id) => lookupUser(id).name).join(', ');
}

function describe(item) {
  const d = item.data || {};
  switch (item.type) {
    case 'created': return d.template ? `created the job from the “${d.template}” template` : 'created the job';
    case 'stage_changed': return html`moved it ${d.from ? html`from <b>${d.from}</b> ` : ''}to <b>${d.to}</b>`;
    case 'assigned': return `added ${names(d.user_ids)}`;
    case 'unassigned': return `removed ${names(d.user_ids)}`;
    case 'due_changed': return d.to ? `set the due date to ${fmtDateTime(d.to)}` : 'removed the due date';
    case 'priority_changed': return `changed priority to ${d.to}`;
    case 'updated': return `edited ${(d.fields || []).map((f) => f.replace(/_/g, ' ')).join(', ')}`;
    case 'checked': return html`checked off “${d.item}”`;
    case 'unchecked': return html`unchecked “${d.item}”`;
    case 'operation_scheduled': return html`scheduled “${d.name}” for ${fmtDateTime(d.start_at)}`;
    case 'operation_unscheduled': return html`unscheduled “${d.name}”`;
    case 'operation_started': return html`started “${d.name}”`;
    case 'operation_done': return html`finished “${d.name}”`;
    case 'operation_reset': return html`reset “${d.name}”`;
    case 'operation_removed': return html`deleted the step “${d.name}”`;
    case 'template_applied': return `added steps from “${d.template}”`;
    case 'auto_scheduled': return `auto-scheduled ${d.count} step${d.count === 1 ? '' : 's'}`;
    case 'files_added': return `added ${(d.names || []).join(', ')}`;
    case 'proof_added': return `added a proof: ${(d.names || []).join(', ')}`;
    case 'file_removed': return `removed ${d.name}`;
    case 'shared': return 'shared the customer proof link';
    case 'unshared': return 'turned off the customer proof link';
    case 'proof_approved': return html`<b>${d.name}</b> approved the proof${d.comment ? html`: “${d.comment}”` : ''}`;
    case 'changes_requested': return html`<b>${d.name}</b> requested changes: “${d.comment}”`;
    case 'conversation_linked': return html`linked the conversation <a href=${`/inbox/c/${d.conversation_id}`}>${d.subject || 'conversation'}</a>`;
    case 'conversation_unlinked': return 'unlinked a conversation';
    case 'due_soon': return 'Due soon — the team was reminded';
    case 'overdue': return 'Overdue — the team was reminded';
    case 'archived': return 'archived the job';
    case 'unarchived': return 'restored the job';
    default: return item.type.replace(/_/g, ' ');
  }
}

const EVENT_ICON = {
  stage_changed: 'arrow-right', proof_approved: 'badge-check', changes_requested: 'pencil', due_soon: 'clock', overdue: 'triangle-alert',
  operation_done: 'circle-check', operation_started: 'circle-play', shared: 'link', created: 'plus', conversation_linked: 'mail',
};

function Comment({ item, reload }) {
  const mine = item.user_id === me().id;
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(item.body);
  const react = async (anchor) => pickEmoji(anchor, {
    onPick: async (emoji) => { try { await api.post('/reactions', { target_type: 'job_activity', target_id: item.id, emoji }); reload(); } catch (err) { toastError(err); } },
  });
  const menu = (e) => showMenu(e.currentTarget, [
    mine && { label: 'Edit', icon: 'pencil', onSelect: () => setEditing(true) },
    (mine || can('admin')) && { label: 'Delete', icon: 'trash', danger: true, onSelect: async () => {
      if (!(await confirmDialog({ title: 'Delete this comment?', danger: true, confirmLabel: 'Delete' }))) return;
      try { await api.del(`/job-activity/${item.id}`); reload(); } catch (err) { toastError(err); }
    } },
  ].filter(Boolean));
  const save = async () => {
    try { await api.patch(`/job-activity/${item.id}`, { body }); setEditing(false); reload(); } catch (err) { toastError(err); }
  };
  return html`<div class="job-comment">
    <${Avatar} user=${item.user_id} size=${28} />
    <div class="job-comment-main">
      <div class="job-comment-head"><b>${lookupUser(item.user_id).name}</b><${RelTime} value=${item.created_at} mode="ago" class="muted text-xs" />
        ${item.data && item.data.edited_at && html`<span class="muted text-xs">(edited)</span>`}
        <span class="grow"></span>
        <${IconButton} icon="smile-plus" size="sm" label="React" onClick=${(e) => react(e.currentTarget)} />
        ${(mine || can('admin')) && html`<${IconButton} icon="ellipsis" size="sm" label="Comment actions" onClick=${menu} />`}
      </div>
      ${editing ? html`<div class="job-comment-edit"><${RichEditor} value=${body} onChange=${setBody} mentions toolbar="mini" autofocus onSubmit=${save}
          onEscape=${() => setEditing(false)} />
        <div class="row mt-2"><${Button} size="sm" variant="primary" onClick=${save}>Save</${Button}><${Button} size="sm" variant="ghost" onClick=${() => setEditing(false)}>Cancel</${Button}></div></div>`
    : html`<${RichText} html=${item.body} class="job-comment-body" />`}
      ${item.reactions && item.reactions.length > 0 && html`<div class="reactions">
        ${item.reactions.map((r) => html`<button type="button" class=${cx('reaction', r.user_ids.includes(me().id) && 'is-mine')}
          title=${names(r.user_ids)}
          onClick=${async () => { try { await api.post('/reactions', { target_type: 'job_activity', target_id: item.id, emoji: r.emoji }); reload(); } catch (err) { toastError(err); } }}>
          ${r.emoji} <span>${r.user_ids.length}</span></button>`)}
      </div>`}
    </div>
  </div>`;
}

function ActivityCard({ data, reload }) {
  const { job, activity } = data;
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const editor = useRef(null);
  const send = async () => {
    if (isEditorEmpty(body) || busy) return;
    setBusy(true);
    try {
      await api.post(`/jobs/${job.id}/comments`, { body });
      setBody('');
      editor.current && editor.current.clear();
      reload();
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  const items = showAll ? activity : activity.slice(-40);
  return html`<${Card} title="Activity" icon="activity">
    ${activity.length > items.length && html`<button type="button" class="btn btn-link text-sm" onClick=${() => setShowAll(true)}>Show ${activity.length - items.length} earlier</button>`}
    <div class="job-activity">
      ${items.map((item) => (item.type === 'comment'
    ? html`<${Comment} key=${item.id} item=${item} reload=${reload} />`
    : html`<div key=${item.id} class="job-event">
            <span class="job-event-icon"><${Icon} name=${EVENT_ICON[item.type] || 'circle-dot'} size=${12} /></span>
            <span class="job-event-text">${item.user_id ? html`<b>${lookupUser(item.user_id).name}</b> ` : ''}${describe(item)}</span>
            <${RelTime} value=${item.created_at} mode="ago" class="muted text-xs" />
          </div>`))}
    </div>
    <div class="job-composer">
      <${RichEditor} value=${body} onChange=${setBody} editorRef=${editor} mentions toolbar=${false}
        placeholder="Comment, or @mention a teammate…  (Ctrl/⌘+Enter to send)" onSubmit=${send} minHeight=${44} />
      <div class="job-composer-actions"><${Button} variant="primary" size="sm" icon="send" loading=${busy} disabled=${isEditorEmpty(body)} onClick=${send}>Comment</${Button}></div>
    </div>
  </${Card}>`;
}

// -- side panels --------------------------------------------------------------------

function PeoplePanel({ job, patch, manage }) {
  return html`<${SidePanel} title="People" icon="users" count=${job.assignee_ids.length}
    actions=${manage && html`<${IconButton} icon="user-plus" size="sm" label="Change people"
      onClick=${(e) => pickUsers(e.currentTarget, { selected: job.assignee_ids, multi: true, onChange: (ids) => patch({ assignee_ids: ids }) })} />`}>
    ${job.assignee_ids.length ? html`<div class="stack-sm">${job.assignee_ids.map((id) => html`<div class="row" key=${id}>
      <${Avatar} user=${id} size=${24} online="auto" /><span class="truncate">${lookupUser(id).name}</span>
      <span class="muted text-xs truncate">${lookupUser(id).title || ''}</span></div>`)}</div>`
    : html`<p class="muted text-sm">Nobody on this job yet.</p>`}
  </${SidePanel}>`;
}

function ProgressPanel({ job }) {
  const list = stages();
  const idx = list.findIndex((s) => s.id === job.stage_id);
  return html`<${SidePanel} title="Stage" icon="square-kanban">
    <ol class="stage-steps">
      ${list.map((s, i) => html`<li key=${s.id} class=${cx(i < idx && 'is-past', i === idx && 'is-current')}>
        <span class="stage-step-dot" style=${{ background: i <= idx ? (s.color || 'var(--accent)') : undefined }}></span>${s.name}</li>`)}
    </ol>
    ${job.stage_entered_at && html`<p class="muted text-xs mt-2">In ${stageOf(job.stage_id)?.name || 'this stage'} since ${fmtDateTime(job.stage_entered_at)}</p>`}
  </${SidePanel}>`;
}

function ProofPanel({ job, files, reload, manage }) {
  const proofs = files.filter((f) => f.is_proof);
  const share = async () => {
    try {
      const res = await api.post(`/jobs/${job.id}/share`);
      try { await navigator.clipboard.writeText(res.url); toast('Customer link copied'); } catch { toast('Customer link ready'); }
      reload();
    } catch (err) { toastError(err); }
  };
  const unshare = async () => {
    if (!(await confirmDialog({ title: 'Turn off the customer link?', message: 'The current link stops working. You can create a new one later.', confirmLabel: 'Turn off' }))) return;
    try { await api.del(`/jobs/${job.id}/share`); reload(); } catch (err) { toastError(err); }
  };
  return html`<${SidePanel} title="Customer proof" icon="eye">
    ${job.proof_status && html`<div class="row mb-2"><${ProofChip} status=${job.proof_status} />
      ${job.proof_decided_by && html`<span class="muted text-xs">${job.proof_decided_by} · ${fmtDateTime(job.proof_decided_at)}</span>`}</div>`}
    ${job.public_url
    ? html`<div class="stack-sm">
        <div class="proof-link"><input class="input input-sm" readOnly value=${job.public_url} onFocus=${(e) => e.currentTarget.select()} />
          <${IconButton} icon="copy" size="sm" label="Copy link" onClick=${async () => { try { await navigator.clipboard.writeText(job.public_url); toast('Copied'); } catch { /* ignore */ } }} /></div>
        <div class="row"><a class="btn btn-sm btn-secondary" href=${job.public_url} target="_blank" rel="noopener"><${Icon} name="external-link" size=${14} />Preview</a>
          ${manage && html`<${Button} size="sm" variant="ghost" onClick=${unshare}>Turn off</${Button}>`}</div>
        ${!proofs.length && html`<p class="muted text-xs">Mark a file as a proof so the customer can review it.</p>`}
      </div>`
    : html`<p class="muted text-sm">Send the customer a page where they can see the job's status and approve proofs.</p>
      ${manage && html`<${Button} size="sm" icon="link" onClick=${share}>Create customer link</${Button}>`}`}
  </${SidePanel}>`;
}

function ConversationsPanel({ data, reload, manage }) {
  const { job, conversations, hidden_conversation_count: hidden } = data;
  const link = async (anchor) => {
    let items = [];
    try {
      const res = await api.get('/conversations', { mailbox: 'all', limit: 40, q: customerOf(job) || undefined });
      items = res.items;
      if (!items.length) items = (await api.get('/conversations', { mailbox: 'all', limit: 40 })).items;
    } catch (err) { toastError(err); return; }
    pickFromList(anchor, {
      title: 'Link a conversation',
      placeholder: 'Search conversations…',
      items: items.filter((c) => !conversations.some((x) => x.id === c.id)).map((c) => ({
        id: c.id, label: c.subject || (c.contact && c.contact.display_name) || 'Conversation', hint: (c.contact && c.contact.display_name) || c.preview, icon: 'mail',
      })),
      multi: false,
      width: 320,
      onChange: async (id) => { try { await api.post(`/jobs/${job.id}/conversations`, { conversation_id: id }); reload(); } catch (err) { toastError(err); } },
    });
  };
  return html`<${SidePanel} title="Conversations" icon="mail" count=${conversations.length}
    actions=${manage && can('inbox') && html`<${IconButton} icon="link" size="sm" label="Link a conversation" onClick=${(e) => link(e.currentTarget)} />`}>
    ${conversations.map((c) => html`<div class="linked-conv" key=${c.id}>
      <a href=${`/inbox/c/${c.id}`} class="linked-conv-main">
        <${Icon} name=${c.channel_type === 'sms' ? 'smartphone' : c.channel_type === 'chat' ? 'message-square' : 'mail'} size=${14} />
        <span class="truncate">${c.subject || c.contact_name || 'Conversation'}</span>
      </a>
      <${RelTime} value=${c.last_activity_at} class="muted text-xs" />
      ${manage && html`<${IconButton} icon="unlink" size="sm" label="Unlink" class="linked-conv-unlink"
        onClick=${async () => { try { await api.del(`/jobs/${job.id}/conversations/${c.id}`); reload(); } catch (err) { toastError(err); } }} />`}
    </div>`)}
    ${!conversations.length && !hidden && html`<p class="muted text-sm">No emails or texts linked.</p>`}
    ${hidden > 0 && html`<p class="muted text-xs">${hidden} linked conversation${hidden === 1 ? '' : 's'} you can't open.</p>`}
  </${SidePanel}>`;
}

function TasksPanel({ tasks }) {
  if (!tasks || !tasks.length) return null;
  return html`<${SidePanel} title="Tasks" icon="square-check-big" count=${tasks.filter((t) => t.status !== 'done').length}>
    ${tasks.map((t) => html`<a key=${t.id} class=${cx('job-task', t.status === 'done' && 'is-done')} href=${`/tasks?task=${t.id}`}>
      <${Icon} name=${t.status === 'done' ? 'circle-check' : 'circle'} size=${14} />
      <span class="truncate grow">${t.title}</span>
      ${t.assignee_id && html`<${Avatar} user=${t.assignee_id} size=${18} />`}
    </a>`)}
  </${SidePanel}>`;
}

function TimePanel({ data }) {
  const { time, estimate_minutes: estimate, actual_minutes: actual } = data;
  if (!estimate && !actual) return null;
  const over = estimate && actual > estimate;
  return html`<${SidePanel} title="Time" icon="timer">
    <div class="row text-sm mb-2"><span class="grow">Clocked ${fmtDuration(actual || 0)}</span><span class="muted">Est. ${estimate ? fmtDuration(estimate) : '—'}</span></div>
    ${estimate ? html`<${ProgressBar} value=${actual || 0} max=${estimate} tone=${over ? 'danger' : 'accent'} />` : null}
    ${time.by_user.map((r) => html`<div class="row text-sm mt-2" key=${r.user_id}><${Avatar} user=${r.user_id} size=${18} />
      <span class="grow truncate">${lookupUser(r.user_id).name}</span>
      ${time.running_user_ids.includes(r.user_id) && html`<span class="live-dot" title="Clocked in on this job"></span>`}
      <span class="tabular">${fmtDuration(r.minutes)}</span></div>`)}
  </${SidePanel}>`;
}

// -- page ---------------------------------------------------------------------------

export function JobDetail({ id }) {
  const { data, error, loading, reload, setData } = useJob(id);
  usePresence(`job:${id}`);
  useStore((s) => s.boot.job_stages);
  const manage = can('manage_jobs');
  if (error) {
    return html`<div class="jobs-page"><${PageHeader} leading=${html`<${SidebarButton} />`} title="Job" />
      ${error.status === 404 ? html`<${Empty} icon="square-kanban" title="Job not found" action=${html`<${Button} onClick=${() => navigate('/jobs')}>Back to the board</${Button}>`}>It may have been deleted.</${Empty}>`
    : html`<${ErrorBox} error=${error} retry=${reload} />`}</div>`;
  }
  if (loading && !data) return html`<div class="jobs-page"><${Loading} /></div>`;
  const { job } = data;
  const patch = async (fields) => {
    setData((d) => ({ ...d, job: { ...d.job, ...fields } }));
    try { await api.patch(`/jobs/${job.id}`, fields); } catch (err) { toastError(err); }
    reload({ quiet: true });
  };
  const st = stageOf(job.stage_id);
  const more = (e) => showMenu(e.currentTarget, [
    { label: 'Copy link', icon: 'link', onSelect: async () => { try { await navigator.clipboard.writeText(`${location.origin}/jobs/${job.id}`); toast('Link copied'); } catch { /* ignore */ } } },
    manage && { label: 'Save as template', icon: 'layers', onSelect: async () => {
      const name = await promptDialog({ title: 'Save as template', label: 'Template name', value: job.title, confirmLabel: 'Save template' });
      if (!name) return;
      try { await api.post('/job-templates', { from_job_id: job.id, name }); toast('Template saved'); } catch (err) { toastError(err); }
    } },
    manage && { divider: true },
    manage && { label: job.archived_at ? 'Unarchive' : 'Archive', icon: 'archive', onSelect: async () => {
      try { await api.post(`/jobs/${job.id}/archive`, { archived: !job.archived_at }); reload(); } catch (err) { toastError(err); }
    } },
    can('admin') && { label: 'Delete job', icon: 'trash', danger: true, onSelect: async () => {
      if (!(await confirmDialog({ title: `Delete ${job.number}?`, message: 'This removes the job, its steps, files and activity for good.', danger: true, confirmLabel: 'Delete' }))) return;
      try { await api.del(`/jobs/${job.id}`); toast(`${job.number} deleted`); navigate('/jobs'); } catch (err) { toastError(err); }
    } },
  ].filter(Boolean), { width: 220 });

  return html`<div class="jobs-page job-detail-page">
    <header class="page-header job-header">
      <${SidebarButton} />
      <${IconButton} icon="arrow-left" label="Back" onClick=${() => (history.length > 1 ? history.back() : navigate('/jobs'))} />
      <div class="job-header-main">
        <div class="job-header-meta"><span class="job-number">${job.number}</span>
          ${job.archived_at && html`<${Chip} tone="muted" size="sm" icon="archive">Archived</${Chip}>`}
          <${PriorityChip} priority=${job.priority} /><${DueChip} job=${job} /><${ProofChip} status=${job.proof_status} /></div>
        <${TitleEditor} job=${job} editable=${manage} onSave=${patch} />
      </div>
      <${Viewers} id=${job.id} />
      <div class="page-header-actions">
        <button type="button" class="btn btn-secondary stage-button" disabled=${!manage} onClick=${(e) => stageMenu(e.currentTarget, job, () => reload({ quiet: true }))}>
          <span class="kanban-dot" style=${{ background: (st && st.color) || 'var(--text-3)' }}></span><span class="btn-label">${st ? st.name : 'No stage'}</span>
          ${manage && html`<${Icon} name="chevron-down" size=${14} />`}
        </button>
        <${IconButton} icon="ellipsis" label="More" variant="secondary" onClick=${more} />
      </div>
    </header>
    <div class="job-detail">
      <div class="job-detail-main">
        ${job.proof_status === 'changes_requested' && html`<${Banner} tone="warn" icon="pencil">
          ${job.proof_decided_by} asked for changes to the proof — see the activity below.</${Banner}>`}
        <${SummaryCard} job=${job} patch=${patch} manage=${manage} />
        <${OperationsCard} data=${data} reload=${() => reload({ quiet: true })} manage=${manage} />
        <div class="job-two-col">
          <${ChecklistCard} data=${data} reload=${() => reload({ quiet: true })} manage=${manage} />
          <${SpecsCard} job=${job} patch=${patch} manage=${manage} />
        </div>
        <${FilesCard} data=${data} reload=${() => reload({ quiet: true })} manage=${manage} />
        <${ActivityCard} data=${data} reload=${() => reload({ quiet: true })} />
      </div>
      <aside class="job-detail-side">
        <${PeoplePanel} job=${job} patch=${patch} manage=${manage} />
        <${ProgressPanel} job=${job} />
        <${ProofPanel} job=${job} files=${data.files} reload=${() => reload({ quiet: true })} manage=${manage} />
        <${ConversationsPanel} data=${data} reload=${() => reload({ quiet: true })} manage=${manage} />
        <${TasksPanel} tasks=${data.tasks} />
        <${TimePanel} data=${data} />
        <div class="job-side-foot muted text-xs">Created ${fmtDateTime(job.created_at)}${job.created_by ? ` by ${lookupUser(job.created_by).name}` : ''}
          ${job.quote_amount != null && html`<br />Quoted ${fmtMoney(job.quote_amount)}`}</div>
      </aside>
    </div>
  </div>`;
}

export default JobDetail;
