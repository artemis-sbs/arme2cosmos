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
| `Done when:` | completion **trigger** | an event's `if_*` conditions |
| `Starts when:` | when it ARMS (a real gate since 2026-07-28) | the flag that reveals the event |
| activation | scene entry | the event body running |
| `Then: reveal` | next scene | a `set_variable` a later event waits on |
| `Then: signal` | side effect | `set_variable` that fires other logic |
| `Win:` / `Lose:` | game-over | `end_mission` gated by a success/fail flag |
| `Fatal:` / `Required:` / `Part of:` | mission tree | flag topology among end-game events |
| `Fails when: <N> seconds` | timed loss | `set_timer` + `if_timer_finished` gate |
| `Fails when: all dead <role>` | wipe loss | `if_not_exists` of the last of a role |

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
     quest listens `Starts when: signal a2x_gate_N`. The watcher body is exactly today's
     [`_cond_bool`](../arme2cosmos/emit.py) polling loop, stripped to a signal source.

```
scene entry (quest_activated)  ─▶  do spawns / comms         [imperative → MAST route]
scene exit  (Done when)        ─▶  kill / dock / collect / signal   [trigger → AMD]
next scene  (Then: reveal)     ─▶  reveal the follow-up quest        [tree → AMD]
```

This reuses the tool's existing `Emitter.emit_command`, `_cond_bool`, and
`_classify_events` wholesale; only the *wiring* changes from MAST labels to AMD
fences + signal routes.

---

## Field-by-field mapping

### Triggers (`Done when:` / `Starts when:`) — [`amd_quest.TRIGGER_VERBS`]

One grammar answers all three life-cycle questions (`Starts when:` / `Done when:` /
`Fails when:`); `Goal:` / `When:` / `Fail after:` / `Complete after:` are the retired
spellings and still parse, but the emitter writes the current ones.

| 2.8 condition | AMD | Notes |
|---|---|---|
| `if_fleet_count fleetN <=0` | `Done when: destroy <count> fleet_N` | count = fleet size at spawn; ship tagged `role("fleet_N")` |
| sole `if_not_exists <enemy>` | `Done when: destroy 1 <role>` | named enemy tagged with a synthesized role |
| generic "kill all hostiles" | `Done when: destroy N enemies` | → `hostile=True` scoring, ceasefire-safe ([amd_quest.py:89]) |
| pickup + collect | `Done when: collect <item>` | pairs with `amd_items` |
| science scan | `Done when: scan <role>` + `Reveals:` | **recovers the dropped `scan_desc`** |
| sole `if_docked` | `Done when: dock <role>` | replaces the `//signal/ship_docked` route |
| sole `if_variable F == v` | `Starts when: signal a2x_flag_F` | `set_variable` already `signal_emit`s (existing trick) |
| anything else (box, distance-to-object, property, multi-cond) | `Starts when: signal a2x_gate_N` | **escape-hatch watcher** |

`reach`/`travel` (`on_reach`) is **sector**-grid based while 2.8 uses absolute
coords; the converter deliberately routes distance/region triggers through the
escape hatch rather than mis-map them to `reach`.

### End-game & tree

| 2.8 | AMD |
|---|---|
| `end_mission` gated by a "success" flag | `Win: <prose reason>` on the deciding quest |
| `end_mission` gated by a "fail" flag | `Lose: <prose reason>` |
| success requires several sub-goals | `Part of:` + `Required:` children |
| a sub-goal whose failure loses the game | `Fatal: true` |
| `set_timer` + `if_timer_finished` → lose | **not emitted** -- see Measured findings |
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
| a reward (rare in 2.8) | `Reward:` |

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
Done when: destroy 1 bad_alien
Win: Congrats! You Saved Us! You are being awarded a medal.
---
Destroy the Bad Alien attacking the station.
// TODO 2.8 also required Station 1 to survive (if_exists) - model as a Fatal child.

# [Keep Your Ship Alive](survive)
---
Scope: shared
Fatal: true
Fails when: all dead player_hero
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
- A clean kill (`if_not_exists NAME` with no surviving gate) → native `Done when: destroy 1
  <role>`; a phase-gated or non-kill trigger → an escape-hatch watcher that ANDs the
  trigger with its phase gate → `Starts when: signal a2x_gate_N`.
