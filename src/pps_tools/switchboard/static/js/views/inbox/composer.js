// Reply / forward / new-message composer.
//
// Drafts live on the server from the first keystroke (autosaved), so teammates see
// them in the conversation and can co-edit; edits from others arrive as draft.changed
// events. Sending hands the draft to the outbox, which waits out the undo window.

import { html, useEffect, useMemo, useRef, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useStore, user as lookupUser, setting } from '../../lib/store.js';
import { useEvent, useDebounced } from '../../lib/hooks.js';
import { fmtDateTime, firstName, escapeHtml } from '../../lib/format.js';
import { Avatar, Button, Chip, Icon, IconButton, Select, Toggle, Spinner, cx } from '../../ui/components.js';
import { showMenu, toast, toastError, confirmDialog, promptDialog } from '../../ui/overlay.js';
import { pickDateTime, pickFromList } from '../../ui/pickers.js';
import { RichEditor, isEditorEmpty } from '../../ui/editor.js';
import { Attachments } from './timeline.js';
import { getAIStatus } from './common.js';

const MODE_LABEL = { new: 'New message', reply: 'Reply', reply_all: 'Reply all', forward: 'Forward' };

// -- recipients -----------------------------------------------------------------------

const EMAIL_RE = /^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$/;

function parseHandles(text, kind) {
  return text.split(/[,;\n]+/).map((s) => s.trim()).filter(Boolean).map((s) => {
    const m = s.match(/^(.*?)\s*<([^>]+)>$/);
    const name = m ? m[1].replace(/^"|"$/g, '').trim() : null;
    const handle = (m ? m[2] : s).trim();
    return { name: name || null, handle };
  }).filter((p) => (kind === 'email' ? EMAIL_RE.test(p.handle) : /\d{7,}/.test(p.handle.replace(/\D/g, ''))));
}

function RecipientsInput({ label, value, onChange, kind = 'email', autoFocus, placeholder }) {
  const [text, setText] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [active, setActive] = useState(0);
  const q = useDebounced(text, 160);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!q.trim()) { setSuggestions([]); return; }
    let alive = true;
    api.get('/compose/recipients', { q: q.trim(), kind: kind === 'email' ? 'email' : 'phone' })
      .then((r) => { if (alive) { setSuggestions(r.items.filter((s) => !value.some((v) => v.handle.toLowerCase() === s.handle.toLowerCase()))); setActive(0); } })
      .catch(() => {});
    return () => { alive = false; };
  }, [q]);

  const add = (people) => {
    const seen = new Set(value.map((v) => v.handle.toLowerCase()));
    const next = [...value];
    for (const p of people) if (!seen.has(p.handle.toLowerCase())) { seen.add(p.handle.toLowerCase()); next.push(p); }
    onChange(next);
    setText('');
    setSuggestions([]);
  };
  const commit = () => {
    const parsed = parseHandles(text, kind);
    if (parsed.length) add(parsed);
    return parsed.length > 0;
  };
  const onKey = (e) => {
    if (suggestions.length && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      setActive((a) => (e.key === 'ArrowDown' ? Math.min(suggestions.length - 1, a + 1) : Math.max(0, a - 1)));
      return;
    }
    if (e.key === 'Enter' || e.key === 'Tab' || e.key === ',' || e.key === ';') {
      if (suggestions.length && (e.key === 'Enter' || e.key === 'Tab')) {
        e.preventDefault();
        const s = suggestions[active];
        add([{ name: s.name, handle: s.handle }]);
        return;
      }
      if (text.trim()) {
        if (commit() || e.key !== 'Tab') e.preventDefault();
      }
    } else if (e.key === 'Backspace' && !text && value.length) {
      onChange(value.slice(0, -1));
    }
  };
  return html`<div class="recipients" onClick=${() => inputRef.current && inputRef.current.focus()}>
    <span class="recipients-label">${label}</span>
    <div class="recipients-chips">
      ${value.map((p, i) => html`<${Chip} key=${p.handle} title=${p.handle} onRemove=${() => onChange(value.filter((_, j) => j !== i))}>${p.name || p.handle}</${Chip}>`)}
      <input ref=${inputRef} class="recipients-input" value=${text} autoFocus=${autoFocus} placeholder=${value.length ? '' : placeholder}
        type=${kind === 'email' ? 'email' : 'tel'} multiple
        onInput=${(e) => setText(e.currentTarget.value)} onKeyDown=${onKey} onBlur=${() => setTimeout(() => { if (text.trim()) commit(); setSuggestions([]); }, 150)}
        onPaste=${(e) => { const t = e.clipboardData.getData('text'); if (/[,;\n]/.test(t)) { e.preventDefault(); add(parseHandles(t, kind)); } }} />
    </div>
    ${suggestions.length > 0 && html`<div class="recipients-suggest">
      ${suggestions.map((s, i) => html`<button type="button" key=${s.handle} class=${cx('recipients-option', i === active && 'is-active')}
        onMouseDown=${(e) => { e.preventDefault(); add([{ name: s.name, handle: s.handle }]); }}>
        <span class="strong">${s.name || s.handle}</span>${s.name && html`<span class="muted text-sm">${s.handle}</span>`}
      </button>`)}
    </div>`}
  </div>`;
}

