"""Tests for the convert (scaffold) stage."""
import os
import tempfile
import unittest

from arme2cosmos.convert import convert_file

SAMPLE = """<?xml version="1.0" ?>
<mission_data version="2.8" playerShipNames_arme="Artemis">
  <mission_description>Defend the base.</mission_description>
  <start>
    <create type="station" x="70000" y="0" z="25000" name="DS1" sideValue="2"/>
    <create type="player" player_slot="0" x="10000" y="0" z="10000" sideValue="2"/>
    <create count="40" type="asteroids" startX="70000" startY="30" startZ="60000" randomRange="2000"/>
    <create type="Anomaly" pickupType="4" x="30000" y="10" z="5500"/>
  </start>
  <event name="Attack">
    <if_docked player_slot="0" name="DS1"/>
    <if_variable name="a1" comparator="NOT" value="1"/>
    <set_variable name="a1" value="1"/>
    <create type="enemy" x="70000" y="0" z="45000" name="KR01" sideValue="1" fleetnumber="1"/>
  </event>
  <event name="End">
    <if_fleet_count comparator="LESS_EQUAL" value="0" fleetnumber="1" sideValue="1"/>
    <end_mission/>
  </event>
</mission_data>
"""


class ConvertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.xml = os.path.join(self.tmp.name, "MISS_Sample.xml")
        with open(self.xml, "w", encoding="utf-8") as f:
            f.write(SAMPLE)
        self.out = os.path.join(self.tmp.name, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def _convert(self):
        d = convert_file(self.xml, self.out)
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        with open(os.path.join(d, "story.json"), encoding="utf-8") as f:
            sjson = f.read()
        return d, story, sjson

    def test_scaffold_files_created(self):
        d, _, _ = self._convert()
        for fname in ("story.mast", "script.py", "story.json",
                      "description.yaml", "MIGRATION_NOTES.md"):
            self.assertTrue(os.path.isfile(os.path.join(d, fname)), fname)

    def test_create_family_translated(self):
        _, story, _ = self._convert()
        self.assertIn('a2x_create_station(70000, 0, 25000', story)
        self.assertIn('a2x_create_player(10000, 0, 10000', story)
        self.assertIn('a2x_create_asteroids(40, (70000, 30, 60000)', story)
        self.assertIn('random_range=2000', story)
        self.assertIn('a2x_create_anomaly(30000, 10, 5500, 4)', story)

    def test_fleet_count_becomes_await_destroyed(self):
        _, story, _ = self._convert()
        self.assertIn('side="enemy, fleet_1"', story)
        self.assertIn('await destroyed_all(role("fleet_1"))', story)

    def test_end_mission(self):
        _, story, _ = self._convert()
        self.assertIn('signal_emit("show_game_results")', story)
        self.assertIn('->END', story)

    def test_comms_and_big_message_are_real_calls(self):
        # add a start with comms + big_message to the sample on the fly
        story = self._convert()[1]
        # base sample has no comms; assert the emitter wires them when present
        from arme2cosmos.emit import Emitter
        from arme2cosmos.model import XmlNode
        em = Emitter.__new__(Emitter)
        em.notes = []
        em.addons = set()
        bm = em.c_big_message(XmlNode("big_message", {"title": 'A "B"', "subtitle1": "by C"}))
        self.assertEqual(bm, ['    a2x_big_message("A \\"B\\"", "by C", "")'])
        ct = em.c_comms_text(XmlNode("incoming_comms_text", {"from": "Adm"}, text="Hi^there"))
        self.assertEqual(ct, ['    a2x_incoming_comms_text("Hi^there", from_name="Adm")'])
        self.assertIn("comms", em.addons)

    def test_anomaly_pulls_upgrades_addon(self):
        _, _, sjson = self._convert()
        self.assertIn("upgrades", sjson)
        self.assertIn("consoles", sjson)  # baseline


if __name__ == "__main__":
    unittest.main()
