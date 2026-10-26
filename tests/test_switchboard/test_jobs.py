"""Jobs: defaults, numbering, permissions, stages, operations & conflicts, the
auto-scheduler, conversation links and the customer proof page."""

from __future__ import annotations

import io
from datetime import datetime, time, timedelta

import pytest

from pps_tools.switchboard import db
from pps_tools.switchboard.services import hooks, inbox, settings
from pps_tools.switchboard.services import jobs as jobs_svc
from pps_tools.switchboard.services.inbox import Inbound
from pps_tools.switchboard.util import iso, now, now_iso, token


def next_monday(hour=7, minute=0, weeks=0):
    tz = settings.timezone()
    d = now().astimezone(tz).date() + timedelta(days=1)
    while d.weekday() != 0:
        d += timedelta(days=1)
    d += timedelta(weeks=weeks)
    return datetime.combine(d, time(hour, minute), tzinfo=tz)


def at(base, **delta):
    return iso(base + timedelta(**delta))


def boot(client):
    b = client.get("/api/bootstrap")
    return {
        "stages": {s["name"]: s for s in b["job_stages"]},
        "resources": {r["name"]: r for r in b["resources"]},
        "templates": {t["name"]: t for t in b["job_templates"]},
        "skills": {s["name"]: s for s in b["job_skills"]},
    }


def new_job(client, **data):
    data.setdefault("title", "Test job")
    return client.post("/api/jobs", data, expect=201)["job"]


def make_conversation(team_id=None, sender="cust@x.test", subject="Need 500 flyers"):
    with db.transaction():
        cid = db.insert("channels", {
            "type": "email", "name": "Orders", "address": f"orders{token(4)}@shop.test", "visibility": "shared",
            "team_id": team_id, "config_json": db.jdump({"demo": True}), "public_key": token(8), "created_at": now_iso(),
        })
    ch = db.one("SELECT * FROM channels WHERE id = ?", cid)
    msg = inbox.deliver_inbound(Inbound(channel=ch, kind="email", from_handle=sender, from_name="Cara Customer",
                                        subject=subject, body_text="Can you print these?", external_id=f"<{token(6)}@x>"))
    return msg["conversation_id"]


def test_workspace_defaults(client):
    b = boot(client)
    assert list(b["stages"]) == ["Quote", "Approved", "Prepress", "Proofing", "Printing", "Finishing",
                                 "Ready for pickup", "Delivered"]
    assert b["stages"]["Delivered"]["is_done"] is True
    assert "Digital Press 1" in b["resources"] and "Delivery Van" in b["resources"]
    assert {"Business cards", "Trifold brochure", "Saddle-stitched booklet", "Vinyl banner", "Menus"} <= set(b["templates"])
    fields = {f["key"]: f for f in client.get("/api/bootstrap")["job_fields"]}
    assert fields["ink"]["options"] == ["4/4", "4/0", "1/1", "1/0"]


def test_numbering_is_sequential_and_skips_taken(client):
    a = new_job(client)
    b = new_job(client)
    assert (a["number"], b["number"]) == ("J-1001", "J-1002")
    with db.transaction():
        db.execute("UPDATE jobs SET number = 'J-1003' WHERE id = ?", b["id"])
    assert new_job(client)["number"] == "J-1004"
    client.patch("/api/settings", {"jobs.number_prefix": "PPS-"})
    assert new_job(client)["number"] == "PPS-1005"


def test_create_from_template_copies_steps_checklist_and_specs(client):
    b = boot(client)
    job = new_job(client, template_id=b["templates"]["Business cards"]["id"], specs={"paper_stock": "18pt soft-touch"},
                  quantity=500, due_at=at(next_monday(), hours=8))
    detail = client.get(f"/api/jobs/{job['id']}")
    assert job["title"] == "Test job"
    assert [o["name"] for o in detail["operations"]] == ["Prepress", "Print", "Cut", "Pack"]
    assert detail["operations"][1]["resource_id"] == b["resources"]["Digital Press 1"]["id"]
    assert len(detail["checklist"]) == 5
    assert detail["job"]["specs"]["paper_stock"] == "18pt soft-touch"
    assert detail["job"]["specs"]["finished_size"] == "3.5 × 2 in"
    assert detail["estimate_minutes"] == 90
    assert detail["job"]["stage_id"] == b["stages"]["Quote"]["id"]


