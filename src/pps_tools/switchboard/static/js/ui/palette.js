// Command palette (⌘K / Ctrl+K): jump anywhere, run actions, search everything.
//
// Modules add commands with registerCommands((query) => [{ id, label, icon, hint, group, run }]).
// Search results come from GET /api/search?q= (each server module contributes).

import { html, useEffect, useMemo, useRef, useState } from '../lib/preact.js';
import { api } from '../lib/api.js';
import { navigate } from '../lib/router.js';
import { useDebounced } from '../lib/hooks.js';
import { Icon } from './icons.js';
import { cx, Spinner } from './components.js';
import { openModal } from './overlay.js';

const providers = new Set();

export function registerCommands(provider) {
  providers.add(provider);
  return () => providers.delete(provider);
}

function score(label, q) {
  const l = label.toLowerCase();
  if (!q) return 1;
  if (l.startsWith(q)) return 3;
  if (l.split(/\s+/).some((w) => w.startsWith(q))) return 2;
  return l.includes(q) ? 1 : 0;
}

function Palette({ close }) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const debounced = useDebounced(query, 180);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  useEffect(() => { inputRef.current && inputRef.current.focus(); }, []);

  useEffect(() => {
    const q = debounced.trim();
    if (q.length < 2) { setResults([]); return undefined; }
    const ctrl = new AbortController();
    setSearching(true);
    api.get('/search', { q, limit: 12 }, { signal: ctrl.signal })
      .then((res) => setResults(res.items || []))
      .catch(() => {})
      .finally(() => setSearching(false));
    return () => ctrl.abort();
  }, [debounced]);

  const commands = useMemo(() => {
    const q = query.trim().toLowerCase();
    const all = [];
    providers.forEach((p) => { try { all.push(...(p(q) || [])); } catch (err) { console.error(err); } });
    return all
      .map((c) => ({ ...c, _s: score(c.label + ' ' + (c.keywords || ''), q) }))
      .filter((c) => c._s > 0)
      .sort((a, b) => b._s - a._s)
      .slice(0, q ? 8 : 12);
  }, [query]);

  const items = [
    ...commands.map((c) => ({ ...c, group: c.group || 'Commands' })),
    ...results.map((r) => ({
      id: `${r.type}:${r.id}`,
      label: r.title,
      hint: r.subtitle,
      icon: r.icon || 'search',
      group: r.group || 'Results',
      run: () => navigate(r.url),
    })),
  ];

  useEffect(() => setActive(0), [query, results.length]);
  useEffect(() => {
    const el = listRef.current && listRef.current.querySelector('.is-active');
    if (el) el.scrollIntoView({ block: 'nearest' });
  }, [active]);

  const run = (item) => {
    if (!item) return;
    close();
    item.run();
  };
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(items.length - 1, a + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); run(items[active]); }
  };

  let lastGroup = null;
  return html`<div class="modal-backdrop palette-backdrop" onMouseDown=${(e) => e.target === e.currentTarget && close()}>
    <div class="palette" role="dialog" aria-label="Command palette" onKeyDown=${onKey}>
      <div class="palette-input-row">
        <${Icon} name="search" size=${18} />
        <input ref=${inputRef} class="palette-input" placeholder="Search conversations, jobs, people… or type a command"
          value=${query} onInput=${(e) => setQuery(e.currentTarget.value)} />
        ${searching && html`<${Spinner} size=${16} />`}
      </div>
      <div class="palette-list" ref=${listRef}>
        ${items.map((item, i) => {
    const header = item.group !== lastGroup ? html`<div class="palette-group">${item.group}</div>` : null;
    lastGroup = item.group;
    return html`${header}<button type="button" key=${item.id} class=${cx('palette-item', i === active && 'is-active')}
            onMouseEnter=${() => setActive(i)} onClick=${() => run(item)}>
            <${Icon} name=${item.icon || 'chevron-right'} size=${16} class="palette-icon" />
            <span class="palette-label">${item.label}</span>
            ${item.hint && html`<span class="palette-hint">${item.hint}</span>`}
            ${item.shortcut && html`<span class="palette-shortcut">${item.shortcut}</span>`}
          </button>`;
  })}
        ${!items.length && html`<div class="palette-empty">${query.trim().length >= 2 && !searching ? 'No matches' : 'Type to search'}</div>`}
      </div>
      <div class="palette-footer"><span><kbd class="kbd">↑</kbd><kbd class="kbd">↓</kbd> move</span><span><kbd class="kbd">↵</kbd> open</span><span><kbd class="kbd">Esc</kbd> close</span></div>
    </div>
  </div>`;
}

let open = false;
export function openPalette() {
  if (open) return;
  open = true;
  openModal((close) => html`<${Palette} close=${close} />`, { onClose: () => { open = false; } });
}
