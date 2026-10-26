// Chart kit for Reports: line, grouped columns, horizontal bars, heatmap, KPI tiles,
// legends, a sortable table and the card that switches a chart to its table view.
//
// Rules (from the data-viz method): color is identity only (series slots 1-3 in a fixed
// order, never by rank); thin marks (2px lines, <=24px bars, 4px rounded data end);
// hairline grid; text never wears a series color; a legend for 2+ series plus sparing
// direct labels; every chart has a hover/focus readout and a table view.

import { html, useEffect, useLayoutEffect, useMemo, useRef, useState } from '../../lib/preact.js';
import { Icon, cx } from '../../ui/components.js';

// -- sizing & scales ------------------------------------------------------------------

export function useWidth(ref) {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver((entries) => setWidth(Math.floor(entries[0].contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return width;
}

function niceStep(max, count) {
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const nice = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
  return nice * mag;
}

export function niceTicks(max, count = 4) {
  if (!max || max <= 0) return [0, 1];
  const step = niceStep(max, count);
  const ticks = [];
  for (let v = 0; v <= max + step * 0.0001; v += step) ticks.push(Number(v.toFixed(10)));
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

const compactFmt = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 });
export const compact = (v) => (Math.abs(v) < 1000 ? String(Math.round(v * 10) / 10) : compactFmt.format(v));

const SERIES = ['var(--viz-1)', 'var(--viz-2)', 'var(--viz-3)'];
export const seriesColor = (i) => SERIES[i] || 'var(--viz-other)';

// -- tooltip --------------------------------------------------------------------------

function Tooltip({ tip, width }) {
  if (!tip) return null;
  const left = Math.max(4, Math.min(tip.x + 14, width - 190));
  return html`<div class="viz-tooltip" style=${{ left: left + 'px', top: Math.max(0, tip.y - 10) + 'px' }} role="status">
    ${tip.title && html`<div class="viz-tooltip-title">${tip.title}</div>`}
    ${tip.rows.map((r) => html`<div class="viz-tooltip-row" key=${r.label}>
      ${r.color && html`<span class=${cx('viz-key', r.shape === 'rect' ? 'viz-key-rect' : 'viz-key-line')} style=${{ background: r.color }}></span>`}
      <span class="viz-tooltip-value">${r.value}</span>
      <span class="viz-tooltip-label">${r.label}</span>
    </div>`)}
  </div>`;
}

// -- legend ---------------------------------------------------------------------------

export function Legend({ series, shape = 'line' }) {
  if (!series || series.length < 2) return null;
  return html`<ul class="viz-legend" aria-label="Legend">
    ${series.map((s, i) => html`<li key=${s.key}>
      <span class=${cx('viz-key', shape === 'rect' ? 'viz-key-rect' : 'viz-key-line')} style=${{ background: seriesColor(i) }}></span>
      ${s.label}
    </li>`)}
  </ul>`;
}

// -- line chart -----------------------------------------------------------------------

export function LineChart({ labels, series, format = compact, xFormat = (l) => l, height = 220, ariaLabel }) {
  const wrap = useRef(null);
  const width = useWidth(wrap);
  const [active, setActive] = useState(null);
  const [tip, setTip] = useState(null);
  const n = labels.length;
  const max = Math.max(0, ...series.flatMap((s) => s.values.map((v) => v || 0)));
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const narrow = width < 460;
  const labelChars = Math.max(...series.map((s) => s.label.length), 0);
  const mt = 10;
  const mb = 26;
  const ph = height - mt - mb;
  const y = (v) => mt + ph - ((v || 0) / top) * ph;

  // End labels only when they fit and don't collide; otherwise the legend carries identity.
  let ends = !narrow && series.length <= 4 && n > 0
    ? series.map((s, i) => ({ i, y: y(s.values[n - 1]), label: s.label, value: format(s.values[n - 1] || 0) })) : [];
  const sorted = [...ends].sort((a, b) => a.y - b.y);
  if (sorted.some((e, k) => k && e.y - sorted[k - 1].y < 14)) ends = [];

  const m = { l: 40, r: ends.length ? Math.min(130, labelChars * 6.6 + 22) : 12, t: mt, b: mb };
  const pw = Math.max(10, width - m.l - m.r);
  const x = (i) => m.l + (n <= 1 ? pw / 2 : (i * pw) / (n - 1));

  const paths = series.map((s) => s.values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(''));
  const area = series.length === 1 && n > 1
    ? `${paths[0]}L${x(n - 1).toFixed(1)},${y(0)}L${x(0).toFixed(1)},${y(0)}Z` : null;

  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(pw / 70))));
  const show = (idx) => {
    if (idx === null || idx < 0 || idx >= n) { setActive(null); setTip(null); return; }
    setActive(idx);
    setTip({
      x: x(idx), y: m.t,
      title: xFormat(labels[idx], true),
      rows: series.map((s, i) => ({ label: s.label, value: format(s.values[idx] || 0), color: seriesColor(i) })),
    });
  };
  const onMove = (e) => {
    const rect = wrap.current.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const idx = n <= 1 ? 0 : Math.round(((px - m.l) / pw) * (n - 1));
    show(Math.max(0, Math.min(n - 1, idx)));
  };
  const onKey = (e) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      const cur = active === null ? n - 1 : active + (e.key === 'ArrowRight' ? 1 : -1);
      show(Math.max(0, Math.min(n - 1, cur)));
    } else if (e.key === 'Escape') show(null);
  };

  return html`<div class="viz-chart" ref=${wrap} style=${{ height: height + 'px' }} tabIndex="0" role="figure"
      aria-label=${ariaLabel} onKeyDown=${onKey} onFocus=${() => active === null && show(n - 1)} onBlur=${() => show(null)}
      onPointerMove=${onMove} onPointerLeave=${() => show(null)}>
    ${width > 0 && html`<svg width=${width} height=${height} aria-hidden="true">
      ${ticks.map((t) => html`<g key=${t}>
        <line x1=${m.l} x2=${m.l + pw} y1=${y(t)} y2=${y(t)} class=${t === 0 ? 'viz-baseline' : 'viz-gridline'} />
        <text x=${m.l - 8} y=${y(t) + 4} class="viz-tick" text-anchor="end">${format(t)}</text>
      </g>`)}
      ${labels.map((l, i) => (i % every === 0 || i === n - 1) && (i === n - 1 || x(n - 1) - x(i) >= 64) && html`<text key=${l}
        x=${x(i)} y=${height - 6} class="viz-tick" text-anchor=${i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}>${xFormat(l)}</text>`)}
      ${area && html`<path d=${area} class="viz-area" style=${{ fill: seriesColor(0) }} />`}
      ${series.map((s, i) => html`<path key=${s.key} d=${paths[i]} class="viz-line" style=${{ stroke: seriesColor(i) }} />`)}
      ${active !== null && html`<line x1=${x(active)} x2=${x(active)} y1=${m.t} y2=${m.t + ph} class="viz-crosshair" />`}
      ${series.map((s, i) => html`<circle key=${'d' + s.key} cx=${x(active ?? n - 1)} cy=${y(s.values[active ?? n - 1])} r="4"
        class="viz-dot" style=${{ fill: seriesColor(i) }} />`)}
      ${ends.map((e) => html`<text key=${'l' + e.i} x=${m.l + pw + 10} y=${e.y + 4} class="viz-end-label">
        <tspan class="viz-end-value">${e.value}</tspan> ${e.label}</text>`)}
    </svg>`}
    <${Tooltip} tip=${tip} width=${width} />
  </div>`;
}

