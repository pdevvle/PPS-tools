// Inbox navigation: compose, mailboxes, team inboxes, labels.

import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useStore, can } from '../../lib/store.js';
import { useFetch } from '../../lib/hooks.js';
import { navigate } from '../../lib/router.js';
import { SidebarHeader, SidebarSection, SidebarItem } from '../../ui/layout.js';
import { Button, Icon, IconButton } from '../../ui/components.js';
import { showMenu, toastError, promptDialog, confirmDialog } from '../../ui/overlay.js';
import { pickColor } from '../../ui/pickers.js';
import { MAILBOXES, TEAM_VIEWS, act, startDiscussion } from './common.js';

const PRIMARY = ['inbox', 'assigned', 'starred', 'snoozed', 'drafts', 'scheduled', 'sent'];
const MORE = ['all', 'closed', 'spam', 'trash'];

export function useCounts() {
  return useFetch('/counts', { refetchOn: ['conversation.changed', 'badges.changed', 'draft.changed'] });
}

function TeamItem({ team, counts, active }) {
  const [open, setOpen] = useState(active);
  const c = counts?.teams?.[team.id] || {};
  const base = `/inbox/team/${team.id}`;
  return html`<div class="sidebar-tree">
    <${SidebarItem}
      href=${base}
      color=${team.color}
      label=${team.name}
      count=${c.unassigned || 0}
      countTone=${c.unassigned ? 'accent' : undefined}
      title=${`${c.open || 0} open, ${c.unassigned || 0} unassigned`}
      trailing=${html`<button type="button" class="sidebar-expand" aria-label=${open ? 'Collapse' : 'Expand'}
        onClick=${(e) => { e.preventDefault(); e.stopPropagation(); setOpen(!open); }}>
        <${Icon} name=${open ? 'chevron-down' : 'chevron-right'} size=${13} /></button>`}
      exact
    />
    ${open && TEAM_VIEWS.filter((v) => v.id !== 'open').map((v) => html`<${SidebarItem}
      key=${v.id} href=${`${base}/${v.id}`} label=${v.label} indent=${1} exact
      count=${v.id === 'unassigned' ? c.unassigned : v.id === 'assigned' ? Math.max(0, (c.open || 0) - (c.unassigned || 0)) : undefined}
    />`)}
  </div>`;
}

function labelMenu(e, label) {
  e.preventDefault();
  e.stopPropagation();
  const anchor = e.currentTarget;
  showMenu(anchor, [
    { label: 'Rename', icon: 'pencil', onSelect: async () => {
      const name = await promptDialog({ title: 'Rename label', value: label.name });
      if (name) api.patch(`/labels/${label.id}`, { name }).catch(toastError);
    } },
    { label: 'Color', icon: 'palette', onSelect: () => pickColor(anchor, { value: label.color, onChange: (color) => api.patch(`/labels/${label.id}`, { color }).catch(toastError) }) },
    { divider: true },
    { label: 'Delete', icon: 'trash', danger: true, onSelect: async () => {
      if (await confirmDialog({ title: `Delete “${label.name}”?`, message: 'It is removed from every conversation.', danger: true, confirmLabel: 'Delete' })) {
        api.del(`/labels/${label.id}`).catch(toastError);
      }
    } },
  ]);
}

function onDropToLabel(labelId) {
  return {
    onDragOver: (e) => { if (e.dataTransfer.types.includes('application/x-sb-conversations')) { e.preventDefault(); e.currentTarget.classList.add('drop-target'); } },
    onDragLeave: (e) => e.currentTarget.classList.remove('drop-target'),
    onDrop: (e) => {
      e.currentTarget.classList.remove('drop-target');
      const ids = JSON.parse(e.dataTransfer.getData('application/x-sb-conversations') || '[]');
      if (ids.length) act(ids, 'label', { add: [labelId] }).catch(() => {});
    },
  };
}

