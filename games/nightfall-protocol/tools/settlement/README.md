# Settlement (stores, production, barter, civics)

- `settlement.js` holds the settlement's rules as plain functions over plain data, with no rendering, so it runs in the pages and in Node. It follows the shared contract in `../sim/README.md`: world time in game minutes, food in kcal, water in litres, survivor records owned by people and written only through hooks.
- `node test.js` checks the rules.
- `node harness.js [seed]` is a quick sanity run: a year of stores, gardens, wells, cooking, scavenging runs, three traders, a summer drought and civics, with 20 stub people (fixed demand per head). It prints a line a month. The shared harness with real people comes later.

## Rules in short

- **Items**: 27 items inside the eight loot categories, each with a unit, kg, kcal (food), litres (water), a base value (1 point ≈ 1 L of bottled water), a shelf life in days and the storage it wants (dry, cool or tank). Flour must be cooked before it is eaten. One unit of a `campaign.js` loot category becomes one default item: ration (2,000 kcal), med kit, scrap part, L gasoline, field gear, lumber, trade goods, L tank water. `receive(stores, pack, minute)` takes `base.stock` or a squad's pack.
- **Stores**: lots of one item with the minute they came in and a condition (1 fresh, 0 gone). Things are used most perishable first, then oldest.
- **Storage and spoilage** (daily): capacity comes from buildings as `{dry:kg, cool:kg, tank:L}`. The most perishable lots get storage first.
  - Condition falls by 1/shelf life a day.
  - Cool items out of the cool store spoil 2.5× faster; tank water in open containers 4×; anything that fits nowhere 1.5× on top.
  - Heat (0..1) adds up to 2× for fresh things (shelf life 30 days or less) and up to 1.3× for the rest.
- **Rationing**: `ration(stores, demands, rules, minute)` returns `{[id]:{water, food, cooked}}` (`cooked` is the share of kcal that came as cooked meals). Levels: full; reduced (food 75%, water 90%); survival (food 50%, water 75%).
  - Tier 0 (children under 13, the sick with a condition of severity 0.3 or more, the pregnant) is never cut and is served first. Tier 1 (guards, scavengers, builders) comes next, then everyone else. A tier that cannot be served in full shares what is left in proportion.
  - `priorities(people, minute)` builds the tiers; `allowance(demands, rules)` gives what the rules allow, the yardstick for a real shortfall.
- **Production**: recipes run at an amenity, once a day per amenity unit, and are offered as tasks `{id, kind, skill, where, hours, urgency, recipe}`. Urgency is 1 − days of supply / target. `work(S, taskId, worker, minute)` takes the inputs and adds the outputs. Skill s scales the yield by 0.7 + 0.15s (0.5 to 1.5).

  | Recipe | Amenity | Hours | In | Out at skill 2 |
  | --- | --- | --- | --- | --- |
  | water | well | 3 | — | 60 L tank water |
  | garden | garden plot | 4 | 25 L water | 8 kg produce |
  | tools | workshop | 4 | 3 scrap | 1 set of hand tools |
  | cook | kitchen | 2 | up to 5,600 kcal of produce or flour (at least 1,400), 3 units of the cheapest fuel | meals of 700 kcal, keeping 90% of the kcal |
  | medicine | infirmary | 3 | 1 clothing, 1 spirits | 6 bandages |

- **Barter**: the value of n units to a holder `{stores, need}` is base × condition × scarcity. Scarcity = √(target days / days on hand), from 0.35 to 3, taken at the middle of the change.
  - Target days: food 30, water 14, the rest 60. `needOf(heads)` gives daily use per head: 2,000 kcal, 6 L, 0.02 med kits, 0.03 scrap, 0.5 L fuel, 0.02 gear, 0.03 lumber, 0.02 goods.
  - Traders never value their goods below base (`floor` 1).
- **Traders**: seeded from a number: a name, two wanted categories (need ×2, the rest ×0.25 of six people) and a visit every 10 to 20 days (±2). Each visit brings fresh stock: five lines worth 40 to 120 points each, plus jerky and water.
  - The trader offers up to three deals: goods we value more than it does, against goods it values more than we do. It asks fair value × a margin from reputation: 1.2 at 0, 1.0 at +50, up to 1.4 below 0.
  - The settlement accepts when what comes in is worth at least what goes out, to us, and food and water stay above 7 days.
  - Every trade goes in `S.ledger`. Reputation: +3 a trade, +1 a visit with trades, −1 a visit with none.
- **Civics**: roles leader, medic, guard, scavenger, cook and builder, with one leader at a time. There are three rules:
  - rationing: full, reduced or survival;
  - curfew: none; dusk (20:00–05:00, night exposure 0.6); strict (19:00–06:00, 0.3);
  - runs: volunteers, rota or leader picks.
- **Support** (−1..1) per adult (16 or older) and rule:
  - Rationing: the level the stores call for (full above 30 days of food and 14 of water, survival at 10 and 4), shifted by traits and by hunger.
  - Curfew: 2 × threat, shifted by traits and role.
  - Runs: a base preference, traits, scavenger role, and opinion of the leader.
- **Mood**: each rule in force writes a modifier through `addMood(p, 'rule:<rule>', value, 24)` each day. The value is the rule's base (rationing 0/−4/−10, curfew 0/−1/−4, runs +1/0/−2) plus 4 × support. Changing a rule gives ±3 for 72 h to those who care (|support| ≥ 0.2).
- **Legitimacy** moves 15% a day towards a target: 50 + 30 × average stance + 20 × average opinion of the leader / 100 − 30 × shortfall (25 with no leader). A survivor's stance is rationing ½, curfew ¼ and runs ¼, with opposition counted double.
- **Unrest** per adult changes each day by:
  - plus 10 × opposition;
  - plus 0.25 × a bad mood;
  - plus 12 × shortfall;
  - minus 6 × legitimacy / 100;
  - minus 1.5.

  Over 60, a survivor leaves with a daily chance of (unrest − 60) / 400. Departures are returned for people to act on. `exile` sends someone away. `factions` is a stub that groups people by the option they prefer.
