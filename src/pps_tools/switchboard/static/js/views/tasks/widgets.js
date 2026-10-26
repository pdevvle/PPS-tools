// "My tasks" card for My Day.

import { html } from '../../lib/preact.js';
import { useFetch } from '../../lib/hooks.js';
import { Button, Card, Empty, Loading } from '../../ui/components.js';
import { navigate } from '../../lib/router.js';
import { TaskRow, groupTasks, openTask } from './shared.js';

export function MyTasksWidget() {
  const { data, loading, setData } = useFetch('/tasks', { query: { view: 'mine' }, refetchOn: ['task.changed'] });
  const replace = (task) => setData((d) => d && { ...d, items: d.items.map((t) => (t.id === task.id ? task : t)) });
  const groups = groupTasks((data?.items || []).filter((t) => t.status !== 'done'));
  const shown = groups.flatMap(([, , list]) => list).slice(0, 7);
  const total = groups.reduce((n, [, , list]) => n + list.length, 0);
  return html`<${Card} title="My tasks" icon="square-check-big" pad=${false}
    actions=${html`<${Button} size="sm" variant="ghost" onClick=${() => navigate('/tasks')}>${total > shown.length ? `All ${total}` : 'Open'}</${Button}>`}>
    ${loading && !data && html`<${Loading} />`}
    ${data && !shown.length && html`<${Empty} icon="circle-check" title="Nothing due" compact>Enjoy the quiet — or grab something from the jobs board.</${Empty}>`}
    <div class="task-widget">${shown.map((t) => html`<${TaskRow} key=${t.id} task=${t} onChange=${replace} showAssignee=${false} onOpen=${(t) => openTask(t.id)} />`)}</div>
  </${Card}>`;
}
