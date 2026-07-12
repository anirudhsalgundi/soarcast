import json
import logging
import threading

from soarcast.constants import Constants

logger = logging.getLogger(__name__)

_lock = threading.Lock()


class DaemonState:
    """
    Persistent JSON-backed state for the always-on daemon, so reminders/
    dedup survive process restarts.

    Shape:
    {
      "aeon": {
        "<date>": {"last_countdown_at": <iso ts>, "night_begun_announced": bool}
      },
      "soar_runs": {
        "<run_id>": {"announced": bool, "posted_targets": [<obj_id>, ...]}
      },
      "nags": {
        "aeon_calendar": {"last_sent_at": <iso ts>},
        "scanning_roster": {"last_sent_at": <iso ts>}
      }
    }
    """

    def __init__(self, path=Constants.DAEMON_STATE_PATH):
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"aeon": {}, "soar_runs": {}, "nags": {}}
        try:
            with open(self.path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load daemon state from {self.path}: {e}")
            return {"aeon": {}, "soar_runs": {}, "nags": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.path, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save daemon state to {self.path}: {e}")

    # -- generic helpers --------------------------------------------------

    def get(self, *keys, default=None):
        with _lock:
            node = self._data
            for k in keys:
                if not isinstance(node, dict) or k not in node:
                    return default
                node = node[k]
            return node

    def set(self, *keys_and_value) -> None:
        *keys, value = keys_and_value
        with _lock:
            node = self._data
            for k in keys[:-1]:
                node = node.setdefault(k, {})
            node[keys[-1]] = value
            self._save()

    # -- AEON night reminders ---------------------------------------------

    def get_aeon_night_state(self, night_date: str) -> dict:
        return self.get("aeon", night_date, default={}) or {}

    def set_aeon_night_state(self, night_date: str, **fields) -> None:
        with _lock:
            night = self._data.setdefault("aeon", {}).setdefault(night_date, {})
            night.update(fields)
            self._save()

    # -- SOAR run announcer -------------------------------------------------

    def get_soar_run_state(self, run_id) -> dict:
        return self.get("soar_runs", str(run_id), default={}) or {}

    def mark_soar_run_announced(self, run_id) -> None:
        with _lock:
            run = self._data.setdefault("soar_runs", {}).setdefault(str(run_id), {"announced": False, "posted_targets": []})
            run["announced"] = True
            self._save()

    def add_posted_targets(self, run_id, obj_ids: list) -> None:
        with _lock:
            run = self._data.setdefault("soar_runs", {}).setdefault(str(run_id), {"announced": False, "posted_targets": []})
            posted = set(run.get("posted_targets", []))
            posted.update(obj_ids)
            run["posted_targets"] = sorted(posted)
            self._save()

    def get_posted_targets(self, run_id) -> set:
        return set(self.get_soar_run_state(run_id).get("posted_targets", []))

    # -- sheet staleness nags ----------------------------------------------

    def get_nag_last_sent(self, key: str):
        return self.get("nags", key, "last_sent_at", default=None)

    def set_nag_last_sent(self, key: str, iso_ts: str) -> None:
        with _lock:
            self._data.setdefault("nags", {}).setdefault(key, {})["last_sent_at"] = iso_ts
            self._save()
