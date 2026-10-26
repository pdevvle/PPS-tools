// Schedule module (/schedule): week grid, people, time off, swap requests, timesheets
// and the shop-tablet kiosk.

import { html } from '../../lib/preact.js';
import { useStore } from '../../lib/store.js';
import { navigate } from '../../lib/router.js';
import { registerCommands } from '../../ui/palette.js';
import { ModuleLayout, SidebarHeader, SidebarItem, SidebarSection } from '../../ui/layout.js';
import { Button } from '../../ui/components.js';
import { WeekGrid } from './grid.js';
import { PeopleList, PersonProfile } from './people.js';
import { TimeOffPage } from './timeoff.js';
import { RequestsPage } from './requests.js';
import { TimesheetsPage } from './timesheets.js';
import { Kiosk } from './kiosk.js';
import * as S from './shared.js';

registerCommands(() => [
  { id: 'schedule-week', label: 'Open the schedule', icon: 'calendar-clock', group: 'Schedule', run: () => navigate('/schedule') },
  { id: 'schedule-timeoff', label: 'Request time off', icon: 'plane', group: 'Schedule', run: () => S.requestTimeOff() },
  { id: 'schedule-timesheets', label: 'Timesheets', icon: 'clock', group: 'Schedule', run: () => navigate('/schedule/timesheets') },
  ...(S.isManager() ? [{ id: 'schedule-kiosk', label: 'Open the time clock kiosk', icon: 'tablet-smartphone', group: 'Schedule', run: () => navigate('/schedule/kiosk') }] : []),
]);

function Sidebar({ page, route }) {
  const manager = S.isManager();
  const counts = S.useStaffCounts();
  const c = counts.data || {};
  const positions = S.usePositions().filter((p) => p.is_active);
  const locations = S.useLocations().filter((l) => l.is_active);
  const filterPos = route.query.position ? Number(route.query.position) : null;
  const filterLoc = route.query.location ? Number(route.query.location) : null;
  const filterHref = (patch) => {
    const q = { ...route.query, ...patch };
    const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v !== null && v !== undefined && v !== ''));
    const s = qs.toString();
    return '/schedule' + (s ? '?' + s : '');
  };
  return html`
    <${SidebarHeader} title="Schedule"
      actions=${html`<${Button} size="sm" variant="ghost" icon="plane" onClick=${() => S.requestTimeOff()} aria-label="Request time off" />`} />
    <${SidebarSection}>
      <${SidebarItem} href="/schedule" icon="calendar-days" label="Week" active=${page === 'week'} count=${manager ? c.drafts : 0} />
      <${SidebarItem} href="/schedule/people" icon="users" label="People" active=${page === 'people'} />
      <${SidebarItem} href="/schedule/timeoff" icon="plane" label="Time off" active=${page === 'timeoff'} count=${c.timeoff} countTone=${page === 'timeoff' ? undefined : 'accent'} />
      <${SidebarItem} href="/schedule/requests" icon="arrow-right-left" label="Requests" active=${page === 'requests'}
        count=${(c.requests || 0) + (c.mine || 0)} countTone=${page === 'requests' ? undefined : 'accent'} />
      <${SidebarItem} href="/schedule/timesheets" icon="clock" label="Timesheets" active=${page === 'timesheets'}
        count=${manager ? c.flagged : 0} countTone=${page === 'timesheets' ? undefined : 'danger'} />
      ${manager && html`<${SidebarItem} href="/schedule/kiosk" icon="tablet-smartphone" label="Kiosk" active=${page === 'kiosk'} />`}
    </${SidebarSection}>
    ${page === 'week' && positions.length > 0 && html`<${SidebarSection} title="Positions" collapsible storageKey="schedule-positions">
      <${SidebarItem} href=${filterHref({ position: null })} label="All positions" icon="layers" active=${!filterPos} />
      ${positions.map((p) => html`<${SidebarItem} key=${p.id} href=${filterHref({ position: p.id })} label=${p.name} color=${p.color} active=${filterPos === p.id} />`)}
    </${SidebarSection}>`}
    ${page === 'week' && locations.length > 1 && html`<${SidebarSection} title="Locations" collapsible storageKey="schedule-locations">
      <${SidebarItem} href=${filterHref({ location: null })} label="All locations" icon="map-pin" active=${!filterLoc} />
      ${locations.map((l) => html`<${SidebarItem} key=${l.id} href=${filterHref({ location: l.id })} label=${l.name} color=${l.color} active=${filterLoc === l.id} />`)}
    </${SidebarSection}>`}
    ${manager && c.clocked_in > 0 && html`<div class="st-sidebar-live"><span class="sg-live is-clocked_in"></span>${c.clocked_in} on the clock now</div>`}
  `;
}

export default function Schedule({ route }) {
  useStore((s) => s.me);
  const seg = route.segments.slice(1);
  const page = seg[0] || 'week';
  if (page === 'kiosk' && S.isManager()) return html`<${Kiosk} />`;
  let body;
  if (page === 'people' && seg[1]) body = html`<${PersonProfile} key=${seg[1]} id=${seg[1]} />`;
  else if (page === 'people') body = html`<${PeopleList} />`;
  else if (page === 'timeoff') body = html`<${TimeOffPage} />`;
  else if (page === 'requests') body = html`<${RequestsPage} />`;
  else if (page === 'timesheets') body = html`<${TimesheetsPage} route=${route} />`;
  else body = html`<${WeekGrid} route=${route} />`;
  return html`<${ModuleLayout} sidebar=${html`<${Sidebar} page=${seg[1] && page === 'people' ? 'people' : page} route=${route} />`} class="schedule-module">
    ${body}
  </${ModuleLayout}>`;
}
