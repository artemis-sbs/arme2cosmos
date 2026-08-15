"""How a 2.8 timer is classified, and what each arming site then emits.

2.8 has no way for a timer to say "I am done", so every timed thing the converter wrote
became a ``delay_sim(0.5)`` task resident from t=0 -- 1839 of them across the reference
corpus, oversampling a median 10-second timer by 20x. ``set_timer(signal=)`` and
``set_interval`` let the engine push the deadline instead, which is what these cover.
"""
import os
import re
import tempfile
import unittest

from arme2cosmos.convert import convert_file, _prescan_timer_model, _prescan_named_objects
from arme2cosmos.emit import Emitter, emit_condition
from arme2cosmos.model import XmlNode
from arme2cosmos.parser import parse_file


TIMER_MISSION = """<?xml version="1.0" ?>
<mission_data version="2.8" playerShipNames_arme="Artemis">
  <mission_description>Timers.</mission_description>
  <start>
    <create type="player" player_slot="0" x="0" y="0" z="0" sideValue="2"/>
    <set_timer name="Lone" seconds="60"/>
    <set_timer name="Guarded" seconds="45"/>
    <set_timer name="Heartbeat" seconds="7"/>
    <set_timer name="Ramp" seconds="30"/>
    <set_timer name="Contested" seconds="5"/>
    <set_timer name="Ignored" seconds="99"/>
  </start>
  <event name="Lone timer">
    <if_timer_finished name="Lone"/>
    <set_variable name="lone_done" value="1"/>
  </event>
  <event name="Guarded timer">
    <if_timer_finished name="Guarded"/>
    <if_variable name="phase" comparator="EQUALS" value="2"/>
    <set_variable name="guarded_done" value="1"/>
  </event>
  <event name="Heartbeat">
    <if_timer_finished name="Heartbeat"/>
    <set_timer name="Heartbeat" seconds="7"/>
    <set_variable name="beats" value="1"/>
  </event>
  <event name="Ramp beat">
    <if_timer_finished name="Ramp"/>
    <set_timer name="Ramp" seconds="3"/>
    <set_variable name="ramped" value="1"/>
  </event>
  <event name="Contested A">
    <if_timer_finished name="Contested"/>
    <if_variable name="which" comparator="EQUALS" value="1"/>
    <set_variable name="a_done" value="1"/>
  </event>
  <event name="Contested re-arm">
    <if_variable name="which" comparator="EQUALS" value="9"/>
    <set_timer name="Contested" seconds="5"/>
  </event>
</mission_data>
"""


class TimerModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.xml = os.path.join(self.tmp.name, "MISS_Timers.xml")
        with open(self.xml, "w", encoding="utf-8") as f:
            f.write(TIMER_MISSION)
        self.mission = parse_file(self.xml)
        self.em = Emitter(self.mission)
        _prescan_named_objects(self.mission, self.em)
        _prescan_timer_model(self.mission, self.em)

    def story(self, target="mast"):
        d = convert_file(self.xml, os.path.join(self.tmp.name, "out_" + target), target=target)
        with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
            return f.read()

    # -- classification ----------------------------------------------------

    def test_a_timer_tested_from_one_arming_is_a_one_shot_signal(self):
        self.assertEqual(self.em.timer_verdict["Lone"], "ONESHOT")
        self.assertEqual(self.em.timer_verdict["Guarded"], "ONESHOT")

    def test_a_timer_its_own_event_re_arms_is_an_interval(self):
        self.assertEqual(self.em.timer_verdict["Heartbeat"], "INTERVAL")
        self.assertEqual(self.em.timer_period["Heartbeat"], "7")

    def test_a_different_repeat_period_is_a_ramp_not_an_interval(self):
        """A long lead-in then a fast beat is not one period, so it stays a
        self-re-arming set_timer -- which mirrors what 2.8 literally wrote."""
        self.assertEqual(self.em.timer_verdict["Ramp"], "INTERVAL_RAMP")

    def test_a_timer_armed_from_several_unrelated_places_keeps_polling(self):
        """Which arming is live at any moment is a runtime question, so there is no one
        deadline to hang a deferred loop off."""
        self.assertEqual(self.em.timer_verdict["Contested"], "POLL")

    def test_a_timer_nothing_tests_is_left_alone(self):
        self.assertEqual(self.em.timer_verdict["Ignored"], "DEAD")
        self.assertNotIn("Ignored", self.em.timer_signal)

    def test_every_timer_gets_its_own_signal_name(self):
        sigs = list(self.em.timer_signal.values())
        self.assertEqual(len(sigs), len(set(sigs)))

    # -- emission ----------------------------------------------------------

    def test_a_lone_timer_becomes_a_route_and_no_loop(self):
        story = self.story()
        self.assertIn('set_timer(0, "Lone", seconds=60, signal="a2x_timer_lone")', story)
        self.assertIn("//shared/signal/a2x_timer_lone", story)
        self.assertNotRegex(story, r"=== ind_event_\d+   # Lone timer")

    def test_a_guarded_one_shot_keeps_its_loop_but_starts_it_at_the_deadline(self):
        """Exactly equivalent to polling from t=0: the event cannot fire before the
        deadline, so every tick before it was never going to do anything."""
        story = self.story()
        self.assertRegex(
            story,
            r"//shared/signal/a2x_timer_guarded[^\n]*\n\s+task_schedule\(ind_event_\d+\)")

    def test_a_guarded_one_shot_is_not_also_started_up_front(self):
        story = self.story()
        deferred = re.search(
            r"//shared/signal/a2x_timer_guarded[^\n]*\n\s+task_schedule\((ind_event_\d+)\)",
            story)
        self.assertIsNotNone(deferred, "expected a deferral route")
        label = deferred.group(1)
        upfront = story.split("@map/", 1)[1]
        upfront = re.split(r"^(?:===|//)", upfront, maxsplit=1, flags=re.M)[0]
        self.assertNotIn(f"task_schedule({label})", upfront)

    def test_an_interval_is_armed_once_and_its_re_arm_is_dropped(self):
        story = self.story()
        self.assertIn('set_interval(0, "Heartbeat", "a2x_timer_heartbeat", seconds=7)', story)
        self.assertIn("the interval above already repeats", story)
        self.assertNotIn('set_timer(0, "Heartbeat"', story)

    def test_a_ramp_re_arms_itself_through_the_signal(self):
        story = self.story()
        self.assertIn('set_timer(0, "Ramp", seconds=30, signal="a2x_timer_ramp")', story)
        self.assertIn('set_timer(0, "Ramp", seconds=3, signal="a2x_timer_ramp")', story)

    def test_a_polling_timer_is_emitted_exactly_as_before(self):
        story = self.story()
        self.assertIn('set_timer(0, "Contested", seconds=5)', story)
        self.assertNotIn("a2x_timer_contested", story)

    def test_armed_signals_and_routes_always_agree(self):
        """A `signal=` nobody handles is a lie in the source; the reverse -- a route on a
        signal nothing arms -- leaves the mission waiting forever, which is exactly what a
        name-vs-signal mix-up in the commit step produced (a whole mission stalled at the
        first deadline, and still reported PASS)."""
        for target in ("mast", "amd"):
            story = self.story(target)
            armed = set(re.findall(r'signal="(a2x_timer_\w+)"', story))
            armed |= set(re.findall(r'set_interval\(0, "[^"]*", "(a2x_timer_\w+)"', story))
            routed = set(re.findall(r"//shared/signal/(a2x_timer_\w+)", story))
            self.assertEqual(armed, routed,
                             f"armed timer signals and routes disagree in the {target} target")

    def test_the_chained_scene_form_still_polls(self):
        """A chain can reach its wait long after the timer already fired, so awaiting a
        signal there would hang forever. This is the one place polling is correct."""
        node = XmlNode("if_timer_finished", {"name": "Lone"})
        self.assertEqual(emit_condition(self.em, node, 0, next_label="event_1"),
                         ['    await is_timer_set_and_finished(0, "Lone")'])


LABEL_COLLISION = """<?xml version="1.0" ?>
<mission_data version="2.8" playerShipNames_arme="Artemis">
  <mission_description>Collide.</mission_description>
  <start>
    <create type="player" player_slot="0" x="0" y="0" z="0" sideValue="2"/>
    <set_variable name="gate_0" value="0"/>
    <set_variable name="beat_1" value="0"/>
    <set_variable name="ind_event_2" value="0"/>
  </start>
  <event name="Uses them">
    <if_variable name="gate_0" comparator="EQUALS" value="1"/>
    <set_variable name="beat_1" value="1"/>
  </event>
</mission_data>
"""


class ReservedLabelNameTests(unittest.TestCase):
    """A 2.8 variable must never land on a name this tool gives a LABEL.

    Since 2026-08-14 a MAST label's name is reserved: assigning to it is a compile error,
    and a story that does not compile schedules no task at all -- 0 labels, no output, and
    a headless run still reports PASS. 2.8 variable names are author-written, so
    ``<set_variable name="gate_0"/>`` is the whole exploit.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.xml = os.path.join(self.tmp.name, "MISS_Collide.xml")
        with open(self.xml, "w", encoding="utf-8") as f:
            f.write(LABEL_COLLISION)

    def test_a_variable_named_like_a_label_is_renamed(self):
        for target in ("mast", "amd"):
            d = convert_file(self.xml, os.path.join(self.tmp.name, "o_" + target), target=target)
            with open(os.path.join(d, "story.mast"), encoding="utf-8") as f:
                story = f.read()
            for name in ("gate_0", "beat_1", "ind_event_2"):
                self.assertNotRegex(
                    story, rf"^\s*(?:default )?shared {name} = ",
                    f"{name} would collide with a generated label in the {target} target")
                self.assertIn(f"shared {name}_ = ", story)


if __name__ == "__main__":
    unittest.main()
