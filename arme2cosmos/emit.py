"""Emit Cosmos MAST (and scaffolding) from a parsed 2.8 mission.

Scaffold-with-TODOs philosophy: the create-family commands translate to real
``a2x_*`` calls (positions pass through verbatim -- ``a2x`` flips coordinates
internally); everything not mechanically translatable is emitted as a
``# TODO`` line with the original XML preserved, and collected into
``MIGRATION_NOTES.md``. Events become a linear chain of ``---`` labels.
"""

from __future__ import annotations

import re
import unicodedata

from .coverage import classify, FULL, PARTIAL
from .model import Event, Mission, XmlNode

# 2.8 sideValue -> the Cosmos side KEY (mirror of a2x.sides.side_key -- keep in step).
# One key per sideValue, never collapsed onto the three LegendaryMissions keys: 2.8's
# sideValue is a faction index, not a 3-valued enum, and its implicit rule is "different
# non-zero value => hostile". MISS_The_Arena puts eight player ships on sideValues 4..11
# (each with its own station); collapsing those would make all eight teams allies.
# a2x_declare_sides (emitted into //shared/signal/create_sides) declares the relations.
_SIDE = {"0": "neutral", "1": "enemy", "2": "friendly"}

# Combat-scope role for hostiles. NOT what makes a ship an enemy -- diplomacy does that.
# LegendaryMissions intersects this role with diplomacy for "is there an enemy" tests,
# e.g. the docking addon's enemies-near gate:
#     side_hostile_members(DOCKING_PLAYER_ID, "raider")
# so without the tag that set is always empty and the gate silently never fires.
_RAIDER_ROLE = "raider"

# The 2.8 sideValue the player is on when a mission never creates a player ship (2.8's
# convention: sideValue 2 is the player/TSN side, which its friendly stations share).
_DEFAULT_PLAYER_SIDE = 2


def _side_key(value) -> str:
    """2.8 sideValue -> Cosmos side key. Mirror of ``a2x.sides.side_key``."""
    s = str(value).strip()
    if s in _SIDE:
        return _SIDE[s]
    try:
        return f"side_{int(float(s))}"
    except (TypeError, ValueError):
        return "enemy"

# 2.8 add_ai block types that a2x_add_ai maps to a real brain (mirror of a2x.ai).
# Others emit the call but a2x_add_ai is a no-op for them -> flagged in notes.
_AI_MAPPED = {"CHASE_PLAYER", "CHASE_STATION", "CHASE_AI_SHIP", "CHASE_NEUTRAL",
              "ATTACK", "TARGET_THROTTLE", "CHASE_FLEET", "CHASE_ANGER",
              "PROCEED_TO_EXIT"}

# add_ai types that attach a real movement/targeting brain -- the ones that genuinely
# REPLACE 2.8's implicit default enemy stack. Anything else (role grants like
# FOLLOW_COMMS_ORDERS, the dropped leader blocks, unmapped types that emit only a TODO)
# leaves the ship with no way to move, so such a ship must KEEP the default stack.
# Getting this wrong is silent: the ship spawns, is re-brained on paper, and sits still.
_AI_OVERRIDES_DEFAULT = _AI_MAPPED | {"DIR_THROTTLE", "POINT_THROTTLE"}

# 2.8 AI blocks Cosmos handles structurally differently (or not at all) -> drop cleanly
# rather than leave a TODO. Value is the reason emitted as a one-line comment.
_AI_DROP = {
    "TRY_TO_BECOME_LEADER": "Cosmos fleets need no leader",
    "LEADER_LEADS": "Cosmos fleets need no leader",
    "FOLLOW_LEADER": "Cosmos fleets need no leader",
    "SPCL_AI": "LM fleets addon drives elite abilities (set via set_special)",
    "ELITE_AI": "LM fleets addon drives elite abilities (set via set_special)",
    "CHASE_WHALE": "no whale in Cosmos",
}

# 2.8 set_object_property names with a confirmed Cosmos mapping (mirror of a2x.props).
# These emit a real a2x_set_object_property call; the rest stay # TODO. See
# docs/property_map.md for the full table and the VERIFY/HUMAN rows.
# 2.8 set_special abilities that map to a Cosmos LM elite ability (mirror of a2x.props).
_ELITE_ABILITIES = {"Stealth", "LowVis", "Drones", "AntiMine", "AntiTorp",
                    "Cloak", "HET", "Warp", "Teleport", "TeleBack", "Tractor",
                    "ShldDrain", "ShldVamp", "ShldReset"}

# 2.8 global difficulty props (no object) -> fleet coefficients (mirror of a2x.props).
_FLEET_COEFF = {"nonPlayerSpeed", "nonPlayerShield", "nonPlayerWeapon",
                "playerShields", "playerWeapon"}

# 2.8's 8 named engineering systems (a2x collapses these 8 -> Cosmos's 4 SHPSYS slots).
_SHPSYS_NAMES = ("Beam", "Torpedo", "Turning", "Impulse", "Warp", "Tactical",
                 "FrontShield", "BackShield")

_AUTO_PROPS = {
    "surrenderChance", "tauntImmunityIndex",
    *(f"systemCurHeat{s}" for s in _SHPSYS_NAMES),
    *(f"systemDamage{s}" for s in _SHPSYS_NAMES),
    *(f"systemCurEnergy{s}" for s in _SHPSYS_NAMES),
    "positionX", "positionY", "positionZ",
    "topSpeed", "currentRealSpeed",
    "angle",  # absolute facing (yaw); a2x maps 2.8 radians -> Cosmos rot_quat (pi - angle)
    "roll",   # roll about the forward axis (radians); composed onto rot_quat
    "pitch",  # pitch about the right axis (radians; >pi treated as degrees)
    "angleDelta", "rollDelta", "pitchDelta", "turnRate", "throttle", "artScale",
    "energy", "hasSurrendered", "shieldsOn",
    "shieldState",  # station single shield -> shield_val[0]
    "shieldStateFront", "shieldStateBack",
    "shieldMaxStateFront", "shieldMaxStateBack", "missileStoresNuke",
    "missileStoresHoming", "missileStoresMine", "missileStoresEMP", "countNuke",
    "countHoming", "countMine", "countEMP",
    "missileStoresPShock", "missileStoresTag", "missileStoresECM", "countShk",
    "missileStoresBeacon", "countBea",
    "missileStoresProbe", "countProbe",  # 2.8 Probe -> Sensor Beacon (set count / add to cargo)
    "pushRadius",
    # pirate docking reputation (LM docking reads a2x_pirate_rep for "pirate"-role players)
    "pirateRepWithStations", "pirateRepWithStation",
    "age",             # kept on inventory (a2x_age) for science flavor
    "nebulaIsOpaque",  # -> nebula max_throttle (opaque slows ships, 0 = no limit)
    "sensorSetting",   # -> ship_base_scan_range (0 = unlimited; N = 100/(3N) km)
    "warpState",       # really the throttle: 0-4 -> throttle 1-5
    "canBuild",        # -> a2x_can_build inventory (LM build console reads it)
}

# 2.8 properties documented as non-functional even in Artemis 2.8 -> a faithful port is a
# no-op. Drop cleanly (a comment, not a TODO): wiring them would add behaviour 2.8 lacked.
_PROP_NOOP = {
    "blocksShotFlag": "documented non-functional in Artemis 2.8",
}

# 2.8 properties that HAVE meaning but no Cosmos equivalent yet -- mapping them would need
# an engine/library change, not mission work. Emit a clear stub comment (NOT a TODO) so a
# port is not blocked on them; the note explains what a real fix would require.
_PROP_ENGINE_STUB = {
    # Cosmos exposes no music master-volume control (set_music_folder/file/tension only, no
    # volume). 2.8 missions use this only to mute (value 0). Needs an engine music-volume API.
    "musicObjectMasterVolume": "no Cosmos music master-volume API -- needs an engine change "
                               "(2.8 uses it to fade/mute music, 0.0-1.0)",
    # 2.8 triggersMines=0 -> the object is not damaged by mines. Cosmos mine triggering
    # (_is_damageable) and blast damage are engine-side; a //damage route only reacts after
    # the hit, so there is no clean per-object mine-immunity hook. Needs an engine feature.
    "triggersMines": "no Cosmos per-object mine-immunity -- needs an engine change "
                     "(2.8 triggersMines=0 = not damaged by mines)",
    # 2.8 deltaX/Y/Z = an object's per-axis velocity (drift). Cosmos exposes only cur_speed
    # (a scalar along the heading), no free velocity vector, so a per-axis drift has no clean
    # mapping -- needs an engine velocity-vector setter.
    "deltaX": "no Cosmos free-velocity vector -- needs an engine change (2.8 deltaX = X drift rate)",
    "deltaY": "no Cosmos free-velocity vector -- needs an engine change (2.8 deltaY = Y drift rate)",
    "deltaZ": "no Cosmos free-velocity vector -- needs an engine change (2.8 deltaZ = Z drift rate)",
}

# Tiny starter hull/art crosswalk. The real table is the tool's `artmap`
# (vesselData.xml <-> shipDataBB.json); these are sensible placeholders so output
# runs, each flagged in MIGRATION_NOTES.
# 2.8 set_player_grid_damage systemType -> Cosmos sbs.SHPSYS (4 systems).
_GRID_SYS = {
    "systemBeam": "WEAPONS", "systemTorpedo": "WEAPONS", "systemTactical": "WEAPONS",
    "systemTurning": "ENGINES", "systemImpulse": "ENGINES", "systemWarp": "ENGINES",
    "systemFrontShield": "SHIELDS", "systemBackShield": "SHIELDS",
}

