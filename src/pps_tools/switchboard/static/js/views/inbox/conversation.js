// One conversation: header + actions, live presence, the timeline, shared drafts,
// the docked composer, the internal comment box and the details sidebar.

import { html, useEffect, useLayoutEffect, useMemo, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useStore, user as lookupUser, can } from '../../lib/store.js';
import { useFetch, useLocalStorage, usePresence, useIsMobile } from '../../lib/hooks.js';
import { useHotkeys } from '../../lib/shortcuts.js';
import { navigate } from '../../lib/router.js';
import { fmtUntil } from '../../lib/format.js';
import { Avatar, AvatarStack, Button, Chip, ErrorBox, Icon, IconButton, Loading, RelTime, cx } from '../../ui/components.js';
import { showMenu, toast, toastError, confirmDialog } from '../../ui/overlay.js';
import { RichEditor, RichText, isEditorEmpty } from '../../ui/editor.js';
import { Composer, scheduledToast } from './composer.js';
import { MessageCard, ChatBubble, CommentItem, EventLine, DaySeparator, Attachments } from './timeline.js';
import { ConversationDetails } from './details.js';
import {
  act, actWithUndo, channelIcon, conversationTitle, copyLink, labelById, openAssign, openLabels, openMerge,
  openMoveTeam, openPriority, openReminder, openSnooze, shareToChat,
} from './common.js';

function Presence({ id }) {
  const viewers = useStore((s) => s.presence[`conversation:${id}`]) || [];
  const meId = useStore((s) => s.me.id);
  const others = viewers.filter((v) => v.user_id !== meId);
  if (!others.length) return null;
  const describe = (v) => (v.state === 'composing' ? 'is replying' : v.state === 'typing' ? 'is commenting' : 'is viewing');
  const replying = others.filter((v) => v.state === 'composing');
  return html`<div class=${cx('presence-bar', replying.length && 'is-replying')}>
    <${AvatarStack} users=${others.map((v) => v.user_id)} max=${4} size=${20} />
    <span>${others.length === 1
    ? `${lookupUser(others[0].user_id).name} ${describe(others[0])}`
    : `${others.length} teammates here${replying.length ? ` · ${replying.map((v) => lookupUser(v.user_id).name.split(' ')[0]).join(', ')} replying` : ''}`}</span>
    ${replying.length > 0 && html`<span class="typing-dots"><i></i><i></i><i></i></span>`}
  </div>`;
}

function SubjectEditor({ conv }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(conv.subject || '');
  useEffect(() => setValue(conv.subject || ''), [conv.subject]);
  const save = async () => {
    setEditing(false);
    if (value.trim() && value !== conv.subject) await act([conv.id], 'subject', { value }).catch(() => {});
  };
  if (editing) {
    return html`<input class="conv-subject-input" value=${value} autoFocus onInput=${(e) => setValue(e.currentTarget.value)}
      onBlur=${save} onKeyDown=${(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') { setValue(conv.subject || ''); setEditing(false); } }} />`;
  }
  return html`<h1 class="conv-subject" title="Click to rename" onClick=${() => setEditing(true)}>${conversationTitle(conv)}</h1>`;
}

