"""Prototype `--target amd` emitter: a 2.8 mission -> an AMD quest tree + thin MAST.

Companion to :mod:`arme2cosmos.convert` (which emits the MAST-only targets). This
module produces the pair described in ``docs/amd_target.md``:

  * ``story.amd``  -- the quest tree (declarative triggers, win/lose), and
  * ``story.mast`` -- a thin ``@map`` task that spawns the ``<start>`` block (reusing
    the existing ``a2x_*`` emitters), tags quest-target roles, grants the AMD, and
    carries the imperative leftovers as ``//signal`` routes / ``gate_*`` watchers.

Scope: a working proof of the win/lose-tree + kill-goal + escape-hatch pattern. It is
deliberately conservative -- anything it cannot map cleanly stays a polling loop or a
``# TODO`` (the same scaffold philosophy as the MAST target). It never invents win/lose
semantics: an ambiguous end-game event is emitted with a ``// TODO win or lose?`` note.
"""

from __future__ import annotations

from .emit import (Emitter, emit_condition, _cond_bool, _pyname, _mast_str, _value,
                   _num_key, _phase_sig_name)
from .model import Event, Mission, XmlNode

# Keywords that classify an end-game decider event as a win or a loss (matched against
# the event name + its big_message text). Ambiguous -> a TODO for the human.
_WIN_WORDS = ("success", "congrat", "victor", "win", "saved", "award", "complete", "prevail")
_LOSE_WORDS = ("fail", "died", "doomed", "destroyed", "lost", "defeat", "death", "overwhelm")

_PLAYER_ROLE = "player_hero"  # role tagged on the player so `Fail on all dead:` can name it

# 2.8 conditions that are a real objective TRIGGER (vs an `if_variable` flag guard or a
# continuous `if_exists` gate). An event carrying one of these becomes an objective quest.
_REAL_TRIGGER_TAGS = {"if_not_exists", "if_fleet_count", "if_docked", "if_distance",
                      "if_inside_sphere", "if_outside_sphere", "if_timer_finished",
                      "if_object_property"}


# --- small local reuses (kept here to avoid a convert<->amd_emit import cycle) --------
def _truthy(v: str) -> bool:
    try:
        return float(v) != 0
    except (TypeError, ValueError):
        return bool(v and v.strip())


def _xml_one(n: XmlNode) -> str:
    attrs = " ".join(f'{k}="{v}"' for k, v in n.attrib.items())
    return f"<{n.tag} {attrs}/>"


# --- quest model ----------------------------------------------------------------------
class Quest:
    """One AMD quest fence + the MAST side-effects it implies (roles, watchers)."""

    def __init__(self, key: str, title: str):
        self.key = key
        self.title = title
        self.scope = "shared"
        self.state = "active"
        self.goal: str | None = None      # `Goal: destroy 1 bad_alien`
        self.when: str | None = None       # `When: signal a2x_gate_0`
        self.complete_after: str | None = None  # `Complete after: 60 seconds` (timed beat)
        self.reveal: str | None = None     # `Then: reveal <key>` (reveal chain)
        self.gate_label: str | None = None  # its escape-hatch watcher label (if When: signal)
        self.phase_gates: list = []         # [(flag, vkey, vraw)] surviving phase-gate flags
        self.critical = False
        self.fail_on_all_dead: str | None = None
        self.win: str | bool | None = None   # prose reason, True (bare flag), or None
        self.lose: str | bool | None = None
        self.desc = ""
        self.todos: list[str] = []

    def render(self) -> str:
        out = [f"# [{_amd_text(self.title)}]({self.key})", "---",
               f"Scope: {self.scope}", f"State: {self.state}"]
        if self.goal:
            out.append(f"Goal: {self.goal}")
        if self.when:
            out.append(f"When: {self.when}")
        if self.complete_after:
            out.append(f"Complete after: {self.complete_after}")
        if self.reveal:
            out.append(f"Then: reveal {self.reveal}")
        if self.critical:
            out.append("Critical: true")
        if self.fail_on_all_dead:
            out.append(f"Fail on all dead: {self.fail_on_all_dead}")
        for label, val in (("Win", self.win), ("Lose", self.lose)):
            if val is True:
                out.append(f"{label}: true")
            elif isinstance(val, str) and val:
                out.append(f"{label}: {_amd_text(val)}")
        out.append("---")
        out.append(self.desc or f"{self.title}.")
        out += [f"// TODO {t}" for t in self.todos]
        return "\n".join(out)