# 2.8 monsterType -> an LM monster prefab (spawned via prefab_spawn). Only the confident
# ones; classic(0)/tube(5)/jelly(7)/derelict(8) stay on the a2x_create_monster placeholder.
# whale->grazer (Cosmos has no space whale; the LM grazer is its placid stand-in).
_MONSTER_PREFAB = {1: "grazer", 2: "shark", 3: "dragon", 4: "piranha", 6: "insect"}

_STATION_ART = "starbase_command"
_ENEMY_ART = "kralien_cruiser"
_NEUTRAL_ART = "transport"
_PLAYER_ART = "tsn_light_cruiser"

# 2.8 player_slot -> the ship that slot has always been, matching LegendaryMissions'
# PLAYER_LIST. A 2.8 <create type="player"> is usually unnamed because the slot already
# implies the ship, so naming by slot (rather than calling every unnamed create
# "Artemis") keeps slots distinct and lets convert fill the ones the mission omitted.
_PLAYER_SLOT_NAMES = ["Artemis", "Intrepid", "Aegis", "Horatio",
                      "Excalibur", "Hera", "Ceres", "Diana"]


def player_slot_name(slot):
    """The default ship name for a 2.8 ``player_slot`` (slot 0 -> Artemis)."""
    try:
        return _PLAYER_SLOT_NAMES[int(float(slot))]
    except (TypeError, ValueError, IndexError):
        return _PLAYER_SLOT_NAMES[0]
_MONSTER_ART = "monster_charbdis"


