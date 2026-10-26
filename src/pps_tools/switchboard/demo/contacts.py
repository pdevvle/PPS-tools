"""Demo address book: fill in the customers the inbox demo met, add a few more, group them."""

from __future__ import annotations

from pps_tools.switchboard import db
from pps_tools.switchboard.services import contact_book
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.util import now_iso


def _contact(email=None, phone=None):
    return (contacts_svc.find("email", email) if email else None) or (contacts_svc.find("phone", phone) if phone else None)


def _org(name):
    row = db.one("SELECT id FROM organizations WHERE name = ?", name)
    return row["id"] if row else None


def _update(contact, **values):
    if contact:
        values["updated_at"] = now_iso()
        db.update("contacts", contact["id"], values)
        contacts_svc.reindex(contact["id"])


def seed_contacts(ctx) -> None:
    # organizations the inbox demo created, with more detail
    for name, website, address in (
        ("Desert Bloom Café", "https://desertbloomcafe.example", "214 E Roosevelt St, Phoenix, AZ 85004"),
        ("Saguaro Realty Group", "https://saguarorealty.example", "4400 N Scottsdale Rd, Suite 210, Scottsdale, AZ 85251"),
        ("Phoenix Arts Council", "https://phxarts.example", "1 N Central Ave, Phoenix, AZ 85004"),
        ("Copperline Brewing", "https://copperlinebrewing.example", "818 W Grant St, Phoenix, AZ 85007"),
        ("Mohawk Paper", "https://mohawkpaper.example", None),
    ):
        oid = _org(name)
        if oid:
            db.update("organizations", oid, {"website": website, "address": address, "updated_at": now_iso()})
            contact_book.reindex_org(oid)
    league = contact_book.find_or_create_org("Valley Little League", "valleyll.example")
    db.update("organizations", league, {"phone": "(602) 555-0164", "notes": "Opening day is the first Saturday in March."})
    roasters = contact_book.find_or_create_org("Cactus Coffee Roasters", "cactuscoffee.example")

    lena = _contact("lena@desertbloomcafe.example")
    _update(lena, title="Owner", phone="+14805550110",
            notes="Reprints menus every spring and fall. Likes a quick call before anything goes to press.")
    if lena:
        contacts_svc.add_handle(lena["id"], "phone", "+14805550110", "mobile")
    marcus = _contact("marcus@saguarorealty.example")
    _update(marcus, title="Office Manager", phone="+16025550188",
            notes="Net-30 account. Orders cards for every new agent; always wants a proof first.")
    if marcus:
        contacts_svc.add_handle(marcus["id"], "phone", "+16025550188", "office")
    dana = _contact(phone="+16025550164")
    if dana:
        _update(dana, name="Dana Price", title="Coach & sponsorship lead", organization_id=league,
                notes="Texts first. Sponsor logos tend to arrive the night before — plan prepress time.")
        contacts_svc.add_handle(dana["id"], "email", "dana.price@valleyll.example", "work")
    priya = _contact("priya@phxarts.example")
    _update(priya, title="Events Director", phone="+16025550123",
            notes="Fall Gala every November. Programs are saddle-stitched; 500–600 copies.")
    tom = _contact("tom@copperlinebrewing.example")
    _update(tom, title="Co-founder", notes="Asked about can labels / shrink sleeves for a seasonal IPA.")
    grace = _contact("grace.kim@mail.example")
    _update(grace, notes="Wedding invitations, letterpress look on 110lb cotton. Very happy customer.")
    steve = _contact("steve.alvarez@mohawkpaper.example")
    _update(steve, title="Account Representative", phone="+16025550190",
            notes="Coated stocks +6% on Jan 1. Lock Q1 pricing before Dec 15.")

    saguaro = _org("Saguaro Realty Group")
    extra = [
        ("Ana Ruiz", "ana@saguarorealty.example", "+16025550131", "Realtor", saguaro),
        ("Ben Cho", "ben@saguarorealty.example", "+16025550132", "Realtor", saguaro),
        ("Kayla Moss", "kayla@saguarorealty.example", "+16025550133", "Office Manager", saguaro),
        ("Jasmine Reed", "jasmine@cactuscoffee.example", "+16025550171", "Owner", roasters),
        ("Hector Morales", "hector@phxarts.example", None, "Facilities", _org("Phoenix Arts Council")),
    ]
    made = {}
    for name, email, phone, title, org in extra:
        if _contact(email):
            continue
        c = contact_book.create_contact({"name": name, "email": email, "phone": phone, "title": title,
                                         "organization_id": org}, ctx.uid("frontdesk"))
        made[name] = c

    groups = {}
    for name, color in (("Restaurants", "#e8590c"), ("Real estate", "#1971c2"), ("Nonprofits", "#2f9e44"), ("Vendors", "#868e96")):
        groups[name] = db.insert("contact_groups", {"name": name, "color": color, "created_at": now_iso()})

    def add(group, *contacts):
        contact_book.add_to_group(groups[group], [c["id"] for c in contacts if c])

    add("Restaurants", lena, tom, made.get("Jasmine Reed"))
    add("Real estate", marcus, made.get("Ana Ruiz"), made.get("Ben Cho"), made.get("Kayla Moss"))
    add("Nonprofits", priya, dana, made.get("Hector Morales"))
    add("Vendors", steve)
    ctx.data["contact_groups"] = groups