export function InboxSidebar({ parsed }) {
  const teams = useStore((s) => s.teams);
  const me = useStore((s) => s.me);
  const labels = useStore((s) => s.boot.labels || []);
  const { data: counts } = useCounts();
  const [showMore, setShowMore] = useState(MORE.includes(parsed.mailbox));
  const myTeams = can('admin') ? teams : teams.filter((t) => (me.team_ids || []).includes(t.id));
  const shared = labels.filter((l) => l.visibility === 'shared');
  const personal = labels.filter((l) => l.visibility === 'personal');

  const countFor = (id) => {
    if (!counts) return 0;
    if (id === 'inbox') return counts.inbox_unread;
    if (id === 'assigned') return counts.assigned;
    if (id === 'drafts') return counts.drafts;
    if (id === 'scheduled') return counts.scheduled;
    return 0;
  };
  const newLabel = async (visibility) => {
    const name = await promptDialog({ title: visibility === 'personal' ? 'New personal label' : 'New shared label', label: 'Name', confirmLabel: 'Create' });
    if (name) api.post('/labels', { name, visibility }).catch(toastError);
  };
  const composeMenu = (e) => showMenu(e.currentTarget, [
    { label: 'New message', icon: 'mail-plus', shortcut: 'C', onSelect: () => navigate('/inbox/compose') },
    { label: 'New text message', icon: 'smartphone', onSelect: () => navigate('/inbox/compose?type=sms') },
    { label: 'New internal discussion', icon: 'messages-square', onSelect: startDiscussion },
  ], { placement: 'bottom-end' });

  return html`
    <${SidebarHeader} title="Inbox" />
    <div class="sidebar-compose">
      <div class="btn-group btn-block">
        <${Button} variant="primary" icon="square-pen" class="grow" onClick=${() => navigate('/inbox/compose')}>Compose</${Button}>
        <${Button} variant="primary" icon="chevron-down" aria-label="More ways to start" onClick=${composeMenu} />
      </div>
    </div>
    <${SidebarSection}>
      ${PRIMARY.map((id) => {
    const m = MAILBOXES.find((x) => x.id === id);
    const n = countFor(id);
    return html`<${SidebarItem} key=${id} href=${m.path} icon=${m.icon} label=${m.label} exact=${id === 'inbox'}
          active=${parsed.mailbox === id ? true : undefined} count=${n} countTone=${id === 'inbox' && n ? 'accent' : undefined} />`;
  })}
      <${SidebarItem} icon=${showMore ? 'chevron-up' : 'chevron-down'} label=${showMore ? 'Less' : 'More'} onClick=${() => setShowMore(!showMore)} class="sidebar-more" />
      ${showMore && MORE.map((id) => {
    const m = MAILBOXES.find((x) => x.id === id);
    return html`<${SidebarItem} key=${id} href=${m.path} icon=${m.icon} label=${m.label} active=${parsed.mailbox === id ? true : undefined} />`;
  })}
    </${SidebarSection}>
    ${myTeams.length > 0 && html`<${SidebarSection} title="Team inboxes" collapsible storageKey="inbox-teams">
      ${myTeams.map((t) => html`<${TeamItem} key=${t.id} team=${t} counts=${counts} active=${parsed.teamId === t.id} />`)}
    </${SidebarSection}>`}
    <${SidebarSection} title="Labels" collapsible storageKey="inbox-labels"
      actions=${html`<${IconButton} icon="plus" size="sm" label="New label" onClick=${() => newLabel('shared')} />`}>
      ${shared.map((l) => html`<${SidebarItem} key=${l.id} href=${`/inbox/label/${l.id}`} color=${l.color} label=${l.name}
        count=${counts?.labels?.[l.id]} onContextMenu=${(e) => labelMenu(e, l)} ...${onDropToLabel(l.id)} />`)}
      ${!shared.length && html`<div class="sidebar-empty">No labels yet</div>`}
    </${SidebarSection}>
    <${SidebarSection} title="My labels" collapsible storageKey="inbox-my-labels"
      actions=${html`<${IconButton} icon="plus" size="sm" label="New personal label" onClick=${() => newLabel('personal')} />`}>
      ${personal.map((l) => html`<${SidebarItem} key=${l.id} href=${`/inbox/label/${l.id}`} color=${l.color} label=${l.name}
        count=${counts?.labels?.[l.id]} onContextMenu=${(e) => labelMenu(e, l)} ...${onDropToLabel(l.id)} />`)}
      ${!personal.length && html`<div class="sidebar-empty">Only you see personal labels</div>`}
    </${SidebarSection}>
  `;
}