// -- grouped columns -------------------------------------------------------------------

function columnPath(x, yTop, w, yBase) {
  const h = yBase - yTop;
  if (h <= 0) return '';
  const r = Math.min(4, h, w / 2);
  return `M${x},${yBase}V${yTop + r}Q${x},${yTop} ${x + r},${yTop}H${x + w - r}Q${x + w},${yTop} ${x + w},${yTop + r}V${yBase}Z`;
}

export function ColumnChart({ labels, series, format = compact, xFormat = (l) => l, height = 220, ariaLabel }) {
  const wrap = useRef(null);
  const width = useWidth(wrap);
  const [active, setActive] = useState(null);
  const n = labels.length;
  const k = series.length;
  const max = Math.max(0, ...series.flatMap((s) => s.values.map((v) => v || 0)));
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const m = { l: 40, r: 12, t: 18, b: 26 };
  const pw = Math.max(10, width - m.l - m.r);
  const ph = height - m.t - m.b;
  const band = pw / Math.max(1, n);
  const barW = Math.max(3, Math.min(24, (band * 0.72 - 2 * (k - 1)) / k));
  const groupW = barW * k + 2 * (k - 1);
  const y = (v) => m.t + ph - ((v || 0) / top) * ph;
  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(pw / 64))));
  const tip = active === null ? null : {
    x: m.l + band * active + band / 2, y: m.t,
    title: xFormat(labels[active], true),
    rows: series.map((s, i) => ({ label: s.label, value: format(s.values[active] || 0), color: seriesColor(i), shape: 'rect' })),
  };
  const onKey = (e) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      const cur = active === null ? n - 1 : active + (e.key === 'ArrowRight' ? 1 : -1);
      setActive(Math.max(0, Math.min(n - 1, cur)));
    } else if (e.key === 'Escape') setActive(null);
  };
  return html`<div class="viz-chart" ref=${wrap} style=${{ height: height + 'px' }} tabIndex="0" role="figure"
      aria-label=${ariaLabel} onKeyDown=${onKey} onFocus=${() => active === null && setActive(n - 1)}
      onBlur=${() => setActive(null)} onPointerLeave=${() => setActive(null)}>
    ${width > 0 && html`<svg width=${width} height=${height} aria-hidden="true">
      ${ticks.map((t) => html`<g key=${t}>
        <line x1=${m.l} x2=${m.l + pw} y1=${y(t)} y2=${y(t)} class=${t === 0 ? 'viz-baseline' : 'viz-gridline'} />
        <text x=${m.l - 8} y=${y(t) + 4} class="viz-tick" text-anchor="end">${format(t)}</text>
      </g>`)}
      ${labels.map((l, gi) => {
    const gx = m.l + band * gi + (band - groupW) / 2;
    return html`<g key=${l} class=${cx('viz-group', active === gi && 'is-active')}>
          <rect x=${m.l + band * gi} y=${m.t} width=${band} height=${ph} class="viz-hit" onPointerEnter=${() => setActive(gi)} />
          ${series.map((s, si) => html`<path key=${s.key} d=${columnPath(gx + si * (barW + 2), y(s.values[gi]), barW, y(0))}
            class="viz-bar" style=${{ fill: seriesColor(si) }} />`)}
          ${gi === n - 1 && series.map((s, si) => (s.values[gi] ? html`<text key=${'v' + s.key}
            x=${gx + si * (barW + 2) + barW / 2} y=${y(s.values[gi]) - 5} class="viz-cap" text-anchor="middle">${format(s.values[gi])}</text>` : null))}
          ${(gi === n - 1 || (gi % every === 0 && (n - 1 - gi) * band >= 64)) && html`<text x=${m.l + band * gi + band / 2} y=${height - 6} class="viz-tick" text-anchor="middle">${xFormat(l)}</text>`}
        </g>`;
  })}
    </svg>`}
    <${Tooltip} tip=${tip} width=${width} />
  </div>`;
}

