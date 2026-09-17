"""Step 3 of plan doc 4.8: users, PINs, sessions, and the gate.

    python -m unittest discover -s tests -v

Two halves. The stores are tested as pure logic with a fixed clock. The
gate is tested against a REAL panel server on a loopback port with the
fake devices, because "the operator routes refuse without a GM session"
is a property of the HTTP layer, and mocking it would test the mock.
"""

import http.client
import json
import os
import shutil
import tempfile
import time
import unittest

from warlock import auth as A
from warlock.config import ConfigError

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "data", "config.example.json")


class PinTests(unittest.TestCase):
    def test_hash_and_check(self):
        h = A.hash_pin("1234")
        self.assertTrue(h.startswith("scrypt$"))
        self.assertTrue(A.check_pin("1234", h))
        self.assertFalse(A.check_pin("1235", h))
        self.assertFalse(A.check_pin("1234", "garbage"))
        self.assertNotEqual(h, A.hash_pin("1234"))     # salted

    def test_valid_pin(self):
        for ok in ("1234", "000000"):
            self.assertTrue(A.valid_pin(ok))
        for bad in ("123", "1234567", "12a4", ""):
            self.assertFalse(A.valid_pin(bad))


class UserStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "users.json")
        self.store = A.UserStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_store_needs_setup(self):
        self.assertTrue(self.store.needs_setup())
        self.assertIsNone(self.store.admin())

    def test_create_admin_persists_and_reloads(self):
        u = self.store.create("Jon", "Jon@Example.com", A.ADMIN, "1234")
        self.assertEqual(u.email, "jon@example.com")
        self.assertFalse(self.store.needs_setup())
        again = A.UserStore(self.path)
        self.assertEqual(again.admin().id, u.id)
        self.assertTrue(A.check_pin("1234", again.admin().pin_hash))
        # the file never holds a PIN in clear
        with open(self.path) as fh:
            self.assertNotIn("1234", fh.read())

    def test_one_admin_and_unique_emails(self):
        self.store.create("Jon", "jon@x.com", A.ADMIN, "1234")
        with self.assertRaises(ConfigError):
            self.store.create("Two", "two@x.com", A.ADMIN, "1234")
        with self.assertRaises(ConfigError):
            self.store.create("Dup", "JON@x.com", A.USER, "1234")
        with self.assertRaises(ConfigError):
            self.store.create("NoMail", "", A.USER, "1234")

    def test_verify_lockout_and_recovery(self):
        u = self.store.create("Jon", "jon@x.com", A.ADMIN, "1234")
        t = 1000.0
        self.assertEqual(self.store.verify(u.id, "1234", now=t).id, u.id)
        for _ in range(A.MAX_FAILURES):
            with self.assertRaises(A.AuthError):
                self.store.verify(u.id, "9999", now=t)
        with self.assertRaises(A.AuthError) as cm:
            self.store.verify(u.id, "1234", now=t + 1)        # right PIN, still locked
        self.assertIn("locked", str(cm.exception))
        self.assertEqual(self.store.verify(u.id, "1234", now=t + A.LOCKOUT_S + 1).id, u.id)

    def test_clear_pin_means_setup_again_for_admin(self):
        u = self.store.create("Jon", "jon@x.com", A.ADMIN, "1234")
        self.store.clear_pin(u.id)
        self.assertTrue(self.store.needs_setup())
        with self.assertRaises(A.AuthError):
            self.store.verify(u.id, "1234")
        self.store.set_pin(u.id, "4321")
        self.assertFalse(self.store.needs_setup())

    def test_admin_cannot_be_deleted_or_demoted(self):
        a = self.store.create("Jon", "jon@x.com", A.ADMIN, "1234")
        with self.assertRaises(ConfigError):
            self.store.delete(a.id)
        with self.assertRaises(ConfigError):
            self.store.update(a.id, role=A.USER)
        u = self.store.create("Sarah", "s@x.com", A.USER, "1111")
        self.store.delete(u.id)
        self.assertIsNone(self.store.get(u.id))

    def test_unreadable_file_means_setup_not_crash(self):
        with open(self.path, "w") as fh:
            fh.write("{not json")
        store = A.UserStore(self.path)
        self.assertTrue(store.needs_setup())

    def test_listing_is_public_shape(self):
        self.store.create("Jon", "jon@x.com", A.ADMIN, "1234")
        row = self.store.listing()[0]
        self.assertEqual(set(row), {"id", "name", "role", "needs_pin"})


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "sessions.json")
        self.store = A.SessionStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_issue_lookup_slide_expire(self):
        tok = self.store.issue("u_1", A.GM)
        s = self.store.lookup(tok)
        self.assertEqual((s.user_id, s.mode), ("u_1", A.GM))
        with open(self.path) as fh:
            self.assertNotIn(tok, fh.read())                # hashed on disk
        later = time.time() + A.SESSION_TTL_S - 10
        self.assertIsNotNone(self.store.lookup(tok, now=later))   # slid
        self.assertIsNotNone(self.store.lookup(tok, now=later + A.SESSION_TTL_S - 10))
        self.assertIsNone(self.store.lookup(tok, now=later + 2 * A.SESSION_TTL_S))
        self.assertIsNone(self.store.lookup("nope"))
        self.assertIsNone(self.store.lookup(None))

    def test_survives_reload_and_revokes(self):
        tok = self.store.issue("u_1", A.PLAYER)
        tok2 = self.store.issue("u_1", A.GM)
        again = A.SessionStore(self.path)
        self.assertIsNotNone(again.lookup(tok))
        again.revoke(tok)
        self.assertIsNone(again.lookup(tok))
        self.assertEqual(again.revoke_user("u_1"), 1)
        self.assertIsNone(again.lookup(tok2))

    def test_cookie_helpers(self):
        self.assertEqual(A.cookie_value("a=1; wt_session=abc; b=2"), "abc")
        self.assertIsNone(A.cookie_value("a=1"))
        self.assertIsNone(A.cookie_value(None))
        self.assertIn("HttpOnly", A.set_cookie_header("abc"))
        self.assertIn("SameSite=Lax", A.set_cookie_header("abc"))
        self.assertNotIn("Secure", A.set_cookie_header("abc"))
        self.assertIn("Max-Age=0", A.clear_cookie_header())


