// Feature modules shown in the left rail. Each `load` resolves to a module whose
// default export is the page component: ({ route }) => vnode, where route is
// { path, segments, query }. URLs start with '/<id>'.

export const MODULES = [
  { id: 'inbox', label: 'Inbox', icon: 'inbox', perm: 'inbox', shortcut: 'g i', load: () => import('./views/inbox/index.js') },
  { id: 'chat', label: 'Chat', icon: 'messages-square', shortcut: 'g c', load: () => import('./views/chat/index.js') },
  { id: 'jobs', label: 'Jobs', icon: 'square-kanban', shortcut: 'g j', load: () => import('./views/jobs/index.js') },
  { id: 'schedule', label: 'Schedule', icon: 'calendar-clock', shortcut: 'g s', load: () => import('./views/staffing/index.js') },
  { id: 'calendar', label: 'Calendar', icon: 'calendar', shortcut: 'g k', load: () => import('./views/calendar/index.js') },
  { id: 'tasks', label: 'Tasks', icon: 'square-check-big', shortcut: 'g t', load: () => import('./views/tasks/index.js') },
  { id: 'contacts', label: 'Contacts', icon: 'contact-round', perm: 'inbox', shortcut: 'g p', load: () => import('./views/contacts/index.js') },
  { id: 'reports', label: 'Reports', icon: 'chart-column', perm: 'analytics', shortcut: 'g r', load: () => import('./views/analytics/index.js') },
];

export const BOTTOM_MODULES = [
  { id: 'me', label: 'My day', icon: 'house', shortcut: 'g m', load: () => import('./views/me/index.js') },
  { id: 'settings', label: 'Settings', icon: 'settings', shortcut: 'g ,', load: () => import('./views/settings/index.js') },
];

export const ALL_MODULES = [...MODULES, ...BOTTOM_MODULES];

export function homePath(me) {
  return me && (me.permissions || []).includes('inbox') ? '/inbox' : '/me';
}
