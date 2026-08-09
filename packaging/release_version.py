#!/usr/bin/env python3
"""Version arithmetic for the release flow.

The /release skill calls this instead of computing versions itself. The cases
that motivate it are the ones that look trivial and are not: 0.9.0 + minor is
0.10.0 rather than 1.0.0, 1.2.9 + patch is 1.2.10 rather than 1.3.0, and
"0.10.0" > "0.9.0" is *false* when compared as strings.

Lives in packaging/ rather than loot_player/ because release tooling has no
business shipping inside the AppImage.

    ./packaging/release_version.py current          -> 0.0.0
    ./packaging/release_version.py bump patch       -> 0.0.1   (prints, does not write)
    ./packaging/release_version.py set 0.0.1        -> 0.0.1   (writes version.py)
    ./packaging/release_version.py newer 0.10.0 0.9.0         (exit 0 if newer, 1 if not)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO / "loot_player" / "version.py"

BUMPS = ("major", "minor", "patch")

# Deliberately strict: no leading v, no pre-release suffixes, no two-part
# versions. tests/test_version.py asserts the same shape, and the CI tag guard
# compares the tag minus its leading v against this file byte for byte.
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_FILE_RE = re.compile(r'^__version__ = "(.*)"$', re.MULTILINE)


class VersionError(ValueError):
    """Raised for anything that is not a plain X.Y.Z version."""


def parse(version: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(version)
    if not match:
        raise VersionError(f"not a three-part version: {version!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def render(parts: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in parts)


def bump(current: str, kind: str) -> str:
    major, minor, patch = parse(current)
    if kind == "major":
        return render((major + 1, 0, 0))
    if kind == "minor":
        return render((major, minor + 1, 0))
    if kind == "patch":
        return render((major, minor, patch + 1))
    raise VersionError(f"unknown bump {kind!r}, expected one of {', '.join(BUMPS)}")


def is_newer(target: str, other: str) -> bool:
    """True when target sorts after other. Numeric, not lexicographic."""
    return parse(target) > parse(other)


def read_current(path: Path = VERSION_FILE) -> str:
    match = _FILE_RE.search(path.read_text())
    if not match:
        raise VersionError(f"no __version__ assignment found in {path}")
    return match.group(1)


def write_current(version: str, path: Path = VERSION_FILE) -> None:
    parse(version)  # refuse to write junk into the source of truth
    text = path.read_text()
    updated, count = _FILE_RE.subn(f'__version__ = "{version}"', text)
    if count != 1:
        raise VersionError(f"expected one __version__ in {path}, replaced {count}")
    path.write_text(updated)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Version arithmetic for releases.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("current", help="print the version in loot_player/version.py")

    bump_parser = sub.add_parser("bump", help="print the next version, without writing")
    bump_parser.add_argument("kind", choices=BUMPS)

    set_parser = sub.add_parser("set", help="write a version into loot_player/version.py")
    set_parser.add_argument("version")

    newer_parser = sub.add_parser("newer", help="exit 0 when target is newer than other")
    newer_parser.add_argument("target")
    newer_parser.add_argument("other")

    args = parser.parse_args(argv)

    try:
        if args.command == "current":
            print(read_current())
        elif args.command == "bump":
            print(bump(read_current(), args.kind))
        elif args.command == "set":
            write_current(args.version)
            print(args.version)
        elif args.command == "newer":
            return 0 if is_newer(args.target, args.other) else 1
    except VersionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
