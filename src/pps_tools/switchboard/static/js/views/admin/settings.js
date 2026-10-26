// Admin settings sections (named exports, loaded by views/settings/index.js):
//   IntegrationsSettings  /settings/integrations  sidebar apps: embedded pages, WooCommerce orders
//   AISettings            /settings/ai            Claude on/off, API key, model, connection test
//   DevelopersSettings    /settings/developers    API tokens and outgoing webhooks
//   DataSettings          /settings/data          backup, JSON export, audit log

import { html, useEffect, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch } from '../../lib/hooks.js';
import { loadBootstrap } from '../../lib/store.js';
import { fmtAgo, fmtDate, fmtDateTime, fmtUntil, plural } from '../../lib/format.js';
import {
  Banner, Button, Checkbox, Chip, Empty, ErrorBox, Field, Icon, IconButton, Input, Loading, Section, Segmented, Select, Toggle, cx,
} from '../../ui/components.js';
import { Modal, confirmDialog, openModal, promptDialog, showMenu, toast, toastError } from '../../ui/overlay.js';

// -- shared bits ----------------------------------------------------------------------

async function copyText(text, message = 'Copied') {
  try {
    await navigator.clipboard.writeText(text);
    toast(message);
  } catch {
    toast("Couldn't copy automatically. Select the text and copy it.", { tone: 'danger' });
  }
}

function CopyField({ value, label = 'Copy', secret = false }) {
  const [shown, setShown] = useState(!secret);
  return html`<div class="copy-field">
    <input class="input mono" readOnly value=${shown ? value : '•'.repeat(Math.min(28, value.length))} aria-label=${label}
      onFocus=${(e) => shown && e.currentTarget.select()} />
    ${secret && html`<${IconButton} icon=${shown ? 'eye-off' : 'eye'} label=${shown ? 'Hide' : 'Show'} onClick=${() => setShown(!shown)} />`}
    <${IconButton} icon="copy" label=${label} onClick=${() => copyText(value)} />
  </div>`;
}

// Loading / error / empty states shared by the list sections.
function ListState({ state, empty }) {
  if (state.loading && !state.data) return html`<${Loading} />`;
  if (state.error && !state.data) return html`<${ErrorBox} error=${state.error} retry=${() => state.reload()} />`;
  return empty;
}

// -- API tokens -----------------------------------------------------------------------

function NewToken({ token }) {
  const example = `curl ${window.location.origin}/api/me \\\n  -H "Authorization: Bearer ${token}"`;
  return html`<div class="stack">
    <${Banner} tone="warn">Copy it now. For your security it won't be shown again.</${Banner}>
    <${CopyField} value=${token} label="Copy token" />
    <div class="stack-sm">
      <div class="field-label">Try it</div>
      <pre class="code-block">${example}</pre>
      <div class="muted text-sm">Requests with a token skip the browser checks, so keep it out of web pages and shared docs.</div>
    </div>
  </div>`;
}

function TokensSection() {
  const state = useFetch('/admin/tokens');
  const items = state.data?.items || [];
  const create = async () => {
    const name = await promptDialog({ title: 'New API token', label: 'Name', placeholder: 'What will use it? e.g. Zapier', confirmLabel: 'Create token' });
    if (!name || !name.trim()) return;
    try {
      const res = await api.post('/admin/tokens', { name: name.trim() });
      state.reload({ quiet: true });
      openModal((close) => html`<${Modal} title="Your new API token" icon="key-round" onClose=${close}
        footer=${html`<${Button} variant="primary" onClick=${close}>Done</${Button}>`}><${NewToken} token=${res.token} /></${Modal}>`);
    } catch (err) { toastError(err); }
  };
  const revoke = async (t) => {
    const yes = await confirmDialog({
      title: `Revoke “${t.name}”?`, message: "Anything using this token stops working right away. This can't be undone.",
      confirmLabel: 'Revoke', danger: true,
    });
    if (!yes) return;
    try { await api.del(`/admin/tokens/${t.id}`); toast('Token revoked'); state.reload({ quiet: true }); } catch (err) { toastError(err); }
  };
  return html`<${Section} title="API tokens"
    description=${html`Let scripts and other tools use the Switchboard API. Send the token as <code class="admin-code">Authorization: Bearer …</code>; it acts as the admin who created it.`}
    actions=${html`<${Button} icon="plus" onClick=${create}>New token</${Button}>`}>
    ${items.length ? html`<div class="settings-list">
      ${items.map((t) => html`<div class=${cx('settings-list-row', t.revoked_at && 'is-dimmed')} key=${t.id}>
        <span class="admin-row-icon"><${Icon} name="key-round" size=${16} /></span>
        <div class="grow">
          <div class="row gap-2"><span class="strong truncate">${t.name}</span>${t.revoked_at && html`<${Chip} size="sm" tone="muted">Revoked</${Chip}>`}</div>
          <div class="muted text-sm admin-meta">
            <span class="mono">${t.prefix}…</span><span>${t.user_name}</span><span>Created ${fmtDate(t.created_at)}</span>
            <span>${t.revoked_at ? `Revoked ${fmtDate(t.revoked_at)}` : t.last_used_at ? `Used ${fmtAgo(t.last_used_at)}` : 'Never used'}</span>
          </div>
        </div>
        ${!t.revoked_at && html`<${Button} size="sm" variant="ghost" onClick=${() => revoke(t)}>Revoke</${Button}>`}
      </div>`)}
    </div>` : html`<${ListState} state=${state} empty=${html`<${Empty} compact icon="key-round" title="No API tokens yet">
      Create one for each tool that connects, so you can revoke them one at a time.</${Empty}>`} />`}
  </${Section}>`;
}

