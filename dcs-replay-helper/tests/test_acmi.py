from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from replay_helper.tacview.acmi import AcmiError, read_acmi, split_fields

DATA = Path(__file__).parent / "data"
SAMPLE = DATA / "sample_caucasus.zip.acmi"


def write(tmp_path: Path, body: str, name: str = "t.txt.acmi", newline: str = "\n", bom: bool = True) -> Path:
    text = "FileType=text/acmi/tacview\nFileVersion=2.2\n" + body
    data = text.replace("\n", newline).encode("utf-8")
    p = tmp_path / name
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    return p


# --- the real sample (DCS 2.9.30, DCS2ACMI 1.9.5, two bookmarks added in Tacview) -------------
def test_sample_globals() -> None:
    f = read_acmi(SAMPLE)
    assert f.file_version == "2.1"
    assert f.reference_time == datetime(2018, 2, 1, 12, 30, tzinfo=timezone.utc)
    assert f.reference_tod == 45000
    assert f.title == "IA-A10CII-Caucasus-Free Flight"
    assert f.data_source == "DCS 2.9.30.28536"
    assert f.data_recorder == "DCS2ACMI 1.9.5.201"
    assert (f.first_t, f.last_t) == (0.08, 116.89)


def test_sample_bookmarks_drop_tacview_camera_suffix() -> None:
    f = read_acmi(SAMPLE)
    marks = [(e.t, e.text, e.object_ids) for e in f.events if e.type == "Bookmark"]
    assert marks == [(67.95, "Running in", (0x5701, 0x5001)), (88.01, "idiot", (0x5701, 0x5001))]


def test_sample_objects() -> None:
    f = read_acmi(SAMPLE)
    player = f.objects[0x5701]
    assert player.pilot == "fubar 1-1 | nicelife" and player.name == "A-10C_2"
    assert player.tags == {"Air", "FixedWing"} and player.color == "Blue"
    assert player.removed_t == 91.06
    rockets = [o for o in f.objects.values() if o.name == "AGR_20A"]
    assert len(rockets) == 7 and all(o.has("Weapon", "Missile") for o in rockets)
    assert min(o.first_t for o in rockets) == 70.76


def test_progress_reaches_one() -> None:
    seen: list[float] = []
    read_acmi(SAMPLE, progress=seen.append)
    assert seen and seen[-1] == 1.0 and seen == sorted(seen)


# --- syntax -----------------------------------------------------------------------------------
def test_escaped_commas_and_continued_lines(tmp_path: Path) -> None:
    p = write(tmp_path, "0,Title=First line\\\nsecond\\, still title\n"
                        "#1\n1,T=1|2|3,Name=F-16C,Pilot=Smith\\, John\n")
    f = read_acmi(p)
    assert f.title == "First line\nsecond, still title"
    assert f.objects[1].pilot == "Smith, John"


def test_split_fields() -> None:
    assert split_fields("a,b") == ["a", "b"]
    assert split_fields(r"a\,b,c") == ["a,b", "c"]
    assert split_fields(r"a\\,b") == ["a\\", "b"]
    assert split_fields(r"x\ny") == [r"x\ny"]


def test_crlf_without_bom(tmp_path: Path) -> None:
    p = write(tmp_path, "0,Title=Hi\n#2.5\n0,Event=Bookmark|Here\n", newline="\r\n", bom=False)
    f = read_acmi(p)
    assert f.title == "Hi" and f.events[0].text == "Here" and f.events[0].t == 2.5


def test_comments_and_removals(tmp_path: Path) -> None:
    p = write(tmp_path, "// 1,Name=Ghost\n#1\n1,Name=F-16C,Type=Air+FixedWing\n#5\n-1\n")
    f = read_acmi(p)
    assert list(f.objects) == [1] and f.objects[1].removed_t == 5


def test_event_ids_must_name_known_objects(tmp_path: Path) -> None:
    p = write(tmp_path, "#1\ncafe,Name=Hornet\n#2\n"
                        "0,Event=Bookmark|CAFE\n"           # only token: it is the text
                        "0,Event=Bookmark|cafe|On the Hornet\n"
                        "0,Event=Bookmark|BEEF|Not an object\n"
                        "0,Event=Message|a|b|c\n")
    f = read_acmi(p)
    got = [(e.object_ids, e.text) for e in f.events]
    assert got == [((), "CAFE"), ((0xCAFE,), "On the Hornet"), ((), "BEEF|Not an object"), ((), "a|b|c")]


def test_timeout_params(tmp_path: Path) -> None:
    p = write(tmp_path, "#1\n1fb,Name=F-16C\nc9,Name=Su-27\n#3\n"
                        "0,Event=Timeout|SourceId:1fb|AmmoType:FOX2|AmmoCount:1|TargetId:c9|Outcome:Kill\n")
    e = read_acmi(p).events[0]
    assert e.type == "Timeout" and e.object_ids == (0x1FB, 0xC9)
    assert e.params["AmmoType"] == "FOX2" and e.params["Outcome"] == "Kill"


def test_out_of_order_frames_are_sorted(tmp_path: Path) -> None:
    p = write(tmp_path, "#10\n0,Event=Bookmark|late\n#2\n0,Event=Bookmark|early\n")
    f = read_acmi(p)
    assert [e.text for e in f.events] == ["early", "late"]
    assert (f.first_t, f.last_t) == (2, 10)


def test_zip_container(tmp_path: Path) -> None:
    src = write(tmp_path, "#1\n0,Event=Bookmark|zipped\n")
    z = tmp_path / "t.zip.acmi"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(src, "inner.txt.acmi")
    assert read_acmi(z).events[0].text == "zipped"


@pytest.mark.parametrize("content,match", [
    (b"7z\xbc\xaf\x27\x1c" + b"\0" * 32, "7-Zip"),
    (b"hello\n", "not a Tacview ACMI"),
    (b"FileType=text/acmi/tacview\nFileVersion=3.0\n", "unsupported ACMI version"),
    (b"", "not a Tacview ACMI"),
])
def test_rejects_bad_files(tmp_path: Path, content: bytes, match: str) -> None:
    p = tmp_path / "bad.acmi"
    p.write_bytes(content)
    with pytest.raises(AcmiError, match=match):
        read_acmi(p)


def test_empty_zip(tmp_path: Path) -> None:
    z = tmp_path / "empty.zip.acmi"
    with zipfile.ZipFile(z, "w"):
        pass
    with pytest.raises(AcmiError, match="empty"):
        read_acmi(z)
