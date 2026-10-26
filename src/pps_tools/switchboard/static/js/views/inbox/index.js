// Inbox module (/inbox): sidebar of mailboxes, the conversation list, and the open
// conversation or composer.

import { html, useEffect, useMemo, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch, useIsMobile } from '../../lib/hooks.js';
import { useHotkeys } from '../../lib/shortcuts.js';
import { navigate } from '../../lib/router.js';
import { useStore } from '../../lib/store.js';
import { ModuleLayout, SidebarButton } from '../../ui/layout.js';
import { Button, Checkbox, Icon, IconButton, Loading, SearchInput, Segmented, cx } from '../../ui/components.js';
import { showPopover, toast, toastError } from '../../ui/overlay.js';
import { registerCommands } from '../../ui/palette.js';
import { InboxSidebar, useCounts } from './sidebar.js';
import { ConversationList, BulkBar } from './list.js';
import { ConversationView } from './conversation.js';
import { Composer, scheduledToast } from './composer.js';
import {
  TEAM_VIEWS, act, actWithUndo, conversationPath, mailboxTitle, openAssign, openLabels, openSnooze, parseInboxRoute,
  startDiscussion,
} from './common.js';

const PAGE = 50;

const SEARCH_HELP = [
  ['from:lena', 'Sent by someone (name or address); from:me'],
  ['to:orders@', 'Sent to an address'],
  ['subject:proof', 'Words in the subject'],
  ['label:rush', 'Has a label'],
  ['assignee:me', 'Assigned to me / none / a name'],
  ['is:unread', 'open, closed, unread, starred, snoozed, unassigned, awaiting'],
  ['has:attachment', 'Also has:draft, has:comments'],
  ['channel:sms', 'Channel type or name'],
  ['team:production', 'In a team inbox'],
  ['after:2026-10-01', 'Also before:'],
  ['in:trash', 'Search Trash or Spam'],
];

function searchHelp(anchor) {
  showPopover(anchor, () => html`<div class="search-help">
    <div class="search-help-title">Search tips</div>
    ${SEARCH_HELP.map(([op, text]) => html`<div class="search-help-row"><code>${op}</code><span>${text}</span></div>`)}
    <div class="search-help-foot">Combine operators with words: <code>from:marcus proof is:open</code></div>
  </div>`, { width: 360, placement: 'bottom-end' });
}

function ListHeader({ parsed, route, count, onSearch, searchRef }) {
  const [q, setQ] = useState(route.query.q || '');
  const timer = useRef(null);
  useEffect(() => { if (parsed.mailbox !== 'search') setQ(''); }, [parsed.mailbox]);
  const change = (v) => {
    setQ(v);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => onSearch(v), 300);
  };
  const title = mailboxTitle(parsed);
  return html`<div class="list-header">
    <div class="list-header-top">
      <${SidebarButton} />
      <h1 class="list-title truncate">${title}</h1>
      ${count !== null && count !== undefined && parsed.mailbox !== 'search' && html`<span class="list-count">${count}</span>`}
      <span class="grow"></span>
      <${IconButton} icon="square-pen" label="Compose (C)" onClick=${() => navigate('/inbox/compose')} class="show-mobile" />
    </div>
    <div class="list-search">
      <${SearchInput} value=${q} onValue=${change} placeholder="Search conversations" inputRef=${searchRef}
        onKeyDown=${(e) => { if (e.key === 'Enter') { clearTimeout(timer.current); onSearch(q); } if (e.key === 'Escape') { change(''); e.currentTarget.blur(); } }} />
      <${IconButton} icon="help" label="Search tips" size="sm" onClick=${(e) => searchHelp(e.currentTarget)} />
    </div>
    ${parsed.teamId && html`<div class="list-tabs">
      <${Segmented} size="sm" value=${parsed.teamView || 'open'}
        options=${TEAM_VIEWS.map((v) => ({ value: v.id, label: v.label }))}
        onChange=${(v) => navigate(`/inbox/team/${parsed.teamId}${v === 'open' ? '' : '/' + v}`)} />
    </div>`}
    ${parsed.labelId && html`<div class="list-tabs">
      <${Checkbox} checked=${route.query.closed === '1'} label="Include closed"
        onChange=${(v) => navigate(parsed.base, { query: v ? { closed: '1' } : {} })} />
    </div>`}
  </div>`;
}