def test_permissions_for_staff(client, make_user):
    staff, staff_client = make_user("staff")
    other_staff, other_client = make_user("staff")
    b = boot(client)
    job = new_job(client, template_id=b["templates"]["Business cards"]["id"], assignee_ids=[staff["id"]])
    staff_client.post("/api/jobs", {"title": "Nope"}, expect=403)
    staff_client.patch(f"/api/jobs/{job['id']}", {"title": "Nope"}, expect=403)
    staff_client.post(f"/api/jobs/{job['id']}/move", {"stage_id": b["stages"]["Printing"]["id"]}, expect=403)
    # can see and comment
    assert staff_client.get("/api/jobs")["total"] == 1
    staff_client.post(f"/api/jobs/{job['id']}/comments", {"body": "<p>On it</p>"}, expect=201)
    other_client.post(f"/api/jobs/{job['id']}/comments", {"body": "<p>Me too</p>"}, expect=201)
    # tick checklist only when on the job
    item = client.get(f"/api/jobs/{job['id']}")["checklist"][0]
    staff_client.patch(f"/api/job-checklist/{item['id']}", {"is_done": True})
    other_client.patch(f"/api/job-checklist/{item['id']}", {"is_done": False}, expect=403)
    staff_client.patch(f"/api/job-checklist/{item['id']}", {"title": "Renamed"}, expect=403)
    # operations: status yes, schedule no
    op = client.get(f"/api/jobs/{job['id']}")["operations"][0]
    staff_client.patch(f"/api/operations/{op['id']}", {"status": "in_progress"})
    staff_client.patch(f"/api/operations/{op['id']}", {"start_at": at(next_monday())}, expect=403)
    other_client.patch(f"/api/operations/{op['id']}", {"status": "done"}, expect=403)
    done = staff_client.patch(f"/api/operations/{op['id']}", {"status": "done"})["operation"]
    assert done["status"] == "done" and done["completed_by"] == staff["id"]


def test_stage_moves_complete_notify_and_fire_hooks(client, owner, make_user):
    agent, agent_client = make_user("agent")
    b = boot(client)
    job = new_job(client, assignee_ids=[agent["id"]])
    seen = []

    def on_change(payload):
        seen.append(payload)

    hooks.on("job.completed", on_change)
    try:
        client.post(f"/api/jobs/{job['id']}/move", {"stage_id": b["stages"]["Delivered"]["id"]})
    finally:
        hooks.off("job.completed", on_change)
    moved = client.get(f"/api/jobs/{job['id']}")
    assert moved["job"]["is_done"] is True and moved["job"]["completed_at"]
    events = [a for a in moved["activity"] if a["type"] == "stage_changed"]
    assert events[-1]["data"]["to"] == "Delivered"
    assert seen and seen[0]["job_id"] == job["id"]
    titles = [n["title"] for n in agent_client.get("/api/notifications")["items"]]
    assert any("moved to Delivered" in t for t in titles)
    assert any("put you on" in t for t in titles)
    client.post(f"/api/jobs/{job['id']}/move", {"stage_id": b["stages"]["Printing"]["id"]})
    assert client.get(f"/api/jobs/{job['id']}")["job"]["completed_at"] is None


