# `set_object_property` mapping: Artemis 2.8 -> Cosmos

2.8's `set_object_property` / `addto_object_property` / `copy_object_property` /
`get_object_property` / `if_object_property` use property names that differ from Cosmos
`data_set` keys. This table is the cross-reference (built from
`object_data_documentation.txt`) and tracks what the converter emits.

**Status legend**
- **DONE** — implemented and verified; the converter emits a real call (via
  `a2x_set_object_property` / `a2x_addto_object_property` / `a2x_copy_object_property`).
- **VERIFY** — a proposed mapping awaiting confirmation (indices / semantics).
- **HUMAN** — no clean Cosmos equivalent found; please provide the conversion or "drop".

**Targets** (how Cosmos applies it):
- `data_set` -> `data_set.set("<key>", value[, index])`
- `engine` -> `engine_object.<attr> = value`
- `pos` -> `engine_object.pos.<axis>` (with the 2.8->Cosmos X/Z mirror applied)
- `role` -> Cosmos side/role membership
- `setting` -> a global game / difficulty / audio setting (2.8 set these with no object)

Counts in parentheses = occurrences across the a28 corpus.

> The DONE rows are live in `sbs_utils/procedural/a2x/props.py` (`_PROP`). `set_*` /
> `addto_*` / `copy_object_property` all use the same map; `position*` applies the
> coordinate flip (set mirrors X/Z, addto negates the delta on mirrored axes, copy is
> direct).

---

## Position / motion

| 2.8 property | Target | Cosmos | Status | Notes |
|---|---|---|---|---|
| `positionX` (269) | pos | `engine_object.pos.x` (mirrored) | **DONE** | flip applied |
| `positionY` (219) | pos | `engine_object.pos.y` | **DONE** | |
| `positionZ` (279) | pos | `engine_object.pos.z` (mirrored) | **DONE** | flip applied |
| `angleDelta` (72) | engine | `engine_object.steer_yaw` | **DONE** | |
| `rollDelta` (107) | engine | `engine_object.steer_roll` | **DONE** | |
| `pitchDelta` (5) | engine | `engine_object.steer_pitch` | **DONE** | |
| `turnRate` (90) | data_set | `turn_rate` | **DONE** | FIXED: was `turnRate` (dead key the engine never reads); the steering physics (NPC + player) reads `turn_rate` |
| `throttle` (9) | data_set | `throttle` | **DONE** | |
| `artScale` (89) | data_set | `local_scale_coeff` | **DONE** | |
| `angle`/`pitch`/`roll` (137/13/24) | quat | orientation quaternion | VERIFY | WIKI: these are **radians** (not degrees), **clockwise from south** (0=south, +pi/2=west, pi/-pi=north, -pi/2=east). Yaw mechanics PROVEN (yaw t -> forward `(sin t, cos t)`). Still needs the Cosmos-side CW/CCW + east/west + the a2x_pos X/Z mirror reconciled by a facing spot-check; the mock's a2x objects have no `rot_quat` so not mock-testable |
| `topSpeed` (564) | data_set | `speed_coeff` (0-1) | **DONE** | PROVEN behaviorally vs the mock engine physics: NPC cruise = throttle x 36 u/s x speed_coeff (1.0/0.5/0.25 -> 36/18/9). NPC-only (Cosmos player top speed is fixed). WIKI: 2.8 topSpeed 1.0 = 100 u/s, so the 1:1 map preserves RELATIVE NPC speeds but not the absolute (Cosmos NPC baseline is 36 u/s, its own scale) |
| `currentRealSpeed` (26) | obj | `cur_speed` (space_object attr) | **DONE** | read side: physics-driven current speed; setting is overwritten each tick (effectively read-only) |
| `pushRadius` (269) | obj | `exclusion_radius` (space_object property) | **DONE** | 2.8 push radius = the object's exclusion / collision radius |
| `deltaX` (2) | — | velocity; no data_set key | HUMAN | drop? |
| `blocksShotFlag` (67) | — | no equivalent | HUMAN | |
| `triggersMines` (22) | — | no equivalent | HUMAN | |

## Shields

