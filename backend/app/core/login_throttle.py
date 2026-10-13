"""Small process-local login throttle for the supported single-worker deployment."""

from math import ceil
from threading import RLock
from time import monotonic


class LoginThrottle:
    def __init__(self, max_failures=5, window_seconds=900, lock_seconds=900, clock=monotonic):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lock_seconds = lock_seconds
        self.clock = clock
        self._entries = {}
        self._lock = RLock()

    @staticmethod
    def _key(username, client_ip):
        return str(username or "").strip().casefold(), str(client_ip or "unknown")

    def _prune(self, now):
        expired = [
            key for key, entry in self._entries.items()
            if entry["locked_until"] <= now
            and not any(timestamp > now - self.window_seconds for timestamp in entry["failures"])
        ]
        for key in expired:
            self._entries.pop(key, None)

    def retry_after(self, username, client_ip):
        now = self.clock()
        key = self._key(username, client_ip)
        with self._lock:
            self._prune(now)
            entry = self._entries.get(key)
            if not entry or entry["locked_until"] <= now:
                return 0
            return max(1, ceil(entry["locked_until"] - now))

    def record_failure(self, username, client_ip):
        now = self.clock()
        key = self._key(username, client_ip)
        with self._lock:
            self._prune(now)
            entry = self._entries.setdefault(key, {"failures": [], "locked_until": 0.0})
            if entry["locked_until"] > now:
                return max(1, ceil(entry["locked_until"] - now))
            entry["failures"] = [
                timestamp for timestamp in entry["failures"] if timestamp > now - self.window_seconds
            ]
            entry["failures"].append(now)
            if len(entry["failures"]) >= self.max_failures:
                entry["locked_until"] = now + self.lock_seconds
                return self.lock_seconds
            return 0

    def clear(self, username, client_ip):
        with self._lock:
            self._entries.pop(self._key(username, client_ip), None)


login_throttle = LoginThrottle()
