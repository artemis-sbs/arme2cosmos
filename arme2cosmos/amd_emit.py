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

import re

from .emit import (Emitter, emit_condition, _cond_bool, _pyname, _mast_str, _value,
                   _num_key, _phase_sig_name, _SIDE, _is_less, to_ascii)
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
    """Source node -> provenance comment, ASCII-folded (see convert._xml_one)."""
    attrs = " ".join(f'{k}="{to_ascii(v)}"' for k, v in n.attrib.items())
    return f"<{n.tag} {attrs}/>"


# --- quest model ----------------------------------------------------------------------
class Quest:
    """One AMD quest fence + the MAST side-effects it implies (roles, watchers)."""

    def __init__(self, key: str, title: str):
        self.key = key
        self.title = title
        self.scope = "shared"
        self.state = "active"
        self.goal: str | None = None      # `Done when: destroy 1 bad_alien`
        self.when: str | None = None       # `Starts when: signal a2x_gate_0`
        self.complete_after: str | None = None  # `Complete after: 60 seconds` (timed beat)
        self.reveal: str | None = None     # `Then: reveal <key>` (reveal chain)
        self.gate_label: str | None = None  # its escape-hatch watcher label (if Starts when: signal)
        self.phase_gates: list = []         # [(flag, vkey, vraw)] surviving phase-gate flags
        self.parent: str | None = None      # `Parent: <key>` (mission-tree aggregation)
        self.required = False               # `Required: true` (parent needs this child)
        self.body_signal = "quest_succeeded"  # completion-body route: driver ANNOUNCEMENT
        self.protect_name: str | None = None  # friendly protect target -> "Protect <name>"
        self.critical = False
        self.fail_on_all_dead: str | None = None
        self.fail_on_signal: str | None = None  # `Fail on signal: <sig>` (protect watcher)
        self.win: str | bool | None = None   # prose reason, True (bare flag), or None
        self.lose: str | bool | None = None
        self.desc = ""
        self.show = "always"     # when this is LISTED in the quest log
        # The screenplay word for what this record IS. `Beat` / `Arc` already imply
        # their own `Show:`, so the noun replaces the field for the common cases and
        # the file reads as a script rather than a config.
        self.kind: str | None = None
        self.todos: list[str] = []
        # The RAW 2.8 event name. `title` gets rewritten by _quest_title for readability,
        # but the original is what carries the author's grouping ("Ramscoop Begin 1").
        self.source_name = title

    def render(self) -> str:
        out = [f"# [{_amd_text(self.title)}]({self.key})", "---"]
        implied = _IMPLIED_BY_KIND.get(self.kind or "", {})
        if self.kind:
            out.append(self.kind)          # the kind line is the FIRST line of a fence
        # Write a field only where the record DIFFERS from what its noun already says.
        if implied.get("scope") != self.scope:
            out.append(f"Scope: {self.scope}")
        # WHEN IT ARMS, in one field. `At start: hidden/running` said the same thing in a
        # second vocabulary; the trigger it used to compete with now lives in `Done when:`
        # where the driver was reading it all along.
        at_start = _AT_START.get(self.state, self.state)
        if implied.get("state") != at_start:
            out.append("Starts when: %s" % _ARMS.get(at_start, at_start))
        if self.goal:
            out.append(f"Done when: {self.goal}")
        if self.when:
            # The gate that advances this record. It went in `Starts when:` and was read
            # as an advancement trigger anyway - the two labels wrote the SAME key. Say
            # the one that is true. (A record carrying both keeps the gate in
            # `Starts when:`, which is exactly where a real start trigger would go.)
            out.append(f"{'Starts when' if self.goal else 'Done when'}: {self.when}")
        if self.complete_after:
            out.append(f"Done when: {self.complete_after}")   # a time is a trigger
        if self.reveal:
            out.append(f"Then: reveal {self.reveal}")
        if self.parent:
            out.append(f"Part of: {self.parent}")
        if self.required:
            out.append("Required: true")
        if self.critical:
            out.append("Fatal: true")
        # One grammar for all three life-cycle questions.
        if self.fail_on_all_dead:
            out.append(f"Fails when: all dead {self.fail_on_all_dead}")
        if self.fail_on_signal:
            out.append(f"Fails when: signal {self.fail_on_signal}")
        # ...and only spell `Show:` out when the noun does not already say it.
        if self.show and self.show != "always" and implied.get("show") != self.show:
            out.append(f"Show: {self.show}")
        for label, val in (("Win", self.win), ("Lose", self.lose)):
            if val is True:
                out.append(f"{label}: true")
            elif isinstance(val, str) and val:
                out.append(f"{label}: {_amd_text(val)}")
        out.append("---")
        out.append(self.desc or f"{self.title}.")
        out += [f"// TODO {t}" for t in self.todos]
        return "\n".join(out)


def _join_names(names: list) -> str:
    """['A'] -> 'A'; ['A','B'] -> 'A and B'; ['A','B','C'] -> 'A, B and C'."""
    names = [n for n in names if n]
    if len(names) <= 1:
        return names[0] if names else ""
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _amd_text(s: str) -> str:
    """One-line, ASCII-safe text for an AMD heading/value (engine text is ASCII-only).

    "ASCII-safe" was the claim; :func:`to_ascii` is what makes it true. A single byte the
    engine's cp1252 read cannot decode fails the whole document load.
    """
    s = to_ascii(s).replace("^", " ").replace("\r", " ").replace("\n", " ")
    s = s.replace("[", "(").replace("]", ")")  # keep link syntax unambiguous
    return " ".join(s.split()).strip()


