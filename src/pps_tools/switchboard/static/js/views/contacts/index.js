// Contacts: people and organizations, groups, merge, CSV import/export.
//   /contacts                 all contacts (?q= ?group= ?blocked=1)
//   /contacts/<id>            a contact
//   /contacts/orgs            organizations
//   /contacts/orgs/<id>       an organization

import { html, useEffect, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useDebounced, useFetch, useIsMobile } from '../../lib/hooks.js';
import { navigate } from '../../lib/router.js';
import { useStore } from '../../lib/store.js';
import { fmtDate, plural } from '../../lib/format.js';
import {
  Avatar, Button, Chip, Empty, ErrorBox, Field, Icon, IconButton, Input, Loading, RelTime, SearchInput, Segmented, Tabs,
  TextArea, cx,
} from '../../ui/components.js';
import { Modal, confirmDialog, openModal, promptDialog, showMenu, showPopover, toast, toastError } from '../../ui/overlay.js';
import { pickColor, pickFromList } from '../../ui/pickers.js';
import { ModuleLayout, SidebarButton, SidebarHeader, SidebarItem, SidebarSection } from '../../ui/layout.js';
import { registerCommands } from '../../ui/palette.js';
import { InlineText, composeLink, formatPhone, handleIcon, pickOrganization } from './shared.js';

const PAGE = 60;

// -- sidebar ------------------------------------------------------------------------

function ContactsSidebar({ route }) {
  const groups = useStore((s) => s.boot.contact_groups || []);
  const groupId = Number(route.query.group || 0);
  const newGroup = async () => {
    const name = await promptDialog({ title: 'New group', label: 'Name', placeholder: 'e.g. Restaurants', confirmLabel: 'Create group' });
    if (!name) return;
    try {
      const res = await api.post('/contact-groups', { name });
      navigate(`/contacts?group=${res.group.id}`);
    } catch (err) { toastError(err); }
  };
  const groupMenu = (e, g) => {
    e.preventDefault();
    e.stopPropagation();
    showMenu(e.currentTarget, [
      { label: 'Rename', icon: 'pencil', onSelect: async () => {
        const name = await promptDialog({ title: 'Rename group', value: g.name });
        if (name) api.patch(`/contact-groups/${g.id}`, { name }).catch(toastError);
      } },
      { label: 'Color', icon: 'palette', onSelect: () => pickColor(e.target, { value: g.color, onChange: (color) => api.patch(`/contact-groups/${g.id}`, { color }).catch(toastError) }) },
      { divider: true },
      { label: 'Delete group', icon: 'trash', danger: true, onSelect: async () => {
        if (!(await confirmDialog({ title: `Delete “${g.name}”?`, message: 'The contacts stay; only the group goes.', danger: true, confirmLabel: 'Delete' }))) return;
        try { await api.del(`/contact-groups/${g.id}`); if (groupId === g.id) navigate('/contacts'); } catch (err) { toastError(err); }
      } },
    ]);
  };
  const isAll = route.segments.length >= 1 && route.segments[1] !== 'orgs' && !route.query.group && !route.query.blocked;
  return html`
    <${SidebarHeader} title="Contacts" actions=${html`
      <${IconButton} icon="user-plus" label="New contact" onClick=${() => openNewContact()} />
      <${IconButton} icon="ellipsis" label="More" onClick=${(e) => showMenu(e.currentTarget, [
        { label: 'Import from CSV…', icon: 'upload', onSelect: openImport },
        { label: 'Export all to CSV', icon: 'download', onSelect: () => window.open('/api/contacts/export.csv', '_blank') },
      ])} />`} />
    <${SidebarSection}>
      <${SidebarItem} href="/contacts" icon="contact-round" label="All contacts" active=${isAll} />
      <${SidebarItem} href="/contacts/orgs" icon="building" label="Organizations" active=${route.segments[1] === 'orgs'} />
      <${SidebarItem} href="/contacts?blocked=1" icon="ban" label="Blocked" active=${!!route.query.blocked} />
    </${SidebarSection}>
    <${SidebarSection} title="Groups" actions=${html`<${IconButton} icon="plus" size="sm" label="New group" onClick=${newGroup} />`}>
      ${groups.map((g) => html`<${SidebarItem} key=${g.id} href=${`/contacts?group=${g.id}`} color=${g.color} label=${g.name}
        count=${g.member_count} active=${groupId === g.id}
        trailing=${html`<span class="sidebar-item-menu" role="button" tabIndex="0" aria-label=${`${g.name} options`} onClick=${(e) => groupMenu(e, g)}><${Icon} name="ellipsis" size=${14} /></span>`} />`)}
      ${!groups.length && html`<div class="sidebar-hint">Group customers to filter and export them together.</div>`}
    </${SidebarSection}>
  `;
}

