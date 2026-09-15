"""Single-owner authentication for the local Luxartium workspace, separate from chain keys."""
from collections import deque
import csv
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import threading
import time

COOKIE = "__Host-luxartium_admin"
ADMIN_HOST = "admin.luxartium.localhost"
IDLE_SECONDS = 30 * 60
ABSOLUTE_SECONDS = 8 * 60 * 60


def assert_plain_path(path: Path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise RuntimeError("Admin credential paths must not be links, junctions or reparse points.")


def set_owner_acl(path: Path, sid: str, directory: bool):
    """Replace the protected DACL atomically; never restore inherited permissions."""
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.ULONG)]
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    api.GetSecurityDescriptorDacl.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.BOOL)]
    api.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    api.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID, wintypes.LPVOID, wintypes.LPVOID]
    api.SetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = [wintypes.LPVOID]
    kernel.LocalFree.restype = wintypes.LPVOID
    descriptor = wintypes.LPVOID()
    policy = f"D:P(A;{'OICI' if directory else ''};FA;;;{sid})"
    if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(policy, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), wintypes.LPVOID()
        if not api.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)) or not present.value or not dacl:
            raise RuntimeError("Cannot construct the owner-only admin credential policy.")
        error = api.SetNamedSecurityInfoW(str(path), 1, 0x80000004, None, None, dacl, None)
        if error:
            raise ctypes.WinError(error)
    finally:
        kernel.LocalFree(descriptor)


def owner_access_key(scope: str = "admin") -> str:
    """Provision/read one high-entropy local credential. Never log it from a server."""
    if scope not in ("admin", "gateway"):
        raise ValueError("Unsupported credential scope")
    directory = Path.home() / ".luxartium" / scope
    path = directory / "access.key"
    for candidate in (directory.parent, directory, path):
        assert_plain_path(candidate)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], check=True,
                                capture_output=True, text=True)
        sid = next(csv.reader(result.stdout.strip().splitlines()))[1]
        if not re.fullmatch(r"S-1-[0-9-]+", sid):
            raise RuntimeError("Cannot establish the local credential owner.")
        set_owner_acl(directory, sid, directory=True)
    else:
        directory.chmod(0o700)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(secrets.token_urlsafe(32) + "\n")
    if os.name == "nt":
        set_owner_acl(path, sid, directory=False)
    else:
        path.chmod(0o600)
    key = path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", key):
        raise RuntimeError("The local admin credential is invalid; it was not overwritten.")
    return key


class AdminSessions:
    def __init__(self, access_key: str, clock=time.monotonic):
        self.key_hash = hashlib.sha256(access_key.encode()).digest()
        self.clock = clock
        self.sessions = {}
        self.failures = deque(maxlen=5)
        self.events = deque(maxlen=100)
        self.lock = threading.Lock()

    def event(self, action):
        self.events.append({"action": action, "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

    def login(self, key: str):
        with self.lock:
            now = self.clock()
            while self.failures and now - self.failures[0] >= 60:
                self.failures.popleft()
            if len(self.failures) >= 5:
                return 429, None
            if not hmac.compare_digest(hashlib.sha256(key.encode()).digest(), self.key_hash):
                self.failures.append(now)
                self.event("Sign-in rejected")
                return 401, None
            self.failures.clear()
            self.sessions = {k: v for k, v in self.sessions.items()
                             if now - v["created"] < ABSOLUTE_SECONDS and now - v["seen"] < IDLE_SECONDS}
            if len(self.sessions) >= 32:
                self.sessions.pop(next(iter(self.sessions)))
            token = secrets.token_urlsafe(32)
            self.sessions[hashlib.sha256(token.encode()).digest()] = {
                "created": now, "seen": now, "csrf": secrets.token_urlsafe(32)}
            self.event("Signed in")
            return 200, token

    def current(self, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return None
        with self.lock:
            identity = hashlib.sha256(token.encode()).digest()
            session = self.sessions.get(identity)
            now = self.clock()
            if not session:
                return None
            if now - session["created"] >= ABSOLUTE_SECONDS or now - session["seen"] >= IDLE_SECONDS:
                del self.sessions[identity]
                self.event("Session expired")
                return None
            session["seen"] = now
            return {"csrf": session["csrf"], "events": list(reversed(self.events)),
                    "expires_in": int(min(IDLE_SECONDS, ABSOLUTE_SECONDS - (now - session["created"])))}

    def logout(self, token: str):
        with self.lock:
            self.sessions.pop(hashlib.sha256(token.encode()).digest(), None)
            self.event("Signed out")
