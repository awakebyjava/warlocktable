"""The dice section of config: matching rules, and the rules it refuses.

    python -m unittest discover -s tests -v
"""

import json
import os
import tempfile
import unittest

from warlock.config import ConfigError, load_config, to_dict

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "data", "config.example.json")


def _write(tmpdir, dice):
    with open(EXAMPLE, encoding="utf-8") as fh:
        raw = json.load(fh)
    raw["dice"] = dice
    path = os.path.join(tmpdir, "config.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(raw, fh)
    return path


class DiceConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, dice):
        return load_config(_write(self.tmp.name, dice))

    def test_example_loads_and_round_trips(self):
        cfg = load_config(EXAMPLE)
        self.assertTrue(cfg.dice_enabled)
        self.assertEqual(len(cfg.dice_triggers), 2)
        out = to_dict(cfg)["dice"]
        self.assertEqual(out["triggers"][0]["face"], 20)
        self.assertEqual(out["known"]["03ef405d"]["name"], "Jon's d20")

    def test_first_match_wins(self):
        cfg = self.load({"triggers": [
            {"die": "03ef405d", "face": 20, "target": {"type": "scene", "name": "forest"}},
            {"type": "d20", "face": 20, "target": {"type": "scene", "name": "swamp"}},
            {"target": {"type": "scene", "name": "plains"}},
        ]})
        self.assertEqual(cfg.match_roll(["03ef405d"], "d20", 20).target.name, "forest")
        self.assertEqual(cfg.match_roll(["deadbeef"], "d20", 20).target.name, "swamp")
        self.assertEqual(cfg.match_roll(["deadbeef"], "d6", 3).target.name, "plains")

    def test_face_list_is_exact_membership(self):
        cfg = self.load({"triggers": [
            {"face": [18, 19, 20], "target": {"type": "scene", "name": "forest"}},
        ]})
        self.assertIsNotNone(cfg.match_roll([], "d20", 19))
        self.assertIsNone(cfg.match_roll([], "d20", 17))
        self.assertIsNone(cfg.match_roll([], "d20", 21))

    def test_die_matched_by_id_or_address(self):
        cfg = self.load({"triggers": [
            {"die": "CA:D8:66:FC:05:74", "target": {"type": "scene", "name": "forest"}},
        ]})
        self.assertIsNotNone(cfg.match_roll(["ca:d8:66:fc:05:74".upper()], "d20", 5))
        self.assertIsNone(cfg.match_roll(["03ef405d"], "d20", 5))

    def test_thresholds_are_refused(self):
        for bad in ({"min": 18}, {"max": 3}, {"at_least": 10}, {"dc": 15}):
            bad["target"] = {"type": "scene", "name": "forest"}
            with self.assertRaises(ConfigError) as cm:
                self.load({"triggers": [bad]})
            self.assertIn("game rule", str(cm.exception))

    def test_bad_face_shapes_refused(self):
        for face in ("20", [], ["a"], True, {"eq": 20}):
            with self.assertRaises(ConfigError):
                self.load({"triggers": [
                    {"face": face, "target": {"type": "scene", "name": "forest"}}]})

    def test_dangling_target_refused(self):
        with self.assertRaises(ConfigError):
            self.load({"triggers": [
                {"face": 20, "target": {"type": "scene", "name": "no_such_scene"}}]})

    def test_unknown_die_type_refused(self):
        with self.assertRaises(ConfigError):
            self.load({"triggers": [
                {"type": "d7", "target": {"type": "scene", "name": "forest"}}]})

    def test_seat_must_be_a_zone_colour(self):
        with self.assertRaises(ConfigError):
            self.load({"known": {"03ef405d": {"name": "x", "seat": "chartreuse"}}})

    def test_disabled(self):
        cfg = self.load({"enabled": False})
        self.assertFalse(cfg.dice_enabled)


class ControllerRollTests(unittest.TestCase):
    """handle_roll through the real controller with the fake devices."""

    def setUp(self):
        from warlock.controller import Controller
        from warlock.devices.fake import FakeAudioDevice, FakeDisplayDevice, FakeLightDevice
        from warlock.eventlog import EventLog
        from warlock.inputs.dice import FakeDiceScanner
        self.config = load_config(EXAMPLE)
        self.log = EventLog(path=None)
        self.controller = Controller(
            self.config, FakeLightDevice(self.log), FakeAudioDevice(self.log),
            FakeDisplayDevice(self.log), self.log)
        self.dice = FakeDiceScanner(self.log, self.controller.handle_roll)

    def kinds(self):
        return [e["kind"] for e in self.log.events]

    def test_matched_roll_fires_the_target(self):
        self.dice.roll("d20", 20)
        self.assertIn("dice.trigger", self.kinds())
        # the_sun is an interruption; the controller reports it playing
        self.assertTrue(any(e["kind"].startswith("interruption") for e in self.log.events))

    def test_unmatched_roll_is_logged_only(self):
        before = len(self.log.events)
        self.dice.roll("d20", 7)
        kinds = self.kinds()[before:]
        self.assertIn("dice.physical", kinds)
        self.assertNotIn("dice.trigger", kinds)
        rows = self.controller.roll_log()["rolls"]
        self.assertEqual(rows[0]["label"], "d20=7")
        self.assertTrue(rows[0]["physical"])
        self.assertEqual(rows[0]["name"], "fake")     # the die's own name

    def test_known_die_rolls_under_its_seat(self):
        from warlock.config import KnownDie
        colour = self.config.zones[1].colour
        self.config.dice_known["fa4e0001"] = KnownDie(key="fa4e0001", name="Sarah's d20",
                                                       die_type="d20", seat=colour)
        self.dice.roll("d20", 7)
        self.assertEqual(self.controller.roll_history(colour)["rolls"][0]["label"], "d20=7")
        self.assertEqual(self.controller.roll_log()["rolls"][0]["name"], "Sarah's d20")

    def test_disabled_ignores_rolls(self):
        self.config.dice_enabled = False
        self.dice.roll("d20", 20)
        self.assertNotIn("dice.physical", self.kinds())


if __name__ == "__main__":
    unittest.main()
