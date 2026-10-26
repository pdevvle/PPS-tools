"""Small server-rendered SVG charts for the dashboard and reports.

Marks follow one spec: columns at most 24px wide with a 4px rounded data
end and a 2px surface gap between neighbours, 2px lines with a 10% area
wash, hairline solid gridlines. Every mark carries its value for the hover
tooltip (``static/books.js``) and every chart ships a table view.
"""

from __future__ import annotations

import json
import math
from typing import Optional

from markupsafe import Markup, escape

from pps_tools.books.money import fmt


def compact_money(cents: int) -> str:
    v = cents / 100
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1_000_000:
        return f"{sign}${a / 1_000_000:.1f}M".replace(".0M", "M")
    if a >= 1_000:
        return f"{sign}${a / 1_000:.1f}K".replace(".0K", "K")
    return f"{sign}${a:,.0f}"


def nice_ticks(max_value: int, count: int = 4) -> list[int]:
    """0 and evenly spaced round ticks covering ``max_value`` (cents)."""
    if max_value <= 0:
        return [0, 10000, 20000, 30000, 40000][: count + 1]
    raw = max_value / count
    mag = 10 ** math.floor(math.log10(raw))
    for step in (1, 2, 2.5, 5, 10):
        if step * mag >= raw:
            break
    step_v = int(step * mag)
    return [i * step_v for i in range(count + 1)]


def _bar_path(x: float, y_top: float, width: float, y_base: float) -> str:
    """A column with a rounded top (4px) and a square foot on the baseline."""
    h = y_base - y_top
    if h <= 0:
        return ""
    r = min(4.0, width / 2, h)
    return (f"M{x:.1f},{y_base:.1f} V{y_top + r:.1f} Q{x:.1f},{y_top:.1f} {x + r:.1f},{y_top:.1f} "
            f"H{x + width - r:.1f} Q{x + width:.1f},{y_top:.1f} {x + width:.1f},{y_top + r:.1f} V{y_base:.1f} Z")


def column_chart(labels: list[str], series: list[dict], height: int = 240, width: int = 640,
                 full_labels: Optional[list[str]] = None, title: str = "") -> Markup:
    """Grouped columns. ``series``: [{"name", "values" (cents), "slot": 1..8}]."""
    full_labels = full_labels or labels
    left, right, top, bottom = 52, 8, 12, 28
    plot_w, plot_h = width - left - right, height - top - bottom
    max_v = max([max(s["values"] or [0]) for s in series] + [0])
    ticks = nice_ticks(max_v)
    y_max = ticks[-1] or 1

    def y(v: int) -> float:
        return top + plot_h - (max(v, 0) / y_max) * plot_h

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">']
    parts.append('<g class="grid">')
    for t in ticks:
        yy = y(t)
        parts.append(f'<line class="gridline" x1="{left}" x2="{width - right}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 8}" y="{yy + 4:.1f}" text-anchor="end">{compact_money(t)}</text>')
    parts.append("</g>")
    n = max(len(labels), 1)
    slot = plot_w / n
    k = max(len(series), 1)
    gap = 2
    bar_w = min(24.0, (slot * 0.62 - gap * (k - 1)) / k)
    group_w = bar_w * k + gap * (k - 1)
    base = top + plot_h
    for i, label in enumerate(labels):
        gx = left + slot * i + (slot - group_w) / 2
        for j, s in enumerate(series):
            v = s["values"][i] if i < len(s["values"]) else 0
            x = gx + j * (bar_w + gap)
            tip_v, tip_l = escape(fmt(v)), escape(f"{s['name']} · {full_labels[i]}")
            path = _bar_path(x, y(v), bar_w, base)
            parts.append(f'<rect class="hit" x="{x - gap / 2:.1f}" y="{top}" width="{bar_w + gap:.1f}" height="{plot_h}"'
                         f' data-tip-value="{tip_v}" data-tip-label="{tip_l}" tabindex="0"/>')
            if path:
                parts.append(f'<path class="mark s{s.get("slot", j + 1)}" d="{path}"/>')
        parts.append(f'<text class="tick" x="{left + slot * i + slot / 2:.1f}" y="{height - 8}" text-anchor="middle">'
                     f'{escape(label)}</text>')
    parts.append(f'<line class="baseline" x1="{left}" x2="{width - right}" y1="{base:.1f}" y2="{base:.1f}"/>')
    parts.append("</svg>")
    return Markup("".join(parts))


