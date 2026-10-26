// Staffing widgets for the "My day" dashboard.

import { html, useEffect, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch, useNow } from '../../lib/hooks.js';
import { navigate } from '../../lib/router.js';
import { useStore } from '../../lib/store.js';
import { fmtClock, fmtDuration } from '../../lib/format.js';
import { Button, Card, Empty, Icon, Loading, Select, cx } from '../../ui/components.js';
import { toastError } from '../../ui/overlay.js';
import * as S from './shared.js';
import { TimeOffRow } from './timeoff.js';
import { RequestCard } from './requests.js';

function useMyJobs(enabled) {
  // Jobs live in another module (it puts job_stages in bootstrap); without it, or if the
  // request fails, the picker just hides.
  const hasJobs = useStore((s) => Array.isArray(s.boot.job_stages));
  const [jobs, setJobs] = useState(null);
  useEffect(() => {
    if (!enabled || !hasJobs) return;
    let alive = true;
    api.get('/jobs', { mine: 1, done: 0, limit: 30 })
      .then((res) => { if (alive) setJobs(Array.isArray(res?.items) ? res.items : []); })
      .catch(() => { if (alive) setJobs([]); });
    return () => { alive = false; };
  }, [enabled, hasJobs]);
  return jobs || [];
}

export function ClockWidget() {
  const { data, loading, reload, setData } = useFetch('/timeclock', { refetchOn: ['timeclock.changed', 'schedule.changed'] });
  const now = useNow(1000);
  const [jobId, setJobId] = useState('');
  const [busy, setBusy] = useState(false);
  const entry = data?.entry;
  const jobs = useMyJobs(!!data && !entry);
  const act = async (path, body) => {
    setBusy(true);
    try {
      setData(await api.post(path, body));
    } catch (err) {
      toastError(err);
      reload();
    } finally { setBusy(false); }
  };
  if (loading && !data) return html`<${Card} title="Time clock" icon="clock"><${Loading} /></${Card}>`;
  if (!data) return html`<${Card} title="Time clock" icon="clock"><${Empty} compact icon="clock">Couldn't load the time clock.</${Empty}></${Card}>`;
  const elapsed = entry ? (now - new Date(entry.clock_in).getTime()) / 1000 - (entry.on_break ? 0 : entry.break_minutes * 60) : 0;
  const breakStart = entry?.on_break ? entry.breaks[entry.breaks.length - 1].start : null;
  const shift = data.shift || data.next_shift;
  return html`<${Card} title="Time clock" icon="clock" class="st-clock-card">
    <div class=${cx('st-clock', entry && 'is-in', entry?.on_break && 'is-break')}>
      <div class="st-clock-status">
        ${entry ? html`<span class="st-clock-dot"></span>${entry.on_break ? 'On break' : 'Clocked in'} since ${S.orgTime(entry.on_break ? breakStart : entry.clock_in)}`
    : html`<span class="muted">You're clocked out</span>`}
      </div>
      <div class="st-clock-timer tabular">${entry ? fmtClock(entry.on_break ? (now - new Date(breakStart).getTime()) / 1000 : Math.max(0, elapsed)) : fmtDuration(data.today_minutes) || '0m'}</div>
      <div class="muted text-sm">${entry ? (entry.on_break ? 'break time' : 'worked on this punch') : 'worked today'}</div>
      ${!entry && jobs.length > 0 && html`<${Select} class="st-clock-job" value=${jobId} onValue=${setJobId} placeholder="Working on… (optional)"
        options=${jobs.map((j) => ({ value: String(j.id), label: `${j.number ? j.number + ' · ' : ''}${j.title}` }))} />`}
      <div class="st-clock-actions">
        ${entry ? html`
          <${Button} variant=${entry.on_break ? 'primary' : 'secondary'} icon=${entry.on_break ? 'play' : 'coffee'} loading=${busy}
            onClick=${() => act(entry.on_break ? '/timeclock/break/end' : '/timeclock/break/start')}>${entry.on_break ? 'End break' : 'Start break'}</${Button}>
          <${Button} variant="danger" icon="log-out" loading=${busy} onClick=${() => act('/timeclock/out')}>Clock out</${Button}>`
    : html`<${Button} variant="primary" size="lg" icon="log-in" class="st-clock-in" loading=${busy}
            onClick=${() => act('/timeclock/in', jobId ? { job_id: Number(jobId) } : {})}>Clock in</${Button}>`}
      </div>
      ${shift && html`<div class="st-clock-shift">
        <${Icon} name="calendar-clock" size=${14} />
        <span>${data.shift ? 'Shift now' : 'Next shift'}: <strong>${S.dayLabel(shift.date)}, ${S.shiftRange(shift)}</strong>
          ${S.positionOf(shift.position_id) ? ` · ${S.positionOf(shift.position_id).name}` : ''}
          ${!data.shift ? html`<span class="muted"> (${S.untilLabel(shift.start_at)})</span>` : null}</span>
      </div>`}
    </div>
  </${Card}>`;
}

export function MyShiftsWidget() {
  const me = useStore((s) => s.me);
  const today = S.todayKey();
  const { data, loading } = useFetch('/shifts', {
    query: { start: today, end: S.addDaysKey(today, 14), user_id: me.id, status: 'published' },
    refetchOn: ['schedule.changed'],
  });
  const items = (data?.items || []).filter((s) => s.end_at > new Date().toISOString()).slice(0, 6);
  const total = (data?.items || []).filter((s) => s.date < S.addDaysKey(today, 7)).reduce((n, s) => n + s.minutes, 0);
  return html`<${Card} title="My shifts" icon="calendar-clock" pad=${false} subtitle=${data ? `${S.hours(total)} in the next 7 days` : null}
    actions=${html`<${Button} size="sm" variant="ghost" onClick=${() => navigate('/schedule')}>Schedule</${Button}>`}>
    ${loading && !data ? html`<${Loading} />` : items.length ? html`<div class="list">
      ${items.map((s) => html`<a key=${s.id} class="list-row is-clickable st-link-row" href=${`/schedule?week=${s.date}`}>
        <span class=${cx('st-day-badge', s.date === today && 'is-today')}><span>${S.weekdayShort(s.date)}</span><strong>${Number(s.date.slice(8))}</strong></span>
        <span class="grow stack-0"><strong>${S.shiftRange(s)}</strong>
          <span class="muted text-sm">${S.positionOf(s.position_id)?.name || 'Shift'}${s.location_id ? ` · ${S.locationOf(s.location_id)?.name || ''}` : ''}</span></span>
        ${s.date === today && html`<span class="st-today-tag">Today</span>`}
      </a>`)}
    </div>` : html`<${Empty} icon="calendar-days" compact>No upcoming shifts.</${Empty}>`}
  </${Card}>`;
}

export function TimeOffWidget() {
  const me = useStore((s) => s.me);
  const { data, loading, reload } = useFetch('/time-off', { query: { mine: 1, status: 'upcoming' }, refetchOn: ['schedule.changed'] });
  const items = (data?.items || []).slice(0, 4);
  return html`<${Card} title="Time off" icon="plane" pad=${false}
    actions=${html`<${Button} size="sm" icon="plus" onClick=${() => S.requestTimeOff({ onDone: reload })}>Request</${Button}>`}>
    ${loading && !data ? html`<${Loading} />` : items.length
    ? html`<div class="st-request-list st-request-list-flush">${items.map((r) => html`<${TimeOffRow} key=${r.id} r=${r} manager=${false} me=${me} compact />`)}</div>`
    : html`<${Empty} icon="umbrella" compact>Nothing booked. Need a day off? Ask here.</${Empty}>`}
  </${Card}>`;
}

export function ApprovalsWidget() {
  const me = useStore((s) => s.me);
  const timeOff = useFetch('/time-off', { query: { status: 'pending' }, refetchOn: ['schedule.changed'] });
  const requests = useFetch('/shift-requests', { query: { status: 'open' }, refetchOn: ['schedule.changed'] });
  const waiting = (requests.data?.items || []).filter((r) => r.can_approve);
  const pending = timeOff.data?.items || [];
  const count = waiting.length + pending.length;
  return html`<${Card} title="Waiting for approval" icon="badge-check" pad=${false} subtitle=${count ? `${count} to review` : null}
    actions=${html`<${Button} size="sm" variant="ghost" onClick=${() => navigate('/schedule/timeoff')}>All</${Button}>`}>
    ${(timeOff.loading && !timeOff.data) || (requests.loading && !requests.data) ? html`<${Loading} />` : count ? html`<div class="st-request-list st-request-list-flush">
      ${pending.slice(0, 4).map((r) => html`<${TimeOffRow} key=${'t' + r.id} r=${r} manager=${true} me=${me} compact />`)}
      ${waiting.slice(0, 4).map((r) => html`<${RequestCard} key=${'r' + r.id} r=${r} compact />`)}
    </div>` : html`<${Empty} icon="badge-check" compact>All caught up.</${Empty}>`}
  </${Card}>`;
}
