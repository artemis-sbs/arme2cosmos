# `set_object_property` mapping: Artemis 2.8 -> Cosmos

2.8's `set_object_property` / `get_object_property` / `addto_object_property` /
`if_object_property` use property names that differ from Cosmos `data_set` keys. This
table is the cross-reference (built from `object_data_documentation.txt`). It drives what
the converter can emit automatically.

**Confidence legend**
- **AUTO** — high confidence; the converter can emit this directly.
- **VERIFY** — a proposed mapping that needs a human to confirm (indices, semantics).
- **HUMAN** — no clean Cosmos equivalent found; please provide the conversion or "drop".

**How Cosmos sets these** (target column):
- `data_set` -> `to_object(obj).data_set.set("<key>", value[, index])`
- `engine` -> `to_object(obj).engine_object.<attr> = value`
- `role` -> Cosmos side/role membership (not a data value)
- `setting` -> a game/difficulty/audio setting (2.8 set these with **no object** — global)

Counts in parentheses = how often the property appears across the a28 corpus.

---

## Position / motion

| 2.8 property | Target | Proposed Cosmos | Conf. | Your value / notes |
|---|---|---|---|---|
| `angleDelta` (72) | engine | `engine_object.steer_yaw = v` | AUTO | (a2x_create_monster already uses this) |
| `rollDelta` (107) | engine | `engine_object.steer_roll = v` | AUTO | |
| `pitchDelta` (5) | engine | `engine_object.steer_pitch = v` | AUTO | |
| `turnRate` (90) | data_set | `data_set.set("turnRate", v)` (or `turn_rate`) | AUTO | confirm `turnRate` vs `turn_rate` |
| `throttle` (9) | data_set | `data_set.set("throttle", v)` (npc); `playerThrottle` for players | AUTO | |
| `artScale` (89) | data_set | `data_set.set("local_scale_coeff", v)` | AUTO | |
| `positionX` (269) | engine | `engine_object.pos.x = v` | VERIFY | no `position*` data_set key; confirm engine pos write |
| `positionY` (219) | engine | `engine_object.pos.y = v` | VERIFY | |
| `positionZ` (279) | engine | `engine_object.pos.z = v` | VERIFY | |
| `angle` (137) | engine | heading (radians) -> engine_object orientation | VERIFY | which engine attr sets heading? |
| `pitch` (13) | engine | engine_object orientation | VERIFY | |
| `roll` (24) | engine | engine_object orientation | VERIFY | |
| `topSpeed` (564) | data_set | `speed_coeff` (0-1 coeff) or `max_throttle`? | VERIFY | 2.8 was absolute; Cosmos uses a coeff |
| `currentRealSpeed` (26) | — | read-only in 2.8 | HUMAN | likely no setter; drop? |
| `pushRadius` (269) | — | no key found (`exclusion_radius`?) | HUMAN | |
| `deltaX` (2) | — | velocity; no data_set key | HUMAN | drop? |
| `blocksShotFlag` (67) | — | no equivalent found | HUMAN | |
| `triggersMines` (22) | — | no equivalent found | HUMAN | |

## Shields

| 2.8 property | Target | Proposed Cosmos | Conf. | Your value / notes |
|---|---|---|---|---|
| `shieldStateFront` (31) | data_set | `data_set.set("shield_val", v, 0)` | AUTO | confirm index 0 = front |
| `shieldStateBack` (41) | data_set | `data_set.set("shield_val", v, 1)` | AUTO | confirm index 1 = back |
| `shieldMaxStateFront` (77) | data_set | `data_set.set("shield_max_val", v, 0)` | AUTO | |
| `shieldMaxStateBack` (85) | data_set | `data_set.set("shield_max_val", v, 1)` | AUTO | |
| `shieldsOn` (2) | data_set | `data_set.set("shields_raised_flag", v)` | AUTO | |
| `shieldState` (14) | data_set | `data_set.set("shield_val", v, ?)` | VERIFY | which index / both? |

## Weapon stores & ammo

(Cosmos uses `<Type>_NUM` for current count, `<Type>_MAX` for capacity. Doc only defines
`Nuke`, `Homing`, `Mine`, `EMP`.)

| 2.8 property | Target | Proposed Cosmos | Conf. | Your value / notes |
|---|---|---|---|---|
| `missileStoresNuke` (—) | data_set | `data_set.set("Nuke_NUM", v)` | AUTO | |
| `missileStoresHoming` (79) | data_set | `data_set.set("Homing_NUM", v)` | AUTO | |
| `missileStoresMine` (96) | data_set | `data_set.set("Mine_NUM", v)` | AUTO | |
| `missileStoresEMP` (98) | data_set | `data_set.set("EMP_NUM", v)` | AUTO | |
| `countNuke` (10) | data_set | `data_set.set("Nuke_NUM", v)` | AUTO | |
| `countHoming` (37) | data_set | `data_set.set("Homing_NUM", v)` | AUTO | |
| `countMine` (9) | data_set | `data_set.set("Mine_NUM", v)` | AUTO | |
| `countEMP` (17) | data_set | `data_set.set("EMP_NUM", v)` | AUTO | |
| `missileStoresPShock` (79) | — | no `PShock_NUM` in doc | HUMAN | Cosmos key for plasma shock? |
| `missileStoresECM` (6) | — | no key | HUMAN | |
| `missileStoresTag` (1) | — | no key | HUMAN | |
| `missileStoresProbe` (1) | — | no key | HUMAN | |
| `missileStoresBeacon` (1) | — | no key | HUMAN | |
| `countShk` (4) | — | no key | HUMAN | |

