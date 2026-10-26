"""Setup, sign-in, people/teams, notifications, files and realtime basics."""

from __future__ import annotations

import io

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.services import notify


def test_setup_then_state(anon):
    state = anon.get("/api/auth/state")
    assert state["setup_required"] is True
    anon.post("/api/auth/setup", {"name": "Ann", "email": "ann@x.test", "password": "longenough1"}, expect=201)
    state = anon.get("/api/auth/state")
    assert state["setup_required"] is False
    assert state["user"]["role"] == "owner"
    # second setup is refused
    anon.post("/api/auth/setup", {"name": "Bob", "email": "bob@x.test", "password": "longenough1"}, expect=409)


def test_login_logout_and_bad_password(app, client):
    from tests.test_switchboard.conftest import ApiClient, OWNER_PASSWORD

    other = ApiClient(app.test_client())
    other.post("/api/auth/login", {"email": "owner@pps.test", "password": "nope"}, expect=401)
    other.post("/api/auth/login", {"email": "OWNER@pps.test", "password": OWNER_PASSWORD}, expect=200)
    assert other.get("/api/me")["me"]["email"] == "owner@pps.test"
    other.post("/api/auth/logout")
    other.get("/api/me", expect=401)


def test_csrf_header_required_for_cookie_writes(client):
    resp = client.c.post("/api/teams", json={"name": "X"})  # no X-Requested-With
    assert resp.status_code == 403
    assert resp.get_json()["error"]["code"] == "csrf"


def test_bootstrap_contains_me_users_settings(client):
    boot = client.get("/api/bootstrap")
    assert boot["me"]["role"] == "owner"
    assert "admin" in boot["me"]["permissions"]
    assert boot["settings"]["org.name"] == "Priority Print Service"
    assert any(u["email"] == "owner@pps.test" for u in boot["users"])


def test_invite_flow(app, client):
    from tests.test_switchboard.conftest import ApiClient

    res = client.post("/api/users", {"email": "new@pps.test", "name": "New Person", "role": "staff"}, expect=201)
    url = res["invite_url"]
    tok = url.rsplit("/", 1)[1]
    guest = ApiClient(app.test_client())
    assert guest.get(f"/api/auth/invite/{tok}")["email"] == "new@pps.test"
    guest.post(f"/api/auth/invite/{tok}", {"password": "short"}, expect=400)
    me = guest.post(f"/api/auth/invite/{tok}", {"password": "a-good-password"}, expect=200)["me"]
    assert me["role"] == "staff"
    assert "inbox" not in me["permissions"]
    guest.get(f"/api/auth/invite/{tok}", expect=404)  # single use


def test_roles_are_enforced(make_user):
    _, staff = make_user("staff")
    staff.post("/api/teams", {"name": "Nope"}, expect=403)
    staff.post("/api/users", {"email": "x@y.test", "name": "X"}, expect=403)


def test_last_owner_cannot_be_demoted(client, owner):
    client.patch(f"/api/users/{owner['id']}", {"role": "agent"}, expect=400)


def test_password_change_signs_out_other_sessions(app, client):
    from tests.test_switchboard.conftest import ApiClient, OWNER_PASSWORD

    second = ApiClient(app.test_client())
    second.post("/api/auth/login", {"email": "owner@pps.test", "password": OWNER_PASSWORD})
    client.post("/api/auth/password", {"current": OWNER_PASSWORD, "new": "another-password"})
    client.get("/api/me")             # this session stays signed in
    second.get("/api/me", expect=401)  # the other one is signed out


def test_teams_crud(client, make_user):
    u, _ = make_user("agent")
    team = client.post("/api/teams", {"name": "Front Desk", "member_ids": [u["id"]]}, expect=201)["team"]
    assert team["member_ids"] == [u["id"]]
    client.patch(f"/api/teams/{team['id']}", {"assignment_mode": "round_robin"})
    teams = {t["name"]: t for t in client.get("/api/teams")["items"]}
    assert teams["Front Desk"]["assignment_mode"] == "round_robin"
    assert "Front Office" in teams  # created with the workspace
    client.delete(f"/api/teams/{team['id']}")
    assert [t["name"] for t in client.get("/api/teams")["items"]] == ["Front Office"]