class DevAuthTests(unittest.TestCase):
    def test_dev_admin_is_in_memory_only(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            a = A.Auth(tmp.name, dev=True)
            self.assertFalse(a.users.needs_setup())
            self.assertIsNotNone(a.users.verify(a.users.admin().id, A.Auth.DEV_PIN))
            self.assertFalse(os.path.exists(os.path.join(tmp.name, "users.json")))
        finally:
            tmp.cleanup()


class GateTests(unittest.TestCase):
    """The real server, the fake devices, a real socket."""

    @classmethod
    def setUpClass(cls):
        import argparse
        from warlock import runtime
        from warlock.eventlog import EventLog
        from warlock.web.server import WebPanel
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = os.path.join(cls.tmp.name, "config.json")
        shutil.copy(EXAMPLE, cfg)
        parser = argparse.ArgumentParser()
        runtime.add_common_arguments(parser)
        args = parser.parse_args(["--config", cfg, "--web-port", "0"])
        cls.log = EventLog(path=None)
        cls.rt = runtime.build(args, cls.log)
        cls.web = WebPanel(cls.rt.controller, cls.rt, cls.log, port=0, host="127.0.0.1")
        assert cls.web.start()
        cls.port = cls.web._server.server_address[1]
        cls.rt.web = cls.web

    @classmethod
    def tearDownClass(cls):
        cls.rt.shutdown()
        cls.tmp.cleanup()

    def call(self, method, path, body=None, cookie=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        if body is not None:
            body = json.dumps(body)
            headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = cookie
        conn.request(method, path, body=body, headers=headers)
        res = conn.getresponse()
        raw = res.read()
        set_cookie = res.getheader("Set-Cookie")
        conn.close()
        try:
            data = json.loads(raw)
        except ValueError:
            data = raw
        return res.status, data, set_cookie

    def login(self, mode, pin="1234"):
        status, data, cookie = self.call("POST", "/api/auth/login",
                                         {"user": self.admin_id, "pin": pin, "mode": mode})
        self.assertEqual(status, 200, data)
        return cookie.split(";")[0]

    def test_00_fresh_data_dir_is_in_setup(self):
        status, page, _ = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Set up the Warlock Table", page)
        status, page, _ = self.call("GET", "/gm")
        self.assertIn(b"Set up the Warlock Table", page)
        status, data, _ = self.call("GET", "/api/status")
        self.assertEqual(status, 401)
        self.assertIn("login", data)

    def test_01_setup_creates_admin_and_signs_in_as_gm(self):
        status, data, cookie = self.call("POST", "/api/auth/setup",
                                         {"name": "Jon", "email": "jon@x.com", "pin": "1234"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["mode"], "gm")
        self.assertIn("HttpOnly", cookie)
        type(self).admin_id = data["id"]
        # second set-up refused
        status, data, _ = self.call("POST", "/api/auth/setup",
                                    {"name": "x", "email": "x@x.com", "pin": "9999"})
        self.assertEqual(status, 400)
        # the door is now the picker
        status, page, _ = self.call("GET", "/")
        self.assertIn(b"screen-who", page)

    def test_02_public_routes_need_no_session(self):
        for path in ("/", "/player", "/api/join", "/api/zones", "/api/auth/users",
                     "/style.css", "/app.js"):
            status, _, _ = self.call("GET", path)
            self.assertEqual(status, 200, path)
        status, _, _ = self.call("POST", "/api/seats/claim",
                                 {"name": "Guest Gus", "colour": self.rt.controller.config.zones[1].colour})
        self.assertIn(status, (200, 400), "guest seat claim must not be gated")

    def test_03_operator_routes_refuse_without_gm(self):
        for method, path in (("GET", "/api/status"), ("GET", "/api/vocabulary"),
                             ("GET", "/api/config/cards"), ("GET", "/api/dice"),
                             ("POST", "/api/action"), ("POST", "/api/config/cards"),
                             ("DELETE", "/api/dice/known/x")):
            status, data, _ = self.call(method, path, {} if method != "GET" else None)
            self.assertEqual(status, 401, (method, path))
        status, page, _ = self.call("GET", "/gm")
        self.assertIn(b"screen-who", page)          # the login page, not the panel

    def test_04_player_mode_is_not_enough(self):
        cookie = self.login("player")
        status, _, _ = self.call("GET", "/api/status", cookie=cookie)
        self.assertEqual(status, 401)
        # ...but switching chairs is
        status, data, _ = self.call("POST", "/api/auth/mode", {"mode": "gm"}, cookie=cookie)
        self.assertEqual(status, 200)
        status, data, _ = self.call("GET", "/api/status", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn("scene", data)

    def test_05_gm_session_opens_everything_and_logout_closes_it(self):
        cookie = self.login("gm")
        status, page, _ = self.call("GET", "/gm", cookie=cookie)
        self.assertIn(b"panel-run", page)           # the real panel
        status, data, _ = self.call("POST", "/api/action",
                                    {"action": "apply_scene", "params": {"scene_name": "forest"}},
                                    cookie=cookie)
        self.assertEqual(status, 200, data)
        status, data, _ = self.call("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual((data["name"], data["mode"]), ("Jon", "gm"))
        self.call("POST", "/api/auth/logout", {}, cookie=cookie)
        status, _, _ = self.call("GET", "/api/status", cookie=cookie)
        self.assertEqual(status, 401)

    def test_06_wrong_pin_is_refused(self):
        status, data, cookie = self.call("POST", "/api/auth/login",
                                         {"user": self.admin_id, "pin": "0000", "mode": "gm"})
        self.assertEqual(status, 403)
        self.assertIsNone(cookie)

    def test_07_admin_manages_users(self):
        cookie = self.login("gm")
        status, data, _ = self.call("POST", "/api/auth/admin/users",
                                    {"name": "Sarah", "email": "s@x.com", "pin": "2222"},
                                    cookie=cookie)
        self.assertEqual(status, 200, data)
        sid = data["id"]
        status, data, _ = self.call("GET", "/api/auth/users")
        self.assertIn("Sarah", [u["name"] for u in data["users"]])
        # Sarah signs in as GM and gets the panel too
        status, data, sc = self.call("POST", "/api/auth/login",
                                     {"user": sid, "pin": "2222", "mode": "gm"})
        self.assertEqual(status, 200)
        scookie = sc.split(";")[0]
        status, _, _ = self.call("GET", "/api/status", cookie=scookie)
        self.assertEqual(status, 200)
        # ...but is not admin
        status, _, _ = self.call("GET", "/api/auth/admin/users", cookie=scookie)
        self.assertEqual(status, 403)
        # reset her PIN: signed out everywhere, must set a new one at next login
        status, _, _ = self.call("POST", "/api/auth/admin/users/%s/reset-pin" % sid, {}, cookie=cookie)
        self.assertEqual(status, 200)
        status, _, _ = self.call("GET", "/api/status", cookie=scookie)
        self.assertEqual(status, 401)
        status, data, _ = self.call("POST", "/api/auth/login",
                                    {"user": sid, "new_pin": "3333", "mode": "player"})
        self.assertEqual(status, 200, data)
        # delete
        status, _, _ = self.call("DELETE", "/api/auth/admin/users/%s" % sid, cookie=cookie)
        self.assertEqual(status, 200)
        status, data, _ = self.call("GET", "/api/auth/users")
        self.assertNotIn("Sarah", [u["name"] for u in data["users"]])


if __name__ == "__main__":
    unittest.main()
