# Brief: strategy map

Read `00-foundation.md` first, and the world map design doc linked there.

## Goal

The region map as the strategic layer: several squads at once on real roads, time passing, knowledge that fades, sites worth visiting, and the encounters that the tactical layer plays out.

## Files

`tools/region/` (`campaign.js` rules and state, `region-main.js` the map view, `region-head.html`, `build.sh`, `test.js`, `page-test.js`), `mockups/region-map.html`, the region half of `mockups/streaming/zoom.html`, and `tools/osm/prep_region.py` with `data/region/`.

## Where it stands

- **Data**: `tools/osm/prep_region.py` builds `data/region/region_i17.json`. It holds:
  - a 600 m sector grid with ground type, elevation range and building counts
  - 100 m terrain
  - roads and a travel graph
  - washes, lakes and land use
  - towns and named peaks
  - about 245 loot sites
- **Code**: the rules live in `tools/region/campaign.js`, which has no rendering and is tested in Node. The view is `tools/region/region-main.js`, one file shared by the standalone map and the zoom page; the old copy, `tools/zoom/region-z.js`, is gone. `tools/region/build.sh` assembles both pages. See `tools/region/README.md` for the rules in short.
- **Campaign state** saves in the browser and resumes paused on reload. It covers knowledge, squads and their trips, water and packs, the clock, searched sites, raider bands, base stock and the log. **New campaign** in the log panel starts over.
- **Day, night and heat**:
  - Early-summer sun and temperature, cooler on high ground.
  - Darkness slows off-road travel, heat slows everyone, thirst slows more.
  - Water follows heat, and resting in shade uses less.
  - A squad can lie up in the heat, and **Wait for dawn** or **Wait for dusk** runs the clock.
  - The sector panel forecasts arrival time, water and hours spent lying up.
- **Scavenging**:
  - A squad in a scouted sector can search its sites; it takes time by site size, head count and light.
  - Sites hold seeded stock, deplete as they are searched and get picked over slowly.
  - Squads carry 25 kg each, water included, and unload into the ranch's stock when they get home.
- **Raiders**:
  - Four bands roam around their lairs, camping between legs and lying up in the heat.
  - They show on the map where a squad or the ranch has seen them.
  - Contact raises an encounter: Go tactical (New River block only), Fight it out (a quick placeholder), Pull back, or Lie low.
- **Zoom page**:
  - Diving from an encounter carries it to the tactical layer as `NF.encounter`.
  - Coming back runs the map clock forward for the time spent on the ground (real time, plus 5 minutes per fight turn), and other squads keep travelling.

## Decisions (keep)

- One fixed region (the corridor), a stylised 3D map, several squads at once.
- Knowledge: unknown, rumoured, scouted, current. Scouted goes stale after 3 days.
- **Clock**:
  - It runs only while something is happening (travelling, searching, lying low, waiting) and holds during an encounter.
  - 1× is 10 game minutes per real second; 4× and pause as before.
- **Tactical time** (follows the foundation's two clocks): exploration on the tactical ground runs in real time, and each character's turn in a fight is 5 game minutes. Combat reports the turn count as `turns` in `NF.tacResult()`. The map catches up on return, and the other squads keep travelling.
- **Season and heat**:
  - Early summer: sunrise 05:20, sunset 19:35.
  - 24 °C before sunrise to 40 °C at 16:00 at 600 m, 0.65 °C cooler per 100 m higher.
  - Heat is 0 at 30 °C or below and 1 at 40 °C.
- **Water** (proposed foundation change): 0.5 L per person per hour on the move, multiplied by 1 + heat, so up to double. This replaces the fixed 10:00–18:00 doubling. Resting in shade: 0.2 × (1 + heat).
- **Travel** (proposed foundation addition):
  - Darkness slows off-road travel to ×0.6 and roads to ×0.85.
  - Heat slows travel by up to ×0.75.
  - Thirst: ×0.6.
  - The +1 h per 300 m climbed now applies on roads too.
- **Lookouts** see one sector less at night (never under 1).
- **Carrying**: 25 kg a person, water included; at most 6 L of water a person.
- **Loot units** (what `base.stock` counts):

  | Category | Unit | Weight |
  |---|---|---|
  | food | rations | 1 kg |
  | medicine | med kits | 0.5 kg |
  | tools | parts | 2 kg |
  | fuel | L fuel | 0.8 kg |
  | gear | gear | 2 kg |
  | water | L water | 1 kg |
  | shelter | materials | 5 kg |
  | goods | trade goods | 1 kg |

## Interfaces

- **Region frame**: centred at 33.945 N, 112.14 W. `tools/zoom/glue-pre.js` converts to tactical blocks.
- **`window.__region`** keeps `squads`, `focus`, `placeSquad` and `resize`.
  - `squads` now reads the campaign's squads. A squad's route is `trip`, where it used to be `path`.
  - New: `campaign` (the `Campaign` module), `back(realSeconds, result)`, `advance(minutes)`, `send(i,x,z)` and `save()`.
- **`Campaign.state.base.stock`**: what squads have brought home, as `{food: n, …}` in the units above. This is the hand-off to `building.md`. Squad sizes are still fixed in `newGame` until the base assigns people.
- **Encounter** (for `combat.md`). The map creates this and puts it in `NF.encounter` when the player goes tactical:

  ```
  { id, at /*game minutes*/, where:{x, z /*region frame*/, sector:[c,r], ground, place},
    light:'day'|'dawn'|'dusk'|'night', tempC,
    squad:{index, name, people, pos:[x,z]},
    enemy:{kind:'raiders', band, count, boss, alert:'unaware'|'suspicious'|'alert', pos:[x,z]},
    firstSight:'squad'|'both'|'enemy', distance /*m*/, forced }
  ```

  `firstSight: 'squad'` means the squad gets the first strike, as in the demo. `'enemy'` means the raiders scramble first.
- **Result back from tactical** (proposed for `combat.md`): `NF.tacResult()` returning `{won, people, turns}`. Until combat provides it, coming back from an encounter fought on the ground counts as a win with no losses, and only the real time spent there is charged.

## Known gaps

- The south-east tile (east Anthem) failed to download. Rerun `regionfetch.sh` and then `prep_region.py`.
- Saving uses the viewer's browser only, and the standalone map and the zoom page share it when they're served from the same origin.
- Fights off the baked block are a quick placeholder until the tactical ground covers more of the corridor.
- No weather beyond the daily heat curve, no moon, no traders, no seasons. Night has no extra danger yet.
- Squad needs beyond water (food, fatigue, injury) are not modelled. A squad that runs dry only slows down.
- Squad management: forming squads, assigning people from the base (`building.md`). Head counts are fixed in `newGame`.
- Raiders don't hunt squads or raid the ranch, and new bands never appear.

## First tasks

1. ~~Persistence of the campaign state.~~ Done.
2. ~~A day–night and heat model that changes travel and water.~~ Done.
3. ~~Scavenging a site: time spent, what comes back.~~ Done; `base.stock` is ready for `building.md`.
4. ~~Roaming threats on the map that become tactical encounters.~~ Done on the map side. The encounter shape is above; combat now needs to read `NF.encounter` and report `NF.tacResult()`.
5. ~~Time while tactical.~~ Done: real time exploring, plus 5 minutes per fight turn once combat reports `turns`.

Next:
- Raiders that react: they follow a squad that was seen and probe the ranch.
- Squad forming from the base's people.
- Traders.
- A night danger bonus.
- Move saving to a shared store if the campaign is to follow the player across devices.

## Out of scope

The ground (`tactical-maps.md`), fights (`combat.md`), the base (`building.md`).