// -- webhooks -------------------------------------------------------------------------

const EVENT_GROUPS = { message: 'Messages', conversation: 'Conversations', comment: 'Comments', job: 'Jobs', shift: 'Schedule', timeoff: 'Time off', timeclock: 'Time clock' };

function groupEvents(catalog) {
  const groups = [];
  for (const ev of catalog) {
    const key = ev.name.split('.')[0];
    let g = groups.find((x) => x.key === key);
    if (!g) groups.push((g = { key, label: EVENT_GROUPS[key] || key, events: [] }));
    g.events.push(ev);
  }
  return groups;
}

function EventPicker({ catalog, value, onChange }) {
  const has = (n) => value.includes(n);
  const setMany = (names, on) => onChange(on ? [...new Set([...value, ...names])] : value.filter((v) => !names.includes(v)));
  return html`<div class="event-groups">
    ${groupEvents(catalog).map((g) => {
    const names = g.events.map((e) => e.name);
    const count = names.filter(has).length;
    return html`<fieldset class="event-group" key=${g.key}>
        <legend><${Checkbox} checked=${count === names.length} indeterminate=${count > 0 && count < names.length}
          onChange=${(on) => setMany(names, on)} label=${html`<span class="strong">${g.label}</span>`} /></legend>
        ${g.events.map((ev) => html`<${Checkbox} key=${ev.name} checked=${has(ev.name)} onChange=${(on) => setMany([ev.name], on)}
          label=${html`<span class="event-name mono">${ev.name}</span><span class="event-desc">${ev.description}</span>`} />`)}
      </fieldset>`;
  })}
  </div>`;
}

