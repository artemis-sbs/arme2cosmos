"""Assemble a Cosmos MAST mission scaffold from a parsed 2.8 mission.

Produces a directory with story.mast, script.py, story.json, description.yaml and
MIGRATION_NOTES.md. The output is a *scaffold*: positions/spawns are real, the rest is
TODO-marked for a human to finish.
"""

from __future__ import annotations

import os
import re

from .emit import (Emitter, emit_condition, _mast_str, _pyname, _cond_bool, _value,
                   _side_key, _DEFAULT_PLAYER_SIDE, _AI_OVERRIDES_DEFAULT,
                   player_slot_name, _num_key)
from .model import Mission
from .parser import parse_file

# Baseline gameplay addons; extras are feature-detected by the Emitter (e.g. upgrades
# when anomalies are present, collisions when there is terrain to hit).
#
# The first six are LegendaryMissions' own recommended set for "a standard multi-console
# combat mission" (see its addons/index.md), which is what a converted 2.8 mission is.
# The last two are baseline because 2.8 gives them to EVERY mission for free, so gating
# them on a source feature leaves a converted mission quietly missing them:
#   science_scans      -- `consoles` provides the Science console, but the scan RESPONSE
#                         routes live here. In 2.8 you can scan anything, so keying this
#                         off the source happening to set `set_ship_text scan_desc` left
#                         most missions with a Science console that answers nothing.
#   basic_player_destroy -- owns //shared/signal/player_ship_destroyed: deletes the ship,
#                         announces the loss, ends the game when the last player dies, and
#                         reassigns orphaned clients. Without it a 2.8 "you were destroyed"
#                         event fires but the game never ends and the crew sits on a wreck.
_BASELINE_ADDONS = ["consoles", "docking", "comms", "damage", "prefabs", "fleets",
                    "science_scans", "basic_player_destroy"]
# Library version tag the generated story.json references. Matches the libs shipped
# in the missions __lib__ folder; override with `convert --lib-version`.
DEFAULT_LIB_VERSION = "v1.4.0"


def _slug(name: str) -> str:
    s = re.sub(r"^MISS_", "", name)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s or "mission"


def _display_name(mission: Mission) -> str:
    return re.sub(r"^MISS_", "", mission.name).replace("_", " ")


# The eight ships 2.8 always gave a crew, matching LegendaryMissions' own PLAYER_LIST
# names and hulls. A 2.8 mission usually `create`s only the slots it cares about (often
# just slot 0) but the game still started with all eight, so a faithful conversion spawns
# the rest itself. It does NOT delegate to LM's PLAYER_CREATE_DEFAULT: those ships are
# built on side "tsn", which is not the mission's player side, so the crew ended up on a
# ship with no declared diplomacy -- hostiles read as neutral and nothing shot at them.
_DEFAULT_PLAYER_LIST = [
    {"name": "Artemis", "ship": "tsn_light_cruiser"},
    {"name": "Intrepid", "ship": "tsn_battle_cruiser"},
    {"name": "Aegis", "ship": "tsn_battle_cruiser"},
    {"name": "Horatio", "ship": "tsn_battle_cruiser"},
    {"name": "Excalibur", "ship": "tsn_battle_cruiser"},
    {"name": "Hera", "ship": "tsn_battle_cruiser"},
    {"name": "Ceres", "ship": "tsn_battle_cruiser"},
    {"name": "Diana", "ship": "tsn_battle_cruiser"},
]

# How far apart the filled-in player ships sit (2.8 units), so eight hulls do not stack
# on one point.
_PLAYER_FILL_SPACING = 1000

# Where the roster goes when the mission positions nobody (2.8 map centre).
_PLAYER_FILL_ORIGIN = (50000, 0, 50000)

# The 2.8 playing field on X and Z. Only the FILL positions are held inside it: a mission
# that puts its own ship at 98000 usually meant it -- the crew starts at the edge and flies
# in -- so its coordinates are emitted untouched. The fill ships are the tool's invention,
# and a2x_pos mirrors about 100000, so one laid out past the edge lands on a negative
# Cosmos coordinate: off the map, where the crew would see it in ship select and never
# find it in the world.
_MAP_MIN, _MAP_MAX = 0, 100000

# Role marking a spawned player ship the mission did not ask for. All eight exist at
# console-select so the crew can pick a hull; game_started then deletes the spares, so
# play starts with exactly the ships the mission declared (or Artemis alone).
_SPARE_PLAYER_ROLE = "a2x_spare_player"


def _on_map(v: float) -> float:
    """Hold a tool-invented FILL coordinate inside the 2.8 playing field. Backstop for the
    layout direction: a base point already off the map would otherwise take the whole
    roster with it."""
    return min(max(v, _MAP_MIN), _MAP_MAX)


def _mission_player_creates(mission: Mission) -> list:
    """Every ``create type="player"`` in the mission, not just the start block.

    Some 2.8 missions spawn their crew from an EVENT (MISS_Medusa's_Maze does), so a
    start-block-only view sees none and would wrongly conclude the mission has no player
    ships -- adding a second, unwanted roster on top of the ones it makes later.
    """
    return [n for n in mission.all_nodes() if n.kind_key() == "create:player"]


def _player_fill_lines(em: Emitter, players: list, mission: Mission | None = None) -> list[str]:
    """Spawn the player ships the 2.8 mission did not `create` itself.

    2.8 started every mission with eight crewable ships; a mission only `create`d the
    slots it positioned. Cosmos has whatever we spawn, so the remaining slots are filled
    here -- on the MISSION'S player side, which is the whole point: LegendaryMissions'
    PLAYER_CREATE_DEFAULT builds them on "tsn", and a crew that took one of those was on
    a side the mission never declared, so its diplomacy was empty (enemies neutral, no
    one hostile). Names and hulls match LM's PLAYER_LIST so the ship select reads the same.

    They are laid out along Z from the last 2.8 player create so eight hulls do not stack.
    """
    if len(players) >= len(_DEFAULT_PLAYER_LIST):
        return []
    # The mission makes its own crew somewhere (an event, not <start>) -- leave it alone.
    if not players and mission is not None and _mission_player_creates(mission):
        return []
    if players:
        last = players[-1]
        try:
            bx = float(last.get("x", "0")); by = float(last.get("y", "0")); bz = float(last.get("z", "0"))
        except (TypeError, ValueError):
            bx, by, bz = _PLAYER_FILL_ORIGIN
    else:
        # The mission positions nobody, so there is no reference point -- but a mission
        # with no player ship at all is unplayable, and 2.8 always had a crew.
        bx, by, bz = _PLAYER_FILL_ORIGIN
    # Mirror the name c_player actually emits, INCLUDING the slot-derived default for an
    # unnamed create -- otherwise the fill happily adds a second "Artemis".
    taken = {(n.get("name") or player_slot_name(n.get("player_slot", 0))).strip().lower()
             for n in players}
    side = _side_key(em.player_side if em.player_side is not None else _DEFAULT_PLAYER_SIDE)
    # The mission's own ships are kept; if it made none, Artemis alone is kept so the
    # mission is playable. Everything past that is a spare, marked at CREATION so
    # game_started can delete it without having to work out which is which.
    keep = max(len(players), 1)
    # Run the line toward whichever side of the base point has more room, so a mission that
    # starts its crew hard against an edge (98000) does not push the fill off the map.
    step = _PLAYER_FILL_SPACING if (_MAP_MAX - bz) >= (bz - _MAP_MIN) else -_PLAYER_FILL_SPACING
    out = [f"    # 2.8 always started with {len(_DEFAULT_PLAYER_LIST)} crewable ships; this mission "
           f"positions {len(players)}.",
           f"    # All {len(_DEFAULT_PLAYER_LIST)} exist for ship select; game_started deletes the",
           f"    # spares, leaving the {keep} the mission actually declared. Spawned on the",
           "    # mission's OWN player side -- PLAYER_CREATE_DEFAULT would use \"tsn\", a side",
           "    # this mission never declares, so its diplomacy would be empty."]
    i = len(players)
    for spec in _DEFAULT_PLAYER_LIST:
        if spec["name"].strip().lower() in taken:
            continue
        if i >= len(_DEFAULT_PLAYER_LIST):
            break
        z = _on_map(bz + step * (i - len(players) + 1))
        roles = side if i < keep else f"{side}, {_SPARE_PLAYER_ROLE}"
        out.append(f'    a2x_create_player({_on_map(bx):g}, {by:g}, {z:g}, "{spec["ship"]}", '
                   f'name="{spec["name"]}", side="{roles}")')
        i += 1
    return out


