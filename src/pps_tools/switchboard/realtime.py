"""Live updates over Server-Sent Events, plus presence (who is viewing / replying).

Every browser tab holds one ``GET /api/events`` stream. Server code calls ``emit()``;
the event reaches subscribers after the surrounding database transaction commits, so
clients that refetch on an event always see the new rows.

Events are small hints (``{"type": "conversation.changed", "data": {"id": 12}}``);
clients refetch what they display. The broker is in-process, so run a single server
process (threads are fine).
"""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

from pps_tools.switchboard import db

HEARTBEAT_SECONDS = 20
PRESENCE_TTL_SECONDS = 45


@dataclass(eq=False)
class Subscriber:
    user_id: int
    queue: "queue.Queue[str]" = field(default_factory=lambda: queue.Queue(maxsize=2000))
    connected_at: float = field(default_factory=time.time)


class Broker:
    def __init__(self):
        self._lock = threading.Lock()
        self._subs: dict[int, set[Subscriber]] = {}

    def subscribe(self, user_id: int) -> Subscriber:
        sub = Subscriber(user_id)
        with self._lock:
            first = not self._subs.get(user_id)
            self._subs.setdefault(user_id, set()).add(sub)
        if first:
            self.publish("user.online", {"user_id": user_id, "online": True})
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            subs = self._subs.get(sub.user_id)
            if not subs:
                return
            subs.discard(sub)
            last = not subs
            if last:
                del self._subs[sub.user_id]
        if last:
            presence.clear_user(sub.user_id)
            self.publish("user.online", {"user_id": sub.user_id, "online": False})

    def publish(self, type_: str, data: dict | None = None, users: Iterable[int] | None = None) -> None:
        payload = json.dumps({"type": type_, "data": data or {}}, separators=(",", ":"), default=str)
        with self._lock:
            if users is None:
                targets = [s for subs in self._subs.values() for s in subs]
            else:
                wanted = set(users)
                targets = [s for uid in wanted for s in self._subs.get(uid, ())]
        for sub in targets:
            try:
                sub.queue.put_nowait(payload)
            except queue.Full:  # a stuck tab; it will resync on reconnect
                pass

    def online_user_ids(self) -> list[int]:
        with self._lock:
            return sorted(self._subs)

    def reset(self) -> None:
        with self._lock:
            self._subs.clear()


broker = Broker()


def emit(type_: str, data: dict | None = None, users: Iterable[int] | None = None) -> None:
    """Publish once the current transaction commits. ``users`` limits delivery."""
    users = list(users) if users is not None else None
    db.after_commit(lambda: broker.publish(type_, data, users))


def stream(user_id: int):
    """Generator for the SSE response body."""
    sub = broker.subscribe(user_id)
    try:
        yield "retry: 3000\n\n"
        hello = {"type": "hello", "data": {"online": broker.online_user_ids(), "presence": presence.snapshot()}}
        yield f"data: {json.dumps(hello, default=str)}\n\n"
        while True:
            try:
                payload = sub.queue.get(timeout=HEARTBEAT_SECONDS)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            yield f"data: {payload}\n\n"
    finally:
        broker.unsubscribe(sub)


class Presence:
    """Who has which conversation (or job, or draft) open, and what they're doing.

    state: 'viewing' | 'composing' (reply editor open) | 'typing' (comment box)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict[int, dict] = {}

    def update(self, user_id: int, target: str | None, state: str = "viewing", draft_id: int | None = None) -> None:
        with self._lock:
            before = self._entries.get(user_id)
            if target:
                self._entries[user_id] = {
                    "user_id": user_id, "target": target, "state": state,
                    "draft_id": draft_id, "at": time.time(),
                }
            else:
                self._entries.pop(user_id, None)
            after = self._entries.get(user_id)
        changed_targets = {e["target"] for e in (before, after) if e}
        same = before and after and all(before[k] == after[k] for k in ("target", "state", "draft_id"))
        if not same:
            for t in changed_targets:
                broker.publish("presence", {"target": t, "viewers": self.viewers(t)})

    def clear_user(self, user_id: int) -> None:
        self.update(user_id, None)

    def viewers(self, target: str) -> list[dict]:
        cutoff = time.time() - PRESENCE_TTL_SECONDS
        with self._lock:
            return [
                {k: e[k] for k in ("user_id", "state", "draft_id")}
                for e in self._entries.values()
                if e["target"] == target and e["at"] >= cutoff
            ]

    def snapshot(self) -> dict[str, list[dict]]:
        cutoff = time.time() - PRESENCE_TTL_SECONDS
        out: dict[str, list[dict]] = {}
        with self._lock:
            for e in self._entries.values():
                if e["at"] >= cutoff:
                    out.setdefault(e["target"], []).append({k: e[k] for k in ("user_id", "state", "draft_id")})
        return out

    def prune(self) -> None:
        cutoff = time.time() - PRESENCE_TTL_SECONDS
        with self._lock:
            stale = [uid for uid, e in self._entries.items() if e["at"] < cutoff]
        for uid in stale:
            self.update(uid, None)

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()


presence = Presence()
