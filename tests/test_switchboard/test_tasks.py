"""Tasks: assignment, views, conversation links & privacy, due notifications, badges."""

from __future__ import annotations

from datetime import timedelta

from pps_tools.switchboard import db
from pps_tools.switchboard.services import hooks
from pps_tools.switchboard.services import tasks as tasks_svc
from pps_tools.switchboard.util import iso, now
from tests.test_switchboard.test_inbox import make_channel, receive


def test_create_assign_notifies(client, owner, make_user):
    agent, agent_client = make_user("agent")
    task = client.post("/api/tasks", {"title": "Call Dana", "assignee_id": agent["id"], "priority": "high",
                                      "due_at": iso(now() + timedelta(days=1)),
                                      "description": "<p>Ask about <b>grommets</b><script>x</script></p>"})["task"]
    assert task["description"] == "<p>Ask about <b>grommets</b></p>"
    note = agent_client.get("/api/notifications")["items"][0]
    assert note["type"] == "task" and note["link"] == f"/tasks?task={task['id']}"
    assert [t["id"] for t in agent_client.get("/api/tasks")["items"]] == [task["id"]]   # mine
    assert client.get("/api/tasks")["items"] == []                                       # not mine
    assert [t["id"] for t in client.get("/api/tasks?view=created")["items"]] == [task["id"]]


def test_default_assignee_is_creator_and_unassigned_allowed(client, owner):
    t = client.post("/api/tasks", {"title": "Mine"})["task"]
    assert t["assignee_id"] == owner["id"]
    t2 = client.post("/api/tasks", {"title": "Anyone", "assignee_id": None})["task"]
    assert t2["assignee_id"] is None
    assert {x["id"] for x in client.get("/api/tasks?view=all")["items"]} == {t["id"], t2["id"]}


def test_validation(client):
    client.post("/api/tasks", {"title": "  "}, expect=400)
    client.post("/api/tasks", {"title": "x", "priority": "asap"}, expect=400)
    client.post("/api/tasks", {"title": "x", "job_id": 999}, expect=400)
    client.post("/api/tasks", {"title": "x", "due_at": "someday"}, expect=400)
    client.get("/api/tasks?view=bogus", expect=400)


def test_complete_and_reopen(client):
    t = client.post("/api/tasks", {"title": "Restock gloss"})["task"]
    done = client.patch(f"/api/tasks/{t['id']}", {"status": "done"})["task"]
    assert done["completed_at"] and done["completed_by"]
    assert [x["id"] for x in client.get("/api/tasks?view=done")["items"]] == [t["id"]]
    # just-finished tasks stay in "mine" for a day so a check-off doesn't vanish
    assert [x["id"] for x in client.get("/api/tasks")["items"]] == [t["id"]]
    with db.transaction():
        db.update("tasks", t["id"], {"completed_at": iso(now() - timedelta(days=2))})
    assert client.get("/api/tasks")["items"] == []
    again = client.patch(f"/api/tasks/{t['id']}", {"status": "todo"})["task"]
    assert again["completed_at"] is None


def test_domain_hooks_for_webhooks(client, owner, monkeypatch):
    seen = []
    monkeypatch.setattr(hooks, "_handlers", {"*": [lambda event, data: seen.append((event, data))]})
    t = client.post("/api/tasks", {"title": "Proof the menu"})["task"]
    client.patch(f"/api/tasks/{t['id']}", {"title": "Proof the menus"})
    client.patch(f"/api/tasks/{t['id']}", {"status": "done"})
    client.patch(f"/api/tasks/{t['id']}", {"status": "done"})      # no second completion
    events = [e for e, _ in seen if e.startswith("task.")]
    assert events == ["task.created", "task.completed"]
    assert seen[0][1] == {"task_id": t["id"], "assignee_id": owner["id"], "conversation_id": None, "job_id": None, "by": owner["id"]}


