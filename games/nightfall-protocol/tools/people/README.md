# People (survivors' individual simulation)

- `people.js` holds the survivor record and the rules for bodies, needs, health, mood, skills, age and job choice, with no rendering, so it runs in the pages and in Node. It follows the shared contract in `../sim/README.md`.
- `harness.js` runs a group at the base headless: `node tools/people/harness.js [seed] [hours] [--supply ok|short|hungry|thin|none] [--water L/day] [--food rations/day] [--med kits/day] [--beds n] [--people n] [--out series.json] [--quiet]`. Defaults: seed 1, 100 h of play (2,500 game days, 100 life days), 20 people, supply `ok`. It prints a summary and with `--out` writes daily averages (needs, energy, mood, health, the pool) and every event (onsets, injuries, breaks, departures, deaths). 100 h runs in about 1.5 s.
- `node test.js` checks the rules.

## API

- `create(seed, {id, minute, stage, sex, name, traits, skills})` makes a survivor; the same seed gives the same person.
- `demand(p, dt, env)` gives `{water, food}` (L, kcal) wanted over `dt` minutes: what they lose plus some of their deficit back. Nothing while asleep.
- `step(p, dt, env, got)` settles `dt` minutes (60 at most) with what was handed out. It returns events: `onset`, `break`, `left`, `death`. `env = {minute, heat, activity, bed, skill}`; `skill` is the skill being practised while working (an addition to the contract).
- `score(p, task, ctx)` gives a task's utility. `ctx = {minute, heat, from, priorities}`. It returns `-Infinity` for a task the person can't or won't do. Self-care tasks (`drink`, `eat`, `sleep`, `rest`, `treat`) score from need.
- `addMood(p, key, value, until)`, `removeMood(p, key)` and `setRole(p, role)` are how other systems write to a survivor.
- `injure(p, severity, minute)`, `addCondition(p, kind, severity, minute)` and `treat(p, kind, quality)` handle conditions. Combat writes wounds, and the medic or settlement treats.
- These read state: `ageOf(p, minute)` (years), `stageOf(p, minute)`, `healthOf`, `moodOf`, `needs`, `capacity`, `thirstStage`, `hungerStage`.
- Fields added to the record (all plain data):
  - `rng`: the person's own random state.
  - `health`: cached by `step`.
  - `brk`: the break in progress, `{kind, until}`.
  - `slept` and `asleep`.
  - `died`: `{minute, cause}`.
  - `left`: `{minute, mood}`.
- Someone who walks out has `at:'gone'` and stays `alive`.

## Rules in short

- **Clocks**: needs, conditions and mood run on world minutes. Age and chronic illness run on life days (`LIFE_RATIO` 25: one life day per 25 game days). Settle in steps of 60 minutes or less.
- **Water**: the body tracks a deficit in litres. Awake it loses 0.5 L/h, up to double in full heat (as `campaign.waterRate`). Asleep it loses 0.15 L/h. That is about 13 L a day for an adult in early summer. A person drinks back up to 1.2 L/h on top of what they lose.
  - Stages: thirsty at 1.5 L short, dehydrated at 3, severe at 5, critical at 7.5.
  - Dehydration alone kills at 10 L short, about 20 h with no water in the heat.
- **Food**: the body tracks a deficit in kcal. Per hour it burns 60 asleep, 85 resting, 170 working and 200 travelling, about 2,250 kcal on a normal day. A person eats back up to 700 kcal/h.
  - Stages: hungry at 1,200 kcal short, malnourished at 8,000, severe at 30,000, starving at 60,000.
  - Starvation kills at 100,000 kcal short, about 5–6 weeks with water.
  - Children's and elders' reserves are smaller (×0.4 and ×0.8).
- **Energy** (0..1) drains awake:
  - 0.045/h resting, 0.065/h working, 0.075/h travelling.
  - Sleep restores 0.14/h in a bed and 0.11/h on the ground (less when in pain).
  - A night in a bed gives +3 mood for 18 h. A night on the ground gives −5 and triples the chance of falling ill.
