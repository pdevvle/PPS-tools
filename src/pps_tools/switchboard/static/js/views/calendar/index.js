// Calendar: /calendar?view=month|week|day|agenda&date=YYYY-MM-DD (&event=<id> opens one)

import { html, useEffect, useLayoutEffect, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch, useIsMobile, useLocalStorage, useNow } from '../../lib/hooks.js';
import { setQuery } from '../../lib/router.js';
import { setting, useStore } from '../../lib/store.js';
import { useHotkeys } from '../../lib/shortcuts.js';
import {
  addDays, addMonths, dateKey, fromDateKey, isToday, monthGrid, startOfDay, startOfMonth, weekdayLabels,
} from '../../lib/dates.js';
import { fmtTime, fmtTimeShort } from '../../lib/format.js';
import {
  Button, Checkbox, ColorChoices, Empty, ErrorBox, Field, Icon, IconButton, Input, Loading, PageHeader, Segmented, Toggle, cx,
} from '../../ui/components.js';
import { Modal, confirmDialog, openModal, promptDialog, showMenu, showPopover, toast, toastError } from '../../ui/overlay.js';
import { ModuleLayout, SidebarButton, SidebarHeader, SidebarSection } from '../../ui/layout.js';
import { registerCommands } from '../../ui/palette.js';
import { EventPopover, askScope, kindIcon, openEditor, whenText } from './editor.js';
import {
  HOUR_PX, SNAP_MIN, VIEWS, itemsOnDay, layoutDay, minutesInDay, prepare, rangeFor, rangeTitle, step,
} from './util.js';

const OVERLAYS = [
  ['shifts', 'My shifts', 'clock'],
  ['all_shifts', "Everyone's shifts", 'users'],
  ['operations', 'My scheduled job work', 'factory'],
  ['jobs', 'Job due dates', 'square-kanban'],
  ['timeoff', 'Time off', 'plane'],
];

// -- sidebar ------------------------------------------------------------------------

function MiniMonth({ date, onPick, weekStart }) {
  const [month, setMonth] = useState(startOfMonth(date));
  useEffect(() => setMonth(startOfMonth(date)), [dateKey(startOfMonth(date))]);
  const grid = monthGrid(month, weekStart);
  const labels = weekdayLabels(weekStart, 'narrow');
  return html`<div class="mini-month">
    <div class="mini-month-head">
      <span class="mini-month-title">${new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(month)}</span>
      <${IconButton} icon="chevron-left" size="sm" label="Previous month" onClick=${() => setMonth(addMonths(month, -1))} />
      <${IconButton} icon="chevron-right" size="sm" label="Next month" onClick=${() => setMonth(addMonths(month, 1))} />
    </div>
    <div class="mini-month-grid">
      ${labels.map((l, i) => html`<span key=${'l' + i} class="mini-month-dow">${l}</span>`)}
      ${grid.flat().map((d) => html`<button type="button" key=${dateKey(d)}
        class=${cx('mini-month-day', d.getMonth() !== month.getMonth() && 'is-other', isToday(d) && 'is-today', dateKey(d) === dateKey(date) && 'is-selected')}
        onClick=${() => onPick(d)} aria-label=${new Intl.DateTimeFormat(undefined, { dateStyle: 'full' }).format(d)}>${d.getDate()}</button>`)}
    </div>
  </div>`;
}