def test_board_order_positions_and_wip(client):
    b = boot(client)
    quote = b["stages"]["Quote"]["id"]
    j1, j2, j3 = (new_job(client, title=f"Job {i}") for i in range(3))
    client.post(f"/api/jobs/{j3['id']}/move", {"stage_id": quote, "position": 0})
    board = client.get("/api/jobs/board")
    col = next(s for s in board["stages"] if s["id"] == quote)
    assert [j["id"] for j in col["jobs"]] == [j3["id"], j1["id"], j2["id"]]
    client.post(f"/api/jobs/{j1['id']}/move", {"stage_id": quote, "position": 2})
    col = next(s for s in client.get("/api/jobs/board")["stages"] if s["id"] == quote)
    assert [j["id"] for j in col["jobs"]] == [j3["id"], j2["id"], j1["id"]]
    client.patch(f"/api/job-stages/{quote}", {"wip_limit": 2})
    res = client.post(f"/api/jobs/{j1['id']}/move", {"stage_id": quote, "position": 0})
    assert res["job"]["wip_exceeded"] is True
    col = next(s for s in client.get("/api/jobs/board")["stages"] if s["id"] == quote)
    assert col["over_wip"] is True


def test_list_filters_and_search(client, owner):
    b = boot(client)
    new_job(client, title="Banner for the fair", priority="rush", due_at=at(now(), hours=5), assignee_ids=[owner["id"]])
    new_job(client, title="Postcards", specs={"paper_stock": "matte cover"})
    assert [j["title"] for j in client.get("/api/jobs", query_string={"q": "banner"})["items"]] == ["Banner for the fair"]
    assert [j["title"] for j in client.get("/api/jobs", query_string={"q": "matte"})["items"]] == ["Postcards"]
    assert client.get("/api/jobs", query_string={"priority": "rush"})["total"] == 1
    assert client.get("/api/jobs", query_string={"mine": 1})["total"] == 1
    mine = client.get("/api/jobs", query_string={"mine": 1})["items"][0]
    assert mine["due_state"] == "soon"
    found = client.get("/api/search", query_string={"q": "J-100"})["items"]
    assert {i["type"] for i in found} >= {"job"}
    assert client.get("/api/badges")["badges"]["jobs"] == 1
    assert b  # stages exist


def test_create_from_conversation_links_and_respects_visibility(client, owner, make_user):
    team = client.post("/api/teams", {"name": "Desk", "member_ids": [owner["id"]]})["team"]
    cid = make_conversation(team_id=team["id"])
    job = new_job(client, conversation_id=cid, title="")
    assert job["title"] == "Need 500 flyers"
    assert job["contact"]["display_name"] == "Cara Customer"
    timeline = client.get(f"/api/conversations/{cid}")["timeline"]
    assert any(t["type"] == "event" and t["event"] == "job_linked" for t in timeline)
    assert client.get(f"/api/conversations/{cid}/jobs")["jobs"][0]["id"] == job["id"]
    # an agent outside the team can see the job but not the conversation
    _, outsider = make_user("agent")
    detail = outsider.get(f"/api/jobs/{job['id']}")
    assert detail["conversations"] == [] and detail["hidden_conversation_count"] == 1
    outsider.post("/api/jobs", {"title": "x", "conversation_id": cid}, expect=404)
    outsider.get(f"/api/conversations/{cid}/jobs", expect=404)
    outsider.post(f"/api/jobs/{job['id']}/conversations", {"conversation_id": cid}, expect=404)
    # unlink / relink
    client.delete(f"/api/jobs/{job['id']}/conversations/{cid}")
    assert client.get(f"/api/conversations/{cid}/jobs")["jobs"] == []
    assert client.post(f"/api/jobs/{job['id']}/conversations", {"conversation_id": cid})["linked"] is True


