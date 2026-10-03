"""Finding DCS's Saved Games folders and installing the hook into them.

The hook lives in <Saved Games>\\DCS\\Scripts\\Hooks\\ReplayHelper.lua (DCS.openbeta for the
old open beta, other DCS* folders for side-by-side installs). Nothing goes into the DCS
install folder, so integrity checks are unaffected and DCS updates leave it alone.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

HOOK_NAME = "ReplayHelper.lua"
SPIKE_NAME = "ReplayHelperSpike.lua"  # milestone 0 probe: same ports, must not run alongside
_VERSION = re.compile(r'^local VERSION\s*=\s*"([^"]+)"', re.M)


def bundled_hook() -> bytes:
    """The hook shipped with this app."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):  # PyInstaller exe
        return (Path(sys._MEIPASS) / "replay_helper" / "hook" / HOOK_NAME).read_bytes()
    return resources.files("replay_helper").joinpath("hook", HOOK_NAME).read_bytes()


def hook_version(source: bytes | str | None) -> str | None:
    if source is None:
        return None
    text = source.decode("utf-8", errors="replace") if isinstance(source, bytes) else source
    m = _VERSION.search(text)
    return m.group(1) if m else None


def version_key(version: str | None) -> tuple:
    parts = []
    for p in (version or "").split("."):
        parts.append(int(p) if p.isdigit() else -1)
    return tuple(parts)


# --------------------------------------------------------------------------------------
# where
# --------------------------------------------------------------------------------------
def saved_games_dir() -> Path:
    """The user's Saved Games folder (asked from Windows, which knows if it was moved)."""
    if sys.platform == "win32":
        try:
            import ctypes
            import uuid

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                            ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

            u = uuid.UUID("{4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4}")  # FOLDERID_SavedGames
            guid = GUID(u.fields[0], u.fields[1], u.fields[2],
                        (ctypes.c_ubyte * 8)(*u.bytes[8:]))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                                           ctypes.byref(out)) == 0:
                path = Path(out.value)
                ctypes.windll.ole32.CoTaskMemFree(out)
                return path
        except (OSError, AttributeError, ValueError):
            pass
    return Path(os.environ.get("USERPROFILE", Path.home())) / "Saved Games"


def find_dcs_dirs(saved_games: Path | None = None) -> list[Path]:
    """DCS* folders in Saved Games that look like DCS's own (have Config, Logs or Scripts)."""
    root = saved_games or saved_games_dir()
    try:
        candidates = sorted(p for p in root.iterdir() if p.is_dir() and p.name.upper().startswith("DCS"))
    except OSError:
        return []
    return [p for p in candidates if any((p / sub).is_dir() for sub in ("Config", "Logs", "Scripts"))]


# --------------------------------------------------------------------------------------
# what is there
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class HookStatus:
    dcs_dir: Path
    installed_version: str | None  # None: not installed
    bundled_version: str | None
    current: bool  # installed and identical to the bundled hook
    newer_installed: bool  # installed version is newer than this app's
    spike_present: bool

    @property
    def hook_path(self) -> Path:
        return self.dcs_dir / "Scripts" / "Hooks" / HOOK_NAME

    @property
    def needs_install(self) -> bool:
        return (not self.current and not self.newer_installed) or self.spike_present

    def describe(self) -> str:
        if self.installed_version is None:
            text = "hook not installed"
        elif self.current:
            text = f"hook {self.installed_version} installed"
        elif self.newer_installed:
            text = f"hook {self.installed_version} installed (newer than this app's {self.bundled_version})"
        else:
            text = f"hook {self.installed_version} installed; {self.bundled_version} available"
        if self.spike_present:
            text += f"; the spike hook ({SPIKE_NAME}) is still there and clashes with it"
        return text


def hook_status(dcs_dir: Path, bundled: bytes | None = None) -> HookStatus:
    bundled = bundled if bundled is not None else bundled_hook()
    hooks = dcs_dir / "Scripts" / "Hooks"
    try:
        installed = (hooks / HOOK_NAME).read_bytes()
    except OSError:
        installed = None
    iv, bv = hook_version(installed), hook_version(bundled)
    return HookStatus(
        dcs_dir=dcs_dir,
        installed_version=iv if installed is not None else None,
        bundled_version=bv,
        current=installed == bundled,
        newer_installed=installed is not None and installed != bundled and version_key(iv) > version_key(bv),
        spike_present=(hooks / SPIKE_NAME).exists(),
    )


def install(dcs_dir: Path, bundled: bytes | None = None) -> HookStatus:
    """Install or update the hook in this DCS folder and remove the spike hook. Raises OSError."""
    bundled = bundled if bundled is not None else bundled_hook()
    hooks = dcs_dir / "Scripts" / "Hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    target = hooks / HOOK_NAME
    tmp = target.with_suffix(".lua.tmp")
    tmp.write_bytes(bundled)
    tmp.replace(target)
    spike = hooks / SPIKE_NAME
    if spike.exists():
        spike.unlink()
    return hook_status(dcs_dir, bundled)