function AddCalendarForm({ close, onDone }) {
  const [form, setForm] = useState({ kind: 'shared', name: '', color: '#0c8599', ics_url: '', private: false });
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setForm({ ...form, [k]: v });
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await api.post('/calendars', form);
      if (res.calendar.sync_error) toast(`Added, but couldn't load it yet: ${res.calendar.sync_error}`, { tone: 'danger' });
      else toast('Calendar added');
      close();
      onDone();
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  return html`<${Modal} title="Add a calendar" icon="calendar-plus" onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="cal-form" loading=${busy}>Add calendar</${Button}>`}>
    <form id="cal-form" class="stack" onSubmit=${submit}>
      <${Segmented} value=${form.kind} onChange=${set('kind')} options=${[{ value: 'shared', label: 'New shared calendar' }, { value: 'subscription', label: 'Subscribe by URL' }]} />
      <${Field} label="Name"><${Input} value=${form.name} onValue=${set('name')} required autoFocus placeholder=${form.kind === 'shared' ? 'Deliveries' : 'US holidays'} /></${Field}>
      ${form.kind === 'subscription' && html`
        <${Field} label="Calendar link (iCal / .ics)" hint="In Google Calendar: Settings → your calendar → “Secret address in iCal format”. Refreshes every 30 minutes.">
          <${Input} type="url" value=${form.ics_url} onValue=${set('ics_url')} required placeholder="https://… or webcal://…" /></${Field}>
        <${Toggle} checked=${form.private} onChange=${set('private')} label="Only visible to me" />`}
      <${Field} label="Color"><${ColorChoices} value=${form.color} onChange=${set('color')} /></${Field}>
    </form>
  </${Modal}>`;
}

function CalendarSidebar({ date, onPickDate, calendars, hidden, setHidden, overlays, setOverlays, reloadCalendars, weekStart }) {
  const toggleCal = (id) => setHidden(hidden.includes(id) ? hidden.filter((x) => x !== id) : [...hidden, id]);
  const toggleOverlay = (k) => setOverlays(overlays.includes(k) ? overlays.filter((x) => x !== k) : [...overlays, k]);
  const menu = (e, c) => {
    const items = [];
    if (c.can_manage) items.push({ label: 'Rename', icon: 'pencil', onSelect: async () => {
      const name = await promptDialog({ title: 'Rename calendar', value: c.name });
      if (name) api.patch(`/calendars/${c.id}`, { name }).then(reloadCalendars).catch(toastError);
    } });
    if (c.can_manage) items.push({ label: 'Change color', icon: 'palette', onSelect: () => showPopover(e.target, (close) => html`<div class="color-picker"><${ColorChoices} value=${c.color}
      onChange=${(color) => { close(); api.patch(`/calendars/${c.id}`, { color }).then(reloadCalendars).catch(toastError); }} /></div>`, { width: 196 }) });
    if (c.kind === 'subscription') items.push({ label: 'Refresh now', icon: 'refresh-cw', hint: c.sync_error || undefined, onSelect: () => api.post(`/calendars/${c.id}/sync`).then((r) => { toast(r.calendar.sync_error ? `Couldn't refresh: ${r.calendar.sync_error}` : `Refreshed (${r.imported} events)`); reloadCalendars(); }).catch(toastError) });
    items.push({ label: 'Download .ics', icon: 'download', onSelect: () => window.open(`/api/calendars/${c.id}/export.ics`, '_blank') });
    if (c.can_manage) {
      items.push({ divider: true });
      items.push({ label: 'Delete calendar', icon: 'trash', danger: true, onSelect: async () => {
        if (!(await confirmDialog({ title: `Delete “${c.name}”?`, message: 'All of its events are deleted too.', danger: true, confirmLabel: 'Delete' }))) return;
        api.del(`/calendars/${c.id}`).then(reloadCalendars).catch(toastError);
      } });
    }
    showMenu(e.currentTarget, items);
  };
  return html`
    <${SidebarHeader} title="Calendar" actions=${html`<${IconButton} icon="calendar-plus" label="Add calendar"
      onClick=${() => openModal((close) => html`<${AddCalendarForm} close=${close} onDone=${reloadCalendars} />`)} />`} />
    <div class="cal-side-mini"><${MiniMonth} date=${date} onPick=${onPickDate} weekStart=${weekStart} /></div>
    <${SidebarSection} title="Calendars">
      ${calendars.map((c) => html`<div class="cal-side-item" key=${c.id}>
        <label class="cal-side-check" style=${{ '--cal': c.color || 'var(--accent)' }}>
          <input type="checkbox" checked=${!hidden.includes(c.id)} onChange=${() => toggleCal(c.id)} />
          <span class="cal-side-box"><${Icon} name="check" size=${11} strokeWidth=${3} /></span>
          <span class="cal-side-name">${c.name}</span>
          ${c.kind === 'personal' && html`<${Icon} name="lock" size=${12} class="cal-side-kind" title="Only you" />`}
          ${c.kind === 'subscription' && html`<${Icon} name=${c.sync_error ? 'triangle-alert' : 'link'} size=${12} class=${cx('cal-side-kind', c.sync_error && 'is-error')} title=${c.sync_error || 'Subscribed'} />`}
        </label>
        <button type="button" class="sidebar-item-menu" aria-label=${`${c.name} options`} onClick=${(e) => menu(e, c)}><${Icon} name="ellipsis" size=${14} /></button>
      </div>`)}
    </${SidebarSection}>
    <${SidebarSection} title="Show on calendar">
      ${OVERLAYS.map(([k, label, icon]) => html`<label class="cal-side-overlay" key=${k}>
        <${Checkbox} checked=${overlays.includes(k)} onChange=${() => toggleOverlay(k)} />
        <${Icon} name=${icon} size=${14} /><span>${label}</span>
      </label>`)}
    </${SidebarSection}>
    <div class="cal-side-foot"><a href="/settings/profile"><${Icon} name="smartphone" size=${13} /> Get your shifts on your phone</a></div>
  `;
}

