// Inbox settings sections: my signature, canned responses, labels.

import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch } from '../../lib/hooks.js';
import { useStore, getState, setState, can } from '../../lib/store.js';
import { Button, Chip, ColorChoices, Empty, Field, IconButton, Input, Loading, Section, Select, SearchInput } from '../../ui/components.js';
import { Modal, openModal, toast, toastError, confirmDialog } from '../../ui/overlay.js';
import { RichEditor, RichText } from '../../ui/editor.js';

const VARIABLES = [
  ['{{contact.first_name}}', 'Customer first name'], ['{{contact.name}}', 'Customer full name'],
  ['{{user.first_name}}', 'Your first name'], ['{{user.name}}', 'Your full name'], ['{{user.title}}', 'Your title'],
  ['{{org.name}}', 'Business name'], ['{{conversation.subject}}', 'Subject'],
];

export function SignatureSettings() {
  const me = useStore((s) => s.me);
  const [value, setValue] = useState(me.prefs?.signature_html || '');
  const [saving, setSaving] = useState(false);
  const { data } = useFetch('/me/signature');
  const save = async () => {
    setSaving(true);
    try {
      const res = await api.patch('/me/prefs', { signature_html: value || null });
      setState({ me: { ...getState().me, prefs: res.prefs } });
      toast('Signature saved');
    } catch (err) { toastError(err); } finally { setSaving(false); }
  };
  return html`<div>
    <${Section} title="Your email signature" description="Added below emails you send. Leave it empty to use each account's shared signature (set by an admin in Channels).">
      <div class="card"><${RichEditor} value=${value} onChange=${setValue} toolbar="mini" placeholder="e.g. Sam Patel · Customer Service · Priority Print Service" minHeight=${120} /></div>
      <div class="row mt-3"><${Button} variant="primary" loading=${saving} onClick=${save}>Save signature</${Button}></div>
    </${Section}>
    ${!value && data?.effective_html && html`<${Section} title="Currently used" description="From the account's shared signature.">
      <div class="card"><div class="card-body"><${RichText} html=${data.effective_html} /></div></div>
    </${Section}>`}
  </div>`;
}

