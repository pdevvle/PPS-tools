// Sidebar apps in the conversation sidebar (inbox/panels.js): an embedded page per
// iframe app, recent orders per WooCommerce app. Configured in Settings → Sidebar apps.

import { html, useEffect, useState } from '../../lib/preact.js';
import { api } from '../../lib/api.js';
import { useFetch } from '../../lib/hooks.js';
import { fmtRelative } from '../../lib/format.js';
import { Chip, Icon, SidePanel, Spinner } from '../../ui/components.js';

const TTL = 60000;
let cache = null; // { at, items } shared by every conversation

function useApps() {
  const fresh = cache && Date.now() - cache.at < TTL;
  const [items, setItems] = useState(cache ? cache.items : null);
  useEffect(() => {
    if (fresh) return;
    api.get('/integrations')
      .then((r) => { cache = { at: Date.now(), items: r.items }; setItems(r.items); })
      .catch(() => setItems((s) => s || []));
  }, []);
  return items;
}

export function IntegrationsPanel({ conversation }) {
  const apps = useApps();
  if (!conversation || !apps || !apps.length) return null;
  return apps.map((app) => html`<${AppPanel} key=${`${app.id}-${conversation.id}`} app=${app} cid=${conversation.id} />`);
}

function AppPanel({ app, cid }) {
  const { data, error, loading } = useFetch(`/integrations/${app.id}/context`, { query: { conversation_id: cid } });
  const woo = app.kind === 'woocommerce';
  const count = woo && data?.orders?.length ? data.orders.length : null;
  const actions = !woo && data?.url && html`<a class="icon-btn icon-btn-sm icon-btn-ghost" href=${data.url} target="_blank" rel="noopener noreferrer"
    aria-label=${`Open ${app.name} in a new tab`} data-tip="Open in new tab"><${Icon} name="external-link" size=${14} /></a>`;
  let body;
  if (loading && !data) body = html`<div class="integration-loading"><${Spinner} size=${14} /></div>`;
  else if (error) body = html`<div class="integration-message"><${Icon} name="circle-alert" size=${14} />${error.message}</div>`;
  else if (data.message && !(data.orders && data.orders.length)) body = html`<div class="integration-message"><${Icon} name="info" size=${14} />${data.message}</div>`;
  else if (woo) body = html`<${Orders} orders=${data.orders} />`;
  else body = html`<iframe class="integration-frame" src=${data.url} title=${app.name} style=${{ height: `${data.height || 320}px` }} loading="lazy"
    referrerpolicy="no-referrer" sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox"></iframe>`;
  return html`<${SidePanel} title=${app.name} icon=${woo ? 'store' : 'globe'} count=${count} actions=${actions}>${body}</${SidePanel}>`;
}

const STATUS_TONES = { completed: 'ok', processing: 'info', 'on-hold': 'warn', pending: 'muted', cancelled: 'muted', refunded: 'muted', failed: 'danger' };

function money(total, currency) {
  const n = Number(total);
  if (Number.isNaN(n)) return total || '';
  try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: currency || 'USD' }).format(n); } catch { return `${n.toFixed(2)} ${currency || ''}`; }
}

function Orders({ orders }) {
  if (!orders.length) return html`<div class="integration-message"><${Icon} name="package" size=${14} />No orders for this customer yet.</div>`;
  return html`<ul class="woo-orders">
    ${orders.map((o) => {
    const items = (o.items || []).map((li) => `${li.quantity} × ${li.name}`).join(', ');
    return html`<li key=${o.id}><a class="woo-order" href=${o.url} target="_blank" rel="noopener noreferrer">
        <span class="woo-order-top">
          <span class="strong">#${o.number}</span>
          <${Chip} size="sm" tone=${STATUS_TONES[o.status] || 'muted'}>${(o.status || '').replace(/-/g, ' ')}</${Chip}>
          <span class="woo-order-total">${money(o.total, o.currency)}</span>
        </span>
        <span class="woo-order-meta muted text-sm truncate">${fmtRelative(o.date)}${items ? ` · ${items}` : ''}</span>
      </a></li>`;
  })}
  </ul>`;
}