def _arc_title(flag: str, vraw: str, is_sequence: bool = False) -> str:
    """A 2.8 phase flag -> a readable arc title.

    Humanising the flag is accurate for every gate and often genuinely good, because 2.8
    authors named these things: `chapter` -> "Chapter 3", `Hostage_Mission` -> "Hostage
    Mission 5", `Decision` -> "Decision", `Bonus_3` -> "Bonus 3".

    The VALUE is appended only when `is_sequence` - the flag takes more than one value
    somewhere in the MISSION, so the number means "which one". A flag used at a single
    value is the arc's whole identity and reads better without a 2.8 state number stuck
    on the end ("Decision", not "Decision 2").
    """
    words = " ".join(w for w in re.split(r"[_\s]+", str(flag).strip()) if w)
    title = " ".join(w if w.isupper() else w.capitalize() for w in words.split())
    v = str(vraw).strip()
    if v.endswith(".0"):
        v = v[:-2]
    if not (is_sequence and v) or title.rstrip().endswith(v):
        return title
    return f"{title} {v}"


# --- fleet / object helpers -----------------------------------------------------------
def _fleet_sizes(mission: Mission) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for n in mission.all_nodes():
        if n.tag == "create" and n.get("fleetnumber"):
            fl = n.get("fleetnumber")
            sizes[fl] = sizes.get(fl, 0) + 1
    return sizes


def _quest_role(name: str) -> str:
    """A 2.8 object name -> the role the tool BOTH tags in story.mast and names in a
    story.amd trigger. The two must be the same string, and naively they were not.

    The AMD trigger grammar singularizes a role token so an author can write the plural
    they'd say out loud (`destroy 6 raiders` -> the `raider` role; see
    `amd_quest._resolve_role`). It applies that to a proper noun too, and the driver
    matches with `has_role`, which is exact. So a 2.8 ship called `Nimbus` produced
    `Done when: destroy 1 nimbus` against a role tagged `nimbus` -- and the driver went
    looking for `nimbu`. The objective could never complete, silently. Nine of them
    across the reference corpus (Nimbus, Archimedes, Nautilus, Nemesis, Rendevous), in
    six missions.

    No token resolves BACK to a role ending in a lone `s`, so the fix has to be in the
    role: a name that would be mangled gets an explicit `_target` suffix. That reads as
    itself in both files, and -- unlike emitting the mangled `archimede` -- it is not
    something a human reading story.amd will "correct" straight back into a broken one.
    """
    role = _pyname(name).lower()
    if role.endswith("s") and not role.endswith("ss"):
        role += "_target"
    return role


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


def _terminal_gates(mission: Mission) -> list[tuple]:
    """The ``(flag, comparator, value)`` conditions that gate an ``end_mission`` -- the flag
    VALUES that actually end the mission. A real decider must drive one of these true (a
    phase counter that merely advances -- e.g. Event1=3 when the end needs Event1>=19 -- is
    setup, not a decider)."""
    gates: list[tuple] = []
    for ev in mission.events:
        if any(c.tag == "end_mission" for c in ev.commands):
            for c in ev.conditions:
                if c.tag == "if_variable" and c.get("name"):
                    gates.append((c.get("name"), c.get("comparator", "EQUALS"), c.get("value")))
    return gates


def _satisfies(comparator: str, set_val, gate_val) -> bool:
    """Does setting a flag to ``set_val`` satisfy a ``comparator gate_val`` end gate?"""
    try:
        s, g = float(set_val), float(gate_val)
    except (TypeError, ValueError):
        return str(set_val) == str(gate_val)
    return {
        "EQUALS": s == g, "NOT_EQUALS": s != g,
        "GREATER": s > g, "GREATER_EQUAL": s >= g,
        "LESS": s < g, "LESS_EQUAL": s <= g,
    }.get(comparator or "EQUALS", s == g)


def _is_decider(ev: Event, gates: list[tuple]) -> bool:
    """An event that drives a terminal end-gate true (a win/lose deciding event), and is not
    itself the ``end_mission`` terminal. Only counts a set_variable that SATISFIES the gate's
    value -- so a phase counter merely advancing (Event1=3 vs end at Event1>=19) is not a
    decider."""
    if any(c.tag == "end_mission" for c in ev.commands):
        return False
    for c in ev.commands:
        if c.tag != "set_variable":
            continue
        for name, comp, val in gates:
            if c.get("name") == name and _satisfies(comp, c.get("value"), val):
                return True
    return False


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


# What each screenplay noun already implies (mirrors amd_schema._KIND_DEFAULTS). A
# record that says `Beat` is the whole crew's and already running, so writing those
# again is ceremony - it was over half of every field line the corpus emitted.
# `At start:` in the author's words - the machine words (active/secret/idle) are still
# accepted by the reader, but nothing needs to WRITE them any more.
_AT_START = {"active": "running", "secret": "hidden", "idle": "offered"}

# ...and how each of those is SAID as an arming trigger.
_ARMS = {"running": "at once", "hidden": "revealed", "offered": "accepted"}

