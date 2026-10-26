// Shift requests: swaps between coworkers, drops, and pickups of open shifts.

import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch } from '../../lib/hooks.js';
import { useStore, user as lookupUser } from '../../lib/store.js';
import { Avatar, Button, Checkbox, Chip, Empty, ErrorBox, Icon, Loading, PageHeader, RelTime } from '../../ui/components.js';
import { SidebarButton } from '../../ui/layout.js';
import { promptDialog, toast, toastError } from '../../ui/overlay.js';
import * as S from './shared.js';

const KIND = {
  swap: { icon: 'arrow-right-left', verb: 'swap' },
  drop: { icon: 'calendar-x', verb: 'drop' },
  pickup: { icon: 'user-plus', verb: 'pick up' },
};

function shiftLine(s) {
  if (!s) return 'a shift that no longer exists';
  const pos = S.positionOf(s.position_id);
  return `${S.dayLabel(s.date)} · ${S.shiftRange(s)}${pos ? ` · ${pos.name}` : ''}`;
}

export async function actOnRequest(r, action) {
  try {
    let note;
    if (action === 'deny') {
      note = await promptDialog({ title: 'Decline request', label: 'Reason (optional)', confirmLabel: 'Decline', multiline: true });
      if (note === null) return;
    }
    await api.post(`/shift-requests/${r.id}/${action}`, note ? { note } : {});
    toast({ accept: 'Accepted', approve: 'Approved — the schedule is updated', deny: 'Declined', cancel: 'Cancelled' }[action]);
  } catch (err) { toastError(err); }
}

export function RequestCard({ r, compact }) {
  const k = KIND[r.kind];
  const requester = lookupUser(r.requester_id).name;
  const target = r.target_user_id ? lookupUser(r.target_user_id).name : null;
  const title = r.kind === 'swap'
    ? (r.target_shift ? `${requester} ⇄ ${target}` : `${requester} → ${target}`)
    : r.kind === 'drop' ? `${requester} wants to drop a shift` : `${requester} wants an open shift`;
  return html`<div class="st-request">
    <span class="st-request-icon"><${Icon} name=${k.icon} size=${16} /></span>
    <div class="st-request-main">
      <div class="st-request-title"><strong>${title}</strong> <${S.RequestStatus} status=${r.status} /></div>
      <div class="text-sm">${r.kind === 'swap' && !r.target_shift ? `${target} takes ` : ''}${shiftLine(r.shift)}</div>
      ${r.target_shift && html`<div class="text-sm muted">in exchange for ${shiftLine(r.target_shift)}</div>`}
      ${r.note && html`<div class="st-request-note">“${r.note}”</div>`}
      ${r.decision_note && html`<div class="muted text-sm">${r.decided_by ? lookupUser(r.decided_by).name : 'Manager'}: ${r.decision_note}</div>`}
      ${!compact && html`<div class="muted text-xs">Asked <${RelTime} value=${r.created_at} mode="ago" /></div>`}
    </div>
    <div class="st-request-actions">
      ${r.can_accept && html`<${Button} size="sm" variant="primary" icon="check" onClick=${() => actOnRequest(r, 'accept')}>Accept</${Button}>`}
      ${r.can_approve && html`<${Button} size="sm" variant="primary" icon="check" onClick=${() => actOnRequest(r, 'approve')}>Approve</${Button}>`}
      ${r.can_deny && html`<${Button} size="sm" onClick=${() => actOnRequest(r, 'deny')}>Decline</${Button}>`}
      ${r.can_cancel && !r.can_approve && html`<${Button} size="sm" variant="ghost" onClick=${() => actOnRequest(r, 'cancel')}>Cancel</${Button}>`}
    </div>
  </div>`;
}

async function pickUp(shift) {
  try {
    const res = await api.post(`/shifts/${shift.id}/pickup`);
    toast(res.request.status === 'approved' ? "It's yours!" : 'Pickup requested — a manager will confirm');
  } catch (err) { toastError(err); }
}

export function RequestsPage() {
  const me = useStore((s) => s.me);
  const manager = S.isManager();
  const [history, setHistory] = useState(false);
  const { data, loading, error, reload } = useFetch('/shift-requests', {
    query: { status: history ? 'all' : 'open' }, refetchOn: ['schedule.changed'],
  });
  const open = useFetch('/shifts/open', { refetchOn: ['schedule.changed'] });
  const items = data?.items || [];
  const attention = items.filter((r) => r.can_accept || r.can_approve);
  const rest = items.filter((r) => !(r.can_accept || r.can_approve));
  const openShifts = open.data?.items || [];
  return html`<${PageHeader} leading=${html`<${SidebarButton} />`} title="Requests" icon="arrow-right-left"
      subtitle="Swaps, drops and open shifts"
      actions=${html`<${Checkbox} checked=${history} onChange=${setHistory} label="Show history" />`} />
    <div class="page-body"><div class="page-body-narrow stack-lg">
      ${error && html`<${ErrorBox} error=${error} retry=${reload} />`}
      ${loading && !data && html`<${Loading} />`}
      ${attention.length > 0 && html`<section>
        <h3 class="st-section-title">Needs you <span class="muted">${attention.length}</span></h3>
        <div class="st-request-list">${attention.map((r) => html`<${RequestCard} key=${r.id} r=${r} />`)}</div>
      </section>`}
      <section>
        <h3 class="st-section-title">Open shifts <span class="muted">${openShifts.length}</span></h3>
        ${openShifts.length ? html`<div class="st-request-list">${openShifts.map((s) => html`<div class="st-request" key=${s.id}>
          <span class="st-request-icon"><${Icon} name="user-plus" size=${16} /></span>
          <div class="st-request-main">
            <div class="st-request-title"><strong>${shiftLine(s)}</strong></div>
            ${s.notes && html`<div class="text-sm muted">${s.notes}</div>`}
          </div>
          <div class="st-request-actions">
            ${s.requested ? html`<${Chip} tone="warn" size="sm">Requested</${Chip}>`
    : s.eligible ? html`<${Button} size="sm" variant="primary" onClick=${() => pickUp(s)}>${open.data.requires_approval ? 'Ask to pick up' : 'Pick up'}</${Button}>`
      : html`<span class="muted text-sm">Not your position</span>`}
          </div>
        </div>`)}</div>` : html`<${Empty} icon="calendar-check" compact>No open shifts right now.</${Empty}>`}
      </section>
      <section>
        <h3 class="st-section-title">${history ? 'All requests' : manager ? 'Other open requests' : 'Your requests'} <span class="muted">${rest.length}</span></h3>
        ${rest.length ? html`<div class="st-request-list">${rest.map((r) => html`<${RequestCard} key=${r.id} r=${r} />`)}</div>`
    : html`<${Empty} icon="arrow-right-left" compact>${manager ? 'Nothing else waiting.' : 'Open a shift on the schedule to ask for a swap or drop.'}</${Empty}>`}
      </section>
    </div></div>`;
}
