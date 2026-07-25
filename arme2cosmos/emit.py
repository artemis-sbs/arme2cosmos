"""Emit Cosmos MAST (and scaffolding) from a parsed 2.8 mission.

Scaffold-with-TODOs philosophy: the create-family commands translate to real
``a2x_*`` calls (positions pass through verbatim -- ``a2x`` flips coordinates
internally); everything not mechanically translatable is emitted as a
``# TODO`` line with the original XML preserved, and collected into
``MIGRATION_NOTES.md``. Events become a linear chain of ``---`` labels.
"""

from __future__ import annotations

import re

from .coverage import classify, FULL, PARTIAL
from .model import Event, Mission, XmlNode

# 2.8 sideValue -> a Cosmos side/role token (1=enemy, 2=friendly/player, 0=none).
_SIDE = {"0": "neutral", "1": "enemy", "2": "friendly"}

# 2.8 add_ai block types that a2x_add_ai maps to a real brain (mirror of a2x.ai).
# Others emit the call but a2x_add_ai is a no-op for them -> flagged in notes.
_AI_MAPPED = {"CHASE_PLAYER", "CHASE_STATION", "CHASE_AI_SHIP", "CHASE_NEUTRAL",
              "ATTACK", "TARGET_THROTTLE", "CHASE_FLEET"}

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
    "angleDelta", "rollDelta", "pitchDelta", "turnRate", "throttle", "artScale",
    "energy", "hasSurrendered", "shieldsOn", "shieldStateFront", "shieldStateBack",
    "shieldMaxStateFront", "shieldMaxStateBack", "missileStoresNuke",
    "missileStoresHoming", "missileStoresMine", "missileStoresEMP", "countNuke",
    "countHoming", "countMine", "countEMP",
    "missileStoresPShock", "missileStoresTag", "missileStoresECM", "countShk",
    "missileStoresBeacon", "countBea",
    "pushRadius",
}

