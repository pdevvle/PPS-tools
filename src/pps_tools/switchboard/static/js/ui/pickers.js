// Searchable pickers that open in a popover next to their trigger.
//
//   pickUsers(e.currentTarget, { selected: [3], multi: true, onChange: (ids) => ... });
//   pickFromList(el, { items: [{ id, label, color }], selected, onChange, allowCreate });
//   pickDateTime(el, { value: iso, onChange: (iso) => ..., title: 'Snooze until' });
//   pickEmoji(el, { onPick: (emoji) => ... });

import { html, useEffect, useMemo, useRef, useState } from '../lib/preact.js';
import { Icon } from './icons.js';
import { Avatar, Button, ColorChoices, cx } from './components.js';
import { showPopover } from './overlay.js';
import { getState } from '../lib/store.js';
import { presets, toLocalInput, fromLocalInput, dateKey, fromDateKey } from '../lib/dates.js';
import { fmtDateTime, fmtDate } from '../lib/format.js';

function normalize(s) {
  return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
}

export function ListPicker({
  items, selected, multi = false, onChange, close, placeholder = 'Search…', allowCreate, createLabel = 'Create',
  emptyText = 'Nothing found', title, footer, search = true,
}) {
  const [query, setQuery] = useState('');
  const [sel, setSel] = useState(() => new Set(Array.isArray(selected) ? selected : selected != null ? [selected] : []));
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  useEffect(() => { inputRef.current && inputRef.current.focus(); }, []);

  const filtered = useMemo(() => {
    const q = normalize(query.trim());
    if (!q) return items;
    return items.filter((i) => normalize(i.label).includes(q) || normalize(i.hint).includes(q) || normalize(i.keywords).includes(q));
  }, [items, query]);
  const canCreate = allowCreate && query.trim() && !items.some((i) => normalize(i.label) === normalize(query.trim()));
  const total = filtered.length + (canCreate ? 1 : 0);

  useEffect(() => { setActive(0); }, [query]);
  useEffect(() => {
    const el = listRef.current && listRef.current.querySelector('.is-active');
    if (el) el.scrollIntoView({ block: 'nearest' });
  }, [active]);

  const toggle = (item) => {
    if (item.disabled) return;
    if (!multi) {
      close();
      onChange(item.id, item);
      return;
    }
    const next = new Set(sel);
    next.has(item.id) ? next.delete(item.id) : next.add(item.id);
    setSel(next);
    onChange([...next], item);
  };
  const create = async () => {
    const item = await allowCreate(query.trim());
    if (!item) return;
    setQuery('');
    if (multi) {
      const next = new Set(sel);
      next.add(item.id);
      setSel(next);
      onChange([...next], item);
    } else {
      close();
      onChange(item.id, item);
    }
  };
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(total - 1, a + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      if (active < filtered.length) toggle(filtered[active]);
      else if (canCreate) create();
    }
  };

  return html`<div class="list-picker" onKeyDown=${onKey}>
    ${title && html`<div class="list-picker-title">${title}</div>`}
    ${search && html`<div class="list-picker-search">
      <${Icon} name="search" size=${14} />
      <input ref=${inputRef} class="list-picker-input" value=${query} placeholder=${placeholder}
        onInput=${(e) => setQuery(e.currentTarget.value)} />
    </div>`}
    <div class="list-picker-items" ref=${listRef} role="listbox" aria-multiselectable=${multi}>
      ${filtered.map((item, idx) => html`<button
        type="button"
        key=${item.id}
        role="option"
        aria-selected=${sel.has(item.id)}
        class=${cx('list-picker-item', idx === active && 'is-active', sel.has(item.id) && 'is-selected', item.disabled && 'is-disabled')}
        onMouseEnter=${() => setActive(idx)}
        onClick=${() => toggle(item)}
      >
        ${multi && html`<span class="list-picker-check">${sel.has(item.id) && html`<${Icon} name="check" size=${13} strokeWidth=${3} />`}</span>`}
        ${item.user ? html`<${Avatar} user=${item.user} size=${20} online="auto" />` : null}
        ${item.color && !item.user ? html`<span class="color-dot" style=${{ background: item.color }}></span>` : null}
        ${item.icon && html`<${Icon} name=${item.icon} size=${15} class="list-picker-icon" />`}
        <span class="list-picker-label">${item.label}${item.hint && html`<span class="list-picker-hint">${item.hint}</span>`}</span>
        ${!multi && sel.has(item.id) && html`<${Icon} name="check" size=${14} class="list-picker-tick" />`}
      </button>`)}
      ${canCreate && html`<button type="button" class=${cx('list-picker-item', 'list-picker-create', active === filtered.length && 'is-active')}
        onMouseEnter=${() => setActive(filtered.length)} onClick=${create}>
        <${Icon} name="plus" size=${14} /><span>${createLabel} “${query.trim()}”</span>
      </button>`}
      ${!filtered.length && !canCreate && html`<div class="list-picker-empty">${emptyText}</div>`}
    </div>
    ${footer && html`<div class="list-picker-footer">${footer(close)}</div>`}
  </div>`;
}

