// Team chat: /chat, /chat/<room_id> (?m=<message> &thread=<parent>), /chat/dm/<user_id>

import { html, useCallback, useEffect, useLayoutEffect, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { on } from '../../lib/events.js';
import { useDebounced, useEvent, useFetch, useIsMobile, usePresence } from '../../lib/hooks.js';
import { navigate, setQuery } from '../../lib/router.js';
import { can, useStore, user as lookupUser } from '../../lib/store.js';
import { dateKey } from '../../lib/dates.js';
import { fmtBytes, fmtDateLong, fmtTime, plural } from '../../lib/format.js';
import {
  Avatar, AvatarStack, Button, Chip, Empty, ErrorBox, Field, Icon, IconButton, Input, Loading, RelTime, SearchInput, Toggle, cx,
} from '../../ui/components.js';
import { Modal, confirmDialog, openModal, promptDialog, showMenu, showPopover, toast, toastError } from '../../ui/overlay.js';
import { pickEmoji, pickUsers } from '../../ui/pickers.js';
import { RichEditor, RichText, isEditorEmpty } from '../../ui/editor.js';
import { ModuleLayout, SidebarButton, SidebarHeader, SidebarSection } from '../../ui/layout.js';
import { registerCommands } from '../../ui/palette.js';

const LAST_ROOM_KEY = 'sb.chat.last';

// -- rooms list ---------------------------------------------------------------------

function roomLabel(r) {
  return r.kind === 'channel' ? r.name : r.title;
}

function RoomIcon({ r, size = 20 }) {
  if (r.kind === 'channel') return html`<span class="chat-room-icon"><${Icon} name=${r.is_private ? 'lock' : 'hash'} size=${15} /></span>`;
  const others = r.other_ids || [];
  if (others.length > 1) return html`<${AvatarStack} users=${others} max=${2} size=${size - 4} />`;
  return html`<${Avatar} user=${others[0]} size=${size} online="auto" />`;
}

function RoomItem({ r, active, onClick }) {
  const unread = !r.muted && r.unread > 0;
  return html`<a href=${`/chat/${r.id}`} onClick=${onClick}
    class=${cx('chat-room-item', active && 'is-active', unread && 'is-unread', r.muted && 'is-muted')} aria-current=${active ? 'page' : undefined}>
    <${RoomIcon} r=${r} />
    <span class="chat-room-name">${roomLabel(r)}</span>
    ${r.muted && html`<${Icon} name="bell-off" size=${12} class="chat-room-muted" />`}
    ${r.mentions > 0 ? html`<span class="chat-badge is-mention">${r.mentions}</span>` : unread ? html`<span class="chat-badge">${r.unread > 99 ? '99+' : r.unread}</span>` : null}
  </a>`;
}

function RoomList({ rooms, activeId, compact }) {
  const channels = rooms.filter((r) => r.kind === 'channel').sort((a, b) => a.name.localeCompare(b.name));
  const dms = rooms.filter((r) => r.kind === 'dm').sort((a, b) => (b.last_message_at || b.created_at).localeCompare(a.last_message_at || a.created_at));
  return html`<div class=${cx('chat-rooms', compact && 'is-page')}>
    <${SidebarSection} title="Channels" actions=${html`
      <${IconButton} icon="search" size="sm" label="Browse channels" onClick=${openBrowse} />
      <${IconButton} icon="plus" size="sm" label="New channel" onClick=${openCreateChannel} />`}>
      ${channels.map((r) => html`<${RoomItem} key=${r.id} r=${r} active=${r.id === activeId} />`)}
      <button type="button" class="chat-room-item chat-room-add" onClick=${openBrowse}><span class="chat-room-icon"><${Icon} name="plus" size=${14} /></span><span class="chat-room-name">Browse channels</span></button>
    </${SidebarSection}>
    <${SidebarSection} title="Direct messages" actions=${html`<${IconButton} icon="message-square-plus" size="sm" label="New message" onClick=${openNewMessageModal} />`}>
      ${dms.map((r) => html`<${RoomItem} key=${r.id} r=${r} active=${r.id === activeId} />`)}
      ${!dms.length && html`<button type="button" class="chat-room-item chat-room-add" onClick=${openNewMessageModal}><span class="chat-room-icon"><${Icon} name="plus" size=${14} /></span><span class="chat-room-name">Message a teammate</span></button>`}
    </${SidebarSection}>
  </div>`;
}

// -- modals -------------------------------------------------------------------------

function CreateChannelForm({ close }) {
  const [form, setForm] = useState({ name: '', topic: '', is_private: false, member_ids: [] });
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await api.post('/chat/rooms', form);
      close();
      navigate(`/chat/${res.room.id}`);
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  return html`<${Modal} title="New channel" icon="hash" onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="channel-form" loading=${busy}>Create channel</${Button}>`}>
    <form id="channel-form" class="stack" onSubmit=${submit}>
      <${Field} label="Name" hint="Lowercase, no spaces — e.g. estimating, deliveries">
        <div class="chat-name-input"><span>#</span><${Input} value=${form.name} onValue=${set('name')} required autoFocus placeholder="estimating" /></div>
      </${Field}>
      <${Field} label="Topic"><${Input} value=${form.topic} onValue=${set('topic')} placeholder="What's this channel for?" /></${Field}>
      <${Toggle} checked=${form.is_private} onChange=${set('is_private')} label="Private channel" hint="Only people you add can find and read it" />
      <${Field} label="Add people">
        <div class="row row-wrap gap-2">
          ${form.member_ids.map((id) => html`<span class="attendee-chip" key=${id}><${Avatar} user=${id} size=${18} />${lookupUser(id).name}
            <button type="button" aria-label="Remove" onClick=${() => set('member_ids')(form.member_ids.filter((x) => x !== id))}><${Icon} name="x" size=${12} /></button></span>`)}
          <${Button} size="sm" icon="user-plus" onClick=${(e) => pickUsers(e.currentTarget, { selected: form.member_ids, multi: true, onChange: set('member_ids') })}>Add</${Button}>
        </div>
      </${Field}>
    </form>
  </${Modal}>`;
}

function openCreateChannel() {
  openModal((close) => html`<${CreateChannelForm} close=${close} />`);
}

function BrowseChannels({ close }) {
  const { data, loading } = useFetch('/chat/rooms/browse', { refetchOn: ['chat.room'] });
  const [q, setQ] = useState('');
  const items = (data?.items || []).filter((r) => !q || r.name.includes(q.toLowerCase()) || (r.topic || '').toLowerCase().includes(q.toLowerCase()));
  const join = async (r) => {
    try {
      if (!r.is_member) await api.post(`/chat/rooms/${r.id}/join`);
      close();
      navigate(`/chat/${r.id}`);
    } catch (err) { toastError(err); }
  };
  return html`<${Modal} title="Browse channels" icon="hash" onClose=${close}
    footer=${html`<${Button} icon="plus" onClick=${() => { close(); openCreateChannel(); }}>New channel</${Button}><span class="grow"></span><${Button} onClick=${close}>Done</${Button}>`}>
    <div class="stack">
      <${SearchInput} value=${q} onValue=${setQ} placeholder="Find a channel" autoFocus />
      ${loading && !data && html`<${Loading} />`}
      <div class="chat-browse">
        ${items.map((r) => html`<div class="chat-browse-row" key=${r.id}>
          <span class="chat-room-icon"><${Icon} name="hash" size=${15} /></span>
          <div class="grow"><div class="strong">${r.name}</div><div class="muted text-sm">${r.topic || 'No topic'} · ${plural(r.member_count, 'member')}</div></div>
          <${Button} size="sm" variant=${r.is_member ? 'secondary' : 'primary'} onClick=${() => join(r)}>${r.is_member ? 'Open' : 'Join'}</${Button}>
        </div>`)}
        ${data && !items.length && html`<${Empty} icon="hash" compact title="No channels found" />`}
      </div>
    </div>
  </${Modal}>`;
}

function openBrowse() {
  openModal((close) => html`<${BrowseChannels} close=${close} />`);
}

function NewMessageForm({ close }) {
  const me = useStore((s) => s.me);
  const users = useStore((s) => s.users.filter((u) => u.is_active && u.id !== s.me.id));
  const [picked, setPicked] = useState([]);
  const [q, setQ] = useState('');
  const toggle = (id) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  const start = async () => {
    if (!picked.length) return;
    try {
      const res = picked.length === 1 ? await api.post(`/chat/dm/${picked[0]}`) : await api.post('/chat/dms', { user_ids: picked });
      close();
      navigate(`/chat/${res.room.id}`);
    } catch (err) { toastError(err); }
  };
  const shown = users.filter((u) => !q || u.name.toLowerCase().includes(q.toLowerCase()));
  return html`<${Modal} title="New message" icon="message-square-plus" onClose=${close}
    footer=${html`<${Button} onClick=${() => { close(); navigate(`/chat/dm/${me.id}`); }}>Notes to self</${Button}><span class="grow"></span>
      <${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" disabled=${!picked.length} onClick=${start}>${picked.length > 1 ? 'Start group message' : 'Start'}</${Button}>`}>
    <div class="stack">
      <${SearchInput} value=${q} onValue=${setQ} placeholder="Search teammates" autoFocus />
      <div class="chat-people">
        ${shown.map((u) => html`<button type="button" key=${u.id} class=${cx('chat-person', picked.includes(u.id) && 'is-picked')} onClick=${() => toggle(u.id)}>
          <${Avatar} user=${u} size=${28} online="auto" />
          <span class="grow"><span class="strong">${u.name}</span><span class="muted text-sm"> ${u.title || ''}</span></span>
          ${picked.includes(u.id) && html`<${Icon} name="check" size=${16} />`}
        </button>`)}
      </div>
    </div>
  </${Modal}>`;
}

function openNewMessageModal() {
  openModal((close) => html`<${NewMessageForm} close=${close} />`);
}

function ShareConversation({ close, roomId }) {
  const [q, setQ] = useState('');
  const debounced = useDebounced(q, 200);
  const { data, loading } = useFetch('/conversations', { query: { mailbox: 'all', q: debounced || undefined, include_closed: 1, limit: 12 } });
  const share = async (c) => {
    try {
      await api.post(`/chat/rooms/${roomId}/messages`, { body: '', conversation_id: c.id });
      close();
    } catch (err) { toastError(err); }
  };
  return html`<${Modal} title="Share a conversation" icon="mail" onClose=${close}>
    <div class="stack">
      <${SearchInput} value=${q} onValue=${setQ} placeholder="Search conversations" autoFocus />
      ${loading && !data && html`<${Loading} />`}
      <div class="chat-share-list">
        ${(data?.items || []).map((c) => html`<button type="button" key=${c.id} class="chat-share-item" onClick=${() => share(c)}>
          <${Icon} name="mail" size=${15} />
          <span class="grow"><span class="strong">${c.subject || c.contact?.display_name || 'Conversation'}</span>
            <span class="muted text-sm"> ${c.contact?.display_name || ''}</span></span>
          <${RelTime} value=${c.last_activity_at} class="muted text-sm" />
        </button>`)}
      </div>
    </div>
  </${Modal}>`;
}

// -- message rendering --------------------------------------------------------------

function ConversationCard({ conv }) {
  if (conv.restricted) {
    return html`<div class="chat-conv-card is-restricted"><${Icon} name="lock" size=${14} /> A conversation you don't have access to</div>`;
  }
  return html`<a class="chat-conv-card" href=${conv.url}>
    <span class="chat-conv-icon"><${Icon} name="mail" size=${16} /></span>
    <span class="chat-conv-main">
      <span class="chat-conv-title">${conv.subject}</span>
      <span class="chat-conv-sub">${conv.contact ? `${conv.contact} · ` : ''}${conv.preview || ''}</span>
    </span>
    <${Chip} size="sm" tone=${conv.status === 'open' ? 'ok' : 'muted'}>${conv.status === 'open' ? 'Open' : 'Closed'}</${Chip}>
  </a>`;
}

