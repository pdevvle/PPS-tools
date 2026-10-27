// JSON API client. Every call sends X-Requested-With (the server's CSRF check).
//
//   const { items } = await api.get('/conversations', { mailbox: 'inbox' });
//   await api.post('/conversations/actions', { ids: [1], action: 'close' });
//
// Paths are relative to /api. Errors throw ApiError with .status, .code, .message.

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message || code || 'Request failed');
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let onUnauthorized = null;
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

function buildUrl(path, query) {
  let url = path.startsWith('/api/') || path.startsWith('http') ? path : '/api' + (path.startsWith('/') ? path : '/' + path);
  if (query) {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === '' || v === false) continue;
      if (Array.isArray(v)) v.forEach((item) => params.append(k, item));
      else params.append(k, v === true ? '1' : String(v));
    }
    const qs = params.toString();
    if (qs) url += (url.includes('?') ? '&' : '?') + qs;
  }
  return url;
}

export async function request(path, { method = 'GET', body, query, signal, headers = {}, raw = false } = {}) {
  const init = {
    method,
    signal,
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'switchboard', Accept: 'application/json', ...headers },
  };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(buildUrl(path, query), init);
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new ApiError(0, 'network', "Can't reach the server. Check your connection.");
  }
  if (raw) return res;
  let data = null;
  const type = res.headers.get('Content-Type') || '';
  if (type.includes('application/json')) {
    try { data = await res.json(); } catch { data = null; }
  }
  if (!res.ok) {
    const err = (data && data.error) || {};
    if (res.status === 401 && onUnauthorized) onUnauthorized();
    throw new ApiError(res.status, err.code || 'http_' + res.status, err.message || res.statusText, err.details);
  }
  return data;
}

export const api = {
  request,
  get: (path, query, opts = {}) => request(path, { ...opts, query }),
  post: (path, body, opts = {}) => request(path, { ...opts, method: 'POST', body: body ?? {} }),
  put: (path, body, opts = {}) => request(path, { ...opts, method: 'PUT', body: body ?? {} }),
  patch: (path, body, opts = {}) => request(path, { ...opts, method: 'PATCH', body: body ?? {} }),
  del: (path, body, opts = {}) => request(path, { ...opts, method: 'DELETE', body }),
  url: buildUrl,

  // Upload File objects; resolves to [{id, filename, url, ...}].
  async upload(fileList, { inline = false } = {}) {
    const form = new FormData();
    for (const f of fileList) form.append('files', f, f.name);
    if (inline) form.append('inline', '1');
    const res = await request('/files', { method: 'POST', body: form });
    return res.items;
  },
};

export default api;
