// Contact card in the conversation sidebar.

import { html } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch } from '../../lib/hooks.js';
import { navigate } from '../../lib/router.js';
import { can } from '../../lib/store.js';
import { Avatar, Button, Chip, Icon, IconButton, Loading, RelTime, SidePanel, cx } from '../../ui/components.js';
import { confirmDialog, toast, toastError } from '../../ui/overlay.js';
import { InlineText, composeLink, formatPhone, handleIcon, pickOrganization } from './shared.js';

export function ContactPanel({ conversation, contact, reload }) {
  if (!contact || !can('inbox')) return null;
  return html`<${ContactPanelBody} key=${contact.id} contactId=${contact.id} conversation=${conversation} reloadConversation=${reload} />`;
}

function ContactPanelBody({ contactId, conversation, reloadConversation }) {
  const { data, loading, setData } = useFetch(`/contacts/${contactId}`, {
    refetchOn: ['contact.changed', 'conversation.changed'],
    filter: (e, type) => type !== 'contact.changed' || !e.id || e.id === contactId,
  });
  if (loading && !data) return html`<${SidePanel} title="Contact" icon="contact-round"><${Loading} /></${SidePanel}>`;
  if (!data) return null;
  const c = data.contact;
  const others = data.conversations.filter((x) => x.id !== conversation?.id).slice(0, 5);
  const save = async (patch) => {
    const res = await api.patch(`/contacts/${c.id}`, patch);
    setData((d) => ({ ...d, contact: res.contact }));
    reloadConversation && reloadConversation();
  };
  const toggleBlock = async () => {
    if (!c.is_blocked && !(await confirmDialog({
      title: `Block ${c.display_name}?`, message: 'New messages from them will go straight to Spam. You can unblock any time.',
      confirmLabel: 'Block', danger: true,
    }))) return;
    try {
      const res = await api.post(`/contacts/${c.id}/block`, { blocked: !c.is_blocked });
      setData((d) => ({ ...d, contact: res.contact }));
      toast(res.contact.is_blocked ? 'Sender blocked' : 'Sender unblocked');
    } catch (err) { toastError(err); }
  };
  const channelType = conversation?.channel?.type;
  return html`<${SidePanel} title="Contact" icon="contact-round"
    actions=${html`<${IconButton} icon="external-link" size="sm" label="Open contact" onClick=${() => navigate(`/contacts/${c.id}`)} />`}>
    <div class="cpanel">
      <div class="cpanel-head">
        <${Avatar} name=${c.display_name} color=${c.color} size=${40} />
        <div class="cpanel-head-text">
          <${InlineText} value=${c.name} placeholder="Add a name" label="name" class="cpanel-name" onSave=${(name) => save({ name })} />
          <div class="cpanel-sub">
            <${InlineText} value=${c.title} placeholder="Title" label="title" onSave=${(title) => save({ title })} />
            <button type="button" class=${cx('inline-edit', !c.organization && 'is-empty')}
              onClick=${(e) => pickOrganization(e.currentTarget, { selected: c.organization?.id, onChange: (org) => save({ organization_id: org ? org.id : null }).catch(toastError) })}>
              ${c.organization ? c.organization.name : 'Organization'}<${Icon} name="pencil" size=${11} class="inline-edit-icon" /></button>
          </div>
        </div>
      </div>
      ${c.is_blocked && html`<div class="cpanel-blocked"><${Icon} name="ban" size=${13} /> Blocked — their messages go to Spam</div>`}
      <div class="cpanel-handles">
        ${c.handles.map((h) => html`<div class="cpanel-handle" key=${h.id}>
          <${Icon} name=${handleIcon(h.kind)} size=${14} />
          <a href=${composeLink(h.value, h.kind === 'email' ? 'email' : (channelType === 'whatsapp' ? 'whatsapp' : 'sms'))}
            title=${h.kind === 'email' ? 'New email' : 'New text message'}>${h.kind === 'phone' ? formatPhone(h.value) : h.value}</a>
          ${h.label && html`<span class="handle-label">${h.label}</span>`}
        </div>`)}
      </div>
      <div class="cpanel-notes">
        <${InlineText} value=${c.notes} multiline placeholder="Add a note for the team" label="notes" onSave=${(notes) => save({ notes })} />
      </div>
      ${others.length > 0 && html`<div class="cpanel-history">
        <div class="cpanel-label">Other conversations</div>
        ${others.map((x) => html`<a key=${x.id} href=${`/inbox/c/${x.id}`} class="cpanel-history-item">
          <span class=${cx('cpanel-status', x.status === 'open' && 'is-open')}></span>
          <span class="cpanel-history-title">${x.subject || x.preview || 'Conversation'}</span>
          <${RelTime} value=${x.last_activity_at} class="cpanel-history-time" />
        </a>`)}
      </div>`}
      ${data.jobs.length > 0 && html`<div class="cpanel-history">
        <div class="cpanel-label">Jobs</div>
        ${data.jobs.slice(0, 4).map((j) => html`<a key=${j.id} href=${`/jobs/${j.id}`} class="cpanel-history-item">
          <${Icon} name="square-kanban" size=${13} />
          <span class="cpanel-history-title">${j.number} · ${j.title}</span>
          ${j.stage_name && html`<${Chip} size="sm" color=${j.stage_color || undefined}>${j.stage_name}</${Chip}>`}
        </a>`)}
      </div>`}
      <div class="cpanel-actions">
        <${Button} size="sm" variant="ghost" icon="ban" onClick=${toggleBlock}>${c.is_blocked ? 'Unblock sender' : 'Block sender'}</${Button}>
      </div>
    </div>
  </${SidePanel}>`;
}