- The event's `big_message`/comms becomes the quest's **objective text** (2.8 has none).
- Bare **mechanism** events (a trigger but no player text and no kill goal — beacon
  toggles, score bookkeeping) are **not** objectives and stay background loops.

**What counts as an objective** (`_objective_kind`) is broader than a narrated event: a
**kill** (any `if_not_exists` on a captured enemy — multi-condition and phase-gated
included, e.g. "destroy A *and* B"), a **protect** (friendly `if_not_exists`), a
**reach** (player approaches an object), or a **dock**. These promote even without comms
text, and an un-narrated multi-kill gets a synthesized `Destroy A and B` title from its
targets. 2.8's always-true `if_not_exists name="."` / `".."` sentinels are filtered out
(they name no real object), so they never become a spurious `Destroy .` goal.

**Story beats.** A pure-flag event with **no** objective trigger but narrative text
(`big_message` / comms) becomes a **story-beat quest** — a story moment in the log.
It is revealed when its gating flag is reached (the same reveal graph), then after a
few seconds fires its narrative and its own `set_variable` (which reveals the next
beat), so a 2.8 flag-chained narrative sequence reads as a chain of story beats. The
body runs on `quest_succeeded` (via a `Done when: <N> seconds`) because `quest_reveal` does not
emit `quest_activated`. Multi-gated narrated events stay loops (the reveal graph can't
defer them without firing prematurely).

Corpus effect: quests **150 → 1816**, beats **3324 → 1628**, all 27 still compile.

**Reveal graph (implemented).** A watcher-backed objective gated on exactly one
`F == v` becomes `State: secret` when a *later* event (not `<start>`) sets `F = v`: its
watcher is left out of the up-front schedule, and a `//signal/a2x_phase_F_v` route
`quest_reveal`s the quest + `task_schedule`s its watcher when the phase is reached. The
phase signal is emitted from `c_set_variable` wherever that flag is set (a body / beat /
another quest). So a wave-2 pirate's kill-quest stays hidden and dormant until wave 2
spawns, then appears in the log with its watcher live. Corpus: **241 quests reveal at
their phase; 203/929 watchers no longer poll from t=0** (Cruiser 148/230 = 64%).
Multi-gate / start-produced / unproduced gates stay active from the start (correctness
over cleverness).

**Side-aware kills (implemented).** `if_not_exists <target>` is read against the
target's 2.8 `sideValue`: an **enemy** target → `Done when: destroy 1 <role>`; a
**friendly/neutral** target → a **protect** objective `Fails when: all dead <role>`
(destroying it is a penalty/loss, not a goal), titled `Protect <name>`, with its 2.8
body routed on `//signal/quest_failed` (the penalty payload). Corpus: 13 protect
quests in Cruiser alone (e.g. `Protect DS1`, was a backwards `destroy` goal).

**Kill aggregation (implemented).** When a mission has >=3 per-ship
`Done when: destroy 1 <role>` objectives, they roll under one synthetic `Part of: hostile_fleet`
("Destroy the hostile fleet") as `Required:` children — the parent completes when every
child does, so a fleet of individual kills reads as one mission objective. Left flat
(all children required, no auto-`Win:`); which kills are optional and whether clearing
the fleet wins are per-mission decisions (flagged as a TODO on the parent).

Side-awareness covers **both** branches: a sole friendly death → `Fails when: all dead <role>`
(event-driven, native branch); a **phase-gated** friendly death → `Fails when: signal
<gate>` (the watcher fires the same `quest_signal` that `quest_on_signal` also uses to
**fail** a quest), still deferred/secret via the reveal graph. Both title as
`Protect <name>` and route the 2.8 body on `//signal/quest_failed`.

**Remaining caveat:**
- The `hostile_fleet` parent groups *all* enemy kills; genuinely optional/bonus targets
  aren't split out (the TODO on the parent says so).

## What stays MAST (graceful degradation)

- **Compound / non-verb triggers** → escape-hatch watchers (`gate_N`). Nothing is
  lost; the quest tree still owns the objective and its state.
