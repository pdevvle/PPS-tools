"""Contacts: CRUD, handles, merge, organizations, groups, CSV, blocking, search."""

from __future__ import annotations

import io

from pps_tools.switchboard.services import inbox
from tests.test_switchboard.test_inbox import make_channel, receive


def create(client, **fields):
    return client.post("/api/contacts", fields, expect=201)["contact"]


def test_create_list_and_search(client):
    c = create(client, name="Lena Ortiz", emails=["Lena@Cafe.test"], phones=["(602) 555-0110"],
               organization_name="Desert Bloom Café", title="Owner")
    assert c["email"] == "lena@cafe.test" and c["phone"] == "+16025550110"
    assert c["organization"]["name"] == "Desert Bloom Café"
    assert [h["value"] for h in c["handles"]] == ["lena@cafe.test", "+16025550110"]
    create(client, name="Marcus Hale", email="marcus@realty.test")
    assert [x["id"] for x in client.get("/api/contacts?q=lena")["items"]] == [c["id"]]
    assert client.get("/api/contacts?q=Desert")["total"] == 1          # by organization name
    assert client.get("/api/contacts?q=5550110")["items"][0]["id"] == c["id"]
    assert client.get("/api/contacts?sort=name")["items"][0]["name"] == "Lena Ortiz"


def test_validation_and_duplicates(client):
    client.post("/api/contacts", {"title": "Nobody"}, expect=400)
    client.post("/api/contacts", {"name": "X", "email": "not-an-email"}, expect=400)
    first = create(client, name="A", email="a@x.test")
    err = client.post("/api/contacts", {"name": "B", "email": "A@x.test"}, expect=409)["error"]
    assert err["code"] == "duplicate_handle" and err["details"]["contact_id"] == first["id"]


def test_staff_have_no_address_book(make_user):
    _, staff = make_user("staff")
    staff.get("/api/contacts", expect=403)
    staff.post("/api/contacts", {"name": "x"}, expect=403)


def test_handles_primary_and_removal(client):
    c = create(client, name="Pat", email="pat@one.test")
    c = client.post(f"/api/contacts/{c['id']}/handles", {"kind": "email", "value": "pat@two.test", "label": "home"})["contact"]
    second = next(h for h in c["handles"] if h["value"] == "pat@two.test")
    c = client.post(f"/api/contacts/{c['id']}/handles/{second['id']}/primary")["contact"]
    assert c["email"] == "pat@two.test"
    c = client.delete(f"/api/contacts/{c['id']}/handles/{second['id']}")["contact"]
    assert c["email"] == "pat@one.test"
    other = create(client, name="Other", email="other@x.test")
    client.post(f"/api/contacts/{c['id']}/handles", {"kind": "email", "value": "other@x.test"}, expect=409)
    assert client.get(f"/api/contacts/{other['id']}")["contact"]["email"] == "other@x.test"


def test_update_custom_fields_and_org(client):
    c = create(client, name="Sam", email="sam@x.test")
    c = client.patch(f"/api/contacts/{c['id']}", {"custom": {"Account #": "4471"}, "organization_name": "Acme",
                                                   "notes": "Prefers text"})["contact"]
    assert c["custom"] == {"Account #": "4471"} and c["organization"]["name"] == "Acme" and c["notes"] == "Prefers text"
    c = client.patch(f"/api/contacts/{c['id']}", {"organization_id": None})["contact"]
    assert c["organization"] is None


def test_merge_moves_everything(client):
    ch = make_channel()
    keep = create(client, name="Lena Ortiz", email="lena@cafe.test")
    msg = receive(ch, sender="lena.o@gmail.test", name="Lena O")
    dupe_id = inbox.get(msg["conversation_id"])["contact_id"]
    assert dupe_id != keep["id"]
    group = client.post("/api/contact-groups", {"name": "Restaurants"})["group"]
    client.post(f"/api/contact-groups/{group['id']}/members", {"contact_ids": [dupe_id]})
    merged = client.post(f"/api/contacts/{keep['id']}/merge", {"other_id": dupe_id})["contact"]
    assert {h["value"] for h in merged["handles"]} == {"lena@cafe.test", "lena.o@gmail.test"}
    assert merged["group_ids"] == [group["id"]]
    assert inbox.get(msg["conversation_id"])["contact_id"] == keep["id"]
    client.get(f"/api/contacts/{dupe_id}", expect=404)
    client.post(f"/api/contacts/{keep['id']}/merge", {"other_id": keep["id"]}, expect=400)


def test_detail_includes_conversation_history(client):
    ch = make_channel()
    msg = receive(ch, sender="grace@mail.test", name="Grace Kim", subject="Invitations")
    contact_id = inbox.get(msg["conversation_id"])["contact_id"]
    detail = client.get(f"/api/contacts/{contact_id}")
    assert [c["id"] for c in detail["conversations"]] == [msg["conversation_id"]]
    assert detail["jobs"] == [] and detail["tasks"] == []


