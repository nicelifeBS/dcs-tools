"""The spike client's key parsing (tools/spike_client.py is a script, so it is loaded by path)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "spike_client", Path(__file__).resolve().parents[1] / "tools" / "spike_client.py")
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


@pytest.mark.parametrize("name,scans", [
    ("f2", [0x3C]),
    ("ctrl+f2", [0x1D, 0x3C]),
    ("alt+num*", [0x38, 0x37]),
    ("alt+num/", [0x38, 0x35 | 0x100]),  # the numpad divide is an extended key
    ("shift+num-", [0x2A, 0x4A]),
    ("numplus", [0x4E]),
    ("ALT+NumPlus", [0x38, 0x4E]),
    ("num5", [0x4C]),
    ("numenter", [0x1C | 0x100]),
])
def test_view_chord(name: str, scans: list[int]) -> None:
    assert client.view_chord(name) == scans


@pytest.mark.parametrize("name", ["x", "alt+x", "num+", "up", "meta+f2", "alt+"])
def test_view_chord_rejects_unknown_keys(name: str) -> None:
    assert client.view_chord(name) is None