function DraftCard({ d, onEdit, onDiscard }) {
  const meId = useStore((s) => s.me.id);
  const viewers = useStore((s) => s.presence[`conversation:${d.conversation_id}`]) || [];
  const editing = viewers.find((v) => v.draft_id === d.id && v.user_id !== meId && v.state === 'composing');
  const author = lookupUser(d.created_by);
  const text = (d.body_html || '').replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
  return html`<div class="draft-card">
    <div class="draft-card-head">
      <${Icon} name="pencil" size=${13} />
      <span><b>${d.created_by === meId ? 'Your draft' : `${author.name}'s draft`}</b>${d.updated_by && d.updated_by !== d.created_by ? ` · edited by ${lookupUser(d.updated_by).name}` : ''}</span>
      <${RelTime} value=${d.updated_at} mode="ago" class="muted text-sm" />
      ${editing && html`<${Chip} size="sm" tone="warn" icon="pen-line">${lookupUser(editing.user_id).name.split(' ')[0]} is editing</${Chip}>`}
      <span class="grow"></span>
      <${Button} size="sm" onClick=${() => onEdit(d)}>${d.created_by === meId ? 'Continue' : 'Edit together'}</${Button}>
      ${d.created_by === meId && html`<${IconButton} icon="trash" size="sm" label="Discard draft" onClick=${() => onDiscard(d)} />`}
    </div>
    ${text && html`<div class="draft-card-body">${text.slice(0, 280)}</div>`}
  </div>`;
}

function CommentBox({ conv, onTyping, boxRef }) {
  const [body, setBody] = useState('');
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const editorRef = useRef(null);
  const fileRef = useRef(null);
  if (boxRef) boxRef.current = { focus: () => editorRef.current && editorRef.current.focus() };
  const upload = async (list) => {
    try {
      const uploaded = await api.upload([...list]);
      setFiles((f) => [...f, ...uploaded]);
    } catch (err) { toastError(err); }
  };
  const submit = async () => {
    if (busy || (isEditorEmpty(body) && !files.length)) return;
    setBusy(true);
    try {
      await api.post(`/conversations/${conv.id}/comments`, { body, attachment_ids: files.map((f) => f.id) });
      editorRef.current && editorRef.current.clear();
      setBody('');
      setFiles([]);
      onTyping(false);
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  return html`<div class="comment-box">
    ${files.length > 0 && html`<div class="comment-box-files"><${Attachments} items=${files} onRemove=${(a) => setFiles(files.filter((f) => f.id !== a.id))} /></div>`}
    <div class="comment-box-row">
      <${RichEditor}
        value=${body}
        onChange=${(v) => { setBody(v); onTyping(!isEditorEmpty(v)); }}
        editorRef=${editorRef}
        toolbar=${false}
        mentions
        submitOnEnter
        onSubmit=${submit}
        onFiles=${upload}
        onBlur=${() => onTyping(false)}
        placeholder="Comment internally…"
        ariaLabel="Internal comment"
        class="comment-editor"
        maxHeight=${180}
      />
      <${IconButton} icon="paperclip" label="Attach" onClick=${() => fileRef.current.click()} />
      <input ref=${fileRef} type="file" multiple hidden onChange=${(e) => { upload(e.currentTarget.files); e.currentTarget.value = ''; }} />
      <${IconButton} icon="send-horizontal" label="Send comment (Enter)" variant=${isEditorEmpty(body) && !files.length ? 'ghost' : 'secondary'} onClick=${submit} />
    </div>
    <div class="comment-box-hint">Only your team sees comments · @mention to notify · Enter to send, Shift+Enter for a new line</div>
  </div>`;
}

function initialExpanded(timeline) {
  const msgs = timeline.filter((t) => t.type === 'message' && t.kind === 'email');
  const open = new Set(msgs.slice(-2).map((m) => m.id));
  timeline.forEach((t) => { if (t.type === 'message' && (t.status === 'failed' || t.status === 'scheduled')) open.add(t.id); });
  return open;
}

export function ConversationView({ id, onBack, onAdvance, listItems }) {
  const me = useStore((s) => s.me);
  const mobile = useIsMobile();
  const { data, error, loading, reload } = useFetch(`/conversations/${id}`, {
    refetchOn: ['conversation.changed', 'reaction.changed', 'draft.changed'],
    filter: (evt, type) => {
      if (type === 'reaction.changed') return evt.target_type === 'comment';
      if (type === 'draft.changed') return evt.conversation_id === id && evt.by !== me.id;
      return evt.id === id;
    },
  });
  const [showDetails, setShowDetails] = useLocalStorage('sb.inbox.details', window.innerWidth >= 1480);
  const [composer, setComposer] = useState(null); // {draft}
  const [typing, setTyping] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [newBelow, setNewBelow] = useState(false);
  const scrollRef = useRef(null);
  const commentRef = useRef(null);
  const lastCount = useRef(0);
  const conv = data?.conversation;

  usePresence(`conversation:${id}`, composer ? 'composing' : typing ? 'typing' : 'viewing', composer?.draft?.id || null);

  const known = useRef(new Set());
  useEffect(() => { setComposer(null); setExpanded(null); lastCount.current = 0; known.current = new Set(); }, [id]);

  useEffect(() => {
    if (!data) return;
    const messageIds = data.timeline.filter((t) => t.type === 'message').map((t) => t.id);
    if (!expanded) setExpanded(initialExpanded(data.timeline));
    else {
      // Messages that arrive while the thread is open start expanded.
      const fresh = messageIds.filter((mid) => !known.current.has(mid));
      if (fresh.length) setExpanded(new Set([...expanded, ...fresh]));
    }
    messageIds.forEach((mid) => known.current.add(mid));
    if (conv.unread && document.visibilityState === 'visible') {
      api.post(`/conversations/${id}/read`).catch(() => {});
    }
  }, [data]);

  // Stick to the bottom when new items arrive and we're already near it.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || !data) return;
    const count = data.timeline.length;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
    if (lastCount.current === 0 || nearBottom) {
      el.scrollTop = el.scrollHeight;
      requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
      setNewBelow(false);
    } else if (count > lastCount.current) {
      setNewBelow(true);
    }
    lastCount.current = count;
  }, [data?.timeline.length, expanded]);

  // Opening the composer shrinks the thread; keep the latest message in view.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && composer) el.scrollTop = el.scrollHeight;
  }, [composer?.draft?.id]);

  const openDraft = async (mode = 'reply', message = null) => {
    if (!conv) return;
    const mine = data.drafts.find((d) => d.created_by === me.id && (mode === 'forward' ? d.mode === 'forward' : d.mode !== 'forward'));
    if (mine && !message) { setComposer({ draft: mine }); return; }
    try {
      const res = await api.post('/drafts', { conversation_id: conv.id, mode, reply_to_message_id: message?.id });
      setComposer({ draft: res.draft });
    } catch (err) { toastError(err); }
  };

  const undoSend = async (messageId) => {
    try {
      const res = await api.post(`/messages/${messageId}/cancel`);
      if (res.draft.conversation_id === id) setComposer({ draft: res.draft });
      else navigate(`/inbox/compose?draft=${res.draft.id}`);
      toast('Back to your draft');
    } catch (err) { toastError(err); }
  };

  const handlers = {
    reply: (m, mode) => openDraft(mode, m),
    cancel: (m) => undoSend(m.id),
    retry: (m) => api.post(`/messages/${m.id}/retry`).then(() => toast('Retrying…')).catch(toastError),
  };

  const close = async () => {
    const closing = conv.status === 'open';
    await actWithUndo([conv.id], closing ? 'close' : 'reopen');
    if (closing && onAdvance) onAdvance(conv.id);
  };

  const discardDraft = async (d) => {
    if (!(await confirmDialog({ title: 'Discard this draft?', danger: true, confirmLabel: 'Discard' }))) return;
    api.del(`/drafts/${d.id}`).then(reload).catch(toastError);
  };

  const moreMenu = (e) => {
    const anchor = e.currentTarget;
    showMenu(anchor, [
      { label: conv.unread ? 'Mark as read' : 'Mark as unread', icon: 'mail', shortcut: '⇧U', onSelect: () => act([conv.id], conv.unread ? 'read' : 'unread') },
      { label: conv.in_inbox ? 'Remove from my inbox' : 'Move to my inbox', icon: conv.in_inbox ? 'archive' : 'inbox', onSelect: () => actWithUndo([conv.id], conv.in_inbox ? 'archive' : 'move_to_inbox') },
      { label: conv.following ? 'Unfollow' : 'Follow', icon: conv.following ? 'bell-off' : 'bell', hint: conv.following ? 'Stop getting it back on new replies' : 'Get it back in your inbox on new replies', onSelect: () => act([conv.id], conv.following ? 'unfollow' : 'follow') },
      { label: 'Remind me…', icon: 'alarm-clock', onSelect: () => openReminder(anchor, conv) },
      { label: 'Set priority…', icon: 'flag', onSelect: () => openPriority(anchor, [conv.id]) },
      { label: 'Move to team…', icon: 'users-round', onSelect: () => openMoveTeam(anchor, [conv.id]) },
      { divider: true },
      { label: 'Merge into…', icon: 'git-merge', disabled: !conv.contact, onSelect: () => openMerge(anchor, conv) },
      { label: 'Share in chat…', icon: 'messages-square', onSelect: () => shareToChat(anchor, conv) },
      { label: 'Copy link', icon: 'link', onSelect: () => copyLink(conv) },
      { label: 'Print', icon: 'printer', onSelect: () => { setExpanded(new Set(data.timeline.filter((t) => t.type === 'message').map((t) => t.id))); setTimeout(() => window.print(), 300); } },
      { divider: true },
      conv.is_spam
        ? { label: 'Not spam', icon: 'inbox', onSelect: () => actWithUndo([conv.id], 'not_spam') }
        : { label: 'Mark as spam', icon: 'octagon-alert', shortcut: '!', onSelect: () => actWithUndo([conv.id], 'spam') },
      ...(conv.contact && !conv.is_spam ? [{ label: 'Block sender', icon: 'ban', onSelect: async () => {
        if (await confirmDialog({ title: `Block ${conv.contact.display_name}?`, message: 'Their future messages go straight to Spam.', confirmLabel: 'Block', danger: true })) {
          act([conv.id], 'spam', { block: true }).then(() => toast('Sender blocked'));
        }
      } }] : []),
      conv.deleted_at
        ? { label: 'Restore from trash', icon: 'archive-restore', onSelect: () => actWithUndo([conv.id], 'restore') }
        : { label: 'Move to trash', icon: 'trash', shortcut: '#', danger: true, onSelect: () => actWithUndo([conv.id], 'trash').then(() => onAdvance && onAdvance(conv.id)) },
      ...(conv.deleted_at && can('admin') ? [{ label: 'Delete forever', icon: 'trash', danger: true, onSelect: async () => {
        if (await confirmDialog({ title: 'Delete forever?', message: 'All messages, comments and files in it are permanently removed.', danger: true, confirmLabel: 'Delete forever' })) {
          act([conv.id], 'delete_forever').then(() => onBack && onBack());
        }
      } }] : []),
    ], { placement: 'bottom-end', width: 250 });
  };

  useHotkeys({
    r: () => conv && conv.channel && openDraft('reply'),
    'shift+r': () => conv && conv.channel?.type === 'email' && openDraft('reply_all'),
    f: () => conv && conv.channel?.type === 'email' && openDraft('forward'),
    m: () => commentRef.current && commentRef.current.focus(),
    escape: () => { if (!composer && onBack) onBack(); },
  }, { enabled: !!conv });

  const timeline = useMemo(() => (data ? data.timeline : []), [data]);
  const openDraftId = composer?.draft?.id;
  const otherDrafts = (data?.drafts || []).filter((d) => d.id !== openDraftId);

  if (error && !data) {
    return html`<div class="conv-view"><div class="conv-empty">
      <${ErrorBox} error=${error} retry=${reload} />
      ${onBack && html`<${Button} onClick=${onBack}>Back</${Button}>`}
    </div></div>`;
  }
  if (!data || !conv || conv.id !== id) return html`<div class="conv-view"><${Loading} /></div>`;

  const canReply = !!conv.channel;
  const isEmail = conv.channel?.type === 'email';
  let lastDay = null;

  return html`<div class=${cx('conv-view', showDetails && !mobile && 'with-details')}>
    <div class="conv-main">
      <header class="conv-header">
        ${onBack && html`<${IconButton} icon="arrow-left" label="Back" onClick=${onBack} class="conv-back" />`}
        <div class="conv-source">
          ${conv.channel ? html`<span class="conv-meta-item"><${Icon} name=${channelIcon(conv.channel)} size=${14} />${conv.channel.name}</span>`
    : html`<span class="conv-meta-item"><${Icon} name="messages-square" size=${14} />Internal discussion</span>`}
          ${conv.contact && html`<a class="conv-meta-item conv-contact-link truncate" href=${`/contacts/${conv.contact.id}`}>${conv.contact.display_name}</a>`}
        </div>
        <div class="conv-actions">
          <button type="button" class="conv-assign" onClick=${(e) => openAssign(e.currentTarget, [conv])} data-tip="Assign (A)">
            ${conv.assignee_ids.length ? html`<${AvatarStack} users=${conv.assignee_ids} max=${3} size=${24} />` : html`<${Icon} name="user-plus" size=${16} /><span class="hide-narrow">Assign</span>`}
          </button>
          <${IconButton} icon="tag" label="Label (L)" onClick=${(e) => openLabels(e.currentTarget, [conv])} />
          <${IconButton} icon="alarm-clock" label="Snooze (H)" onClick=${(e) => openSnooze(e.currentTarget, [conv.id], { onDone: () => onAdvance && onAdvance(conv.id) })} />
          <${IconButton} icon="star" label=${conv.starred ? 'Unstar (S)' : 'Star (S)'} active=${conv.starred} onClick=${() => act([conv.id], conv.starred ? 'unstar' : 'star')} />
          <${Button} variant=${conv.status === 'open' ? 'secondary' : 'soft'} icon=${conv.status === 'open' ? 'check' : 'inbox'} onClick=${close} data-tip=${conv.status === 'open' ? 'Close for everyone (E)' : 'Reopen (E)'} class="conv-close-btn">
            <span class="hide-narrow">${conv.status === 'open' ? 'Close' : 'Reopen'}</span>
          </${Button}>
          <${IconButton} icon="ellipsis" label="More" onClick=${moreMenu} />
          ${!mobile && html`<${IconButton} icon=${showDetails ? 'panel-right-close' : 'panel-right-open'} label=${showDetails ? 'Hide details' : 'Show details'} onClick=${() => setShowDetails(!showDetails)} />`}
        </div>
      </header>
      <${Presence} id=${conv.id} />
      <div class="conv-scroll" ref=${scrollRef} onScroll=${(e) => { const el = e.currentTarget; if (el.scrollHeight - el.scrollTop - el.clientHeight < 80) setNewBelow(false); }}>
        <div class="timeline">
          <div class="conv-hero">
            <${SubjectEditor} conv=${conv} />
            <div class="conv-meta">
              ${conv.status === 'closed' && html`<${Chip} size="sm" tone="muted" icon="archive">Closed</${Chip}>`}
              ${conv.snoozed_until && html`<${Chip} size="sm" tone="purple" icon="alarm-clock" onClick=${() => act([conv.id], 'unsnooze')} title="Click to unsnooze">Snoozed ${fmtUntil(conv.snoozed_until)}</${Chip}>`}
              ${conv.is_spam && html`<${Chip} size="sm" tone="danger" icon="octagon-alert">Spam</${Chip}>`}
              ${conv.deleted_at && html`<${Chip} size="sm" tone="danger" icon="trash">In trash</${Chip}>`}
              ${conv.overdue && html`<${Chip} size="sm" tone="danger" icon="timer">Reply overdue</${Chip}>`}
              ${conv.priority !== 'normal' && html`<${Chip} size="sm" tone=${conv.priority === 'urgent' ? 'danger' : conv.priority === 'high' ? 'orange' : 'muted'} icon="flag">${conv.priority}</${Chip}>`}
              ${conv.label_ids.map((lid) => { const l = labelById(lid); return l && html`<${Chip} key=${lid} size="sm" color=${l.color} onRemove=${() => act([conv.id], 'label', { remove: [lid] })}>${l.name}</${Chip}>`; })}
              <button type="button" class="conv-add-label" onClick=${(e) => openLabels(e.currentTarget, [conv])}><${Icon} name="plus" size=${12} />Label</button>
            </div>
          </div>
          ${timeline.map((t, i) => {
    const day = new Date(t.at).toDateString();
    const sep = day !== lastDay ? html`<${DaySeparator} key=${'d' + day} at=${t.at} />` : null;
    lastDay = day;
    let item;
    if (t.type === 'message') {
      if (t.kind === 'email' || t.kind === 'api') {
        const showSubject = i === 0 || (t.subject && t.subject.replace(/^(re|fwd?):\s*/i, '') !== (conv.subject || '').replace(/^(re|fwd?):\s*/i, ''));
        item = html`<${MessageCard} key=${'m' + t.id} m=${{ ...t, showSubject }} expanded=${!expanded || expanded.has(t.id)} handlers=${handlers}
                onToggle=${() => { const next = new Set(expanded || []); next.has(t.id) ? next.delete(t.id) : next.add(t.id); setExpanded(next); }} />`;
      } else {
        item = html`<${ChatBubble} key=${'m' + t.id} m=${t} handlers=${handlers} />`;
      }
    } else if (t.type === 'comment') {
      item = html`<${CommentItem} key=${'c' + t.id} c=${t} onChanged=${reload} />`;
    } else {
      item = html`<${EventLine} key=${'e' + t.id} e=${t} />`;
    }
    return html`${sep}${item}`;
  })}
          ${otherDrafts.map((d) => html`<${DraftCard} key=${'dr' + d.id} d=${d} onEdit=${(draft) => setComposer({ draft })} onDiscard=${discardDraft} />`)}
        </div>
      </div>
      ${newBelow && html`<button type="button" class="new-below" onClick=${() => { const el = scrollRef.current; el.scrollTop = el.scrollHeight; setNewBelow(false); }}>
        <${Icon} name="arrow-down" size=${14} /> New activity</button>`}
      ${composer && html`<div class="conv-composer"><${Composer}
        key=${composer.draft.id}
        conversation=${conv}
        initialDraft=${composer.draft}
        onClose=${() => { setComposer(null); reload({ quiet: true }); }}
        onSent=${(res, opts) => scheduledToast(res, opts, () => undoSend(res.message_id))}
      /></div>`}
      ${!composer && canReply && html`<div class="reply-bar">
        <${Button} size="sm" icon="reply" onClick=${() => openDraft('reply')} data-tip="Reply (R)">Reply</${Button}>
        ${isEmail && html`<${Button} size="sm" variant="ghost" icon="reply-all" onClick=${() => openDraft('reply_all')} data-tip="Reply all (Shift+R)">Reply all</${Button}>`}
        ${isEmail && html`<${Button} size="sm" variant="ghost" icon="forward" onClick=${() => openDraft('forward')} data-tip="Forward (F)">Forward</${Button}>`}
      </div>`}
      <${CommentBox} conv=${conv} onTyping=${setTyping} boxRef=${commentRef} />
    </div>
    ${showDetails && !mobile && html`<${ConversationDetails} detail=${data} reload=${reload} />`}
  </div>`;
}
