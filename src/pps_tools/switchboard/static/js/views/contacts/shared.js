// Small pieces shared by the contacts pages and the inbox sidebar panel.

import { html, useEffect, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { Icon, cx } from '../../ui/components.js';
import { pickFromList } from '../../ui/pickers.js';
import { toastError } from '../../ui/overlay.js';

// Click-to-edit text. onSave(value) may return a promise; Enter saves (Shift+Enter is a
// newline when multiline), Escape cancels.
export function InlineText({ value, onSave, placeholder = 'Add…', multiline = false, class: cls, inputClass, label }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || '');
  const ref = useRef(null);
  useEffect(() => { if (!editing) setDraft(value || ''); }, [value, editing]);
  useEffect(() => {
    if (editing && ref.current) {
      ref.current.focus();
      if (ref.current.select && !multiline) ref.current.select();
    }
  }, [editing]);
  const commit = async () => {
    setEditing(false);
    const next = draft.trim();
    if (next === (value || '').trim()) return;
    try { await onSave(next); } catch (err) { toastError(err); setDraft(value || ''); }
  };
  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); setDraft(value || ''); setEditing(false); }
    if (e.key === 'Enter' && (!multiline || e.metaKey || e.ctrlKey)) { e.preventDefault(); commit(); }
  };
  if (editing) {
    return multiline
      ? html`<textarea ref=${ref} class=${cx('input textarea inline-edit-input', inputClass)} rows="3" value=${draft}
          aria-label=${label || placeholder} onInput=${(e) => setDraft(e.currentTarget.value)} onBlur=${commit} onKeyDown=${onKey}></textarea>`
      : html`<input ref=${ref} class=${cx('input input-sm inline-edit-input', inputClass)} value=${draft}
          aria-label=${label || placeholder} onInput=${(e) => setDraft(e.currentTarget.value)} onBlur=${commit} onKeyDown=${onKey} />`;
  }
  return html`<button type="button" class=${cx('inline-edit', !value && 'is-empty', multiline && 'is-multiline', cls)}
    onClick=${() => setEditing(true)} title="Click to edit" aria-label=${label ? `Edit ${label}` : undefined}>
    ${value || placeholder}<${Icon} name="pencil" size=${12} class="inline-edit-icon" />
  </button>`;
}

// Organization picker with "create" — resolves via onChange(org) (or null to clear).
export async function pickOrganization(anchor, { selected, onChange, allowClear = true }) {
  let items = [];
  try { items = (await api.get('/organizations')).items; } catch (err) { toastError(err); return; }
  const list = items.map((o) => ({ id: o.id, label: o.name, hint: o.domain, color: o.color }));
  if (allowClear && selected) list.unshift({ id: 0, label: 'No organization', icon: 'x' });
  pickFromList(anchor, {
    items: list,
    selected,
    placeholder: 'Find or add an organization…',
    createLabel: 'Add organization',
    allowCreate: async (name) => {
      try {
        const res = await api.post('/organizations', { name });
        return { id: res.organization.id, label: res.organization.name, org: res.organization };
      } catch (err) { toastError(err); return null; }
    },
    onChange: (id, item) => onChange(id ? (item.org || items.find((o) => o.id === id) || { id, name: item.label }) : null),
  });
}

export function handleIcon(kind) {
  return kind === 'email' ? 'mail' : kind === 'phone' ? 'phone' : 'message-circle';
}

export function formatPhone(value) {
  const m = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(value || '');
  return m ? `(${m[1]}) ${m[2]}-${m[3]}` : value;
}

export function composeLink(handle, channelType) {
  const q = new URLSearchParams({ to: handle });
  if (channelType) q.set('type', channelType);
  return `/inbox/compose?${q.toString()}`;
}
