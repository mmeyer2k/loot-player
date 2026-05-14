#!/usr/bin/env bash
# Install loot.desktop into the user's KDE applications directory.
# Re-run after moving or renaming the repo.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
TARGET="$TARGET_DIR/loot.desktop"

mkdir -p "$TARGET_DIR"
sed "s|@REPO@|${REPO}|g" "$REPO/packaging/loot.desktop.in" \
  | sed "s|^Exec=.*|Exec=python3 ${REPO}/main.py|" \
  > "$TARGET"
chmod +x "$TARGET"

# Refresh the desktop database so KDE / GNOME pick it up immediately.
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$TARGET_DIR" >/dev/null
fi

echo "Installed: $TARGET"
echo "Icon:      $REPO/assets/loot.svg"