- **Life stages** (years): child under 13, teen 13–17, adult 18–59, elder 60+. They scale water, food, capacity for work, learning speed and body reserves. Children only take light tasks.
- **Health** = 1 − Σ weight × severity over conditions, and death comes at 0. The cause is the heaviest condition. Each condition has a severity from 0 to 1, a `since` time and a treatment quality, `treated`, from 0 to 1.
  - **Wound**: below 0.6 it heals, 0.003/h untreated and 0.008/h treated, at half speed when hungry or thirsty. At 0.6 and above it bleeds, +0.01/h until treated. Each hour an untreated wound can turn into an infection, with a chance of 0.003 × severity; treatment cuts the chance to a fifth.
  - **Infection**: untreated it grows 0.001/h, or 0.004/h in a weak body. Treated, it clears at 0.01/h.
  - **Illness**: about once per 10,000 h. It rises at 0.006/h to a peak 2–5 days in, then falls at 0.008/h. Treatment halves the rise and speeds the fall.
  - **Heatstroke**: working or travelling at heat 0.6 or more risks it, at a rate of 0.01/h × heat × (1 + litres short). It grows while the person keeps going and passes with rest.
  - **Dehydration and malnutrition**: severity follows the deficit.
  - **Chronic** (elders): onset per life day is 0.002 × (age − 60)/10, and it grows 0.004 per life day (0.0015 treated).
  - Traits: tough people get worse 0.7× as fast and frail people 1.4×.
- **Mood** = trait base (optimist +8, pessimist −8) + the modifiers `{key, value, until}`. Modifiers expire at `until`; with `until: null` they last until whoever added them removes them. Need modifiers are rebuilt every step:
  - thirst: −5, −12, −25, −40 by stage
  - hunger: −4, −10, −20, −30 by stage
  - tired: −6, or −15 below 0.1 energy
  - pain: up to −40
  - well kept: +6
  - working in the heat: −4
- **Breaks**:
  - A minor break comes below −25, a major one below −50; nervous people break 8 points sooner and steady ones 8 later.
  - While below a threshold, the chance per hour is 0.03 × (1 + points below / 10).
  - Minor: 8 h refusing work. Major: 24 h, or the person leaves for good (40%).
  - After a break, catharsis adds +10 for a day.
- **Skills** (0–5):
  - Each working hour in a skill adds 0.0006 / (1 + level), × 1.5 for quick learners and children and × 0.7 for slow learners and elders. Going from 0 to 2 takes about 6,700 working hours (about 33 real hours of 1× play at 8 h of work a day).
  - Unused skills lose 0.0005% of their level per hour.
- **Job choice**:
  - A task scores more for urgency, skill, priority, a matching role and the industrious trait.
  - It scores less for distance, heat (outdoor tasks), fatigue, hunger or thirst, low capacity (heavy tasks most) and the lazy trait.
- **Traits** come from the seed (1–3, no opposite pairs): tough/frail, optimist/pessimist, hardy (less water, half the heatstroke risk), glutton/ascetic, quick/slow, industrious/lazy, nervous/steady.

## Harness results (seed 1, 100 h, 20 people)

| Supply | What happens |
| --- | --- |
| `ok` (14 L and 1.25 rations per person a day) | Stable: no deaths in 5 seeds. Mood is about +6 and health about 0.99. 6–16 minor breaks, about 100 injuries and 120 illnesses, all treated. |
| `hungry` (water, no food) | Malnourished by day 5 (mood −8, health 0.90). Mood is −29 by day 30. Deaths from day 38 and all gone by about day 45; one walks out. |
| `thin` (water, 60% food) | Slow decline. Health is 0.78 at day 30. Deaths start at day 58, then the survivors stabilise once there are fewer mouths. |
| `short` (half of everything) | The water pool runs dry. Dehydration from day 2 and deaths from day 3.7. |
| `none` | Deaths within about 1.5 days. |
| `--beds 10` | No deaths, but mood drops 2–3 points and illness doubles from sleeping rough. |