function Attachments({ items }) {
  if (!items?.length) return null;
  const images = items.filter((a) => a.is_image);
  const others = items.filter((a) => !a.is_image);
  return html`<div class="chat-attachments">
    ${images.length > 0 && html`<div class="image-attachments">${images.map((a) => html`<a key=${a.id} class="image-attachment" href=${a.url} target="_blank" rel="noopener">
      <img src=${a.url} alt=${a.filename} loading="lazy" /></a>`)}</div>`}
    ${others.length > 0 && html`<div class="attachments">${others.map((a) => html`<a key=${a.id} class="attachment" href=${`${a.url}?download=1`} target="_blank" rel="noopener">
      <span class="attachment-icon"><${Icon} name="file" size=${15} /></span>
      <span class="stack-0"><span class="attachment-name">${a.filename}</span><span class="attachment-size">${fmtBytes(a.size)}</span></span></a>`)}</div>`}
  </div>`;
}

function Reactions({ m, me, onToggle }) {
  if (!m.reactions?.length) return null;
  return html`<div class="chat-reactions">
    ${m.reactions.map((r) => html`<button type="button" key=${r.emoji} class=${cx('chat-reaction', r.user_ids.includes(me.id) && 'is-mine')}
      title=${r.user_ids.map((id) => lookupUser(id).name).join(', ')} onClick=${() => onToggle(m, r.emoji)}>
      <span>${r.emoji}</span><span class="chat-reaction-count">${r.user_ids.length}</span></button>`)}
    <button type="button" class="chat-reaction chat-reaction-add" aria-label="Add reaction" onClick=${(e) => pickEmoji(e.currentTarget, { onPick: (emoji) => onToggle(m, emoji) })}>
      <${Icon} name="smile-plus" size=${14} /></button>
  </div>`;
}

