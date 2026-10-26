// Calendar helpers: visible ranges, per-day placement, overlap layout, recurrence presets.

import { addDays, addMonths, dateKey, fromDateKey, monthGrid, startOfDay, startOfWeek } from '../../lib/dates.js';

export const VIEWS = ['month', 'week', 'day', 'agenda'];
export const HOUR_PX = 44;
export const SNAP_MIN = 15;

export function rangeFor(view, date, weekStart) {
  if (view === 'month') {
    const grid = monthGrid(date, weekStart);
    return { start: grid[0][0], end: addDays(grid[5][6], 1), grid };
  }
  if (view === 'week') {
    const start = startOfWeek(date, weekStart);
    return { start, end: addDays(start, 7) };
  }
  if (view === 'day') {
    const start = startOfDay(date);
    return { start, end: addDays(start, 1) };
  }
  const start = startOfDay(date);
  return { start, end: addDays(start, 30) };
}

export function step(view, date, dir) {
  if (view === 'month') return addMonths(date, dir);
  if (view === 'week') return addDays(date, 7 * dir);
  if (view === 'agenda') return addDays(date, 30 * dir);
  return addDays(date, dir);
}

const titleFmt = (opts) => new Intl.DateTimeFormat(undefined, opts);

export function rangeTitle(view, date, weekStart) {
  if (view === 'month') return titleFmt({ month: 'long', year: 'numeric' }).format(date);
  if (view === 'day') return titleFmt({ weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }).format(date);
  const { start, end } = rangeFor(view, date, weekStart);
  const last = addDays(end, -1);
  const fmt = titleFmt({ month: 'short', day: 'numeric', year: 'numeric' });
  // formatRange gives "Oct 25 – 31, 2026"; a {day, year} format alone renders oddly in some locales.
  if (fmt.formatRange) return fmt.formatRange(start, last);
  return `${titleFmt({ month: 'short', day: 'numeric' }).format(start)} – ${fmt.format(last)}`;
}

// Normalize API items: Date objects plus local day keys for placement.
export function prepare(items) {
  return items.map((it) => {
    const s = new Date(it.start);
    const e = new Date(it.end);
    const startKey = it.all_day && it.start_date ? it.start_date : dateKey(s);
    const endKey = it.all_day && it.end_date ? it.end_date : dateKey(new Date(Math.max(s.getTime(), e.getTime() - 1)));
    return { ...it, s, e, startKey, endKey, multiDay: startKey !== endKey };
  });
}

export function itemsOnDay(items, day) {
  const key = dateKey(day);
  return items.filter((it) => it.startKey <= key && key <= it.endKey);
}

// Timed, single-day items get columns where they overlap (like every calendar app).
export function layoutDay(items) {
  const sorted = [...items].sort((a, b) => a.s - b.s || b.e - a.e);
  const placed = [];
  let cluster = [];
  let clusterEnd = 0;
  const flush = () => {
    const cols = [];
    for (const it of cluster) {
      let col = cols.findIndex((end) => end <= it.s.getTime());
      if (col < 0) { col = cols.length; cols.push(0); }
      cols[col] = Math.max(it.e.getTime(), it.s.getTime() + 20 * 60000);
      it._col = col;
    }
    for (const it of cluster) placed.push({ ...it, col: it._col, cols: cols.length });
    cluster = [];
  };
  for (const it of sorted) {
    if (cluster.length && it.s.getTime() >= clusterEnd) flush();
    cluster.push(it);
    clusterEnd = Math.max(clusterEnd, it.e.getTime(), it.s.getTime() + 20 * 60000);
  }
  flush();
  return placed;
}

export function minutesInDay(d, day) {
  return Math.max(0, Math.min(24 * 60, (d - startOfDay(day)) / 60000));
}

// -- recurrence -----------------------------------------------------------------------

const RRULE_DAYS = ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'];
const ORD = { 1: 'first', 2: 'second', 3: 'third', 4: 'fourth', 5: 'fifth', '-1': 'last' };

function weekdayName(d, style = 'long') {
  return new Intl.DateTimeFormat(undefined, { weekday: style }).format(d);
}

export function nthOfMonth(d) {
  const n = Math.ceil(d.getDate() / 7);
  const isLast = addDays(d, 7).getMonth() !== d.getMonth();
  return isLast && n >= 4 ? -1 : n;
}

