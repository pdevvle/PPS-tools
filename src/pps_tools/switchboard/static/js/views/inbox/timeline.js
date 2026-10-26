// Conversation timeline: emails, texts/chats, internal comments, events and drafts.

import { html, useLayoutEffect, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useStore, user as lookupUser, setting, boot } from '../../lib/store.js';
import { fmtBytes, fmtDateTime, fmtFull, fmtTime, fmtUntil, fmtDate, participantName } from '../../lib/format.js';
import { isToday, isSameDay, addDays } from '../../lib/dates.js';
import { Avatar, Button, Chip, Icon, IconButton, RelTime, cx } from '../../ui/components.js';
import { showMenu, confirmDialog, toastError } from '../../ui/overlay.js';
import { pickEmoji } from '../../ui/pickers.js';
import { RichEditor, RichText } from '../../ui/editor.js';
import { colorFor } from './list.js';

// -- email body -----------------------------------------------------------------------

const QUOTE_SELECTORS = '.gmail_quote, blockquote[type="cite"], .yahoo_quoted, .moz-cite-prefix + blockquote, div[id^="divRplyFwdMsg"], #appendonsend';

function withInlineImages(markup, attachments) {
  if (!markup) return '';
  const byCid = {};
  for (const a of attachments || []) if (a.content_id) byCid[a.content_id.replace(/[<>]/g, '')] = a.url;
  return markup.replace(/(src=["'])cid:([^"']+)(["'])/gi, (m, pre, cid, post) => (byCid[cid] ? `${pre}${byCid[cid]}${post}` : m));
}