function MessageEditor({ m, onDone }) {
  const [value, setValue] = useState(m.body);
  const save = async () => {
    if (isEditorEmpty(value) && !m.attachments.length && !m.conversation) return;
    try { await api.patch(`/chat/messages/${m.id}`, { body: value }); onDone(); } catch (err) { toastError(err); }
  };
  return html`<div class="chat-edit">
    <${RichEditor} value=${m.body} onChange=${setValue} toolbar=${false} submitOnEnter onSubmit=${save} onEscape=${onDone} mentions autofocus />
    <div class="chat-edit-actions"><span class="muted text-xs">Enter to save · Esc to cancel</span><span class="grow"></span>
      <${Button} size="sm" onClick=${onDone}>Cancel</${Button}><${Button} size="sm" variant="primary" onClick=${save}>Save</${Button}></div>
  </div>`;
}

function Message({ m, grouped, room, me, onReply, onToggleReaction, highlight, inThread = false }) {
  const [editing, setEditing] = useState(false);
  const mine = m.user_id === me.id;
  const author = lookupUser(m.user_id);
  const canDelete = mine || ['owner', 'admin'].includes(me.role);
  const remove = async () => {
    if (!(await confirmDialog({ title: 'Delete this message?', confirmLabel: 'Delete', danger: true }))) return;
    try { await api.del(`/chat/messages/${m.id}`); } catch (err) { toastError(err); }
  };
  const copyLink = () => {
    const url = `${location.origin}/chat/${room.id}?m=${m.id}${m.parent_id ? `&thread=${m.parent_id}` : ''}`;
    navigator.clipboard?.writeText(url).then(() => toast('Link copied')).catch(() => {});
  };
  const more = (e) => showMenu(e.currentTarget, [
    { label: 'Copy link', icon: 'link', onSelect: copyLink },
    mine && !m.deleted && { label: 'Edit', icon: 'pencil', onSelect: () => setEditing(true) },
    canDelete && !m.deleted && { label: 'Delete', icon: 'trash', danger: true, onSelect: remove },
  ].filter(Boolean));
  return html`<div id=${`m${m.id}`} tabIndex="-1" class=${cx('chat-msg', grouped && 'is-grouped', highlight && 'is-highlight', m.deleted && 'is-deleted')}>
    <div class="chat-msg-gutter">
      ${grouped ? html`<span class="chat-msg-hovertime">${fmtTime(m.created_at)}</span>` : html`<${Avatar} user=${author} size=${34} />`}
    </div>
    <div class="chat-msg-main">
      ${!grouped && html`<div class="chat-msg-head"><span class="chat-msg-author">${author.name}</span>
        <time class="chat-msg-time" datetime=${m.created_at} title=${fmtDateLong(m.created_at)}>${fmtTime(m.created_at)}</time></div>`}
      ${editing ? html`<${MessageEditor} m=${m} onDone=${() => setEditing(false)} />`
    : m.deleted ? html`<div class="chat-msg-deleted">This message was deleted.</div>`
      : html`${!isEditorEmpty(m.body) && html`<${RichText} html=${m.body} class="chat-msg-body" />`}
            ${m.edited_at && html`<span class="chat-msg-edited">(edited)</span>`}`}
      ${!m.deleted && html`<${Attachments} items=${m.attachments} />`}
      ${m.conversation && html`<${ConversationCard} conv=${m.conversation} />`}
      ${!m.deleted && html`<${Reactions} m=${m} me=${me} onToggle=${onToggleReaction} />`}
      ${!inThread && m.reply_count > 0 && html`<button type="button" class="chat-thread-summary" onClick=${() => onReply(m)}>
        <${AvatarStack} users=${m.reply_user_ids || []} max=${3} size=${18} />
        <span class="chat-thread-count">${plural(m.reply_count, 'reply', 'replies')}</span>
        ${m.last_reply_at && html`<span class="muted">Last reply <${RelTime} value=${m.last_reply_at} mode="ago" /></span>`}
      </button>`}
    </div>
    ${!m.deleted && !editing && html`<div class="chat-msg-tools">
      <${IconButton} icon="smile-plus" size="sm" label="React" onClick=${(e) => pickEmoji(e.currentTarget, { onPick: (emoji) => onToggleReaction(m, emoji) })} />
      ${!inThread && html`<${IconButton} icon="message-square" size="sm" label="Reply in thread" onClick=${() => onReply(m)} />`}
      ${mine && html`<${IconButton} icon="pencil" size="sm" label="Edit" onClick=${() => setEditing(true)} />`}
      <${IconButton} icon="ellipsis" size="sm" label="More" onClick=${more} />
    </div>`}
  </div>`;
}