// -- new contact / import ---------------------------------------------------------------

function NewContactForm({ close, initial = {} }) {
  const [form, setForm] = useState({ name: '', email: '', phone: '', title: '', organization_name: '', notes: '', ...initial });
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setForm({ ...form, [k]: v });
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await api.post('/contacts', form);
      close();
      navigate(`/contacts/${res.contact.id}`);
    } catch (err) {
      if (err.code === 'duplicate_handle' && err.details?.contact_id) {
        toast(err.message, { tone: 'danger', action: { label: 'Open', onClick: () => { close(); navigate(`/contacts/${err.details.contact_id}`); } } });
      } else toastError(err);
    } finally { setBusy(false); }
  };
  return html`<${Modal} title="New contact" icon="user-plus" onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="new-contact" loading=${busy}>Create contact</${Button}>`}>
    <form id="new-contact" class="stack" onSubmit=${submit}>
      <${Field} label="Name"><${Input} value=${form.name} onValue=${set('name')} placeholder="Lena Ortiz" autoFocus /></${Field}>
      <div class="form-grid">
        <${Field} label="Email"><${Input} type="email" value=${form.email} onValue=${set('email')} placeholder="lena@example.com" /></${Field}>
        <${Field} label="Phone"><${Input} type="tel" value=${form.phone} onValue=${set('phone')} placeholder="(602) 555-0110" /></${Field}>
        <${Field} label="Organization"><${Input} value=${form.organization_name} onValue=${set('organization_name')} placeholder="Company" /></${Field}>
        <${Field} label="Title"><${Input} value=${form.title} onValue=${set('title')} placeholder="Owner" /></${Field}>
      </div>
      <${Field} label="Notes"><${TextArea} value=${form.notes} onValue=${set('notes')} rows="3" /></${Field}>
    </form>
  </${Modal}>`;
}

export function openNewContact(initial) {
  openModal((close) => html`<${NewContactForm} close=${close} initial=${initial} />`);
}

function ImportForm({ close }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append('file', file, file.name);
      setResult(await api.request('/contacts/import', { method: 'POST', body: form }));
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  return html`<${Modal} title="Import contacts" icon="upload" onClose=${close}
    footer=${result
    ? html`<${Button} variant="primary" onClick=${close}>Done</${Button}>`
    : html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="import-form" loading=${busy} disabled=${!file}>Import</${Button}>`}>
    ${result ? html`<div class="stack">
      <div class="import-result">
        <div><strong>${result.created}</strong><span>created</span></div>
        <div><strong>${result.updated}</strong><span>updated</span></div>
        <div><strong>${result.skipped}</strong><span>skipped</span></div>
      </div>
      ${result.errors.length > 0 && html`<div class="import-errors">
        ${result.errors.slice(0, 20).map((e) => html`<div>Line ${e.line}: ${e.error}</div>`)}
      </div>`}
      <p class="muted text-sm">Existing contacts (matched by email, then phone) only had blank fields filled in.</p>
    </div>` : html`<form id="import-form" class="stack" onSubmit=${submit}>
      <p class="muted">Upload a CSV with a header row. Recognized columns: <b>Name</b> (or First/Last name), <b>Email</b>, <b>Phone</b>,
        <b>Company</b>/Organization, <b>Title</b>, <b>Notes</b>, <b>Address</b>, <b>Groups</b>. Exports from Google Contacts and Outlook work.</p>
      <label class="file-drop">
        <${Icon} name="file-spreadsheet" size=${22} />
        <span>${file ? file.name : 'Choose a .csv file'}</span>
        <input type="file" accept=".csv,text/csv" onChange=${(e) => setFile(e.currentTarget.files[0] || null)} />
      </label>
    </form>`}
  </${Modal}>`;
}

function openImport() {
  openModal((close) => html`<${ImportForm} close=${close} />`);
}

// -- list ---------------------------------------------------------------------------