| 2.8 property | Target | Cosmos | Status | Notes |
|---|---|---|---|---|
| `shieldStateFront` (31) | data_set | `shield_val` [0] | **DONE** | front=0 |
| `shieldStateBack` (41) | data_set | `shield_val` [1] | **DONE** | back=1 |
| `shieldMaxStateFront` (77) | data_set | `shield_max_val` [0] | **DONE** | |
| `shieldMaxStateBack` (85) | data_set | `shield_max_val` [1] | **DONE** | |
| `shieldsOn` (2) | data_set | `shields_raised_flag` | **DONE** | |
| `shieldState` (14) | data_set | `shield_val` | VERIFY | WIKI (station): current shield strength (e.g. 400); can't exceed the inherent max |

## Weapon stores & ammo

`missileStores*` on a **station** = how many of each torpedo type the station has to
**build/hand out** (the per-type `<Type>_NUM` build counts); on a ship it's the ship's
ammo of that type. Same `<Type>_NUM` keys either way. PShock and Tag are now first-class
LM torpedo types (`PShock_NUM`, `Tag_NUM`), and ECM ~ EMP.

| 2.8 property | Target | Cosmos | Status | Notes |
|---|---|---|---|---|
| `missileStoresNuke` | data_set | `Nuke_NUM` | **DONE** | |
| `missileStoresHoming` (79) | data_set | `Homing_NUM` | **DONE** | |
| `missileStoresMine` (96) | data_set | `Mine_NUM` | **DONE** | |
| `missileStoresEMP` (98) | data_set | `EMP_NUM` | **DONE** | |
| `countNuke` (10) | data_set | `Nuke_NUM` | **DONE** | |
| `countHoming` (37) | data_set | `Homing_NUM` | **DONE** | |
| `countMine` (9) | data_set | `Mine_NUM` | **DONE** | |
| `countEMP` (17) | data_set | `EMP_NUM` | **DONE** | |
| `missileStoresPShock` (79) | data_set | `PShock_NUM` | **DONE** | LM plasma-shock torpedo type |
| `missileStoresECM` (6) | data_set | `EMP_NUM` | **DONE** | ECM ~ EMP |
| `missileStoresTag` (1) | data_set | `Tag_NUM` | **DONE** | LM tag torpedo type |
| `missileStoresProbe` (1) | — | no key | HUMAN | |
| `missileStoresBeacon` (1) | — | no key | HUMAN | |
| `countShk` (4) | data_set | `PShock_NUM` | **DONE** | Shk = plasma shock |

## Ship systems (heat / energy / damage)

2.8 has 8 systems; Cosmos tracks **4** (`sbs.SHPSYS`: `WEAPONS`=0, `ENGINES`=1,
`SENSORS`=2, `SHIELDS`=3), each with a heat and a coolant slot -- so the 2.8 8-system
heat/coolant becomes **4 heats + 4 coolant**, all `data_set` arrays indexed 0..3:

- **heat** -> `system_cur_heat` [0..3] (0.0-1.0)
- **coolant** -> `system_coolant_used` [0..3] (with `system_coolant_available` /
  `system_coolant_setting` alongside)
- **damage** -> `system_damage` [0..3]

The 8->4 collapse (same shape as the grid-damage `_GRID_SYS` map): Beam/Torpedo ->
`WEAPONS`; Impulse/Turning/Warp -> `ENGINES`; Tactical/Sensors -> `SENSORS`;
Front/Back Shield -> `SHIELDS`. NOTE: heat is Cosmos's engineering **over-power** model
(driven by `eng_control_value` + `system_coolant_used`), so a 2.8 heat value must be
normalized to 0..1 and a written value is transient (the engine recomputes it from
overpower/coolant).

