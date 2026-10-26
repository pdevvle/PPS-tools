/* PPS Marketing Hub — shared browser code: theme, fetch + CSRF, toasts,
   tables, copy buttons, and the dependency-free SVG charts. */
(function () {
  "use strict";

  var MK = (window.MK = {});
  var SVG = "http://www.w3.org/2000/svg";

  // -- basics -------------------------------------------------------------------

  function csrf() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  MK.post = function (url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
      body: JSON.stringify(body || {}),
      credentials: "same-origin",
    }).then(function (resp) {
      return resp
        .json()
        .catch(function () { return {}; })
        .then(function (data) {
          if (!resp.ok || data.ok === false) {
            throw new Error(data.error || resp.statusText || "Request failed");
          }
          return data;
        });
    });
  };

  MK.el = function (tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };

  MK.toast = function (message, kind) {
    var box = document.querySelector(".toasts");
    if (!box) {
      box = MK.el("div", { class: "toasts", role: "status", "aria-live": "polite" });
      document.body.appendChild(box);
    }
    var t = MK.el("div", { class: "toast" + (kind === "error" ? " error" : "") }, message);
    box.appendChild(t);
    setTimeout(function () { t.remove(); }, kind === "error" ? 7000 : 4000);
  };

  MK.copy = function (text) {
    var done = function () { MK.toast("Copied to clipboard"); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text); done(); });
    } else {
      fallbackCopy(text);
      done();
    }
  };

  function fallbackCopy(text) {
    var ta = MK.el("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) { /* ignore */ }
    ta.remove();
  }

  // -- number formatting (mirrors the server-side filters) ------------------------

  MK.fmt = {
    money: function (v, sym) {
      if (v === null || v === undefined || isNaN(v)) return "—";
      sym = sym === undefined ? "$" : sym;
      var abs = Math.abs(v);
      var s = abs.toLocaleString(undefined, { minimumFractionDigits: abs < 1000 ? 2 : 0, maximumFractionDigits: abs < 1000 ? 2 : 0 });
      return (v < 0 ? "-" : "") + sym + s;
    },
    compact: function (v, sym) {
      if (v === null || v === undefined || isNaN(v)) return "—";
      sym = sym || "";
      var abs = Math.abs(v);
      var out;
      if (abs >= 1e6) out = (abs / 1e6).toFixed(1) + "M";
      else if (abs >= 1e3) out = (abs / 1e3).toFixed(abs >= 1e4 ? 0 : 1) + "K";
      else out = abs.toLocaleString(undefined, { maximumFractionDigits: abs < 10 ? 1 : 0 });
      return (v < 0 ? "-" : "") + sym + out;
    },
    num: function (v, digits) {
      if (v === null || v === undefined || isNaN(v)) return "—";
      return Number(v).toLocaleString(undefined, { minimumFractionDigits: digits || 0, maximumFractionDigits: digits || 0 });
    },
    pct: function (v) {
      return v === null || v === undefined ? "—" : (v * 100).toFixed(2) + "%";
    },
    day: function (iso, long) {
      var d = new Date(iso + "T00:00:00");
      return d.toLocaleDateString(undefined, long ? { weekday: "short", month: "short", day: "numeric" } : { month: "short", day: "numeric" });
    },
  };

  // -- theme ------------------------------------------------------------------------

  function applyTheme(mode) {
    var root = document.documentElement;
    if (mode === "light" || mode === "dark") root.setAttribute("data-theme", mode);
    else root.removeAttribute("data-theme");
    try { localStorage.setItem("mk-theme", mode); } catch (e) { /* private mode */ }
    document.querySelectorAll("[data-theme-set]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-theme-set") === mode));
    });
    document.dispatchEvent(new Event("mk:theme"));
  }

  function storedTheme() {
    try { return localStorage.getItem("mk-theme") || "auto"; } catch (e) { return "auto"; }
  }

  // -- tables: sort + filter ---------------------------------------------------------

  function sortTable(table, th) {
    var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
    var dir = th.getAttribute("aria-sort") === "descending" ? "ascending" : "descending";
    table.querySelectorAll("th[aria-sort]").forEach(function (h) { h.removeAttribute("aria-sort"); });
    th.setAttribute("aria-sort", dir);
    var body = table.tBodies[0];
    var rows = Array.prototype.slice.call(body.rows);
    var numeric = th.getAttribute("data-sort") === "num";
    rows.sort(function (a, b) {
      var ca = a.cells[idx], cb = b.cells[idx];
      var va = ca ? ca.getAttribute("data-value") || ca.textContent.trim() : "";
      var vb = cb ? cb.getAttribute("data-value") || cb.textContent.trim() : "";
      var r;
      if (numeric) {
        var na = parseFloat(va), nb = parseFloat(vb);
        na = isNaN(na) ? -Infinity : na;
        nb = isNaN(nb) ? -Infinity : nb;
        r = na - nb;
      } else {
        r = va.localeCompare(vb);
      }
      return dir === "ascending" ? r : -r;
    });
    rows.forEach(function (r) { body.appendChild(r); });
  }

  // -- charts -------------------------------------------------------------------------

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function svgEl(tag, attrs) {
    var node = document.createElementNS(SVG, tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    return node;
  }

  function niceStep(raw) {
    var exp = Math.pow(10, Math.floor(Math.log10(raw)));
    var f = raw / exp;
    var nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
    return nice * exp;
  }

  function ticks(max, count) {
    if (!(max > 0)) return [0, 1];
    var step = niceStep(max / (count || 4));
    var out = [];
    for (var v = 0; v <= max + step * 0.999; v += step) out.push(Math.round(v * 1e6) / 1e6);
    return out;
  }

  var tooltip;
  function tip() {
    if (!tooltip) {
      tooltip = MK.el("div", { class: "tooltip", role: "tooltip" });
      document.body.appendChild(tooltip);
    }
    return tooltip;
  }

  function showTip(evt, title, rows, total) {
    var t = tip();
    t.textContent = "";
    t.appendChild(MK.el("div", { class: "tt-title" }, title));
    rows.forEach(function (r) {
      var row = MK.el("div", { class: "tt-row" });
      var k = MK.el("span", { class: "k" });
      if (r.color) {
        var key = MK.el("i");
        key.style.background = r.color;
        k.appendChild(key);
      }
      k.appendChild(document.createTextNode(r.label));
      row.appendChild(k);
      row.appendChild(MK.el("span", { class: "v" }, r.value));
      t.appendChild(row);
    });
    if (total) {
      var tr = MK.el("div", { class: "tt-row tt-total" });
      tr.appendChild(MK.el("span", { class: "k" }, total.label));
      tr.appendChild(MK.el("span", { class: "v" }, total.value));
      t.appendChild(tr);
    }
    t.style.display = "block";
    var x, y;
    if (evt && evt.clientX !== undefined && evt.type !== "focus") {
      x = evt.clientX; y = evt.clientY;
    } else {
      var r0 = evt.target.getBoundingClientRect();
      x = r0.left + r0.width / 2; y = r0.top;
    }
    var w = t.offsetWidth, h = t.offsetHeight;
    var left = x + 14, top = y - h - 10;
    if (left + w > window.innerWidth - 8) left = x - w - 14;
    if (top < 8) top = y + 16;
    t.style.left = Math.max(8, left) + "px";
    t.style.top = top + "px";
  }

  function hideTip() {
    if (tooltip) tooltip.style.display = "none";
  }

  function xLabelIndexes(n, width) {
    var max = Math.max(2, Math.floor(width / 70));
    var step = Math.max(1, Math.ceil(n / max));
    var out = [];
    for (var i = 0; i < n; i += step) out.push(i);
    return out;
  }

  function axes(svg, opts) {
    var g = svgEl("g", {});
    opts.ticks.forEach(function (v) {
      var y = opts.y(v);
      g.appendChild(svgEl("line", { x1: opts.left, x2: opts.width - opts.right, y1: y, y2: y, stroke: v === 0 ? cssVar("--axis") : cssVar("--grid"), "stroke-width": 1, "shape-rendering": "crispEdges" }));
      var label = svgEl("text", { x: opts.left - 8, y: y + 4, "text-anchor": "end", fill: cssVar("--muted"), "font-size": 11, style: "font-variant-numeric: tabular-nums" });
      label.textContent = opts.format(v);
      g.appendChild(label);
    });
    xLabelIndexes(opts.days.length, opts.width - opts.left - opts.right).forEach(function (i) {
      var t = svgEl("text", { x: opts.x(i), y: opts.height - 6, "text-anchor": "middle", fill: cssVar("--muted"), "font-size": 11 });
      t.textContent = MK.fmt.day(opts.days[i]);
      g.appendChild(t);
    });
    svg.appendChild(g);
  }

  function buildTable(container, head, rows) {
    var table = MK.el("table", { class: "data" });
    var thead = MK.el("thead");
    var tr = MK.el("tr");
    head.forEach(function (h, i) { tr.appendChild(MK.el("th", { class: i ? "num" : "" }, h)); });
    thead.appendChild(tr);
    table.appendChild(thead);
    var tbody = MK.el("tbody");
    rows.forEach(function (r) {
      var row = MK.el("tr");
      r.forEach(function (c, i) { row.appendChild(MK.el("td", { class: i ? "num" : "" }, c)); });
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    container.textContent = "";
    container.appendChild(table);
  }

  /* Stacked columns: one column per day, one segment per network (fixed order). */
  function stacked(root, data) {
    var chartBox = root.querySelector(".chart");
    var legend = root.querySelector(".legend");
    var tableBox = root.querySelector(".chart-table");
    var sym = data.currency || "";
    var series = data.series.filter(function (s) { return s.values.some(function (v) { return v > 0; }); });
    var n = data.days.length;
    var totals = data.days.map(function (_, i) {
      return series.reduce(function (sum, s) { return sum + (s.values[i] || 0); }, 0);
    });

    if (legend) {
      legend.textContent = "";
      series.forEach(function (s) {
        var li = MK.el("li");
        li.appendChild(MK.el("span", { class: "swatch s" + s.slot }));
        var sum = s.values.reduce(function (a, b) { return a + b; }, 0);
        li.appendChild(document.createTextNode(s.label + " · " + MK.fmt.compact(sum, sym)));
        legend.appendChild(li);
      });
    }
    if (tableBox) {
      buildTable(
        tableBox,
        ["Date"].concat(series.map(function (s) { return s.label; })).concat(["Total"]),
        data.days.map(function (d, i) {
          return [MK.fmt.day(d, true)].concat(series.map(function (s) { return MK.fmt.money(s.values[i], sym); })).concat([MK.fmt.money(totals[i], sym)]);
        })
      );
    }

    function draw() {
      var width = chartBox.clientWidth || 600;
      var height = 264, left = 52, right = 8, top = 10, bottom = 26;
      var plotH = height - top - bottom;
      var max = Math.max.apply(null, totals.concat([0]));
      var tk = ticks(max, 4);
      var yMax = tk[tk.length - 1] || 1;
      var band = (width - left - right) / Math.max(n, 1);
      var barW = Math.max(1, Math.min(24, band - 2));
      var y = function (v) { return top + plotH - (v / yMax) * plotH; };
      var x = function (i) { return left + band * i + band / 2; };
      var svg = svgEl("svg", { width: width, height: height, role: "img", "aria-label": root.getAttribute("data-title") || "Chart" });
      var hover = svgEl("rect", { y: top, height: plotH, width: band, fill: cssVar("--surface-3"), opacity: 0, rx: 3 });
      svg.appendChild(hover);
      axes(svg, { ticks: tk, y: y, x: x, left: left, right: right, width: width, height: height, days: data.days, format: function (v) { return MK.fmt.compact(v, sym); } });

      var bars = svgEl("g", {});
      for (var i = 0; i < n; i++) {
        var base = 0;
        var segs = [];
        series.forEach(function (s) {
          var v = s.values[i] || 0;
          if (v > 0) segs.push({ s: s, v0: base, v1: base + v });
          base += v;
        });
        segs.forEach(function (seg, j) {
          var y0 = y(seg.v0), y1 = y(seg.v1);
          var h = y0 - y1 - (j > 0 ? 2 : 0); // 2px surface gap between stacked segments
          if (h < 0.5) return;
          var x0 = x(i) - barW / 2;
          var fill = cssVar("--series-" + seg.s.slot);
          var isTop = j === segs.length - 1;
          var r = Math.min(4, barW / 2, h);
          if (isTop && r > 0) {
            var d = "M" + x0 + "," + (y1 + h) + "V" + (y1 + r) + "Q" + x0 + "," + y1 + " " + (x0 + r) + "," + y1 +
              "H" + (x0 + barW - r) + "Q" + (x0 + barW) + "," + y1 + " " + (x0 + barW) + "," + (y1 + r) + "V" + (y1 + h) + "Z";
            bars.appendChild(svgEl("path", { d: d, fill: fill }));
          } else {
            bars.appendChild(svgEl("rect", { x: x0, y: y1, width: barW, height: h, fill: fill }));
          }
        });
      }
      svg.appendChild(bars);

      // Hit targets: the whole day band, keyboard-focusable.
      var hits = svgEl("g", {});
      data.days.forEach(function (day, i) {
        var rect = svgEl("rect", { x: left + band * i, y: top, width: band, height: plotH, fill: "transparent", tabindex: 0, "aria-label": MK.fmt.day(day, true) + ": " + MK.fmt.money(totals[i], sym) });
        var show = function (evt) {
          hover.setAttribute("x", left + band * i);
          hover.setAttribute("opacity", 1);
          showTip(evt, MK.fmt.day(day, true),
            series.filter(function (s) { return s.values[i] > 0; }).slice().reverse().map(function (s) {
              return { label: s.label, value: MK.fmt.money(s.values[i], sym), color: cssVar("--series-" + s.slot) };
            }),
            { label: "Total", value: MK.fmt.money(totals[i], sym) });
        };
        rect.addEventListener("pointermove", show);
        rect.addEventListener("focus", show);
        rect.addEventListener("pointerleave", function () { hover.setAttribute("opacity", 0); hideTip(); });
        rect.addEventListener("blur", function () { hover.setAttribute("opacity", 0); hideTip(); });
        hits.appendChild(rect);
      });
      svg.appendChild(hits);
      chartBox.textContent = "";
      chartBox.appendChild(svg);
    }
    draw();
    observe(chartBox, draw);
  }

  /* Single-series line with a soft area wash, crosshair and an end label. */
  function line(root, data) {
    var chartBox = root.querySelector(".chart");
    var tableBox = root.querySelector(".chart-table");
    var values = data.values;
    var n = values.length;
    var fmt = data.format === "money" ? function (v) { return MK.fmt.money(v, data.currency || "$"); } : function (v) { return MK.fmt.num(v, v % 1 ? 1 : 0); };
    if (tableBox) {
      buildTable(tableBox, ["Date", data.label], data.days.map(function (d, i) { return [MK.fmt.day(d, true), fmt(values[i])]; }));
    }
    function draw() {
      var width = chartBox.clientWidth || 600;
      var height = 220, left = 44, right = 44, top = 14, bottom = 26;
      var plotH = height - top - bottom;
      var tk = ticks(Math.max.apply(null, values.concat([0])), 4);
      var yMax = tk[tk.length - 1] || 1;
      var step = n > 1 ? (width - left - right) / (n - 1) : 0;
      var x = function (i) { return left + step * i; };
      var y = function (v) { return top + plotH - (v / yMax) * plotH; };
      var svg = svgEl("svg", { width: width, height: height, role: "img", "aria-label": data.label });
      axes(svg, { ticks: tk, y: y, x: x, left: left, right: right, width: width, height: height, days: data.days, format: function (v) { return MK.fmt.compact(v); } });
      var stroke = cssVar("--ink-2");
      var pts = values.map(function (v, i) { return x(i) + "," + y(v); });
      if (n > 1) {
        svg.appendChild(svgEl("path", { d: "M" + x(0) + "," + y(0) + "L" + pts.join("L") + "L" + x(n - 1) + "," + y(0) + "Z", fill: stroke, opacity: 0.1 }));
        svg.appendChild(svgEl("path", { d: "M" + pts.join("L"), fill: "none", stroke: stroke, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      }
      var last = n - 1;
      if (last >= 0) {
        svg.appendChild(svgEl("circle", { cx: x(last), cy: y(values[last]), r: 4, fill: stroke, stroke: cssVar("--surface"), "stroke-width": 2 }));
        var endLabel = svgEl("text", { x: x(last) + 8, y: y(values[last]) + 4, fill: cssVar("--ink"), "font-size": 11, "font-weight": 600 });
        endLabel.textContent = fmt(values[last]);
        svg.appendChild(endLabel);
      }
      var cross = svgEl("line", { y1: top, y2: top + plotH, stroke: cssVar("--axis"), "stroke-width": 1, opacity: 0 });
      var dot = svgEl("circle", { r: 4, fill: stroke, stroke: cssVar("--surface"), "stroke-width": 2, opacity: 0 });
      svg.appendChild(cross);
      svg.appendChild(dot);
      var hit = svgEl("rect", { x: left - step / 2, y: top, width: width - left - right + step, height: plotH, fill: "transparent", tabindex: 0, "aria-label": data.label + " by day" });
      var focusIdx = last;
      var show = function (evt, idx) {
        var i = idx;
        if (i === undefined) {
          var box = svg.getBoundingClientRect();
          i = Math.round((evt.clientX - box.left - left) / (step || 1));
        }
        i = Math.max(0, Math.min(n - 1, i));
        cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("opacity", 1);
        dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(values[i])); dot.setAttribute("opacity", 1);
        showTip(evt, MK.fmt.day(data.days[i], true), [{ label: data.label, value: fmt(values[i]), color: stroke }]);
        focusIdx = i;
      };
      var hide = function () { cross.setAttribute("opacity", 0); dot.setAttribute("opacity", 0); hideTip(); };
      hit.addEventListener("pointermove", function (e) { show(e); });
      hit.addEventListener("pointerleave", hide);
      hit.addEventListener("focus", function (e) { show(e, focusIdx); });
      hit.addEventListener("blur", hide);
      hit.addEventListener("keydown", function (e) {
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          show({ target: hit, type: "focus" }, focusIdx + (e.key === "ArrowRight" ? 1 : -1));
        }
      });
      svg.appendChild(hit);
      chartBox.textContent = "";
      chartBox.appendChild(svg);
    }
    draw();
    observe(chartBox, draw);
  }

  /* Sparkline: de-emphasized line, the latest point marked in ink. */
  function spark(svg, values) {
    if (!values || !values.length) return;
    function draw() {
      var w = svg.clientWidth || svg.parentNode.clientWidth || 100;
      var h = svg.clientHeight || 28;
      var max = Math.max.apply(null, values), min = Math.min.apply(null, values.concat([0]));
      var span = max - min || 1;
      var pad = 4;
      var step = values.length > 1 ? (w - pad * 2) / (values.length - 1) : 0;
      var pts = values.map(function (v, i) { return [pad + step * i, h - pad - ((v - min) / span) * (h - pad * 2)]; });
      svg.textContent = "";
      svg.setAttribute("viewBox", "0 0 " + w + " " + h);
      svg.appendChild(svgEl("polyline", { points: pts.map(function (p) { return p.join(","); }).join(" "), fill: "none", stroke: cssVar("--muted"), "stroke-width": 1.5, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      var lastPt = pts[pts.length - 1];
      svg.appendChild(svgEl("circle", { cx: lastPt[0], cy: lastPt[1], r: 2.5, fill: cssVar("--ink") }));
    }
    draw();
    observe(svg.parentNode, draw);
  }

  var observers = [];
  function observe(node, fn) {
    observers.push(fn);
    if (!window.ResizeObserver) return;
    var last = node.clientWidth;
    var ro = new ResizeObserver(function () {
      if (Math.abs(node.clientWidth - last) > 4) {
        last = node.clientWidth;
        fn();
      }
    });
    ro.observe(node);
  }
  document.addEventListener("mk:theme", function () { observers.forEach(function (fn) { fn(); }); });
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    var redraw = function () { observers.forEach(function (fn) { fn(); }); };
    if (mq.addEventListener) mq.addEventListener("change", redraw);
  }

  MK.charts = { stacked: stacked, line: line, spark: spark };

  MK.readJSON = function (id) {
    var node = document.getElementById(id);
    return node ? JSON.parse(node.textContent) : null;
  };

  // -- wire up page-wide behaviours ------------------------------------------------------

  document.addEventListener("DOMContentLoaded", function () {
    applyTheme(storedTheme());
    document.querySelectorAll("[data-theme-set]").forEach(function (b) {
      b.addEventListener("click", function () { applyTheme(b.getAttribute("data-theme-set")); });
    });

    document.querySelectorAll("time[data-local]").forEach(function (t) {
      var d = new Date(t.getAttribute("datetime"));
      if (isNaN(d)) return;
      t.textContent = d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
      t.title = d.toString();
    });

    document.querySelectorAll("[data-copy]").forEach(function (b) {
      b.addEventListener("click", function () { MK.copy(b.getAttribute("data-copy")); });
    });

    document.querySelectorAll("form[data-confirm]").forEach(function (f) {
      f.addEventListener("submit", function (e) {
        if (!window.confirm(f.getAttribute("data-confirm"))) e.preventDefault();
      });
    });

    document.querySelectorAll("table[data-sortable] th[data-sort]").forEach(function (th) {
      th.setAttribute("tabindex", "0");
      var go = function () { sortTable(th.closest("table"), th); };
      th.addEventListener("click", go);
      th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    });

    document.querySelectorAll("[data-table-toggle]").forEach(function (b) {
      b.addEventListener("click", function () {
        var box = document.getElementById(b.getAttribute("data-table-toggle"));
        var open = box.classList.toggle("open");
        b.textContent = open ? "Hide table" : "Show as table";
        b.setAttribute("aria-expanded", String(open));
      });
    });

    document.querySelectorAll("svg[data-spark]").forEach(function (svg) {
      try { spark(svg, JSON.parse(svg.getAttribute("data-spark"))); } catch (e) { /* ignore bad data */ }
    });

    document.querySelectorAll("form[data-busy]").forEach(function (f) {
      f.addEventListener("submit", function (e) {
        var btn = e.submitter || f.querySelector("button[type=submit]");
        if (!btn) return;
        // Wait until every submit handler has run (one may cancel), and until the
        // browser has read the clicked button's name/value, before disabling it.
        setTimeout(function () {
          if (e.defaultPrevented) return;
          btn.insertAdjacentHTML("afterbegin", '<span class="spinner" aria-hidden="true"></span> ');
          btn.disabled = true;
        }, 0);
      });
    });
  });
})();