_IMPLIED_BY_KIND = {
    "Objective": {"scope": "shared", "state": "running"},
    "Beat": {"show": "when done", "scope": "shared", "state": "running"},
    "Cue":  {"show": "never",     "scope": "shared", "state": "running"},
    "Arc":  {"show": "with children", "scope": "shared", "state": "running"},
}


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
        # (quest_key, [body XmlNodes], driver_signal) -> a //signal/<driver_signal> route
        # carrying the event body (driver_signal is quest_completed, or quest_failed for a
        # protect objective whose body is a penalty).
        self.completion_bodies: list[tuple[str, list[XmlNode], str]] = []
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
                role = _quest_role(c.get("name"))
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
        `Complete after:` quests (bodies on //shared/signal/quest_succeeded). Returns the set of
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
                    # unknown wait -> fall back to a MAST timer watcher (the same
                    # if_timer_finished polling the MAST target uses): complete this beat when
                    # its own conditions fire, via a gate signal. Consistent with MAST, no TODO.
                    conds = [c for c in ev.conditions if _cond_bool(self.em, c) is not None]
                    if conds:
                        sig, label = self._new_gate(conds)
                        q.when = f"signal {sig}"
                        q.gate_label = label
                    else:
                        q.todos.append("timed beat: could not resolve the wait -- "
                                       "set a trigger by hand")
                if i + 1 < len(chain):
                    q.reveal = keys[i + 1]
                q.desc = self._objective_text(ev) or q.desc
                body = [n for n in ev.commands
                        if not (n.tag == "set_timer" and n.get("name") == info["T"])
                        and not (n.tag == "set_variable" and n.get("name") == info["F"])]
                if body:
                    self.completion_bodies.append((keys[i], body, "quest_succeeded"))
                self.quests.append(q)
                prev_secs = info["set_timer_secs"] or prev_secs
            consumed |= {id(ev) for ev, _ in chain}
        return consumed

    def build(self) -> None:
        terminal = _terminal_flags(self.mission)   # names -> self-guard drop in _trigger_for
        gates = _terminal_gates(self.mission)      # value-specific -> real end-deciders only
        used_ids: set = set()
        chained = self._extract_timed_chains(used_ids)  # all timed reveal chains
        for ev in self.events:
            if id(ev) in chained:
                continue  # already emitted as a reveal-chain quest
            if any(c.tag == "end_mission" for c in ev.commands) and not _is_decider(ev, terminal):
                continue  # the bare end_mission terminal is absorbed into Win:/Lose:
            if _is_decider(ev, gates):
                key = _quest_key(ev, used_ids)
                q = Quest(key, ev.name or key)
                self._trigger_for(q, ev, terminal)
                outcome = _classify_outcome(ev)
                if outcome == "win":
                    q.win = _outcome_prose(ev)
                elif outcome == "lose":
                    q.lose = _outcome_prose(ev)
                else:
                    # Neither target distinguishes win/lose -- the mission just ends
                    # (end_mission -> show_game_results, same in the MAST target). Leave the
                    # decider quest neutral (no blocking story.amd TODO, matching MAST);
                    # surface the optional enrichment in MIGRATION_NOTES instead.
                    self.em.note(f"AMD: end-decider '{ev.name}' left neutral -- the mission "
                                 f"just ends (as the MAST target does); optionally add "
                                 f"Win:/Lose: to its story.amd quest to enrich the log")
                q.desc = self._objective_text(ev) or q.desc
                q.title = _quest_title(ev, q)
                self.quests.append(q)
                continue
            # an event carrying a real trigger becomes an OBJECTIVE quest (its flag guards
            # fold into the trigger); a pure-flag NARRATED event becomes a STORY BEAT quest
            # (a story moment in the log); pure flag-glue / continuous events stay loops.
            q = self._objective_quest(ev, used_ids, terminal) \
                or self._story_beat_quest(ev, used_ids, terminal)
            (self.quests.append(q) if q is not None else self.beats.append(ev))
        self._wire_reveal_graph()  # defer phase-gated watchers until their phase is reached
        self._aggregate_kills(used_ids)  # roll per-ship kills under one Parent quest
        # AFTER the reveal graph (it fills phase_routes, whose reveal lists must be
        # re-keyed) and AFTER kill aggregation (so the synthetic fleet parent is grouped
        # like any other quest).
        self._assign_show()          # decide what is LISTED before anything is nested
        self._group_name_families(used_ids)
        # if nothing produced a real objective, still give the log a root quest
        if not any(q.goal or q.when or q.fail_on_all_dead or q.fail_on_signal
                   or q.win or q.lose or q.complete_after for q in self.quests):
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
            if len(q.phase_gates) != 1:
                continue  # (watcher objectives AND story beats carry a single phase gate)
            flag, vkey, vraw = q.phase_gates[0]
            key = (flag, vkey)
            if key not in event_sets or key in start_sets:
                continue  # produced at start (or never) -> leave active from t=0
            q.state = "secret"
            if q.gate_label:                       # a watcher objective -> also start it
                self.deferred_gates.add(q.gate_label)
            self.em.phase_signals.add(key)
            vraw2, items = self.phase_routes.setdefault(key, (vraw, []))
            items.append((q.key, q.gate_label))    # gate_label is None for a story beat

    def _aggregate_kills(self, used_ids: set) -> None:
        """Roll the per-ship ``Goal: destroy 1 <role>`` objectives under one synthetic
        Parent quest, so a fleet of individual kills reads as one mission objective in the
        log (the parent completes when every child does). Only when there are >=3 -- fewer
        isn't worth a parent. Left as a flat aggregate: which kills are optional, and
        whether clearing the fleet WINS, are per-mission decisions (flagged as a TODO)."""
        kills = [q for q in self.quests if q.goal and q.goal.startswith("destroy 1 ")]
        if len(kills) < 3:
            return
        pkey = "hostile_fleet"
        while pkey in used_ids:
            pkey += "_x"
        used_ids.add(pkey)
        parent = Quest(pkey, "Destroy the hostile fleet")
        parent.desc = "Destroy every hostile vessel."
        # The kill Goal is real; whether clearing the fleet WINS is win/lose enrichment the
        # MAST target does not make either -- leave it neutral (no blocking story.amd TODO)
        # and note the optional enrichment in MIGRATION_NOTES.
        self.em.note("AMD: auto-grouped kill objectives under 'Destroy the hostile fleet' -- "
                     "optionally add Win: (if clearing the fleet wins) or split out optional targets.")
        for q in kills:
            q.parent = pkey
            q.required = True
        self.quests.insert(0, parent)

    # 2.8 commands that SAY something to the crew - the mark of a story beat rather
    # than pure bookkeeping.
    NARRATIVE_TAGS = {"incoming_comms_text", "big_message", "warning_popup_message"}

    def _assign_show(self) -> None:
        """Decide WHEN each quest is listed in the log (`Show:`).

        A converted 2.8 event is a timeline step whether or not a player can act on it,
        and the quest system is right to model them alike - but the LOG is a different
        surface. HamakSector listed 48 rows for 5 real objectives, so the crew read the
        whole story up front.

        Three cases, all derivable here:
          * a real trigger verb (destroy / reach / dock / scan ...) -> `always`.
            Something the crew can DO: a to-do, listed from the start.
          * the body says something to the crew -> `when done`. A story beat: it runs
            unseen and appears once it RESOLVES, where it reads as history. Nearly all
            beats qualify (hamaksector 59/70, cruiser 284/284), so the history is real
            content rather than noise.
          * the body only sets flags / moves objects / arms timers -> `never`. Pure
            machinery ("Play SPFX"), which should drive its event invisibly.
        """
        VERBS = ("destroy", "kill", "collect", "recover", "gather", "scan", "survey",
                 "dock", "reach", "travel")
        says = {}
        for key, body, _sig in self.completion_bodies:
            says[key] = says.get(key, False) or any(n.tag in self.NARRATIVE_TAGS for n in body)
        for q in self.quests:
            if q.goal and any(q.goal.lower().startswith(v) for v in VERBS):
                q.show = "always"          # a player objective
                q.kind = "Objective"       # ...the crew's, and live from the start
            elif q.win or q.lose or q.fail_on_all_dead or q.fail_on_signal:
                q.show = "always"          # end-game / protect objectives stay visible
                q.kind = "Objective"
            elif says.get(q.key):
                q.show = "when done"       # a story beat -> history
                q.kind = "Beat"
            else:
                q.show = "never"           # bookkeeping
                q.kind = "Cue"             # a stage direction: it happens, unseen

    # -- arcs (name families -> a container quest with its members nested under it) ----
    ARC_MIN = 3          # a family of 1-2 is not a group; wrapping it groups nothing
    CATCHALL = "Other"   # everything that belongs to no family

    def _group_name_families(self, used_ids: set) -> None:
        """Nest quests under a container ARC per 2.8 event-name FAMILY, so the Quests tab
        reads as a tree instead of one flat list the crew can read ahead.

        The 2.8 author did the grouping already, in the event names: HamakSector has 17
        "Ramscoop *" events in ordered runs ("Begin 1/2/3", "25%/50%/75%", "Installed
        1/2/3"), 19 "Tachyon *", 18 "Haynes *". Across the corpus that is 282 families
        covering a median 78% of a mission's events - by far the broadest signal, and the
        only one that reaches the quests a player can actually SEE.

        Chapter comments were measured and rejected: exactly ONE mission of 29 uses them
        (HamakSector's "Chapter 1, wherein..."). Phase flags were tried first and are the
        wrong axis - they only ever group quests the gate was ALREADY keeping secret, so
        the visible list did not change at all. Phase gates still drive REVEAL; grouping
        and reveal are orthogonal (where a quest sits vs when it appears).

        Families are NOT nested under chapters even where both exist: 5 of HamakSector's
        55 families straddle a chapter boundary (Ramscoop runs through 1 and 3), and
        splitting a family in two reads worse than having no outer level.

        The quest system does the rest, unchanged: nested `arc/step` keys render indented,
        a SECRET row hides its whole subtree, and quest_reeval_tree_parent completes the
        arc when every member is done. Containers carry no trigger of their own.
        """
        fams: dict[str, list] = {}
        for q in self.quests:
            word = (q.source_name or "").split()
            fams.setdefault(word[0] if word else "", []).append(q)

        groups: list[tuple[str, str, list]] = []      # (key-stem, title, members)
        loose: list = []
        for prefix, members in fams.items():
            if prefix and len(members) >= self.ARC_MIN:
                groups.append((_pyname(prefix), prefix, members))
            else:
                loose.extend(members)
        # Everything with no family of its own goes in one catch-all rather than sitting
        # loose beside the groups, so the log has no ragged top level.
        if len(loose) >= self.ARC_MIN:
            groups.append((_pyname(self.CATCHALL), self.CATCHALL, loose))
        if not groups:
            return

        rekey: dict[str, str] = {}
        arcs: list[Quest] = []
        for stem, title, members in groups:
            akey = f"fam_{stem}"
            while akey in used_ids:
                akey += "_x"
            used_ids.add(akey)
            arc = Quest(akey, title)
            # Visible as soon as ANY member is - an all-secret family stays hidden, so a
            # container cannot spoil a chapter by naming it before anything has happened.
            arc.state = "secret" if all(m.state == "secret" for m in members) else "active"
            # A container is a HEADING, not a job: `with children` gives it a row only
            # while something under it is listed, so a family whose beats are all still
            # running (`Show: when done`) does not sit there naming a thread that has
            # not happened yet. Declared rather than left to the renderer to infer,
            # because a hand-authored multi-step JOB also has children and must stay
            # visible - it is the thing the player accepts.
            arc.show = "with children"
            arc.kind = "Arc"
            arc.desc = f"{title} events."
            arc.todos.append("name this group (auto-named from the 2.8 event names)")
            arcs.append(arc)
            for m in members:
                rekey[m.key] = f"{akey}/{m.key}"

        # Re-point EVERY reference: QUEST_ID is the full '/'-path, so a stale flat key
        # silently matches nothing (the same class of bug as listening on the wrong signal).
        for q in self.quests:
            if q.key in rekey:
                q.key = rekey[q.key]
            if q.reveal in rekey:
                q.reveal = rekey[q.reveal]
            if q.parent in rekey:
                q.parent = rekey[q.parent]
        self.completion_bodies = [(rekey.get(k, k), body, sig)
                                  for k, body, sig in self.completion_bodies]
        for key, (vraw, items) in list(self.phase_routes.items()):
            self.phase_routes[key] = (vraw, [(rekey.get(k, k), lbl) for k, lbl in items])
        self.quests = arcs + self.quests
        self.em.note(f"AMD: grouped {len(rekey)} quest(s) into {len(arcs)} group(s) from the "
                     f"2.8 event names - rename them in story.amd (each carries a TODO).")

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

    def _reach_trigger(self, conds: list) -> tuple | None:
        """A player-approaches-object ``if_distance`` (LESS) -> (role, radius) for a
        ``Goal: reach``; else None. One side must be the player, the other a captured
        object (the landmark to reach); the object is tagged with a role."""
        for c in conds:
            if c.tag != "if_distance" or not _is_less(c.get("comparator")):
                continue
            pv = self.em.player_var
            p1 = c.get("player_slot1") is not None or self.em.symbols.get(c.get("name1")) == pv
            p2 = c.get("player_slot2") is not None or self.em.symbols.get(c.get("name2")) == pv
            target = None
            if p1 and self.em.symbols.get(c.get("name2")):
                target = c.get("name2")
            elif p2 and self.em.symbols.get(c.get("name1")):
                target = c.get("name1")
            if target:
                role = _quest_role(target)
                self._add_role(self.em.symbols[target], role)
                try:
                    radius = int(float(c.get("value", "5000")))
                except ValueError:
                    radius = 5000
                return role, radius
        return None

    def _target_side(self, name: str | None) -> str | None:
        """The Cosmos side ('enemy'/'friendly'/'neutral') of a named 2.8 object, from its
        create node's sideValue; None if unknown."""
        if not name:
            return None
        for n in self.mission.all_nodes():
            if n.tag == "create" and n.get("name") == name:
                return _SIDE.get((n.get("sideValue") or "").strip())
        return None

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

    def _killable(self, c: XmlNode) -> str | None:
        """The captured non-player, non-sentinel object an ``if_not_exists`` targets, else
        None. 2.8 uses ``if_not_exists name="."`` / ``".."`` as an always-true guard (no
        object has that name), so a pure-punctuation name is not a kill target."""
        name = c.get("name")
        if c.tag != "if_not_exists" or _is_player_ref(self.em, c) or not name:
            return None
        if not any(ch.isalnum() for ch in name):
            return None  # "." / ".." sentinel (2.8 always-true idiom)
        return name if self.em.symbols.get(name) else None

    def _kill_target_names(self, ev: Event, terminal: set) -> list:
        """Captured non-player objects whose destruction this event tests (if_not_exists)."""
        conds = [c for c in ev.conditions if c not in self._dropped_guards(ev, terminal)]
        return [self._killable(c) for c in conds if self._killable(c)]

    def _objective_kind(self, ev: Event, terminal: set) -> str | None:
        """The player-facing objective kind of this event, or None (mechanism / glue):
        'player' (own death), 'kill'/'protect' (a captured object's destruction -- any
        count, phase-gated ok), 'reach' (player approaches an object), or 'dock'. A bare
        property/exists/timed trigger is NOT an objective unless the event is narrated."""
        conds = [c for c in ev.conditions if c not in self._dropped_guards(ev, terminal)]
        if any(c.tag == "if_not_exists" and _is_player_ref(self.em, c) for c in conds):
            return "player"
        for c in conds:
            if self._killable(c):
                return "protect" if self._target_side(c.get("name")) in ("friendly", "neutral") else "kill"
            if c.tag == "if_fleet_count" and c.get("fleetnumber"):
                return "kill"
        if self._reach_trigger(conds) is not None:
            return "reach"
        if any(c.tag == "if_docked" for c in conds):
            return "dock"
        return None

    def _objective_quest(self, ev: Event, used_ids: set, terminal: set):
        """An event -> an objective quest, or None (stays a background loop).

        Promoted if it is a genuine objective -- a kill / protect / reach / dock / survive
        goal (see :meth:`_objective_kind`), OR a NARRATED event (big_message / comms). A
        bare mechanism event (a property/exists/timed trigger with no player-facing text
        and no objective kind -- spawn triggers, score bookkeeping) stays a loop."""
        if not any(c.tag in _REAL_TRIGGER_TAGS for c in ev.conditions):
            return None
        text = self._objective_text(ev)
        kind = self._objective_kind(ev, terminal)
        if not text and kind is None:
            return None
        key = _quest_key(ev, used_ids)
        q = Quest(key, ev.name or key)
        self._fill_objective(q, ev, terminal)
        q.desc = text or q.desc
        # an un-narrated multi/gated KILL that didn't get a native Goal (watcher form) --
        # synthesize a readable "Destroy A and B" title from the targets instead of the
        # (often mechanism-flavored) 2.8 event name.
        names = self._kill_target_names(ev, terminal) if (not text and kind == "kill" and not q.goal) else []
        if names:
            q.title = "Destroy " + _amd_text(_join_names(names))
            q.desc = q.desc or (q.title + ".")
        else:
            q.title = _quest_title(ev, q)
        if ev.commands:
            self.completion_bodies.append((key, list(ev.commands), q.body_signal))
        return q

    def _story_beat_quest(self, ev: Event, used_ids: set, terminal: set):
        """A pure-flag NARRATED event (no real trigger, but carries big_message / comms)
        -> a story-beat quest: a story moment that appears in the log. It is revealed when
        its gating flag is reached (reveal graph, like a phase-gated objective), fires its
        narrative on activation (``quest_activated``), and auto-clears a few seconds later
        so the log advances. Its own ``set_variable`` reveals the next beat -- so a 2.8
        flag-chained narrative sequence reads as a chain of story beats. Un-narrated
        pure-flag events (glue) return None and stay background loops."""
        if any(c.tag in _REAL_TRIGGER_TAGS for c in ev.conditions):
            return None  # has a trigger -> an objective, not a bare story beat
        text = self._objective_text(ev)
        if not text:
            return None  # not narrated -> flag glue, stays a loop
        # its single positive phase gate (revealed when a LATER event sets it). A beat with
        # 0 gates is an intro (active from start); with >1 the reveal graph can't defer it
        # (it would fire prematurely) -> leave it a loop.
        gates = [(c.get("name"), _num_key(c.get("value")), c.get("value"))
                 for c in ev.conditions if c.tag == "if_variable"
                 and (c.get("comparator", "") or "").strip().upper() in ("EQUALS", "=")
                 and _num_key(c.get("value")) is not None and c.get("name") not in terminal]
        if len(gates) > 1:
            return None
        key = _quest_key(ev, used_ids)
        q = Quest(key, ev.name or key)
        q.desc = text
        q.title = _quest_title(ev, q)
        q.phase_gates = gates
        # A story beat is displayed, then a few seconds later fires its narrative body
        # (comms / big_message + its set_variable, which reveals the next beat) and clears.
        # Body on quest_completed (Complete after drives it) -- quest_reveal/mark_active
        # does NOT emit quest_activated, so an activation-body would never fire.
        q.complete_after = "5 seconds"
        if ev.commands:
            self.completion_bodies.append((key, list(ev.commands), "quest_succeeded"))
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
            if self._killable(c):
                name = c.get("name")
                role = _quest_role(name)
                self._add_role(self.em.symbols[name], role)
                if self._target_side(name) in ("friendly", "neutral"):
                    # destroying a friendly/neutral object is a LOSS/penalty, not a goal:
                    # a PROTECT objective that FAILS when it dies (body on quest_failed).
                    q.fail_on_all_dead = role
                    q.body_signal = "quest_failed_done"
                    q.protect_name = name
                else:
                    q.goal = f"destroy 1 {role}"
                return
            if c.tag == "if_fleet_count" and c.get("fleetnumber"):
                fl = c.get("fleetnumber")
                q.goal = f"destroy {_fleet_sizes(self.mission).get(fl, 1)} fleet_{fl}"
                return
        # native reach goal: player approaches a captured object (2.8 if_distance LESS),
        # not phase-gated -> `Goal: reach <role> <radius>` (quest_tick_reach completes it)
        if not kept_flags:
            reach = self._reach_trigger(conds)
            if reach is not None:
                role, radius = reach
                q.goal = f"reach {role} {radius}"
                return
        # otherwise a watcher ANDs the real trigger with any surviving phase-gate flags
        expr = [c for c in conds if _cond_bool(self.em, c) is not None]
        if expr:
            sig, label = self._new_gate(expr)
            q.gate_label = label
            # surviving `if_variable F == v` guards are phase gates -> reveal-graph inputs
            q.phase_gates = [(c.get("name"), _num_key(c.get("value")), c.get("value"))
                             for c in kept_flags if _num_key(c.get("value")) is not None]
            # a phase-gated friendly/neutral death is a PROTECT-fail, not a completion:
            # the same watcher signal FAILS the quest (quest_on_signal handles both).
            friendly = next((c for c in reals if c.tag == "if_not_exists"
                             and not _is_player_ref(self.em, c)
                             and self._target_side(c.get("name")) in ("friendly", "neutral")),
                            None)
            if friendly is not None:
                q.fail_on_signal = sig
                q.body_signal = "quest_failed_done"
                q.protect_name = friendly.get("name")
            else:
                q.when = f"signal {sig}"
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
    if q.protect_name:
        return f"Protect {q.protect_name}"
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
                          build_notes, build_button_route, build_gm_tree_routes, _prescan_timers,
                          is_player_respawn_event, build_player_respawn_routes,
                          redundant_gm_key_events, gm_key_label)

    _prescan_named_objects(mission, em)
    _prescan_timers(mission, em)
    em.addons.add("quests")  # LM quest_driver reads the granted AMD
    # ...and the tab that DISPLAYS it. quest_driver only runs the tree; the quest log the
    # crew reads is `documents/quest_tab.mast` (gui_tab_add_top("quest"), shown on the
    # standard bridge consoles). Without it the whole point of the AMD target -- a live
    # objectives log -- is built and then invisible in game.
    em.addons.add("documents")
    em.emit_scan_roles = True  # tag scanned objects so amd_science scans render (scan_desc)
    # prescan scan_desc up front so the science_define_scan call is emitted even when the
    # set_ship_text lives in an event body (emitted after the grant line).
    for nd in mission.all_nodes():
        if nd.tag == "set_ship_text" and em.symbols.get(nd.get("name")):
            if nd.get("scan_desc") is not None:
                em.scans[nd.get("name")] = _mast_str(nd.get("scan_desc"))
            if nd.get("hailtext") is not None:
                em.hails[nd.get("name")] = _mast_str(nd.get("hailtext"))

    # Partition comms/GM-button events out to //comms routes (reuse the MAST-target
    # builders) -- exactly as convert.build_story_mast does. Only the remaining "plain"
    # events become quests/beats, so button trees don't degrade into polling loops.
    _dupe_gm_keys = redundant_gm_key_events(mission)
    comms_btn_events: dict[str, object] = {}
    gm_btn_events: dict[str, object] = {}
    respawn_player_events = []
    plain_events = []
    for ev in mission.events:
        # 2.8 player-respawn events go to Cosmos' own respawn, not a quest -- same as the
        # MAST target (see convert.build_player_respawn_routes).
        if is_player_respawn_event(ev, em):
            respawn_player_events.append(ev)
            continue
        cb = next((c for c in ev.conditions if c.tag == "if_comms_button"), None)
        gb = next((c for c in ev.conditions if c.tag == "if_gm_button"), None)
        gk = next((c for c in ev.conditions if c.tag == "if_gm_key"), None)
        # GM key shortcut / any command acting on the GM selection only makes sense on the
        # GM console. Cosmos has no GM hotkeys, so route these into the gamemaster //comms
        # tree -- the one context where use_gm_selection == COMMS_SELECTED_ID is valid.
        # Otherwise they become polling beats referencing an undefined COMMS_SELECTED_ID.
        uses_gm_sel = any(n.get("use_gm_selection") is not None for n in ev.commands)
        if cb is not None:
            comms_btn_events.setdefault(cb.get("text", ""), ev)
        elif gb is not None:
            gm_btn_events.setdefault(gb.get("text", ""), ev)
        elif gk is not None:
            # Same as the MAST target: skip a hotkey that only repeats a GM button.
            if id(ev) in _dupe_gm_keys:
                continue
            gm_btn_events.setdefault(f"Hotkeys/{gm_key_label(gk.get('keyText'))}", ev)
        elif uses_gm_sel:
            gm_btn_events.setdefault(ev.name or "GM Action", ev)
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
    routes += build_player_respawn_routes(respawn_player_events, em)
    # 2.8 set_ship_text hailtext -> one gated Hail comms button showing the ship's stored
    # hail line (set as an a2x_hail inventory value where set_ship_text ran).
    if em.hails:
        em.addons.add("comms")
        routes += [
            "",
            "# 2.8 set_ship_text hailtext -> a Hail comms button (per-ship stored hail).",
            "# NOTE: enemies may also show the LM race-taunt Hail; refine the gating if so.",
            '//comms if is_space_object_id(COMMS_SELECTED_ID) and '
            'get_inventory_value(COMMS_SELECTED_ID, "a2x_hail", "") != ""',
            '    + "Hail":',
            '        comms_receive(get_inventory_value(COMMS_SELECTED_ID, "a2x_hail", ""), '
            'title="Hail")',
        ]
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

    files = {
        "story.amd": story_amd,
        "story.mast": story_mast,
        "script.py": build_script_py(mission),
        "story.json": build_story_json(em, lib_version),
        "description.yaml": build_description_yaml(mission),
        "MIGRATION_NOTES.md": notes,
        "__lib__.json": '{"version": "' + lib_version + '"}\n',
    }
    # 2.8 scan_desc recovered as declarative science scans (loaded by story.mast).
    if em.scans:
        files["scans.amd"] = _build_scans_amd(em.scans)
    return files


