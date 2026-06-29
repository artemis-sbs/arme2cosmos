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
| `turnRate` (90) | data_set | `turnRate` | **DONE** | |
| `throttle` (9) | data_set | `throttle` | **DONE** | |
| `artScale` (89) | data_set | `local_scale_coeff` | **DONE** | |
| `angle` (137) | engine | heading (radians) -> engine_object orientation | VERIFY | which engine attr sets heading? |
| `pitch` (13) | engine | engine_object orientation | VERIFY | |
| `roll` (24) | engine | engine_object orientation | VERIFY | |
| `topSpeed` (564) | data_set | `speed_coeff` (0-1) or `max_throttle`? | VERIFY | 2.8 was absolute; Cosmos uses a coeff |
| `currentRealSpeed` (26) | — | read-only in 2.8 | HUMAN | likely no setter; drop? |
| `pushRadius` (269) | — | no key found (`exclusion_radius`?) | HUMAN | |
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
| `shieldState` (14) | data_set | `shield_val` [?] | VERIFY | which index / both? |

## Weapon stores & ammo

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
| `missileStoresPShock` (79) | — | no `PShock_NUM` in doc | HUMAN | Cosmos key for plasma shock? |
| `missileStoresECM` (6) | — | no key | HUMAN | |
| `missileStoresTag` (1) | — | no key | HUMAN | |
| `missileStoresProbe` (1) | — | no key | HUMAN | |
| `missileStoresBeacon` (1) | — | no key | HUMAN | |
| `countShk` (4) | — | no key | HUMAN | |

## Ship systems (heat / energy / damage)

2.8 has 8 systems; Cosmos `system_cur_heat` / `system_damage` are arrays indexed by a
smaller set (`eng_control_type_index` is 0-3). The 8->4 index mapping needs you.

| 2.8 property | Target | Cosmos | Status | Notes |
|---|---|---|---|---|
| `energy` (49) | data_set | `energy` | **DONE** | |
| `systemCurHeat*` (~41 ea) | data_set | `system_cur_heat` [idx] | VERIFY | need 2.8 system -> Cosmos index |
| `systemDamageImpulse` (13) | data_set | `system_damage` [idx] | VERIFY | impulse index? |
| `systemDamageTurning` (6) | data_set | `system_damage` [idx] | VERIFY | turning index? |
| `warpState` (58) | data_set | `warp_drive_active` (flag) | VERIFY | 2.8 had a level; Cosmos has 0/1 |
| `systemCurEnergyFrontShield` (32) | — | no per-system energy key | HUMAN | |
| `systemCurEnergyBackShield` (32) | — | no key | HUMAN | |

## Enemy AI / elite

| 2.8 property | Target | Cosmos | Status | Notes |
|---|---|---|---|---|
| `hasSurrendered` (328) | data_set | `surrender_flag` | **DONE** | 0 = not surrendered |
| `eliteAbilityBits` (40) | data_set | decompose -> `elite_*` flags | VERIFY | confirm bit->flag mapping |
| `surrenderChance` (52) | — | no key | HUMAN | |
| `tauntImmunityIndex` (24) | — | no key | HUMAN | |
| `age` (19) | — | monster age; no key | HUMAN | size via `local_scale_coeff`? |

## Side / identity

| 2.8 property | Target | Cosmos | Status | Notes |
|---|---|---|---|---|
| `sideValue` (272) + `SideValue` (12) | role | re-assign Cosmos side/role | VERIFY | map 1=enemy/2=friendly to roles? |
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
| `musicObjectMasterVolume` (299) | setting | Cosmos music-volume API | VERIFY | which call? |
| `nebulaIsOpaque` (30) | setting | global nebula setting | HUMAN | |
| `sensorSetting` (38) | setting | global sensor setting | HUMAN | |

---

## Related commands (status)

Beyond `set_object_property`, these 2.8 commands are also wired:

| 2.8 command | Status | Cosmos |
|---|---|---|
| `addto_object_property` | **DONE** | `a2x_addto_object_property` (read-modify a mapped prop) |
| `copy_object_property` | **DONE** | `a2x_copy_object_property` (copy a mapped prop A->B) |
| `set_ship_text` | **DONE** | `a2x_set_ship_text` (name->`name_tag`, race->`hull_origin`, class->`hull_name`, desc->`long_description`; scan_desc/hail have no key) |
| `set_relative_position` | **DONE** | `a2x_set_relative_position` (place near a reference, XZ; heading-relative nuance is a refinement) |
| `set_special` (ability) | **DONE (partial)** | `a2x_set_special` -> `elite_*` flags for Stealth/LowVis/Drones/AntiMine/AntiTorp; combat abilities (Cloak/HET/Warp/Teleport/Tractor/ShldDrain/ShldVamp) have no key |
| `set_special` (ship/captain) | HUMAN | 2.8 special ship/captain types have no Cosmos equivalent |

---

## Summary

- **DONE (verified, emitting real calls):** `position*` (with flip), `angleDelta`/
  `rollDelta`/`pitchDelta`, `turnRate`, `throttle`, `artScale`, `energy`,
  `hasSurrendered`, `shieldsOn`, `shieldState{Front,Back}`, `shieldMaxState{Front,Back}`,
  `missileStores{Nuke,Homing,Mine,EMP}`, `count{Nuke,Homing,Mine,EMP}` -- plus the
  `addto` / `copy` / `set_ship_text` / `set_relative_position` / `set_special` commands.
- **VERIFY (need your confirm):** `angle`/`pitch`/`roll` heading writes, `topSpeed`,
  `shieldState`, the `systemCurHeat*` / `systemDamage*` 8->4 index mapping, `warpState`,
  `eliteAbilityBits` bit-decomposition, `sideValue`->roles, `musicObjectMasterVolume`.
- **HUMAN (need a Cosmos key, or "drop"):** the rest -- `pushRadius`, `surrenderChance`,
  `tauntImmunityIndex`, `pirateRepWithStations`, the plasma-shock/ECM/tag/probe/beacon
  stores, `systemCurEnergy*`, the global difficulty coeffs, `nebulaIsOpaque`,
  `sensorSetting`, etc.

Confirm a VERIFY row or fill a HUMAN row and it's a one-line addition to the `_PROP` map.
