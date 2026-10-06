# Brief: people (survivors' individual simulation)

Read `00-foundation.md` first, especially "Time: two clocks" and "Simulation rules".

## Goal

Every survivor is a person with a body, a history and relationships: they drink, eat, sleep, get hurt and sick, age, feel, like and dislike each other, pair up and have children. Their state drives what they choose to do and feeds the settlement's systems (`settlement.md`).

## Where it stands

- **Done (first tasks 1 and 2)**: `tools/people/people.js` holds the survivor record and the water, food, energy, health, mood, skill, age and job-choice rules. `tools/people/harness.js` runs 20 survivors over 100 h of play in about 1.5 s. `node tools/people/test.js` runs 17 checks. See `tools/people/README.md`.
- **Not yet**: relationships, attraction, partnership, reproduction and grief (task 3; `rel` and `partner` are in the record but nothing uses them yet) and the inspector page (task 4).

## Systems

- **Water**: litres, drain 0.5 L/h awake (world clock), doubled 10:00–18:00 in heat; dehydration stages.
- **Food**: calories, drain by activity; malnutrition stages; preferences and spoilage risk.
- **Energy and sleep**: needs a bed or ground; sleeping rough hurts mood and health.
- **Health**: conditions instead of one bar (wounds from combat, infection, illness, heatstroke, dehydration, malnutrition, chronic conditions in old age), each with severity, progression and treatment.
- **Age**: life stages (child, teen, adult, elder) on the life clock. The life clock is very slow (one life day per real hour), so age is mostly fixed per survivor; stages still set capacity and needs, and long campaigns move people along slowly.
- **Mood**: sum of time-limited modifiers (needs, pain, events, environment, relationships, civics decisions); thresholds lead to minor and major breaks.
- **Traits and skills**: traits from the seed; skills grow with practice and decay slowly.
- **Relationships**: opinion per pair, moved by interactions, shared events and traits. Attraction depends on traits, compatibility, age stage (adults only) and opinion. Partnership is mutual and can end.
- **Reproduction**: partnered adults may conceive; pregnancy on the life clock (about 270 life days, so hundreds of hours of play: a rare, late event); birth risk with health and care; children inherit traits and features (FigureKit faces from both parents' seeds, with heritage blending).
- **Death**: from health, age, combat; grief spreads through relationships.

## Interfaces

- Survivor record: plain data (id, seed, birth on the life clock, body, needs, conditions, traits, skills, mood modifiers, relationships). Shared with `settlement.md` (consumption, roles, civics), `building.md` (jobs at the base), `combat.md` (squad members' health and wounds persist both ways), `models.md` (appearance from seed, age and inheritance).
- Job choice: a utility score per available task from needs, skills, traits, priorities and distance; tasks are offered by `building.md` and `settlement.md`.

## First tasks

1. Survivor data model and the needs, health and mood systems as pure functions.
2. A headless harness: 20 survivors simulated over 100 hours of play (2,500 game days, about 100 life days) compressed to seconds, charting needs, mood, health, departures and deaths. Use it to tune every rate.
3. Relationships, attraction, partnership and reproduction on top, checked in the harness over a 300-hour campaign.
4. A small inspector page: pick a survivor, see their needs, conditions, mood modifiers and relationships over time.

## Decisions

Values chosen in the harness; all are named constants at the top of `people.js` and exported as `People.RATES`.

- **Clocks**: water, food, energy, conditions, mood and skills run on world minutes. Age, stage and chronic illness run on life days (`LIFE_RATIO` 25). The rules are settled in steps of up to 60 game minutes.
- **Water**: awake 0.5 L/h × (1 + heat), asleep 0.15 L/h × (1 + heat). That is about 13 L a day for an adult in early summer on the harness day (8 h of sleep, 5 h of work in the cool, 11 h of rest through the heat).
  - Stages by deficit: thirsty at 1.5 L, dehydrated at 3, severe at 5, critical at 7.5. Death at 10 L, about 20 h with no water in the heat.
  - People drink back up to 1.2 L/h on top of what they lose.
- **Food**: kcal/h of 60 asleep, 85 resting, 170 working, 200 travelling, about 2,250 kcal a day.
  - Stages by deficit: hungry at 1,200 kcal, malnourished at 8,000, severe at 30,000, starving at 60,000. Death at 100,000, about 5–6 weeks with water.
  - People eat back up to 700 kcal/h. Nobody eats or drinks asleep.
  - By stage, water / food are ×0.6/0.6 for children, 0.9/0.95 for teens and 0.9/0.8 for elders. Body reserves are ×0.4 for children and ×0.8 for teens and elders.
- **Energy** (0..1): it drains 0.045/h resting, 0.065/h working and 0.075/h travelling. Sleep restores 0.14/h in a bed and 0.11/h on the ground, so the ground barely covers a normal day. A night in a bed gives +3 mood for 18 h. A night on the ground gives −5 and triples the chance of illness.
- **Stages** (years): child 0–12, teen 13–17, adult 18–59, elder 60+.
  - Capacity for work: 0.4, 0.8, 1 and 0.7.
  - Children only take light tasks (cook, grow, haul, nurse, craft).
  - New survivors are 70% adults, 12% elders, 10% teens and 8% children.
- **Health** = 1 − Σ weight × severity. Death comes at 0, with the heaviest condition as the cause. Weights:

  | Wound | Infection | Illness | Heatstroke | Dehydration | Malnutrition | Chronic |
  | --- | --- | --- | --- | --- | --- | --- |
  | 1 | 1 | 0.8 | 1 | 1 | 1 | 0.7 |

  Severity of dehydration and malnutrition follows the deficit between the first stage and death.
- **Conditions** (per hour unless said):
  - **Wound**: heals 0.003, or 0.008 treated, at half speed when hungry or thirsty. At 0.6 and above it bleeds +0.01 until treated. An untreated wound turns into an infection at 0.003 × severity; treated, at a fifth of that.
  - **Infection**: grows 0.001, or 0.004 in a malnourished or dehydrated body. Treated, it clears at 0.01 × quality.
  - **Illness**: onset 0.0001, ×3 after sleeping rough, more when malnourished. It rises 0.006 to a peak 48–120 h in, then falls 0.008.
  - **Heatstroke**: onset 0.01 × heat × (1 + litres short) when working or travelling at heat 0.6 or more. It grows 0.08 × heat while the person keeps going and falls 0.05 at rest.
  - **Chronic** (elders): onset 0.002 × (age − 60)/10 per life day. It grows 0.004 per life day, or 0.0015 treated.
  - **Traits**: tough people get worse 0.7× as fast and frail people 1.4×.
- **Mood**: trait base (optimist +8, pessimist −8) + modifiers. Need modifiers are rebuilt each step:
  - thirst: −5, −12, −25, −40 by stage
  - hunger: −4, −10, −20, −30 by stage
  - tired: −6 below 0.3 energy, −15 below 0.1
  - pain: −40 × the weighted pain of conditions, at most −40
  - well kept: +6
  - working in heat over 0.5: −4

  A well-supplied group sits at about +6.
- **Breaks**:
  - Minor below −25, major below −50; ±8 for nervous and steady people.
  - The chance per hour is 0.03 × (1 + points below the threshold / 10).
  - Minor: 8 h refusing work. Major: 24 h, or the person leaves for good (40%: `at:'gone'`, still alive).
  - Catharsis adds +10 for a day after a break.
- **Skills** 0–5: each working hour in a skill adds 0.0006 / (1 + level), × 1.5 for quick learners, × 0.7 for slow ones, and scaled by stage. Unused skills lose 0.0005% of their level per hour, about 26% over a 100-hour campaign of disuse. A dedicated worker gains 1–3 levels in a campaign.
- **Job choice**: the score adds 1 × urgency, 0.6 × skill/5, 0.8 × priority, 0.3 for a matching role and ±0.15 for industrious or lazy. It subtracts:
  - 0.15 per km of distance
  - 0.5 × heat for outdoor tasks (half for hardy people)
  - 0.6 × (1 − energy)
  - 0.8 × the worse of thirst and hunger
  - lost capacity
  Self-care tasks score 2 × need.
- **Harness** (seed 1, 100 h, 20 people, results in `tools/people/README.md`):
  - Supply of 14 L and 1.25 rations per person a day: stable over 5 seeds, no deaths. About 100 work injuries and 120 illnesses are all treated from 0.3 med kits a day.
  - No food: malnourished within 5 days, deaths from day 38.
  - Half of everything: dehydration deaths from day 4.
  - No supply: deaths within 1.5 days.

## Proposals (foundation and contract)

- **Proposal: resting water.** The foundation's 0.5 L/h awake doubled in heat gives about 13 L per adult a day at the base, which is high next to `campaign.waterRate`'s 0.2–0.4 L/h for resting in shade. The proposal is a lower resting rate in shade at the base (0.3 L/h × (1 + heat), about 9 L a day). It is not applied; `WATER_AWAKE` is one constant.
- **Proposal: skills on practice time.** The foundation lists "skills that build over years" on the life clock. On the life clock, skills would barely move within a campaign (about 100 life days). The proposal is for skills to grow per world hour of practice, as built here, at a rate tuned so a campaign moves a worker 1–3 levels.
- **Contract additions (proposed for `tools/sim/README.md`)**:
  - `env.skill`: the skill practised while working.
  - `step` returns an event list.
  - Extra record fields: `rng`, `health`, `brk`, `slept`, `asleep`, `died`, `left`.
  - `at:'gone'` for someone who walked out.
  - New functions `removeMood`, `injure`, `treat` and `addCondition`, for combat and the medic.
- **Settlement needs**:
  - Rationing should be able to favour some people. Equal proportional cuts make a water shortage kill everyone together within days.
  - A medicine and treatment hook is needed: who treats, with what quality.
  - Settlement should call `removeMood` for its own `until: null` modifiers.

## Out of scope

Stores, trade and civics (`settlement.md`), construction (`building.md`), appearance geometry (`models.md`).
