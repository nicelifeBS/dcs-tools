#!/usr/bin/env python3
"""Set forcedOptions.optionsView to "optview_all" and externalViews to true in a DCS .trk,
and drop optionsViewExtended.
Also sets f11_free_camera to true in the "options" entry (enables the F11 free camera keys).

Usage: python trk_edit.py <file.trk>
Writes <file>_edited.trk next to the input; the input is left untouched.
"""
import re
import shutil
import sys
import zipfile
from pathlib import Path

TARGET = "optview_all"
KEY_EXT = re.compile(r'(\["optionsViewExtended"\]|\boptionsViewExtended)\s*=\s*\{')
KEY_VIEW = re.compile(r'((?:\["optionsView"\]|\boptionsView)\s*=\s*)"[^"]*"')
KEY_EXTVIEWS = re.compile(r'((?:\["externalViews"\]|\bexternalViews)\s*=\s*)(?:true|false)')


KEY_F11 = re.compile(r'((?:\["f11_free_camera"\]|\bf11_free_camera)\s*=\s*)(?:true|false)')


def remove_table(text, m):
    """Remove the `key = { ... },` table starting at match m (brace-matched)."""
    depth, i, in_str = 1, m.end(), False
    while depth:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    end = i
    if text[end:end + 1] == ",":
        end += 1
    # also swallow trailing comment (e.g. "-- end of [...]") and newline
    rest = re.match(r"[ \t]*(--[^\n]*)?\n?", text[end:])
    end += rest.end()
    start = text.rfind("\n", 0, m.start()) + 1  # drop leading indent
    return text[:start] + text[end:]


def edit_mission(text):
    fo = text.find("forcedOptions")
    if fo < 0:
        raise SystemExit("forcedOptions not found in mission")
    head, tail = text[:fo], text[fo:]
    tail, n = KEY_VIEW.subn(lambda m: f'{m.group(1)}"{TARGET}"', tail, count=1)
    if not n:
        raise SystemExit("optionsView not found in forcedOptions")
    tail, n = KEY_EXTVIEWS.subn(r"\g<1>true", tail, count=1)
    if not n:
        raise SystemExit("externalViews not found in forcedOptions")
    m = KEY_EXT.search(tail)
    removed = bool(m)
    if m:
        tail = remove_table(tail, m)
    return head + tail, removed


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    src = Path(sys.argv[1])
    dst = src.with_name(src.stem + "_edited.trk")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            if info.filename == "mission":
                raw = zin.read(info).decode("utf-8", "surrogateescape")
                new, removed = edit_mission(raw)
                zout.writestr(info, new.encode("utf-8", "surrogateescape"),
                              compress_type=info.compress_type)
                print(f'mission: optionsView -> "{TARGET}"; externalViews -> true; '
                      f'optionsViewExtended {"removed" if removed else "not present"}')
            elif info.filename == "options":
                raw = zin.read(info).decode("utf-8", "surrogateescape")
                new, n = KEY_F11.subn(r"\g<1>true", raw, count=1)
                if not n:
                    raise SystemExit("f11_free_camera not found in options")
                zout.writestr(info, new.encode("utf-8", "surrogateescape"),
                              compress_type=info.compress_type)
                print("options: f11_free_camera -> true")
            else:
                with zin.open(info) as fi, zout.open(info, "w") as fo:
                    shutil.copyfileobj(fi, fo, 1 << 20)
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
