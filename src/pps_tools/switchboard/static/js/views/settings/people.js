import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch } from '../../lib/hooks.js';
import { useStore, loadBootstrap } from '../../lib/store.js';
import { Avatar, Badge, Button, Checkbox, Field, Input, Loading, Section, Select, Chip, SearchInput, IconButton } from '../../ui/components.js';
import { Modal, openModal, toast, toastError, showMenu, confirmDialog } from '../../ui/overlay.js';

export const ROLE_INFO = {
  owner: ['Owner', 'Everything, including billing-level decisions and other owners'],
  admin: ['Admin', 'Settings, channels, people, rules — plus everything agents can do'],
  manager: ['Manager', 'Inbox and jobs, plus building schedules, approving time off and timesheets, seeing pay rates'],
  agent: ['Agent', 'Team inbox, contacts and jobs; their own schedule and time clock'],
  staff: ['Staff', 'Their own schedule, time clock, time off, chat, tasks and the jobs floor — no inbox'],
};

function PersonForm({ person, teams, onDone, close }) {
  const me = useStore((s) => s.me);
  const isNew = !person;
  const [form, setForm] = useState(() => ({
    name: person?.name || '', email: person?.email || '', role: person?.role || 'agent', title: person?.title || '',
    phone: person?.phone || '', team_ids: person?.team_ids || [], send_invite: true,
  }));
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setForm({ ...form, [k]: v });
  const toggleTeam = (id) => set('team_ids')(form.team_ids.includes(id) ? form.team_ids.filter((t) => t !== id) : [...form.team_ids, id]);
  const roles = Object.keys(ROLE_INFO).filter((r) => r !== 'owner' || me.role === 'owner');
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (isNew) {
        const res = await api.post('/users', form);
        if (res.invite_url && !res.emailed) {
          await navigator.clipboard?.writeText(res.invite_url).catch(() => {});
          toast('Invite link copied — send it to them however you like.', { duration: 7000 });
        } else toast(`Invitation emailed to ${form.email}`);
      } else {
        await api.patch(`/users/${person.id}`, form);
        toast('Saved');
      }
      await loadBootstrap();
      onDone();
      close();
    } catch (err) { toastError(err); } finally { setBusy(false); }
  };
  return html`<${Modal} title=${isNew ? 'Invite a teammate' : `Edit ${person.name}`} onClose=${close}
    footer=${html`<${Button} onClick=${close}>Cancel</${Button}><${Button} variant="primary" type="submit" form="person-form" loading=${busy}>${isNew ? 'Send invite' : 'Save'}</${Button}>`}>
    <form id="person-form" class="stack" onSubmit=${submit}>
      <div class="form-grid">
        <${Field} label="Name"><${Input} value=${form.name} onValue=${set('name')} required autoFocus /></${Field}>
        <${Field} label="Email" hint="They sign in with this"><${Input} type="email" value=${form.email} onValue=${set('email')} required /></${Field}>
        <${Field} label="Job title"><${Input} value=${form.title} onValue=${set('title')} placeholder="Press Operator" /></${Field}>
        <${Field} label="Mobile"><${Input} type="tel" value=${form.phone} onValue=${set('phone')} /></${Field}>
      </div>
      <${Field} label="Role" hint=${ROLE_INFO[form.role][1]}>
        <${Select} value=${form.role} onValue=${set('role')} options=${roles.map((r) => ({ value: r, label: ROLE_INFO[r][0] }))} />
      </${Field}>
      ${teams.length > 0 && html`<${Field} label="Teams" hint="Team members share that team's inbox">
        <div class="row row-wrap gap-3">${teams.map((t) => html`<${Checkbox} key=${t.id} checked=${form.team_ids.includes(t.id)} onChange=${() => toggleTeam(t.id)} label=${t.name} />`)}</div>
      </${Field}>`}
      ${isNew && html`<${Checkbox} checked=${form.send_invite} onChange=${set('send_invite')} label="Email them an invitation (otherwise you'll get a link to share)" />`}
    </form>
  </${Modal}>`;
}

