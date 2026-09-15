"""Authentication and audience separation; all credentials here are synthetic fixtures."""
from http.client import HTTPConnection
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from admin_auth import AdminSessions, ADMIN_HOST, COOKIE, assert_plain_path, owner_access_key, set_owner_acl
from sites import WebsiteServer

KEY = "fixture-key-for-browser-verification-only-01"


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.auth = AdminSessions(KEY, lambda: self.now)

    def test_bad_keys_throttled_without_issuing_session(self):
        for _ in range(5):
            self.assertEqual(self.auth.login("wrong")[0], 401)
        self.assertEqual(self.auth.login(KEY)[0], 429)
        self.now = 60
        self.assertEqual(self.auth.login(KEY)[0], 200)

    def test_fresh_tokens_and_idle_expiry(self):
        _, first = self.auth.login(KEY)
        _, second = self.auth.login(KEY)
        self.assertNotEqual(first, second)
        self.assertIsNotNone(self.auth.current(first))
        self.now = 1800
        self.assertIsNone(self.auth.current(first))
        self.assertNotIn(KEY, repr(self.auth.sessions))

    def test_absolute_expiry_even_with_activity(self):
        _, token = self.auth.login(KEY)
        for now in range(1000, 28001, 1000):
            self.now = now
            self.assertIsNotNone(self.auth.current(token))
        self.now = 28800
        self.assertIsNone(self.auth.current(token))

    def test_logout_revokes_and_events_omit_credentials(self):
        _, token = self.auth.login(KEY)
        self.auth.logout(token)
        self.assertIsNone(self.auth.current(token))
        self.assertNotIn(token, repr(self.auth.events))
        self.assertNotIn(KEY, repr(self.auth.events))
        self.assertIsNone(self.auth.current("invented"))

    def test_new_server_invalidates_old_sessions(self):
        _, token = self.auth.login(KEY)
        self.assertIsNone(AdminSessions(KEY).current(token))

    def test_key_provisioning_is_private_and_persistent_in_temporary_home(self):
        with tempfile.TemporaryDirectory(prefix="luxartium-key-test-") as root, patch.object(Path, "home", return_value=Path(root)):
            first = owner_access_key()
            self.assertRegex(first, r"^[A-Za-z0-9_-]{43}$")
            self.assertEqual(owner_access_key(), first)
            self.assertTrue((Path(root) / ".luxartium/admin/access.key").is_file())

    def test_links_and_windows_reparse_points_are_rejected(self):
        for mode, attributes in ((stat.S_IFLNK, 0), (stat.S_IFDIR, 0x400)):
            with patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=mode, st_file_attributes=attributes)):
                with self.assertRaises(RuntimeError):
                    assert_plain_path(Path("synthetic-path"))

    @unittest.skipUnless(os.name == "nt", "Windows ACL regression")
    def test_repeated_provisioning_never_inherits_broad_parent_permissions(self):
        with tempfile.TemporaryDirectory(prefix="luxartium-acl-test-") as root, patch.object(Path, "home", return_value=Path(root)):
            subprocess.run(["icacls", root, "/grant", "*S-1-5-32-545:(OI)(CI)RX"], check=True, capture_output=True)
            keyfile = Path(root) / ".luxartium/admin/access.key"
            observed = []

            def audited(path, sid, directory):
                set_owner_acl(path, sid, directory)
                if keyfile.exists():
                    acl = subprocess.check_output(["icacls", str(keyfile)], text=True)
                    self.assertNotIn("BUILTIN\\Users", acl)
                    self.assertNotIn("Everyone", acl)
                    observed.append(path)

            with patch("admin_auth.set_owner_acl", side_effect=audited):
                first = owner_access_key()
                self.assertEqual(owner_access_key(), first)
            self.assertGreaterEqual(len(observed), 3)