function buildBlocks(items, lastRead, meId) {
  const blocks = [];
  let prev = null;
  let unreadPlaced = !lastRead;
  for (const m of items) {
    const day = dateKey(m.created_at);
    let divider = false;
    if (!prev || dateKey(prev.created_at) !== day) {
      blocks.push({ type: 'day', key: 'd' + day, at: m.created_at });
      divider = true;
    }
    if (!unreadPlaced && m.created_at > lastRead && m.user_id !== meId) {
      blocks.push({ type: 'unread', key: 'unread' });
      unreadPlaced = true;
      divider = true;
    }
    const grouped = !divider && prev && prev.user_id === m.user_id && !prev.deleted
      && new Date(m.created_at) - new Date(prev.created_at) < 5 * 60000;
    blocks.push({ type: 'msg', key: m.id, m, grouped });
    prev = m;
  }
  return blocks;
}

function dayLabel(at) {
  const d = new Date(at);
  const today = new Date();
  const y = new Date(Date.now() - 86400000);
  if (dateKey(d) === dateKey(today)) return 'Today';
  if (dateKey(d) === dateKey(y)) return 'Yesterday';
  return fmtDateLong(d);
}

function applyReactions(list, evt) {
  if (evt.target_type !== 'chat_message') return list;
  return list.map((m) => (m.id === evt.target_id ? { ...m, reactions: evt.reactions } : m));
}

async function toggleReaction(m, emoji, update) {
  try {
    const res = await api.post('/reactions', { target_type: 'chat_message', target_id: m.id, emoji });
    update((list) => list.map((x) => (x.id === m.id ? { ...x, reactions: res.reactions } : x)));
  } catch (err) { toastError(err); }
}

// -- composer -----------------------------------------------------------------------