function ContactRow({ c, active }) {
  const sub = [c.title, c.organization?.name].filter(Boolean).join(' · ') || c.email || (c.phone && formatPhone(c.phone)) || '';
  return html`<a href=${`/contacts/${c.id}`} class=${cx('contact-row', active && 'is-active')}>
    <${Avatar} name=${c.display_name} color=${c.color} size=${34} />
    <span class="contact-row-text">
      <span class="contact-row-name">${c.display_name}${c.is_blocked && html` <${Chip} tone="danger" size="sm">Blocked</${Chip}>`}</span>
      <span class="contact-row-sub">${sub}</span>
    </span>
    ${c.last_activity_at && html`<span class="contact-row-time"><${RelTime} value=${c.last_activity_at} /></span>`}
  </a>`;
}

function ContactList({ route, activeId }) {
  const [q, setQ] = useState(route.query.q || '');
  const debounced = useDebounced(q, 220);
  const [sort, setSort] = useState('recent');
  const [limit, setLimit] = useState(PAGE);
  const groups = useStore((s) => s.boot.contact_groups || []);
  const group = groups.find((g) => g.id === Number(route.query.group));
  useEffect(() => setLimit(PAGE), [debounced, sort, route.query.group, route.query.blocked]);
  const { data, loading, error, reload } = useFetch('/contacts', {
    query: { q: debounced, sort, limit, group_id: route.query.group, blocked: route.query.blocked ? 1 : undefined },
    refetchOn: ['contact.changed'],
  });
  const title = group ? group.name : route.query.blocked ? 'Blocked' : 'All contacts';
  const items = data?.items || [];
  return html`<div class="contacts-list-pane">
    <div class="contacts-list-head">
      <div class="row">
        <${SidebarButton} />
        <h1 class="page-title grow">${title}</h1>
        ${data && html`<span class="muted text-sm">${plural(data.total, 'contact')}</span>`}
      </div>
      <${SearchInput} value=${q} onValue=${setQ} placeholder="Search name, email, phone, company" />
      <${Segmented} size="sm" value=${sort} onChange=${setSort} options=${[{ value: 'recent', label: 'Recent' }, { value: 'name', label: 'A–Z' }]} />
    </div>
    <div class="contacts-list-body">
      <${ErrorBox} error=${error} retry=${reload} />
      ${loading && !data && html`<${Loading} />`}
      ${data && !items.length && html`<${Empty} icon="contact-round" title=${q ? 'No matches' : 'No contacts yet'}
        action=${!q && html`<${Button} icon="user-plus" onClick=${() => openNewContact()}>New contact</${Button}>`}>
        ${q ? 'Try a different name, email or phone number.' : 'People you email, text or chat with show up here automatically.'}</${Empty}>`}
      ${items.map((c) => html`<${ContactRow} key=${c.id} c=${c} active=${c.id === activeId} />`)}
      ${data && items.length < data.total && html`<div class="center pad"><${Button} size="sm" onClick=${() => setLimit(limit + PAGE)}>Load more</${Button}></div>`}
    </div>
  </div>`;
}

// -- contact detail -------------------------------------------------------------------

