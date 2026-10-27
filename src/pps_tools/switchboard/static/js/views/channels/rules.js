// Settings → Rules: automation that labels, routes, assigns and replies as messages
// arrive. Rules run top to bottom; each can stop the ones below it.

import { html, useEffect, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useDebounced, useFetch } from '../../lib/hooks.js';
import { user } from '../../lib/store.js';
import {
  Banner, Button, Chip, Empty, ErrorBox, Field, Icon, IconButton, Input, Loading, RelTime, SearchInput, Section,
  Segmented, Select, Toggle, cx,
} from '../../ui/components.js';
import { Modal, confirmDialog, openModal, showMenu, toast, toastError } from '../../ui/overlay.js';
import { pickFromList, pickUsers } from '../../ui/pickers.js';
import { RichEditor } from '../../ui/editor.js';

const TRIGGER_ICONS = { incoming: 'mail', new_conversation: 'message-square-text', outgoing: 'send', comment: 'message-square' };

export const FIELDS = {
  from: 'Sender', to: 'To', cc: 'Cc', subject: 'Subject', body: 'Message text', channel: 'Channel',
  channel_type: 'Channel type', has_attachment: 'Has an attachment', is_reply: 'Is a reply', label: 'Label',
  assigned: 'Is assigned', team: 'Team', contact_group: 'Contact group', business_hours: 'Business hours',
  weekday: 'Day of the week', priority: 'Priority',
};

const OPS = {
  contains: 'contains', not_contains: "doesn't contain", equals: 'is exactly', starts_with: 'starts with',
  ends_with: 'ends with', matches: 'matches pattern', is: 'is', is_not: 'is not', has: 'has', lacks: "doesn't have",
  in: 'is in', not_in: "isn't in",
};

export const ACTIONS = {
  assign: 'Assign', unassign: 'Remove assignees', add_label: 'Add label', remove_label: 'Remove label',
  move_team: 'Move to team', priority: 'Set priority', snooze: 'Snooze', close: 'Close', reopen: 'Reopen',
  auto_reply: 'Send an auto-reply', add_comment: 'Add an internal comment', forward: 'Forward to email',
  notify: 'Notify teammates', webhook: 'Send a webhook', spam: 'Mark as spam', trash: 'Move to trash',
  stop: 'Stop processing more rules',
};

const CHANNEL_TYPES = [
  { id: 'email', label: 'Email' }, { id: 'sms', label: 'SMS' }, { id: 'whatsapp', label: 'WhatsApp' },
  { id: 'chat', label: 'Website chat' }, { id: 'api', label: 'API & forms' },
];
const PRIORITIES = ['low', 'normal', 'high', 'urgent'];
const DAYS = [['mon', 'Mon'], ['tue', 'Tue'], ['wed', 'Wed'], ['thu', 'Thu'], ['fri', 'Fri'], ['sat', 'Sat'], ['sun', 'Sun']];
const TEXT_FIELDS = ['from', 'to', 'cc', 'subject', 'body'];

const TEMPLATES = [
  {
    id: 'after_hours', icon: 'clock', title: 'Auto-reply after hours',
    text: 'Let people know when you\'ll answer if they write while you\'re closed.',
    rule: { name: 'After-hours auto-reply', trigger: 'new_conversation', match: 'all',
      conditions: [{ field: 'business_hours', op: 'is', value: 'outside' }], actions: [{ type: 'auto_reply' }] },
  },
  {
    id: 'keyword_label', icon: 'tag', title: 'Label by keyword',
    text: 'Tag quote requests, rush orders or invoices from the words they use.',
    rule: { name: 'Label quote requests', trigger: 'incoming', match: 'any',
      conditions: [{ field: 'subject', op: 'contains', value: 'quote, estimate' }, { field: 'body', op: 'contains', value: 'quote, estimate' }],
      actions: [{ type: 'add_label', label_ids: [] }] },
  },
  {
    id: 'route_texts', icon: 'smartphone', title: 'Route texts to a team',
    text: 'Send SMS and WhatsApp conversations to the people who answer the phone.',
    rule: { name: 'Texts go to the front desk', trigger: 'new_conversation', match: 'all',
      conditions: [{ field: 'channel_type', op: 'is', value: ['sms', 'whatsapp'] }], actions: [{ type: 'move_team' }] },
  },
  {
    id: 'on_shift', icon: 'user-check', title: 'Assign to whoever is on shift',
    text: 'New conversations go to someone who is working right now (from the schedule and time clock).',
    rule: { name: 'Assign to whoever is on shift', trigger: 'new_conversation', match: 'all', conditions: [],
      actions: [{ type: 'assign', mode: 'on_shift' }] },
  },
  {
    id: 'forward_invoices', icon: 'forward', title: 'Forward invoices',
    text: 'Copy vendor invoices to your bookkeeper automatically.',
    rule: { name: 'Forward invoices to the bookkeeper', trigger: 'incoming', match: 'all',
      conditions: [{ field: 'subject', op: 'contains', value: 'invoice' }], actions: [{ type: 'forward', to: '' }] },
  },
];

