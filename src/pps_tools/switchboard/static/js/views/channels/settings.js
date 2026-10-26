// Settings → Channels: connect email accounts, Twilio numbers, the website chat widget
// and API/form endpoints; test them, sync mail, and grab the URLs and snippets to paste
// elsewhere.

import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch } from '../../lib/hooks.js';
import { useStore, loadBootstrap } from '../../lib/store.js';
import {
  Banner, Button, Checkbox, Chip, ColorChoices, Empty, ErrorBox, Field, Icon, IconButton, Input, Loading, RelTime,
  Section, Segmented, Select, Tabs, TextArea, Toggle, cx,
} from '../../ui/components.js';
import { Modal, confirmDialog, openModal, showMenu, toast, toastError } from '../../ui/overlay.js';
import { RichEditor } from '../../ui/editor.js';

export const TYPE_META = {
  email: { icon: 'mail', label: 'Email account', blurb: 'Gmail, Outlook or any IMAP/SMTP mailbox' },
  sms: { icon: 'smartphone', label: 'Text messages (SMS)', blurb: 'A Twilio phone number' },
  whatsapp: { icon: 'message-circle', label: 'WhatsApp', blurb: 'WhatsApp Business through Twilio' },
  chat: { icon: 'message-square', label: 'Website chat', blurb: 'A chat bubble on your website' },
  api: { icon: 'code', label: 'API & web forms', blurb: 'Website forms, Zapier, your POS' },
};

const MASK = '••••••';

const EMPTY_CONFIG = {
  email: { preset: 'gmail', imap_host: 'imap.gmail.com', imap_port: 993, imap_ssl: true, imap_user: '', imap_password: '',
    imap_folder: 'INBOX', smtp_host: 'smtp.gmail.com', smtp_port: 587, smtp_security: 'starttls', smtp_user: '',
    smtp_password: '', from_name_mode: 'user', initial_days: 7, track_opens: false, append_sent: false },
  sms: { account_sid: '', auth_token: '', from_number: '', messaging_service_sid: '', validate_signature: true },
  whatsapp: { account_sid: '', auth_token: '', from_number: '', validate_signature: true },
  chat: { greeting: "Hi! 👋 Questions about an order or a quote? We usually reply in a few minutes.", color: '#3b5bdb',
    require_email: false, offline_message: "We're away right now — leave a message with your email and we'll get back to you.",
    email_fallback: true },
  api: { outbound_url: '' },
};

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Copied to clipboard');
  } catch {
    toast("Couldn't copy — select the text and copy it manually", { tone: 'danger' });
  }
}

function CopyField({ label, value, multiline, hint }) {
  return html`<${Field} label=${label} hint=${hint}>
    <div class="ch-copy">
      ${multiline
    ? html`<textarea class="input textarea mono ch-copy-text" readOnly value=${value}
          rows=${Math.min(10, String(value).split('\n').length + 1)} onFocus=${(e) => e.currentTarget.select()}></textarea>`
    : html`<input class="input mono" readOnly value=${value} onFocus=${(e) => e.currentTarget.select()} />`}
      <${IconButton} icon="copy" label="Copy" variant="secondary" onClick=${() => copy(value)} />
    </div>
  </${Field}>`;
}

function statusOf(ch) {
  if (!ch.is_active) return { tone: 'warn', label: 'Paused', icon: 'circle-pause' };
  if (ch.sync_error) return { tone: 'danger', label: 'Needs attention', icon: 'circle-alert' };
  if (ch.demo) return { tone: 'muted', label: 'Demo', icon: 'circle-dot' };
  return { tone: 'ok', label: 'Connected', icon: 'circle-check' };
}

// -- editor -------------------------------------------------------------------------

