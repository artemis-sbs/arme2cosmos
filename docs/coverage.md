# arme2cosmos coverage & open questions

Status of the 2.8 -> Cosmos MAST conversion: what's finished, what's partial, and what
needs a human decision. Property-level detail for `set_object_property` lives in
[`property_map.md`](property_map.md).

## Pipeline status

- The full a28 corpus (23 missions) **compiles** under `MastStory`.
- Converted missions **run headless** with no runtime errors; with `--exercise` a
  mission plays its comms/event chain to game-end.
- Remaining `# TODO` lines across the corpus: ~1525 (down from ~5384). ~73% of those are
  unmapped `set_object_property`/`addto`/`copy` properties (one table -- see
  [`property_map.md`](property_map.md)); the rest is unmappable 2.8 gameplay or the
  decisions below.

**Legend:** DONE = real translation · PARTIAL = real for the mapped cases, `# TODO` for
the rest · TODO = not yet wired · NO-EQUIV = no Cosmos equivalent (stays `# TODO`).

---

## Commands

| 2.8 command | Status | Cosmos / notes |
|---|---|---|
| `create` player/enemy/neutral/station | **DONE** | `a2x_create_*` (coords flipped; named objects captured) |
| `create` monster / whale | **DONE** | `a2x_create_monster` (real art for classic/derelict, placeholder + `creature_*` role otherwise) |
| `create` genericMesh | **DONE** | `a2x_create_generic` (placeholder art; raw `.dxs` mesh has no Cosmos equivalent) |
| `create` blackHole / Anomaly | **DONE** | `prefab_black_hole` / `a2x_create_anomaly` |
| `create` nebulas/asteroids/mines | **DONE** | `a2x_create_*` (sphere/line, random_range, seed) |
| `destroy` | **DONE** | `a2x_destroy(var)` (when the object was captured) |
| `destroy_near` | **PARTIAL** | center form -> `a2x_destroy_near`; the "near a named object" form is `# TODO` |
| `direct` | **DONE** | `target_pos` / `target` |
| `add_ai` / `clear_ai` | **PARTIAL** | mapped 2.8 brains -> `a2x_add_ai`; unmapped types emit a no-op call + note |
| `set_variable` / `set_timer` / `set_difficulty_level` | **DONE** | direct |
| `log` / `play_sound_now` | **DONE** | `log()` / `sbs.play_audio_file` |
| `big_message` / `incoming_comms_text` / `incoming_message` / `warning_popup_message` | **DONE** | info-panel card (`comms_info_card`) / audio |
| `set_player_grid_damage` | **DONE** | `grid_damage_system(ship, sbs.SHPSYS.*)` |
| `set_object_property` | **PARTIAL** | mapped props -> real `data_set`/`engine`/`pos`/fleet calls; VERIFY/HUMAN props -> `# TODO` (see property_map) |
| `addto_object_property` / `copy_object_property` | **PARTIAL** | same, for mapped props |
| `set_ship_text` | **DONE** | name/race/class/desc -> `name_tag`/`hull_origin`/`hull_name`/`long_description` (scan_desc/hail dropped) |
| `set_relative_position` | **DONE** | `a2x_set_relative_position` (XZ; heading-relative nuance is a refinement) |
| `set_side_value` | **DONE** | `a2x_set_side_value` (swaps the side role) |
| `set_special` (ability) | **DONE** | all 14 abilities -> LM elite system (engine flags + scripted `elite/*` roles via `handle_elite_abilities`); no-name calls target `COMMS_SELECTED_ID` |
| `set_special` (ship/captain) | NO-EQUIV | the 2.8 special ship/captain *types* have no Cosmos equivalent |
| `set_comms_button` (+ `if_comms_button`) | **DONE** | a `//comms` route with `+ "label":` buttons |
| `set_gm_button` (+ `if_gm_button`) | **DONE** | a gamemaster-gated `//comms/gm/...` **tree** (slash = submenu) |
| `set_monster_tag_data` / `set_named_object_tag_state` | **PARTIAL** | stored as inventory values; the tagging *gameplay* needs a tag-torpedo + `//damage` route (note emitted) |
| `end_mission` | **DONE** | `signal_emit("show_game_results")` |
| `set_skybox_index` | TODO | maps to `@media/skybox` (index->name table needed) |
| `get_object_property` | TODO | read a mapped prop into a variable (the `_PROP` map already supports the key) |
| `set_fleet_property` / `set_to_gm_position` | TODO | low frequency |
| `set_player_carried_type` / `set_player_station_carried` / `clear_player_station_carried` | TODO | carried single-seat craft config |
| `start_getting_keypresses_from` / `end_getting_keypresses_from` | TODO | console key capture (GM) |
| `spawn_external_program` | NO-EQUIV | 2.8 launched external programs (e.g. VLC for video); nothing to map to |