function Composer({ roomId, parentId = null, placeholder, autofocus, onSent, allowShare }) {
  const editorRef = useRef(null);
  const [value, setValue] = useState('');
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);
  const lastTyping = useRef(0);
  const fileInput = useRef(null);
  const upload = async (list) => {
    if (!list.length) return;
    setUploading(true);
    try { const added = await api.upload(list); setFiles((f) => [...f, ...added]); } catch (err) { toastError(err); } finally { setUploading(false); }
  };
  const onChange = (v) => {
    setValue(v);
    if (!isEditorEmpty(v) && Date.now() - lastTyping.current > 3000) {
      lastTyping.current = Date.now();
      api.post(`/chat/rooms/${roomId}/typing`).catch(() => {});
    }
  };
  const send = async () => {
    const html_ = editorRef.current ? editorRef.current.getHTML() : value;
    if ((isEditorEmpty(html_) && !files.length) || sending || uploading) return;
    setSending(true);
    try {
      const res = await api.post(`/chat/rooms/${roomId}/messages`, { body: html_, parent_id: parentId, attachment_ids: files.map((f) => f.id) });
      editorRef.current && editorRef.current.clear();
      setValue('');
      setFiles([]);
      lastTyping.current = 0;
      onSent && onSent(res.message);
    } catch (err) { toastError(err); } finally {
      setSending(false);
      editorRef.current && editorRef.current.focus();
    }
  };
  const extra = html`
    <input type="file" multiple hidden ref=${fileInput} onChange=${(e) => { upload([...e.currentTarget.files]); e.currentTarget.value = ''; }} />
    <button type="button" class="editor-tool" data-tip="Attach files" aria-label="Attach files" onMouseDown=${(e) => e.preventDefault()} onClick=${() => fileInput.current.click()}><${Icon} name="paperclip" size=${15} /></button>
    <button type="button" class="editor-tool" data-tip="Emoji" aria-label="Insert emoji" onMouseDown=${(e) => e.preventDefault()}
      onClick=${(e) => pickEmoji(e.currentTarget, { onPick: (emoji) => editorRef.current && editorRef.current.insertHTML(emoji) })}><${Icon} name="smile" size=${15} /></button>
    ${allowShare && can('inbox') && html`<button type="button" class="editor-tool" data-tip="Share an inbox conversation" aria-label="Share a conversation"
      onMouseDown=${(e) => e.preventDefault()} onClick=${() => openModal((close) => html`<${ShareConversation} close=${close} roomId=${roomId} />`)}><${Icon} name="mail" size=${15} /></button>`}
    <${Button} size="sm" variant="primary" icon="send-horizontal" class="chat-send" loading=${sending}
      disabled=${(isEditorEmpty(value) && !files.length) || uploading} onClick=${send} aria-label="Send" />`;
  return html`<div class="chat-composer">
    ${files.length > 0 && html`<div class="attachments chat-composer-files">
      ${files.map((f) => html`<span class="attachment" key=${f.id}><span class="attachment-icon"><${Icon} name=${f.is_image ? 'image' : 'file'} size=${14} /></span>
        <span class="attachment-name">${f.filename}</span>
        <button type="button" class="attachment-remove" aria-label=${`Remove ${f.filename}`} onClick=${() => setFiles(files.filter((x) => x.id !== f.id))}><${Icon} name="x" size=${12} /></button></span>`)}
    </div>`}
    ${uploading && html`<div class="muted text-sm chat-uploading">Uploading…</div>`}
    <${RichEditor} editorRef=${editorRef} value="" onChange=${onChange} placeholder=${placeholder} toolbar="mini" toolbarPosition="bottom"
      toolbarExtra=${extra} submitOnEnter onSubmit=${send} mentions onFiles=${upload} autofocus=${autofocus} maxHeight=${220} />
  </div>`;
}

