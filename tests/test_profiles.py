"""Step 1 of plan doc 4.8: config.json split into table + library.

The acceptance test is equivalence: a Config loaded through the split
files equals one loaded from the single file, and the migration leaves
config.json untouched. Runs against the shipped example AND, when
present, the real config snapshotted from the table -- the migration is
the risky part of the whole accounts plan, and it should be rehearsed
against the data it will actually meet.

    python -m unittest discover -s tests -v
"""

import json
import os
import shutil
import tempfile
import unittest

from warlock.config import ConfigError, config_from_raw, load_config
from warlock.profiles import ProfileStore, compose_raw, migrate, split_raw

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "data", "config.example.json")
SNAPSHOT = os.path.expanduser(
    "~/Documents/warlocktable-backups/snapshot/warlocktable/config.json")

SOURCES = [("example", EXAMPLE)]
if os.path.exists(SNAPSHOT):
    SOURCES.append(("table-snapshot", SNAPSHOT))


def _raw(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class SplitComposeTests(unittest.TestCase):
    def test_round_trip_is_exact(self):
        for name, path in SOURCES:
            with self.subTest(source=name):
                raw = _raw(path)
                table, library = split_raw(raw)
                self.assertEqual(compose_raw(table, library), raw)

    def test_ownership(self):
        raw = _raw(EXAMPLE)
        table, library = split_raw(raw)
        self.assertIn("cards", table)
        self.assertIn("zones", table)
        self.assertIn("settings", table)
        self.assertNotIn("scenes", table)
        self.assertIn("scenes", library)
        self.assertIn("interruptions", library)
        self.assertNotIn("cards", library)
        # dice straddles: known dice are the table's, triggers the library's
        self.assertIn("known", table["dice"])
        self.assertIn("triggers", library["dice"])
        self.assertNotIn("triggers", table["dice"])

    def test_unknown_top_level_key_refused(self):
        raw = _raw(EXAMPLE)
        raw["mystery"] = 1
        with self.assertRaises(ConfigError):
            split_raw(raw)

    def test_loaded_configs_are_equal(self):
        for name, path in SOURCES:
            with self.subTest(source=name):
                raw = _raw(path)
                table, library = split_raw(raw)
                via_split = config_from_raw(compose_raw(table, library))
                direct = load_config(path)
                self.assertEqual(via_split, direct)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, path):
        cfg = os.path.join(self.dir, "config.json")
        shutil.copy(path, cfg)
        return cfg

    def test_migration_is_additive_and_equivalent(self):
        for name, path in SOURCES:
            with self.subTest(source=name):
                shutil.rmtree(self.dir); os.makedirs(self.dir)
                cfg = self.stage(path)
                with open(cfg, "rb") as fh:
                    before = fh.read()
                store = migrate(cfg, backup_dir=os.path.join(self.dir, "backups"))
                with open(cfg, "rb") as fh:
                    self.assertEqual(fh.read(), before)      # untouched, byte for byte
                self.assertTrue(os.path.exists(store.table_path))
                self.assertTrue(os.path.exists(store.library_path))
                self.assertEqual(store.load(), load_config(cfg))
                self.assertTrue(any(f.startswith("config-pre-profiles-")
                                    for f in os.listdir(os.path.join(self.dir, "backups"))))

    def test_migration_refuses_to_run_twice(self):
        cfg = self.stage(EXAMPLE)
        migrate(cfg)
        with self.assertRaises(ConfigError):
            migrate(cfg)

    def test_migration_refuses_a_config_that_does_not_load(self):
        cfg = self.stage(EXAMPLE)
        raw = _raw(cfg)
        raw["cards"]["deadbeef"] = {"label": "x", "target": {"type": "scene", "name": "nope"}}
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump(raw, fh)
        with self.assertRaises(ConfigError):
            migrate(cfg)
        self.assertIsNone(ProfileStore.beside(cfg))

    def test_beside_is_the_switch(self):
        cfg = self.stage(EXAMPLE)
        self.assertIsNone(ProfileStore.beside(cfg))
        migrate(cfg)
        store = ProfileStore.beside(cfg)
        self.assertIsNotNone(store)
        self.assertEqual(store.data_dir, os.path.abspath(self.dir))


class StoreSaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "config.json")
        shutil.copy(EXAMPLE, self.cfg)
        self.store = migrate(self.cfg)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_round_trips_and_leaves_config_json_alone(self):
        with open(self.cfg, "rb") as fh:
            before = fh.read()
        config = self.store.load()
        config.volume = 0.42
        config.scenes["forest"].lights = "plains"
        self.store.save(config, backup_dir=os.path.join(self.tmp.name, "backups"))
        again = self.store.load()
        self.assertEqual(again.volume, 0.42)
        self.assertEqual(again.scenes["forest"].lights, "plains")
        self.assertEqual(again, config)
        with open(self.cfg, "rb") as fh:
            self.assertEqual(fh.read(), before)
        # the two halves went to the right files
        table = _raw(self.store.table_path)
        library = _raw(self.store.library_path)
        self.assertEqual(table["settings"]["volume"], 0.42)
        self.assertEqual(library["scenes"]["forest"]["lights"], "plains")
        self.assertNotIn("scenes", table)
        backups = os.listdir(os.path.join(self.tmp.name, "backups"))
        self.assertTrue(any(b.startswith("table-") for b in backups))
        self.assertTrue(any(b.startswith("library-") for b in backups))

    def test_save_refuses_dangling_and_writes_nothing(self):
        from warlock.config import Card, Target
        config = self.store.load()
        config.cards["deadbeef"] = Card(uid="deadbeef", label="x",
                                        target=Target(kind="scene", name="nope"))
        before = (_raw(self.store.table_path), _raw(self.store.library_path))
        with self.assertRaises(ConfigError):
            self.store.save(config)
        self.assertEqual((_raw(self.store.table_path), _raw(self.store.library_path)), before)


if __name__ == "__main__":
    unittest.main()
