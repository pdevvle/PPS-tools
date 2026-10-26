// Reports: inbox responsiveness, team hours & labor cost, job throughput.
// /reports/inbox | /reports/team | /reports/jobs ; range & filters live in the query.

import { html, useEffect, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { navigate, setQuery } from '../../lib/router.js';
import { boot, useStore } from '../../lib/store.js';
import { addDays, dateKey, fromDateKey, startOfMonth } from '../../lib/dates.js';
import { fmtDate, fmtMoney, fmtNumber, plural } from '../../lib/format.js';
import { ModuleLayout, SidebarButton, SidebarHeader, SidebarItem, SidebarSection } from '../../ui/layout.js';
import { Avatar, Banner, Button, ErrorBox, Icon, Loading, PageHeader, Select, Spinner, cx } from '../../ui/components.js';
import { showMenu, showPopover } from '../../ui/overlay.js';
import { BarList, ChartCard, ColumnChart, DataTable, Heatmap, Kpi, Legend, LineChart, Meter } from './charts.js';

// -- formatting -------------------------------------------------------------------------

export function fmtSpan(min) {
  if (min === null || min === undefined) return '—';
  if (min < 1) return '<1m';
  if (min < 60) return `${Math.round(min)}m`;
  if (min < 600) {
    const h = Math.floor(min / 60);
    const m = Math.round(min % 60);
    return m ? `${h}h ${m}m` : `${h}h`;
  }
  if (min < 1440) return `${Math.round(min / 60)}h`;
  return `${(min / 1440).toFixed(1)}d`;
}

const hrs = (min) => (min === null || min === undefined ? '—' : `${fmtNumber(Math.round((min / 60) * 10) / 10)}h`);
const pct = (v) => (v === null || v === undefined ? '—' : `${Math.round(v)}%`);
const num = (v) => (v === null || v === undefined ? '—' : fmtNumber(v));
const money = (v) => (v === null || v === undefined ? '—' : fmtMoney(v, { whole: v >= 1000 }));
const dayLabel = (key, long) => (long ? fmtDate(fromDateKey(key), { weekday: true }) : fmtDate(fromDateKey(key), { year: false }));
const weekLabel = (key, long) => (long ? `Week of ${fmtDate(fromDateKey(key), { year: false })}` : fmtDate(fromDateKey(key), { year: false }));

// -- date range ---------------------------------------------------------------------------

const PRESETS = [
  { id: '7d', label: 'Last 7 days' },
  { id: '30d', label: 'Last 30 days' },
  { id: '90d', label: 'Last 90 days' },
  { id: 'mtd', label: 'This month' },
  { id: 'last_month', label: 'Last month' },
  { id: 'ytd', label: 'Year to date' },
];

export function rangeFromQuery(query) {
  const today = new Date();
  const id = query.range || (query.start && query.end ? 'custom' : '30d');
  if (id === 'custom' && query.start && query.end) {
    return { id, start: query.start, end: query.end, label: `${fmtDate(fromDateKey(query.start))} – ${fmtDate(fromDateKey(query.end))}` };
  }
  const end = dateKey(today);
  const preset = PRESETS.find((p) => p.id === id) || PRESETS[1];
  let start;
  let stop = end;
  if (preset.id === '7d') start = dateKey(addDays(today, -6));
  else if (preset.id === '90d') start = dateKey(addDays(today, -89));
  else if (preset.id === 'mtd') start = dateKey(startOfMonth(today));
  else if (preset.id === 'last_month') {
    const first = startOfMonth(addDays(startOfMonth(today), -1));
    start = dateKey(first);
    stop = dateKey(addDays(startOfMonth(today), -1));
  } else if (preset.id === 'ytd') start = `${today.getFullYear()}-01-01`;
  else start = dateKey(addDays(today, -29));
  return { id: preset.id, start, end: stop, label: preset.label };
}

function RangePicker({ range, close }) {
  const [start, setStart] = useState(range.start);
  const [end, setEnd] = useState(range.end);
  const pick = (id) => { close(); setQuery({ range: id, start: undefined, end: undefined }); };
  const apply = (e) => {
    e.preventDefault();
    if (!start || !end || start > end) return;
    close();
    setQuery({ range: 'custom', start, end });
  };
  return html`<div class="range-picker">
    <div class="range-presets" role="listbox" aria-label="Date range">
      ${PRESETS.map((p) => html`<button type="button" key=${p.id} role="option" aria-selected=${range.id === p.id}
        class=${cx('range-preset', range.id === p.id && 'is-selected')} onClick=${() => pick(p.id)}>
        <span class="range-check">${range.id === p.id && html`<${Icon} name="check" size=${16} strokeWidth=${3} />`}</span>
        ${p.label}
      </button>`)}
    </div>
    <form class="range-custom" onSubmit=${apply}>
      <div class="range-custom-title">Custom range</div>
      <div class="row">
        <input type="date" class="input input-sm" value=${start} max=${end} aria-label="Start date" onInput=${(e) => setStart(e.currentTarget.value)} />
        <span class="muted">–</span>
        <input type="date" class="input input-sm" value=${end} min=${start} aria-label="End date" onInput=${(e) => setEnd(e.currentTarget.value)} />
      </div>
      <${Button} size="sm" variant="primary" type="submit">Apply</${Button}>
    </form>
  </div>`;
}

// Keeps showing the last result (dimmed) while a new range loads.
function useReport(report, query) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [nonce, setNonce] = useState(0);
  const key = JSON.stringify([report, query, nonce]);
  const seq = useRef(0);
  useEffect(() => {
    const id = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: null, data: s.data && s.data.__report === report ? s.data : null }));
    api.get(`/analytics/${report}`, query)
      .then((data) => { if (id === seq.current) setState({ data: { ...data, __report: report }, error: null, loading: false }); })
      .catch((error) => { if (id === seq.current) setState((s) => ({ ...s, error, loading: false })); });
  }, [key]);
  return { ...state, reload: () => setNonce((n) => n + 1) };
}