function HandleList({ contact, onChange }) {
  const [adding, setAdding] = useState(null);
  const [value, setValue] = useState('');
  const [label, setLabel] = useState('');
  const add = async (e) => {
    e.preventDefault();
    try {
      const res = await api.post(`/contacts/${contact.id}/handles`, { kind: adding, value, label });
      onChange(res.contact);
      setAdding(null);
      setValue('');
      setLabel('');
    } catch (err) { toastError(err); }
  };
  const remove = async (h) => {
    if (!(await confirmDialog({ title: `Remove ${h.value}?`, confirmLabel: 'Remove', danger: true }))) return;
    try { onChange((await api.del(`/contacts/${contact.id}/handles/${h.id}`)).contact); } catch (err) { toastError(err); }
  };
  const primary = async (h) => {
    try { onChange((await api.post(`/contacts/${contact.id}/handles/${h.id}/primary`)).contact); } catch (err) { toastError(err); }
  };
  return html`<div class="handle-list">
    ${contact.handles.map((h) => {
    const isPrimary = (h.kind === 'email' && h.value === contact.email) || (h.kind === 'phone' && h.value === contact.phone);
    const href = h.kind === 'email' ? composeLink(h.value, 'email') : composeLink(h.value, 'sms');
    return html`<div class="handle-row" key=${h.id}>
        <${Icon} name=${handleIcon(h.kind)} size=${15} class="handle-icon" />
        <a href=${href} class="handle-value" title=${h.kind === 'email' ? 'Write an email' : 'Send a text'}>${h.kind === 'phone' ? formatPhone(h.value) : h.value}</a>
        ${h.label && html`<span class="handle-label">${h.label}</span>`}
        ${isPrimary ? html`<span class="handle-primary" data-tip="Primary">★</span>` : html`<button type="button" class="handle-action" onClick=${() => primary(h)} data-tip="Make primary">☆</button>`}
        ${h.kind === 'phone' && html`<a class="handle-action" href=${`tel:${h.value}`} data-native data-tip="Call"><${Icon} name="phone" size=${13} /></a>`}
        <button type="button" class="handle-action" onClick=${() => remove(h)} aria-label=${`Remove ${h.value}`} data-tip="Remove"><${Icon} name="x" size=${13} /></button>
      </div>`;
  })}
    ${adding ? html`<form class="handle-add" onSubmit=${add}>
      <${Input} class="input-sm" value=${value} onValue=${setValue} placeholder=${adding === 'email' ? 'name@example.com' : '(602) 555-0100'} autoFocus
        type=${adding === 'email' ? 'email' : 'tel'} required />
      <${Input} class="input-sm handle-add-label" value=${label} onValue=${setLabel} placeholder="Label" />
      <${Button} size="sm" variant="primary" type="submit">Add</${Button}>
      <${IconButton} icon="x" size="sm" label="Cancel" onClick=${() => setAdding(null)} />
    </form>` : html`<div class="row gap-1">
      <${Button} size="sm" variant="ghost" icon="mail-plus" onClick=${() => setAdding('email')}>Email</${Button}>
      <${Button} size="sm" variant="ghost" icon="phone" onClick=${() => setAdding('phone')}>Phone</${Button}>
    </div>`}
  </div>`;
}

function CustomFields({ value, onSave }) {
  const entries = Object.entries(value || {});
  const add = async () => {
    const key = await promptDialog({ title: 'Add a field', label: 'Field name', placeholder: 'e.g. Account #' });
    if (!key) return;
    onSave({ ...value, [key]: '' });
  };
  return html`<div class="custom-fields">
    ${entries.map(([k, v]) => html`<div class="kv-row" key=${k}>
      <dt>${k}</dt>
      <dd class="row gap-1"><${InlineText} value=${v} label=${k} onSave=${(nv) => onSave({ ...value, [k]: nv })} />
        <${IconButton} icon="x" size="sm" label=${`Remove ${k}`} onClick=${() => { const next = { ...value }; delete next[k]; onSave(next); }} /></dd>
    </div>`)}
    <${Button} size="sm" variant="ghost" icon="plus" onClick=${add}>Add field</${Button}>
  </div>`;
}

function LinkedList({ items, empty, render }) {
  if (!items) return html`<${Loading} />`;
  if (!items.length) return html`<div class="muted text-sm pad">${empty}</div>`;
  return html`<div class="linked-list">${items.map(render)}</div>`;
}

export function ConversationLink({ c }) {
  return html`<a href=${`/inbox/c/${c.id}`} class="linked-item" key=${c.id}>
    <${Icon} name=${{ sms: 'smartphone', whatsapp: 'message-circle', chat: 'message-square' }[c.channel?.type] || 'mail'} size=${15} class="linked-icon" />
    <span class="linked-main"><span class="linked-title">${c.subject || c.contact?.display_name || 'Conversation'}</span>
      <span class="linked-sub">${c.preview}</span></span>
    <span class="linked-meta">${c.status === 'closed' ? html`<${Chip} size="sm" tone="muted">Closed</${Chip}>` : html`<${Chip} size="sm" tone="ok">Open</${Chip}>`}
      <${RelTime} value=${c.last_activity_at} /></span>
  </a>`;
}

export function JobLink({ j }) {
  return html`<a href=${`/jobs/${j.id}`} class="linked-item" key=${j.id}>
    <${Icon} name="square-kanban" size=${15} class="linked-icon" />
    <span class="linked-main"><span class="linked-title">${j.number} · ${j.title}</span>
      <span class="linked-sub">${j.due_at ? `Due ${fmtDate(j.due_at, { weekday: true })}` : 'No due date'}</span></span>
    <span class="linked-meta">${j.stage_name && html`<${Chip} size="sm" color=${j.stage_color || undefined}>${j.stage_name}</${Chip}>`}</span>
  </a>`;
}

