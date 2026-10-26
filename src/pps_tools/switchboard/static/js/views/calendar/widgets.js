// "Today & tomorrow" agenda card for My Day: my events, shifts and scheduled job work.

import { html } from '../../lib/preact.js';
import { useFetch } from '../../lib/hooks.js';
import { navigate } from '../../lib/router.js';
import { addDays, dateKey, fromDateKey } from '../../lib/dates.js';
import { fmtTimeShort } from '../../lib/format.js';
import { Button, Card, Empty, Icon, Loading, cx } from '../../ui/components.js';
import { kindIcon } from './editor.js';
import { itemsOnDay, prepare } from './util.js';

export function AgendaWidget() {
  const todayKey = dateKey(new Date());
  const { data, loading } = useFetch('/calendar/agenda', {
    query: { date: todayKey },
    refetchOn: ['calendar.changed', 'shift.changed', 'schedule.changed', 'job.changed'],
    interval: 5 * 60000,
  });
  const items = prepare(data?.items || []);
  const today = fromDateKey(data?.today || todayKey);
  const days = [[today, 'Today'], [addDays(today, 1), 'Tomorrow']];
  const now = new Date();
  return html`<${Card} title="Agenda" icon="calendar-days" pad=${false}
    actions=${html`<${Button} size="sm" variant="ghost" onClick=${() => navigate('/calendar')}>Calendar</${Button}>`}>
    ${loading && !data && html`<${Loading} />`}
    ${data && !items.length && html`<${Empty} icon="calendar" title="Nothing scheduled" compact>No events, shifts or job work today or tomorrow.</${Empty}>`}
    ${data && items.length > 0 && html`<div class="agenda-widget">
      ${days.map(([d, label]) => {
    const list = itemsOnDay(items, d).sort((a, b) => (b.all_day || b.multiDay) - (a.all_day || a.multiDay) || a.s - b.s);
    if (!list.length) return null;
    return html`<div key=${label} class="agenda-widget-day">
          <div class="agenda-widget-label">${label}</div>
          ${list.map((it) => html`<button type="button" key=${it.id} style=${{ '--ev': it.color || 'var(--accent)' }}
            class=${cx('agenda-widget-item', it.read_only && 'is-overlay', !it.all_day && it.e < now && 'is-past')}
            onClick=${() => navigate(it.url && it.read_only ? it.url : `/calendar?view=day&date=${dateKey(d)}`)}>
            <span class="agenda-widget-time">${it.all_day || it.multiDay ? 'All day' : fmtTimeShort(it.s)}</span>
            <span class="agenda-widget-bar"></span>
            <span class="agenda-widget-text">
              <span class="agenda-widget-title">${it.kind !== 'event' && html`<${Icon} name=${kindIcon(it.kind)} size=${12} />`}${it.title}</span>
              ${!it.all_day && html`<span class="agenda-widget-sub">${fmtTimeShort(it.s)} – ${fmtTimeShort(it.e)}${it.location ? ` · ${it.location}` : it.subtitle ? ` · ${it.subtitle}` : ''}</span>`}
            </span>
          </button>`)}
        </div>`;
  })}
    </div>`}
  </${Card}>`;
}
