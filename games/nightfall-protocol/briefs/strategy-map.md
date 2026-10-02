# Brief: strategy map

Read `00-foundation.md` first, and the world map design doc linked there.

## Goal

The region map as the strategic layer: several squads at once on real roads, time passing, knowledge that fades, sites worth visiting, and the encounters that the tactical layer plays out.

## Where it stands

- `mockups/region-map.html` (and the region half of `mockups/streaming/zoom.html`), built from `tools/osm/prep_region.py` into `data/region/region_i17.json`: 600 m sector grid with ground type, elevation range and building counts; 100 m terrain; roads and a travel graph; washes, lakes, land use; towns and named peaks; about 245 loot sites.
- Two squads (Ranch party, Scouts). Click a sector: panel with knowledge, ground, elevation, sites, a route preview with time and water. Send a squad: routes on the road graph by Dijkstra (paved 5, dirt 4, off-road 2.5 km/h, slower uphill). The clock runs while anyone moves (1× = 10 game minutes per second). Squads reveal sectors as they go, further from high ground. Knowledge levels and staleness are drawn on the map.
- Zoom page: zooming all the way in on the New River block goes tactical and brings any squad there; zooming out writes its position and head count back.

## Decisions (keep)

- One fixed region (the corridor), a stylised 3D map, several squads at once.
- Knowledge: unknown, rumoured, scouted, current; stale after 3 days.
- Travel and water numbers in the foundation.

## Interfaces

- Region frame centred at 33.945 N, 112.14 W; `tools/zoom/glue-pre.js` converts to tactical blocks. `window.__region` exposes `squads`, `focus`, `placeSquad`, `resize`.
- Encounters the map creates must be playable by combat: agree a data shape with `combat.md` (where, who, how alert).

## Known gaps

- The south-east tile (east Anthem) failed to download; rerun `regionfetch.sh` then `prep_region.py`.
- Nothing persists: knowledge, squads and time reset on reload.
- No events: no raiders roaming, weather, heat, night, or traders. No squad needs beyond water.
- Time doesn't pass while a squad is on the tactical ground.
- Sites have a loot category but no amounts, and scavenging does nothing yet.
- Squad management: forming squads, assigning people from the base (`building.md`), carrying capacity.

## First tasks

1. Persistence of the campaign state (knowledge, squads, clock, discovered sites).
2. A day–night and heat model that changes travel and water.
3. Scavenging a site: time spent, what comes back (feeds `building.md`).
4. Roaming threats on the map that become tactical encounters (with `combat.md`).
5. Time while tactical: decide how tactical real-time maps onto the clock.

## Out of scope

The ground (`tactical-maps.md`), fights (`combat.md`), the base (`building.md`).