// -- shared bits --------------------------------------------------------------------

function itemStyle(it) {
  return { '--ev': it.color || 'var(--accent)' };
}

function Chip({ it, onOpen, draggable, onDragStart }) {
  const timed = !it.all_day && !it.multiDay;
  return html`<button type="button" class=${cx('cal-chip', timed ? 'is-timed' : 'is-allday', it.read_only && 'is-overlay', it.done && 'is-done')}
    style=${itemStyle(it)} title=${`${it.title}\n${whenText(it)}`} draggable=${draggable} onDragStart=${onDragStart}
    onClick=${(e) => { e.stopPropagation(); onOpen(it, e.currentTarget); }}>
    ${timed && html`<span class="cal-chip-dot"></span><span class="cal-chip-time">${fmtTimeShort(it.s)}</span>`}
    ${it.kind !== 'event' && html`<${Icon} name=${kindIcon(it.kind)} size=${11} />`}
    <span class="cal-chip-title">${it.title}</span>
  </button>`;
}

// -- month --------------------------------------------------------------------------

function MonthView({ grid, date, items, onOpen, onCreate, onMoveDays, weekStart, onPickDay, compact }) {
  const labels = weekdayLabels(weekStart, compact ? 'narrow' : 'short');
  const [dragging, setDragging] = useState(null);
  const [over, setOver] = useState(null);
  const more = (e, day, list) => {
    e.stopPropagation();
    showPopover(e.currentTarget, (close) => html`<div class="cal-more">
      <div class="cal-more-title">${new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'short', day: 'numeric' }).format(day)}</div>
      ${list.map((it) => html`<${Chip} key=${it.id} it=${it} onOpen=${(x, el) => { close(); onOpen(x, el); }} />`)}
    </div>`, { width: 260 });
  };
  return html`<div class="cal-month">
    <div class="cal-month-head">${labels.map((l, i) => html`<div key=${i} class="cal-month-dow">${l}</div>`)}</div>
    <div class="cal-month-grid">
      ${grid.map((week, wi) => html`<div class="cal-month-week" key=${wi}>
        ${week.map((day) => {
    const key = dateKey(day);
    const list = itemsOnDay(items, day).sort((a, b) => (b.all_day || b.multiDay) - (a.all_day || a.multiDay) || a.s - b.s);
    const max = compact ? 0 : 3;
    return html`<div key=${key}
            class=${cx('cal-month-cell', day.getMonth() !== date.getMonth() && 'is-other', isToday(day) && 'is-today', over === key && 'is-drop')}
            onClick=${() => onCreate(day)}
            onDragOver=${(e) => { if (dragging) { e.preventDefault(); setOver(key); } }}
            onDragLeave=${() => setOver((o) => (o === key ? null : o))}
            onDrop=${(e) => { e.preventDefault(); setOver(null); if (dragging) onMoveDays(dragging.it, Math.round((fromDateKey(key) - fromDateKey(dragging.fromKey)) / 86400000)); setDragging(null); }}>
            <button type="button" class="cal-month-num" onClick=${(e) => { e.stopPropagation(); onPickDay(day); }}>${day.getDate()}</button>
            ${compact
    ? (list.length > 0 && html`<div class="cal-month-dots">${list.slice(0, 4).map((it) => html`<span key=${it.id} class="cal-dot" style=${itemStyle(it)}></span>`)}</div>`)
    : html`<div class="cal-month-items">
                ${list.slice(0, max).map((it) => html`<${Chip} key=${it.id} it=${it} onOpen=${onOpen}
                  draggable=${it.can_edit} onDragStart=${(e) => { setDragging({ it, fromKey: key }); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', it.id); }} />`)}
                ${list.length > max && html`<button type="button" class="cal-month-more" onClick=${(e) => more(e, day, list)}>+${list.length - max} more</button>`}
              </div>`}
          </div>`;
  })}
      </div>`)}
    </div>
  </div>`;
}

