"""Step 2 of plan doc 4.8: a private library composed over the shared one.

    python -m unittest discover -s tests -v
"""

import json
import os
import shutil
import tempfile
import unittest

from warlock.config import ConfigError, load_config
from warlock.profiles import PRIVATE, SHARED, ProfileStore, migrate

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "data", "config.example.json")


def _raw(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


class PrivateLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "config.json")
        shutil.copy(EXAMPLE, self.cfg)
        migrate(self.cfg)
        self.shared = ProfileStore.beside(self.cfg)
        self.mine = ProfileStore.beside(self.cfg, private="jon")

    def tearDown(self):
        self.tmp.cleanup()

    # ---- composition

    def test_no_private_file_composes_to_the_shared_config(self):
        self.assertEqual(self.mine.load(), self.shared.load())
        self.assertEqual(self.mine.write_target, PRIVATE)
        self.assertEqual(self.shared.write_target, SHARED)

    def test_private_entries_appear_and_are_marked(self):
        _write(self.mine.private_path, {"scenes": {
            "lair": {"lights": "breathing", "transition": {"crossfade_s": 1.0, "duck": True}}}})
        cfg = self.mine.load()
        self.assertIn("lair", cfg.scenes)
        self.assertIn("forest", cfg.scenes)                  # shared still there
        self.assertEqual(cfg.owner_of("scenes", "lair"), PRIVATE)
        self.assertEqual(cfg.owner_of("scenes", "forest"), SHARED)
        self.assertEqual(cfg.owner_of("interruptions", "the_sun"), SHARED)
        # the shared-only store does not see it
        self.assertNotIn("lair", self.shared.load().scenes)

    def test_name_in_both_libraries_is_refused_naming_both_files(self):
        _write(self.mine.private_path, {"scenes": {
            "forest": {"lights": "breathing"}}})
        with self.assertRaises(ConfigError) as cm:
            self.mine.load()
        msg = str(cm.exception)
        self.assertIn("forest", msg)
        self.assertIn("shared", msg)
        self.assertIn("jon", msg)

    def test_private_library_may_not_hold_table_things(self):
        _write(self.mine.private_path, {"cards": {}})
        with self.assertRaises(ConfigError):
            self.mine.load()

    def test_bad_profile_ids(self):
        for bad in ("shared", "", "../x", "a b", "x" * 41):
            with self.assertRaises(ConfigError):
                ProfileStore(self.tmp.name, private=bad)

    # ---- routing on save

    def test_new_scene_goes_to_the_private_file(self):
        from warlock.config import Scene, Transition
        cfg = self.mine.load()
        cfg.scenes["lair"] = Scene(name="lair", lights="breathing", soundscape=None,
                                   background=None, transition=Transition())
        self.mine.save(cfg)
        self.assertIn("lair", _raw(self.mine.private_path)["scenes"])
        self.assertNotIn("lair", _raw(self.mine.library_path)["scenes"])
        self.assertEqual(cfg.owner_of("scenes", "lair"), PRIVATE)

    def test_editing_a_shared_scene_stays_shared(self):
        cfg = self.mine.load()
        cfg.scenes["forest"].lights = "plains"
        self.mine.save(cfg)
        self.assertEqual(_raw(self.mine.library_path)["scenes"]["forest"]["lights"], "plains")
        self.assertFalse(os.path.exists(self.mine.private_path)
                         and "forest" in (_raw(self.mine.private_path).get("scenes") or {}))

    def test_deleting_a_private_scene_removes_it_from_the_private_file(self):
        _write(self.mine.private_path, {"scenes": {
            "lair": {"lights": "breathing"}}})
        cfg = self.mine.load()
        del cfg.scenes["lair"]
        self.mine.save(cfg)
        self.assertNotIn("lair", _raw(self.mine.private_path).get("scenes") or {})
        self.assertIn("forest", _raw(self.mine.library_path)["scenes"])

    def test_table_and_triggers_are_never_private(self):
        from warlock.config import Card, Target
        cfg = self.mine.load()
        cfg.cards["04:AA"] = Card(uid="04:AA", label="x", target=Target("scene", "forest"))
        cfg.volume = 0.11
        self.mine.save(cfg)
        table = _raw(self.mine.table_path)
        self.assertIn("04:AA", table["cards"])
        self.assertEqual(table["settings"]["volume"], 0.11)
        private = _raw(self.mine.private_path) if os.path.exists(self.mine.private_path) else {}
        self.assertNotIn("cards", private)
        self.assertNotIn("dice", private)
        self.assertEqual(len(_raw(self.mine.library_path)["dice"]["triggers"]), 2)

    def test_second_save_routes_the_same_way(self):
        from warlock.config import Scene, Transition
        cfg = self.mine.load()
        cfg.scenes["lair"] = Scene(name="lair", lights="breathing", soundscape=None,
                                   background=None, transition=Transition())
        self.mine.save(cfg)
        cfg.scenes["lair"].lights = "plains"
        self.mine.save(cfg)                      # no reload in between
        self.assertEqual(_raw(self.mine.private_path)["scenes"]["lair"]["lights"], "plains")
        self.assertNotIn("lair", _raw(self.mine.library_path)["scenes"])

    def test_config_json_still_untouched(self):
        from warlock.config import Scene, Transition
        cfg = self.mine.load()
        cfg.scenes["lair"] = Scene(name="lair", lights="breathing", soundscape=None,
                                   background=None, transition=Transition())
        self.mine.save(cfg)
        with open(self.cfg, "rb") as a, open(EXAMPLE, "rb") as b:
            self.assertEqual(a.read(), b.read())


class PrivateSceneFiresTests(unittest.TestCase):
    """The step-2 acceptance: a scene that exists only in the private
    library is applied by the controller like any other."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = os.path.join(self.tmp.name, "config.json")
        shutil.copy(EXAMPLE, cfg)
        migrate(cfg)
        self.store = ProfileStore.beside(cfg, private="jon")
        _write(self.store.private_path, {"scenes": {
            "lair": {"lights": "breathing", "transition": {"crossfade_s": 0.5, "duck": True}}}})

    def tearDown(self):
        self.tmp.cleanup()

    def test_private_scene_applies(self):
        from warlock.controller import Controller
        from warlock.devices.fake import FakeAudioDevice, FakeDisplayDevice, FakeLightDevice
        from warlock.eventlog import EventLog
        log = EventLog(path=None)
        config = self.store.load()
        controller = Controller(config, FakeLightDevice(log), FakeAudioDevice(log),
                                FakeDisplayDevice(log), log)
        controller.apply_scene("lair")
        self.assertEqual(controller.current_scene.name, "lair")
        self.assertTrue(any(e["kind"] == "lights.set_pattern" and e.get("pattern") == "breathing"
                            for e in log.events))


if __name__ == "__main__":
    unittest.main()
