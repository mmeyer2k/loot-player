#!/usr/bin/env python3
"""Sweep every host VLC plugin through the AppImage's bundled interpreter.

WHY THIS EXISTS

This AppImage does not bundle libVLC. At runtime it dlopens the host's
libvlc, which in turn dlopens on the order of 400 plugin .so files into the
same process (codecs, demuxers, access modules, and so on). The AppImage's
bundled `python3` (from python-build-standalone) carries `DT_RPATH`
(not `DT_RUNPATH`) `$ORIGIN/../lib`. RPATH on the main executable is
inherited by every `dlopen()` call made anywhere in that process — not just
Python's own imports — and it outranks `LD_LIBRARY_PATH`. So any shared
library that happens to sit in the AppDir's `usr/lib` shadows the host's
copy of that library for the host's VLC plugins too, even though those
plugins were never built against anything in the AppDir.

This has already broken a shipped build once. An early version of this
AppImage bundled `libglib-2.0.so.0` (needed by Qt's xcb platform plugin) at a
version missing symbols that several host VLC plugins expect at load time.
8 of 382 plugins failed to load, including `libavcodec_plugin.so` and
`libavformat_plugin.so` — silently removing H.264, HEVC, AAC and MP3
decoding. Nothing else in the build or the test suite noticed.

WHY `--version` CANNOT CATCH THIS

`--version` exits before `QApplication` is constructed and before libVLC is
touched at all. It never dlopens libvlc, let alone any of its plugins, so a
broken plugin tree is completely invisible to it. The only way to see this
class of bug is to actually attempt to load every plugin, under the exact
environment AppRun hands the real process, using the exact python3 binary
that ships in the AppImage (a host python3 has no such RPATH and would not
reproduce the shadowing at all).

The build now denies bundling glib specifically (see
packaging/appimage-extra-excludes), which fixes the one instance that was
caught. That guard is coincidental, not structural: several other bundled
libraries (libdbus-1, libgcrypt, libpng16, libsystemd, and others) are still
NEEDED by host VLC plugins, and some export fewer symbols than the host's
copies. Nothing stops a future dependency change from reintroducing this bug
under a different library name. This sweep is the only thing that would
catch it, so it runs on every build.

WHAT IT DOES

1. Finds the host's VLC plugin directory and collects every `.so` under it.
2. Extracts the given AppImage (`--appimage-extract`, no FUSE required) to
   get at its bundled `usr/bin/python3` and `usr/lib`.
3. Re-invokes itself as a worker under that bundled python3, with
   LD_LIBRARY_PATH and the Python path variables set the way AppRun sets
   them, and `ctypes.CDLL()`s every plugin path in that one process — the
   same load order and process-wide symbol visibility libvlccore itself
   uses.
4. Exits nonzero and lists every plugin that failed to load, if any did.

Usage:
    python3 packaging/vlc-plugin-sweep.py [path/to/loot-*.AppImage]
    python3 packaging/vlc-plugin-sweep.py --plugin-dir /usr/lib/x86_64-linux-gnu/vlc/plugins dist/loot-0.1.0-x86_64.AppImage

With no AppImage argument, the first match of dist/loot-*-x86_64.AppImage
under the repo root is used.
"""

from __future__ import annotations

import argparse
import ctypes
import glob
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Debian/Ubuntu multiarch triplets first, since that's what the CI container
# (ubuntu:22.04) and most dev machines use. Order doesn't matter beyond the
# first match found.
CANDIDATE_PLUGIN_DIRS = [
    "/usr/lib/x86_64-linux-gnu/vlc/plugins",
    "/usr/lib/aarch64-linux-gnu/vlc/plugins",
    "/usr/lib/vlc/plugins",
    "/usr/lib64/vlc/plugins",
]


def find_plugin_dir(explicit: str | None) -> str:
    if explicit:
        if not os.path.isdir(explicit):
            raise SystemExit(f"--plugin-dir {explicit} is not a directory")
        return explicit

    env = os.environ.get("VLC_PLUGIN_PATH")
    if env and os.path.isdir(env):
        return env

    for candidate in CANDIDATE_PLUGIN_DIRS:
        if os.path.isdir(candidate):
            return candidate

    matches = glob.glob("/usr/lib/*/vlc/plugins")
    if matches:
        return matches[0]

    raise SystemExit(
        "could not find the host's VLC plugin directory; "
        "is VLC installed? pass --plugin-dir to override"
    )


