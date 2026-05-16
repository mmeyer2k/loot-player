from __future__ import annotations
import ctypes
from threading import Lock
from typing import Optional

import vlc
from PyQt6.QtCore import QObject, pyqtSignal


class CastController(QObject):
    """Discovers and manages Chromecast renderers via libVLC.

    The service name for renderer discovery isn't portable across libVLC
    builds: upstream uses ``microdns_renderer`` (mDNS via libmicrodns), but
    Ubuntu/Debian's vlc-plugin-base ships an Avahi-backed module registered
    as ``mdns_renderer``/``avahi_renderer`` instead. We try a priority list.

    The python-vlc binding doesn't expose the renderer item pointer inside
    the discoverer event payload (the union sub-struct fields are empty), so
    we read the pointer directly from the union's memory via ctypes — the C
    struct lays the pointer at offset 0 of the union.
    """

    SERVICE_CANDIDATES = ("microdns_renderer", "mdns_renderer", "avahi_renderer")

    devices_changed = pyqtSignal()

    def __init__(self, instance: vlc.Instance, parent=None):
        super().__init__(parent)
        self._instance = instance
        self._discoverer: Optional[vlc.RendererDiscoverer] = None
        self._lock = Lock()
        self._items: dict[int, vlc.Renderer] = {}
        self._seen_keys: set[tuple] = set()
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    def devices(self) -> list[vlc.Renderer]:
        with self._lock:
            return list(self._items.values())

    def start(self) -> bool:
        if self._discoverer is not None:
            return True
        for name in self.SERVICE_CANDIDATES:
            try:
                d = self._instance.renderer_discoverer_new(name)
            except Exception:
                d = None
            if d is None:
                continue
            em = d.event_manager()
            em.event_attach(vlc.EventType.RendererDiscovererItemAdded, self._on_added)
            em.event_attach(vlc.EventType.RendererDiscovererItemDeleted, self._on_removed)
            try:
                rc = d.start()
            except Exception:
                rc = -1
            if rc == 0:
                self._discoverer = d
                return True
            try:
                d.release()
            except Exception:
                pass
        self._available = False
        return False

    def stop(self):
        if self._discoverer is not None:
            try:
                self._discoverer.stop()
            except Exception:
                pass
            self._discoverer = None
        with self._lock:
            for item in self._items.values():
                try:
                    item.release()
                except Exception:
                    pass
            self._items.clear()
            self._seen_keys.clear()

    @staticmethod
    def _extract_ptr(event) -> int:
        try:
            return ctypes.c_void_p.from_address(ctypes.addressof(event.u)).value or 0
        except Exception:
            return 0

    def _on_added(self, event):
        ptr = self._extract_ptr(event)
        if not ptr:
            return
        try:
            item = vlc.Renderer(ptr)
        except Exception:
            return
        if item is None:
            return
        try:
            key = (item.name(), item.type())
        except Exception:
            key = (None, None)
        try:
            item.hold()
        except Exception:
            pass
        with self._lock:
            if key in self._seen_keys:
                # mDNS double-announces (IPv4 + IPv6) — keep only the first.
                try:
                    item.release()
                except Exception:
                    pass
                return
            self._seen_keys.add(key)
            self._items[ptr] = item
        self.devices_changed.emit()

    def _on_removed(self, event):
        ptr = self._extract_ptr(event)
        if not ptr:
            return
        with self._lock:
            item = self._items.pop(ptr, None)
            if item is not None:
                try:
                    key = (item.name(), item.type())
                    self._seen_keys.discard(key)
                except Exception:
                    pass
        if item is not None:
            try:
                item.release()
            except Exception:
                pass
        self.devices_changed.emit()
