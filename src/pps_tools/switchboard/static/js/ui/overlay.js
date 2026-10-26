// Modals, popovers, menus, toasts and dialogs, opened imperatively from anywhere:
//
//   showMenu(e.currentTarget, [{ label: 'Rename', icon: 'pencil', onSelect: rename }, { divider: true }, ...]);
//   const close = showPopover(anchorEl, (close) => html`<${Picker} onDone=${close} />`);
//   openModal((close) => html`<${Modal} title="New job" onClose=${close}>...</${Modal}>`);
//   toast('Saved'); toast('Failed', { tone: 'danger' });
//   if (await confirmDialog({ title: 'Delete?', danger: true })) ...
//   const name = await promptDialog({ title: 'Rename', value: old });
//
// <OverlayHost/> is mounted once by the app shell.

import { html, useEffect, useLayoutEffect, useReducer, useRef, useState } from '../lib/preact.js';
import { Icon } from './icons.js';
import { Button, cx } from './components.js';

let stack = [];
let seq = 1;
const subs = new Set();
const notify = () => subs.forEach((fn) => fn());

let lastClosedAnchor = null;
let lastClosedAt = 0;

function push(entry) {
  const id = seq++;
  stack = [...stack, { id, ...entry }];
  notify();
  return id;
}

function remove(id) {
  const entry = stack.find((o) => o.id === id);
  if (!entry) return;
  stack = stack.filter((o) => o.id !== id);
  notify();
  if (entry.onClose) entry.onClose();
  if (entry.restoreFocus && document.contains(entry.restoreFocus)) {
    try { entry.restoreFocus.focus({ preventScroll: true }); } catch { /* ignore */ }
  }
}

export function closeAllPopovers() {
  stack.filter((o) => o.kind === 'popover').forEach((o) => remove(o.id));
}

export function openModal(render, { size = 'md', dismissable = true, onClose } = {}) {
  let id = null;
  const close = () => id && remove(id);
  id = push({ kind: 'modal', render, size, dismissable, onClose, restoreFocus: document.activeElement });
  return close;
}

export function showPopover(anchor, render, { placement = 'bottom-start', width, class: cls, onClose, offset = 6 } = {}) {
  // Clicking the anchor of a popover that just closed (on mousedown) acts as a toggle.
  if (anchor && anchor === lastClosedAnchor && Date.now() - lastClosedAt < 400) {
    lastClosedAnchor = null;
    return () => {};
  }
  let id = null;
  const close = () => id && remove(id);
  id = push({ kind: 'popover', anchor, render, placement, width, cls, onClose, offset, restoreFocus: document.activeElement });
  return close;
}

export function showMenu(anchor, items, opts = {}) {
  return showPopover(anchor, (close) => html`<${Menu} items=${items} close=${close} />`, { width: opts.width || 220, ...opts });
}

// -- toasts -------------------------------------------------------------------------

let toasts = [];
let toastSeq = 1;
const toastSubs = new Set();

export function toast(message, { tone = 'default', action, duration = 4200, icon } = {}) {
  const id = toastSeq++;
  toasts = [...toasts, { id, message, tone, action, icon }];
  toastSubs.forEach((fn) => fn());
  if (duration) setTimeout(() => dismissToast(id), duration);
  return () => dismissToast(id);
}

export function dismissToast(id) {
  toasts = toasts.filter((t) => t.id !== id);
  toastSubs.forEach((fn) => fn());
}

// Shorthand for API errors in handlers: catch(toastError)
export function toastError(err) {
  if (err && err.name === 'AbortError') return;
  toast(err?.message || 'Something went wrong', { tone: 'danger' });
}

// -- dialogs ------------------------------------------------------------------------

export function confirmDialog({ title = 'Are you sure?', message, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger = false } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    const close = openModal((closeFn) => html`<${Modal}
      title=${title}
      size="sm"
      onClose=${() => { finish(false); closeFn(); }}
      footer=${html`
        <${Button} onClick=${() => { finish(false); closeFn(); }}>${cancelLabel}</${Button}>
        <${Button} variant=${danger ? 'danger' : 'primary'} autoFocus onClick=${() => { finish(true); closeFn(); }}>${confirmLabel}</${Button}>
      `}
    >${message && html`<p class="dialog-message">${message}</p>`}</${Modal}>`, { size: 'sm', onClose: () => finish(false) });
    void close;
  });
}