function names(list, ids) {
  const set = new Set((ids || []).map(Number));
  return list.filter((x) => set.has(x.id)).map((x) => x.name || x.title).join(', ');
}

export function describeCondition(c, opts) {
  const v = c.value;
  let value;
  if (TEXT_FIELDS.includes(c.field)) value = `“${v}”`;
  else if (c.field === 'channel') value = names(opts.channels, v) || 'a channel';
  else if (c.field === 'channel_type') value = (v || []).map((t) => CHANNEL_TYPES.find((x) => x.id === t)?.label || t).join(' or ');
  else if (c.field === 'label') value = names(opts.labels, v) || 'a label';
  else if (c.field === 'contact_group') value = names(opts.groups, v) || 'a group';
  else if (c.field === 'team') value = v ? names(opts.teams, v) || 'a team' : 'no team';
  else if (c.field === 'weekday') value = (v || []).map((d) => DAYS.find(([k]) => k === d)?.[1] || d).join(', ');
  else if (c.field === 'priority') value = (v || []).join(' or ');
  else if (c.field === 'business_hours') return v === 'inside' ? 'during business hours' : 'outside business hours';
  else if (['has_attachment', 'is_reply', 'assigned'].includes(c.field)) return `${FIELDS[c.field].toLowerCase()}: ${v ? 'yes' : 'no'}`;
  else value = String(v ?? '');
  return `${FIELDS[c.field] || c.field} ${OPS[c.op] || c.op} ${value}`;
}

// -- value editors ----------------------------------------------------------------------

function MultiPick({ items, value, onChange, placeholder, emptyText }) {
  const selected = items.filter((i) => (value || []).map(String).includes(String(i.id)));
  const open = (e) => pickFromList(e.currentTarget, {
    items: items.map((i) => ({ id: i.id, label: i.name || i.title || i.label, color: i.color, hint: i.hint })),
    selected: value || [],
    multi: true,
    onChange: (ids) => onChange(ids),
    emptyText: emptyText || 'Nothing to choose from',
  });
  return html`<button type="button" class="input rl-pick" onClick=${open}>
    ${selected.length
    ? selected.map((i) => html`<${Chip} key=${i.id} size="sm" color=${i.color}>${i.name || i.title || i.label}</${Chip}>`)
    : html`<span class="muted">${placeholder || 'Choose…'}</span>`}
    <${Icon} name="chevron-down" size=${13} class="rl-pick-caret" />
  </button>`;
}

function UserPick({ value, onChange, placeholder }) {
  const ids = value || [];
  return html`<button type="button" class="input rl-pick" onClick=${(e) => pickUsers(e.currentTarget, {
    selected: ids, multi: true, onChange,
  })}>
    ${ids.length ? ids.map((id) => html`<${Chip} key=${id} size="sm" color=${user(id).color}>${user(id).name}</${Chip}>`)
    : html`<span class="muted">${placeholder || 'Choose people…'}</span>`}
    <${Icon} name="chevron-down" size=${13} class="rl-pick-caret" />
  </button>`;
}

