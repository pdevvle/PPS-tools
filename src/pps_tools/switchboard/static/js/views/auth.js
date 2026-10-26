// Signed-out screens: first-run setup, sign in, accept invite, reset password.

import { html, useEffect, useState } from '../lib/preact.js';
import { api } from '../lib/api.js';
import { navigate, useRoute, matchPath } from '../lib/router.js';
import { Banner, Button, Field, Input } from '../ui/components.js';

function AuthCard({ title, subtitle, children, footer }) {
  return html`<div class="auth-page">
    <div class="auth-card">
      <div class="auth-brand"><span class="logo-mark logo-mark-lg"></span><span class="auth-brand-name">Switchboard</span></div>
      <h1 class="auth-title">${title}</h1>
      ${subtitle && html`<p class="auth-subtitle">${subtitle}</p>`}
      ${children}
    </div>
    ${footer && html`<div class="auth-footer">${footer}</div>`}
  </div>`;
}

function useSubmit(fn) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err.message || 'Something went wrong');
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, submit, setError };
}

function Setup({ onSignedIn }) {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const [form, setForm] = useState({ org_name: '', name: '', email: '', password: '' });
  const set = (k) => (v) => setForm({ ...form, [k]: v });
  const { busy, error, submit } = useSubmit(async () => {
    const res = await api.post('/auth/setup', { ...form, timezone: tz });
    onSignedIn(res.me);
  });
  return html`<${AuthCard} title="Set up your workspace" subtitle="One place for your team's email, texts and chat — plus who's working when, and what's being made.">
    <form class="stack" onSubmit=${submit}>
      ${error && html`<${Banner} tone="danger">${error}</${Banner}>`}
      <${Field} label="Business name"><${Input} value=${form.org_name} onValue=${set('org_name')} placeholder="Priority Print Service" required autoFocus /></${Field}>
      <${Field} label="Your name"><${Input} value=${form.name} onValue=${set('name')} autoComplete="name" required /></${Field}>
      <${Field} label="Work email"><${Input} type="email" value=${form.email} onValue=${set('email')} autoComplete="email" required /></${Field}>
      <${Field} label="Password" hint="At least 8 characters"><${Input} type="password" value=${form.password} onValue=${set('password')} autoComplete="new-password" minLength="8" required /></${Field}>
      <p class="muted text-sm">Timezone: ${tz}. You can change this later in Settings.</p>
      <${Button} variant="primary" type="submit" loading=${busy} class="btn-block">Create workspace</${Button}>
    </form>
  </${AuthCard}>`;
}