function PromptBody({ label, value, placeholder, multiline, onSubmit, inputType = 'text' }) {
  const [v, setV] = useState(value || '');
  const ref = useRef(null);
  useEffect(() => { ref.current && ref.current.focus(); ref.current && ref.current.select && ref.current.select(); }, []);
  const submit = (e) => { e.preventDefault(); onSubmit(v); };
  return html`<form id="prompt-form" onSubmit=${submit} class="stack">
    ${label && html`<label class="field-label">${label}</label>`}
    ${multiline
    ? html`<textarea ref=${ref} class="input textarea" rows="4" value=${v} placeholder=${placeholder} onInput=${(e) => setV(e.currentTarget.value)}
          onKeyDown=${(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(e); }}></textarea>`
    : html`<input ref=${ref} type=${inputType} class="input" value=${v} placeholder=${placeholder} onInput=${(e) => setV(e.currentTarget.value)} />`}
  </form>`;
}

export function promptDialog({ title, label, value = '', placeholder, confirmLabel = 'Save', multiline = false, inputType } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    openModal((close) => html`<${Modal}
      title=${title}
      size="sm"
      onClose=${() => { finish(null); close(); }}
      footer=${html`
        <${Button} onClick=${() => { finish(null); close(); }}>Cancel</${Button}>
        <${Button} variant="primary" type="submit" form="prompt-form">${confirmLabel}</${Button}>
      `}
    ><${PromptBody} label=${label} value=${value} placeholder=${placeholder} multiline=${multiline} inputType=${inputType}
        onSubmit=${(v) => { finish(v); close(); }} /></${Modal}>`, { size: 'sm', onClose: () => finish(null) });
  });
}

// -- components ---------------------------------------------------------------------

export function Modal({ title, icon, children, footer, onClose, size = 'md', class: cls, headerExtra, bodyClass }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const target = el.querySelector('[autofocus], input:not([type=hidden]), textarea, select, [contenteditable=true]');
    (target || el).focus({ preventScroll: true });
  }, []);
  return html`<div class="modal-backdrop" onMouseDown=${(e) => { if (e.target === e.currentTarget && onClose) onClose(); }}>
    <div ref=${ref} class=${cx('modal', `modal-${size}`, cls)} role="dialog" aria-modal="true" aria-label=${typeof title === 'string' ? title : undefined} tabIndex="-1">
      ${title !== undefined && html`<header class="modal-header">
        ${icon && html`<span class="modal-icon"><${Icon} name=${icon} size=${18} /></span>`}
        <h2 class="modal-title">${title}</h2>
        ${headerExtra}
        ${onClose && html`<button type="button" class="icon-btn icon-btn-md icon-btn-ghost" aria-label="Close" onClick=${onClose}><${Icon} name="x" size=${18} /></button>`}
      </header>`}
      <div class=${cx('modal-body', bodyClass)}>${children}</div>
      ${footer && html`<footer class="modal-footer">${footer}</footer>`}
    </div>
  </div>`;
}

function anchorRect(anchor) {
  if (!anchor) return { left: window.innerWidth / 2, top: window.innerHeight / 3, right: window.innerWidth / 2, bottom: window.innerHeight / 3, width: 0, height: 0 };
  if (typeof anchor.getBoundingClientRect === 'function') return anchor.getBoundingClientRect();
  if ('x' in anchor && 'y' in anchor && !('left' in anchor)) return { left: anchor.x, right: anchor.x, top: anchor.y, bottom: anchor.y, width: 0, height: 0 };
  return anchor;
}

function Popover({ entry, close }) {
  const ref = useRef(null);
  const [pos, setPos] = useState({ left: -9999, top: -9999, visibility: 'hidden' });
  const place = () => {
    const el = ref.current;
    if (!el) return;
    const r = anchorRect(entry.anchor);
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const gap = entry.offset;
    const [side, align] = entry.placement.split('-');
    let left;
    let top;
    if (side === 'right' || side === 'left') {
      left = side === 'right' ? r.right + gap : r.left - w - gap;
      if (left + w > vw - 8) left = r.left - w - gap;
      if (left < 8) left = Math.min(vw - w - 8, r.right + gap);
      top = align === 'end' ? r.bottom - h : r.top;
    } else {
      top = side === 'top' ? r.top - h - gap : r.bottom + gap;
      if (side !== 'top' && top + h > vh - 8 && r.top - h - gap > 8) top = r.top - h - gap;
      if (side === 'top' && top < 8) top = r.bottom + gap;
      left = align === 'end' ? r.right - w : align === 'center' ? r.left + r.width / 2 - w / 2 : r.left;
    }
    left = Math.max(8, Math.min(left, vw - w - 8));
    top = Math.max(8, Math.min(top, vh - h - 8));
    setPos({ left, top, visibility: 'visible' });
  };
  useLayoutEffect(place, []);
  useEffect(() => {
    const ro = new ResizeObserver(place);
    if (ref.current) ro.observe(ref.current);
    window.addEventListener('resize', place);
    return () => { ro.disconnect(); window.removeEventListener('resize', place); };
  }, []);
  const style = { ...pos, width: entry.width ? entry.width + 'px' : undefined };
  return html`<div ref=${ref} class=${cx('popover', entry.cls)} style=${style} data-overlay-id=${entry.id}>${entry.render(close)}</div>`;
}

