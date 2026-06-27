"""Unit tests for the parser and coverage report (stdlib unittest, no pip)."""

import os
import tempfile
import unittest

from arme2cosmos import coverage
from arme2cosmos.parser import find_mission_files, parse_file
from arme2cosmos.report import analyze

SAMPLE = """<?xml version="1.0" ?>
<mission_data version="1.0" playerShipNames_arme="Artemis\\Intrepid">
  <mission_description> Test mission. </mission_description>
  <start>
    <create type="player" player_slot="0" x="98000" y="0" z="98000" name="Artemis"/>
    <create type="enemy" x="50000" y="2" z="59000" raceKeys="BioMech" hullKeys="Stage 1"/>
    <create count="40" type="asteroids" startX="70000" startY="30" startZ="60000"/>
    <set_variable name="Flag" value="1.0"/>
    <set_timer name="t1" seconds="10"/>
    <frobnicate gizmo="yes"/>
  </start>
  <event name="Briefing">
    <if_timer_finished name="t1"/>
    <if_variable name="Flag" comparator="EQUALS" value="1.0"/>
    <big_message title="Hi"/>
    <set_comms_button text="Talk" sideValue="2"/>
  </event>
</mission_data>
"""


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "MISS_Test.xml")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(SAMPLE)

    def tearDown(self):
        self.tmp.cleanup()

    def test_basic_structure(self):
        m = parse_file(self.path)
        self.assertEqual(m.name, "MISS_Test")
        self.assertEqual(m.description, "Test mission.")
        self.assertEqual(m.player_ship_names, ["Artemis", "Intrepid"])
        self.assertEqual(len(m.start), 6)
        self.assertEqual(len(m.events), 1)

    def test_condition_vs_command_split(self):
        m = parse_file(self.path)
        ev = m.events[0]
        self.assertEqual(len(ev.conditions), 2)  # the two if_*
        self.assertEqual(len(ev.commands), 2)    # big_message, set_comms_button
        self.assertTrue(all(c.is_condition for c in ev.conditions))

    def test_create_kind_key_split_by_type(self):
        m = parse_file(self.path)
        keys = {n.kind_key() for n in m.start}
        self.assertIn("create:player", keys)
        self.assertIn("create:enemy", keys)
        self.assertIn("create:asteroids", keys)

    def test_coverage_classification(self):
        self.assertEqual(coverage.classify("create:player").status, coverage.FULL)
        self.assertEqual(coverage.classify("set_comms_button").status, coverage.MANUAL)
        self.assertEqual(coverage.classify("frobnicate").status, coverage.UNKNOWN)

    def test_analyze_counts_and_unknown(self):
        m = parse_file(self.path)
        s = analyze(m)
        self.assertEqual(s["events"], 1)
        self.assertEqual(s["total_nodes"], 10)  # 6 start + 2 cond + 2 cmd
        self.assertIn("unknown", s["status_counts"])  # frobnicate
        self.assertGreater(s["status_counts"]["full"], 0)

    def test_find_dedups_and_skips_backups(self):
        # a ~backup beside the file must be skipped
        backup = os.path.join(self.tmp.name, "~MISS_Test.xml")
        with open(backup, "w", encoding="utf-8") as f:
            f.write(SAMPLE)
        files = find_mission_files(self.tmp.name)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith("MISS_Test.xml"))


if __name__ == "__main__":
    unittest.main()