function Login({ onSignedIn, state }) {
  const [form, setForm] = useState({ email: '', password: '' });
  const set = (k) => (v) => setForm({ ...form, [k]: v });
  const { busy, error, submit } = useSubmit(async () => {
    const res = await api.post('/auth/login', { ...form, remember: true });
    onSignedIn(res.me);
  });
  return html`<${AuthCard} title=${`Sign in to ${state?.org_name || 'Switchboard'}`}
    footer=${html`<a href="/forgot">Forgot your password?</a>`}>
    <form class="stack" onSubmit=${submit}>
      ${state?.offline && html`<${Banner} tone="warn">Can't reach the server right now.</${Banner}>`}
      ${error && html`<${Banner} tone="danger">${error}</${Banner}>`}
      <${Field} label="Email"><${Input} type="email" value=${form.email} onValue=${set('email')} autoComplete="username" required autoFocus /></${Field}>
      <${Field} label="Password"><${Input} type="password" value=${form.password} onValue=${set('password')} autoComplete="current-password" required /></${Field}>
      <${Button} variant="primary" type="submit" loading=${busy} class="btn-block">Sign in</${Button}>
    </form>
  </${AuthCard}>`;
}

function Invite({ token, onSignedIn }) {
  const [info, setInfo] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [form, setForm] = useState({ name: '', password: '' });
  useEffect(() => {
    api.get(`/auth/invite/${token}`).then((i) => { setInfo(i); setForm((f) => ({ ...f, name: i.name })); }).catch((e) => setLoadError(e.message));
  }, [token]);
  const { busy, error, submit } = useSubmit(async () => {
    const res = await api.post(`/auth/invite/${token}`, { ...form, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
    navigate('/', { replace: true });
    onSignedIn(res.me);
  });
  if (loadError) {
    return html`<${AuthCard} title="Invitation unavailable" subtitle=${loadError} footer=${html`<a href="/login">Go to sign in</a>`} />`;
  }
  return html`<${AuthCard} title=${info ? `Join ${info.org_name}` : 'Join your team'} subtitle=${info && `You're signing up as ${info.email}.`}>
    <form class="stack" onSubmit=${submit}>
      ${error && html`<${Banner} tone="danger">${error}</${Banner}>`}
      <${Field} label="Your name"><${Input} value=${form.name} onValue=${(v) => setForm({ ...form, name: v })} required /></${Field}>
      <${Field} label="Choose a password" hint="At least 8 characters"><${Input} type="password" value=${form.password}
        onValue=${(v) => setForm({ ...form, password: v })} autoComplete="new-password" minLength="8" required autoFocus /></${Field}>
      <${Button} variant="primary" type="submit" loading=${busy} class="btn-block" disabled=${!info}>Join</${Button}>
    </form>
  </${AuthCard}>`;
}

function Forgot() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(null);
  const { busy, error, submit } = useSubmit(async () => {
    const res = await api.post('/auth/forgot', { email });
    setSent(res);
  });
  return html`<${AuthCard} title="Reset your password" footer=${html`<a href="/login">Back to sign in</a>`}>
    ${sent
    ? html`<${Banner} tone=${sent.can_email ? 'info' : 'warn'}>${sent.can_email
      ? 'If that email has an account, a reset link is on its way.'
      : "Email isn't set up for this workspace yet. Ask an admin to send you a reset link from Settings → People."}</${Banner}>`
    : html`<form class="stack" onSubmit=${submit}>
        ${error && html`<${Banner} tone="danger">${error}</${Banner}>`}
        <${Field} label="Email"><${Input} type="email" value=${email} onValue=${setEmail} required autoFocus /></${Field}>
        <${Button} variant="primary" type="submit" loading=${busy} class="btn-block">Send reset link</${Button}>
      </form>`}
  </${AuthCard}>`;
}

function Reset({ token, onSignedIn }) {
  const [password, setPassword] = useState('');
  const { busy, error, submit } = useSubmit(async () => {
    const res = await api.post(`/auth/reset/${token}`, { password });
    navigate('/', { replace: true });
    onSignedIn(res.me);
  });
  return html`<${AuthCard} title="Choose a new password" footer=${html`<a href="/login">Back to sign in</a>`}>
    <form class="stack" onSubmit=${submit}>
      ${error && html`<${Banner} tone="danger">${error}</${Banner}>`}
      <${Field} label="New password" hint="At least 8 characters"><${Input} type="password" value=${password} onValue=${setPassword}
        autoComplete="new-password" minLength="8" required autoFocus /></${Field}>
      <${Button} variant="primary" type="submit" loading=${busy} class="btn-block">Save and sign in</${Button}>
    </form>
  </${AuthCard}>`;
}

export function AuthGate({ state, onSignedIn }) {
  const route = useRoute();
  if (state?.setup_required) return html`<${Setup} onSignedIn=${onSignedIn} />`;
  const invite = matchPath('/invite/:token', route.path);
  if (invite) return html`<${Invite} token=${invite.token} onSignedIn=${onSignedIn} />`;
  const reset = matchPath('/reset/:token', route.path);
  if (reset) return html`<${Reset} token=${reset.token} onSignedIn=${onSignedIn} />`;
  if (route.path === '/forgot') return html`<${Forgot} />`;
  return html`<${Login} onSignedIn=${onSignedIn} state=${state} />`;
}