// -- canned responses -----------------------------------------------------------------

function renderVars(markup, ctx) {
  return (markup || '').replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_, key) => {
    const v = key.split('.').reduce((o, k) => (o && o[k] !== undefined ? o[k] : undefined), ctx);
    return v === undefined || v === null ? '' : escapeHtml(String(v));
  });
}

function templateContext(conversation, me, orgName) {
  const contact = conversation?.contact || {};
  return {
    contact: { name: contact.name || '', first_name: firstName(contact.name) || 'there', email: contact.email || '', phone: contact.phone || '' },
    user: { name: me.name, first_name: firstName(me.name), email: me.email, title: me.title || '', phone: me.phone || '' },
    org: { name: orgName },
    conversation: { subject: conversation?.subject || '', id: conversation?.id || '' },
  };
}

// -- SMS length -----------------------------------------------------------------------

const GSM = /^[\n\r @£$¥èéùìòÇØøÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ!"#¤%&'()*+,\-./0-9:;<=>?¡A-ZÄÖÑÜ§¿a-zäöñüà^{}\\[~\]|€]*$/;
function smsInfo(text) {
  const gsm = GSM.test(text);
  const per = gsm ? (text.length > 160 ? 153 : 160) : (text.length > 70 ? 67 : 70);
  const segments = Math.max(1, Math.ceil(text.length / per));
  return { length: text.length, segments, gsm };
}

function textOf(markup) {
  const d = document.createElement('div');
  d.innerHTML = (markup || '').replace(/<br\s*\/?>/gi, '\n').replace(/<\/(p|div)>/gi, '\n');
  return (d.textContent || '').replace(/\n{3,}/g, '\n\n').trim();
}

// -- composer -------------------------------------------------------------------------

// initialDraft: an existing server draft (has an id). initialFields: prefill for a new
// message that has no draft yet (it's created on the first autosave).
export function Composer({ conversation, initialDraft, initialFields, onClose, onSent, variant = 'docked', autoFocus = true, presetType }) {
  const me = useStore((s) => s.me);
  const orgName = useStore((s) => s.settings['org.name']);
  const seed = initialDraft || initialFields || {};
  const [channels, setChannels] = useState(null);
  const [draft, setDraft] = useState(initialDraft && initialDraft.id ? initialDraft : null);
  const [fields, setFields] = useState(() => ({
    to: seed.to || [],
    cc: seed.cc || [],
    bcc: seed.bcc || [],
    subject: seed.subject || '',
    body_html: seed.body_html || '',
    channel_id: seed.channel_id || null,
    include_signature: seed.include_signature !== undefined ? seed.include_signature : true,
  }));
  const [attachments, setAttachments] = useState(seed.attachments || []);
  const [showCc, setShowCc] = useState(!!(seed.cc?.length || seed.bcc?.length));
  const [showSubject, setShowSubject] = useState(!conversation || seed.mode === 'forward');
  const [saveState, setSaveState] = useState('saved'); // saved | dirty | saving | error
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(0);
  const [remoteEdit, setRemoteEdit] = useState(null);
  const [signature, setSignature] = useState('');
  const [ai, setAI] = useState(null);
  const editorRef = useRef(null);
  const fileRef = useRef(null);
  const dirtyKeys = useRef(new Set());
  const saveTimer = useRef(null);
  const savePromise = useRef(Promise.resolve());
  const lastLocalEdit = useRef(0);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const fieldsRef = useRef(fields);
  fieldsRef.current = fields;

  useEffect(() => {
    api.get('/compose/channels').then((r) => setChannels(r.items)).catch(() => setChannels([]));
    getAIStatus().then(setAI);
  }, []);

  const channel = channels?.find((c) => c.id === fields.channel_id) || null;
  const kind = channel?.type || (conversation?.channel?.type) || 'email';
  // API/form channels reply by email (or their webhook), so they compose like email.
  const isEmail = kind === 'email' || kind === 'api';
  const isText = kind === 'sms' || kind === 'whatsapp';
  const isChat = kind === 'chat';

  // Default the From account for new messages (shared accounts first). Not a user
  // edit, so it doesn't create a draft by itself.
  useEffect(() => {
    if (!channels || fields.channel_id) return;
    const want = presetType || 'email';
    const ofType = channels.filter((c) => c.type === want);
    const pick = ofType.find((c) => c.visibility === 'shared') || ofType[0] || channels[0];
    if (pick) setFields((f) => ({ ...f, channel_id: pick.id }));
  }, [channels]);

  useEffect(() => {
    if (!isEmail || !fields.include_signature) { setSignature(''); return; }
    api.get('/me/signature', { channel_id: fields.channel_id }).then((r) => setSignature(r.effective_html || '')).catch(() => {});
  }, [fields.channel_id, fields.include_signature, isEmail]);

  const channelOptions = useMemo(() => {
    if (!channels) return [];
    const type = conversation?.channel?.type;
    // Replies stay on the conversation's kind of channel; form/API conversations can
    // also be answered from an email account.
    return channels.filter((c) => !conversation || !type || c.type === type || (type === 'api' && c.type === 'email'));
  }, [channels, conversation]);

  // -- saving ---------------------------------------------------------------------

  const save = async () => {
    clearTimeout(saveTimer.current);
    const keys = [...dirtyKeys.current];
    if (!keys.length && draftRef.current) return;
    dirtyKeys.current.clear();
    const payload = {};
    for (const k of keys) payload[k] = fieldsRef.current[k];
    setSaveState('saving');
    const run = async () => {
      try {
        let d;
        if (!draftRef.current) {
          d = (await api.post('/drafts', {
            ...fieldsRef.current, mode: 'new', attachment_ids: attachments.map((a) => a.id),
          })).draft;
          if (variant === 'page') history.replaceState({}, '', `/inbox/compose?draft=${d.id}`);
        } else {
          d = (await api.patch(`/drafts/${draftRef.current.id}`, payload)).draft;
        }
        draftRef.current = d;
        setDraft(d);
        setSaveState(dirtyKeys.current.size ? 'dirty' : 'saved');
      } catch (err) {
        setSaveState('error');
        keys.forEach((k) => dirtyKeys.current.add(k));
        if (err.status === 404) {
          toast('This draft was sent or discarded by a teammate');
          onClose && onClose();
        }
      }
    };
    savePromise.current = savePromise.current.then(run);
    return savePromise.current;
  };

  const update = (patch) => {
    setFields((f) => ({ ...f, ...patch }));
    Object.keys(patch).forEach((k) => dirtyKeys.current.add(k));
    lastLocalEdit.current = Date.now();
    setSaveState('dirty');
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(save, 700);
  };

  useEffect(() => () => {
    clearTimeout(saveTimer.current);
    if (dirtyKeys.current.size && draftRef.current) save();
  }, []);

  // -- live co-editing --------------------------------------------------------------

  const applyRemote = (d) => {
    setFields({
      to: d.to, cc: d.cc, bcc: d.bcc, subject: d.subject || '', body_html: d.body_html,
      channel_id: d.channel_id, include_signature: d.include_signature,
    });
    setAttachments(d.attachments || []);
    editorRef.current && editorRef.current.setHTML(d.body_html);
    setDraft(d);
    setRemoteEdit(null);
  };

  useEvent('draft.changed', (evt) => {
    const d = draftRef.current;
    if (!d || evt.id !== d.id || evt.by === me.id) return;
    if (evt.deleted) {
      toast(`${lookupUser(evt.by).name} ${evt.sent ? 'sent' : 'discarded'} this draft`);
      onClose && onClose({ remote: true });
      return;
    }
    if (!evt.draft || evt.version <= d.version) return;
    if (Date.now() - lastLocalEdit.current > 2500 && !dirtyKeys.current.size) applyRemote(evt.draft);
    else setRemoteEdit({ by: evt.by, draft: evt.draft });
  }, [me.id]);

  // -- attachments ----------------------------------------------------------------

  const uploadFiles = async (fileList) => {
    const list = [...fileList];
    if (!list.length) return;
    setUploading((n) => n + list.length);
    try {
      const uploaded = await api.upload(list);
      const next = [...attachments, ...uploaded];
      setAttachments(next);
      if (draftRef.current) await api.patch(`/drafts/${draftRef.current.id}`, { attachment_ids: uploaded.map((a) => a.id) });
      else update({});
    } catch (err) {
      toastError(err);
    } finally {
      setUploading((n) => n - list.length);
    }
  };
  const removeAttachment = async (a) => {
    setAttachments(attachments.filter((x) => x.id !== a.id));
    api.del(`/files/${a.id}`).catch(() => {});
  };

  // -- send / discard ---------------------------------------------------------------

  const empty = isEditorEmpty(fields.body_html) && !attachments.length;

  const send = async ({ sendAt = null, close = false } = {}) => {
    if (sending) return;
    if (empty) { toast('Write a message first'); return; }
    if (!isChat && !fields.to.length && !fields.cc.length && !fields.bcc.length) { toast('Add a recipient'); return; }
    setSending(true);
    try {
      dirtyKeys.current = new Set(Object.keys(fieldsRef.current));
      await save();
      const d = draftRef.current;
      const res = await api.post(`/drafts/${d.id}/send`, { send_at: sendAt, close });
      onSent && onSent(res, { sendAt, close });
      onClose && onClose({ sent: true });
    } catch (err) {
      toastError(err);
    } finally {
      setSending(false);
    }
  };

  const discard = async () => {
    if (!empty && !(await confirmDialog({ title: 'Discard this draft?', confirmLabel: 'Discard', danger: true }))) return;
    clearTimeout(saveTimer.current);
    dirtyKeys.current.clear();
    if (draftRef.current) await api.del(`/drafts/${draftRef.current.id}`).catch(() => {});
    onClose && onClose({ discarded: true });
  };

  const sendMenu = (e) => showMenu(e.currentTarget, [
    { label: 'Send and close', icon: 'archive', shortcut: '⇧↵', onSelect: () => send({ close: true }), disabled: !conversation },
    { label: 'Send later…', icon: 'clock', onSelect: () => pickDateTime(e.target.closest('.btn-group') || e.target, {
      title: 'Send at', allowClear: false,
      onChange: (iso) => iso && send({ sendAt: iso }),
    }) },
  ], { placement: 'top-end' });

  // -- canned responses & AI ----------------------------------------------------------

  const ctx = templateContext(conversation, me, orgName);
  const responseItems = async (q) => {
    const res = await api.get('/responses', { q: q || undefined }).catch(() => ({ items: [] }));
    return res.items.map((r) => ({ id: r.id, label: r.title, hint: r.shortcut ? '/' + r.shortcut : r.folder, html: renderVars(r.body_html, ctx), subject: r.subject }));
  };
  const slash = async (q) => {
    const items = await responseItems(q);
    return items.map((i) => ({ ...i, html: i.html }));
  };
  const insertResponse = async (e) => {
    const anchor = e.currentTarget;
    const items = await responseItems('');
    pickFromList(anchor, {
      title: 'Canned responses',
      items: items.map((i) => ({ id: i.id, label: i.label, hint: i.hint })),
      emptyText: 'No canned responses yet — add some in Settings',
      placement: 'top-start',
      width: 320,
      onChange: (id) => {
        const item = items.find((i) => i.id === id);
        if (!item) return;
        editorRef.current.insertHTML(item.html);
        if (item.subject && !fields.subject) update({ subject: renderVars(item.subject, ctx) });
        api.post(`/responses/${id}/render`, { conversation_id: conversation?.id }).catch(() => {});
      },
    });
  };

  const aiMenu = (e) => {
    const previous = fields.body_html;
    const replace = (markup) => {
      editorRef.current.setHTML(markup);
      update({ body_html: markup });
      toast('Updated by AI', { action: { label: 'Undo', onClick: () => { editorRef.current.setHTML(previous); update({ body_html: previous }); } } });
    };
    const run = async (fn) => {
      const stop = toast('Thinking…', { duration: 0, icon: 'sparkles' });
      try { replace(await fn()); } catch (err) { toastError(err); } finally { stop(); }
    };
    const rewrite = (mode) => run(async () => (await api.post('/ai/rewrite', { html: fields.body_html, mode })).html);
    showMenu(e.currentTarget, [
      ...(conversation ? [{ label: 'Draft a reply', icon: 'wand-sparkles', onSelect: async () => {
        const instructions = isEditorEmpty(fields.body_html) ? '' : textOf(fields.body_html);
        run(async () => (await api.post('/ai/draft', { conversation_id: conversation.id, instructions })).body_html);
      } }] : []),
      { header: 'Rewrite' },
      { label: 'Fix spelling & grammar', icon: 'check', disabled: empty, onSelect: () => rewrite('fix') },
      { label: 'Friendlier', icon: 'smile', disabled: empty, onSelect: () => rewrite('friendly') },
      { label: 'More formal', icon: 'briefcase', disabled: empty, onSelect: () => rewrite('formal') },
      { label: 'Shorter', icon: 'minimize-2', disabled: empty, onSelect: () => rewrite('shorter') },
      { label: 'Translate…', icon: 'globe', disabled: empty, onSelect: async () => {
        const language = await promptDialog({ title: 'Translate to', label: 'Language', value: 'Spanish', confirmLabel: 'Translate' });
        if (language) run(async () => (await api.post('/ai/translate', { html: fields.body_html, language })).html);
      } },
    ], { placement: 'top-start', width: 240 });
  };

  // -- keyboard -------------------------------------------------------------------------

  const onEditorSubmit = () => send();
  const onKeyDown = (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.shiftKey && e.key === 'Enter') { e.preventDefault(); send({ close: true }); }
  };

  const sms = isText ? smsInfo(textOf(fields.body_html)) : null;
  const undoSeconds = setting('inbox.undo_send_seconds', 8);
  const modeLabel = conversation ? MODE_LABEL[draft?.mode || 'reply'] : (isText ? 'New text message' : 'New message');
  const coEditors = draft && draft.updated_by && draft.updated_by !== me.id ? [draft.updated_by] : [];

  return html`<div class=${cx('composer', `composer-${variant}`, isText && 'composer-text')} onKeyDown=${onKeyDown}>
    <div class="composer-head">
      <span class="composer-mode"><${Icon} name=${draft?.mode === 'forward' ? 'forward' : draft?.mode === 'reply_all' ? 'reply-all' : conversation ? 'reply' : 'square-pen'} size=${14} />${modeLabel}</span>
      ${channelOptions.length > 1 || !conversation ? html`<label class="composer-from">
        <span>From</span>
        <${Select} class="input-sm" value=${String(fields.channel_id || '')} onValue=${(v) => update({ channel_id: Number(v) })}
          options=${channelOptions.map((c) => ({ value: String(c.id), label: `${c.name}${c.address ? ` <${c.address}>` : ''}` }))} />
      </label>` : html`<span class="composer-from muted text-sm">via ${channel?.name || ''}</span>`}
      <span class="grow"></span>
      ${coEditors.map((uid) => html`<span key=${uid} class="composer-coeditor" title=${`${lookupUser(uid).name} edited this draft`}><${Avatar} user=${uid} size=${18} /></span>`)}
      <span class=${cx('composer-save', `is-${saveState}`)}>${saveState === 'saving' ? 'Saving…' : saveState === 'error' ? 'Not saved' : saveState === 'dirty' ? '' : draft ? 'Saved' : ''}</span>
      ${onClose && variant === 'docked' && html`<${IconButton} icon="minimize-2" size="sm" label="Hide (draft is kept)" onClick=${() => { save(); onClose({ minimized: true }); }} />`}
    </div>
    ${remoteEdit && html`<div class="composer-remote">
      <${Avatar} user=${remoteEdit.by} size=${18} /> ${lookupUser(remoteEdit.by).name} also edited this draft.
      <button type="button" class="btn-link" onClick=${() => applyRemote(remoteEdit.draft)}>Load their version</button>
    </div>`}
    ${channels && !channels.length && html`<div class="composer-remote"><${Icon} name="plug" size=${14} /> No connected account you can send from. An admin can add one in Settings → Channels.</div>`}
    <div class="composer-fields">
      ${isChat
    ? html`<div class="recipients"><span class="recipients-label">To</span><span class="muted text-sm">${conversation?.contact?.display_name || 'Website visitor'} · replies appear in their chat window</span></div>`
    : conversation && isText
      ? html`<div class="recipients"><span class="recipients-label">To</span><div class="recipients-chips">
          ${fields.to.map((p) => html`<${Chip} key=${p.handle} icon="smartphone">${conversation.contact?.display_name || p.name || p.handle}${conversation.contact?.display_name ? ` · ${p.handle}` : ''}</${Chip}>`)}
        </div></div>`
      : html`<${RecipientsInput} label="To" value=${fields.to} onChange=${(to) => update({ to })} kind=${isEmail ? 'email' : 'phone'}
          autoFocus=${autoFocus && !fields.to.length} placeholder=${isEmail ? 'Name or email' : 'Phone number'} />`}
      ${isEmail && !showCc && html`<button type="button" class="composer-cc-toggle" onClick=${() => setShowCc(true)}>Cc/Bcc</button>`}
      ${isEmail && showCc && html`<${RecipientsInput} label="Cc" value=${fields.cc} onChange=${(cc) => update({ cc })} />
        <${RecipientsInput} label="Bcc" value=${fields.bcc} onChange=${(bcc) => update({ bcc })} />`}
      ${isEmail && (showSubject
    ? html`<div class="composer-subject"><input class="composer-subject-input" value=${fields.subject} placeholder="Subject"
          onInput=${(e) => update({ subject: e.currentTarget.value })} /></div>`
    : html`<button type="button" class="composer-cc-toggle" onClick=${() => setShowSubject(true)}>Subject</button>`)}
    </div>
    <${RichEditor}
      value=${fields.body_html}
      onChange=${(body_html) => update({ body_html })}
      editorRef=${editorRef}
      toolbar=${isEmail ? 'full' : false}
      placeholder=${isEmail ? `Write your ${conversation ? 'reply' : 'message'}… (type / for canned responses)` : 'Write a text… (type / for canned responses)'}
      slash=${slash}
      onFiles=${uploadFiles}
      onSubmit=${onEditorSubmit}
      autofocus=${autoFocus && fields.to.length > 0}
      minHeight=${variant === 'page' ? 220 : 110}
      maxHeight=${variant === 'page' ? 520 : 340}
      class="composer-editor"
    />
    ${signature && html`<div class="composer-signature" title="Your signature is added when sending"><div dangerouslySetInnerHTML=${{ __html: signature }}></div></div>`}
    ${(attachments.length > 0 || uploading > 0) && html`<div class="composer-attachments">
      <${Attachments} items=${attachments} onRemove=${removeAttachment} />
      ${uploading > 0 && html`<span class="row muted text-sm"><${Spinner} size=${13} /> Uploading…</span>`}
    </div>`}
    <div class="composer-foot">
      <div class="btn-group">
        <${Button} variant="primary" icon="send" loading=${sending} onClick=${() => send()} data-tip=${`Send (${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl+'}↵) · ${undoSeconds}s to undo`}>Send</${Button}>
        <${Button} variant="primary" icon="chevron-down" aria-label="More send options" onClick=${sendMenu} />
      </div>
      <${IconButton} icon="paperclip" label="Attach files" onClick=${() => fileRef.current.click()} />
      <input ref=${fileRef} type="file" multiple hidden onChange=${(e) => { uploadFiles(e.currentTarget.files); e.currentTarget.value = ''; }} />
      <${IconButton} icon="message-square-text" label="Canned responses (/)" onClick=${insertResponse} />
      ${ai?.configured && html`<${IconButton} icon="sparkles" label="AI assist" onClick=${aiMenu} />`}
      ${isEmail && html`<${Toggle} checked=${fields.include_signature} onChange=${(v) => update({ include_signature: v })} label="Signature" class="composer-sig-toggle" />`}
      ${sms && html`<span class=${cx('sms-count', sms.segments > 1 && 'is-multi')} title=${sms.gsm ? 'Standard characters' : 'Contains emoji or special characters (70 per segment)'}>${sms.length} chars · ${sms.segments} ${sms.segments === 1 ? 'segment' : 'segments'}</span>`}
      <span class="grow"></span>
      <${IconButton} icon="trash" label="Discard draft" onClick=${discard} />
    </div>
  </div>`;
}

export function scheduledToast(res, { sendAt } = {}, onUndo) {
  const label = sendAt ? `Scheduled for ${fmtDateTime(sendAt)}` : 'Sending…';
  toast(label, {
    icon: sendAt ? 'clock' : 'send',
    duration: sendAt ? 6000 : Math.max(4000, (setting('inbox.undo_send_seconds', 8) || 0) * 1000),
    action: { label: sendAt ? 'Cancel' : 'Undo', onClick: onUndo },
  });
}