def _amd_text(s: str) -> str:
    """One-line, ASCII-safe text for an AMD heading/value (engine text is ASCII-only)."""
    s = (s or "").replace("^", " ").replace("\r", " ").replace("\n", " ")
    s = s.replace("[", "(").replace("]", ")")  # keep link syntax unambiguous
    return " ".join(s.split()).strip()


# --- fleet / object helpers -----------------------------------------------------------
def _fleet_sizes(mission: Mission) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for n in mission.all_nodes():
        if n.tag == "create" and n.get("fleetnumber"):
            fl = n.get("fleetnumber")
            sizes[fl] = sizes.get(fl, 0) + 1
    return sizes


def _is_player_ref(em: Emitter, n: XmlNode) -> bool:
    if n.get("player_slot") is not None:
        return True
    name = n.get("name")
    return bool(name and em.symbols.get(name) == em.player_var)


# --- end-game (win/lose tree) extraction ----------------------------------------------
def _terminal_flags(mission: Mission) -> set[str]:
    """Flags that gate an ``end_mission`` event (e.g. ``EndMisson``)."""
    flags: set[str] = set()
    for ev in mission.events:
        if any(c.tag == "end_mission" for c in ev.commands):
            for c in ev.conditions:
                if c.tag == "if_variable" and c.get("name"):
                    flags.add(c.get("name"))
    return flags


def _is_decider(ev: Event, terminal: set[str]) -> bool:
    """An event that SETS a terminal flag truthy (a win/lose deciding event), and is not
    itself the ``end_mission`` terminal."""
    if any(c.tag == "end_mission" for c in ev.commands):
        return False
    return any(c.tag == "set_variable" and c.get("name") in terminal
               and _truthy(c.get("value")) for c in ev.commands)


def _classify_outcome(ev: Event) -> str | None:
    text = (ev.name or "").lower()
    for n in ev.commands:
        if n.tag == "big_message":
            text += " " + " ".join(filter(None, (n.get("title"), n.get("subtitle1"),
                                                  n.get("subtitle2")))).lower()
    win = any(w in text for w in _WIN_WORDS)
    lose = any(w in text for w in _LOSE_WORDS)
    if win and not lose:
        return "win"
    if lose and not win:
        return "lose"
    return None


def _outcome_prose(ev: Event) -> str:
    for n in ev.commands:
        if n.tag == "big_message":
            parts = [n.get("title"), n.get("subtitle1"), n.get("subtitle2")]
            return _amd_text(" ".join(p for p in parts if p)) or True  # type: ignore[return-value]
    return True  # type: ignore[return-value]


