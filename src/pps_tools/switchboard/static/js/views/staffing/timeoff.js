// Time off: request it, see what's coming, and (for managers) approve or decline.

import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch } from '../../lib/hooks.js';
import { navigate } from '../../lib/router.js';
import { useStore, user as lookupUser } from '../../lib/store.js';
import { Avatar, Button, Empty, ErrorBox, Loading, PageHeader, Tabs, RelTime } from '../../ui/components.js';
import { SidebarButton } from '../../ui/layout.js';
import { confirmDialog, promptDialog, toast, toastError } from '../../ui/overlay.js';
import * as S from './shared.js';

export async function decideTimeOff(r, approve) {
  try {
    if (approve) {
      const res = await api.post(`/time-off/${r.id}/approve`);
      const clashes = res.conflicting_shifts || [];
      if (clashes.length) {
        toast(`${lookupUser(r.user_id).name} has ${clashes.length} shift${clashes.length === 1 ? '' : 's'} during this time off — reassign ${clashes.length === 1 ? 'it' : 'them'}.`, {
          tone: 'danger', icon: 'triangle-alert', duration: 9000,
          action: { label: 'Open schedule', onClick: () => navigate(`/schedule?week=${clashes[0].date}`) },
        });
      } else {
        toast('Approved');
      }
    } else {
      const note = await promptDialog({ title: 'Decline time off', label: 'Reason (shared with them)', placeholder: 'Optional', confirmLabel: 'Decline', multiline: true });
      if (note === null) return;
      await api.post(`/time-off/${r.id}/deny`, { note });
      toast('Declined');
    }
  } catch (err) { toastError(err); }
}

async function cancel(r) {
  if (!(await confirmDialog({ title: 'Cancel this time off?', confirmLabel: 'Cancel time off', cancelLabel: 'Keep it', danger: true }))) return;
  try {
    await api.post(`/time-off/${r.id}/cancel`);
    toast('Cancelled');
  } catch (err) { toastError(err); }
}

export function TimeOffRow({ r, manager, me, compact }) {
  const mine = r.user_id === me.id;
  const canCancel = (mine && r.status === 'pending') || (manager && ['pending', 'approved'].includes(r.status));
  return html`<div class="st-request">
    <${Avatar} user=${r.user_id} size=${compact ? 28 : 34} />
    <div class="st-request-main">
      <div class="st-request-title"><strong>${lookupUser(r.user_id).name}</strong> <${S.KindChip} kind=${r.kind} /> <${S.RequestStatus} status=${r.status} /></div>
      <div class="text-sm">${S.timeOffSpan(r)}<span class="muted"> · ${r.start_time ? `${r.hours}h` : `${r.days} day${r.days === 1 ? '' : 's'}`}</span></div>
      ${r.reason && html`<div class="st-request-note">“${r.reason}”</div>`}
      ${r.review_note && html`<div class="muted text-sm">${r.reviewed_by ? lookupUser(r.reviewed_by).name : 'Manager'}: ${r.review_note}</div>`}
      ${!compact && html`<div class="muted text-xs">Requested <${RelTime} value=${r.created_at} mode="ago" /></div>`}
    </div>
    <div class="st-request-actions">
      ${manager && r.status === 'pending' && html`<${Button} size="sm" variant="primary" icon="check" onClick=${() => decideTimeOff(r, true)}>Approve</${Button}>
        <${Button} size="sm" onClick=${() => decideTimeOff(r, false)}>Decline</${Button}>`}
      ${canCancel && !(manager && r.status === 'pending') && html`<${Button} size="sm" variant="ghost" onClick=${() => cancel(r)}>Cancel</${Button}>`}
    </div>
  </div>`;
}

export function TimeOffPage() {
  const me = useStore((s) => s.me);
  const manager = S.isManager();
  const [tab, setTab] = useState(manager ? 'pending' : 'upcoming');
  const counts = S.useStaffCounts();
  const { data, loading, error, reload } = useFetch('/time-off', {
    query: { status: tab === 'all' ? undefined : tab },
    refetchOn: ['schedule.changed'],
  });
  const tabs = [
    ...(manager ? [{ id: 'pending', label: 'To review', count: counts.data?.timeoff }] : []),
    { id: 'upcoming', label: 'Upcoming' },
    { id: 'past', label: 'Past' },
    { id: 'all', label: 'All' },
  ];
  const items = data?.items || [];
  return html`<${PageHeader} leading=${html`<${SidebarButton} />`} title="Time off" icon="plane"
      subtitle=${manager ? 'Requests from the whole team' : 'Your requests'}
      actions=${html`<${Button} variant="primary" size="sm" icon="plus" onClick=${() => S.requestTimeOff({ onDone: reload })}>Request time off</${Button}>`} />
    <div class="st-tabs"><${Tabs} tabs=${tabs} value=${tab} onChange=${setTab} /></div>
    <div class="page-body"><div class="page-body-narrow">
      ${error && html`<${ErrorBox} error=${error} retry=${reload} />`}
      ${loading && !data ? html`<${Loading} />` : html`<div class="st-request-list">
        ${items.map((r) => html`<${TimeOffRow} key=${r.id} r=${r} manager=${manager} me=${me} />`)}
      </div>`}
      ${data && !items.length && html`<${Empty} icon="plane" title=${tab === 'pending' ? 'Nothing to review' : 'No time off here'}>
        ${tab === 'pending' ? 'New requests from your team show up here.' : 'Requests you make show up here once sent.'}
      </${Empty}>`}
    </div></div>`;
}