export default function People() {
  const teams = useStore((s) => s.teams);
  const { data, loading, reload } = useFetch('/users', { refetchOn: ['settings.changed'] });
  const [q, setQ] = useState('');
  const [showInactive, setShowInactive] = useState(false);
  const people = (data?.items || [])
    .filter((p) => showInactive || p.is_active)
    .filter((p) => !q || (p.name + ' ' + p.email + ' ' + (p.title || '')).toLowerCase().includes(q.toLowerCase()));
  const open = (person) => openModal((close) => html`<${PersonForm} person=${person} teams=${teams} onDone=${reload} close=${close} />`);
  const actions = (e, p) => showMenu(e.currentTarget, [
    { label: 'Edit', icon: 'pencil', onSelect: () => open(p) },
    {
      label: p.invite_pending ? 'Copy invite link' : 'Copy password reset link',
      icon: 'link',
      onSelect: async () => {
        try {
          const res = await api.post(`/users/${p.id}/invite`, { send: false });
          await navigator.clipboard?.writeText(res.url);
          toast(`${res.kind === 'invite' ? 'Invite' : 'Reset'} link copied`);
        } catch (err) { toastError(err); }
      },
    },
    p.is_active
      ? { label: 'Deactivate', icon: 'user-x', danger: true, onSelect: async () => {
        if (!(await confirmDialog({ title: `Deactivate ${p.name}?`, message: 'They are signed out everywhere and can no longer sign in. Their history stays.', confirmLabel: 'Deactivate', danger: true }))) return;
        try { await api.patch(`/users/${p.id}`, { is_active: false }); reload(); loadBootstrap(); } catch (err) { toastError(err); }
      } }
      : { label: 'Reactivate', icon: 'user-check', onSelect: async () => { try { await api.patch(`/users/${p.id}`, { is_active: true }); reload(); loadBootstrap(); } catch (err) { toastError(err); } } },
  ]);
  const teamName = (id) => teams.find((t) => t.id === id)?.name;
  return html`<${Section} title="People" description="Everyone who can sign in. Staff-only accounts see their schedule, time clock and the jobs floor without the inbox."
    actions=${html`<${Button} variant="primary" icon="user-plus" onClick=${() => open(null)}>Invite</${Button}>`}>
    <div class="row mb-3">
      <${SearchInput} value=${q} onValue=${setQ} placeholder="Search people" class="grow" />
      <${Checkbox} checked=${showInactive} onChange=${setShowInactive} label="Show deactivated" />
    </div>
    ${loading && !data ? html`<${Loading} />` : html`<div class="table-wrap"><table class="table">
      <thead><tr><th>Name</th><th>Role</th><th class="hide-mobile">Teams</th><th></th></tr></thead>
      <tbody>${people.map((p) => html`<tr key=${p.id} class="is-clickable" onClick=${() => open(p)}>
        <td><div class="row"><${Avatar} user=${p} size=${28} online="auto" /><div class="stack-0"><span class="strong">${p.name}</span><span class="muted text-sm">${p.title || p.email}</span></div>
          ${p.invite_pending && html`<${Chip} tone="warn" size="sm">Invited</${Chip}>`}
          ${!p.is_active && html`<${Chip} tone="muted" size="sm">Deactivated</${Chip}>`}</div></td>
        <td>${ROLE_INFO[p.role]?.[0] || p.role}</td>
        <td class="hide-mobile"><div class="row row-wrap gap-1">${(p.team_ids || []).map((t) => html`<${Chip} key=${t} size="sm">${teamName(t)}</${Chip}>`)}</div></td>
        <td style="width:40px" onClick=${(e) => e.stopPropagation()}><${IconButton} icon="ellipsis" label="Actions" onClick=${(e) => actions(e, p)} /></td>
      </tr>`)}</tbody>
    </table></div>`}
  </${Section}>`;
}