class AmdBuilder:
    def __init__(self, mission: Mission, em: Emitter, events: list[Event] | None = None):
        self.mission = mission
        self.em = em
        # events to turn into quests/beats (comms/GM-button events are partitioned out
        # upstream and handled as //comms routes, exactly as the MAST target does).
        self.events = events if events is not None else mission.events
        self.quests: list[Quest] = []
        self.roles: list[tuple[str, str]] = []      # (mast_var, role) to add_role in @map
        self.watchers: list[tuple[str, list[XmlNode]]] = []  # (gate_label, conditions)
        self.beats: list[Event] = []                # leftover events -> background loops
        # (quest_key, [body XmlNodes]) -> a //signal/quest_completed route (reveal chain)
        self.completion_bodies: list[tuple[str, list[XmlNode]]] = []
        self._gate = 0
        # reveal graph: watcher labels deferred until their phase is reached, and the
        # phase routes that reveal+start them. Keyed by (flag, vkey) -> (vraw, [(q,label)]).
        self.deferred_gates: set[str] = set()
        self.phase_routes: dict[tuple[str, str], tuple] = {}

    def _add_role(self, var: str, role: str) -> None:
        if (var, role) not in self.roles:
            self.roles.append((var, role))

    def _new_gate(self, conditions: list[XmlNode]) -> tuple[str, str]:
        """Register an escape-hatch watcher; return (signal_name, task_label)."""
        sig = f"a2x_gate_{self._gate}"
        label = f"gate_{self._gate}"
        self.watchers.append((label, conditions))
        self._gate += 1
        return sig, label

    def _trigger_for(self, q: Quest, ev: Event, terminal: set[str]) -> None:
        """Fill a quest's completion trigger from a decider event's conditions."""
        # drop the self-guard (`if_variable <terminal> != / == v`) -- it only prevents
        # re-firing in 2.8; the quest state machine handles that.
        conds = [c for c in ev.conditions
                 if not (c.tag == "if_variable" and c.get("name") in terminal)]
        fleets = _fleet_sizes(self.mission)

        for c in conds:
            if c.tag == "if_not_exists" and _is_player_ref(self.em, c):
                # player death -> a survive/critical fail-on-death
                q.critical = True
                q.fail_on_all_dead = _PLAYER_ROLE
                if self.em.player_var:
                    self._add_role(self.em.player_var, _PLAYER_ROLE)
                return
            if c.tag == "if_not_exists" and self.em.symbols.get(c.get("name") or ""):
                role = _pyname(c.get("name")).lower()
                q.goal = f"destroy 1 {role}"
                self._add_role(self.em.symbols[c.get("name")], role)
                return
            if c.tag == "if_fleet_count" and c.get("fleetnumber"):
                fl = c.get("fleetnumber")
                q.goal = f"destroy {fleets.get(fl, 1)} fleet_{fl}"
                return
            if c.tag == "if_fleet_count" and c.get("sideValue") in ("1", None):
                # "all hostiles gone" -> diplomacy-aware, ceasefire-safe kill goal
                total = sum(fleets.values()) or 1
                q.goal = f"destroy {total} enemies"
                return

        # nothing expressible as a verb -> escape hatch (a MAST watcher emits the signal)
        expressible = [c for c in conds if _cond_bool(self.em, c) is not None]
        if expressible:
            sig, label = self._new_gate(expressible)
            q.when = f"signal {sig}"
            q.gate_label = label
        else:
            q.todos.append(f"trigger not mapped: {' '.join(_xml_one(c) for c in conds)}")

    def _extract_timed_chains(self, used_ids: set) -> set:
        """Emit EVERY linear chain of >=2 timed narrative beats as a reveal chain of
        `Complete after:` quests (bodies on //signal/quest_completed). Returns the set of
        consumed event ids. A beat = an event gated on exactly ``if_timer_finished T`` +
        ``if_variable F == n`` that advances ``F`` (2.8's timed-sequence idiom); each
        beat's wait is the timer the previous step reset (the ``<start>`` timer first)."""
        groups: dict[tuple, list] = {}
        for ev in self.events:
            info = _beat_info(ev)
            if info:
                groups.setdefault((info["F"], info["T"]), []).append((ev, info))
        consumed: set = set()
        for (fflag, timer), chain in groups.items():
            if len(chain) < 2:
                continue  # a lone timed event is handled as an objective quest instead
            chain.sort(key=lambda ei: ei[1]["n"])
            start_secs = next((n.get("seconds") for n in self.mission.start
                               if n.tag == "set_timer" and n.get("name") == timer), None)
            keys = [_quest_key(ev, used_ids) for ev, _ in chain]
            prev_secs = start_secs
            for i, (ev, info) in enumerate(chain):
                q = Quest(keys[i], ev.name or keys[i])
                q.state = "active" if i == 0 else "secret"
                if prev_secs:
                    q.complete_after = f"{prev_secs} seconds"
                else:
                    q.todos.append("timed beat: could not resolve the wait duration -- "
                                   "set `Complete after:` by hand")
                if i + 1 < len(chain):
                    q.reveal = keys[i + 1]
                q.desc = self._objective_text(ev) or q.desc
                body = [n for n in ev.commands
                        if not (n.tag == "set_timer" and n.get("name") == info["T"])
                        and not (n.tag == "set_variable" and n.get("name") == info["F"])]
                if body:
                    self.completion_bodies.append((keys[i], body))
                self.quests.append(q)
                prev_secs = info["set_timer_secs"] or prev_secs
            consumed |= {id(ev) for ev, _ in chain}
        return consumed

    def build(self) -> None:
        terminal = _terminal_flags(self.mission)
        used_ids: set = set()
        chained = self._extract_timed_chains(used_ids)  # all timed reveal chains
        for ev in self.events:
            if id(ev) in chained:
                continue  # already emitted as a reveal-chain quest
            if any(c.tag == "end_mission" for c in ev.commands) and not _is_decider(ev, terminal):
                continue  # the bare end_mission terminal is absorbed into Win:/Lose:
            if _is_decider(ev, terminal):
                key = _quest_key(ev, used_ids)
                q = Quest(key, ev.name or key)
                self._trigger_for(q, ev, terminal)
                outcome = _classify_outcome(ev)
                if outcome == "win":
                    q.win = _outcome_prose(ev)
                elif outcome == "lose":
                    q.lose = _outcome_prose(ev)
                else:
                    q.todos.append("win or lose? (end-game decider -- classify by hand)")
                q.desc = self._objective_text(ev) or q.desc
                q.title = _quest_title(ev, q)
                self.quests.append(q)
                continue
            # an event carrying a real trigger becomes an OBJECTIVE quest (its flag guards
            # fold into the trigger); pure flag-glue / continuous events stay loops.
            q = self._objective_quest(ev, used_ids, terminal)
            (self.quests.append(q) if q is not None else self.beats.append(ev))
        self._wire_reveal_graph()  # defer phase-gated watchers until their phase is reached
        # if nothing produced a real objective, still give the log a root quest
        if not any(q.goal or q.when or q.fail_on_all_dead for q in self.quests):
            root = Quest("main", "Mission")
            root.desc = _amd_text(self.mission.description) or "Complete the mission."
            root.todos.append("no auto-mapped objective -- author Goal:/Win:/Lose: by hand")
            self.quests.insert(0, root)

    def _wire_reveal_graph(self) -> None:
        """Defer each single-phase-gated objective quest until its phase is reached.

        A watcher-backed quest gated on exactly one ``F == v`` becomes ``State: secret``
        when some LATER event (not the ``<start>`` block) sets ``F = v``: its watcher is
        left OUT of the up-front schedule and a ``//signal/a2x_phase_F_v`` route reveals
        the quest + starts its watcher when the phase is reached. This turns "all watchers
        poll from t=0" into "a watcher runs only once its phase is live", and gives the
        quest log real phase structure. Multi-gate / start-produced / unproduced gates are
        left active from the start (correctness over cleverness)."""
        # which (flag, vkey) are set by the <start> block vs by a later event
        start_sets, event_sets = set(), set()
        for n in self.mission.start:
            if n.tag == "set_variable":
                k = (n.get("name"), _num_key(n.get("value")))
                if k[1] is not None:
                    start_sets.add(k)
        for ev in self.mission.events:
            for n in ev.commands:
                if n.tag == "set_variable":
                    k = (n.get("name"), _num_key(n.get("value")))
                    if k[1] is not None:
                        event_sets.add(k)
        for q in self.quests:
            if not q.gate_label or len(q.phase_gates) != 1:
                continue
            flag, vkey, vraw = q.phase_gates[0]
            key = (flag, vkey)
            if key not in event_sets or key in start_sets:
                continue  # produced at start (or never) -> leave active from t=0
            q.state = "secret"
            self.deferred_gates.add(q.gate_label)
            self.em.phase_signals.add(key)
            vraw2, items = self.phase_routes.setdefault(key, (vraw, []))
            items.append((q.key, q.gate_label))

    # -- objective quests (flag-guarded trigger events) --------------------------------
    def _dropped_guards(self, ev: Event, terminal: set) -> list:
        """`if_variable` conditions to drop from an event's trigger: the end_mission
        terminal flags, the event's OWN flags (run-once/advance bookkeeping), and
        "not-yet" latches (``!= v`` or ``== 0``). What survives is a genuine phase gate
        set by ANOTHER event, which folds into the objective's trigger watcher."""
        sets = {c.get("name") for c in ev.commands if c.tag == "set_variable"}
        out = []
        for c in ev.conditions:
            if c.tag != "if_variable":
                continue
            name = c.get("name")
            cmp = (c.get("comparator", "") or "").strip().upper()
            is_zero = (c.get("value", "") or "").strip() in ("0", "0.0")
            latch = cmp in ("NOT", "!=") or (cmp in ("EQUALS", "=") and is_zero)
            if name in terminal or name in sets or latch:
                out.append(c)
        return out

    def _objective_text(self, ev: Event) -> str:
        """Objective/description prose lifted from the event's big_message or first comms
        (2.8 has no objective text; this is a readability upgrade, not gameplay)."""
        for n in ev.commands:
            if n.tag == "big_message":
                t = _amd_text(" ".join(filter(None, (n.get("title"), n.get("subtitle1"),
                                                     n.get("subtitle2")))))
                if t:
                    return t
        for n in ev.commands:
            if n.tag == "incoming_comms_text" and n.text:
                return _amd_text(n.text[:140])
        return ""

    def _native_goal_kind(self, ev: Event, terminal: set) -> str | None:
        """'kill' / 'player' if this event's trigger is a concrete destroy/survive goal,
        else None. Mirrors the native branch of :meth:`_fill_objective`."""
        conds = [c for c in ev.conditions if c not in self._dropped_guards(ev, terminal)]
        reals = [c for c in conds if c.tag in _REAL_TRIGGER_TAGS]
        kept_flags = [c for c in conds if c.tag == "if_variable"]
        if (len(conds) == 1 and reals and reals[0].tag == "if_not_exists"
                and _is_player_ref(self.em, reals[0])):
            return "player"
        if not kept_flags and len(reals) == 1:
            c = reals[0]
            if (c.tag == "if_not_exists" and not _is_player_ref(self.em, c)
                    and self.em.symbols.get(c.get("name") or "")):
                return "kill"
            if c.tag == "if_fleet_count" and c.get("fleetnumber"):
                return "kill"
        return None

    def _objective_quest(self, ev: Event, used_ids: set, terminal: set):
        """An event -> an objective quest, or None (stays a background loop).

        Promoted only if it is a genuine objective: a concrete kill/survive goal, or a
        NARRATED event (carries big_message / comms text). A bare mechanism event -- a
        trigger with no player-facing text and no kill goal (beacon toggles, score
        bookkeeping) -- is not an objective and stays a loop."""
        if not any(c.tag in _REAL_TRIGGER_TAGS for c in ev.conditions):
            return None
        text = self._objective_text(ev)
        if not text and self._native_goal_kind(ev, terminal) is None:
            return None
        key = _quest_key(ev, used_ids)
        q = Quest(key, ev.name or key)
        self._fill_objective(q, ev, terminal)
        q.desc = text or q.desc
        q.title = _quest_title(ev, q)
        if ev.commands:
            self.completion_bodies.append((key, list(ev.commands)))
        return q

    def _fill_objective(self, q: Quest, ev: Event, terminal: set) -> None:
        dropped = self._dropped_guards(ev, terminal)
        conds = [c for c in ev.conditions if c not in dropped]
        kept_flags = [c for c in conds if c.tag == "if_variable"]
        reals = [c for c in conds if c.tag in _REAL_TRIGGER_TAGS]
        # sole player death -> a critical fail-on-death
        if (len(conds) == 1 and reals and reals[0].tag == "if_not_exists"
                and _is_player_ref(self.em, reals[0])):
            q.critical = True
            q.fail_on_all_dead = _PLAYER_ROLE
            if self.em.player_var:
                self._add_role(self.em.player_var, _PLAYER_ROLE)
            return
        # native kill goal when nothing else gates it (target existence IS the gate)
        if not kept_flags and len(reals) == 1:
            c = reals[0]
            if (c.tag == "if_not_exists" and not _is_player_ref(self.em, c)
                    and self.em.symbols.get(c.get("name") or "")):
                role = _pyname(c.get("name")).lower()
                q.goal = f"destroy 1 {role}"
                self._add_role(self.em.symbols[c.get("name")], role)
                return
            if c.tag == "if_fleet_count" and c.get("fleetnumber"):
                fl = c.get("fleetnumber")
                q.goal = f"destroy {_fleet_sizes(self.mission).get(fl, 1)} fleet_{fl}"
                return
        # otherwise a watcher ANDs the real trigger with any surviving phase-gate flags
        expr = [c for c in conds if _cond_bool(self.em, c) is not None]
        if expr:
            sig, label = self._new_gate(expr)
            q.when = f"signal {sig}"
            q.gate_label = label
            # surviving `if_variable F == v` guards are phase gates -> reveal-graph inputs
            q.phase_gates = [(c.get("name"), _num_key(c.get("value")), c.get("value"))
                             for c in kept_flags if _num_key(c.get("value")) is not None]
        else:
            q.todos.append(f"trigger not expressible: {' '.join(_xml_one(c) for c in conds)}")


