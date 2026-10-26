// Panels in the conversation's right sidebar, contributed by other modules. Each is a
// named export receiving { conversation, contact, detail, reload } where `detail` is
// the full GET /api/conversations/:id payload. Missing files are skipped.

export const PANELS = [
  { id: 'contact', load: () => import('../contacts/panels.js'), name: 'ContactPanel' },
  { id: 'jobs', load: () => import('../jobs/panels.js'), name: 'ConversationJobsPanel' },
  { id: 'tasks', load: () => import('../tasks/panels.js'), name: 'ConversationTasksPanel' },
  { id: 'integrations', load: () => import('../admin/panels.js'), name: 'IntegrationsPanel' },
];