def collect_plugins(plugin_dir: str) -> list[str]:
    paths = []
    for root, _dirs, files in os.walk(plugin_dir):
        for name in files:
            if name.endswith(".so"):
                paths.append(os.path.join(root, name))
    paths.sort()
    return paths


def find_default_appimage() -> str:
    matches = sorted(glob.glob(os.path.join(REPO_ROOT, "dist", "loot-*-x86_64.AppImage")))
    if not matches:
        raise SystemExit(
            "no AppImage found under dist/; build one first (`make appimage`) "
            "or pass its path explicitly"
        )
    return matches[0]


def extract_appdir(appimage_or_appdir: str, extract_to: str) -> str:
    """Return a path to an AppDir for the given AppImage, extracting if needed."""
    path = os.path.abspath(appimage_or_appdir)

    if os.path.isdir(path):
        return path

    if not os.path.isfile(path):
        raise SystemExit(f"{path} is not a file or directory")

    # --appimage-extract unpacks the squashfs to ./squashfs-root and exits,
    # without running AppRun and without needing /dev/fuse. That matters in
    # CI, where GitHub runners have no FUSE 2.
    result = subprocess.run(
        [path, "--appimage-extract"],
        cwd=extract_to,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"extracting {path} failed (exit {result.returncode}):\n{result.stderr}"
        )

    appdir = os.path.join(extract_to, "squashfs-root")
    if not os.path.isdir(appdir):
        raise SystemExit(f"extraction did not produce {appdir}")
    return appdir


def apprun_environment(appdir: str) -> dict[str, str]:
    """The subset of packaging/AppRun's environment that governs dlopen().

    LD_LIBRARY_PATH is the one that matters for this sweep: it puts
    AppDir/usr/lib on the dynamic linker's search path exactly as AppRun does
    for the real app. The bundled python3's own DT_RPATH does the rest
    regardless of this variable, which is the whole point of the sweep — but
    setting it too keeps this faithful to AppRun rather than to a hand-picked
    subset of it.
    """
    env = dict(os.environ)
    old_ld = env.get("LD_LIBRARY_PATH", "")
    lib_dir = os.path.join(appdir, "usr", "lib")
    env["LD_LIBRARY_PATH"] = f"{lib_dir}:{old_ld}" if old_ld else lib_dir
    env["PYTHONSAFEPATH"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


def run_worker(list_path: str) -> int:
    """Runs inside the bundled python3. Loads every plugin, reports failures."""
    with open(list_path, encoding="utf-8") as f:
        plugins = [line.rstrip("\n") for line in f if line.strip()]

    failures = []
    for plugin_path in plugins:
        try:
            ctypes.CDLL(plugin_path)
        except OSError as exc:
            failures.append((os.path.basename(plugin_path), str(exc)))

    print(f"FAILCOUNT {len(failures)} of {len(plugins)}", flush=True)
    for name, err in failures:
        print(f"  {name} -> {err}", flush=True)
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="dlopen-sweep every host VLC plugin under the AppImage's "
        "bundled python3, the way libvlc itself would load them."
    )
    parser.add_argument(
        "appimage",
        nargs="?",
        help="path to the .AppImage (or an already-extracted AppDir); "
        "defaults to dist/loot-*-x86_64.AppImage",
    )
    parser.add_argument(
        "--plugin-dir",
        help="override the host VLC plugin directory (autodetected by default)",
    )
    parser.add_argument("--worker", metavar="LISTFILE", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    # Re-invoked by ourselves, running under the bundled python3.
    if args.worker:
        return run_worker(args.worker)

    plugin_dir = find_plugin_dir(args.plugin_dir)
    plugins = collect_plugins(plugin_dir)
    if not plugins:
        raise SystemExit(f"no .so files found under {plugin_dir}")
    print(f"sweeping {len(plugins)} plugins from {plugin_dir}", flush=True)

    appimage = args.appimage or find_default_appimage()

    with tempfile.TemporaryDirectory(prefix="vlc-plugin-sweep-") as tmp:
        appdir = extract_appdir(appimage, tmp)
        bundled_python = os.path.join(appdir, "usr", "bin", "python3")
        if not os.path.exists(bundled_python):
            raise SystemExit(f"no bundled python3 at {bundled_python}")

        list_path = os.path.join(tmp, "plugins.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            f.write("\n".join(plugins) + "\n")

        env = apprun_environment(appdir)
        result = subprocess.run(
            [bundled_python, os.path.abspath(__file__), "--worker", list_path],
            env=env,
        )
        return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