// -- week / day time grid -----------------------------------------------------------

function snap(min) {
  return Math.round(min / SNAP_MIN) * SNAP_MIN;
}

function TimeGrid({ days, items, onOpen, onCreateRange, onCommit, onPickDay }) {
  const now = useNow(60000);
  const scrollRef = useRef(null);
  const gridRef = useRef(null);
  const colRefs = useRef([]);
  const dragRef = useRef(null);
  const [ghost, setGhost] = useState(null);
  const keys = days.map(dateKey);
  const allDay = items.filter((it) => it.all_day || it.multiDay);
  const timed = items.filter((it) => !it.all_day && !it.multiDay);

  useLayoutEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 7 * HOUR_PX - 8;
  }, [keys.join()]);

  const colAt = (clientX) => {
    for (let i = 0; i < colRefs.current.length; i++) {
      const el = colRefs.current[i];
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (clientX >= r.left && clientX < r.right) return i;
    }
    return null;
  };
  const minuteAt = (clientY, i) => {
    const el = colRefs.current[i] || colRefs.current[0];
    const r = el.getBoundingClientRect();
    return Math.max(0, Math.min(24 * 60, ((clientY - r.top) / HOUR_PX) * 60));
  };

  const onDown = (e, i, it = null) => {
    if (e.button !== 0) return;
    const resize = !!(e.target.closest && e.target.closest('.tg-resize'));
    const anchorEl = it ? e.currentTarget : null;
    if (it) {
      e.stopPropagation();
      if (it.read_only || !it.can_edit) {
        dragRef.current = { mode: 'open', it, anchorEl };
      } else {
        const s = minutesInDay(it.s, days[i]);
        const en = Math.max(s + 15, minutesInDay(it.e, days[i]) || 24 * 60);
        dragRef.current = { mode: resize ? 'resize' : 'move', it, anchorEl, day: i, startMin: s, endMin: en, grab: minuteAt(e.clientY, i) - s, x0: e.clientX, y0: e.clientY, moved: false };
      }
    } else {
      const m = snap(minuteAt(e.clientY, i));
      dragRef.current = { mode: 'create', day: i, anchor: m, startMin: m, endMin: m + 30, x0: e.clientX, y0: e.clientY, moved: false };
    }
    try { gridRef.current.setPointerCapture(e.pointerId); } catch { /* ignore */ }
  };
  const onMove = (e) => {
    const d = dragRef.current;
    if (!d || d.mode === 'open') return;
    if (!d.moved && Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 5) return;
    d.moved = true;
    const col = colAt(e.clientX);
    const m = minuteAt(e.clientY, col ?? d.day);
    if (d.mode === 'create') {
      const at = snap(m);
      d.startMin = Math.min(d.anchor, at);
      d.endMin = Math.max(d.anchor + SNAP_MIN, at);
    } else if (d.mode === 'move') {
      const len = d.endMin - d.startMin;
      const start = Math.max(0, Math.min(24 * 60 - len, snap(m - d.grab)));
      d.newStart = start;
      d.newEnd = start + len;
      if (col !== null) d.newDay = col;
    } else if (d.mode === 'resize') {
      d.newStart = d.startMin;
      d.newEnd = Math.max(d.startMin + SNAP_MIN, snap(m));
      d.newDay = d.day;
    }
    const day = d.mode === 'create' ? d.day : (d.newDay ?? d.day);
    const start = d.mode === 'create' ? d.startMin : d.newStart;
    const end = d.mode === 'create' ? d.endMin : d.newEnd;
    setGhost({ day, start, end, color: d.it?.color, title: d.it?.title || 'New event' });
  };
  const onUp = (e) => {
    const d = dragRef.current;
    dragRef.current = null;
    setGhost(null);
    if (!d) return;
    if (d.mode === 'open' || (!d.moved && d.it)) { onOpen(d.it, d.anchorEl); return; }
    const toDate = (dayIdx, min) => new Date(days[dayIdx].getTime() + min * 60000);
    if (d.mode === 'create') {
      const start = d.moved ? d.startMin : snap(minuteAt(e.clientY, d.day));
      const end = d.moved ? d.endMin : start + 60;
      onCreateRange(toDate(d.day, start), toDate(d.day, Math.min(end, 24 * 60)));
      return;
    }
    if (d.newStart === undefined) return;
    const dayIdx = d.newDay ?? d.day;
    onCommit(d.it, toDate(dayIdx, d.newStart), toDate(dayIdx, d.newEnd));
  };

  const nowMin = minutesInDay(new Date(now), startOfDay(new Date(now)));
  return html`<div class="tg" style=${{ '--days': days.length }}>
    <div class="tg-head">
      <div class="tg-gutter"></div>
      ${days.map((d) => html`<button type="button" key=${dateKey(d)} class=${cx('tg-day-head', isToday(d) && 'is-today')} onClick=${() => onPickDay(d)}>
        <span class="tg-dow">${new Intl.DateTimeFormat(undefined, { weekday: 'short' }).format(d)}</span>
        <span class="tg-date">${d.getDate()}</span>
      </button>`)}
    </div>
    <div class="tg-allday">
      <div class="tg-gutter tg-allday-label">all-day</div>
      ${days.map((d) => html`<div key=${dateKey(d)} class="tg-allday-cell">
        ${itemsOnDay(allDay, d).map((it) => html`<${Chip} key=${it.id} it=${it} onOpen=${onOpen} />`)}
      </div>`)}
    </div>
    <div class="tg-scroll" ref=${scrollRef}>
      <div class="tg-body" ref=${gridRef} style=${{ height: 24 * HOUR_PX + 'px' }} onPointerMove=${onMove} onPointerUp=${onUp}
        onPointerCancel=${() => { dragRef.current = null; setGhost(null); }}>
        <div class="tg-gutter tg-hours">
          ${Array.from({ length: 24 }, (_, h) => html`<div key=${h} class="tg-hour" style=${{ top: h * HOUR_PX + 'px' }}>
            ${h === 0 ? '' : fmtTimeShort(new Date(2026, 0, 1, h))}</div>`)}
        </div>
        ${days.map((day, i) => {
    const list = layoutDay(timed.filter((it) => it.startKey === keys[i]));
    return html`<div key=${keys[i]} class=${cx('tg-col', isToday(day) && 'is-today')} ref=${(el) => { colRefs.current[i] = el; }}
            onPointerDown=${(e) => onDown(e, i)}>
            ${list.map((it) => {
      const top = (minutesInDay(it.s, day) / 60) * HOUR_PX;
      const bottom = (Math.max(minutesInDay(it.e, day), minutesInDay(it.s, day) + 20) / 60) * HOUR_PX;
      const short = bottom - top < 34;
      return html`<div key=${it.id} class=${cx('tg-event', it.read_only && 'is-overlay', it.done && 'is-done', short && 'is-short', ghost && dragRef.current?.it?.id === it.id && 'is-dragging')}
                style=${{ ...itemStyle(it), top: top + 'px', height: Math.max(18, bottom - top - 2) + 'px',
      left: `calc(${(it.col / it.cols) * 100}% + 2px)`, width: `calc(${100 / it.cols}% - 4px)` }}
                role="button" tabIndex="0" aria-label=${`${it.title}, ${whenText(it)}`}
                onPointerDown=${(e) => onDown(e, i, it)} onKeyDown=${(e) => { if (e.key === 'Enter') onOpen(it, e.currentTarget); }}>
                <div class="tg-event-title">${it.kind !== 'event' && html`<${Icon} name=${kindIcon(it.kind)} size=${11} />`}${it.title}</div>
                ${!short && html`<div class="tg-event-time">${fmtTime(it.s)} – ${fmtTime(it.e)}${it.location ? ` · ${it.location}` : it.subtitle ? ` · ${it.subtitle}` : ''}</div>`}
                ${it.can_edit && !it.read_only && html`<div class="tg-resize" aria-hidden="true"></div>`}
              </div>`;
    })}
            ${ghost && ghost.day === i && html`<div class="tg-ghost" style=${{ '--ev': ghost.color || 'var(--accent)', top: (ghost.start / 60) * HOUR_PX + 'px',
      height: Math.max(16, ((ghost.end - ghost.start) / 60) * HOUR_PX - 2) + 'px' }}>
              <span>${fmtTime(new Date(day.getTime() + ghost.start * 60000))} – ${fmtTime(new Date(day.getTime() + ghost.end * 60000))}</span></div>`}
            ${isToday(day) && html`<div class="tg-now" style=${{ top: (nowMin / 60) * HOUR_PX + 'px' }}></div>`}
          </div>`;
  })}
      </div>
    </div>
  </div>`;
}

