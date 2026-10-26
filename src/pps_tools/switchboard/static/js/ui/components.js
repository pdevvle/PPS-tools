// Shared UI building blocks. Styles live in css/base.css.

import { html, useEffect, useRef, useState } from '../lib/preact.js';
import { Icon } from './icons.js';
import { initials, fmtAgo, fmtFull, fmtRelative } from '../lib/format.js';
import { user as lookupUser, useStore } from '../lib/store.js';

export { Icon };

const cx = (...parts) => parts.filter(Boolean).join(' ');
export { cx };

export function Button({ variant = 'secondary', size, icon, iconRight, loading, children, class: cls, type = 'button', ...rest }) {
  return html`<button
    type=${type}
    class=${cx('btn', `btn-${variant}`, size && `btn-${size}`, !children && 'btn-icon-only', loading && 'is-loading', cls)}
    disabled=${rest.disabled || loading}
    ...${rest}
  >
    ${loading ? html`<${Spinner} size=${14} />` : icon && html`<${Icon} name=${icon} size=${size === 'sm' ? 14 : 16} />`}
    ${children && html`<span class="btn-label">${children}</span>`}
    ${iconRight && html`<${Icon} name=${iconRight} size=${14} class="btn-icon-right" />`}
  </button>`;
}

export function IconButton({ icon, label, size = 'md', variant = 'ghost', active, badge, tipPos, class: cls, iconSize, ...rest }) {
  return html`<button
    type="button"
    class=${cx('icon-btn', `icon-btn-${size}`, `icon-btn-${variant}`, active && 'is-active', cls)}
    aria-label=${label}
    data-tip=${label}
    data-tip-pos=${tipPos}
    ...${rest}
  >
    <${Icon} name=${icon} size=${iconSize || (size === 'sm' ? 14 : size === 'lg' ? 20 : 16)} />
    ${badge ? html`<span class="icon-btn-badge">${badge > 99 ? '99+' : badge}</span>` : null}
  </button>`;
}

export function Spinner({ size = 16, class: cls }) {
  return html`<span class=${cx('spinner', cls)} style=${{ width: size + 'px', height: size + 'px' }} role="status" aria-label="Loading"></span>`;
}

export function Loading({ label, class: cls }) {
  return html`<div class=${cx('loading', cls)}><${Spinner} size=${20} />${label && html`<span>${label}</span>`}</div>`;
}

export function ErrorBox({ error, retry, class: cls }) {
  if (!error) return null;
  return html`<div class=${cx('error-box', cls)}>
    <${Icon} name="circle-alert" size=${16} />
    <span>${error.message || String(error)}</span>
    ${retry && html`<${Button} size="sm" onClick=${retry}>Try again</${Button}>`}
  </div>`;
}

export function Empty({ icon = 'inbox', title, children, action, compact, class: cls }) {
  return html`<div class=${cx('empty', compact && 'empty-compact', cls)}>
    ${icon && html`<div class="empty-icon"><${Icon} name=${icon} size=${compact ? 20 : 28} strokeWidth=${1.6} /></div>`}
    ${title && html`<div class="empty-title">${title}</div>`}
    ${children && html`<div class="empty-text">${children}</div>`}
    ${action && html`<div class="empty-action">${action}</div>`}
  </div>`;
}

// <Avatar user=${12} /> or user=${obj} or name/color for contacts.
export function Avatar({ user, name, color, size = 24, online, title, class: cls, square }) {
  const onlineSet = useStore((s) => s.online);
  const u = typeof user === 'number' ? lookupUser(user) : user;
  const label = name || u?.name || u?.email || '?';
  const bg = color || u?.color || '#868e96';
  const showOnline = online === 'auto' ? (u?.id && onlineSet.has(u.id)) : online;
  return html`<span
    class=${cx('avatar', square && 'avatar-square', cls)}
    style=${{ width: size + 'px', height: size + 'px', fontSize: Math.max(9, Math.round(size * 0.42)) + 'px', background: bg }}
    title=${title === false ? undefined : (title || label)}
  >${initials(label)}${online !== undefined && online !== false ? html`<span class=${cx('avatar-presence', showOnline && 'is-online')}></span>` : null}</span>`;
}

export function AvatarStack({ users = [], max = 3, size = 22, class: cls }) {
  const list = users.slice(0, max);
  const extra = users.length - list.length;
  return html`<span class=${cx('avatar-stack', cls)}>
    ${list.map((u) => html`<${Avatar} key=${typeof u === 'number' ? u : u.id} user=${u} size=${size} />`)}
    ${extra > 0 && html`<span class="avatar avatar-more" style=${{ width: size + 'px', height: size + 'px', fontSize: Math.round(size * 0.4) + 'px' }}>+${extra}</span>`}
  </span>`;
}

