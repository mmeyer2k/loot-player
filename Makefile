.PHONY: run test install-desktop clean

# libVLC embeds video via an X11 window id (set_xwindow), so Qt must run on the
# xcb platform. xcb is X11's native default and works under XWayland, so force
# it unconditionally (a no-op on plain X11); honor an explicit override.
run:
	QT_QPA_PLATFORM=$${QT_QPA_PLATFORM:-xcb} python3 main.py

test:
	python3 -m pytest tests/ -v

install-desktop:
	./packaging/install-desktop.sh

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