function YesNo({ value, onChange }) {
  return html`<${Segmented} size="sm" value=${value ? 'yes' : 'no'} onChange=${(v) => onChange(v === 'yes')}
    options=${[{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }]} />`;
}

function ConditionValue({ cond, set, opts }) {
  const f = cond.field;
  if (TEXT_FIELDS.includes(f)) {
    return html`<${Input} value=${Array.isArray(cond.value) ? cond.value.join(', ') : cond.value || ''}
      onValue=${(v) => set({ value: v })} placeholder=${cond.op === 'matches' ? 'Regular expression' : 'Words or phrases, separated by commas'} />`;
  }
  if (f === 'channel') return html`<${MultiPick} items=${opts.channels.map((c) => ({ ...c, hint: c.address }))} value=${cond.value} onChange=${(v) => set({ value: v })} placeholder="Choose channels…" />`;
  if (f === 'channel_type') return html`<${MultiPick} items=${CHANNEL_TYPES} value=${cond.value} onChange=${(v) => set({ value: v })} placeholder="Choose types…" />`;
  if (f === 'label') return html`<${MultiPick} items=${opts.labels} value=${cond.value} onChange=${(v) => set({ value: v })} placeholder="Choose labels…" />`;
  if (f === 'contact_group') return html`<${MultiPick} items=${opts.groups} value=${cond.value} onChange=${(v) => set({ value: v })}
    placeholder="Choose groups…" emptyText="No contact groups yet — create them under Contacts" />`;
  if (f === 'team') {
    return html`<${Select} value=${Array.isArray(cond.value) ? cond.value[0] ?? '' : cond.value ?? ''} onValue=${(v) => set({ value: v ? [Number(v)] : null })}
      placeholder="No team" options=${opts.teams.map((t) => ({ value: t.id, label: t.name }))} />`;
  }
  if (['has_attachment', 'is_reply', 'assigned'].includes(f)) return html`<${YesNo} value=${!!cond.value} onChange=${(v) => set({ value: v })} />`;
  if (f === 'business_hours') {
    return html`<${Segmented} size="sm" value=${cond.value || 'outside'} onChange=${(v) => set({ value: v })}
      options=${[{ value: 'inside', label: 'Inside' }, { value: 'outside', label: 'Outside' }]} />`;
  }
  if (f === 'weekday') {
    const days = cond.value || [];
    return html`<div class="rl-days">${DAYS.map(([k, label]) => html`<button type="button" key=${k}
      class=${cx('rl-day', days.includes(k) && 'is-active')} onClick=${() => set({ value: days.includes(k) ? days.filter((d) => d !== k) : [...days, k] })}>${label}</button>`)}</div>`;
  }
  if (f === 'priority') return html`<${MultiPick} items=${PRIORITIES.map((p) => ({ id: p, label: p[0].toUpperCase() + p.slice(1) }))} value=${cond.value} onChange=${(v) => set({ value: v })} />`;
  return null;
}

function defaultValue(field) {
  if (['has_attachment', 'is_reply'].includes(field)) return true;
  if (field === 'assigned') return false;
  if (field === 'business_hours') return 'outside';
  if (['channel', 'channel_type', 'label', 'contact_group', 'weekday', 'priority'].includes(field)) return [];
  if (field === 'team') return null;
  return '';
}

function ConditionRow({ cond, onChange, onRemove, opts }) {
  const fieldOps = opts.fields[cond.field] || ['is'];
  const set = (patch) => onChange({ ...cond, ...patch });
  return html`<div class="rl-row">
    <div class="rl-row-fields">
      <${Select} value=${cond.field} class="rl-field"
        onValue=${(f) => onChange({ field: f, op: (opts.fields[f] || ['is'])[0], value: defaultValue(f) })}
        options=${Object.keys(opts.fields).map((f) => ({ value: f, label: FIELDS[f] || f }))} />
      ${fieldOps.length > 1 && html`<${Select} value=${cond.op} class="rl-op" onValue=${(op) => set({ op })}
        options=${fieldOps.map((op) => ({ value: op, label: OPS[op] || op }))} />`}
      <div class="rl-value"><${ConditionValue} cond=${cond} set=${set} opts=${opts} /></div>
    </div>
    <${IconButton} icon="x" label="Remove condition" onClick=${onRemove} />
  </div>`;
}