const TABLES = {
  inbox: [['daily', 'Daily volume'], ['agents', 'Teammates'], ['channels', 'Channels'], ['labels', 'Labels'], ['hours', 'Busiest hours'], ['waiting', 'Waiting for a reply']],
  team: [['people', 'People'], ['daily', 'Daily hours'], ['positions', 'Positions'], ['late', 'Late clock-ins']],
  jobs: [['weekly', 'Weekly jobs'], ['wip', 'Work in progress'], ['stages', 'Time in stage'], ['hours', 'Estimated vs actual'], ['customers', 'Customers']],
};

function exportMenu(e, report, query) {
  showMenu(e.currentTarget, TABLES[report].map(([table, label]) => ({
    label, icon: 'file-down',
    onSelect: () => { window.location.href = api.url(`/analytics/${report}`, { ...query, format: 'csv', table }); },
  })), { placement: 'bottom-end', width: 230 });
}

// -- inbox ------------------------------------------------------------------------------

function InboxReport({ data, stale, prevLabel }) {
  const t = data.totals;
  const p = data.previous;
  const daily = data.daily;
  const volume = [
    { key: 'received', label: 'Received', values: daily.map((d) => d.received) },
    { key: 'sent', label: 'Replies sent', values: daily.map((d) => d.sent) },
    { key: 'closed', label: 'Closed', values: daily.map((d) => d.closed) },
  ];
  const sla = data.sla;
  const slaStatus = !sla || sla.within_pct === null || sla.within_pct >= 90 ? 'good' : sla.within_pct >= 75 ? 'warning' : 'critical';
  const anyVolume = daily.some((d) => d.received || d.sent || d.closed);
  return html`
    <div class="kpi-row">
      <${Kpi} label="Conversations" value=${num(t.conversations)} current=${t.conversations} previous=${p.conversations} direction=${null} periodLabel=${prevLabel} />
      <${Kpi} label="Messages received" value=${num(t.received)} current=${t.received} previous=${p.received} direction=${null} periodLabel=${prevLabel} />
      <${Kpi} label="Replies sent" value=${num(t.sent)} current=${t.sent} previous=${p.sent} direction=${null} periodLabel=${prevLabel} />
      <${Kpi} label="Median first response" value=${fmtSpan(t.median_first_response)} current=${t.median_first_response}
        previous=${p.median_first_response} direction="down" periodLabel=${prevLabel} />
      <${Kpi} label="Closed" value=${num(t.closed)} current=${t.closed} previous=${p.closed} direction="up" periodLabel=${prevLabel} />
      <${Kpi} label="Waiting for a reply" value=${num(t.waiting)} hint="Open now, customer spoke last" />
    </div>
    <div class="viz-grid">
      <${ChartCard} wide title="Message volume" subtitle="Per day, in your business's time zone" stale=${stale}
        legend=${html`<${Legend} series=${volume} />`}
        table=${{ columns: [
          { key: 'date', label: 'Date', format: (v) => dayLabel(v, true) }, { key: 'received', label: 'Received', num: true },
          { key: 'sent', label: 'Replies sent', num: true }, { key: 'closed', label: 'Closed', num: true }], rows: daily }}>
        ${anyVolume ? html`<${LineChart} labels=${daily.map((d) => d.date)} series=${volume} xFormat=${dayLabel} height=${240}
          ariaLabel="Messages received, replies sent and conversations closed per day" />`
    : html`<div class="viz-empty">No messages in this period</div>`}
      </${ChartCard}>

      <${ChartCard} title="Response times" subtitle="First reply to a customer, and time to close" stale=${stale}>
        <div class="figure-grid">
          <div class="figure"><div class="figure-label">Median first response</div><div class="figure-value">${fmtSpan(data.first_response.median)}</div></div>
          <div class="figure"><div class="figure-label">Average</div><div class="figure-value">${fmtSpan(data.first_response.average)}</div></div>
          <div class="figure"><div class="figure-label">90% answered within</div><div class="figure-value">${fmtSpan(data.first_response.p90)}</div></div>
          <div class="figure"><div class="figure-label">Median time to close</div><div class="figure-value">${fmtSpan(data.resolution.median)}</div></div>
        </div>
        ${sla && html`<div class="sla">
          <div class="sla-head">
            <span class=${cx('sla-status', `is-${slaStatus}`)}>
              <${Icon} name=${slaStatus === 'good' ? 'circle-check' : slaStatus === 'warning' ? 'triangle-alert' : 'octagon-alert'} size=${15} />
              ${sla.within_pct === null ? 'No replies yet' : `${pct(sla.within_pct)} answered within ${fmtSpan(sla.target_minutes)}`}
            </span>
            <span class="muted text-sm">${plural(sla.breaches, 'breach', 'breaches')}</span>
          </div>
          <${Meter} value=${sla.within_pct} status=${slaStatus} label="Share of first replies within target" />
          <div class="muted text-sm">${num(sla.late)} answered late · ${num(sla.waiting_over)} still waiting past target</div>
        </div>`}
        ${data.first_response.count === 0 && html`<div class="viz-empty">No first replies in this period</div>`}
      </${ChartCard}>

      <${ChartCard} wide title="When messages arrive" subtitle="Messages received by weekday and hour" stale=${stale}
        table=${{ columns: [{ key: 'day', label: 'Weekday' }, { key: 'hour', label: 'Hour', num: true }, { key: 'count', label: 'Messages', num: true }],
          rows: data.heatmap.cells.flatMap((row, ri) => row.map((count, hour) => ({ day: data.heatmap.weekdays[ri], hour, count }))),
          defaultSort: { key: 'count', dir: 'desc' } }}>
        ${data.heatmap.max ? html`<${Heatmap} rows=${data.heatmap.weekdays} cells=${data.heatmap.cells} ariaLabel="Messages received by weekday and hour" />`
    : html`<div class="viz-empty">No messages in this period</div>`}
      </${ChartCard}>

      <${ChartCard} title="By channel" subtitle="Messages received" stale=${stale}
        table=${{ columns: [{ key: 'name', label: 'Channel' }, { key: 'type', label: 'Type' }, { key: 'received', label: 'Received', num: true },
          { key: 'sent', label: 'Sent', num: true }], rows: data.channels }}>
        <${BarList} items=${data.channels.map((c) => ({ key: c.channel_id, label: c.name, value: c.received, hint: `${c.sent} sent`,
    href: `/reports/inbox?${new URLSearchParams({ ...currentQuery(), channel_id: c.channel_id })}` }))} format=${num} />
      </${ChartCard}>

      <${ChartCard} title="Top labels" subtitle="Conversations active in this period" stale=${stale}
        table=${{ columns: [{ key: 'name', label: 'Label' }, { key: 'conversations', label: 'Conversations', num: true }], rows: data.labels }}>
        <${BarList} items=${data.labels.map((l) => ({ key: l.label_id, label: l.name, value: l.conversations, dot: l.color,
    href: `/inbox/label/${l.label_id}` }))} format=${num} empty="No labeled conversations" />
      </${ChartCard}>

      <${ChartCard} title="Waiting for a reply" subtitle=${data.waiting.count ? `${plural(data.waiting.count, 'conversation')} right now, longest first` : 'Right now'}>
        ${data.waiting.items.length ? html`<ul class="waiting-list">
          ${data.waiting.items.map((w) => html`<li key=${w.id}><a href=${`/inbox/c/${w.id}`} class="waiting-item">
            <span class="waiting-text"><span class="waiting-subject">${w.subject || w.contact || 'Conversation'}</span>
              ${w.subject && w.contact && html`<span class="muted text-sm">${w.contact}</span>`}</span>
            <span class=${cx('waiting-time', w.minutes > (sla?.target_minutes || 1e9) && 'is-late')}>${fmtSpan(w.minutes)}</span>
          </a></li>`)}
        </ul>` : html`<div class="viz-empty"><${Icon} name="circle-check" size=${16} /> Everyone has an answer</div>`}
      </${ChartCard}>

      <${ChartCard} wide title="Teammates" subtitle="Replies, closes and first-response speed in this period" stale=${stale}>
        <${DataTable} rows=${data.agents} rowKey=${(r) => r.user_id} defaultSort=${{ key: 'sent', dir: 'desc' }} columns=${[
    { key: 'name', label: 'Teammate', render: (r) => html`<span class="row"><${Avatar} user=${r.user_id} size=${22} />${r.name}</span>` },
    { key: 'sent', label: 'Replies sent', num: true, format: num },
    { key: 'closed', label: 'Closed', num: true, format: num },
    { key: 'first_responses', label: 'First replies', num: true, format: num },
    { key: 'median_first_response', label: 'Median first reply', num: true, format: fmtSpan },
    { key: 'comments', label: 'Comments', num: true, format: num },
    { key: 'open_assigned', label: 'Open assigned', num: true, format: num },
  ]} />
      </${ChartCard}>
    </div>`;
}