function ResponseForm({ response, close, onSaved }) {
  const teams = useStore((s) => s.teams);
  const [form, setForm] = useState(() => ({
    title: response?.title || '', shortcut: response?.shortcut || '', subject: response?.subject || '', folder: response?.folder || '',
    body_html: response?.body_html || '', visibility: response?.visibility || 'shared', team_id: response?.team_id || '',
  }));
  const set = (k) => (v) => setForm({ ...form, [k]: v });
  const submit = async (e) => {
    e.preventDefault();
    try {
      const payload = { ...form, team_id: form.visibility === 'team' ? Number(form.team_id) || null : null };
      if (response) await api.patch(`/responses/${response.id}`, payload);
      else await api.post('/responses', payload);
      onSaved();
      close();
    } catch (err) { toastError(err); }
  };
  return html`<${Modal} title=${response ? 'Edit response' : 'New canned response'} size="lg" onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="response-form">Save</${Button}>`}>
    <form id="response-form" class="stack" onSubmit=${submit}>
      <div class="form-grid">
        <${Field} label="Name"><${Input} value=${form.title} onValue=${set('title')} required autoFocus placeholder="Proof ready" /></${Field}>
        <${Field} label="Shortcut" hint="Type /shortcut in the composer"><${Input} value=${form.shortcut} onValue=${set('shortcut')} placeholder="proof" /></${Field}>
        <${Field} label="Subject (optional)"><${Input} value=${form.subject} onValue=${set('subject')} /></${Field}>
        <${Field} label="Folder (optional)"><${Input} value=${form.folder} onValue=${set('folder')} placeholder="Orders" /></${Field}>
        <${Field} label="Who can use it">
          <${Select} value=${form.visibility} onValue=${set('visibility')} options=${[{ value: 'shared', label: 'Everyone' }, { value: 'team', label: 'A team' }, { value: 'personal', label: 'Only me' }]} />
        </${Field}>
        ${form.visibility === 'team' && html`<${Field} label="Team"><${Select} value=${String(form.team_id)} onValue=${set('team_id')} placeholder="Choose a team"
          options=${teams.map((t) => ({ value: String(t.id), label: t.name }))} /></${Field}>`}
      </div>
      <${Field} label="Message">
        <div class="card"><${RichEditor} value=${form.body_html} onChange=${set('body_html')} toolbar="full" minHeight=${160} /></div>
      </${Field}>
      <div class="vars-help">
        <span class="muted text-sm">Variables:</span>
        ${VARIABLES.map(([v, label]) => html`<button type="button" key=${v} class="var-chip" title=${label}
          onClick=${() => { navigator.clipboard?.writeText(v); toast(`Copied ${v}`); }}>${v}</button>`)}
      </div>
    </form>
  </${Modal}>`;
}

export function ResponsesSettings() {
  const { data, loading, reload } = useFetch('/responses');
  const [q, setQ] = useState('');
  const me = useStore((s) => s.me);
  const open = (response) => openModal((close) => html`<${ResponseForm} response=${response} close=${close} onSaved=${reload} />`);
  const remove = async (r) => {
    if (!(await confirmDialog({ title: `Delete “${r.title}”?`, danger: true, confirmLabel: 'Delete' }))) return;
    api.del(`/responses/${r.id}`).then(reload).catch(toastError);
  };
  const items = (data?.items || []).filter((r) => !q || (r.title + ' ' + (r.shortcut || '') + ' ' + (r.folder || '')).toLowerCase().includes(q.toLowerCase()));
  return html`<${Section} title="Canned responses" description="Reusable replies with variables. Type / in any composer to insert one."
    actions=${html`<${Button} variant="primary" icon="plus" onClick=${() => open(null)}>New response</${Button}>`}>
    <${SearchInput} value=${q} onValue=${setQ} placeholder="Search responses" class="mb-3" />
    ${loading && !data ? html`<${Loading} />` : !items.length ? html`<${Empty} icon="message-square-text" title="No canned responses">Save the replies you send all the time.</${Empty}>` : html`
    <div class="settings-list">
      ${items.map((r) => html`<div class="settings-list-row" key=${r.id}>
        <div class="grow stack-0">
          <div class="row"><span class="strong">${r.title}</span>${r.shortcut && html`<${Chip} size="sm">/${r.shortcut}</${Chip}>`}${r.folder && html`<${Chip} size="sm" tone="muted">${r.folder}</${Chip}>`}${r.visibility !== 'shared' && html`<${Chip} size="sm" tone="purple">${r.visibility === 'personal' ? 'Only me' : 'Team'}</${Chip}>`}</div>
          <div class="muted text-sm truncate">${(r.body_html || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()}</div>
        </div>
        <span class="muted text-sm nowrap">${r.usage_count} uses</span>
        ${(r.visibility !== 'personal' || r.owner_user_id === me.id) && html`
          <${IconButton} icon="pencil" label="Edit" onClick=${() => open(r)} />
          <${IconButton} icon="trash" label="Delete" onClick=${() => remove(r)} />`}
      </div>`)}
    </div>`}
  </${Section}>`;
}

function LabelForm({ label, close }) {
  const [form, setForm] = useState({ name: label?.name || '', color: label?.color || '#3b5bdb', visibility: label?.visibility || 'shared' });
  const submit = async (e) => {
    e.preventDefault();
    try {
      if (label) await api.patch(`/labels/${label.id}`, { name: form.name, color: form.color });
      else await api.post('/labels', form);
      close();
    } catch (err) { toastError(err); }
  };
  return html`<${Modal} title=${label ? 'Edit label' : 'New label'} size="sm" onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="label-form">Save</${Button}>`}>
    <form id="label-form" class="stack" onSubmit=${submit}>
      <${Field} label="Name"><${Input} value=${form.name} onValue=${(v) => setForm({ ...form, name: v })} required autoFocus /></${Field}>
      <${Field} label="Color"><${ColorChoices} value=${form.color} onChange=${(c) => setForm({ ...form, color: c })} /></${Field}>
      ${!label && html`<${Field} label="Visible to"><${Select} value=${form.visibility} onValue=${(v) => setForm({ ...form, visibility: v })}
        options=${[{ value: 'shared', label: 'Everyone' }, { value: 'personal', label: 'Only me' }]} /></${Field}>`}
    </form>
  </${Modal}>`;
}

export function LabelsSettings() {
  const labels = useStore((s) => s.boot.labels || []);
  const meId = useStore((s) => s.me.id);
  const open = (label) => openModal((close) => html`<${LabelForm} label=${label} close=${close} />`);
  const remove = async (l) => {
    if (!(await confirmDialog({ title: `Delete “${l.name}”?`, message: 'It is removed from every conversation.', danger: true, confirmLabel: 'Delete' }))) return;
    api.del(`/labels/${l.id}`).catch(toastError);
  };
  const editable = (l) => l.visibility === 'personal' ? l.owner_user_id === meId : can('inbox');
  return html`<${Section} title="Labels" description="Organize conversations across channels. Shared labels are visible to everyone; personal labels only to you. Rules can add labels automatically."
    actions=${html`<${Button} variant="primary" icon="plus" onClick=${() => open(null)}>New label</${Button}>`}>
    ${!labels.length ? html`<${Empty} icon="tags" title="No labels" />` : html`<div class="settings-list">
      ${labels.map((l) => html`<div class="settings-list-row" key=${l.id}>
        <${Chip} color=${l.color}>${l.name}</${Chip}>
        <span class="grow muted text-sm">${l.visibility === 'personal' ? 'Only you' : 'Everyone'}</span>
        <a class="btn-link text-sm" href=${`/inbox/label/${l.id}`}>View</a>
        ${editable(l) && html`<${IconButton} icon="pencil" label="Edit" onClick=${() => open(l)} /><${IconButton} icon="trash" label="Delete" onClick=${() => remove(l)} />`}
      </div>`)}
    </div>`}
  </${Section}>`;
}
