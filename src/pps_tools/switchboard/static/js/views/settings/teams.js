import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useStore, loadBootstrap } from '../../lib/store.js';
import { AvatarStack, Button, Checkbox, ColorChoices, Empty, Field, Input, Section, Select, Toggle, IconButton, Avatar } from '../../ui/components.js';
import { Modal, openModal, toast, toastError, confirmDialog } from '../../ui/overlay.js';

const MODES = [
  { value: 'manual', label: 'Manual — someone picks an owner' },
  { value: 'round_robin', label: 'Round robin — take turns' },
  { value: 'load_balanced', label: 'Load balanced — fewest open conversations' },
  { value: 'on_shift', label: "On shift — whoever's scheduled right now" },
];

function TeamForm({ team, close }) {
  const users = useStore((s) => s.users.filter((u) => u.is_active));
  const [form, setForm] = useState(() => ({
    name: team?.name || '', color: team?.color || '#3b5bdb', description: team?.description || '',
    member_ids: team?.member_ids || [], deliver_to_members: !!team?.deliver_to_members, assignment_mode: team?.assignment_mode || 'manual',
  }));
  const set = (k) => (v) => setForm({ ...form, [k]: v });
  const toggle = (id) => set('member_ids')(form.member_ids.includes(id) ? form.member_ids.filter((x) => x !== id) : [...form.member_ids, id]);
  const submit = async (e) => {
    e.preventDefault();
    try {
      if (team) await api.patch(`/teams/${team.id}`, form);
      else await api.post('/teams', form);
      await loadBootstrap();
      toast('Team saved');
      close();
    } catch (err) { toastError(err); }
  };
  return html`<${Modal} title=${team ? `Edit ${team.name}` : 'New team'} onClose=${close} size="lg"
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="team-form">Save</${Button}>`}>
    <form id="team-form" class="stack" onSubmit=${submit}>
      <div class="form-grid">
        <${Field} label="Team name"><${Input} value=${form.name} onValue=${set('name')} required autoFocus /></${Field}>
        <${Field} label="Description"><${Input} value=${form.description} onValue=${set('description')} placeholder="What this team handles" /></${Field}>
      </div>
      <${Field} label="Color"><${ColorChoices} value=${form.color} onChange=${set('color')} /></${Field}>
      <${Field} label="New conversations get an owner by">
        <${Select} value=${form.assignment_mode} onValue=${set('assignment_mode')} options=${MODES} />
      </${Field}>
      <${Toggle} checked=${form.deliver_to_members} onChange=${set('deliver_to_members')} label="Also put new conversations in every member's personal Inbox"
        hint="Off: they wait in the team inbox until someone takes them" />
      <${Field} label=${`Members (${form.member_ids.length})`}>
        <div class="member-grid">
          ${users.map((u) => html`<label key=${u.id} class="member-choice">
            <${Checkbox} checked=${form.member_ids.includes(u.id)} onChange=${() => toggle(u.id)} />
            <${Avatar} user=${u} size=${22} /><span class="truncate">${u.name}</span>
          </label>`)}
        </div>
      </${Field}>
    </form>
  </${Modal}>`;
}

export default function Teams() {
  const teams = useStore((s) => s.teams);
  const open = (team) => openModal((close) => html`<${TeamForm} team=${team} close=${close} />`);
  const remove = async (team) => {
    if (!(await confirmDialog({ title: `Delete ${team.name}?`, message: 'Its conversations stay, but leave the team inbox.', danger: true, confirmLabel: 'Delete team' }))) return;
    try { await api.del(`/teams/${team.id}`); await loadBootstrap(); } catch (err) { toastError(err); }
  };
  return html`<${Section} title="Teams" description="Each team has a shared inbox. Connect channels (like orders@ or your shop's text number) to a team so its members handle them together."
    actions=${html`<${Button} variant="primary" icon="plus" onClick=${() => open(null)}>New team</${Button}>`}>
    ${!teams.length && html`<${Empty} icon="users-round" title="No teams yet">Create teams like “Front Office” or “Production”.</${Empty}>`}
    <div class="stack">
      ${teams.map((t) => html`<div class="card" key=${t.id}><div class="card-body row">
        <span class="sidebar-dot" style=${{ background: t.color }}></span>
        <div class="grow"><div class="strong">${t.name}</div><div class="muted text-sm">${t.description || MODES.find((m) => m.value === t.assignment_mode)?.label}</div></div>
        <${AvatarStack} users=${t.member_ids} max=${5} />
        <${IconButton} icon="pencil" label="Edit" onClick=${() => open(t)} />
        <${IconButton} icon="trash" label="Delete" onClick=${() => remove(t)} />
      </div></div>`)}
    </div>
  </${Section}>`;
}
