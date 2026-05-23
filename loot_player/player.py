from __future__ import annotations
import sys

import vlc
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import QFrame


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
        if self.instance is None:
            raise RuntimeError(
                "Could not initialize libVLC. VLC's libraries or plugins are "
                "missing or unloadable. If running from source, install VLC "
                "(e.g. `sudo apt install vlc`)."
            )
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
        elif sys.platform == "win32":
            self.player.set_hwnd(wid)
        elif sys.platform == "darwin":
            self.player.set_nsobject(wid)

    def play_path(self, path: str):
        media = self.instance.media_new(path)
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
