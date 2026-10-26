// Kanban board: one column per stage, drag cards between and within columns.

import { html, useMemo, useRef, useState } from '../../lib/preact.js';
import { can, useStore } from '../../lib/store.js';
import { navigate } from '../../lib/router.js';
import { useFetch, useIsMobile } from '../../lib/hooks.js';
import { Button, Empty, ErrorBox, Icon, IconButton, Loading, PageHeader, cx } from '../../ui/components.js';
import { SidebarButton } from '../../ui/layout.js';
import { toastError } from '../../ui/overlay.js';
import { JOB_EVENTS, JobCard, moveJob, openJobMenu } from './common.js';
import { FilterBar, filterQuery } from './filters.js';
import { openNewJob } from './new.js';

function insertionIndex(listEl, clientY, draggingId) {
  const cards = [...listEl.querySelectorAll('.job-card')].filter((c) => String(c.dataset.jobId) !== String(draggingId));
  for (let i = 0; i < cards.length; i++) {
    const r = cards[i].getBoundingClientRect();
    if (clientY < r.top + r.height / 2) return i;
  }
  return cards.length;
}

export function Board({ route }) {
  const q = route.query;
  const mobile = useIsMobile();
  const manage = can('manage_jobs');
  useStore((s) => s.boot.job_stages);
  const query = { ...filterQuery(q), done_days: q.show_done === '1' ? 60 : 14 };
  const { data, error, loading, reload, setData } = useFetch('/jobs/board', { query, refetchOn: JOB_EVENTS });
  const [drag, setDrag] = useState(null); // { job, fromStage }
  const [hover, setHover] = useState(null); // { stageId, index }
  const listRefs = useRef({});

  const columns = useMemo(() => (data ? data.stages : []), [data]);

  const onDrop = async (stageId) => {
    const target = hover && hover.stageId === stageId ? hover : { stageId, index: undefined };
    const job = drag && drag.job;
    setDrag(null);
    setHover(null);
    if (!job) return;
    const sameColumn = job.stage_id === stageId;
    // optimistic: move the card locally
    setData((d) => {
      if (!d) return d;
      const stagesCopy = d.stages.map((s) => ({ ...s, jobs: s.jobs.filter((j) => j.id !== job.id) }));
      const col = stagesCopy.find((s) => s.id === stageId);
      if (col) {
        const idx = target.index === undefined ? col.jobs.length : Math.min(target.index, col.jobs.length);
        col.jobs.splice(idx, 0, { ...job, stage_id: stageId });
        if (!sameColumn) {
          col.count += 1;
          const from = stagesCopy.find((s) => s.id === job.stage_id);
          if (from) from.count -= 1;
        }
      }
      return { ...d, stages: stagesCopy };
    });
    try {
      await moveJob(job, stageId, target.index);
    } catch (err) {
      toastError(err);
    }
    reload({ quiet: true });
  };

  const header = html`<${PageHeader} leading=${html`<${SidebarButton} />`} title="Jobs board" icon="square-kanban"
    subtitle=${data ? `${columns.reduce((n, s) => n + s.jobs.length, 0)} jobs` : ''}
    actions=${manage && html`<${Button} variant="primary" icon="plus" onClick=${() => openNewJob()}>New job</${Button}>`} />`;

  return html`<div class="jobs-page">
    ${header}
    <${FilterBar} query=${q} showDoneToggle />
    ${error && html`<${ErrorBox} error=${error} retry=${reload} />`}
    ${loading && !data ? html`<${Loading} />` : null}
    ${data && html`<div class="kanban" role="list">
      ${columns.map((st) => {
    const isHover = hover && hover.stageId === st.id;
    return html`<section
          key=${st.id}
          class=${cx('kanban-col', isHover && 'is-drop-target', st.over_wip && 'is-over-wip')}
          role="listitem"
          aria-label=${st.name}
          onDragOver=${(e) => {
      if (!drag) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const el = listRefs.current[st.id];
      const index = el ? insertionIndex(el, e.clientY, drag.job.id) : 0;
      if (!hover || hover.stageId !== st.id || hover.index !== index) setHover({ stageId: st.id, index });
    }}
          onDragLeave=${(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setHover(null); }}
          onDrop=${(e) => { e.preventDefault(); onDrop(st.id); }}
        >
          <header class="kanban-col-header">
            <span class="kanban-dot" style=${{ background: st.color || 'var(--text-3)' }}></span>
            <span class="kanban-col-title">${st.name}</span>
            <span class=${cx('kanban-count', st.over_wip && 'is-over')} title=${st.wip_limit ? `WIP limit ${st.wip_limit}` : ''}>
              ${st.count}${st.wip_limit ? `/${st.wip_limit}` : ''}
            </span>
            ${st.is_done && html`<${Icon} name="circle-check" size=${14} class="kanban-done-icon" title="Counts as finished" />`}
            <span class="grow"></span>
            ${manage && !st.is_done && html`<${IconButton} icon="plus" size="sm" label=${`New job in ${st.name}`} onClick=${() => openNewJob({ stageId: st.id })} />`}
          </header>
          <div class="kanban-list" ref=${(el) => { listRefs.current[st.id] = el; }}>
            ${st.jobs.map((job, i) => html`
              ${isHover && hover.index === i && html`<div class="kanban-drop-line"></div>`}
              <${JobCard}
                key=${job.id}
                job=${job}
                draggable=${manage && !mobile}
                dragging=${drag && drag.job.id === job.id}
                onDragStart=${(e) => {
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', String(job.id));
      setDrag({ job });
    }}
                onDragEnd=${() => { setDrag(null); setHover(null); }}
                onClick=${() => navigate(`/jobs/${job.id}`)}
                onMenu=${(e) => openJobMenu(e.currentTarget, job, { onChanged: () => reload({ quiet: true }) })}
              />`)}
            ${isHover && (hover.index === undefined || hover.index >= st.jobs.length) && html`<div class="kanban-drop-line"></div>`}
            ${!st.jobs.length && !isHover && html`<div class="kanban-empty">${st.is_done ? 'Finished jobs from the last two weeks show here' : 'No jobs'}</div>`}
          </div>
        </section>`;
  })}
    </div>`}
    ${data && !columns.length && html`<${Empty} icon="square-kanban" title="No stages yet"
      action=${can('manage_jobs') && html`<${Button} onClick=${() => navigate('/settings/job-stages')}>Set up stages</${Button}>`}>
      Stages are the columns jobs move through (Quote → Printing → Ready…).</${Empty}>`}
  </div>`;
}

export default Board;