function WebhookForm({ hook, catalog, close, onSaved }) {
  const editing = !!hook;
  const [form, setForm] = useState(() => ({
    name: hook?.name || '',
    url: hook?.url || '',
    mode: !hook || (hook.events || ['*']).includes('*') ? 'all' : 'pick',
    events: (hook?.events || []).filter((e) => e !== '*'),
    is_active: hook ? hook.is_active : true,
  }));
  const [secret, setSecret] = useState(hook?.secret || null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const save = async (e) => {
    e.preventDefault();
    if (form.mode === 'pick' && !form.events.length) { toast('Pick at least one event, or send them all', { tone: 'danger' }); return; }
    setBusy(true);
    const payload = { name: form.name, url: form.url.trim(), events: form.mode === 'all' ? ['*'] : form.events, is_active: form.is_active };
    try {
      if (editing) await api.patch(`/admin/webhooks/${hook.id}`, payload);
      else await api.post('/admin/webhooks', payload);
      onSaved();
      close();
      toast(editing ? 'Webhook saved' : 'Webhook added. Send a test event to check it.');
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  const rotate = async () => {
    const yes = await confirmDialog({ title: 'Rotate the signing secret?', message: 'New requests are signed with the new secret right away, so update your receiver too.', confirmLabel: 'Rotate' });
    if (!yes) return;
    try { const r = await api.post(`/admin/webhooks/${hook.id}/rotate-secret`); setSecret(r.item.secret); onSaved(); toast('New secret ready'); } catch (err) { toastError(err); }
  };
  return html`<${Modal} title=${editing ? 'Edit webhook' : 'Add a webhook'} icon="webhook" size="lg" onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}>
      <${Button} variant="primary" type="submit" form="webhook-form" loading=${busy}>${editing ? 'Save' : 'Add webhook'}</${Button}>`}>
    <form id="webhook-form" class="stack" onSubmit=${save}>
      <div class="form-grid">
        <${Field} label="Name" required><${Input} value=${form.name} onValue=${set('name')} placeholder="e.g. Zapier: new messages" required maxLength="80" /></${Field}>
        <${Field} label="Payload URL" required hint="We POST JSON to this address"><${Input} type="url" class="mono" value=${form.url} onValue=${set('url')}
          placeholder="https://example.com/hooks/switchboard" required /></${Field}>
      </div>
      <${Field} label="Events">
        <div class="stack-sm">
          <${Segmented} size="sm" value=${form.mode} onChange=${set('mode')} options=${[{ value: 'all', label: 'Everything' }, { value: 'pick', label: 'Choose events' }]} />
          ${form.mode === 'pick' && html`<${EventPicker} catalog=${catalog} value=${form.events} onChange=${set('events')} />`}
        </div>
      </${Field}>
      <${Toggle} checked=${form.is_active} onChange=${set('is_active')} label="Active" hint="Paused webhooks don't receive events" />
      ${editing && secret && html`<${Field} label="Signing secret"
        hint=${html`Each request has <code class="admin-code">X-Switchboard-Signature: sha256=…</code>, an HMAC-SHA256 of the raw body with this secret.`}>
        <div class="row"><div class="grow"><${CopyField} value=${secret} secret label="Copy secret" /></div>
          <${Button} icon="refresh-cw" onClick=${rotate}>Rotate</${Button}></div>
      </${Field}>`}
    </form>
  </${Modal}>`;
}

function DeliveryStatus({ d }) {
  if (d.status === 'delivered') return html`<${Chip} size="sm" tone="ok" icon="circle-check">Delivered</${Chip}>`;
  if (d.status === 'failed') return html`<${Chip} size="sm" tone="danger" icon="circle-x">Failed</${Chip}>`;
  if (d.attempts > 0) return html`<${Chip} size="sm" tone="warn" icon="clock">Retrying</${Chip}>`;
  return html`<${Chip} size="sm" tone="muted" icon="hourglass">Queued</${Chip}>`;
}

function Deliveries({ hook, close }) {
  const state = useFetch(`/admin/webhooks/${hook.id}/deliveries`, { query: { limit: 50 }, interval: 8000 });
  const [open, setOpen] = useState(null);
  const items = state.data?.items || [];
  const retry = async (d) => {
    try { await api.post(`/admin/deliveries/${d.id}/retry`); toast('Queued to send again'); state.reload({ quiet: true }); } catch (err) { toastError(err); }
  };
  return html`<${Modal} title=${`Deliveries · ${hook.name}`} icon="history" size="lg" onClose=${close}
    footer=${html`<${Button} onClick=${close}>Close</${Button}>`}>
    ${items.length ? html`<div class="delivery-list">
      ${items.map((d) => html`<div class=${cx('delivery', open === d.id && 'is-open')} key=${d.id}>
        <button type="button" class="delivery-row" aria-expanded=${open === d.id} onClick=${() => setOpen(open === d.id ? null : d.id)}>
          <${DeliveryStatus} d=${d} />
          <span class="mono delivery-event truncate">${d.event}</span>
          <span class="muted text-sm delivery-detail truncate">
            ${d.response_code ? `HTTP ${d.response_code}` : ''}${d.response_code && d.error ? ' · ' : ''}${d.error || ''}
            ${d.status === 'pending' && d.next_attempt_at ? ` · next try ${fmtUntil(d.next_attempt_at)}` : ''}
          </span>
          <span class="muted text-sm nowrap">${plural(d.attempts, 'try', 'tries')} · ${fmtAgo(d.created_at)}</span>
          <${Icon} name="chevron-down" size=${14} class="delivery-chevron" />
        </button>
        ${open === d.id && html`<div class="delivery-body">
          <pre class="code-block delivery-payload">${JSON.stringify(d.payload, null, 2)}</pre>
          ${d.status !== 'delivered' && html`<div class="row mt-2"><${Button} size="sm" icon="refresh-cw" onClick=${() => retry(d)}>Send again</${Button}></div>`}
        </div>`}
      </div>`)}
    </div>` : html`<${ListState} state=${state} empty=${html`<${Empty} compact icon="send" title="Nothing sent yet">
      Deliveries show up here as events happen. Send a test event to try it.</${Empty}>`} />`}
  </${Modal}>`;
}

function HookHealth({ hook }) {
  if (!hook.is_active) return html`<${Chip} size="sm" tone="muted" icon="circle-pause">Paused</${Chip}>`;
  if (!hook.last_delivery_at) return html`<span class="muted text-sm">No deliveries yet</span>`;
  const healthy = !hook.last_error && hook.last_status >= 200 && hook.last_status < 300;
  return html`<span class="row gap-2 hook-health">
    <${Chip} size="sm" tone=${healthy ? 'ok' : 'danger'} icon=${healthy ? 'circle-check' : 'circle-alert'}>${healthy ? 'Healthy' : 'Failing'}</${Chip}>
    <span class="muted text-sm truncate">${healthy ? `HTTP ${hook.last_status}` : hook.last_error || `HTTP ${hook.last_status}`} · ${fmtAgo(hook.last_delivery_at)}</span>
  </span>`;
}

function WebhooksSection() {
  const state = useFetch('/admin/webhooks', { interval: 30000 });
  const items = state.data?.items || [];
  const catalog = state.data?.events || [];
  const refresh = () => state.reload({ quiet: true });
  const edit = (hook) => openModal((close) => html`<${WebhookForm} hook=${hook} catalog=${catalog} close=${close} onSaved=${refresh} />`, { size: 'lg' });
  const deliveries = (hook) => openModal((close) => html`<${Deliveries} hook=${hook} close=${close} />`, { size: 'lg', onClose: refresh });
  const toggle = async (hook, on) => {
    try { await api.patch(`/admin/webhooks/${hook.id}`, { is_active: on }); refresh(); } catch (err) { toastError(err); }
  };
  const test = async (hook) => {
    try {
      const { delivery: d } = await api.post(`/admin/webhooks/${hook.id}/test`);
      if (d.status === 'delivered') toast(`Test delivered (HTTP ${d.response_code})`);
      else toast(`Test didn't go through: ${d.error || `HTTP ${d.response_code}`}`, { tone: 'danger' });
      refresh();
    } catch (err) { toastError(err); }
  };
  const remove = async (hook) => {
    if (!(await confirmDialog({ title: `Delete “${hook.name}”?`, message: 'It stops receiving events and its delivery history is removed.', confirmLabel: 'Delete', danger: true }))) return;
    try { await api.del(`/admin/webhooks/${hook.id}`); toast('Webhook deleted'); refresh(); } catch (err) { toastError(err); }
  };
  const menu = (e, hook) => showMenu(e.currentTarget, [
    { label: 'Edit', icon: 'pencil', onSelect: () => edit(hook) },
    { label: 'Send a test event', icon: 'send', onSelect: () => test(hook) },
    { label: 'Recent deliveries', icon: 'history', onSelect: () => deliveries(hook) },
    { label: hook.is_active ? 'Pause' : 'Resume', icon: hook.is_active ? 'circle-pause' : 'circle-play', onSelect: () => toggle(hook, !hook.is_active) },
    { divider: true },
    { label: 'Delete', icon: 'trash', danger: true, onSelect: () => remove(hook) },
  ], { placement: 'bottom-end' });
  return html`<${Section} title="Webhooks"
    description="Switchboard sends a signed JSON POST to your URL when things happen: new messages, assignments, job moves, published shifts and more. Failed deliveries are retried for about 2.5 hours."
    actions=${html`<${Button} icon="plus" onClick=${() => edit(null)} disabled=${!state.data}>Add webhook</${Button}>`}>
    ${items.length ? html`<div class="settings-list">
      ${items.map((h) => html`<div class=${cx('settings-list-row hook-row', !h.is_active && 'is-dimmed')} key=${h.id}>
        <span class="admin-row-icon"><${Icon} name="webhook" size=${16} /></span>
        <div class="grow stack-0">
          <button type="button" class="admin-title-link strong truncate" onClick=${() => edit(h)}>${h.name}</button>
          <span class="mono text-sm muted truncate">${h.url}</span>
          <div class="row gap-2 mt-1 row-wrap">
            <${HookHealth} hook=${h} />
            <span class="muted text-sm">${h.events.includes('*') ? 'All events' : plural(h.events.length, 'event')}</span>
            ${h.pending > 0 && html`<span class="muted text-sm">${h.pending} waiting to send</span>`}
          </div>
        </div>
        <div class="row gap-1 hook-actions">
          <${Button} size="sm" variant="ghost" class="hide-mobile" onClick=${() => deliveries(h)}>Deliveries</${Button}>
          <${IconButton} icon="ellipsis" label="More" onClick=${(e) => menu(e, h)} />
        </div>
      </div>`)}
    </div>` : html`<${ListState} state=${state} empty=${html`<${Empty} compact icon="webhook" title="No webhooks yet">
      Connect Zapier, Make, n8n or your own code. Add a webhook and pick the events to send.</${Empty}>`} />`}
    <details class="admin-details mt-3">
      <summary>How to check a signature</summary>
      <pre class="code-block">${`import hmac, hashlib

def is_from_switchboard(secret: str, body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)

# header = request.headers["X-Switchboard-Signature"]; body = the raw request body`}</pre>
      <p class="muted text-sm">Other headers: <code class="admin-code">X-Switchboard-Event</code> (the event name) and <code class="admin-code">X-Switchboard-Delivery</code>
        (a unique id; retries reuse it, so you can ignore duplicates). Answer with any 2xx status within 10 seconds.</p>
    </details>
  </${Section}>`;
}

export function DevelopersSettings() {
  return html`<div>
    <${TokensSection} />
    <${WebhooksSection} />
  </div>`;
}

// -- sidebar apps (integrations) --------------------------------------------------------

const SAMPLE = {
  'contact.email': 'sam@example.com', 'contact.name': 'Sam Carter', 'contact.phone': '+15550100', 'contact.address': '100 Main St, Springfield',
  'contact.organization': 'Acme Printing', 'conversation.id': '123', 'conversation.subject': 'Quote request',
};

const preview = (template) => template.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_, v) => encodeURIComponent(SAMPLE[v] ?? ''));

function IntegrationForm({ item, variables, close, onSaved }) {
  const { kind } = item;
  const editing = !!item.id;
  const woo = kind === 'woocommerce';
  const [form, setForm] = useState(() => (woo
    ? { name: item.name || 'WooCommerce orders', store_url: item.config?.store_url || '', consumer_key: item.config?.consumer_key || '',
      consumer_secret: item.config?.consumer_secret || '', is_active: item.is_active ?? true }
    : { name: item.name || '', url: item.config?.url || 'https://', height: item.config?.height || 320, is_active: item.is_active ?? true }));
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const urlRef = useRef(null);
  const set = (k) => (v) => { setForm((f) => ({ ...f, [k]: v })); setResult(null); };
  const config = () => (woo
    ? { store_url: form.store_url, consumer_key: form.consumer_key, consumer_secret: form.consumer_secret }
    : { url: form.url.trim(), height: Number(form.height) || 320 });
  const insert = (variable) => {
    const el = urlRef.current;
    const token = `{{${variable}}}`;
    const start = el ? el.selectionStart : form.url.length;
    const end = el ? el.selectionEnd : start;
    set('url')(form.url.slice(0, start) + token + form.url.slice(end));
    requestAnimationFrame(() => { if (el) { el.focus(); el.setSelectionRange(start + token.length, start + token.length); } });
  };
  const test = async () => {
    setTesting(true);
    try { setResult(await api.post('/admin/integrations/test', { kind, config: config(), id: item.id })); } catch (err) { setResult({ ok: false, message: err.message }); } finally { setTesting(false); }
  };
  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (editing) await api.patch(`/admin/integrations/${item.id}`, { name: form.name, config: config(), is_active: form.is_active });
      else await api.post('/admin/integrations', { kind, name: form.name, config: config(), is_active: form.is_active });
      onSaved();
      close();
      toast(editing ? 'Saved' : 'Added. It shows in the sidebar of every conversation.');
    } catch (err) { setResult({ ok: false, message: err.message }); } finally { setBusy(false); }
  };
  return html`<${Modal} title=${`${editing ? 'Edit' : 'Add'} ${woo ? 'WooCommerce orders' : 'embedded page'}`} icon=${woo ? 'store' : 'globe'} size="lg" onClose=${close}
    footer=${html`<${Button} icon="plug" onClick=${test} loading=${testing} class="integration-test-btn">Test</${Button}>
      <${Button} onClick=${close}>Cancel</${Button}>
      <${Button} variant="primary" type="submit" form="integration-form" loading=${busy}>${editing ? 'Save' : 'Add app'}</${Button}>`}>
    <form id="integration-form" class="stack" onSubmit=${save}>
      <${Field} label="Name" hint="Shown as the panel title in the conversation sidebar"><${Input} value=${form.name} onValue=${set('name')} required maxLength="80" /></${Field}>
      ${woo ? html`
        <${Banner} tone="info">In WordPress, open <b>WooCommerce → Settings → Advanced → REST API</b>, add a key with <b>Read</b> access, then paste it here.
          The sidebar shows the five most recent orders for the customer's email address.</${Banner}>
        <${Field} label="Store address" required><${Input} type="url" class="mono" value=${form.store_url} onValue=${set('store_url')} placeholder="https://shop.example.com" required /></${Field}>
        <div class="form-grid">
          <${Field} label="Consumer key" required><${Input} class="mono" value=${form.consumer_key} onValue=${set('consumer_key')} placeholder="ck_…" autoComplete="off" /></${Field}>
          <${Field} label="Consumer secret" required hint=${editing ? 'Leave as is to keep the saved secret' : null}>
            <${Input} type="password" class="mono" value=${form.consumer_secret} onValue=${set('consumer_secret')} placeholder="cs_…" autoComplete="new-password" /></${Field}>
        </div>`
    : html`
        <${Field} label="Page address" required hint="Must be https. Insert details about the conversation with the variables below.">
          <input ref=${urlRef} class="input mono" type="text" value=${form.url} required spellcheck=${false}
            onInput=${(e) => set('url')(e.currentTarget.value)} placeholder="https://crm.example.com/lookup?email={{contact.email}}" />
        </${Field}>
        <div class="variable-chips" aria-label="Insert a variable">
          ${variables.map((v) => html`<button type="button" class="chip is-clickable variable-chip" key=${v} onClick=${() => insert(v)}>
            <${Icon} name="plus" size=${11} /><span class="mono">${v}</span></button>`)}
        </div>
        ${form.url.includes('{{') && html`<div class="muted text-sm integration-preview"><span>Example:</span> <span class="mono">${preview(form.url)}</span></div>`}
        <${Field} label="Height (pixels)" class="integration-height"><${Input} type="number" min="120" max="1200" step="10" value=${form.height} onValue=${set('height')} /></${Field}>`}
      <${Toggle} checked=${form.is_active} onChange=${set('is_active')} label="Show in conversations" />
      ${result && html`<${Banner} tone=${result.ok ? 'ok' : 'danger'} icon=${result.ok ? 'circle-check' : 'circle-alert'}>${result.message}</${Banner}>`}
    </form>
  </${Modal}>`;
}

export function IntegrationsSettings() {
  const state = useFetch('/admin/integrations');
  const items = state.data?.items || [];
  const variables = state.data?.variables || [];
  const refresh = () => state.reload({ quiet: true });
  const edit = (item) => openModal((close) => html`<${IntegrationForm} item=${item} variables=${variables} close=${close} onSaved=${refresh} />`, { size: 'lg' });
  const add = (e) => showMenu(e.currentTarget, [
    { label: 'Embedded web page', hint: 'A CRM, map or order tool, filled in per conversation', icon: 'globe', onSelect: () => edit({ kind: 'iframe' }) },
    { label: 'WooCommerce orders', hint: "The customer's recent orders", icon: 'store', onSelect: () => edit({ kind: 'woocommerce' }) },
  ], { placement: 'bottom-end', width: 300 });
  const toggle = async (item, on) => {
    try { await api.patch(`/admin/integrations/${item.id}`, { is_active: on }); refresh(); } catch (err) { toastError(err); }
  };
  const remove = async (item) => {
    if (!(await confirmDialog({ title: `Remove “${item.name}”?`, message: 'It disappears from the conversation sidebar for everyone.', confirmLabel: 'Remove', danger: true }))) return;
    try { await api.del(`/admin/integrations/${item.id}`); toast('Removed'); refresh(); } catch (err) { toastError(err); }
  };
  return html`<div>
    <${Section} title="Sidebar apps" description="Show information from your other tools next to every conversation, matched to the customer you're talking to."
      actions=${html`<${Button} icon="plus" iconRight="chevron-down" onClick=${add} disabled=${!state.data}>Add app</${Button}>`}>
      ${items.length ? html`<div class="settings-list">
        ${items.map((it) => html`<div class=${cx('settings-list-row', !it.is_active && 'is-dimmed')} key=${it.id}>
          <span class="admin-row-icon"><${Icon} name=${it.kind === 'woocommerce' ? 'store' : 'globe'} size=${16} /></span>
          <div class="grow stack-0">
            <button type="button" class="admin-title-link strong truncate" onClick=${() => edit(it)}>${it.name}</button>
            <span class="muted text-sm truncate">${it.kind === 'woocommerce' ? `WooCommerce · ${it.config.store_url}` : it.config.url}</span>
          </div>
          <${Toggle} checked=${it.is_active} onChange=${(on) => toggle(it, on)} label=${html`<span class="admin-sr">Show ${it.name}</span>`} />
          <${IconButton} icon="pencil" label="Edit" onClick=${() => edit(it)} />
          <${IconButton} icon="trash" label="Remove" onClick=${() => remove(it)} />
        </div>`)}
      </div>` : html`<${ListState} state=${state} empty=${html`<${Empty} compact icon="layout-grid" title="No sidebar apps yet">
        Embed any web page (with the customer's email, phone or address filled in) or show their WooCommerce orders.</${Empty}>`} />`}
    </${Section}>
  </div>`;
}

// -- AI assistant ---------------------------------------------------------------------

const AI_FEATURES = [
  ['sparkles', 'Summaries', 'A few bullets and the next step for long threads'],
  ['wand-sparkles', 'Draft replies', 'A first draft in your voice, using your canned responses as examples'],
  ['pen-line', 'Rewrite', 'Friendlier, more formal, shorter, longer, or just fix the spelling'],
  ['globe', 'Translate', 'Into any language before you send'],
  ['square-kanban', 'Jobs from emails', 'Pulls quantity, stock, size and due date into a new job'],
];

export function AISettings() {
  const state = useFetch('/ai/settings');
  const { data } = state;
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState(null);
  useEffect(() => { if (data) setForm({ enabled: data.enabled, model: data.model, key: '' }); }, [data]);
  if (!data || !form) return html`<${ListState} state=${state} empty=${null} />`;
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const dirty = form.enabled !== data.enabled || form.model !== data.model || form.key.trim() !== '';
  const save = async () => {
    setBusy(true);
    const patch = { 'ai.enabled': form.enabled, 'ai.model': form.model };
    if (form.key.trim()) patch['ai.api_key'] = form.key.trim();
    try {
      await api.patch('/settings', patch);
      setResult(null);
      await Promise.all([state.reload({ quiet: true }), loadBootstrap()]);
      toast('AI settings saved');
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  const removeKey = async () => {
    if (!(await confirmDialog({ title: 'Remove the API key?', message: 'AI features stop working until a new key is added.', confirmLabel: 'Remove', danger: true }))) return;
    try { await api.patch('/settings', { 'ai.api_key': null }); setResult(null); await state.reload({ quiet: true }); toast('Key removed'); } catch (err) { toastError(err); }
  };
  const test = async () => {
    setTesting(true);
    try {
      const r = await api.post('/ai/test');
      const label = data.models.find((m) => m.id === r.model)?.label || r.model;
      setResult({ ok: true, message: `Connected to ${label} in ${(r.latency_ms / 1000).toFixed(1)}s.` });
    } catch (err) { setResult({ ok: false, message: err.message }); } finally { setTesting(false); }
  };
  const current = data.models.find((m) => m.id === data.model);
  return html`<div>
    <${Section} title="Status">
      ${!data.enabled ? html`<${Banner} tone="muted" icon="circle-pause">AI features are off. Teammates won't see AI buttons.</${Banner}>`
    : !data.configured ? html`<${Banner} tone="warn">Add an Anthropic API key to turn on AI features.</${Banner}>`
      : html`<${Banner} tone="ok" icon="circle-check">Ready, using ${current?.label || data.model}${data.key_source === 'environment' ? ' with the key from the server environment' : ''}.</${Banner}>`}
      <ul class="ai-features">
        ${AI_FEATURES.map(([icon, title, text]) => html`<li key=${title}><span class="admin-row-icon"><${Icon} name=${icon} size=${15} /></span>
          <span><span class="strong">${title}</span><span class="muted text-sm"> · ${text}</span></span></li>`)}
      </ul>
    </${Section}>
    <${Section} title="Settings">
      <div class="stack ai-form">
        <${Toggle} checked=${form.enabled} onChange=${set('enabled')} label="Turn on AI features" hint="AI buttons in the composer, conversation sidebar and new-job form" />
        <${Field} label="Anthropic API key" hint=${html`Get one at <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer">console.anthropic.com</a>. Stored on this server and never shown again.`}>
          <div class="row">
            <${Input} type="password" class="mono grow" value=${form.key} onValue=${set('key')} autoComplete="new-password"
              placeholder=${data.key_hint ? `Saved key ${data.key_hint}. Paste a new one to replace it.` : data.key_source === 'environment' ? 'Using ANTHROPIC_API_KEY from the environment' : 'sk-ant-…'} />
            ${data.key_hint && html`<${Button} variant="ghost" onClick=${removeKey}>Remove</${Button}>`}
          </div>
        </${Field}>
        <${Field} label="Model">
          <${Select} value=${form.model} onValue=${set('model')} options=${data.models.map((m) => ({ value: m.id, label: `${m.label}: ${m.hint}` }))} />
        </${Field}>
        <div class="row row-wrap">
          <${Button} variant="primary" loading=${busy} disabled=${!dirty} onClick=${save}>Save</${Button}>
          <${Button} icon="plug" loading=${testing} disabled=${!data.configured || dirty} onClick=${test}>Test connection</${Button}>
          ${dirty && data.configured && html`<span class="muted text-sm">Save first to test the new settings</span>`}
        </div>
        ${result && html`<${Banner} tone=${result.ok ? 'ok' : 'danger'} icon=${result.ok ? 'circle-check' : 'circle-alert'}>${result.message}</${Banner}>`}
      </div>
    </${Section}>
    <${Section} title="Privacy">
      <p class="text-2 ai-privacy">Nothing is sent to Anthropic until a teammate presses an AI button. Then the text it needs (the conversation, or the draft
        being rewritten) goes to the Claude API to produce the result. Anthropic doesn't train models on API data.</p>
    </${Section}>
  </div>`;
}

// -- data: backup, export, audit -----------------------------------------------------------

const ACTION_LABELS = {
  'api_token.create': 'Created an API token',
  'api_token.revoke': 'Revoked an API token',
  'webhook.create': 'Added a webhook',
  'webhook.update': 'Changed a webhook',
  'webhook.delete': 'Deleted a webhook',
  'webhook.rotate_secret': 'Rotated a webhook secret',
  'integration.create': 'Added a sidebar app',
  'integration.update': 'Changed a sidebar app',
  'integration.delete': 'Removed a sidebar app',
  'data.backup': 'Downloaded a backup',
  'data.export': 'Exported all data',
  'settings.update': 'Changed settings',
};

const humanize = (action) => ACTION_LABELS[action] || (action.charAt(0).toUpperCase() + action.slice(1)).replace(/[._]/g, ' ');

function auditDetails(r) {
  const bits = [];
  const d = r.data;
  if (d && typeof d === 'object' && !Array.isArray(d)) {
    for (const [k, v] of Object.entries(d)) {
      if (v === null || typeof v === 'object') continue;
      bits.push(`${k.replace(/_/g, ' ')}: ${v}`);
      if (bits.length >= 3) break;
    }
  }
  if (!bits.length && r.entity_type) bits.push(`${r.entity_type.replace(/_/g, ' ')}${r.entity_id ? ` #${r.entity_id}` : ''}`);
  return bits.join(' · ');
}

function AuditLog() {
  const state = useFetch('/admin/audit', { query: { limit: 50 } });
  const [older, setOlder] = useState([]);
  const [next, setNext] = useState(undefined);
  const [busy, setBusy] = useState(false);
  const first = state.data?.items || [];
  const items = [...first, ...older];
  const cursor = next === undefined ? state.data?.next : next;
  const more = async () => {
    setBusy(true);
    try { const r = await api.get('/admin/audit', { limit: 50, before: cursor }); setOlder((o) => [...o, ...r.items]); setNext(r.next); } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  return html`<${Section} title="Audit log" description="Sign-ins, permission changes, settings and other admin actions, newest first."
    actions=${html`<${IconButton} icon="refresh-cw" label="Refresh" onClick=${() => { setOlder([]); setNext(undefined); state.reload(); }} />`}>
    ${items.length ? html`<div class="table-wrap audit-wrap"><table class="table audit-table">
      <thead><tr><th>When</th><th>Who</th><th>What</th><th class="hide-mobile">Details</th></tr></thead>
      <tbody>${items.map((r) => html`<tr key=${r.id}>
        <td class="nowrap muted" title=${fmtDateTime(r.created_at)}>${fmtAgo(r.created_at)}</td>
        <td class="nowrap">${r.user_name || html`<span class="muted">System</span>`}</td>
        <td>${humanize(r.action)}<div class="show-mobile muted text-sm">${auditDetails(r)}</div></td>
        <td class="hide-mobile muted text-sm audit-details">${auditDetails(r)}${r.ip ? html`<span class="audit-ip"> · ${r.ip}</span>` : ''}</td>
      </tr>`)}</tbody>
    </table></div>
    ${cursor && html`<div class="row mt-2"><${Button} size="sm" loading=${busy} onClick=${more}>Show older</${Button}></div>`}`
    : html`<${ListState} state=${state} empty=${html`<${Empty} compact icon="history" title="Nothing logged yet" />`} />`}
  </${Section}>`;
}

export function DataSettings() {
  return html`<div>
    <${Section} title="Backup" description="A complete copy of the database as one SQLite file. It holds everything, including password hashes and connection secrets, so store it somewhere safe.">
      <a class="btn btn-secondary" href="/api/admin/backup" download data-native><${Icon} name="archive" size=${16} /><span class="btn-label">Download backup</span></a>
      <p class="muted text-sm mt-2">To restore, stop Switchboard, replace <span class="mono">switchboard.db</span> in the data folder with the backup, and start it again.</p>
    </${Section}>
    <${Section} title="Export" description="Your data as JSON, to move elsewhere or keep for your records: people, teams, contacts, conversations with messages and comments, jobs, shifts, timesheets, time off and tasks. Passwords and secrets are left out.">
      <a class="btn btn-secondary" href="/api/admin/export.json" download data-native><${Icon} name="file-down" size=${16} /><span class="btn-label">Export everything (JSON)</span></a>
      <ul class="data-links">
        <li><a href="/contacts">Contacts</a> can be imported from and exported to CSV.</li>
        <li><a href="/reports">Reports</a> export each table as CSV.</li>
      </ul>
    </${Section}>
    <${AuditLog} />
  </div>`;
}