def test_schedule_conflicts(client, owner, make_user):
    alex, _ = make_user("staff", name="Alex Press")
    b = boot(client)
    press = b["resources"]["Digital Press 1"]["id"]
    monday = next_monday(9)
    a = new_job(client, title="A", due_at=at(monday, hours=1))
    c = new_job(client, title="C")
    op_a1 = client.post(f"/api/jobs/{a['id']}/operations", {"name": "Prep", "duration_minutes": 60}, expect=201)["operation"]
    op_a2 = client.post(f"/api/jobs/{a['id']}/operations", {"name": "Print", "resource_id": press, "user_id": alex["id"],
                                                            "duration_minutes": 120}, expect=201)["operation"]
    op_c = client.post(f"/api/jobs/{c['id']}/operations", {"name": "Print", "resource_id": press, "user_id": alex["id"],
                                                          "duration_minutes": 60}, expect=201)["operation"]
    client.patch(f"/api/operations/{op_a1['id']}", {"start_at": at(monday), "end_at": at(monday, hours=1)})
    client.patch(f"/api/operations/{op_a2['id']}", {"start_at": at(monday, minutes=30)})  # before prep ends
    client.patch(f"/api/operations/{op_c['id']}", {"start_at": at(monday, hours=1)})
    sched = client.get("/api/schedule", query_string={"start": at(monday, hours=-9), "end": at(monday, hours=15)})
    blocks = {blk["id"]: blk for blk in sched["blocks"]}
    codes = {c["code"] for c in blocks[op_a2["id"]]["conflicts"]}
    assert {"resource_busy", "person_busy", "sequence", "after_due"} <= codes
    assert "off_shift" not in codes  # no shift data at all -> not checked
    assert blocks[op_a2["id"]]["end_at"] == at(monday, hours=2, minutes=30)
    # with shift data, working outside a shift is flagged; time off too
    with db.transaction():
        db.insert("shifts", {"user_id": alex["id"], "start_at": at(monday, hours=-2), "end_at": at(monday, hours=1),
                             "status": "published", "created_at": now_iso()})
        db.insert("time_off_requests", {"user_id": alex["id"], "kind": "personal", "start_date": monday.date().isoformat(),
                                        "end_date": monday.date().isoformat(), "start_time": "10:30", "end_time": "12:00",
                                        "status": "approved", "created_at": now_iso()})
    sched = client.get("/api/schedule", query_string={"start": at(monday, hours=-9), "end": at(monday, hours=15), "group": "user"})
    blocks = {blk["id"]: blk for blk in sched["blocks"]}
    codes_c = {c["code"] for c in blocks[op_c["id"]]["conflicts"]}
    assert {"off_shift", "time_off"} <= codes_c
    assert any(r["id"] == alex["id"] for r in sched["rows"])
    assert sched["shifts"] and sched["time_off"]
    # unscheduling empties it from the board and puts it in the queue
    client.patch(f"/api/operations/{op_c['id']}", {"start_at": None})
    sched = client.get("/api/schedule", query_string={"start": at(monday, hours=-9), "end": at(monday, hours=15)})
    assert op_c["id"] not in {blk["id"] for blk in sched["blocks"]}
    assert op_c["id"] in {q["id"] for q in sched["queue"]}


def test_auto_scheduler_places_in_order_on_free_time(client, make_user):
    b = boot(client)
    monday = next_monday(7)
    press = b["resources"]["Digital Press 1"]["id"]
    tmpl = b["templates"]["Business cards"]["id"]
    urgent = new_job(client, title="Urgent", template_id=tmpl, due_at=at(monday, hours=6))
    later = new_job(client, title="Later", template_id=tmpl, due_at=at(monday, days=3))
    # the press is already busy first thing Monday
    blocker = new_job(client, title="Blocker")
    op = client.post(f"/api/jobs/{blocker['id']}/operations", {"name": "Print", "resource_id": press,
                                                              "duration_minutes": 120}, expect=201)["operation"]
    client.patch(f"/api/operations/{op['id']}", {"start_at": at(monday)})
    plan = client.post("/api/schedule/auto", {"from": at(monday), "apply": False})
    assert plan["applied"] is False
    by_job = {}
    for p in plan["placements"]:
        by_job.setdefault(p["job_id"], []).append(p)
    urgent_steps = by_job[urgent["id"]]
    assert [p["name"] for p in urgent_steps] == ["Prepress", "Print", "Cut", "Pack"]
    for prev, nxt in zip(urgent_steps, urgent_steps[1:]):
        assert nxt["start_at"] >= prev["end_at"]
    urgent_print = urgent_steps[1]
    assert urgent_print["start_at"] >= at(monday, hours=2)  # waits for the blocker
    later_print = by_job[later["id"]][1]
    assert later_print["start_at"] >= urgent_print["end_at"]  # urgent first on the shared press
    # nothing written yet
    assert all(o["start_at"] is None for o in client.get(f"/api/jobs/{urgent['id']}")["operations"])
    applied = client.post("/api/schedule/auto", {"from": at(monday), "apply": True})
    assert applied["applied"] is True
    assert all(o["start_at"] for o in client.get(f"/api/jobs/{urgent['id']}")["operations"])
    again = client.post("/api/schedule/auto", {"from": at(monday), "apply": True})
    assert again["placements"] == []


