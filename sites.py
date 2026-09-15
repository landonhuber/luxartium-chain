"""Three local Luxartium surfaces: public home, read-only explorer, private operator workspace."""
from contextlib import ExitStack
from http.cookies import SimpleCookie, CookieError
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit

from admin_auth import AdminSessions, ADMIN_HOST, COOKIE, ABSOLUTE_SECONDS, owner_access_key
from explorer import ASSETS, ChainReader, ExplorerError, ExplorerHandler, ExplorerServer

ROOT = Path(__file__).resolve().parent / "operator-ui"
HOME_PORT, EXPLORER_PORT, ADMIN_PORT = 4172, 4173, 4174


class WebsiteServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, role: str, access_key: str | None = None, reader=None):
        if role not in ("public", "admin"):
            raise ValueError("Unsupported site role")
        if role == "admin" and not access_key:
            raise ValueError("Admin requires an access key")
        self.role = role
        self.sessions = AdminSessions(access_key) if role == "admin" else None
        self.reader = reader or ChainReader()
        super().__init__(("127.0.0.1", port), WebsiteHandler)


class WebsiteHandler(ExplorerHandler):
    server_version = "LuxartiumSites/0.2"

    def valid_origin(self, mutation=False):
        hosts = {f"127.0.0.1:{self.server.server_port}"} if self.server.role == "public" else {f"{ADMIN_HOST}:{self.server.server_port}"}
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        if host not in hosts or (origin is not None and origin != "http://" + host) or (mutation and origin is None):
            self.json(403, {"error": "This request must use the site's own local origin."})
            return False
        return True

    def token(self):
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return cookie[COOKIE].value if COOKIE in cookie else ""
        except CookieError:
            return ""

    def redirect(self, path):
        self.reply(303, b"", "text/plain", {"Location": path})

    def file(self, path, mime, private=False):
        headers = {"X-Robots-Tag": "noindex, nofollow", "Cross-Origin-Resource-Policy": "same-origin"} if private else {}
        self.reply(200, path.read_bytes(), mime + "; charset=utf-8", headers)

    def do_GET(self):
        if not self.valid_origin():
            return
        try:
            if len(self.path) > 512:
                raise ExplorerError(414, "Request too long.")
            url = urlsplit(self.path)
            if url.scheme or url.netloc or url.query:
                raise ExplorerError(400, "Unsupported site path.")
            path = url.path
            if path == "/favicon.svg":
                self.file(ASSETS / "favicon.svg", "image/svg+xml")
                return
            if self.server.role == "public":
                files = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                         "/style.css": ("style.css", "text/css")}
                if path == "/api/network":
                    status = self.server.reader.rpc("status")
                    supply = self.server.reader.rest("cosmos/bank/v1beta1/supply/by_denom", {"denom": "uluxar"})["amount"]
                    self.json(200, {"chain_id": status["node_info"]["network"], "height": status["sync_info"]["latest_block_height"],
                                    "time": status["sync_info"]["latest_block_time"], "catching_up": status["sync_info"]["catching_up"], "supply": supply})
                    return
                if path in files:
                    name, mime = files[path]
                    self.file(ROOT / "website" / name, mime)
                    return
            else:
                if path == "/":
                    self.redirect("/admin/")
                    return
                public = {"/login": (ROOT / "admin/login.html", "text/html"),
                          "/login.js": (ROOT / "admin/login.js", "text/javascript"),
                          "/style.css": (ASSETS / "style.css", "text/css"),
                          "/admin-style.css": (ROOT / "admin/style.css", "text/css")}
                if path in public:
                    file, mime = public[path]
                    self.file(file, mime, private=True)
                    return
                session = self.server.sessions.current(self.token())
                if path.startswith("/admin/") and not session:
                    if path == "/admin/":
                        self.redirect("/login")
                    else:
                        self.json(401, {"error": "Sign in to access the operator workspace."})
                    return
                private = {"/admin/": ("index.html", "text/html"),
                           "/admin/app.js": ("app.js", "text/javascript"),
                           "/admin/workspace.js": ("workspace.js", "text/javascript")}
                if path in private:
                    name, mime = private[path]
                    self.file(ROOT / "admin" / name, mime, private=True)
                    return
                if path == "/admin/api/session":
                    self.json(200, {"role": "owner", **session})
                    return
            raise ExplorerError(404, "That page does not exist.")
        except ExplorerError as error:
            self.json(error.status, {"error": str(error)})
        except (ValueError, KeyError, TypeError, OSError):
            self.json(502, {"error": "Site data is temporarily unavailable."})

    def do_POST(self):
        if self.server.role != "admin":
            self.json(405, {"error": "The public site is read-only."})
            return
        if not self.valid_origin(mutation=True):
            return
        try:
            if self.path not in ("/session", "/admin/logout"):
                raise ExplorerError(404, "That action does not exist.")
            if self.headers.get("Content-Type") != "application/json" or self.headers.get("Transfer-Encoding"):
                raise ExplorerError(415, "Use a bounded JSON request.")
            length = self.headers.get("Content-Length", "")
            if not re.fullmatch(r"[0-9]{1,4}", length) or not 0 < int(length) <= 1024:
                raise ExplorerError(413, "The sign-in request is too large or has no length.")
            payload = json.loads(self.rfile.read(int(length)))
            if not isinstance(payload, dict):
                raise ExplorerError(400, "Invalid request.")
            if self.path == "/session":
                key = payload.get("key")
                if set(payload) != {"key"} or not isinstance(key, str) or len(key) > 128:
                    raise ExplorerError(400, "Enter your operator access key.")
                status, token = self.server.sessions.login(key)
                if status != 200:
                    raise ExplorerError(status, "Too many attempts. Try again in one minute." if status == 429 else "The access key was not accepted.")
                cookie = f"{COOKIE}={token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age={ABSOLUTE_SECONDS}"
                self.reply(200, b'{"ok":true}', "application/json", {"Set-Cookie": cookie})
            else:
                session = self.server.sessions.current(self.token())
                if not session:
                    raise ExplorerError(401, "Your session has expired.")
                import hmac
                csrf = self.headers.get("X-CSRF-Token", "")
                if not re.fullmatch(r"[A-Za-z0-9_-]{43}", csrf) or not hmac.compare_digest(csrf, session["csrf"]):
                    raise ExplorerError(403, "The sign-out request could not be verified.")
                self.server.sessions.logout(self.token())
                self.reply(200, b'{"ok":true}', "application/json", {"Set-Cookie": f"{COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0"})
        except ExplorerError as error:
            self.json(error.status, {"error": str(error)})
        except (ValueError, UnicodeError, OSError):
            self.json(400, {"error": "The request could not be read."})

    # Only the explicit POST sign-in/sign-out routes above may change session state.
    do_PUT = ExplorerHandler.do_POST
    do_PATCH = ExplorerHandler.do_POST
    do_DELETE = ExplorerHandler.do_POST


def serve_sites():
    key = owner_access_key()
    with ExitStack() as stack:
        servers = [stack.enter_context(WebsiteServer(HOME_PORT, "public")),
                   stack.enter_context(ExplorerServer(EXPLORER_PORT)),
                   stack.enter_context(WebsiteServer(ADMIN_PORT, "admin", key))]
        del key
        threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
        for thread in threads:
            thread.start()
        print(f"Luxartium: http://127.0.0.1:{HOME_PORT}", flush=True)
        print(f"Explorer: http://127.0.0.1:{EXPLORER_PORT}", flush=True)
        print(f"Admin: http://{ADMIN_HOST}:{ADMIN_PORT}/admin/", flush=True)
        print("For your local operator access key: python localnet.py admin-key", flush=True)
        try:
            threads[0].join()
        except KeyboardInterrupt:
            pass
        finally:
            for server in servers:
                server.shutdown()
            for thread in threads:
                thread.join()
