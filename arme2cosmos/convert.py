"""Assemble a Cosmos MAST mission scaffold from a parsed 2.8 mission.

Produces a directory with story.mast, script.py, story.json, description.yaml and
MIGRATION_NOTES.md. The output is a *scaffold*: positions/spawns are real, the rest is
TODO-marked for a human to finish.
"""

from __future__ import annotations

import os
import re

from .emit import Emitter, emit_condition, _mast_str
from .model import Mission
from .parser import parse_file

# Baseline gameplay addons (a gameplay port needs at least consoles); extras are
# feature-detected by the Emitter (e.g. upgrades when anomalies are present).
_BASELINE_ADDONS = ["consoles", "docking", "comms", "damage", "prefabs", "fleets"]
# Library version tag the generated story.json references. Matches the libs shipped
# in the missions __lib__ folder; override with `convert --lib-version`.
DEFAULT_LIB_VERSION = "v1.4.0_dev"


def _slug(name: str) -> str:
    s = re.sub(r"^MISS_", "", name)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s or "mission"


def _display_name(mission: Mission) -> str:
    return re.sub(r"^MISS_", "", mission.name).replace("_", " ")


def build_story_mast(mission: Mission, em: Emitter) -> str:
    _prescan_named_objects(mission, em)
    label = _slug(mission.name)
    disp = _display_name(mission)
    lines: list[str] = []
    lines.append(f"# Migrated from {os.path.basename(mission.source_path)} by arme2cosmos.")
    lines.append("# Scaffold only -- see MIGRATION_NOTES.md for the punch-list.")
    lines.append("# Positions use 2.8 coords; a2x_* helpers flip them to Cosmos internally.")
    lines.append("")
    lines.append("PLAYER_CREATE_DEFAULT = False")
    lines.append("")
    lines.append(f'@map/{label} "{disp}"')
    for d in mission.description.replace("^", " ").split("\n"):
        d = d.strip()
        if d:
            lines.append(f'" {d}')
    lines.append("    shared main_story_task = mast_task")
    obj_vars = sorted(set(em.symbols.values()) | ({em.player_var} if em.player_var else set()))
    if obj_vars:
        lines.append("    # objects forward-declared so references resolve before/across creates")
        for v in obj_vars:
            lines.append(f"    default {v} = None")
    lines.append("")
    lines.append("    # --- start block ---")
    for n in mission.start:
        lines.append(f"    # {_xml_one(n)}")
        lines.extend(em.emit_command(n))
    lines.append("")

    # Comms-button and GM-button handler events become //comms buttons (the GM ones
    # gated to the gamemaster console), not linear-chain labels.
    comms_btn_events: dict[str, object] = {}
    gm_btn_events: dict[str, object] = {}
    chain_events = []
    for ev in mission.events:
        cb = next((c for c in ev.conditions if c.tag == "if_comms_button"), None)
        gb = next((c for c in ev.conditions if c.tag == "if_gm_button"), None)
        if cb is not None:
            comms_btn_events.setdefault(cb.get("text", ""), ev)
        elif gb is not None:
            gm_btn_events.setdefault(gb.get("text", ""), ev)
        else:
            chain_events.append(ev)

    for i, ev in enumerate(chain_events):
        lines.append(f"--- event_{i}" + (f"   # {ev.name}" if ev.name != f"event_{i}" else ""))
        for c in ev.conditions:
            lines.extend(emit_condition(em, c, i))
        for n in ev.commands:
            lines.append(f"    # {_xml_one(n)}")
            lines.extend(em.emit_command(n))
        lines.append("")

    if not chain_events:
        lines.append("    ->END")

    lines.extend(build_button_route(
        mission, em, comms_btn_events, set_tag="set_comms_button",
        header="//comms", handler_tag="if_comms_button",
        comment="# 2.8 comms buttons -> a //comms route (refine the gating/selection).",
        addons=["comms"]))
    lines.extend(build_gm_tree_routes(mission, em, gm_btn_events))
    return "\n".join(lines) + "\n"


GM_GATE = "if has_roles(COMMS_ORIGIN_ID, 'gamemaster')"


# create kinds that are captured into a MAST variable (mirror of the c_* emitters).
_CAPTURED_CREATES = {"create:station", "create:enemy", "create:neutral",
                     "create:monster", "create:whale", "create:genericMesh",
                     "create:Anomaly", "create:blackHole"}


def _prescan_named_objects(mission: Mission, em: Emitter) -> None:
    """Register every named created object up front so later commands resolve them
    regardless of emission order (forward references, button-handler events)."""
    for n in mission.all_nodes():
        if n.tag != "create":
            continue
        name = n.get("name")
        if not name:
            continue
        kind = n.kind_key()
        if kind == "create:player":
            em.player_var = "player_ship"
            em.symbols.setdefault(name, "player_ship")
        elif kind in _CAPTURED_CREATES:
            em._var_for(name)


def _button_body(em: Emitter, ev, handler_tag: str) -> list[str]:
    """The inline body (8-space indented) for a `+ "label":` button."""
    body: list[str] = []
    if ev is None:
        body.append(f"        # TODO: 2.8 button had no {handler_tag} handler")
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


def build_description_yaml(mission: Mission) -> str:
    disp = _display_name(mission)
    desc = mission.description.replace("^", " ").replace("\n", " ").strip()
    return (f"format version: 1\n"
            f"Category: Standard\n"
            f"Category Priority: C\n"
            f"Visible Mission Name: {disp}\n"
            f"Description: {desc}\n")


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
    lines.append("## Reminders")
    lines.append("- Headings from 2.8 `angle` are not yet applied (a2x_angle exists if needed).")
    lines.append("- Ship art is placeholder; resolve via the hull crosswalk (artmap).")
    lines.append("- Events are chained linearly; verify the order matches the original flags.")
    return "\n".join(lines) + "\n"


def convert_file(path: str, out_root: str, lib_version: str = DEFAULT_LIB_VERSION,
                 hullmap: dict | None = None) -> str:
    """Convert one mission XML; write a scaffold dir under out_root. Returns the dir."""
    mission = parse_file(path)
    em = Emitter(mission, hullmap=hullmap)

    story = build_story_mast(mission, em)  # run first so em.addons/notes are populated
    files = {
        "story.mast": story,
        "script.py": build_script_py(mission),
        "story.json": build_story_json(em, lib_version),
        "description.yaml": build_description_yaml(mission),
        "MIGRATION_NOTES.md": build_notes(mission, em),
        "__lib__.json": '{"version": "' + lib_version + '"}\n',
    }

    out_dir = os.path.join(out_root, _slug(mission.name))
    os.makedirs(out_dir, exist_ok=True)
    for fname, content in files.items():
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
            f.write(content)
    return out_dir
