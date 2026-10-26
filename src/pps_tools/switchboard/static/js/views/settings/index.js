// Settings: a registry of sections. Each section is the default export (or `name`d
// export) of a file owned by the module it configures; sections whose file is
// missing show a placeholder.

import { html, useEffect, useState } from '../../lib/preact.js';
import { can, useStore } from '../../lib/store.js';
import { navigate } from '../../lib/router.js';
import { ModuleLayout, SidebarHeader, SidebarSection, SidebarItem, SidebarButton } from '../../ui/layout.js';
import { Empty, Loading, PageHeader } from '../../ui/components.js';

export const SECTIONS = [
  { group: 'You', items: [
    { id: 'profile', label: 'Profile', icon: 'user', load: () => import('./profile.js') },
    { id: 'preferences', label: 'Notifications & display', icon: 'bell', load: () => import('./preferences.js') },
    { id: 'signature', label: 'Email signature', icon: 'pen-line', perm: 'inbox', load: () => import('../inbox/settings.js'), name: 'SignatureSettings' },
  ] },
  { group: 'Workspace', perm: 'admin', items: [
    { id: 'general', label: 'General', icon: 'building', load: () => import('./general.js') },
    { id: 'people', label: 'People & roles', icon: 'users', load: () => import('./people.js') },
    { id: 'teams', label: 'Teams', icon: 'users-round', load: () => import('./teams.js') },
  ] },
  { group: 'Inbox', perm: 'inbox', items: [
    { id: 'channels', label: 'Channels', icon: 'plug', perm: 'admin', load: () => import('../channels/settings.js') },
    { id: 'rules', label: 'Rules', icon: 'zap', perm: 'admin', load: () => import('../channels/rules.js') },
    { id: 'responses', label: 'Canned responses', icon: 'message-square-text', load: () => import('../inbox/settings.js'), name: 'ResponsesSettings' },
    { id: 'labels', label: 'Labels', icon: 'tags', load: () => import('../inbox/settings.js'), name: 'LabelsSettings' },
  ] },
  { group: 'Staffing', perm: 'manage_staff', items: [
    { id: 'staffing', label: 'Positions & locations', icon: 'briefcase', load: () => import('../staffing/settings.js'), name: 'PositionsSettings' },
    { id: 'staffing-rules', label: 'Scheduling rules', icon: 'calendar-clock', load: () => import('../staffing/settings.js'), name: 'PolicySettings' },
  ] },
  { group: 'Jobs', perm: 'manage_jobs', items: [
    { id: 'job-stages', label: 'Stages', icon: 'square-kanban', load: () => import('../jobs/settings.js'), name: 'StagesSettings' },
    { id: 'job-fields', label: 'Spec fields', icon: 'sliders-horizontal', load: () => import('../jobs/settings.js'), name: 'FieldsSettings' },
    { id: 'resources', label: 'Equipment', icon: 'factory', load: () => import('../jobs/settings.js'), name: 'ResourcesSettings' },
    { id: 'job-templates', label: 'Job templates', icon: 'layers', load: () => import('../jobs/settings.js'), name: 'TemplatesSettings' },
  ] },
  { group: 'Integrations', perm: 'admin', items: [
    { id: 'integrations', label: 'Sidebar apps', icon: 'layout-grid', load: () => import('../admin/settings.js'), name: 'IntegrationsSettings' },
    { id: 'ai', label: 'AI assistant', icon: 'sparkles', load: () => import('../admin/settings.js'), name: 'AISettings' },
    { id: 'developers', label: 'API & webhooks', icon: 'code', load: () => import('../admin/settings.js'), name: 'DevelopersSettings' },
    { id: 'data', label: 'Import & export', icon: 'download', load: () => import('../admin/settings.js'), name: 'DataSettings' },
  ] },
];

function visibleSections() {
  return SECTIONS
    .filter((g) => !g.perm || can(g.perm))
    .map((g) => ({ ...g, items: g.items.filter((i) => !i.perm || can(i.perm)) }))
    .filter((g) => g.items.length);
}

function SectionOutlet({ section, route }) {
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    let alive = true;
    setState({ loading: true });
    section.load()
      .then((m) => {
        const C = m[section.name || 'default'];
        if (alive) setState(C ? { Component: C } : { missing: true });
      })
      .catch((err) => { console.warn(err); if (alive) setState({ missing: true }); });
    return () => { alive = false; };
  }, [section.id]);
  if (state.loading) return html`<${Loading} />`;
  if (state.missing) return html`<${Empty} icon="settings" title=${section.label}>This section isn't available yet.</${Empty}>`;
  const { Component } = state;
  return html`<${Component} route=${route} />`;
}

export default function Settings({ route }) {
  useStore((s) => s.me);
  const groups = visibleSections();
  const all = groups.flatMap((g) => g.items);
  const current = all.find((i) => i.id === route.segments[1]);
  useEffect(() => {
    if (!current && all.length) navigate('/settings/' + all[0].id, { replace: true });
  }, [route.path]);
  const sidebar = html`
    <${SidebarHeader} title="Settings" />
    ${groups.map((g) => html`<${SidebarSection} key=${g.group} title=${g.group}>
      ${g.items.map((i) => html`<${SidebarItem} key=${i.id} href=${'/settings/' + i.id} icon=${i.icon} label=${i.label} />`)}
    </${SidebarSection}>`)}
  `;
  return html`<${ModuleLayout} sidebar=${sidebar} class="settings-module">
    ${current && html`<${PageHeader} leading=${html`<${SidebarButton} />`} title=${current.label} icon=${current.icon} />
      <div class="page-body"><div class="settings-body"><${SectionOutlet} key=${current.id} section=${current} route=${route} /></div></div>`}
  </${ModuleLayout}>`;
}