def _player_default_lines(em: Emitter) -> list[str]:
    """Turn LegendaryMissions' default player-ship creation OFF, always.

    Those ships are built on side ``"tsn"``, which is not the mission's player side. A
    crew that took one was on a side the mission never declared, so its diplomacy was
    empty -- hostiles rendered neutral and nothing treated the ship as an enemy. The
    converter spawns every player ship itself instead, on the mission's own side (see
    :func:`_player_fill_lines`), so there is one player side and it is a declared one.
    """
    em.side_values.add(em.player_side if em.player_side is not None else _DEFAULT_PLAYER_SIDE)
    return ["# Player ships are spawned by this mission on its OWN side; LegendaryMissions'",
            "# defaults would build them on \"tsn\", a side this mission never declares.",
            "PLAYER_CREATE_DEFAULT = False"]


def _player_route_lines(mission: Mission, em: Emitter) -> list[str]:
    """The ``//shared/signal/create_player_ships`` route holding the START block's player
    ships (plus the roster fill), so they exist before the crew picks a console.

    The map task is the wrong place for them. It runs when the map LOADS -- after the
    server console has already offered ship select -- so the crew was choosing from
    whatever hulls existed at that point, and the mission's own ships appeared underneath
    them. ``create_player_ships`` is the hook the server console fires inside start_server,
    right after ``create_sides`` and before the menu, which is where LegendaryMissions
    builds its own PLAYER_LIST ships. Spawning here puts the mission's ships in the list
    the crew actually picks from.

    Only ``<start>`` player creates move. A 2.8 mission may also create a player from an
    EVENT (MISS_Medusa's_Maze does); those stay where the event puts them, because they
    are mid-mission gameplay, not the starting roster.
    """
    players = [n for n in start_nodes(mission) if n.kind_key() == "create:player"]
    fill = _player_fill_lines(em, players, mission)
    if not players and not fill:
        return []   # the mission makes its crew from an event -- leave it there
    out = ["# 2.8 <start> player ships. Fired by the server console during start_server,",
           "# after create_sides and BEFORE ship select, so the crew picks from the ships",
           "# this mission declares (the map task would run too late -- it loads after the",
           "# console menu). Player creates inside 2.8 EVENTS stay in their event.",
           "//shared/signal/create_player_ships"]
    for n in players:
        out.append(f"    # {_xml_one(n)}")
        out.extend(em.emit_command(n))
    out.extend(fill)
    # Safe to end the task: a //shared/signal route is dispatched on its own spawned task
    # (signal_register defaults is_jump, and emit_signal start_task()s it), so ->END stops
    # this handler only -- not the server-start task that emitted the signal.
    out.append("    ->END")
    out.append("")
    return out


def plan_chain_flag_gates(seq_events: list, mission: Mission, em: Emitter) -> None:
    """Decide what each chained scene's ``if_variable`` becomes: a skip, a wait, or nothing.

    A flag test in a chained scene used to emit only a comment, leaving scenes with no gate
    at all -- how MISS_TrialsOfDeneb01 announced MISSION SUCCESS at t=0. But the two things
    a 2.8 flag test means need opposite translations, and getting it backwards is worse than
    the comment, so the decision is made HERE, where the chain order is known, rather than
    in the emitter, which sees one condition at a time.

    * a **latch** (``!= v``, ``== 0``, or a flag this scene's own body sets) is 2.8's
      run-once bookkeeping: "not done yet". Failing it means this scene has already had its
      turn -> SKIP.
    * a **phase gate** (``== v`` produced elsewhere) is "wait until the story reaches here"
      -> WAIT, but only when something that runs BEFORE this scene can set it: the start
      block, an event that is not in the chain (a polling loop or a route), or an earlier
      chained scene.
    * a gate whose only producer is a LATER chained scene would wait on its own future.
      2.8 does not care -- its events all run continuously, so order is free -- but a linear
      chain would deadlock, and a deadlocked mission is worse than a mistimed one. Those
      SKIP as well, and are counted into MIGRATION_NOTES as the ordering the chain could not
      express.
    * a flag never set to that value anywhere fires in neither engine -> SKIP.
    """
    chain_pos = {id(ev): i for i, ev in enumerate(seq_events)}
    # (flag, numeric value) -> the chain positions that produce it, and whether anything
    # OUTSIDE the chain does (start block, polling loop, route -- all live from t=0).
    setters: dict[tuple, set] = {}
    off_chain: set = set()
    for n in mission.start:
        if n.tag == "set_variable" and n.get("name"):
            off_chain.add((_pyname(n.get("name")), _num_key(n.get("value"))))
    for ev in mission.events:
        pos = chain_pos.get(id(ev))
        for n in ev.commands:
            if n.tag != "set_variable" or not n.get("name"):
                continue
            key = (_pyname(n.get("name")), _num_key(n.get("value")))
            if pos is None:
                off_chain.add(key)
            else:
                setters.setdefault(key, set()).add(pos)
    late = 0
    for i, ev in enumerate(seq_events):
        own = {_pyname(n.get("name")) for n in ev.commands
               if n.tag == "set_variable" and n.get("name")}
        for c in ev.conditions:
            if c.tag != "if_variable" or not c.get("name"):
                continue
            name, vkey = _pyname(c.get("name")), _num_key(c.get("value"))
            cmp_ = (c.get("comparator", "") or "").strip().upper()
            is_zero = (c.get("value", "") or "").strip() in ("0", "0.0")
            if cmp_ in ("NOT", "!=") or (cmp_ in ("EQUALS", "=") and is_zero) or name in own:
                em.chain_flag_gate[id(c)] = "skip"
                continue
            if vkey is None:
                continue   # an expression, not a value we can reason about -> comment
            before = {p for p in setters.get((name, vkey), set()) if p < i}
            if (name, vkey) in off_chain or before:
                em.chain_flag_gate[id(c)] = "wait"
            else:
                em.chain_flag_gate[id(c)] = "skip"
                if setters.get((name, vkey)):
                    late += 1
    if late:
        em.note(f"chain order: {late} chained scene(s) gate on a flag that only a LATER "
                f"scene sets. 2.8 events run continuously so order was free; a linear chain "
                f"cannot wait on its own future without deadlocking, so those scenes are "
                f"skipped. Re-order them, or regenerate with --event-model a28_compatible.")