function AccessFields({ form, set }) {
  const teams = useStore((s) => s.teams);
  const users = useStore((s) => s.users.filter((u) => u.is_active && u.role !== 'staff'));
  return html`<div class="stack">
    <${Field} label="Who handles it" hint=${form.visibility === 'personal'
    ? 'Only the owner sees conversations from a personal account.'
    : form.team_id ? 'New conversations land in this team\'s inbox.' : 'Everyone with inbox access gets new conversations in their Inbox.'}>
      <${Segmented} value=${form.visibility} onChange=${(v) => set({ visibility: v })}
        options=${[{ value: 'shared', label: 'Shared', icon: 'users-round' }, { value: 'personal', label: 'Personal', icon: 'lock' }]} />
    </${Field}>
    ${form.visibility === 'shared'
    ? html`<${Field} label="Team inbox">
        <${Select} value=${form.team_id ?? ''} onValue=${(v) => set({ team_id: v ? Number(v) : null })}
          placeholder="Everyone (no team)" options=${teams.map((t) => ({ value: t.id, label: t.name }))} />
      </${Field}>`
    : html`<${Field} label="Owner">
        <${Select} value=${form.owner_user_id ?? ''} onValue=${(v) => set({ owner_user_id: v ? Number(v) : null })}
          placeholder="Me" options=${users.map((u) => ({ value: u.id, label: u.name }))} />
      </${Field}>`}
    <${Toggle} checked=${form.is_active} onChange=${(v) => set({ is_active: v })} label="Active"
      hint="Paused channels stop receiving and sending" />
  </div>`;
}

function EmailSetup({ form, setConfig, presets, isNew }) {
  const c = form.config;
  const [sameLogin, setSameLogin] = useState(() => !c.smtp_user || c.smtp_user === c.imap_user);
  const choose = (key) => {
    if (key === 'custom') { setConfig({ preset: 'custom' }); return; }
    const p = presets[key];
    if (!p) return;
    setConfig({ preset: key, imap_host: p.imap_host, imap_port: p.imap_port, imap_ssl: true, smtp_host: p.smtp_host,
      smtp_port: p.smtp_port, smtp_security: p.smtp_security });
  };
  const preset = presets[c.preset];
  return html`<div class="stack">
    <${Field} label="Provider">
      <div class="ch-presets">
        ${[...Object.entries(presets).map(([k, p]) => [k, p.label]), ['custom', 'Other (IMAP/SMTP)']].map(([key, label]) => html`
          <button type="button" key=${key} class=${cx('ch-preset', (c.preset || 'custom') === key && 'is-active')} onClick=${() => choose(key)}>${label}</button>`)}
      </div>
    </${Field}>
    ${preset && html`<${Banner} tone="info" icon="key">${preset.hint}</${Banner}>`}
    <div class="ch-subhead">Receiving (IMAP)</div>
    <div class="form-grid">
      <${Field} label="IMAP server"><${Input} value=${c.imap_host || ''} onValue=${(v) => setConfig({ imap_host: v })} placeholder="imap.example.com" /></${Field}>
      <div class="ch-port-row">
        <${Field} label="Port"><${Input} type="number" value=${c.imap_port ?? 993} onValue=${(v) => setConfig({ imap_port: v })} /></${Field}>
        <${Field} label="Folder"><${Input} value=${c.imap_folder || 'INBOX'} onValue=${(v) => setConfig({ imap_folder: v })} /></${Field}>
      </div>
      <${Field} label="Username"><${Input} value=${c.imap_user || ''} onValue=${(v) => setConfig({ imap_user: v })} autoComplete="off" placeholder=${form.address} /></${Field}>
      <${Field} label="Password" hint=${c.imap_password === MASK ? 'Saved — type to replace' : 'An app password if your provider requires one'}>
        <${Input} type="password" value=${c.imap_password === MASK ? '' : c.imap_password || ''} placeholder=${c.imap_password === MASK ? MASK : ''}
          onValue=${(v) => setConfig({ imap_password: v })} autoComplete="new-password" />
      </${Field}>
    </div>
    <div class="ch-subhead">Sending (SMTP)</div>
    <div class="form-grid">
      <${Field} label="SMTP server"><${Input} value=${c.smtp_host || ''} onValue=${(v) => setConfig({ smtp_host: v })} placeholder="smtp.example.com" /></${Field}>
      <div class="ch-port-row">
        <${Field} label="Port"><${Input} type="number" value=${c.smtp_port ?? 587} onValue=${(v) => setConfig({ smtp_port: v })} /></${Field}>
        <${Field} label="Security">
          <${Select} value=${c.smtp_security || 'starttls'} onValue=${(v) => setConfig({ smtp_security: v })}
            options=${[{ value: 'starttls', label: 'STARTTLS' }, { value: 'ssl', label: 'SSL/TLS' }, { value: 'none', label: 'None' }]} />
        </${Field}>
      </div>
    </div>
    <${Checkbox} checked=${sameLogin} onChange=${(v) => { setSameLogin(v); if (v) setConfig({ smtp_user: '', smtp_password: '' }); }}
      label="Use the same username and password for sending" />
    ${!sameLogin && html`<div class="form-grid">
      <${Field} label="SMTP username"><${Input} value=${c.smtp_user || ''} onValue=${(v) => setConfig({ smtp_user: v })} autoComplete="off" /></${Field}>
      <${Field} label="SMTP password" hint=${c.smtp_password === MASK ? 'Saved — type to replace' : ''}>
        <${Input} type="password" value=${c.smtp_password === MASK ? '' : c.smtp_password || ''} placeholder=${c.smtp_password === MASK ? MASK : ''}
          onValue=${(v) => setConfig({ smtp_password: v })} autoComplete="new-password" />
      </${Field}>
    </div>`}
    ${isNew && html`<${Field} label="Import recent mail" hint="On the first sync, fetch messages from the last few days (older mail stays in your mailbox).">
      <${Select} value=${String(c.initial_days ?? 7)} onValue=${(v) => setConfig({ initial_days: Number(v) })}
        options=${[1, 3, 7, 14, 30].map((d) => ({ value: String(d), label: `${d} day${d === 1 ? '' : 's'}` }))} />
    </${Field}>`}
  </div>`;
}

