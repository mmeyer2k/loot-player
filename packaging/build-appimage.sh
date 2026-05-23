#!/usr/bin/env bash
# Build a self-contained loot-player AppImage.
#
# Usage: packaging/build-appimage.sh [VERSION]
#   VERSION defaults to loot_player.version.__version__.
#
# Requires (apt): vlc, librsvg2-bin, file, patchelf, wget, ca-certificates.
# Downloads python-build-standalone and appimagetool on first run.
set -euo pipefail

REPO="$(cd "$(dirname "${0}")/.." && pwd)"
VERSION="${1:-$(python3 -c 'import loot_player.version as v; print(v.__version__)')}"
ARCH="x86_64"

# Pinned tool versions (bump deliberately).
PY_VERSION="3.11.9"
PBS_TAG="20240415"   # astral-sh/python-build-standalone release date tag
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PY_VERSION}+${PBS_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"

BUILD="${REPO}/build/appimage"
APPDIR="${BUILD}/AppDir"
rm -rf "${BUILD}"
mkdir -p "${APPDIR}/usr/lib/vlc" "${BUILD}/tools"

echo ">> Fetching relocatable CPython ${PY_VERSION}"
wget -qO "${BUILD}/python.tar.gz" "${PBS_URL}"
tar -xzf "${BUILD}/python.tar.gz" -C "${BUILD}"
mv "${BUILD}/python" "${APPDIR}/usr/python"
PYBIN="${APPDIR}/usr/python/bin/python3"

echo ">> Installing loot-player and deps into the bundle"
"${PYBIN}" -m pip install --upgrade pip
"${PYBIN}" -m pip install "${REPO}"

echo ">> Locating system libVLC"
# NB: no early `exit` in awk — exiting before ldconfig finishes writing would
# SIGPIPE it, and `set -o pipefail` would then abort the script (exit 141).
LIBVLC="$(ldconfig -p | awk '/libvlc\.so/ && !x {print $NF; x=1}')"
LIBVLCCORE="$(ldconfig -p | awk '/libvlccore\.so/ && !x {print $NF; x=1}')"
VLC_PLUGINS="$(dirname "${LIBVLC}")/vlc/plugins"
[ -d "${VLC_PLUGINS}" ] || VLC_PLUGINS="/usr/lib/x86_64-linux-gnu/vlc/plugins"
[ -d "${VLC_PLUGINS}" ] || { echo "VLC plugins dir not found"; exit 1; }

echo ">> Copying libVLC + plugin tree"
cp -L "${LIBVLC}"* "${APPDIR}/usr/lib/" 2>/dev/null || cp -L "${LIBVLC}" "${APPDIR}/usr/lib/libvlc.so"
cp -L "${LIBVLCCORE}" "${APPDIR}/usr/lib/" || echo "WARN: could not copy libvlccore (${LIBVLCCORE})"
ln -sf "$(basename "${LIBVLC}")" "${APPDIR}/usr/lib/libvlc.so" 2>/dev/null || true
cp -a "${VLC_PLUGINS}" "${APPDIR}/usr/lib/vlc/plugins"

echo ">> Resolving transitive .so dependencies via ldd"
# Libraries that must come from the host (glibc family, GL, X server side).
EXCLUDE='^(libc|libm|libdl|libpthread|librt|libresolv|ld-linux.*|libutil|libgcc_s|libGL|libGLX|libEGL|libdrm|libGLdispatch|libX11|libxcb)\.so'
collect_deps() {
  for f in "$@"; do
    ldd "${f}" 2>/dev/null | awk '/=> \//{print $3}' || true
  done
}
mapfile -t SCAN < <(find "${APPDIR}/usr/lib" -name '*.so*' -type f)
collect_deps "${SCAN[@]}" | sort -u | while read -r dep; do
  base="$(basename "${dep}")"
  if echo "${base}" | grep -Eq "${EXCLUDE}"; then continue; fi
  [ -e "${APPDIR}/usr/lib/${base}" ] || cp -L "${dep}" "${APPDIR}/usr/lib/"
done

echo ">> Bundling Qt's xcb platform-plugin prerequisites"
for lib in libxcb-cursor.so.0 libxkbcommon.so.0 libxkbcommon-x11.so.0; do
  p="$(ldconfig -p | awk -v l="${lib}" '$1==l && !x {print $NF; x=1}')"
  [ -n "${p}" ] && cp -L "${p}" "${APPDIR}/usr/lib/" || true
done

echo ">> Regenerating the VLC plugin cache"
CACHEGEN="$(find /usr/lib -name vlc-cache-gen -type f -print -quit 2>/dev/null || true)"
[ -n "${CACHEGEN}" ] && "${CACHEGEN}" "${APPDIR}/usr/lib/vlc/plugins" || \
  echo "WARN: vlc-cache-gen not found; plugins will be scanned at startup"

echo ">> Desktop integration (icon + .desktop + AppRun)"
rsvg-convert -w 256 -h 256 "${REPO}/assets/loot.svg" -o "${APPDIR}/loot-player.png"
sed -e "s|^Exec=.*|Exec=AppRun|" \
    -e "s|^Icon=.*|Icon=loot-player|" \
    "${REPO}/packaging/loot.desktop.in" \
  | sed -e "s|@REPO@||g" \
  > "${APPDIR}/loot-player.desktop"
cp "${REPO}/packaging/AppRun" "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"

echo ">> Packaging with appimagetool"
wget -qO "${BUILD}/tools/appimagetool" "${APPIMAGETOOL_URL}"
chmod +x "${BUILD}/tools/appimagetool"
OUT="${REPO}/loot-player-${VERSION}-${ARCH}.AppImage"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="${ARCH}" \
  "${BUILD}/tools/appimagetool" "${APPDIR}" "${OUT}"

echo ">> Built: ${OUT}"
