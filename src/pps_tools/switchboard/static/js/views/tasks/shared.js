// Task rows, quick add and the task detail drawer, shared by /tasks, the conversation
// sidebar panel and the My Day widget.

import { html, useEffect, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch } from '../../lib/hooks.js';
import { navigate } from '../../lib/router.js';
import { useStore, user as lookupUser } from '../../lib/store.js';
import { fmtDate, fmtDateTime, fmtTimeShort } from '../../lib/format.js';
import { isSameDay, addDays, startOfDay } from '../../lib/dates.js';
import { Avatar, Button, Chip, Icon, IconButton, Loading, Segmented, Select, cx } from '../../ui/components.js';
import { confirmDialog, openModal, toastError } from '../../ui/overlay.js';
import { pickDateTime, pickUsers } from '../../ui/pickers.js';
import { RichEditor } from '../../ui/editor.js';

export const PRIORITY = {
  low: { label: 'Low', tone: 'muted' },
  normal: { label: 'Normal', tone: 'muted' },
  high: { label: 'High', tone: 'orange' },
  urgent: { label: 'Urgent', tone: 'danger' },
};

export function dueLabel(t) {
  if (!t.due_at) return null;
  const d = new Date(t.due_at);
  const today = startOfDay(new Date());
  const time = d.getHours() || d.getMinutes() ? ` ${fmtTimeShort(d)}` : '';
  if (isSameDay(d, today)) return `Today${time}`;
  if (isSameDay(d, addDays(today, 1))) return `Tomorrow${time}`;
  if (isSameDay(d, addDays(today, -1))) return `Yesterday${time}`;
  return fmtDate(d, { weekday: true }) + (time ? `,${time}` : '');
}

// Overdue / Today / Upcoming / No due date / Done
export function groupTasks(items) {
  const now = new Date();
  const endToday = addDays(startOfDay(now), 1);
  const groups = { overdue: [], today: [], upcoming: [], none: [], done: [] };
  for (const t of items) {
    if (t.status === 'done') groups.done.push(t);
    else if (!t.due_at) groups.none.push(t);
    else if (new Date(t.due_at) < now) groups.overdue.push(t);
    else if (new Date(t.due_at) < endToday) groups.today.push(t);
    else groups.upcoming.push(t);
  }
  const byDue = (a, b) => (a.due_at || '').localeCompare(b.due_at || '') || a.position - b.position;
  groups.overdue.sort(byDue);
  groups.upcoming.sort(byDue);
  groups.today.sort((a, b) => a.position - b.position || byDue(a, b));
  groups.none.sort((a, b) => a.position - b.position);
  groups.done.sort((a, b) => (b.completed_at || '').localeCompare(a.completed_at || ''));
  return [
    ['overdue', 'Overdue', groups.overdue],
    ['today', 'Today', groups.today],
    ['upcoming', 'Upcoming', groups.upcoming],
    ['none', 'No due date', groups.none],
    ['done', 'Done', groups.done],
  ].filter(([, , list]) => list.length);
}

export async function toggleDone(t, onChange) {
  const status = t.status === 'done' ? 'todo' : 'done';
  onChange && onChange({ ...t, status });
  try {
    const res = await api.patch(`/tasks/${t.id}`, { status });
    onChange && onChange(res.task);
  } catch (err) { toastError(err); onChange && onChange(t); }
}

export function TaskCheck({ task, onChange }) {
  const done = task.status === 'done';
  return html`<button type="button" class=${cx('task-check', done && 'is-done', task.status === 'in_progress' && 'is-progress')}
    aria-label=${done ? 'Mark as not done' : 'Mark as done'} aria-pressed=${done}
    onClick=${(e) => { e.stopPropagation(); toggleDone(task, onChange); }}>
    ${done && html`<${Icon} name="check" size=${12} strokeWidth=${3} />`}
  </button>`;
}

// Open a task's details over whatever page you're on (inbox sidebar, My Day).
export function openTask(id) {
  openModal((close) => html`<${TaskDrawer} id=${id} onClose=${close} />`);
}

