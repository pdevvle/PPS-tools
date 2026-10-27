// Conversation list: rows, multi-select, bulk actions.

import { html, useEffect, useRef } from '../../lib/preact.js';
import { useStore, user as lookupUser } from '../../lib/store.js';
import { fmtUntil } from '../../lib/format.js';
import { Avatar, AvatarStack, Checkbox, Chip, Empty, Icon, IconButton, Loading, RelTime, Button, cx } from '../../ui/components.js';
import { showMenu } from '../../ui/overlay.js';
import {
  act, actWithUndo, channelIcon, conversationTitle, labelById, openAssign, openLabels, openMoveTeam, openPriority,
  openSnooze, participantLabel,
} from './common.js';

const EMPTY = {
  inbox: ['check-check', 'Inbox zero', 'Nothing needs you right now. New messages, assignments and mentions land here.'],
  assigned: ['user-check', 'Nothing assigned to you', 'Conversations assigned to you show up here until they’re closed.'],
  starred: ['star', 'No starred conversations', 'Press S on a conversation to star it.'],
  snoozed: ['alarm-clock', 'Nothing snoozed', 'Snooze a conversation (H) to hide it until you need it.'],
  drafts: ['square-pen', 'No drafts', 'Replies you start but don’t send are kept here.'],
  scheduled: ['send', 'Nothing scheduled', 'Use “Send later” to schedule a message.'],
  sent: ['send-horizontal', 'Nothing sent yet', 'Conversations you’ve replied to appear here.'],
  closed: ['archive', 'No closed conversations', ''],
  spam: ['octagon-alert', 'No spam', ''],
  trash: ['trash', 'Trash is empty', ''],
  search: ['search', 'No matches', 'Try fewer words, or operators like from:, label:, is:unread, has:attachment.'],
};

function PresenceDots({ id }) {
  const viewers = useStore((s) => s.presence[`conversation:${id}`]) || [];
  const meId = useStore((s) => s.me.id);
  const others = viewers.filter((v) => v.user_id !== meId);
  if (!others.length) return null;
  const replying = others.find((v) => v.state === 'composing');
  return html`<span class=${cx('row-presence', replying && 'is-replying')}
    title=${others.map((v) => `${lookupUser(v.user_id).name} ${v.state === 'composing' ? 'is replying' : v.state === 'typing' ? 'is commenting' : 'is viewing'}`).join('\n')}>
    <${Icon} name=${replying ? 'pen-line' : 'eye'} size=${11} />
    <${AvatarStack} users=${others.map((v) => v.user_id)} max=${2} size=${16} />
  </span>`;
}

