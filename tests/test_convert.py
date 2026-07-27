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
        d = convert_file(self.xml, self.out, target="mast")
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
        # a name containing ": " and quotes must not break YAML (the browser blurb is built
        # from the display name, which comes straight from the 2.8 filename)
        from arme2cosmos.convert import build_description_yaml
        from arme2cosmos.model import Mission
        m = Mission(name='MISS_One_thing:_"TROUBLE"', source_path="x.xml")
        m.description = "Long 2.8 briefing text that must NOT land here."
        text = build_description_yaml(m)
        # parse with the same yaml the engine uses
        try:
            from sbs_utils import yaml
        except ImportError:
            self.skipTest("sbs_utils.yaml not importable in this environment")
        data = yaml.safe_load(text)
        self.assertIn("TROUBLE", data["Visible Mission Name"])
        self.assertEqual(data["Keywords"], "2.8 port")

    def test_description_is_a_short_blurb_not_the_2_8_briefing(self):
        # the browser blurb is one short line; the full 2.8 <mission_description> stays in
        # story.mast as the map's briefing.
        from arme2cosmos.convert import build_description_yaml
        from arme2cosmos.model import Mission
        m = Mission(name="MISS_Deep_Strike", source_path="x.xml")
        m.description = "Paragraph one of a very long 2.8 briefing. " * 20
        text = build_description_yaml(m)
        line = [ln for ln in text.splitlines() if ln.startswith("Description:")][0]
        self.assertNotIn("Paragraph one", line)
        self.assertIn("A conversion of the Artemis 2.8 mission Deep Strike.", line)
        self.assertLess(len(line), 100)

    def test_create_family_translated(self):
        _, story, _ = self._convert()
        self.assertIn('a2x_create_station(70000, 0, 25000', story)
        self.assertIn('a2x_create_player(10000, 0, 10000', story)
        self.assertIn('a2x_create_asteroids(40, (70000, 30, 60000)', story)
        self.assertIn('random_range=2000', story)
        self.assertIn('a2x_create_anomaly(30000, 10, 5500, 4)', story)

    def test_fleet_count_becomes_await_destroyed(self):
        _, story, _ = self._convert()
        # side KEY first (identity + diplomacy), then the combat-scope role, then the
        # fleet role -- spawn_common splits on commas and adds every entry as a role.
        self.assertIn('side="enemy, raider, fleet_1"', story)
        self.assertIn('await destroyed_all(role("fleet_1"))', story)

    def test_sides_declared_in_create_sides_route(self):
        # 2.8 declares no sides; Cosmos needs them or side_are_enemies is always False
        # (and the LM npc brains gate firing on exactly that). One side per distinct
        # sideValue the mission touches, declared before anything spawns.
        _, story, _ = self._convert()
        self.assertIn("//shared/signal/create_sides", story)
        self.assertIn("a2x_declare_sides([1, 2])", story)
        # must come BEFORE the map: the server console fires it during start_server,
        # ahead of default player ships and any map.
        self.assertLess(story.index("//shared/signal/create_sides"), story.index("@map/"))
        # the route runs inline in the server-start task -- an ->END would end the caller.
        # Bounded at the NEXT route label: create_player_ships follows it, before the map.
        body = story[story.index("//shared/signal/create_sides"):story.index("@map/")]
        route = body[:body.index("//shared/signal/create_player_ships")]
        self.assertNotIn("->END", route)

    def test_player_and_friendly_station_share_a_side(self):
        # both carry 2.8 sideValue 2. If the player kept a2x_create_player's "tsn"
        # default it would be on a different side from its own station -- and once
        # diplomacy is declared, a different side means hostile.
        _, story, _ = self._convert()
        self.assertIn('a2x_create_station(70000, 0, 25000, "starbase_command", side="friendly"', story)
        self.assertIn('side="friendly"', story.split("a2x_create_player")[1].split("\n")[0])

    def test_unnamed_player_create_does_not_double_spawn(self):
        # regression: the prescan skipped un-named creates before checking the type, so a
        # 2.8 `<create type="player" player_slot="0" .../>` (usually unnamed) left
        # player_var None -- the header then asked LM to build a ship from PLAYER_LIST
        # *and* the body spawned one, giving two Artemis.
        _, story, _ = self._convert()
        # LM's defaults are always off: they build on side "tsn", which the mission never
        # declares, so a crew that took one had empty diplomacy (enemies read neutral).
        self.assertIn("PLAYER_CREATE_DEFAULT = False", story)
        self.assertNotIn("PLAYER_CREATE_DEFAULT = True", story)
        # 2.8 started with 8 crewable ships; the mission creates slot 0 and we fill the
        # rest -- all on the mission's OWN player side, so there is one declared side.
        self.assertEqual(story.count("a2x_create_player("), 8)
        # slot 0 is the mission's own ship; the 7 spares carry the spare marker so
        # game_started can drop them.
        self.assertEqual(story.count('side="friendly, a2x_spare_player"'), 7)
        for nm in ("Artemis", "Intrepid", "Diana"):
            self.assertIn(f'name="{nm}"', story)
        self.assertNotIn('side="tsn"', story)
        # Tagged in game_started so LM's crew-select / loadout machinery sees them. NOT
        # via spawn_players, which repositions ships near a friendly station and would
        # throw away the 2.8 spawn coordinates the mission actually specified.
        route = story[story.index("//shared/signal/game_started"):]
        self.assertIn('delete_object(role("a2x_spare_player"))', route)
        # no CALL to spawn_players (the name appears in a comment explaining why not)
        for call in ("task_schedule(spawn_players", "await spawn_players", "\n    spawn_players("):
            self.assertNotIn(call, story)

    def test_enemies_get_2_8_implicit_default_brain(self):
        # 2.8 gives every enemy a brain stack from the engine; a mission writes <add_ai>
        # only to override it. Without carrying that over, a converted enemy spawned with
        # no brain and sat inert -- the "AI doesn't work" report.
        _, story, sjson = self._convert()
        self.assertIn("a2x_default_enemy_ai(obj_kr01)", story)
        self.assertIn("LegendaryMissions.ai.", sjson)   # the brain labels live there

    def test_explicit_add_ai_suppresses_the_default_brain(self):
        # A ship the mission re-brains keeps ONLY its own stack, so the two can't fight.
        xml = os.path.join(self.tmp.name, "MISS_Ai.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Ai.</mission_description>
  <start>
    <create type="enemy" x="1" y="0" z="2" name="KR01" sideValue="1"/>
    <create type="enemy" x="3" y="0" z="4" name="KR02" sideValue="1"/>
    <add_ai name="KR01" type="CHASE_STATION"/>
  </start>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        self.assertNotIn("a2x_default_enemy_ai(obj_kr01)", story)  # overridden
        self.assertIn("a2x_add_ai(obj_kr01", story)
        self.assertIn("a2x_default_enemy_ai(obj_kr02)", story)     # not overridden

    def test_start_block_messages_wait_for_game_started(self):
        # A console-addressed message resolves its audience when called, and an empty
        # console set is silently ignored -- so a big_message fired from the map task (at
        # map LOAD, before the crew take consoles) was discarded with no error at all.
        xml = os.path.join(self.tmp.name, "MISS_Msg.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Msg.</mission_description>
  <start>
    <big_message title="Chapter One" subtitle1="by someone"/>
    <create type="station" x="1" y="0" z="2" name="DS1" sideValue="2"/>
  </start>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        self.assertIn("//shared/signal/game_started", story)
        # The route MUST yield a frame before messaging: server_console signals
        # game_started while "consoles are waiting to be started", so the console pages
        # do not exist yet and an empty audience is discarded silently. Verified in-game
        # -- and invisible to the headless runner, which never has consoles, so nothing
        # else in this suite can catch its removal.
        route_head = story[story.index("//shared/signal/game_started"):]
        self.assertLess(route_head.index("await delay_sim("),
                        route_head.index("a2x_big_message"),
                        "game_started must yield before addressing consoles")
        # the card is in the route, NOT in the map's start block
        start = story[story.index("--- start block ---"):story.index("//shared/signal/game_started")]
        self.assertNotIn("a2x_big_message", start)
        route = story[story.index("//shared/signal/game_started"):]
        self.assertIn('a2x_big_message("Chapter One"', route)
        # spawns stay in the start block
        self.assertIn("a2x_create_station", start)

    def test_non_movement_add_ai_keeps_the_default_brain(self):
        # Only an add_ai that attaches a real MOVEMENT/targeting brain replaces 2.8's
        # default stack. FOLLOW_COMMS_ORDERS just grants orderable roles, and the leader
        # blocks are dropped outright -- a ship with only those still needs the default,
        # or it spawns "re-brained" on paper and sits perfectly still (44 ships in the
        # corpus did exactly that).
        xml = os.path.join(self.tmp.name, "MISS_Orders.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Orders.</mission_description>
  <start>
    <create type="enemy" x="1" y="0" z="2" name="KR01" sideValue="1"/>
    <create type="enemy" x="3" y="0" z="4" name="KR02" sideValue="1"/>
    <add_ai name="KR01" type="FOLLOW_COMMS_ORDERS"/>
    <add_ai name="KR02" type="FOLLOW_LEADER"/>
  </start>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        self.assertIn("a2x_default_enemy_ai(obj_kr01)", story)  # role grant is not a brain
        self.assertIn("a2x_default_enemy_ai(obj_kr02)", story)  # dropped block is not a brain

    def test_mission_with_no_player_create_still_keeps_artemis(self):
        # Turning PLAYER_CREATE_DEFAULT off meant a 2.8 mission that positions no player
        # would have had NO player ship at all -- unplayable. The roster is still spawned
        # for ship select, and game_started keeps Artemis (max(N,1)) rather than 0.
        xml = os.path.join(self.tmp.name, "MISS_NoPlayer.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>No player.</mission_description>
  <start>
    <create type="station" x="1" y="0" z="2" name="DS1" sideValue="2"/>
  </start>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        self.assertEqual(story.count("a2x_create_player("), 8)
        # Artemis is kept; the other 7 are spares dropped at game_started
        self.assertEqual(story.count('side="friendly, a2x_spare_player"'), 7)
        artemis = [l for l in story.splitlines() if 'name="Artemis"' in l][0]
        self.assertNotIn("a2x_spare_player", artemis)
        self.assertIn('delete_object(role("a2x_spare_player"))', story)

    def test_baseline_addons_cover_what_2_8_gives_every_mission(self):
        # science_scans and basic_player_destroy are BASELINE, not feature-detected: 2.8
        # lets you scan anything and always ends the game when the player dies, so gating
        # them on a source feature left converted missions with a Science console that
        # answers nothing and a player death that never ends the mission.
        _, _, sjson = self._convert()
        for addon in ("consoles", "docking", "comms", "damage", "prefabs", "fleets",
                      "science_scans", "basic_player_destroy"):
            self.assertIn(f"LegendaryMissions.{addon}.", sjson, addon)

    def test_collisions_added_for_terrain_and_black_holes(self):
        # The LM collisions addon owns asteroid/mine impact damage AND the black-hole
        # lethal-proximity watcher (the engine's own maelstrom collision does not
        # reliably fire, so a ship can otherwise survive a black hole).
        _, _, sjson = self._convert()   # SAMPLE has an asteroid field
        self.assertIn("LegendaryMissions.collisions.", sjson)
        # nebulas are pass-through -- they alone should NOT pull it in
        xml = os.path.join(self.tmp.name, "MISS_Neb.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Neb.</mission_description>
  <start>
    <create count="5" type="nebulas" startX="1" startY="0" startZ="2"/>
  </start>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast")
        with open(os.path.join(d, "story.json"), encoding="utf-8") as f:
            self.assertNotIn("LegendaryMissions.collisions.", f.read())

    def test_player_create_is_hoisted_above_references_to_it(self):
        # In 2.8 the player ship already EXISTS when the mission loads; `create
        # type="player"` only places it. So a start block may reference the player above
        # its own create (MISS_Cruiser_Tournament puts set_player_carried_type there).
        # Cosmos has no such ship until we spawn one, so in source order the reference
        # resolved to nothing and the LM hangar crashed on to_space_object(None).origin.
        xml = os.path.join(self.tmp.name, "MISS_Carry.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Carry.</mission_description>
  <start>
    <set_player_carried_type player_slot="0" bay_slot="0" hullKeys="TSN Shuttle" name="Dagger"/>
    <create type="player" player_slot="0" x="1" y="0" z="2" sideValue="2"/>
  </start>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        spawn = story.index("a2x_create_player(")
        use = story.index("hangar_random_craft_spawn(")
        self.assertLess(spawn, use, "player create must be emitted before it is referenced")
        # and the reference resolves to the variable, not a not-yet-assigned forward decl
        self.assertIn("hangar_random_craft_spawn(player_ship,", story)

    def test_start_players_spawn_from_create_player_ships_route(self):
        # The map task runs when the map LOADS -- after the server console has offered
        # ship select -- so player ships spawned there were not in the list the crew picked
        # from. create_player_ships is fired inside start_server (right after create_sides,
        # before the menu), which is where LM builds its own PLAYER_LIST ships.
        _, story, _ = self._convert()
        self.assertIn("//shared/signal/create_player_ships", story)
        route = story[story.index("//shared/signal/create_player_ships"):]
        route = route[:route.index("@map/")]
        self.assertEqual(route.count("a2x_create_player("), 8)  # the one create + the fill
        # nothing spawns a player from the map task any more
        self.assertNotIn("a2x_create_player(", story[story.index("@map/"):])
        # ...and it runs before the map, after the sides it needs
        self.assertLess(story.index("//shared/signal/create_sides"),
                        story.index("//shared/signal/create_player_ships"))
        self.assertLess(story.index("//shared/signal/create_player_ships"),
                        story.index("@map/"))
        # the route already assigned player_ship, so the map must not reset it to None
        self.assertIn("    default shared player_ship = None", story)
        self.assertNotIn("\n    shared player_ship = None", story)

    RESPAWN_XML = """<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Respawn.</mission_description>
  <start>
    <create type="player" player_slot="0" x="1" y="0" z="2" name="Artemis" sideValue="2"/>
  </start>
  <event name="You Died">
    <if_not_exists name="Artemis"/>
    <if_variable name="Mission_Complete" comparator="EQUALS" value="1.0"/>
    <big_message title="Mission Failed!" subtitle1="You are Dead"/>
    <set_variable name="Mission_Complete" value="0.0"/>
    <create type="player" player_slot="0" x="1" y="0" z="2" name="Artemis" sideValue="2"/>
  </event>
</mission_data>
"""

    def _convert_respawn(self, target):
        xml = os.path.join(self.tmp.name, f"MISS_Died{target}.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write(self.RESPAWN_XML)
        d = convert_file(xml, self.out, target=target)
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            return d, f.read()

    def test_fleet_count_by_side_is_a_real_gate(self):
        # 2.8 if_fleet_count counts EITHER a named fleet or, with no fleetnumber, every ship
        # on a sideValue -- "are all the enemies dead?", the standard mission-success test.
        # Only the fleet form was mapped, so the side form became a comment and the scene it
        # gated ran immediately: MISS_TrialsOfDeneb01 declared MISSION SUCCESS at t=0.
        xml = os.path.join(self.tmp.name, "MISS_Wipe.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Wipe.</mission_description>
  <start>
    <create type="player" player_slot="0" x="1" y="0" z="2" sideValue="2"/>
    <create type="enemy" x="9" y="0" z="9" name="KR1" sideValue="1"/>
  </start>
  <event name="Victory">
    <if_fleet_count comparator="LESS_EQUAL" value="0" sideValue="1"/>
    <big_message title="MISSION SUCCESS" subtitle1="You are victorious"/>
  </event>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast", event_model="linear")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        # sideValue 1 -> the "enemy" side key, which is the role a2x_create_enemy tags with
        self.assertIn('await destroyed_all(role("enemy"))', story)
        # the win card must sit BEHIND that wait, not run at t=0
        self.assertLess(story.index('await destroyed_all(role("enemy"))'),
                        story.index('a2x_big_message("MISSION SUCCESS"'))
        self.assertNotIn("# when: fleet None", story)

    def test_object_gone_reaction_is_not_treated_as_a_respawn(self):
        # A respawn candidate is emitted as `=== respawn_j` AND scheduled once at map start
        # (the initial spawn, before //damage/destroy takes over). That is only right if the
        # body actually re-creates the object. 2.8 uses "when X is gone" just as often to
        # REACT -- announce a loss, end the mission -- and giving those the respawn
        # treatment ran the reaction at t=0. MISS_ShipyardEscape called show_game_results in
        # the first tick that way.
        xml = os.path.join(self.tmp.name, "MISS_Gone.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Gone.</mission_description>
  <start>
    <create type="player" player_slot="0" x="1" y="0" z="2" sideValue="2"/>
    <create type="station" x="5" y="0" z="5" name="DS1" sideValue="2"/>
    <create type="enemy" x="9" y="0" z="9" name="KR1" sideValue="1"/>
  </start>
  <event name="Rebuild the enemy">
    <if_not_exists name="KR1"/>
    <create type="enemy" x="9" y="0" z="9" name="KR1" sideValue="1"/>
  </event>
  <event name="Base lost">
    <if_not_exists name="DS1"/>
    <end_mission/>
  </event>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        # the real respawn keeps its route + initial schedule
        self.assertIn("=== respawn_0", story)
        self.assertIn("task_schedule(respawn_0)", story)
        self.assertIn('//damage/destroy if has_role(DESTROYED_ID, "respawn_KR1")', story)
        # the reaction must NOT become a scheduled respawn -- that fires end_mission at t=0
        self.assertEqual(story.count("=== respawn_"), 1)
        self.assertNotIn("task_schedule(respawn_1)", story)
        # it stays a guarded polling loop, so it only fires once DS1 really is gone
        self.assertIn("not object_exists(obj_ds1)", story)

    def test_unset_timer_does_not_fire_at_t0(self):
        # is_timer_finished answers True for a timer that was NEVER SET ("nothing pending"
        # reads as done), so a guard on one is true from the first tick. Four corpus
        # missions ran their end-game loop immediately and called show_game_results seconds
        # in. 2.8 does not fire an event on a timer that never started.
        xml = os.path.join(self.tmp.name, "MISS_Timer.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Timer.</mission_description>
  <start>
    <create type="player" player_slot="0" x="1" y="0" z="2" sideValue="2"/>
  </start>
  <event name="Arm it">
    <if_distance name1="Artemis" player_slot2="0" comparator="LESS" value="500"/>
    <set_timer name="game_end" seconds="60"/>
  </event>
  <event name="The end">
    <if_timer_finished name="game_end"/>
    <end_mission/>
  </event>
  <event name="Never armed">
    <if_timer_finished name="ghost_timer"/>
    <log text="should not fire at t=0"/>
  </event>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast", event_model="linear")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        # a timer the mission really sets -> wait for it to be set AND expire
        self.assertIn('await is_timer_set_and_finished(0, "game_end")', story)
        # a timer nothing ever sets can never fire in 2.8 either -- skip the scene rather
        # than block the chain forever on something that is not coming. (Skip is a jump to
        # the next scene, or ->END on the last one, which this is.)
        self.assertRegex(story, r'(?:jump event_\d+|->END) if not '
                                r'\(is_timer_set_and_finished\(0, "ghost_timer"\)\)')
        # the bare form must be gone everywhere: it is true before the timer exists
        self.assertNotIn("is_timer_finished(0,", story)

    def test_chained_flag_latch_skips_and_phase_gate_waits(self):
        # The two things a 2.8 flag test means need OPPOSITE translations in a chain, and
        # getting it backwards is worse than the comment it replaces:
        #   "phase != 1"  -> run-once bookkeeping. Already done? skip this scene.
        #   "phase == 1"  -> wait until the story gets here.
        xml = os.path.join(self.tmp.name, "MISS_Flags.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Flags.</mission_description>
  <start>
    <create type="player" player_slot="0" x="1" y="0" z="2" sideValue="2"/>
  </start>
  <event name="Opening">
    <if_variable name="phase" comparator="NOT" value="1.0"/>
    <log text="opening"/>
    <set_variable name="phase" value="1.0"/>
  </event>
  <event name="After opening">
    <if_variable name="phase" comparator="EQUALS" value="1.0"/>
    <log text="second"/>
  </event>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast", event_model="linear")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        # latch -> skip forward, never a wait (its own body sets the flag too)
        self.assertRegex(story, r"jump event_\d+ if not \(phase != 1\.0\)")
        # phase gate produced by the EARLIER scene -> a wait, which can actually resolve
        self.assertRegex(story, r"---wait_flag_\d+\n    await delay_sim\(0\.5\)\n"
                                r"    jump wait_flag_\d+ if not \(phase == 1\.0\)")
        self.assertNotIn("# guard: phase", story)

    def test_flag_gate_set_only_by_a_later_scene_does_not_deadlock(self):
        # 2.8 events run continuously, so a gate set by a "later" event is fine there. A
        # linear chain waiting on its own future would hang, and a deadlocked mission is
        # worse than a mistimed one -- so it skips, and MIGRATION_NOTES says so.
        xml = os.path.join(self.tmp.name, "MISS_Backwards.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Backwards.</mission_description>
  <start>
    <create type="player" player_slot="0" x="1" y="0" z="2" sideValue="2"/>
  </start>
  <event name="Needs the flag">
    <if_variable name="late" comparator="EQUALS" value="1.0"/>
    <log text="needs it"/>
  </event>
  <event name="Sets the flag">
    <if_timer_finished name="t"/>
    <set_variable name="late" value="1.0"/>
  </event>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast", event_model="linear")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        with open(os.path.join(d, "MIGRATION_NOTES.md"), encoding="utf-8") as f:
            notes = f.read()
        self.assertRegex(story, r"jump event_\d+ if not \(late == 1\.0\)")
        self.assertNotIn("wait_flag", story)      # a wait here would never resolve
        self.assertIn("only a LATER scene sets", notes)

    def test_chained_scenes_gate_on_box_difficulty_and_fleet_counts(self):
        # A chained scene whose conditions all degrade to comments has NO gate and runs the
        # instant the chain reaches it. _cond_bool could already express these three; only
        # the chain path was dropping them. Region triggers WAIT (same as the sphere pair);
        # difficulty is settled before the mission starts, so it SKIPS.
        xml = os.path.join(self.tmp.name, "MISS_Gates.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Gates.</mission_description>
  <start>
    <create type="player" player_slot="0" x="1" y="0" z="2" sideValue="2"/>
    <create type="enemy" x="9" y="0" z="9" name="KR1" sideValue="1"/>
  </start>
  <event name="Region">
    <if_inside_box player_slot="0" leastX="10" leastZ="10" mostX="99" mostZ="99"/>
    <log text="in the box"/>
  </event>
  <event name="Hard only">
    <if_difficulty comparator="GREATER" value="5"/>
    <log text="hard"/>
  </event>
  <event name="Thinned out">
    <if_fleet_count comparator="LESS_EQUAL" value="2" sideValue="1"/>
    <log text="thinned"/>
  </event>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast", event_model="linear")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        # region trigger -> a poll wait on the a2x_in_box helper that always existed
        self.assertIn("a2x_in_box(", story)
        self.assertRegex(story, r"---wait_box_\d+\n    await delay_sim\(0\.5\)\n"
                                r"    jump wait_box_\d+ if not \(a2x_in_box\(")
        # difficulty -> a skip to the next scene, never a wait
        self.assertRegex(story, r"jump event_\d+ if not \(DIFFICULTY > 5\)")
        # a non-zero fleet comparator has no awaitable, so it polls the count
        self.assertRegex(story, r"jump wait_fleet_\d+ if not \(len\(to_object_list\("
                                r'role\("enemy"\)\)\) <= 2\)')
        # none of the three may be left as a bare comment
        for dead in ("# guard: a2x_in_box", "# when: difficulty", "# when: fleet"):
            self.assertNotIn(dead, story)

    def test_chained_exists_guard_skips_the_scene_not_the_mission(self):
        # An if_exists/if_not_exists in a CHAINED scene used to emit `->END if ...`, which
        # ends the whole map task -- so one unmet condition silently threw away every
        # remaining scene (862 scenes across 22 corpus missions). 2.8 just skips the event.
        xml = os.path.join(self.tmp.name, "MISS_Guard.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Guard.</mission_description>
  <start>
    <create type="player" player_slot="0" x="1" y="0" z="2" sideValue="2"/>
    <create type="station" x="3" y="0" z="4" name="DS1" sideValue="2"/>
  </start>
  <event name="First">
    <if_exists name="DS1"/>
    <log text="one"/>
  </event>
  <event name="Second">
    <if_not_exists name="DS1"/>
    <log text="two"/>
  </event>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast", event_model="linear")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        # the non-final scene hands off to the next one...
        self.assertIn("jump event_1 if not object_exists(obj_ds1)", story)
        # ...and only the LAST scene ends the task, where the chain ends anyway
        self.assertIn("->END if object_exists(obj_ds1)", story)
        self.assertNotIn("->END if not object_exists(obj_ds1)", story)

    def test_player_respawn_event_uses_the_cosmos_respawn(self):
        # 2.8 "the crew died" idiom: an event gated on the player not existing that
        # re-creates it. Cosmos does this itself -- basic_player_destroy revives the SAME
        # ship at its spawn point when PLAYER_SHIP_RESPAWN is on -- and re-creating instead
        # loses the crew, whose clients the destroy route already sent to console-select.
        d, story = self._convert_respawn("mast")
        with open(os.path.join(d, "settings.yaml"), encoding="utf-8") as f:
            self.assertIn("PLAYER_SHIP_RESPAWN: true", f.read())
        route = story[story.index("//shared/signal/player_ship_destroyed"):]
        route = route[:route.index("\n\n")]
        # the mission's own reaction is kept...
        self.assertIn('a2x_big_message("Mission Failed!", "You are Dead"', route)
        # ...its other condition still guards (which is what keeps the 2.8 one-shot: the
        # body clears the very flag the guard reads)...
        self.assertIn("->END if not (Mission_Complete == 1.0)", route)
        # ...but if_not_exists does NOT, because that is what the signal means -- and the
        # ship still exists (flagged "exploded") at the moment it fires.
        self.assertNotIn("object_exists", route)
        # the duplicate create is dropped: only the <start> roster spawns players
        self.assertNotIn("a2x_create_player(", route)
        self.assertEqual(story.count("a2x_create_player("), 8)
        # and it is no longer a scene in the chain, where it would only get one shot at
        # whatever point the chain reached it
        self.assertNotIn("# You Died", story[:story.index("//shared/signal/player_ship_destroyed")])

    def test_non_ascii_source_text_cannot_break_the_story_load(self):
        # MastStory.from_file reads with the PLATFORM codec (cp1252 on Windows), so one
        # byte it cannot decode fails the whole story: no labels, no @map, the mission
        # silently never starts -- and the headless runner still says "PASS - no runtime
        # errors" because nothing ran to error. MISS_JewelHeist did exactly that on the
        # three U+015D in its Ximni flavour text. Every engine-read file must be ASCII.
        xml = os.path.join(self.tmp.name, "MISS_Accents.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>A café – the “Quiet” sector…</mission_description>
  <start>
    <create type="player" player_slot="0" x="1" y="0" z="2" sideValue="2"/>
    <incoming_comms_text from="Bunenag Aŝor" message="Mokamer Flaz — naïve…"/>
  </start>
</mission_data>
""")
        for target in ("mast", "amd"):
            d = convert_file(xml, self.out + target, target=target)
            for fn in os.listdir(d):
                if not fn.endswith((".mast", ".amd", ".yaml", ".json")):
                    continue
                raw = open(os.path.join(d, fn), "rb").read()
                raw.decode("cp1252")   # the engine's read -- must not raise
                self.assertTrue(all(b < 128 for b in raw), f"{target}/{fn} is not ASCII")
        # and the text survives readably rather than being dropped
        with open(os.path.join(self.out + "mast", "accents", "story.mast"), encoding="utf-8") as f:
            story = f.read()
        self.assertIn("Bunenag Asor", story)
        self.assertIn('"Quiet"', story)

    def test_amd_target_asks_for_the_quest_tab_that_displays_its_tree(self):
        # The AMD target's whole point is a live objectives log. `quests` is only the
        # DRIVER (quest_driver runs the tree); the log the crew actually reads is the quest
        # tab in the `documents` addon. Without it the tree is built and then invisible.
        d = convert_file(self.xml, self.out, target="amd")
        with open(os.path.join(d, "story.json"), encoding="utf-8") as f:
            sjson = f.read()
        for addon in ("quests", "documents"):
            self.assertIn(f"LegendaryMissions.{addon}.", sjson, addon)
        # the MAST target has no quest tree, so it must not drag the tab in
        dm = convert_file(self.xml, self.out + "_m", target="mast")
        with open(os.path.join(dm, "story.json"), encoding="utf-8") as f:
            self.assertNotIn("LegendaryMissions.documents.", f.read())

    def test_player_respawn_event_routed_in_the_amd_target_too(self):
        d, story = self._convert_respawn("amd")
        self.assertIn("//shared/signal/player_ship_destroyed", story)
        self.assertTrue(os.path.exists(os.path.join(d, "settings.yaml")))

    def test_no_settings_yaml_when_nothing_needs_one(self):
        # settings.yaml is written only when a setting must be flipped -- an empty one is
        # just another file for the porter to explain.
        d = convert_file(self.xml, self.out, target="mast")
        self.assertFalse(os.path.exists(os.path.join(d, "settings.yaml")))

    def test_roster_fill_stays_on_the_map(self):
        # The fill is laid out along Z from the mission's own player ship. A 2.8 mission
        # that starts its crew hard against an edge (98000 -- they meant it: the crew flies
        # in from there) pushed the fill past 100000, and a2x_pos mirrors about 100000, so
        # those hulls landed on NEGATIVE Cosmos coords: pickable at ship select, nowhere in
        # the world. The mission's own coordinates are still emitted untouched.
        xml = os.path.join(self.tmp.name, "MISS_Edge.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Edge.</mission_description>
  <start>
    <create type="player" player_slot="0" x="98000" y="0" z="98000" sideValue="2"/>
  </start>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        self.assertIn('a2x_create_player(98000, 0, 98000,', story)   # the mission's own
        zs = [float(l.split("a2x_create_player(")[1].split(",")[2])
              for l in story.splitlines() if "a2x_create_player(" in l]
        self.assertEqual(len(zs), 8)
        for z in zs:
            self.assertGreaterEqual(z, 0)
            self.assertLessEqual(z, 100000)
        # laid out AWAY from the edge, still 1000 apart -- not stacked on the clamp
        self.assertEqual(sorted(zs), [91000, 92000, 93000, 94000,
                                      95000, 96000, 97000, 98000])

    def test_player_created_in_an_event_stays_in_the_event(self):
        # Only <start> players are the starting roster. MISS_Medusa's_Maze spawns a player
        # from an EVENT -- that is mid-mission gameplay and must not be hoisted to server
        # start (nor must the roster fill kick in and add eight ships alongside it).
        xml = os.path.join(self.tmp.name, "MISS_LatePlayer.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Late player.</mission_description>
  <start>
    <create type="station" x="1" y="0" z="2" name="DS1" sideValue="2"/>
  </start>
  <event>
    <if_timer_finished name="t1"/>
    <create type="player" player_slot="0" x="5" y="0" z="6" sideValue="2"/>
  </event>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        self.assertNotIn("//shared/signal/create_player_ships", story)
        self.assertEqual(story.count("a2x_create_player("), 1)
        self.assertGreater(story.index("a2x_create_player("), story.index("@map/"))

    def test_sides_are_not_collapsed_onto_lm_keys(self):
        # 2.8 sideValue is a faction index, not a 3-valued enum: MISS_The_Arena puts
        # eight player ships on sideValues 4..11, each with its own station. Collapsing
        # those onto tsn/raider/civ would make all eight teams allies.
        xml = os.path.join(self.tmp.name, "MISS_Arena.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>PvP.</mission_description>
  <start>
    <create type="player" player_slot="0" x="1" y="0" z="1" name="A" sideValue="4"/>
    <create type="player" player_slot="1" x="2" y="0" z="2" name="B" sideValue="5"/>
    <create type="station" x="3" y="0" z="3" name="AS" sideValue="4"/>
  </start>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        self.assertIn("a2x_declare_sides([4, 5])", story)
        self.assertIn('side="side_4"', story)
        self.assertIn('side="side_5"', story)
        # the station pairs with its own team, not a shared "friendly"
        self.assertIn('a2x_create_station(3, 0, 3, "starbase_command", side="side_4"', story)

    def test_set_side_value_target_is_declared(self):
        # a mid-mission defection must land on a side that has diplomacy, or the ship
        # silently stops being anyone's enemy.
        xml = os.path.join(self.tmp.name, "MISS_Defect.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>Defect.</mission_description>
  <start>
    <create type="enemy" x="1" y="0" z="1" name="KR01" sideValue="1"/>
  </start>
  <event name="Turn">
    <if_variable name="a1" comparator="EQUALS" value="1"/>
    <set_side_value name="KR01" value="3"/>
  </event>
</mission_data>
""")
        d = convert_file(xml, self.out, target="mast")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            story = f.read()
        self.assertIn("a2x_set_side_value(obj_kr01, 3)", story)
        self.assertIn("3", story.split("a2x_declare_sides(")[1].split(")")[0])

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

    def test_player_slot_property_targets_player_ship(self):
        # set/addto_object_property on a player_slot (no name) -> the player ship, so mapped
        # player props (energy / count* / shieldState) are real calls, not lost TODOs.
        from arme2cosmos.emit import Emitter
        from arme2cosmos.model import XmlNode
        em = Emitter.__new__(Emitter)
        em.notes = []
        em.addons = set()
        em.symbols = {}
        em.player_var = "player_ship"
        em.player_emitted = True   # these fixtures emit AFTER the create:player line
        s = em.c_set_object_property(XmlNode("set_object_property", {"property": "energy", "value": "1100", "player_slot": "0"}))
        self.assertEqual(s, ['    a2x_set_object_property(player_ship, "energy", 1100)'])
        a = em.c_addto_object_property(XmlNode("addto_object_property", {"property": "countEMP", "value": "2", "player_slot": "0"}))
        self.assertEqual(a, ['    a2x_addto_object_property(player_ship, "countEMP", 2)'])

    def test_player_carried_type_maps_to_hangar_craft(self):
        # 2.8 set_player_carried_type (bay of a fighter/bomber/shuttle) -> LM hangar_random_
        # craft_spawn of that variant (no bays; it spawns + associates with the ship).
        from arme2cosmos.emit import Emitter
        from arme2cosmos.model import XmlNode
        em = Emitter.__new__(Emitter)
        em.notes = []
        em.addons = set()
        em.symbols = {}
        em.player_var = "player_ship"
        em.player_emitted = True   # these fixtures emit AFTER the create:player line
        out = em.c_set_player_carried_type(XmlNode("set_player_carried_type", {"player_slot": "0", "bay_slot": "0", "hullKeys": "singleseat TSN Bomber", "name": "Badger"}))
        self.assertEqual(out, ['    hangar_random_craft_spawn(player_ship, "bomber")'])
        self.assertIn("hangar", em.addons)
        em.symbols["Beachwood"] = "obj_beachwood"
        out2 = em.c_set_player_station_carried(XmlNode("set_player_station_carried", {"name": "Beachwood", "hullKeys": "singleseat fighter"}))
        self.assertEqual(out2, ['    hangar_random_craft_spawn(obj_beachwood, "fighter")'])

    def test_add_ai_point_throttle_maps_to_target_pos(self):
        # add_ai POINT_THROTTLE (fly to a point at a throttle) -> target_pos with the coordinate
        # flip; the engine steers the NPC there (was a no-op a2x_add_ai before).
        from arme2cosmos.emit import Emitter
        from arme2cosmos.model import XmlNode
        em = Emitter.__new__(Emitter)
        em.notes = []
        em.addons = set()
        em.symbols = {"Profit": "obj_profit"}
        out = em.c_add_ai(XmlNode("add_ai", {"type": "POINT_THROTTLE", "value1": "2000", "value2": "0", "value3": "15000", "value4": "1.0", "name": "Profit"}))
        self.assertEqual(out, ['    target_pos(obj_profit, *a2x_pos(2000, 0, 15000), 1.0)'])
        # DIR_THROTTLE -> a2x_dir_throttle(heading, throttle) (goto_object_or_location brain)
        outd = em.c_add_ai(XmlNode("add_ai", {"type": "DIR_THROTTLE", "value1": "270", "value2": "0.3", "name": "Profit"}))
        self.assertEqual(outd, ['    a2x_dir_throttle(obj_profit, 270, 0.3)'])
        # DEFEND -> LM defender role + protect-area objective
        outdef = em.c_add_ai(XmlNode("add_ai", {"type": "DEFEND", "value1": "5000", "value2": "5000", "name": "Profit"}))
        self.assertEqual(outdef, ['    add_role(obj_profit, "prefab_npc_defender")', '    objective_add(obj_profit, objective_protect_area)'])
        # FOLLOW_COMMS_ORDERS -> orderable + the LM orders popup (defender role + give_orders_type)
        out2 = em.c_add_ai(XmlNode("add_ai", {"type": "FOLLOW_COMMS_ORDERS", "name": "Profit"}))
        self.assertEqual(out2, ['    add_role(obj_profit, "civ")',
                                '    add_role(obj_profit, "friendly")',
                                '    add_role(obj_profit, "prefab_npc_defender")',
                                '    set_inventory_value(obj_profit, "give_orders_type", "objective/orders/defender")'])

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
        em.side_values, em.player_side = set(), None
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
        dh = convert_file(self.xml, self.out + "h", event_model="hybrid", target="mast")
        dl = convert_file(self.xml, self.out + "l", event_model="linear", target="mast")
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
        d = convert_file(self.xml, self.out, target="mast")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            return f.read()

    def test_a28_compatible_makes_every_event_a_polling_task(self):
        # worst-case faithful: no chain, no routes -- both events become ind_event loops.
        d = convert_file(self.xml, self.out + "a", event_model="a28_compatible", target="mast")
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
        d = convert_file(self.xml, self.out, target="mast")
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
        em.player_emitted = True   # emitting AFTER the create:player line
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
        # unmapped property -> TODO (use a synthetic name so it stays unmapped as real
        # 2.8 properties get wired over time)
        todo = em.c_set_object_property(XmlNode("set_object_property",
               {"name": "X", "property": "someUnmapped2p8Prop", "value": "1"}))
        self.assertTrue(any("# TODO" in ln for ln in todo))

    def test_use_gm_selection_resolves_to_comms_selected(self):
        # 2.8 commands carrying use_gm_selection act on the GM's selection; in the
        # converter's gamemaster //comms tree that is COMMS_SELECTED_ID -- not a TODO.
        from arme2cosmos.emit import Emitter
        from arme2cosmos.model import XmlNode
        em = Emitter.__new__(Emitter)
        em.notes, em.addons, em.symbols, em.player_var, em.hullmap = [], set(), {}, None, None
        add = em.c_add_ai(XmlNode("add_ai", {"type": "CHASE_PLAYER", "use_gm_selection": ""}))
        self.assertEqual(add, ['    a2x_add_ai(COMMS_SELECTED_ID, "CHASE_PLAYER")'])
        clr = em.c_clear_ai(XmlNode("clear_ai", {"use_gm_selection": ""}))
        self.assertEqual(clr, ["    a2x_clear_ai(COMMS_SELECTED_ID)"])
        # it also feature-detects the gamemaster addons
        self.assertIn("gamemaster_comms", em.addons)
        # without use_gm_selection and no captured name -> still a TODO
        self.assertTrue(any("# TODO" in ln for ln in
                            em.c_clear_ai(XmlNode("clear_ai", {"name": "ghost"}))))

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


class AmdQuestStructureTests(unittest.TestCase):
    """The AMD target's quest-tree classification: value-specific end-deciders, no spurious
    win/lose TODOs, and the timed-beat gate fallback."""

    def _amd(self, mission):
        from arme2cosmos.emit import Emitter
        from arme2cosmos.amd_emit import build_amd_target
        em = Emitter(mission, hullmap=None)
        return build_amd_target(mission, em, "v1.4.0")["story.amd"]

    def test_phase_counter_advance_is_not_a_decider(self):
        # end_mission gates on Event1 >= 19; a setup event that merely advances Event1 to 3
        # must NOT be classified as a win/lose decider (value-specific _is_decider).
        from arme2cosmos.model import Mission, Event, XmlNode
        m = Mission(name="MISS_Phase", source_path="p.xml")
        end = Event(name="End", index=0,
                    conditions=[XmlNode("if_variable", {"name": "Event1", "comparator": "GREATER_EQUAL", "value": "19"})],
                    commands=[XmlNode("end_mission", {})])
        setup = Event(name="Build Maze", index=1,
                      conditions=[XmlNode("if_variable", {"name": "Event1", "comparator": "EQUALS", "value": "2"})],
                      commands=[XmlNode("create", {"type": "asteroids", "count": "5", "startX": "50000", "startY": "0", "startZ": "50000"}),
                                XmlNode("set_variable", {"name": "Event1", "value": "3", "integer": "yes"})])
        m.events = [end, setup]
        amd = self._amd(m)
        # the setup event should not carry the "win or lose?" decider TODO
        self.assertNotIn("win or lose?", amd)

    def test_no_win_lose_todo_ever(self):
        # even a REAL end-decider (sets the gate value) is left neutral, not a story.amd TODO.
        from arme2cosmos.model import Mission, Event, XmlNode
        m = Mission(name="MISS_Decide", source_path="d.xml")
        end = Event(name="End", index=0,
                    conditions=[XmlNode("if_variable", {"name": "Win", "comparator": "EQUALS", "value": "1"})],
                    commands=[XmlNode("end_mission", {})])
        decider = Event(name="Trigger", index=1,
                        conditions=[XmlNode("if_variable", {"name": "Setup", "comparator": "EQUALS", "value": "1"})],
                        commands=[XmlNode("set_variable", {"name": "Win", "value": "1", "integer": "yes"})])
        m.events = [end, decider]
        amd = self._amd(m)
        self.assertNotIn("win or lose?", amd)
        self.assertNotIn("mark `Win:`", amd)  # kill-grouping TODO also neutralized


DISTANCE_SAMPLE = """<?xml version="1.0" ?>
<mission_data version="2.8">
  <mission_description>distance</mission_description>
  <start>
    <create type="station" x="50000" y="0" z="50000" name="Base" raceKeys="TSN"/>
    <create type="player" player_slot="0" x="10000" y="0" z="10000"/>
  </start>
  <event name="Close To Base">
    <if_distance name1="Base" player_slot2="0" comparator="LESS" value="5000"/>
    <set_variable name="near" value="1" integer="yes"/>
  </event>
  <event name="Far From Ghost">
    <if_distance name1="Ghost" name2="Base" comparator="GREATER" value="9000"/>
    <set_variable name="far" value="1" integer="yes"/>
  </event>
</mission_data>
"""


class DistanceConditionTests(unittest.TestCase):
    """A two-object if_distance in a polling loop must use the guarded a2x helpers.

    A raw ``sbs.distance_id`` crashes the engine ("was sent None") the moment either
    handle is None -- an a2x_named miss, or an object that has been destroyed.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.xml = os.path.join(self.tmp.name, "MISS_Dist.xml")
        with open(self.xml, "w", encoding="utf-8") as f:
            f.write(DISTANCE_SAMPLE)

    def tearDown(self):
        self.tmp.cleanup()

    def _story(self):
        # a28_compatible: every event is a polling loop, so conditions go through
        # the live-boolean path (_cond_bool) rather than the await path.
        d = convert_file(self.xml, os.path.join(self.tmp.name, "out"),
                         event_model="a28_compatible", target="mast")
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            return f.read()

    def test_polling_distance_uses_guarded_helpers(self):
        story = self._story()
        self.assertIn("a2x_distance_less(", story)
        self.assertIn("a2x_distance_greater(", story)

    def test_no_raw_distance_id_emitted(self):
        self.assertNotIn("sbs.distance_id", self._story())

    def test_unresolved_name_still_goes_through_a_guarded_helper(self):
        # "Ghost" is never created -> a2x_named(), which returns None at runtime.
        story = self._story()
        self.assertIn('a2x_distance_greater(a2x_named("Ghost")', story)


if __name__ == "__main__":
    unittest.main()
