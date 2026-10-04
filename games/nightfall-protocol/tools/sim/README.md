# Settlement simulation: shared contract

`tools/people/` (survivors, `briefs/people.md`) and `tools/settlement/` (stores, barter, civics, `briefs/settlement.md`) are built side by side. This page is what both rely on. Change it on purpose and say so in the PR.

## Code shape

- Plain JavaScript, no build step, one IIFE per module that runs in the pages and in Node, like `tools/region/campaign.js`: `const People=(()=>{ ... return {...}; })(); if(typeof module!=='undefined') module.exports=People;`
- Pure functions over plain data (foundation, "Simulation rules"): no rendering, no `Math.random`, no `Date`. Randomness comes from a seeded generator passed in or kept in the state, so a run is repeatable from its seed.
- Rules are checked with `node test.js` in each folder.

## Time

- **World time** is in game minutes since the campaign started, the same number as `campaign.js` `state.minutes` (a campaign starts at 07:30 on day 0). Time of day = `minutes % 1440`.
- **Life time** is in life days: `lifeDay = minutes / (1440 * 25)` (one life day per 25 game days, foundation). `People.LIFE_RATIO = 25`.
- Every rate says which clock it uses. Needs run on world time; age, pregnancy and lifespan on life time.
- Rates are continuous and settled in steps of up to 60 game minutes, so any stretch can be fast-forwarded in one call.

## Units

| Thing | Unit |
| --- | --- |
| Water | litres |
| Food in a body | kcal; 1 ration = 2,000 kcal = 1 kg (`campaign.js` `UNIT.food`) |
| Stock | units of each loot category as in `campaign.js` `UNIT` (food rations, medicine kits, tools parts, fuel L, gear, water L, shelter materials, goods) |
| Mood | points, roughly −100 to +100 in total |
| Opinion | −100 to +100 per pair |

## The survivor record (owned by people)

```js
{ id:'s1', seed:12345, name:'Ana Ruiz', sex:'f',
  born:-11000,                      // life day of birth (negative: before the campaign)
  body:{ water:0, food:0, energy:1 },   // deficits in L and kcal (0 = sated), energy 0..1
  conditions:[ {kind:'wound', severity:.3, since:0} ],
  traits:['tough'], skills:{ build:1, grow:0, cook:2, medic:0, craft:1, shoot:2 },
  mood:[ {key:'ate-cooked', value:5, until:600} ],   // until = world minute, null = while the cause lasts
  rel:{ s2:{ opinion:20 } }, partner:null,
  role:null,                        // set by settlement: 'leader', 'medic', 'guard', 'scavenger', 'cook', 'builder' or null
  at:'base',                        // 'base' or a squad id
  alive:true }
```

Settlement and building read the record and write to it only through `People` functions (`People.addMood`, `People.setRole`), never directly.

## How the two meet each step

```js
const dem = People.demand(p, dt, env);        // {water:L, food:kcal} this person wants over dt minutes
const got = Settlement.ration(stores, demands, rules, minute);   // per id: what the stores can and the rules will give
People.step(p, dt, env, got[p.id]);          // drains, eats, drinks, settles health and mood
```

- `env` = `{ minute, heat (0..1, campaign.heatOf), activity:'rest'|'work'|'sleep'|'travel', bed:true|false }`.
- `Settlement.ration` takes items out of the stores and returns `{[id]:{water:L, food:kcal}}`. Rules (rationing level) can give less than asked; people then carry a deficit.
- Until both sides are wired, the people harness uses a stub that hands out what is asked from a simple pool.

## Tasks offered to job choice

Settlement and building offer tasks as `{ id, kind:'cook'|'haul'|'build'|'grow'|'guard'|'trade'|'nurse'|..., skill:'cook'|..., where:{x,z}|null, hours, urgency:0..1 }`. People score them with `People.score(p, task, ctx)` (utility from needs, skills, traits, priorities and distance) and pick the best when a task ends.
