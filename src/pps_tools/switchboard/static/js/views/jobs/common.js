// Shared bits for the jobs module: stage/priority/due chips, the job card, menus.

import { html } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { boot, can } from '../../lib/store.js';
import { navigate } from '../../lib/router.js';
import { fmtDate, fmtTimeShort, fmtDuration, fmtMoney } from '../../lib/format.js';
import { isSameDay, addDays } from '../../lib/dates.js';
import { AvatarStack, Chip, Icon, cx } from '../../ui/components.js';
import { showMenu, toast, toastError } from '../../ui/overlay.js';

// Server events that can change what a jobs screen shows.
export const JOB_EVENTS = ['job.changed', 'settings.changed'];

export const PRIORITIES = [
  { value: 'low', label: 'Low' },
  { value: 'normal', label: 'Normal' },
  { value: 'high', label: 'High' },
  { value: 'rush', label: 'Rush' },
];

export const STATUS_LABEL = { pending: 'Not started', in_progress: 'In progress', done: 'Done' };

export function stages() {
  return boot('job_stages');
}

export function stageOf(id) {
  return stages().find((s) => s.id === id) || null;
}

export function resourceOf(id) {
  return boot('resources').find((r) => r.id === id) || null;
}

export function skillOf(id) {
  return boot('job_skills').find((s) => s.id === id) || null;
}

export function StageChip({ stageId, size }) {
  const st = stageOf(stageId);
  if (!st) return html`<${Chip} size=${size} tone="muted">No stage</${Chip}>`;
  return html`<${Chip} color=${st.color || '#868e96'} size=${size}>${st.name}</${Chip}>`;
}

export function PriorityChip({ priority, size = 'sm', showNormal = false }) {
  if (priority === 'rush') return html`<${Chip} tone="danger" size=${size} icon="flame">Rush</${Chip}>`;
  if (priority === 'high') return html`<${Chip} tone="orange" size=${size}>High</${Chip}>`;
  if (priority === 'low') return html`<${Chip} tone="muted" size=${size}>Low</${Chip}>`;
  return showNormal ? html`<${Chip} tone="muted" size=${size}>Normal</${Chip}>` : null;
}

export function dueLabel(due) {
  if (!due) return '';
  const d = new Date(due);
  const today = new Date();
  if (isSameDay(d, today)) return `Today ${fmtTimeShort(d)}`;
  if (isSameDay(d, addDays(today, 1))) return `Tomorrow ${fmtTimeShort(d)}`;
  if (isSameDay(d, addDays(today, -1))) return `Yesterday ${fmtTimeShort(d)}`;
  return fmtDate(d, { weekday: true });
}

export function DueChip({ job, size = 'sm' }) {
  if (job.is_done) return html`<${Chip} tone="ok" size=${size} icon="check">Done</${Chip}>`;
  if (!job.due_at) return null;
  const tone = job.due_state === 'overdue' ? 'danger' : job.due_state === 'soon' ? 'warn' : 'muted';
  return html`<${Chip} tone=${tone} size=${size} icon=${job.due_state === 'overdue' ? 'triangle-alert' : 'clock'}
    title=${job.due_state === 'overdue' ? 'Overdue' : 'Due'}>${dueLabel(job.due_at)}</${Chip}>`;
}

export function ProofChip({ status, size = 'sm' }) {
  if (status === 'pending') return html`<${Chip} tone="purple" size=${size} icon="eye">Proof out</${Chip}>`;
  if (status === 'approved') return html`<${Chip} tone="ok" size=${size} icon="badge-check">Approved</${Chip}>`;
  if (status === 'changes_requested') return html`<${Chip} tone="warn" size=${size} icon="pencil">Changes</${Chip}>`;
  return null;
}

export function customerOf(job) {
  return job.customer || (job.contact && job.contact.display_name) || '';
}