export function UserName({ id, fallback = 'Unknown' }) {
  useStore((s) => s.usersById[id]);
  const u = lookupUser(id);
  return html`<span class="user-name">${u.id ? u.name : fallback}</span>`;
}

export function Badge({ count, tone = 'accent', dot, class: cls, children }) {
  if (dot) return html`<span class=${cx('badge-dot', `tone-${tone}`, cls)}></span>`;
  const value = children ?? count;
  if (value === undefined || value === null || value === 0 || value === '') return null;
  return html`<span class=${cx('badge', `tone-${tone}`, cls)}>${typeof value === 'number' && value > 999 ? '999+' : value}</span>`;
}

// Colored chip, e.g. labels: <Chip color="#e8590c">Rush</Chip>
export function Chip({ color, children, icon, onRemove, onClick, tone, size, title, class: cls }) {
  const style = color ? { '--chip': color } : undefined;
  return html`<span
    class=${cx('chip', color && 'chip-colored', tone && `tone-${tone}`, size && `chip-${size}`, onClick && 'is-clickable', cls)}
    style=${style}
    onClick=${onClick}
    title=${title}
  >
    ${color && html`<span class="chip-dot"></span>`}
    ${icon && html`<${Icon} name=${icon} size=${12} />`}
    <span class="chip-label">${children}</span>
    ${onRemove && html`<button type="button" class="chip-remove" aria-label="Remove" onClick=${(e) => { e.stopPropagation(); onRemove(); }}><${Icon} name="x" size=${11} /></button>`}
  </span>`;
}

export function Dot({ color, size = 8, class: cls }) {
  return html`<span class=${cx('dot', cls)} style=${{ background: color, width: size + 'px', height: size + 'px' }}></span>`;
}

export function Kbd({ children }) {
  return html`<kbd class="kbd">${children}</kbd>`;
}

export function Toggle({ checked, onChange, label, disabled, hint, class: cls }) {
  return html`<label class=${cx('toggle', disabled && 'is-disabled', cls)}>
    <input type="checkbox" checked=${!!checked} disabled=${disabled} onChange=${(e) => onChange && onChange(e.currentTarget.checked)} />
    <span class="toggle-track"><span class="toggle-thumb"></span></span>
    ${(label || hint) && html`<span class="toggle-text">${label}${hint && html`<span class="toggle-hint">${hint}</span>`}</span>`}
  </label>`;
}

export function Checkbox({ checked, indeterminate, onChange, label, disabled, class: cls, onClick }) {
  const ref = useRef(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = !!indeterminate; }, [indeterminate]);
  return html`<label class=${cx('checkbox', disabled && 'is-disabled', cls)} onClick=${onClick}>
    <input ref=${ref} type="checkbox" checked=${!!checked} disabled=${disabled} onChange=${(e) => onChange && onChange(e.currentTarget.checked)} />
    <span class="checkbox-box"><${Icon} name=${indeterminate ? 'minus' : 'check'} size=${12} strokeWidth=${3} /></span>
    ${label && html`<span class="checkbox-label">${label}</span>`}
  </label>`;
}

export function Field({ label, hint, error, children, required, class: cls, inline, htmlFor }) {
  return html`<div class=${cx('field', inline && 'field-inline', error && 'has-error', cls)}>
    ${label && html`<label class="field-label" for=${htmlFor}>${label}${required && html`<span class="field-required">*</span>`}</label>`}
    <div class="field-control">${children}</div>
    ${error ? html`<div class="field-error">${error}</div>` : hint && html`<div class="field-hint">${hint}</div>`}
  </div>`;
}

export function Input({ class: cls, onValue, onInput, ...rest }) {
  return html`<input class=${cx('input', cls)} onInput=${(e) => { onInput && onInput(e); onValue && onValue(e.currentTarget.value); }} ...${rest} />`;
}

export function TextArea({ class: cls, autoSize, onValue, onInput, rows = 3, ...rest }) {
  const ref = useRef(null);
  const resize = () => {
    if (!autoSize || !ref.current) return;
    ref.current.style.height = 'auto';
    ref.current.style.height = ref.current.scrollHeight + 2 + 'px';
  };
  useEffect(resize, [rest.value]);
  return html`<textarea ref=${ref} rows=${rows} class=${cx('input', 'textarea', cls)}
    onInput=${(e) => { resize(); onInput && onInput(e); onValue && onValue(e.currentTarget.value); }} ...${rest}></textarea>`;
}