def test_notifications_roundtrip(client, owner, make_user):
    other, other_client = make_user("agent")
    with db.transaction():
        notify.notify([other["id"]], "system", "Hello", actor_id=owner["id"])
    res = other_client.get("/api/notifications")
    assert res["unread_count"] == 1
    assert res["items"][0]["title"] == "Hello"
    other_client.post("/api/notifications/read", {})
    assert other_client.get("/api/notifications")["unread_count"] == 0


def test_file_upload_download_and_access(client, make_user):
    resp = client.raw("post", "/api/files", data={"files": (io.BytesIO(b"hello world"), "note.txt")},
                      content_type="multipart/form-data")
    assert resp.status_code == 201
    att = resp.get_json()["items"][0]
    dl = client.raw("get", att["url"])
    assert dl.status_code == 200 and dl.data == b"hello world"
    assert "sandbox" in dl.headers["Content-Security-Policy"]
    # unowned uploads are private to the uploader
    _, other = make_user("agent")
    assert other.raw("get", att["url"]).status_code == 404


def test_html_upload_is_never_served_inline(client):
    resp = client.raw("post", "/api/files", data={"files": (io.BytesIO(b"<script>alert(1)</script>"), "x.html")},
                      content_type="multipart/form-data")
    att = resp.get_json()["items"][0]
    dl = client.raw("get", att["url"])
    assert dl.headers["Content-Disposition"].startswith("attachment")


def test_realtime_events_wait_for_commit(app):
    sub = realtime.broker.subscribe(42)
    assert '"user.online"' in sub.queue.get_nowait()  # everyone hears about the new tab
    try:
        with db.transaction():
            realtime.emit("thing.changed", {"id": 1}, users=[42])
            assert sub.queue.empty()  # not before commit
        payload = sub.queue.get_nowait()
        assert '"thing.changed"' in payload
        with db.transaction():
            realtime.emit("rolled.back", {}, users=[42])
            db.execute("SELECT 1")
            try:
                with db.transaction():
                    raise RuntimeError
            except RuntimeError:
                pass
        # the outer transaction committed, so the event goes out
        assert '"rolled.back"' in sub.queue.get_nowait()
        try:
            with db.transaction():
                realtime.emit("never.sent", {}, users=[42])
                raise ValueError
        except ValueError:
            pass
        assert sub.queue.empty()
    finally:
        realtime.broker.unsubscribe(sub)


def test_presence_updates(client, owner):
    client.post("/api/presence", {"target": "conversation:5", "state": "composing"})
    viewers = realtime.presence.viewers("conversation:5")
    assert viewers == [{"user_id": owner["id"], "state": "composing", "draft_id": None}]
    client.post("/api/presence", {"target": None})
    assert realtime.presence.viewers("conversation:5") == []


def test_spa_fallback_and_api_404(client):
    page = client.raw("get", "/inbox/inbox")
    assert page.status_code == 200 and b"<div id=\"app\"" in page.data
    assert client.raw("get", "/api/nope").status_code == 404


def _failed_logins_from_spoofed_ips(api, count):
    """Wrong-password sign-ins, each claiming a different X-Forwarded-For address."""
    codes = []
    for i in range(count):
        resp = api.raw("post", "/api/auth/login", json={"email": f"nobody{i}@pps.test", "password": "wrong-password"},
                       headers={"X-Forwarded-For": f"203.0.113.{i}"})
        codes.append(resp.status_code)
    return codes


def test_forwarded_for_is_ignored_unless_a_proxy_is_configured(app, client):
    from pps_tools.switchboard.api import auth as auth_api
    from tests.test_switchboard.conftest import ApiClient

    auth_api._failures.clear()
    try:
        # Faking X-Forwarded-For must not dodge the per-address sign-in throttle.
        codes = _failed_logins_from_spoofed_ips(ApiClient(app.test_client()), auth_api.MAX_FAILURES + 1)
        assert codes[-1] == 429 and set(codes[:-1]) == {401}

        # Behind a configured proxy the forwarded address is the client's real one.
        auth_api._failures.clear()
        app.extensions["switchboard"].proxy_count = 1
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
        codes = _failed_logins_from_spoofed_ips(ApiClient(app.test_client()), auth_api.MAX_FAILURES + 1)
        assert set(codes) == {401}
    finally:
        auth_api._failures.clear()