def is_player_respawn_event(ev, em: Emitter) -> bool:
    """The 2.8 "the crew died" respawn idiom: an event gated on the player ship no longer
    existing whose body re-creates it (MISS_HereThereBeMonsters' "Mission Report 3" shows
    the failure card, starts the outro timers, then re-creates Artemis at the start point).

    Cosmos has this built in, so the tool routes the event onto it rather than re-emitting
    the create -- see :func:`build_player_respawn_routes`.
    """
    if not any(n.kind_key() == "create:player" for n in ev.commands):
        return False
    return any(c.tag == "if_not_exists" and _names_player(c, em) for c in ev.conditions)


def _names_player(c, em: Emitter) -> bool:
    """Does this condition name the player ship (by 2.8 name, or by player_slot)?"""
    if c.get("name"):
        return em.symbols.get(c.get("name")) == em.player_var and em.player_var is not None
    return c.get("player_slot") is not None


def build_player_respawn_routes(events: list, em: Emitter) -> list[str]:
    """2.8 player-respawn events -> LegendaryMissions' own respawn + a
    ``//shared/signal/player_ship_destroyed`` route carrying the rest of the event.

    The 2.8 body is kept (failure card, timers, flags) but its ``create type="player"`` is
    DROPPED, because Cosmos already does that better. With ``PLAYER_SHIP_RESPAWN`` on,
    ``basic_player_destroy`` revives the SAME ship agent 2s after death at its ``spawn_pos``
    -- which for a converted mission is the 2.8 create's own coordinates -- and rebuilds its
    grid. Re-creating a ship instead would leave the crew behind: the client route has
    already bounced them to console-select, and they do not follow a brand-new hull.

    The ``if_not_exists`` condition is deliberately NOT part of the guard. It is what the
    signal MEANS, and it is not even true yet when the signal fires: the ship is still there
    (flagged ``exploded``) and is only deleted/revived afterwards, so testing it here would
    make the route never run. Every OTHER condition stays as a guard, which is also what
    preserves the one-shot 2.8 behaviour -- these events gate on a flag their own body
    clears.
    """
    if not events:
        return []
    # settings.yaml, merged over the built-in defaults by settings_get_defaults(). It has to
    # be a SETTING: basic_player_destroy reads it into a plain `shared` (not `default
    # shared`), so a story.mast assignment can be clobbered depending on load order.
    em.settings["PLAYER_SHIP_RESPAWN"] = True
    em.note("player respawn: settings.yaml turns PLAYER_SHIP_RESPAWN on, so EVERY player "
            "death revives the ship. The 2.8 event was one-shot -- if the mission meant "
            "'one extra life', gate it by hand or turn the setting off.")
    out = ["",
           "# 2.8 player-respawn event -> Cosmos' own player respawn. settings.yaml sets",
           "# PLAYER_SHIP_RESPAWN, so LegendaryMissions' basic_player_destroy revives the",
           "# SAME ship 2s after death at its spawn point (the 2.8 create's coordinates)",
           "# and rebuilds its grid. The 2.8 <create type=\"player\"> is dropped: a fresh",
           "# hull would not get the crew back, whose clients the destroy route has already",
           "# sent to console-select. What is left here is the mission's own reaction."]
    for ev in events:
        out.append(f"//shared/signal/player_ship_destroyed   # {ev.name} (was if_not_exists)")
        bools, unhandled = [], []
        for c in ev.conditions:
            if c.tag == "if_not_exists" and _names_player(c, em):
                continue   # that IS this signal (and is not true yet when it fires)
            b = _cond_bool(em, c)
            (bools.append(b) if b else unhandled.append(c))
        for c in unhandled:
            out.append(f"    # when (verify by hand): {_xml_one(c)}")
        if bools:
            out.append(f"    ->END if not ({' and '.join(bools)})")
        for n in ev.commands:
            out.append(f"    # {_xml_one(n)}")
            if n.kind_key() == "create:player":
                out.append("    # ^ dropped: respawn_player_ship revives the ship the crew "
                           "is already on.")
                continue
            out.extend(em.emit_command(n))
        out.append("    ->END")
        out.append("")
    return out


