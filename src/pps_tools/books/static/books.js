/* PPS Books client script. Plain JS, no dependencies. The server recomputes
   every total when a form is saved; this keeps the screen honest meanwhile. */
(function () {
  "use strict";

  // ---------- money helpers (integer cents, like the server) ----------
  function parseCents(text) {
    if (text === null || text === undefined) return 0;
    var s = String(text).trim();
    if (!s) return 0;
    var neg = false;
    if (/^\(.*\)$/.test(s)) { neg = true; s = s.slice(1, -1); }
    s = s.replace(/[$,\s]/g, "");
    if (s.endsWith("-")) { neg = !neg; s = s.slice(0, -1); }
    if (s.startsWith("-")) { neg = !neg; s = s.slice(1); }
    var n = parseFloat(s);
    if (isNaN(n)) return 0;
    var c = Math.round(n * 100 + (n >= 0 ? 1e-9 : -1e-9));
    return neg ? -c : c;
  }
  function parseNum(text) {
    if (text === null || text === undefined) return NaN;
    var s = String(text).replace(/[$,\s]/g, "");
    return s === "" ? NaN : parseFloat(s);
  }
  function fmt(cents) {
    var neg = cents < 0, v = Math.abs(cents);
    var whole = Math.floor(v / 100), frac = v % 100;
    var body = "$" + whole.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "." + (frac < 10 ? "0" : "") + frac;
    return neg ? "-" + body : body;
  }
  function plain(cents) {
    var neg = cents < 0, v = Math.abs(cents);
    return (neg ? "-" : "") + Math.floor(v / 100) + "." + ((v % 100) < 10 ? "0" : "") + (v % 100);
  }
  function roundHalfUp(x) { return x >= 0 ? Math.floor(x + 0.5 + 1e-9) : -Math.floor(-x + 0.5 + 1e-9); }
  window.Books = { parseCents: parseCents, fmt: fmt, plain: plain };

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function csrf() { var m = $('meta[name="csrf-token"]'); return m ? m.content : ""; }

  // ---------- generic page behaviour ----------
  document.addEventListener("click", function (e) {
    $$("details.menu[open]").forEach(function (d) { if (!d.contains(e.target)) d.removeAttribute("open"); });
    var tr = e.target.closest("tr[data-href]");
    if (tr && !e.target.closest("a, button, input, select, textarea, label")) window.location = tr.dataset.href;
  });
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (t.matches("[data-select-all]")) {
      $$('input[type=checkbox][name="' + t.dataset.selectAll + '"]').forEach(function (c) { c.checked = t.checked; });
      updateBatch();
    } else if (t.matches("input[type=checkbox][data-batch]")) {
      updateBatch();
    }
    if (t.matches("[data-autosubmit]")) t.form.submit();
  });
  function updateBatch() {
    var bar = $("#batch-bar");
    if (!bar) return;
    var n = $$("input[type=checkbox][data-batch]:checked").length;
    bar.classList.toggle("hidden", n === 0);
    var c = $("#batch-count", bar);
    if (c) c.textContent = n;
  }
  // Report date presets: show custom date inputs only for "custom".
  $$("select[data-preset]").forEach(function (sel) {
    function sync() {
      $$(".custom-dates", sel.form).forEach(function (el) { el.classList.toggle("hidden", sel.value !== "custom"); });
    }
    sel.addEventListener("change", sync); sync();
  });
  $$("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var el = document.getElementById(btn.dataset.copy);
      if (!el) return;
      navigator.clipboard && navigator.clipboard.writeText(el.value || el.textContent);
      btn.textContent = "Copied";
    });
  });

  // ---------- transaction form ----------
  var form = document.getElementById("txn-form");
  if (form) initTxnForm(form);

  function initTxnForm(form) {
    var type = form.dataset.type;
    var items = JSON.parse(($("#items-json") || { textContent: "{}" }).textContent || "{}");
    var terms = JSON.parse(($("#terms-json") || { textContent: "{}" }).textContent || "{}");
    var salesDoc = ["estimate", "invoice", "sales_receipt", "credit_memo", "refund_receipt", "delayed_charge", "delayed_credit"].indexOf(type) >= 0;
    var counter = 1000;
    var customerTaxable = true;

    // footer buttons set the next action
    $$("button[data-action]", form).forEach(function (b) {
      b.addEventListener("click", function () { $("#next-action").value = b.dataset.action; });
    });
    ["void-form", "delete-form"].forEach(function (id) {
      var f = document.getElementById(id);
      if (!f) return;
      f.addEventListener("submit", function () {
        var pw = $('input[name="closing_password"]', form), ok = $('input[name="confirm_closed"]', form);
        if (pw && pw.value) addHidden(f, "closing_password", pw.value);
        if (ok && ok.checked) addHidden(f, "confirm_closed", "1");
      });
    });
    function addHidden(f, name, value) {
      var i = document.createElement("input"); i.type = "hidden"; i.name = name; i.value = value; f.appendChild(i);
    }

    // ---- lines ----
    function lineTables() { return $$("table.lines", form); }
    function renumber() {
      var pos = 0;
      lineTables().forEach(function (tbl) {
        var n = 0;
        $$("tbody tr.line", tbl).forEach(function (tr) {
          n += 1;
          var num = $(".ln-num", tr); if (num) num.textContent = n;
          var p = $('[data-f="pos"]', tr); if (p) p.value = pos;
          pos += 1;
        });
      });
    }
    function addLine(tplId, tableId, values) {
      var tpl = document.getElementById(tplId), tbl = document.getElementById(tableId);
      if (!tpl || !tbl) return null;
      counter += 1;
      var html = tpl.innerHTML.replace(/__I__/g, String(counter));
      var tbody = $("tbody", tbl);
      var tmp = document.createElement("tbody");
      tmp.innerHTML = html;
      var tr = tmp.firstElementChild;
      tbody.appendChild(tr);
      if (values) fillLine(tr, values);
      renumber();
      return tr;
    }
    function fillLine(tr, v) {
      Object.keys(v).forEach(function (k) {
        var el = $('[name$="-' + k + '"]', tr);
        if (!el) return;
        if (el.type === "checkbox") el.checked = !!v[k];
        else if (v[k] !== null && v[k] !== undefined) el.value = v[k];
      });
    }
    form.addEventListener("click", function (e) {
      var b = e.target.closest("[data-act]");
      if (!b) return;
      var act = b.dataset.act;
      if (act === "add-line") { e.preventDefault(); addLine(b.dataset.tpl, b.dataset.table); }
      else if (act === "del-line") {
        e.preventDefault();
        var tr = b.closest("tr"), tbody = tr.parentNode;
        tr.remove();
        if (!$("tr.line", tbody)) {
          var tbl = tbody.closest("table"), tpl = tbl.id === "cat-lines" ? "tpl-cat" : tbl.id === "je-lines" ? "tpl-je"
            : tbl.id === "dep-lines" ? "tpl-dep" : (tbl.dataset.purchase ? "tpl-pitem" : "tpl-item");
          if (tbl.id !== "item-lines" || !tbl.dataset.purchase) addLine(tpl, tbl.id);
        }
        renumber(); recalc();
      } else if (act === "clear-lines") {
        e.preventDefault();
        var t = document.getElementById(b.dataset.table);
        if (t && confirm("Clear all lines?")) { $$("tbody tr.line", t).forEach(function (tr) { tr.remove(); }); recalc(); renumber(); }
      } else if (act === "add-billable") {
        e.preventDefault();
        var row = b.closest("tr"), data = JSON.parse(row.dataset.billable);
        var tr = addLine("tpl-item", "item-lines");
        if (tr) {
          fillLine(tr, { item_id: data.item_id || "", description: data.description, qty: data.qty, rate: data.rate,
                         amount: data.amount, taxable: data.taxable, source_type: data.source_type, source_id: data.source_id });
          if (!data.item_id && data.account_id) {
            var h = document.createElement("input"); h.type = "hidden"; h.name = $('[data-f="pos"]', tr).name.replace("-pos", "-account_id");
            h.value = data.account_id; $(".ln", tr).appendChild(h);
          }
          removeBlankLines("item-lines");
        }
        row.remove(); recalc();
      } else if (act === "apply-all") {
        var on = b.checked;
        $$("#apply-targets tbody tr", form).forEach(function (tr) {
          var cb = $('[data-act="apply-one"]', tr), input = $('[data-f="apply"]', tr), open = $("[data-open]", tr);
          if (!cb || !input) return;
          cb.checked = on; input.value = on ? open.dataset.open : "";
        });
        applyChanged();
      } else if (act === "apply-one" || act === "credit-one") {
        var tr2 = b.closest("tr"), input2 = $('[data-f="apply"], [data-f="credit"]', tr2), open2 = $("[data-open]", tr2);
        input2.value = b.checked ? fitToRemaining(open2.dataset.open, act) : "";
        applyChanged();
      } else if (act === "toggle-all-deposits") {
        $$('input[name="deposit_ids"]', form).forEach(function (c) { c.checked = b.checked; });
        recalc();
      }
    });
    function fitToRemaining(openText, act) {
      // When ticking an invoice in Receive Payment, apply what's left of the amount received (or the full balance).
      var open = parseCents(openText);
      if (act !== "apply-one") return plain(open);
      var received = $('[data-role="amount-received"]', form);
      if (!received || !received.value || received.dataset.userTyped !== "1") return plain(open);
      var left = parseCents(received.value) + creditTotal() - targetTotal();
      return plain(Math.max(0, Math.min(open, left)));
    }
    function removeBlankLines(tableId) {
      var tbl = document.getElementById(tableId);
      $$("tbody tr.line", tbl).forEach(function (tr) {
        var any = $$("select, input:not([type=hidden]):not([type=checkbox]), textarea", tr).some(function (el) { return el.value && !el.readOnly; });
        if (!any) tr.remove();
      });
      renumber();
    }

    form.addEventListener("change", function (e) {
      var el = e.target, tr = el.closest("tr.line");
      if (el.matches('[data-f="item"]') && tr) onItem(tr, el.value);
      if (el.matches('[data-role="customer"]')) onCustomer(el.value);
      if (el.matches('[data-role="vendor"]')) onVendor(el.value);
      if (el.matches('[data-role="payee"]') && el.value.indexOf("vendor:") === 0) onVendor(el.value.split(":")[1], true);
      if (el.matches('[data-role="terms"]') || el.matches('[data-role="date"]')) { updateDue(); checkClosing(); }
      if (el.matches('[data-role="pay-account"]') && type === "check") nextCheck(el.value);
      if (el.matches('[data-role="tax-override"]')) {
        var amt = $('[data-role="tax-amount"]', form); amt.readOnly = !el.checked;
        if (el.checked) amt.focus();
      }
      if (el.matches('input[name="deposit_ids"]')) recalc();
      recalc();
    });
    form.addEventListener("input", function (e) {
      var el = e.target, tr = el.closest("tr.line");
      if (tr) {
        var f = el.dataset.f;
        if (type === "inventory_adjustment" && f === "qty") adjFromChange(tr);
        else if (f === "qty" || f === "rate") lineFromQtyRate(tr);
        else if (f === "amount") lineFromAmount(tr);
        else if (f === "newqty") adjFromNew(tr);
        else if (f === "debit" && el.value) { var c = $('[data-f="credit"]', tr); if (c) c.value = ""; }
        else if (f === "credit" && el.value) { var d = $('[data-f="debit"]', tr); if (d) d.value = ""; }
        maybeGrow(tr);
      }
      if (el.matches('[data-f="apply"], [data-f="credit"]')) {
        var cb = $('input[type=checkbox]', el.closest("tr")); if (cb) cb.checked = !!el.value;
        applyChanged();
      }
      if (el.matches('[data-role="amount-received"]')) { el.dataset.userTyped = "1"; distribute(); }
      recalc();
    });

    function maybeGrow(tr) {
      // Typing in the last line adds a fresh one below, as in QBO.
      var tbody = tr.parentNode;
      if (tr !== tbody.lastElementChild) return;
      var tbl = tbody.closest("table");
      var tpl = { "cat-lines": "tpl-cat", "je-lines": "tpl-je", "dep-lines": "tpl-dep" }[tbl.id] ||
        (tbl.dataset.purchase ? "tpl-pitem" : "tpl-item");
      if (tr.dataset.kind === "description") return;
      addLine(tpl, tbl.id);
    }
    function onItem(tr, id) {
      var it = items[id];
      if (!it) return;
      var purchase = !salesDoc;
      var desc = $('[data-f="desc"]', tr), rate = $('[data-f="rate"]', tr), qty = $('[data-f="qty"]', tr);
      var tax = $('[data-f="taxable"]', tr), onhand = $('[data-f="onhand"]', tr);
      if (desc) desc.value = purchase ? it.pdesc : it.desc;
      if (onhand) { onhand.value = it.onhand || "0"; adjFromNew(tr); return; }
      var price = purchase ? it.cost : it.price;
      if (rate && price !== "") rate.value = trimNum(price);
      if (qty && !qty.value) qty.value = "1";
      if (tax) tax.checked = !!it.taxable;
      lineFromQtyRate(tr);
    }
    function trimNum(s) { var n = parseFloat(s); if (isNaN(n)) return s; return String(Math.round(n * 100000) / 100000); }
    function lineFromQtyRate(tr) {
      var q = parseNum(($('[data-f="qty"]', tr) || {}).value), r = parseNum(($('[data-f="rate"]', tr) || {}).value);
      var amt = $('[data-f="amount"]', tr);
      if (!amt || isNaN(q) || isNaN(r)) return;
      amt.value = plain(roundHalfUp(q * r * 100));
    }
    function lineFromAmount(tr) {
      var q = parseNum(($('[data-f="qty"]', tr) || {}).value), rate = $('[data-f="rate"]', tr);
      var a = parseCents(($('[data-f="amount"]', tr) || {}).value);
      if (rate && !isNaN(q) && q) rate.value = String(Math.round(a / q * 1000) / 100000);
    }
    function adjFromNew(tr) {
      var onhand = parseNum(($('[data-f="onhand"]', tr) || {}).value), nq = parseNum(($('[data-f="newqty"]', tr) || {}).value);
      var ch = $('[data-f="qty"]', tr);
      if (ch && !isNaN(onhand) && !isNaN(nq)) ch.value = String(Math.round((nq - onhand) * 10000) / 10000);
    }
    function adjFromChange(tr) {
      var onhand = parseNum(($('[data-f="onhand"]', tr) || {}).value), ch = parseNum(($('[data-f="qty"]', tr) || {}).value);
      var nq = $('[data-f="newqty"]', tr);
      if (nq && !isNaN(onhand) && !isNaN(ch)) nq.value = String(Math.round((onhand + ch) * 10000) / 10000);
    }

    // ---- totals ----
    function recalc() {
      var big = $("#big-amount");
      if (type === "journal_entry") {
        var dr = 0, cr = 0;
        $$("#je-lines tbody tr.line", form).forEach(function (tr) {
          dr += parseCents(($('[data-f="debit"]', tr) || {}).value);
          cr += parseCents(($('[data-f="credit"]', tr) || {}).value);
        });
        setText("#je-debits", fmt(dr)); setText("#je-credits", fmt(cr));
        var diff = $("#je-diff");
        if (diff) { diff.textContent = dr === cr ? "" : "Out of balance by " + fmt(Math.abs(dr - cr)); diff.className = dr === cr ? "small" : "small neg"; }
        if (big) big.textContent = fmt(dr);
        return;
      }
      if (["payment", "bill_payment", "customer_refund", "credit_memo", "vendor_credit"].indexOf(type) >= 0) applyTotals();
      if (["transfer", "cc_payment", "sales_tax_payment", "sales_tax_adjustment"].indexOf(type) >= 0) {
        var a = $('[data-role="simple-amount"]', form);
        if (big && a) big.textContent = fmt(parseCents(a.value));
        return;
      }
      if (type === "payment" || type === "bill_payment" || type === "customer_refund") {
        var r = $('[data-role="amount-received"]', form);
        if (big && r) big.textContent = fmt(parseCents(r.value));
        return;
      }
      if (type === "inventory_adjustment") return;
      var subtotal = 0, taxable = 0;
      $$("table.lines tbody tr.line", form).forEach(function (tr) {
        if (tr.dataset.kind === "description") return;
        var amt = parseCents(($('[data-f="amount"]', tr) || {}).value);
        subtotal += amt;
        var tx = $('[data-f="taxable"]', tr);
        if (tx && tx.checked) taxable += amt;
      });
      if (type === "deposit") {
        $$('input[name="deposit_ids"]:checked', form).forEach(function (c) { subtotal += parseCents(c.dataset.amount); });
      }
      var total = subtotal;
      if ($("#tot-taxable")) {
        var discount = 0, dtype = $('[data-role="discount-type"]', form), dval = $('[data-role="discount-value"]', form);
        if (dtype && dval && dval.value) {
          if (dtype.value === "percent") discount = roundHalfUp(subtotal * parseNum(dval.value) / 100);
          else discount = parseCents(dval.value);
          if (subtotal >= 0) discount = Math.max(0, Math.min(discount, subtotal));
        }
        var before = $('[data-role="discount-before"]', form);
        var base = taxable;
        if (discount && (!before || before.checked) && subtotal) base = taxable - roundHalfUp(discount * taxable / subtotal);
        var shipEl = $('[data-role="shipping"]', form), ship = shipEl ? parseCents(shipEl.value) : 0;
        if (ship && form.dataset.shippingTaxable === "1") base += ship;
        if (!customerTaxable) base = 0;
        var rateSel = $('[data-role="tax-rate"]', form), override = $('[data-role="tax-override"]', form);
        var taxAmt = $('[data-role="tax-amount"]', form), tax = 0;
        if (override && override.checked) tax = parseCents(taxAmt.value);
        else if (rateSel && rateSel.value) {
          var opt = rateSel.options[rateSel.selectedIndex];
          var comps = (opt.dataset.components || opt.dataset.rate || "0").split(",");
          comps.forEach(function (p) { tax += roundHalfUp(base * parseFloat(p) / 100); });
          if (taxAmt) taxAmt.value = plain(tax);
        } else if (taxAmt) taxAmt.value = "0.00";
        setText("#tot-discount", fmt(-discount));
        setText("#tot-taxable", fmt(base));
        total = subtotal - discount + tax + ship;
        var exempt = $("#exempt-note"); if (exempt) exempt.classList.toggle("hidden", customerTaxable);
      }
      setText("#tot-subtotal", fmt(subtotal));
      setText("#tot-total", fmt(total));
      var paid = parseInt(form.dataset.paid || "0", 10);
      setText("#tot-balance", fmt(total - paid));
      if (big) big.textContent = fmt(type === "invoice" ? total - paid : total);
    }
    function setText(sel, text) { var el = $(sel, form); if (el) el.textContent = text; }

    // ---- apply table (payments) ----
    function targetTotal() { return $$('#apply-targets [data-f="apply"]', form).reduce(function (s, i) { return s + parseCents(i.value); }, 0); }
    function creditTotal() { return $$('#apply-credits [data-f="credit"]', form).reduce(function (s, i) { return s + parseCents(i.value); }, 0); }
    function applyTotals() {
      var t = targetTotal(), c = creditTotal();
      setText("#amt-apply", fmt(t)); setText("#amt-credit", fmt(c));
      var received = $('[data-role="amount-received"]', form);
      if (received && $("#amt-unapplied")) setText("#amt-unapplied", fmt(Math.max(0, parseCents(received.value) + c - t)));
    }
    function applyChanged() {
      var received = $('[data-role="amount-received"]', form);
      var mode = ($("#apply-section") || {}).dataset ? $("#apply-section").dataset.mode : "";
      if (received && (mode === "payment" || mode === "refund")) {
        received.value = plain(Math.max(0, targetTotal() - creditTotal()));
        received.dataset.userTyped = "0";
      }
      applyTotals(); recalc();
    }
    function distribute() {
      // Amount received typed in: fill invoices oldest first.
      var received = $('[data-role="amount-received"]', form);
      if (!received) return;
      var left = parseCents(received.value) + creditTotal();
      $$("#apply-targets tbody tr", form).forEach(function (tr) {
        var input = $('[data-f="apply"]', tr), open = $("[data-open]", tr), cb = $('[data-act="apply-one"]', tr);
        if (!input || !open) return;
        var use = Math.max(0, Math.min(parseCents(open.dataset.open), left));
        input.value = use ? plain(use) : "";
        if (cb) cb.checked = use > 0;
        left -= use;
      });
      applyTotals();
    }
    function rebuildApply(data) {
      var sec = $("#apply-section");
      if (!sec || !data.targets) return;
      var tb = $("#apply-targets tbody", form);
      tb.innerHTML = "";
      if (!data.targets.length) tb.innerHTML = '<tr class="empty-row"><td colspan="6" class="muted">Nothing open.</td></tr>';
      data.targets.forEach(function (r, i) {
        tb.insertAdjacentHTML("beforeend", '<tr><td class="sel"><input type="checkbox" data-act="apply-one"' + (r.applied ? " checked" : "") + '></td>' +
          '<td><input type="hidden" name="ap-' + i + '-txn_id" value="' + r.id + '">' + esc(r.label) + ' <span class="faint">(' + r.date + ')</span></td>' +
          '<td>' + r.due + '</td><td class="num">' + fmt(parseCents(r.original)) + '</td><td class="num" data-open="' + r.open + '">' + fmt(parseCents(r.open)) + '</td>' +
          '<td class="num"><input class="num" name="ap-' + i + '-amount" data-f="apply" value="' + (r.applied || "") + '" inputmode="decimal"></td></tr>');
      });
      var cb = $("#apply-credits tbody", form);
      if (cb) {
        cb.innerHTML = "";
        if (!data.credits.length) cb.innerHTML = '<tr class="empty-row"><td colspan="6" class="muted">No credits available.</td></tr>';
        data.credits.forEach(function (r, i) {
          cb.insertAdjacentHTML("beforeend", '<tr><td class="sel"><input type="checkbox" data-act="credit-one"' + (r.applied ? " checked" : "") + '></td>' +
            '<td><input type="hidden" name="cr-' + i + '-txn_id" value="' + r.id + '">' + esc(r.label) + ' <span class="faint">(' + r.date + ')</span></td><td></td>' +
            '<td class="num">' + fmt(parseCents(r.original)) + '</td><td class="num" data-open="' + r.open + '">' + fmt(parseCents(r.open)) + '</td>' +
            '<td class="num"><input class="num" name="cr-' + i + '-amount" data-f="credit" value="' + (r.applied || "") + '" inputmode="decimal"></td></tr>');
        });
      }
      var received = $('[data-role="amount-received"]', form);
      if (received && received.value && parseCents(received.value)) distribute();
      applyTotals();
    }
    function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

    // ---- customer / vendor defaults ----
    function onCustomer(id) {
      if (!id) return;
      var url = form.dataset.uiCustomer.replace(/\/0$/, "/" + id) + "?type=" + type + "&txn_id=" + (form.dataset.txnId || "");
      fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
        var email = $('[name="email_to"]', form); if (email && !email.dataset.touched) email.value = d.email || "";
        var bill = $('[name="billing_address"]', form); if (bill) bill.value = d.billing_address || "";
        var ship = $('[name="shipping_address"]', form); if (ship) ship.value = d.shipping_address || "";
        var tsel = $('[data-role="terms"]', form); if (tsel && d.terms_id) { tsel.value = d.terms_id; updateDue(); }
        var rate = $('[data-role="tax-rate"]', form); if (rate && d.tax_rate_id) rate.value = d.tax_rate_id;
        var pm = $('[name="payment_method_id"]', form); if (pm && d.payment_method_id && !pm.value) pm.value = d.payment_method_id;
        customerTaxable = d.taxable !== false;
        var note = $("#customer-note");
        if (note) {
          var msg = [];
          if (!customerTaxable) msg.push("Tax exempt" + (d.exempt_reason ? " (" + d.exempt_reason + ")" : ""));
          if (d.notes) msg.push(d.notes);
          note.textContent = msg.join(" · "); note.classList.toggle("hidden", !msg.length);
        }
        rebuildApply(d);
        if (d.billable && d.billable.length && type === "invoice") showBillable(d.billable);
        recalc();
      });
    }
    function showBillable(list) {
      var slot = $("#billable-slot");
      if (!slot || $("#billable-panel")) return;
      var rows = list.map(function (b) {
        return '<tr data-billable="' + esc(JSON.stringify(b)) + '"><td>' + esc(b.date) + '</td><td>' + esc(b.label) + '</td><td>' + esc(b.description) +
          '</td><td class="num">' + fmt(parseCents(b.amount)) + '</td><td class="actions"><button type="button" class="small" data-act="add-billable">Add</button></td></tr>';
      }).join("");
      slot.innerHTML = '<details class="card" id="billable-panel" open style="margin-bottom:1rem"><summary class="card-head"><h3>Add billable charges (' + list.length +
        ')</h3></summary><table class="data compact"><tbody>' + rows + '</tbody></table></details>';
    }
    function onVendor(id, payeeOnly) {
      if (!id) return;
      var url = form.dataset.uiVendor.replace(/\/0$/, "/" + id) + "?type=" + type + "&txn_id=" + (form.dataset.txnId || "");
      fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
        var bill = $('[name="billing_address"]', form); if (bill && !bill.value) bill.value = d.address || "";
        var tsel = $('[data-role="terms"]', form); if (tsel && d.terms_id) { tsel.value = d.terms_id; updateDue(); }
        var email = $('[name="email_to"]', form); if (email && type === "purchase_order") email.value = d.email || "";
        if (d.default_account_id) {
          var first = $('#cat-lines [data-f="account"]', form);
          if (first && !first.value) first.value = d.default_account_id;
        }
        var poNote = $("#po-note");
        if (poNote && d.open_pos && d.open_pos.length) {
          poNote.innerHTML = "Open purchase orders: " + d.open_pos.map(function (p) {
            return '<a href="?from_po=' + p.id + '">#' + esc(p.number || p.id) + " (" + esc(p.total) + ")</a>";
          }).join(", ");
          poNote.classList.remove("hidden");
        }
        if (!payeeOnly) rebuildApply(d);
        recalc();
      });
    }
    function nextCheck(accountId) {
      if (!accountId || form.dataset.txnId) return;
      fetch(form.dataset.uiCheck.replace(/\/0$/, "/" + accountId), { credentials: "same-origin" })
        .then(function (r) { return r.json(); }).then(function (d) { var n = $('[name="number"]', form); if (n && d.number) n.value = d.number; });
    }
    function updateDue() {
      var tsel = $('[data-role="terms"]', form), dateEl = $('[data-role="date"]', form), due = $('[name="due_date"]', form);
      if (!tsel || !dateEl || !due || !dateEl.value) return;
      var t = terms[tsel.value];
      var d = new Date(dateEl.value + "T00:00:00");
      if (!t) { due.value = dateEl.value; return; }
      if (t.kind === "day_of_month" && t.dom) {
        var cand = new Date(d.getFullYear(), d.getMonth(), Math.min(t.dom, 28));
        if (cand < d || (t.cutoff && (cand - d) / 864e5 < t.cutoff)) cand = new Date(d.getFullYear(), d.getMonth() + 1, Math.min(t.dom, 28));
        due.value = iso(cand);
      } else {
        d.setDate(d.getDate() + (t.days || 0));
        due.value = iso(d);
      }
    }
    function iso(d) { return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }
    function checkClosing() {
      var box = $("#closing-box");
      if (!box || !window.BOOKS_CLOSING_DATE) return;
      var dateEl = $('[name="date"]', form);
      box.classList.toggle("hidden", !(dateEl && dateEl.value && dateEl.value <= window.BOOKS_CLOSING_DATE));
    }
    var emailEl = $('[name="email_to"]', form);
    if (emailEl) emailEl.addEventListener("input", function () { emailEl.dataset.touched = "1"; });

    // ---- drag to reorder ----
    var dragRow = null;
    form.addEventListener("mousedown", function (e) {
      var h = e.target.closest("td.handle");
      $$("tr.line", form).forEach(function (tr) { tr.draggable = false; });
      if (h) h.parentNode.draggable = true;
    });
    form.addEventListener("dragstart", function (e) { dragRow = e.target.closest("tr.line"); });
    form.addEventListener("dragover", function (e) {
      var over = e.target.closest("tr.line");
      if (!dragRow || !over || over === dragRow || over.parentNode !== dragRow.parentNode) return;
      e.preventDefault();
      var rect = over.getBoundingClientRect();
      over.parentNode.insertBefore(dragRow, (e.clientY - rect.top) > rect.height / 2 ? over.nextSibling : over);
    });
    form.addEventListener("dragend", function () { dragRow = null; renumber(); });

    form.addEventListener("submit", function () { renumber(); });

    // ---- initial state ----
    $$('tr.line [data-f="item"]', form).forEach(function (sel) {
      var tr = sel.closest("tr"), onhand = $('[data-f="onhand"]', tr);
      if (onhand && items[sel.value]) onhand.value = items[sel.value].onhand || "0";
    });
    var cust = $('[data-role="customer"]', form);
    if (cust && cust.value && !form.dataset.txnId && ["payment", "customer_refund"].indexOf(type) < 0) onCustomer(cust.value);
    renumber(); applyTotals(); recalc(); checkClosing();
    var dateField = $('[data-role="date"]', form);
    if (dateField && !form.dataset.txnId) updateDue();
  }

  // ---------- bank feed review ----------
  $$("[data-feed-row]").forEach(function (tr) {
    tr.addEventListener("click", function (e) {
      if (e.target.closest("a, button, input, select, textarea, label")) return;
      var detail = document.getElementById("detail-" + tr.dataset.feedRow);
      if (detail) detail.classList.toggle("hidden");
    });
  });
  $$("form[data-feed-form]").forEach(function (f) {
    var mode = $('[name="mode"]', f);
    function sync() {
      $$("[data-mode]", f).forEach(function (el) { el.classList.toggle("hidden", el.dataset.mode.split(" ").indexOf(mode.value) < 0); });
    }
    if (mode) { mode.addEventListener("change", sync); sync(); }
  });

  // ---------- reconcile ----------
  var rec = document.getElementById("reconcile-form");
  if (rec) {
    var ending = parseInt(rec.dataset.ending, 10), beginning = parseInt(rec.dataset.beginning, 10);
    function recalcRec() {
      var dep = 0, pay = 0;
      $$('input[name="cleared"]:checked', rec).forEach(function (c) {
        var a = parseInt(c.dataset.amount, 10);
        if (a >= 0) dep += a; else pay += -a;
      });
      var cleared = beginning + dep - pay;
      setT("#rec-deposits", fmt(dep)); setT("#rec-payments", fmt(pay)); setT("#rec-cleared", fmt(cleared));
      var diff = ending - cleared;
      setT("#rec-diff", fmt(diff));
      var el = $("#rec-diff"); if (el) el.className = diff === 0 ? "money-in" : "neg";
      var done = $("#rec-finish"); if (done) done.classList.toggle("primary", diff === 0);
    }
    function setT(sel, txt) { var el = $(sel, rec) || $(sel); if (el) el.textContent = txt; }
    rec.addEventListener("change", recalcRec);
    var all = $("[data-rec-all]", rec);
    if (all) all.addEventListener("change", function () {
      $$('input[name="cleared"]', rec).forEach(function (c) { if (!c.closest("tr").classList.contains("hidden")) c.checked = all.checked; });
      recalcRec();
    });
    $$("[data-rec-filter]", rec).forEach(function (b) {
      b.addEventListener("click", function (e) {
        e.preventDefault();
        var which = b.dataset.recFilter;
        $$("tr[data-sign]", rec).forEach(function (tr) {
          tr.classList.toggle("hidden", which !== "all" && tr.dataset.sign !== which);
        });
        $$("[data-rec-filter]", rec).forEach(function (x) { x.classList.toggle("active", x === b); });
      });
    });
    recalcRec();
  }

  // ---------- chart tooltips ----------
  var tip = null;
  function showTip(value, label, x, y) {
    if (!tip) { tip = document.createElement("div"); tip.className = "chart-tip"; document.body.appendChild(tip); }
    tip.textContent = "";
    var strong = document.createElement("strong"); strong.textContent = value;
    var span = document.createElement("span"); span.textContent = label;
    tip.appendChild(strong); tip.appendChild(span);
    tip.style.display = "block";
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.min(window.innerWidth - w - 8, x + 14), top = Math.max(8, y - h - 10);
    tip.style.left = left + "px"; tip.style.top = top + "px";
  }
  function hideTip() { if (tip) tip.style.display = "none"; }
  document.addEventListener("pointermove", function (e) {
    var el = e.target.closest && e.target.closest("[data-tip-value]");
    if (el) { showTip(el.dataset.tipValue, el.dataset.tipLabel, e.clientX, e.clientY); return; }
    var overlay = e.target.closest && e.target.closest(".line-chart .overlay");
    if (overlay) { lineHover(overlay.closest("svg"), e.clientX, e.clientY); return; }
    hideTip();
    $$(".line-chart .crosshair").forEach(function (c) { c.classList.add("hidden"); });
  });
  document.addEventListener("focusin", function (e) {
    var el = e.target.closest && e.target.closest("[data-tip-value]");
    if (el) { var r = el.getBoundingClientRect(); showTip(el.dataset.tipValue, el.dataset.tipLabel, r.left + r.width / 2, r.top); }
  });
  document.addEventListener("focusout", hideTip);
  function lineHover(svg, cx, cy) {
    var pts = JSON.parse(svg.dataset.points || "[]");
    if (!pts.length) return;
    var box = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal;
    var sx = vb.width / box.width, x = (cx - box.left) * sx;
    var best = pts[0];
    pts.forEach(function (p) { if (Math.abs(p.x - x) < Math.abs(best.x - x)) best = p; });
    var ch = $(".crosshair", svg);
    ch.setAttribute("x1", best.x); ch.setAttribute("x2", best.x); ch.classList.remove("hidden");
    showTip(best.v, best.l, box.left + best.x / sx, box.top + best.y / sx);
  }
})();
