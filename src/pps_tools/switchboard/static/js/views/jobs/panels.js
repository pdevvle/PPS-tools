// "Jobs" panel in the conversation sidebar: jobs linked to this conversation, create a
// job from it, or link an existing one (e.g. the customer's other jobs).

import { html } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { can } from '../../lib/store.js';
import { navigate } from '../../lib/router.js';
import { useFetch } from '../../lib/hooks.js';
import { IconButton, SidePanel, cx } from '../../ui/components.js';
import { toastError } from '../../ui/overlay.js';
import { pickFromList } from '../../ui/pickers.js';
import { DueChip, StageChip } from './common.js';
import { openNewJob } from './new.js';

function JobRow({ job, onUnlink, onLink }) {
  return html`<div class=${cx('panel-job', job.archived_at && 'is-archived')}>
    <a class="panel-job-main" href=${`/jobs/${job.id}`}>
      <div class="row gap-1"><span class="job-number">${job.number}</span><span class="truncate strong">${job.title}</span></div>
      <div class="row gap-1 mt-1"><${StageChip} stageId=${job.stage_id} size="sm" /><${DueChip} job=${job} /></div>
    </a>
    ${onUnlink && html`<${IconButton} icon="unlink" size="sm" label="Unlink job" class="panel-job-action" onClick=${onUnlink} />`}
    ${onLink && html`<${IconButton} icon="link" size="sm" label="Link to this conversation" class="panel-job-action" onClick=${onLink} />`}
  </div>`;
}

export function ConversationJobsPanel({ conversation, contact, reload: reloadConversation }) {
  const cid = conversation && conversation.id;
  const { data, reload } = useFetch(cid ? `/conversations/${cid}/jobs` : null, {
    refetchOn: ['job.changed', 'conversation.changed'],
    filter: (e, type) => type !== 'conversation.changed' || e.id === cid,
  });
  const manage = can('manage_jobs');
  if (!cid) return null;
  const jobs = data ? data.jobs : [];
  const others = data ? data.customer_jobs : [];
  const done = () => { reload({ quiet: true }); reloadConversation && reloadConversation(); };
  const link = async (jobId) => {
    try { await api.post(`/jobs/${jobId}/conversations`, { conversation_id: cid }); done(); } catch (err) { toastError(err); }
  };
  const unlink = async (jobId) => {
    try { await api.del(`/jobs/${jobId}/conversations/${cid}`); done(); } catch (err) { toastError(err); }
  };
  const pickExisting = async (anchor) => {
    let items = [];
    try { items = (await api.get('/jobs', { done: 0, limit: 200, sort: 'updated', dir: 'desc' })).items; } catch (err) { toastError(err); return; }
    pickFromList(anchor, {
      title: 'Link an existing job',
      placeholder: 'Search by number, title or customer…',
      items: items.filter((j) => !jobs.some((x) => x.id === j.id)).map((j) => ({
        id: j.id, label: `${j.number} · ${j.title}`, hint: j.customer || '', icon: 'square-kanban', keywords: j.customer,
      })),
      multi: false,
      width: 340,
      onChange: (id) => link(id),
    });
  };
  const contactForJob = contact ? { id: contact.id, display_name: contact.display_name || contact.name, email: contact.email, phone: contact.phone } : conversation.contact;
  return html`<${SidePanel} title="Jobs" icon="square-kanban" count=${jobs.length}
    actions=${manage && html`
      <${IconButton} icon="link" size="sm" label="Link an existing job" onClick=${(e) => pickExisting(e.currentTarget)} />
      <${IconButton} icon="plus" size="sm" label="Create a job from this conversation"
        onClick=${() => openNewJob({ conversation: { ...conversation, contact: contactForJob }, contact: contactForJob, navigateTo: false, onCreated: done })} />`}>
    ${jobs.map((j) => html`<${JobRow} key=${j.id} job=${j} onUnlink=${manage ? () => unlink(j.id) : null} />`)}
    ${data && !jobs.length && html`<div class="panel-empty">
      <p class="muted text-sm">No job for this conversation yet.</p>
      ${manage && html`<button type="button" class="btn btn-sm btn-soft" onClick=${() => openNewJob({ conversation: { ...conversation, contact: contactForJob }, contact: contactForJob, navigateTo: false, onCreated: done })}>
        Create a job</button>`}
    </div>`}
    ${others.length > 0 && html`<div class="panel-subhead">Other jobs for this customer</div>
      ${others.map((j) => html`<${JobRow} key=${j.id} job=${j} onLink=${manage ? () => link(j.id) : null} />`)}`}
  </${SidePanel}>`;
}

export function openJob(id) {
  navigate(`/jobs/${id}`);
}