| 2.8 property | Target | Cosmos | Status | Notes |
|---|---|---|---|---|
| `energy` (49) | data_set | `energy` | **DONE** | |
| `systemCurHeat*` (8 systems, ~41 ea) | data_set | `system_cur_heat` [SHPSYS 0..3] | VERIFY | index per the 8->4 collapse above (Beam/Torpedo->0, Impulse/Turning/Warp->1, Tactical->2, Front/BackShield->3); normalize the 2.8 value to 0..1. No `systemCurCoolant*` in the a28 corpus |
| `systemDamageImpulse` (13) | data_set | `system_damage` [idx] | VERIFY | impulse system |
| `systemDamageTurning` (6) | data_set | `system_damage` [idx] | VERIFY | turning / maneuver system |
| `warpState` (58) | data_set | player warp level | VERIFY | WIKI: 0-4 current warp speed (jump ships always 0). Cosmos: playerThrottle>1 = warp (1..5) -- map 0-4 onto that |
| `systemCurEnergy*` (8 systems, ~32 ea) | data_set | `eng_control_value` [per control] | VERIFY | WIKI: **0.0-1.0** = the Engineering console power slider per system (Beam/Torpedo/Sensors/Maneuver/Impulse/Warp/FrontShld/RearShld). Cosmos over-power goes 0..3 (300%), so 2.8 0-1 maps to the 0-100% part; index via the 8->4 SHPSYS collapse |

## Enemy AI / elite

| 2.8 property | Target | Cosmos | Status | Notes |
|---|---|---|---|---|
| `hasSurrendered` (328) | data_set | `surrender_flag` | **DONE** | 0 = not surrendered |
| `eliteAbilityBits` / `specialAbilityBits` (40) | data_set | `a2x_set_special_bits` | **DONE** | WIKI bit-sum (1=Stealth,2=LowVis,4=Cloak,8=HET,16=Warp,32=Teleport,64=Tractor,128=Drones,256=AntiMine,512=AntiTorp,1024=ShldDrain,2048=ShldVamp,4096=TeleBack,8192=ShldReset) -> each `set_special` |
| `surrenderChance` (52) | — | script-side calc | HUMAN | WIKI: 0-100 (a %); in Cosmos it's a script calculation, not a data key |
| `tauntImmunityIndex` (24) | — | no key | HUMAN | WIKI: 0, 1, or 2 |
| `age` (19) | — | LM monster age system | VERIFY | monsters have an age system now (LM prefabs: `monster_roll_age` / `monster_bake_age` + stage roles) -- map to that, not a raw key |

## Side / identity

| 2.8 property | Target | Cosmos | Status | Notes |
|---|---|---|---|---|
| `sideValue` (272) + `SideValue` (12) | role | `a2x_set_side_value` (1=enemy / 2=friendly) | **DONE** | property reuses the `set_side_value` side-role reassignment |
| `pirateRepWithStations` (72) | — | no key | HUMAN | |
| `canBuild` (4) | — | no key | HUMAN | |

## Global settings (2.8 set these with no object -- game-wide)

"nonPlayer" = all NPC ships, so the difficulty knobs map to per-ship coefficients
applied across the fleet (`coeff = value/100`) via `a2x_set_fleet_coeff`. Applied to
ships that exist at the call; 2.8 also affected future spawns -- re-apply after later
spawns if needed.

| 2.8 property | Target | Cosmos | Status | Notes |
|---|---|---|---|---|
| `nonPlayerSpeed` (25) | data_set | `speed_coeff` on all NPCs | **DONE** | value/100 |
| `nonPlayerShield` (25) | data_set | `all_shield_upgrade_coeff` on all NPCs | **DONE** | |
| `nonPlayerWeapon` (25) | data_set | `all_beam_upgrade_coeff` + `all_tube_upgrade_coeff` on all NPCs | **DONE** | |
| `playerShields` (25) | data_set | `all_shield_upgrade_coeff` on all players | **DONE** | |
| `playerWeapon` (25) | data_set | `all_beam_upgrade_coeff` on all players | **DONE** | |
| `musicObjectMasterVolume` (299) | setting | Cosmos music-volume API | VERIFY | no equiv add a stub |
| `nebulaIsOpaque` (30) | setting | global nebula setting | HUMAN | WIKI: 0/1, ~ the "Nebula Hides All" PVP server setting |
| `sensorSetting` (38) | setting | sensor range setting | HUMAN | WIKI: 0 = unlimited (100km), N = 100/(3N) km (1=33, 2=16, 3=11, 4=8km ...) |