import re as _re


def _beat_info(ev: Event) -> dict | None:
    """If *ev* is a timed narrative beat (exactly ``if_timer_finished T`` +
    ``if_variable F == n``, advancing ``F``), return {T, F, n, set_timer_secs}; else None."""
    if len(ev.conditions) != 2:
        return None
    tf = [c for c in ev.conditions if c.tag == "if_timer_finished"]
    iv = [c for c in ev.conditions if c.tag == "if_variable"
          and (c.get("comparator", "") or "").strip().upper() in ("EQUALS", "=")]
    if len(tf) != 1 or len(iv) != 1:
        return None
    fflag, timer = iv[0].get("name"), tf[0].get("name")
    if not any(c.tag == "set_variable" and c.get("name") == fflag for c in ev.commands):
        return None  # must advance the chain flag
    st = next((c.get("seconds") for c in ev.commands
               if c.tag == "set_timer" and c.get("name") == timer), None)
    try:
        n = float(_value(iv[0].get("value", "0")))
    except ValueError:
        return None
    return {"T": timer, "F": fflag, "n": n, "set_timer_secs": st}


def _quest_title(ev: Event, q: Quest) -> str:
    """A readable quest title. Prefer the 2.8 event name; if it is a generic
    ``event_N`` (2.8 left it unnamed), synthesize one from the objective/outcome."""
    name = (ev.name or "").strip()
    if name and not _re.fullmatch(r"event_\d+", name):
        return name
    if q.goal:
        return q.goal[:1].upper() + q.goal[1:]
    if q.fail_on_all_dead:
        return "Survive"
    if isinstance(q.win, str):
        return q.win
    if isinstance(q.lose, str):
        return q.lose
    return name or "Objective"