function ActionParams({ action, set, opts }) {
  const t = action.type;
  if (t === 'assign') {
    const mode = action.mode || 'users';
    return html`<div class="rl-params">
      <${Select} value=${mode} onValue=${(v) => set({ mode: v })} options=${[
  { value: 'users', label: 'to specific people' }, { value: 'round_robin', label: 'taking turns (round robin)' },
  { value: 'load_balanced', label: 'to whoever is least busy' }, { value: 'on_shift', label: 'to whoever is on shift' },
]} />
      ${mode === 'users'
    ? html`<${UserPick} value=${action.user_ids} onChange=${(ids) => set({ user_ids: ids })} />`
    : html`<${Select} value=${action.team_id ?? ''} onValue=${(v) => set({ team_id: v ? Number(v) : null })}
          placeholder="in the conversation's team" options=${opts.teams.map((tm) => ({ value: tm.id, label: `in ${tm.name}` }))} />`}
    </div>`;
  }
  if (t === 'add_label' || t === 'remove_label') {
    return html`<${MultiPick} items=${opts.labels} value=${action.label_ids} onChange=${(v) => set({ label_ids: v })} placeholder="Choose labels…" />`;
  }
  if (t === 'move_team') {
    return html`<${Select} value=${action.team_id ?? ''} onValue=${(v) => set({ team_id: v ? Number(v) : null })}
      placeholder="No team" options=${opts.teams.map((tm) => ({ value: tm.id, label: tm.name }))} />`;
  }
  if (t === 'priority') {
    return html`<${Select} value=${action.value || 'high'} onValue=${(v) => set({ value: v })}
      options=${PRIORITIES.map((p) => ({ value: p, label: p[0].toUpperCase() + p.slice(1) }))} />`;
  }
  if (t === 'snooze') {
    const minutes = action.minutes || 60;
    const unit = minutes % 1440 === 0 ? 1440 : minutes % 60 === 0 ? 60 : 1;
    return html`<div class="rl-params rl-snooze">
      <${Input} type="number" min="1" value=${minutes / unit} onValue=${(v) => set({ minutes: Math.max(1, Math.round(Number(v) || 1)) * unit })} />
      <${Select} value=${String(unit)} onValue=${(u) => set({ minutes: Math.max(1, Math.round(minutes / unit)) * Number(u) })}
        options=${[{ value: '1', label: 'minutes' }, { value: '60', label: 'hours' }, { value: '1440', label: 'days' }]} />
    </div>`;
  }
  if (t === 'auto_reply') {
    const custom = !action.response_id && action.body_html !== undefined;
    return html`<div class="stack stack-sm">
      <${Segmented} size="sm" value=${custom ? 'custom' : 'response'}
        onChange=${(v) => set(v === 'custom' ? { response_id: null, body_html: action.body_html || '' } : { body_html: undefined, subject: undefined })}
        options=${[{ value: 'response', label: 'Canned response' }, { value: 'custom', label: 'Write it here' }]} />
      ${custom
    ? html`<${Input} value=${action.subject || ''} onValue=${(v) => set({ subject: v })} placeholder="Subject (optional, email only)" />
          <div class="rl-editor"><${RichEditor} value=${action.body_html || ''} onChange=${(v) => set({ body_html: v })} toolbar="mini"
            placeholder="Hi {{contact.first_name}}, thanks for writing…" minHeight=${70} /></div>`
    : html`<${Select} value=${action.response_id ?? ''} onValue=${(v) => set({ response_id: v ? Number(v) : null })}
          placeholder=${opts.responses.length ? 'Choose a canned response…' : 'No canned responses yet'}
          options=${opts.responses.map((r) => ({ value: r.id, label: r.title }))} />`}
      <span class="muted text-xs">Sent once per contact per day; never to automated mail.</span>
    </div>`;
  }
  if (t === 'add_comment') {
    return html`<div class="rl-editor"><${RichEditor} value=${action.body_html || ''} onChange=${(v) => set({ body_html: v })}
      toolbar=${false} mentions placeholder="Visible only to your team. Type @ to mention someone." minHeight=${50} /></div>`;
  }
  if (t === 'forward') return html`<${Input} type="email" value=${action.to || ''} onValue=${(v) => set({ to: v })} placeholder="bookkeeper@example.com" />`;
  if (t === 'notify') {
    return html`<div class="stack stack-sm">
      <${UserPick} value=${action.user_ids} onChange=${(ids) => set({ user_ids: ids })} placeholder="Who to notify…" />
      <${Input} value=${action.note || ''} onValue=${(v) => set({ note: v })} placeholder="Note (optional)" />
    </div>`;
  }
  if (t === 'webhook') {
    return html`<${Input} type="url" value=${action.url || ''} onValue=${(v) => set({ url: v })} placeholder="https://hooks.zapier.com/…" />`;
  }
  return null;
}

