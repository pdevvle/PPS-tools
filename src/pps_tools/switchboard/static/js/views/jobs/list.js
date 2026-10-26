// Sortable table of jobs with the same filters as the board.

import { html, useState } from '../../lib/preact.js';
import { can, useStore } from '../../lib/store.js';
import { navigate, setQuery } from '../../lib/router.js';
import { useFetch } from '../../lib/hooks.js';
import { fmtMoney, fmtRelative } from '../../lib/format.js';
import { AvatarStack, Button, Empty, ErrorBox, Icon, IconButton, Loading, PageHeader, ProgressBar, cx } from '../../ui/components.js';
import { SidebarButton } from '../../ui/layout.js';
import { DueChip, JOB_EVENTS, PriorityChip, ProofChip, StageChip, customerOf, openJobMenu } from './common.js';
import { FilterBar, filterQuery } from './filters.js';
import { openNewJob } from './new.js';

// Phones show only the title column (with number, stage and due under it); narrower
// desktops drop the col-* columns one by one (see jobs.css).
const COLUMNS = [
  { key: 'number', label: 'Job', cls: 'hide-mobile' },
  { key: 'title', label: 'Title', cls: 'jobs-title-cell' },
  { key: 'stage', label: 'Stage', cls: 'hide-mobile' },
  { key: 'priority', label: 'Priority', cls: 'hide-mobile' },
  { key: 'due', label: 'Due', cls: 'hide-mobile' },
  { key: null, label: 'People', cls: 'hide-mobile col-people' },
  { key: null, label: 'Progress', cls: 'hide-mobile col-progress' },
  { key: null, label: 'Quote', cls: 'hide-mobile col-quote', num: true },
  { key: 'updated', label: 'Updated', cls: 'hide-mobile col-updated' },
];

export function JobsList({ route, title = 'All jobs', preset = {} }) {
  const q = { ...route.query, ...preset };
  useStore((s) => s.boot.job_stages);
  const sort = q.sort || 'due';
  const dir = q.dir || (sort === 'updated' || sort === 'number' ? 'desc' : 'asc');
  const [limit, setLimit] = useState(100);
  const { data, error, loading, reload } = useFetch('/jobs', {
    query: { ...filterQuery(q), sort, dir, limit }, refetchOn: JOB_EVENTS,
  });
  const items = data ? data.items : [];
  const toggleSort = (key) => {
    if (!key) return;
    setQuery({ sort: key, dir: sort === key && dir === 'asc' ? 'desc' : 'asc' });
  };
  return html`<div class="jobs-page">
    <${PageHeader} leading=${html`<${SidebarButton} />`} title=${title} icon="list"
      subtitle=${data ? `${data.total} job${data.total === 1 ? '' : 's'}` : ''}
      actions=${can('manage_jobs') && html`<${Button} variant="primary" icon="plus" onClick=${() => openNewJob()}>New job</${Button}>`} />
    <${FilterBar} query=${q} />
    ${error && html`<${ErrorBox} error=${error} retry=${reload} />`}
    <div class="page-body jobs-list-body">
      ${loading && !data ? html`<${Loading} />` : null}
      ${data && !items.length && html`<${Empty} icon="square-kanban" title="No jobs match"
        action=${can('manage_jobs') && html`<${Button} icon="plus" onClick=${() => openNewJob()}>New job</${Button}>`}>
        Try clearing a filter, or create a job from a customer conversation.</${Empty}>`}
      ${items.length > 0 && html`<div class="table-wrap"><table class="table jobs-table">
        <thead><tr>
          ${COLUMNS.map((c) => html`<th class=${cx(c.cls, c.num && 'num', c.key && 'is-sortable')}
            onClick=${() => toggleSort(c.key)} aria-sort=${c.key === sort ? (dir === 'asc' ? 'ascending' : 'descending') : undefined}>
            ${c.label}${c.key === sort && html`<${Icon} name=${dir === 'asc' ? 'arrow-up' : 'arrow-down'} size=${12} class="sort-icon" />`}
          </th>`)}
          <th></th>
        </tr></thead>
        <tbody>
          ${items.map((j) => html`<tr key=${j.id} class=${cx('is-clickable', j.archived_at && 'is-archived')} onClick=${() => navigate(`/jobs/${j.id}`)}>
            <td class="nowrap hide-mobile"><span class="job-number">${j.number}</span></td>
            <td class="jobs-title-cell">
              <div class="strong truncate">${j.title}</div>
              ${customerOf(j) && html`<div class="muted text-sm truncate">${customerOf(j)}</div>`}
              <div class="jobs-mobile-meta"><span class="job-number">${j.number}</span><${StageChip} stageId=${j.stage_id} size="sm" />
                <${DueChip} job=${j} /><${ProofChip} status=${j.proof_status} /></div>
            </td>
            <td class="hide-mobile"><div class="jobs-stage-cell"><${StageChip} stageId=${j.stage_id} size="sm" /><${ProofChip} status=${j.proof_status} /></div></td>
            <td class="hide-mobile"><${PriorityChip} priority=${j.priority} showNormal /></td>
            <td class="nowrap hide-mobile"><${DueChip} job=${j} /></td>
            <td class="hide-mobile col-people">${j.assignee_ids.length ? html`<${AvatarStack} users=${j.assignee_ids} size=${22} />` : html`<span class="muted">—</span>`}</td>
            <td class="hide-mobile col-progress jobs-progress-cell">${j.operations.total
    ? html`<div class="row gap-2"><${ProgressBar} value=${j.operations.done} max=${j.operations.total} tone=${j.is_done ? 'ok' : 'accent'} class="grow" />
                <span class="muted text-xs tabular">${j.operations.done}/${j.operations.total}</span></div>`
    : html`<span class="muted">—</span>`}</td>
            <td class="hide-mobile col-quote num">${j.quote_amount != null ? fmtMoney(j.quote_amount) : html`<span class="muted">—</span>`}</td>
            <td class="hide-mobile col-updated muted nowrap">${fmtRelative(j.updated_at)}</td>
            <td style="width:40px" onClick=${(e) => e.stopPropagation()}>
              <${IconButton} icon="ellipsis" label="Actions" size="sm" onClick=${(e) => openJobMenu(e.currentTarget, j, { onChanged: () => reload({ quiet: true }) })} />
            </td>
          </tr>`)}
        </tbody>
      </table></div>`}
      ${data && data.total > items.length && html`<div class="center mt-3"><${Button} onClick=${() => setLimit(limit + 100)}>Show more</${Button}></div>`}
    </div>
  </div>`;
}

export default JobsList;