function Row({ c, active, selected, onOpen, onToggle, showTeam, dragIds }) {
  const teams = useStore((s) => s.teamsById);
  const labels = c.label_ids.map(labelById).filter(Boolean);
  const team = showTeam && c.team_id ? teams[c.team_id] : null;
  const unread = c.unread && !active;
  const onDragStart = (e) => {
    const ids = selected ? dragIds() : [c.id];
    e.dataTransfer.setData('application/x-sb-conversations', JSON.stringify(ids));
    e.dataTransfer.setData('text/plain', `${location.origin}/inbox/c/${c.id}`);
    e.dataTransfer.effectAllowed = 'copy';
  };
  return html`<div
    class=${cx('conv-row', active && 'is-active', selected && 'is-selected', unread && 'is-unread', c.status === 'closed' && 'is-closed')}
    data-id=${c.id}
    role="option"
    aria-selected=${active}
    draggable="true"
    onDragStart=${onDragStart}
    onClick=${(e) => (e.shiftKey || e.metaKey || e.ctrlKey ? onToggle(e) : onOpen(c))}
  >
    <div class="conv-row-lead" onClick=${(e) => { e.stopPropagation(); onToggle(e); }}>
      <span class="conv-row-avatar">
        ${c.contact
    ? html`<${Avatar} name=${c.contact.display_name} color=${colorFor(c.contact.id)} size=${32} title=${false} />`
    : html`<span class="conv-row-icon"><${Icon} name=${channelIcon(c.channel)} size=${16} /></span>`}
        ${c.channel && c.contact && html`<span class=${`conv-row-channel ch-${c.channel.type}`}><${Icon} name=${channelIcon(c.channel)} size=${9} strokeWidth=${2.5} /></span>`}
      </span>
      <span class="conv-row-check"><${Checkbox} checked=${selected} /></span>
    </div>
    <div class="conv-row-main">
      <div class="conv-row-top">
        ${unread && html`<span class="unread-dot" aria-label="Unread"></span>`}
        <span class="conv-row-from truncate">${participantLabel(c)}${c.message_count > 1 ? html`<span class="conv-row-n">${c.message_count}</span>` : null}</span>
        <span class="conv-row-icons">
          ${c.priority === 'urgent' && html`<${Icon} name="flame" size=${13} class="ic-urgent" title="Urgent" />`}
          ${c.priority === 'high' && html`<${Icon} name="flag" size=${13} class="ic-high" title="High priority" />`}
          ${c.has_attachments && html`<${Icon} name="paperclip" size=${13} title="Has attachments" />`}
          ${c.comment_count > 0 && html`<span class="conv-row-comments" title=${`${c.comment_count} comments`}><${Icon} name="message-square" size=${12} />${c.comment_count}</span>`}
          ${c.draft_count > 0 && html`<${Icon} name="pencil" size=${13} class="ic-draft" title="Draft" />`}
          ${c.scheduled_count > 0 && html`<${Icon} name="clock" size=${13} class="ic-scheduled" title="Scheduled message" />`}
          ${c.has_failed && html`<${Icon} name="circle-alert" size=${13} class="ic-failed" title="A message failed to send" />`}
          ${c.starred && html`<${Icon} name="star" size=${13} class="ic-star" title="Starred" />`}
        </span>
        <${RelTime} value=${c.last_activity_at} class="conv-row-time" />
      </div>
      <div class="conv-row-subject truncate">
        <span class="conv-row-subject-text">${conversationTitle(c) !== participantLabel(c) ? conversationTitle(c) : ''}</span>
        <span class="conv-row-preview">${c.preview || ''}</span>
      </div>
      <div class="conv-row-meta">
        ${c.snoozed_until && html`<${Chip} size="sm" icon="alarm-clock" tone="purple">${fmtUntil(c.snoozed_until)}</${Chip}>`}
        ${c.overdue && html`<${Chip} size="sm" icon="timer" tone="danger">Overdue</${Chip}>`}
        ${c.status === 'closed' && html`<${Chip} size="sm" icon="archive" tone="muted">Closed</${Chip}>`}
        ${team && html`<${Chip} size="sm" color=${team.color}>${team.name}</${Chip}>`}
        ${labels.map((l) => html`<${Chip} key=${l.id} size="sm" color=${l.color}>${l.name}</${Chip}>`)}
        <span class="grow"></span>
        <${PresenceDots} id=${c.id} />
        ${c.assignee_ids.length > 0 && html`<${AvatarStack} users=${c.assignee_ids} max=${3} size=${18} />`}
      </div>
    </div>
  </div>`;
}

const CONTACT_COLORS = ['#3b5bdb', '#0c8599', '#2f9e44', '#e8590c', '#c2255c', '#7048e8', '#1971c2', '#d6336c', '#5c940d', '#f08c00'];
export function colorFor(id) {
  return CONTACT_COLORS[(Number(id) || 0) % CONTACT_COLORS.length];
}