function ActionRow({ action, onChange, onRemove, onMove, index, count, opts }) {
  const set = (patch) => onChange({ ...action, ...patch });
  return html`<div class="rl-row">
    <div class="rl-row-fields rl-action-fields">
      <${Select} value=${action.type} class="rl-field" onValue=${(type) => onChange({ type })}
        options=${opts.actions.map((a) => ({ value: a, label: ACTIONS[a] || a }))} />
      <div class="rl-value"><${ActionParams} action=${action} set=${set} opts=${opts} /></div>
    </div>
    <div class="rl-row-tools">
      <${IconButton} icon="arrow-up" size="sm" label="Move up" disabled=${index === 0} onClick=${() => onMove(-1)} />
      <${IconButton} icon="arrow-down" size="sm" label="Move down" disabled=${index === count - 1} onClick=${() => onMove(1)} />
      <${IconButton} icon="x" size="sm" label="Remove action" onClick=${onRemove} />
    </div>
  </div>`;
}

// -- dry run ------------------------------------------------------------------------

function RuleTester({ rule, opts }) {
  const [q, setQ] = useState('');
  const debounced = useDebounced(q, 250);
  const [results, setResults] = useState(null);
  const [picked, setPicked] = useState(null);
  const [outcome, setOutcome] = useState(null);
  useEffect(() => {
    let alive = true;
    api.get('/conversations', { mailbox: 'all', q: debounced.trim() || undefined, limit: 6 })
      .then((res) => alive && setResults(res.items))
      .catch(() => alive && setResults([]));
    return () => { alive = false; };
  }, [debounced]);
  const run = async (conv) => {
    setPicked(conv);
    setOutcome(null);
    try {
      setOutcome(await api.post(`/rules/${rule.id}/test`, { conversation_id: conv.id }));
      setTimeout(() => document.querySelector('.rl-outcome')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 30);
    } catch (err) {
      toastError(err);
    }
  };
  return html`<div class="rl-tester">
    <${SearchInput} value=${q} onValue=${setQ} placeholder="Find a conversation to test against" />
    <div class="rl-tester-list">
      ${results === null && html`<${Loading} />`}
      ${results && !results.length && html`<div class="muted text-sm pad">No conversations match.</div>`}
      ${(results || []).map((c) => html`<button type="button" key=${c.id} class=${cx('rl-tester-item', picked?.id === c.id && 'is-active')} onClick=${() => run(c)}>
        <span class="truncate strong">${c.subject || c.contact?.display_name || 'Conversation'}</span>
        <span class="truncate muted text-sm">${c.contact?.display_name || ''} · ${c.preview || ''}</span>
      </button>`)}
    </div>
    ${outcome && html`<div class=${cx('rl-outcome', outcome.matched ? 'is-match' : 'is-miss')}>
      <div class="rl-outcome-head"><${Icon} name=${outcome.matched ? 'circle-check' : 'circle-x'} size=${16} />
        ${outcome.matched ? 'This rule would run' : "This rule wouldn't run"}</div>
      ${outcome.note && html`<div class="muted text-sm">${outcome.note}</div>`}
      ${outcome.conditions.length > 0 && html`<ul class="rl-outcome-list">
        ${outcome.conditions.map((c, i) => html`<li key=${i} class=${c.matched ? 'is-ok' : 'is-no'}>
          <${Icon} name=${c.matched ? 'check' : 'x'} size=${13} />${describeCondition(c, opts)}</li>`)}
      </ul>`}
      ${outcome.matched && html`<div class="text-sm"><b>Then:</b> ${outcome.actions.join(' · ')}</div>`}
    </div>`}
  </div>`;
}

