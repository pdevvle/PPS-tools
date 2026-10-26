// Rich text editor on contenteditable, used by the email composer, comments, chat
// and notes.
//
//   <RichEditor value=${html} onChange=${setHtml} mentions placeholder="Write a comment…"
//     submitOnEnter onSubmit=${send} slash=${(q) => responsesMatching(q)} onFiles=${upload}
//     editorRef=${ref} />
//
// - mentions: typing @ suggests teammates; inserts <span data-mention="id">@Name</span>
// - slash(query): typing / at a word start suggests items {id, label, hint, html}; the
//   chosen item's html is inserted (canned responses)
// - value is applied when it changes from outside while the editor isn't focused;
//   use editorRef.current.setHTML() to force it (e.g. a teammate's live draft edit).

import { html, useEffect, useRef, useState } from '../lib/preact.js';
import { Icon } from './icons.js';
import { Avatar, cx } from './components.js';
import { promptDialog } from './overlay.js';
import { getState } from '../lib/store.js';
import { escapeHtml } from '../lib/format.js';
import { isMac } from '../lib/shortcuts.js';

const KEEP_TAGS = new Set(['B', 'STRONG', 'I', 'EM', 'U', 'S', 'STRIKE', 'DEL', 'A', 'P', 'DIV', 'BR', 'UL', 'OL', 'LI',
  'BLOCKQUOTE', 'CODE', 'PRE', 'H1', 'H2', 'H3', 'IMG']);
const DROP_TAGS = new Set(['SCRIPT', 'STYLE', 'META', 'LINK', 'TITLE', 'IFRAME', 'OBJECT', 'EMBED', 'SVG', 'HEAD']);

export function cleanPastedHTML(markup) {
  const doc = new DOMParser().parseFromString(markup, 'text/html');
  const walk = (node) => {
    for (const child of [...node.childNodes]) {
      if (child.nodeType === 8) { child.remove(); continue; }
      if (child.nodeType !== 1) continue;
      if (DROP_TAGS.has(child.tagName)) { child.remove(); continue; }
      walk(child);
      if (child.tagName === 'SPAN' && child.dataset.mention) continue;
      if (!KEEP_TAGS.has(child.tagName) || (child.tagName === 'IMG' && !/^(https?:|data:image\/)/.test(child.getAttribute('src') || ''))) {
        child.replaceWith(...child.childNodes);
        continue;
      }
      for (const attr of [...child.attributes]) {
        const keep = (child.tagName === 'A' && attr.name === 'href') || (child.tagName === 'IMG' && ['src', 'alt'].includes(attr.name));
        if (!keep) child.removeAttribute(attr.name);
      }
    }
  };
  walk(doc.body);
  return doc.body.innerHTML;
}

export function isEditorEmpty(markup) {
  if (!markup) return true;
  if (/<img/i.test(markup)) return false;
  const text = markup.replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').trim();
  return !text;
}

function mentionHTML(u) {
  return `<span class="mention" data-mention="${u.id}" contenteditable="false">@${escapeHtml(u.name)}</span>&nbsp;`;
}

const TOOLBARS = {
  full: ['bold', 'italic', 'underline', 'strike', '|', 'ul', 'ol', 'quote', 'code', '|', 'link', 'clear'],
  mini: ['bold', 'italic', 'link', 'ul'],
};

const BUTTONS = {
  bold: { icon: 'bold', label: 'Bold', cmd: () => document.execCommand('bold'), key: 'B' },
  italic: { icon: 'italic', label: 'Italic', cmd: () => document.execCommand('italic'), key: 'I' },
  underline: { icon: 'underline', label: 'Underline', cmd: () => document.execCommand('underline'), key: 'U' },
  strike: { icon: 'strikethrough', label: 'Strikethrough', cmd: () => document.execCommand('strikeThrough') },
  ul: { icon: 'list', label: 'Bulleted list', cmd: () => document.execCommand('insertUnorderedList') },
  ol: { icon: 'list-ordered', label: 'Numbered list', cmd: () => document.execCommand('insertOrderedList') },
  quote: { icon: 'text-quote', label: 'Quote', cmd: () => document.execCommand('formatBlock', false, 'blockquote') },
  code: {
    icon: 'code-xml',
    label: 'Code',
    cmd: () => {
      const sel = window.getSelection();
      const text = sel ? sel.toString() : '';
      document.execCommand('insertHTML', false, `<code>${escapeHtml(text || 'code')}</code>&nbsp;`);
    },
  },
  clear: { icon: 'remove-formatting', label: 'Clear formatting', cmd: () => { document.execCommand('removeFormat'); document.execCommand('formatBlock', false, 'div'); } },
};