function TaskLink({ t }) {
  return html`<a href=${`/tasks?task=${t.id}`} class="linked-item" key=${t.id}>
    <${Icon} name=${t.status === 'done' ? 'circle-check' : 'circle'} size=${15} class=${cx('linked-icon', t.status === 'done' && 'is-done')} />
    <span class="linked-main"><span class=${cx('linked-title', t.status === 'done' && 'is-done')}>${t.title}</span>
      <span class="linked-sub">${t.due_at ? `Due ${fmtDate(t.due_at, { weekday: true })}` : 'No due date'}</span></span>
  </a>`;
}

function mergeWith(anchor, contact, done) {
  showPopover(anchor, (close) => html`<${MergeSearch} contact=${contact} close=${close} done=${done} />`, { width: 320 });
}

function MergeSearch({ contact, close, done }) {
  const [q, setQ] = useState('');
  const debounced = useDebounced(q, 200);
  const [items, setItems] = useState([]);
  useEffect(() => {
    if (!debounced.trim()) { setItems([]); return; }
    api.get('/contacts', { q: debounced, limit: 8 }).then((r) => setItems(r.items.filter((c) => c.id !== contact.id))).catch(() => {});
  }, [debounced]);
  const pick = async (other) => {
    close();
    if (!(await confirmDialog({
      title: `Merge ${other.display_name} into ${contact.display_name}?`,
      message: `Their emails, phone numbers, conversations, jobs and groups move to ${contact.display_name}, and ${other.display_name} is removed. This can't be undone.`,
      confirmLabel: 'Merge', danger: true,
    }))) return;
    try {
      const res = await api.post(`/contacts/${contact.id}/merge`, { other_id: other.id });
      toast('Contacts merged');
      done(res.contact);
    } catch (err) { toastError(err); }
  };
  return html`<div class="list-picker">
    <div class="list-picker-title">Merge a duplicate into ${contact.display_name}</div>
    <div class="list-picker-search"><${Icon} name="search" size=${14} />
      <input class="list-picker-input" autoFocus placeholder="Search contacts…" value=${q} onInput=${(e) => setQ(e.currentTarget.value)} /></div>
    <div class="list-picker-items">
      ${items.map((c) => html`<button type="button" class="list-picker-item" key=${c.id} onClick=${() => pick(c)}>
        <${Avatar} name=${c.display_name} color=${c.color} size=${20} />
        <span class="list-picker-label">${c.display_name}<span class="list-picker-hint">${c.email || c.phone || ''}</span></span>
      </button>`)}
      ${debounced && !items.length && html`<div class="list-picker-empty">No other contacts match</div>`}
    </div>
  </div>`;
}

