.PHONY: run test install-desktop clean

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