// -- horizontal bars --------------------------------------------------------------------

export function BarList({ items, format = compact, max, empty = 'Nothing in this period', onSelect }) {
  const [hover, setHover] = useState(null);
  if (!items.length || items.every((it) => !it.value)) return html`<div class="viz-empty">${empty}</div>`;
  const top = max || Math.max(...items.map((it) => it.value || 0)) || 1;
  return html`<ul class="viz-barlist">
    ${items.map((it, i) => {
    const pct = Math.max(0, ((it.value || 0) / top) * 100);
    const Tag = onSelect || it.href ? 'a' : 'div';
    return html`<li key=${it.key ?? it.label} class=${cx('viz-barrow', hover === i && 'is-active')}
          onPointerEnter=${() => setHover(i)} onPointerLeave=${() => setHover(null)}>
        <${Tag} class="viz-barrow-inner" href=${it.href} onClick=${onSelect ? () => onSelect(it) : undefined}
          title=${it.hint ? `${it.label}: ${format(it.value || 0)} · ${it.hint}` : undefined}>
          <span class="viz-barrow-label">${it.dot && html`<span class="viz-dot-key" style=${{ background: it.dot }}></span>`}${it.label}</span>
          <span class="viz-barrow-track"><span class="viz-barrow-fill" style=${{ width: pct + '%' }}></span></span>
          <span class="viz-barrow-value">${format(it.value || 0)}${it.suffix && html`<span class="viz-barrow-suffix">${it.suffix}</span>`}</span>
        </${Tag}>
      </li>`;
  })}
  </ul>`;
}

// -- heatmap ----------------------------------------------------------------------------

const BINS = 8;

