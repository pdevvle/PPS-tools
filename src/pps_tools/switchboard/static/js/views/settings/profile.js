import { html, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useStore, loadBootstrap } from '../../lib/store.js';
import { Avatar, Button, ColorChoices, Field, Input, Section, Select } from '../../ui/components.js';
import { toast, toastError } from '../../ui/overlay.js';

const ZONES = (Intl.supportedValuesOf ? Intl.supportedValuesOf('timeZone') : ['America/Phoenix', 'America/Los_Angeles', 'America/Denver', 'America/Chicago', 'America/New_York', 'UTC']);

export default function Profile() {
  const me = useStore((s) => s.me);
  const [form, setForm] = useState({ name: me.name, title: me.title || '', phone: me.phone || '', color: me.color, timezone: me.timezone || '' });
  const [pw, setPw] = useState({ current: '', new: '' });
  const [pin, setPin] = useState('');
  const [feed, setFeed] = useState(null);
  const set = (k) => (v) => setForm({ ...form, [k]: v });

  const save = async (e) => {
    e.preventDefault();
    try {
      await api.patch(`/users/${me.id}`, form);
      await loadBootstrap();
      toast('Profile saved');
    } catch (err) { toastError(err); }
  };
  const changePassword = async (e) => {
    e.preventDefault();
    try {
      await api.post('/auth/password', pw);
      setPw({ current: '', new: '' });
      toast('Password changed. Other devices were signed out.');
    } catch (err) { toastError(err); }
  };
  const savePin = async (e) => {
    e.preventDefault();
    try {
      await api.post('/me/pin', { pin });
      setPin('');
      toast('Time clock PIN saved');
    } catch (err) { toastError(err); }
  };
  const rotateFeed = async () => {
    try {
      const res = await api.post('/me/feed-token');
      setFeed(res.feed_token);
      toast('New calendar link created; the old one stops working.');
    } catch (err) { toastError(err); }
  };
  const feedUrl = feed ? `${location.origin}/feeds/${feed}.ics` : null;

  return html`<div>
    <${Section} title="Your profile" description="How teammates see you across the inbox, chat and schedule.">
      <form class="stack" onSubmit=${save} style="max-width:520px">
        <div class="row gap-3"><${Avatar} user=${{ ...me, ...form }} size=${52} /><div class="stack-sm"><div class="strong">${form.name}</div><div class="muted text-sm">${me.email} · ${me.role}</div></div></div>
        <div class="form-grid">
          <${Field} label="Name"><${Input} value=${form.name} onValue=${set('name')} required /></${Field}>
          <${Field} label="Title"><${Input} value=${form.title} onValue=${set('title')} placeholder="e.g. Press Operator" /></${Field}>
          <${Field} label="Mobile phone" hint="Used for shift reminders by text, if enabled"><${Input} type="tel" value=${form.phone} onValue=${set('phone')} /></${Field}>
          <${Field} label="Timezone"><${Select} value=${form.timezone} onValue=${set('timezone')} placeholder="Workspace default" options=${ZONES} /></${Field}>
        </div>
        <${Field} label="Color"><${ColorChoices} value=${form.color} onChange=${set('color')} /></${Field}>
        <div><${Button} variant="primary" type="submit">Save profile</${Button}></div>
      </form>
    </${Section}>
    <${Section} title="Password">
      <form class="stack" onSubmit=${changePassword} style="max-width:360px">
        <${Field} label="Current password"><${Input} type="password" value=${pw.current} onValue=${(v) => setPw({ ...pw, current: v })} autoComplete="current-password" /></${Field}>
        <${Field} label="New password" hint="At least 8 characters"><${Input} type="password" value=${pw.new} onValue=${(v) => setPw({ ...pw, new: v })} autoComplete="new-password" minLength="8" required /></${Field}>
        <div><${Button} type="submit">Change password</${Button}></div>
      </form>
    </${Section}>
    <${Section} title="Time clock PIN" description="Clock in and out on the shared shop tablet (Schedule → Kiosk) with a 4–8 digit PIN.">
      <form class="row" onSubmit=${savePin} style="max-width:360px">
        <${Input} type="password" inputMode="numeric" pattern="[0-9]{4,8}" value=${pin} onValue=${setPin} placeholder=${me.has_pin ? '••••  (set)' : 'New PIN'} />
        <${Button} type="submit">Save PIN</${Button}>
      </form>
    </${Section}>
    <${Section} title="Calendar feed" description="Subscribe from Google Calendar, Outlook or your phone to see your shifts, scheduled work and events. Treat the link like a password.">
      ${feedUrl
    ? html`<div class="row"><${Input} readOnly value=${feedUrl} onFocus=${(e) => e.currentTarget.select()} /><${Button} icon="copy" onClick=${() => { navigator.clipboard.writeText(feedUrl); toast('Copied'); }}>Copy</${Button}></div>`
    : html`<${Button} icon="link" onClick=${rotateFeed}>Create my private calendar link</${Button}>`}
    </${Section}>
  </div>`;
}