class SiteHTTPTests(unittest.TestCase):
    def setUp(self):
        self.admin = WebsiteServer(0, "admin", KEY)
        self.public = WebsiteServer(0, "public")
        self.threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (self.admin, self.public)]
        for t in self.threads:
            t.start()

    def tearDown(self):
        for server in (self.admin, self.public):
            server.shutdown()
            server.server_close()
        for t in self.threads:
            t.join()

    def request(self, path, *, server=None, method="GET", payload=None, cookie=None, headers=None):
        server = server or self.admin
        host = f"{ADMIN_HOST}:{server.server_port}" if server.role == "admin" else f"127.0.0.1:{server.server_port}"
        selected = {"Host": host}
        if method == "POST":
            selected.update({"Origin": "http://" + host, "Content-Type": "application/json"})
        if cookie:
            selected["Cookie"] = cookie
        selected.update(headers or {})
        conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            conn.request(method, path, body=json.dumps(payload).encode() if payload is not None else None, headers=selected)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def login(self):
        status, headers, _ = self.request("/session", method="POST", payload={"key": KEY})
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_private_html_scripts_and_api_require_session(self):
        self.assertEqual(self.request("/admin/")[1]["Location"], "/login")
        for path in ("/admin/app.js", "/admin/workspace.js", "/admin/api/session"):
            status, _, body = self.request(path)
            self.assertEqual(status, 401)
            self.assertNotIn(b"Backups and recovery", body)
        cookie = self.login()
        for path in ("/admin/", "/admin/app.js", "/admin/workspace.js", "/admin/api/session"):
            status, headers, _ = self.request(path, cookie=cookie)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")

    def test_public_pages_never_serve_private_assets(self):
        for path in ("/", "/app.js", "/style.css", "/favicon.svg"):
            self.assertEqual(self.request(path, server=self.public)[0], 200)
        for path in ("/admin/", "/admin/workspace.js", "/workspace.js", "/access.key", "/../admin/workspace.js"):
            self.assertEqual(self.request(path, server=self.public)[0], 404)
        body = self.request("/app.js", server=self.public)[2]
        self.assertNotIn(b"Backups and recovery", body)
        self.assertNotIn(b"admin-key", body)

    def test_cookie_is_host_only_secure_and_httponly(self):
        _, headers, _ = self.request("/session", method="POST", payload={"key": KEY})
        cookie = SimpleCookie(headers["Set-Cookie"])[COOKIE]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["domain"], "")
        self.assertEqual(cookie["path"], "/")

    def test_origin_host_and_csrf_fail_closed(self):
        for headers in ({"Origin": "http://127.0.0.1:4173"}, {"Host": f"127.0.0.1:{self.admin.server_port}"}, {"Origin": "null"}):
            self.assertEqual(self.request("/session", method="POST", payload={"key": KEY}, headers=headers)[0], 403)
        cookie = self.login()
        for csrf in ("wrong", "\u00e9"):
            self.assertEqual(self.request("/admin/logout", method="POST", payload={}, cookie=cookie, headers={"X-CSRF-Token": csrf})[0], 403)
        self.assertEqual(self.request("/admin/api/session", cookie=cookie)[0], 200)

    def test_login_validation_and_size_limits(self):
        self.assertEqual(self.request("/session", method="POST", payload={"key": "wrong"})[0], 401)
        self.assertEqual(self.request("/session", method="POST", payload={"key": "x" * 2000})[0], 413)
        self.assertEqual(self.request("/session", method="POST", payload={}, headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("/session", method="POST", payload=[])[0], 400)
        self.assertEqual(self.request("/session", method="GET")[0], 404)
        self.assertEqual(self.request("/admin/logout", method="PUT")[0], 405)

    def test_logout_revokes_private_assets_and_replay(self):
        cookie = self.login()
        session = json.loads(self.request("/admin/api/session", cookie=cookie)[2])
        self.assertEqual(self.request("/admin/logout", method="POST", payload={}, cookie=cookie, headers={"X-CSRF-Token": session["csrf"]})[0], 200)
        self.assertEqual(self.request("/admin/workspace.js", cookie=cookie)[0], 401)
        self.assertEqual(self.request("/admin/api/session", cookie=cookie)[0], 401)

    def test_no_browser_control_of_chain(self):
        with patch.object(self.admin.reader, "rpc") as rpc:
            cookie = self.login()
            for path in ("/admin/fund", "/admin/restart", "/admin/broadcast_tx", "/api/overview"):
                self.assertEqual(self.request(path, method="POST", payload={}, cookie=cookie)[0], 404)
            rpc.assert_not_called()


if __name__ == "__main__":
    if sys.argv[1:] == ["--browser-fixture"]:
        # Temporary browser acceptance only; never uses the real owner credential.
        with WebsiteServer(4184, "admin", KEY) as server:
            print("Synthetic admin fixture on port 4184", flush=True)
            server.serve_forever()
    else:
        unittest.main()