export function pickFromList(anchor, opts) {
  return showPopover(anchor, (close) => html`<${ListPicker} ...${opts} close=${close} />`, { width: opts.width || 260, placement: opts.placement || 'bottom-start' });
}

// Teammates. filter(user) narrows the list (e.g. only inbox users).
export function pickUsers(anchor, { selected = [], multi = true, onChange, title, filter, placeholder = 'Search people…', extra = [] } = {}) {
  const { users } = getState();
  const items = [
    ...extra,
    ...users
      .filter((u) => u.is_active && (!filter || filter(u)))
      .map((u) => ({ id: u.id, label: u.name, hint: u.title || u.email, user: u, keywords: u.email })),
  ];
  return pickFromList(anchor, { items, selected, multi, onChange, title, placeholder, emptyText: 'No one matches' });
}

function DateTimePicker({ value, onChange, close, title, showPresets = true, dateOnly = false, allowClear = true, presetsList }) {
  const initial = value ? new Date(value) : null;
  const [day, setDay] = useState(initial ? dateKey(initial) : dateKey(new Date()));
  const [time, setTime] = useState(initial ? toLocalInput(initial).slice(11) : '09:00');
  const choices = presetsList || presets();
  const apply = (d) => {
    close();
    onChange(d ? d.toISOString() : null);
  };
  const applyCustom = (e) => {
    e && e.preventDefault();
    if (dateOnly) {
      onChange(day ? dateKey(fromDateKey(day)) : null);
      close();
      return;
    }
    const iso = fromLocalInput(`${day}T${time || '09:00'}`);
    if (iso) apply(new Date(iso));
  };
  return html`<div class="dt-picker">
    ${title && html`<div class="list-picker-title">${title}</div>`}
    ${showPresets && !dateOnly && html`<div class="dt-presets">
      ${choices.map((p) => html`<button type="button" key=${p.id} class="dt-preset" onClick=${() => apply(p.date)}>
        <span>${p.label}</span><span class="dt-preset-when">${fmtDateTime(p.date)}</span>
      </button>`)}
    </div>`}
    <form class="dt-custom" onSubmit=${applyCustom}>
      <div class="dt-custom-row">
        <input type="date" class="input input-sm" value=${day} onInput=${(e) => setDay(e.currentTarget.value)} required />
        ${!dateOnly && html`<input type="time" class="input input-sm" value=${time} step="300" onInput=${(e) => setTime(e.currentTarget.value)} />`}
      </div>
      <div class="dt-custom-actions">
        ${allowClear && value && html`<${Button} size="sm" variant="ghost" onClick=${() => { close(); onChange(null); }}>Clear</${Button}>`}
        <span class="grow"></span>
        <${Button} size="sm" variant="primary" type="submit">Set</${Button}>
      </div>
    </form>
  </div>`;
}

// onChange receives an ISO instant (or 'YYYY-MM-DD' with dateOnly), or null when cleared.
export function pickDateTime(anchor, opts) {
  return showPopover(anchor, (close) => html`<${DateTimePicker} ...${opts} close=${close} />`, { width: 290, placement: opts.placement || 'bottom-start' });
}

export function DateTimeButton({ value, onChange, placeholder = 'Set date', dateOnly = false, icon = 'calendar', title, class: cls, size = 'sm', allowClear = true, showPresets }) {
  const label = value ? (dateOnly ? fmtDate(fromDateKey(value), { weekday: true }) : fmtDateTime(value)) : placeholder;
  return html`<${Button}
    size=${size}
    icon=${icon}
    class=${cx('dt-button', !value && 'is-empty', cls)}
    onClick=${(e) => pickDateTime(e.currentTarget, { value: dateOnly && value ? fromDateKey(value).toISOString() : value, onChange, dateOnly, title, allowClear, showPresets })}
  >${label}</${Button}>`;
}

export function pickColor(anchor, { value, onChange }) {
  return showPopover(anchor, (close) => html`<div class="color-picker"><${ColorChoices} value=${value} onChange=${(c) => { close(); onChange(c); }} /></div>`, { width: 196 });
}

export const QUICK_EMOJI = ['👍', '❤️', '😂', '🎉', '😮', '🙏', '👀', '✅', '🔥', '💯', '😕', '👎', '🚀', '⏰', '📦', '🖨️'];

export function pickEmoji(anchor, { onPick }) {
  return showPopover(anchor, (close) => html`<div class="emoji-picker">
    ${QUICK_EMOJI.map((e) => html`<button type="button" key=${e} class="emoji-choice" onClick=${() => { close(); onPick(e); }}>${e}</button>`)}
  </div>`, { width: 232, placement: 'top-start' });
}
