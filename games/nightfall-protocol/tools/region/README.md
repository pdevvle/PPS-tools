# Region map (the strategic layer)

- `campaign.js` holds the rules and the campaign state, with no rendering, so it runs in the pages and in Node. It covers the clock, light and heat, travel on the road graph, water, knowledge, scavenging, roaming raiders, encounters and saving.
- `region-main.js` draws the campaign and takes orders. The same file is the standalone map (`mockups/region-map.html`) and the map half of the zoom page (`mockups/streaming/zoom.html`), where `../zoom/glue-pre.js` defines `NF`.
- `region-head.html` is the standalone page's markup and style. The zoom page's markup is in `../zoom/zoom-head.html`.
- `./build.sh` assembles both pages.
- `node test.js` checks the rules.
- `page-test.js` checks both pages in Chromium: load, play, save, reload, resume. Serve `mockups/` over HTTP first, as described at the top of the file.

## Rules in short

- **Clock**: 1× is 10 game minutes per real second. It runs only while something is happening: a squad travelling, searching or lying low, or the player waiting for dawn or dusk. It holds during an encounter. On the tactical ground exploration runs in real time, and each character's turn in a fight is 5 game minutes (foundation). The map catches up when you come back.
- **Light and heat**: early summer. The sun rises at 05:20 and sets at 19:35. Temperature runs from 24 °C just before sunrise to 40 °C at 16:00 at 600 m, 0.65 °C cooler per 100 m higher. Heat is 0 at 30 °C or below and 1 at 40 °C.
- **Travel**: Dijkstra on the road graph from the foundation speeds, with +1 h per 300 m climbed on roads as well as off them. Each leg keeps its base hours and whether it is off-road, and progress is spent at a pace that changes with the hour:
  - darkness: off-road ×0.6, roads ×0.85
  - heat: up to ×0.75
  - thirst: ×0.6

  A squad can lie up whenever heat is 0.5 or more. The sector panel forecasts arrival, water and hours spent lying up.
- **Water**: on the move, 0.5 L per person per hour, up to double in full heat. Resting in shade (lying up, searching, idle away from home), 0.2 to 0.4 L. Each person carries up to 6 L, and water counts towards the 25 kg a person carries. Squads refill and unload at the ranch.
- **Knowledge**: a lookout reveals 1 to 3 sectors, more from high ground, one less at night. Scouted sectors go stale after 3 days.
- **Scavenging**: a squad standing in a scouted sector can search any site there. It takes 1, 2 or 3 h depending on the site's size, scaled by √(4 / people), and 1.3× in the dark.
  - Each site has a seeded stock: its main loot category plus up to two others. Tanks and wells hold litres of water.
  - A search takes 60% of what is left, as far as the squad can carry. Water tops up the bottles first.
  - Other people pick sites over at 1.5% a day.
  - The haul goes into `base.stock` when the squad gets home.
- **Raiders**: four bands start in lairs more than 6 km from the ranch. They roam 1.5 to 5 km around their lair on the road graph, camp 2 to 6 h between legs and lie up when heat is 0.6 or more.
  - Squads spot them at 900 m by day and about 400 m at night, further from high ground.
  - Raiders spot a moving squad at 650 m by day, and a squad that is holding still at 60% of that.
  - The ranch keeps watch 1.5 km out.
  - Bands show on the map where they were last seen, for 12 hours.
- **Encounters**: who saw whom first sets the raiders' alertness: unaware, suspicious or alert. The player chooses:
  - **Go tactical**: only in the baked New River block.
  - **Fight it out (quick)**: a placeholder that resolves from head count, aim and first sight.
  - **Pull back**: alert raiders that outnumber the squad may run it down.
  - **Lie low**: an hour hidden. Alert raiders find you; suspicious ones sometimes do.