def _quest_key(ev: Event, used: set) -> str:
    base = _pyname(ev.name or "quest").lower().strip("_") or "quest"
    key, i = base, 1
    while key in used:
        i += 1
        key = f"{base}_{i}"
    used.add(key)
    return key


# --- assembly -------------------------------------------------------------------------
def build_amd_target(mission: Mission, em: Emitter, lib_version: str) -> dict[str, str]:
    """Build the full ``--target amd`` scaffold (files dict). Populates em.addons/notes."""
    from .convert import (_slug, _display_name, _prescan_named_objects,
                          build_script_py, build_story_json, build_description_yaml,
                          build_notes, build_button_route, build_gm_tree_routes)

    _prescan_named_objects(mission, em)
    em.addons.add("quests")  # LM quest_driver reads the granted AMD

    # Partition comms/GM-button events out to //comms routes (reuse the MAST-target
    # builders) -- exactly as convert.build_story_mast does. Only the remaining "plain"
    # events become quests/beats, so button trees don't degrade into polling loops.
    comms_btn_events: dict[str, object] = {}
    gm_btn_events: dict[str, object] = {}
    plain_events = []
    for ev in mission.events:
        cb = next((c for c in ev.conditions if c.tag == "if_comms_button"), None)
        gb = next((c for c in ev.conditions if c.tag == "if_gm_button"), None)
        if cb is not None:
            comms_btn_events.setdefault(cb.get("text", ""), ev)
        elif gb is not None:
            gm_btn_events.setdefault(gb.get("text", ""), ev)
        else:
            plain_events.append(ev)

    builder = AmdBuilder(mission, em, plain_events)
    builder.build()

    story_amd = "\n\n".join(q.render() for q in builder.quests) + "\n"
    story_mast = _build_story_mast(mission, em, builder, _slug, _display_name)
    # comms/GM buttons -> the same //comms route trees the MAST target emits.
    routes = build_button_route(
        mission, em, comms_btn_events, set_tag="set_comms_button",
        header="//comms", handler_tag="if_comms_button",
        comment="# 2.8 comms buttons -> a //comms route (refine the gating/selection).",
        addons=["comms"])
    routes += build_gm_tree_routes(mission, em, gm_btn_events)
    if routes:
        story_mast += "\n".join(routes) + "\n"

    notes = build_notes(mission, em)
    notes += ("\n## AMD target\n"
              f"- Emitted {len(builder.quests)} quest(s) to story.amd "
              f"({sum(1 for q in builder.quests if q.win)} win / "
              f"{sum(1 for q in builder.quests if q.lose)} lose).\n"
              f"- {len(builder.watchers)} escape-hatch watcher(s), "
              f"{len(builder.beats)} background beat(s) kept as MAST loops.\n"
              "- Review each quest's Goal/Win/Lose and the synthesized objective prose; "
              "see docs/amd_target.md.\n")

    return {
        "story.amd": story_amd,
        "story.mast": story_mast,
        "script.py": build_script_py(mission),
        "story.json": build_story_json(em, lib_version),
        "description.yaml": build_description_yaml(mission),
        "MIGRATION_NOTES.md": notes,
        "__lib__.json": '{"version": "' + lib_version + '"}\n',
    }