def build_story_mast(mission: Mission, em: Emitter, event_model: str = "hybrid") -> str:
    _prescan_named_objects(mission, em)
    em.emit_scan_roles = True  # recover set_ship_text scan_desc / hailtext (see below)
    _prescan_scan_hail(mission, em)
    label = _slug(mission.name)
    disp = _display_name(mission)
    lines: list[str] = []
    lines.append(f"# Migrated from {os.path.basename(mission.source_path)} by arme2cosmos.")
    lines.append("# Scaffold only -- see MIGRATION_NOTES.md for the punch-list.")
    lines.append("# Positions use 2.8 coords; a2x_* helpers flip them to Cosmos internally.")
    lines.append("")
    lines.extend(_player_default_lines(em))
    lines.append("")
    # Built BEFORE the map body: the route runs before the map loads, so every emitter
    # below is right to treat player_ship as already assigned (em.player_emitted).
    player_route = _player_route_lines(mission, em)
    lines.append(f'@map/{label} "{disp}"')
    for d in mission.description.replace("^", " ").split("\n"):
        d = d.strip()
        if d:
            lines.append(f'" {d}')
    lines.append("    shared main_story_task = mast_task")
    obj_vars = sorted(set(em.symbols.values()) | ({em.player_var} if em.player_var else set()))
    if obj_vars:
        lines.append("    # objects forward-declared (shared so concurrent event tasks see them)")
        for v in obj_vars:
            # player_ship is filled in by //shared/signal/create_player_ships, which has
            # ALREADY run by the time the map loads -- `shared player_ship = None` here
            # would throw the spawned ship away. `default` leaves an existing value alone.
            kw = "default shared" if player_route and v == em.player_var else "shared"
            lines.append(f"    {kw} {v} = None")
    # flags forward-declared (shared) so independent-event tasks can poll/guard on them
    flag_vars = sorted({_pyname(n.get("name")) for n in mission.all_nodes()
                        if n.tag in ("set_variable", "if_variable") and n.get("name")})
    flag_vars = [f for f in flag_vars if f not in obj_vars]
    if flag_vars:
        lines.append("    # event flags forward-declared (shared, default 0)")
        for v in flag_vars:
            lines.append(f"    default shared {v} = 0")
    lines.append("")

    # Partition events up front (before the start block, so a set_variable on a
    # signal-flag there can emit its signal too).
    # Comms/GM button-handler events become //comms buttons (GM ones gated to the GM
    # console), not linear-chain labels.
    comms_btn_events: dict[str, object] = {}
    gm_btn_events: dict[str, object] = {}
    respawn_player_events = []
    plain_events = []
    for ev in mission.events:
        # "player is gone -> re-create it" is engine-driven in Cosmos; pull those out before
        # anything else, or they land in the scene chain and only get one shot at whatever
        # point the chain reaches them (2.8 had them armed from the start).
        if is_player_respawn_event(ev, em):
            respawn_player_events.append(ev)
            continue
        cb = next((c for c in ev.conditions if c.tag == "if_comms_button"), None)
        gb = next((c for c in ev.conditions if c.tag == "if_gm_button"), None)
        gk = next((c for c in ev.conditions if c.tag == "if_gm_key"), None)
        # A GM key shortcut (and any event acting on the GM's selection) only makes sense on
        # the GM console -- route it into the gamemaster //comms tree, the one context where
        # use_gm_selection == COMMS_SELECTED_ID is valid. Otherwise it would become a polling
        # beat referencing an undefined COMMS_SELECTED_ID.
        uses_gm_sel = any(n.get("use_gm_selection") is not None for n in ev.commands)
        if cb is not None:
            comms_btn_events.setdefault(cb.get("text", ""), ev)
        elif gb is not None:
            gm_btn_events.setdefault(gb.get("text", ""), ev)
        elif gk is not None:
            # Cosmos has no GM hotkeys -> expose the 2.8 hotkey action as a GM comms button
            # (grouped under a "Hotkeys" submenu), the closest supported GM trigger.
            gm_btn_events.setdefault(f"Hotkeys/{gk.get('keyText', '?')}", ev)
        elif uses_gm_sel:
            gm_btn_events.setdefault(ev.name or "GM Action", ev)
        else:
            plain_events.append(ev)

    # Event model:
    #   'linear'         = one sequential scene chain (most readable, least faithful).
    #   'hybrid' (default) = flag-chained scenes stay linear, independent events run
    #                      concurrently, the engine-pushable ones become routes.
    #   'a28_compatible' = every event becomes its own continuous polling task, exactly
    #                      like 2.8's flat-event model -- the worst-case faithful fallback
    #                      (no classification, no chain, no routes).
    if event_model == "linear":
        seq_events, indep_events = plain_events, []
    elif event_model == "a28_compatible":
        seq_events, indep_events = [], plain_events
    else:
        seq_events, indep_events = _classify_events(plain_events)

    # Independent events: convert the ones the engine can PUSH into event-driven routes
    # (respawn-on-destroy, dock, flag-signal) so they don't poll; the rest stay loops.
    # a28_compatible skips routing entirely -- every event is a uniform polling task.
    respawn_events, dock_events, flag_events, loop_events = [], [], [], []
    if event_model == "a28_compatible":
        loop_events = list(indep_events)
    else:
        for ev in indep_events:
            rn = _respawn_name(ev)
            if rn and rn in em.symbols:
                respawn_events.append(ev)
            elif _is_dock(ev):
                dock_events.append(ev)
            elif _flag_signal(ev) is not None:
                flag_events.append(ev)
            else:
                loop_events.append(ev)
    em.signal_flags = {_pyname(_flag_signal(ev).get("name")) for ev in flag_events}
    if dock_events:
        em.addons.add("docking")
    em.event_model = event_model
    em.event_summary = {
        "scene chain": len(seq_events), "polling loops": len(loop_events),
        "respawn routes": len(respawn_events), "dock routes": len(dock_events),
        "flag-signal routes": len(flag_events),
        "player-respawn routes": len(respawn_player_events),
    }

    lines.append("    # --- start block ---")
    for n in start_nodes(mission):
        if n.tag in _CONSOLE_ADDRESSED_START:
            continue   # deferred to //shared/signal/game_started (see _game_started_lines)
        if n.kind_key() == "create:player":
            continue   # hoisted to //shared/signal/create_player_ships (runs before select)
        lines.append(f"    # {_xml_one(n)}")
        lines.extend(em.emit_command(n))
    lines.append("")

    if em.scans:  # 2.8 set_ship_text scan_desc -> declarative science scans (scans.amd)
        em.addons.add("science_scans")
        lines.append("    # 2.8 set_ship_text scan_desc -> declarative science scans")
        lines.append('    science_define_scan_amd(document_get_amd_file('
                     'get_mission_dir_filename("scans.amd"), data_parser=amd_scan_data))')
        lines.append("")

    if loop_events or respawn_events:
        lines.append("    # independent events: start polling loops + initial respawns")
        for i, _ev in enumerate(loop_events):
            lines.append(f"    task_schedule(ind_event_{i})")
        for j, _ev in enumerate(respawn_events):
            lines.append(f"    task_schedule(respawn_{j})")  # initial spawn (then routed)
        lines.append("")

    # Decide the flag gates before emitting any scene: the verdict for one scene depends on
    # where every OTHER scene sits in the chain, which a per-condition emitter cannot see.
    plan_chain_flag_gates(seq_events, mission, em)
    for i, ev in enumerate(seq_events):
        lines.append(f"--- event_{i}" + (f"   # {ev.name}" if ev.name != f"event_{i}" else ""))
        # A guard that fails skips to the NEXT scene. The last one has no next, so there it
        # ends the task -- which is also where the chain ends anyway.
        nxt = f"event_{i + 1}" if i + 1 < len(seq_events) else None
        for c in ev.conditions:
            lines.extend(emit_condition(em, c, i, next_label=nxt))
        for n in ev.commands:
            lines.append(f"    # {_xml_one(n)}")
            lines.extend(em.emit_command(n))
        lines.append("")

    lines.append("    ->END")  # end the map task before the route/loop labels

    # --- respawn-on-destroy -> //damage/destroy routes (event-driven, no polling) ---
    for j, ev in enumerate(respawn_events):
        name = _respawn_name(ev)
        var, slug = em.symbols[name], _pyname(name)
        lines.append(f"=== respawn_{j}   # {ev.name}: (re)spawn {name}")
        for n in ev.commands:
            lines.append(f"    # {_xml_one(n)}")
            lines.extend(em.emit_command(n))
        lines.append(f'    add_role({var}, "respawn_{slug}")')  # tag so the route finds it
        lines.append("    ->END")
        lines.append("")
        lines.append(f'//damage/destroy if has_role(DESTROYED_ID, "respawn_{slug}")')
        lines.append(f"    task_schedule(respawn_{j})")
        lines.append("    ->END")
        lines.append("")

    # --- docked -> //signal/ship_docked (LM docking emits this on station dock) ---
    for ev in dock_events:
        lines.append(f"//signal/ship_docked   # {ev.name} (was if_docked)")
        for n in ev.commands:
            lines.append(f"    # {_xml_one(n)}")
            lines.extend(em.emit_command(n))
        lines.append("    ->END")
        lines.append("")

    # --- flag waits -> //signal routes fired by set_variable (event-driven) ---
    for ev in flag_events:
        c = _flag_signal(ev)
        name, val = _pyname(c.get("name")), _value(c.get("value", "0"))
        lines.append(f"//signal/a2x_flag_{name}   # {ev.name} (was if_variable {name})")
        lines.append(f"    ->END if not ({name} == {val})")  # signal fires on any set; guard value
        for n in ev.commands:
            lines.append(f"    # {_xml_one(n)}")
            lines.extend(em.emit_command(n))
        lines.append("    ->END")
        lines.append("")

    # --- remaining independent events -> continuous polling loops (re-fire each tick) ---
    for i, ev in enumerate(loop_events):
        nm = f"   # {ev.name}" if ev.name != f"event_{i}" else ""
        lines.append(f"=== ind_event_{i}{nm}")
        bools, unhandled = [], []
        for c in ev.conditions:
            b = _cond_bool(em, c)
            (bools.append(b) if b else unhandled.append(c))
        for c in unhandled:
            lines.append(f"    # when (verify by hand): {_xml_one(c)}")
        loop = f"ind_event_{i}_loop"
        lines.append(f"---{loop}")
        lines.append("    await delay_sim(0.5)")
        if bools:
            lines.append(f"    jump {loop} if not ({' and '.join(bools)})")
        for n in ev.commands:
            lines.append(f"    # {_xml_one(n)}")
            lines.extend(em.emit_command(n))
        if bools and not _is_fire_once(ev):
            lines.append(f"    jump {loop}")  # 2.8 event re-fires while conditions hold
        else:
            lines.append("    ->END")  # fire-once self-guard (or nothing to loop on)
        lines.append("")

    lines.extend(build_player_respawn_routes(respawn_player_events, em))
    lines.extend(build_button_route(
        mission, em, comms_btn_events, set_tag="set_comms_button",
        header="//comms", handler_tag="if_comms_button",
        comment="# 2.8 comms buttons -> a //comms route (refine the gating/selection).",
        addons=["comms"]))
    lines.extend(build_gm_tree_routes(mission, em, gm_btn_events))
    if em.hails:  # 2.8 set_ship_text hailtext -> a Hail comms button (per-ship stored hail)
        em.addons.add("comms")
        lines += [
            "",
            "# 2.8 set_ship_text hailtext -> a Hail comms button (per-ship stored hail).",
            '//comms if is_space_object_id(COMMS_SELECTED_ID) and '
            'get_inventory_value(COMMS_SELECTED_ID, "a2x_hail", "") != ""',
            '    + "Hail":',
            '        comms_receive(get_inventory_value(COMMS_SELECTED_ID, "a2x_hail", ""), '
            'title="Hail")',
        ]
    # Every sideValue the mission touches is known only now, so splice the side
    # declaration in ahead of the map (it must run before anything spawns) -- and the
    # player route after it, matching the order start_server fires the two signals in.
    lines[_map_label_index(lines):_map_label_index(lines)] = (
        _create_sides_lines(em) + player_route)
    lines += _game_started_lines(mission, em)
    return "\n".join(lines) + "\n"


