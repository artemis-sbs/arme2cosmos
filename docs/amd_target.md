# `--target amd` — converting 2.8 missions to the AMD quest model

**Status:** design + working prototype (`arme2cosmos/amd_emit.py`, `convert --target amd`).

This document describes a new **conversion target** that emits an
[AMD](../../Cosmos-1-3-0/data/missions/LegendaryMissions/documents/amd_doc.md) quest
tree (`story.amd`) plus a thin `story.mast`, instead of hand-wiring 2.8's event
semantics into MAST polling loops and routes. It complements the existing
`--event-model` MAST output; it does not replace it.

The same **one rule** applies: the tool still emits only *text*. `story.amd` is
markdown; the generated MAST calls `quest_grant_amd(...)` / `document_get_amd_file(...)`
(LM `quest_driver`, feature-detected in `story.json`). No `import sbs_utils` at build
time.

---

## Why AMD fits 2.8

A 2.8 mission is a flat list of `when <conditions> do <commands>` events plus
flag-gated win/lose (see [`model.py`](../arme2cosmos/model.py)). The v1.4.0 quest
system ([`amd_quest.py`](../../Cosmos-1-3-0/data/missions/sbs_utils/sbs_utils/procedural/amd_quest.py),
[build/quests.md](../../Cosmos-1-3-0/data/missions/sbs_utils/mkdocs/docs/build/quests.md))
is the same shape expressed declaratively:

| Quest fence field | Role | 2.8 analogue |
|---|---|---|
| `Goal:` / `When:` | completion **trigger** | an event's `if_*` conditions |
| activation | scene entry | the event body running |
| `Then: reveal` | next scene | a `set_variable` a later event waits on |
| `Then: signal` | side effect | `set_variable` that fires other logic |
| `Win:` / `Lose:` | game-over | `end_mission` gated by a success/fail flag |
| `Critical:` / `Required:` / `Parent:` | mission tree | flag topology among end-game events |
| `Fail after:` | timed loss | `set_timer` + `if_timer_finished` gate |
| `Fail on all dead:` | wipe loss | `if_not_exists` of the last of a role |

The payoff: the weakest part of today's output — the hand-rolled end-game and
event machinery — becomes declarative data, and the port gets a **live quest log,
objective text, and engine-driven win/lose** for free.

---

## The three-part split

AMD quest fences carry only *declarative* fields. A 2.8 event body is *imperative*
(spawn, comms, big_message). They meet through the quest **signals**
(`quest_activated`, `quest_completed`, and `Then: signal`):

1. **`story.amd`** — the quest tree: triggers, reveal-chains, win/lose. Data only.
2. **`story.mast` `@map` task** — spawns the `<start>` block (reusing the existing
   `a2x_*` emitters verbatim), tags quest-target **roles**, then one
   `quest_grant_amd(SHARED, document_get_amd_file("story.amd", data_parser=amd_quest_data))`.
3. **`story.mast` routes** — the imperative bodies:
   - `//signal/quest_activated if QUEST_ID == "<key>"` — the event body, run when its
     scene begins (a revealed quest).
   - `=== gate_N` polling watchers — the **escape hatch**: for any trigger AMD's verb
     set can't express, a tiny loop that `signal_emit`s when the condition holds; the
     quest listens `When: signal a2x_gate_N`. The watcher body is exactly today's
     [`_cond_bool`](../arme2cosmos/emit.py) polling loop, stripped to a signal source.

```
scene entry (quest_activated)  ─▶  do spawns / comms         [imperative → MAST route]
scene exit  (Goal / When)      ─▶  kill / dock / collect / signal   [trigger → AMD]
next scene  (Then: reveal)     ─▶  reveal the follow-up quest        [tree → AMD]
```

This reuses the tool's existing `Emitter.emit_command`, `_cond_bool`, and
`_classify_events` wholesale; only the *wiring* changes from MAST labels to AMD
fences + signal routes.

---

## Field-by-field mapping

### Triggers (`Goal:` / `When:`) — [`amd_quest.TRIGGER_VERBS`]

