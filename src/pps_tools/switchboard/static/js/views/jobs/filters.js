// Search + filter bar shared by the board and the list. Filters live in the URL query.

import { html, useEffect, useState } from '../../lib/preact.js';
import { setQuery } from '../../lib/router.js';
import { user as lookupUser, me } from '../../lib/store.js';
import { useDebounced } from '../../lib/hooks.js';
import { Button, Chip, SearchInput, Toggle } from '../../ui/components.js';
import { showMenu } from '../../ui/overlay.js';
import { pickUsers } from '../../ui/pickers.js';
import { stageOf } from './common.js';

const KEYS = ['q', 'priority', 'assignee_id', 'due', 'mine', 'stage_id', 'archived'];

export function filterQuery(q) {
  const out = {};
  for (const k of KEYS) if (q[k]) out[k] = q[k];
  return out;
}

export function hasFilters(q) {
  return KEYS.some((k) => k !== 'q' && q[k]);
}

const DUE_LABEL = { overdue: 'Overdue', week: 'Due within a week' };

export function FilterBar({ query, showDoneToggle, children }) {
  const [text, setText] = useState(query.q || '');
  const debounced = useDebounced(text, 250);
  useEffect(() => { if ((query.q || '') !== debounced) setQuery({ q: debounced || undefined }); }, [debounced]);
  useEffect(() => { if ((query.q || '') !== text && document.activeElement?.type !== 'search') setText(query.q || ''); }, [query.q]);

  const chips = [];
  if (query.mine) chips.push(['mine', 'My jobs']);
  if (query.priority) chips.push(['priority', query.priority === 'rush' ? 'Rush' : query.priority === 'high,rush' ? 'High & rush' : query.priority]);
  if (query.due) chips.push(['due', DUE_LABEL[query.due] || query.due]);
  if (query.assignee_id) chips.push(['assignee_id', `With ${lookupUser(Number(query.assignee_id)).name}`]);
  if (query.stage_id) chips.push(['stage_id', stageOf(Number(query.stage_id))?.name || 'Stage']);
  if (query.archived) chips.push(['archived', 'Archived']);

  const filterMenu = (e) => { const anchor = e.currentTarget; showMenu(anchor, [
    { label: 'My jobs', icon: 'user', checked: !!query.mine, onSelect: () => setQuery({ mine: query.mine ? undefined : '1' }) },
    { label: 'Someone else\'s…', icon: 'users', onSelect: () => pickUsers(anchor, {
      multi: false, selected: query.assignee_id ? [Number(query.assignee_id)] : [], title: 'Jobs with',
      onChange: (id) => setQuery({ assignee_id: id, mine: undefined }),
    }) },
    { divider: true },
    { label: 'Rush only', icon: 'flame', checked: query.priority === 'rush', onSelect: () => setQuery({ priority: query.priority === 'rush' ? undefined : 'rush' }) },
    { label: 'High & rush', icon: 'arrow-up', checked: query.priority === 'high,rush', onSelect: () => setQuery({ priority: query.priority === 'high,rush' ? undefined : 'high,rush' }) },
    { divider: true },
    { label: 'Overdue', icon: 'triangle-alert', checked: query.due === 'overdue', onSelect: () => setQuery({ due: query.due === 'overdue' ? undefined : 'overdue' }) },
    { label: 'Due within a week', icon: 'calendar-clock', checked: query.due === 'week', onSelect: () => setQuery({ due: query.due === 'week' ? undefined : 'week' }) },
    { divider: true },
    { label: 'Archived jobs', icon: 'archive', checked: !!query.archived, onSelect: () => setQuery({ archived: query.archived ? undefined : '1' }) },
  ], { width: 240 }); };

  return html`<div class="toolbar jobs-toolbar">
    <${SearchInput} value=${text} onValue=${setText} placeholder="Search jobs, customers, PO…" class="jobs-search" />
    <${Button} size="sm" icon="filter" onClick=${filterMenu}>Filter</${Button}>
    ${chips.map(([key, label]) => html`<${Chip} key=${key} tone="accent" onRemove=${() => setQuery({ [key]: undefined })}>${label}</${Chip}>`)}
    ${chips.length > 1 && html`<${Button} size="sm" variant="ghost" onClick=${() => setQuery(Object.fromEntries(KEYS.filter((k) => k !== 'q').map((k) => [k, undefined])))}>Clear</${Button}>`}
    <span class="grow"></span>
    ${children}
    ${showDoneToggle && html`<${Toggle} checked=${query.show_done === '1'} onChange=${(v) => setQuery({ show_done: v ? '1' : undefined })} label="Older finished jobs" />`}
  </div>`;
}

export function myId() {
  return me()?.id;
}
