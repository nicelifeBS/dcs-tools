"""Small JSON settings store: per-recording time sync, and app preferences.

Lives in %APPDATA%\\dcs-replay-helper\\settings.json on Windows, ~/.config/dcs-replay-helper
elsewhere; REPLAY_HELPER_CONFIG_DIR overrides the folder (tests use it).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .timesync import SyncSettings

APP_DIR = "dcs-replay-helper"


def config_dir() -> Path:
    override = os.environ.get("REPLAY_HELPER_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / APP_DIR
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_DIR


class Settings:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_dir() / "settings.json"
        self.data: dict = {}
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        if not isinstance(self.data, dict):
            self.data = {}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass  # settings are a convenience; never fail the app over them

    # --- per-recording time sync --------------------------------------------------------
    @staticmethod
    def _key(acmi_path: str | Path) -> str:
        return str(Path(acmi_path).resolve()).lower() if sys.platform == "win32" else str(Path(acmi_path).resolve())

    def sync_for(self, acmi_path: str | Path) -> SyncSettings:
        entry = self.data.get("sync", {}).get(self._key(acmi_path))
        if not isinstance(entry, dict):
            return SyncSettings()
        tz = entry.get("tz_minutes")
        fine = entry.get("fine_s", 0.0)
        return SyncSettings(tz_minutes=int(tz) if isinstance(tz, (int, float)) else None,
                            fine_s=float(fine) if isinstance(fine, (int, float)) else 0.0)

    def set_sync(self, acmi_path: str | Path, sync: SyncSettings) -> None:
        table = self.data.setdefault("sync", {})
        key = self._key(acmi_path)
        if sync == SyncSettings():
            table.pop(key, None)
        else:
            table[key] = {"tz_minutes": sync.tz_minutes, "fine_s": sync.fine_s}
        self.save()

    # --- simple values ------------------------------------------------------------------
    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()
