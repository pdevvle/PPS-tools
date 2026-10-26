// Display formatting for dates, durations, money and names (browser timezone & locale).

const LOCALE = undefined; // user's browser locale

const fmtCache = new Map();
function dtf(opts) {
  const key = JSON.stringify(opts);
  if (!fmtCache.has(key)) fmtCache.set(key, new Intl.DateTimeFormat(LOCALE, opts));
  return fmtCache.get(key);
}

export function toDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtTime(value) {
  const d = toDate(value);
  return d ? dtf({ hour: 'numeric', minute: '2-digit' }).format(d) : '';
}

// "9 AM" when on the hour, else "9:30 AM" — compact for schedules.
export function fmtTimeShort(value) {
  const d = toDate(value);
  if (!d) return '';
  if (d.getMinutes() === 0) return dtf({ hour: 'numeric' }).format(d);
  return dtf({ hour: 'numeric', minute: '2-digit' }).format(d);
}

export function fmtDate(value, { weekday = false, year } = {}) {
  const d = toDate(value);
  if (!d) return '';
  const showYear = year ?? d.getFullYear() !== new Date().getFullYear();
  return dtf({ weekday: weekday ? 'short' : undefined, month: 'short', day: 'numeric', year: showYear ? 'numeric' : undefined }).format(d);
}

export function fmtDateLong(value) {
  const d = toDate(value);
  return d ? dtf({ weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }).format(d) : '';
}

export function fmtDateTime(value) {
  const d = toDate(value);
  return d ? `${fmtDate(d, { weekday: true })}, ${fmtTime(d)}` : '';
}

export function fmtFull(value) {
  const d = toDate(value);
  return d ? `${fmtDateLong(d)} at ${fmtTime(d)}` : '';
}

export function fmtWeekday(value, style = 'short') {
  const d = toDate(value);
  return d ? dtf({ weekday: style }).format(d) : '';
}

function startOfDay(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

// Conversation-list style: today -> time, yesterday, weekday, date.
export function fmtRelative(value) {
  const d = toDate(value);
  if (!d) return '';
  const today = startOfDay(new Date());
  const day = startOfDay(d);
  const diffDays = Math.round((today - day) / 86400000);
  if (diffDays === 0) return fmtTime(d);
  if (diffDays === 1) return 'Yesterday';
  if (diffDays > 1 && diffDays < 7) return fmtWeekday(d);
  if (diffDays === -1) return 'Tomorrow';
  return fmtDate(d);
}

export function fmtAgo(value, now = Date.now()) {
  const d = toDate(value);
  if (!d) return '';
  const s = Math.round((now - d.getTime()) / 1000);
  if (s < 45) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)}d ago`;
  return fmtDate(d);
}

// "in 2h", "tomorrow 8 AM", "Mon 9 AM", "Oct 3".
export function fmtUntil(value, now = Date.now()) {
  const d = toDate(value);
  if (!d) return '';
  const s = Math.round((d.getTime() - now) / 1000);
  if (s < 0) return fmtAgo(value, now);
  if (s < 3600) return `in ${Math.max(1, Math.round(s / 60))}m`;
  const today = startOfDay(new Date(now));
  const days = Math.round((startOfDay(d) - today) / 86400000);
  if (days === 0) return `today ${fmtTimeShort(d)}`;
  if (days === 1) return `tomorrow ${fmtTimeShort(d)}`;
  if (days < 7) return `${fmtWeekday(d)} ${fmtTimeShort(d)}`;
  return fmtDate(d);
}

export function fmtDuration(minutes) {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) return '';
  const m = Math.round(minutes);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h}h ${r}m` : `${h}h`;
}

export function fmtHours(minutes, digits = 1) {
  if (minutes === null || minutes === undefined) return '';
  const h = minutes / 60;
  return `${Number.isInteger(h) ? h : h.toFixed(digits)}h`;
}

// Running clock "1:05:09" for elapsed seconds.
export function fmtClock(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

const money = new Intl.NumberFormat(LOCALE, { style: 'currency', currency: 'USD' });
const money0 = new Intl.NumberFormat(LOCALE, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
export function fmtMoney(n, { whole = false } = {}) {
  if (n === null || n === undefined || n === '' || Number.isNaN(Number(n))) return '';
  return (whole ? money0 : money).format(Number(n));
}

const num = new Intl.NumberFormat(LOCALE);
export function fmtNumber(n) {
  return n === null || n === undefined ? '' : num.format(n);
}

export function fmtBytes(n) {
  if (!n && n !== 0) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function initials(name) {
  const parts = String(name || '').split(/[\s._@-]+/).filter(Boolean);
  if (!parts.length) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function firstName(name) {
  return String(name || '').trim().split(/\s+/)[0] || '';
}

export function plural(n, word, pluralWord) {
  return `${fmtNumber(n)} ${n === 1 ? word : pluralWord || word + 's'}`;
}

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function stripHtml(markup) {
  if (!markup) return '';
  const doc = new DOMParser().parseFromString(markup, 'text/html');
  return (doc.body.textContent || '').replace(/\s+/g, ' ').trim();
}

// Name for a {name, handle} participant.
export function participantName(p) {
  if (!p) return '';
  return p.name || p.handle || '';
}

export function capitalize(s) {
  return s ? s[0].toUpperCase() + s.slice(1) : '';
}

export function titleCase(s) {
  return String(s || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