| 2.8 condition | AMD | Notes |
|---|---|---|
| `if_fleet_count fleetN <=0` | `Goal: destroy <count> fleet_N` | count = fleet size at spawn; ship tagged `role("fleet_N")` |
| sole `if_not_exists <enemy>` | `Goal: destroy 1 <role>` | named enemy tagged with a synthesized role |
| generic "kill all hostiles" | `Goal: destroy N enemies` | → `hostile=True` scoring, ceasefire-safe ([amd_quest.py:89]) |
| pickup + collect | `Goal: collect <item>` | pairs with `amd_items` |
| science scan | `Goal: scan <role>` + `Reveals:` | **recovers the dropped `scan_desc`** |
| sole `if_docked` | `Goal: dock <role>` | replaces the `//signal/ship_docked` route |
| sole `if_variable F == v` | `When: signal a2x_flag_F` | `set_variable` already `signal_emit`s (existing trick) |
| anything else (box, distance-to-object, property, multi-cond) | `When: signal a2x_gate_N` | **escape-hatch watcher** |

`reach`/`travel` (`on_reach`) is **sector**-grid based while 2.8 uses absolute
coords; the converter deliberately routes distance/region triggers through the
escape hatch rather than mis-map them to `reach`.

### End-game & tree

| 2.8 | AMD |
|---|---|
| `end_mission` gated by a "success" flag | `Win: <prose reason>` on the deciding quest |
| `end_mission` gated by a "fail" flag | `Lose: <prose reason>` |
| success requires several sub-goals | `Parent:` + `Required:` children |
| a sub-goal whose failure loses the game | `Critical: true` |
| `set_timer` + `if_timer_finished` → lose | `Fail after: N minutes` (lazy-anchored on ACTIVE) |
| `if_not_exists` of the last of a role → lose | `Fail on all dead: <role>` |

**Win/lose detection heuristic.** Trace the flag that gates the `end_mission`
event (`EndMisson == 1`) back to the events that *set* it. Each such event is a
decider; classify by its title/`big_message` keywords
(`success|congrats|victor|win` → `Win:`, `fail|died|doomed|destroyed|lost` →
`Lose:`), and its own trigger becomes the quest's completion condition. Ambiguous
deciders are emitted as quests with a `# TODO: win or lose?` note — consistent with
the scaffold philosophy (never invent game logic).

### Body / effects

| 2.8 | AMD / MAST |
|---|---|
| event commands (spawn, comms, log…) | `//signal/quest_activated if QUEST_ID == "<key>"` body |
| `set_variable F` that a later event waits on | `Then: reveal <next_quest>` (reveal-chain) |
| `Pays`-like reward (rare in 2.8) | `Pays:` |

---

## Worked example — `MISS_Practice`

Source ([a28/…/MISS_Practice.xml](../../a28/dat/Missions/Armada2018/MISS_Practice/MISS_Practice.xml)):
one enemy `Bad Alien` (fleet 1), a station, three timed narrative comms beats
chained on a `Jump` flag, and three end-game events (`Mission End Sucess`,
`Mission End Failure`, `EndGame`) chained on `EndMisson` + `end_mission_timer`.

`story.amd` (the whole win/lose tree, declaratively):

```amd
# [Defeat the Bad Alien](main)
---
Scope: shared
State: active
Goal: destroy 1 bad_alien
Win: Congrats! You Saved Us! You are being awarded a medal.
---
Destroy the Bad Alien attacking the station.
// TODO 2.8 also required Station 1 to survive (if_exists) - model as a Critical child.

# [Keep Your Ship Alive](survive)
---
Scope: shared
State: active
Critical: true
Fail on all dead: player_hero
Lose: You Died. We are doomed!
---
Do not let the Artemis be destroyed.
```

`story.mast` (thin — spawns, roles, one grant, bodies as routes):

```
@map/practice "Practice"
== main ==
    <a2x_create_player ...>            # reused from the existing emitter
    <a2x_create_station ...>
    shared obj_bad_alien = a2x_create_enemy(..., side="enemy, fleet_1")
    add_role(player_ship, "player_hero")   # role the Lose trigger names
    add_role(obj_bad_alien, "bad_alien")   # role the Win goal names
    quest_grant_amd(SHARED, document_get_amd_file(
        get_mission_dir_filename("story.amd"), data_parser=amd_quest_data))
    task_schedule(gate_0)              # narrative beats: escape-hatch watchers
    ->END

//signal/quest_activated if QUEST_ID == "main"
    a2x_big_message("Practice Mission", "by Paul Rockwell", "")
    ->END

=== gate_0    # "Call for Help": timer + Jump==2 (no verb) -> escape hatch
---gate_0_loop
    await delay_sim(0.5)
    jump gate_0_loop if not (is_timer_finished(0, "Jump") and Jump == 2)
    a2x_incoming_comms_text("Help Us! We are under attack!", from_name="Station 1")
    ->END
```

