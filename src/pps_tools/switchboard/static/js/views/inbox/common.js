// Inbox routing, mailbox metadata and conversation actions shared by the list, the
// conversation view and keyboard shortcuts.

import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { getState, boot, user as lookupUser } from '../../lib/store.js';
import { navigate } from '../../lib/router.js';
import { fmtDateTime, fmtUntil } from '../../lib/format.js';
import { pickUsers, pickFromList, pickDateTime } from '../../ui/pickers.js';
import { showMenu, toast, toastError, confirmDialog, openModal, Modal, promptDialog } from '../../ui/overlay.js';
import { Button, Empty, Loading } from '../../ui/components.js';

export const MAILBOXES = [
  { id: 'inbox', label: 'Inbox', icon: 'inbox', path: '/inbox' },
  { id: 'assigned', label: 'Assigned to me', icon: 'user-check', path: '/inbox/assigned' },
  { id: 'starred', label: 'Starred', icon: 'star', path: '/inbox/starred' },
  { id: 'snoozed', label: 'Snoozed', icon: 'alarm-clock', path: '/inbox/snoozed' },
  { id: 'drafts', label: 'Drafts', icon: 'square-pen', path: '/inbox/drafts' },
  { id: 'scheduled', label: 'Scheduled', icon: 'send', path: '/inbox/scheduled' },
  { id: 'sent', label: 'Sent', icon: 'send-horizontal', path: '/inbox/sent' },
  { id: 'all', label: 'All conversations', icon: 'mails', path: '/inbox/all' },
  { id: 'closed', label: 'Closed', icon: 'archive', path: '/inbox/closed' },
  { id: 'spam', label: 'Spam', icon: 'octagon-alert', path: '/inbox/spam' },
  { id: 'trash', label: 'Trash', icon: 'trash', path: '/inbox/trash' },
];

export const TEAM_VIEWS = [
  { id: 'open', label: 'Open' },
  { id: 'unassigned', label: 'Unassigned' },
  { id: 'assigned', label: 'Assigned' },
  { id: 'closed', label: 'Closed' },
];

// /inbox/<...>[/c/<id>] -> { mailbox, base, conversationId, compose }
export function parseInboxRoute(route) {
  let segs = route.segments.slice(1);
  let conversationId = null;
  const ci = segs.indexOf('c');
  if (ci >= 0 && segs[ci + 1]) {
    conversationId = Number(segs[ci + 1]);
    segs = segs.slice(0, ci);
  }
  const base = '/inbox' + (segs.length ? '/' + segs.join('/') : '');
  if (segs[0] === 'compose') return { mailbox: 'inbox', base: '/inbox', conversationId: null, compose: true };
  if (!segs.length) return { mailbox: 'inbox', base, conversationId };
  if (segs[0] === 'team' && segs[1]) {
    const sub = segs[2] && segs[2] !== 'open' ? `:${segs[2]}` : '';
    return { mailbox: `team:${segs[1]}${sub}`, base, conversationId, teamId: Number(segs[1]), teamView: segs[2] || 'open' };
  }
  if (segs[0] === 'label' && segs[1]) return { mailbox: `label:${segs[1]}`, base, conversationId, labelId: Number(segs[1]) };
  if (segs[0] === 'search') return { mailbox: 'search', base, conversationId };
  return { mailbox: segs[0], base, conversationId };
}

export function conversationPath(base, id) {
  return `${base === '/inbox' ? '/inbox' : base}/c/${id}`;
}

export function mailboxTitle(parsed) {
  if (parsed.mailbox === 'search') return 'Search';
  if (parsed.teamId) {
    const t = getState().teamsById[parsed.teamId];
    const view = TEAM_VIEWS.find((v) => v.id === parsed.teamView);
    return `${t ? t.name : 'Team'}${view && view.id !== 'open' ? ' · ' + view.label : ''}`;
  }
  if (parsed.labelId) {
    const l = boot('labels').find((x) => x.id === parsed.labelId);
    return l ? l.name : 'Label';
  }
  return MAILBOXES.find((m) => m.id === parsed.mailbox)?.label || 'Inbox';
}

export const CHANNEL_ICONS = { email: 'mail', sms: 'smartphone', whatsapp: 'message-circle', chat: 'message-square', api: 'webhook' };

export function channelIcon(ch) {
  return ch ? CHANNEL_ICONS[ch.type] || 'mail' : 'messages-square';
}

export function conversationTitle(c) {
  if (c.subject) return c.subject;
  if (c.contact) return c.contact.display_name;
  return c.channel ? 'Conversation' : 'Discussion';
}

export function participantLabel(c) {
  if (c.contact) return c.contact.display_name;
  if (!c.channel) return 'Internal discussion';
  return c.channel.name;
}

export function labelById(id) {
  return boot('labels').find((l) => l.id === id);
}