// options: [{value, label}] or ['a', 'b']
export function Select({ options = [], value, onChange, onValue, class: cls, placeholder, children, ...rest }) {
  return html`<select
    class=${cx('input', 'select', cls)}
    value=${value ?? ''}
    onChange=${(e) => { onChange && onChange(e); onValue && onValue(e.currentTarget.value); }}
    ...${rest}
  >
    ${placeholder !== undefined && html`<option value="">${placeholder}</option>`}
    ${options.map((o) => (typeof o === 'object'
    ? html`<option value=${o.value} disabled=${o.disabled}>${o.label}</option>`
    : html`<option value=${o}>${o}</option>`))}
    ${children}
  </select>`;
}

export function Tabs({ tabs, value, onChange, class: cls, size }) {
  return html`<div class=${cx('tabs', size && `tabs-${size}`, cls)} role="tablist">
    ${tabs.map((t) => html`<button
      type="button"
      role="tab"
      key=${t.id}
      class=${cx('tab', value === t.id && 'is-active')}
      aria-selected=${value === t.id}
      onClick=${() => onChange(t.id)}
    >
      ${t.icon && html`<${Icon} name=${t.icon} size=${15} />`}
      <span>${t.label}</span>
      ${t.count ? html`<span class="tab-count">${t.count}</span>` : null}
    </button>`)}
  </div>`;
}

export function Segmented({ options, value, onChange, size = 'md', class: cls }) {
  return html`<div class=${cx('segmented', `segmented-${size}`, cls)} role="radiogroup">
    ${options.map((o) => {
    const opt = typeof o === 'object' ? o : { value: o, label: o };
    return html`<button
        type="button"
        key=${opt.value}
        role="radio"
        aria-checked=${value === opt.value}
        class=${cx('segmented-item', value === opt.value && 'is-active')}
        onClick=${() => onChange(opt.value)}
        data-tip=${opt.tip}
      >${opt.icon && html`<${Icon} name=${opt.icon} size=${14} />`}${opt.label && html`<span>${opt.label}</span>`}</button>`;
  })}
  </div>`;
}

export function Card({ title, actions, children, class: cls, pad = true, icon, subtitle }) {
  return html`<section class=${cx('card', cls)}>
    ${(title || actions) && html`<header class="card-header">
      <div class="card-title-wrap">
        ${icon && html`<${Icon} name=${icon} size=${16} class="card-icon" />`}
        <div>
          ${title && html`<h3 class="card-title">${title}</h3>`}
          ${subtitle && html`<div class="card-subtitle">${subtitle}</div>`}
        </div>
      </div>
      ${actions && html`<div class="card-actions">${actions}</div>`}
    </header>`}
    <div class=${cx('card-body', !pad && 'card-body-flush')}>${children}</div>
  </section>`;
}

// Settings-page section: title + description on the left, controls on the right.
export function Section({ title, description, children, actions, class: cls }) {
  return html`<section class=${cx('section', cls)}>
    <header class="section-header">
      <div>
        <h2 class="section-title">${title}</h2>
        ${description && html`<p class="section-desc">${description}</p>`}
      </div>
      ${actions && html`<div class="section-actions">${actions}</div>`}
    </header>
    <div class="section-body">${children}</div>
  </section>`;
}

export function PageHeader({ title, subtitle, actions, icon, children, class: cls, leading }) {
  return html`<header class=${cx('page-header', cls)}>
    ${leading}
    ${icon && html`<span class="page-header-icon"><${Icon} name=${icon} size=${18} /></span>`}
    <div class="page-header-text">
      <h1 class="page-title">${title}</h1>
      ${subtitle && html`<div class="page-subtitle">${subtitle}</div>`}
    </div>
    ${children}
    ${actions && html`<div class="page-header-actions">${actions}</div>`}
  </header>`;
}

export function Stat({ label, value, hint, tone, icon, class: cls }) {
  return html`<div class=${cx('stat', tone && `tone-${tone}`, cls)}>
    <div class="stat-label">${icon && html`<${Icon} name=${icon} size=${14} />`}${label}</div>
    <div class="stat-value">${value}</div>
    ${hint && html`<div class="stat-hint">${hint}</div>`}
  </div>`;
}

export function ProgressBar({ value = 0, max = 100, tone = 'accent', class: cls, label }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return html`<div class=${cx('progress', `tone-${tone}`, cls)} role="progressbar" aria-valuenow=${value} aria-valuemax=${max} aria-label=${label}>
    <div class="progress-fill" style=${{ width: pct + '%' }}></div>
  </div>`;
}

export function Collapsible({ title, defaultOpen = true, children, count, actions, class: cls }) {
  const [open, setOpen] = useState(defaultOpen);
  return html`<div class=${cx('collapsible', open && 'is-open', cls)}>
    <div class="collapsible-header">
      <button type="button" class="collapsible-toggle" onClick=${() => setOpen(!open)} aria-expanded=${open}>
        <${Icon} name="chevron-right" size=${12} class="collapsible-chevron" />
        <span>${title}</span>
        ${count ? html`<span class="collapsible-count">${count}</span>` : null}
      </button>
      ${actions && html`<div class="collapsible-actions">${actions}</div>`}
    </div>
    ${open && html`<div class="collapsible-body">${children}</div>`}
  </div>`;
}

