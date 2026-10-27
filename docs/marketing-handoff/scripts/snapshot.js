/* PPS Marketing Hub: read-only demo copy.
   Every page here is a saved copy of the running app in demo mode. This script
   points the app's own links at those copies and answers anything that would
   change data with a short note. Rule previews (dry runs) are read-only in the
   real app too, so their answers were saved with the copy. */
(function () {
  "use strict";

  var PAGES = /*PAGES*/{};
  var DRY_RUNS = /*DRY_RUNS*/{};
  var DEFAULTS = { range: "30d", tab: "queue" };
  var READ_ONLY = "This demo copy is read-only. Saving, pausing, budget changes and publishing work in the running hub.";
  var MESSAGES = {
    "/api/studio/generate": "Writing copy with Claude needs the running hub and an Anthropic API key.",
    "/api/insights": "Claude's review needs the running hub and an Anthropic API key.",
    "/api/automation/run": "Rules only change campaigns in the running hub. Preview (dry run) works here.",
  };

  document.documentElement.lang = "en";

  function note(message) {
    if (window.MK && window.MK.toast) window.MK.toast(message, "error");
  }

  // The same rules the copy was built with: drop "refresh" and default values, sort the rest.
  function normalize(href) {
    var parts = href.split("#")[0].split("?");
    var kept = [];
    new URLSearchParams(parts[1] || "").forEach(function (v, k) {
      if (k !== "refresh" && DEFAULTS[k] !== v) kept.push([k, v]);
    });
    kept.sort(function (a, b) {
      return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0;
    });
    var query = kept.map(function (p) { return encodeURIComponent(p[0]) + "=" + encodeURIComponent(p[1]); }).join("&");
    return parts[0] + (query ? "?" + query : "");
  }

  function isAppPath(href) {
    return href.charAt(0) === "/" && href.charAt(1) !== "/";
  }

  // Links the app builds with its own paths (some are made by script after load).
  document.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest("a") : null;
    if (!a) return;
    var raw = a.getAttribute("data-off") || a.getAttribute("href") || "";
    if (!isAppPath(raw)) return;
    var file = PAGES[normalize(raw)];
    if (file) {
      a.setAttribute("href", file);
      a.removeAttribute("data-off");
      return;
    }
    e.preventDefault();
    note(raw.indexOf("/oauth/") === 0 ? "Connecting an account happens in the running hub."
      : raw.indexOf("/export.csv") === 0 ? "CSV export works in the running hub."
      : "That page isn't part of this demo copy.");
  }, true);

  // Forms would post to the app; stop them before the app's own handlers run.
  document.addEventListener("submit", function (e) {
    e.preventDefault();
    e.stopImmediatePropagation();
    var form = e.target;
    if ((form.getAttribute("method") || "get").toLowerCase() !== "get") note(READ_ONLY);
    else if (form.querySelector("[name=month]")) note("Other months need the running hub.");
    else note("Custom date ranges need the running hub. The preset ranges work here.");
  }, true);

  // The app asks before risky actions; here every one ends in the read-only note anyway.
  window.confirm = function () { return true; };

  var realFetch = window.fetch ? window.fetch.bind(window) : null;

  function reply(status, data) {
    return Promise.resolve(new Response(JSON.stringify(data), {
      status: status,
      headers: { "Content-Type": "application/json" },
    }));
  }

  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    if (url.indexOf(location.origin) === 0) url = url.slice(location.origin.length);
    if (!isAppPath(url)) return realFetch(input, init);
    var path = url.split("?")[0];
    var body = {};
    try { body = JSON.parse((init && init.body) || "{}"); } catch (err) { /* not JSON */ }
    if (path === "/api/automation/run" && body.dry_run) {
      var run = DRY_RUNS[body.rule_id ? String(body.rule_id) : "all"];
      if (run) return reply(200, run);
    }
    return reply(403, { ok: false, error: MESSAGES[path] || READ_ONLY });
  };
})();