The three end-game events + the `EndGame` timer collapse into **two AMD fences**.
The kill-count, the objectives UI, and the game-over are now the engine's job.

Run it:

```
python -m arme2cosmos convert <MISS_Practice.xml> --target amd --out out_amd
```

---

## Objective quests from the flag graph

2.8 missions are **flag state machines**: most events carry a real trigger (kill /
dock / reach / timer / property) *plus* `if_variable` flag guards, so early versions
of this target only promoted *sole*-trigger events and dumped the rest into polling
loops. The converter now promotes any event that is a **genuine objective** — a
concrete kill/survive goal, or a **narrated** event (carries `big_message` / comms
text) — to a quest:

- Flag guards are split: the end-game terminal flags, the event's own run-once/advance
  flags, and "not-yet" latches (`!= v` / `== 0`) are **dropped**; a surviving phase
  gate (a flag another event sets to a positive value) **folds into the trigger**.
- A clean kill (`if_not_exists NAME` with no surviving gate) → native `Goal: destroy 1
  <role>`; a phase-gated or non-kill trigger → an escape-hatch watcher that ANDs the
  trigger with its phase gate → `When: signal a2x_gate_N`.
- The event's `big_message`/comms becomes the quest's **objective text** (2.8 has none).
- Bare **mechanism** events (a trigger but no player text and no kill goal — beacon
  toggles, score bookkeeping) are **not** objectives and stay background loops.

Corpus effect: quests **150 → 1372**, beats **3324 → 2082**, all 27 still compile.

**Caveats / next refinements (known):**
- **Watcher volume.** Phase-gated objectives each get a polling watcher — ~929 across
  the corpus (Cruiser alone ~230). The fix is a **reveal graph**: make a downstream
  quest `State: secret` and have its phase-setter `Then: reveal` it, so its watcher
  only runs once the phase is reached (most watchers are dormant instead of all polling
  at once). Not yet built.
- **Friendly-target kills.** `if_not_exists <friendly base>` becomes `Goal: destroy 1
  <base>` even when destroying it is a **penalty/loss** (e.g. Cruiser's
  "DS1 Destroyed / Penalty -90 kilotons"). A side-aware pass should route a
  friendly-target `if_not_exists` to a `Lose:`/penalty instead of a goal.
- **Aggregation.** A tournament's N per-pirate kills should roll under a `Parent:`
  "Destroy the pirate fleet" with `Required:` children (or one `Goal: destroy N
  pirates`) rather than N separate log entries.

## What stays MAST (graceful degradation)

- **Compound / non-verb triggers** → escape-hatch watchers (`gate_N`). Nothing is
  lost; the quest tree still owns the objective and its state.
- **Timed narrative beats** (`if_timer_finished` chains) — a clean chain of `>=2`
  pure timed beats (exactly `if_timer_finished T` + `if_variable F == n`, advancing
  `F`) is now emitted as a **reveal chain**: each beat is a `Complete after: N seconds`
  quest that `Then: reveal`s the next, with its payload on
  `//signal/quest_completed if QUEST_ID == "<key>"`. This required a small **library
  addition** — a `Complete after:` vocabulary in `amd_quest.py` and a symmetric
  `quest_tick_complete_after()` watcher in the LM `quest_driver` (mirrors
  `Fail after:` / `quest_tick_fail_after`). A beat carrying an extra guard (e.g. an
  `if_exists`) is not a pure timed beat and stays a background loop.
- **Objective prose** — 2.8 has none; the converter synthesizes it from the trigger
  ("Destroy the Bad Alien") and flags `# TODO: improve objective prose`. This is a
  content *upgrade*, not a loss.
- **Anything already unmapped** in the MAST target (property TODOs, tag gameplay)
  stays exactly as-is inside the route bodies.