// One shared ticker so "5m ago" labels refresh without a timer per label.
let tick = 0;
const tickers = new Set();
setInterval(() => { tick++; tickers.forEach((fn) => fn(tick)); }, 30000);
function useTick() {
  const [, set] = useState(0);
  useEffect(() => { tickers.add(set); return () => tickers.delete(set); }, []);
}

export function RelTime({ value, mode = 'relative', class: cls }) {
  useTick();
  if (!value) return null;
  const text = mode === 'ago' ? fmtAgo(value) : fmtRelative(value);
  return html`<time class=${cx('reltime', cls)} datetime=${value} title=${fmtFull(value)}>${text}</time>`;
}

export function ColorDot({ color, size = 10 }) {
  return html`<span class="color-dot" style=${{ background: color || 'var(--text-3)', width: size + 'px', height: size + 'px' }}></span>`;
}

export const COLORS = ['#3b5bdb', '#1971c2', '#0c8599', '#2f9e44', '#5c940d', '#f08c00', '#e8590c', '#e03131', '#c2255c', '#ae3ec9', '#7048e8', '#868e96'];

export function ColorChoices({ value, onChange }) {
  return html`<div class="color-choices">
    ${COLORS.map((c) => html`<button type="button" key=${c} class=${cx('color-choice', value === c && 'is-active')}
      style=${{ background: c }} aria-label=${c} onClick=${() => onChange(c)}></button>`)}
  </div>`;
}

export function KeyValue({ items, class: cls }) {
  return html`<dl class=${cx('kv', cls)}>
    ${items.filter(Boolean).map(([k, v]) => html`<div class="kv-row"><dt>${k}</dt><dd>${v}</dd></div>`)}
  </dl>`;
}

export function Banner({ tone = 'info', icon, children, action, onClose, class: cls }) {
  return html`<div class=${cx('banner', `tone-${tone}`, cls)}>
    ${icon !== false && html`<${Icon} name=${icon || (tone === 'danger' ? 'circle-alert' : tone === 'warn' ? 'triangle-alert' : 'info')} size=${16} />`}
    <div class="banner-text">${children}</div>
    ${action}
    ${onClose && html`<${IconButton} icon="x" label="Dismiss" size="sm" onClick=${onClose} />`}
  </div>`;
}

export function SearchInput({ value, onValue, placeholder = 'Search', autoFocus, onKeyDown, class: cls, inputRef }) {
  return html`<div class=${cx('search-input', cls)}>
    <${Icon} name="search" size=${15} />
    <input ref=${inputRef} type="search" class="search-input-field" value=${value} placeholder=${placeholder}
      autoFocus=${autoFocus} onInput=${(e) => onValue(e.currentTarget.value)} onKeyDown=${onKeyDown} />
    ${value && html`<button type="button" class="search-input-clear" aria-label="Clear search" onClick=${() => onValue('')}><${Icon} name="x" size=${13} /></button>`}
  </div>`;
}

// A titled block in a right-hand sidebar (conversation details, job details...).
export function SidePanel({ title, icon, actions, children, count, collapsible = true, defaultOpen = true, class: cls }) {
  const key = typeof title === 'string' ? 'sb.panel.' + title : null;
  const [open, setOpen] = useState(() => {
    if (!key) return defaultOpen;
    try { const v = localStorage.getItem(key); return v === null ? defaultOpen : v === '1'; } catch { return defaultOpen; }
  });
  const toggle = () => {
    setOpen(!open);
    try { if (key) localStorage.setItem(key, open ? '0' : '1'); } catch { /* ignore */ }
  };
  return html`<section class=${cx('side-panel', open && 'is-open', cls)}>
    <header class="side-panel-header">
      ${collapsible
    ? html`<button type="button" class="side-panel-toggle" onClick=${toggle} aria-expanded=${open}>
          <${Icon} name="chevron-right" size=${12} class="side-panel-chevron" />
          ${icon && html`<${Icon} name=${icon} size=${14} />`}
          <span>${title}</span>${count ? html`<span class="side-panel-count">${count}</span>` : null}
        </button>`
    : html`<div class="side-panel-toggle">${icon && html`<${Icon} name=${icon} size=${14} />`}<span>${title}</span></div>`}
      ${actions && html`<div class="side-panel-actions">${actions}</div>`}
    </header>
    ${(open || !collapsible) && html`<div class="side-panel-body">${children}</div>`}
  </section>`;
}
