// Tasks: /tasks?view=mine|created|team|all|overdue|done  (&task=<id> opens the drawer)

import { html, useEffect, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useDebounced, useFetch } from '../../lib/hooks.js';
import { navigate, setQuery } from '../../lib/router.js';
import { useHotkeys } from '../../lib/shortcuts.js';
import { Empty, ErrorBox, Loading, PageHeader, SearchInput, cx } from '../../ui/components.js';
import { toastError } from '../../ui/overlay.js';
import { ModuleLayout, SidebarButton, SidebarHeader, SidebarItem, SidebarSection } from '../../ui/layout.js';
import { registerCommands } from '../../ui/palette.js';
import { QuickAdd, TaskDrawer, TaskRow, groupTasks } from './shared.js';

const VIEWS = [
  { id: 'mine', label: 'My tasks', icon: 'user', count: 'mine' },
  { id: 'created', label: 'Created by me', icon: 'pen-line', count: 'created' },
  { id: 'team', label: 'My teams', icon: 'users-round' },
  { id: 'all', label: 'Everyone', icon: 'list-todo', count: 'open' },
  { id: 'overdue', label: 'Overdue', icon: 'alarm-clock', count: 'overdue', tone: 'danger' },
  { id: 'done', label: 'Completed', icon: 'circle-check' },
];

const EMPTY = {
  mine: ['Nothing on your plate', 'Tasks assigned to you show up here. Add one above, or from a conversation or job.'],
  created: ['You haven’t handed anything out', 'Tasks you create for yourself or teammates show up here.'],
  team: ['Your teams are all caught up', 'Tasks for your teams and teammates show up here.'],
  all: ['No open tasks', 'Everyone is caught up.'],
  overdue: ['Nothing overdue', 'Nice work, everyone.'],
  done: ['Nothing completed yet', 'Checked-off tasks land here.'],
};

function TasksSidebar({ view }) {
  const { data } = useFetch('/tasks/counts', { refetchOn: ['task.changed'] });
  return html`
    <${SidebarHeader} title="Tasks" />
    <${SidebarSection}>
      ${VIEWS.map((v) => html`<${SidebarItem} key=${v.id} href=${`/tasks?view=${v.id}`} icon=${v.icon} label=${v.label}
        active=${view === v.id} count=${v.count && data ? data[v.count] : 0} countTone=${v.tone && data?.[v.count] ? v.tone : undefined} />`)}
    </${SidebarSection}>
  `;
}

export default function Tasks({ route }) {
  const view = VIEWS.some((v) => v.id === route.query.view) ? route.query.view : 'mine';
  const openId = Number(route.query.task) || null;
  const [q, setQ] = useState('');
  const debounced = useDebounced(q, 220);
  const { data, loading, error, reload, setData } = useFetch('/tasks', { query: { view, q: debounced }, refetchOn: ['task.changed'] });
  const [dragId, setDragId] = useState(null);
  const items = data?.items || [];
  const groups = groupTasks(items);
  const label = VIEWS.find((v) => v.id === view).label;

  useEffect(() => registerCommands(() => [
    { id: 'task-new', label: 'New task', icon: 'square-check-big', group: 'Tasks', run: () => { navigate('/tasks'); setTimeout(() => document.querySelector('.task-quick-input')?.focus(), 50); } },
  ]), []);
  useHotkeys({ n: () => document.querySelector('.task-quick-input')?.focus() }, { enabled: !openId });

  const replace = (task) => setData((d) => d && { ...d, items: d.items.map((t) => (t.id === task.id ? task : t)) });
  const closeDrawer = () => setQuery({ task: undefined });

  const drop = async (group, targetId) => {
    const ids = group.map((t) => t.id).filter((id) => id !== dragId);
    const at = ids.indexOf(targetId);
    ids.splice(at < 0 ? ids.length : at, 0, dragId);
    setDragId(null);
    setData((d) => d && { ...d, items: d.items.map((t) => (ids.includes(t.id) ? { ...t, position: ids.indexOf(t.id) + 1 } : t)) });
    try { await api.post('/tasks/reorder', { ids }); } catch (err) { toastError(err); reload(); }
  };

  return html`<${ModuleLayout} sidebar=${html`<${TasksSidebar} view=${view} />`} class="tasks-module">
    <${PageHeader} leading=${html`<${SidebarButton} />`} title=${label} icon="square-check-big"
      actions=${html`<${SearchInput} value=${q} onValue=${setQ} placeholder="Search tasks" class="tasks-search" />`} />
    <div class="page-body tasks-body">
      <div class="tasks-inner">
        ${view !== 'done' && html`<${QuickAdd} assigneeDefault=${view === 'all' || view === 'team' ? null : undefined}
          placeholder=${view === 'mine' ? 'Add a task for yourself… (press N)' : 'Add a task…'} onCreated=${() => reload({ quiet: true })} />`}
        <${ErrorBox} error=${error} retry=${reload} />
        ${loading && !data && html`<${Loading} />`}
        ${data && !items.length && html`<${Empty} icon="square-check-big" title=${q ? 'No matching tasks' : EMPTY[view][0]}>${q ? '' : EMPTY[view][1]}</${Empty}>`}
        ${groups.map(([key, title, list]) => html`<section key=${key} class=${cx('task-group', `task-group-${key}`)}>
          <h2 class="task-group-title">${title}<span class="task-group-count">${list.length}</span></h2>
          <div class="task-list">
            ${list.map((t) => html`<${TaskRow} key=${t.id} task=${t} onChange=${replace}
              draggable=${key !== 'done'} dragging=${dragId === t.id}
              onDragStart=${(e) => { setDragId(t.id); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(t.id)); }}
              onDragOver=${(e) => { if (dragId && list.some((x) => x.id === dragId)) e.preventDefault(); }}
              onDrop=${(e) => { e.preventDefault(); if (dragId) drop(list, t.id); }} />`)}
          </div>
        </section>`)}
      </div>
    </div>
    ${openId && html`<${TaskDrawer} key=${openId} id=${openId} onClose=${closeDrawer} />`}
  </${ModuleLayout}>`;
}