def test_overdue_view_and_badge(client, owner):
    client.post("/api/tasks", {"title": "Late", "due_at": iso(now() - timedelta(hours=2))})
    client.post("/api/tasks", {"title": "Later", "due_at": iso(now() + timedelta(days=5))})
    overdue = client.get("/api/tasks?view=overdue")["items"]
    assert [t["title"] for t in overdue] == ["Late"] and overdue[0]["overdue"] is True
    assert client.get("/api/badges")["badges"]["tasks"] == 1
    assert client.get("/api/tasks/counts")["overdue"] == 1


def test_conversation_tasks_and_privacy(client, owner, make_user):
    team = client.post("/api/teams", {"name": "Desk", "member_ids": [owner["id"]]})["team"]
    cid = receive(make_channel(team_id=team["id"]))["conversation_id"]
    task = client.post("/api/tasks", {"title": "Send quote", "conversation_id": cid})["task"]
    assert task["conversation"]["id"] == cid
    timeline = client.get(f"/api/conversations/{cid}")["timeline"]
    assert any(t["type"] == "event" and t["event"] == "task_created" for t in timeline)
    assert [t["id"] for t in client.get(f"/api/tasks?conversation_id={cid}")["items"]] == [task["id"]]
    _, staff = make_user("staff")
    staff.post("/api/tasks", {"title": "Sneaky", "conversation_id": cid}, expect=404)
    staff.get(f"/api/tasks?conversation_id={cid}", expect=404)
    assert all(t["id"] != task["id"] for t in staff.get("/api/tasks?view=all")["items"])
    staff.get(f"/api/tasks/{task['id']}", expect=404)
    client.patch(f"/api/tasks/{task['id']}", {"status": "done"})
    timeline = client.get(f"/api/conversations/{cid}")["timeline"]
    assert any(t["type"] == "event" and t["event"] == "task_completed" for t in timeline)


def test_due_and_overdue_notifications_fire_once(client, owner, make_user):
    agent, agent_client = make_user("agent")
    t = client.post("/api/tasks", {"title": "Deliver samples", "assignee_id": agent["id"],
                                   "due_at": iso(now() + timedelta(minutes=30))})["task"]
    agent_client.post("/api/notifications/read", {})
    assert tasks_svc.process_due() == 1
    assert tasks_svc.process_due() == 0
    with db.transaction():
        db.update("tasks", t["id"], {"due_at": iso(now() - timedelta(minutes=5))})
    assert tasks_svc.process_due() == 1
    assert tasks_svc.process_due() == 0
    titles = [n["title"] for n in agent_client.get("/api/notifications")["items"]]
    assert titles[:2] == ["Overdue: Deliver samples", "Due within the hour: Deliver samples"]
    # moving the due date re-arms the reminders
    client.patch(f"/api/tasks/{t['id']}", {"due_at": iso(now() + timedelta(minutes=20))})
    assert tasks_svc.process_due() == 1


def test_reorder_and_search(client):
    a = client.post("/api/tasks", {"title": "Alpha"})["task"]
    b = client.post("/api/tasks", {"title": "Bravo vinyl"})["task"]
    client.post("/api/tasks/reorder", {"ids": [b["id"], a["id"]]})
    assert [t["id"] for t in client.get("/api/tasks")["items"]] == [b["id"], a["id"]]
    assert [t["id"] for t in client.get("/api/tasks?q=vinyl")["items"]] == [b["id"]]
    items = client.get("/api/search", query_string={"q": "bravo"})["items"]
    assert any(i["type"] == "task" and i["url"] == f"/tasks?task={b['id']}" for i in items)


def test_delete_permissions(client, owner, make_user):
    t = client.post("/api/tasks", {"title": "Owner's"})["task"]
    _, agent = make_user("agent")
    agent.delete(f"/api/tasks/{t['id']}", expect=403)
    _, manager = make_user("manager")
    manager.delete(f"/api/tasks/{t['id']}")
    client.get(f"/api/tasks/{t['id']}", expect=404)


def test_team_view(client, owner, make_user):
    agent, agent_client = make_user("agent")
    client.post("/api/teams", {"name": "Crew", "member_ids": [owner["id"], agent["id"]]})
    t = client.post("/api/tasks", {"title": "For the crew", "assignee_id": agent["id"]})["task"]
    assert [x["id"] for x in client.get("/api/tasks?view=team")["items"]] == [t["id"]]
