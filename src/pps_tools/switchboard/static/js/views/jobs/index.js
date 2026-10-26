// Jobs module: /jobs (board), /jobs/list, /jobs/schedule, /jobs/<id>.

import { html, useEffect } from '../../lib/preact.js';
import { can, useStore } from '../../lib/store.js';
import { matchPath, navigate, setQuery } from '../../lib/router.js';
import { useFetch } from '../../lib/hooks.js';
import { useHotkeys } from '../../lib/shortcuts.js';
import { IconButton } from '../../ui/components.js';
import { ModuleLayout, SidebarHeader, SidebarItem, SidebarSection } from '../../ui/layout.js';
import { registerCommands } from '../../ui/palette.js';
import { Board } from './board.js';
import { JobsList } from './list.js';
import { JobDetail } from './detail.js';
import { ScheduleBoard } from './schedule.js';
import { JOB_EVENTS } from './common.js';
import { openNewJob } from './new.js';

registerCommands(() => [
  can('manage_jobs') && { id: 'job-new', label: 'New job', icon: 'square-kanban', group: 'Jobs', keywords: 'create work order', run: () => openNewJob() },
  { id: 'job-schedule', label: 'Production schedule', icon: 'chart-gantt', group: 'Jobs', keywords: 'gantt timeline presses', run: () => navigate('/jobs/schedule') },
  { id: 'job-mine', label: 'My jobs', icon: 'user', group: 'Jobs', run: () => navigate('/jobs/list?mine=1') },
].filter(Boolean));

function Sidebar({ route }) {
  const stages = useStore((s) => s.boot.job_stages || []);
  const { data } = useFetch('/jobs/board', { query: { done_days: 1 }, refetchOn: JOB_EVENTS });
  const counts = {};
  let overdue = 0;
  let rush = 0;
  for (const st of (data ? data.stages : [])) {
    counts[st.id] = st.count;
    for (const j of st.jobs) {
      if (j.due_state === 'overdue') overdue += 1;
      if (j.priority === 'rush' && !j.is_done) rush += 1;
    }
  }
  const q = route.query;
  const onList = route.path === '/jobs/list';
  return html`
    <${SidebarHeader} title="Jobs" actions=${can('manage_jobs') && html`<${IconButton} icon="plus" label="New job" onClick=${() => openNewJob()} />`} />
    <${SidebarSection}>
      <${SidebarItem} href="/jobs" exact icon="square-kanban" label="Board" active=${route.path === '/jobs' && !q.priority && !q.due} />
      <${SidebarItem} href="/jobs/list" icon="list" label="List" active=${onList && !q.mine && !q.stage_id && !q.archived && !q.priority && !q.due} />
      <${SidebarItem} href="/jobs/schedule" icon="chart-gantt" label="Schedule" />
      <${SidebarItem} href="/jobs/list?mine=1" icon="user" label="My jobs" active=${onList && !!q.mine} />
    </${SidebarSection}>
    <${SidebarSection} title="Quick filters">
      <${SidebarItem} href="/jobs?priority=rush" icon="flame" label="Rush" count=${rush} countTone=${rush ? 'danger' : undefined}
        active=${route.path === '/jobs' && q.priority === 'rush'} />
      <${SidebarItem} href="/jobs/list?due=overdue" icon="triangle-alert" label="Overdue" count=${overdue} countTone=${overdue ? 'danger' : undefined}
        active=${onList && q.due === 'overdue'} />
      <${SidebarItem} href="/jobs?due=week" icon="calendar-clock" label="Due this week" active=${route.path === '/jobs' && q.due === 'week'} />
      <${SidebarItem} href="/jobs/list?archived=1" icon="archive" label="Archived" active=${onList && !!q.archived} />
    </${SidebarSection}>
    <${SidebarSection} title="Stages" collapsible storageKey="jobs-stages">
      ${stages.map((st) => html`<${SidebarItem} key=${st.id} href=${`/jobs/list?stage_id=${st.id}`} color=${st.color} label=${st.name}
        count=${counts[st.id]} active=${onList && String(q.stage_id) === String(st.id)} />`)}
    </${SidebarSection}>
  `;
}

export default function Jobs({ route }) {
  useHotkeys({ n: () => can('manage_jobs') && openNewJob() });
  useEffect(() => {
    if (route.query.new === '1' && can('manage_jobs')) {
      setQuery({ new: undefined });
      openNewJob();
    }
  }, [route.query.new]);
  const detail = matchPath('/jobs/:id', route.path);
  let content;
  if (route.path === '/jobs' || route.path === '/jobs/board') content = html`<${Board} route=${route} />`;
  else if (route.path === '/jobs/list') content = html`<${JobsList} route=${route} title=${route.query.mine ? 'My jobs' : route.query.archived ? 'Archived jobs' : 'All jobs'} />`;
  else if (route.path === '/jobs/schedule') content = html`<${ScheduleBoard} route=${route} />`;
  else if (detail && /^\d+$/.test(detail.id)) content = html`<${JobDetail} key=${detail.id} id=${Number(detail.id)} />`;
  else content = html`<${Board} route=${route} />`;
  return html`<${ModuleLayout} sidebar=${html`<${Sidebar} route=${route} />`} class="jobs-module">${content}</${ModuleLayout}>`;
}