// -- actions ------------------------------------------------------------------------

export async function act(ids, action, params = {}, { quiet = false } = {}) {
  try {
    const res = await api.post('/conversations/actions', { ids, action, ...params });
    return res;
  } catch (err) {
    if (!quiet) toastError(err);
    throw err;
  }
}

const VERBS = {
  close: ['Closed', 'reopen'], reopen: ['Reopened', 'close'], archive: ['Removed from your inbox', 'move_to_inbox'],
  trash: ['Moved to Trash', 'restore'], spam: ['Marked as spam', 'not_spam'], restore: ['Restored', 'trash'],
  not_spam: ['Moved out of Spam', 'spam'], unsnooze: ['Unsnoozed', null], move_to_inbox: ['Moved to your inbox', 'archive'],
};

// Run an action with an "Undo" toast when it can be reversed.
export async function actWithUndo(ids, action, params = {}) {
  await act(ids, action, params);
  const [verb, inverse] = VERBS[action] || [null, null];
  if (!verb) return;
  const what = ids.length > 1 ? `${ids.length} conversations` : 'Conversation';
  toast(`${what}: ${verb.toLowerCase()}`, inverse ? { action: { label: 'Undo', onClick: () => act(ids, inverse) } } : {});
}

export function openAssign(anchor, convs, { onDone } = {}) {
  const single = convs.length === 1 ? convs[0] : null;
  return pickUsers(anchor, {
    title: single ? 'Assign to' : `Assign ${convs.length} conversations`,
    selected: single ? single.assignee_ids : [],
    multi: true,
    filter: (u) => (u.role !== 'staff') || (single && single.assignee_ids.includes(u.id)),
    onChange: async (ids) => {
      try {
        if (single) await act([single.id], 'assign', { user_ids: ids, mode: 'set' });
        else await act(convs.map((c) => c.id), 'assign', { user_ids: ids, mode: 'add' });
        onDone && onDone();
      } catch { /* toasted */ }
    },
  });
}

export function openLabels(anchor, convs, { onDone } = {}) {
  const labels = boot('labels');
  const single = convs.length === 1 ? convs[0] : null;
  const items = labels.map((l) => ({
    id: l.id, label: l.name, color: l.color, hint: l.visibility === 'personal' ? 'Only you' : undefined,
  }));
  let current = new Set(single ? single.label_ids : []);
  return pickFromList(anchor, {
    title: 'Labels',
    items,
    multi: true,
    selected: [...current],
    placeholder: 'Search or create a label…',
    createLabel: 'Create label',
    allowCreate: async (name) => {
      try {
        const res = await api.post('/labels', { name });
        return { id: res.label.id, label: res.label.name, color: res.label.color };
      } catch (err) { toastError(err); return null; }
    },
    onChange: async (ids) => {
      const next = new Set(ids);
      const add = [...next].filter((x) => !current.has(x));
      const remove = single ? [...current].filter((x) => !next.has(x)) : [];
      current = next;
      try {
        await act(convs.map((c) => c.id), 'label', { add, remove });
        onDone && onDone();
      } catch { /* toasted */ }
    },
  });
}

export function openSnooze(anchor, ids, { onDone } = {}) {
  return pickDateTime(anchor, {
    title: 'Snooze until',
    allowClear: false,
    onChange: async (iso) => {
      if (!iso) return;
      try {
        await act(ids, 'snooze', { until: iso });
        toast(`Snoozed until ${fmtDateTime(iso)}`, { action: { label: 'Undo', onClick: () => act(ids, 'unsnooze') } });
        onDone && onDone();
      } catch { /* toasted */ }
    },
  });
}

export function openMoveTeam(anchor, ids) {
  const teams = getState().teams;
  return pickFromList(anchor, {
    title: 'Move to team',
    items: [{ id: 0, label: 'No team', icon: 'circle' }, ...teams.map((t) => ({ id: t.id, label: t.name, color: t.color }))],
    onChange: async (id) => {
      try {
        await act(ids, 'team', { team_id: id || null });
        toast(id ? `Moved to ${teams.find((t) => t.id === id)?.name}` : 'Removed from team');
      } catch { /* toasted */ }
    },
  });
}

export function openPriority(anchor, ids) {
  return showMenu(anchor, ['urgent', 'high', 'normal', 'low'].map((p) => ({
    label: p[0].toUpperCase() + p.slice(1),
    icon: p === 'urgent' ? 'flame' : p === 'high' ? 'flag' : p === 'low' ? 'arrow-down' : 'minus',
    onSelect: () => act(ids, 'priority', { value: p }),
  })));
}