- **Timed narrative beats** (`if_timer_finished` chains) — a clean chain of `>=2`
  pure timed beats (exactly `if_timer_finished T` + `if_variable F == n`, advancing
  `F`) is now emitted as a **reveal chain**: each beat is a `Done when: N seconds`
  quest that `Then: reveal`s the next, with its payload on
  `//shared/signal/quest_succeeded if QUEST_ID == "<key>"`. This required a small **library
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

## Measured findings (2026-08-15) — what was checked and left alone

Three candidate additions were sized against the corpus before building. All three came
back empty, and are recorded here so the next person does not re-derive them.

- **`Action:` stage directions on story beats — NOT built.** Across 1279 story-beat bodies
  the commands are 5402 `set_variable`, 3865 `clear_comms_button`, 2015
  `incoming_comms_text`, 814 `set_comms_button`, 779 `set_timer` -- plumbing. Of AMD's six
  core verbs, `becomes` has no 2.8 source (2.8 has no roles), `arrives` needs a **declared
  landmark record** the converter does not emit, `departs` is ~0, and `hails` would regress
  the existing comms-scene extraction (`a2x_comms_scene`), which lifts contiguous comms runs
  into real AMD dialogue scenes. What remains is `joins <side>`: **~20 lines out of ~13,000**.
  Converting 20 and leaving 12,980 in the MAST route would make a beat's effects live in two
  places, which reads worse than one.
- **`Fails when: <N> seconds` — NOT emitted.** Of 46 decider quests corpus-wide, **zero**
  fit the shape it would be sound for. `fail_after` anchors when the quest goes ACTIVE, so
  the mapping is only correct when the 2.8 timer is armed at that same moment; 24 timed
  deciders are WIN not LOSE, and the one timed LOSE is not armed at activation. The timer
  routes already express these exactly (`Starts when: signal <gate>`, pushed at the
  deadline).
- **`sbs lint` on generated AMD: 0 findings** across 8 missions. The vocabulary the emitter
  writes is current; there was nothing to catch up on.

## Library bug this work uncovered (2026-08-15)

Adopting `set_timer(signal=)` surfaced a real defect in it: **the signal fired and no route
ran**. `_signals_tick` runs outside any task, and the MastScheduler leaves its last task in
`FrameContext.task` without restoring it -- by then that task is FINISHED.
`signal_emit` passes it as the sender and `MastAsyncTask.emit_signal` drops any emit whose
sender is done (`mastscheduler.py:909`), so every `//signal` and `//shared/signal` route was
skipped.

The library's 24 `TestTimerSignals` cases all passed through it, because they assert via
`signal_observe` -- which runs *before* `signal_emit` even looks at the MAST context -- and
call `_signals_tick()` by hand. Repro: a two-label mission where the same signal is emitted
by a timer and by MAST; only the MAST one runs the route.

Fixed in `sbs_utils/procedural/timers.py` by clearing `FrameContext._task` (only the task;
page and event still belong to the frame) around the emit, with two regression tests in
`sbs_utils/tests/test_timers.py`.

## Open questions

- **Win/lose keyword heuristic** — good enough on the corpus, but titles are
  free-text. Worth a `--win-flag NAME` / `--lose-flag NAME` override?
- **Station/multi-condition wins** — `Done when:` is a single trigger. A win requiring
  "kill X *and* keep Y alive" needs a `Part of:` + `Required:` child (kill) plus a
  `Fatal:` child (`Fails when: all dead Y`). Auto-decompose, or scaffold + TODO?
- **Roles for goal targets** — the converter tags targets with synthesized roles
  (`bad_alien`, `fleet_1`). Confirm naming rules so hand-authored follow-ups agree.
- **`reach` sectors** — is a coord→sector table worth building so region triggers
  can use the native `on_reach` verb instead of the escape hatch?
- **Objective and decider quests still run their bodies on completion**
  (`//shared/signal/quest_succeeded if QUEST_ID == ...`). Now that `Starts when:` is a real
  arming gate, a 2.8 event could instead be a quest with `Starts when: <trigger>` and its
  body in the start slot -- a closer model of "when these conditions hold, do this". Left
  alone here: it touches the reveal graph, kill aggregation and win/lose wiring at once.