function TypingLine({ roomId }) {
  const [typers, setTypers] = useState({});
  useEvent('chat.typing', (e) => {
    if (e.room_id !== roomId) return;
    setTypers((t) => ({ ...t, [e.user_id]: Date.now() }));
  }, [roomId]);
  useEffect(() => {
    const off = on('chat.message', (e) => { if (e.room_id === roomId) setTypers((t) => { const n = { ...t }; delete n[e.user_id]; return n; }); });
    const timer = setInterval(() => setTypers((t) => {
      const n = Object.fromEntries(Object.entries(t).filter(([, at]) => Date.now() - at < 4500));
      return Object.keys(n).length === Object.keys(t).length ? t : n;
    }), 1500);
    return () => { off(); clearInterval(timer); };
  }, [roomId]);
  const names = Object.keys(typers).map((id) => lookupUser(Number(id)).name.split(' ')[0]);
  return html`<div class="chat-typing" aria-live="polite">${names.length ? html`<span class="chat-typing-dots"><i></i><i></i><i></i></span>
    ${names.length === 1 ? `${names[0]} is typing…` : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]} are typing…`}` : ''}</div>`;
}

// -- thread -------------------------------------------------------------------------

function ThreadPanel({ parentId, room, me, onClose, highlightId }) {
  const { data, error, setData } = useFetch(`/chat/messages/${parentId}/thread`, {
    refetchOn: ['chat.message'],
    filter: (e) => e.room_id === room.id && (e.parent_id === parentId || e.id === parentId),
  });
  const listRef = useRef(null);
  useEvent('reaction.changed', (e) => {
    setData((d) => d && { parent: applyReactions([d.parent], e)[0], replies: applyReactions(d.replies, e) });
  });
  useLayoutEffect(() => {
    if (listRef.current && !highlightId) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [data?.replies?.length]);
  const update = (fn) => setData((d) => d && { parent: fn([d.parent])[0], replies: fn(d.replies) });
  const blocks = data ? buildBlocks(data.replies, null, me.id) : [];
  return html`<aside class="chat-thread" aria-label="Thread">
    <header class="chat-thread-head">
      <div class="grow"><div class="strong">Thread</div><div class="muted text-sm">${room.kind === 'channel' ? `#${room.name}` : room.title}</div></div>
      <${IconButton} icon="x" label="Close thread" onClick=${onClose} />
    </header>
    <div class="chat-thread-list" ref=${listRef}>
      ${error && html`<div class="pad muted">This thread isn't available.</div>`}
      ${!data && !error && html`<${Loading} />`}
      ${data && html`<${Message} m=${data.parent} room=${room} me=${me} inThread onReply=${() => {}}
        onToggleReaction=${(m, emoji) => toggleReaction(m, emoji, update)} highlight=${highlightId === data.parent.id} />
        <div class="chat-thread-divider"><span>${plural(data.replies.length, 'reply', 'replies')}</span></div>
        ${blocks.filter((b) => b.type === 'msg').map((b) => html`<${Message} key=${b.key} m=${b.m} grouped=${b.grouped} room=${room} me=${me} inThread
          onReply=${() => {}} onToggleReaction=${(m, emoji) => toggleReaction(m, emoji, update)} highlight=${highlightId === b.m.id} />`)}`}
    </div>
    <${Composer} roomId=${room.id} parentId=${parentId} placeholder="Reply…" autofocus />
  </aside>`;
}

// -- room ---------------------------------------------------------------------------

function RoomHeader({ room, me, mobile, onShowMembers, reloadRooms }) {
  const isChannel = room.kind === 'channel';
  const canManage = isChannel && (room.created_by === me.id || ['owner', 'admin', 'manager'].includes(me.role));
  const editTopic = async () => {
    const topic = await promptDialog({ title: `Topic for #${room.name}`, value: room.topic || '', confirmLabel: 'Save topic' });
    if (topic === null) return;
    api.patch(`/chat/rooms/${room.id}`, { topic }).then(reloadRooms).catch(toastError);
  };
  const menu = (e) => showMenu(e.currentTarget, [
    isChannel && room.is_member && { label: 'Edit topic', icon: 'pencil', onSelect: editTopic },
    canManage && { label: 'Rename channel', icon: 'type', onSelect: async () => {
      const name = await promptDialog({ title: 'Rename channel', value: room.name });
      if (name) api.patch(`/chat/rooms/${room.id}`, { name }).then(reloadRooms).catch(toastError);
    } },
    canManage && !room.is_default && { label: room.is_private ? 'Make public' : 'Make private', icon: room.is_private ? 'lock-open' : 'lock',
      onSelect: () => api.patch(`/chat/rooms/${room.id}`, { is_private: !room.is_private }).then(reloadRooms).catch(toastError) },
    room.is_member && { label: room.muted ? 'Unmute' : 'Mute', icon: room.muted ? 'bell' : 'bell-off', hint: room.muted ? null : 'No badge; mentions still notify you',
      onSelect: () => api.post(`/chat/rooms/${room.id}/mute`, { muted: !room.muted }).then(reloadRooms).catch(toastError) },
    { label: 'Copy link', icon: 'link', onSelect: () => navigator.clipboard?.writeText(`${location.origin}/chat/${room.id}`).then(() => toast('Link copied')) },
    isChannel && room.is_member && { divider: true },
    isChannel && room.is_member && { label: 'Leave channel', icon: 'log-out', onSelect: async () => {
      try { await api.post(`/chat/rooms/${room.id}/leave`); reloadRooms(); navigate('/chat'); } catch (err) { toastError(err); }
    } },
    canManage && !room.is_default && { label: 'Archive channel', icon: 'archive', danger: true, onSelect: async () => {
      if (!(await confirmDialog({ title: `Archive #${room.name}?`, message: 'It disappears for everyone. Messages are kept.', danger: true, confirmLabel: 'Archive' }))) return;
      try { await api.patch(`/chat/rooms/${room.id}`, { archived: true }); reloadRooms(); navigate('/chat'); } catch (err) { toastError(err); }
    } },
  ].filter(Boolean));
  const others = room.other_ids || [];
  return html`<header class="page-header chat-head">
    ${mobile ? html`<${IconButton} icon="chevron-left" label="All chats" onClick=${() => navigate('/chat')} />` : html`<${SidebarButton} />`}
    <div class="chat-head-title">
      <div class="chat-head-name">
        ${isChannel ? html`<${Icon} name=${room.is_private ? 'lock' : 'hash'} size=${17} />` : html`<${RoomIcon} r=${room} size=${24} />`}
        <h1 class="page-title">${roomLabel(room)}</h1>
        ${room.muted && html`<${Icon} name="bell-off" size=${14} class="muted" />`}
      </div>
      ${isChannel ? html`<button type="button" class="chat-head-topic" onClick=${room.is_member ? editTopic : undefined}>${room.topic || (room.is_member ? 'Add a topic' : '')}</button>`
    : others.length === 1 && html`<div class="chat-head-topic">${lookupUser(others[0]).title || ''}</div>`}
    </div>
    <div class="page-header-actions">
      ${isChannel && html`<button type="button" class="chat-head-members" onClick=${onShowMembers} aria-label=${`${plural(room.member_count, 'member')} — show`}
        data-tip=${plural(room.member_count, 'member')}><${AvatarStack} users=${room.member_ids} max=${3} size=${22} /></button>`}
      <${IconButton} icon="ellipsis" label="Channel options" onClick=${menu} />
    </div>
  </header>`;
}

function MembersPopover({ room, close, reloadRooms }) {
  const add = (e) => pickUsers(e.currentTarget, {
    multi: false, title: `Add to #${room.name}`, filter: (u) => !room.member_ids.includes(u.id),
    onChange: async (id) => {
      close();
      try { await api.post(`/chat/rooms/${room.id}/members`, { user_ids: [id] }); reloadRooms(); toast(`Added ${lookupUser(id).name}`); } catch (err) { toastError(err); }
    },
  });
  return html`<div class="chat-members">
    <div class="list-picker-title">${plural(room.member_count, 'member')}</div>
    <div class="chat-members-list">
      ${room.member_ids.map((id) => html`<a key=${id} class="chat-member" href=${`/chat/dm/${id}`} onClick=${close}>
        <${Avatar} user=${id} size=${24} online="auto" /><span class="grow">${lookupUser(id).name}</span><span class="muted text-sm">${lookupUser(id).title || ''}</span></a>`)}
    </div>
    ${room.is_member && html`<div class="list-picker-footer"><${Button} size="sm" icon="user-plus" onClick=${add}>Add people</${Button}></div>`}
  </div>`;
}

