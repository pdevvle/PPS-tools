// Production schedule: job steps on a timeline, one row per piece of equipment or per
// person. Drag blocks to move them (or onto another row), drag the right edge to
// resize, drop unscheduled steps from the queue, and let auto-schedule fill the week.

import { html, useEffect, useLayoutEffect, useMemo, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { boot, can, me, setting, useStore, user as lookupUser } from '../../lib/store.js';
import { navigate, setQuery } from '../../lib/router.js';
import { useFetch, useIsMobile, useNow } from '../../lib/hooks.js';
import {
  addDays, addMinutes, dateKey, fromDateKey, isSameDay, minutesOfDay, parseISO, startOfDay, startOfWeek,
} from '../../lib/dates.js';
import { fmtDate, fmtDateTime, fmtDuration, fmtTimeShort, fmtWeekday } from '../../lib/format.js';
import {
  Avatar, Banner, Button, Empty, ErrorBox, Icon, IconButton, Loading, PageHeader, Segmented, cx,
} from '../../ui/components.js';
import { SidebarButton } from '../../ui/layout.js';
import { Modal, openModal, showPopover, toast, toastError } from '../../ui/overlay.js';
import { DateTimeButton, pickFromList, pickUsers } from '../../ui/pickers.js';
import { DueChip, PriorityChip, STATUS_LABEL, resourceOf } from './common.js';

const LANE_H = 46;
const SNAP = 15;
const EVENTS = ['schedule.changed', 'job.changed', 'settings.changed'];

function hhmmToMinutes(s, fallback) {
  if (!s) return fallback;
  const [h, m] = s.split(':').map(Number);
  return h * 60 + (m || 0);
}

function assignLanes(blocks) {
  const sorted = [...blocks].sort((a, b) => (a.start_at < b.start_at ? -1 : a.start_at > b.start_at ? 1 : a.id - b.id));
  const ends = [];
  const lanes = {};
  for (const b of sorted) {
    let lane = ends.findIndex((end) => end <= b.start_at);
    if (lane === -1) { lane = ends.length; ends.push(b.end_at); } else ends[lane] = b.end_at;
    lanes[b.id] = lane;
  }
  return { lanes, count: Math.max(1, ends.length) };
}

function rowKey(id) {
  return id === null || id === undefined ? 'none' : String(id);
}

async function patchOp(id, fields) {
  return api.patch(`/operations/${id}`, fields);
}

// -- popovers & modals --------------------------------------------------------------

function BlockDetails({ block, group, close, onChanged }) {
  const manage = can('manage_jobs');
  const myId = me().id;
  const canWork = manage || block.user_id === myId;
  const res = resourceOf(block.resource_id);
  const save = async (fields) => {
    try { await patchOp(block.id, fields); onChanged(); close(); } catch (err) { toastError(err); }
  };
  return html`<div class="sched-pop">
    <div class="sched-pop-head">
      <span class="job-number">${block.job_number}</span>
      <${PriorityChip} priority=${block.job_priority} />
      <span class="grow"></span>
      <${IconButton} icon="x" size="sm" label="Close" onClick=${close} />
    </div>
    <a class="sched-pop-title" href=${`/jobs/${block.job_id}`} onClick=${close}>${block.job_title}</a>
    ${block.customer && html`<div class="muted text-sm">${block.customer}</div>`}
    <div class="sched-pop-step">
      <span class=${cx('op-status-dot', `is-${block.status}`)}></span><b>${block.name}</b>
      <span class="muted text-sm">${STATUS_LABEL[block.status]}</span>
    </div>
    <div class="kv">
      <div class="kv-row"><dt>When</dt><dd>${fmtDateTime(block.start_at)} – ${fmtTimeShort(block.end_at)} (${fmtDuration(block.duration_minutes)})</dd></div>
      <div class="kv-row"><dt>Equipment</dt><dd>${manage
    ? html`<button type="button" class="btn btn-link" onClick=${(e) => pickFromList(e.currentTarget, {
      items: [{ id: 0, label: 'No equipment', icon: 'x' }, ...boot('resources').filter((r) => r.is_active).map((r) => ({ id: r.id, label: r.name, color: r.color, hint: r.kind }))],
      selected: block.resource_id || 0, multi: false, onChange: (id) => save({ resource_id: id || null }),
    })}>${res ? res.name : 'None'}</button>`
    : (res ? res.name : 'None')}</dd></div>
      <div class="kv-row"><dt>Person</dt><dd>${manage
    ? html`<button type="button" class="btn btn-link" onClick=${(e) => pickUsers(e.currentTarget, {
      multi: false, selected: block.user_id ? [block.user_id] : [], title: 'Who does this step?',
      extra: [{ id: 0, label: 'Nobody yet', icon: 'user-x' }], onChange: (id) => save({ user_id: id || null }),
    })}>${block.user_id ? lookupUser(block.user_id).name : 'Unassigned'}</button>`
    : (block.user_id ? lookupUser(block.user_id).name : 'Unassigned')}</dd></div>
      ${block.job_due_at && html`<div class="kv-row"><dt>Job due</dt><dd>${fmtDateTime(block.job_due_at)}</dd></div>`}
    </div>
    ${block.conflicts && block.conflicts.length > 0 && html`<div class="sched-conflicts">
      ${block.conflicts.map((c, i) => html`<div key=${i}><${Icon} name="triangle-alert" size=${13} />${c.message}</div>`)}
    </div>`}
    <div class="sched-pop-actions">
      ${canWork && block.status === 'pending' && html`<${Button} size="sm" icon="play" onClick=${() => save({ status: 'in_progress' })}>Start</${Button}>`}
      ${canWork && block.status !== 'done' && html`<${Button} size="sm" variant="primary" icon="check" onClick=${() => save({ status: 'done' })}>Done</${Button}>`}
      ${canWork && block.status === 'done' && html`<${Button} size="sm" icon="rotate-ccw" onClick=${() => save({ status: 'pending' })}>Reopen</${Button}>`}
      ${manage && html`<${DateTimeButton} value=${block.start_at} showPresets=${false} title="Move to" icon="calendar-clock" placeholder="Move"
        onChange=${(v) => v && save({ start_at: v })} />`}
      ${manage && html`<${Button} size="sm" variant="ghost" icon="calendar-x" onClick=${() => save({ start_at: null })}>Unschedule</${Button}>`}
    </div>
  </div>`;
}

function QueueScheduler({ item, rows, group, close, onChanged }) {
  const [start, setStart] = useState(null);
  const [row, setRow] = useState(group === 'resource' ? item.resource_id : item.user_id);
  const save = async () => {
    if (!start) return;
    try {
      await patchOp(item.id, { start_at: start, ...(group === 'resource' ? { resource_id: row ?? null } : { user_id: row ?? null }) });
      onChanged();
      close();
    } catch (err) { toastError(err); }
  };
  return html`<div class="sched-pop">
    <div class="sched-pop-head"><span class="job-number">${item.job_number}</span><b class="truncate">${item.name}</b></div>
    <label class="field-label mt-2">Start</label>
    <${DateTimeButton} value=${start} onChange=${setStart} showPresets=${false} title="Start" placeholder="Pick a time" />
    <label class="field-label mt-2">${group === 'resource' ? 'Equipment' : 'Person'}</label>
    <select class="input input-sm select" value=${row ?? ''} onChange=${(e) => setRow(e.currentTarget.value ? Number(e.currentTarget.value) : null)}>
      <option value="">${group === 'resource' ? 'No equipment' : 'Unassigned'}</option>
      ${rows.filter((r) => r.id !== null).map((r) => html`<option value=${r.id}>${r.name}</option>`)}
    </select>
    <div class="sched-pop-actions"><${Button} size="sm" variant="primary" disabled=${!start} onClick=${save}>Schedule</${Button}>
      <${Button} size="sm" variant="ghost" onClick=${() => { close(); navigate(`/jobs/${item.job_id}`); }}>Open job</${Button}></div>
  </div>`;
}

function AutoScheduleModal({ close, onApplied }) {
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.post('/schedule/auto', { apply: false }).then(setPlan).catch(setError);
  }, []);
  const apply = async () => {
    setBusy(true);
    try {
      const res = await api.post('/schedule/auto', { apply: true });
      toast(`Scheduled ${res.placements.length} step${res.placements.length === 1 ? '' : 's'}`);
      onApplied();
      close();
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  const groups = [];
  for (const p of plan ? plan.placements : []) {
    let g = groups.find((x) => x.job_id === p.job_id);
    if (!g) { g = { job_id: p.job_id, number: p.job_number, title: p.job_title, steps: [] }; groups.push(g); }
    g.steps.push(p);
  }
  const late = plan ? plan.placements.filter((p) => p.late).length : 0;
  return html`<${Modal} title="Auto-schedule" icon="wand-sparkles" size="lg" onClose=${close}
    footer=${html`<span class="muted text-sm grow">Earliest due date first, inside work hours, on free equipment${boot('job_skills').length ? ' with someone skilled and on shift' : ''}.</span>
      <${Button} onClick=${close}>Cancel</${Button}>
      <${Button} variant="primary" loading=${busy} disabled=${!plan || !plan.placements.length} onClick=${apply}>
        ${plan && plan.placements.length ? `Schedule ${plan.placements.length} steps` : 'Schedule'}</${Button}>`}>
    ${error && html`<${ErrorBox} error=${error} />`}
    ${!plan && !error && html`<${Loading} label="Working out a plan…" />`}
    ${plan && !plan.placements.length && !plan.unplaced.length && html`<${Empty} icon="circle-check" title="Everything is already scheduled" compact>
      Unscheduled steps of open jobs would show up here.</${Empty}>`}
    ${late > 0 && html`<${Banner} tone="warn">${late} step${late === 1 ? '' : 's'} would finish after the job is due.</${Banner}>`}
    <div class="auto-plan">
      ${groups.map((g) => html`<div class="auto-plan-job" key=${g.job_id}>
        <div class="auto-plan-head"><span class="job-number">${g.number}</span><b class="truncate">${g.title}</b></div>
        ${g.steps.map((s) => html`<div class=${cx('auto-plan-step', s.late && 'is-late')} key=${s.operation_id}>
          <span class="truncate">${s.name}</span>
          <span class="muted text-sm nowrap">${fmtDate(s.start_at, { weekday: true })} ${fmtTimeShort(s.start_at)}–${fmtTimeShort(s.end_at)}</span>
          <span class="text-sm truncate">${resourceOf(s.resource_id)?.name || ''}</span>
          ${s.user_id ? html`<${Avatar} user=${s.user_id} size=${20} />` : html`<span></span>`}
        </div>`)}
      </div>`)}
      ${plan && plan.unplaced.map((u) => html`<div class="auto-plan-unplaced" key=${u.operation_id}>
        <${Icon} name="triangle-alert" size=${14} /><span class="job-number">${u.job_number}</span> ${u.name} — ${u.reason}</div>`)}
    </div>
  </${Modal}>`;
}

// -- board --------------------------------------------------------------------------

export function ScheduleBoard({ route }) {
  const q = route.query;
  const mobile = useIsMobile();
  const manage = can('manage_jobs') && !mobile;
  const view = q.view === 'week' ? 'week' : 'day';
  const group = q.group === 'user' ? 'user' : 'resource';
  const weekStart = setting('org.week_start', 0);
  const anchor = q.date ? fromDateKey(q.date) : startOfDay(new Date());
  const rangeStart = view === 'week' ? startOfWeek(anchor, weekStart) : startOfDay(anchor);
  const dayCount = view === 'week' ? 7 : 1;
  const days = useMemo(() => Array.from({ length: dayCount }, (_, i) => addDays(rangeStart, i)), [rangeStart.getTime(), dayCount]);
  const rangeEnd = addDays(rangeStart, dayCount);
  useStore((s) => s.boot.resources);
  const { data, error, loading, reload, setData } = useFetch('/schedule', {
    query: { start: rangeStart.toISOString(), end: rangeEnd.toISOString(), group }, refetchOn: EVENTS,
  });
  const now = useNow(60000);
  const scrollRef = useRef(null);
  const [width, setWidth] = useState(0); // 0 until the scroll area is measured
  const [drag, setDrag] = useState(null);
  const [dropHint, setDropHint] = useState(null); // { rowKey, x }
  const [showQueue, setShowQueue] = useState(!mobile);
  const dragRef = useRef(null);
  const scrolledFor = useRef(null);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, [!!data]);

  // -- geometry ---------------------------------------------------------------------
  // Work windows come from the server in UTC (org timezone applied there), so shading
  // stays right even when this browser is in another timezone.
  const wh = (data && data.work_hours) || { start: '07:00', end: '18:00', days: [0, 1, 2, 3, 4] };
  const windows = useMemo(() => (data ? data.windows : []).map((w) => [parseISO(w.start_at), parseISO(w.end_at)]), [data]);
  const pad = view === 'week' ? 30 : 60;
  let minMin;
  let maxMin;
  if (windows.length) {
    minMin = Math.min(...windows.map(([a]) => minutesOfDay(a)));
    maxMin = Math.max(...windows.map(([a, b]) => (isSameDay(a, b) ? minutesOfDay(b) : 1440)));
  } else {
    minMin = hhmmToMinutes(wh.start, 420);
    maxMin = hhmmToMinutes(wh.end, 1080);
  }
  minMin = Math.max(0, Math.floor((minMin - pad) / 30) * 30);
  maxMin = Math.min(24 * 60, Math.ceil((maxMin + pad) / 30) * 30);
  for (const b of (data ? data.blocks : [])) {
    const s = parseISO(b.start_at);
    const e = parseISO(b.end_at);
    if (days.some((d) => isSameDay(d, s))) minMin = Math.min(minMin, Math.floor(minutesOfDay(s) / 60) * 60);
    if (days.some((d) => isSameDay(d, e))) maxMin = Math.max(maxMin, Math.ceil(minutesOfDay(e) / 60) * 60 || 0);
  }
  const span = Math.max(60, maxMin - minMin);
  const labelW = mobile ? 104 : 176;
  const avail = Math.max(320, (width || 900) - labelW);
  const dayWidth = view === 'week' ? Math.max(150, avail / 7) : Math.max(avail, span * (mobile ? 1.6 : 2));
  const pxPerMin = dayWidth / span;
  const totalW = dayWidth * dayCount;
  const hourStep = [1, 2, 3, 4, 6, 12, 24].find((h) => h * 60 * pxPerMin >= 46) || 24;

  const dayIndex = (d) => {
    for (let i = 0; i < dayCount; i++) if (isSameDay(days[i], d)) return i;
    return d < days[0] ? -1 : dayCount;
  };
  const xOf = (value) => {
    const d = parseISO(value);
    const i = dayIndex(d);
    if (i < 0) return 0;
    if (i >= dayCount) return totalW;
    const m = Math.min(Math.max(minutesOfDay(d) - minMin, 0), span);
    return i * dayWidth + m * pxPerMin;
  };
  const geom = (start, end) => {
    const s = parseISO(start);
    const left = xOf(start);
    const i = dayIndex(s);
    let right = xOf(end);
    if (i >= 0 && i < dayCount && !isSameDay(s, parseISO(end))) right = i * dayWidth + span * pxPerMin;
    return { left, width: Math.max(8, right - left) };
  };
  const timeAt = (x) => {
    const i = Math.min(dayCount - 1, Math.max(0, Math.floor(x / dayWidth)));
    let m = (x - i * dayWidth) / pxPerMin + minMin;
    m = Math.round(m / SNAP) * SNAP;
    m = Math.min(Math.max(m, minMin), maxMin);
    const d = new Date(days[i]);
    d.setHours(0, 0, 0, 0);
    d.setMinutes(m);
    return d;
  };

  // -- rows & lanes -----------------------------------------------------------------
  const rows = data ? data.rows : [];
  const blocksByRow = useMemo(() => {
    const out = {};
    for (const b of (data ? data.blocks : [])) {
      const key = rowKey(group === 'user' ? b.user_id : b.resource_id);
      (out[key] = out[key] || []).push(b);
    }
    return out;
  }, [data, group]);
  const shiftsByUser = useMemo(() => {
    const out = {};
    for (const s of (data ? data.shifts : [])) (out[s.user_id] = out[s.user_id] || []).push(s);
    return out;
  }, [data]);
  const hasShifts = !!(data && data.shifts.length);
  const timeOffByUser = useMemo(() => {
    const out = {};
    for (const t of (data ? data.time_off : [])) (out[t.user_id] = out[t.user_id] || []).push(t);
    return out;
  }, [data]);

  // Non-working stripes shared by every row: each day's visible span minus work windows.
  const offHours = useMemo(() => {
    const segs = [];
    days.forEach((d, i) => {
      const open = windows
        .filter(([a]) => isSameDay(a, d))
        .map(([a, b]) => [Math.max(minutesOfDay(a), minMin), isSameDay(a, b) ? Math.min(minutesOfDay(b), maxMin) : maxMin])
        .sort((x, y) => x[0] - y[0]);
      let cursor = minMin;
      for (const [a, b] of open) {
        if (a > cursor) segs.push({ left: i * dayWidth + (cursor - minMin) * pxPerMin, width: (a - cursor) * pxPerMin });
        cursor = Math.max(cursor, b);
      }
      if (cursor < maxMin) segs.push({ left: i * dayWidth + (cursor - minMin) * pxPerMin, width: (maxMin - cursor) * pxPerMin });
    });
    return segs;
  }, [days, windows, dayWidth, pxPerMin, minMin, maxMin]);

  const offShift = (uid) => {
    if (!hasShifts || uid === null) return [];
    const segs = [];
    const shifts = (shiftsByUser[uid] || []).map((s) => [parseISO(s.start_at), parseISO(s.end_at)]);
    days.forEach((d, i) => {
      const dayStart = new Date(d); dayStart.setHours(0, 0, 0, 0); dayStart.setMinutes(minMin);
      const dayEnd = new Date(d); dayEnd.setHours(0, 0, 0, 0); dayEnd.setMinutes(maxMin);
      let cursor = dayStart;
      const covered = shifts.filter(([a, b]) => a < dayEnd && b > dayStart).sort((x, y) => x[0] - y[0]);
      for (const [a, b] of covered) {
        if (a > cursor) segs.push([cursor, a, i]);
        if (b > cursor) cursor = b;
      }
      if (cursor < dayEnd) segs.push([cursor, dayEnd, i]);
    });
    return segs.map(([a, b, i]) => {
      const left = i * dayWidth + Math.max(0, (minutesOfDay(a) - minMin + (isSameDay(a, days[i]) ? 0 : -1440))) * pxPerMin;
      const right = i * dayWidth + Math.min(span, (isSameDay(b, days[i]) ? minutesOfDay(b) : maxMin) - minMin) * pxPerMin;
      return { left, width: Math.max(0, right - left) };
    }).filter((s) => s.width > 0);
  };

  // -- drag: move & resize ------------------------------------------------------------
  // Listeners go on in pointerdown itself (not an effect) so a quick click or tap can't
  // release before they exist. No preventDefault: the overlay host closes any open
  // popover on mousedown, and CSS keeps the grid from selecting text.
  const trackX = (clientX) => {
    const el = scrollRef.current;
    const rect = el.getBoundingClientRect();
    return clientX - rect.left + el.scrollLeft - labelW;
  };
  const rowAt = (clientX, clientY) => {
    const el = document.elementFromPoint(clientX, clientY);
    const rowEl = el && el.closest && el.closest('[data-row-key]');
    return rowEl ? rowEl.dataset.rowKey : null;
  };

  const finishDrag = async (d) => {
    const b = d.block;
    if (!d.moved) {
      openDetails(d.anchorEl, b);
      return;
    }
    const preview = previewTimes(d);
    const fields = { start_at: preview.start.toISOString(), end_at: preview.end.toISOString() };
    if (d.mode === 'move' && d.targetRow !== d.row) {
      const id = d.targetRow === 'none' ? null : Number(d.targetRow);
      fields[group === 'user' ? 'user_id' : 'resource_id'] = id;
    }
    setData((prev) => prev && {
      ...prev,
      blocks: prev.blocks.map((x) => (x.id === b.id ? { ...x, ...fields } : x)),
    });
    try { await patchOp(b.id, fields); } catch (err) { toastError(err); }
    reload({ quiet: true });
  };

  const startDrag = (e, block, mode) => {
    if (!manage || e.button !== 0 || dragRef.current) return;
    e.stopPropagation();
    const target = e.currentTarget;
    const row = rowKey(group === 'user' ? block.user_id : block.resource_id);
    dragRef.current = {
      id: block.id, block, mode, startX: e.clientX, startY: e.clientY, dx: 0, moved: false, row, targetRow: row,
      anchorEl: mode === 'resize' ? target.parentElement : target,
    };
    setDrag(dragRef.current);
    const onMove = (ev) => {
      const d = dragRef.current;
      if (!d) return;
      const dx = ev.clientX - d.startX;
      const moved = d.moved || Math.abs(dx) > 4 || Math.abs(ev.clientY - d.startY) > 4;
      const targetRow = d.mode === 'move' ? (rowAt(ev.clientX, ev.clientY) || d.targetRow) : d.row;
      dragRef.current = { ...d, dx, moved, targetRow };
      setDrag(dragRef.current);
    };
    const onUp = (ev) => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
      const d = dragRef.current;
      dragRef.current = null;
      setDrag(null);
      if (d && ev.type === 'pointerup') finishDrag(d);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
  };

  const previewTimes = (d) => {
    const b = d.block;
    const g = geom(b.start_at, b.end_at);
    if (d.mode === 'resize') {
      const start = parseISO(b.start_at);
      let end = timeAt(g.left + g.width + d.dx);
      if (end - start < SNAP * 60000) end = addMinutes(start, SNAP);
      return { start, end };
    }
    const start = timeAt(g.left + d.dx);
    return { start, end: addMinutes(start, b.duration_minutes) };
  };

  const openDetails = (anchorEl, block) => {
    showPopover(anchorEl, (close) => html`<${BlockDetails} block=${block} group=${group} close=${close} onChanged=${() => reload({ quiet: true })} />`,
      { width: 330, placement: 'bottom-start' });
  };

  // -- queue drops -------------------------------------------------------------------
  const onRowDragOver = (e, key) => {
    if (!manage || !e.dataTransfer.types.includes('application/x-sb-op')) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const x = Math.max(0, trackX(e.clientX));
    setDropHint({ rowKey: key, x: Math.round((x) / (pxPerMin * SNAP)) * pxPerMin * SNAP });
  };
  const onRowDrop = async (e, key) => {
    const raw = e.dataTransfer.getData('application/x-sb-op');
    setDropHint(null);
    if (!raw) return;
    e.preventDefault();
    const item = JSON.parse(raw);
    const start = timeAt(Math.max(0, trackX(e.clientX)));
    const fields = { start_at: start.toISOString() };
    fields[group === 'user' ? 'user_id' : 'resource_id'] = key === 'none' ? null : Number(key);
    try {
      await patchOp(item.id, fields);
      toast(`Scheduled ${item.job_number} · ${item.name}`);
    } catch (err) { toastError(err); }
    reload({ quiet: true });
  };

  // -- navigation ---------------------------------------------------------------------
  const go = (delta) => setQuery({ date: dateKey(addDays(anchor, delta * (view === 'week' ? 7 : 1))) });
  const label = view === 'week'
    ? `${fmtDate(days[0])} – ${fmtDate(days[6], { year: true })}`
    : fmtDate(days[0], { weekday: true, year: true });

  useEffect(() => {
    if (!q.focus || !data) return;
    const el = document.querySelector(`[data-op-id="${q.focus}"]`);
    if (el) {
      el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' });
      el.classList.add('is-focused');
      setTimeout(() => el.classList.remove('is-focused'), 2400);
    }
  }, [q.focus, !!data]);

  const nowX = now >= rangeStart.getTime() && now < rangeEnd.getTime() ? xOf(new Date(now).toISOString()) : null;

  useLayoutEffect(() => {
    const el = scrollRef.current;
    const key = `${view}:${rangeStart.getTime()}:${group}`;
    if (!el || !data || !width || q.focus || scrolledFor.current === key) return;
    scrolledFor.current = key;
    const nowMin = minutesOfDay(new Date(now));
    let x = 0;
    if (view === 'week') {
      const i = dayIndex(new Date(now));
      x = i > 0 && i < dayCount ? i * dayWidth - 8 : 0;
    } else if (nowX !== null && nowMin > minMin && nowMin < maxMin) {
      x = nowX - 160;
    } else if (data.blocks.length) {
      x = Math.min(...data.blocks.map((b) => xOf(b.start_at))) - 40;
    } else if (windows.length) {
      x = xOf(windows[0][0].toISOString()) - 40;
    }
    el.scrollLeft = Math.max(0, x);
  }, [data, width, view, group, rangeStart.getTime()]);
  const conflictCount = data ? data.blocks.filter((b) => b.conflicts && b.conflicts.length).length : 0;

  const header = html`<${PageHeader} leading=${html`<${SidebarButton} />`} title="Production schedule" icon="chart-gantt"
    subtitle=${data ? `${data.blocks.length} scheduled · ${data.queue.length} waiting${conflictCount ? ` · ${conflictCount} conflict${conflictCount === 1 ? '' : 's'}` : ''}` : ''}
    actions=${can('manage_jobs') && html`<${Button} icon="wand-sparkles" onClick=${() => openModal((close) => html`<${AutoScheduleModal} close=${close} onApplied=${() => reload({ quiet: true })} />`)}>Auto-schedule</${Button}>`} />`;

  return html`<div class="jobs-page sched-page">
    ${header}
    <div class="toolbar sched-toolbar">
      <${Button} size="sm" onClick=${() => setQuery({ date: dateKey(new Date()) })}>Today</${Button}>
      <${IconButton} icon="chevron-left" label="Previous" onClick=${() => go(-1)} />
      <${IconButton} icon="chevron-right" label="Next" onClick=${() => go(1)} />
      <span class="sched-range">${label}</span>
      <span class="grow"></span>
      <${Segmented} size="sm" value=${view} onChange=${(v) => setQuery({ view: v === 'day' ? undefined : v })}
        options=${[{ value: 'day', label: 'Day' }, { value: 'week', label: 'Week' }]} />
      <${Segmented} size="sm" value=${group} onChange=${(v) => setQuery({ group: v === 'resource' ? undefined : v })}
        options=${[{ value: 'resource', label: 'Equipment', icon: 'factory' }, { value: 'user', label: 'People', icon: 'users' }]} />
      <${Button} size="sm" variant=${showQueue ? 'soft' : 'secondary'} icon="list-todo" onClick=${() => setShowQueue(!showQueue)}>
        Queue${data && data.queue.length ? ` (${data.queue.length})` : ''}</${Button}>
    </div>
    ${error && html`<${ErrorBox} error=${error} retry=${reload} />`}
    ${loading && !data ? html`<${Loading} />` : null}
    ${data && html`<div class=${cx('sched-body', showQueue && 'has-queue')}>
      <div class="sched-scroll" ref=${scrollRef}>
        <div class="sched-grid" style=${{ width: labelW + totalW + 'px', '--label-w': labelW + 'px' }}>
          <div class="sched-head">
            <div class="sched-corner">${group === 'user' ? 'Person' : 'Equipment'}</div>
            <div class="sched-scale" style=${{ width: totalW + 'px' }}>
              ${days.map((d, i) => html`<div class=${cx('sched-day', isSameDay(d, new Date()) && 'is-today')} key=${i} style=${{ left: i * dayWidth + 'px', width: dayWidth + 'px' }}>
                ${view === 'week' && html`<div class="sched-day-label">${fmtWeekday(d)} ${d.getDate()}</div>`}
                <div class="sched-hours">
                  ${Array.from({ length: Math.floor(span / 60) + 1 }, (_, h) => h).map((h) => {
    const minutes = Math.ceil(minMin / 60) * 60 + h * 60;
    if (minutes >= maxMin || (minutes / 60) % hourStep !== 0) return null;
    const t = new Date(d); t.setHours(0, 0, 0, 0); t.setMinutes(minutes);
    return html`<span class="sched-hour" key=${h} style=${{ left: (minutes - minMin) * pxPerMin + 'px' }}>${fmtTimeShort(t)}</span>`;
  })}
                </div>
              </div>`)}
            </div>
          </div>
          ${rows.map((row) => {
    const key = rowKey(row.id);
    const blocks = blocksByRow[key] || [];
    const { lanes, count } = assignLanes(blocks);
    const height = count * LANE_H + 10;
    const isUser = row.kind === 'user';
    return html`<div class="sched-row" key=${key} data-row-key=${key} style=${{ height: height + 'px' }}
              onDragOver=${(e) => onRowDragOver(e, key)} onDragLeave=${() => setDropHint(null)} onDrop=${(e) => onRowDrop(e, key)}>
              <div class="sched-label">
                ${isUser && row.id ? html`<${Avatar} user=${row.id} size=${24} online="auto" />` : html`<span class="sched-label-swatch" style=${{ background: row.color || 'var(--border-strong)' }}></span>`}
                <div class="sched-label-text"><div class="truncate strong">${row.name}</div>${row.subtitle && html`<div class="truncate muted text-xs">${row.subtitle}</div>`}</div>
              </div>
              <div class="sched-track" style=${{ width: totalW + 'px' }}>
                ${offHours.map((s, i) => html`<div class="sched-off" key=${'o' + i} style=${{ left: s.left + 'px', width: s.width + 'px' }}></div>`)}
                ${isUser && offShift(row.id).map((s, i) => html`<div class="sched-offshift" key=${'s' + i} style=${{ left: s.left + 'px', width: s.width + 'px' }} title="Not on shift"></div>`)}
                ${isUser && (timeOffByUser[row.id] || []).map((t, i) => {
      const g = geom(t.start_at, t.end_at);
      return html`<div class="sched-timeoff" key=${'t' + i} style=${{ left: g.left + 'px', width: g.width + 'px' }} title=${`Off: ${t.kind}`}><span>Off · ${t.kind}</span></div>`;
    })}
                ${days.map((_, i) => html`<div class="sched-dayline" key=${'d' + i} style=${{ left: i * dayWidth + 'px' }}></div>`)}
                ${dropHint && dropHint.rowKey === key && html`<div class="sched-drop" style=${{ left: dropHint.x + 'px' }}></div>`}
                ${blocks.map((b) => {
      const dragging = drag && drag.id === b.id && drag.moved;
      let g = geom(b.start_at, b.end_at);
      const top = 5 + lanes[b.id] * LANE_H;
      if (dragging) {
        if (drag.targetRow !== key) return html`<div class="sched-block is-ghost" key=${b.id} style=${{ left: g.left + 'px', width: g.width + 'px', top: top + 'px' }}></div>`;
        const p = previewTimes(drag);
        g = geom(p.start.toISOString(), p.end.toISOString());
      }
      const bad = b.conflicts && b.conflicts.length;
      return html`<div
                    key=${b.id}
                    data-op-id=${b.id}
                    class=${cx('sched-block', `is-${b.status}`, bad && 'has-conflict', dragging && 'is-dragging', manage && 'is-draggable', b.job_priority === 'rush' && 'is-rush', g.width < 56 && 'is-narrow')}
                    style=${{ left: g.left + 'px', width: g.width + 'px', top: top + 'px', '--block': b.stage_color || 'var(--accent)' }}
                    title=${`${b.job_number} · ${b.name}\n${fmtTimeShort(b.start_at)}–${fmtTimeShort(b.end_at)}${bad ? '\n⚠ ' + b.conflicts.map((c) => c.message).join('\n⚠ ') : ''}`}
                    onPointerDown=${(e) => (manage ? startDrag(e, b, 'move') : null)}
                    onClick=${(e) => { if (!manage) openDetails(e.currentTarget, b); }}
                    role="button" tabIndex="0"
                    onKeyDown=${(e) => { if (e.key === 'Enter') openDetails(e.currentTarget, b); }}
                  >
                    <div class="sched-block-line1">
                      ${bad ? html`<${Icon} name="triangle-alert" size=${12} class="sched-block-warn" />` : null}
                      ${b.status === 'done' && html`<${Icon} name="circle-check" size=${12} />`}
                      ${b.status === 'in_progress' && html`<span class="live-dot"></span>`}
                      <span class="sched-block-num">${b.job_number}</span><span class="truncate">${b.name}</span>
                    </div>
                    <div class="sched-block-line2 truncate">${group === 'user' ? (resourceOf(b.resource_id)?.name || b.customer || b.job_title) : (b.user_id ? lookupUser(b.user_id).name.split(' ')[0] + ' · ' : '') + (b.customer || b.job_title)}</div>
                    ${manage && html`<span class="sched-resize" onPointerDown=${(e) => startDrag(e, b, 'resize')}></span>`}
                  </div>`;
    })}
                ${drag && drag.moved && drag.mode === 'move' && drag.targetRow === key && rowKey(group === 'user' ? drag.block.user_id : drag.block.resource_id) !== key && (() => {
      const p = previewTimes(drag);
      const g = geom(p.start.toISOString(), p.end.toISOString());
      return html`<div class="sched-block is-preview" style=${{ left: g.left + 'px', width: g.width + 'px', top: '5px', '--block': drag.block.stage_color || 'var(--accent)' }}>
                    <div class="sched-block-line1"><span class="sched-block-num">${drag.block.job_number}</span><span class="truncate">${drag.block.name}</span></div>
                    <div class="sched-block-line2">${fmtTimeShort(p.start)}–${fmtTimeShort(p.end)}</div></div>`;
    })()}
              </div>
            </div>`;
  })}
          ${nowX !== null && html`<div class="sched-now" style=${{ left: labelW + nowX + 'px' }}><span></span></div>`}
          ${drag && drag.moved && html`<div class="sched-drag-time" style=${{ left: labelW + geom(previewTimes(drag).start.toISOString(), previewTimes(drag).end.toISOString()).left + 'px' }}>
            ${fmtTimeShort(previewTimes(drag).start)}–${fmtTimeShort(previewTimes(drag).end)}</div>`}
        </div>
        ${!rows.length && html`<${Empty} icon=${group === 'user' ? 'users' : 'factory'} title=${group === 'user' ? 'No one to schedule' : 'No equipment yet'}
          action=${can('manage_jobs') && group !== 'user' && html`<${Button} onClick=${() => navigate('/settings/resources')}>Add equipment</${Button}>`}>
          ${group === 'user' ? 'People with staff profiles (or staff accounts) appear here.' : 'Add presses, cutters and vans in Settings → Equipment.'}</${Empty}>`}
      </div>
      ${showQueue && html`<aside class="sched-queue" aria-label="Unscheduled steps">
        <div class="sched-queue-head"><b>Waiting to schedule</b><span class="muted text-sm">${data.queue.length}</span>
          ${mobile && html`<${IconButton} icon="x" size="sm" label="Hide queue" onClick=${() => setShowQueue(false)} />`}</div>
        ${manage && data.queue.length > 0 && html`<p class="muted text-xs sched-queue-hint">Drag a step onto a row, or use Auto-schedule.</p>`}
        <div class="sched-queue-list">
          ${data.queue.map((item) => html`<div
            key=${item.id}
            class="sched-queue-item"
            draggable=${manage ? 'true' : undefined}
            onDragStart=${(e) => { e.dataTransfer.setData('application/x-sb-op', JSON.stringify({ id: item.id, name: item.name, job_number: item.job_number })); e.dataTransfer.effectAllowed = 'move'; }}
            onDragEnd=${() => setDropHint(null)}
            onClick=${(e) => (can('manage_jobs')
      ? showPopover(e.currentTarget, (close) => html`<${QueueScheduler} item=${item} rows=${rows} group=${group} close=${close} onChanged=${() => reload({ quiet: true })} />`, { width: 300, placement: 'left-start' })
      : navigate(`/jobs/${item.job_id}`))}
            style=${{ '--block': item.stage_color || 'var(--accent)' }}
          >
            <div class="row gap-1"><span class="job-number">${item.job_number}</span><${PriorityChip} priority=${item.job_priority} />
              <span class="grow"></span><span class="muted text-xs">${fmtDuration(item.duration_minutes)}</span></div>
            <div class="strong truncate">${item.name}</div>
            <div class="muted text-xs truncate">${item.customer || item.job_title}</div>
            ${item.job_due_at && html`<div class="mt-1"><${DueChip} job=${{ due_at: item.job_due_at, due_state: new Date(item.job_due_at) < new Date() ? 'overdue' : (new Date(item.job_due_at) - Date.now() < 86400000 ? 'soon' : null) }} /></div>`}
          </div>`)}
          ${!data.queue.length && html`<${Empty} icon="circle-check" title="All caught up" compact>Every step of every open job has a time.</${Empty}>`}
        </div>
      </aside>`}
    </div>`}
  </div>`;
}

export default ScheduleBoard;