// -- editor -------------------------------------------------------------------------

function RuleEditor({ initial, opts, close, onSaved }) {
  const [rule, setRule] = useState(() => ({
    name: '', trigger: 'incoming', match: 'all', conditions: [], actions: [{ type: 'add_label', label_ids: [] }],
    is_active: true, stop_processing: false, ...(initial || {}),
  }));
  const [saved, setSaved] = useState(initial?.id ? initial : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (patch) => setRule((r) => ({ ...r, ...patch }));
  const setCondition = (i, c) => set({ conditions: rule.conditions.map((x, j) => (j === i ? c : x)) });
  const setAction = (i, a) => set({ actions: rule.actions.map((x, j) => (j === i ? a : x)) });
  const moveAction = (i, delta) => {
    const next = [...rule.actions];
    const [item] = next.splice(i, 1);
    next.splice(i + delta, 0, item);
    set({ actions: next });
  };
  const addCondition = () => set({ conditions: [...rule.conditions, { field: 'subject', op: 'contains', value: '' }] });
  const save = async (e) => {
    e && e.preventDefault();
    setBusy(true);
    setError(null);
    const body = {
      name: rule.name, trigger: rule.trigger, match: rule.match, conditions: rule.conditions, actions: rule.actions,
      is_active: rule.is_active, stop_processing: rule.stop_processing,
    };
    try {
      const res = saved ? await api.patch(`/rules/${saved.id}`, body) : await api.post('/rules', body);
      setSaved(res.rule);
      onSaved();
      toast(saved ? 'Rule saved' : 'Rule created');
      close();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!(await confirmDialog({ title: `Delete “${saved.name}”?`, message: 'Conversations it already changed stay as they are.', confirmLabel: 'Delete rule', danger: true }))) return;
    try { await api.del(`/rules/${saved.id}`); onSaved(); close(); } catch (err) { toastError(err); }
  };
  return html`<${Modal} title=${saved ? 'Edit rule' : 'New rule'} icon="zap" size="lg" onClose=${close}
    footer=${html`
      ${saved && html`<${Button} variant="ghost" icon="trash" onClick=${remove}>Delete</${Button}>`}
      <span class="grow"></span>
      <${Button} onClick=${close}>Cancel</${Button}>
      <${Button} variant="primary" type="submit" form="rule-form" loading=${busy}>${saved ? 'Save rule' : 'Create rule'}</${Button}>
    `}>
    <form id="rule-form" class="stack rl-editor-form" onSubmit=${save}>
      ${error && html`<${Banner} tone="danger">${error}</${Banner}>`}
      <${Field} label="Name"><${Input} value=${rule.name} onValue=${(v) => set({ name: v })} placeholder="e.g. Label rush orders" required autoFocus=${!saved} /></${Field}>
      <div class="rl-block">
        <div class="rl-block-title"><span class="rl-step">When</span></div>
        <${Select} value=${rule.trigger} onValue=${(v) => set({ trigger: v })}
          options=${Object.entries(opts.triggers).map(([k, label]) => ({ value: k, label }))} />
      </div>
      <div class="rl-block">
        <div class="rl-block-title">
          <span class="rl-step">If</span>
          ${rule.conditions.length > 1 && html`<${Segmented} size="sm" value=${rule.match} onChange=${(v) => set({ match: v })}
            options=${[{ value: 'all', label: 'All of these' }, { value: 'any', label: 'Any of these' }]} />`}
        </div>
        ${!rule.conditions.length && html`<div class="muted text-sm rl-always">Always — every time it happens.</div>`}
        ${rule.conditions.map((c, i) => html`<${ConditionRow} key=${i} cond=${c} opts=${opts}
          onChange=${(next) => setCondition(i, next)} onRemove=${() => set({ conditions: rule.conditions.filter((_, j) => j !== i) })} />`)}
        <div><${Button} size="sm" variant="ghost" icon="plus" onClick=${addCondition}>Add condition</${Button}></div>
      </div>
      <div class="rl-block">
        <div class="rl-block-title"><span class="rl-step">Then</span></div>
        ${rule.actions.map((a, i) => html`<${ActionRow} key=${i} action=${a} index=${i} count=${rule.actions.length} opts=${opts}
          onChange=${(next) => setAction(i, next)} onMove=${(d) => moveAction(i, d)}
          onRemove=${() => set({ actions: rule.actions.filter((_, j) => j !== i) })} />`)}
        <div><${Button} size="sm" variant="ghost" icon="plus" onClick=${() => set({ actions: [...rule.actions, { type: 'add_label', label_ids: [] }] })}>Add action</${Button}></div>
      </div>
      <div class="stack stack-sm">
        <${Toggle} checked=${rule.is_active} onChange=${(v) => set({ is_active: v })} label="Active" />
        <${Toggle} checked=${rule.stop_processing} onChange=${(v) => set({ stop_processing: v })} label="Stop processing rules below this one when it runs" />
      </div>
      ${saved && html`<details class="rl-test-wrap">
        <summary><${Icon} name="circle-play" size=${14} /> Test against a conversation</summary>
        <p class="muted text-sm">Checks the saved version of this rule against a conversation's latest message. Nothing changes.</p>
        <${RuleTester} rule=${saved} opts=${opts} />
      </details>`}
    </form>
  </${Modal}>`;
}

// -- list ---------------------------------------------------------------------------

function RuleRow({ rule, index, count, opts, onEdit, onChanged, onMove }) {
  const toggle = async (v) => {
    try { await api.patch(`/rules/${rule.id}`, { is_active: v }); onChanged(); } catch (err) { toastError(err); }
  };
  const apply = async () => {
    if (!(await confirmDialog({ title: `Apply “${rule.name}” to open conversations?`, message: 'Labels, assignment, team, priority and status changes are applied to open conversations whose latest message matches. Replies, comments, forwards and webhooks are skipped.', confirmLabel: 'Apply' }))) return;
    try {
      const res = await api.post(`/rules/${rule.id}/apply`, {});
      toast(`Applied to ${res.applied} of ${res.checked} open conversations`);
      onChanged();
    } catch (err) { toastError(err); }
  };
  const duplicate = async () => {
    try {
      await api.post('/rules', { name: `${rule.name} (copy)`, trigger: rule.trigger, match: rule.match, conditions: rule.conditions,
        actions: rule.actions, is_active: false, stop_processing: rule.stop_processing });
      onChanged();
      toast('Duplicated (paused)');
    } catch (err) { toastError(err); }
  };
  const remove = async () => {
    if (!(await confirmDialog({ title: `Delete “${rule.name}”?`, confirmLabel: 'Delete rule', danger: true }))) return;
    try { await api.del(`/rules/${rule.id}`); onChanged(); } catch (err) { toastError(err); }
  };
  const menu = (e) => showMenu(e.currentTarget, [
    { label: 'Edit', icon: 'pencil', onSelect: onEdit },
    ['incoming', 'new_conversation'].includes(rule.trigger) && { label: 'Apply to open conversations', icon: 'wand-sparkles', onSelect: apply },
    { label: 'Duplicate', icon: 'copy', onSelect: duplicate },
    { divider: true },
    { label: 'Delete', icon: 'trash', danger: true, onSelect: remove },
  ].filter(Boolean));
  const conds = rule.conditions.map((c) => describeCondition(c, opts));
  return html`<div class=${cx('rl-list-row', !rule.is_active && 'is-paused')}>
    <div class="rl-order">
      <${IconButton} icon="chevron-up" size="sm" label="Move up" disabled=${index === 0} onClick=${() => onMove(-1)} />
      <${IconButton} icon="chevron-down" size="sm" label="Move down" disabled=${index === count - 1} onClick=${() => onMove(1)} />
    </div>
    <${Toggle} checked=${rule.is_active} onChange=${toggle} />
    <button type="button" class="rl-list-main" onClick=${onEdit}>
      <span class="rl-list-name">${rule.name}${rule.stop_processing && html`<${Chip} size="sm" tone="muted">stops</${Chip}>`}</span>
      <span class="rl-list-summary">
        <span class="rl-when"><${Icon} name=${TRIGGER_ICONS[rule.trigger] || 'zap'} size=${13} />${opts.triggers[rule.trigger]}</span>
        ${conds.length > 0 && html`<span>if ${conds.join(rule.match === 'any' ? ' or ' : ' and ')}</span>`}
        <span class="rl-then">→ ${(rule.summary || []).join(' · ')}</span>
      </span>
      <span class="rl-list-stats">${rule.run_count ? html`Ran ${rule.run_count} time${rule.run_count === 1 ? '' : 's'}${rule.last_run_at && html`, last <${RelTime} value=${rule.last_run_at} mode="ago" />`}` : 'Hasn’t run yet'}</span>
    </button>
    <${IconButton} icon="ellipsis" label="Rule actions" onClick=${menu} />
  </div>`;
}

export default function RulesSettings() {
  const { data, loading, error, reload } = useFetch('/rules', { refetchOn: ['rules.changed'] });
  const optsReq = useFetch('/rules/options', { refetchOn: ['settings.changed'] });
  const opts = optsReq.data;
  const rules = data?.items || [];
  const open = (rule) => openModal((close) => html`<${RuleEditor} initial=${rule} opts=${opts} close=${close} onSaved=${reload} />`, { size: 'lg' });
  const fromTemplate = (tpl) => open(JSON.parse(JSON.stringify(tpl.rule)));
  const templatesMenu = (e) => showMenu(e.currentTarget, TEMPLATES.map((t) => ({ label: t.title, hint: t.text, icon: t.icon, onSelect: () => fromTemplate(t) })),
    { width: 320, placement: 'bottom-end' });
  const move = async (index, delta) => {
    const ids = rules.map((r) => r.id);
    const [id] = ids.splice(index, 1);
    ids.splice(index + delta, 0, id);
    try { await api.post('/rules/reorder', { ids }); reload(); } catch (err) { toastError(err); }
  };
  if (!opts) return html`${optsReq.error ? html`<${ErrorBox} error=${optsReq.error} retry=${optsReq.reload} />` : html`<${Loading} />`}`;
  return html`<div class="rl-settings">
    <${Section} title="Rules" description="Automate the busywork: label, route, assign and auto-reply as messages arrive. Rules run from top to bottom on every new message (or send, or comment)."
      actions=${html`<${Button} icon="layout-grid" onClick=${templatesMenu}>Templates</${Button}><${Button} variant="primary" icon="plus" onClick=${() => open(null)}>New rule</${Button}>`}>
      ${loading && !data && html`<${Loading} />`}
      <${ErrorBox} error=${error} retry=${reload} />
      ${data && !rules.length && html`<div class="stack">
        <${Empty} icon="zap" title="No rules yet" compact>Start from a template or build your own.</${Empty}>
        <div class="rl-templates">${TEMPLATES.map((t) => html`<button type="button" key=${t.id} class="rl-template" onClick=${() => fromTemplate(t)}>
          <span class="rl-template-icon"><${Icon} name=${t.icon} size=${18} /></span>
          <span class="strong">${t.title}</span><span class="muted text-sm">${t.text}</span>
        </button>`)}</div>
      </div>`}
      ${rules.length > 0 && html`<div class="rl-list">${rules.map((r, i) => html`<${RuleRow} key=${r.id} rule=${r} index=${i} count=${rules.length}
        opts=${opts} onEdit=${() => open(r)} onChanged=${reload} onMove=${(d) => move(i, d)} />`)}</div>`}
    </${Section}>
  </div>`;
}