function caretRect(wrapper) {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount) return null;
  const range = sel.getRangeAt(0).cloneRange();
  range.collapse(true);
  let rect = range.getClientRects()[0];
  if (!rect) {
    const span = document.createElement('span');
    span.textContent = '​';
    range.insertNode(span);
    rect = span.getBoundingClientRect();
    span.remove();
  }
  const base = wrapper.getBoundingClientRect();
  return { left: rect.left - base.left, top: rect.bottom - base.top, bottomSpace: window.innerHeight - rect.bottom };
}

// Text before the caret within the current text node, and the node itself.
function textBeforeCaret() {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount || !sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  const node = range.startContainer;
  if (node.nodeType !== 3) return null;
  return { node, offset: range.startOffset, text: node.textContent.slice(0, range.startOffset) };
}

export function RichEditor({
  value = '', onChange, placeholder, toolbar = 'full', onSubmit, submitOnEnter = false, onEscape,
  mentions = false, slash, onFiles, autofocus, class: cls, minHeight, maxHeight, editorRef, disabled,
  onFocus, onBlur, toolbarExtra, toolbarPosition = 'top', ariaLabel,
}) {
  const wrapRef = useRef(null);
  const elRef = useRef(null);
  const lastEmitted = useRef(value);
  const savedRange = useRef(null);
  const [empty, setEmpty] = useState(isEditorEmpty(value));
  const [popup, setPopup] = useState(null); // {kind, query, items, active, pos, start}
  const popupRef = useRef(popup);
  popupRef.current = popup;

  const emit = () => {
    const el = elRef.current;
    if (!el) return;
    const markup = el.innerHTML;
    lastEmitted.current = markup;
    setEmpty(isEditorEmpty(markup));
    onChange && onChange(markup);
  };

  useEffect(() => {
    const el = elRef.current;
    el.innerHTML = value || '';
    setEmpty(isEditorEmpty(value));
    if (autofocus) {
      el.focus();
      placeCaretAtEnd(el);
    }
  }, []);

  useEffect(() => {
    const el = elRef.current;
    if (!el || value === lastEmitted.current) return;
    if (document.activeElement === el) return;
    el.innerHTML = value || '';
    lastEmitted.current = value;
    setEmpty(isEditorEmpty(value));
  }, [value]);

  useEffect(() => {
    if (!editorRef) return;
    editorRef.current = {
      el: elRef.current,
      focus: () => { elRef.current.focus(); placeCaretAtEnd(elRef.current); },
      getHTML: () => elRef.current.innerHTML,
      setHTML: (markup) => { elRef.current.innerHTML = markup || ''; lastEmitted.current = markup || ''; setEmpty(isEditorEmpty(markup)); },
      clear: () => { elRef.current.innerHTML = ''; emit(); },
      insertHTML: (markup) => {
        const el = elRef.current;
        if (document.activeElement !== el) {
          el.focus();
          if (savedRange.current) restoreRange(savedRange.current);
          else placeCaretAtEnd(el);
        }
        document.execCommand('insertHTML', false, markup);
        emit();
      },
    };
  });

  const closePopup = () => setPopup(null);

  const updatePopup = async () => {
    const ctx = textBeforeCaret();
    if (!ctx) { closePopup(); return; }
    let m = mentions && ctx.text.match(/(?:^|[\s(])@([\w.'-]{0,30})$/);
    if (m) {
      const q = m[1].toLowerCase();
      const items = getState().users
        .filter((u) => u.is_active && (u.name.toLowerCase().includes(q) || u.email.toLowerCase().startsWith(q)))
        .slice(0, 8)
        .map((u) => ({ id: u.id, label: u.name, hint: u.title, user: u, html: mentionHTML(u) }));
      const pos = caretRect(wrapRef.current);
      setPopup(items.length ? { kind: 'mention', items, active: 0, pos, start: ctx.offset - m[1].length - 1, node: ctx.node } : null);
      return;
    }
    m = slash && ctx.text.match(/(?:^|\s)\/([\w-]{0,40})$/);
    if (m) {
      const start = ctx.offset - m[1].length - 1;
      const items = await slash(m[1]);
      const now = textBeforeCaret();
      if (!now || now.node !== ctx.node) return;
      const pos = caretRect(wrapRef.current);
      setPopup(items && items.length ? { kind: 'slash', items: items.slice(0, 8), active: 0, pos, start, node: ctx.node } : null);
      return;
    }
    closePopup();
  };

  const choose = (item) => {
    const p = popupRef.current;
    if (!p || !item) return;
    const sel = window.getSelection();
    const range = document.createRange();
    const ctx = textBeforeCaret();
    if (ctx && ctx.node === p.node) {
      range.setStart(p.node, Math.max(0, p.start));
      range.setEnd(p.node, ctx.offset);
      sel.removeAllRanges();
      sel.addRange(range);
      range.deleteContents();
    }
    document.execCommand('insertHTML', false, item.html);
    closePopup();
    emit();
  };

  const onKeyDown = (e) => {
    const p = popupRef.current;
    if (p) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setPopup({ ...p, active: (p.active + 1) % p.items.length }); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setPopup({ ...p, active: (p.active - 1 + p.items.length) % p.items.length }); return; }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); choose(p.items[p.active]); return; }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closePopup(); return; }
    }
    const mod = isMac ? e.metaKey : e.ctrlKey;
    if (e.key === 'Enter' && mod) {
      e.preventDefault();
      onSubmit && onSubmit();
      return;
    }
    if (e.key === 'Enter' && submitOnEnter && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      onSubmit && onSubmit();
      return;
    }
    if (e.key === 'Escape' && onEscape) {
      e.preventDefault();
      e.stopPropagation();
      onEscape();
      return;
    }
    if (mod && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      e.stopPropagation();
      addLink();
    }
    // Backspace right after a mention chip removes the whole chip.
    if (e.key === 'Backspace') {
      const sel = window.getSelection();
      if (sel && sel.isCollapsed && sel.rangeCount) {
        const { startContainer, startOffset } = sel.getRangeAt(0);
        const prev = startContainer.nodeType === 3
          ? (startOffset === 0 ? startContainer.previousSibling : null)
          : startContainer.childNodes[startOffset - 1];
        if (prev && prev.nodeType === 1 && prev.dataset && prev.dataset.mention) {
          e.preventDefault();
          prev.remove();
          emit();
        }
      }
    }
  };

  const onPaste = (e) => {
    const data = e.clipboardData;
    if (!data) return;
    const fileItems = [...(data.files || [])];
    if (fileItems.length && onFiles) {
      e.preventDefault();
      onFiles(fileItems);
      return;
    }
    const markup = data.getData('text/html');
    if (markup) {
      e.preventDefault();
      document.execCommand('insertHTML', false, cleanPastedHTML(markup));
      emit();
      return;
    }
    const text = data.getData('text/plain');
    if (text) {
      e.preventDefault();
      document.execCommand('insertText', false, text);
      emit();
    }
  };

  const onDrop = (e) => {
    const dropped = [...(e.dataTransfer?.files || [])];
    if (dropped.length && onFiles) {
      e.preventDefault();
      onFiles(dropped);
    }
  };

  const saveRange = () => {
    const sel = window.getSelection();
    if (sel && sel.rangeCount && elRef.current.contains(sel.anchorNode)) savedRange.current = sel.getRangeAt(0).cloneRange();
  };

  const addLink = async () => {
    saveRange();
    const range = savedRange.current;
    const selected = range ? range.toString() : '';
    const url = await promptDialog({ title: 'Add link', label: 'URL', value: 'https://', confirmLabel: 'Add link', inputType: 'url' });
    if (!url) return;
    elRef.current.focus();
    if (range) restoreRange(range);
    const href = /^(https?:|mailto:|tel:)/i.test(url) ? url : 'https://' + url;
    if (selected) document.execCommand('createLink', false, href);
    else document.execCommand('insertHTML', false, `<a href="${escapeHtml(href)}">${escapeHtml(url)}</a>&nbsp;`);
    emit();
  };

  const runButton = (name) => (e) => {
    e.preventDefault();
    if (name === 'link') { addLink(); return; }
    elRef.current.focus();
    BUTTONS[name].cmd();
    emit();
  };

  const tools = toolbar ? (Array.isArray(toolbar) ? toolbar : TOOLBARS[toolbar] || TOOLBARS.full) : [];
  const toolbarEl = tools.length || toolbarExtra ? html`<div class="editor-toolbar">
    ${tools.map((name, i) => (name === '|'
    ? html`<span key=${'s' + i} class="editor-sep"></span>`
    : html`<button key=${name} type="button" class="editor-tool" data-tip=${(name === 'link' ? 'Link' : BUTTONS[name].label) + (BUTTONS[name]?.key ? ` (${isMac ? '⌘' : 'Ctrl+'}${BUTTONS[name].key})` : name === 'link' ? ` (${isMac ? '⌘' : 'Ctrl+'}K)` : '')}
          aria-label=${name === 'link' ? 'Link' : BUTTONS[name].label} onMouseDown=${runButton(name)}>
          <${Icon} name=${name === 'link' ? 'link' : BUTTONS[name].icon} size=${15} />
        </button>`))}
    ${toolbarExtra && html`<span class="grow"></span>${toolbarExtra}`}
  </div>` : null;

  return html`<div ref=${wrapRef} class=${cx('rich-editor', disabled && 'is-disabled', cls)}>
    ${toolbarPosition === 'top' && toolbarEl}
    <div
      ref=${elRef}
      class="rich-editor-content"
      contenteditable=${disabled ? 'false' : 'true'}
      role="textbox"
      aria-multiline="true"
      aria-label=${ariaLabel || placeholder}
      data-placeholder=${placeholder}
      data-empty=${empty ? 'true' : 'false'}
      style=${{ minHeight: minHeight ? minHeight + 'px' : undefined, maxHeight: maxHeight ? maxHeight + 'px' : undefined }}
      onInput=${() => { emit(); updatePopup(); }}
      onKeyDown=${onKeyDown}
      onKeyUp=${(e) => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) updatePopup(); }}
      onPaste=${onPaste}
      onDrop=${onDrop}
      onFocus=${onFocus}
      onBlur=${(e) => { saveRange(); setTimeout(closePopup, 150); onBlur && onBlur(e); }}
      onMouseUp=${saveRange}
    ></div>
    ${toolbarPosition === 'bottom' && toolbarEl}
    ${popup && html`<div class=${cx('editor-popup', popup.pos.bottomSpace < 260 && 'is-above')}
      style=${{ left: Math.max(0, popup.pos.left - 8) + 'px', top: popup.pos.top + 4 + 'px' }}>
      ${popup.kind === 'slash' && html`<div class="editor-popup-title">Canned responses</div>`}
      ${popup.items.map((item, i) => html`<button
        type="button"
        key=${item.id}
        class=${cx('editor-popup-item', i === popup.active && 'is-active')}
        onMouseDown=${(e) => { e.preventDefault(); choose(item); }}
      >
        ${item.user && html`<${Avatar} user=${item.user} size=${18} />`}
        <span class="editor-popup-label">${item.label}</span>
        ${item.hint && html`<span class="editor-popup-hint">${item.hint}</span>`}
      </button>`)}
    </div>`}
  </div>`;
}

function placeCaretAtEnd(el) {
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}

function restoreRange(range) {
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}

// Render stored comment/chat HTML (already sanitized server-side) with mention chips.
export function RichText({ html: markup, class: cls }) {
  return html`<div class=${cx('rich-text', cls)} dangerouslySetInnerHTML=${{ __html: markup || '' }}></div>`;
}
