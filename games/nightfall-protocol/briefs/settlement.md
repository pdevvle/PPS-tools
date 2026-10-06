# Brief: settlement (stores, economy, civics)

Read `00-foundation.md` first, especially "Time: two clocks" and "Simulation rules".

## Goal

The aggregate systems the survivors live inside: what the settlement has, how things change hands with traders and other settlements, and how the community governs itself.

## Systems

- **Stores**: inventory by item within the eight loot categories (food, medicine, tools, fuel, gear, water, shelter, goods); storage capacity and conditions; spoilage; rationing.
- **Production**: simple chains (water collection and storage, gardens to food, scrap to tools, cooking, medicine from supplies); jobs come from these and from building.
- **Transactions and barter**: no currency at first; item values from local scarcity and need, so the same item is worth different amounts in different places. A ledger of trades. Reputation with traders and settlements.
- **Trade**: travelling traders with stock and wants; later, abstract settlements along the corridor (population, stocks, attitude) to trade with and send people to.
- **Civics**: roles (leader, medic, guards, scavengers, cooks, builders); rules (rationing levels, curfews, who goes on runs, sharing versus private stores, how newcomers are taken in); decisions with support and opposition per survivor, legitimacy, factions forming from shared opinions; unrest, desertion and exile.
- **Newcomers and departures**: strangers asking to join, refugees, people leaving when mood and civics fail.

## Interfaces

- Reads survivors' needs, opinions and mood from `people.md`; writes consumption, mood modifiers and role assignments back.
- Offers tasks (production, hauling, guarding, trading) to survivors' job choice.
- Receives loot from squads and scavenging (`strategy-map.md`); gives supplies for runs.
- Buildings set storage, production capacity and amenities (`building.md`).

## First tasks

1. Item list and store model with spoilage; consumption hooked to `people.md` needs.
2. Barter valuation from scarcity, and a trader visit loop.
3. Roles and three rules (rationing, curfew, run assignment) with their mood and support effects.
4. Add to the shared headless harness: a year with traders and a rationing crisis, charting stores, values, support and departures.

## Out of scope

Individual bodies and relationships (`people.md`), construction and layout (`building.md`), the map (`strategy-map.md`).

## Decisions

First draft in `tools/settlement/` (`settlement.js`, `test.js`, `harness.js`). It follows `tools/sim/README.md`. All of these values are tunable.

- **Items**: 27 items within the eight loot categories. Each has a category, unit, kg, kcal (food) or litres (water), a base value, a shelf life in game days (none for things that keep) and the storage it wants (dry, cool or tank).
  - **Value scale**: 1 point ≈ 1 L of bottled water. A ration (2,000 kcal) is 10, a med kit 15, antibiotics 25 and a rifle 120.
  - **Shelf lives**: cooked meals 2 days, fresh produce 10, tank water 60, flour 240, rations 365, gasoline 365, canned food 1,100.
  - **Cooking**: flour is not eaten until it is cooked.
- **Loot from the map**: one unit of a `campaign.js` loot category becomes one default item:

  | Category | Default item |
  | --- | --- |
  | food | ration |
  | medicine | med kit |
  | tools | scrap part |
  | fuel | gasoline (L) |
  | gear | field gear |
  | water | tank water (L) |
  | shelter | lumber |
  | goods | trade goods |

  `receive()` takes `base.stock` or a pack by category, or by item id.
- **Stores**: lots of one item, each with the minute it came in and a condition from 1 to 0. Use goes most perishable first, then oldest.
  - **Capacity**: building supplies it as `{dry:kg, cool:kg, tank:L}`. The most perishable lots get storage first.
  - **Spoilage** (daily): condition falls by 1/shelf life a day.
    - A cool item out of the cool store spoils ×2.5, tank water outside a tank ×4, and anything that does not fit ×1.5.
    - Heat adds up to ×2 for things that keep 30 days or less, and up to ×1.3 for the rest.
- **Rationing levels**:

  | Level | Food | Water |
  | --- | --- | --- |
  | full | 100% | 100% |
  | reduced | 75% | 90% |
  | survival | 50% | 75% |

  Water is cut less because the desert kills fast.
- **Priority tiers** for rationing (served in order):
  - **Tier 0**: children under 13.
  - **Tier 1**: the sick, wounded and pregnant (any condition but dehydration or malnutrition at severity 0.3 or more).
  - **Tier 2**: working roles (guard, scavenger, builder, medic).
  - **Tier 3**: everyone else.

  Tiers 0 and 1 are never cut by the level.
  - **Sharing within a tier** (`rules.share`) when it cannot be served in full:
    - **ordered**: people are served whole, one after another, by `rules.order` and then by id. This is the default for water, because an equal water cut dehydrates everyone within about two days (people side).
    - **equal**: everyone is cut in proportion. This is the default for food.
  - `ration()` adds a `cooked` field (the share of kcal that came as meals) beside `water` and `food`, for people's mood.
  - `allowance()` gives what the rules allow. A shortfall is measured against that, not against appetite.
- **Production**: recipes at amenities, once a day per amenity unit. They are offered as tasks in the contract's shape, with urgency 1 − days of supply / target. Under 7 days of water (half the target), recipes that use water (gardens) aren't offered, so people drink first; the shared harness found gardens otherwise drink the tanks dry in a drought.

  | Recipe | Amenity | In | Out |
  | --- | --- | --- | --- |
  | water | well | — | 150 L |
  | garden | garden plot | 25 L water | 8 kg produce |
  | tools | workshop | 3 scrap | hand tools |
  | cook | kitchen | up to 5,600 kcal of produce or flour, plus 3 units of the cheapest fuel | 700-kcal meals, 90% of the kcal |
  | medicine | infirmary | clothing and spirits | 6 bandages |

  Skill s scales the yield by 0.7 + 0.15s, from 0.5 to 1.5.
