# arme2cosmos

A migration **assistant** that ports legacy **Artemis 2.8** XML missions (`MISS_*.xml`)
to **Artemis Cosmos** MAST. It is a *scaffolder*, not a perfect compiler: the goal is to
get a mission **80–90% of the way** to a runnable Cosmos mission and leave a clear,
per-item punch-list (`MIGRATION_NOTES.md`) for you to finish.

- **No dependencies** — Python 3.10+ is all you need.
- Output is idiomatic MAST: every translatable command becomes a real call; everything
  else is a `# TODO` with the original XML preserved inline.

---

## Install

Run it directly from the folder:

```sh
python -m arme2cosmos --help
```

Or install it to get the `arme2cosmos` command:

```sh
pip install .
arme2cosmos --help
```

---

## The three commands

| Command | What it does | Writes files? |
|---|---|---|
| `report`  | Shows how much of a mission maps to Cosmos | No |
| `artmap`  | Builds the ship-hull crosswalk (`hullmap.json`) | `hullmap.json` |
| `convert` | Scaffolds a full Cosmos mission folder | Yes (`out/<name>/`) |

### Typical workflow

```sh
# 1. (once) Build the hull crosswalk from the two game data files.
arme2cosmos artmap \
    --vesseldata /path/to/Artemis2.8/dat/vesselData.xml \
    --shipdata   /path/to/Cosmos/data/shipDataBB.json \
    --out hullmap.json

# 2. See how much of a mission (or a whole folder) maps.
arme2cosmos report /path/to/Artemis2.8/dat/missions/MISS_TheEndOfPeace

# 3. Scaffold it, using the hullmap for real ship art.
arme2cosmos convert /path/to/Artemis2.8/dat/missions/MISS_TheEndOfPeace \
    --hullmap hullmap.json --out out/

# 4. Open out/<name>/MIGRATION_NOTES.md and finish the TODOs by hand.
```

Every command accepts a single `.xml` file, a single `MISS_*` mission folder, or a parent
directory full of them (it recurses and skips `~` editor backups).

---

## `report` — see what maps

```sh
arme2cosmos report <path> [--json] [--summary] [--detail]
```

Classifies every command/condition in a mission. For one mission it prints a per-kind
breakdown; for many it prints a one-line summary per mission plus a corpus total.

Each item is rated:

| Status | Meaning |
|---|---|
| `full`    | Translated mechanically, high confidence |
| `partial` | Translated, but leaves a `# TODO` (closest-fit) |
| `manual`  | Needs you to wire it (a few object properties, GM keys) |
| `unknown` | Not recognized (shouldn't normally happen) |

Options: `--json` (machine-readable), `--summary` (skip the per-kind detail for one
mission), `--detail` (corpus mode: also print each mission's breakdown).

---

## `artmap` — ship art crosswalk

```sh
arme2cosmos artmap --vesseldata <vesselData.xml> --shipdata <shipDataBB.json> [--out hullmap.json]
```

Artemis 2.8 and Cosmos name their ship hulls differently, so this builds a best-effort
map between them by matching each 2.8 vessel (race + class) to the closest Cosmos hull.

It prints how many vessels matched and writes `hullmap.json`. Hand that file to
`convert --hullmap` so converted ships use real Cosmos art instead of placeholders.
Vessels it couldn't match confidently are listed under `unmatched` in the file — those
will use a placeholder you can swap later.

---

## `convert` — scaffold a mission

```sh
arme2cosmos convert <path> [--out out] [--lib-version v1.4.0_dev] [--hullmap hullmap.json]
```

Creates a ready-to-open Cosmos mission folder:

```
out/<name>/
├── story.mast           # the translated mission (the main file)
├── script.py            # standard Cosmos entry-point boilerplate
├── story.json           # the sbslib + LegendaryMissions addons the mission needs
├── description.yaml     # mission browser entry
├── __lib__.json         # library version marker
└── MIGRATION_NOTES.md   # your punch-list of TODOs / things to verify
```

Options:
- `--out` — where to write (default `out/`).
- `--lib-version` — the library version tag written into `story.json`
  (default `v1.4.0_dev`; set it to match the libraries installed with your Cosmos).
- `--hullmap` — a `hullmap.json` from `artmap`, for real ship art.
- `--event-model` — how 2.8 events are generated:
  - `hybrid` (default) — flag-chained "scene" events stay one readable sequence;
    events with independent triggers (a timer/distance/dock not gated by the chain)
    run as concurrent tasks, matching how 2.8 checks all events every tick.
  - `linear` — force every event into a single sequential chain (simpler to read /
    hand-edit; use for missions you know are strictly sequential).

### What it translates for you

Positions are converted automatically (2.8 and Cosmos use mirrored coordinates — you
don't have to think about it). Translated mechanically:

- **Spawns** — players, enemies, neutrals, stations, monsters, black holes, anomalies.
  Named objects are remembered, so later commands that reference them by name still work.
- **Terrain** — nebula / asteroid / mine fields.
- **Messages** — comms text, big chapter titles, audio messages, and console warnings.
- **AI** — common enemy/monster behaviors (chase player, chase station, attack, …).
- **Movement** — `direct` to a point or a target; `destroy`.
- **Story flow** — events become a step-by-step sequence; "when" conditions become real
  waits (distance, sphere, fleet destroyed, docked, object exists, timers).
- **Comms buttons** — become a comms menu (`//comms` route).
- **Game Master buttons** — become a Game-Master comms menu.
- **Tags** — preserved as object data, with notes on rebuilding the tag gameplay.

### What you finish by hand

Anything without a clean Cosmos equivalent is written as a `# TODO` (with the original
XML next to it) and listed in `MIGRATION_NOTES.md`, for example:

- Ship art where no confident match was found (a placeholder is used).
- Setting specific object properties (the 2.8 and Cosmos property names differ).
- Game-Master key/click interactions.
- Anything 2.8-specific with no Cosmos counterpart.

Treat the output as a strong first draft: the structure, spawns, positions, and story
flow are in place; you polish the details the notes call out.

For the full command-by-command coverage (what's finished vs. what needs a human
decision), see [`docs/coverage.md`](docs/coverage.md); property mappings are detailed in
[`docs/property_map.md`](docs/property_map.md).

---

## Running the converted mission

1. Copy the `out/<name>/` folder into your Cosmos `data/missions/` directory.
2. Make sure the libraries listed in its `story.json` are installed with your Cosmos
   (adjust `--lib-version` when converting if your version differs).
3. Start Cosmos, host a server, and pick the mission from the list — or smoke-test it
   headless if you have the Cosmos dev tools.

"Close enough to the original" is the goal — expect to playtest and tweak.
