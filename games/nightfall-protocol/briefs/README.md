# Nightfall briefs

Nightfall Protocol is being built in parallel conversations. This folder is how they stay in step.

- `00-foundation.md` holds the general formula and values: the pitch, the three layers, art direction, units and numbers that every part shares. **It is owned by the home conversation.** Topic conversations read it and follow it. If a topic needs a foundation value changed, propose it in its pull request description instead of editing the file.
- Each topic brief is a starting prompt for its own conversation:

| Brief | Topic | State |
|---|---|---|
| `combat.md` | Turn-based combat that folds out of real-time exploration | demonstration running |
| `tactical-maps.md` | Real-world sectors, baking and streaming the ground | groundwork running |
| `strategy-map.md` | The region map: squads, knowledge, travel, time | prototype running |
| `models.md` | Characters, clothing and hair layers, props, weapons | figure study done |
| `animation.md` | Procedural motion for walking, actions and idles | shared module running |
| `building.md` | The base: site, layout, construction and the tasks buildings offer | one-page design done |
| `people.md` | Survivors' individual simulation: needs, health, age, mood, relationships, reproduction | not started |
| `settlement.md` | Stores, barter and trade, roles, rules and civics | not started |
| `lore.md` | Setting, history, factions, item and place lore that feeds loot | backstory in, four open questions |
| `interiors.md` | Procedural interiors for every building: plans, doors, furniture, loot | not started |

## Starting a topic conversation

Open a new Claude Code session on `pdevvle/PPS-tools` and say:

> Read `games/nightfall-protocol/briefs/00-foundation.md` and `games/nightfall-protocol/briefs/<topic>.md`, then start on the brief's first tasks. Base your work on branch `claude/quickbooks-book-categorizer-Q85ha` and open your pull request against it.

## Rules for every topic conversation

1. Stay inside your topic's files (each brief lists them). If you must touch another topic's file, keep the change minimal and list it under "Touches other topics" in your PR description.
2. Keep the interfaces your brief lists stable, or change them on purpose and say so in the PR.
3. Mockups are single HTML files, also published as Artifacts; follow the conventions in the foundation.
4. When a decision is made in your conversation that other topics need, write it into your brief's "Decisions" section in the same PR, and flag it in the PR description so the home conversation can lift it into the foundation.
