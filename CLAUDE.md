# arme2cosmos — Guide for Claude

A command-line tool that converts **Artemis 2.8 XML missions** (`MISS_*.xml`) into
**Artemis Cosmos MAST** mission scaffolds. Pure translator: it reads 2.8 XML and writes
a `story.mast` (+ `script.py`, `story.json`, `description.yaml`, `__lib__.json`,
`MIGRATION_NOTES.md`) for a human to finish.

## The one rule that shapes everything

**This tool has ZERO runtime dependency on `sbs_utils` or Cosmos — stdlib only.**
It must run standalone (e.g. `pipx`/`python -m arme2cosmos`) on a machine with no Cosmos
install. Never `import sbs_utils` (or `sbs`, or any Cosmos module) in `arme2cosmos/`.

The split is: **the tool is standalone; the missions it GENERATES are not.** A generated
`story.mast` depends on two things at *run* time (inside Cosmos), never at the tool's
build time:

1. the **`a2x` layer** in `sbs_utils` (the `a2x_*` functions the tool emits), and
2. the **LegendaryMissions (LM) addons** listed in the generated `story.json`.

So the tool only ever emits *text* — calls like `a2x_create_enemy(...)` and routes like
`//damage/destroy` — and is not coupled to the code that implements them.

## Relationship with `sbs_utils` (the `a2x` layer)

`a2x` is a companion layer that lives in **`sbs_utils`**, not in this repo:
`sbs_utils/sbs_utils/procedural/a2x/` (`coords.py`, `spawn.py`, `props.py`, `comms.py`,
`ai.py`, `conditions.py`, `terrain.py`). It is a *comfort layer* for 2.8 idioms — small
functions that take **2.8-style arguments** and do the Cosmos-side work, so the generated
MAST reads close to the original mission.

- **Registration.** `sbs_utils` registers the module with
  `MastGlobals.import_python_module('sbs_utils.procedural.a2x', 'a2x')`, which exposes
  each public function as an **`a2x_`-prefixed MAST global** (`pos` -> `a2x_pos`,
  `create_enemy` -> `a2x_create_enemy`, `within` -> `a2x_within`, ...). The tool emits
  those prefixed names; it does **not** import a2x.
- **What a2x hides:** the 2.8<->Cosmos **coordinate flip** (`a2x_pos` = `Vec3.from2x_coord`,
  X and Z mirror about 100000), property-name mapping (`a2x_set_object_property`), the
  elite-ability system (`a2x_set_special`), creature placeholders, etc.
- **Grounded IDs.** a2x `create_*` return the spawned object's **ID**, not the object
  (the engine can delete objects). The tool stores `shared obj_x = a2x_create_*(...)` and
  later calls re-validate with `to_space_object(id)`.
- **If a conversion needs new behaviour**, the usual fix is to **add/extend an `a2x_*`
  function in `sbs_utils`** and have the tool emit a call to it — keep mapping logic in
  a2x, keep the tool a thin text generator. Editing a2x means editing the **`sbs_utils`
  repo** (a different working tree / branch), and those changes need to ship in the
  `sbs_utils` `.sbslib`.
- **a2x must NEVER depend on LM.** a2x may reference LM only by name/feature-detection
  (e.g. scheduling `handle_elite_abilities`, which *lives* in the LM fleets addon), never
  by importing it. LM is optional; a2x ships inside `sbs_utils`.

## Relationship with LegendaryMissions (LM)

LM is a set of **MAST addon libraries** (`.mastlib`) that provide standard gameplay:
consoles, docking, comms, damage, prefabs, fleets, upgrades, etc. A gameplay port needs
them, so the tool lists them in the generated `story.json`.

- **Baseline addons** always written: `consoles, docking, comms, damage, prefabs, fleets`
  (`_BASELINE_ADDONS` in `convert.py`).
- **Feature-detected** addons get added as the emitters encounter the need (`em.addons`):
  e.g. `upgrades` for pickups, `ai` for `add_ai`, `fleets` for elite abilities.
- **What the generated MAST relies on from LM:**
  - `spawn_players`, `docking_standard_player_station`, `prefab_fleet_raider`,
    `prefab_side_generic` (fleets/docking/prefabs).
  - The elite-ability driver `handle_elite_abilities` and the `elite/*` roles (fleets).
  - `//signal/ship_docked` — **emitted by the LM docking addon** when a ship docks at a
    station; the tool routes 2.8 `if_docked` events onto it.
  - `//damage/destroy` is an engine route (not LM), used for respawn-on-destroy.
- The tool references LM **only as names in `story.json` and as labels/signals in the
  emitted MAST** — it never imports or inspects LM. LM is feature-detected and optional;
  a mission can in principle run with fewer addons if it uses fewer features.

## Validating a conversion

The tool's own unit tests are **stdlib-only** (`python -m unittest discover -s tests`)
and need neither Cosmos nor `sbs_utils` (the one YAML-parse test skips if `sbs_utils`
isn't importable). But to check that *generated* MAST is correct you need Cosmos:

- **Compile** — `MastStory().compile(code, ...)` with `sbs_utils` on `PYTHONPATH`
  (catches MAST syntax/label errors). The engine compiler is stricter than the mock.
- **Headless run** — `python -m cosmos_dev.mission_runner <mission> --test <secs>
  --map 0 --use-working-tree`. `--use-working-tree` makes it load the working-tree
  `sbs_utils` (so a2x edits are picked up over the packaged `.sbslib`).

## Repo layout

```
arme2cosmos/
├── model.py      # XmlNode / Event / Mission; create-type normalization
├── parser.py     # tolerant ElementTree parser + corpus discovery
├── emit.py       # per-command/-condition emitters (the bulk of the mapping)
├── convert.py    # assembles the scaffold (event model, story.json, description.yaml, notes)
├── artmap.py     # vesselData <-> shipDataBB hull crosswalk (-> hullmap.json)
├── coverage.py   # read-only coverage report
└── cli.py        # report / convert / artmap subcommands
docs/
├── property_map.md  # 2.8 set_object_property -> Cosmos data_set crosswalk + status
└── coverage.md      # command/condition coverage, the event model, open questions
tests/            # unittest, stdlib only
```

## Conventions

- **Event model** (`--event-model`, default `hybrid`): 2.8 events run continuously. `hybrid`
  keeps flag-chained scenes a linear chain, runs independent events as re-firing polling
  loops, and converts single-trigger ones to engine routes (respawn -> `//damage/destroy`,
  dock -> `//signal/ship_docked`, flag -> `//signal/a2x_flag_*`). `a28_compatible` makes
  every event its own polling task (faithful flat-event fallback); `linear` is one chain.
  See `docs/coverage.md`.
- **Output is a scaffold.** Positions/spawns are real; everything the tool can't map is a
  `# TODO`. Don't invent gameplay — emit a TODO and (when useful) `em.note(...)`.
- **`--lib-version`** (default `v1.4.0`) is the version tag written into `story.json` /
  `__lib__.json`; match the libraries installed alongside the missions.
- **Engine text is ASCII-only** — no emoji / smart-quotes / em-dashes in any string that
  ends up in generated MAST or YAML the engine renders.
- Keep mapping knowledge in two places: per-command logic in `emit.py`, property names in
  `docs/property_map.md` (mirrored by the a2x `props.py` table in `sbs_utils`).
