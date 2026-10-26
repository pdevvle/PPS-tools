// Date math in the browser's local time. Instants travel as ISO strings (UTC);
// calendar days as 'YYYY-MM-DD' keys.

export const DAY_MS = 86400000;

export function parseISO(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function startOfDay(d) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

export function endOfDay(d) {
  const x = new Date(d);
  x.setHours(23, 59, 59, 999);
  return x;
}

export function addDays(d, n) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

export function addMinutes(d, n) {
  return new Date(new Date(d).getTime() + n * 60000);
}

export function addMonths(d, n) {
  const x = new Date(d);
  const day = x.getDate();
  x.setDate(1);
  x.setMonth(x.getMonth() + n);
  x.setDate(Math.min(day, daysInMonth(x)));
  return x;
}

export function daysInMonth(d) {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
}

// weekStart: 0 = Sunday, 1 = Monday
export function startOfWeek(d, weekStart = 0) {
  const x = startOfDay(d);
  const diff = (x.getDay() - weekStart + 7) % 7;
  return addDays(x, -diff);
}

export function startOfMonth(d) {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

export function isSameDay(a, b) {
  const x = parseISO(a);
  const y = parseISO(b);
  return !!x && !!y && x.getFullYear() === y.getFullYear() && x.getMonth() === y.getMonth() && x.getDate() === y.getDate();
}

export function isToday(d) {
  return isSameDay(d, new Date());
}

const pad = (n) => String(n).padStart(2, '0');

export function dateKey(d) {
  const x = parseISO(d);
  return `${x.getFullYear()}-${pad(x.getMonth() + 1)}-${pad(x.getDate())}`;
}

export function fromDateKey(key) {
  const [y, m, d] = String(key).split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function timeKey(d) {
  const x = parseISO(d);
  return `${pad(x.getHours())}:${pad(x.getMinutes())}`;
}

// '2026-10-26' + '08:30' (local) -> Date
export function combine(day, hhmm) {
  const base = typeof day === 'string' ? fromDateKey(day) : startOfDay(day);
  const [h, m] = String(hhmm || '00:00').split(':').map(Number);
  base.setHours(h, m || 0, 0, 0);
  return base;
}

// <input type="datetime-local"> value <-> ISO
export function toLocalInput(value) {
  const d = parseISO(value);
  return d ? `${dateKey(d)}T${timeKey(d)}` : '';
}

export function fromLocalInput(value) {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

export function minutesBetween(a, b) {
  return (parseISO(b) - parseISO(a)) / 60000;
}

export function overlaps(aStart, aEnd, bStart, bEnd) {
  return parseISO(aStart) < parseISO(bEnd) && parseISO(bStart) < parseISO(aEnd);
}

export function minutesOfDay(d) {
  const x = parseISO(d);
  return x.getHours() * 60 + x.getMinutes();
}

export function weekdayLabels(weekStart = 0, style = 'short') {
  const base = startOfWeek(new Date(2026, 0, 4), weekStart); // any week
  const f = new Intl.DateTimeFormat(undefined, { weekday: style });
  return Array.from({ length: 7 }, (_, i) => f.format(addDays(base, i)));
}

// 6 rows x 7 days covering the month of `d`.
export function monthGrid(d, weekStart = 0) {
  const first = startOfWeek(startOfMonth(d), weekStart);
  return Array.from({ length: 6 }, (_, r) => Array.from({ length: 7 }, (_, c) => addDays(first, r * 7 + c)));
}

export function roundTo(d, minutes) {
  const ms = minutes * 60000;
  return new Date(Math.round(parseISO(d).getTime() / ms) * ms);
}

// Quick picks for snooze / send later / reminders / due dates.
export function presets(now = new Date()) {
  const at = (day, h, m = 0) => { const x = new Date(day); x.setHours(h, m, 0, 0); return x; };
  const tomorrow = addDays(now, 1);
  const nextMonday = addDays(startOfDay(now), ((8 - now.getDay()) % 7) || 7);
  const out = [];
  const inHours = new Date(now.getTime() + 3 * 3600000);
  if (now.getHours() < 17) out.push({ id: 'later', label: 'Later today', date: inHours.getHours() < 18 ? roundTo(inHours, 30) : at(now, 18) });
  out.push({ id: 'tomorrow', label: 'Tomorrow morning', date: at(tomorrow, 8) });
  out.push({ id: 'tomorrow_pm', label: 'Tomorrow afternoon', date: at(tomorrow, 13) });
  if (now.getDay() >= 1 && now.getDay() <= 4) out.push({ id: 'weekend', label: 'This weekend', date: at(addDays(startOfDay(now), 6 - now.getDay()), 9) });
  out.push({ id: 'next_week', label: 'Next week', date: at(nextMonday, 8) });
  out.push({ id: 'next_month', label: 'In a month', date: at(addMonths(now, 1), 8) });
  return out;
}