def _game_started_lines(mission: Mission, em: Emitter) -> list[str]:
    """The ``//shared/signal/game_started`` route carrying the start block's
    console-addressed messages.

    A 2.8 mission opens with a big_message chapter card, and the converter emitted it
    first in the map task -- which runs at map LOAD. Those calls resolve their audience
    immediately, and an empty console set is a normal quiet case for the overlay layer,
    so before the crew took consoles the card was discarded with no error at all. This
    route fires once play actually begins, which is what 2.8's start block meant.
    """
    nodes = [n for n in start_nodes(mission) if n.tag in _CONSOLE_ADDRESSED_START]
    players = [n for n in start_nodes(mission) if n.kind_key() == "create:player"]
    # Spares exist whenever the mission positioned fewer than the full roster -- including
    # when it positioned NONE, where the roster is spawned wholesale and only Artemis is
    # kept. Keying this on `players` alone missed exactly that case.
    has_spares = (len(players) < len(_DEFAULT_PLAYER_LIST)
                  and not (not players and _mission_player_creates(mission)))
    if not nodes and not has_spares:
        return []
    out = ["",
           "# 2.8 start-block messages, shown when play BEGINS rather than at map load.",
           "# They address console clients, and an empty console set is silently ignored,",
           "# so firing them from the map task meant the crew never saw them.",
           "//shared/signal/game_started",
           "    # Yield first: the consoles server_console signals here are still coming up",
           "    # ('Consoles are waiting to be started'), so this route runs before their",
           "    # pages exist. Resolving the audience in that same frame finds nobody, and",
           "    # an empty console set is discarded silently -- the card just never appears.",
           "    # One frame is enough in practice; a second gives margin for a slower client.",
           "    await delay_sim(1)",
           "    # Re-apply the contact colours here as well as in a2x_declare_sides. The",
           "    # sides are declared from //shared/signal/create_sides, which the server",
           "    # console fires during start_server, where sim may not be live yet -- and a",
           "    # missing sim skips the colours SILENTLY, which looks exactly like broken",
           "    # diplomacy: correctly hostile ships drawn in the neutral colour.",
           "    a2x_set_diplomacy_colors()"]
    if em.side_values:
        # Re-declare the sides here as well as in //shared/signal/create_sides.
        # declare_sides is idempotent, and the point is its ENGINE-side calls:
        # sim.set_side_relationship (2D map / diplomacy shading) and
        # sim.set_side_icon_color. Those do not stick when issued during
        # create_sides, which the server console fires inside start_server -- the
        # link graph survives (so every scripting-level check passes) while the
        # engine's own tables stay at their defaults and contacts render gray.
        # Verified: the icon colour was gray until re-applied after start.
        out += ["    # Re-assert sides AFTER start: the engine-side relationship/colour",
                "    # tables do not retain what create_sides set during start_server,",
                "    # even though the scripting-level link graph does. One re-assert at",
                "    # ~1s proved too early in-engine (contacts stayed grey); the same",
                "    # calls at ~3s took. Rather than bet on one delay, re-assert a few",
                "    # times over the first seconds -- it is idempotent and cheap.",
                "    task_schedule(a2x_reassert_sides)"]
    if has_spares:
        # The mission spawned its own player ships at the 2.8 positions. Tag them so the
        # LegendaryMissions crew-select / loadout machinery treats them as the game's
        # player ships. Deliberately NOT via spawn_players: that also repositions ships
        # near a friendly station, which would throw away the 2.8 spawn coordinates.
        out += [f"    # Ship select is over: drop the spare hulls, leaving the ships the",
                f"    # mission declared. a2x_create_player already tagged every player ship",
                f"    # default_player_ship at creation, so LM's crew-select / loadout",
                f"    # machinery sees them without spawn_players (which would reposition",
                f"    # them and discard the 2.8 spawn coordinates).",
                f'    delete_object(role("{_SPARE_PLAYER_ROLE}"))']
    for n in nodes:
        out.append(f"    # {_xml_one(n)}")
        out.extend(em.emit_command(n))
    out.append("    ->END")
    if has_spares or em.side_values:
        pass
    if em.side_values:
        vals = sorted(em.side_values)
        out += ["",
                "# The engine's side relationship / icon-colour tables do not retain what",
                "# create_sides wrote during start_server, and a single re-assert just after",
                "# game_started is still too early. Re-apply over the first few seconds; both",
                "# calls are idempotent, so the repeats cost nothing once they have taken.",
                "=== a2x_reassert_sides",
                "    _n = 0",
                "---a2x_reassert_loop",
                "    await delay_sim(1)",
                f"    a2x_declare_sides({vals!r})",
                "    a2x_set_diplomacy_colors()",
                "    _n = _n + 1",
                "    jump a2x_reassert_loop if _n < 6",
                "    ->END"]
    return out