function ContactDetail({ id, mobile }) {
  const { data, loading, error, reload, setData } = useFetch(`/contacts/${id}`, { refetchOn: ['contact.changed'], filter: (e) => !e.id || e.id === id });
  const [tab, setTab] = useState('conversations');
  const groups = useStore((s) => s.boot.contact_groups || []);
  if (error) return html`<div class="contact-detail"><${ErrorBox} error=${error} retry=${reload} /></div>`;
  if (loading && !data) return html`<div class="contact-detail"><${Loading} /></div>`;
  if (!data) return null;
  const c = data.contact;
  const setContact = (contact) => setData((d) => ({ ...d, contact }));
  const save = async (patch) => {
    const res = await api.patch(`/contacts/${c.id}`, patch);
    setContact(res.contact);
  };
  const toggleBlock = async () => {
    try { setContact((await api.post(`/contacts/${c.id}/block`, { blocked: !c.is_blocked })).contact); } catch (err) { toastError(err); }
  };
  const remove = async () => {
    if (!(await confirmDialog({ title: `Delete ${c.display_name}?`, message: 'Their conversations stay, without a linked contact.', danger: true, confirmLabel: 'Delete contact' }))) return;
    try { await api.del(`/contacts/${c.id}`); navigate('/contacts'); } catch (err) { toastError(err); }
  };
  const menu = (e) => showMenu(e.currentTarget, [
    { label: 'Merge a duplicate…', icon: 'git-merge', onSelect: () => mergeWith(e.target, c, (merged) => setContact(merged)) },
    { label: c.is_blocked ? 'Unblock sender' : 'Block sender', icon: 'ban', onSelect: toggleBlock, hint: c.is_blocked ? null : 'Their messages go to Spam' },
    { divider: true },
    { label: 'Delete contact', icon: 'trash', danger: true, onSelect: remove },
  ]);
  const addGroup = (e) => pickFromList(e.currentTarget, {
    items: groups.map((g) => ({ id: g.id, label: g.name, color: g.color })),
    selected: c.group_ids, multi: true, placeholder: 'Groups…',
    onChange: (ids) => save({ group_ids: ids }).catch(toastError),
    allowCreate: async (name) => {
      try { const r = await api.post('/contact-groups', { name }); return { id: r.group.id, label: r.group.name, color: r.group.color }; } catch (err) { toastError(err); return null; }
    },
  });
  const tabs = [
    { id: 'conversations', label: 'Conversations', count: data.conversations.length },
    { id: 'jobs', label: 'Jobs', count: data.jobs.length },
    { id: 'tasks', label: 'Tasks', count: data.tasks.length },
  ];
  return html`<div class="contact-detail">
    <header class="contact-hero">
      ${mobile && html`<${IconButton} icon="chevron-left" label="Back to contacts" onClick=${() => navigate('/contacts')} />`}
      <${Avatar} name=${c.display_name} color=${c.color} size=${56} />
      <div class="contact-hero-text">
        <${InlineText} value=${c.name} placeholder="Add a name" label="name" class="contact-hero-name" onSave=${(name) => save({ name })} />
        <div class="contact-hero-sub">
          <${InlineText} value=${c.title} placeholder="Add a title" label="title" onSave=${(title) => save({ title })} />
          <span class="muted">at</span>
          <button type="button" class=${cx('inline-edit', !c.organization && 'is-empty')}
            onClick=${(e) => pickOrganization(e.currentTarget, { selected: c.organization?.id, onChange: (org) => save({ organization_id: org ? org.id : null }).catch(toastError) })}>
            ${c.organization ? c.organization.name : 'Add organization'}<${Icon} name="pencil" size=${12} class="inline-edit-icon" /></button>
          ${c.organization && html`<a class="contact-org-link" href=${`/contacts/orgs/${c.organization.id}`} aria-label="Open organization"><${Icon} name="external-link" size=${12} /></a>`}
        </div>
      </div>
      <div class="contact-hero-actions">
        ${c.email && html`<${Button} size="sm" icon="mail" onClick=${() => navigate(composeLink(c.email, 'email'))}>Email</${Button}>`}
        ${c.phone && html`<${Button} size="sm" icon="smartphone" onClick=${() => navigate(composeLink(c.phone, 'sms'))}>Text</${Button}>`}
        <${IconButton} icon="ellipsis" label="More actions" onClick=${menu} />
      </div>
    </header>
    ${c.is_blocked && html`<div class="banner tone-danger contact-banner"><${Icon} name="ban" size=${16} /><span class="banner-text">Blocked — new messages from ${c.display_name} go straight to Spam.</span>
      <${Button} size="sm" onClick=${toggleBlock}>Unblock</${Button}></div>`}
    <div class="contact-body">
      <section class="contact-card">
        <h3 class="contact-card-title">Contact info</h3>
        <${HandleList} contact=${c} onChange=${setContact} />
      </section>
      <section class="contact-card">
        <h3 class="contact-card-title">Details</h3>
        <dl class="kv">
          <div class="kv-row"><dt>Address</dt><dd><${InlineText} value=${c.address} multiline label="address" onSave=${(address) => save({ address })} /></dd></div>
          <div class="kv-row"><dt>Groups</dt><dd class="row row-wrap gap-1">
            ${c.group_ids.map((gid) => { const g = groups.find((x) => x.id === gid); return g && html`<${Chip} key=${gid} color=${g.color} onRemove=${() => save({ group_ids: c.group_ids.filter((x) => x !== gid) }).catch(toastError)}>${g.name}</${Chip}>`; })}
            <${Button} size="sm" variant="ghost" icon="plus" onClick=${addGroup}>Group</${Button}>
          </dd></div>
          <div class="kv-row"><dt>Added</dt><dd>${fmtDate(c.created_at, { year: true })}</dd></div>
        </dl>
        <${CustomFields} value=${c.custom} onSave=${(custom) => save({ custom }).catch(toastError)} />
      </section>
      <section class="contact-card contact-notes">
        <h3 class="contact-card-title">Notes</h3>
        <${InlineText} value=${c.notes} multiline placeholder="Add notes — preferences, account details, anything the team should know" label="notes" onSave=${(notes) => save({ notes })} />
      </section>
    </div>
    <div class="contact-tabs">
      <${Tabs} tabs=${tabs} value=${tab} onChange=${setTab} />
      ${tab === 'conversations' && html`<${LinkedList} items=${data.conversations} empty="No conversations yet." render=${(conv) => html`<${ConversationLink} c=${conv} />`} />`}
      ${tab === 'jobs' && html`<${LinkedList} items=${data.jobs} empty="No jobs for this contact." render=${(j) => html`<${JobLink} j=${j} />`} />`}
      ${tab === 'tasks' && html`<${LinkedList} items=${data.tasks} empty="No tasks linked to this contact." render=${(t) => html`<${TaskLink} t=${t} />`} />`}
    </div>
  </div>`;
}

