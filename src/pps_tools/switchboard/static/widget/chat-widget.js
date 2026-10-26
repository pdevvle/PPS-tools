/* Switchboard website chat widget.
 * Served as /widget/<public key>.js with its configuration filled in; embed with
 *   <script src="https://your-switchboard/widget/<key>.js" async></script>
 * Everything renders inside a Shadow DOM so the host site's CSS can't leak in or out.
 */
(function () {
  'use strict';

  var CONFIG = __SB_CONFIG__;
  if (window.__switchboardChat) return;
  window.__switchboardChat = true;

  var script = document.currentScript;
  var BASE = '';
  try { BASE = new URL(script && script.src ? script.src : location.href).origin; } catch (e) { BASE = ''; }
  var API = BASE + '/public/chat/' + encodeURIComponent(CONFIG.key);
  var STORE_KEY = 'sb-chat:' + CONFIG.key;
  var COLOR = /^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(CONFIG.color || '') ? CONFIG.color : '#3b5bdb';

  var state = {
    open: false,
    token: null,
    name: '',
    email: '',
    messages: [],
    lastId: 0,
    unread: 0,
    sending: false,
    typing: false,
    online: !!CONFIG.online,
    timer: null,
  };

  // -- storage -----------------------------------------------------------------

  function load() {
    try {
      var saved = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
      if (saved && saved.token) {
        state.token = saved.token;
        state.name = saved.name || '';
        state.email = saved.email || '';
        state.lastSeenId = saved.lastSeenId || 0;
      }
    } catch (e) { /* storage blocked */ }
  }

  function save() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        token: state.token, name: state.name, email: state.email, lastSeenId: state.lastSeenId || 0,
      }));
    } catch (e) { /* storage blocked */ }
  }

  function forget() {
    state.token = null;
    state.messages = [];
    state.lastId = 0;
    try { localStorage.removeItem(STORE_KEY); } catch (e) { /* ignore */ }
  }

  // -- network -----------------------------------------------------------------

  function request(method, path, body) {
    var opts = { method: method, headers: {} };
    if (body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(API + path, opts).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) {
          var err = new Error((data.error && data.error.message) || 'Something went wrong');
          err.code = data.error && data.error.code;
          err.status = res.status;
          throw err;
        }
        return data;
      });
    });
  }

  // -- DOM ---------------------------------------------------------------------

  var host = document.createElement('div');
  host.setAttribute('data-switchboard-chat', '');
  var root = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === 'text') node.textContent = attrs[k];
        else if (k === 'class') node.className = attrs[k];
        else if (k.slice(0, 2) === 'on') node.addEventListener(k.slice(2), attrs[k]);
        else node.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(function (c) { if (c) node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return node;
  }

  function svg(path, size) {
    var ns = 'http://www.w3.org/2000/svg';
    var s = document.createElementNS(ns, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('width', size || 24);
    s.setAttribute('height', size || 24);
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '2');
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    s.setAttribute('aria-hidden', 'true');
    path.split('|').forEach(function (d) {
      var p = document.createElementNS(ns, 'path');
      p.setAttribute('d', d);
      s.appendChild(p);
    });
    return s;
  }

  var ICON_CHAT = 'M7.9 20A9 9 0 1 0 4 16.1L2 22Z';
  var ICON_X = 'M18 6 6 18|m6 6 12 12';
  var ICON_SEND = 'M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z|m21.854 2.147-10.94 10.939';

  var style = el('style', { text: [
    ':host{all:initial}',
    '[hidden]{display:none!important}',
    '*{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}',
    '.launcher{position:fixed;right:20px;bottom:20px;z-index:2147483000;width:58px;height:58px;border-radius:50%;border:0;cursor:pointer;',
    'background:' + COLOR + ';color:#fff;box-shadow:0 6px 24px rgba(0,0,0,.22);display:flex;align-items:center;justify-content:center;transition:transform .15s}',
    '.launcher:hover{transform:scale(1.06)}',
    '.launcher:focus-visible,.panel button:focus-visible,.panel textarea:focus-visible,.panel input:focus-visible{outline:3px solid rgba(59,91,219,.45);outline-offset:2px}',
    '.badge{position:absolute;top:-2px;right:-2px;min-width:20px;height:20px;padding:0 5px;border-radius:10px;background:#e03131;color:#fff;font-size:11px;font-weight:700;line-height:20px;text-align:center;box-shadow:0 0 0 2px #fff}',
    '.panel{position:fixed;right:20px;bottom:92px;z-index:2147483000;width:370px;max-width:calc(100vw - 32px);height:560px;max-height:calc(100vh - 120px);',
    'background:#fff;color:#1d2433;border-radius:16px;box-shadow:0 12px 48px rgba(0,0,0,.25);display:flex;flex-direction:column;overflow:hidden;',
    'opacity:0;transform:translateY(12px) scale(.98);pointer-events:none;transition:opacity .18s,transform .18s}',
    '.panel.open{opacity:1;transform:none;pointer-events:auto}',
    '.head{background:' + COLOR + ';color:#fff;padding:16px 16px 14px;display:flex;align-items:flex-start;gap:10px}',
    '.head-text{flex:1;min-width:0}',
    '.title{font-size:16px;font-weight:700;margin:0 0 3px}',
    '.status{font-size:12.5px;opacity:.9;display:flex;align-items:center;gap:6px}',
    '.status:before{content:"";width:8px;height:8px;border-radius:50%;background:#9be7a8}',
    '.status.away:before{background:#ffd43b}',
    '.agents{display:flex;margin-top:8px}',
    '.agent{width:26px;height:26px;border-radius:50%;color:#fff;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;border:2px solid rgba(255,255,255,.9);margin-right:-6px}',
    '.close{background:rgba(255,255,255,.18);border:0;color:#fff;width:30px;height:30px;border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex:none}',
    '.close:hover{background:rgba(255,255,255,.3)}',
    '.body{flex:1;overflow-y:auto;padding:16px;background:#f6f7f9;display:flex;flex-direction:column;gap:8px}',
    '.greeting{background:#fff;border:1px solid #e3e6ec;border-radius:12px;padding:10px 12px;font-size:14px;line-height:1.45;align-self:flex-start;max-width:88%}',
    '.msg{max-width:82%;padding:8px 12px;border-radius:14px;font-size:14px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}',
    '.msg a{color:inherit}',
    '.in{align-self:flex-end;background:' + COLOR + ';color:#fff;border-bottom-right-radius:4px}',
    '.out{align-self:flex-start;background:#fff;border:1px solid #e3e6ec;border-bottom-left-radius:4px}',
    '.who{font-size:11.5px;color:#7a8396;margin:4px 2px -4px;align-self:flex-start}',
    '.file{display:block;font-size:13px;margin-top:4px}',
    '.file img{max-width:100%;border-radius:8px;display:block}',
    '.typing{align-self:flex-start;font-size:12.5px;color:#7a8396;padding:2px 4px}',
    '.composer{display:flex;gap:8px;align-items:flex-end;padding:10px;border-top:1px solid #e3e6ec;background:#fff}',
    'textarea,input{width:100%;border:1px solid #cdd2db;border-radius:10px;padding:9px 11px;font-size:14px;color:#1d2433;background:#fff;resize:none}',
    'textarea{max-height:120px;min-height:40px}',
    '.send{flex:none;width:40px;height:40px;border-radius:10px;border:0;background:' + COLOR + ';color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center}',
    '.send:disabled{opacity:.5;cursor:default}',
    '.intro{padding:14px 16px;border-top:1px solid #e3e6ec;background:#fff;display:flex;flex-direction:column;gap:8px}',
    '.intro p{margin:0;font-size:13px;color:#475063}',
    '.primary{border:0;border-radius:10px;padding:10px 14px;font-size:14px;font-weight:600;background:' + COLOR + ';color:#fff;cursor:pointer}',
    '.error{color:#c41d1d;font-size:12.5px;min-height:0}',
    '.foot{text-align:center;font-size:11px;color:#9aa2b4;padding:6px 0 8px;background:#fff}',
    '@media (max-width:480px){.panel{right:0;bottom:0;width:100vw;max-width:100vw;height:100%;max-height:100%;border-radius:0}.launcher{right:16px;bottom:16px}}',
  ].join('') });

  var badge = el('span', { class: 'badge', hidden: '' });
  var launcher = el('button', { class: 'launcher', type: 'button', 'aria-label': 'Chat with ' + (CONFIG.org_name || 'us'), onclick: toggle }, [svg(ICON_CHAT, 26), badge]);

  var statusEl = el('div', { class: 'status' });
  var agentsEl = el('div', { class: 'agents' });
  var head = el('div', { class: 'head' }, [
    el('div', { class: 'head-text' }, [el('p', { class: 'title', text: CONFIG.org_name || CONFIG.name || 'Chat' }), statusEl, agentsEl]),
    el('button', { class: 'close', type: 'button', 'aria-label': 'Close chat', onclick: close }, [svg(ICON_X, 18)]),
  ]);
  var greetingEl = el('div', { class: 'greeting' });
  var list = el('div', { role: 'log', 'aria-live': 'polite' });
  list.style.display = 'contents';
  var typingEl = el('div', { class: 'typing', hidden: '', text: 'Typing…' });
  var bodyEl = el('div', { class: 'body' }, [greetingEl, list, typingEl]);

  var introName = el('input', { type: 'text', placeholder: 'Your name', autocomplete: 'name', 'aria-label': 'Your name' });
  var introEmail = el('input', { type: 'email', placeholder: CONFIG.require_email ? 'Email' : 'Email (so we can reply if you leave)', autocomplete: 'email', 'aria-label': 'Email' });
  var introMsg = el('textarea', { rows: '3', placeholder: 'How can we help?', 'aria-label': 'Message' });
  var introError = el('div', { class: 'error' });
  var introBtn = el('button', { class: 'primary', type: 'submit', text: 'Start chat' });
  var intro = el('form', { class: 'intro', onsubmit: startChat }, [introName, introEmail, introMsg, introError, introBtn]);

  var input = el('textarea', { rows: '1', placeholder: 'Write a message…', 'aria-label': 'Message' });
  var sendBtn = el('button', { class: 'send', type: 'submit', 'aria-label': 'Send' }, [svg(ICON_SEND, 18)]);
  var composer = el('form', { class: 'composer', onsubmit: sendMessage }, [input, sendBtn]);
  var composerError = el('div', { class: 'error' });
  composerError.style.padding = '0 12px';
  var foot = el('div', { class: 'foot', text: 'Powered by Switchboard' });

  var panel = el('div', { class: 'panel', role: 'dialog', 'aria-label': 'Chat with ' + (CONFIG.org_name || 'us') }, [head, bodyEl, intro, composerError, composer, foot]);

  root.appendChild(style);
  root.appendChild(launcher);
  root.appendChild(panel);

  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendMessage(e); }
  });
  input.addEventListener('input', autosize);
  panel.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });

  function autosize() {
    input.style.height = 'auto';
    input.style.height = Math.min(120, input.scrollHeight) + 'px';
  }

  // -- rendering ---------------------------------------------------------------

  function renderHeader() {
    statusEl.textContent = state.online ? "We're online" : 'Away — we\'ll reply soon';
    statusEl.className = 'status' + (state.online ? '' : ' away');
    agentsEl.textContent = '';
    (CONFIG.agents || []).forEach(function (a) {
      agentsEl.appendChild(el('span', { class: 'agent', title: a.name, text: a.initials, style: 'background:' + (a.color || '#555') }));
    });
    greetingEl.textContent = state.online || !CONFIG.offline_message ? (CONFIG.greeting || 'Hi! How can we help?') : CONFIG.offline_message;
  }

  function linkify(parent, text) {
    var re = /(https?:\/\/[^\s<]+[^\s<.,;:!?)\]])/g;
    var last = 0;
    var m;
    while ((m = re.exec(text))) {
      if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
      parent.appendChild(el('a', { href: m[1], target: '_blank', rel: 'noopener noreferrer', text: m[1] }));
      last = m.index + m[1].length;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  }

  function renderMessage(m) {
    var frag = document.createDocumentFragment();
    var prev = state.messages[state.messages.indexOf(m) - 1];
    if (m.direction === 'out' && m.author && (!prev || prev.direction !== 'out' || (prev.author && prev.author.name) !== m.author.name)) {
      frag.appendChild(el('div', { class: 'who', text: m.author.name }));
    }
    var bubble = el('div', { class: 'msg ' + (m.direction === 'in' ? 'in' : 'out') });
    linkify(bubble, m.text || '');
    (m.attachments || []).forEach(function (a) {
      var link = el('a', { class: 'file', href: a.url, target: '_blank', rel: 'noopener noreferrer' });
      if (a.is_image) link.appendChild(el('img', { src: a.url, alt: a.filename }));
      else link.textContent = '📎 ' + a.filename;
      bubble.appendChild(link);
    });
    frag.appendChild(bubble);
    return frag;
  }

  function renderAll() {
    list.textContent = '';
    state.messages.forEach(function (m) { list.appendChild(renderMessage(m)); });
    typingEl.hidden = !state.typing;
    var started = !!state.token && state.messages.length > 0;
    intro.hidden = started;
    composer.hidden = !started;
    if (!started && state.name) introName.value = state.name;
    if (!started && state.email) introEmail.value = state.email;
    bodyEl.scrollTop = bodyEl.scrollHeight;
  }

  function renderBadge() {
    badge.hidden = !state.unread;
    badge.textContent = state.unread > 9 ? '9+' : String(state.unread || '');
  }

  // -- behaviour ---------------------------------------------------------------

  function open() {
    state.open = true;
    panel.classList.add('open');
    state.unread = 0;
    renderBadge();
    renderAll();
    poll();
    setTimeout(function () { (composer.hidden ? (state.name ? introMsg : introName) : input).focus(); }, 60);
  }

  function close() {
    state.open = false;
    panel.classList.remove('open');
    launcher.focus();
    schedule();
  }

  function toggle() { state.open ? close() : open(); }

  function addMessages(items) {
    var added = false;
    items.forEach(function (m) {
      if (state.messages.some(function (x) { return x.id === m.id; })) return;
      state.messages.push(m);
      state.lastId = Math.max(state.lastId, m.id);
      if (m.direction === 'out' && !state.open && m.id > (state.lastSeenId || 0)) state.unread += 1;
      added = true;
    });
    if (state.open) {
      state.lastSeenId = state.lastId;
      save();
    }
    return added;
  }

  function schedule() {
    clearTimeout(state.timer);
    if (!state.token) return;
    state.timer = setTimeout(poll, state.open ? 3000 : 15000);
  }

  function poll() {
    clearTimeout(state.timer);
    if (!state.token) return;
    request('GET', '/messages?token=' + encodeURIComponent(state.token) + '&after=' + state.lastId)
      .then(function (data) {
        var changed = addMessages(data.messages || []);
        if (typeof data.online === 'boolean' && data.online !== state.online) { state.online = data.online; renderHeader(); }
        if (state.typing !== !!data.agent_typing) { state.typing = !!data.agent_typing; changed = true; }
        if (changed) { renderAll(); renderBadge(); }
      })
      .catch(function (err) {
        if (err.code === 'unknown_visitor') { forget(); renderAll(); }
      })
      .then(schedule);
  }

  function startChat(e) {
    e.preventDefault();
    var text = introMsg.value.trim();
    var email = introEmail.value.trim();
    introError.textContent = '';
    if (!text) { introError.textContent = 'Type your question first.'; introMsg.focus(); return; }
    if (CONFIG.require_email && !email) { introError.textContent = 'Please add your email so we can reply.'; introEmail.focus(); return; }
    introBtn.disabled = true;
    state.name = introName.value.trim();
    state.email = email;
    request('POST', '/session', { name: state.name, email: email, page_url: location.href, token: state.token })
      .then(function (s) {
        state.token = s.token;
        save();
        return request('POST', '/messages', { token: state.token, body: text, page_url: location.href });
      })
      .then(function (res) {
        introMsg.value = '';
        addMessages([res.message]);
        renderAll();
        input.focus();
        schedule();
      })
      .catch(function (err) { introError.textContent = err.message; })
      .then(function () { introBtn.disabled = false; });
  }

  function sendMessage(e) {
    if (e) e.preventDefault();
    var text = input.value.trim();
    if (!text || state.sending) return;
    state.sending = true;
    sendBtn.disabled = true;
    composerError.textContent = '';
    request('POST', '/messages', { token: state.token, body: text, page_url: location.href })
      .then(function (res) {
        input.value = '';
        autosize();
        addMessages([res.message]);
        renderAll();
      })
      .catch(function (err) {
        if (err.code === 'unknown_visitor') { forget(); renderAll(); }
        composerError.textContent = err.message;
      })
      .then(function () {
        state.sending = false;
        sendBtn.disabled = false;
        input.focus();
        schedule();
      });
  }

  load();
  renderHeader();
  renderAll();
  renderBadge();
  function mount() {
    document.body.appendChild(host);
    if (state.token) poll();
  }
  if (document.body) mount();
  else document.addEventListener('DOMContentLoaded', mount);
})();
