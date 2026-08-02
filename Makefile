.PHONY: run test install-desktop clean appimage appimage-clean

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
