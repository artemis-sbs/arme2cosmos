"""Emit Cosmos MAST (and scaffolding) from a parsed 2.8 mission.

Scaffold-with-TODOs philosophy: the create-family commands translate to real
``a2x_*`` calls (positions pass through verbatim -- ``a2x`` flips coordinates
internally); everything not mechanically translatable is emitted as a
``# TODO`` line with the original XML preserved, and collected into
``MIGRATION_NOTES.md``. Events become a linear chain of ``---`` labels.
"""

from __future__ import annotations

from .coverage import classify, FULL, PARTIAL
from .model import Event, Mission, XmlNode

# 2.8 sideValue -> a Cosmos side/role token (1=enemy, 2=friendly/player, 0=none).
_SIDE = {"0": "neutral", "1": "enemy", "2": "friendly"}

# 2.8 add_ai block types that a2x_add_ai maps to a real brain (mirror of a2x.ai).
# Others emit the call but a2x_add_ai is a no-op for them -> flagged in notes.
_AI_MAPPED = {"CHASE_PLAYER", "CHASE_STATION", "CHASE_AI_SHIP", "CHASE_NEUTRAL",
              "ATTACK", "TARGET_THROTTLE"}

# Tiny starter hull/art crosswalk. The real table is the tool's `artmap`
# (vesselData.xml <-> shipDataBB.json); these are sensible placeholders so output
# runs, each flagged in MIGRATION_NOTES.
_STATION_ART = "starbase_command"
_ENEMY_ART = "kralien_cruiser"
_NEUTRAL_ART = "transport"
_PLAYER_ART = "tsn_light_cruiser"
_MONSTER_ART = "monster_charbdis"


class Emitter:
    def __init__(self, mission: Mission):
        self.mission = mission
        self.notes: list[str] = []  # punch-list lines for MIGRATION_NOTES.md
        self.addons: set[str] = set()  # feature-detected story.json mastlibs
        self.symbols: dict[str, str] = {}  # 2.8 object name -> MAST variable

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
        """Indented line; captures the spawn into a variable when the object is named."""
        name = n.get("name")
        if name:
            return f"    {self._var_for(name)} = {expr}"
        return f"    {expr}"

    def _xyz(self, n: XmlNode, px="x", py="y", pz="z"):
        return (n.get(px, "0"), n.get(py, "0"), n.get(pz, "0"))

    def _side(self, n: XmlNode) -> str:
        return _SIDE.get((n.get("sideValue") or "").strip(), "enemy")

    def _name_kw(self, n: XmlNode) -> str:
        nm = n.get("name")
        return f', name="{nm}"' if nm else ""

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
        self.note(f"verify station art for {n.get('name','?')} "
                  f"(hullID={n.get('hullID')} race={n.get('raceKeys')})")
        return [self._assign(n, f'a2x_create_station({x}, {y}, {z}, "{_STATION_ART}", '
                f'side="{self._side(n)}"{self._name_kw(n)})')]

    def c_enemy(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        side = "enemy"
        fleet = n.get("fleetnumber")
        if fleet:
            side = f"enemy, fleet_{fleet}"  # role so if_fleet_count can await it
        self.note(f"verify enemy art for {n.get('name','?')} "
                  f"(hullID={n.get('hullID')} race={n.get('raceKeys')})")
        return [self._assign(n, f'a2x_create_enemy({x}, {y}, {z}, "{_ENEMY_ART}", '
                f'side="{side}"{self._name_kw(n)})')]

    def c_neutral(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        return [self._assign(n, f'a2x_create_neutral({x}, {y}, {z}, "{_NEUTRAL_ART}", '
                f'side="{self._side(n)}"{self._name_kw(n)})')]

    def c_player(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        self.addons.update({"consoles", "fleets"})
        self.note("player ship: a2x_create_player is a scaffold; prefer the consoles/"
                  "fleets addon (PLAYER_LIST + spawn_players) for real console wiring")
        nm = n.get("name") or "Artemis"
        expr = f'a2x_create_player({x}, {y}, {z}, "{_PLAYER_ART}", name="{nm}")'
        return [self._assign(n, expr) if n.get("name") else f"    {expr}"]

    def c_monster(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        mt = n.get("monsterType", "0")
        self.note(f"monster type {mt}: placeholder art + creature_ role (real art only "
                  f"for classic/derelict)")
        return [self._assign(n, f'a2x_create_monster({x}, {y}, {z}, '
                f'monster_type={mt}{self._name_kw(n)})')]

    def c_anomaly(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        self.addons.add("upgrades")
        pt = n.get("pickupType", "0")
        return [f'    a2x_create_anomaly({x}, {y}, {z}, {pt})']

    def c_black_hole(self, n: XmlNode) -> list[str]:
        x, y, z = self._xyz(n)
        return [f'    a2x_create_black_hole({x}, {y}, {z}){self._name_kw(n) and ""}']

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
        name = n.get("name")
        val = n.get("value", "0")
        return [f"    {_pyname(name)} = {val}"]

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
        return [f'    a2x_incoming_comms_text("{body}", from_name="{frm}")']

    def c_add_ai(self, n: XmlNode) -> list[str]:
        self.addons.add("ai")
        name = n.get("name")
        typ = (n.get("type") or "").upper()
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


def _pyname(name: str) -> str:
    """A 2.8 variable name -> a safe MAST/python identifier."""
    out = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in (name or "var"))
    if out and out[0].isdigit():
        out = "_" + out
    return out or "var"


_COMMAND_EMIT = {
    "create:station": Emitter.c_station,
    "create:enemy": Emitter.c_enemy,
    "create:neutral": Emitter.c_neutral,
    "create:player": Emitter.c_player,
    "create:monster": Emitter.c_monster,
    "create:whale": Emitter.c_monster,
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
    "big_message": Emitter.c_big_message,
    "incoming_comms_text": Emitter.c_comms_text,
    "incoming_message": Emitter.c_incoming_message,
    "end_mission": Emitter.c_end_mission,
}


# --- condition emitters (for event entry) -----------------------------------
def emit_condition(em: Emitter, n: XmlNode) -> list[str]:
    """Translate an event condition into a wait/guard line (best-effort)."""
    tag = n.tag
    if tag == "if_fleet_count":
        fl = n.get("fleetnumber")
        if fl and (n.get("comparator", "") in ("<=", "LESS_EQUAL")) and n.get("value") in ("0", "0.0"):
            return [f'    await destroyed_all(role("fleet_{fl}"))']
    if tag == "if_docked":
        return [f'    # when: player docked with {n.get("name","?")} '
                f'(await a dock signal / poll dock_state)']
    if tag == "if_distance":
        return [f'    # when: distance {n.get("name1","?")}..{n.get("name2","?")} '
                f'{n.get("comparator","")} {n.get("value","")}']
    if tag == "if_variable":
        # flag guard -- in a linear chain the sequencing usually subsumes this
        return [f'    # guard: {_pyname(n.get("name"))} {n.get("comparator","")} {n.get("value","")}']
    if tag == "if_timer_finished":
        return [f'    await is_timer_finished(0, "{n.get("name")}")']
    return [f"    # when: {_xml_repr(n)}"]