function srcdoc(markup, allowImages) {
  const remote = allowImages ? 'https: http: ' : '';
  const csp = `default-src 'none'; img-src ${remote}data: ${location.origin}; style-src 'unsafe-inline' ${allowImages ? 'https:' : ''}; font-src ${remote}data:; media-src ${remote}`;
  return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<base target="_blank">
<style>
html,body{margin:0;padding:0;background:#fff;color:#1d2433}
body{font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;overflow-wrap:anywhere;padding:1px 0 2px;overflow-x:auto;overflow-y:hidden}
img{max-width:100%;height:auto}p{margin:0 0 .75em}a{color:#3250c7}
blockquote{margin:.4em 0 .4em .3em;padding-left:.8em;border-left:3px solid #d5d9e0;color:#555e70}
pre{white-space:pre-wrap}table{max-width:100%}
.sb-quote-toggle{display:inline-flex;align-items:center;margin:6px 0;padding:0 9px;height:18px;border:1px solid #d5d9e0;border-radius:9px;background:#f3f4f7;color:#556;font:700 13px/1 sans-serif;letter-spacing:2px;cursor:pointer}
.sb-quote-toggle:hover{background:#e8eaef}.sb-hidden{display:none!important}.sb-signature{color:#555e70}
</style></head><body>${markup}</body></html>`;
}

function collapseQuotes(doc) {
  const first = doc.querySelector(QUOTE_SELECTORS);
  if (!first) return;
  let hidden = [first];
  if (first.id === 'appendonsend' || (first.id || '').startsWith('divRplyFwdMsg')) {
    hidden = [];
    for (let n = first; n; n = n.nextElementSibling) hidden.push(n);
  }
  const prefix = first.previousElementSibling;
  if (prefix && /wrote:\s*$/i.test(prefix.textContent || '') && prefix.textContent.length < 300) hidden.unshift(prefix);
  hidden.forEach((el) => el.classList.add('sb-hidden'));
  const toggle = doc.createElement('button');
  toggle.className = 'sb-quote-toggle';
  toggle.type = 'button';
  toggle.title = 'Show quoted text';
  toggle.textContent = '•••';
  toggle.addEventListener('click', () => hidden.forEach((el) => el.classList.toggle('sb-hidden')));
  hidden[0].parentNode.insertBefore(toggle, hidden[0]);
}

export function EmailFrame({ markup, attachments }) {
  const blockSetting = setting('inbox.block_remote_images', false);
  const hasRemote = /<img[^>]+src=["']https?:/i.test(markup || '') || /url\(\s*['"]?https?:/i.test(markup || '');
  const [allowImages, setAllowImages] = useState(!blockSetting);
  const ref = useRef(null);
  const resize = () => {
    const f = ref.current;
    if (!f || !f.contentDocument || !f.contentDocument.body) return;
    const h = Math.max(f.contentDocument.documentElement.scrollHeight, f.contentDocument.body.scrollHeight);
    f.style.height = h + 'px';
  };
  const onLoad = () => {
    const f = ref.current;
    if (!f || !f.contentDocument) return;
    collapseQuotes(f.contentDocument);
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(f.contentDocument.body);
    f.contentDocument.querySelectorAll('img').forEach((img) => img.addEventListener('load', resize));
    f.contentDocument.addEventListener('click', () => setTimeout(resize, 0));
  };
  const doc = srcdoc(withInlineImages(markup, attachments), allowImages);
  return html`<div class="email-body">
    ${!allowImages && hasRemote && html`<div class="email-images-blocked"><${Icon} name="image" size=${14} /> Remote images are hidden.
      <button type="button" class="btn-link" onClick=${() => setAllowImages(true)}>Show images</button></div>`}
    <iframe ref=${ref} class="email-frame" title="Message" sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
      srcdoc=${doc} onLoad=${onLoad} scrolling="no"></iframe>
  </div>`;
}

// -- attachments ----------------------------------------------------------------------

function fileIcon(a) {
  if (a.content_type === 'application/pdf') return 'file-text';
  if (/spreadsheet|excel|csv/.test(a.content_type)) return 'file-spreadsheet';
  if (a.is_image) return 'image';
  return 'file';
}

export function Attachments({ items, onRemove }) {
  const list = (items || []).filter((a) => !a.is_inline);
  if (!list.length) return null;
  const images = list.filter((a) => a.is_image && !onRemove);
  const files = list.filter((a) => !(a.is_image && !onRemove));
  return html`<div class="stack-sm">
    ${images.length > 0 && html`<div class="image-attachments">
      ${images.map((a) => html`<a key=${a.id} class="image-attachment" href=${a.url} target="_blank" rel="noopener" title=${a.filename}>
        <img src=${a.url} alt=${a.filename} loading="lazy" />
      </a>`)}
    </div>`}
    ${files.length > 0 && html`<div class="attachments">
      ${files.map((a) => html`<a key=${a.id} class="attachment" href=${a.url} target="_blank" rel="noopener" title=${a.filename}>
        ${a.is_image ? html`<img class="attachment-thumb" src=${a.url} alt="" />` : html`<span class="attachment-icon"><${Icon} name=${fileIcon(a)} size=${15} /></span>`}
        <span class="stack-0"><span class="attachment-name">${a.filename}</span><span class="attachment-size">${fmtBytes(a.size)}</span></span>
        ${onRemove && html`<button type="button" class="attachment-remove" aria-label=${`Remove ${a.filename}`}
          onClick=${(e) => { e.preventDefault(); onRemove(a); }}><${Icon} name="x" size=${13} /></button>`}
      </a>`)}
    </div>`}
  </div>`;
}

// -- messages -------------------------------------------------------------------------

function recipients(m) {
  const to = (m.to || []).map(participantName).filter(Boolean);
  const cc = (m.cc || []).map(participantName).filter(Boolean);
  let s = to.length ? `to ${to.join(', ')}` : '';
  if (cc.length) s += `${s ? ', ' : ''}cc ${cc.join(', ')}`;
  return s;
}

function StatusChip({ m, onCancel, onRetry }) {
  if (m.status === 'scheduled') {
    const soon = m.scheduled_at && new Date(m.scheduled_at) - Date.now() < 60000;
    return html`<span class="msg-status">
      <${Chip} size="sm" tone=${soon ? 'warn' : 'purple'} icon="clock">${soon ? 'Sending…' : `Scheduled ${fmtUntil(m.scheduled_at)}`}</${Chip}>
      ${onCancel && html`<button type="button" class="btn-link text-sm" onClick=${() => onCancel(m)}>${soon ? 'Undo' : 'Cancel'}</button>`}
    </span>`;
  }
  if (m.status === 'sending') return html`<${Chip} size="sm" tone="warn" icon="send">Sending…</${Chip}>`;
  if (m.status === 'failed') {
    return html`<span class="msg-status" title=${m.error}>
      <${Chip} size="sm" tone="danger" icon="circle-alert">Not sent</${Chip}>
      ${onRetry && html`<button type="button" class="btn-link text-sm" onClick=${() => onRetry(m)}>Retry</button>`}
    </span>`;
  }
  if (m.opened_at) return html`<span title=${`Opened ${fmtDateTime(m.opened_at)}`}><${Icon} name="check-check" size=${14} class="ic-opened" /></span>`;
  if (m.status === 'delivered' || m.status === 'read') return html`<span title=${m.status}><${Icon} name="check-check" size=${14} class="ic-delivered" /></span>`;
  return null;
}

function messageMenu(e, m, handlers) {
  const items = [];
  if (m.kind === 'email') {
    items.push({ label: 'Reply', icon: 'reply', onSelect: () => handlers.reply(m, 'reply') });
    items.push({ label: 'Reply all', icon: 'reply-all', onSelect: () => handlers.reply(m, 'reply_all') });
    items.push({ label: 'Forward', icon: 'forward', onSelect: () => handlers.reply(m, 'forward') });
  }
  items.push({ label: 'Copy text', icon: 'copy', onSelect: () => navigator.clipboard?.writeText(m.body_text || '') });
  if (m.has_raw) items.push({ label: 'View original', icon: 'code', onSelect: () => window.open(`/api/messages/${m.id}/raw`, '_blank') });
  showMenu(e.currentTarget, items, { placement: 'bottom-end' });
}

export function MessageCard({ m, expanded, onToggle, handlers }) {
  const outbound = m.direction === 'out';
  const author = outbound ? lookupUser(m.author_id) : null;
  const channel = boot('channels').find((c) => c.id === m.channel_id);
  const name = outbound ? (author?.id ? author.name : m.from_name) : (m.from_name || m.from_handle);
  const avatar = outbound
    ? html`<${Avatar} user=${author?.id ? author : null} name=${name} size=${32} />`
    : html`<${Avatar} name=${name} color=${colorFor(m.contact_id)} size=${32} title=${false} />`;
  if (!expanded) {
    return html`<div class=${cx('msg-card', 'is-collapsed', outbound && 'is-outbound')} onClick=${onToggle} role="button" tabIndex="0">
      ${avatar}
      <span class="msg-collapsed-from">${name}</span>
      <span class="msg-collapsed-snippet truncate">${m.snippet}</span>
      ${(m.attachments || []).some((a) => !a.is_inline) && html`<${Icon} name="paperclip" size=${13} class="muted" />`}
      <${RelTime} value=${m.at} class="msg-time" />
    </div>`;
  }
  return html`<article class=${cx('msg-card', outbound && 'is-outbound', m.status === 'failed' && 'is-failed')} data-message-id=${m.id}>
    <header class="msg-header" onClick=${onToggle}>
      ${avatar}
      <div class="msg-head-text">
        <div class="msg-from">
          <span class="msg-from-name">${name}</span>
          ${!outbound && m.from_handle && m.from_handle !== name && html`<span class="msg-from-handle">${m.from_handle}</span>`}
          ${outbound && channel && html`<span class="msg-from-handle">via ${channel.name}</span>`}
          ${m.is_auto && html`<${Chip} size="sm" tone="muted">Automatic</${Chip}>`}
          <${StatusChip} m=${m} onCancel=${handlers.cancel} onRetry=${handlers.retry} />
        </div>
        <div class="msg-to truncate">${recipients(m)}</div>
      </div>
      <time class="msg-time" title=${fmtFull(m.at)}>${fmtDateTime(m.at)}</time>
      <div class="msg-actions" onClick=${(e) => e.stopPropagation()}>
        ${m.kind === 'email' && html`<${IconButton} icon="reply" size="sm" label="Reply" onClick=${() => handlers.reply(m, 'reply')} />`}
        <${IconButton} icon="ellipsis" size="sm" label="More" onClick=${(e) => messageMenu(e, m, handlers)} />
      </div>
    </header>
    ${m.subject && m.kind === 'email' && m.showSubject && html`<div class="msg-subject">${m.subject}</div>`}
    <div class="msg-body">
      ${m.body_html ? html`<${EmailFrame} markup=${m.body_html} attachments=${m.attachments} />` : html`<div class="msg-text">${m.body_text}</div>`}
    </div>
    ${m.attachments && m.attachments.length > 0 && html`<div class="msg-attachments"><${Attachments} items=${m.attachments} /></div>`}
  </article>`;
}

export function ChatBubble({ m, handlers }) {
  const outbound = m.direction === 'out';
  const author = outbound ? lookupUser(m.author_id) : null;
  const name = outbound ? (author?.id ? author.name : m.from_name) : (m.from_name || m.from_handle || 'Visitor');
  return html`<div class=${cx('bubble-row', outbound && 'is-outbound')} data-message-id=${m.id}>
    ${!outbound && html`<${Avatar} name=${name} color=${colorFor(m.contact_id)} size=${28} title=${false} />`}
    <div class="bubble-wrap">
      <div class="bubble-meta">${name} · <time title=${fmtFull(m.at)}>${fmtTime(m.at)}</time> <${StatusChip} m=${m} onCancel=${handlers.cancel} onRetry=${handlers.retry} /></div>
      <div class="bubble">${m.kind === 'chat' && m.body_html ? html`<${RichText} html=${m.body_html} />` : html`<span class="msg-text">${m.body_text}</span>`}</div>
      ${m.attachments && m.attachments.length > 0 && html`<${Attachments} items=${m.attachments} />`}
    </div>
    ${outbound && html`<${Avatar} user=${author?.id ? author : null} name=${name} size=${28} />`}
  </div>`;
}

// -- comments -------------------------------------------------------------------------

function Reactions({ c }) {
  const me = useStore((s) => s.me);
  const toggle = (emoji) => api.post('/reactions', { target_type: 'comment', target_id: c.id, emoji }).catch(toastError);
  if (!c.reactions || !c.reactions.length) return null;
  return html`<div class="reactions">
    ${c.reactions.map((r) => html`<button type="button" key=${r.emoji} class=${cx('reaction', r.user_ids.includes(me.id) && 'is-mine')}
      title=${r.user_ids.map((id) => lookupUser(id).name).join(', ')} onClick=${() => toggle(r.emoji)}>
      <span>${r.emoji}</span><span class="reaction-count">${r.user_ids.length}</span>
    </button>`)}
  </div>`;
}

export function CommentItem({ c, onChanged }) {
  const me = useStore((s) => s.me);
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(c.body);
  const author = lookupUser(c.user_id);
  const mine = c.user_id === me.id;
  const save = async () => {
    try {
      await api.patch(`/comments/${c.id}`, { body });
      setEditing(false);
      onChanged && onChanged();
    } catch (err) { toastError(err); }
  };
  const remove = async () => {
    if (!(await confirmDialog({ title: 'Delete comment?', danger: true, confirmLabel: 'Delete' }))) return;
    api.del(`/comments/${c.id}`).then(onChanged).catch(toastError);
  };
  const react = (e) => pickEmoji(e.currentTarget, {
    onPick: (emoji) => api.post('/reactions', { target_type: 'comment', target_id: c.id, emoji }).catch(toastError),
  });
  return html`<div class="comment" data-comment-id=${c.id}>
    <${Avatar} user=${author} size=${28} />
    <div class="comment-main">
      <div class="comment-head">
        <span class="comment-author">${author.name}</span>
        <time class="comment-time" title=${fmtFull(c.at)}>${fmtTime(c.at)}</time>
        ${c.edited_at && html`<span class="comment-edited">edited</span>`}
      </div>
      ${editing
    ? html`<div class="comment-edit">
          <${RichEditor} value=${body} onChange=${setBody} toolbar=${false} mentions autofocus onSubmit=${save} onEscape=${() => setEditing(false)} />
          <div class="row gap-1"><${Button} size="sm" variant="primary" onClick=${save}>Save</${Button}><${Button} size="sm" variant="ghost" onClick=${() => setEditing(false)}>Cancel</${Button}></div>
        </div>`
    : html`<div class="comment-bubble"><${RichText} html=${c.body} /></div>`}
      ${c.attachments && c.attachments.length > 0 && html`<${Attachments} items=${c.attachments} />`}
      <${Reactions} c=${c} />
    </div>
    <div class="comment-actions">
      <${IconButton} icon="smile-plus" size="sm" label="React" onClick=${react} />
      ${mine && html`<${IconButton} icon="pencil" size="sm" label="Edit" onClick=${() => { setBody(c.body); setEditing(true); }} />`}
      ${(mine || me.role === 'owner' || me.role === 'admin') && html`<${IconButton} icon="trash" size="sm" label="Delete" onClick=${remove} />`}
    </div>
  </div>`;
}

// -- events ---------------------------------------------------------------------------

function names(ids) {
  return (ids || []).map((id) => lookupUser(id).name).join(', ');
}

function labelChips(ids) {
  const labels = boot('labels');
  return (ids || []).map((id) => labels.find((l) => l.id === id)).filter(Boolean)
    .map((l) => html`<${Chip} key=${l.id} size="sm" color=${l.color}>${l.name}</${Chip}>`);
}

const EVENT_ICONS = {
  assigned: 'user-check', unassigned: 'user-x', closed: 'archive', reopened: 'inbox', snoozed: 'alarm-clock',
  unsnoozed: 'alarm-clock', labeled: 'tag', unlabeled: 'tag', moved_team: 'users-round', priority: 'flag',
  renamed: 'pencil', spam: 'octagon-alert', not_spam: 'inbox', trashed: 'trash', restored: 'archive-restore',
  merged: 'git-merge', reminder_set: 'bell', reminder: 'bell-ring', discussion_started: 'messages-square',
  rule_applied: 'zap', task_created: 'square-check-big',
};

const RULE_ACTIONS = {
  assign: 'assigned', unassign: 'unassigned', add_label: 'labeled', remove_label: 'removed a label', move_team: 'moved team',
  close: 'closed', snooze: 'snoozed', priority: 'set priority', spam: 'marked spam', trash: 'trashed',
  auto_reply: 'sent an auto-reply', add_comment: 'added a note', forward: 'forwarded', notify: 'notified people',
  webhook: 'called a webhook', stop: '',
};

function eventText(e, teams) {
  const who = e.user_id ? lookupUser(e.user_id).name : null;
  const d = e.data || {};
  switch (e.event) {
    case 'assigned': return who ? html`<b>${who}</b> assigned <b>${names(d.user_ids)}</b>` : html`Auto-assigned to <b>${names(d.user_ids)}</b>`;
    case 'unassigned': return html`<b>${who || 'Switchboard'}</b> unassigned <b>${names(d.user_ids)}</b>`;
    case 'closed': return html`<b>${who || 'Switchboard'}</b> closed the conversation`;
    case 'reopened': return html`<b>${who || 'Switchboard'}</b> reopened the conversation`;
    case 'snoozed': return html`<b>${who}</b> snoozed until ${fmtDateTime(d.until)}`;
    case 'unsnoozed': return d.by_timer ? 'Snooze ended' : html`<b>${who}</b> unsnoozed`;
    case 'labeled': return html`<b>${who || 'Switchboard'}</b> added ${labelChips(d.label_ids)}`;
    case 'unlabeled': return html`<b>${who || 'Switchboard'}</b> removed ${labelChips(d.label_ids)}`;
    case 'moved_team': {
      const team = d.to ? teams[d.to] : null;
      return html`<b>${who || 'Switchboard'}</b> moved this to ${team ? html`<b>${team.name}</b>` : d.to ? 'another team' : 'no team'}`;
    }
    case 'priority': return html`<b>${who || 'Switchboard'}</b> set priority to <b>${d.value}</b>`;
    case 'renamed': return html`<b>${who}</b> renamed this to “${d.to}”`;
    case 'spam': return html`<b>${who || 'Switchboard'}</b> marked this as spam${d.blocked ? ' and blocked the sender' : ''}`;
    case 'not_spam': return html`<b>${who}</b> marked this as not spam`;
    case 'trashed': return html`<b>${who}</b> moved this to Trash`;
    case 'restored': return html`<b>${who}</b> restored this from Trash`;
    case 'merged': return html`<b>${who}</b> merged “${d.subject || 'another conversation'}” into this one`;
    case 'reminder_set': return html`<b>${who}</b> set a reminder for ${fmtDateTime(d.at)}${d.condition === 'no_reply' ? ' if no one replies' : ''}`;
    case 'reminder': return html`Reminder for <b>${who}</b>${d.note ? `: ${d.note}` : ''}`;
    case 'discussion_started': return html`<b>${who}</b> started this discussion`;
    case 'rule_applied': {
      const did = (d.actions || []).map((a) => RULE_ACTIONS[a] || a.replace(/_/g, ' ')).filter(Boolean);
      return html`Rule <b>${d.name || ''}</b> ran${did.length ? `: ${[...new Set(did)].join(', ')}` : ''}`;
    }
    case 'task_created': return html`<b>${who}</b> added a task: ${d.title || ''}`;
    default: return html`${who ? html`<b>${who}</b> ` : ''}${String(e.event).replace(/_/g, ' ')}`;
  }
}

export function EventLine({ e }) {
  const teams = useStore((s) => s.teamsById);
  return html`<div class="event-line">
    <${Icon} name=${EVENT_ICONS[e.event] || 'activity'} size=${13} />
    <span class="event-text">${eventText(e, teams)}</span>
    <${RelTime} value=${e.at} mode="ago" class="event-time" />
  </div>`;
}

export function DaySeparator({ at }) {
  const d = new Date(at);
  const label = isToday(d) ? 'Today' : isSameDay(d, addDays(new Date(), -1)) ? 'Yesterday' : fmtDate(d, { weekday: true });
  return html`<div class="day-separator"><span>${label}</span></div>`;
}

export function useAutoScroll(dep) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [dep]);
  return ref;
}

