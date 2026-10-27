// Keyboard shortcuts.
//
//   useHotkeys({ j: next, k: prev, 'mod+k': openPalette, 'g i': goInbox, escape: close })
//
// Combos: 'mod' is ⌘ on Mac and Ctrl elsewhere; letters take 'shift+'; symbols are
// matched as typed ('?', '#'); two-key sequences are written 'g i'. Bindings
// registered later win. Plain keys are ignored while typing in a field; combos with
// mod (and Escape) still fire.

import { useEffect, useRef } from './preact.js';

export const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

const scopes = [];
let pending = null; // first key of a sequence
let pendingTimer = null;
let enabled = true;

export function setShortcutsEnabled(value) {
  enabled = value;
}

function comboOf(e) {
  const key = e.key;
  if (!key) return '';
  const parts = [];
  if (isMac ? e.metaKey : e.ctrlKey) parts.push('mod');
  if (e.altKey) parts.push('alt');
  let k = key.length === 1 ? key : key.toLowerCase();
  if (k === ' ') k = 'space';
  if (k.length === 1 && /[a-zA-Z]/.test(k)) {
    if (e.shiftKey) parts.push('shift');
    k = k.toLowerCase();
  } else if (k.length > 1 && e.shiftKey) {
    parts.push('shift');
  }
  parts.push(k);
  return parts.join('+');
}

function isTyping(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

function onKeyDown(e) {
  if (!enabled || e.isComposing) return;
  const combo = comboOf(e);
  if (!combo || ['shift', 'control', 'alt', 'meta'].includes(combo)) return;
  const typing = isTyping(e.target);
  const candidates = pending ? [`${pending} ${combo}`] : [combo];
  for (let i = scopes.length - 1; i >= 0; i--) {
    const scope = scopes[i];
    if (!scope.active()) continue;
    for (const c of candidates) {
      const fn = scope.map[c];
      if (!fn) continue;
      const needsMod = c.includes('mod+') || c === 'escape';
      if (typing && !needsMod && !scope.allowInInputs) continue;
      e.preventDefault();
      clearPending();
      fn(e);
      return;
    }
  }
  if (!typing && !pending && !combo.includes('+')) {
    const starts = scopes.some((s) => s.active() && Object.keys(s.map).some((k) => k.startsWith(combo + ' ')));
    if (starts) {
      pending = combo;
      clearTimeout(pendingTimer);
      pendingTimer = setTimeout(clearPending, 1200);
      return;
    }
  }
  clearPending();
}

function clearPending() {
  pending = null;
  clearTimeout(pendingTimer);
}

window.addEventListener('keydown', onKeyDown);

export function useHotkeys(map, { enabled: on = true, allowInInputs = false } = {}) {
  const ref = useRef(map);
  ref.current = map;
  const enabledRef = useRef(on);
  enabledRef.current = on;
  useEffect(() => {
    const scope = {
      get map() { return ref.current; },
      active: () => enabledRef.current,
      allowInInputs,
    };
    scopes.push(scope);
    return () => {
      const i = scopes.indexOf(scope);
      if (i >= 0) scopes.splice(i, 1);
    };
  }, []);
}

// Label for help text: 'mod+k' -> '⌘K' / 'Ctrl+K'.
export function keyLabel(combo) {
  return combo.split(' ').map((part) => part.split('+').map((k) => {
    if (k === 'mod') return isMac ? '⌘' : 'Ctrl';
    if (k === 'shift') return isMac ? '⇧' : 'Shift';
    if (k === 'alt') return isMac ? '⌥' : 'Alt';
    if (k === 'enter') return '↵';
    if (k === 'escape') return 'Esc';
    if (k === 'arrowup') return '↑';
    if (k === 'arrowdown') return '↓';
    return k.length === 1 ? k.toUpperCase() : k[0].toUpperCase() + k.slice(1);
  }).join(isMac ? '' : '+')).join(' then ');
}
