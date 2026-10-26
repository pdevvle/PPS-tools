// "My day": a personal dashboard assembled from widgets that other modules provide
// (time clock and shifts from staffing, my jobs, my tasks, agenda, inbox).
// A widget is a named export of a module file; missing files are skipped.

import { html, useEffect, useState } from '../../lib/preact.js';
import { useStore, can } from '../../lib/store.js';
import { fmtDateLong, firstName } from '../../lib/format.js';
import { ModuleLayout } from '../../ui/layout.js';
import { PageHeader } from '../../ui/components.js';

export const WIDGETS = [
  { id: 'clock', load: () => import('../staffing/widgets.js'), name: 'ClockWidget', size: 'sm' },
  { id: 'shifts', load: () => import('../staffing/widgets.js'), name: 'MyShiftsWidget', size: 'sm' },
  { id: 'inbox', load: () => import('../inbox/widgets.js'), name: 'InboxWidget', perm: 'inbox', size: 'sm' },
  { id: 'jobs', load: () => import('../jobs/widgets.js'), name: 'MyJobsWidget', size: 'md' },
  { id: 'tasks', load: () => import('../tasks/widgets.js'), name: 'MyTasksWidget', size: 'md' },
  { id: 'agenda', load: () => import('../calendar/widgets.js'), name: 'AgendaWidget', size: 'md' },
  { id: 'timeoff', load: () => import('../staffing/widgets.js'), name: 'TimeOffWidget', size: 'sm' },
  { id: 'approvals', load: () => import('../staffing/widgets.js'), name: 'ApprovalsWidget', perm: 'manage_staff', size: 'sm' },
];

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

export function useWidgets(list) {
  const [loaded, setLoaded] = useState([]);
  useEffect(() => {
    let alive = true;
    Promise.all(list.map((w) => w.load().then((m) => (m[w.name] ? { ...w, Component: m[w.name] } : null)).catch(() => null)))
      .then((res) => { if (alive) setLoaded(res.filter(Boolean)); });
    return () => { alive = false; };
  }, []);
  return loaded;
}

export default function MyDay() {
  const me = useStore((s) => s.me);
  const widgets = useWidgets(WIDGETS.filter((w) => !w.perm || can(w.perm)));
  return html`<${ModuleLayout}>
    <${PageHeader} title=${`${greeting()}, ${firstName(me.name)}`} subtitle=${fmtDateLong(new Date())} icon="house" />
    <div class="page-body">
      <div class="widget-grid">
        ${widgets.map(({ id, Component, size }) => html`<div key=${id} class=${`widget widget-${size || 'md'}`}><${Component} /></div>`)}
      </div>
    </div>
  </${ModuleLayout}>`;
}