def _map_label_index(lines: list[str]) -> int:
    """Index of the ``@map/...`` line -- where mission-level routes are spliced in."""
    for i, l in enumerate(lines):
        if l.startswith("@map/"):
            return i
    return len(lines)


def _create_sides_lines(em: Emitter) -> list[str]:
    """The ``//shared/signal/create_sides`` route that declares this mission's sides.

    2.8 has no diplomacy table: sideValue IS the faction, and the engine implicitly makes
    different non-zero values hostile. Cosmos resolves allegiance through registered side
    agents instead, so a converted mission must declare it -- otherwise every
    ``side_are_enemies`` test is False, and the LegendaryMissions NPC brains gate firing on
    exactly that (``shoot = side_are_enemies(...)``), giving ships that chase but never fire.

    ``create_sides`` is the right hook rather than the map's start block: the server console
    fires it during start_server, BEFORE default player ships spawn and before any map runs.
    (Same route OpenUniverse defines for its own sides -- LegendaryMissions' answer to it
    lives in its maps/ folder, which is mission content, not one of the shipped mastlibs, so
    a converted mission never inherits it.)
    """
    if not em.side_values:
        return []
    values = sorted(em.side_values)
    keys = ", ".join(_side_key(v) for v in values)
    return [
        "# 2.8 sideValue -> Cosmos sides + diplomacy. 2.8 leaves this implicit (different",
        "# sideValue = hostile); Cosmos needs it declared or nothing is anyone's enemy --",
        f"# no NPC fires, and Science shows no allied/hostile split. Sides here: {keys}.",
        "# Fired by the server console before player ships spawn. Synchronous on purpose:",
        "# no await, and NO ->END (the route runs inline in the server-start task, so",
        "# ending the task would end the caller).",
        "//shared/signal/create_sides",
        f"    a2x_declare_sides({values!r})",
        "",
    ]


def _prescan_references(mission: Mission, em: Emitter) -> None:
    """Collect the object names a NON-create node references (name / name1 / name2 /
    objectName / targetName). A monster whose name is referenced later needs the capturable
    a2x_create_monster path (prefab_spawn returns a task, not a grabbable object id)."""
    ref: set[str] = set()
    for n in mission.all_nodes():
        if n.tag == "create":
            continue
        for k in ("name", "name1", "name2", "objectName", "targetName"):
            v = n.get(k)
            if v:
                ref.add(v)
    em.referenced_names = ref


def _prescan_scan_hail(mission: Mission, em: Emitter) -> None:
    """Populate em.scans / em.hails from set_ship_text so the science-scan load call and
    the Hail route are emitted even when the set_ship_text lives in an event body."""
    for nd in mission.all_nodes():
        if nd.tag == "set_ship_text" and em.symbols.get(nd.get("name")):
            if nd.get("scan_desc") is not None:
                em.scans[nd.get("name")] = _mast_str(nd.get("scan_desc"))
            if nd.get("hailtext") is not None:
                em.hails[nd.get("name")] = _mast_str(nd.get("hailtext"))


GM_GATE = "if has_roles(COMMS_ORIGIN_ID, 'gamemaster')"


# create kinds that are captured into a MAST variable (mirror of the c_* emitters).
_CAPTURED_CREATES = {"create:station", "create:enemy", "create:neutral",
                     "create:monster", "create:whale", "create:genericMesh",
                     "create:Anomaly", "create:blackHole"}


# Start-block commands that address CONSOLE CLIENTS. They resolve their audience when
# called, and the overlay / info-panel layers treat an empty console set as the normal
# "nobody connected yet" case -- so they are dropped SILENTLY. Run at map load, before the
# crew has taken consoles, they simply never appear. These are deferred to
# //shared/signal/game_started, the point LegendaryMissions treats as "play has begun"
# (autoplay, collisions, fleets and quest_driver all hook it).
_CONSOLE_ADDRESSED_START = {"big_message", "incoming_comms_text", "warning_popup_message",
                            "incoming_message"}


def start_nodes(mission: Mission) -> list:
    """The start block's commands, with every `create type="player"` hoisted to the front.

    In 2.8 the player ship ALREADY EXISTS when the mission loads -- the player picks it at
    the console, and `create type="player"` only places and configures that ship. So a 2.8
    start block may legitimately reference the player above its own create; MISS_Cruiser_
    Tournament puts `set_player_carried_type` there. Cosmos has no such ship until we spawn
    one, so emitting in source order left the reference resolving to nothing (the LM hangar
    then crashed on `to_space_object(None).origin`).

    Hoisting restores the 2.8 guarantee. It is safe: a player create depends on nothing but
    its own coordinates, and relative order among the player creates (slot 0, 1, ...) is
    preserved, as is the order of everything else.
    """
    players = [n for n in mission.start if n.kind_key() == "create:player"]
    rest = [n for n in mission.start if n.kind_key() != "create:player"]
    return players + rest


def _side_value_of(n, em: Emitter) -> int:
    """A create node's 2.8 sideValue as an int, defaulting to the player side (2)."""
    raw = (n.get("sideValue") or "").strip()
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return _DEFAULT_PLAYER_SIDE


def _prescan_named_objects(mission: Mission, em: Emitter) -> None:
    """Register every named created object up front so later commands resolve them
    regardless of emission order (forward references, button-handler events)."""
    for n in mission.all_nodes():
        if n.tag != "create":
            continue
        kind = n.kind_key()
        if kind == "create:player":
            # Note the player BEFORE the name check: a 2.8 player create is usually
            # unnamed (`<create type="player" player_slot="0" .../>`), and skipping those
            # left player_var None -- so the header asked LegendaryMissions to build a
            # default ship from PLAYER_LIST *and* the body spawned one, giving two ships.
            em.player_var = "player_ship"
            em.player_side = _side_value_of(n, em)
            if n.get("name"):
                em.symbols.setdefault(n.get("name"), "player_ship")
            continue
        if n.get("name") and kind in _CAPTURED_CREATES:
            em._var_for(n.get("name"))
    # 2.8 gives EVERY enemy an implicit default brain stack; a mission only writes
    # <add_ai> to override it. Record which ships get an explicit override so the rest
    # can be given the default (without it a converted enemy has no brain and sits inert).
    for n in mission.all_nodes():
        if (n.tag == "add_ai" and n.get("name")
                and (n.get("type") or "").upper() in _AI_OVERRIDES_DEFAULT):
            em.explicit_ai_names.add(n.get("name"))
    # 2.8 named carried craft (set_player_carried_type) are real spawned hangar objects --
    # capture their names too, so later references (set_relative_position / if_distance /
    # add_ai targetName) resolve to the spawned craft.
    for n in mission.all_nodes():
        if n.tag == "set_player_carried_type" and n.get("name"):
            em._var_for(n.get("name"))


def _truthy(v: str) -> bool:
    try:
        return float(v) != 0
    except (TypeError, ValueError):
        return bool(v and v.strip())


def _respawn_name(ev) -> str | None:
    """A single ``if_not_exists NAME`` event -> NAME (a respawn-on-destroy candidate)."""
    if len(ev.conditions) == 1 and ev.conditions[0].tag == "if_not_exists":
        return ev.conditions[0].get("name")
    return None