function EmailSending({ form, set, setConfig }) {
  const c = form.config;
  const org = useStore((s) => s.settings['org.name']);
  const me = useStore((s) => s.me);
  return html`<div class="stack">
    <${Field} label="Sender name customers see">
      <${Select} value=${c.from_name_mode || 'user'} onValue=${(v) => setConfig({ from_name_mode: v })} options=${[
  { value: 'user', label: `The teammate's name — “${me.name}”` },
  { value: 'channel', label: `The account name — “${form.name || 'Orders'}”` },
  { value: 'user_at_org', label: `Name at business — “${me.name.split(' ')[0]} at ${org}”` },
]} />
    </${Field}>
    <${Toggle} checked=${!!c.track_opens} onChange=${(v) => setConfig({ track_opens: v })} label="Show when emails are opened"
      hint="Adds an invisible image; needs Switchboard to be reachable from the internet" />
    <${Toggle} checked=${!!c.append_sent} onChange=${(v) => setConfig({ append_sent: v })} label="Save a copy to the mailbox's Sent folder"
      hint="Leave off for Gmail and Outlook — they keep sent copies automatically" />
    <${Field} label="Default signature" hint="Used when a teammate hasn't set their own. Placeholders: {{user.name}}, {{user.title}}, {{user.phone}}, {{org.name}}">
      <div class="ch-editor"><${RichEditor} value=${form.signature_html || ''} onChange=${(v) => set({ signature_html: v })} toolbar="mini"
        placeholder="{{user.name}} · {{org.name}}" minHeight=${90} /></div>
    </${Field}>
  </div>`;
}

function TwilioSetup({ form, setConfig, type }) {
  const c = form.config;
  return html`<div class="stack">
    <${Banner} tone="info" icon="info">Find these in the Twilio Console under Account Info. ${type === 'whatsapp'
  ? 'Your WhatsApp sender must be approved in Twilio first.' : 'Use a Twilio number with SMS (and MMS for pictures).'}</${Banner}>
    <div class="form-grid">
      <${Field} label="Account SID"><${Input} value=${c.account_sid || ''} onValue=${(v) => setConfig({ account_sid: v.trim() })} placeholder="AC…" autoComplete="off" /></${Field}>
      <${Field} label="Auth token" hint=${c.auth_token === MASK ? 'Saved — type to replace' : ''}>
        <${Input} type="password" value=${c.auth_token === MASK ? '' : c.auth_token || ''} placeholder=${c.auth_token === MASK ? MASK : ''}
          onValue=${(v) => setConfig({ auth_token: v.trim() })} autoComplete="new-password" />
      </${Field}>
      ${type === 'sms' && html`<${Field} label="Messaging Service SID (optional)" hint="Send through a Messaging Service instead of the number">
        <${Input} value=${c.messaging_service_sid || ''} onValue=${(v) => setConfig({ messaging_service_sid: v.trim() })} placeholder="MG…" />
      </${Field}>`}
    </div>
    <${Toggle} checked=${c.validate_signature !== false} onChange=${(v) => setConfig({ validate_signature: v })}
      label="Verify that webhooks really come from Twilio" hint="Turn off only if Switchboard sits behind a proxy that changes its address" />
  </div>`;
}

function ChatPreview({ form }) {
  const c = form.config;
  const org = useStore((s) => s.settings['org.name']);
  return html`<div class="ch-preview" aria-label="Widget preview">
    <div class="ch-preview-panel">
      <div class="ch-preview-head" style=${{ background: c.color }}>
        <div class="strong">${org}</div>
        <div class="ch-preview-status">We're online</div>
      </div>
      <div class="ch-preview-body">
        <div class="ch-preview-greeting">${c.greeting || 'Hi! How can we help?'}</div>
        <div class="ch-preview-msg" style=${{ background: c.color }}>Do you print door hangers?</div>
      </div>
      <div class="ch-preview-input">Write a message…</div>
    </div>
    <div class="ch-preview-launcher" style=${{ background: c.color }}><${Icon} name="message-circle" size=${22} /></div>
  </div>`;
}

function ChatSetup({ form, set, setConfig }) {
  const c = form.config;
  return html`<div class="ch-chat-setup">
    <div class="stack">
      <div class="form-grid">
        <${Field} label="Name in your inbox"><${Input} value=${form.name} onValue=${(v) => set({ name: v })} placeholder="Website chat" /></${Field}>
        <${Field} label="Website" hint="For your reference"><${Input} value=${form.address || ''} onValue=${(v) => set({ address: v })} placeholder="priorityprint.example" /></${Field}>
      </div>
      <${Field} label="Greeting"><${TextArea} value=${c.greeting || ''} onValue=${(v) => setConfig({ greeting: v })} rows=${2} /></${Field}>
      <${Field} label="Message when nobody's around"><${TextArea} value=${c.offline_message || ''} onValue=${(v) => setConfig({ offline_message: v })} rows=${2} /></${Field}>
      <${Field} label="Color"><${ColorChoices} value=${c.color} onChange=${(v) => setConfig({ color: v })} /></${Field}>
      <${Toggle} checked=${!!c.require_email} onChange=${(v) => setConfig({ require_email: v })} label="Ask for an email before chatting" />
      <${Toggle} checked=${c.email_fallback !== false} onChange=${(v) => setConfig({ email_fallback: v })} label="Email replies to visitors who left the page"
        hint="Sent from your system email account when they've been gone 10 minutes" />
    </div>
    <${ChatPreview} form=${form} />
  </div>`;
}

function ConnectInfo({ channel }) {
  if (!channel) {
    return html`<${Empty} icon="link" title="Save first" compact>The URLs and snippets appear once the channel is created.</${Empty}>`;
  }
  const info = channel.connect || {};
  const warn = !info.base_is_public && html`<${Banner} tone="warn">
    Switchboard is running at <span class="mono">${info.base_url}</span>, which the internet can't reach. Set${' '}
    <span class="mono">SWITCHBOARD_BASE_URL</span> to your public address (and restart) before using these URLs.</${Banner}>`;
  if (channel.type === 'chat') {
    return html`<div class="stack">${warn}
      <${CopyField} label="Paste this before </body> on every page of your website" value=${info.snippet} multiline />
      <p class="muted text-sm">WordPress: add it with a header/footer scripts plugin, or in your theme's footer.php.</p>
    </div>`;
  }
  if (channel.type === 'sms' || channel.type === 'whatsapp') {
    return html`<div class="stack">${warn}
      <${CopyField} label="“A message comes in” webhook (HTTP POST)" value=${info.twilio_inbound}
        hint="Twilio Console → Phone Numbers → your number → Messaging configuration" />
      <${CopyField} label="Status callback URL" value=${info.twilio_status} hint="Switchboard also sets this automatically on every text it sends" />
    </div>`;
  }
  if (channel.type === 'api') {
    return html`<div class="stack">${warn}
      <${CopyField} label="Website form endpoint" value=${info.form_endpoint}
        hint="Point any HTML form here. Fields named name, email, phone, subject and message are recognized; everything else is listed in the message." />
      <${CopyField} label="Example form" value=${info.form_snippet} multiline />
      <${CopyField} label="API endpoint (needs an API token)" value=${info.api_endpoint} />
      <${CopyField} label="Example request" value=${info.curl} multiline />
      <${CopyField} label="Signing secret for replies" value=${info.secret || ''}
        hint="Replies are POSTed to your reply URL with an X-Switchboard-Signature: sha256=… header made with this secret" />
    </div>`;
  }
  return html`<div class="stack">${warn}
    <p class="text-2">No IMAP access? Forward mail with a service like Mailgun or SendGrid Inbound Parse (raw MIME) to:</p>
    <${CopyField} label="Inbound email webhook" value=${info.inbound_hook} hint="Treat this like a password — anyone with it can add messages" />
  </div>`;
}

function ChannelEditor({ initial, type, close, onSaved, presets }) {
  const isNew = !initial;
  const [channel, setChannel] = useState(initial);
  const [form, setForm] = useState(() => ({
    name: initial?.name || '',
    address: initial?.address || '',
    visibility: initial?.visibility || 'shared',
    team_id: initial ? initial.team_id : null,
    owner_user_id: initial?.owner_user_id || null,
    is_active: initial ? initial.is_active : true,
    signature_html: initial?.signature_html || '',
    config: { ...EMPTY_CONFIG[type], ...(initial?.config || {}) },
  }));
  const tabs = {
    email: [['setup', 'Account'], ['sending', 'Sending'], ['access', 'Access'], ['connect', 'Forwarding']],
    sms: [['setup', 'Account'], ['access', 'Access'], ['connect', 'Webhooks']],
    whatsapp: [['setup', 'Account'], ['access', 'Access'], ['connect', 'Webhooks']],
    chat: [['setup', 'Appearance'], ['access', 'Access'], ['connect', 'Install']],
    api: [['setup', 'Setup'], ['access', 'Access'], ['connect', 'Connect']],
  }[type];
  const [tab, setTab] = useState('setup');
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState(null);
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const setConfig = (patch) => setForm((f) => ({ ...f, config: { ...f.config, ...patch } }));
  const meta = TYPE_META[type];

  const payload = () => ({ ...form, type, team_id: form.visibility === 'shared' ? form.team_id : null });
  const save = async (e) => {
    e && e.preventDefault();
    setBusy(true);
    try {
      const res = isNew ? await api.post('/channels', payload()) : await api.patch(`/channels/${channel.id}`, payload());
      setChannel(res.channel);
      onSaved();
      loadBootstrap().catch(() => {});
      if (isNew && ['chat', 'sms', 'whatsapp', 'api'].includes(type)) {
        toast(`${meta.label} added — here's how to connect it`);
        setTab('connect');
      } else {
        toast(isNew ? `${meta.label} added` : 'Saved');
        close();
      }
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  };
  const runTest = async () => {
    setTest({ pending: true });
    try {
      const res = channel
        ? await api.post(`/channels/${channel.id}/test`, { config: form.config })
        : await api.post('/channels/test', { type, config: form.config });
      setTest(res);
    } catch (err) {
      setTest({ ok: false, message: err.message });
    }
  };

  const canTest = type !== 'chat';
  return html`<${Modal}
    title=${isNew ? `Add ${meta.label.toLowerCase()}` : channel.name}
    icon=${meta.icon}
    size="lg"
    onClose=${close}
    footer=${html`
      ${canTest && html`<${Button} icon="circle-play" onClick=${runTest} loading=${test?.pending}>Test connection</${Button}>`}
      <span class="grow"></span>
      <${Button} onClick=${close}>${isNew && channel ? 'Done' : 'Cancel'}</${Button}>
      <${Button} variant="primary" type="submit" form="channel-form" loading=${busy}>${isNew && !channel ? 'Add channel' : 'Save'}</${Button}>
    `}
  >
    <form id="channel-form" class="stack" onSubmit=${save}>
      ${(type === 'email' || type === 'sms' || type === 'whatsapp' || type === 'api') && html`<div class="form-grid">
        <${Field} label="Name" hint="Shown in the inbox and the From menu"><${Input} value=${form.name} onValue=${(v) => set({ name: v })}
          placeholder=${{ email: 'Orders', sms: 'Shop text line', whatsapp: 'WhatsApp', api: 'Website quote form' }[type]} autoFocus=${isNew} /></${Field}>
        ${type !== 'api'
    ? html`<${Field} label=${type === 'email' ? 'Email address' : 'Phone number'} required>
            <${Input} type=${type === 'email' ? 'email' : 'tel'} value=${form.address} onValue=${(v) => set({ address: v })}
              placeholder=${type === 'email' ? 'orders@yourshop.com' : '+16025550142'} required />
          </${Field}>`
    : html`<${Field} label="Reply URL (optional)" hint="We POST your replies here as JSON">
            <${Input} type="url" value=${form.config.outbound_url || ''} onValue=${(v) => setConfig({ outbound_url: v })} placeholder="https://…" />
          </${Field}>`}
      </div>`}
      ${initial?.demo && html`<${Banner} tone="info" icon="info">This is a demo channel: it never contacts real servers.</${Banner}>`}
      <${Tabs} tabs=${tabs.map(([id, label]) => ({ id, label }))} value=${tab} onChange=${setTab} size="sm" />
      <div class="ch-tab-body">
        ${tab === 'setup' && type === 'email' && html`<${EmailSetup} form=${form} setConfig=${setConfig} presets=${presets} isNew=${isNew} />`}
        ${tab === 'setup' && (type === 'sms' || type === 'whatsapp') && html`<${TwilioSetup} form=${form} setConfig=${setConfig} type=${type} />`}
        ${tab === 'setup' && type === 'chat' && html`<${ChatSetup} form=${form} set=${set} setConfig=${setConfig} />`}
        ${tab === 'setup' && type === 'api' && html`<div class="stack">
          <p class="text-2">Messages posted by your website forms, Zapier or other tools arrive in the inbox like email. Replies are emailed to the sender from your system email account when they left an address — or, if you set a reply URL above, POSTed to your system instead.</p>
        </div>`}
        ${tab === 'sending' && html`<${EmailSending} form=${form} set=${set} setConfig=${setConfig} />`}
        ${tab === 'access' && html`<${AccessFields} form=${form} set=${set} />`}
        ${tab === 'connect' && html`<${ConnectInfo} channel=${channel} />`}
      </div>
      ${test && !test.pending && html`<${Banner} tone=${test.ok ? 'ok' : 'danger'} icon=${test.ok ? 'circle-check' : 'circle-alert'}>${test.message}</${Banner}>`}
    </form>
  </${Modal}>`;
}