class Emitter:
    def __init__(self, mission: Mission, hullmap: dict | None = None):
        self.mission = mission
        self.hullmap = hullmap  # optional vesselData<->shipDataBB crosswalk
        self.notes: list[str] = []  # punch-list lines for MIGRATION_NOTES.md
        self.addons: set[str] = set()  # feature-detected story.json mastlibs
        self.symbols: dict[str, str] = {}  # 2.8 object name -> MAST variable
        self.player_var: str | None = None  # MAST var holding the player ship
        # whether the create:player line has been EMITTED yet. Before it, the variable
        # is still the forward-declared None, so references resolve at runtime instead.
        self.player_emitted = False
        # every 2.8 sideValue the mission touches (creates + runtime set_side_value), so
        # the emitted a2x_declare_sides covers each one; 2.8 declares no sides at all, and
        # an undeclared side means side_are_enemies is False and NPC brains never fire.
        self.side_values: set[int] = set()
        # the sideValue the player ships are on (from create type="player"); friendly
        # objects share it, so it must not be hardcoded -- a player on a different side
        # from its own station reads as hostile once diplomacy is declared.
        self.player_side: int | None = None
        # 2.8 object names that get an explicit <add_ai> override (populated by prescan).
        # Everything else that spawns as an enemy needs 2.8's implicit default brain.
        self.explicit_ai_names: set[str] = set()
        # flags consumed by a //signal-converted event: set_variable on these also
        # emits the signal that drives the route (set by build_story_mast).
        self.signal_flags: set[str] = set()
        # how events were translated (set by build_story_mast, used by build_notes).
        self.event_summary: dict[str, int] = {}
        self.event_model: str = "hybrid"
        # AMD reveal graph: (flag_name, numeric-value-key) pairs whose set_variable should
        # also emit a phase signal (populated by the AMD target's reveal-graph pass).
        self.phase_signals: set[tuple[str, str]] = set()
        # 2.8 set_ship_text scan_desc recovered as declarative science scans: object name
        # -> scan text (the AMD target emits these as amd_science + tags a scan_<name> role).
        self.scans: dict[str, str] = {}
        self.emit_scan_roles = False  # AMD target: tag scanned objects with their scan role
        self.scan_roles_done: set[str] = set()  # objects already given their scan_ role tag
        # 2.8 set_ship_text hailtext recovered as a Hail comms button: object name -> hail
        # text (the AMD target stores it as an inventory value + a gated //comms Hail route).
        self.hails: dict[str, str] = {}
        self.hail_done: set[str] = set()  # objects already given their stored hail value
        self.wait_prop_n = 0  # unique-label counter for chained-scene poll waits
        # Timer names any set_timer in the mission actually starts. A condition naming a
        # timer NOTHING sets can never fire in 2.8, so waiting on it would hang the chain.
        self.timers_set: set[str] = set()
        # True only while the <start> roster is being emitted into
        # //shared/signal/create_player_ships. Everywhere else a `create
        # type="player"` PLACES an existing ship (2.8 has 8 fixed slots), so
        # c_player emits a2x_place_player instead of spawning a 9th hull.
        self.player_spawn_phase = False
        # What a chained scene's if_variable becomes: id(condition node) -> "skip" | "wait".
        # Decided by convert.plan_chain_flag_gates, which can see the chain ORDER and who
        # sets each flag; an absent entry means it stays a comment.
        self.chain_flag_gate: dict[int, str] = {}
        # 2.8 object names referenced by a later command/condition (not the create) -- a
        # monster with a referenced name needs the capturable path, not a prefab_spawn.
        self.referenced_names: set[str] = set()
        # Cosmos SETTINGS the conversion needs turned on (written to settings.yaml, which
        # settings_get_defaults merges over the built-ins). Only written when non-empty.
        self.settings: dict[str, object] = {}

    def _art(self, n: XmlNode, default: str) -> str:
        """Resolve a Cosmos art key from the hullmap (2.8 hullID/raceKeys/hullKeys),
        falling back to *default* (a placeholder) when there is no match."""
        from .artmap import resolve_art
        key = resolve_art(self.hullmap, hull_id=n.get("hullID"),
                          race_keys=n.get("raceKeys"), hull_keys=n.get("hullKeys"))
        return key or default

    # -- helpers --------------------------------------------------------------
    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def _var_for(self, name: str) -> str:
        """A stable MAST variable for a 2.8 object name (creates one if needed)."""
        if name in self.symbols:
            return self.symbols[name]
        base = "obj_" + _pyname(name).lower()
        var, i, used = base, 1, set(self.symbols.values())
        while var in used:
            i += 1
            var = f"{base}_{i}"
        self.symbols[name] = var
        return var

    def _assign(self, n: XmlNode, expr: str) -> str:
        """Indented line; captures the spawn into a `shared` variable when the object is
        named (shared so concurrent independent-event tasks can resolve it too)."""
        name = n.get("name")
        if name:
            return f"    shared {self._var_for(name)} = {expr}"
        return f"    {expr}"

    def _xyz(self, n: XmlNode, px="x", py="y", pz="z"):
        return (n.get(px, "0"), n.get(py, "0"), n.get(pz, "0"))

    def _player_ref(self, n: XmlNode | None = None, slot=None) -> str | None:
        """The MAST expression for "the player ship" AT THIS POINT in the emission.

        `shared player_ship` is only assigned where the 2.8 `create type="player"` is
        emitted, but 2.8 lets a command reference the player BEFORE that create -- e.g.
        MISS_Cruiser_Tournament puts `set_player_carried_type` above it. Reading the
        variable there gets the forward-declared None, which reaches the LM hangar as a
        missing ship (`to_space_object(None)` -> `so.origin` crashes). So until the
        create has been emitted, resolve the ship at RUNTIME by its 2.8 slot instead.
        """
        if self.player_var is None:
            return None
        if self.player_emitted:
            return self.player_var
        if slot is None and n is not None:
            slot = n.get("player_slot")
        return f"a2x_player_ship({_value(slot)})" if slot is not None else "a2x_player_ship(0)"

    def _note_side(self, value) -> str:
        """Record a 2.8 sideValue as one this mission uses, and return its Cosmos key.
        Every value that reaches here ends up in the emitted a2x_declare_sides call."""
        try:
            self.side_values.add(int(float(str(value).strip())))
        except (TypeError, ValueError):
            pass  # a non-literal (variable) sideValue -- can't declare it statically
        return _side_key(value)

    def _side(self, n: XmlNode, default: int = 1) -> str:
        """The Cosmos side key for a create node, recording the sideValue for declaration.

        ``default`` is the 2.8 sideValue to assume when the node omits one -- per create
        type, matching the a2x create_* defaults (station 2/friendly, enemy 1, neutral 0).
        It is recorded like an explicit value: once diplomacy is declared the fallback is
        a real allegiance, not just an inert role name as it was before."""
        raw = (n.get("sideValue") or "").strip()
        return self._note_side(raw if raw else default)

    def _is_player_side(self, n: XmlNode) -> bool:
        """Whether this node's sideValue is the player's (so it must NOT be raider-tagged)."""
        raw = (n.get("sideValue") or "").strip()
        if not raw:
            return False
        ps = self.player_side if self.player_side is not None else _DEFAULT_PLAYER_SIDE
        try:
            return int(float(raw)) == ps
        except (TypeError, ValueError):
            return False

    def _name_kw(self, n: XmlNode) -> str:
        nm = n.get("name")
        return f', name="{_mast_str(nm)}"' if nm else ""

    # -- command emitters -----------------------------------------------------
    def emit_command(self, n: XmlNode) -> list[str]:
        kind = n.kind_key()
        fn = _COMMAND_EMIT.get(kind)
        if fn is None:
            cov = classify(kind)
            self.note(f"[{cov.status}] {kind}: {cov.note}")
            return [f"    # TODO [{cov.status}] {kind}: {cov.note}",
                    f"    #   {_xml_repr(n)}"]
        return fn(self, n)

    def c_station(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        art = self._art(n, _STATION_ART)
        if art == _STATION_ART:
            self.note(f"verify station art for {n.get('name','?')} "
                      f"(hullID={n.get('hullID')} race={n.get('raceKeys')})")
        return [self._assign(n, f'a2x_create_station({x}, {y}, {z}, "{art}", '
                f'side="{self._side(n, _DEFAULT_PLAYER_SIDE)}"{self._name_kw(n)})')]

    def c_enemy(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        # The first token is the side KEY (identity + diplomacy); the rest become plain
        # roles -- spawn_common splits on commas and adds every entry as a role.
        parts = [self._side(n)]
        if not self._is_player_side(n):
            parts.append(_RAIDER_ROLE)  # combat scope for LM's hostile-set queries
        fleet = n.get("fleetnumber")
        if fleet:
            parts.append(f"fleet_{fleet}")  # role so if_fleet_count can await it
        side = ", ".join(parts)
        art = self._art(n, _ENEMY_ART)
        if art == _ENEMY_ART:
            self.note(f"verify enemy art for {n.get('name','?')} "
                      f"(hullID={n.get('hullID')} race={n.get('raceKeys')})")
        expr = (f'a2x_create_enemy({x}, {y}, {z}, "{art}", '
                f'side="{side}"{self._name_kw(n)})')
        # 2.8 enemies get their brain stack from the ENGINE -- a mission writes <add_ai>
        # only to OVERRIDE it. Nothing carried that over, so a converted enemy spawned
        # with no brain and just sat there. Give 2.8's default to every enemy the mission
        # does not explicitly re-brain (a ship with its own add_ai keeps only that, so the
        # two brain stacks can't fight each other).
        name = n.get("name")
        if name in self.explicit_ai_names:
            return [self._assign(n, expr)]
        self.addons.add("ai")   # the default brain's labels live in the LM ai addon
        if name:
            var = self._var_for(name)
            return [f"    shared {var} = {expr}", f"    a2x_default_enemy_ai({var})"]
        # unnamed: no variable to hold it, so brain the id the spawn returns
        return [f"    a2x_default_enemy_ai({expr})"]

    def c_neutral(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        art = self._art(n, _NEUTRAL_ART)
        return [self._assign(n, f'a2x_create_neutral({x}, {y}, {z}, "{art}", '
                f'side="{self._side(n, 0)}"{self._name_kw(n)})')]

    def c_player(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        self.addons.update({"consoles", "fleets"})
        nm = _mast_str(n.get("name") or player_slot_name(n.get("player_slot", 0)))
        if not self.player_spawn_phase:
            # NOT the <start> roster: 2.8 has exactly 8 player slots and the crew is
            # already flying one, so this command PLACES a ship rather than making a 9th.
            # Spawning here gave the mission a second, unmanned hull -- and where the only
            # player create is in an event (MISS_Medusa's_Maze rolls one of eight maze
            # entrances) it also meant no ship existed at ship-select time.
            slot = n.get("player_slot", 0)
            side = self._side(n, _DEFAULT_PLAYER_SIDE)
            args = [f"{x}, {y}, {z}", f"slot={slot}", f'name="{nm}"', f'side="{side}"']
            return [f'    a2x_place_player({", ".join(args)})']
        self.note("player ship: a2x_create_player is a scaffold; prefer the consoles/"
                  "fleets addon (PLAYER_LIST + spawn_players) for real console wiring")
        self.player_var = "player_ship"
        if n.get("name"):
            self._var_for(n.get("name"))  # also resolvable by name
            self.symbols[n.get("name")] = "player_ship"
        # The player's side comes from its own sideValue, never a2x_create_player's "tsn"
        # default: friendly stations carry the same 2.8 sideValue, and once diplomacy is
        # declared a player on a different side from its own station reads as hostile.
        side = self._side(n, _DEFAULT_PLAYER_SIDE)
        # From here on `player_ship` holds a real id, so later references can use the
        # variable; anything emitted ABOVE this line resolved the slot at runtime.
        self.player_emitted = True
        return [f'    shared player_ship = a2x_create_player({x}, {y}, {z}, "{_PLAYER_ART}", '
                f'name="{nm}", side="{side}")']

    def c_generic(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        art = self._art(n, _NEUTRAL_ART)  # raw .dxs mesh has no Cosmos art -> placeholder
        self.note(f"genericMesh '{n.get('name','?')}': 2.8 raw mesh "
                  f"({n.get('meshFileName','?')}) has no Cosmos equivalent -- placeholder art")
        side = self._side(n) if n.get("sideValue") else "generic"
        return [self._assign(n, f'a2x_create_generic({x}, {y}, {z}, "{art}", '
                f'side="{side}"{self._name_kw(n)})')]

    def c_monster(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        mt = n.get("monsterType", "0")
        name = n.get("name")
        prefab = _MONSTER_PREFAB.get(int(mt)) if (mt or "").strip().lstrip("-").isdigit() else None
        # A real LM monster prototype (with its own brain + age) when the type maps to one
        # AND the object isn't referenced later -- prefab_spawn returns a task, not a
        # capturable object id, so referenced monsters keep the capturable placeholder path.
        if prefab and (not name or name not in self.referenced_names):
            self.addons.add("prefabs")
            nm = f', "NAME": "{_mast_str(name)}"' if name else ""
            return [f'    prefab_spawn(prefab_{prefab}, {{"START_X": a2x_pos({x}, {y}, {z}).x, '
                    f'"START_Y": a2x_pos({x}, {y}, {z}).y, '
                    f'"START_Z": a2x_pos({x}, {y}, {z}).z{nm}}})']
        self.note(f"monster type {mt}: placeholder art + creature_ role (no LM prefab for "
                  f"this type, or the object is referenced later so it needs the capturable path)")
        return [self._assign(n, f'a2x_create_monster({x}, {y}, {z}, '
                f'monster_type={mt}{self._name_kw(n)})')]

    def c_anomaly(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        self.addons.add("upgrades")
        pt = n.get("pickupType", "0")
        # capture named anomalies so later destroy/property commands resolve them
        return [self._assign(n, f"a2x_create_anomaly({x}, {y}, {z}, {pt})")]

    def c_black_hole(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        # The LM collisions addon carries the black-hole lethal-proximity watcher: the
        # engine's own maelstrom collision does not reliably fire, so without it a ship
        # can sit in the well (or warp free) and SURVIVE a black hole.
        self.addons.add("collisions")
        return [self._assign(n, f"a2x_create_black_hole({x}, {y}, {z})")]

    def c_terrain(self, n: XmlNode) -> list[str]:
        # create type=nebulas/asteroids/mines -> a2x bulk terrain
        kind = n.get("type")
        count = n.get("count", "0")
        sx, sy, sz = self._xyz(n, "startX", "startY", "startZ")
        start = f"({sx}, {sy}, {sz})"
        end = ""
        if n.get("endX") is not None:
            ex, ey, ez = self._xyz(n, "endX", "endY", "endZ")
            end = f", end=({ex}, {ey}, {ez})"
        radius = f", radius={n.get('radius')}" if n.get("radius") else ""
        rng = f", random_range={n.get('randomRange')}" if n.get("randomRange") else ""
        seed = f", seed={n.get('randomSeed')}" if n.get("randomSeed") else ""
        fnmap = {"nebulas": "a2x_create_nebulas", "asteroids": "a2x_create_asteroids",
                 "mines": "a2x_create_mines"}
        fn = fnmap.get(kind)
        if fn is None:
            return [f"    # TODO create type={kind}: {_xml_repr(n)}"]
        nt = f", neb_type={n.get('nebType')}" if (kind == "nebulas" and n.get("nebType")) else ""
        if kind in ("asteroids", "mines"):
            # Impact damage (shields -> hull -> grid internal damage) and asteroid
            # destruction live in the LM collisions addon; without it flying into a
            # 2.8 mine/asteroid field is harmless. Nebulas are pass-through, so they
            # do not need it.
            self.addons.add("collisions")
        return [f"    {fn}({count}, {start}{end}{radius}{rng}{seed}{nt})"]

    def c_set_variable(self, n: XmlNode) -> list[str]:
        # shared so concurrent independent-event tasks can read the flag
        raw = n.get("name")
        name = _pyname(raw)
        out = [f"    shared {name} = {_set_variable_value(n)}"]
        # if a //signal route listens on this flag, fire the signal too (push)
        if name in self.signal_flags:
            out.append(f'    signal_emit("a2x_flag_{name}")')
        # AMD reveal graph: when this set reaches a tracked phase value, fire its phase
        # signal so the phase route can reveal + start the quests gated on that phase.
        vkey = _num_key(n.get("value"))
        if vkey is not None and (raw, vkey) in self.phase_signals:
            out.append(f'    signal_emit("{_phase_sig_name(raw, vkey)}")')
        return out

    def c_set_timer(self, n: XmlNode) -> list[str]:
        return [f'    set_timer(0, "{n.get("name")}", seconds={n.get("seconds", "0")})']

    def c_set_difficulty(self, n: XmlNode) -> list[str]:
        return [f'    DIFFICULTY = {n.get("value", "5")}']

    def c_big_message(self, n: XmlNode) -> list[str]:
        t = _mast_str(n.get("title", ""))
        s1 = _mast_str(n.get("subtitle1", ""))
        s2 = _mast_str(n.get("subtitle2", ""))
        return [f'    a2x_big_message("{t}", "{s1}", "{s2}")']

    def c_comms_text(self, n: XmlNode) -> list[str]:
        self.addons.add("comms")
        frm = _mast_str(n.get("from", ""))
        body = _mast_str(n.text or "")  # ^ line-breaks preserved; a2x_clean converts them
        # 2.8 `from` is just the sender label (the comms title), not an object reference.
        return [f'    a2x_incoming_comms_text("{body}", from_name="{frm}")']

    def _gm_selected(self, n: XmlNode) -> str | None:
        """The GM's selected object, for a 2.8 command carrying ``use_gm_selection``.

        2.8 GM-button commands act on whatever the Game Master has selected. The converter
        turns 2.8 GM buttons into a gamemaster-gated ``//comms`` tree
        (``build_gm_tree_routes``), and inside that button body ``COMMS_SELECTED_ID`` IS the
        GM's current comms selection -- so that is the faithful target. Returns the MAST
        expression, or ``None`` if the command is not GM-selection-based.
        """
        if n.get("use_gm_selection") is not None:
            self.addons.update({"gamemaster", "gamemaster_comms"})
            return "COMMS_SELECTED_ID"
        return None

    def c_add_ai(self, n: XmlNode) -> list[str]:
        name = n.get("name")
        typ = (n.get("type") or "").upper()
        if typ in _AI_DROP:
            return [f'    # add_ai {typ}: dropped -- {_AI_DROP[typ]}']
        var = self.symbols.get(name) or self._gm_selected(n)
        if var is None:
            self.note(f"add_ai {typ} references object '{name}' not captured here "
                      f"(forward ref or gm-selected) -- wire by hand")
            return [f'    # TODO add_ai {typ} on "{name}"']
        # POINT_THROTTLE: fly to a point at a throttle. value1/2/3 = the 2.8 point (needs the
        # coordinate flip), value4 = throttle. target_pos sets the target and the engine steers
        # the NPC there (no brain needed) -- same as the `direct` command.
        if typ == "POINT_THROTTLE":
            v1, v2, v3 = n.get("value1", "0"), n.get("value2", "0"), n.get("value3", "0")
            return [f'    target_pos({var}, *a2x_pos({v1}, {v2}, {v3}), {n.get("value4", "1")})']
        # DIR_THROTTLE: fly a compass heading (value1) at a throttle (value2) -> a2x computes a
        # far point along the heading and drives there via the goto_object_or_location brain.
        if typ == "DIR_THROTTLE":
            return [f'    a2x_dir_throttle({var}, {n.get("value1", "0")}, {n.get("value2", "1")})']
        # FOLLOW_COMMS_ORDERS: make the ship player-orderable in Cosmos (LM
        # comms/friendly_give_orders). civ+friendly gives the give-orders comms + Hail; the
        # actual "Have <ship> go here / attack that" ORDERS POPUP is gated on the
        # prefab_npc_defender role + a give_orders_type (the same idiom the "take as prize"
        # flow uses). Grant all so the popup appears -- the 2.8 intent (accepts player orders).
        if typ == "FOLLOW_COMMS_ORDERS":
            self.addons.add("comms")
            return [f'    add_role({var}, "civ")',
                    f'    add_role({var}, "friendly")',
                    f'    add_role({var}, "prefab_npc_defender")',
                    f'    set_inventory_value({var}, "give_orders_type", "objective/orders/defender")']
        # DEFEND: protect its area -> the LM defender setup (prefab_npc_defender role + the
        # protect-area objective, LM prefabs/defender.mast).
        if typ == "DEFEND":
            self.addons.add("prefabs")
            return [f'    add_role({var}, "prefab_npc_defender")',
                    f'    objective_add({var}, objective_protect_area)']
        self.addons.add("ai")
        if typ not in _AI_MAPPED:
            self.note(f"add_ai {typ} on '{name}': no Cosmos brain mapping yet "
                      f"(a2x_add_ai is a no-op for it) -- choose/author a brain")
        return [f'    a2x_add_ai({var}, "{typ}")']

    def c_clear_ai(self, n: XmlNode) -> list[str]:
        var = self.symbols.get(n.get("name")) or self._gm_selected(n)
        if var is None:
            return [f'    # TODO clear_ai on "{n.get("name")}" (object not captured)']
        return [f"    a2x_clear_ai({var})"]

    def c_destroy(self, n: XmlNode) -> list[str]:
        var = self.symbols.get(n.get("name"))
        if var is not None:
            return [f"    a2x_destroy({var})"]
        var = self._gm_selected(n)
        if var is not None:
            # "Delete selected" acts on whatever the GM has highlighted -- including, if
            # they are careless, the gamemaster's own ship, which takes the console that
            # issued the command with it. 2.8 had the same hazard; nothing is lost by
            # refusing. The role is the one the //comms tree already gates on.
            return [f'    if not has_roles({var}, "gamemaster"):',
                    f"        a2x_destroy({var})"]
        name = n.get("name")
        if name:
            # no create the tool saw (dynamically created, or a dead reference in the 2.8
            # mission) -> destroy by name at runtime; a no-op if the object never existed.
            return [f'    a2x_destroy_named("{_mast_str(name)}")']
        return [f"    # TODO destroy: {_xml_repr(n)}"]

    def c_destroy_near(self, n: XmlNode) -> list[str]:
        kind = n.get("type", "all")
        if n.get("name"):
            # centered on a named object -> use its RUNTIME position if it is captured
            var = self.symbols.get(n.get("name"))
            if var is not None:
                return [f'    a2x_destroy_near_object({var}, {n.get("radius", "0")}, "{kind}")']
            return [f"    # TODO destroy_near near \"{n.get('name')}\": {_xml_repr(n)}"]
        cx, cy, cz = self._xyz(n, "centerX", "centerY", "centerZ")
        return [f'    a2x_destroy_near({cx}, {cy}, {cz}, {n.get("radius", "0")}, "{kind}")']

    def c_set_side_value(self, n: XmlNode) -> list[str]:
        obj = self.symbols.get(n.get("name"))
        if obj is None and n.get("player_slot") is not None:
            obj = self._player_ref(n)
        if obj is None:
            obj = self._gm_selected(n)
        if obj is None:
            return [f"    # TODO set_side_value: {_xml_repr(n)}"]
        # a mid-mission defection: declare the destination side too, or the ship lands on
        # a side with no diplomacy and silently stops being anyone's enemy.
        self._note_side(n.get("value", "0"))
        return [f'    a2x_set_side_value({obj}, {_value(n.get("value", "0"))})']

    def c_direct(self, n: XmlNode) -> list[str]:
        var = self.symbols.get(n.get("name")) or self._gm_selected(n)
        if var is None:
            return [f'    # TODO direct "{n.get("name")}" (object not captured)']
        thr = n.get("scriptThrottle", "1.0")
        tname = n.get("targetName")
        if tname:
            tvar = self.symbols.get(tname)
            if tvar:
                return [f"    target({var}, to_id({tvar}), throttle={thr})"]
            return [f'    # TODO direct {var} toward "{tname}" (target not captured)']
        px, py, pz = n.get("pointX", "0"), n.get("pointY", "0"), n.get("pointZ", "0")
        return [f"    target_pos({var}, *a2x_pos({px}, {py}, {pz}), {thr})"]

    def c_set_object_property(self, n: XmlNode) -> list[str]:
        var = self.symbols.get(n.get("name"))
        # player_slot props (energy / count* / shieldState ... on the player) -> the player ship
        if var is None and n.get("player_slot") is not None:
            var = self._player_ref(n)
        if var is None:
            var = self._gm_selected(n)  # use_gm_selection -> the GM's comms selection
        prop, val = n.get("property", "?"), n.get("value", "0")
        # global difficulty knobs (no object name): nonPlayer*/player* -> fleet coeffs
        if n.get("name") is None and prop in _FLEET_COEFF:
            return [f'    a2x_set_fleet_coeff("{prop}", {_value(val)})']
        # nameless nebulaIsOpaque -> global: set every nebula's throttle limit
        # (non-zero = opaque = slows ships; 0 = no limit)
        if n.get("name") is None and prop == "nebulaIsOpaque":
            return [f'    a2x_set_nebula_opaque_all({_value(val)})']
        # nameless sensorSetting -> global: set every player ship's scan range
        if n.get("name") is None and prop == "sensorSetting":
            return [f'    a2x_set_sensor_setting_all({_value(val)})']
        # sideValue as a property reuses the side reassignment (same declare-the-target rule)
        if var is not None and prop in ("sideValue", "SideValue"):
            self._note_side(val)
            return [f"    a2x_set_side_value({var}, {_value(val)})"]
        # elite/special ability bit-sum -> enable each named elite ability (LM fleets addon)
        if var is not None and prop in ("eliteAbilityBits", "specialAbilityBits"):
            self.addons.add("fleets")
            return [f"    a2x_set_special_bits({var}, {_value(val)})"]
        if var is not None and prop in _AUTO_PROPS:
            return [f'    a2x_set_object_property({var}, "{prop}", {_value(val)})']
        if prop in _PROP_NOOP:
            return [f'    # set_object_property {prop}: dropped -- {_PROP_NOOP[prop]}']
        if prop in _PROP_ENGINE_STUB:
            # a clear stub, not a TODO: does not block migration, needs an engine change
            return [f'    # set_object_property {prop}={_value(val)}: stub -- {_PROP_ENGINE_STUB[prop]}']
        self.note(f"set_object_property {prop}={val} on '{n.get('name','?')}': no "
                  f"confirmed Cosmos mapping yet -- see docs/property_map.md")
        if var is None:
            return [f"    # TODO set_object_property {prop}={val}: {_xml_repr(n)}"]
        return [f'    # TODO {var}.data_set.set("<cosmos_key>", {val})  '
                f'# 2.8 property "{prop}"']

    def c_set_monster_tag_data(self, n: XmlNode) -> list[str]:
        var = self.symbols.get(n.get("name"))
        self.note("2.8 tags stored as inventory values. The tag-torpedo gameplay can be "
                  "rebuilt in Cosmos: register a tag torpedo via torpedo_type(), then a "
                  "//damage route keyed on EVENT.sub_tag records the tag on hit "
                  "(set_inventory_value(DAMAGE_TARGET_ID, 'tag_source_name', ...)).")
        if var is None:
            return [f"    # TODO set_monster_tag_data: {_xml_repr(n)}"]
        slot = n.get("tag_slot", "0")
        out = []
        if n.get("sourcetext") is not None:
            out.append(f'    set_inventory_value({var}, "tag_{slot}_source", '
                       f'"{_mast_str(n.get("sourcetext"))}")')
        if n.get("datetext") is not None:
            out.append(f'    set_inventory_value({var}, "tag_{slot}_date", '
                       f'"{_mast_str(n.get("datetext"))}")')
        return out or [f"    # set_monster_tag_data clears slot {slot} on {var}"]

    def c_set_named_object_tag_state(self, n: XmlNode) -> list[str]:
        var = self.symbols.get(n.get("name"))
        if var is None:
            return [f"    # TODO set_named_object_tag_state: {_xml_repr(n)}"]
        out = [f'    set_inventory_value({var}, "tagged", '
               f'{"True" if n.get("tagged") is not None else "False"})']
        if n.get("tagSourceName") is not None:
            out.append(f'    set_inventory_value({var}, "tag_source_name", '
                       f'"{_mast_str(n.get("tagSourceName"))}")')
        if n.get("tagSourceSide") is not None:
            out.append(f'    set_inventory_value({var}, "tag_source_side", '
                       f'{n.get("tagSourceSide")})')
        return out

    def c_warning_popup(self, n: XmlNode) -> list[str]:
        self.addons.add("comms")
        msg = _mast_str(n.get("message", ""))
        ship = self.symbols.get(n.get("name"))
        if ship is None and n.get("player_slot") is not None:
            ship = self._player_ref(n)
        args = [f'"{msg}"']
        if n.get("consoles"):
            args.append(f'consoles="{n.get("consoles")}"')
        if ship:
            args.append(f"ship={ship}")
        return [f'    a2x_warning_popup({", ".join(args)})']

    def c_set_comms_button(self, n: XmlNode) -> list[str]:
        # The button itself lives in the generated //comms route; this command just
        # marks when 2.8 made it appear. Keep as a breadcrumb.
        self.addons.add("comms")
        return [f'    # set_comms_button "{n.get("text","")}" '
                f'(button is in the //comms route below)']

    def c_clear_comms_button(self, n: XmlNode) -> list[str]:
        return [f'    # clear_comms_button "{n.get("text","")}" '
                f'(consider gating the //comms button with a flag)']

    def c_set_gm_button(self, n: XmlNode) -> list[str]:
        self.addons.update({"gamemaster", "gamemaster_comms"})
        return [f'    # set_gm_button "{n.get("text","")}" '
                f'(button is in the gamemaster //comms route below)']

    def c_clear_gm_button(self, n: XmlNode) -> list[str]:
        return [f'    # clear_gm_button "{n.get("text","")}"']

    def c_set_relative_position(self, n: XmlNode) -> list[str]:
        # name1/name2 may instead be given as player_slot1/player_slot2 (the player ship)
        obj = self.symbols.get(n.get("name2"))
        if obj is None and n.get("player_slot2") is not None:
            obj = self._player_ref(n)
        ref = self.symbols.get(n.get("name1"))
        if ref is None and n.get("player_slot1") is not None:
            ref = self._player_ref(n)
        if obj is None or ref is None:
            return [f"    # TODO set_relative_position: {_xml_repr(n)}"]
        return [f"    a2x_set_relative_position({obj}, {ref}, "
                f"{_value(n.get('angle', '0'))}, {_value(n.get('distance', '0'))})"]

    def c_addto_object_property(self, n: XmlNode) -> list[str]:
        var = self.symbols.get(n.get("name"))
        if var is None and n.get("player_slot") is not None:
            var = self._player_ref(n)
        if var is None:
            var = self._gm_selected(n)  # use_gm_selection -> the GM's comms selection
        prop, val = n.get("property", "?"), n.get("value", "0")
        if var is not None and prop in _AUTO_PROPS:
            return [f'    a2x_addto_object_property({var}, "{prop}", {_value(val)})']
        if prop in _PROP_NOOP:
            return [f'    # addto_object_property {prop}: dropped -- {_PROP_NOOP[prop]}']
        self.note(f"addto_object_property {prop} on '{n.get('name','?')}': "
                  f"unmapped property -- see docs/property_map.md")
        return [f"    # TODO addto_object_property {prop}+={val}: {_xml_repr(n)}"]

    def c_copy_object_property(self, n: XmlNode) -> list[str]:
        src, dst = self.symbols.get(n.get("name1")), self.symbols.get(n.get("name2"))
        if src is None and n.get("player_slot1") is not None:
            src = self._player_ref(n)
        if dst is None and n.get("player_slot2") is not None:
            dst = self._player_ref(n)
        prop = n.get("property", "?")
        if src is not None and dst is not None and prop in _AUTO_PROPS:
            return [f'    a2x_copy_object_property({src}, {dst}, "{prop}")']
        return [f"    # TODO copy_object_property {prop}: {_xml_repr(n)}"]

    def c_set_ship_text(self, n: XmlNode) -> list[str]:
        var = self.symbols.get(n.get("name"))
        if var is None:
            return [f"    # TODO set_ship_text: {_xml_repr(n)}"]
        kw = {"newname": "name", "race": "race", "class": "ship_class", "desc": "desc"}
        args = [f'{kw[a]}="{_mast_str(n.get(a))}"' for a in kw if n.get(a) is not None]
        out: list[str] = []
        # scan_desc -> a declarative science scan (2.8 lost it: a2x_set_ship_text has no
        # key for it). The AMD target renders it via amd_science; tag the object here (where
        # it is known to exist) with its scan role, and record the text for scans.amd.
        if n.get("scan_desc") is not None:
            name = n.get("name")
            self.scans[name] = _mast_str(n.get("scan_desc"))
            if self.emit_scan_roles and name not in self.scan_roles_done:
                self.scan_roles_done.add(name)
                out.append(f'    add_role({var}, "scan_{_pyname(name).lower()}")')
        # hailtext -> a Hail comms button (2.8 lost it). Store the line on the ship; the
        # AMD target adds one gated //comms Hail route that shows it (see build_amd_target).
        if n.get("hailtext") is not None:
            name = n.get("name")
            self.hails[name] = _mast_str(n.get("hailtext"))
            if self.emit_scan_roles and name not in self.hail_done:
                self.hail_done.add(name)
                out.append(f'    set_inventory_value({var}, "a2x_hail", '
                           f'"{_mast_str(n.get("hailtext"))}")')
        if args:
            out.append(f'    a2x_set_ship_text({var}, {", ".join(args)})')
        elif not out:
            out.append(f"    # set_ship_text (no mappable fields): {_xml_repr(n)}")
        return out

    def c_set_player_carried_type(self, n: XmlNode) -> list[str]:
        # 2.8 stows a craft in a numbered hangar bay; Cosmos has no bays -- spawn a craft of
        # the right variant into the player's hangar (LM hangar_random_craft_spawn spawns it
        # AND associates it with the ship). bay_slot is dropped. The craft is a real spawned
        # object, so CAPTURE it under its 2.8 name (and name it) when that name is referenced
        # elsewhere -- so set_relative_position / if_distance / add_ai targetName resolve.
        ship = self._player_ref(n)
        if ship is None and n.get("player_slot") is not None:
            # no explicit create:player -> resolve the 2.8 slot to the runtime player-ship ID
            ship = f'a2x_player_ship({_value(n.get("player_slot"))})'
        if ship is None:
            return [f"    # TODO set_player_carried_type (no player ship): {_xml_repr(n)}"]
        self.addons.add("hangar")
        variant = _craft_variant(n.get("hullKeys"))
        var = self.symbols.get(n.get("name"))
        if var is not None:
            # capture the spawned craft under its 2.8 name so later references resolve
            # (the binding is the symbol; the Cosmos-assigned display name is kept).
            return [f'    shared {var} = to_id(hangar_random_craft_spawn({ship}, "{variant}"))']
        return [f'    hangar_random_craft_spawn({ship}, "{variant}")']

    def c_set_player_station_carried(self, n: XmlNode) -> list[str]:
        # station-carried craft -> spawn the variant into the station's hangar.
        ship = self.symbols.get(n.get("name"))
        if ship is None:
            self.note(f"set_player_station_carried on station '{n.get('name')}' not captured "
                      f"-- wire by hand")
            return [f"    # TODO set_player_station_carried: {_xml_repr(n)}"]
        self.addons.add("hangar")
        return [f'    hangar_random_craft_spawn({ship}, "{_craft_variant(n.get("hullKeys"))}")']

    def c_clear_player_station_carried(self, n: XmlNode) -> list[str]:
        # remove a station's stored (standby, in-hangar) single-seat craft
        station = self.symbols.get(n.get("name"))
        if station is None:
            return [f"    # TODO clear_player_station_carried: {_xml_repr(n)}"]
        self.addons.add("hangar")
        return [f"    a2x_clear_station_carried({station})"]

    def c_set_special(self, n: XmlNode) -> list[str]:
        # the ship: a captured named object, a player_slot, or (GM-button handlers
        # with no name) the comms-selected ship.
        obj = self.symbols.get(n.get("name"))
        if obj is None and n.get("name") is None:
            obj = "COMMS_SELECTED_ID"
        ability = n.get("ability")
        on = "False" if n.get("clear") is not None else "True"
        out = []
        if ability and obj is not None and ability in _ELITE_ABILITIES:
            self.addons.add("fleets")  # handle_elite_abilities lives in the fleets addon
            out.append(f'    a2x_set_special({obj}, "{ability}", on={on})')
        elif ability:
            self.note(f"set_special ability '{ability}': object not resolvable / "
                      f"unmapped ability -- wire by hand")
            out.append(f"    # TODO set_special ability={ability} on={on}: {_xml_repr(n)}")
        # 2.8 ship/captain form (no ability): power tier + captain personality, both
        # enumerated ints (-1 = leave unchanged). a2x maps them onto the LM surrender/
        # taunt/fleets systems (captain) and shield/weapon coeffs (ship power).
        is_ship_cap = n.get("ship") is not None or n.get("captain") is not None
        if is_ship_cap and obj is not None:
            before = len(out)
            cap = _int_or_none(n.get("captain"))
            if cap is not None and cap >= 0:
                self.addons.add("fleets")  # bombastic/seething/duplicitous drivers live in fleets/comms
                out.append(f"    a2x_set_captain({obj}, {cap})")
            ship = _int_or_none(n.get("ship"))
            if ship is not None and ship >= 0:
                out.append(f"    a2x_set_ship_power({obj}, {ship})")
            if len(out) == before:
                # both tiers -1/absent == 2.8 "leave unchanged": a real no-op, not a TODO
                out.append(f"    # set_special no-op (ship/captain both unchanged): {_xml_repr(n)}")
        elif is_ship_cap:
            self.note("set_special ship/captain: object not captured -- wire by hand")
            out.append(f"    # TODO set_special ship/captain: {_xml_repr(n)}")
        return out or [f"    # TODO set_special: {_xml_repr(n)}"]

    def c_set_damcon_members(self, n: XmlNode) -> list[str]:
        # damcons are a ship-grid concept (player ships in Cosmos). Resolve the ship from
        # name/player_slot, defaulting to the player ship. value = the team's HP,
        # team_index 0..2 -> DC1..DC3. (No-ops on a non-player ship with no grid.)
        ship = self.symbols.get(n.get("name")) or self._player_ref(n)
        if ship is None:
            return [f"    # TODO set_damcon_members: {_xml_repr(n)}"]
        return [f'    a2x_set_damcon_members({ship}, {_value(n.get("team_index", "0"))}, {_value(n.get("value", "0"))})']

    def c_set_to_gm_position(self, n: XmlNode) -> list[str]:
        # move the GM-selected object to the GM position (the gamemaster console ship,
        # COMMS_ORIGIN, which tracks the GM's clicks). Runs in the GM comms tree.
        obj = self.symbols.get(n.get("name")) or self._gm_selected(n)
        if obj is None:
            return [f"    # TODO set_to_gm_position: {_xml_repr(n)}"]
        return [f"    a2x_set_to_gm_position({obj}, COMMS_ORIGIN_ID)"]

    def c_set_fleet_property(self, n: XmlNode) -> list[str]:
        # 2.8 fleet formation config -> the general LM fleet_spacing/fleet_max_radius keys
        # (a2x resolves the fleet agent for the index). fleetSpacing / fleetMaxRadius only.
        prop = n.get("property", "?")
        if prop not in ("fleetSpacing", "fleetMaxRadius"):
            self.note(f"set_fleet_property {prop}: no Cosmos fleet mapping -- wire by hand")
            return [f"    # TODO set_fleet_property {prop}: {_xml_repr(n)}"]
        self.addons.add("fleets")
        return [f'    a2x_set_fleet_property({_value(n.get("fleetIndex", "0"))}, '
                f'"{prop}", {_value(n.get("value", "0"))})']

    def c_gm_instructions(self, n: XmlNode) -> list[str]:
        # 2.8 GM briefing text -> the LM GM console instruction panel (GAMEMASTER_INSTRUCTIONS).
        self.addons.update({"gamemaster", "gamemaster_comms"})
        title = n.get("title", "")
        body = " ".join(ln.strip() for ln in (n.text or "").split("\n")).strip()
        return [f'    a2x_set_gm_instructions("{_mast_str(title)}", "{_mast_str(body)}")']

    def c_set_skybox_index(self, n: XmlNode) -> list[str]:
        # 2.8 SB00..SB29 -> a Cosmos skybox. Cosmos has no SB## art; a2x maps the index
        # across the LM basic_random_skybox media labels (@media/skybox/*), so feature-detect
        # that addon.
        self.addons.add("basic_random_skybox")
        return [f'    a2x_set_skybox_index({_value(n.get("index", "0"))})']

    def c_log(self, n: XmlNode) -> list[str]:
        return [f'    log("{_mast_str(n.get("text", ""))}")']

    def c_spawn_external(self, n: XmlNode) -> list[str]:
        self.note(f"spawn_external_program '{n.get('name','?')}': launches an external "
                  f"program (2.8 used it for cutscene videos); update the path for Cosmos")
        return [f'    a2x_spawn_external_program("{_mast_str(n.get("name", ""))}", '
                f'"{_mast_str(n.get("arguments", ""))}")']

    def c_play_sound(self, n: XmlNode) -> list[str]:
        fn = _mast_str(n.get("filename", ""))
        return [f'    sbs.play_audio_file(0, get_mission_audio_file("{fn}"), 1.0, 1.0)']

    def c_grid_damage(self, n: XmlNode) -> list[str]:
        ship = self.symbols.get(n.get("name")) or self._player_ref(n) or 'role("__player__")'
        sysn = _GRID_SYS.get(n.get("systemType"))
        if sysn is None:
            return [f"    # TODO set_player_grid_damage systemType="
                    f"{n.get('systemType')}: {_xml_repr(n)}"]
        return [f"    grid_damage_system({ship}, sbs.SHPSYS.{sysn})"]

    def c_incoming_message(self, n: XmlNode) -> list[str]:
        frm = _mast_str(n.get("from", ""))
        fn = _mast_str(n.get("fileName", ""))
        self.note(f'incoming_message "{fn}": 2.8 made a play button; a2x plays it directly')
        return [f'    a2x_incoming_message("{frm}", "{fn}")']

    def c_end_mission(self, n: XmlNode) -> list[str]:
        return ['    signal_emit("show_game_results")', "    ->END"]


def _xml_repr(n: XmlNode) -> str:
    """Source node -> a `# when:` / `# TODO` comment, ASCII-folded (see :func:`to_ascii`)."""
    attrs = " ".join(f'{k}="{to_ascii(v)}"' for k, v in n.attrib.items())
    return f"<{n.tag} {attrs}/>"


_ASCII_PUNCT = {"‘": "'", "’": "'", "“": '"', "”": '"',
                    "–": "-", "—": "--", "…": "...", " ": " ",
                    "×": "x", "°": " deg", "•": "*"}


def to_ascii(s: str) -> str:
    """Fold text down to ASCII. Engine text is ASCII-only, and not as a style rule.

    ``MastStory.from_file`` reads with the platform codec -- cp1252 on Windows -- so ONE
    byte it cannot decode fails the whole story load. Not the line, the story: no labels,
    no ``@map``, and the mission silently never starts (the headless runner still reports
    "PASS - no runtime errors", because nothing ran to error). MISS_JewelHeist did exactly
    that on the three U+015D in its Ximni flavour text.

    2.8 text is author-written and does contain this: smart quotes, accents, the odd
    Esperanto diacritic. Punctuation is mapped to its ASCII twin, letters are stripped of
    their accents (NFKD drops the combining marks, so ``s-circumflex`` -> ``s``), and
    anything still non-ASCII becomes ``?`` rather than being dropped silently.
    """
    s = s or ""
    for ch, rep in _ASCII_PUNCT.items():
        s = s.replace(ch, rep)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.encode("ascii", "replace").decode("ascii")


def _mast_str(s: str) -> str:
    """Make 2.8 text safe inside a double-quoted MAST string literal.

    Collapses real newlines to spaces (2.8 uses ``^`` for line breaks, which the
    a2x helpers convert at runtime), escapes backslashes and double quotes, and folds the
    text to ASCII (see :func:`to_ascii` -- a stray non-ASCII byte costs the whole story).
    """
    s = to_ascii(s).replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\r", " ").replace("\n", " ").strip()
    return s


# 2.8 comparator -> Python operator.
_CMP_OP = {"=": "==", "EQUALS": "==", "!=": "!=", "NOT": "!=",
           "<": "<", "LESS": "<", ">": ">", "GREATER": ">",
           "<=": "<=", "LESS_EQUAL": "<=", ">=": ">=", "GREATER_EQUAL": ">="}


def _set_variable_value(n: XmlNode) -> str:
    """The value a 2.8 ``set_variable`` assigns -- a literal, or a RANDOM ROLL.

    2.8 rolls a range in place: ``randomIntLow``/``randomIntHigh`` (and the float pair)
    instead of ``value``. Reading only ``value`` gave those a flat ``0``, which is not a
    near-miss -- every event gated on the rolled result then tested against a number the
    flag could never hold, so none of them could fire. MISS_Medusa's_Maze picks its start
    corner that way (``StartPlayer`` = 1..8, one create-player event per value), so the
    mission got no player ship at all. 2734 int rolls and 66 float rolls across the corpus,
    2736 of them in MISS_The_Arena.

    ``random`` is a MAST global (LegendaryMissions uses ``random.choice`` in its own maps),
    and the whole mission is seeded once by ``settings_seed_apply``, so these stay
    reproducible under a fixed ``--seed``.
    """
    lo, hi = n.get("randomIntLow"), n.get("randomIntHigh")
    if lo is not None and hi is not None:
        return f"random.randint({_value(lo)}, {_value(hi)})"
    lo, hi = n.get("randomFloatLow"), n.get("randomFloatHigh")
    if lo is not None and hi is not None:
        return f"random.uniform({_value(lo)}, {_value(hi)})"
    return _value(n.get("value", "0"))


def var_cond_bool(n: XmlNode) -> str:
    """An if_variable condition -> a Python boolean expression (e.g. ``spawn2 == 1``)."""
    op = _CMP_OP.get((n.get("comparator", "") or "").strip().upper(), "==")
    return f"{_pyname(n.get('name'))} {op} {_value(n.get('value', '0'))}"


def _value(v: str) -> str:
    """Normalize a 2.8 attribute value for use as MAST/Python code.

    2.8 allows leading-zero integers (``01``), which are a syntax error in Python 3;
    normalize those. Anything else (decimals, expressions like ``1/100``, variables)
    passes through unchanged.
    """
    v = (v or "0").strip()
    if re.fullmatch(r"-?0[0-9]+", v):
        return str(int(v))
    return v


def _int_or_none(v):
    """Parse a 2.8 attribute as an int, or None if absent / not an integer literal.

    Used for the enumerated ship/captain tiers on ``set_special`` (values like -1..5);
    anything non-integer (a variable/expression) yields None so the caller can skip it.
    """
    if v is None:
        return None
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return None


def _pyname(name: str) -> str:
    """A 2.8 variable name -> a safe MAST/python identifier."""
    out = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in (name or "var"))
    if out and out[0].isdigit():
        out = "_" + out
    return out or "var"


def _num_key(v: str | None) -> str | None:
    """A canonical numeric key for a 2.8 value (``2`` / ``2.0`` -> ``2.0``); None if the
    value is not a plain number (e.g. an expression like ``Tonnage+20``)."""
    v = (v or "").strip()
    try:
        return str(float(v))
    except ValueError:
        return None


def _phase_sig_name(name: str, vkey: str) -> str:
    """The signal name for an AMD phase gate (a flag reaching a numeric value)."""
    return f"a2x_phase_{_pyname(name)}_{vkey.replace('-', 'm').replace('.', '_')}"


_COMMAND_EMIT = {
    "create:station": Emitter.c_station,
    "create:enemy": Emitter.c_enemy,
    "create:neutral": Emitter.c_neutral,
    "create:player": Emitter.c_player,
    "create:monster": Emitter.c_monster,
    "create:whale": Emitter.c_monster,
    "create:genericMesh": Emitter.c_generic,
    "create:Anomaly": Emitter.c_anomaly,
    "create:anomaly": Emitter.c_anomaly,
    "create:blackHole": Emitter.c_black_hole,
    "create:nebulas": Emitter.c_terrain,
    "create:asteroids": Emitter.c_terrain,
    "create:mines": Emitter.c_terrain,
    "set_variable": Emitter.c_set_variable,
    "set_timer": Emitter.c_set_timer,
    "set_difficulty_level": Emitter.c_set_difficulty,
    "add_ai": Emitter.c_add_ai,
    "clear_ai": Emitter.c_clear_ai,
    "destroy": Emitter.c_destroy,
    "destroy_near": Emitter.c_destroy_near,
    "direct": Emitter.c_direct,
    "set_object_property": Emitter.c_set_object_property,
    "addto_object_property": Emitter.c_addto_object_property,
    "copy_object_property": Emitter.c_copy_object_property,
    "set_ship_text": Emitter.c_set_ship_text,
    "set_relative_position": Emitter.c_set_relative_position,
    "set_comms_button": Emitter.c_set_comms_button,
    "clear_comms_button": Emitter.c_clear_comms_button,
    "set_gm_button": Emitter.c_set_gm_button,
    "clear_gm_button": Emitter.c_clear_gm_button,
    "set_monster_tag_data": Emitter.c_set_monster_tag_data,
    "set_named_object_tag_state": Emitter.c_set_named_object_tag_state,
    "warning_popup_message": Emitter.c_warning_popup,
    "log": Emitter.c_log,
    "spawn_external_program": Emitter.c_spawn_external,
    "play_sound_now": Emitter.c_play_sound,
    "set_player_grid_damage": Emitter.c_grid_damage,
    "set_special": Emitter.c_set_special,
    "set_skybox_index": Emitter.c_set_skybox_index,
    "set_damcon_members": Emitter.c_set_damcon_members,
    "gm_instructions": Emitter.c_gm_instructions,
    "set_to_gm_position": Emitter.c_set_to_gm_position,
    "set_fleet_property": Emitter.c_set_fleet_property,
    "set_player_carried_type": Emitter.c_set_player_carried_type,
    "set_player_station_carried": Emitter.c_set_player_station_carried,
    "clear_player_station_carried": Emitter.c_clear_player_station_carried,
    "set_side_value": Emitter.c_set_side_value,
    "big_message": Emitter.c_big_message,
    "incoming_comms_text": Emitter.c_comms_text,
    "incoming_message": Emitter.c_incoming_message,
    "end_mission": Emitter.c_end_mission,
}


# --- condition emitters (for event entry) -----------------------------------
_LESS_CMP = {"<", "<=", "LESS", "LESS_EQUAL", "EQUALS", "="}


def _is_less(comparator: str) -> bool:
    """2.8 distance comparator -> True if the wait is 'until closer than value'."""
    return (comparator or "").strip() in _LESS_CMP


def _craft_variant(hull_keys: str | None) -> str:
    """2.8 hullKeys -> Cosmos hangar craft variant (fighter | bomber | shuttle)."""
    h = (hull_keys or "").lower()
    if "bomber" in h:
        return "bomber"
    if "shuttle" in h:
        return "shuttle"
    return "fighter"


def _resolve_obj(em: Emitter, name: str | None, slot: str | None) -> str:
    """A MAST handle for a condition's object reference (name or player slot)."""
    if name and name in em.symbols:
        return em.symbols[name]
    if slot is not None or name is None:
        return em._player_ref(slot=slot) or 'role("__player__")'
    # unknown name -> a runtime name->id lookup (None if absent). Safe in object_exists and
    # in the guarded a2x_distance_* / a2x_within helpers (they evaluate False for a missing
    # object), unlike a bare role(name) set which throws when passed as an id. Never emit a
    # raw sbs.distance_id with one of these -- the engine errors on None.
    return em.symbols.get(name) or f'a2x_named("{_mast_str(name)}")'


def _fleet_count_role(n: XmlNode) -> str | None:
    """The role ``if_fleet_count`` counts: a 2.8 ``fleetnumber``, else every object on its
    ``sideValue``. None when it names neither (nothing to count).

    The side form is how a 2.8 mission asks "are they all dead yet?" -- it is the standard
    mission-success test -- and the side key is the role a2x_create_* already tags each
    spawn with, so counting it needs no new bookkeeping.
    """
    fl = (n.get("fleetnumber") or "").strip()
    if fl:
        return f"fleet_{fl}"
    sv = (n.get("sideValue") or "").strip()
    return _side_key(sv) if sv else None


def _wait_until(em: Emitter, expr: str, stem: str) -> list[str]:
    """Hold the chain here until *expr* is true (a half-second poll).

    The shape a chained scene needs for a condition that BECOMES true -- a ship reaching a
    box, a fleet thinning out. ``await`` covers the handful of conditions with a real
    awaitable behind them; everything else polls. Labels are numbered off one counter so an
    event carrying several waits does not collide with itself.
    """
    em.wait_prop_n += 1
    lbl = f"wait_{stem}_{em.wait_prop_n}"
    return [f"---{lbl}", "    await delay_sim(0.5)", f"    jump {lbl} if not ({expr})"]


def _skip_unless(expr: str, next_label: str | None) -> list[str]:
    """Skip this scene when *expr* is false. For a condition that is already settled when
    the chain arrives (difficulty, an object's existence) -- waiting on one of those would
    hang the chain on something that is never going to change."""
    return [f"    {f'jump {next_label}' if next_label else '->END'} if not ({expr})"]


def emit_condition(em: Emitter, n: XmlNode, idx: int = 0,
                   next_label: str | None = None) -> list[str]:
    """Translate an event condition into a wait/guard line (best-effort).

    Three shapes, and which one a condition gets is the whole game:

    * ``await`` / poll (:func:`_wait_until`) -- the condition BECOMES true, so the scene
      waits for it (distance, timers, docking, a fleet being wiped out).
    * skip (:func:`_skip_unless`) -- the condition is already settled on arrival, so a
      false one means this scene is not for this playthrough (difficulty; whether an
      object exists).
    * a comment -- nothing maps yet. **This is the dangerous one**: a scene whose every
      condition is a comment has no gate left and runs the moment the chain reaches it.
      That is how MISS_TrialsOfDeneb01 announced MISSION SUCCESS at t=0.

    ``next_label`` is the scene AFTER this one, and is what a skip jumps to. Without it a
    guard has nowhere to go but ``->END``, which ends the whole map task -- so one unmet
    condition threw away every remaining scene. Pass None only for the last scene in the
    chain, where ending really is what comes next.
    """
    tag = n.tag
    if tag == "if_fleet_count":
        # 2.8 counts EITHER a named fleet or -- with no fleetnumber -- every ship on a
        # sideValue ("are all the enemies dead?", the usual mission-success test). Only the
        # fleet form was mapped, so the side form degraded to a comment: a scene whose one
        # real gate was "all enemies destroyed" then ran the instant the chain reached it.
        # MISS_TrialsOfDeneb01 declared MISSION SUCCESS at t=0 that way.
        who = _fleet_count_role(n)
        if who and (n.get("comparator", "") in ("<=", "LESS_EQUAL")) and n.get("value") in ("0", "0.0"):
            return [f'    await destroyed_all(role("{who}"))']
        # Any other comparator ("more than 3 left", "exactly 1") has no awaitable behind
        # it, but it is still a count the mission is waiting on -- poll it rather than
        # leaving the scene with no gate.
        b = _cond_bool(em, n)
        if b:
            return _wait_until(em, b, "fleet")
        return [f"    # when: fleet {n.get('fleetnumber')} side {n.get('sideValue')} "
                f"count {n.get('comparator','')} {n.get('value','')}"]
    if tag == "if_difficulty":
        # Settled before the mission starts and never changes, so this selects whether the
        # scene belongs in this playthrough at all -- skip, never wait.
        b = _cond_bool(em, n)
        if b:
            return _skip_unless(b, next_label)
        return [f"    # when: difficulty {n.get('comparator','')} {n.get('value','')}"]
    if tag == "if_docked":
        who = _resolve_obj(em, n.get("name"), n.get("player_slot"))
        # which ship docks: the player (player_slot/name=player) -> player_var
        ship = em._player_ref(n) or 'role("__player__")'
        em.addons.add("docking")
        return [f"---wait_dock_{idx}",
                "    await delay_sim(1)",
                f"    jump wait_dock_{idx} if not a2x_is_docked({ship})"]
    if tag == "if_distance":
        a = _resolve_obj(em, n.get("name1"), n.get("player_slot1"))
        val = n.get("value", "0")
        fn = "distance_less" if _is_less(n.get("comparator")) else "distance_greater"
        if n.get("name2") or n.get("player_slot2"):
            b = _resolve_obj(em, n.get("name2"), n.get("player_slot2"))
            return [f"    await {fn}({a}, {b}, {val})"]
        px, py, pz = n.get("pointX", "0"), n.get("pointY", "0"), n.get("pointZ", "0")
        pfn = "distance_point_less" if _is_less(n.get("comparator")) else "distance_point_greater"
        return [f"    await {pfn}({a}, a2x_pos({px}, {py}, {pz}), {val})"]
    if tag in ("if_inside_sphere", "if_outside_sphere"):
        o = _resolve_obj(em, n.get("name"), n.get("player_slot"))
        cx, cy, cz = n.get("centerX", "0"), n.get("centerY", "0"), n.get("centerZ", "0")
        r = n.get("radius", "0")
        fn = "distance_point_less" if tag == "if_inside_sphere" else "distance_point_greater"
        return [f"    await {fn}({o}, a2x_pos({cx}, {cy}, {cz}), {r})"]
    if tag in ("if_inside_box", "if_outside_box"):
        # Same job as the sphere pair above (a ship reaching a region), so the same shape:
        # wait for it. a2x_in_box has always existed and _cond_bool has always emitted it --
        # only the chain path was leaving a comment here, and a region trigger is usually
        # the ONLY condition on its scene, so that scene fired on arrival instead.
        b = _cond_bool(em, n)
        if b:
            return _wait_until(em, b, "box")
        return [f'    # when: {tag} {n.get("name") or n.get("player_slot")}']
    if tag in ("if_exists", "if_not_exists"):
        # A one-shot test, not something to wait on: 2.8 checks it the moment the event is
        # considered. Failing it SKIPS this scene -- it does not end the mission.
        o = _resolve_obj(em, n.get("name"), n.get("player_slot"))
        neg = "not " if tag == "if_exists" else ""
        skip = f"jump {next_label}" if next_label else "->END"
        return [f"    {skip} if {neg}object_exists({o})"]
    if tag in ("if_monster_tag_matches", "if_object_tag_matches"):
        name = n.get("name") or n.get("objectName")
        var = em.symbols.get(name) or f'"{name}"'
        s = _mast_str(n.get("string", ""))
        em.note("tag-match: rebuild 2.8 tagging with a tag torpedo_type() + a //damage "
                "route that sets tag_source_name on hit, then this guard works.")
        return [f'    # guard: tag match ~ "{s}"  '
                f'(get_inventory_value({var}, "tag_source_name") == "{s}")']
    if tag == "if_variable":
        # A latch skips, a phase gate waits -- and which is which needs the chain order and
        # the set_variable graph, so convert.plan_chain_flag_gates decides it and leaves the
        # verdict here. No verdict (no chain, or a value we cannot reason about) -> comment.
        gate = em.chain_flag_gate.get(id(n))
        if gate == "skip":
            return _skip_unless(var_cond_bool(n), next_label)
        if gate == "wait":
            return _wait_until(em, var_cond_bool(n), "flag")
        return [f'    # guard: {_pyname(n.get("name"))} {n.get("comparator","")} {n.get("value","")}']
    if tag == "if_timer_finished":
        # is_timer_finished says True for a timer that was NEVER SET, so `await` on one
        # returns instantly and the scene fires at t=0. Wait on set-and-finished instead --
        # but only when something in the mission actually sets this timer. If nothing does,
        # 2.8 never fires the event either, so skip the scene rather than block the chain
        # on a timer that is never coming.
        name = n.get("name")
        if name in em.timers_set:
            return [f'    await is_timer_set_and_finished(0, "{name}")']
        return _skip_unless(f'is_timer_set_and_finished(0, "{name}")', next_label)
    if tag == "if_object_property":
        b = _cond_bool(em, n)  # mapped props -> a live boolean; poll until it holds
        if b:
            return _wait_until(em, b, "prop")
    return [f"    # when: {_xml_repr(n)}"]


def _cond_bool(em: Emitter, n: XmlNode) -> str | None:
    """A condition as a live Python boolean (for a per-tick polling loop), or None if
    it can't be expressed -- the caller then leaves a 'verify by hand' comment.

    Unlike :func:`emit_condition` (which emits one-shot ``await`` waits suited to a
    sequential scene), these re-evaluate every loop pass, so a continuous 2.8 event can
    re-fire (respawn / wave / periodic) the way it does in the old engine.
    """
    tag = n.tag
    if tag == "if_variable":
        return var_cond_bool(n)
    if tag in ("if_exists", "if_not_exists"):
        o = _resolve_obj(em, n.get("name"), n.get("player_slot"))
        return f"object_exists({o})" if tag == "if_exists" else f"not object_exists({o})"
    if tag == "if_timer_finished":
        # SET-and-finished, not just finished: is_timer_finished returns True for a timer
        # that was NEVER SET ("nothing pending" reads as done). 2.8 does not fire an event
        # on a timer that never started, so the plain form made every such guard true at
        # t=0 -- four corpus missions ran their end-game loop in the first tick and called
        # show_game_results seconds in.
        return f'is_timer_set_and_finished(0, "{n.get("name")}")'
    if tag == "if_docked":
        em.addons.add("docking")
        ship = em._player_ref(n) or 'role("__player__")'
        return f"a2x_is_docked({ship})"
    if tag == "if_difficulty":
        op = _CMP_OP.get((n.get("comparator", "") or "").strip().upper(), "==")
        return f"DIFFICULTY {op} {_value(n.get('value', '0'))}"
    if tag == "if_fleet_count":
        who = _fleet_count_role(n)   # a named fleet, or every ship on a sideValue
        if not who:
            return None
        op = _CMP_OP.get((n.get("comparator", "") or "").strip().upper(), "==")
        return f'len(to_object_list(role("{who}"))) {op} {_value(n.get("value", "0"))}'
    if tag == "if_distance":
        a = _resolve_obj(em, n.get("name1"), n.get("player_slot1"))
        val = _value(n.get("value", "0"))
        less = _is_less(n.get("comparator"))
        if n.get("name2") or n.get("player_slot2"):
            b = _resolve_obj(em, n.get("name2"), n.get("player_slot2"))
            # a2x_distance_* (not a raw sbs.distance_id): either handle can be None
            # (a2x_named miss, unset shared var) or a destroyed object's stale id, and
            # the engine errors "sbs.distance_id was sent None" on those. The helpers
            # evaluate False instead, matching 2.8 (a condition about a missing object
            # never fires).
            fn = "a2x_distance_less" if less else "a2x_distance_greater"
            return f"{fn}({a}, {b}, {val})"
        px, py, pz = n.get("pointX", "0"), n.get("pointY", "0"), n.get("pointZ", "0")
        w = f"a2x_within({a}, {px}, {py}, {pz}, {val})"
        return w if less else f"not {w}"
    if tag in ("if_inside_sphere", "if_outside_sphere"):
        o = _resolve_obj(em, n.get("name"), n.get("player_slot"))
        cx, cy, cz = n.get("centerX", "0"), n.get("centerY", "0"), n.get("centerZ", "0")
        w = f"a2x_within({o}, {cx}, {cy}, {cz}, {_value(n.get('radius', '0'))})"
        return w if tag == "if_inside_sphere" else f"not {w}"
    if tag in ("if_inside_box", "if_outside_box"):
        o = _resolve_obj(em, n.get("name"), n.get("player_slot"))
        inside = "True" if tag == "if_inside_box" else "False"
        return (f'a2x_in_box({o}, {n.get("leastX","0")}, {n.get("leastZ","0")}, '
                f'{n.get("mostX","0")}, {n.get("mostZ","0")}, inside={inside})')
    if tag == "if_object_property":
        # Read a mapped 2.8 property live (a2x_object_property mirrors the a2x setter
        # table). Only the confirmed props (_AUTO_PROPS) become a live boolean; the rest
        # stay unexpressible (-> verify-by-hand comment / not an AMD escape-hatch trigger).
        prop = n.get("property")
        if prop in _AUTO_PROPS:
            o = _resolve_obj(em, n.get("name"), n.get("player_slot"))
            op = _CMP_OP.get((n.get("comparator", "") or "").strip().upper(), "==")
            # `or 0` guards a gone object (a2x_object_property -> None) so the compare
            # never throws in a polling loop.
            return f'(a2x_object_property({o}, "{prop}") or 0) {op} {_value(n.get("value", "0"))}'
        return None
    return None