def _build_scans_amd(scans: dict) -> str:
    """One AMD science-scan section per object: `Scan of: scan_<name>` + the 2.8 scan_desc
    as the scan body. The object is tagged with the matching `scan_<name>` role in
    story.mast (see c_set_ship_text); the LM science_scans addon renders it on scan."""
    out = ["# 2.8 set_ship_text scan_desc -> declarative science scans (amd_science).",
           "# Loaded by story.mast via science_define_scan_amd; the scanned objects are",
           "# tagged with their scan_<name> role there.", ""]
    for name, text in scans.items():
        role = "scan_" + _pyname(name).lower()
        out.append(f"# [{_amd_text(name)}]({role}_def)")
        out.append("---")
        out.append(f"Scan of: {role}")
        out.append("Tab: scan")
        out.append("---")
        out.append(f"% {_amd_text(text)}")
        out.append("")
    return "\n".join(out) + "\n"


def _build_story_mast(mission, em, builder, _slug, _display_name) -> str:
    from .convert import _player_default_lines, _player_route_lines
    label = _slug(mission.name)
    disp = _display_name(mission)
    L: list[str] = [
        f"# Migrated from {mission.source_path.split('/')[-1]} by arme2cosmos (--target amd).",
        "# The quest tree lives in story.amd; this task spawns, tags roles, and grants it.",
        "# Positions use 2.8 coords; a2x_* helpers flip them to Cosmos internally.",
        "",
        *_player_default_lines(em),
        "",
    ]
    # Same as the MAST target: the <start> player ships spawn from
    # //shared/signal/create_player_ships so they exist at ship select, not at map load.
    # Built here (before the map body) so the emitters below see player_ship assigned;
    # spliced in below create_sides, the order start_server fires the two signals in.
    player_route = _player_route_lines(mission, em)
    L.append(f'@map/{label} "{disp}"')
    # Folded for the same reason as the MAST target: engine-read text must be ASCII.
    for d in to_ascii(mission.description).replace("^", " ").split("\n"):
        d = d.strip()
        if d:
            L.append(f'" {d}')
    L.append("    shared main_story_task = mast_task")

    obj_vars = sorted(set(em.symbols.values()) | ({em.player_var} if em.player_var else set()))
    if obj_vars:
        L.append("    # objects forward-declared (shared so routes/watchers resolve them)")
        # player_ship is already assigned by the create_player_ships route (which runs
        # before the map loads), so it is declared `default` -- see the MAST target.
        L += [f"    {'default shared' if player_route and v == em.player_var else 'shared'}"
              f" {v} = None" for v in obj_vars]
    flag_vars = sorted({_pyname(n.get("name")) for n in mission.all_nodes()
                        if n.tag in ("set_variable", "if_variable") and n.get("name")})
    flag_vars = [f for f in flag_vars if f not in obj_vars]
    if flag_vars:
        L.append("    # event flags forward-declared (shared, default 0)")
        L += [f"    default shared {v} = 0" for v in flag_vars]
    L.append("")

    L.append("    # --- start block ---")
    from .convert import start_nodes, _CONSOLE_ADDRESSED_START
    for n in start_nodes(mission):
        if n.tag in _CONSOLE_ADDRESSED_START:
            continue   # deferred to //shared/signal/game_started, same as the MAST target
        if n.kind_key() == "create:player":
            continue   # hoisted to //shared/signal/create_player_ships, same as MAST
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
    if em.scans:
        em.addons.add("science_scans")  # LM addon: renders science_define_scan content
        L.append("    # 2.8 set_ship_text scan_desc -> declarative science scans")
        L.append('    science_define_scan_amd(document_get_amd_file('
                 'get_mission_dir_filename("scans.amd"), data_parser=amd_scan_data))')
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
        # SHARED: this reveals quests and SCHEDULES WATCHER TASKS. Per-console it would
        # spawn one gate watcher per connected console, each firing the same quest
        # signal - duplicate advancement, not just duplicate display.
        L.append(f"//shared/signal/{sig}   # phase {flag} == {vraw} reached -> reveal + start")
        L.append(f"    quest_reveal(SHARED, {keys!r})")
        for _k, gl in items:
            if gl:                       # a watcher objective; story beats reveal only
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

    # Event bodies: run when the quest resolves.
    #
    # ANNOUNCEMENTS, not requests. The driver EMITS quest_succeeded / quest_failed_done
    # once it has finished processing a resolution. quest_completed / quest_failed are
    # the opposite direction - signals the driver LISTENS for, so a mission can ASK for a
    # transition. Listening on a request waits for something nothing sends, which is what
    # silently killed every narrated beat in every conversion.
    # SHARED, not per-console. A 2.8 event body is server work - it messages the crew,
    # sets variables, moves objects, arms timers - and every message verb it emits
    # addresses its own audience. On a plain //signal it runs once per connected console
    # PLUS the server, so a five-console bridge saw each hail five times and every side
    # effect happened five times over.
    for key, body, sig in builder.completion_bodies:
        L.append(f'//shared/signal/{sig} if QUEST_ID == "{key}"   # event body')
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

    # Same side declaration the MAST target emits -- spliced in ahead of the map now that
    # every sideValue the mission touches is known. See convert._create_sides_lines.
    from .convert import _create_sides_lines, _map_label_index, _game_started_lines
    L[_map_label_index(L):_map_label_index(L)] = _create_sides_lines(em) + player_route
    # ...and the start block's console-addressed messages, which must wait for the crew to
    # be at consoles or they are silently dropped. See convert._game_started_lines.
    L += _game_started_lines(mission, em)
    return "\n".join(L) + "\n"