// -- organizations ------------------------------------------------------------------

function OrgList({ activeId }) {
  const [q, setQ] = useState('');
  const debounced = useDebounced(q, 200);
  const { data, loading, error, reload } = useFetch('/organizations', { query: { q: debounced }, refetchOn: ['contact.changed'] });
  const add = async () => {
    const name = await promptDialog({ title: 'New organization', label: 'Name', placeholder: 'Desert Bloom Café', confirmLabel: 'Create' });
    if (!name) return;
    try { const r = await api.post('/organizations', { name }); navigate(`/contacts/orgs/${r.organization.id}`); } catch (err) { toastError(err); }
  };
  const items = data?.items || [];
  return html`<div class="contacts-list-pane">
    <div class="contacts-list-head">
      <div class="row"><${SidebarButton} /><h1 class="page-title grow">Organizations</h1><${IconButton} icon="plus" label="New organization" onClick=${add} /></div>
      <${SearchInput} value=${q} onValue=${setQ} placeholder="Search organizations" />
    </div>
    <div class="contacts-list-body">
      <${ErrorBox} error=${error} retry=${reload} />
      ${loading && !data && html`<${Loading} />`}
      ${data && !items.length && html`<${Empty} icon="building" title="No organizations">Organizations group the people who work together.</${Empty}>`}
      ${items.map((o) => html`<a key=${o.id} href=${`/contacts/orgs/${o.id}`} class=${cx('contact-row', o.id === activeId && 'is-active')}>
        <${Avatar} name=${o.name} color=${o.color} size=${34} square />
        <span class="contact-row-text"><span class="contact-row-name">${o.name}</span>
          <span class="contact-row-sub">${[o.domain, plural(o.contact_count, 'person', 'people')].filter(Boolean).join(' · ')}</span></span>
      </a>`)}
    </div>
  </div>`;
}