---

## Improvements the newer library unlocks for *all* targets

These apply to `hybrid`/`linear`/`a28_compatible` too, not just `amd`:

1. **Close dropped-content gaps.** `scan_desc` / `hailtext` (currently dropped —
   see [coverage.md](coverage.md)) get a home via `amd_science`
   (`science_define_scan_amd`) and `amd_dialogue` / `amd_chatter`.
2. **One consolidated `<mission>.amd`.** `amd_mission_data` parses quests + scans +
   landmarks in one file via `amd_section`.
3. **Landmarks for terrain.** Bulk `create nebulas/asteroids/mines` and fixed
   stations can be authored as `amd_landmarks` (`landmarks_spawn`) instead of
   imperative `a2x_create_*`.
4. **Diplomacy-aware kill scoring.** Generic "destroy enemies" goals use the
   `hostile=True` path (ceasefire-safe) instead of binding to a fixed role.
5. **Console gating.** `QUEST_ACCEPT_CONSOLES` / `Accept On:` gives the comms/GM
   button trees a declarative answer to "which console may act".
6. **Canonical signal hooks.** Prefer `quest_completed` / `quest_activated` over
   ad-hoc `a2x_flag_*` where a quest already exists.
7. **`amd_lint` validation.** Add the AMD linter to the "Validating a conversion"
   workflow (run-time, alongside the headless check — not a build-time dep).

---

## Library changes shipped with this (in `sbs_utils` + LM, v1.4.0 working tree)

To make timed sequences convertible, the AMD quest vocabulary gained a
completion-by-time trigger symmetric to the existing `Fail after:`:

- **`sbs_utils/procedural/amd_quest.py`** — a `Complete after:` / `complete_after`
  label → `data["complete_after"] = {seconds|minutes: N}`.
- **`LegendaryMissions/quests/quest_driver.py`** — `quest_tick_complete_after()`, a
  lazy-anchored watcher that **completes** an active quest when its deadline elapses
  (mirror of `quest_tick_fail_after`), firing its `reveal`. Scheduled next to the
  fail-after tick in `quest_driver.mast`.
- **Tests** — `QuestCompleteAfterTests` in `test_quest_end_game.py` (idle beat never
  anchors; active beat completes after the deadline; a two-step reveal chain advances
  on timed completion). All 16 end-game tests pass.

Also added, from the corpus gap analysis (helps **all** targets, not just `amd`):

- **`sbs_utils/procedural/a2x/props.py`** — `a2x_object_property(obj, prop)`, the read
  counterpart of `a2x_set_object_property` (same mapping table: engine attr,
  coordinate-flipped `pos`, or `data_set` slot; unmapped → `None`). Tests in
  `test_a2x_props.py` (round-trip, pos-flip, unmapped).
- **`emit.py`** — `if_object_property` on a mapped prop now compiles to a live boolean
  `(a2x_object_property(obj, "prop") or 0) <op> val` in both `_cond_bool` (polling
  loops / AMD escape-hatch triggers) and the one-shot `emit_condition` poll. Corpus
  effect: `if_object_property` "verify by hand" conditions **473 → 247** (the rest are
  genuinely-unmapped props like `topSpeed`, tracked in `property_map.md`).

This is the intended shape of the tool↔library relationship: when a conversion needs
new behaviour, add a small declarative primitive to `sbs_utils`/LM and have the tool
emit it, rather than hand-rolling the mechanism in generated MAST.

## Open questions

- **Win/lose keyword heuristic** — good enough on the corpus, but titles are
  free-text. Worth a `--win-flag NAME` / `--lose-flag NAME` override?
- **Station/multi-condition wins** — `Goal:` is a single trigger. A win requiring
  "kill X *and* keep Y alive" needs a `Parent:` + `Required:` child (kill) plus a
  `Critical:` child (`Fail on all dead:` Y). Auto-decompose, or scaffold + TODO?
- **Roles for goal targets** — the converter tags targets with synthesized roles
  (`bad_alien`, `fleet_1`). Confirm naming rules so hand-authored follow-ups agree.
- **`reach` sectors** — is a coord→sector table worth building so region triggers
  can use the native `on_reach` verb instead of the escape hatch?