## Ship systems (heat / energy / damage)

2.8 has 8 systems (Beam, Torpedo, Tactical, Turning, Impulse, Warp, FrontShield,
BackShield). Cosmos `system_cur_heat` / `system_damage` are **arrays indexed by a smaller
set of systems** (`eng_control_type_index` is 0-3). The 8->4 index mapping needs you.

| 2.8 property | Target | Proposed Cosmos | Conf. | Your value / notes |
|---|---|---|---|---|
| `energy` (49) | data_set | `data_set.set("energy", v)` | AUTO | |
| `systemCurHeat*` (~41 ea) | data_set | `data_set.set("system_cur_heat", v, <idx>)` | VERIFY | need 2.8 system -> Cosmos index |
| `systemDamageImpulse` (13) | data_set | `data_set.set("system_damage", v, <idx>)` | VERIFY | impulse index? |
| `systemDamageTurning` (6) | data_set | `data_set.set("system_damage", v, <idx>)` | VERIFY | turning index? |
| `warpState` (58) | data_set | `data_set.set("warp_drive_active", v)` (flag) | VERIFY | 2.8 had a level; Cosmos has 0/1 flag |
| `systemCurEnergyFrontShield` (32) | — | no per-system energy key (`eng_control_value`?) | HUMAN | |
| `systemCurEnergyBackShield` (32) | — | no key | HUMAN | |

## Enemy AI / elite

| 2.8 property | Target | Proposed Cosmos | Conf. | Your value / notes |
|---|---|---|---|---|
| `hasSurrendered` (328) | data_set | `data_set.set("surrender_flag", v)` (0 = not) | AUTO | |
| `eliteAbilityBits` (40) | data_set | decompose bits -> `elite_anti_mine` / `elite_anti_torpedo` / `elite_drone_launcher` / `elite_low_vis` / `elite_main_scn_invis` | VERIFY | confirm bit->flag mapping |
| `surrenderChance` (52) | — | no key | HUMAN | |
| `tauntImmunityIndex` (24) | — | no key | HUMAN | |
| `age` (19) | — | monster age (young/mature/ancient); no key | HUMAN | size via `local_scale_coeff`? |

## Side / identity

| 2.8 property | Target | Proposed Cosmos | Conf. | Your value / notes |
|---|---|---|---|---|
| `sideValue` (272) + `SideValue` (12) | role | re-assign Cosmos side/role (not a data value) | VERIFY | a2x could map 1=enemy/2=friendly to roles |
| `pirateRepWithStations` (72) | — | no key | HUMAN | |
| `canBuild` (4) | — | station build flag; no key | HUMAN | |

## Global settings (2.8 set these with **no object** — game-wide)

These are not object properties; 2.8 used them as global difficulty / audio knobs.

| 2.8 property | Target | Proposed Cosmos | Conf. | Your value / notes |
|---|---|---|---|---|
| `musicObjectMasterVolume` (299) | setting | Cosmos music-volume API | VERIFY | which call? |
| `nonPlayerSpeed` (25) | setting | 2.8 difficulty coeff -> Cosmos difficulty | HUMAN | |
| `nonPlayerShield` (25) | setting | difficulty coeff | HUMAN | |
| `nonPlayerWeapon` (25) | setting | difficulty coeff | HUMAN | |
| `playerWeapon` (25) | setting | difficulty coeff | HUMAN | |
| `playerShields` (25) | setting | difficulty coeff | HUMAN | |
| `nebulaIsOpaque` (30) | setting | global nebula setting | HUMAN | |
| `sensorSetting` (38) | setting | global sensor setting | HUMAN | |

---

## Summary

- **AUTO (can wire now):** `angleDelta`, `rollDelta`, `pitchDelta`, `turnRate`, `throttle`,
  `artScale`, `shieldStateFront/Back`, `shieldMaxStateFront/Back`, `shieldsOn`,
  `missileStores{Nuke,Homing,Mine,EMP}`, `count{Nuke,Homing,Mine,EMP}`, `energy`,
  `hasSurrendered` — ~20 names, and these cover a large share of the corpus volume.
- **VERIFY:** position/heading writes, `topSpeed`, `shieldState`, the `systemCurHeat*` /
  `systemDamage*` index mapping, `warpState`, `eliteAbilityBits` bit decomposition,
  `sideValue`, `musicObjectMasterVolume`.
- **HUMAN:** the rest (no clean equivalent) — tell me the Cosmos key, or "drop".

Once you confirm the VERIFY rows and fill the HUMAN rows, the converter can emit real
`data_set` / `engine_object` / setting calls for them instead of `# TODO`.
