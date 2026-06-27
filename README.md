# arme2cosmos

A migration **assistant** that ports legacy **Artemis 2.8** XML missions (`MISS_*.xml`)
to **Artemis Cosmos** MAST. It is a *scaffolder*, not a perfect compiler: the goal is to
get a mission **80–90% of the way** to a runnable Cosmos mission and leave a clear,
per-item punch-list (`MIGRATION_NOTES.md`) for a human to finish.

- **Stdlib-only** — no pip dependencies. Python 3.10+.
- Output is idiomatic MAST: every translatable command becomes a real call; everything
  else is a `# TODO` with the original XML preserved inline.
- Validated end-to-end: the whole 13/27-mission a28 corpus compiles, and a converted
  mission runs headless under the Cosmos `mission_runner` with no runtime errors.

> Design rationale and the full 2.8→MAST mapping live in `A2X_MIGRATION_PLAN.md`
> (in the `sbs_utils` repo).

---

## Install

No install required — run it as a module from the repo root:

```sh
python -m arme2cosmos --help
```

Or install it (editable) to get the `arme2cosmos` console script:

```sh
pip install -e .
arme2cosmos --help
```

---

## The three commands

| Command | What it does | Writes files? |
|---|---|---|
| `report`  | Read-only coverage analysis: what maps, what doesn't | No |
| `artmap`  | Build the ship-hull crosswalk (`hullmap.json`) | `hullmap.json` |
| `convert` | Scaffold a full Cosmos mission folder | Yes (`out/<name>/`) |

### Typical workflow

```sh
# 1. (once) Build the hull crosswalk from the two game registries.
python -m arme2cosmos artmap \
    --vesseldata /path/to/a28/dat/vesselData.xml \
    --shipdata   /path/to/Cosmos/data/shipDataBB.json \
    --out hullmap.json

# 2. See how much of a mission (or a whole folder) maps.
python -m arme2cosmos report /path/to/a28/dat/missions/MISS_TheEndOfPeace

# 3. Scaffold it, resolving real ship art from the hullmap.
python -m arme2cosmos convert /path/to/a28/dat/missions/MISS_TheEndOfPeace \
    --hullmap hullmap.json --out out/

# 4. Read out/<name>/MIGRATION_NOTES.md and finish the TODOs by hand.
```

All commands accept a single `.xml` file, a single `MISS_*` mission folder, or a parent
directory containing many (it recurses, de-duplicates case-insensitively, and skips `~`
editor backups).

---

## `report` — coverage analysis

```sh
python -m arme2cosmos report <path> [--json] [--summary] [--detail]
```

Parses each mission and classifies every command/condition against the 2.8→MAST mapping
table. For one mission it prints a per-kind breakdown; for many it prints a one-line-per-
mission overview plus an aggregate and a list of any unmapped kinds.

Coverage statuses:

| Status | Meaning |
|---|---|
| `full`    | Mechanical, high-confidence translation |
| `partial` | Translatable, but emits a `# TODO` (closest-fit) |
| `manual`  | Needs a human / a chosen new path (some object properties, GM keys) |
| `unknown` | Not in the mapping table yet (should stay at 0) |

