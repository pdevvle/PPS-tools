// Right-hand sidebar of a conversation: details, reminders, AI summary, and panels
// contributed by other modules (contact card, jobs, tasks, integrations).

import { html, useEffect, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useStore, hasModule, user as lookupUser } from '../../lib/store.js';
import { fmtDateTime, fmtDuration, fmtUntil } from '../../lib/format.js';
import { minutesBetween } from '../../lib/dates.js';
import { AvatarStack, Button, Chip, Icon, IconButton, KeyValue, SidePanel, Spinner } from '../../ui/components.js';
import { toastError } from '../../ui/overlay.js';
import { RichText } from '../../ui/editor.js';
import { PANELS } from './panels.js';
import { act, getAIStatus, openAssign, openMoveTeam, openPriority, openReminder } from './common.js';

let panelCache = null;
function usePanels() {
  const [panels, setPanels] = useState(panelCache);
  useEffect(() => {
    if (panelCache) return;
    Promise.all(PANELS.filter((p) => hasModule(p.module)).map((p) => p.load().then((m) => (m[p.name] ? { ...p, Component: m[p.name] } : null)).catch(() => null)))
      .then((list) => { panelCache = list.filter(Boolean); setPanels(panelCache); });
  }, []);
  return panels; // null while loading
}

function AISummary({ conv }) {
  const [status, setStatus] = useState(null);
  const [summary, setSummary] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { getAIStatus().then(setStatus); }, []);
  useEffect(() => setSummary(null), [conv.id]);
  if (!status?.configured || !conv.message_count) return null;
  const run = async () => {
    setBusy(true);
    try { setSummary(await api.post('/ai/summarize', { conversation_id: conv.id })); } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  return html`<${SidePanel} title="AI summary" icon="sparkles" actions=${summary && html`<${IconButton} icon="refresh-cw" size="sm" label="Summarize again" onClick=${run} />`}>
    ${summary
    ? html`<div class="ai-summary"><${RichText} html=${summary.summary_html} />${summary.next_step && html`<p class="ai-next"><b>Next step:</b> ${summary.next_step}</p>`}</div>`
    : html`<${Button} size="sm" icon="sparkles" onClick=${run} loading=${busy}>Summarize this conversation</${Button}>`}
  </${SidePanel}>`;
}

function Reminders({ detail, reload }) {
  const conv = detail.conversation;
  const remove = (r) => api.del(`/reminders/${r.id}`).then(reload).catch(toastError);
  return html`<div class="detail-reminders">
    ${detail.reminders.map((r) => html`<div class="detail-reminder" key=${r.id}>
      <${Icon} name="bell" size=${13} />
      <span class="grow">${fmtUntil(r.remind_at)}${r.condition === 'no_reply' ? ' if no reply' : ''}${r.note ? ` — ${r.note}` : ''}</span>
      <${IconButton} icon="x" size="sm" label="Remove reminder" onClick=${() => remove(r)} />
    </div>`)}
    <button type="button" class="btn-link text-sm" onClick=${(e) => openReminder(e.currentTarget, conv)}>+ Remind me</button>
  </div>`;
}

export function ConversationDetails({ detail, reload }) {
  const conv = detail.conversation;
  const teams = useStore((s) => s.teamsById);
  const meId = useStore((s) => s.me.id);
  const panels = usePanels();
  const team = conv.team_id ? teams[conv.team_id] : null;
  const firstResponse = conv.first_response_at && conv.created_at ? minutesBetween(conv.created_at, conv.first_response_at) : null;
  return html`<aside class="conv-details" aria-label="Conversation details">
    <${SidePanel} title="Details" icon="info">
      <${KeyValue} items=${[
    ['Assigned', html`<button type="button" class="detail-link" onClick=${(e) => openAssign(e.currentTarget, [conv])}>
          ${conv.assignee_ids.length ? html`<${AvatarStack} users=${conv.assignee_ids} max=${4} size=${20} /> <span class="truncate">${conv.assignee_ids.map((id) => lookupUser(id).name.split(' ')[0]).join(', ')}</span>` : 'Nobody — assign'}
        </button>`],
    ['Team', html`<button type="button" class="detail-link" onClick=${(e) => openMoveTeam(e.currentTarget, [conv.id])}>${team ? html`<${Chip} size="sm" color=${team.color}>${team.name}</${Chip}>` : 'None'}</button>`],
    ['Priority', html`<button type="button" class="detail-link" onClick=${(e) => openPriority(e.currentTarget, [conv.id])}>${conv.priority[0].toUpperCase() + conv.priority.slice(1)}</button>`],
    ['Status', conv.status === 'open' ? (conv.awaiting_reply ? html`<span class=${conv.overdue ? 'text-danger' : ''}>Waiting for reply${conv.overdue ? ' · overdue' : ''}</span>` : 'Open') : 'Closed'],
    ['Started', fmtDateTime(conv.created_at)],
    firstResponse !== null && ['First reply', fmtDuration(firstResponse)],
    ['Followers', html`<span class="row gap-1">
          ${conv.followers.length ? html`<${AvatarStack} users=${conv.followers} max=${5} size=${20} />` : html`<span class="muted">None</span>`}
          <button type="button" class="btn-link text-sm" onClick=${() => act([conv.id], conv.followers.includes(meId) ? 'unfollow' : 'follow').then(reload)}>${conv.followers.includes(meId) ? 'Unfollow' : 'Follow'}</button>
        </span>`],
  ]} />
      <div class="mt-3"><${Reminders} detail=${detail} reload=${reload} /></div>
    </${SidePanel}>
    <${AISummary} conv=${conv} />
    ${(panels || []).map(({ id, Component }) => html`<${Component} key=${id} conversation=${conv} contact=${detail.contact} detail=${detail} reload=${reload} />`)}
    ${!panels && html`<div class="detail-loading"><${Spinner} size=${14} /></div>`}
  </aside>`;
}