export function TaskRow({ task, onChange, compact = false, showAssignee = true, draggable = false, onDragStart, onDragOver, onDrop, dragging, onOpen }) {
  const due = dueLabel(task);
  const pri = PRIORITY[task.priority];
  const open = () => (onOpen ? onOpen(task) : navigate(`/tasks?task=${task.id}`));
  return html`<div
    class=${cx('task-row', task.status === 'done' && 'is-done', task.overdue && 'is-overdue', compact && 'is-compact', dragging && 'is-dragging')}
    role="button" tabIndex="0"
    draggable=${draggable}
    onDragStart=${onDragStart} onDragOver=${onDragOver} onDrop=${onDrop}
    onClick=${open}
    onKeyDown=${(e) => { if (e.key === 'Enter') open(); }}
  >
    ${draggable && html`<span class="task-grip" aria-hidden="true"><${Icon} name="grip-vertical" size=${14} /></span>`}
    <${TaskCheck} task=${task} onChange=${onChange} />
    <div class="task-main">
      <div class="task-title">${task.title}</div>
      ${!compact && html`<div class="task-meta">
        ${due && html`<span class=${cx('task-due', task.overdue && 'is-overdue', due.startsWith('Today') && 'is-today')}><${Icon} name="clock" size=${12} />${due}</span>`}
        ${task.status === 'in_progress' && html`<${Chip} size="sm" tone="info">In progress</${Chip}>`}
        ${task.priority !== 'normal' && task.priority !== 'low' && html`<${Chip} size="sm" tone=${pri.tone} icon="flag">${pri.label}</${Chip}>`}
        ${task.conversation && html`<a class="task-link" href=${`/inbox/c/${task.conversation.id}`} onClick=${(e) => e.stopPropagation()}>
          <${Icon} name="mail" size=${12} /><span>${task.conversation.subject}</span></a>`}
        ${task.job && html`<a class="task-link" href=${`/jobs/${task.job.id}`} onClick=${(e) => e.stopPropagation()}>
          <${Icon} name="square-kanban" size=${12} /><span>${task.job.number}</span></a>`}
      </div>`}
    </div>
    ${compact && due && html`<span class=${cx('task-due', task.overdue && 'is-overdue')}>${due}</span>`}
    ${showAssignee && task.assignee_id && html`<${Avatar} user=${task.assignee_id} size=${22} />`}
  </div>`;
}