// -- list ---------------------------------------------------------------------------

function ChannelRow({ ch, onEdit, onChanged, teamName, ownerName }) {
  const meta = TYPE_META[ch.type] || TYPE_META.api;
  const status = statusOf(ch);
  const syncNow = async () => {
    try {
      const res = await api.post(`/channels/${ch.id}/sync`);
      toast(res.message, { tone: res.error ? 'danger' : 'default' });
      onChanged();
    } catch (err) { toastError(err); }
  };
  const testIt = async () => {
    try {
      const res = await api.post(`/channels/${ch.id}/test`, {});
      toast(res.message, { tone: res.ok ? 'success' : 'danger' });
    } catch (err) { toastError(err); }
  };
  const toggle = async () => {
    try {
      await api.patch(`/channels/${ch.id}`, { is_active: !ch.is_active });
      onChanged();
      loadBootstrap().catch(() => {});
    } catch (err) { toastError(err); }
  };
  const rotate = async () => {
    if (!(await confirmDialog({ title: 'Reset this channel’s URLs?', message: 'The webhook, widget or form URLs change and the old ones stop working immediately. You will need to paste the new ones where you used the old.', confirmLabel: 'Reset URLs', danger: true }))) return;
    try { await api.post(`/channels/${ch.id}/rotate-key`); onChanged(); toast('New URLs are ready'); } catch (err) { toastError(err); }
  };
  const remove = async () => {
    if (!(await confirmDialog({ title: `Remove ${ch.name}?`, message: 'Its conversations stay in the inbox, but you can no longer reply from this account. To stop it temporarily, pause it instead.', confirmLabel: 'Remove channel', danger: true }))) return;
    try {
      await api.del(`/channels/${ch.id}`);
      onChanged();
      loadBootstrap().catch(() => {});
      toast('Channel removed');
    } catch (err) { toastError(err); }
  };
  const menu = (e) => showMenu(e.currentTarget, [
    { label: 'Edit', icon: 'pencil', onSelect: onEdit },
    ch.type !== 'chat' && { label: 'Test connection', icon: 'circle-play', onSelect: testIt },
    ch.type === 'email' && ch.capabilities?.can_receive && !ch.demo && { label: 'Check for new mail', icon: 'refresh-cw', onSelect: syncNow },
    { label: ch.is_active ? 'Pause' : 'Resume', icon: ch.is_active ? 'pause' : 'play', onSelect: toggle },
    ch.type !== 'email' && { label: 'Reset URLs', icon: 'rotate-ccw', onSelect: rotate },
    { divider: true },
    { label: 'Remove', icon: 'trash', danger: true, onSelect: remove },
  ].filter(Boolean));
  return html`<div class=${cx('ch-row', !ch.is_active && 'is-paused')}>
    <button type="button" class="ch-row-main" onClick=${onEdit}>
      <span class=${cx('ch-type-icon', `ch-type-${ch.type}`)}><${Icon} name=${meta.icon} size=${18} /></span>
      <span class="ch-row-text">
        <span class="ch-row-title">${ch.name}${ch.visibility === 'personal'
    ? html`<${Chip} size="sm" icon="lock">${ownerName(ch.owner_user_id)}</${Chip}>`
    : html`<${Chip} size="sm" icon="users-round">${teamName(ch.team_id)}</${Chip}>`}</span>
        <span class="ch-row-sub">
          <span>${ch.address || meta.label}</span>
          <span>· ${ch.stats.open} open</span>
          ${ch.type === 'email' && ch.last_sync_at && html`<span>· checked <${RelTime} value=${ch.last_sync_at} mode="ago" /></span>`}
        </span>
        ${ch.sync_error && html`<span class="ch-row-error"><${Icon} name="triangle-alert" size=${13} />${ch.sync_error}</span>`}
      </span>
    </button>
    <${Chip} tone=${status.tone} icon=${status.icon} class="ch-status">${status.label}</${Chip}>
    <${IconButton} icon="ellipsis" label="Channel actions" onClick=${menu} />
  </div>`;
}