Flags: `--json` (machine-readable), `--summary` (omit per-kind detail for a single
mission), `--detail` (corpus mode: also print each mission's breakdown).

---

## `artmap` — hull crosswalk

```sh
python -m arme2cosmos artmap --vesseldata <vesselData.xml> --shipdata <shipDataBB.json> [--out hullmap.json]
```

There is no shared identifier between Artemis 2.8's `vesselData.xml` and Cosmos's
`shipDataBB.json`, so this builds a **draft** crosswalk by fuzzy-matching each 2.8 vessel
(race + classname) to the Cosmos hull on the same side whose name/key best matches.

It prints a summary (`matched`/`unmatched`) and writes a `hullmap.json` with:
`by_hull_id` (2.8 `hullID` → Cosmos art key), `by_race_class`
(`race|classname` → key), and `unmatched` (vessels with no confident match —
review these). Pass the file to `convert --hullmap` to resolve real ship art instead of
placeholders.

---

## `convert` — scaffold a mission

```sh
python -m arme2cosmos convert <path> [--out out] [--lib-version v1.4.0_dev] [--hullmap hullmap.json]
```

Writes a complete mission folder per source mission:

```
out/<name>/
├── story.mast          # the translated mission (the main artifact)
├── script.py           # standard Cosmos entry-point boilerplate
├── story.json          # sbslib + feature-detected LegendaryMissions addons
├── description.yaml     # mission browser entry (from <mission_description>)
├── __lib__.json         # library version manifest
└── MIGRATION_NOTES.md   # the punch-list of TODOs / things to verify
```

Flags:
- `--out` — output root directory (default `out/`).
- `--lib-version` — the sbslib/mastlib version tag written into `story.json`
  (default `v1.4.0_dev`; must match the libs in your missions `__lib__/` folder).
- `--hullmap` — a `hullmap.json` from `artmap` to resolve real ship art.

### What gets translated

Real, mechanical translations (positions pass through verbatim — the `a2x_*` helpers
flip 2.8 coordinates to Cosmos internally):

- **Spawns** — `create` player/enemy/neutral/station/monster/blackHole/anomaly →
  `a2x_create_*`. Named objects are captured into MAST variables (`obj_<name>`) so later
  commands that reference them by name resolve.
- **Terrain** — `create` nebulas/asteroids/mines → `a2x_create_*` (sphere/line modes,
  `random_range` jitter, `seed`).
- **Messages** — `incoming_comms_text`/`big_message`/`incoming_message`/
  `warning_popup_message` → the comms waterfall / info-panel helpers.
- **AI** — `add_ai`/`clear_ai` → `a2x_add_ai`/`a2x_clear_ai` (common 2.8 brain types
  map to LegendaryMissions `ai` brains; unmapped types emit the call + a note).
- **Movement** — `direct` → `target_pos`/`target`; `destroy` → `a2x_destroy`.
- **Events** — flag/timer-gated events become a linear chain of `---` labels; conditions
  become real waits: `if_distance`→`await distance_less/greater`, `if_inside_sphere`→
  `await distance_point_less`, `if_fleet_count`→`await destroyed_all(role("fleet_N"))`,
  `if_docked`→a `a2x_is_docked` poll, `if_exists`→`object_exists` guard.
- **Comms buttons** — `set_comms_button` + its `if_comms_button` handler (matched by
  text) → a `//comms` route with `+ "label":` buttons.
- **GM buttons** — `set_gm_button` + `if_gm_button` → a gamemaster-gated `//comms` route.
- **Tags** — `set_monster_tag_data`/tag-match conditions → inventory values (notes point
  to rebuilding the tag-torpedo gameplay).

### What's left as TODO

Everything that has no clean mechanical mapping is emitted as a `# TODO` line (with the
original XML inline) and collected into `MIGRATION_NOTES.md`, e.g.:

- Ship **art** where the hullmap had no confident match (placeholder + note).
- `set_object_property` (2.8 property names differ from Cosmos `data_set` keys).
- `if_gm_key` / `use_gm_position` / `use_gm_selection` (GM click/key interactions).
- `spawn_external_program` (no Cosmos equivalent).

### Coordinate system note

Artemis 2.8 uses a corner-origin map (x,z in 0..100000); Cosmos mirrors X and Z about the
map centre (a 180° horizontal rotation). The generated MAST passes **2.8 coordinates
verbatim** to `a2x_*` helpers, which apply `Vec3.from2x_coord` internally — so positions
"just work". Headings (`angle`) are not auto-applied; `a2x_angle()` exists if needed.

---

## Runtime requirements for the generated mission

The output references the `a2x_*` helper layer, which lives in **`sbs_utils`
(v1.4.0_dev+)**. To run a converted mission:

1. Place the `out/<name>/` folder in your Cosmos `data/missions/` directory.
2. Ensure the `story.json` libs (sbslib + the feature-detected LegendaryMissions
   addons) exist in the missions `__lib__/` folder for your `--lib-version`.
3. Run it (headless smoke test):
   ```sh
   python -m cosmos_dev.mission_runner data/missions/<name> --test 20 --map 0 --use-working-tree
   ```
   `--use-working-tree` is needed if your `a2x` changes are only in the working tree (not
   yet packaged into the sbslib).

---

## Layout

```
arme2cosmos/
├── model.py      # typed mission model (Mission / Event / XmlNode)
├── parser.py     # tolerant ElementTree parser; corpus discovery
├── coverage.py   # the 2.8 XML -> Cosmos MAST mapping/coverage table (drives `report`)
├── artmap.py     # vesselData <-> shipDataBB hull crosswalk
├── emit.py       # per-command emitters (the translation rules)
├── convert.py    # assembles the scaffold; event chain + comms/GM routes
├── cli.py        # argparse CLI
└── __main__.py
tests/            # stdlib unittest (no pip)
```

## Tests

```sh
python -m unittest discover -s tests
```