function currentQuery() {
  return Object.fromEntries(new URLSearchParams(window.location.search));
}

// -- team -------------------------------------------------------------------------------

function TeamReport({ data, stale, prevLabel }) {
  const t = data.totals;
  const p = data.previous;
  const daily = data.daily;
  const hours = [
    { key: 'scheduled', label: 'Scheduled', values: daily.map((d) => Math.round(((d.scheduled_minutes || 0) / 60) * 10) / 10) },
    { key: 'worked', label: 'Worked', values: daily.map((d) => Math.round(((d.worked_minutes || 0) / 60) * 10) / 10) },
  ];
  const any = daily.some((d) => d.scheduled_minutes || d.worked_minutes);
  const rule = data.overtime_rule;
  return html`
    ${t.missing_rates > 0 && html`<${Banner} tone="warn" class="mb-3">${plural(t.missing_rates, 'person has', 'people have')} no hourly rate, so labor cost is incomplete.
      <a href="/schedule/people">Set rates</a></${Banner}>`}
    <div class="kpi-row">
      <${Kpi} label="Scheduled" value=${hrs(t.scheduled_minutes)} current=${t.scheduled_minutes} previous=${p.scheduled_minutes} direction=${null} periodLabel=${prevLabel} />
      <${Kpi} label="Worked" value=${hrs(t.worked_minutes)} current=${t.worked_minutes} previous=${p.worked_minutes} direction=${null} periodLabel=${prevLabel} />
      <${Kpi} label="Overtime" value=${hrs(t.overtime_minutes)} current=${t.overtime_minutes} previous=${p.overtime_minutes} direction="down" periodLabel=${prevLabel}
        hint=${`Over ${rule.weekly_hours}h a week${rule.daily_hours ? ` or ${rule.daily_hours}h a day` : ''}`} />
      <${Kpi} label="Labor cost" value=${money(t.labor_cost)} current=${t.labor_cost} previous=${p.labor_cost} direction=${null} periodLabel=${prevLabel}
        hint="Worked hours × rate, overtime at 1.5×" />
      <${Kpi} label="Late clock-ins" value=${num(t.late)} current=${t.late} previous=${p.late} direction="down" periodLabel=${prevLabel} hint="More than 5 min after shift start" />
      <${Kpi} label="Time off" value=${`${fmtNumber(t.timeoff_days)} days`} hint="Approved, in this period" />
    </div>
    <div class="viz-grid">
      <${ChartCard} wide title="Scheduled vs worked hours" subtitle="Per day, all staff" stale=${stale}
        legend=${html`<${Legend} series=${hours} />`}
        table=${{ columns: [{ key: 'date', label: 'Date', format: (v) => dayLabel(v, true) },
          { key: 'scheduled_minutes', label: 'Scheduled', num: true, format: hrs }, { key: 'worked_minutes', label: 'Worked', num: true, format: hrs }], rows: daily }}>
        ${any ? html`<${LineChart} labels=${daily.map((d) => d.date)} series=${hours} xFormat=${dayLabel} format=${(v) => `${fmtNumber(v)}h`}
          height=${230} ariaLabel="Scheduled and worked hours per day" />` : html`<div class="viz-empty">No shifts or time punches in this period</div>`}
      </${ChartCard}>

      <${ChartCard} wide title="People" subtitle="Click someone to open their profile" stale=${stale}>
        <${DataTable} rows=${data.people} rowKey=${(r) => r.user_id} defaultSort=${{ key: 'worked_minutes', dir: 'desc' }}
          onRowClick=${(r) => navigate(`/schedule/people/${r.user_id}`)} columns=${[
    { key: 'name', label: 'Person', render: (r) => html`<span class="row"><${Avatar} user=${r.user_id} size=${22} />${r.name}</span>` },
    { key: 'shifts', label: 'Shifts', num: true, format: num },
    { key: 'scheduled_minutes', label: 'Scheduled', num: true, format: hrs },
    { key: 'worked_minutes', label: 'Worked', num: true, format: hrs },
    { key: 'variance_minutes', label: '+/– plan', num: true, format: (v) => (v === null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${hrs(Math.abs(v))}`) },
    { key: 'overtime_minutes', label: 'Overtime', num: true, format: (v) => (v ? hrs(v) : '—') },
    { key: 'labor_cost', label: 'Labor cost', num: true, format: money },
    { key: 'late', label: 'Late', num: true, format: (v) => (v ? num(v) : '—') },
    { key: 'timeoff_days', label: 'Time off', num: true, format: (v) => (v ? `${fmtNumber(v)}d` : '—') },
  ]} />
      </${ChartCard}>

      <${ChartCard} title="Hours by position" subtitle="Worked hours and cost" stale=${stale}
        table=${{ columns: [{ key: 'name', label: 'Position' }, { key: 'scheduled_minutes', label: 'Scheduled', num: true, format: hrs },
          { key: 'worked_minutes', label: 'Worked', num: true, format: hrs }, { key: 'labor_cost', label: 'Labor cost', num: true, format: money }], rows: data.positions }}>
        <${BarList} items=${data.positions.map((pos) => ({ key: pos.position_id ?? 'none', label: pos.name, value: (pos.worked_minutes || 0) / 60,
    dot: pos.color, suffix: pos.labor_cost ? ` · ${money(pos.labor_cost)}` : '' }))} format=${(v) => `${fmtNumber(Math.round(v * 10) / 10)}h`} />
      </${ChartCard}>

      <${ChartCard} title="Late clock-ins" subtitle="Most recent first">
        ${data.late.length ? html`<ul class="waiting-list">
          ${data.late.map((x) => html`<li key=${x.user_id + x.clock_in}><div class="waiting-item">
            <span class="waiting-text"><span class="row"><${Avatar} user=${x.user_id} size=${20} /><span class="waiting-subject">${x.name}</span></span>
              <span class="muted text-sm">${fmtDate(x.clock_in, { weekday: true })} · shift at ${new Date(x.shift_start).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</span></span>
            <span class="waiting-time is-late">+${fmtSpan(x.minutes_late)}</span>
          </div></li>`)}
        </ul>` : html`<div class="viz-empty"><${Icon} name="circle-check" size=${16} /> Everyone was on time</div>`}
      </${ChartCard}>
    </div>`;
}

// -- jobs -------------------------------------------------------------------------------

function JobsReport({ data, stale, prevLabel }) {
  const t = data.totals;
  const p = data.previous;
  const weekly = data.weekly;
  const series = [
    { key: 'created', label: 'Created', values: weekly.map((w) => w.created) },
    { key: 'completed', label: 'Completed', values: weekly.map((w) => w.completed) },
  ];
  const anyWeekly = weekly.some((w) => w.created || w.completed);
  return html`
    <div class="kpi-row">
      <${Kpi} label="Jobs created" value=${num(t.created)} current=${t.created} previous=${p.created} direction=${null} periodLabel=${prevLabel} />
      <${Kpi} label="Completed" value=${num(t.completed)} current=${t.completed} previous=${p.completed} direction="up" periodLabel=${prevLabel} />
      <${Kpi} label="On time" value=${pct(t.on_time_pct)} current=${t.on_time_pct} previous=${p.on_time_pct} direction="up" periodLabel=${prevLabel}
        hint=${t.with_due ? `${t.on_time} of ${t.with_due} with a due date` : 'No due dates in this period'} />
      <${Kpi} label="Avg. turnaround" value=${fmtSpan(t.average_cycle_minutes)} hint="Created to completed" />
      <${Kpi} label="Revenue" value=${money(t.revenue)} current=${t.revenue} previous=${p.revenue} direction="up" periodLabel=${prevLabel} hint="Quoted value of completed jobs" />
      <${Kpi} label="Open now" value=${num(t.open)} hint=${t.overdue ? `${t.overdue} overdue` : 'None overdue'} />
    </div>
    <div class="viz-grid">
      <${ChartCard} wide title="Jobs per week" stale=${stale} legend=${html`<${Legend} series=${series} shape="rect" />`}
        table=${{ columns: [{ key: 'week_start', label: 'Week of', format: (v) => weekLabel(v) }, { key: 'created', label: 'Created', num: true },
          { key: 'completed', label: 'Completed', num: true }], rows: weekly }}>
        ${anyWeekly ? html`<${ColumnChart} labels=${weekly.map((w) => w.week_start)} series=${series} xFormat=${weekLabel} height=${230}
          ariaLabel="Jobs created and completed per week" />` : html`<div class="viz-empty">No jobs created or completed in this period</div>`}
      </${ChartCard}>

      <${ChartCard} title="Work in progress" subtitle="Open jobs by stage, right now"
        table=${{ columns: [{ key: 'name', label: 'Stage' }, { key: 'jobs', label: 'Open jobs', num: true }, { key: 'overdue', label: 'Overdue', num: true },
          { key: 'wip_limit', label: 'WIP limit', num: true }], rows: data.wip }}>
        <${BarList} items=${data.wip.map((w) => ({ key: w.stage_id ?? 'none', label: w.name, value: w.jobs, dot: w.color,
    suffix: w.overdue ? ` · ${w.overdue} overdue` : w.wip_limit && w.jobs > w.wip_limit ? ' · over limit' : '', href: '/jobs' }))}
          format=${num} empty="No open jobs" />
      </${ChartCard}>

      <${ChartCard} title="Time in stage" subtitle="Average, for moves made in this period" stale=${stale}
        table=${{ columns: [{ key: 'name', label: 'Stage' }, { key: 'transitions', label: 'Moves out', num: true },
          { key: 'average_minutes', label: 'Average', num: true, format: fmtSpan }, { key: 'median_minutes', label: 'Median', num: true, format: fmtSpan }],
          rows: data.time_in_stage }}>
        <${BarList} items=${data.time_in_stage.map((s) => ({ key: s.stage_id, label: s.name, value: s.average_minutes || 0, dot: s.color,
    hint: `${s.transitions} moves` }))} format=${fmtSpan} empty="No stage changes in this period" />
      </${ChartCard}>

      <${ChartCard} wide title="Estimated vs actual hours" subtitle="Jobs finished or worked on in this period; actual comes from the time clock" stale=${stale}>
        <${DataTable} rows=${data.hours} rowKey=${(r) => r.job_id} defaultSort=${{ key: 'actual_minutes', dir: 'desc' }}
          onRowClick=${(r) => navigate(`/jobs/${r.job_id}`)} empty="No time tracked against jobs in this period" columns=${[
    { key: 'number', label: 'Job', render: (r) => html`<span class="mono">${r.number}</span>` },
    { key: 'title', label: 'Title', render: (r) => html`<span class="truncate viz-cell-title">${r.title}</span>` },
    { key: 'stage', label: 'Stage', format: (v) => v || '—' },
    { key: 'estimated_minutes', label: 'Estimated', num: true, format: hrs },
    { key: 'actual_minutes', label: 'Actual', num: true, format: hrs },
    { key: 'variance_pct', label: 'Variance', num: true, render: (r) => (r.variance_pct === null ? '—'
      : html`<span class=${cx('variance', r.variance_pct > 15 ? 'is-over' : r.variance_pct < -15 ? 'is-under' : '')}>${r.variance_pct > 0 ? '+' : ''}${Math.round(r.variance_pct)}%</span>`) },
  ]} />
        ${t.estimated_minutes && html`<div class="muted text-sm mt-2">Total: ${hrs(t.actual_minutes)} actual vs ${hrs(t.estimated_minutes)} estimated.</div>`}
      </${ChartCard}>

      <${ChartCard} wide title="Top customers" subtitle="Jobs created in this period" stale=${stale}>
        <${DataTable} rows=${data.customers} rowKey=${(r) => `${r.kind}-${r.id}`} defaultSort=${{ key: 'quoted', dir: 'desc' }}
          onRowClick=${(r) => (r.kind === 'org' ? navigate(`/contacts/orgs/${r.id}`) : r.kind === 'contact' ? navigate(`/contacts/${r.id}`) : null)}
          empty="No jobs created in this period" columns=${[
    { key: 'name', label: 'Customer' },
    { key: 'jobs', label: 'Jobs', num: true, format: num },
    { key: 'completed', label: 'Completed', num: true, format: num },
    { key: 'quoted', label: 'Quoted value', num: true, format: money },
  ]} />
      </${ChartCard}>
    </div>`;
}

// -- page -------------------------------------------------------------------------------

const REPORTS = {
  inbox: { title: 'Inbox', icon: 'inbox', Component: InboxReport },
  team: { title: 'Team', icon: 'users', Component: TeamReport },
  jobs: { title: 'Jobs', icon: 'square-kanban', Component: JobsReport },
};

export default function Reports({ route }) {
  const report = route.segments[1];
  useEffect(() => {
    if (!REPORTS[report]) navigate('/reports/inbox' + (route.search || ''), { replace: true });
  }, [report]);
  const current = REPORTS[report] ? report : 'inbox';
  const range = rangeFromQuery(route.query);
  const teams = useStore((s) => s.teams);
  const channels = boot('channels').filter((c) => c.visibility === 'shared');
  const query = { start: range.start, end: range.end };
  if (current === 'inbox') {
    if (route.query.team_id) query.team_id = route.query.team_id;
    if (route.query.channel_id) query.channel_id = route.query.channel_id;
  }
  const { data, error, loading, reload } = useReport(current, query);
  const { title, Component } = REPORTS[current];
  const days = Math.round((fromDateKey(range.end) - fromDateKey(range.start)) / 86400000) + 1;
  const prevLabel = `previous ${days} days`;
  const keep = new URLSearchParams(Object.entries(route.query).filter(([k]) => ['range', 'start', 'end'].includes(k))).toString();

  const sidebar = html`
    <${SidebarHeader} title="Reports" />
    <${SidebarSection}>
      ${Object.entries(REPORTS).map(([id, r]) => html`<${SidebarItem} key=${id} href=${`/reports/${id}${keep ? '?' + keep : ''}`}
        icon=${r.icon} label=${r.title} active=${current === id} />`)}
    </${SidebarSection}>`;

  const openRange = (e) => showPopover(e.currentTarget, (close) => html`<${RangePicker} range=${range} close=${close} />`,
    { width: 290, placement: 'bottom-start' });

  return html`<${ModuleLayout} sidebar=${sidebar} class="reports-module">
    <${PageHeader} leading=${html`<${SidebarButton} />`} title=${`${title} report`} icon="chart-column"
      subtitle=${`${fmtDate(fromDateKey(range.start))} – ${fmtDate(fromDateKey(range.end))}${data?.period?.timezone ? ` · ${data.period.timezone}` : ''}`}
      actions=${html`<${Button} icon="download" onClick=${(e) => exportMenu(e, current, query)}>Export CSV</${Button}>`} />
    <div class="toolbar reports-filters" role="group" aria-label="Report filters">
      <${Button} icon="calendar" iconRight="chevron-down" onClick=${openRange} aria-label=${`Date range: ${range.label}`}>${range.label}</${Button}>
      ${current === 'inbox' && html`
        <${Select} class="reports-select" value=${route.query.team_id || ''} placeholder="All teams" aria-label="Team"
          options=${teams.map((tm) => ({ value: String(tm.id), label: tm.name }))} onValue=${(v) => setQuery({ team_id: v || undefined })} />
        <${Select} class="reports-select" value=${route.query.channel_id || ''} placeholder="All channels" aria-label="Channel"
          options=${channels.map((c) => ({ value: String(c.id), label: c.name }))} onValue=${(v) => setQuery({ channel_id: v || undefined })} />`}
      ${loading && data && html`<${Spinner} size=${14} class="reports-spinner" />`}
    </div>
    <div class="page-body viz-root">
      ${error && html`<${ErrorBox} error=${error} retry=${reload} class="mb-3" />`}
      ${!data && loading && html`<${Loading} label="Crunching numbers…" />`}
      ${data && html`<div class=${cx('reports-body', loading && 'is-stale')}><${Component} data=${data} stale=${loading} prevLabel=${prevLabel} /></div>`}
    </div>
  </${ModuleLayout}>`;
}

