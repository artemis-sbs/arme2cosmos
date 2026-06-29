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
    <if_variable name="a1" comparator="EQUALS" value="1"/>
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

    def test_description_yaml_has_all_expected_keys(self):
        # every Cosmos description.yaml is expected to carry these six keys.
        d, _, _ = self._convert()
        with open(os.path.join(d, "description.yaml"), encoding="utf-8") as f:
            text = f.read()
        keys = {ln.split(":", 1)[0].strip() for ln in text.splitlines() if ":" in ln}
        for expected in ("format version", "Category", "Category Priority",
                         "Visible Mission Name", "Description", "Keywords"):
            self.assertIn(expected, keys, expected)

    def test_description_yaml_with_colon_is_valid(self):
        # a 2.8 description containing ": " (e.g. "one thing: TROUBLE!") must not break YAML
        from arme2cosmos.convert import build_description_yaml
        from arme2cosmos.model import Mission
        m = Mission(name="MISS_X", source_path="x.xml")
        m.description = 'Uncover one thing: TROUBLE! The "best" crew wins.'
        text = build_description_yaml(m)
        # parse with the same yaml the engine uses
        try:
            from sbs_utils import yaml
        except ImportError:
            self.skipTest("sbs_utils.yaml not importable in this environment")
        data = yaml.safe_load(text)
        self.assertIn("TROUBLE", data["Description"])
        self.assertEqual(data["Keywords"], "2.8 port")

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

    def test_named_objects_captured_in_variables(self):
        _, story, _ = self._convert()
        self.assertIn("obj_ds1 = a2x_create_station", story)
        self.assertIn("obj_kr01 = a2x_create_enemy", story)

    def test_if_docked_becomes_dock_wait(self):
        _, story, sjson = self._convert()
        self.assertIn("---wait_dock_0", story)
        self.assertIn("a2x_is_docked(player_ship)", story)
        self.assertIn("docking", sjson)  # if_docked pulls the docking addon


ADD_AI_SAMPLE = """<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>monsters</mission_description>
  <start>
    <create type="monster" monsterType="2" x="20000" y="1" z="70000" name="Bruce"/>
  </start>
  <event name="Wake">
    <if_variable name="go" comparator="EQUALS" value="1"/>
    <clear_ai name="Bruce"/>
    <add_ai type="CHASE_PLAYER" value1="10000" name="Bruce"/>
    <add_ai type="GUARD_STATION" name="Bruce"/>
  </event>
</mission_data>
"""


class ConvertAddAiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.xml = os.path.join(self.tmp.name, "MISS_Mon.xml")
        with open(self.xml, "w", encoding="utf-8") as f:
            f.write(ADD_AI_SAMPLE)
        self.out = os.path.join(self.tmp.name, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def _story(self):
        d = convert_file(self.xml, self.out)
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            return f.read()

    def test_add_ai_resolves_named_object_across_events(self):
        story = self._story()
        self.assertIn("obj_bruce = a2x_create_monster", story)
        self.assertIn('a2x_add_ai(obj_bruce, "CHASE_PLAYER")', story)
        self.assertIn("a2x_clear_ai(obj_bruce)", story)

    def test_names_with_quotes_are_escaped(self):
        # regression: a 2.8 name containing double quotes must not break the MAST
        # string literal (found by compile-checking the corpus).
        from arme2cosmos.emit import Emitter
        from arme2cosmos.model import XmlNode
        em = Emitter.__new__(Emitter)
        em.notes, em.addons, em.symbols, em.player_var = [], set(), {}, None
        em.hullmap = None
        line = em.c_neutral(XmlNode("create", {"type": "neutral", "x": "1", "y": "0",
                                               "z": "2", "name": '"Used" Scout'}))[0]
        self.assertIn(r'name="\"Used\" Scout"', line)
        self.assertNotIn('name=""Used"', line)

    def test_unmapped_ai_still_emits_call(self):
        # GUARD_STATION has no brain; still emitted (a2x_add_ai no-ops) + noted.
        self.assertIn('a2x_add_ai(obj_bruce, "GUARD_STATION")', self._story())

    def test_add_ai_pulls_ai_addon(self):
        d = convert_file(self.xml, self.out)
        with open(os.path.join(d, "story.json"), encoding="utf-8") as f:
            self.assertIn("ai", f.read())

    def test_event_model_hybrid_vs_linear(self):
        # ADD_AI_SAMPLE's single event waits on a flag (go == 1): in hybrid it becomes
        # an event-driven //signal route; in linear it is folded into the scene chain.
        dh = convert_file(self.xml, self.out + "h", event_model="hybrid")
        dl = convert_file(self.xml, self.out + "l", event_model="linear")
        sh = open(os.path.join(dh, "story.mast"), encoding="utf-8").read()
        sl = open(os.path.join(dl, "story.mast"), encoding="utf-8").read()
        # hybrid: a //signal route guarded by the flag value (no polling task)
        self.assertIn("//signal/a2x_flag_go", sh)
        self.assertIn("->END if not (go == 1)", sh)
        # linear: forced into the sequential chain, no route
        self.assertNotIn("//signal", sl)
        self.assertIn("--- event_0", sl)


RESPAWN_SAMPLE = """<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>respawn</mission_description>
  <start>
    <create type="station" x="50000" y="0" z="50000" name="Base" raceKeys="TSN"/>
  </start>
  <event name="Respawn Sentry">
    <if_not_exists name="Sentry"/>
    <create type="enemy" x="60000" y="0" z="60000" name="Sentry" raceKeys="Kralien"/>
  </event>
  <event name="One Shot Greeting">
    <if_variable name="greeted" comparator="!=" value="1"/>
    <if_distance name1="Base" player_slot1="1" comparator="LESS" value="5000"/>
    <set_variable name="greeted" value="1" integer="yes"/>
  </event>
</mission_data>
"""


class ConvertEventLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.xml = os.path.join(self.tmp.name, "MISS_Re.xml")
        with open(self.xml, "w", encoding="utf-8") as f:
            f.write(RESPAWN_SAMPLE)
        self.out = os.path.join(self.tmp.name, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def _story(self):
        d = convert_file(self.xml, self.out)
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            return f.read()

    def test_a28_compatible_makes_every_event_a_polling_task(self):
        # worst-case faithful: no chain, no routes -- both events become ind_event loops.
        d = convert_file(self.xml, self.out + "a", event_model="a28_compatible")
        story = open(os.path.join(d, "story.mast"), encoding="utf-8").read()
        self.assertIn("=== ind_event_0", story)
        self.assertIn("=== ind_event_1", story)
        self.assertNotIn("--- event_0", story)            # no sequential chain
        self.assertNotIn("//damage/destroy", story)       # no push routes
        self.assertNotIn("//signal/a2x_flag", story)

    def test_respawn_event_becomes_destroy_route(self):
        # if_not_exists Sentry -> an event-driven //damage/destroy route (no polling):
        # spawn once initially, then respawn whenever the tagged object is destroyed.
        story = self._story()
        self.assertIn("=== respawn_0", story)
        self.assertIn("task_schedule(respawn_0)", story)               # initial spawn
        self.assertIn('//damage/destroy if has_role(DESTROYED_ID, "respawn_Sentry")', story)
        respawn = story.split("=== respawn_0")[1]
        self.assertIn("a2x_create_enemy", respawn)                     # (re)creates it
        self.assertIn('add_role(obj_sentry, "respawn_Sentry")', respawn)  # re-tag on spawn
        # it is NOT a polling loop for the respawn object
        self.assertNotIn("object_exists(obj_sentry)", story)

    def test_fire_once_event_ends(self):
        # a self-guard (if_variable greeted != 1 + set greeted = 1) should ->END, not loop
        story = self._story()
        # find the ind_event whose guard mentions greeted
        chunks = story.split("=== ind_event_")
        greet = next(c for c in chunks if "greeted != 1" in c)
        self.assertIn("shared greeted = 1", greet)
        self.assertIn("->END", greet)
        self.assertNotRegex(greet.split("->END")[0], r"jump ind_event_\d+_loop\n")

    def test_flags_are_shared_and_declared(self):
        story = self._story()
        self.assertIn("default shared greeted = 0", story)  # forward-declared
        self.assertIn("shared greeted = 1", story)          # set as shared


FLAG_SIGNAL_SAMPLE = """<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>signal</mission_description>
  <start>
    <create type="station" x="50000" y="0" z="50000" name="Base" raceKeys="TSN"/>
    <set_variable name="alarm" value="1" integer="yes"/>
  </start>
  <event name="On Alarm">
    <if_variable name="alarm" comparator="EQUALS" value="1"/>
    <destroy name="Base"/>
  </event>
</mission_data>
"""


class ConvertFlagSignalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.xml = os.path.join(self.tmp.name, "MISS_Sig.xml")
        with open(self.xml, "w", encoding="utf-8") as f:
            f.write(FLAG_SIGNAL_SAMPLE)
        self.out = os.path.join(self.tmp.name, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def test_flag_wait_becomes_signal_route_and_emit(self):
        d = convert_file(self.xml, self.out)
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        # the set_variable that the route listens on also emits the signal (push)
        self.assertIn("shared alarm = 1", story)
        self.assertIn('signal_emit("a2x_flag_alarm")', story)
        # the waiting event is now an event-driven route guarded by the value
        self.assertIn("//signal/a2x_flag_alarm", story)
        self.assertIn("->END if not (alarm == 1)", story)
        # not a polling loop
        self.assertNotIn("=== ind_event_", story)


DIRECT_SAMPLE = """<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>directing</mission_description>
  <start>
    <create type="neutral" x="1000" y="0" z="2000" name="Amb" sideValue="0"/>
    <create type="enemy" x="5000" y="0" z="6000" name="Foe" sideValue="1"/>
  </start>
  <event name="Move">
    <if_variable name="go" comparator="EQUALS" value="1"/>
    <direct name="Amb" pointX="0" pointY="0" pointZ="0" scriptThrottle="0.5"/>
    <direct name="Foe" targetName="Amb" scriptThrottle="1.0"/>
    <destroy name="Amb"/>
  </event>
</mission_data>
"""


class ConvertDirectDestroyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.xml = os.path.join(self.tmp.name, "MISS_Dir.xml")
        with open(self.xml, "w", encoding="utf-8") as f:
            f.write(DIRECT_SAMPLE)
        self.out = os.path.join(self.tmp.name, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def _story(self):
        d = convert_file(self.xml, self.out)
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            return f.read()

    def test_direct_to_point_uses_flipped_coords(self):
        self.assertIn("target_pos(obj_amb, *a2x_pos(0, 0, 0), 0.5)", self._story())

    def test_direct_to_target_resolves_both(self):
        self.assertIn("target(obj_foe, to_id(obj_amb), throttle=1.0)", self._story())

    def test_destroy_resolves_var(self):
        self.assertIn("a2x_destroy(obj_amb)", self._story())


COMMS_BTN_SAMPLE = """<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>buttons</mission_description>
  <start>
    <set_comms_button text="Request Bounty" sideValue="2"/>
  </start>
  <event name="Bounty">
    <if_comms_button text="Request Bounty"/>
    <if_variable name="paid" comparator="NOT" value="1"/>
    <set_variable name="paid" value="1"/>
    <big_message title="Bounty paid"/>
  </event>
  <event name="OtherLinear">
    <if_variable name="go" comparator="EQUALS" value="1"/>
    <set_variable name="done" value="1"/>
  </event>
</mission_data>
"""


class ConvertCommsButtonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.xml = os.path.join(self.tmp.name, "MISS_Btn.xml")
        with open(self.xml, "w", encoding="utf-8") as f:
            f.write(COMMS_BTN_SAMPLE)
        self.out = os.path.join(self.tmp.name, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def _story(self):
        d = convert_file(self.xml, self.out)
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            return f.read()

    def test_comms_route_with_button(self):
        story = self._story()
        self.assertIn("//comms", story)
        self.assertIn('+ "Request Bounty":', story)
        # the handler event's command shows up inside the button body (indented 8)
        self.assertIn("        a2x_big_message", story)

    def test_button_event_excluded_from_chain(self):
        story = self._story()
        # the comms-button event lives in the //comms route (its handler body indented 8),
        # not as a chain/task event; the non-button event is emitted once elsewhere.
        self.assertIn('+ "Request Bounty":', story)
        self.assertIn("        a2x_big_message", story)
        self.assertEqual(story.count("done = 1"), 1)

    def test_quick_wins_log_sound_griddamage(self):
        from arme2cosmos.emit import Emitter
        from arme2cosmos.model import XmlNode
        em = Emitter.__new__(Emitter)
        em.notes, em.addons, em.symbols, em.player_var, em.hullmap = [], set(), {}, "player_ship", None
        self.assertEqual(em.c_log(XmlNode("log", {"text": 'hi "there"'}))[0],
                         '    log("hi \\"there\\"")')
        self.assertEqual(em.c_play_sound(XmlNode("play_sound_now", {"filename": "boom.wav"}))[0],
                         '    sbs.play_audio_file(0, get_mission_audio_file("boom.wav"), 1.0, 1.0)')
        self.assertEqual(em.c_grid_damage(XmlNode("set_player_grid_damage",
                         {"player_slot": "0", "systemType": "systemImpulse"}))[0],
                         "    grid_damage_system(player_ship, sbs.SHPSYS.ENGINES)")

    def test_set_object_property_mapped_vs_todo(self):
        from arme2cosmos.emit import Emitter
        from arme2cosmos.model import XmlNode
        em = Emitter.__new__(Emitter)
        em.notes, em.addons, em.symbols, em.player_var, em.hullmap = [], set(), {"X": "obj_x"}, None, None
        # mapped property -> real call
        mapped = em.c_set_object_property(XmlNode("set_object_property",
                 {"name": "X", "property": "hasSurrendered", "value": "1"}))[0]
        self.assertEqual(mapped, '    a2x_set_object_property(obj_x, "hasSurrendered", 1)')
        # unmapped property -> TODO
        todo = em.c_set_object_property(XmlNode("set_object_property",
               {"name": "X", "property": "pirateRepWithStations", "value": "5"}))
        self.assertTrue(any("# TODO" in ln for ln in todo))

    def test_tags_become_inventory_values(self):
        from arme2cosmos.emit import Emitter, emit_condition
        from arme2cosmos.model import XmlNode
        em = Emitter.__new__(Emitter)
        em.notes, em.addons, em.symbols, em.player_var, em.hullmap = [], set(), {"M": "obj_m"}, None, None
        out = "\n".join(em.c_set_monster_tag_data(XmlNode("set_monster_tag_data",
              {"name": "M", "tag_slot": "1", "sourcetext": "Artemis", "datetext": "D3"})))
        self.assertIn('set_inventory_value(obj_m, "tag_1_source", "Artemis")', out)
        cond = emit_condition(em, XmlNode("if_object_tag_matches",
               {"objectName": "M", "string": "Artemis"}))[0]
        self.assertIn('get_inventory_value(obj_m, "tag_source_name") == "Artemis"', cond)

    def test_gm_button_becomes_gamemaster_route(self):
        xml = os.path.join(self.tmp.name, "MISS_Gm.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<mission_data version="2.8">
  <mission_description>gm</mission_description>
  <start><set_gm_button text="Spawn Wave"/></start>
  <event name="GH"><if_gm_button text="Spawn Wave"/>
    <set_variable name="wave" value="1"/></event>
</mission_data>""")
        d = convert_file(xml, self.out + "gm")
        story = open(os.path.join(d, "story.mast"), encoding="utf-8").read()
        sjson = open(os.path.join(d, "story.json"), encoding="utf-8").read()
        self.assertIn("//comms if has_roles(COMMS_ORIGIN_ID, 'gamemaster')", story)
        self.assertIn('+ "Spawn Wave":', story)
        self.assertIn("wave = 1", story)
        self.assertIn("gamemaster", sjson)

    def test_gm_slash_path_becomes_submenu_tree(self):
        xml = os.path.join(self.tmp.name, "MISS_GmTree.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<mission_data version="2.8">
  <mission_description>gm</mission_description>
  <start>
    <set_gm_button text="AI/Enemy/chase player"/>
    <set_gm_button text="AI/Enemy/brave captain"/>
  </start>
  <event name="A"><if_gm_button text="AI/Enemy/chase player"/>
    <set_variable name="x" value="1"/></event>
</mission_data>""")
        d = convert_file(xml, self.out + "tree")
        s = open(os.path.join(d, "story.mast"), encoding="utf-8").read()
        # root: nav into the AI submenu
        self.assertIn('+ "AI" //comms/gm/ai', s)
        # AI route: gated, Back, and nav into Enemy
        self.assertIn("//comms/gm/ai if has_roles(COMMS_ORIGIN_ID, 'gamemaster')", s)
        self.assertIn('+ "Back" //comms', s)
        self.assertIn('+ "Enemy" //comms/gm/ai/enemy', s)
        # Enemy route: gated, Back to parent, leaf buttons (display text preserved)
        self.assertIn("//comms/gm/ai/enemy if has_roles(COMMS_ORIGIN_ID, 'gamemaster')", s)
        self.assertIn('+ "Back" //comms/gm/ai', s)
        self.assertIn('+ "chase player":', s)
        self.assertIn('+ "brave captain":', s)

    def test_comment_only_button_body_gets_noop(self):
        # a button whose handler emits only comments must still have a real
        # statement (~~ pass ~~), else the + block is empty and MAST rejects it.
        xml = os.path.join(self.tmp.name, "MISS_Empty.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<mission_data version="2.8">
  <mission_description>x</mission_description>
  <start><set_comms_button text="Noop"/></start>
  <event name="H"><if_comms_button text="Noop"/>
    <set_object_property name="z" property="throttle" value="1"/></event>
</mission_data>""")
        d = convert_file(xml, self.out + "2")
        story = open(os.path.join(d, "story.mast"), encoding="utf-8").read()
        self.assertIn('+ "Noop":', story)
        self.assertIn("~~ pass ~~", story)


if __name__ == "__main__":
    unittest.main()