export function openReminder(anchor, conv) {
  return pickDateTime(anchor, {
    title: 'Remind me',
    allowClear: false,
    onChange: async (iso) => {
      if (!iso) return;
      const noReply = conv.last_outbound_at && (!conv.last_inbound_at || conv.last_outbound_at > conv.last_inbound_at);
      try {
        await api.post(`/conversations/${conv.id}/reminders`, { remind_at: iso, condition: noReply ? 'no_reply' : 'always' });
        toast(noReply ? `I'll bring this back ${fmtUntil(iso)} if they haven't replied` : `Reminder set for ${fmtDateTime(iso)}`);
      } catch (err) { toastError(err); }
    },
  });
}

export async function openMerge(anchor, conv) {
  let candidates = [];
  try {
    candidates = (await api.get(`/conversations/${conv.id}/history`)).items;
  } catch { /* none */ }
  const items = candidates.map((c) => ({ id: c.id, label: conversationTitle(c), hint: c.preview || '', icon: channelIcon(c.channel) }));
  pickFromList(anchor, {
    title: `Merge “${conversationTitle(conv)}” into…`,
    items,
    emptyText: 'No other conversations with this contact',
    width: 340,
    onChange: async (targetId) => {
      const ok = await confirmDialog({
        title: 'Merge conversations?',
        message: 'Messages, comments, labels and assignees move into the other conversation. This can’t be undone.',
        confirmLabel: 'Merge',
      });
      if (!ok) return;
      try {
        await act([conv.id], 'merge', { target_id: targetId });
        toast('Merged');
        navigate(`/inbox/c/${targetId}`);
      } catch { /* toasted */ }
    },
  });
}

export async function shareToChat(anchor, conv) {
  let rooms = [];
  try {
    rooms = (await api.get('/chat/rooms')).items || [];
  } catch {
    toast('Team chat is not available');
    return;
  }
  pickFromList(anchor, {
    title: 'Share in chat',
    items: rooms.map((r) => ({
      id: r.id,
      label: r.kind === 'dm' ? (r.name || 'Direct message') : `#${r.name}`,
      icon: r.kind === 'dm' ? 'user' : 'hash',
    })),
    onChange: async (roomId) => {
      const note = await promptDialog({ title: 'Add a note (optional)', label: 'Message', confirmLabel: 'Share', multiline: true });
      if (note === null) return;
      try {
        await api.post(`/chat/rooms/${roomId}/messages`, { body: note ? `<p>${note.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]))}</p>` : '<p></p>', conversation_id: conv.id });
        toast('Shared in chat', { action: { label: 'Open', onClick: () => navigate(`/chat/${roomId}`) } });
      } catch (err) { toastError(err); }
    },
  });
}

export function copyLink(conv) {
  const url = `${location.origin}/inbox/c/${conv.id}`;
  navigator.clipboard?.writeText(url).then(() => toast('Link copied'), () => toast(url));
}

export function startDiscussion() {
  openModal((close) => html`<${DiscussionForm} close=${close} />`);
}

function DiscussionForm({ close }) {
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [userIds, setUserIds] = useState([]);
  const submit = async (e) => {
    e.preventDefault();
    if (!subject.trim()) return;
    const esc = (t) => t.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
    try {
      const res = await api.post('/conversations', {
        subject, body: body.trim() ? `<p>${esc(body).replace(/\n/g, '<br>')}</p>` : '', user_ids: userIds,
      });
      close();
      navigate(`/inbox/c/${res.conversation.id}`);
    } catch (err) { toastError(err); }
  };
  const names = userIds.map((id) => lookupUser(id).name.split(' ')[0]).join(', ');
  return html`<${Modal} title="New internal discussion" icon="messages-square" onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="discussion-form">Start discussion</${Button}>`}>
    <form id="discussion-form" class="stack" onSubmit=${submit}>
      <p class="muted text-sm" style="margin:0">A conversation just for your team — no customer sees it. Good for planning a job or flagging an issue.</p>
      <label class="field"><span class="field-label">Topic</span><input class="input" required autoFocus value=${subject} onInput=${(e) => setSubject(e.currentTarget.value)} placeholder="e.g. Press 2 maintenance window" /></label>
      <label class="field"><span class="field-label">Message</span><textarea class="input textarea" rows="4" value=${body} onInput=${(e) => setBody(e.currentTarget.value)} placeholder="What do you want to discuss?"></textarea></label>
      <div class="field"><span class="field-label">Invite</span>
        <div><${Button} size="sm" icon="user-plus" onClick=${(e) => pickUsers(e.currentTarget, { multi: true, selected: userIds, onChange: setUserIds })}>${names || 'Choose people'}</${Button}></div>
      </div>
    </form>
  </${Modal}>`;
}

// -- AI availability (provided by the ai module when installed) ----------------------

let aiStatus = null;
export async function getAIStatus() {
  if (aiStatus) return aiStatus;
  try {
    aiStatus = await api.get('/ai/status');
  } catch {
    aiStatus = { enabled: false, configured: false };
  }
  return aiStatus;
}

export { Empty, Loading };
