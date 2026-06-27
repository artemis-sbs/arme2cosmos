"""Typed model of a parsed Artemis 2.8 mission XML.

A 2.8 mission is a single ``<mission_data>`` (older docs say ``<mission_description>``)
root containing:
  * one ``<mission_description>`` text block,
  * one ``<start>`` block of commands run at mission start,
  * any number of ``<event>`` blocks, each a mix of CONDITION children (tags starting
    with ``if_``) and COMMAND children (everything else). If every condition is true,
    the commands run.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class XmlNode:
    """A single command or condition element: its tag plus attributes."""

    tag: str
    attrib: dict[str, str] = field(default_factory=dict)
    text: str | None = None

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.attrib.get(key, default)

    @property
    def is_condition(self) -> bool:
        # In 2.8, every CONDITION tag begins with ``if_``; commands never do.
        return self.tag.startswith("if_")

    def kind_key(self) -> str:
        """A finer-grained key for coverage: ``create`` is split by its ``type``.

        e.g. ``create type="enemy"`` -> ``create:enemy``; everything else -> the tag.
        """
        if self.tag == "create":
            t = (self.attrib.get("type") or "").strip()
            return f"create:{t}" if t else "create"
        return self.tag


@dataclass
class Event:
    name: str
    conditions: list[XmlNode] = field(default_factory=list)
    commands: list[XmlNode] = field(default_factory=list)
    index: int = 0


@dataclass
class Mission:
    name: str
    description: str = ""
    start: list[XmlNode] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    player_ship_names: list[str] = field(default_factory=list)
    source_path: str = ""

    def all_nodes(self):
        """Yield every command/condition node in the mission (start + all events)."""
        yield from self.start
        for ev in self.events:
            yield from ev.conditions
            yield from ev.commands