function OverlayItem({ entry }) {
  const close = () => remove(entry.id);
  if (entry.kind === 'modal') {
    return html`<div class="overlay-layer" data-overlay-id=${entry.id}>${entry.render(close)}</div>`;
  }
  return html`<${Popover} entry=${entry} close=${close} />`;
}

function ToastStack() {
  const [, force] = useReducer((x) => x + 1, 0);
  useEffect(() => { toastSubs.add(force); return () => toastSubs.delete(force); }, []);
  return html`<div class="toast-stack" role="status" aria-live="polite">
    ${toasts.map((t) => html`<div key=${t.id} class=${cx('toast', `toast-${t.tone}`)}>
      ${t.icon && html`<${Icon} name=${t.icon} size=${16} />`}
      <span class="toast-message">${t.message}</span>
      ${t.action && html`<button type="button" class="toast-action" onClick=${() => { t.action.onClick(); dismissToast(t.id); }}>${t.action.label}</button>`}
      <button type="button" class="toast-close" aria-label="Dismiss" onClick=${() => dismissToast(t.id)}><${Icon} name="x" size=${14} /></button>
    </div>`)}
  </div>`;
}

export function OverlayHost() {
  const [, force] = useReducer((x) => x + 1, 0);
  useEffect(() => {
    subs.add(force);
    const onDown = (e) => {
      if (!stack.length) return;
      const hit = e.target.closest && e.target.closest('[data-overlay-id]');
      const hitId = hit ? Number(hit.dataset.overlayId) : null;
      for (const o of [...stack].reverse()) {
        if (hitId !== null && o.id <= hitId) break;
        if (o.kind !== 'popover') break;
        const anchorEl = o.anchor && o.anchor.contains ? o.anchor : null;
        if (anchorEl && anchorEl.contains(e.target)) {
          lastClosedAnchor = anchorEl;
          lastClosedAt = Date.now();
        }
        remove(o.id);
      }
    };
    const onKey = (e) => {
      if (e.key !== 'Escape' || !stack.length) return;
      const top = stack[stack.length - 1];
      if (top.kind === 'modal' && !top.dismissable) return;
      e.stopPropagation();
      e.preventDefault();
      remove(top.id);
    };
    document.addEventListener('mousedown', onDown, true);
    window.addEventListener('keydown', onKey, true);
    return () => {
      subs.delete(force);
      document.removeEventListener('mousedown', onDown, true);
      window.removeEventListener('keydown', onKey, true);
    };
  }, []);
  return html`<div class="overlay-host">
    ${stack.map((o) => html`<${OverlayItem} key=${o.id} entry=${o} />`)}
    <${ToastStack} />
  </div>`;
}

export function hasOpenOverlay() {
  return stack.length > 0;
}

// items: { label, icon, onSelect, hint, shortcut, danger, checked, disabled, divider, header, color, avatar }
export function Menu({ items, close }) {
  const ref = useRef(null);
  const actionable = items.filter((i) => !i.divider && !i.header && !i.disabled);
  const [active, setActive] = useState(-1);
  useEffect(() => { ref.current && ref.current.focus({ preventScroll: true }); }, []);
  const choose = (item) => {
    if (!item || item.disabled) return;
    if (!item.keepOpen) close();
    item.onSelect && item.onSelect();
  };
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => (a + 1) % actionable.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => (a <= 0 ? actionable.length - 1 : a - 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); choose(actionable[active]); }
  };
  return html`<div class="menu" role="menu" tabIndex="-1" ref=${ref} onKeyDown=${onKey}>
    ${items.map((item, idx) => {
    if (item.divider) return html`<div key=${'d' + idx} class="menu-divider" role="separator"></div>`;
    if (item.header) return html`<div key=${'h' + idx} class="menu-header">${item.header}</div>`;
    const isActive = actionable[active] === item;
    return html`<button
        key=${item.id || item.label}
        type="button"
        role="menuitem"
        class=${cx('menu-item', item.danger && 'is-danger', isActive && 'is-active', item.disabled && 'is-disabled')}
        disabled=${item.disabled}
        onMouseEnter=${() => setActive(actionable.indexOf(item))}
        onClick=${() => choose(item)}
      >
        ${item.checked !== undefined && html`<span class="menu-check">${item.checked && html`<${Icon} name="check" size=${14} />`}</span>`}
        ${item.color && html`<span class="color-dot" style=${{ background: item.color }}></span>`}
        ${item.icon && html`<${Icon} name=${item.icon} size=${15} class="menu-icon" />`}
        <span class="menu-label">${item.label}${item.hint && html`<span class="menu-hint">${item.hint}</span>`}</span>
        ${item.shortcut && html`<span class="menu-shortcut">${item.shortcut}</span>`}
      </button>`;
  })}
  </div>`;
}