def test_block_sends_future_mail_to_spam(client):
    ch = make_channel()
    c = create(client, name="Spammer", email="spam@bad.test")
    assert client.post(f"/api/contacts/{c['id']}/block", {"blocked": True})["contact"]["is_blocked"] is True
    msg = receive(ch, sender="spam@bad.test")
    assert inbox.get(msg["conversation_id"])["is_spam"] == 1
    assert client.get("/api/contacts?blocked=1")["items"][0]["id"] == c["id"]


def test_organizations_and_link_domain(client):
    a = create(client, name="A", email="a@acme.test")
    create(client, name="B", email="b@acme.test")
    create(client, name="C", email="c@other.test")
    org = client.post("/api/organizations", {"name": "Acme Inc", "domain": "@ACME.test"})["organization"]
    assert org["domain"] == "acme.test"
    assert client.post(f"/api/organizations/{org['id']}/link-domain")["linked"] == 2
    detail = client.get(f"/api/organizations/{org['id']}")
    assert {c["name"] for c in detail["contacts"]} == {"A", "B"}
    assert client.get(f"/api/contacts/{a['id']}")["contact"]["organization"]["id"] == org["id"]
    # new contacts at that domain are linked automatically
    d = create(client, name="D", email="d@acme.test")
    assert d["organization"]["id"] == org["id"]
    gmail = client.post("/api/organizations", {"name": "Gmail people", "domain": "gmail.com"})["organization"]
    client.post(f"/api/organizations/{gmail['id']}/link-domain", expect=400)
    client.post("/api/organizations", {"name": "acme inc"}, expect=409)
    client.post("/api/organizations", {"name": "Bad", "domain": "not a domain"}, expect=400)


def test_groups(client):
    a = create(client, name="A", email="a@x.test")
    b = create(client, name="B", email="b@x.test")
    g = client.post("/api/contact-groups", {"name": "Vendors"})["group"]
    client.post("/api/contact-groups", {"name": "vendors"}, expect=409)
    client.post(f"/api/contact-groups/{g['id']}/members", {"contact_ids": [a["id"], b["id"]]})
    assert {c["id"] for c in client.get(f"/api/contacts?group_id={g['id']}")["items"]} == {a["id"], b["id"]}
    client.post(f"/api/contact-groups/{g['id']}/members", {"contact_ids": [b["id"]], "remove": True})
    assert [c["id"] for c in client.get(f"/api/contacts?group_id={g['id']}")["items"]] == [a["id"]]
    assert client.get("/api/contact-groups")["items"][0]["member_count"] == 1
    assert client.get("/api/bootstrap")["contact_groups"][0]["name"] == "Vendors"


def test_csv_import_and_export(client):
    existing = create(client, name="Marcus Hale", email="marcus@realty.test")
    text = (
        "Full Name,E-mail,Company,Job Title,Mobile,Groups\n"
        "Lena Ortiz,lena@cafe.test,Desert Bloom,Owner,602-555-0110,Restaurants\n"
        ",marcus@realty.test,Saguaro Realty,Office Manager,,Real estate\n"
        ",,,,,\n"
        "Bad Email,nope,,,,\n"
    )
    resp = client.raw("post", "/api/contacts/import", data={"file": (io.BytesIO(text.encode()), "people.csv")},
                      content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    result = resp.get_json()
    assert (result["created"], result["updated"], result["skipped"]) == (2, 1, 1)
    assert result["errors"][0]["line"] == 5
    marcus = client.get(f"/api/contacts/{existing['id']}")["contact"]
    assert marcus["title"] == "Office Manager" and marcus["organization"]["name"] == "Saguaro Realty"
    lena = client.get("/api/contacts?q=lena")["items"][0]
    assert lena["phone"] == "+16025550110" and lena["organization"]["name"] == "Desert Bloom"
    groups = {g["name"] for g in client.get("/api/contact-groups")["items"]}
    assert {"Restaurants", "Real estate"} <= groups
    csv_out = client.raw("get", "/api/contacts/export.csv")
    assert csv_out.status_code == 200 and csv_out.mimetype == "text/csv"
    body = csv_out.get_data(as_text=True)
    assert body.splitlines()[0].startswith("name,email,phone,organization")
    assert "Lena Ortiz,lena@cafe.test,+16025550110,Desert Bloom,Owner" in body
    client.post("/api/contacts/import", {"csv": "foo,bar\n1,2\n"}, expect=400)


def test_delete_contact_keeps_conversation(client):
    ch = make_channel()
    msg = receive(ch, sender="x@y.test")
    cid = inbox.get(msg["conversation_id"])["contact_id"]
    client.delete(f"/api/contacts/{cid}")
    assert inbox.get(msg["conversation_id"])["contact_id"] is None


def test_global_search_finds_contacts_and_orgs(client):
    create(client, name="Priya Raman", email="priya@arts.test", organization_name="Phoenix Arts Council")
    items = client.get("/api/search", query_string={"q": "priya"})["items"]
    assert any(i["type"] == "contact" and i["url"].startswith("/contacts/") for i in items)
    items = client.get("/api/search", query_string={"q": "arts council"})["items"]
    assert any(i["type"] == "organization" for i in items)