# 2.8 properties documented as non-functional even in Artemis 2.8 -> a faithful port is a
# no-op. Drop cleanly (a comment, not a TODO): wiring them would add behaviour 2.8 lacked.
_PROP_NOOP = {
    "blocksShotFlag": "documented non-functional in Artemis 2.8",
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
_MONSTER_ART = "monster_charbdis"


class Emitter:
    def __init__(self, mission: Mission, hullmap: dict | None = None):
        self.mission = mission
        self.hullmap = hullmap  # optional vesselData<->shipDataBB crosswalk
        self.notes: list[str] = []  # punch-list lines for MIGRATION_NOTES.md
        self.addons: set[str] = set()  # feature-detected story.json mastlibs
        self.symbols: dict[str, str] = {}  # 2.8 object name -> MAST variable
        self.player_var: str | None = None  # MAST var holding the player ship
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
        self.wait_prop_n = 0  # unique-label counter for if_object_property poll waits
        # 2.8 object names referenced by a later command/condition (not the create) -- a
        # monster with a referenced name needs the capturable path, not a prefab_spawn.
        self.referenced_names: set[str] = set()

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

    def _side(self, n: XmlNode) -> str:
        return _SIDE.get((n.get("sideValue") or "").strip(), "enemy")

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
                f'side="{self._side(n)}"{self._name_kw(n)})')]

    def c_enemy(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        side = "enemy"
        fleet = n.get("fleetnumber")
        if fleet:
            side = f"enemy, fleet_{fleet}"  # role so if_fleet_count can await it
        art = self._art(n, _ENEMY_ART)
        if art == _ENEMY_ART:
            self.note(f"verify enemy art for {n.get('name','?')} "
                      f"(hullID={n.get('hullID')} race={n.get('raceKeys')})")
        return [self._assign(n, f'a2x_create_enemy({x}, {y}, {z}, "{art}", '
                f'side="{side}"{self._name_kw(n)})')]

    def c_neutral(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        art = self._art(n, _NEUTRAL_ART)
        return [self._assign(n, f'a2x_create_neutral({x}, {y}, {z}, "{art}", '
                f'side="{self._side(n)}"{self._name_kw(n)})')]

    def c_player(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        self.addons.update({"consoles", "fleets"})
        self.note("player ship: a2x_create_player is a scaffold; prefer the consoles/"
                  "fleets addon (PLAYER_LIST + spawn_players) for real console wiring")
        nm = _mast_str(n.get("name") or "Artemis")
        self.player_var = "player_ship"
        if n.get("name"):
            self._var_for(n.get("name"))  # also resolvable by name
            self.symbols[n.get("name")] = "player_ship"
        return [f'    shared player_ship = a2x_create_player({x}, {y}, {z}, "{_PLAYER_ART}", name="{nm}")']

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
        return [f"    {fn}({count}, {start}{end}{radius}{rng}{seed}{nt})"]

    def c_set_variable(self, n: XmlNode) -> list[str]:
        # shared so concurrent independent-event tasks can read the flag
        raw = n.get("name")
        name = _pyname(raw)
        out = [f"    shared {name} = {_value(n.get('value', '0'))}"]
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

    def c_add_ai(self, n: XmlNode) -> list[str]:
        name = n.get("name")
        typ = (n.get("type") or "").upper()
        if typ in _AI_DROP:
            return [f'    # add_ai {typ}: dropped -- {_AI_DROP[typ]}']
        self.addons.add("ai")
        var = self.symbols.get(name)
        if var is None:
            self.note(f"add_ai {typ} references object '{name}' not captured here "
                      f"(forward ref or gm-selected) -- wire by hand")
            return [f'    # TODO add_ai {typ} on "{name}"']
        if typ not in _AI_MAPPED:
            self.note(f"add_ai {typ} on '{name}': no Cosmos brain mapping yet "
                      f"(a2x_add_ai is a no-op for it) -- choose/author a brain")
        return [f'    a2x_add_ai({var}, "{typ}")']

    def c_clear_ai(self, n: XmlNode) -> list[str]:
        var = self.symbols.get(n.get("name"))
        if var is None:
            return [f'    # TODO clear_ai on "{n.get("name")}" (object not captured)']
        return [f"    a2x_clear_ai({var})"]

    def c_destroy(self, n: XmlNode) -> list[str]:
        var = self.symbols.get(n.get("name"))
        if var is None:
            self.note(f"destroy '{n.get('name')}' references object not captured "
                      f"(forward ref / gm-selected / player_slot) -- wire by hand")
            return [f'    # TODO destroy "{n.get("name")}"']
        return [f"    a2x_destroy({var})"]

    def c_destroy_near(self, n: XmlNode) -> list[str]:
        kind = n.get("type", "all")
        if n.get("name"):  # destroy near a named object -> no point known at convert time
            self.note(f"destroy_near near object '{n.get('name')}': use that object's "
                      f"position (a2x_destroy_near takes a point) -- wire by hand")
            return [f"    # TODO destroy_near near \"{n.get('name')}\": {_xml_repr(n)}"]
        cx, cy, cz = self._xyz(n, "centerX", "centerY", "centerZ")
        return [f'    a2x_destroy_near({cx}, {cy}, {cz}, {n.get("radius", "0")}, "{kind}")']

    def c_set_side_value(self, n: XmlNode) -> list[str]:
        obj = self.symbols.get(n.get("name"))
        if obj is None and n.get("player_slot") is not None:
            obj = self.player_var
        if obj is None:
            return [f"    # TODO set_side_value: {_xml_repr(n)}"]
        return [f'    a2x_set_side_value({obj}, {_value(n.get("value", "0"))})']

    def c_direct(self, n: XmlNode) -> list[str]:
        var = self.symbols.get(n.get("name"))
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
        prop, val = n.get("property", "?"), n.get("value", "0")
        # global difficulty knobs (no object name): nonPlayer*/player* -> fleet coeffs
        if n.get("name") is None and prop in _FLEET_COEFF:
            return [f'    a2x_set_fleet_coeff("{prop}", {_value(val)})']
        # sideValue as a property reuses the side-role reassignment (1=enemy / 2=friendly)
        if var is not None and prop in ("sideValue", "SideValue"):
            return [f"    a2x_set_side_value({var}, {_value(val)})"]
        # elite/special ability bit-sum -> enable each named elite ability (LM fleets addon)
        if var is not None and prop in ("eliteAbilityBits", "specialAbilityBits"):
            self.addons.add("fleets")
            return [f"    a2x_set_special_bits({var}, {_value(val)})"]
        if var is not None and prop in _AUTO_PROPS:
            return [f'    a2x_set_object_property({var}, "{prop}", {_value(val)})']
        if prop in _PROP_NOOP:
            return [f'    # set_object_property {prop}: dropped -- {_PROP_NOOP[prop]}']
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
            ship = self.player_var
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
        obj = self.symbols.get(n.get("name2"))
        ref = self.symbols.get(n.get("name1"))
        if obj is None or ref is None:
            return [f"    # TODO set_relative_position: {_xml_repr(n)}"]
        return [f"    a2x_set_relative_position({obj}, {ref}, "
                f"{_value(n.get('angle', '0'))}, {_value(n.get('distance', '0'))})"]

    def c_addto_object_property(self, n: XmlNode) -> list[str]:
        var = self.symbols.get(n.get("name"))
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
        if n.get("ship") is not None or n.get("captain") is not None:
            self.note("set_special ship/captain type has no Cosmos equivalent")
            out.append(f"    # TODO set_special ship/captain: {_xml_repr(n)}")
        return out or [f"    # TODO set_special: {_xml_repr(n)}"]

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
        ship = self.symbols.get(n.get("name")) or self.player_var or 'role("__player__")'
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
    attrs = " ".join(f'{k}="{v}"' for k, v in n.attrib.items())
    return f"<{n.tag} {attrs}/>"


def _mast_str(s: str) -> str:
    """Make 2.8 text safe inside a double-quoted MAST string literal.

    Collapses real newlines to spaces (2.8 uses ``^`` for line breaks, which the
    a2x helpers convert at runtime), and escapes backslashes and double quotes.
    """
    s = (s or "").replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\r", " ").replace("\n", " ").strip()
    return s


# 2.8 comparator -> Python operator.
_CMP_OP = {"=": "==", "EQUALS": "==", "!=": "!=", "NOT": "!=",
           "<": "<", "LESS": "<", ">": ">", "GREATER": ">",
           "<=": "<=", "LESS_EQUAL": "<=", ">=": ">=", "GREATER_EQUAL": ">="}


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


def _resolve_obj(em: Emitter, name: str | None, slot: str | None) -> str:
    """A MAST handle for a condition's object reference (name or player slot)."""
    if name and name in em.symbols:
        return em.symbols[name]
    if slot is not None or name is None:
        return em.player_var or 'role("__player__")'
    return em.symbols.get(name) or f'role("{name}")'  # unknown -> best-effort role


def emit_condition(em: Emitter, n: XmlNode, idx: int = 0) -> list[str]:
    """Translate an event condition into a wait/guard line (best-effort)."""
    tag = n.tag
    if tag == "if_fleet_count":
        fl = n.get("fleetnumber")
        if fl and (n.get("comparator", "") in ("<=", "LESS_EQUAL")) and n.get("value") in ("0", "0.0"):
            return [f'    await destroyed_all(role("fleet_{fl}"))']
        return [f"    # when: fleet {fl} count {n.get('comparator','')} {n.get('value','')}"]
    if tag == "if_docked":
        who = _resolve_obj(em, n.get("name"), n.get("player_slot"))
        # which ship docks: the player (player_slot/name=player) -> player_var
        ship = em.player_var or 'role("__player__")'
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
        o = _resolve_obj(em, n.get("name"), n.get("player_slot"))
        inside = "True" if tag == "if_inside_box" else "False"
        return [f'    # guard: a2x_in_box({o}, {n.get("leastX","0")}, {n.get("leastZ","0")}, '
                f'{n.get("mostX","0")}, {n.get("mostZ","0")}, inside={inside})']
    if tag in ("if_exists", "if_not_exists"):
        o = _resolve_obj(em, n.get("name"), n.get("player_slot"))
        neg = "not " if tag == "if_exists" else ""
        return [f"    ->END if {neg}object_exists({o})"]
    if tag in ("if_monster_tag_matches", "if_object_tag_matches"):
        name = n.get("name") or n.get("objectName")
        var = em.symbols.get(name) or f'"{name}"'
        s = _mast_str(n.get("string", ""))
        em.note("tag-match: rebuild 2.8 tagging with a tag torpedo_type() + a //damage "
                "route that sets tag_source_name on hit, then this guard works.")
        return [f'    # guard: tag match ~ "{s}"  '
                f'(get_inventory_value({var}, "tag_source_name") == "{s}")']
    if tag == "if_variable":
        return [f'    # guard: {_pyname(n.get("name"))} {n.get("comparator","")} {n.get("value","")}']
    if tag == "if_timer_finished":
        return [f'    await is_timer_finished(0, "{n.get("name")}")']
    if tag == "if_object_property":
        b = _cond_bool(em, n)  # mapped props -> a live boolean; poll until it holds
        if b:
            em.wait_prop_n += 1  # unique per condition (an event can have several)
            lbl = f"wait_prop_{em.wait_prop_n}"
            return [f"---{lbl}", "    await delay_sim(0.5)", f"    jump {lbl} if not ({b})"]
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
        return f'is_timer_finished(0, "{n.get("name")}")'
    if tag == "if_docked":
        em.addons.add("docking")
        ship = em.player_var or 'role("__player__")'
        return f"a2x_is_docked({ship})"
    if tag == "if_difficulty":
        op = _CMP_OP.get((n.get("comparator", "") or "").strip().upper(), "==")
        return f"DIFFICULTY {op} {_value(n.get('value', '0'))}"
    if tag == "if_fleet_count":
        fl = n.get("fleetnumber")
        if not fl:
            return None
        op = _CMP_OP.get((n.get("comparator", "") or "").strip().upper(), "==")
        return f'len(to_object_list(role("fleet_{fl}"))) {op} {_value(n.get("value", "0"))}'
    if tag == "if_distance":
        a = _resolve_obj(em, n.get("name1"), n.get("player_slot1"))
        val = _value(n.get("value", "0"))
        less = _is_less(n.get("comparator"))
        if n.get("name2") or n.get("player_slot2"):
            b = _resolve_obj(em, n.get("name2"), n.get("player_slot2"))
            return f"sbs.distance_id({a}, {b}) {'<' if less else '>'} {val}"
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
