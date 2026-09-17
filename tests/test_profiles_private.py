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
        _write(self.mine.private_path, {"zones": []})
        with self.assertRaises(ConfigError):
            self.mine.load()
        _write(self.mine.private_path, {"settings": {}})
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

    def test_settings_and_triggers_are_never_private(self):
        cfg = self.mine.load()
        cfg.volume = 0.11
        self.mine.save(cfg)
        table = _raw(self.mine.table_path)
        self.assertEqual(table["settings"]["volume"], 0.11)
        private = _raw(self.mine.private_path) if os.path.exists(self.mine.private_path) else {}
        self.assertNotIn("settings", private)
        self.assertNotIn("dice", private)
        self.assertEqual(len(_raw(self.mine.library_path)["dice"]["triggers"]), 2)


class OwnCardsTests(unittest.TestCase):
    """Step 5: a GM's own tags live in their library; the deck is the admin's."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "config.json")
        shutil.copy(EXAMPLE, self.cfg)
        migrate(self.cfg)
        self.shared = ProfileStore.beside(self.cfg)
        self.mine = ProfileStore.beside(self.cfg, private="jon")
        self.deck_uid = next(iter(self.shared.load().cards))

    def tearDown(self):
        self.tmp.cleanup()

    def store(self, profiles):
        from warlock.configstore import ConfigStore
        from warlock.eventlog import EventLog
        cfg = profiles.load()
        return ConfigStore(cfg, self.cfg, EventLog(path=None), profiles=profiles)

    def test_new_tag_is_mine_and_resolves_on_tap(self):
        st = self.store(self.mine)
        st.set_card("04:AA:BB", "My omen", "scene", "forest")
        private = _raw(self.mine.private_path)
        self.assertIn("04:AA:BB", private["cards"])
        self.assertNotIn("04:AA:BB", _raw(self.mine.table_path)["cards"])
        # the composed config sees deck + mine, marked
        cfg = self.mine.load()
        self.assertIn(self.deck_uid, cfg.cards)
        self.assertEqual(cfg.owner_of("cards", "04:AA:BB"), PRIVATE)
        self.assertEqual(cfg.owner_of("cards", self.deck_uid), SHARED)
        self.assertEqual(cfg.find_card("04:AA:BB").label, "My omen")
        # ...and the shared-only view does not
        self.assertNotIn("04:AA:BB", self.shared.load().cards)

    def test_deck_is_read_only_while_a_private_library_is_open(self):
        st = self.store(self.mine)
        with self.assertRaises(ConfigError) as cm:
            st.set_card(self.deck_uid, "Renamed", "scene", "forest")
        self.assertIn("table owner", str(cm.exception))
        with self.assertRaises(ConfigError):
            st.delete_card(self.deck_uid)
        # the admin, with the shared library open, can
        st2 = self.store(self.shared)
        st2.set_card(self.deck_uid, "Renamed", "scene", "forest")
        self.assertEqual(_raw(self.shared.table_path)["cards"][self.deck_uid]["label"], "Renamed")

    def test_own_card_can_be_edited_and_deleted(self):
        st = self.store(self.mine)
        st.set_card("04:AA:BB", "My omen", "scene", "forest")
        st.set_card("04:AA:BB", "My better omen", "scene", "plains")
        self.assertEqual(_raw(self.mine.private_path)["cards"]["04:AA:BB"]["label"], "My better omen")
        st.delete_card("04:AA:BB")
        self.assertNotIn("04:AA:BB", _raw(self.mine.private_path).get("cards") or {})

    def test_uid_in_both_deck_and_library_is_refused(self):
        _write(self.mine.private_path, {"cards": {
            self.deck_uid: {"label": "x", "target": {"type": "scene", "name": "forest"}}}})
        with self.assertRaises(ConfigError) as cm:
            self.mine.load()
        self.assertIn("table.json", str(cm.exception))

    def test_list_cards_marks_owner(self):
        st = self.store(self.mine)
        st.set_card("04:AA:BB", "My omen", "scene", "forest")
        owners = {c["uid"]: c["owner"] for c in st.list_cards()}
        self.assertEqual(owners["04:AA:BB"], PRIVATE)
        self.assertEqual(owners[self.deck_uid], SHARED)

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


class SharedIsReadOnlyTests(unittest.TestCase):
    """Decided 2026-09-17: a non-owner GM adds to the table, never changes
    what is already in it -- shared scenes, interruptions, dice triggers,
    and the deck alike."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "config.json")
        shutil.copy(EXAMPLE, self.cfg)
        migrate(self.cfg)
        from warlock.configstore import ConfigStore
        from warlock.eventlog import EventLog
        self.mine = ProfileStore.beside(self.cfg, private="jon")
        self.st = ConfigStore(self.mine.load(), self.cfg, EventLog(path=None), profiles=self.mine)
        self.shared = ProfileStore.beside(self.cfg)
        self.st_owner = ConfigStore(self.shared.load(), self.cfg, EventLog(path=None), profiles=self.shared)

    def tearDown(self):
        self.tmp.cleanup()

    def test_shared_scene_and_interruption_refuse_edit_and_delete(self):
        for call in (lambda: self.st.set_scene("forest", "breathing"),
                     lambda: self.st.delete_scene("forest"),
                     lambda: self.st.set_interruption("the_sun", audio="x"),
                     lambda: self.st.delete_interruption("the_sun"),
                     lambda: self.st.set_dice_triggers([])):
            with self.assertRaises(ConfigError) as cm:
                call()
            self.assertIn("table owner", str(cm.exception))

    def test_own_entries_still_editable_and_shared_owner_unaffected(self):
        self.st.set_scene("lair", "breathing")
        self.st.set_scene("lair", "plains")
        self.st.delete_scene("lair")
        self.st_owner.set_scene("forest", "plains")          # the owner may
        self.st_owner.set_dice_triggers([])
