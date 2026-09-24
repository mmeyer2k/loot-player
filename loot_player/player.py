from __future__ import annotations
import ctypes
import sys

import vlc
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import QFrame


# libVLC 3's set_xwindow sets the player's "window" variable to
# "embed-xid,any". The ",any" means that if embedding into our X window fails
# (the drawable is still held by the previous video's output, or the XID is
# bad), libVLC quietly opens its own top-level window and the video pops out.
# There's no public API to drop the fallback, so set the variable directly
# through libvlccore. A libvlc_media_player_t starts with its vlc_object_t
# header, so the player handle can be passed as the object.
_VLC_VAR_STRING = 0x0040


class _VlcValue(ctypes.Union):
    _fields_ = [("i_int", ctypes.c_int64), ("psz_string", ctypes.c_char_p)]


def _embed_only(player) -> bool:
    """Restrict the player to the embedded window. False if unsupported."""
    try:
        fn = vlc.dll.var_SetChecked
    except AttributeError:
        return False
    fn.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, _VlcValue]
    fn.restype = ctypes.c_int
    handle = ctypes.cast(player._as_parameter_, ctypes.c_void_p)
    return fn(handle, b"window", _VLC_VAR_STRING,
              _VlcValue(psz_string=b"embed-xid")) == 0


class VlcWidget(QFrame):
    double_clicked = pyqtSignal()
    # Emitted from VLC's worker thread (queued — connect normally in Qt).
    loading_started = pyqtSignal()
    playback_started = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), Qt.GlobalColor.black)
        self.setPalette(pal)
        self.setMinimumSize(QSize(480, 270))

        self.instance = vlc.Instance(["--no-video-title-show", "--quiet"])
        self.player = self.instance.media_player_new()
        em = self.player.event_manager()
        em.event_attach(vlc.EventType.MediaPlayerOpening,
                        lambda _ev: self.loading_started.emit())
        em.event_attach(vlc.EventType.MediaPlayerBuffering,
                        lambda _ev: self.loading_started.emit())
        em.event_attach(vlc.EventType.MediaPlayerPlaying,
                        lambda _ev: self.playback_started.emit())

    def attach(self):
        wid = int(self.winId())
        if sys.platform.startswith("linux"):
            self.player.set_xwindow(wid)
            _embed_only(self.player)
        elif sys.platform == "win32":
            self.player.set_hwnd(wid)
        elif sys.platform == "darwin":
            self.player.set_nsobject(wid)

    def play_path(self, path: str):
        media = self.instance.media_new(path)
        # set_media alone keeps the previous video output alive for reuse,
        # still holding our X window. stop() tears it down so the next
        # output can claim the window instead of finding it busy.
        self.player.stop()
        self.player.set_media(media)
        self.player.play()

    def toggle_pause(self):
        self.player.pause()

    def stop(self):
        self.player.stop()

    def set_renderer(self, item) -> int:
        """Route playback to a renderer (e.g. Chromecast). Pass None to clear.

        Must be called while stopped; libVLC ignores it mid-playback."""
        return self.player.set_renderer(item)

    def set_position(self, frac: float):
        self.player.set_position(max(0.0, min(1.0, frac)))

    def position(self) -> float:
        return float(self.player.get_position() or 0.0)

    def is_ended(self) -> bool:
        return self.player.get_state() == vlc.State.Ended

    def is_playing(self) -> bool:
        return self.player.get_state() == vlc.State.Playing

    def is_buffering(self) -> bool:
        """True while libVLC is opening or buffering the current media."""
        return self.player.get_state() in (vlc.State.Opening, vlc.State.Buffering)

    def set_volume(self, v: int) -> None:
        self.player.audio_set_volume(int(v))

    def get_volume(self) -> int:
        return int(self.player.audio_get_volume() or 0)

    def set_mute(self, m: bool) -> None:
        self.player.audio_set_mute(bool(m))

    def get_mute(self) -> bool:
        # audio_get_mute returns -1 when no audio output exists yet; treat
        # that as "not muted" rather than letting bool(-1) report True.
        return self.player.audio_get_mute() == 1

    def get_time(self) -> int:
        """Current playback time in milliseconds; -1 if unknown."""
        return int(self.player.get_time() if self.player.get_time() is not None else -1)

    def get_length(self) -> int:
        """Total length in milliseconds; -1 if unknown."""
        return int(self.player.get_length() if self.player.get_length() is not None else -1)

    def mouseDoubleClickEvent(self, ev):
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(ev)
