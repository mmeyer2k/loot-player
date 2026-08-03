.PHONY: run test install-desktop clean appimage appimage-clean appimage-sweep

# xcb is required for libVLC's set_xwindow on KDE Wayland and a no-op on X11
# (xcb is X11's native default), so set it unconditionally.
run:
	QT_QPA_PLATFORM=xcb python3 main.py

test:
	python3 -m pytest tests/ -v

install-desktop:
	./packaging/install-desktop.sh

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

# Prefer podman; docker works too. Override with CONTAINER_ENGINE=docker.
#
# Only rootless podman is exercised. It maps container root to the invoking
# user, so build/ and dist/ come out owned normally. Rootful docker does not,
# and leaves both owned by root, which makes `make appimage-clean` fail until
# you sudo it. Passing --user does not fix that: the script gates its apt step
# on being root, so a non-root container skips installing build dependencies
# and then dies at the first curl, which the base image does not ship. A
# blanket chown inside the container is worse, because under rootless podman
# it would map the files onto a subuid the user cannot touch.
CONTAINER_ENGINE ?= $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
APPIMAGE_IMAGE ?= docker.io/library/ubuntu:22.04

# Built in ubuntu:22.04 because PyQt6's only x86_64 wheel is manylinux_2_34,
# so glibc 2.34 is the floor. Building on the host would target its glibc.
appimage:
	@test -n "$(CONTAINER_ENGINE)" || { echo "need podman or docker"; exit 1; }
	$(CONTAINER_ENGINE) run --rm -v "$(CURDIR)":/src:Z -w /src \
	  $(APPIMAGE_IMAGE) /src/packaging/build-appimage.sh

appimage-clean:
	rm -rf build dist

# Requires a build (see `appimage`, above) and VLC installed on this machine
# (`apt install vlc` / `dnf install vlc` / `pacman -S vlc`). Same script CI
# runs after the --version smoke test; see packaging/vlc-plugin-sweep.py for
# what class of bug this catches and why --version can't. Running it here is
# worth more than the 22.04 run in CI: the bug only shows when the host's
# libraries differ from the bundled ones, and this machine is newer than the
# build container.
#
# `ls -t` for newest, not `ls` for alphabetically first. Two builds in dist/
# and the old one sorts ahead of the new one, so you would sweep the stale
# artifact and believe you had checked the fresh one. Matches
# find_default_appimage() in the sweep script.
appimage-sweep:
	@appimage="$$(ls -t dist/loot-*-x86_64.AppImage 2>/dev/null | head -1)"; \
	if [ -z "$$appimage" ]; then \
	  echo "no AppImage in dist/; run 'make appimage' first" >&2; \
	  exit 1; \
	fi; \
	python3 packaging/vlc-plugin-sweep.py "$$appimage"
