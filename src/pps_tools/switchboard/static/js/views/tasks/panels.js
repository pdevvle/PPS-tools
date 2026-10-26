// Tasks for one conversation, in the inbox sidebar.

import { html } from '../../lib/preact.js';
import { useFetch } from '../../lib/hooks.js';
import { SidePanel } from '../../ui/components.js';
import { QuickAdd, TaskRow, openTask } from './shared.js';

export function ConversationTasksPanel({ conversation }) {
  if (!conversation) return null;
  return html`<${PanelBody} key=${conversation.id} cid=${conversation.id} />`;
}

function PanelBody({ cid }) {
  const { data, reload, setData } = useFetch('/tasks', {
    query: { conversation_id: cid },
    refetchOn: ['task.changed'],
    filter: (e) => !e.conversation_id || e.conversation_id === cid || Array.isArray(e.ids),
  });
  const items = data?.items || [];
  const open = items.filter((t) => t.status !== 'done').length;
  const replace = (task) => setData((d) => d && { ...d, items: d.items.map((t) => (t.id === task.id ? task : t)) });
  return html`<${SidePanel} title="Tasks" icon="square-check-big" count=${open || null}>
    <div class="task-panel">
      ${items.map((t) => html`<${TaskRow} key=${t.id} task=${t} onChange=${replace} compact onOpen=${(t) => openTask(t.id)} />`)}
      <${QuickAdd} defaults=${{ conversation_id: cid }} placeholder="Add a follow-up…" onCreated=${() => reload({ quiet: true })} />
    </div>
  </${SidePanel}>`;
}
