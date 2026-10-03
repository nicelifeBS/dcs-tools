from __future__ import annotations

from pathlib import Path

import pytest

from replay_helper import hook_installer as hi

SRC_HOOK = Path(__file__).resolve().parents[1] / "src" / "replay_helper" / "hook" / "ReplayHelper.lua"


def dcs_dir(root: Path, name: str = "DCS") -> Path:
    d = root / name
    (d / "Config").mkdir(parents=True)
    return d


def test_bundled_hook_is_the_source_file() -> None:
    assert hi.bundled_hook() == SRC_HOOK.read_bytes()
    assert hi.hook_version(hi.bundled_hook()) == "0.1.0"


def test_find_dcs_dirs(tmp_path: Path) -> None:
    dcs_dir(tmp_path, "DCS")
    dcs_dir(tmp_path, "DCS.openbeta")
    (tmp_path / "DCS.empty").mkdir()           # not a DCS folder: nothing DCS made inside
    (tmp_path / "Other Game" / "Config").mkdir(parents=True)
    assert [p.name for p in hi.find_dcs_dirs(tmp_path)] == ["DCS", "DCS.openbeta"]
    assert hi.find_dcs_dirs(tmp_path / "missing") == []


def test_install_and_status(tmp_path: Path) -> None:
    d = dcs_dir(tmp_path)
    st = hi.hook_status(d)
    assert st.installed_version is None and st.needs_install
    assert st.describe() == "hook not installed"

    st = hi.install(d)
    assert (d / "Scripts" / "Hooks" / "ReplayHelper.lua").read_bytes() == hi.bundled_hook()
    assert st.current and not st.needs_install and st.describe() == "hook 0.1.0 installed"


def test_update_replaces_older_hook_and_removes_spike(tmp_path: Path) -> None:
    d = dcs_dir(tmp_path)
    hooks = d / "Scripts" / "Hooks"
    hooks.mkdir(parents=True)
    (hooks / "ReplayHelper.lua").write_text('local VERSION = "0.0.9"\n')
    (hooks / "ReplayHelperSpike.lua").write_text("-- spike")
    st = hi.hook_status(d)
    assert st.needs_install and st.spike_present
    assert st.describe() == ("hook 0.0.9 installed; 0.1.0 available; the spike hook "
                             "(ReplayHelperSpike.lua) is still there and clashes with it")
    st = hi.install(d)
    assert st.current and not st.spike_present and not (hooks / "ReplayHelperSpike.lua").exists()


def test_newer_installed_hook_is_left_alone(tmp_path: Path) -> None:
    d = dcs_dir(tmp_path)
    hooks = d / "Scripts" / "Hooks"
    hooks.mkdir(parents=True)
    (hooks / "ReplayHelper.lua").write_text('local VERSION = "0.10.0"\n')
    st = hi.hook_status(d)
    assert st.newer_installed and not st.needs_install


@pytest.mark.parametrize("a,b", [("0.1.0", "0.2.0"), ("0.9.0", "0.10.0"), (None, "0.1.0"), ("x", "0.0.1")])
def test_version_order(a, b) -> None:
    assert hi.version_key(a) < hi.version_key(b)