def _build_story_mast(mission, em, builder, _slug, _display_name) -> str:
    label = _slug(mission.name)
    disp = _display_name(mission)
    L: list[str] = [
        f"# Migrated from {mission.source_path.split('/')[-1]} by arme2cosmos (--target amd).",
        "# The quest tree lives in story.amd; this task spawns, tags roles, and grants it.",
        "# Positions use 2.8 coords; a2x_* helpers flip them to Cosmos internally.",
        "",
        "PLAYER_CREATE_DEFAULT = False",
        "",
        f'@map/{label} "{disp}"',
    ]
    for d in mission.description.replace("^", " ").split("\n"):
        d = d.strip()
        if d:
            L.append(f'" {d}')
    L.append("    shared main_story_task = mast_task")

    obj_vars = sorted(set(em.symbols.values()) | ({em.player_var} if em.player_var else set()))
    if obj_vars:
        L.append("    # objects forward-declared (shared so routes/watchers resolve them)")
        L += [f"    shared {v} = None" for v in obj_vars]
    flag_vars = sorted({_pyname(n.get("name")) for n in mission.all_nodes()
                        if n.tag in ("set_variable", "if_variable") and n.get("name")})
    flag_vars = [f for f in flag_vars if f not in obj_vars]
    if flag_vars:
        L.append("    # event flags forward-declared (shared, default 0)")
        L += [f"    default shared {v} = 0" for v in flag_vars]
    L.append("")

    L.append("    # --- start block ---")
    for n in mission.start:
        L.append(f"    # {_xml_one(n)}")
        L.extend(em.emit_command(n))
    L.append("")

    if builder.roles:
        L.append("    # --- tag quest-target roles (the story.amd Goal/Fail lines name these) ---")
        for var, role in builder.roles:
            L.append(f'    add_role({var}, "{role}")')
        L.append("")

    L.append("    # --- grant the AMD quest tree (LM quest_driver takes over win/lose) ---")
    L.append('    quest_grant_amd(SHARED, document_get_amd_file('
             'get_mission_dir_filename("story.amd"), data_parser=amd_quest_data))')
    L.append("")

    active_watchers = [gl for gl, _c in builder.watchers if gl not in builder.deferred_gates]
    if active_watchers or builder.beats:
        L.append("    # --- start non-deferred watchers + background beats "
                 f"({len(builder.deferred_gates)} watcher(s) deferred to phase routes) ---")
        for gl in active_watchers:
            L.append(f"    task_schedule({gl})")
        for i, _ev in enumerate(builder.beats):
            L.append(f"    task_schedule(beat_{i})")
        L.append("")
    L.append("    ->END")
    L.append("")

    # reveal graph: when a phase flag reaches its value, reveal the quests gated on it and
    # start their (until-now-dormant) watchers. Fed by the phase signal emitted in
    # c_set_variable wherever that flag is set (a body / beat / another quest).
    for (flag, vkey), (vraw, items) in builder.phase_routes.items():
        sig = _phase_sig_name(flag, vkey)
        keys = [k for k, _ in items]
        L.append(f"//signal/{sig}   # phase {flag} == {vraw} reached -> reveal + start")
        L.append(f"    quest_reveal(SHARED, {keys!r})")
        for _k, gl in items:
            L.append(f"    task_schedule({gl})")
        L.append("    ->END")
        L.append("")

    # escape-hatch watchers: poll a non-verb condition, then advance the quest whose
    # `When: signal a2x_<gl>` (on_signal) matches. The LM quest_driver dispatches
    # on_signal via //shared/signal/quest_signal reading SIGNAL_NAME -- so the trigger
    # is signal_emit("quest_signal", {SIGNAL_NAME: ...}), NOT a bare signal_emit.
    for gl, conds in builder.watchers:
        L.append(f"=== {gl}   # escape hatch -> quest_signal a2x_{gl}")
        bools = [b for b in (_cond_bool(em, c) for c in conds) if b]
        L.append(f"---{gl}_loop")
        L.append("    await delay_sim(0.5)")
        if bools:
            L.append(f"    jump {gl}_loop if not ({' and '.join(bools)})")
        L.append(f'    signal_emit("quest_signal", {{"SIGNAL_NAME": "a2x_{gl}"}})')
        L.append("    ->END")
        L.append("")

    # reveal-chain beat bodies: run when the timed quest completes (the AMD
    # `Complete after:` fires quest_completed; the body is the 2.8 beat's payload).
    for key, body in builder.completion_bodies:
        L.append(f'//signal/quest_completed if QUEST_ID == "{key}"   # timed beat body')
        for n in body:
            L.append(f"    # {_xml_one(n)}")
            L.extend(em.emit_command(n))
        L.append("    ->END")
        L.append("")

    # background narrative beats: leftover events kept as re-firing polling loops
    # (timed comms beats etc. -- no AMD verb; see docs/amd_target.md).
    for i, ev in enumerate(builder.beats):
        L.append(f"=== beat_{i}   # {ev.name}")
        bools, unhandled = [], []
        for c in ev.conditions:
            b = _cond_bool(em, c)
            (bools.append(b) if b else unhandled.append(c))
        for c in unhandled:
            L.append(f"    # when (verify by hand): {_xml_one(c)}")
        L.append(f"---beat_{i}_loop")
        L.append("    await delay_sim(0.5)")
        if bools:
            L.append(f"    jump beat_{i}_loop if not ({' and '.join(bools)})")
        for n in ev.commands:
            L.append(f"    # {_xml_one(n)}")
            L.extend(em.emit_command(n))
        L.append("    ->END")
        L.append("")

    return "\n".join(L) + "\n"