## Conditions (event "when")

| 2.8 condition | Status | Cosmos |
|---|---|---|
| `if_distance` | **DONE** | `await distance_less/greater` (object or point) |
| `if_inside_sphere` / `if_outside_sphere` | **DONE** | `await distance_point_less/greater` (centre flipped) |
| `if_inside_box` / `if_outside_box` | **DONE** | `a2x_in_box` guard |
| `if_exists` / `if_not_exists` | **DONE** | live `object_exists` (loops) / `//damage/destroy` route (sole `if_not_exists` -> respawn) |
| `if_fleet_count` (<=0) | **DONE** | `await destroyed_all` (chain) / live `len(role("fleet_N"))` (loops) |
| `if_docked` | **DONE** | `a2x_is_docked` (loops) / `//signal/ship_docked` route (sole `if_docked`) |
| `if_timer_finished` | **DONE** | `is_timer_finished` |
| `if_variable` | **DONE** | live boolean guard (loops) / `//signal/a2x_flag_F` route (sole `==`) |
| `if_difficulty` | **DONE** | live `DIFFICULTY <op> v` boolean (in polling loops) |
| `if_monster_tag_matches` / `if_object_tag_matches` | **PARTIAL** | inventory guard (tagging gameplay TODO) |
| `if_comms_button` / `if_gm_button` | **DONE** | handled structurally (become route buttons) |
| `if_object_property` / `if_scan_level` / `if_in_nebula` / `if_damcon_members` / `if_player_is_targeting` | TODO | emitted as a `# when (verify by hand)` comment |
| `if_gm_key` / `if_client_key` | TODO | key handlers |

---

## Event model

2.8 events all run continuously -- each re-checks its conditions every tick and fires
whenever they are true; it never "ends". The converter reproduces that and, where it can,
turns polling into event-driven routes. Selectable with `--event-model`:

| Mode | Shape |
|---|---|
| `linear` | every event folded into one sequential scene chain (simplest to read) |
| **`hybrid`** (default) | flag-chained scenes stay a linear chain; independent events run concurrently; engine-pushable ones become routes |
| `a28_compatible` | every event becomes its own continuous polling task (no chain, no routes) -- the worst-case faithful fallback |

**hybrid specifics:**
- **Classification** -- an event is *sequential* if it is flag-linked to another (waits on
  a flag an earlier event sets, or feeds a later one); otherwise *independent*.
- **Independent events re-fire** -- emitted as a polling loop over **live boolean**
  conditions (`_cond_bool`) that re-evaluates each tick, so respawn / wave / periodic rules
  work. A loop ends (`->END`) only on a 2.8 fire-once self-guard (`if_variable F != 1` +
  `set F = 1`) or when it has no expressible condition to loop on.
- **Poll -> push routes** (single-trigger independent events, no polling):
  - sole `if_not_exists X` -> spawn once + `//damage/destroy if has_role(DESTROYED_ID, "respawn_X")`.
  - sole `if_docked` -> `//signal/ship_docked` (LM docking emits this on station dock).
  - sole `if_variable F == v` -> `//signal/a2x_flag_F`; the matching `set_variable` also `signal_emit`s it.
  - Multi-condition events stay polling loops **on purpose**: a pure route would miss the
    "gate flag opens after the object died / undocked" case that a per-tick loop catches.
