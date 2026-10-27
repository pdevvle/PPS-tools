// Page layout used by every module: a sidebar (collapses into a drawer on phones) and
// the main area.
//
//   <ModuleLayout sidebar=${html`<${SidebarHeader} title="Jobs" />
//       <${SidebarSection} title="Views"><${SidebarItem} href="/jobs" icon="square-kanban" label="Board" /></${SidebarSection}>`}>
//     <${PageHeader} leading=${html`<${SidebarButton} />`} title="Board" />
//     ...
//   </ModuleLayout>

import { createContext, html, useContext, useEffect, useState } from '../lib/preact.js';
import { useIsMobile, useLocalStorage } from '../lib/hooks.js';
import { useRoute } from '../lib/router.js';
import { Icon } from './icons.js';
import { cx } from './components.js';

const SidebarCtx = createContext(null);

export function ModuleLayout({ sidebar, children, class: cls, wide }) {
  const mobile = useIsMobile();
  const [open, setOpen] = useState(false);
  const route = useRoute();
  useEffect(() => setOpen(false), [route.path, route.search]);
  return html`<${SidebarCtx.Provider} value=${{ open: () => setOpen(true), hasSidebar: !!sidebar }}>
    <div class=${cx('module', !sidebar && 'module-no-sidebar', wide && 'module-wide', cls)}>
      ${sidebar && html`<aside class=${cx('module-sidebar', open && 'is-open')} aria-label="Section navigation">${sidebar}</aside>`}
      ${sidebar && mobile && open && html`<div class="module-scrim" onClick=${() => setOpen(false)}></div>`}
      <section class="module-main">${children}</section>
    </div>
  </${SidebarCtx.Provider}>`;
}

// Hamburger that opens the module sidebar on phones (renders nothing on desktop).
export function SidebarButton() {
  const ctx = useContext(SidebarCtx);
  const mobile = useIsMobile();
  if (!ctx || !ctx.hasSidebar || !mobile) return null;
  return html`<button type="button" class="icon-btn icon-btn-md icon-btn-ghost sidebar-button" aria-label="Menu" onClick=${ctx.open}>
    <${Icon} name="menu" size=${18} />
  </button>`;
}

export function SidebarHeader({ title, actions, children }) {
  return html`<div class="sidebar-header">
    <h2 class="sidebar-title">${title}</h2>
    ${actions && html`<div class="sidebar-header-actions">${actions}</div>`}
    ${children}
  </div>`;
}

export function SidebarSection({ title, children, actions, collapsible = false, storageKey }) {
  const [open, setOpen] = useLocalStorage(storageKey ? 'sb.sidebar.' + storageKey : 'sb.sidebar.none', true);
  const isOpen = collapsible ? open : true;
  return html`<div class=${cx('sidebar-section', !isOpen && 'is-collapsed')}>
    ${title && html`<div class="sidebar-section-header">
      ${collapsible
    ? html`<button type="button" class="sidebar-section-toggle" onClick=${() => setOpen(!open)} aria-expanded=${isOpen}>
            <${Icon} name="chevron-right" size=${11} class="sidebar-section-chevron" /><span>${title}</span>
          </button>`
    : html`<span class="sidebar-section-title">${title}</span>`}
      ${actions && html`<span class="sidebar-section-actions">${actions}</span>`}
    </div>`}
    ${isOpen && html`<div class="sidebar-section-body">${children}</div>`}
  </div>`;
}

export function SidebarItem({ href, icon, label, count, countTone, color, active, exact = false, onClick, indent = 0, title, trailing, class: cls, ...rest }) {
  const route = useRoute();
  const isActive = active ?? (href ? (exact ? route.path === href : route.path === href || route.path.startsWith(href + '/')) : false);
  const content = html`
    ${color ? html`<span class="sidebar-dot" style=${{ background: color }}></span>` : icon && html`<${Icon} name=${icon} size=${16} class="sidebar-icon" />`}
    <span class="sidebar-label">${label}</span>
    ${trailing}
    ${count ? html`<span class=${cx('sidebar-count', countTone && `tone-${countTone}`)}>${count > 999 ? '999+' : count}</span>` : null}
  `;
  const props = {
    class: cx('sidebar-item', isActive && 'is-active', cls),
    style: indent ? { paddingLeft: 10 + indent * 14 + 'px' } : undefined,
    title: title || (typeof label === 'string' ? label : undefined),
    'aria-current': isActive ? 'page' : undefined,
    ...rest,
  };
  if (href) return html`<a href=${href} onClick=${onClick} ...${props}>${content}</a>`;
  return html`<button type="button" onClick=${onClick} ...${props}>${content}</button>`;
}