- **Care**: `offerCare()` offers a `nurse`/`medic` task for each condition of someone at base treated below 0.5, one a day per patient and kind, with urgency 1.5 × severity.
  - **Supplies**, tried in order:
    - wound: bandage (+0.3), else med kit (+0.4);
    - infection: antibiotics (+0.5), else med kit (+0.2);
    - illness: painkillers (+0.2), else med kit (+0.2);
    - heatstroke: 3 L of water (+0.3);
    - chronic: painkillers (+0.2).
  - **Quality** = 0.25 + 0.1 × medic skill + the supply's bonus + 0.1 at an infirmary, at most 1.
  - **Result**: `work()` returns `treat:{patient, kind, quality, by}` for the integration to pass to `People.treat`.
- **Needs and targets**:
  - **Daily use per head**: 2,250 kcal and 13 L water (people.md's adult in early summer), 0.02 med kits, 0.03 scrap, 0.5 L fuel, 0.02 gear, 0.03 lumber and 0.02 goods.
  - **Comfortable supply**: food 30 days, water 14, everything else 60.
- **Barter value** = base × condition × scarcity.
  - Scarcity is √(target days / days on hand), from 0.35 to 3, taken at the middle of the change. Each extra unit is worth less, and the same item is worth more to whoever is short of it.
  - Traders never value their own goods below base (floor 1).
- **Traders**: seeded from a number.
  - **Wants**: two wanted categories, with need ×2 for those and ×0.25 for the rest, on a base of six people.
  - **Schedule**: a visit every 10–20 days, ±2 days.
  - **Stock**: fresh at each visit, five lines worth 40–120 points each.
  - **Deals**: up to three a visit. The trader asks fair value × a margin of 1.2 at reputation 0, 1.0 at +50 and up to 1.4 when reputation is negative.
  - **Fair-deal rule**: the settlement accepts when what comes in is worth at least what goes out (to us) and food and water stay above 7 days of supply.
  - **Ledger and reputation**: every trade is recorded in the ledger. Reputation is −100..100: +3 a trade, +1 for a visit with trades, −1 for one without.
- **Roles**: leader (one at a time; a new leader caps legitimacy at 40), medic, guard, scavenger, cook and builder. Roles are written through `setRole(p, role)`.
- **Rules**: rationing (full, reduced, survival), curfew (none; dusk 20:00–05:00; strict 19:00–06:00) and runs (volunteers, rota, leader picks).
  - **Curfew exposure**: night exposure is 1, 0.6 or 0.3 for none, dusk and strict.
  - **Volunteers**: the willing go (brave and scavenger first, lazy and restless last).
  - **Rota**: people go in turn by id.
  - **Leader picks**: the best shots and scavengers go.
- **Support** (−1..1) per adult (16 or older):
  - **Rationing**: the level the stores call for is full above 30 days of food and 14 of water, and survival at 10 days of food or 4 of water. Hunger and traits shift what each person wants.
  - **Curfew**: 2 × threat, shifted by traits; guards lean stricter and scavengers looser.
  - **Runs**: base preferences (volunteers +0.3, rota +0.2, leader −0.2), plus traits, plus 0.8 × opinion of the leader / 100 for leader picks.
  - **Traits read**: greedy, glutton, frugal, selfless, cautious, nervous, night-owl, free-spirit, brave, lazy, fair, kind, loyal and ambitious. Unknown traits do nothing; people owns the list.
- **Mood** (through `addMood(p, key, value, hours)` only):
  - **Rules in force**: `rule:<rule>` is refreshed daily for 24 h. Its value is the rule's base plus 4 × support. The bases are:
    - rationing 0 / −4 / −10;
    - curfew 0 / −1 / −4;
    - runs +1 / 0 / −2.
  - **Rule changes**: the old `rule:<rule>` is removed through `removeMood(p, key)` and the new one set at once. `decision:<rule>` is ±3 for 72 h, for anyone whose |support| ≥ 0.2.
  - **Expiry**: no settlement modifier uses `until: null`. `clearMoods()` removes them all from someone who leaves or is exiled.
  - **Hook time**: the `addMood` hook takes hours. `People.addMood` takes an `until` minute, so the integration wraps it as `(p, k, v, h) => People.addMood(p, k, v, minute + h*60)`.
- **Legitimacy** (0..100) moves 15% a day towards 50 + 30 × average stance + 20 × average opinion of the leader / 100 − 30 × shortfall. With no leader the target is 25.
  - **Stance**: each survivor's is weighted rationing ½, curfew ¼ and runs ¼, with opposition counted double.
  - **Rule changes**: changing a rule moves legitimacy by 5 × the average support.
- **Unrest** (0..100) per adult changes each day by +10 × opposition, +0.25 × a negative mood, +12 × shortfall, −6 × legitimacy / 100 and −1.5.
  - **Departures**: over 60, the daily chance of leaving is (unrest − 60) / 400. Departures are returned for people to carry out.
  - **Exile and factions**: `exile()` sends someone away; factions are a stub that groups people by the option they prefer.
- **Clocks**: stores, spoilage, prices and civics run daily on the world clock. Age, for child status and adulthood, comes from `born` on the life clock (`minute / (1440 × 25)`).
