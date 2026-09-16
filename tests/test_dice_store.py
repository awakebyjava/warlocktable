"""The dice editor's writes through ConfigStore: validated, persisted,
rolled back when refused.

    python -m unittest discover -s tests -v
"""

import json
import os
import shutil
import tempfile
import unittest

from warlock.config import ConfigError, load_config
from warlock.configstore import ConfigStore
from warlock.eventlog import EventLog

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "data", "config.example.json")


class DiceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.json")
        shutil.copy(EXAMPLE, self.path)
        self.config = load_config(self.path)
        self.store = ConfigStore(self.config, self.path, EventLog(path=None),
                                 backup_dir=os.path.join(self.tmp.name, "backups"))

    def tearDown(self):
        self.tmp.cleanup()

    def on_disk(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)["dice"]

    def test_list_offers_only_what_exists(self):
        d = self.store.list_dice()
        self.assertEqual(d["seats"], [z.colour for z in self.config.zones])
        self.assertIn("d20", d["types"])
        self.assertIn("forest", d["targets"]["scene"])
        self.assertEqual(d["triggers"][0]["target_name"], "the_sun")

    def test_register_die_with_seat_persists(self):
        seat = self.config.zones[2].colour
        out = self.store.set_known_die("9F8E7D6C", "Sarah's d20", "d20", seat)
        self.assertEqual(out["die"], "9f8e7d6c")       # canonical: lowercase id
        self.assertEqual(out["action"], "created")
        self.assertEqual(self.on_disk()["known"]["9f8e7d6c"]["seat"], seat)
        out = self.store.set_known_die("9f8e7d6c", "Sarah's lucky d20", "d20", None)
        self.assertEqual(out["action"], "updated")
        self.assertNotIn("seat", self.on_disk()["known"]["9f8e7d6c"])

    def test_register_by_address(self):
        out = self.store.set_known_die("ca:d8:66:fc:05:74", "Spare", None, None)
        self.assertEqual(out["die"], "CA:D8:66:FC:05:74")

    def test_bad_seat_refused_and_nothing_written(self):
        before = self.on_disk()
        with self.assertRaises(ConfigError):
            self.store.set_known_die("9f8e7d6c", "x", "d20", "chartreuse")
        self.assertEqual(self.on_disk(), before)
        self.assertNotIn("9f8e7d6c", self.config.dice_known)

    def test_delete_die_blocked_while_a_trigger_names_it(self):
        self.store.set_known_die("9f8e7d6c", "Sarah's d20", "d20", None)
        self.store.set_dice_triggers([
            {"die": "9f8e7d6c", "face": 20, "target": {"type": "scene", "name": "forest"}}])
        with self.assertRaises(ConfigError) as cm:
            self.store.delete_known_die("9f8e7d6c")
        self.assertIn("trigger 1", str(cm.exception))
        self.store.set_dice_triggers([])
        self.store.delete_known_die("9f8e7d6c")
        self.assertNotIn("9f8e7d6c", self.on_disk()["known"])

    def test_triggers_replace_in_order(self):
        rows = [
            {"type": "d20", "face": [18, 19, 20], "target": {"type": "scene", "name": "forest"}},
            {"target": {"type": "interruption", "name": "the_tower"}},
        ]
        out = self.store.set_dice_triggers(rows)
        self.assertEqual([t["target_name"] for t in out], ["forest", "the_tower"])
        self.assertEqual(self.config.match_roll([], "d20", 19).target.name, "forest")
        self.assertEqual(self.config.match_roll([], "d6", 2).target.name, "the_tower")
        disk = self.on_disk()["triggers"]
        self.assertEqual(disk[0]["face"], [18, 19, 20])
        self.assertNotIn("face", disk[1])

    def test_trigger_with_dangling_target_refused_whole(self):
        before = self.on_disk()
        with self.assertRaises(ConfigError):
            self.store.set_dice_triggers([
                {"face": 20, "target": {"type": "scene", "name": "forest"}},
                {"face": 1, "target": {"type": "scene", "name": "nope"}},
            ])
        self.assertEqual(self.on_disk(), before)
        self.assertEqual(len(self.config.dice_triggers), 2)   # the example's two

    def test_threshold_refused_by_the_store_too(self):
        with self.assertRaises(ConfigError):
            self.store.set_dice_triggers([
                {"min": 15, "target": {"type": "scene", "name": "forest"}}])

    def test_usage_of_names_triggers(self):
        self.assertIn("dice trigger 1", self.store.usage_of("interruption", "the_sun"))

    def test_enabled_toggle(self):
        self.store.set_dice_enabled(False)
        self.assertFalse(self.on_disk()["enabled"])
        self.assertFalse(self.config.dice_enabled)


if __name__ == "__main__":
    unittest.main()