def line_chart(points: list[dict], height: int = 200, width: int = 640, title: str = "") -> Markup:
    """One series over time with an area wash and a crosshair tooltip.
    ``points``: [{"label", "full", "value" (cents)}]."""
    left, right, top, bottom = 56, 14, 14, 28
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [p["value"] for p in points] or [0]
    lo, hi = min(values + [0]), max(values + [0])
    ticks = nice_ticks(max(hi, abs(lo)) if lo >= 0 else hi - lo)
    if lo < 0:
        step = ticks[1] if len(ticks) > 1 else 1
        neg_steps = math.ceil(-lo / step)
        ticks = [-(i * step) for i in range(neg_steps, 0, -1)] + [t for t in ticks if t <= max(hi, step)]
    t_lo, t_hi = ticks[0], ticks[-1] if ticks[-1] != ticks[0] else ticks[0] + 1

    def y(v: int) -> float:
        return top + plot_h - (v - t_lo) / (t_hi - t_lo) * plot_h

    n = len(points)

    def x(i: int) -> float:
        return left + (plot_w * i / (n - 1) if n > 1 else plot_w / 2)

    data = [{"x": round(x(i), 1), "y": round(y(p["value"]), 1), "v": fmt(p["value"]), "l": p.get("full", p["label"])}
            for i, p in enumerate(points)]
    parts = [f'<svg class="chart line-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}"'
             f' data-points="{escape(json.dumps(data))}">']
    parts.append('<g class="grid">')
    for t in ticks:
        yy = y(t)
        parts.append(f'<line class="gridline" x1="{left}" x2="{width - right}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 8}" y="{yy + 4:.1f}" text-anchor="end">{compact_money(t)}</text>')
    parts.append("</g>")
    if points:
        line = " ".join(f"{'M' if i == 0 else 'L'}{d['x']},{d['y']}" for i, d in enumerate(data))
        zero = y(max(t_lo, 0)) if t_lo <= 0 <= t_hi else y(t_lo)
        area = f"{line} L{data[-1]['x']},{zero:.1f} L{data[0]['x']},{zero:.1f} Z"
        parts.append(f'<path class="area s1" d="{area}"/>')
        parts.append(f'<path class="line s1" d="{line}"/>')
        end = data[-1]
        parts.append(f'<circle class="dot s1" cx="{end["x"]}" cy="{end["y"]}" r="4"/>')
        parts.append(f'<text class="end-label" x="{end["x"] - 6}" y="{end["y"] - 10}" text-anchor="end">'
                     f'{escape(end["v"])}</text>')
    for i, p in enumerate(points):
        parts.append(f'<text class="tick" x="{x(i):.1f}" y="{height - 8}" text-anchor="middle">{escape(p["label"])}</text>')
    parts.append(f'<line class="crosshair hidden" x1="0" x2="0" y1="{top}" y2="{top + plot_h}"/>')
    parts.append(f'<rect class="overlay" x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" tabindex="0"/>')
    parts.append("</svg>")
    return Markup("".join(parts))


def hbar_rows(rows: list[dict]) -> Markup:
    """Horizontal bars as HTML rows: label, bar, value at the tip. One series."""
    max_v = max([r["amount"] for r in rows] + [1])
    out = ['<div class="hbars">']
    for r in rows:
        # The longest bar fills 75% of the track so its value label still fits beside it.
        pct = max(0.0, r["amount"] / max_v * 75)
        label = escape(r["name"])
        href = r.get("href")
        name = f'<a href="{escape(href)}">{label}</a>' if href else label
        out.append(f'<div class="hbar-row"><div class="hbar-label">{name}</div>'
                   f'<div class="hbar-track"><span class="hbar s1" style="width:{pct:.1f}%" '
                   f'data-tip-value="{escape(fmt(r["amount"]))}" data-tip-label="{label}" tabindex="0"></span>'
                   f'<span class="hbar-value">{escape(fmt(r["amount"]))}</span></div></div>')
    out.append("</div>")
    return Markup("".join(out))
