"""Tests for the hull crosswalk (artmap) with small synthetic registries."""
import os
import tempfile
import unittest

from arme2cosmos.artmap import (
    parse_shipdata, parse_vesseldata, build_hullmap, resolve_art, generate,
)

VESSELDATA = """<?xml version="1.0" ?>
<vessel_data>
  <hullRace ID="0" name="TSN" keys="player"></hullRace>
  <hullRace ID="2" name="Kralien" keys="enemy standard"></hullRace>
  <vessel uniqueID="0" side="0" classname="Light Cruiser" broadType="player"/>
  <vessel uniqueID="2000" side="2" classname="Cruiser" broadType="medium"/>
  <vessel uniqueID="2001" side="2" classname="Battleship" broadType="large"/>
  <vessel uniqueID="9999" side="2" classname="Mystery Hull" broadType="weird"/>
</vessel_data>
"""

# Minimal HJSON-ish shipdata (with // comments and inline comments).
SHIPDATA = """// game data
{
  "#ship-list": [
    { "key": "tsn_light_cruiser", "name": "Light Cruiser", "side": "TSN" }, // player
    { "key": "kralien_cruiser",   "name": "Cruiser",       "side": "Kralien" },
    { "key": "kralien_battleship","name": "Battleship",    "side": "Kralien" }
  ]
}
"""


class ArtmapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vd = os.path.join(self.tmp.name, "vesselData.xml")
        self.sd = os.path.join(self.tmp.name, "shipDataBB.json")
        with open(self.vd, "w", encoding="utf-8") as f:
            f.write(VESSELDATA)
        with open(self.sd, "w", encoding="utf-8") as f:
            f.write(SHIPDATA)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_shipdata_extracts_triples(self):
        hulls = parse_shipdata(self.sd)
        self.assertEqual(len(hulls), 3)
        self.assertEqual(hulls[1], {"key": "kralien_cruiser", "name": "Cruiser",
                                    "side": "Kralien"})

    def test_build_hullmap_matches_by_side_and_class(self):
        races, vessels = parse_vesseldata(self.vd)
        hm = build_hullmap(races, vessels, parse_shipdata(self.sd))
        self.assertEqual(hm["by_hull_id"]["0"], "tsn_light_cruiser")
        self.assertEqual(hm["by_hull_id"]["2000"], "kralien_cruiser")
        self.assertEqual(hm["by_hull_id"]["2001"], "kralien_battleship")
        self.assertEqual(hm["by_race_class"]["kralien|battleship"], "kralien_battleship")

    def test_unmatched_listed(self):
        hm = generate(self.vd, self.sd)[0]
        ids = {u["id"] for u in hm["unmatched"]}
        self.assertIn("9999", ids)  # Mystery Hull has no Kralien match

    def test_resolve_art_by_hull_id_and_race_class(self):
        hm = generate(self.vd, self.sd)[0]
        self.assertEqual(resolve_art(hm, hull_id="2000"), "kralien_cruiser")
        self.assertEqual(resolve_art(hm, race_keys="Kralien standard",
                                     hull_keys="Battleship"), "kralien_battleship")
        self.assertIsNone(resolve_art(hm, hull_id="404"))
        self.assertIsNone(resolve_art(None, hull_id="2000"))


if __name__ == "__main__":
    unittest.main()