function ComposePage({ route, onDone }) {
  const draftId = Number(route.query.draft) || null;
  const [draft, setDraft] = useState(draftId ? undefined : null);
  useEffect(() => {
    if (!draftId) { setDraft(null); return; }
    api.get(`/drafts/${draftId}`).then((r) => setDraft(r.draft)).catch((err) => { toastError(err); setDraft(null); });
  }, [draftId]);
  if (draft === undefined) return html`<${Loading} />`;
  const prefill = {
    to: route.query.to ? [{ name: null, handle: route.query.to }] : [],
    subject: route.query.subject || '',
    channel_id: route.query.channel ? Number(route.query.channel) : null,
  };
  return html`<div class="compose-page">
    <${Composer}
      key=${draftId || 'new'}
      initialDraft=${draft}
      initialFields=${draft ? null : prefill}
      presetType=${route.query.type}
      variant="page"
      onClose=${(info) => { if (!info || !info.sent) onDone(); }}
      onSent=${(res, opts) => {
        navigate(`/inbox/c/${res.conversation_id}`);
        scheduledToast(res, opts, async () => {
          try {
            const r = await api.post(`/messages/${res.message_id}/cancel`);
            navigate(r.draft.conversation_id ? `/inbox/c/${r.draft.conversation_id}` : `/inbox/compose?draft=${r.draft.id}`);
          } catch (err) { toastError(err); }
        });
      }}
    />
  </div>`;
}

