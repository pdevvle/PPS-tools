// Live events from the server (Server-Sent Events) plus an in-page event bus.
//
//   const off = on('conversation.changed', (data) => ...);   // server or local events
//   on('*', (type, data) => ...)                             // everything
//   emit('compose', { to: 'x@y.com' })                        // local only
//
// The connection reconnects by itself; on reconnect a 'reconnected' event fires so
// views can refetch anything they may have missed.

const handlers = new Map();
let source = null;
let status = 'idle';
const statusListeners = new Set();
let wasConnected = false;

export function on(type, fn) {
  if (!handlers.has(type)) handlers.set(type, new Set());
  handlers.get(type).add(fn);
  return () => handlers.get(type)?.delete(fn);
}

export function emit(type, data) {
  for (const fn of handlers.get(type) || []) {
    try { fn(data, type); } catch (err) { console.error('event handler failed', type, err); }
  }
  for (const fn of handlers.get('*') || []) {
    try { fn(type, data); } catch (err) { console.error('event handler failed', type, err); }
  }
}

function setStatus(next) {
  status = next;
  statusListeners.forEach((fn) => fn(status));
}

export function connectionStatus() {
  return status;
}

export function onStatus(fn) {
  statusListeners.add(fn);
  return () => statusListeners.delete(fn);
}

export function connect() {
  if (source) return;
  setStatus('connecting');
  source = new EventSource('/api/events');
  source.onopen = () => {
    setStatus('open');
    if (wasConnected) emit('reconnected', {});
    wasConnected = true;
  };
  source.onerror = () => {
    // EventSource retries on its own; a CLOSED state means the server refused us.
    setStatus(source && source.readyState === EventSource.CLOSED ? 'closed' : 'reconnecting');
    if (source && source.readyState === EventSource.CLOSED) {
      source = null;
      setTimeout(connect, 5000);
    }
  };
  source.onmessage = (msg) => {
    let evt;
    try { evt = JSON.parse(msg.data); } catch { return; }
    emit(evt.type, evt.data);
  };
}

export function disconnect() {
  if (source) source.close();
  source = null;
  wasConnected = false;
  setStatus('idle');
}