export function repeatPresets(d) {
  const wd = RRULE_DAYS[d.getDay()];
  const n = nthOfMonth(d);
  return [
    { id: 'none', label: 'Does not repeat', rule: null },
    { id: 'daily', label: 'Every day', rule: 'FREQ=DAILY' },
    { id: 'weekdays', label: 'Every weekday (Mon–Fri)', rule: 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR' },
    { id: 'weekly', label: `Weekly on ${weekdayName(d)}`, rule: `FREQ=WEEKLY;BYDAY=${wd}` },
    { id: 'monthly_day', label: `Monthly on day ${d.getDate()}`, rule: `FREQ=MONTHLY;BYMONTHDAY=${d.getDate()}` },
    { id: 'monthly_nth', label: `Monthly on the ${ORD[n]} ${weekdayName(d)}`, rule: `FREQ=MONTHLY;BYDAY=${n}${wd}` },
    { id: 'yearly', label: `Every year on ${new Intl.DateTimeFormat(undefined, { month: 'long', day: 'numeric' }).format(d)}`, rule: 'FREQ=YEARLY' },
    { id: 'custom', label: 'Custom…', rule: undefined },
  ];
}

export function parseRule(rule) {
  const out = { freq: 'WEEKLY', interval: 1, byday: [], bymonthday: null, count: null, until: null };
  if (!rule) return out;
  for (const part of rule.split(';')) {
    const [k, v] = part.split('=');
    if (k === 'FREQ') out.freq = v;
    else if (k === 'INTERVAL') out.interval = Number(v) || 1;
    else if (k === 'BYDAY') out.byday = v.split(',').filter(Boolean);
    else if (k === 'BYMONTHDAY') out.bymonthday = Number(v.split(',')[0]);
    else if (k === 'COUNT') out.count = Number(v);
    else if (k === 'UNTIL') out.until = v;
  }
  return out;
}

export function untilToDateKey(until) {
  if (!until) return '';
  const m = /^(\d{4})(\d{2})(\d{2})(T(\d{2})(\d{2})(\d{2})Z)?$/.exec(until);
  if (!m) return '';
  if (!m[4]) return `${m[1]}-${m[2]}-${m[3]}`;
  return dateKey(new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[5], +m[6], +m[7])));
}

export function buildRule({ freq, interval, byday, bymonthday, ends, until, count }) {
  const parts = [`FREQ=${freq}`];
  if (interval > 1) parts.push(`INTERVAL=${interval}`);
  if (freq === 'WEEKLY' && byday?.length) parts.push(`BYDAY=${byday.join(',')}`);
  if (freq === 'MONTHLY' && byday?.length) parts.push(`BYDAY=${byday.join(',')}`);
  if (freq === 'MONTHLY' && !byday?.length && bymonthday) parts.push(`BYMONTHDAY=${bymonthday}`);
  if (ends === 'after' && count) parts.push(`COUNT=${count}`);
  if (ends === 'on' && until) parts.push(`UNTIL=${until.replace(/-/g, '')}`);
  return parts.join(';');
}

export function stripEnd(rule) {
  return (rule || '').split(';').filter((p) => !p.startsWith('COUNT=') && !p.startsWith('UNTIL=')).join(';');
}

export function presetFor(rule, d) {
  if (!rule) return 'none';
  const parsed = parseRule(rule);
  if (parsed.count || parsed.until) return 'custom';
  const match = repeatPresets(d).find((p) => p.rule && p.rule === stripEnd(rule));
  return match ? match.id : 'custom';
}

export function describeRule(rule, start) {
  if (!rule) return '';
  const r = parseRule(rule);
  const every = (unit) => (r.interval > 1 ? `Every ${r.interval} ${unit}s` : unit === 'day' ? 'Daily' : unit === 'week' ? 'Weekly'
    : unit === 'month' ? 'Monthly' : 'Yearly');
  const dayNames = r.byday.map((code) => {
    const m = /^(-?\d)?([A-Z]{2})$/.exec(code);
    if (!m) return code;
    const base = new Date(2026, 0, 4 + RRULE_DAYS.indexOf(m[2]));
    const name = weekdayName(base, m[1] ? 'long' : 'short');
    return m[1] ? `the ${ORD[m[1]]} ${name}` : name;
  });
  let text;
  if (r.freq === 'DAILY') text = every('day');
  else if (r.freq === 'WEEKLY') {
    const weekdays = r.byday.join(',') === 'MO,TU,WE,TH,FR';
    text = weekdays && r.interval === 1 ? 'Every weekday' : `${every('week')} on ${dayNames.join(', ') || weekdayName(start)}`;
  } else if (r.freq === 'MONTHLY') {
    text = `${every('month')} on ${dayNames.length ? dayNames.join(', ') : `day ${r.bymonthday || start.getDate()}`}`;
  } else text = every('year');
  if (r.count) text += `, ${r.count} times`;
  if (r.until) text += `, until ${new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(fromDateKey(untilToDateKey(r.until)))}`;
  return text;
}

export { RRULE_DAYS };