export function JobCard({ job, onClick, dragging, draggable, onDragStart, onDragEnd, onMenu, compact }) {
  const ops = job.operations || {};
  const cl = job.checklist || {};
  return html`<article
    class=${cx('job-card', dragging && 'is-dragging', job.priority === 'rush' && 'is-rush', job.due_state === 'overdue' && 'is-overdue')}
    draggable=${draggable ? 'true' : undefined}
    onDragStart=${onDragStart}
    onDragEnd=${onDragEnd}
    onClick=${onClick}
    data-job-id=${job.id}
    tabIndex="0"
    onKeyDown=${(e) => { if (e.key === 'Enter') onClick && onClick(e); }}
    aria-label=${`${job.number} ${job.title}`}
  >
    <div class="job-card-top">
      <span class="job-number">${job.number}</span>
      <${PriorityChip} priority=${job.priority} />
      <${ProofChip} status=${job.proof_status} />
      ${onMenu && html`<button type="button" class="job-card-menu" aria-label="Job actions"
        onClick=${(e) => { e.stopPropagation(); onMenu(e); }}><${Icon} name="ellipsis" size=${15} /></button>`}
    </div>
    <div class="job-card-title">${job.title}</div>
    ${customerOf(job) && html`<div class="job-card-customer">${customerOf(job)}</div>`}
    ${!compact && html`<div class="job-card-meta">
      <${DueChip} job=${job} />
      ${ops.total ? html`<span class="job-meta-item" title="Steps done"><${Icon} name="chart-gantt" size=${13} />${ops.done}/${ops.total}</span>` : null}
      ${cl.total ? html`<span class="job-meta-item" title="Checklist"><${Icon} name="list-checks" size=${13} />${cl.done}/${cl.total}</span>` : null}
      ${job.comment_count ? html`<span class="job-meta-item" title="Comments"><${Icon} name="message-square" size=${13} />${job.comment_count}</span>` : null}
      ${job.conversation_count ? html`<span class="job-meta-item" title="Linked conversations"><${Icon} name="mail" size=${13} />${job.conversation_count}</span>` : null}
      <span class="grow"></span>
      ${job.assignee_ids && job.assignee_ids.length ? html`<${AvatarStack} users=${job.assignee_ids} size=${20} max=${3} />` : null}
    </div>`}
    ${ops.active ? html`<div class="job-card-live"><span class="live-dot"></span>On ${ops.active === 1 ? 'a step' : `${ops.active} steps`} now</div>` : null}
  </article>`;
}

export async function moveJob(job, stageId, position) {
  const res = await api.post(`/jobs/${job.id}/move`, { stage_id: stageId, position });
  if (res.job && res.job.wip_exceeded) {
    const st = stageOf(stageId);
    toast(`${st ? st.name : 'That stage'} is over its WIP limit`, { tone: 'default', icon: 'triangle-alert' });
  }
  return res.job;
}

// "Move to…" / open / archive menu for a job card or row.
export function openJobMenu(anchor, job, { onChanged } = {}) {
  const manage = can('manage_jobs');
  const items = [
    { label: 'Open', icon: 'external-link', onSelect: () => navigate(`/jobs/${job.id}`) },
  ];
  if (manage) {
    items.push({ divider: true }, { header: 'Move to' });
    for (const st of stages()) {
      items.push({
        label: st.name,
        color: st.color,
        checked: st.id === job.stage_id,
        onSelect: async () => {
          try { await moveJob(job, st.id); onChanged && onChanged(); } catch (err) { toastError(err); }
        },
      });
    }
    items.push({ divider: true }, {
      label: job.archived_at ? 'Unarchive' : 'Archive',
      icon: 'archive',
      onSelect: async () => {
        try {
          await api.post(`/jobs/${job.id}/archive`, { archived: !job.archived_at });
          toast(job.archived_at ? 'Job restored' : `${job.number} archived`);
          onChanged && onChanged();
        } catch (err) { toastError(err); }
      },
    });
  }
  showMenu(anchor, items, { width: 230 });
}

export function opSummary(op) {
  const res = resourceOf(op.resource_id);
  return [res && res.name, op.duration_minutes && fmtDuration(op.duration_minutes)].filter(Boolean).join(' · ');
}

export function moneyOrDash(n) {
  return n === null || n === undefined || n === '' ? '—' : fmtMoney(n);
}