export function Heatmap({ rows, cells, format = (v) => v, ariaLabel, unit = 'messages' }) {
  const wrap = useRef(null);
  const width = useWidth(wrap);
  const [active, setActive] = useState(null); // [row, col]
  const max = Math.max(0, ...cells.flat());
  const labelW = 38;
  const gap = 2;
  const cell = Math.max(8, Math.min(30, Math.floor((width - labelW - gap * 24) / 24)));
  const gridW = 24 * (cell + gap);
  const height = rows.length * (cell + gap) + 22;
  const bin = (v) => (v <= 0 || !max ? 0 : Math.min(BINS, Math.ceil((v / max) * BINS)));
  const hourLabel = (h) => (h === 0 ? '12a' : h < 12 ? `${h}a` : h === 12 ? '12p' : `${h - 12}p`);
  const hourRange = (h) => `${hourLabel(h)}–${hourLabel((h + 1) % 24)}`;
  const tip = active && {
    x: labelW + active[1] * (cell + gap), y: active[0] * (cell + gap) + cell + 6,
    title: `${rows[active[0]]} ${hourRange(active[1])}`,
    rows: [{ label: unit, value: format(cells[active[0]][active[1]]) }],
  };
  const onKey = (e) => {
    const [r, c] = active || [0, 9];
    const moves = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (moves[e.key]) {
      e.preventDefault();
      const [dr, dc] = moves[e.key];
      setActive([Math.max(0, Math.min(rows.length - 1, r + dr)), Math.max(0, Math.min(23, c + dc))]);
    } else if (e.key === 'Escape') setActive(null);
  };
  return html`<div class="viz-heatmap" ref=${wrap} tabIndex="0" role="figure" aria-label=${ariaLabel}
      onKeyDown=${onKey} onFocus=${() => !active && setActive([0, 9])} onBlur=${() => setActive(null)}
      onPointerLeave=${() => setActive(null)}>
    ${width > 0 && html`<svg width=${Math.min(width, labelW + gridW)} height=${height} aria-hidden="true">
      ${rows.map((r, ri) => html`<g key=${r}>
        <text x="0" y=${ri * (cell + gap) + cell / 2 + 4} class="viz-tick">${r}</text>
        ${cells[ri].map((v, ci) => html`<rect key=${ci} x=${labelW + ci * (cell + gap)} y=${ri * (cell + gap)}
          width=${cell} height=${cell} rx="3" class=${cx('viz-cell', `viz-bin-${bin(v)}`, active && active[0] === ri && active[1] === ci && 'is-active')}
          onPointerEnter=${() => setActive([ri, ci])} />`)}
      </g>`)}
      ${[0, 3, 6, 9, 12, 15, 18, 21].map((h) => html`<text key=${h} x=${labelW + h * (cell + gap)} y=${height - 4} class="viz-tick">${hourLabel(h)}</text>`)}
    </svg>`}
    <${Tooltip} tip=${tip} width=${width} />
    <div class="viz-scale" aria-hidden="true">
      <span>Fewer</span>
      ${Array.from({ length: BINS }, (_, i) => html`<span key=${i} class=${`viz-scale-step viz-bin-${i + 1}`}></span>`)}
      <span>More${max ? ` (${format(max)} max)` : ''}</span>
    </div>
  </div>`;
}

// -- figures ----------------------------------------------------------------------------

// direction: 'up' when higher is better, 'down' when lower is better, null for neutral.
export function Kpi({ label, value, current, previous, direction = 'up', hint, periodLabel }) {
  let delta = null;
  if (current !== null && current !== undefined && previous !== null && previous !== undefined) {
    if (previous === 0) delta = current === 0 ? { pct: 0 } : { pct: null };
    else delta = { pct: ((current - previous) / Math.abs(previous)) * 100 };
  }
  let tone = 'flat';
  let arrow = null;
  if (delta && delta.pct !== null && Math.abs(delta.pct) >= 0.5) {
    const up = delta.pct > 0;
    arrow = up ? 'arrow-up' : 'arrow-down';
    if (direction) tone = (up === (direction === 'up')) ? 'good' : 'bad';
  }
  return html`<div class="kpi">
    <div class="kpi-label">${label}</div>
    <div class="kpi-value">${value}</div>
    ${delta && html`<div class=${cx('kpi-delta', `is-${tone}`)}>
      ${arrow && html`<${Icon} name=${arrow} size=${13} strokeWidth=${2.4} />`}
      <span>${delta.pct === null ? 'new' : `${Math.abs(delta.pct) < 0.5 ? 'no change' : `${Math.round(Math.abs(delta.pct))}%`}`}</span>
      <span class="kpi-delta-period">vs ${periodLabel || 'previous period'}</span>
    </div>`}
    ${hint && html`<div class="kpi-hint">${hint}</div>`}
  </div>`;
}

