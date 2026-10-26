// "New job" modal. openNewJob({ conversation, contact, stageId, onCreated, navigateTo })
// Prefills from a conversation (title, customer) and can ask the AI assistant to read
// the email ("Fill from email") when that module is installed and configured.

import { html, useEffect, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { boot, can } from '../../lib/store.js';
import { navigate } from '../../lib/router.js';
import { useDebounced } from '../../lib/hooks.js';
import { AvatarStack, Banner, Button, Chip, Field, Icon, Input, Segmented, Select, TextArea, cx } from '../../ui/components.js';
import { Modal, openModal, toast, toastError } from '../../ui/overlay.js';
import { DateTimeButton, pickUsers } from '../../ui/pickers.js';
import { PRIORITIES, stages } from './common.js';

let aiMissing = false; // remember a 404 so we stop offering it

export function SpecFields({ value, onChange, compact }) {
  const fields = boot('job_fields');
  const set = (key, v) => onChange({ ...value, [key]: v });
  if (!fields.length) return html`<p class="muted text-sm">No spec fields yet — add them in Settings → Spec fields.</p>`;
  return html`<div class=${cx('form-grid', compact && 'spec-grid-compact')}>
    ${fields.map((f) => {
    const v = value[f.key];
    let control;
    if (f.type === 'select') {
      const opts = [...f.options];
      if (v && !opts.includes(v)) opts.push(v);
      control = html`<${Select} value=${v || ''} placeholder="—" options=${opts} onValue=${(x) => set(f.key, x || null)} />`;
    } else if (f.type === 'checkbox') {
      control = html`<label class="checkbox"><input type="checkbox" checked=${!!v} onChange=${(e) => set(f.key, e.currentTarget.checked)} />
          <span class="checkbox-box"><${Icon} name="check" size=${12} strokeWidth=${3} /></span><span class="checkbox-label">Yes</span></label>`;
    } else if (f.type === 'number') {
      control = html`<${Input} type="number" value=${v ?? ''} onValue=${(x) => set(f.key, x === '' ? null : Number(x))} />`;
    } else if (f.type === 'date') {
      control = html`<${Input} type="date" value=${v || ''} onValue=${(x) => set(f.key, x || null)} />`;
    } else if (f.type === 'textarea') {
      control = html`<${TextArea} rows="2" autoSize value=${v || ''} onValue=${(x) => set(f.key, x)} />`;
    } else {
      control = html`<${Input} value=${v || ''} onValue=${(x) => set(f.key, x)} />`;
    }
    return html`<${Field} key=${f.key} label=${f.label} class=${f.type === 'textarea' ? 'span-2' : ''}>${control}</${Field}>`;
  })}
  </div>`;
}

// Customer picker: searches contacts (contacts module if present, else recent senders).
export function CustomerField({ contact, onChange }) {
  const [q, setQ] = useState('');
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const debounced = useDebounced(q, 200);
  useEffect(() => {
    if (!debounced.trim()) { setItems([]); return undefined; }
    let alive = true;
    (async () => {
      let rows = [];
      try {
        const res = await api.get('/contacts', { q: debounced, limit: 8 });
        rows = (res.items || []).map((c) => ({ id: c.id, name: c.display_name || c.name || c.email || c.phone, hint: c.email || c.phone || (c.organization && c.organization.name) }));
      } catch {
        try {
          const res = await api.get('/compose/recipients', { q: debounced });
          const seen = new Set();
          rows = (res.items || []).filter((r) => !seen.has(r.contact_id) && seen.add(r.contact_id))
            .map((r) => ({ id: r.contact_id, name: r.name || r.handle, hint: r.handle }));
        } catch { rows = []; }
      }
      if (alive) setItems(rows);
    })();
    return () => { alive = false; };
  }, [debounced]);
  if (contact) {
    return html`<div class="row"><${Chip} icon="contact-round" onRemove=${() => onChange(null)}>${contact.name}</${Chip}>
      ${contact.hint && html`<span class="muted text-sm truncate">${contact.hint}</span>`}</div>`;
  }
  return html`<div class="customer-field">
    <${Input} value=${q} placeholder="Search customers by name, email or phone" onValue=${(v) => { setQ(v); setOpen(true); }}
      onFocus=${() => setOpen(true)} onBlur=${() => setTimeout(() => setOpen(false), 150)} />
    ${open && items.length > 0 && html`<div class="customer-suggest">
      ${items.map((c) => html`<button type="button" key=${c.id} class="customer-suggest-item"
        onMouseDown=${(e) => { e.preventDefault(); onChange(c); setQ(''); setOpen(false); }}>
        <span class="strong">${c.name}</span>${c.hint && html`<span class="muted text-sm"> ${c.hint}</span>`}
      </button>`)}
    </div>`}
  </div>`;
}

function NewJobForm({ close, conversation, contact, stageId, onCreated, navigateTo = true }) {
  const templates = boot('job_templates');
  const allStages = stages().filter((s) => !s.is_done);
  const [form, setForm] = useState(() => ({
    template_id: '',
    title: conversation ? (conversation.subject || '') : '',
    stage_id: stageId || (allStages[0] && allStages[0].id) || '',
    priority: 'normal',
    due_at: null,
    quantity: '',
    quote_amount: '',
    description: '',
    assignee_ids: [],
  }));
  const [specs, setSpecs] = useState({});
  const [customer, setCustomer] = useState(() => {
    const c = contact || (conversation && conversation.contact);
    return c ? { id: c.id, name: c.display_name || c.name || c.email, hint: c.email || c.phone } : null;
  });
  const [steps, setSteps] = useState(0);
  const [busy, setBusy] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiNote, setAiNote] = useState(null);
  const titleRef = useRef(null);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  const chooseTemplate = async (id) => {
    set('template_id')(id);
    if (!id) { setSteps(0); return; }
    try {
      const { template } = await api.get(`/job-templates/${id}`);
      setSteps(template.operations.length);
      setSpecs((s) => ({ ...template.specs, ...Object.fromEntries(Object.entries(s).filter(([, v]) => v !== '' && v !== null && v !== undefined)) }));
      setForm((f) => ({ ...f, title: f.title || template.name }));
    } catch (err) { toastError(err); }
  };

  const fillFromEmail = async () => {
    setAiBusy(true);
    try {
      const res = await api.post('/ai/extract-job', { conversation_id: conversation.id });
      setForm((f) => ({
        ...f,
        title: res.title || f.title,
        description: res.description || f.description,
        quantity: res.quantity ?? f.quantity,
        due_at: res.due_at || f.due_at,
        priority: PRIORITIES.some((p) => p.value === res.priority) ? res.priority : f.priority,
      }));
      if (res.specs) setSpecs((s) => ({ ...s, ...res.specs }));
      setAiNote('Filled in from the email — check it over before saving.');
    } catch (err) {
      if (err.status === 404) { aiMissing = true; setAiNote('The AI assistant isn\'t installed.'); }
      else if (err.code === 'ai_not_configured') setAiNote('Turn on the AI assistant in Settings → AI assistant to use this.');
      else toastError(err);
    } finally { setAiBusy(false); }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.title.trim() && !form.template_id) { titleRef.current && titleRef.current.focus(); return; }
    setBusy(true);
    try {
      const payload = {
        ...form,
        template_id: form.template_id || null,
        stage_id: form.stage_id || null,
        quantity: form.quantity === '' ? null : Number(form.quantity),
        quote_amount: form.quote_amount === '' ? null : Number(form.quote_amount),
        contact_id: customer ? customer.id : null,
        conversation_id: conversation ? conversation.id : null,
        specs,
      };
      const { job } = await api.post('/jobs', payload);
      toast(`${job.number} created`, { action: navigateTo ? null : { label: 'Open', onClick: () => navigate(`/jobs/${job.id}`) } });
      close();
      onCreated && onCreated(job);
      if (navigateTo) navigate(`/jobs/${job.id}`);
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };

  return html`<${Modal} title="New job" icon="square-kanban" size="lg" onClose=${close}
    footer=${html`<span class="muted text-sm grow">${steps ? `${steps} steps and a checklist will be added from the template.` : ''}</span>
      <${Button} onClick=${close}>Cancel</${Button}>
      <${Button} variant="primary" type="submit" form="new-job-form" loading=${busy}>Create job</${Button}>`}>
    <form id="new-job-form" class="stack" onSubmit=${submit}>
      ${conversation && html`<${Banner} tone="info" icon="mail" action=${!aiMissing && html`<${Button} size="sm" icon="sparkles" loading=${aiBusy} onClick=${fillFromEmail}>Fill from email</${Button}>`}>
        Linked to “${conversation.subject || 'conversation'}”
      </${Banner}>`}
      ${aiNote && html`<${Banner} tone="warn" onClose=${() => setAiNote(null)}>${aiNote}</${Banner}>`}
      <div class="form-grid">
        <${Field} label="Template">
          <${Select} value=${form.template_id} placeholder="Start from scratch" onValue=${chooseTemplate}
            options=${templates.map((t) => ({ value: t.id, label: t.name }))} />
        </${Field}>
        <${Field} label="Stage">
          <${Select} value=${form.stage_id} onValue=${(v) => set('stage_id')(v ? Number(v) : '')}
            options=${stages().map((s) => ({ value: s.id, label: s.name }))} />
        </${Field}>
        <${Field} label="Title" class="span-2" required>
          <input ref=${titleRef} class="input" value=${form.title} placeholder="e.g. Business cards — 3 new agents"
            onInput=${(e) => set('title')(e.currentTarget.value)} autoFocus=${!conversation} />
        </${Field}>
        <${Field} label="Customer" class="span-2"><${CustomerField} contact=${customer} onChange=${setCustomer} /></${Field}>
        <${Field} label="Due"><${DateTimeButton} value=${form.due_at} onChange=${set('due_at')} placeholder="No due date" title="Due" /></${Field}>
        <${Field} label="Priority"><${Segmented} size="sm" value=${form.priority} onChange=${set('priority')} options=${PRIORITIES} /></${Field}>
        <${Field} label="Quantity"><${Input} type="number" min="0" value=${form.quantity} onValue=${set('quantity')} /></${Field}>
        <${Field} label="Quote ($)"><${Input} type="number" min="0" step="0.01" value=${form.quote_amount} onValue=${set('quote_amount')} /></${Field}>
        <${Field} label="People on this job" class="span-2">
          <div class="row">
            <${AvatarStack} users=${form.assignee_ids} max=${6} size=${24} />
            <${Button} size="sm" icon="user-plus" onClick=${(e) => pickUsers(e.currentTarget, { selected: form.assignee_ids, multi: true, onChange: set('assignee_ids') })}>
              ${form.assignee_ids.length ? 'Change' : 'Add people'}
            </${Button}>
          </div>
        </${Field}>
        <${Field} label="Notes" class="span-2"><${TextArea} rows="3" autoSize value=${form.description} onValue=${set('description')}
          placeholder="Anything the shop should know: stock, special instructions, delivery…" /></${Field}>
      </div>
      <details class="new-job-specs" open=${!!form.template_id}>
        <summary>Specs</summary>
        <${SpecFields} value=${specs} onChange=${setSpecs} />
      </details>
    </form>
  </${Modal}>`;
}

export function openNewJob(opts = {}) {
  if (!can('manage_jobs')) {
    toast("You don't have permission to create jobs", { tone: 'danger' });
    return () => {};
  }
  return openModal((close) => html`<${NewJobForm} close=${close} ...${opts} />`, { size: 'lg' });
}
