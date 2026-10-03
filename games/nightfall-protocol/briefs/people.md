# Brief: people (survivors' individual simulation)

Read `00-foundation.md` first, especially "Time: two clocks" and "Simulation rules".

## Goal

Every survivor is a person with a body, a history and relationships: they drink, eat, sleep, get hurt and sick, age, feel, like and dislike each other, pair up and have children. Their state drives what they choose to do and feeds the settlement's systems (`settlement.md`).

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

## Out of scope

Stores, trade and civics (`settlement.md`), construction (`building.md`), appearance geometry (`models.md`).