// -- agenda -------------------------------------------------------------------------

function AgendaView({ start, end, items, onOpen }) {
  const days = [];
  for (let d = start; d < end; d = addDays(d, 1)) {
    const list = itemsOnDay(items, d).sort((a, b) => (b.all_day || b.multiDay) - (a.all_day || a.multiDay) || a.s - b.s);
    if (list.length) days.push([d, list]);
  }
  if (!days.length) return html`<${Empty} icon="calendar" title="Nothing scheduled">Nothing in the next 30 days. Enjoy the calm.</${Empty}>`;
  return html`<div class="cal-agenda">
    ${days.map(([d, list]) => html`<section key=${dateKey(d)} class="cal-agenda-day">
      <div class=${cx('cal-agenda-date', isToday(d) && 'is-today')}>
        <span class="cal-agenda-dnum">${d.getDate()}</span>
        <span class="cal-agenda-dlabel">${new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short' }).format(d)}</span>
      </div>
      <div class="cal-agenda-items">
        ${list.map((it) => html`<button type="button" key=${it.id} class=${cx('cal-agenda-item', it.read_only && 'is-overlay', it.done && 'is-done')}
          style=${itemStyle(it)} onClick=${(e) => onOpen(it, e.currentTarget)}>
          <span class="cal-agenda-time">${it.all_day || it.multiDay ? 'All day' : `${fmtTimeShort(it.s)} – ${fmtTimeShort(it.e)}`}</span>
          <span class="cal-agenda-bar"></span>
          <span class="cal-agenda-text"><span class="cal-agenda-title">${it.kind !== 'event' && html`<${Icon} name=${kindIcon(it.kind)} size=${12} />`}${it.title}</span>
            ${(it.location || it.subtitle) && html`<span class="cal-agenda-sub">${it.location || it.subtitle}</span>`}</span>
        </button>`)}
      </div>
    </section>`)}
  </div>`;
}

// -- module -------------------------------------------------------------------------

export default function Calendar({ route }) {
  const mobile = useIsMobile();
  const weekStart = Number(setting('org.week_start', 0)) || 0;
  useStore((s) => s.settings);
  const view = VIEWS.includes(route.query.view) ? route.query.view : (mobile ? 'agenda' : 'week');
  const date = route.query.date ? fromDateKey(route.query.date) : startOfDay(new Date());
  const { start, end, grid } = rangeFor(view, date, weekStart);
  const [hidden, setHidden] = useLocalStorage('sb.cal.hidden', []);
  const [overlays, setOverlays] = useLocalStorage('sb.cal.overlays', ['shifts', 'operations', 'jobs', 'timeoff']);
  const cals = useFetch('/calendars', { refetchOn: ['calendar.changed'] });
  const calendars = cals.data?.items || [];
  const { data, loading, error, reload } = useFetch('/calendar/events', {
    query: { start: start.toISOString(), end: end.toISOString(), overlays: overlays.join(',') },
    refetchOn: ['calendar.changed', 'shift.changed', 'schedule.changed', 'timeoff.changed', 'job.changed'],
  });
  const items = prepare((data?.items || []).filter((it) => it.kind !== 'event' || !hidden.includes(it.calendar_id)));

  const go = (patch) => setQuery({ view: patch.view ?? route.query.view, date: patch.date ?? route.query.date, event: undefined });
  const goDate = (d) => go({ date: dateKey(d) });
  const create = (defaults) => openEditor({ defaults, calendars, onSaved: reload });
  const edit = (it) => openEditor({ item: it, calendars, onSaved: reload });
  const open = (it, anchor) => showPopover(anchor, (close) => html`<${EventPopover} it=${it} calendars=${calendars} close=${close} onEdit=${edit} onChanged=${reload} />`,
    { width: 340, placement: mobile ? 'bottom-start' : 'right-start' });

  const commitTimes = async (it, s, e, allDayDates) => {
    let scope = 'all';
    if (it.recurring) {
      scope = await askScope('Move');
      if (!scope) { reload(); return; }
    }
    const q = new URLSearchParams({ scope });
    if (it.recurring) q.set('original_start', it.original_start);
    const body = allDayDates ? { all_day: true, ...allDayDates } : { start_at: s.toISOString(), end_at: e.toISOString() };
    try {
      await api.patch(`/calendar/events/${it.event_id}?${q.toString()}`, body);
      reload({ quiet: true });
    } catch (err) { toastError(err); reload(); }
  };
  const moveDays = (it, delta) => {
    if (!delta || !it.can_edit) return;
    if (it.all_day) {
      const sd = dateKey(addDays(fromDateKey(it.start_date), delta));
      const ed = dateKey(addDays(fromDateKey(it.end_date), delta));
      commitTimes(it, null, null, { start_date: sd, end_date: ed });
    } else {
      commitTimes(it, addDays(it.s, delta), addDays(it.e, delta));
    }
  };

  // ?event=<id> deep link (notifications, search)
  useEffect(() => {
    const id = route.query.event;
    if (!id || !calendars.length) return;
    api.get(`/calendar/events/${id}`).then(({ event }) => {
      openModal((close) => html`<${Modal} title="Event" icon="calendar" onClose=${close} size="sm">
        <${EventPopover} it=${event} calendars=${calendars} close=${close} onEdit=${edit} onChanged=${reload} /></${Modal}>`);
    }).catch(() => toast("That event isn't available anymore"));
    setQuery({ event: undefined });
  }, [route.query.event, calendars.length]);

  useEffect(() => registerCommands(() => [
    { id: 'event-new', label: 'New event', icon: 'calendar-plus', group: 'Calendar', run: () => create({ start: new Date(Math.ceil(Date.now() / 1800000) * 1800000), end: new Date(Math.ceil(Date.now() / 1800000) * 1800000 + 3600000) }) },
  ]), [calendars.length]);
  useHotkeys({
    t: () => goDate(new Date()),
    j: () => goDate(step(view, date, 1)),
    k: () => goDate(step(view, date, -1)),
    arrowright: () => goDate(step(view, date, 1)),
    arrowleft: () => goDate(step(view, date, -1)),
    m: () => go({ view: 'month' }),
    w: () => go({ view: 'week' }),
    d: () => go({ view: 'day' }),
    a: () => go({ view: 'agenda' }),
    n: () => create({ start: new Date(Math.ceil(Date.now() / 1800000) * 1800000), end: new Date(Math.ceil(Date.now() / 1800000) * 1800000 + 3600000) }),
  });

  const sidebar = html`<${CalendarSidebar} date=${date} onPickDate=${goDate} calendars=${calendars} hidden=${hidden} setHidden=${setHidden}
    overlays=${overlays} setOverlays=${setOverlays} reloadCalendars=${() => { cals.reload(); reload(); }} weekStart=${weekStart} />`;
  const days = view === 'week' ? Array.from({ length: 7 }, (_, i) => addDays(start, i)) : [start];
  const viewOptions = [{ value: 'month', label: 'Month' }, { value: 'week', label: 'Week' }, { value: 'day', label: 'Day' }, { value: 'agenda', label: 'Agenda' }]
    .filter((o) => !mobile || o.value !== 'week');

  return html`<${ModuleLayout} sidebar=${sidebar} class="calendar-module">
    <${PageHeader} leading=${html`<${SidebarButton} />`} title=${rangeTitle(view, date, weekStart)}
      actions=${html`
        <${Button} size="sm" onClick=${() => goDate(new Date())}>Today</${Button}>
        <div class="row gap-1">
          <${IconButton} icon="chevron-left" label="Previous" onClick=${() => goDate(step(view, date, -1))} />
          <${IconButton} icon="chevron-right" label="Next" onClick=${() => goDate(step(view, date, 1))} />
        </div>
        <${Segmented} size="sm" value=${view} onChange=${(v) => go({ view: v })} options=${viewOptions} />
        <${Button} size="sm" variant="primary" icon="plus" onClick=${() => {
    const base = view === 'month' || view === 'agenda' ? new Date() : start;
    const s = new Date(Math.ceil(Math.max(base.getTime(), Date.now()) / 1800000) * 1800000);
    create({ start: s, end: new Date(s.getTime() + 3600000) });
  }}>Event</${Button}>`} />
    <div class=${cx('cal-body', `cal-view-${view}`)}>
      <${ErrorBox} error=${error} retry=${reload} />
      ${loading && !data && html`<div class="cal-loading"><${Loading} /></div>`}
      ${view === 'month' && html`<${MonthView} grid=${grid} date=${date} items=${items} onOpen=${open} weekStart=${weekStart} compact=${mobile}
        onCreate=${(day) => (mobile ? go({ view: 'day', date: dateKey(day) }) : create({ start: new Date(day.getFullYear(), day.getMonth(), day.getDate(), 9), end: new Date(day.getFullYear(), day.getMonth(), day.getDate(), 10) }))}
        onPickDay=${(day) => go({ view: 'day', date: dateKey(day) })} onMoveDays=${moveDays} />`}
      ${(view === 'week' || view === 'day') && html`<${TimeGrid} days=${days} items=${items} onOpen=${open}
        onCreateRange=${(s, e) => create({ start: s, end: e })} onCommit=${(it, s, e) => commitTimes(it, s, e)}
        onPickDay=${(day) => go({ view: 'day', date: dateKey(day) })} />`}
      ${view === 'agenda' && html`<${AgendaView} start=${start} end=${end} items=${items} onOpen=${open} />`}
    </div>
  </${ModuleLayout}>`;
}