export function BulkBar({ items, selection, setSelection, mailbox }) {
  const ids = [...selection];
  const convs = items.filter((c) => selection.has(c.id));
  const allSelected = items.length > 0 && ids.length === items.length;
  const done = () => setSelection(new Set());
  const anyClosed = convs.some((c) => c.status === 'closed');
  const more = (e) => showMenu(e.currentTarget, [
    { label: 'Mark as read', icon: 'mail-open', onSelect: () => act(ids, 'read').then(done) },
    { label: 'Mark as unread', icon: 'mail', onSelect: () => act(ids, 'unread').then(done) },
    { label: 'Star', icon: 'star', onSelect: () => act(ids, 'star').then(done) },
    { label: 'Remove from my inbox', icon: 'archive', onSelect: () => actWithUndo(ids, 'archive').then(done) },
    { label: 'Move to team…', icon: 'users-round', onSelect: () => openMoveTeam(e.target, ids) },
    { label: 'Set priority…', icon: 'flag', onSelect: () => openPriority(e.target, ids) },
    { divider: true },
    mailbox === 'spam'
      ? { label: 'Not spam', icon: 'inbox', onSelect: () => actWithUndo(ids, 'not_spam').then(done) }
      : { label: 'Mark as spam', icon: 'octagon-alert', onSelect: () => actWithUndo(ids, 'spam').then(done) },
    mailbox === 'trash'
      ? { label: 'Restore', icon: 'archive-restore', onSelect: () => actWithUndo(ids, 'restore').then(done) }
      : { label: 'Move to trash', icon: 'trash', danger: true, onSelect: () => actWithUndo(ids, 'trash').then(done) },
  ], { placement: 'bottom-end' });
  return html`<div class="bulk-bar">
    <${Checkbox} checked=${allSelected} indeterminate=${!allSelected && ids.length > 0}
      onChange=${() => setSelection(allSelected ? new Set() : new Set(items.map((c) => c.id)))} />
    <span class="bulk-count">${ids.length} selected</span>
    <span class="grow"></span>
    <${IconButton} icon=${anyClosed ? 'inbox' : 'archive'} label=${anyClosed ? 'Reopen (E)' : 'Close (E)'}
      onClick=${() => actWithUndo(ids, anyClosed ? 'reopen' : 'close').then(done)} />
    <${IconButton} icon="user-plus" label="Assign (A)" onClick=${(e) => openAssign(e.currentTarget, convs, { onDone: done })} />
    <${IconButton} icon="tag" label="Label (L)" onClick=${(e) => openLabels(e.currentTarget, convs)} />
    <${IconButton} icon="alarm-clock" label="Snooze (H)" onClick=${(e) => openSnooze(e.currentTarget, ids, { onDone: done })} />
    <${IconButton} icon="ellipsis" label="More" onClick=${more} />
    <${IconButton} icon="x" label="Clear selection" onClick=${done} />
  </div>`;
}

export function ConversationList({ items, loading, error, parsed, openId, onOpen, selection, setSelection, hasMore, onLoadMore, newDrafts }) {
  const listRef = useRef(null);
  const lastClicked = useRef(null);
  const showTeam = !parsed.teamId;

  useEffect(() => {
    if (!openId || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-id="${openId}"]`);
    if (el) el.scrollIntoView({ block: 'nearest' });
  }, [openId]);

  const toggle = (c) => (e) => {
    const next = new Set(selection);
    if (e && e.shiftKey && lastClicked.current !== null) {
      const ids = items.map((x) => x.id);
      const a = ids.indexOf(lastClicked.current);
      const b = ids.indexOf(c.id);
      ids.slice(Math.min(a, b), Math.max(a, b) + 1).forEach((id) => next.add(id));
    } else {
      next.has(c.id) ? next.delete(c.id) : next.add(c.id);
    }
    lastClicked.current = c.id;
    setSelection(next);
  };

  if (error && !items) return html`<div class="conv-list"><div class="error-box">${error.message}</div></div>`;
  if (!items) return html`<div class="conv-list"><${Loading} /></div>`;
  const [icon, title, text] = EMPTY[parsed.mailbox] || (parsed.teamId
    ? ['users-round', 'All clear', 'No open conversations in this team inbox.']
    : ['tag', 'Nothing here', 'No open conversations with this label.']);
  return html`<div class="conv-list" ref=${listRef} role="listbox" aria-label="Conversations">
    ${newDrafts && newDrafts.length > 0 && html`<div class="conv-list-section">
      <div class="conv-list-section-title">New messages in progress</div>
      ${newDrafts.map((d) => html`<a key=${d.id} class="conv-row draft-row" href=${`/inbox/compose?draft=${d.id}`}>
        <span class="conv-row-icon"><${Icon} name="square-pen" size=${15} /></span>
        <div class="conv-row-main"><div class="conv-row-top"><span class="conv-row-from truncate">${(d.to || []).map((p) => p.name || p.handle).join(', ') || 'No recipients'}</span><${RelTime} value=${d.updated_at} class="conv-row-time" /></div>
        <div class="conv-row-subject truncate"><span class="conv-row-subject-text">${d.subject || '(no subject)'}</span></div></div>
      </a>`)}
    </div>`}
    ${items.map((c) => html`<${Row}
      key=${c.id}
      c=${c}
      active=${c.id === openId}
      selected=${selection.has(c.id)}
      onOpen=${onOpen}
      onToggle=${toggle(c)}
      showTeam=${showTeam}
      dragIds=${() => [...selection]}
    />`)}
    ${!items.length && !(newDrafts && newDrafts.length) && html`<${Empty} icon=${icon} title=${title}>${text}</${Empty}>`}
    ${hasMore && html`<div class="conv-list-more"><${Button} size="sm" variant="ghost" onClick=${onLoadMore} loading=${loading}>Load more</${Button}></div>`}
  </div>`;
}