def test_auto_scheduler_uses_skills_and_shifts(client, make_user):
    b = boot(client)
    monday = next_monday(7)
    cutter, _ = make_user("staff", name="Cutter Pro")
    skill = b["skills"]["Cutting"]["id"]
    with db.transaction():
        db.execute("INSERT INTO staff_skills (user_id, skill_id, level) VALUES (?, ?, 2)", cutter["id"], skill)
        # only working Monday afternoon
        db.insert("shifts", {"user_id": cutter["id"], "start_at": at(monday, hours=6), "end_at": at(monday, hours=10),
                             "status": "published", "created_at": now_iso()})
    job = new_job(client, title="Cut job", due_at=at(monday, days=2))
    client.post(f"/api/jobs/{job['id']}/operations", {"name": "Cut", "skill_id": skill, "duration_minutes": 60})
    plan = client.post("/api/schedule/auto", {"from": at(monday), "job_ids": [job["id"]]})
    [p] = plan["placements"]
    assert p["user_id"] == cutter["id"]
    assert p["start_at"] == at(monday, hours=6)


def test_proof_page_approve_and_changes(client, anon, owner, make_user):
    agent, agent_client = make_user("agent")
    job = new_job(client, title="Wedding invites", assignee_ids=[agent["id"]])
    resp = client.raw("post", "/api/files", data={"files": (io.BytesIO(b"%PDF-1.4 proof"), "proof.pdf")},
                      content_type="multipart/form-data")
    att = resp.get_json()["items"][0]
    files_ = client.post(f"/api/jobs/{job['id']}/files", {"attachment_ids": [att["id"]], "is_proof": True})["files"]
    assert files_[0]["is_proof"] is True
    shared = client.post(f"/api/jobs/{job['id']}/share")
    tok = shared["public_token"]
    assert shared["url"].endswith(f"/public/jobs/{tok}")
    page = anon.raw("get", f"/public/jobs/{tok}")
    assert page.status_code == 200 and b"Wedding invites" in page.data and b"proof.pdf" in page.data
    # the proof file is reachable without signing in through its token URL
    proof_url = jobs_svc.public_proofs(jobs_svc.get(job["id"]))[0]["url"]
    assert anon.raw("get", proof_url).status_code == 200
    # request changes without a note -> back to the page with an error
    r = anon.raw("post", f"/public/jobs/{tok}/changes", data={"name": "Grace", "comment": ""})
    assert r.status_code == 303 and "error=comment" in r.headers["Location"]
    r = anon.raw("post", f"/public/jobs/{tok}/changes", data={"name": "Grace", "comment": "Make the names bigger"})
    assert r.status_code == 303 and "done=changes" in r.headers["Location"]
    assert jobs_svc.get(job["id"])["proof_status"] == "changes_requested"
    r = anon.raw("post", f"/public/jobs/{tok}/approve", json={"name": "Grace"})
    assert r.status_code == 200 and r.get_json()["status"] == "approved"
    detail = client.get(f"/api/jobs/{job['id']}")
    assert detail["job"]["proof_status"] == "approved" and detail["job"]["proof_decided_by"] == "Grace"
    assert {"changes_requested", "proof_approved"} <= {a["type"] for a in detail["activity"]}
    titles = [n["title"] for n in agent_client.get("/api/notifications")["items"]]
    assert any("approved the proof" in t for t in titles) and any("requested changes" in t for t in titles)
    client.delete(f"/api/jobs/{job['id']}/share")
    assert anon.raw("get", f"/public/jobs/{tok}").status_code == 404
    assert anon.raw("get", "/public/jobs/nope").status_code == 404