export default function Inbox({ route }) {
  const parsed = parseInboxRoute(route);
  const mobile = useIsMobile();
  const [selection, setSelection] = useState(new Set());
  const [limit, setLimit] = useState(PAGE);
  const searchRef = useRef(null);
  const q = parsed.mailbox === 'search' ? route.query.q || '' : '';
  const listKey = parsed.mailbox + '|' + q + '|' + (route.query.closed || '');

  useEffect(() => { setSelection(new Set()); setLimit(PAGE); }, [listKey]);

  const query = parsed.mailbox === 'search'
    ? { mailbox: 'all', q, limit }
    : { mailbox: parsed.mailbox, limit, include_closed: route.query.closed === '1' };
  const listPath = parsed.mailbox === 'search' && !q ? null : '/conversations';
  const { data, loading, error } = useFetch(listPath, { query, refetchOn: ['conversation.changed', 'settings.changed'] });
  const { data: draftData } = useFetch(parsed.mailbox === 'drafts' ? '/drafts' : null, { refetchOn: ['draft.changed'] });
  const { data: counts } = useCounts();
  const items = listPath ? data?.items || null : [];
  const openId = parsed.conversationId;

  // Drop selected ids that left the list.
  useEffect(() => {
    if (!items || !selection.size) return;
    const ids = new Set(items.map((c) => c.id));
    const next = new Set([...selection].filter((id) => ids.has(id)));
    if (next.size !== selection.size) setSelection(next);
  }, [items]);

  const countForHeader = useMemo(() => {
    if (!counts) return null;
    if (parsed.mailbox === 'inbox') return counts.inbox;
    if (parsed.mailbox === 'assigned') return counts.assigned;
    if (parsed.teamId && (parsed.teamView || 'open') === 'open') return counts.teams?.[parsed.teamId]?.open || 0;
    if (parsed.teamId && parsed.teamView === 'unassigned') return counts.teams?.[parsed.teamId]?.unassigned || 0;
    return items ? items.length : null;
  }, [counts, items, parsed.mailbox, parsed.teamId, parsed.teamView]);

  const open = (c) => navigate(conversationPath(parsed.base, c.id) + (route.search || ''));
  const back = () => navigate(parsed.base + (route.search || ''));
  const advance = (fromId) => {
    if (!items || mobile) { back(); return; }
    const idx = items.findIndex((c) => c.id === fromId);
    const next = items[idx + 1] || items[idx - 1];
    if (next && next.id !== fromId) open(next); else back();
  };
  const onSearch = (value) => {
    const v = value.trim();
    if (v) navigate('/inbox/search', { replace: parsed.mailbox === 'search', query: { q: v } });
    else if (parsed.mailbox === 'search') navigate('/inbox');
  };

  // Keyboard: list navigation and actions on the selection (or the open conversation).
  const targets = () => {
    if (selection.size) return items.filter((c) => selection.has(c.id));
    const c = items && items.find((x) => x.id === openId);
    return c ? [c] : [];
  };
  const move = (delta) => {
    if (!items || !items.length) return;
    const idx = items.findIndex((c) => c.id === openId);
    const next = items[Math.max(0, Math.min(items.length - 1, idx === -1 ? 0 : idx + delta))];
    if (next) open(next);
  };
  const withTargets = (fn) => () => { const t = targets(); if (t.length) fn(t); };
  const anchor = () => document.querySelector('.conv-actions') || document.querySelector('.bulk-bar') || document.querySelector('.list-header');
  useHotkeys({
    j: () => move(1),
    k: () => move(-1),
    arrowdown: () => move(1),
    arrowup: () => move(-1),
    x: () => { if (!openId) return; const next = new Set(selection); next.has(openId) ? next.delete(openId) : next.add(openId); setSelection(next); },
    e: withTargets((t) => {
      const reopen = t.every((c) => c.status === 'closed');
      actWithUndo(t.map((c) => c.id), reopen ? 'reopen' : 'close').then(() => { if (!reopen && !selection.size) advance(t[0].id); setSelection(new Set()); });
    }),
    s: withTargets((t) => act(t.map((c) => c.id), t.every((c) => c.starred) ? 'unstar' : 'star')),
    h: withTargets((t) => openSnooze(anchor(), t.map((c) => c.id), { onDone: () => { setSelection(new Set()); if (t.length === 1) advance(t[0].id); } })),
    a: withTargets((t) => openAssign(anchor(), t)),
    l: withTargets((t) => openLabels(anchor(), t)),
    '#': withTargets((t) => actWithUndo(t.map((c) => c.id), 'trash').then(() => { setSelection(new Set()); if (t.length === 1) advance(t[0].id); })),
    '!': withTargets((t) => actWithUndo(t.map((c) => c.id), 'spam').then(() => { setSelection(new Set()); if (t.length === 1) advance(t[0].id); })),
    'shift+u': withTargets((t) => act(t.map((c) => c.id), 'unread').then(() => toast('Marked as unread'))),
    'shift+i': withTargets((t) => act(t.map((c) => c.id), 'read')),
    '/': () => searchRef.current && searchRef.current.focus(),
    c: () => navigate('/inbox/compose'),
  });

  useEffect(() => registerCommands((qq) => [
    { id: 'compose', label: 'Compose new message', icon: 'square-pen', group: 'Inbox', shortcut: 'C', run: () => navigate('/inbox/compose') },
    { id: 'compose-sms', label: 'New text message', icon: 'smartphone', group: 'Inbox', run: () => navigate('/inbox/compose?type=sms') },
    { id: 'discussion', label: 'New internal discussion', icon: 'messages-square', group: 'Inbox', run: startDiscussion },
    { id: 'assigned', label: 'Assigned to me', icon: 'user-check', group: 'Inbox', run: () => navigate('/inbox/assigned') },
    ...(qq && qq.length > 1 ? [{ id: 'search-inbox', label: `Search inbox for “${qq}”`, icon: 'search', group: 'Inbox', run: () => navigate('/inbox/search', { query: { q: qq } }) }] : []),
  ]), []);

  const detailPane = parsed.compose
    ? html`<${ComposePage} route=${route} onDone=${() => navigate('/inbox')} />`
    : openId
      ? html`<${ConversationView} key=${openId} id=${openId} onBack=${back} onAdvance=${advance} listItems=${items} />`
      : html`<div class="conv-placeholder">
          <div class="conv-placeholder-art"><${Icon} name="inbox" size=${36} strokeWidth=${1.4} /></div>
          <div class="conv-placeholder-title">${items && items.length ? 'Select a conversation' : 'Nothing selected'}</div>
          <div class="conv-placeholder-keys"><kbd class="kbd">J</kbd><kbd class="kbd">K</kbd> to move · <kbd class="kbd">C</kbd> to compose · <kbd class="kbd">?</kbd> for shortcuts</div>
          <div class="row mt-3"><${Button} icon="square-pen" onClick=${() => navigate('/inbox/compose')}>Compose</${Button}></div>
        </div>`;

  const showDetail = !!(openId || parsed.compose);
  return html`<${ModuleLayout} sidebar=${html`<${InboxSidebar} parsed=${parsed} />`} class="inbox-module">
    <div class=${cx('inbox-panes', showDetail && 'has-detail')}>
      <section class="inbox-list-pane" aria-label="Conversation list">
        ${selection.size > 0
    ? html`<${BulkBar} items=${items || []} selection=${selection} setSelection=${setSelection} mailbox=${parsed.mailbox} />`
    : html`<${ListHeader} parsed=${parsed} route=${route} count=${countForHeader} onSearch=${onSearch} searchRef=${searchRef} />`}
        ${parsed.mailbox === 'search' && !q
    ? html`<div class="search-empty">Type to search every conversation you can see. Press <kbd class="kbd">?</kbd> next to the box for operators.</div>`
    : html`<${ConversationList}
            items=${items}
            loading=${loading}
            error=${error}
            parsed=${parsed}
            openId=${openId}
            onOpen=${open}
            selection=${selection}
            setSelection=${setSelection}
            hasMore=${!!(data && data.next) && limit < 200}
            onLoadMore=${() => setLimit((l) => Math.min(200, l + PAGE))}
            newDrafts=${parsed.mailbox === 'drafts' ? draftData?.items : null}
          />`}
      </section>
      <section class="inbox-detail-pane">${detailPane}</section>
    </div>
  </${ModuleLayout}>`;
}
