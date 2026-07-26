# arme2cosmos coverage & open questions

Status of the 2.8 -> Cosmos MAST conversion: what's finished, what's partial, and what
needs a human decision. Property-level detail for `set_object_property` lives in
[`property_map.md`](property_map.md).

## Pipeline status

- The full a28 corpus (27 convertible missions; 2 more fail to *parse* -- malformed 2.8
  XML, not a tool bug) **compiles** under the real `MastStory` compiler, in both targets.
- **All 27 run headless** in both `mast` and `amd` targets with no runtime errors
  (`mission_runner --test`), verified by the mock-run batch.
- Remaining `# TODO` lines across the corpus: **~2** (down from ~2210), both genuine
  source issues left on purpose -- a 2.8 name that references an object never created
  (`mm8`), and a `Probe` store mapped to a Sensor Beacon. The AMD quest tree (`story.amd`)
  is down to 1 (a GM-sandbox mission with no auto-derivable objective).
- **26/27 are clean converts** (zero `# TODO`).

Every emitted `a2x_*` function is exercised by an [A2xTestRange](#validation) conformance
map; see [Validation](#validation).

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
| `destroy_near` | **DONE** | center form -> `a2x_destroy_near`; the "near a named object" form -> `a2x_destroy_near_object` (uses the object's runtime position) |
| `direct` | **DONE** | `target_pos` / `target` |
| `add_ai` / `clear_ai` | **PARTIAL** | mapped 2.8 brains -> `a2x_add_ai`; unmapped types emit a no-op call + note |
| `set_variable` / `set_timer` / `set_difficulty_level` | **DONE** | direct |
| `log` / `play_sound_now` | **DONE** | `log()` / `sbs.play_audio_file` |
| `big_message` / `incoming_comms_text` / `incoming_message` / `warning_popup_message` | **DONE** | info-panel card (`comms_info_card`) / audio |
| `set_player_grid_damage` | **DONE** | `grid_damage_system(ship, sbs.SHPSYS.*)` |
| `set_object_property` | **PARTIAL** | mapped props -> real `data_set`/`engine`/`pos`/fleet calls; VERIFY/HUMAN props -> `# TODO` (see property_map) |
| `addto_object_property` / `copy_object_property` | **PARTIAL** | same, for mapped props |
| `set_ship_text` | **DONE** | name/race/class/desc -> `name_tag`/`hull_origin`/`hull_name`/`long_description`. **`scan_desc` recovered** (all targets): emitted as a declarative `amd_science` scan in `scans.amd`, the object tagged with a `scan_<name>` role, loaded via `science_define_scan_amd` + the `science_scans` addon. **`hailtext` recovered** (all targets): stored on the ship as an `a2x_hail` inventory value where `set_ship_text` runs, plus one gated `//comms` **Hail** button that shows it (`comms_receive`). Per-ship (not the LM race-taunt pool) |
| `set_relative_position` | **DONE** | `a2x_set_relative_position` (XZ; heading-relative nuance is a refinement) |
| `set_side_value` | **DONE** | `a2x_set_side_value` (moves the ship to another declared side; diplomacy follows the side). The destination sideValue is added to the mission's `a2x_declare_sides` set, so a defection can't land on an undeclared side |
| `sideValue` (on `create`) | **DONE** | one Cosmos side per distinct 2.8 sideValue (`a2x_declare_sides`, emitted into `//shared/signal/create_sides`) -- see *Sides and diplomacy* below |
| `set_special` (ability) | **DONE** | all 14 abilities -> LM elite system (engine flags + scripted `elite/*` roles via `handle_elite_abilities`); no-name calls target `COMMS_SELECTED_ID` |
| `set_special` (ship/captain) | **DONE** | captain personality (cowardly/brave/bombastic/seething/duplicitous/exceptional) -> `a2x_set_captain` (LM surrender/taunt/fleets driver); ship power tier -> `a2x_set_ship_power` (shield/beam/tube coeffs) |
| `set_comms_button` (+ `if_comms_button`) | **DONE** | a `//comms` route with `+ "label":` buttons |
| `set_gm_button` (+ `if_gm_button`) | **DONE** | a gamemaster-gated `//comms/gm/...` **tree** (slash = submenu) |
| `set_monster_tag_data` / `set_named_object_tag_state` | **PARTIAL** | stored as inventory values; the tagging *gameplay* needs a tag-torpedo + `//damage` route (note emitted) |
| `end_mission` | **DONE** | `signal_emit("show_game_results")` |
| `set_skybox_index` | **DONE** | `a2x_set_skybox_index` -> the LM `basic_random_skybox` media labels (2.8 SB00..SB29 index mapped across them) |
| `get_object_property` / `if_object_property` | **DONE** | `a2x_object_property(obj, prop)` reads any mapped prop back |
| `set_fleet_property` | **DONE** | fleetSpacing/fleetMaxRadius -> `a2x_set_fleet_property` -> the general `fleet_spacing`/`fleet_max_radius` formation-ring keys the LM scatter brain reads |
| `set_to_gm_position` | **DONE** | `a2x_set_to_gm_position` -> move the GM-selected object to the gamemaster console ship's position |
| `set_damcon_members` | **DONE** | `a2x_set_damcon_members` -> the HP of the Cosmos damcon teams DC1..DC3 (value = team HP) |
| `set_player_carried_type` | **DONE** | `hangar_random_craft_spawn` into the player hangar; the named craft is CAPTURED so later references resolve. `player_slot` with no create:player -> `a2x_player_ship(slot)` |
| `clear_player_station_carried` | **DONE** | `a2x_clear_station_carried` -> delete a station's standby (in-hangar) craft, leaving launched ones flying |
| `gm_instructions` | **DONE** | `a2x_set_gm_instructions` -> the shared `GAMEMASTER_INSTRUCTIONS` the GM console instruction panel renders |
| `start_getting_keypresses_from` / `end_getting_keypresses_from` | TODO | console key capture (GM); `if_gm_key` events already route to a GM comms "Hotkeys" submenu |
| `spawn_external_program` | NO-EQUIV | 2.8 launched external programs (e.g. VLC for video); emitted as `a2x_spawn_external_program` (a no-op stub) |

## Conditions (event "when")

| 2.8 condition | Status | Cosmos |
|---|---|---|
| `if_distance` | **DONE** | `await distance_less/greater` (chain) / `a2x_distance_less/greater` (loops; object or point) |
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
| `if_object_property` | **PARTIAL** | mapped props (`_AUTO_PROPS`) -> live `a2x_object_property(obj, prop) <op> val` boolean (loops + one-shot poll); unmapped props stay a `# when (verify by hand)` comment. Corpus: ~48% of occurrences now evaluate for real |
| `if_scan_level` / `if_in_nebula` / `if_damcon_members` / `if_player_is_targeting` | TODO | emitted as a `# when (verify by hand)` comment |
| `if_gm_key` / `if_client_key` | TODO | key handlers |

---

## Sides and diplomacy

2.8 has **no diplomacy table**. A ship's `sideValue` *is* its faction, and the engine
applies one implicit rule: different non-zero values are hostile, the same value is
friendly, `0` means "no side". Nothing in a 2.8 mission ever declares it.

Cosmos resolves allegiance the other way round -- through registered **side agents**
linked by `side_ally` / `side_hostile`. A converted mission must therefore declare what
2.8 left implicit, and the failure mode when it doesn't is silent rather than loud: the
LM NPC brains gate the trigger on diplomacy,

```
shoot = side_are_enemies(BRAIN_AGENT_ID, _target) or force_shoot
```

so undeclared sides give you ships that chase and never fire, a Science console with no
allied/hostile split, and grey sensor contacts. (LM declares its own sides in
`maps/sides.amd`; `maps` is mission content, **not** one of the shipped mastlibs, so a
converted mission never inherits it.)

**What the tool emits.** One Cosmos side per *distinct sideValue the mission touches*
(creates plus any runtime `set_side_value` destination), declared in a
`//shared/signal/create_sides` route -- the hook the server console fires during
start_server, before default player ships spawn and before any map runs:

```
//shared/signal/create_sides
    a2x_declare_sides([1, 2])
```

Sides are **not** collapsed onto the three LM keys (`tsn`/`raider`/`civ`). `sideValue` is
a faction index, not a 3-valued enum: MISS_The_Arena puts eight player ships on
sideValues 4..11, each with its own station, and collapsing those would make all eight
teams allies. Keys are `neutral`/`enemy`/`friendly` for 0/1/2 and `side_N` above that
(mirrored between `emit._side_key` and `a2x.sides.side_key` -- keep them in step).

**Side key vs combat role.** These are different jobs and the emitted spawn string
carries both -- `spawn_common` splits on commas, the first token becomes the side key,
every token becomes a role:

```
a2x_create_enemy(..., side="enemy, raider, fleet_1")
                       ^key   ^scope  ^fleet role
```

* the **key** carries identity and diplomacy -- it is what makes a ship an enemy.
* `raider` is only a **combat scope** tag. LM intersects it with diplomacy rather than
  trusting it alone, e.g. the docking addon's enemies-near gate
  `side_hostile_members(DOCKING_PLAYER_ID, "raider")`; without the tag that set is always
  empty and the gate silently never fires. Tagging without declaring sides achieves
  nothing. `tsn`/`civ` are not emitted -- nothing in the baseline mastlibs needs them.

**The player's side comes from its own `sideValue`**, never a2x_create_player's `tsn`
default (and `PLAYER_LIST` is written with the same key when the mission creates no
player). Friendly stations carry that sideValue too; a player on a different side from
its own station reads as hostile once diplomacy is declared.

Runtime behaviour is pinned by `test_convert_sides` in the A2xTestRange suite.

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

## Validation

Two layers verify the port, both run against `sbs_utils` + LegendaryMissions:

- **Conformance suite** -- [`A2xTestRange`](https://github.com/artemis-sbs/A2xTestRange)
  is a standalone sister mission (its own repo) of ~28 `test_convert_*` maps. Each asserts the
  *runtime behavior* of an emitted `a2x_*` call (the recorded decision -- roles, data_set
  values, orientation vectors, coords -- not live physics). **Every emitted `a2x_*`
  function is covered.** Run one: `python -m cosmos_dev.mission_runner A2xTestRange
  --map test_convert_angle --test 20`.
- **Mock/engine run** -- every converted mission is run headless
  (`mission_runner <mission> --test 2 --use-working-tree`) in both targets; the whole
  corpus passes 46/46 (23 unique missions x 2 targets). This is what caught the
  `role(name)`-in-a-condition crash that compile-only checks missed (now `a2x_named`).
- **Unit tests** -- `python -m unittest discover -s tests` (stdlib only): emitter logic +
  the AMD quest-tree classifier.

## Resolved / open decisions

Most of the earlier open questions are now wired (see [`property_map.md`](property_map.md)):
`angle`/`pitch`/`roll` (rot_quat), `sensorSetting`, `nebulaIsOpaque`, `pushRadius`,
`surrenderChance`/`tauntImmunityIndex`, `pirateRepWithStations`, `warpState`, `canBuild`,
`shieldState`, PShock/Tag/EMP/Probe/Beacon stores, `systemCurHeat*`/`Damage*`,
`missileStoresProbe` (-> Sensor Beacon), the elite `eliteAbilityBits`, and the object-ref
residual (`use_gm_selection` -> `COMMS_SELECTED_ID`; `player_slot` -> `a2x_player_ship`;
uncaptured names -> `a2x_named`/`a2x_destroy_named`). Engine-stubs (needs an engine
feature, non-blocking): `musicObjectMasterVolume`, `triggersMines`, `deltaX/Y/Z`.

Remaining decisions:

### Tagging gameplay
`set_*_tag_data` / tag-match conditions store data as inventory, but 2.8's tagging is a
**tag-torpedo** mechanic. To make it play: register a tag `torpedo_type()` + a `//damage`
route keyed on `EVENT.sub_tag` that records the tag on hit.

### Global difficulty vs future spawns
`nonPlayer*`/`player*` (`a2x_set_fleet_coeff`) apply to ships that **exist when the call
runs**; 2.8 also affected *future* spawns. If a mission sets difficulty in `<start>`
before spawning enemies in events, the coeff won't reach them (re-apply after later spawns
if needed).

### Unmapped conditions
`if_scan_level` / `if_in_nebula` / `if_damcon_members` / `if_player_is_targeting` and
`if_gm_key`/`if_client_key` still emit a `# when (verify by hand)` comment.

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
