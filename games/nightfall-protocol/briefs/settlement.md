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