- **Flags** are `shared` + forward-declared (`default shared F = 0`) so concurrent tasks/routes read them.

---

## Needs human feedback

These are the things blocking further automation. Each is a small change once decided.

### 1. `set_object_property` VERIFY/HUMAN rows
See [`property_map.md`](property_map.md). The high-value open ones:
- **`musicObjectMasterVolume`** (34) -- which Cosmos audio/volume call?
- **`systemCurHeat*` / `systemDamage*`** -- the 2.8 8-system -> Cosmos 4-system (`system_cur_heat`/`system_damage`) **index mapping**.
- **`sideValue` as a property** -- should `set_object_property property="sideValue"` reuse `a2x_set_side_value`? (Currently only the `set_side_value` command does.)
- **`eliteAbilityBits`** -- confirm the bit -> `elite_*` flag decomposition.
- **`angle`/`pitch`/`roll`** -- which engine attribute sets heading?
- **`topSpeed`** -- `speed_coeff` (0-1) vs `max_throttle`?
- HUMAN rows with no found key: `pushRadius`, `surrenderChance`, `tauntImmunityIndex`,
  `pirateRepWithStations`, plasma-shock/ECM/tag/probe/beacon stores, `nebulaIsOpaque`,
  `sensorSetting`, monster `age`.

### 2. `set_special` combat abilities -- RESOLVED
All 14 elite abilities now map to the LegendaryMissions elite system (the 9 combat
abilities are scripted in the `fleets` addon, not engine flags). Only the special
**ship/captain** *types* remain NO-EQUIV (decide: drop, or author a stand-in).

### 3. Tagging gameplay
`set_*_tag_data` / tag-match conditions store data as inventory, but 2.8's tagging is a
**tag-torpedo** mechanic. To make it play: register a tag `torpedo_type()` + a `//damage`
route keyed on `EVENT.sub_tag` that records the tag on hit. Want this scaffolded?

### 4. Global difficulty vs future spawns
`nonPlayer*`/`player*` are applied to ships that **exist when the call runs**; 2.8 also
affected *future* spawns. If a mission sets difficulty in `<start>` before spawning
enemies in events, the coeff won't reach them. Acceptable, or should the converter
re-apply after later spawns?

### 5. Object resolution residual (~170)
`destroy` / `add_ai` / `set_ship_text` / `destroy_near` that reference an object via
`use_gm_selection`, a `player_slot`, or a forward reference can't be resolved to a
captured variable, so they stay `# TODO`. These need a per-mission look; is it worth a
heuristic (e.g. `use_gm_selection` -> the GM-selected context var)?

### 6. Backslash in GM button labels
Some GM labels contain a literal backslash (`Delete\Selected ship`). Only `/` is treated
as a submenu separator. If `\` was *also* meant as a separator in 2.8, say so and I'll
split on it too.

---

## "Close enough" behaviours to be aware of

- **Headings** (`angle`) from `create` are not auto-applied (`a2x_angle()` exists).
- **Ship art** uses a fuzzy-matched hull crosswalk; unmatched hulls use a placeholder
  (listed per mission in `MIGRATION_NOTES.md`).
- **Events** default to the `hybrid` model (flag-chained scenes linear, independent events
  concurrent loops/routes -- see the Event model section); verify the order matches the
  original flag logic, or fall back to `--event-model a28_compatible` if it misbehaves.
- **Conditions** that have no live-boolean form (tag-match, scan level, in-nebula, object
  property) become a `# when (verify by hand)` comment, so that event may fire without
  re-checking them.
- **Comms/GM buttons** become routes; the selection/gating may need refining per mission.
- Generated missions depend on the `a2x` layer in `sbs_utils` (v1.4.0+) + the
  feature-detected LegendaryMissions addons.
