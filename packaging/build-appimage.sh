#!/usr/bin/env bash
# Build dist/loot-<version>-x86_64.AppImage.
#
# CONTAINER ONLY. Run it through `make appimage`, which starts ubuntu:22.04
# for you. It apt-installs build dependencies and expects to be root.
#
# Why 22.04: PyQt6 publishes exactly one x86_64 Linux wheel tag,
# manylinux_2_34, so glibc 2.34 is the floor no matter what. 22.04 ships
# glibc 2.35, which sits at that floor. Building on a newer host produces a
# binary that runs on almost nothing.
#
# libVLC is deliberately NOT bundled; the AppImage links against the host's
# VLC. See docs/superpowers/specs/2026-08-01-appimage-build-design.md.

set -euo pipefail

PYTHON_VERSION="3.13.14"
PYTHON_MINOR="3.13"
PYTHON_BUILD="20260728"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_BUILD}/cpython-${PYTHON_VERSION}+${PYTHON_BUILD}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$REPO/build"
APPDIR="$BUILD/AppDir"
CACHE="$BUILD/cache"
DIST="$REPO/dist"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$REPO/loot_player/version.py")"
[ -n "$VERSION" ] || { echo "could not read __version__" >&2; exit 1; }
OUT="$DIST/loot-${VERSION}-x86_64.AppImage"

log() { printf '\n==> %s\n' "$*"; }

if [ "$(id -u)" -eq 0 ]; then
    log "Installing build dependencies"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    # curl/ca-certificates to fetch, file/desktop-file-utils for appimagetool,
    # and the xcb runtime so ldd can resolve the Qt platform plugin's needs.
    apt-get install -y -qq --no-install-recommends \
        curl ca-certificates file desktop-file-utils \
        libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
        libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
        libxcb-xkb1 libxkbcommon-x11-0 libsm6 libice6 libgl1 libegl1 \
        libfontconfig1 libdbus-1-3 >/dev/null
fi

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr" "$CACHE" "$DIST"

log "Fetching CPython ${PYTHON_VERSION}"
PBS_TAR="$CACHE/cpython-${PYTHON_VERSION}-${PYTHON_BUILD}.tar.gz"
[ -f "$PBS_TAR" ] || curl -fsSL "$PBS_URL" -o "$PBS_TAR"
tar -xf "$PBS_TAR" -C "$APPDIR/usr" --strip-components=1

PY="$APPDIR/usr/bin/python3"
"$PY" -V

log "Installing loot and its dependencies"
"$PY" -m pip install --no-cache-dir --quiet --upgrade pip setuptools
"$PY" -m pip install --no-cache-dir --quiet "$REPO"

SITE="$APPDIR/usr/lib/python${PYTHON_MINOR}/site-packages"
QT6="$SITE/PyQt6/Qt6"
[ -d "$QT6" ] || { echo "PyQt6/Qt6 missing at $QT6" >&2; exit 1; }

# libVLC must never end up inside the AppDir.
if find "$APPDIR" -name 'libvlc*.so*' -print -quit | grep -q .; then
    echo "libvlc found in AppDir; it must not be bundled" >&2
    exit 1
fi

log "Pruning unused Qt modules"
# loot imports QtCore, QtGui and QtWidgets only.
rm -rf "$QT6/qml" "$QT6/translations" "$QT6/plugins/qmltooling"
rm -f "$QT6"/lib/libQt6Quick*.so* "$QT6"/lib/libQt6Qml*.so*

log "Deploying xcb libraries for the Qt platform plugin"
mkdir -p "$APPDIR/usr/lib"
QXCB="$QT6/plugins/platforms/libqxcb.so"
[ -f "$QXCB" ] || { echo "libqxcb.so missing at $QXCB" >&2; exit 1; }

if ldd "$QXCB" | grep -q 'not found'; then
    echo "unresolved dependencies for libqxcb.so:" >&2
    ldd "$QXCB" | grep 'not found' >&2
    echo "add the providing package to the apt-get list above" >&2
    exit 1
fi

while read -r lib; do
    base="$(basename "$lib")"
    grep -qxF "$base" "$REPO/packaging/appimage-excludelist" && continue
    [ -e "$APPDIR/usr/lib/$base" ] && continue
    cp -L "$lib" "$APPDIR/usr/lib/$base"
    echo "    + $base"
done < <(ldd "$QXCB" | awk '/=> \//{print $3}' | sort -u)

log "Writing AppDir metadata"
install -Dm755 "$REPO/packaging/AppRun" "$APPDIR/AppRun"
install -Dm644 "$REPO/packaging/loot-appimage.desktop" "$APPDIR/loot.desktop"
install -Dm644 "$REPO/loot_player/assets/loot.svg" "$APPDIR/loot.svg"
install -Dm644 "$REPO/packaging/loot-appimage.desktop" \
    "$APPDIR/usr/share/applications/loot.desktop"
install -Dm644 "$REPO/loot_player/assets/loot.svg" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps/loot.svg"

log "Packaging"
TOOL="$CACHE/appimagetool-x86_64.AppImage"
if [ ! -f "$TOOL" ]; then
    curl -fsSL "$APPIMAGETOOL_URL" -o "$TOOL"
    chmod +x "$TOOL"
fi
rm -f "$OUT"
# No /dev/fuse in the build container, so appimagetool has to unpack itself.
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$TOOL" "$APPDIR" "$OUT" >/dev/null

log "Built $OUT ($(du -h "$OUT" | cut -f1))"
