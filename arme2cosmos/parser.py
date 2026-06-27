"""Parse Artemis 2.8 mission XML into the :mod:`arme2cosmos.model` types.

Uses only ``xml.etree.ElementTree`` (stdlib). Tolerant of the real-world quirks seen
in the a28 corpus: root element is usually ``<mission_data>`` (not the
``<mission_description>`` the old docs describe), file extensions vary in case
(``.xml`` / ``.XML``), and editor backup files are prefixed with ``~``.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

from .model import Event, Mission, XmlNode


def _node(el: ET.Element) -> XmlNode:
    text = (el.text or "").strip() or None
    return XmlNode(tag=el.tag, attrib=dict(el.attrib), text=text)


def parse_file(path: str) -> Mission:
    """Parse a single mission ``.xml`` file into a :class:`Mission`."""
    tree = ET.parse(path)
    root = tree.getroot()

    name = os.path.splitext(os.path.basename(path))[0]
    mission = Mission(name=name, source_path=os.path.abspath(path))

    # playerShipNames live as a root attribute (e.g. "Artemis\Intrepid\...").
    for key, val in root.attrib.items():
        if key.startswith("playerShipNames"):
            mission.player_ship_names = [s for s in val.split("\\") if s]

    desc = root.find("mission_description")
    if desc is not None and desc.text:
        mission.description = desc.text.strip()

    start = root.find("start")
    if start is not None:
        mission.start = [_node(child) for child in start]

    for idx, ev in enumerate(root.findall("event")):
        event = Event(name=ev.attrib.get("name", f"event_{idx}"), index=idx)
        for child in ev:
            node = _node(child)
            (event.conditions if node.is_condition else event.commands).append(node)
        mission.events.append(event)

    return mission


def find_mission_files(path: str) -> list[str]:
    """Resolve *path* to a list of mission XML files.

    Accepts a single ``.xml`` file, a single ``MISS_*`` mission folder, or a parent
    directory containing many. De-duplicates case-insensitively (the a28 tree exposes
    both ``missions/`` and ``Missions/`` on a case-insensitive filesystem) and skips
    ``~`` editor backups.
    """
    found: dict[str, str] = {}

    def add(p: str) -> None:
        base = os.path.basename(p)
        if base.startswith("~"):
            return
        if not base.lower().endswith(".xml"):
            return
        found.setdefault(os.path.normcase(os.path.abspath(p)), os.path.abspath(p))

    if os.path.isfile(path):
        add(path)
    elif os.path.isdir(path):
        for dirpath, _dirs, files in os.walk(path):
            for f in files:
                add(os.path.join(dirpath, f))

    return sorted(found.values(), key=str.lower)