// One-line "add a task" bar. defaults: extra fields for the new task (conversation_id...).
export function QuickAdd({ defaults = {}, placeholder = 'Add a task…', onCreated, assigneeDefault }) {
  const me = useStore((s) => s.me);
  const [title, setTitle] = useState('');
  const [due, setDue] = useState(null);
  const [assignee, setAssignee] = useState(assigneeDefault === undefined ? me.id : assigneeDefault);
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    try {
      const res = await api.post('/tasks', { title: title.trim(), due_at: due, assignee_id: assignee, ...defaults });
      setTitle('');
      setDue(null);
      onCreated && onCreated(res.task);
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  const who = assignee ? lookupUser(assignee) : null;
  return html`<form class="task-quick-add" onSubmit=${submit}>
    <${Icon} name="plus" size=${16} class="task-quick-icon" />
    <input class="task-quick-input" value=${title} placeholder=${placeholder} aria-label="New task title"
      onInput=${(e) => setTitle(e.currentTarget.value)} disabled=${busy} />
    <button type="button" class=${cx('task-quick-chip', due && 'is-set')} data-tip="Due date"
      onClick=${(e) => pickDateTime(e.currentTarget, { value: due, title: 'Due', onChange: setDue })}>
      <${Icon} name="calendar" size=${14} />${due ? html`<span>${dueLabel({ due_at: due })}</span>` : null}
    </button>
    <button type="button" class="task-quick-chip" data-tip=${who ? `Assigned to ${who.name}` : 'Unassigned'}
      onClick=${(e) => pickUsers(e.currentTarget, { multi: false, selected: assignee ? [assignee] : [],
    extra: [{ id: 0, label: 'Unassigned', icon: 'user' }], onChange: (id) => setAssignee(id || null) })}>
      ${who ? html`<${Avatar} user=${who} size=${20} />` : html`<${Icon} name="user" size=${14} />`}
    </button>
    <${Button} size="sm" variant="primary" type="submit" disabled=${!title.trim()} loading=${busy}>Add</${Button}>
  </form>`;
}

// Right-hand drawer for ?task=<id>
// Grow a textarea to fit its text (the title can wrap over a few lines).
function fitHeight(el) {
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = el.scrollHeight + 'px';
}

export function TaskDrawer({ id, onClose }) {
  const teams = useStore((s) => s.teams);
  const me = useStore((s) => s.me);
  const { data, loading, error, setData } = useFetch(`/tasks/${id}`, { refetchOn: ['task.changed'], filter: (e) => !e.id || e.id === id || (e.ids || []).includes(id) });
  const [desc, setDesc] = useState(null);
  const saveTimer = useRef(null);
  const task = data?.task;
  useEffect(() => { if (task && desc === null) setDesc(task.description || ''); }, [task?.id]);
  useEffect(() => () => clearTimeout(saveTimer.current), []);
  const patch = async (values) => {
    setData((d) => ({ ...d, task: { ...d.task, ...values } }));
    try {
      const res = await api.patch(`/tasks/${id}`, values);
      setData((d) => ({ ...d, task: res.task }));
    } catch (err) { toastError(err); }
  };
  const onDesc = (value) => {
    setDesc(value);
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => patch({ description: value }), 700);
  };
  const remove = async () => {
    if (!(await confirmDialog({ title: 'Delete this task?', danger: true, confirmLabel: 'Delete' }))) return;
    try { await api.del(`/tasks/${id}`); onClose(); } catch (err) { toastError(err); }
  };
  return html`<div class="task-drawer-backdrop" onMouseDown=${(e) => e.target === e.currentTarget && onClose()}>
    <aside class="task-drawer" role="dialog" aria-label="Task details">
      <header class="task-drawer-head">
        <span class="muted text-sm">Task</span>
        <span class="grow"></span>
        ${task && html`<${IconButton} icon="trash" label="Delete task" onClick=${remove} />`}
        <${IconButton} icon="x" label="Close" onClick=${onClose} />
      </header>
      ${loading && !data && html`<${Loading} />`}
      ${error && html`<div class="pad muted">This task doesn't exist or you can't see it.</div>`}
      ${task && html`<div class="task-drawer-body">
        <div class="row row-top gap-2">
          <${TaskCheck} task=${task} onChange=${(t) => setData((d) => ({ ...d, task: t }))} />
          <textarea class="task-title-input" rows="1" value=${task.title} aria-label="Title" ref=${fitHeight}
            onInput=${(e) => fitHeight(e.currentTarget)}
            onBlur=${(e) => { const v = e.currentTarget.value.trim(); if (v && v !== task.title) patch({ title: v }); }}
            onKeyDown=${(e) => { if (e.key === 'Enter') { e.preventDefault(); e.currentTarget.blur(); } }}></textarea>
        </div>
        <${Segmented} size="sm" value=${task.status} onChange=${(status) => patch({ status })}
          options=${[{ value: 'todo', label: 'To do' }, { value: 'in_progress', label: 'In progress' }, { value: 'done', label: 'Done' }]} />
        <dl class="task-props">
          <dt>Assignee</dt>
          <dd><button type="button" class="task-prop-btn" onClick=${(e) => pickUsers(e.currentTarget, {
    multi: false, selected: task.assignee_id ? [task.assignee_id] : [], extra: [{ id: 0, label: 'Unassigned', icon: 'user' }],
    onChange: (uid) => patch({ assignee_id: uid || null }),
  })}>${task.assignee_id ? html`<${Avatar} user=${task.assignee_id} size=${20} /><span>${lookupUser(task.assignee_id).name}${task.assignee_id === me.id ? ' (you)' : ''}</span>` : html`<span class="muted">Unassigned</span>`}</button></dd>
          <dt>Due</dt>
          <dd><button type="button" class=${cx('task-prop-btn', task.overdue && 'is-overdue')}
            onClick=${(e) => pickDateTime(e.currentTarget, { value: task.due_at, title: 'Due', onChange: (due_at) => patch({ due_at }) })}>
            <${Icon} name="calendar" size=${14} />${task.due_at ? fmtDateTime(task.due_at) : html`<span class="muted">No due date</span>`}</button></dd>
          <dt>Priority</dt>
          <dd><${Select} class="input-sm task-prop-select" value=${task.priority} onValue=${(priority) => patch({ priority })}
            options=${Object.entries(PRIORITY).map(([value, p]) => ({ value, label: p.label }))} /></dd>
          <dt>Team</dt>
          <dd><${Select} class="input-sm task-prop-select" value=${task.team_id || ''} placeholder="No team"
            onValue=${(v) => patch({ team_id: v ? Number(v) : null })} options=${teams.map((t) => ({ value: t.id, label: t.name }))} /></dd>
          ${task.conversation && html`<dt>Conversation</dt><dd><a href=${`/inbox/c/${task.conversation.id}`} class="task-prop-link"><${Icon} name="mail" size=${13} />${task.conversation.subject}</a></dd>`}
          ${task.job && html`<dt>Job</dt><dd><a href=${`/jobs/${task.job.id}`} class="task-prop-link"><${Icon} name="square-kanban" size=${13} />${task.job.number} · ${task.job.title}</a></dd>`}
        </dl>
        <div class="task-desc">
          <${RichEditor} value=${desc ?? task.description ?? ''} onChange=${onDesc} toolbar="mini" placeholder="Add details, links, checklists…" minHeight=${120} mentions />
        </div>
        <div class="task-foot muted text-sm">
          Created by ${lookupUser(task.created_by).name} · ${fmtDateTime(task.created_at)}
          ${task.completed_at && html`<br />Completed by ${lookupUser(task.completed_by).name} · ${fmtDateTime(task.completed_at)}`}
        </div>
      </div>`}
    </aside>
  </div>`;
}