export default function ChannelsSettings() {
  const { data, loading, error, reload } = useFetch('/channels', { refetchOn: ['settings.changed'] });
  const presetsReq = useFetch('/channels/presets');
  const teams = useStore((s) => s.teams);
  const usersById = useStore((s) => s.usersById);
  const presets = presetsReq.data?.email || {};
  const items = data?.items || [];

  const edit = (ch, type) => openModal((close) => html`<${ChannelEditor}
    initial=${ch} type=${ch ? ch.type : type} close=${close} onSaved=${reload} presets=${presets} />`, { size: 'lg' });
  const addMenu = (e) => showMenu(e.currentTarget, Object.entries(TYPE_META).map(([type, m]) => ({
    label: m.label, hint: m.blurb, icon: m.icon, onSelect: () => edit(null, type),
  })), { width: 300, placement: 'bottom-end' });
  const teamName = (id) => (id ? teams.find((t) => t.id === id)?.name || 'Team' : 'Everyone');
  const ownerName = (id) => usersById[id]?.name || 'Personal';

  const byType = Object.keys(TYPE_META).map((t) => [t, items.filter((c) => c.type === t)]).filter(([, list]) => list.length);
  return html`<div class="ch-settings">
    <${Section} title="Channels" description="Connect the places customers reach you. Email, texts, WhatsApp, website chat and form submissions all arrive in the shared inbox, where your team can assign, discuss and reply."
      actions=${html`<${Button} variant="primary" icon="plus" iconRight="chevron-down" onClick=${addMenu}>Add channel</${Button}>`}>
      ${loading && !data && html`<${Loading} />`}
      <${ErrorBox} error=${error} retry=${reload} />
      ${data && !items.length && html`<${Empty} icon="plug" title="No channels yet"
        action=${html`<${Button} variant="primary" icon="plus" onClick=${addMenu}>Add your first channel</${Button}>`}>
        Start with your main email address, then add your shop's text number and a chat bubble for your website.</${Empty}>`}
      ${byType.map(([type, list]) => html`<div class="ch-group" key=${type}>
        <div class="ch-group-title"><${Icon} name=${TYPE_META[type].icon} size=${14} />${TYPE_META[type].label}</div>
        <div class="ch-list">${list.map((ch) => html`<${ChannelRow} key=${ch.id} ch=${ch} onEdit=${() => edit(ch)}
          onChanged=${reload} teamName=${teamName} ownerName=${ownerName} />`)}</div>
      </div>`)}
    </${Section}>
    ${data && items.some((c) => c.type === 'email') && html`<p class="muted text-sm ch-footnote">
      Email accounts are checked about once a minute. Use “Check for new mail” in an account's menu to fetch right away.</p>`}
  </div>`;
}