function OrgDetail({ id, mobile }) {
  const { data, loading, error, reload, setData } = useFetch(`/organizations/${id}`, { refetchOn: ['contact.changed'] });
  if (error) return html`<div class="contact-detail"><${ErrorBox} error=${error} retry=${reload} /></div>`;
  if (loading && !data) return html`<div class="contact-detail"><${Loading} /></div>`;
  if (!data) return null;
  const o = data.organization;
  const save = async (patch) => {
    const res = await api.patch(`/organizations/${o.id}`, patch);
    setData((d) => ({ ...d, organization: res.organization }));
  };
  const linkDomain = async () => {
    try {
      const res = await api.post(`/organizations/${o.id}/link-domain`);
      toast(res.linked ? `Linked ${plural(res.linked, 'person', 'people')} at @${o.domain}` : `No one new at @${o.domain}`);
      reload();
    } catch (err) { toastError(err); }
  };
  const remove = async () => {
    if (!(await confirmDialog({ title: `Delete ${o.name}?`, message: 'Its people stay, just without an organization.', danger: true, confirmLabel: 'Delete' }))) return;
    try { await api.del(`/organizations/${o.id}`); navigate('/contacts/orgs'); } catch (err) { toastError(err); }
  };
  return html`<div class="contact-detail">
    <header class="contact-hero">
      ${mobile && html`<${IconButton} icon="chevron-left" label="Back" onClick=${() => navigate('/contacts/orgs')} />`}
      <${Avatar} name=${o.name} color=${o.color} size=${56} square />
      <div class="contact-hero-text">
        <${InlineText} value=${o.name} label="name" class="contact-hero-name" onSave=${(name) => save({ name })} />
        <div class="contact-hero-sub">${plural(o.contact_count, 'person', 'people')}</div>
      </div>
      <div class="contact-hero-actions">
        <${Button} size="sm" icon="user-plus" onClick=${() => openNewContact({ organization_name: o.name })}>Add person</${Button}>
        <${IconButton} icon="trash" label="Delete organization" onClick=${remove} />
      </div>
    </header>
    <div class="contact-body">
      <section class="contact-card">
        <h3 class="contact-card-title">Details</h3>
        <dl class="kv">
          <div class="kv-row"><dt>Domain</dt><dd class="row gap-1"><${InlineText} value=${o.domain} placeholder="example.com" label="domain" onSave=${(domain) => save({ domain })} />
            ${o.domain && html`<${Button} size="sm" variant="ghost" icon="link" onClick=${linkDomain}>Link @${o.domain}</${Button}>`}</dd></div>
          <div class="kv-row"><dt>Phone</dt><dd><${InlineText} value=${o.phone} label="phone" onSave=${(phone) => save({ phone })} /></dd></div>
          <div class="kv-row"><dt>Website</dt><dd><${InlineText} value=${o.website} label="website" onSave=${(website) => save({ website })} />
            ${o.website && html` <a href=${o.website} target="_blank" rel="noopener" aria-label="Open website"><${Icon} name="external-link" size=${12} /></a>`}</dd></div>
          <div class="kv-row"><dt>Address</dt><dd><${InlineText} value=${o.address} multiline label="address" onSave=${(address) => save({ address })} /></dd></div>
        </dl>
      </section>
      <section class="contact-card contact-notes">
        <h3 class="contact-card-title">Notes</h3>
        <${InlineText} value=${o.notes} multiline placeholder="Billing terms, delivery instructions…" label="notes" onSave=${(notes) => save({ notes })} />
      </section>
    </div>
    <div class="contact-tabs">
      <h3 class="contact-section-title">People</h3>
      <div class="linked-list">${data.contacts.map((c) => html`<${ContactRow} key=${c.id} c=${c} />`)}</div>
      ${!data.contacts.length && html`<div class="muted text-sm pad">No one linked yet.</div>`}
      <h3 class="contact-section-title">Recent conversations</h3>
      <${LinkedList} items=${data.conversations} empty="No conversations yet." render=${(conv) => html`<${ConversationLink} c=${conv} />`} />
      ${data.jobs.length > 0 && html`<h3 class="contact-section-title">Jobs</h3>
        <${LinkedList} items=${data.jobs} empty="" render=${(j) => html`<${JobLink} j=${j} />`} />`}
    </div>
  </div>`;
}

// -- module -------------------------------------------------------------------------

export default function Contacts({ route }) {
  const mobile = useIsMobile();
  const isOrgs = route.segments[1] === 'orgs';
  const id = Number(isOrgs ? route.segments[2] : route.segments[1]) || null;
  useEffect(() => registerCommands(() => [
    { id: 'contact-new', label: 'New contact', icon: 'user-plus', group: 'Contacts', run: () => openNewContact() },
    { id: 'contact-import', label: 'Import contacts from CSV', icon: 'upload', group: 'Contacts', run: openImport },
  ]), []);
  const list = isOrgs ? html`<${OrgList} activeId=${id} />` : html`<${ContactList} route=${route} activeId=${id} />`;
  const detail = id
    ? (isOrgs ? html`<${OrgDetail} key=${'o' + id} id=${id} mobile=${mobile} />` : html`<${ContactDetail} key=${'c' + id} id=${id} mobile=${mobile} />`)
    : html`<div class="contact-detail contact-detail-empty"><${Empty} icon=${isOrgs ? 'building' : 'contact-round'}
        title=${isOrgs ? 'Pick an organization' : 'Pick a contact'}>${isOrgs ? 'See its people, conversations and jobs.' : 'See their conversations, jobs, notes and details.'}</${Empty}></div>`;
  return html`<${ModuleLayout} sidebar=${html`<${ContactsSidebar} route=${route} />`} class="contacts-module">
    <div class=${cx('contacts-split', id && 'has-detail')}>
      ${(!mobile || !id) && list}
      ${(!mobile || id) && detail}
    </div>
  </${ModuleLayout}>`;
}