---

## Related commands (status)

Beyond `set_object_property`, these 2.8 commands are also wired:

| 2.8 command | Status | Cosmos |
|---|---|---|
| `addto_object_property` | **DONE** | `a2x_addto_object_property` (read-modify a mapped prop) |
| `copy_object_property` | **DONE** | `a2x_copy_object_property` (copy a mapped prop A->B) |
| `set_ship_text` | **DONE** | `a2x_set_ship_text` (name->`name_tag`, race->`hull_origin`, class->`hull_name`, desc->`long_description`). `scan_desc` -> a declarative `amd_science` scan (`scans.amd`); `hailtext` -> a stored `a2x_hail` + a `//comms` Hail button. Both recovered on all targets |
| `set_relative_position` | **DONE** | `a2x_set_relative_position` (place near a reference, XZ; heading-relative nuance is a refinement) |
| `set_special` (ability) | **DONE (partial)** | `a2x_set_special` -> `elite_*` flags for Stealth/LowVis/Drones/AntiMine/AntiTorp; combat abilities (Cloak/HET/Warp/Teleport/Tractor/ShldDrain/ShldVamp) have no key |
| `set_special` (ship/captain) | HUMAN | 2.8 special ship/captain types have no Cosmos equivalent |

---

## Summary

- **DONE (verified, emitting real calls):** `position*` (with flip), `angleDelta`/
  `rollDelta`/`pitchDelta`, `turnRate` (-> `turn_rate`), `topSpeed` (-> `speed_coeff`,
  behaviorally proven, NPC-only), `currentRealSpeed` (-> `cur_speed`, read), `pushRadius`
  (-> `exclusion_radius`), `throttle`, `artScale`, `energy`, `hasSurrendered`, `shieldsOn`,
  `shieldState{Front,Back}`, `shieldMaxState{Front,Back}`,
  `missileStores{Nuke,Homing,Mine,EMP,PShock,Tag,ECM}`, `count{Nuke,Homing,Mine,EMP,Shk}`,
  `sideValue` (-> `a2x_set_side_value`), `eliteAbilityBits`/`specialAbilityBits`
  (-> `a2x_set_special_bits`) -- plus the `addto` / `copy` / `set_ship_text` /
  `set_relative_position` / `set_special` commands.
- **VERIFY (key known / ready to wire):** monster `age` (-> LM age system), `angle`/`pitch`/
  `roll` (radians CW-from-south, needs facing spot-check), `shieldState`, the
  `systemCurHeat*`/`systemCurEnergy*`/`systemDamage*` indexed writes (8->4 SHPSYS collapse),
  `warpState`, `musicObjectMasterVolume`.
- **HUMAN (no Cosmos key, or "drop"):** `surrenderChance` (script-side calc),
  `tauntImmunityIndex`, `pirateRepWithStations`, `missileStoresProbe`/`Beacon`,
  `nebulaIsOpaque`, `sensorSetting`, `blocksShotFlag`, `triggersMines`, `deltaX`.

Confirm a VERIFY row or fill a HUMAN row and it's a one-line addition to the `_PROP` map.

## Related follow-ups (from the Artemis wiki, not `set_object_property`)

- **`add_ai` brain stack** — the 2.8 AI blocks (CHASE_PLAYER/STATION/AI_SHIP, ATTACK,
  DIR_THROTTLE, GUARD_STATION, monster CHASE_MONSTER/RANDOM_PATROL, ...) map to Cosmos
  brains. Note: **Cosmos fleets need no leader**, so drop `TRY_TO_BECOME_LEADER` /
  `LEADER_LEADS` / `FOLLOW_LEADER`. See the wiki Default Brain Stack.
- **`set_player_carried_type`** (26) — HANGAR: a single-seat craft (shuttle/fighter/bomber)
  carried in a player ship (`player_slot` + `bay_slot`); must run before the player is
  created. Wire via the LM `hangar` addon.
- **Monster properties** (2.7.2+) — `speed`/`health`/`maxHealth`/`turnRate`/`age`/`size`;
  `age` is 1/2/3 = Young/Mature/Ancient (= the LM prefab age stages).
