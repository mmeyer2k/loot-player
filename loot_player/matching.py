"""Pure-function filename parsers per library type. Called from Scanner.
Each function returns a dict of whatever fields it could extract."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any


def parse_generic(filename: str) -> dict[str, Any]:
    title, _ = os.path.splitext(filename)
    return {"title": title}


_YEAR_PATTERNS = [
    re.compile(r"\((\d{4})\)"),         # (1999)
    re.compile(r"\[(\d{4})\]"),         # [1999]
    re.compile(r"[.\s](\d{4})[.\s]"),   # .1999. or  1999
]


def _plausible_year(y: int) -> bool:
    return 1900 <= y <= datetime.now().year + 2


def _normalize_title(s: str) -> str:
    s = s.replace(".", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" -")


def parse_movie(filename: str) -> dict[str, Any]:
    base, _ = os.path.splitext(filename)
    best_pos = -1
    best_year: int | None = None
    for pat in _YEAR_PATTERNS:
        for m in pat.finditer(base):
            y = int(m.group(1))
            if _plausible_year(y) and m.start() > best_pos:
                best_pos = m.start()
                best_year = y
    if best_year is None:
        return {"title": _normalize_title(base), "year": None}
    return {"title": _normalize_title(base[:best_pos]), "year": best_year}


_SXXEYY = re.compile(r"[sS](\d{1,2})[eE](\d{1,3})")
_ONE_X = re.compile(r"(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)")
_SEASON_FOLDER = re.compile(r"(?i)^(?:season\s*|s0?)(\d{1,2})$")
_LEADING_NUM = re.compile(r"^\s*(\d{1,3})\b")


def parse_tv(filename: str, parent_dir: str) -> dict[str, Any]:
    base, _ = os.path.splitext(filename)

    m = _SXXEYY.search(base) or _ONE_X.search(base)
    if m:
        season, episode = int(m.group(1)), int(m.group(2))
        series = _normalize_title(base[:m.start()]) \
                 or os.path.basename(parent_dir.rstrip("/"))
        return {"series": series, "season": season, "episode": episode}

    folder_name = os.path.basename(parent_dir.rstrip("/"))
    season_match = _SEASON_FOLDER.match(folder_name)
    if season_match:
        season = int(season_match.group(1))
        series_dir = os.path.dirname(parent_dir.rstrip("/"))
        series = os.path.basename(series_dir) or parent_dir
        ep_match = _LEADING_NUM.search(base)
        episode = int(ep_match.group(1)) if ep_match else None
        return {"series": series, "season": season, "episode": episode}

    return {"series": folder_name, "season": None, "episode": None}


_TRACK_PREFIX = re.compile(r"^\s*(\d{1,3})\s*[-.\s]+(.*)$")


def parse_music(filename: str, parent_dir: str) -> dict[str, Any]:
    base, _ = os.path.splitext(filename)
    track = None
    title = base
    m = _TRACK_PREFIX.match(base)
    if m:
        track = int(m.group(1))
        title = m.group(2).strip()
    title = _normalize_title(title)

    parts = [p for p in parent_dir.strip("/").split("/") if p]
    # parts[0] is treated as the library root; album/artist live below it.
    album = parts[-1] if len(parts) >= 2 else None
    artist = parts[-2] if len(parts) >= 3 else None
    return {"artist": artist, "album": album, "track": track, "title": title}


def parse(library_type: str, filename: str, parent_dir: str) -> dict[str, Any]:
    if library_type == "movies":
        return parse_movie(filename)
    if library_type == "tv":
        return parse_tv(filename, parent_dir)
    if library_type == "music":
        return parse_music(filename, parent_dir)
    return parse_generic(filename)