def test_due_alerts_fire_once(client, make_user):
    staff, staff_client = make_user("staff")
    job = new_job(client, title="Soon", due_at=at(now(), hours=3), assignee_ids=[staff["id"]])
    assert jobs_svc.notify_due() == 1
    assert jobs_svc.notify_due() == 0
    with db.transaction():
        db.update("jobs", job["id"], {"due_at": at(now(), hours=-1)})
    assert jobs_svc.notify_due() == 1
    titles = [n["title"] for n in staff_client.get("/api/notifications")["items"]]
    assert any(t.startswith("Overdue:") for t in titles) and any(t.startswith("Due soon:") for t in titles)
    assert staff_client.get("/api/badges")["badges"]["jobs"] == 1


def test_comment_mentions_notify(client, owner, make_user):
    staff, staff_client = make_user("staff")
    job = new_job(client)
    client.post(f"/api/jobs/{job['id']}/comments",
                {"body": f'<p>Check this <span data-mention="{staff["id"]}">@x</span> <img src=x onerror=alert(1)></p>'})
    note = staff_client.get("/api/notifications")["items"][0]
    assert note["type"] == "mention" and note["link"] == f"/jobs/{job['id']}"
    body = client.get(f"/api/jobs/{job['id']}")["activity"][-1]["body"]
    assert "onerror" not in body


def test_stage_delete_requires_destination(client):
    b = boot(client)
    job = new_job(client, stage_id=b["stages"]["Proofing"]["id"])
    r = client.raw("delete", f"/api/job-stages/{b['stages']['Proofing']['id']}")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "stage_in_use"
    client.delete(f"/api/job-stages/{b['stages']['Proofing']['id']}?move_to={b['stages']['Printing']['id']}")
    assert client.get(f"/api/jobs/{job['id']}")["job"]["stage_id"] == b["stages"]["Printing"]["id"]


def test_templates_crud_and_from_job(client):
    b = boot(client)
    job = new_job(client, template_id=b["templates"]["Menus"]["id"])
    t = client.post("/api/job-templates", {"from_job_id": job["id"], "name": "Menus (copy)"}, expect=201)["template"]
    assert [o["name"] for o in t["operations"]][:2] == ["Prepress", "Print"]
    client.patch(f"/api/job-templates/{t['id']}", {"operations": [{"name": "Only step", "duration_minutes": 15}]})
    assert client.get(f"/api/job-templates/{t['id']}")["template"]["operations"][0]["duration_minutes"] == 15
    client.delete(f"/api/job-templates/{t['id']}")
    client.get(f"/api/job-templates/{t['id']}", expect=404)


def test_demo_seed_builds_a_working_board(app):
    from pps_tools.switchboard.api import inbox as inbox_api
    from pps_tools.switchboard.api import jobs as jobs_api
    from pps_tools.switchboard.demo.inbox import seed_inbox
    from pps_tools.switchboard.demo.jobs import seed_jobs
    from pps_tools.switchboard.seed import SeedContext, seed_core

    ctx = SeedContext()
    with db.transaction():
        seed_core(ctx)
        inbox_api.on_setup({"owner_id": ctx.uid("owner"), "demo": True})
        jobs_api.on_setup({"owner_id": ctx.uid("owner"), "demo": True})
        seed_inbox(ctx)
        seed_jobs(ctx)
    assert db.scalar("SELECT COUNT(*) FROM jobs") >= 14
    linked = db.scalar("SELECT COUNT(*) FROM job_conversations")
    assert linked >= 4
    from pps_tools.switchboard.services import scheduling

    start = now() - timedelta(days=3)
    sched = scheduling.board(iso(start), iso(start + timedelta(days=10)), "user")
    assert sched["blocks"] and sched["queue"]
    assert any(blk["conflicts"] for blk in sched["blocks"])  # the demo has one double-booking to fix
    assert db.one("SELECT public_token FROM jobs WHERE public_token IS NOT NULL")
