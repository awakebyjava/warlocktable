"""Step 4 of plan doc 4.8: opening a profile -- the GM taking the table.

    python -m unittest discover -s tests -v
"""

import argparse
import http.client
import json
import os
import shutil
import tempfile
import unittest

from warlock.config import ConfigError
from warlock.profiles import migrate

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "data", "config.example.json")


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _build(tmpdir, extra_args=()):
    from warlock import runtime
    from warlock.eventlog import EventLog
    cfg = os.path.join(tmpdir, "config.json")
    shutil.copy(EXAMPLE, cfg)
    migrate(cfg)
    parser = argparse.ArgumentParser()
    runtime.add_common_arguments(parser)
    args = parser.parse_args(["--config", cfg] + list(extra_args))
    log = EventLog(path=None)
    return runtime.build(args, log), log, cfg


class OpenProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rt, self.log, self.cfg = _build(self.tmp.name)
        self.private = os.path.join(self.tmp.name, "profiles", "u_sarah", "library.json")
        _write(self.private, {"scenes": {
            "lair": {"lights": "breathing", "transition": {"crossfade_s": 0.5, "duck": True}}}})

    def tearDown(self):
        self.rt.shutdown()
        self.tmp.cleanup()

    def test_open_swaps_config_and_goes_idle(self):
        c = self.rt.controller
        c.apply_scene("forest")
        self.assertEqual(c.current_scene.name, "forest")
        self.assertNotIn("lair", c.config.scenes)
        src = self.rt.open_profile("u_sarah", "Sarah")
        self.assertIn("u_sarah", src)
        self.assertIn("lair", c.config.scenes)
        self.assertEqual(c.config.owner_of("scenes", "lair"), "private")
        self.assertEqual(c.current_scene.name, c.config.idle_scene_name)   # went idle
        self.assertIs(self.rt.store.config, c.config)                     # store follows
        self.assertEqual(self.rt.open_profile_id, "u_sarah")
        # and back to shared
        self.rt.open_profile(None)
        self.assertNotIn("lair", c.config.scenes)
        self.assertIsNone(self.rt.open_profile_id)

    def test_seats_and_rolls_survive_the_swap(self):
        c = self.rt.controller
        colour = c.config.zones[1].colour
        self.assertTrue(c.claim_seat("Dave", colour))
        c.roll(colour, 1, 20)
        c.whisper(colour, "psst")
        self.rt.open_profile("u_sarah", "Sarah")
        seated = {p.name for p in c.config.players}
        self.assertIn("Dave", seated)                       # seat persisted via table.json
        self.assertEqual(len(c.roll_history(colour)["rolls"]), 1)
        self.assertTrue(c.whisper_thread(colour)["messages"])

    def test_bad_library_leaves_previous_running(self):
        c = self.rt.controller
        _write(self.private, {"scenes": {"forest": {"lights": "breathing"}}})   # collides
        before = c.config
        with self.assertRaises(ConfigError):
            self.rt.open_profile("u_sarah", "Sarah")
        self.assertIs(c.config, before)
        self.assertIsNone(self.rt.open_profile_id)

    def test_edits_after_open_go_to_the_private_file(self):
        self.rt.open_profile("u_sarah", "Sarah")
        self.rt.store.set_scene("den", "breathing")
        with open(self.private, encoding="utf-8") as fh:
            self.assertIn("den", json.load(fh)["scenes"])
        with open(os.path.join(self.tmp.name, "profiles", "shared", "library.json"),
                  encoding="utf-8") as fh:
            self.assertNotIn("den", json.load(fh)["scenes"])


class OpenThroughLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from warlock.web.server import WebPanel
        cls.tmp = tempfile.TemporaryDirectory()
        cls.rt, cls.log, cls.cfg = _build(cls.tmp.name)
        cls.web = WebPanel(cls.rt.controller, cls.rt, cls.log, port=0, host="127.0.0.1")
        assert cls.web.start()
        cls.port = cls.web._server.server_address[1]
        cls.rt.web = cls.web
        # the admin, and a user with a private library
        cls.admin = cls.rt.auth.users.create("Jon", "jon@x.com", "admin", "1234")
        cls.sarah = cls.rt.auth.users.create("Sarah", "s@x.com", "user", "2222")
        _write(os.path.join(cls.tmp.name, "profiles", cls.sarah.id, "library.json"),
               {"scenes": {"lair": {"lights": "breathing"}}})

    @classmethod
    def tearDownClass(cls):
        cls.rt.shutdown()
        cls.tmp.cleanup()

    def call(self, method, path, body=None, cookie=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        if body is not None:
            body = json.dumps(body); headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = cookie
        conn.request(method, path, body=body, headers=headers)
        res = conn.getresponse(); raw = res.read(); sc = res.getheader("Set-Cookie"); conn.close()
        try:
            data = json.loads(raw)
        except ValueError:
            data = raw
        return res.status, data, (sc.split(";")[0] if sc else None)

    def test_gm_login_opens_own_library_and_admin_can_switch(self):
        # Sarah signs in as GM: her library runs
        status, me, sc = self.call("POST", "/api/auth/login",
                                   {"user": self.sarah.id, "pin": "2222", "mode": "gm"})
        self.assertEqual(status, 200, me)
        self.assertEqual(me["campaign"]["open"], self.sarah.id)
        status, voc, _ = self.call("GET", "/api/vocabulary", cookie=sc)
        self.assertIn("lair", voc["scenes"])
        self.assertEqual(voc["owners"]["scenes"]["lair"], "private")
        # Jon signs in as GM: the shared library alone (admin has no private one)
        status, me, jc = self.call("POST", "/api/auth/login",
                                   {"user": self.admin.id, "pin": "1234", "mode": "gm"})
        self.assertIsNone(me["campaign"]["open"])
        status, voc, _ = self.call("GET", "/api/vocabulary", cookie=jc)
        self.assertNotIn("lair", voc["scenes"])
        # the admin opens Sarah's to have a look
        status, c, _ = self.call("POST", "/api/campaign/open", {"user": self.sarah.id}, cookie=jc)
        self.assertEqual(status, 200, c)
        self.assertEqual(c["open"], self.sarah.id)
        status, voc, _ = self.call("GET", "/api/vocabulary", cookie=jc)
        self.assertIn("lair", voc["scenes"])
        # Sarah cannot use the admin switch
        status, _, _ = self.call("POST", "/api/campaign/open", {"user": None}, cookie=sc)
        self.assertEqual(status, 403)
        # player mode does not open anything
        status, me, pc = self.call("POST", "/api/auth/login",
                                   {"user": self.admin.id, "pin": "1234", "mode": "player"})
        self.assertEqual(me["campaign"]["open"], self.sarah.id)        # unchanged


class MediaPathsTests(unittest.TestCase):
    """Step 6: the open library's maps and sounds sit in front of the
    devices' search paths, and uploads go into its folder."""

    def setUp(self):
        from warlock.devices.fake import FakeAudioDevice, FakeDisplayDevice
        self.tmp = tempfile.TemporaryDirectory()
        self.rt, self.log, self.cfg = _build(self.tmp.name)

        # The real fakes, given the two attributes the real devices have.
        class Display(FakeDisplayDevice):
            rescans = 0
            def rescan(self): self.rescans += 1
        class Audio(FakeAudioDevice):
            rescans = 0
            def rescan(self): self.rescans += 1
        self.display = Display(self.log); self.display.search_paths = ["/shared/backgrounds"]
        self.audio = Audio(self.log)
        self.audio.search_paths = ["/shared/tracks"]; self.audio.cue_paths = ["/shared/cues"]
        self.rt.controller.display = self.display
        self.rt.controller.audio = self.audio

    def tearDown(self):
        self.rt.shutdown()
        self.tmp.cleanup()

    def test_open_prepends_private_media_and_close_removes_it(self):
        self.assertIsNone(self.rt.media_root("maps"))
        self.rt.open_profile("u_sarah", "Sarah")
        base = os.path.join(self.tmp.name, "profiles", "u_sarah")
        self.assertEqual(self.display.search_paths[0], os.path.join(base, "maps"))
        self.assertEqual(self.display.search_paths[1:], ["/shared/backgrounds"])
        self.assertEqual(self.audio.search_paths[0], os.path.join(base, "sounds", "tracks"))
        self.assertEqual(self.audio.cue_paths[0], os.path.join(base, "sounds", "cues"))
        self.assertTrue(os.path.isdir(os.path.join(base, "maps")))
        self.assertEqual(self.rt.media_root("sounds"), os.path.join(base, "sounds"))
        self.assertEqual((self.display.rescans, self.audio.rescans), (1, 1))
        # a second open does not stack
        self.rt.open_profile("u_dave", "Dave")
        self.assertEqual(len(self.display.search_paths), 2)
        self.assertIn("u_dave", self.display.search_paths[0])
        # back to shared: only the base paths
        self.rt.open_profile(None)
        self.assertEqual(self.display.search_paths, ["/shared/backgrounds"])
        self.assertEqual(self.audio.search_paths, ["/shared/tracks"])
        self.assertIsNone(self.rt.media_root("maps"))


if __name__ == "__main__":
    unittest.main()