// Meter: a single ratio against a target; the fill carries severity, with a label.
export function Meter({ value, label, status = 'good' }) {
  const pct = Math.max(0, Math.min(100, value || 0));
  return html`<div class=${cx('viz-meter', `is-${status}`)} role="meter" aria-valuenow=${pct} aria-valuemin="0" aria-valuemax="100" aria-label=${label}>
    <div class="viz-meter-fill" style=${{ width: pct + '%' }}></div>
  </div>`;
}

// -- tables -------------------------------------------------------------------------------

// columns: [{ key, label, num?, format?(value,row), sortValue?(row), render?(row) }]
export function DataTable({ columns, rows, defaultSort, empty = 'No data for this period', rowKey = (r, i) => i, onRowClick }) {
  const [sort, setSort] = useState(defaultSort || null); // { key, dir: 'asc'|'desc' }
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col) return rows;
    const val = col.sortValue || ((r) => r[col.key]);
    const out = [...rows].sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      if (va === vb) return 0;
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      return (va > vb ? 1 : -1) * (sort.dir === 'asc' ? 1 : -1);
    });
    return out;
  }, [rows, sort]);
  const toggle = (key, num) => {
    if (!sort || sort.key !== key) setSort({ key, dir: num ? 'desc' : 'asc' });
    else setSort({ key, dir: sort.dir === 'asc' ? 'desc' : 'asc' });
  };
  if (!rows.length) return html`<div class="viz-empty">${empty}</div>`;
  return html`<div class="viz-table-wrap"><table class="table viz-table">
    <thead><tr>${columns.map((c) => {
    const dir = sort && sort.key === c.key ? sort.dir : null;
    return html`<th key=${c.key} class=${cx(c.num && 'num')} aria-sort=${dir ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
        <button type="button" class="viz-sort" onClick=${() => toggle(c.key, c.num)}>
          ${c.label}${dir && html`<${Icon} name=${dir === 'asc' ? 'arrow-up' : 'arrow-down'} size=${11} />`}
        </button></th>`;
  })}</tr></thead>
    <tbody>${sorted.map((r, i) => html`<tr key=${rowKey(r, i)} class=${cx(onRowClick && 'is-clickable')} onClick=${onRowClick ? () => onRowClick(r) : undefined}>
      ${columns.map((c) => html`<td key=${c.key} class=${cx(c.num && 'num')}>${c.render ? c.render(r) : c.format ? c.format(r[c.key], r) : (r[c.key] ?? '—')}</td>`)}
    </tr>`)}</tbody>
  </table></div>`;
}

// A titled chart card that can flip to its accessible table view.
export function ChartCard({ title, subtitle, legend, table, children, actions, stale, class: cls, wide }) {
  const [view, setView] = useState('chart');
  useEffect(() => { if (!table && view === 'table') setView('chart'); }, [!!table]);
  return html`<section class=${cx('card viz-card', wide && 'viz-card-wide', cls)}>
    <header class="viz-card-header">
      <div class="viz-card-titles">
        <h3 class="viz-card-title">${title}</h3>
        ${subtitle && html`<div class="viz-card-sub">${subtitle}</div>`}
      </div>
      <div class="viz-card-tools">
        ${view === 'chart' && legend}
        ${table && html`<div class="segmented segmented-sm" role="radiogroup" aria-label="View">
          <button type="button" role="radio" aria-checked=${view === 'chart'} class=${cx('segmented-item', view === 'chart' && 'is-active')}
            onClick=${() => setView('chart')} aria-label="Chart view" data-tip="Chart"><${Icon} name="chart-line" size=${13} /></button>
          <button type="button" role="radio" aria-checked=${view === 'table'} class=${cx('segmented-item', view === 'table' && 'is-active')}
            onClick=${() => setView('table')} aria-label="Table view" data-tip="Table"><${Icon} name="table" size=${13} /></button>
        </div>`}
        ${actions}
      </div>
    </header>
    <div class=${cx('viz-card-body', stale && 'is-stale')}>
      ${view === 'table' && table ? html`<${DataTable} ...${table} />` : children}
    </div>
  </section>`;
}