def _is_dock(ev) -> bool:
    """A single ``if_docked`` event -> a //signal/ship_docked route candidate."""
    return len(ev.conditions) == 1 and ev.conditions[0].tag == "if_docked"


def _flag_signal(ev):
    """A single ``if_variable F == val`` event the engine can push as a signal.

    Returns the condition node, or None. Excludes ``!=``/other comparators (a signal
    fires on a *set*, so only ``==`` maps cleanly) and events that set the flag they
    listen on (would self-trigger -- keep those as polling loops).
    """
    if len(ev.conditions) != 1 or ev.conditions[0].tag != "if_variable":
        return None
    c = ev.conditions[0]
    if (c.get("comparator", "") or "").strip().upper() not in ("EQUALS", "="):
        return None
    if c.get("name") in {x.get("name") for x in ev.commands if x.tag == "set_variable"}:
        return None
    return c


def _is_fire_once(ev) -> bool:
    """True if the event self-guards against re-firing: an ``if_variable`` NOT/!= test
    on a flag the event itself sets (2.8's run-once idiom). Such an event makes sense to
    ``->END`` after firing; others loop continuously like a real 2.8 event.
    """
    sets = {c.get("name") for c in ev.commands if c.tag == "set_variable"}
    return any(c.tag == "if_variable"
               and (c.get("comparator", "") or "").strip().upper() in ("NOT", "!=")
               and c.get("name") in sets
               for c in ev.conditions)


def _event_flags(ev):
    """(flags this event SETS to a truthy value, flags it WAITS on == truthy)."""
    sets = {c.get("name") for c in ev.commands
            if c.tag == "set_variable" and _truthy(c.get("value"))}
    needs = {c.get("name") for c in ev.conditions
             if c.tag == "if_variable"
             and (c.get("comparator", "") or "").strip().upper() in ("EQUALS", "=")
             and _truthy(c.get("value"))}
    return sets, needs


def _classify_events(events):
    """Split events into (sequential, independent).

    An event is *sequential* (kept in the linear scene chain) if it is flag-linked to
    another event -- it waits on a flag an earlier event sets, or it sets a flag a
    later event waits on. Otherwise it is *independent* (its trigger is external --
    a timer/distance/dock, not gated by the chain) and is scheduled as its own task.
    """
    flags = [_event_flags(ev) for ev in events]
    sets_l = [s for s, _ in flags]
    needs_l = [n for _, n in flags]
    seq, indep = [], []
    for i, ev in enumerate(events):
        sets, needs = flags[i]
        consumes_prior = any(needs & sets_l[j] for j in range(i))
        feeds_later = any(sets & needs_l[j] for j in range(i + 1, len(events)))
        (seq if (consumes_prior or feeds_later) else indep).append(ev)
    return seq, indep


def _button_body(em: Emitter, ev, handler_tag: str) -> list[str]:
    """The inline body (8-space indented) for a `+ "label":` button."""
    body: list[str] = []
    if ev is None:
        # A 2.8 button declared with no handler event is a genuine no-op button; keep it as
        # a clean GM comms-tree item (not a TODO -- there is nothing to wire).
        body.append(f"        # 2.8 button declared with no {handler_tag} handler -- no-op")
        body.append("        ~~ pass ~~")
    else:
        for c in ev.conditions:
            if c.tag != handler_tag:
                body.append(f"        # guard: {_xml_one(c)}")
        for n in ev.commands:
            body.append(f"        # {_xml_one(n)}")
            for ln in em.emit_command(n):
                body.append(("    " + ln) if ln.strip() else ln)
    # A `+ "..":` block needs at least one real statement; an all-comment body is an
    # empty block to MAST.
    if not any(ln.strip() and not ln.strip().startswith("#") for ln in body):
        body.append("        ~~ pass ~~")
    return body


def build_gm_tree_routes(mission: Mission, em: Emitter, gm_events: dict) -> list[str]:
    """2.8 GM buttons -> a gamemaster-gated //comms tree. Slash-delimited button text
    (``AI/Enemy/bombastic captain``) becomes nested //comms/gm/... submenu routes;
    the final segment is the leaf button carrying the handler body."""
    declared = [n.get("text", "") for n in mission.all_nodes()
                if n.tag == "set_gm_button" and n.get("text")]
    texts = list(dict.fromkeys(declared + list(gm_events)))
    if not texts:
        return []
    em.addons.update({"gamemaster", "gamemaster_comms"})

    root = {"kids": {}}
    for text in texts:
        node = root
        for seg in (s.strip() for s in text.split("/") if s.strip()):
            node = node["kids"].setdefault(seg, {"kids": {}, "event": None})
        node["event"] = gm_events.get(text)

    out = ["", "# 2.8 GM buttons -> a gamemaster-gated //comms tree (slash = submenu).",
           f"//comms {GM_GATE}"]
    out += _gm_buttons(em, root, "//comms/gm")
    for seg, child in root["kids"].items():
        if child["kids"]:
            out += _gm_route(em, child, f"//comms/gm/{_slug(seg)}", back="//comms")
    return out


def _gm_buttons(em: Emitter, node: dict, child_base: str) -> list[str]:
    """The `+` buttons for a node's children: nav buttons for branches, leaf bodies."""
    out = []
    for seg, child in node["kids"].items():
        if child["kids"]:
            out.append(f'    + "{_mast_str(seg)}" {child_base}/{_slug(seg)}')
        else:
            out.append(f'    + "{_mast_str(seg)}":')
            out += _button_body(em, child.get("event"), "if_gm_button")
    return out


def _gm_route(em: Emitter, node: dict, route_path: str, back: str) -> list[str]:
    out = ["", f"{route_path} {GM_GATE}", f'    + "Back" {back}']
    out += _gm_buttons(em, node, route_path)
    for seg, child in node["kids"].items():
        if child["kids"]:
            out += _gm_route(em, child, f"{route_path}/{_slug(seg)}", back=route_path)
    return out


def build_button_route(mission: Mission, em: Emitter, button_events: dict, *,
                       set_tag: str, header: str, handler_tag: str,
                       comment: str, addons: list) -> list[str]:
    """Emit a //comms-style route gathering 2.8 buttons (``set_tag`` declarations +
    ``handler_tag`` handler events) as `+ "label":` buttons with inline bodies."""
    declared = []
    for n in mission.all_nodes():
        if n.tag == set_tag:
            t = n.get("text", "")
            if t and t not in declared:
                declared.append(t)
    texts = list(dict.fromkeys(declared + list(button_events)))
    if not texts:
        return []

    for a in addons:
        em.addons.add(a)
    out = ["", comment, header]
    for t in texts:
        out.append(f'    + "{_mast_str(t)}":')
        out += _button_body(em, button_events.get(t), handler_tag)
    return out


def _xml_one(n) -> str:
    attrs = " ".join(f'{k}="{v}"' for k, v in n.attrib.items())
    return f"<{n.tag} {attrs}/>"