function RoomView({ roomId, roomsById, route, me, mobile, reloadRooms }) {
  const fallback = useFetch(roomsById[roomId] ? null : `/chat/rooms/${roomId}`, { refetchOn: ['chat.room'] });
  const room = roomsById[roomId] || fallback.data?.room;
  const [state, setState] = useState({ items: [], more: false, loading: true, error: null });
  const [newBelow, setNewBelow] = useState(0);
  const listRef = useRef(null);
  const nearBottom = useRef(true);
  const lastRead = useRef(undefined);
  const highlight = Number(route.query.m) || null;
  const threadId = Number(route.query.thread) || null;
  usePresence(`chat:${roomId}`);

  if (room && lastRead.current === undefined) lastRead.current = room.last_read_at || null;

  const markRead = useCallback(() => {
    if (document.visibilityState !== 'visible') return;
    api.post(`/chat/rooms/${roomId}/read`).catch(() => {});
  }, [roomId]);

  const scrollToBottom = () => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    setNewBelow(0);
  };

  // initial load (latest, or around a linked message)
  useEffect(() => {
    let alive = true;
    setState({ items: [], more: false, loading: true, error: null });
    const query = highlight ? { around: highlight, limit: 60 } : { limit: 50 };
    api.get(`/chat/rooms/${roomId}/messages`, query).then((res) => {
      if (!alive) return;
      setState({ items: res.items, more: res.has_more_before, loading: false, error: null });
      requestAnimationFrame(() => {
        if (highlight) document.getElementById(`m${highlight}`)?.scrollIntoView({ block: 'center' });
        else scrollToBottom();
      });
      markRead();
    }).catch((error) => alive && setState({ items: [], more: false, loading: false, error }));
    return () => { alive = false; };
  }, [roomId]);

  const refreshWindow = async () => {
    const first = state.items[0];
    try {
      const res = await api.get(`/chat/rooms/${roomId}/messages`, first ? { after: first.id - 1, limit: 200 } : { limit: 50 });
      setState((s) => ({ ...s, items: res.items }));
    } catch { /* next event retries */ }
  };

  useEvent('chat.message', async (e) => {
    if (e.room_id !== roomId) return;
    if (e.parent_id || e.edited || e.deleted) { refreshWindow(); return; }
    const last = state.items[state.items.length - 1];
    try {
      const res = await api.get(`/chat/rooms/${roomId}/messages`, last ? { after: last.id, limit: 100 } : { limit: 50 });
      setState((s) => {
        const known = new Set(s.items.map((m) => m.id));
        return { ...s, items: [...s.items, ...res.items.filter((m) => !known.has(m.id))] };
      });
      if (nearBottom.current || e.user_id === me.id) {
        requestAnimationFrame(scrollToBottom);
        markRead();
      } else setNewBelow((n) => n + 1);
    } catch { /* ignore */ }
  }, [roomId, state.items]);
  useEvent('reaction.changed', (e) => setState((s) => ({ ...s, items: applyReactions(s.items, e) })));
  useEvent('reconnected', () => refreshWindow(), [state.items]);

  const loadOlder = async () => {
    const el = listRef.current;
    const first = state.items[0];
    if (!first || !state.more || state.loadingOlder) return;
    setState((s) => ({ ...s, loadingOlder: true }));
    const before = el ? el.scrollHeight : 0;
    try {
      const res = await api.get(`/chat/rooms/${roomId}/messages`, { before: first.id, limit: 50 });
      setState((s) => ({ ...s, items: [...res.items, ...s.items], more: res.has_more_before, loadingOlder: false }));
      requestAnimationFrame(() => { if (el) el.scrollTop = el.scrollHeight - before; });
    } catch { setState((s) => ({ ...s, loadingOlder: false })); }
  };
  const onScroll = (e) => {
    const el = e.currentTarget;
    nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom.current && newBelow) { setNewBelow(0); markRead(); }
    if (el.scrollTop < 120) loadOlder();
  };

  if (!room && (fallback.loading || !fallback.data)) {
    return fallback.error ? html`<div class="chat-main"><${Empty} icon="messages-square" title="Chat not found">It may be private or archived.</${Empty}></div>`
      : html`<div class="chat-main"><${Loading} /></div>`;
  }
  const openThread = (m) => setQuery({ thread: m.id, m: undefined });
  const update = (fn) => setState((s) => ({ ...s, items: fn(s.items) }));
  const blocks = buildBlocks(state.items, lastRead.current, me.id);
  const join = async () => {
    try { await api.post(`/chat/rooms/${roomId}/join`); reloadRooms(); } catch (err) { toastError(err); }
  };
  const showMembers = (e) => showPopover(e.currentTarget, (close) => html`<${MembersPopover} room=${room} close=${close} reloadRooms=${reloadRooms} />`, { width: 300, placement: 'bottom-end' });
  const intro = room.kind === 'channel'
    ? html`<div class="chat-intro"><div class="chat-intro-icon"><${Icon} name=${room.is_private ? 'lock' : 'hash'} size=${22} /></div>
        <h2>Welcome to #${room.name}</h2><p class="muted">${room.topic || 'This is the very beginning of the channel.'}</p></div>`
    : html`<div class="chat-intro"><${RoomIcon} r=${room} size=${48} /><h2>${room.title}</h2>
        <p class="muted">${(room.other_ids || []).includes(me.id) ? 'Jot down notes, links and files for yourself.' : 'This is the start of your direct message history.'}</p></div>`;
  return html`<div class=${cx('chat-main', threadId && 'has-thread')}>
    <div class="chat-room">
      <${RoomHeader} room=${room} me=${me} mobile=${mobile} onShowMembers=${showMembers} reloadRooms=${reloadRooms} />
      <div class="chat-list" ref=${listRef} onScroll=${onScroll}>
        <${ErrorBox} error=${state.error} />
        ${state.loading && html`<${Loading} />`}
        ${!state.loading && !state.more && intro}
        ${state.loadingOlder && html`<div class="center muted text-sm pad">Loading older messages…</div>`}
        ${blocks.map((b) => (b.type === 'day'
    ? html`<div key=${b.key} class="chat-day"><span>${dayLabel(b.at)}</span></div>`
    : b.type === 'unread'
      ? html`<div key="unread" class="chat-unread-divider"><span>New</span></div>`
      : html`<${Message} key=${b.key} m=${b.m} grouped=${b.grouped} room=${room} me=${me} highlight=${highlight === b.m.id}
          onReply=${openThread} onToggleReaction=${(m, emoji) => toggleReaction(m, emoji, update)} />`))}
      </div>
      ${newBelow > 0 && html`<button type="button" class="chat-jump" onClick=${() => { scrollToBottom(); markRead(); }}>
        <${Icon} name="arrow-down" size=${14} /> ${plural(newBelow, 'new message')}</button>`}
      <${TypingLine} roomId=${roomId} />
      ${room.is_member
    ? html`<${Composer} roomId=${roomId} placeholder=${room.kind === 'channel' ? `Message #${room.name}` : `Message ${room.title}`} autofocus=${!mobile} allowShare
          onSent=${() => { nearBottom.current = true; }} />`
    : html`<div class="chat-join"><span>You're viewing <b>#${room.name}</b>.</span><${Button} variant="primary" onClick=${join}>Join channel</${Button}></div>`}
    </div>
    ${threadId && html`<${ThreadPanel} key=${threadId} parentId=${threadId} room=${room} me=${me} highlightId=${highlight}
      onClose=${() => setQuery({ thread: undefined, m: undefined })} />`}
  </div>`;
}

// -- module -------------------------------------------------------------------------

export default function Chat({ route }) {
  const mobile = useIsMobile();
  const me = useStore((s) => s.me);
  const seg = route.segments;
  const isDm = seg[1] === 'dm';
  const roomId = !isDm && Number(seg[1]) ? Number(seg[1]) : null;
  const rooms = useFetch('/chat/rooms', { refetchOn: ['chat.room', 'chat.message', 'chat.read'] });
  const list = rooms.data?.items || [];
  const byId = Object.fromEntries(list.map((r) => [r.id, r]));

  useEffect(() => {
    if (!isDm) return;
    api.post(`/chat/dm/${seg[2]}`).then((res) => navigate(`/chat/${res.room.id}`, { replace: true }))
      .catch((err) => { toastError(err); navigate('/chat', { replace: true }); });
  }, [isDm, seg[2]]);

  useEffect(() => {
    if (roomId) {
      try { localStorage.setItem(LAST_ROOM_KEY, String(roomId)); } catch { /* ignore */ }
      return;
    }
    if (isDm || mobile || !rooms.data) return;
    let last = null;
    try { last = Number(localStorage.getItem(LAST_ROOM_KEY)); } catch { /* ignore */ }
    const target = (last && byId[last]) || list.find((r) => r.is_default) || list[0];
    if (target) navigate(`/chat/${target.id}`, { replace: true });
  }, [roomId, isDm, !!rooms.data]);

  useEffect(() => registerCommands(() => [
    { id: 'chat-new-channel', label: 'New chat channel', icon: 'hash', group: 'Chat', run: openCreateChannel },
    { id: 'chat-new-dm', label: 'New direct message', icon: 'message-square-plus', group: 'Chat', run: openNewMessageModal },
    { id: 'chat-browse', label: 'Browse chat channels', icon: 'search', group: 'Chat', run: openBrowse },
  ]), []);

  const sidebar = html`
    <${SidebarHeader} title="Chat" actions=${html`<${IconButton} icon="square-pen" label="New message" onClick=${openNewMessageModal} />`} />
    ${rooms.error && html`<${ErrorBox} error=${rooms.error} retry=${rooms.reload} />`}
    <${RoomList} rooms=${list} activeId=${roomId} />`;
  let main;
  if (roomId) {
    main = html`<${RoomView} key=${roomId} roomId=${roomId} roomsById=${byId} route=${route} me=${me} mobile=${mobile} reloadRooms=${rooms.reload} />`;
  } else if (mobile) {
    main = html`<div class="chat-mobile-list">
      <header class="page-header"><h1 class="page-title grow">Chat</h1><${IconButton} icon="square-pen" label="New message" onClick=${openNewMessageModal} /></header>
      ${rooms.loading && !rooms.data ? html`<${Loading} />` : html`<${RoomList} rooms=${list} activeId=${null} compact />`}
    </div>`;
  } else {
    main = html`<div class="chat-main"><${Empty} icon="messages-square" title="Team chat">Pick a channel or start a direct message.</${Empty}></div>`;
  }
  return html`<${ModuleLayout} sidebar=${sidebar} class="chat-module">${main}</${ModuleLayout}>`;
}

