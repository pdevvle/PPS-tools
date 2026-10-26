// "My day" widget: what's waiting in my inbox.

import { html } from '../../lib/preact.js';
import { useFetch } from '../../lib/hooks.js';
import { Card, Empty, Icon, Loading, RelTime, Button, cx } from '../../ui/components.js';
import { navigate } from '../../lib/router.js';
import { conversationTitle, participantLabel, channelIcon } from './common.js';

export function InboxWidget() {
  const { data: counts } = useFetch('/counts', { refetchOn: ['conversation.changed', 'badges.changed'] });
  const { data } = useFetch('/conversations', { query: { mailbox: 'inbox', limit: 6 }, refetchOn: ['conversation.changed'] });
  const items = data?.items;
  return html`<${Card} title="Inbox" icon="inbox"
    actions=${html`<${Button} size="sm" variant="ghost" onClick=${() => navigate('/inbox')}>Open</${Button}>`}>
    ${counts && html`<div class="inbox-widget-stats">
      <a href="/inbox" class="inbox-widget-stat"><span class="inbox-widget-num">${counts.inbox_unread}</span><span>unread</span></a>
      <a href="/inbox/assigned" class="inbox-widget-stat"><span class="inbox-widget-num">${counts.assigned}</span><span>assigned to you</span></a>
      <a href="/inbox/drafts" class="inbox-widget-stat"><span class="inbox-widget-num">${counts.drafts}</span><span>drafts</span></a>
    </div>`}
    ${!items ? html`<${Loading} />` : !items.length
    ? html`<${Empty} icon="check-check" title="Inbox zero" compact>Nothing is waiting on you.</${Empty}>`
    : html`<div class="widget-list">
        ${items.map((c) => html`<a key=${c.id} href=${`/inbox/c/${c.id}`} class=${cx('widget-row', c.unread && 'is-unread')}>
          <${Icon} name=${channelIcon(c.channel)} size=${14} class="muted" />
          <span class="truncate grow"><b>${participantLabel(c)}</b> <span class="muted">${conversationTitle(c) !== participantLabel(c) ? conversationTitle(c) : c.preview}</span></span>
          <${RelTime} value=${c.last_activity_at} class="muted text-sm" />
        </a>`)}
      </div>`}
  </${Card}>`;
}