def build_script_py(mission: Mission) -> str:
    cls = _slug(mission.name).title().replace("_", "") + "StoryPage"
    return f'''try:
    import sbslibs
    from sbs_utils.handlerhooks import *
    from sbs_utils.gui import Gui
    from sbs_utils.mast.maststorypage import StoryPage
    from sbs_utils.mast.mast import Mast

    class {cls}(StoryPage):
        story_file = "story.mast"

    Mast.include_code = True

    Gui.server_start_page_class({cls})
    Gui.client_start_page_class({cls})
except Exception as e:
    message = e
    def cosmos_event_handler(sim, event):
        import sbs
        sbs.send_gui_clear(event.client_id, "")
        sbs.send_gui_text(event.client_id, "", "text",
                          f"$text:sbs_utils runtime error^{{message}};", 0, 0, 80, 95)
        sbs.send_gui_complete(event.client_id, "")
'''


def build_story_json(em: Emitter, lib_version: str = DEFAULT_LIB_VERSION) -> str:
    addons = list(dict.fromkeys(_BASELINE_ADDONS + sorted(em.addons)))
    sbslib = f"artemis-sbs.sbs_utils.{lib_version}.sbslib"
    fmt = "artemis-sbs.LegendaryMissions.{}." + lib_version + ".mastlib"
    mastlibs = ",\n".join(f'        "{fmt.format(a)}"' for a in addons)
    return ('{\n'
            f'    "sbslib": [\n        "{sbslib}"\n    ],\n'
            f'    "mastlib": [\n{mastlibs}\n    ]\n'
            '}\n')


def _yaml_scalar(s: str) -> str:
    """A YAML-safe scalar: plain when it can't confuse the parser, else a double-quoted
    scalar (so a colon/quote/`#` in a 2.8 description -- e.g. "one thing: TROUBLE!" --
    doesn't break parsing). Double quotes keep apostrophes literal (no `''` doubling)."""
    s = s.replace("\n", " ").strip()
    if s and not re.search(r"""[:#"'\[\]{}|>&*!%@`,]""", s) and s[0] not in "-?":
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_settings_yaml(em: Emitter) -> str:
    """The mission's ``settings.yaml`` -- only the keys the conversion needs flipped.

    ``settings_get_defaults()`` merges this file over the built-in defaults, so anything
    left out keeps its default. This is the right place for a setting an LM addon reads
    into a plain ``shared`` (rather than ``default shared``), where a story.mast assignment
    could be clobbered by load order.
    """
    out = ["# Settings this conversion needs. Merged over the Cosmos defaults by",
           "# settings_get_defaults(); everything not listed keeps its default value."]
    for k, v in sorted(em.settings.items()):
        out.append(f"{k}: {'true' if v is True else 'false' if v is False else v}")
    return "\n".join(out) + "\n"


def build_description_yaml(mission: Mission) -> str:
    # The six keys every Cosmos description.yaml is expected to carry (matches the
    # production missions: format version, Category, Category Priority, Visible Mission
    # Name, Description, Keywords).
    disp = _display_name(mission)
    # One short line, NOT the 2.8 <mission_description>: that can run to paragraphs, and
    # this field is a one-line blurb in the mission browser. The full 2.8 text is already
    # the map's briefing in story.mast, so nothing is lost by keeping this to a label.
    desc = f"A conversion of the Artemis 2.8 mission {disp}."
    # 2.8 has no keyword/category metadata; tag the port so it is findable in the list.
    return (f"format version: 1\n"
            f"Category: migrated 2.x\n"
            f"Category Priority: C\n"
            f"Visible Mission Name: {_yaml_scalar(disp)}\n"
            f"Description: {_yaml_scalar(desc)}\n"
            f"Keywords: 2.8 port\n")


def build_notes(mission: Mission, em: Emitter) -> str:
    lines = [f"# Migration notes: {_display_name(mission)}", "",
             f"Source: {mission.source_path}", "",
             "Generated by arme2cosmos. This is a scaffold -- the items below need a human.",
             ""]
    if mission.player_ship_names:
        lines.append(f"Player ship names (2.8): {', '.join(mission.player_ship_names)}")
        lines.append("")
    lines.append("## Punch-list")
    if em.notes:
        # de-dup while preserving order
        for msg in dict.fromkeys(em.notes):
            lines.append(f"- {msg}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Event model")
    model_desc = {
        "hybrid": "**hybrid** (default): flag-chained scene events form a linear chain; "
                  "independent events run as concurrent polling loops that re-fire each "
                  "tick, and single-trigger ones became event-driven routes instead of "
                  "polling. Multi-condition events stay loops on purpose.",
        "linear": "**linear**: every event folded into one sequential chain.",
        "a28_compatible": "**a28_compatible**: every event is its own continuous polling "
                          "task (the faithful 2.8 flat-event model -- no chain, no routes).",
    }.get(em.event_model, em.event_model)
    lines.append(f"- Model: {model_desc}")
    if em.event_summary:
        parts = [f"{v} {k}" for k, v in em.event_summary.items() if v]
        if parts:
            lines.append(f"- Translated as: {', '.join(parts)}.")
    lines.append("- Verify scene order matches the original 2.8 flag logic. Respawn "
                 "(`//damage/destroy`), dock (`//signal/ship_docked`) and flag "
                 "(`//signal/a2x_flag_*`) routes fire on engine events -- confirm they "
                 "trigger as intended.")
    lines.append("- If event behaviour looks wrong, regenerate with "
                 "`--event-model a28_compatible` (faithful fallback) or `--event-model linear`.")
    lines.append("")
    lines.append("## Reminders")
    lines.append("- Headings from 2.8 `angle` are not yet applied (a2x_angle exists if needed).")
    lines.append("- Ship art uses the hull crosswalk (artmap); unmatched hulls use a placeholder.")
    return "\n".join(lines) + "\n"


def convert_file(path: str, out_root: str, lib_version: str = DEFAULT_LIB_VERSION,
                 hullmap: dict | None = None, event_model: str = "hybrid",
                 target: str = "amd") -> str:
    """Convert one mission XML; write a scaffold dir under out_root. Returns the dir.

    ``target='amd'`` (default) emits an AMD quest tree (story.amd) plus a thin
    story.mast -- see ``docs/amd_target.md``. ``target='mast'`` emits the MAST-only
    scaffold controlled by ``event_model`` instead.
    """
    mission = parse_file(path)
    em = Emitter(mission, hullmap=hullmap)
    _prescan_references(mission, em)  # names used later -> keep those monsters capturable

    if target == "amd":
        from .amd_emit import build_amd_target
        files = build_amd_target(mission, em, lib_version)
    else:
        story = build_story_mast(mission, em, event_model)  # populates em.addons/notes
        files = {
            "story.mast": story,
            "script.py": build_script_py(mission),
            "story.json": build_story_json(em, lib_version),
            "description.yaml": build_description_yaml(mission),
            "MIGRATION_NOTES.md": build_notes(mission, em),
            "__lib__.json": '{"version": "' + lib_version + '"}\n',
        }
        if em.scans:  # recovered 2.8 scan_desc as declarative science scans
            from .amd_emit import _build_scans_amd
            files["scans.amd"] = _build_scans_amd(em.scans)

    # Only written when the conversion actually needs a setting flipped -- an empty
    # settings.yaml would shadow nothing but is one more file to explain.
    if em.settings:
        files["settings.yaml"] = build_settings_yaml(em)

    out_dir = os.path.join(out_root, _slug(mission.name))
    os.makedirs(out_dir, exist_ok=True)
    for fname, content in files.items():
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
            f.write(content)
    return out_dir
