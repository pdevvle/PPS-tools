"""Fixtures for Switchboard API tests: a fresh workspace per test, signed-in clients."""

from __future__ import annotations

import itertools

import pytest

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.app import create_app
from pps_tools.switchboard.config import Config

OWNER_PASSWORD = "correct-horse-battery"


class ApiClient:
    """Flask test client that sends JSON and the CSRF header, and raises on surprises."""

    def __init__(self, flask_client):
        self.c = flask_client

    def _call(self, method, path, json=None, expect=None, **kwargs):
        headers = kwargs.pop("headers", {})
        headers.setdefault("X-Requested-With", "test")
        resp = getattr(self.c, method)(path, json=json, headers=headers, **kwargs)
        if expect is not None:
            assert resp.status_code == expect, f"{method.upper()} {path} -> {resp.status_code}: {resp.get_data(as_text=True)[:800]}"
        return resp

    def get(self, path, expect=200, **kw):
        return self._call("get", path, expect=expect, **kw).get_json()

    def post(self, path, json=None, expect=(200, 201), **kw):
        resp = self._call("post", path, json=json or {}, **kw)
        if expect is not None:
            ok = resp.status_code in expect if isinstance(expect, tuple) else resp.status_code == expect
            assert ok, f"POST {path} -> {resp.status_code}: {resp.get_data(as_text=True)[:800]}"
        return resp.get_json()

    def patch(self, path, json=None, expect=200, **kw):
        return self._call("patch", path, json=json or {}, expect=expect, **kw).get_json()

    def put(self, path, json=None, expect=200, **kw):
        return self._call("put", path, json=json or {}, expect=expect, **kw).get_json()

    def delete(self, path, expect=200, **kw):
        return self._call("delete", path, expect=expect, **kw).get_json()

    def raw(self, method, path, **kw):
        return self._call(method, path, **kw)


@pytest.fixture
def app(tmp_path):
    realtime.broker.reset()
    realtime.presence.reset()
    cfg = Config(data_dir=tmp_path, secret_key="test-secret", base_url="http://testserver",
                 testing=True, start_worker=False)
    application = create_app(cfg)
    with application.app_context():
        yield application
    db.close()


@pytest.fixture
def anon(app):
    return ApiClient(app.test_client())


@pytest.fixture
def client(app):
    """Signed in as the workspace owner (created through the real setup flow)."""
    api = ApiClient(app.test_client())
    api.post("/api/auth/setup", {
        "org_name": "Priority Print Service",
        "name": "Olivia Owner",
        "email": "owner@pps.test",
        "password": OWNER_PASSWORD,
        "timezone": "America/Phoenix",
    }, expect=201)
    return api


@pytest.fixture
def owner(client):
    return client.get("/api/me")["me"]


_counter = itertools.count(1)


@pytest.fixture
def make_user(app, client):
    """make_user(role='agent', **fields) -> (user dict, ApiClient signed in as them)."""

    def _make(role="agent", name=None, **fields):
        n = next(_counter)
        email = fields.pop("email", f"user{n}@pps.test")
        res = client.post("/api/users", {
            "email": email,
            "name": name or f"{role.title()} {n}",
            "role": role,
            "password": "password-123",
            "send_invite": False,
            **fields,
        }, expect=201)
        other = ApiClient(app.test_client())
        other.post("/api/auth/login", {"email": email, "password": "password-123"}, expect=200)
        return res["user"], other

    return _make
