// "My jobs" card for the My Day dashboard: today's steps assigned to me (with
// start/finish buttons for the shop floor) and my jobs that are due soon.

import { html } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { me } from '../../lib/store.js';
import { navigate } from '../../lib/router.js';
import { useFetch } from '../../lib/hooks.js';
import { addDays, startOfDay } from '../../lib/dates.js';
import { fmtTimeShort } from '../../lib/format.js';
import { Button, Card, Empty, Icon, Loading, cx } from '../../ui/components.js';
import { toastError } from '../../ui/overlay.js';
import { DueChip, StageChip, resourceOf } from './common.js';

export function MyJobsWidget() {
  const today = startOfDay(new Date());
  const { data: sched, reload: reloadSched } = useFetch('/schedule', {
    query: { start: today.toISOString(), end: addDays(today, 1).toISOString(), group: 'user' },
    refetchOn: ['schedule.changed', 'job.changed'],
  });
  const { data: jobs } = useFetch('/jobs', { query: { mine: 1, done: 0, sort: 'due', limit: 6 }, refetchOn: ['job.changed'] });
  const myId = me().id;
  const steps = sched ? sched.blocks.filter((b) => b.user_id === myId).sort((a, b) => (a.start_at < b.start_at ? -1 : 1)) : [];
  const setStatus = async (step, status) => {
    try { await api.patch(`/operations/${step.id}`, { status }); reloadSched({ quiet: true }); } catch (err) { toastError(err); }
  };
  const loading = !sched || !jobs;
  return html`<${Card} title="My jobs" icon="square-kanban" actions=${html`<${Button} size="sm" variant="ghost" onClick=${() => navigate('/jobs/list?mine=1')}>All</${Button}>`}>
    ${loading && html`<${Loading} />`}
    ${!loading && html`<div class="stack">
      <div>
        <div class="widget-subhead">Today's steps</div>
        ${steps.length ? steps.map((s) => html`<div class=${cx('widget-step', `is-${s.status}`)} key=${s.id}>
          <span class="widget-step-time tabular">${fmtTimeShort(s.start_at)}</span>
          <a class="grow widget-step-main" href=${`/jobs/${s.job_id}`}>
            <span class="strong truncate">${s.name}</span>
            <span class="muted text-xs truncate">${s.job_number} · ${s.job_title}${resourceOf(s.resource_id) ? ` · ${resourceOf(s.resource_id).name}` : ''}</span>
          </a>
          ${s.status === 'pending' && html`<${Button} size="sm" icon="play" onClick=${() => setStatus(s, 'in_progress')}>Start</${Button}>`}
          ${s.status === 'in_progress' && html`<${Button} size="sm" variant="primary" icon="check" onClick=${() => setStatus(s, 'done')}>Done</${Button}>`}
          ${s.status === 'done' && html`<${Icon} name="circle-check" size=${18} class="widget-step-done" />`}
        </div>`) : html`<p class="muted text-sm">Nothing on the schedule for you today.</p>`}
      </div>
      <div>
        <div class="widget-subhead">Due soon</div>
        ${jobs.items.length ? jobs.items.map((j) => html`<a class="widget-job" key=${j.id} href=${`/jobs/${j.id}`}>
          <span class="job-number">${j.number}</span><span class="truncate grow">${j.title}</span>
          <${StageChip} stageId=${j.stage_id} size="sm" /><${DueChip} job=${j} />
        </a>`) : html`<${Empty} icon="square-kanban" compact title="No open jobs">Jobs you're on show up here.</${Empty}>`}
      </div>
    </div>`}
  </${Card}>`;
}
