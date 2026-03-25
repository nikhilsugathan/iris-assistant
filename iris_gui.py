from __future__ import annotations

import html
import math
import os
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from config import Config
from core.engine import IRISEngine
from core.visual_identity import apply_windows_app_user_model_id, create_app_icon


class BackdropWidget(QtWidgets.QWidget):
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        rect = self.rect()
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QtGui.QColor("#F6F2E8"))
        gradient.setColorAt(0.45, QtGui.QColor("#D7E5E2"))
        gradient.setColorAt(1.0, QtGui.QColor("#12202A"))
        painter.fillRect(rect, gradient)

        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 24), 1))
        step = 36
        for x in range(0, rect.width(), step):
            painter.drawLine(x, 0, x, rect.height())
        for y in range(0, rect.height(), step):
            painter.drawLine(0, y, rect.width(), y)

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(255, 255, 255, 22))
        painter.drawEllipse(rect.width() - 260, -40, 300, 300)
        painter.drawEllipse(-110, rect.height() - 280, 320, 320)


class OrbWidget(QtWidgets.QWidget):
    activated = QtCore.Signal()
    secondary_activated = QtCore.Signal()

    COLORS = {
        "idle": ("#0E4E86", "#7FDBFF"),
        "standby": ("#1079A5", "#C4F4FF"),
        "listening": ("#1195D4", "#CFF9FF"),
        "thinking": ("#1769C4", "#98D5FF"),
        "speaking": ("#1AB7D7", "#E7FDFF"),
        "error": ("#7E2E58", "#FF98B6"),
    }

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self._phase = 0.0
        self._state = "idle"
        self._overdrive = False
        self._compact = compact
        self._base_radius = 70 if compact else 88
        self.setMinimumSize(220, 220) if compact else self.setMinimumSize(340, 340)
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    def set_state(self, state: str):
        self._state = state if state in self.COLORS else "idle"
        self.update()

    def set_overdrive(self, active: bool):
        self._overdrive = bool(active)
        self.update()

    def _tick(self):
        speed = {
            "idle": 0.02,
            "standby": 0.028,
            "listening": 0.05,
            "thinking": 0.09,
            "speaking": 0.07,
            "error": 0.12,
        }.get(self._state, 0.02)
        if self._overdrive:
            speed += 0.018
        self._phase += speed
        self.update()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.activated.emit()
        elif event.button() == QtCore.Qt.RightButton:
            self.secondary_activated.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.secondary_activated.emit()
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(12, 12, -12, -12)
        center = rect.center()
        w = rect.width()
        h = rect.height()

        primary_hex, accent_hex = self.COLORS.get(self._state, self.COLORS["idle"])
        primary = QtGui.QColor(primary_hex)
        accent = QtGui.QColor(accent_hex)

        pulse = (math.sin(self._phase * 2.2) + 1.0) / 2.0
        radius = self._base_radius + pulse * (14 if self._state != "idle" else 8)
        if self._overdrive:
            radius += 4

        halo = QtGui.QRadialGradient(center, radius * 2.15)
        halo.setColorAt(0.0, QtGui.QColor(accent.red(), accent.green(), accent.blue(), 145))
        halo.setColorAt(0.34, QtGui.QColor(primary.red(), primary.green(), primary.blue(), 110))
        halo.setColorAt(1.0, QtGui.QColor(primary.red(), primary.green(), primary.blue(), 0))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(halo))
        painter.drawEllipse(center, radius * 2.15, radius * 2.15)

        core = QtGui.QRadialGradient(center, radius)
        core.setColorAt(0.0, QtGui.QColor("#F6FEFF"))
        core.setColorAt(0.24, QtGui.QColor(210, 248, 255, 250))
        core.setColorAt(0.56, QtGui.QColor(accent.red(), accent.green(), accent.blue(), 220))
        core.setColorAt(1.0, QtGui.QColor(primary.red(), primary.green(), primary.blue(), 240))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(core))
        painter.drawEllipse(center, radius, radius)

        sheen = QtGui.QRadialGradient(
            QtCore.QPointF(center.x() - radius * 0.32, center.y() - radius * 0.42),
            radius * 0.82,
        )
        sheen.setColorAt(0.0, QtGui.QColor(255, 255, 255, 165))
        sheen.setColorAt(0.55, QtGui.QColor(255, 255, 255, 36))
        sheen.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))
        painter.setBrush(sheen)
        painter.drawEllipse(
            QtCore.QRectF(center.x() - radius * 0.78, center.y() - radius * 0.95, radius * 1.2, radius * 0.98)
        )

        grid_pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 88), 1.2)
        painter.setPen(grid_pen)
        painter.setBrush(QtCore.Qt.NoBrush)

        painter.save()
        painter.translate(center)
        painter.rotate(math.sin(self._phase * 0.75) * 18)
        for scale in (1.0, 0.72, 0.44):
            painter.drawEllipse(
                QtCore.QRectF(-radius * scale, -radius * 0.94, radius * 2 * scale, radius * 1.88)
            )
        painter.restore()

        for latitude in (-0.62, -0.28, 0.0, 0.28, 0.62):
            band_height = max(radius * 0.08, radius * (0.24 - abs(latitude) * 0.15))
            painter.drawEllipse(
                QtCore.QRectF(
                    center.x() - radius * 0.88,
                    center.y() + latitude * radius - band_height / 2,
                    radius * 1.76,
                    band_height,
                )
            )

        painter.setPen(QtGui.QPen(QtGui.QColor(accent.red(), accent.green(), accent.blue(), 128), 2.0))
        for idx, orbit_scale in enumerate((1.24, 1.52)):
            orbit_rect = QtCore.QRectF(
                center.x() - radius * orbit_scale,
                center.y() - radius * orbit_scale * 0.58,
                radius * orbit_scale * 2,
                radius * orbit_scale * 1.16,
            )
            start = int((self._phase * 135 + idx * 140) * 16)
            span = int((150 + pulse * 80) * 16)
            painter.drawArc(orbit_rect, start, span)

        for idx in range(3):
            angle = self._phase * (1.3 + idx * 0.18) + idx * 2.15
            x = center.x() + math.cos(angle) * radius * (1.15 + idx * 0.08)
            y = center.y() + math.sin(angle) * radius * 0.52
            dot_color = QtGui.QColor(255, 255, 255, 210 if idx == 0 else 145)
            painter.setBrush(dot_color)
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawEllipse(QtCore.QPointF(x, y), 3.4 + idx, 3.4 + idx)

        if self._overdrive:
            overdrive_pen = QtGui.QPen(QtGui.QColor(223, 251, 255, 215), 2.6)
            painter.setPen(overdrive_pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(center, radius * 1.14, radius * 1.14)
            painter.drawEllipse(center, radius * 1.32, radius * 1.32)

        label_font = QtGui.QFont("Bahnschrift SemiBold", 12 if not self._compact else 11)
        painter.setFont(label_font)
        painter.setPen(QtGui.QColor("#F3FDFF"))
        painter.drawText(
            QtCore.QRectF(center.x() - 85, center.y() - 18, 170, 36),
            QtCore.Qt.AlignCenter,
            Config.PUBLIC_NAME.upper(),
        )

        if not self._compact:
            state_font = QtGui.QFont("Segoe UI Semibold", 10)
            painter.setFont(state_font)
            painter.setPen(QtGui.QColor(235, 250, 255, 188))
            painter.drawText(
                QtCore.QRectF(0, h - 42, w, 24),
                QtCore.Qt.AlignCenter,
                f"{self._state.upper()}{' // OVERDRIVE' if self._overdrive else ''}",
            )


class FloatingOrbWindow(QtWidgets.QWidget):
    request_dashboard = QtCore.Signal()
    position_changed = QtCore.Signal(int, int)

    def __init__(self, app_icon: QtGui.QIcon, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{Config.PUBLIC_NAME} Orb")
        self.setWindowIcon(app_icon)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.resize(250, 270)
        self._drag_offset = None
        self._current_state = "idle"
        self._overdrive = False

        wrapper = QtWidgets.QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)

        layout = QtWidgets.QVBoxLayout()
        wrapper.addLayout(layout)
        layout.setContentsMargins(10, 6, 10, 10)
        layout.setSpacing(6)

        self.orb = OrbWidget(compact=True)
        self.orb.secondary_activated.connect(self.request_dashboard.emit)
        layout.addWidget(self.orb, alignment=QtCore.Qt.AlignCenter)

        self.state_label = QtWidgets.QLabel("VOICE STANDBY")
        self.state_label.setAlignment(QtCore.Qt.AlignCenter)
        self.state_label.setStyleSheet("color: rgba(225, 248, 255, 0.90); font-size: 11px; letter-spacing: 2px;")
        layout.addWidget(self.state_label)

        self.hint_label = QtWidgets.QLabel("Say Iris. Double-click for chat.")
        self.hint_label.setWordWrap(True)
        self.hint_label.setAlignment(QtCore.Qt.AlignCenter)
        self.hint_label.setStyleSheet("color: rgba(225, 248, 255, 0.62); font-size: 11px;")
        layout.addWidget(self.hint_label)

    def set_state(self, state: str):
        self._current_state = state
        self.orb.set_state(state)
        self._refresh_labels()

    def set_overdrive(self, active: bool):
        self._overdrive = bool(active)
        self.orb.set_overdrive(active)
        self._refresh_labels()

    def _refresh_labels(self):
        prefix = "OVERDRIVE // " if self._overdrive else ""
        label_map = {
            "standby": "VOICE STANDBY",
            "idle": "IDLE",
            "listening": "LISTENING",
            "thinking": "THINKING",
            "speaking": "SPEAKING",
            "error": "ERROR",
        }
        self.state_label.setText(f"{prefix}{label_map.get(self._current_state, self._current_state.upper())}")
        if self._overdrive:
            self.hint_label.setText("Critical-focus mode is active.")
        else:
            self.hint_label.setText("Say Iris. Double-click for chat.")

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & QtCore.Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        self.position_changed.emit(self.x(), self.y())
        super().mouseReleaseEvent(event)


class AppSignals(QtCore.QObject):
    voice_state = QtCore.Signal(str)


class EngineWorker(QtCore.QThread):
    completed = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, engine: IRISEngine, mode: str, text: str = ""):
        super().__init__()
        self.engine = engine
        self.mode = mode
        self.text = text

    def run(self):
        try:
            if self.mode == "listen":
                captured = self.engine.listen_for_voice_command()
                if not captured:
                    self.completed.emit(
                        {
                            "captured": "",
                            "result": None,
                            "mode": "listen",
                            "listen_feedback": self.engine.voice.describe_last_listen_feedback(),
                            "listen_feedback_short": self.engine.voice.short_last_listen_feedback(),
                        }
                    )
                    return
                ack_token = self.engine.begin_slow_voice_ack(captured, enabled=True)
                try:
                    result = self.engine.process_user_input(captured, speak_response=False, input_source="voice")
                finally:
                    self.engine.finish_slow_voice_ack(ack_token, stop_audio=True)
                self.completed.emit({"captured": captured, "result": result, "mode": "listen"})
                return

            result = self.engine.process_user_input(self.text, speak_response=False, input_source="text")
            self.completed.emit({"captured": self.text, "result": result, "mode": "process"})
        except Exception as exc:
            self.failed.emit(str(exc))


class VoiceStandbyWorker(QtCore.QThread):
    event = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, engine: IRISEngine, should_pause):
        super().__init__()
        self.engine = engine
        self.should_pause = should_pause

    def run(self):
        try:
            if not getattr(self.engine.voice, "mic_ready", False):
                self.event.emit(
                    {
                        "type": "feedback",
                        "text": self.engine.voice.describe_last_listen_feedback(),
                    }
                )
                return

            follow_up_turns = max(1, int(getattr(Config, "VOICE_FOLLOWUP_TURNS", 4)))

            while not self.isInterruptionRequested():
                if self.should_pause():
                    self.msleep(180)
                    continue

                heard_text = self.engine.voice.listen_for_wake()
                normalized_heard = self.engine.normalize_wake_transcript(heard_text)
                if self.isInterruptionRequested():
                    break
                if not normalized_heard or not self.engine.contains_wake_word(normalized_heard):
                    continue

                stripped = self.engine.strip_wake_word(normalized_heard)
                if stripped:
                    if not self._handle_command(normalized_heard, stripped, follow_up_turns):
                        break
                    continue

                ack = getattr(Config, "WAKE_ACKNOWLEDGEMENT", "I'm here.")
                self.event.emit({"type": "ack", "text": ack})
                quick_ack = getattr(self.engine.voice, "speak_quick_ack", None)
                if callable(quick_ack):
                    quick_ack(ack)
                else:
                    self.engine.voice.speak(ack)

                if self.isInterruptionRequested():
                    break

                command = self.engine.listen_for_voice_command()
                if not command:
                    if getattr(self.engine.voice, "last_listen_status", "") == "transcription_failed":
                        self.event.emit(
                            {
                                "type": "feedback",
                                "text": self.engine.voice.describe_last_listen_feedback(),
                            }
                        )
                    continue

                if not self._handle_command(command, command, follow_up_turns):
                    break
        except Exception as exc:
            self.failed.emit(str(exc))

    def _handle_command(self, display_text: str, command_text: str, follow_up_turns: int) -> bool:
        self.event.emit({"type": "heard", "text": display_text})
        ack_token = self.engine.begin_slow_voice_ack(command_text, enabled=True)
        try:
            result = self.engine.process_user_input(command_text, speak_response=False, input_source="voice")
        finally:
            self.engine.finish_slow_voice_ack(ack_token, stop_audio=True)
        self.event.emit({"type": "result", "result": result})

        if result.should_exit:
            if result.response and not getattr(result, "exit_immediately", False):
                self.engine.voice.speak(result.response)
            else:
                self.engine.voice.stop_speaking()
            self.event.emit({"type": "shutdown", "immediate": getattr(result, "exit_immediately", False)})
            return False
        if result.response:
            self.engine.voice.speak(result.response)

        for _ in range(follow_up_turns):
            if self.isInterruptionRequested() or self.should_pause():
                return True

            follow_up = self.engine.listen_for_voice_command()
            if not follow_up:
                break
            if self.engine.should_end_followup(follow_up):
                break

            self.event.emit({"type": "heard", "text": follow_up})
            ack_token = self.engine.begin_slow_voice_ack(follow_up, enabled=True)
            try:
                result = self.engine.process_user_input(follow_up, speak_response=False, input_source="voice")
            finally:
                self.engine.finish_slow_voice_ack(ack_token, stop_audio=True)
            self.event.emit({"type": "result", "result": result})
            if result.should_exit:
                if result.response and not getattr(result, "exit_immediately", False):
                    self.engine.voice.speak(result.response)
                else:
                    self.engine.voice.stop_speaking()
                self.event.emit({"type": "shutdown", "immediate": getattr(result, "exit_immediately", False)})
                return False
            if result.response:
                self.engine.voice.speak(result.response)

        return True


class IrisWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        engine: IRISEngine | None = None,
        start_voice_standby: bool = True,
        enable_tray: bool = True,
    ):
        super().__init__()
        self.settings = QtCore.QSettings("Aletheia", "IrisDesktop")
        self.engine = engine or IRISEngine(text_mode=False)
        self._start_voice_standby_enabled = bool(start_voice_standby)
        self._tray_enabled = bool(enable_tray)
        self.signals = AppSignals()
        self.engine.voice.set_state_callback(self.signals.voice_state.emit)
        self.signals.voice_state.connect(self.on_voice_state)
        self.worker = None
        self.wake_worker = None
        self.busy = False
        self._quitting = False
        self._sticky_footer = False
        self._startup_enabled = self._has_startup_shortcut()
        self._first_tray_hint_shown = self.settings.value("tray_hint_shown", False, type=bool)
        self._startup_sequence_completed = False
        self._mode_banner_base = "SAY IRIS ANY TIME"
        self.app_icon = create_app_icon()
        self.setWindowIcon(self.app_icon)

        self.setWindowTitle(Config.PUBLIC_NAME.upper())
        self.resize(720, 900)
        self.setMinimumSize(560, 760)

        self._build_ui()
        if self._tray_enabled:
            self._setup_tray()
        else:
            self.tray = None
        self._setup_floating_orb()
        self.refresh_status()
        self._queue_startup_sequence()

        if self.settings.value("floating_mode", False, type=bool):
            self.set_floating_mode(True, announce=False)

    def _setup_tray(self):
        self.tray = None
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray = QtWidgets.QSystemTrayIcon(self.app_icon, self)
        self.tray.setToolTip(Config.PUBLIC_NAME)
        self.tray.activated.connect(self._on_tray_activated)

        menu = QtWidgets.QMenu(self)
        show_action = menu.addAction("Show Dashboard")
        show_action.triggered.connect(self.show_dashboard)

        self.floating_action = menu.addAction("Floating Orb Mode")
        self.floating_action.setCheckable(True)
        self.floating_action.triggered.connect(lambda checked: self.set_floating_mode(checked))

        self.overdrive_action = menu.addAction("Enable Overdrive")
        self.overdrive_action.setCheckable(True)
        self.overdrive_action.triggered.connect(lambda _checked: self.toggle_overdrive())

        self.startup_action = menu.addAction("Launch At Sign-In")
        self.startup_action.setCheckable(True)
        self.startup_action.setChecked(self._startup_enabled)
        self.startup_action.triggered.connect(self.set_launch_at_login)

        menu.addSeparator()
        quit_action = menu.addAction("Quit Iris")
        quit_action.triggered.connect(self.quit_app)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def _setup_floating_orb(self):
        self.floating_window = FloatingOrbWindow(self.app_icon)
        self.floating_window.request_dashboard.connect(self.show_dashboard)
        self.floating_window.position_changed.connect(self._save_floating_orb_position)
        self._restore_floating_orb_position()

    def _start_voice_standby(self):
        if self.wake_worker and self.wake_worker.isRunning():
            return
        self.wake_worker = VoiceStandbyWorker(self.engine, self._voice_standby_paused)
        self.wake_worker.event.connect(self.on_standby_event)
        self.wake_worker.failed.connect(self.on_worker_failed)
        self.wake_worker.start()

    def _queue_startup_sequence(self):
        delay_ms = max(0, int(getattr(Config, "STARTUP_GREETING_DELAY_MS", 0)))
        QtCore.QTimer.singleShot(delay_ms, self._complete_startup_sequence)

    def _complete_startup_sequence(self):
        if self._startup_sequence_completed or self._quitting:
            return
        self._startup_sequence_completed = True

        greeting = ""
        greeting_thread = None
        if bool(getattr(Config, "STARTUP_GREETING_ENABLED", True)):
            try:
                greeting = (self.engine.brain.startup_greeting() or "").strip()
            except Exception:
                greeting = ""

        if greeting:
            self.append_message(Config.PUBLIC_NAME, greeting, "assistant")
            self.footer.setText(greeting)
            if self.tray and not self.isVisible():
                self.tray.showMessage(Config.PUBLIC_NAME, greeting, self.app_icon, 5000)
            if getattr(self.engine.voice, "audio_ready", False):
                greeting_thread = self.engine.voice.speak_background(greeting)

        if self._start_voice_standby_enabled:
            self._start_voice_standby_after_greeting(greeting_thread)

    def _start_voice_standby_after_greeting(self, greeting_thread=None):
        if self._quitting or not self._start_voice_standby_enabled:
            return

        if greeting_thread is not None and getattr(greeting_thread, "is_alive", None):
            if greeting_thread.is_alive():
                QtCore.QTimer.singleShot(
                    120,
                    lambda thread=greeting_thread: self._start_voice_standby_after_greeting(thread),
                )
                return

        delay_ms = max(0, int(getattr(Config, "STARTUP_LISTEN_AFTER_GREETING_MS", 180)))
        QtCore.QTimer.singleShot(delay_ms, self._start_voice_standby)

    def _stop_voice_standby(self):
        if not self.wake_worker:
            return
        self.wake_worker.requestInterruption()
        if not self.wake_worker.wait(5500):
            self.wake_worker.terminate()
            self.wake_worker.wait(500)
        self.wake_worker = None

    def _voice_standby_paused(self):
        return bool(self.busy or self._quitting)

    def _build_ui(self):
        self.setStyleSheet(
            """
            QWidget {
                color: #F7F3EA;
                font-family: 'Segoe UI';
            }
            QLabel#Title {
                font-family: 'Bahnschrift SemiBold';
                font-size: 30px;
                color: #F7F3EA;
            }
            QLabel#SubTitle {
                font-size: 12px;
                color: rgba(247, 243, 234, 0.62);
                letter-spacing: 1px;
            }
            QFrame#GlassPanel {
                background: rgba(7, 16, 24, 0.72);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 34px;
            }
            QTextBrowser {
                background: transparent;
                border: none;
                color: #F7F3EA;
                font-size: 14px;
                selection-background-color: rgba(244, 176, 102, 0.35);
            }
            QLineEdit {
                background: rgba(255, 255, 255, 0.12);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 16px;
                padding: 14px 16px;
                font-size: 14px;
                color: #F7F3EA;
            }
            QPushButton {
                border-radius: 16px;
                padding: 12px 18px;
                font-family: 'Bahnschrift SemiBold';
                font-size: 12px;
            }
            QPushButton#PrimaryButton {
                background: #D9A25F;
                color: #12202A;
                border: 1px solid rgba(255, 255, 255, 0.12);
            }
            QPushButton#PrimaryButton:hover {
                background: #E8B776;
            }
            QPushButton#SecondaryButton {
                background: rgba(126, 219, 255, 0.14);
                color: #E7FBFF;
                border: 1px solid rgba(126, 219, 255, 0.28);
            }
            QPushButton#SecondaryButton:hover {
                background: rgba(126, 219, 255, 0.24);
            }
            QLabel#Chip {
                border-radius: 13px;
                padding: 7px 12px;
                background: rgba(255, 255, 255, 0.09);
                color: #F7F3EA;
                font-size: 11px;
            }
            QLabel#StatePill {
                border-radius: 14px;
                padding: 8px 16px;
                background: rgba(244, 176, 102, 0.14);
                color: #F7E5C8;
                font-family: 'Bahnschrift SemiBold';
                font-size: 11px;
                letter-spacing: 2px;
            }
            QLabel#DiagnosticsChip {
                border-radius: 18px;
                padding: 10px 14px;
                background: rgba(255, 255, 255, 0.07);
                color: rgba(231, 251, 255, 0.84);
                font-size: 11px;
                line-height: 1.4;
            }
            """
        )

        backdrop = BackdropWidget()
        self.setCentralWidget(backdrop)

        root = QtWidgets.QVBoxLayout(backdrop)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(0)

        panel = QtWidgets.QFrame()
        panel.setObjectName("GlassPanel")
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        title = QtWidgets.QLabel(Config.PUBLIC_NAME.upper())
        title.setObjectName("Title")
        title.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel("VOICE STANDBY ONLINE")
        subtitle.setObjectName("SubTitle")
        subtitle.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(subtitle)

        self.mode_label = QtWidgets.QLabel("SAY IRIS ANY TIME")
        self.mode_label.setObjectName("Chip")
        self.mode_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.mode_label, alignment=QtCore.Qt.AlignCenter)

        self.orb = OrbWidget()
        self.orb.secondary_activated.connect(self.open_floating_orb)
        layout.addWidget(self.orb, alignment=QtCore.Qt.AlignCenter)

        self.state_pill = QtWidgets.QLabel("VOICE STANDBY")
        self.state_pill.setObjectName("StatePill")
        self.state_pill.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.state_pill, alignment=QtCore.Qt.AlignCenter)

        self.overdrive_button = QtWidgets.QPushButton("Enable Overdrive")
        self.overdrive_button.setObjectName("SecondaryButton")
        self.overdrive_button.clicked.connect(self.toggle_overdrive)
        layout.addWidget(self.overdrive_button, alignment=QtCore.Qt.AlignCenter)

        orbit_hint = QtWidgets.QLabel("Double-click the orb to float it. Voice standby stays active even when hidden.")
        orbit_hint.setWordWrap(True)
        orbit_hint.setAlignment(QtCore.Qt.AlignCenter)
        orbit_hint.setStyleSheet("color: rgba(247, 243, 234, 0.58); font-size: 12px;")
        layout.addWidget(orbit_hint)

        self.diagnostics_label = QtWidgets.QLabel("")
        self.diagnostics_label.setObjectName("DiagnosticsChip")
        self.diagnostics_label.setWordWrap(True)
        self.diagnostics_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.diagnostics_label)

        self.transcript = QtWidgets.QTextBrowser()
        self.transcript.setOpenExternalLinks(False)
        self.transcript.document().setDocumentMargin(18)
        layout.addWidget(self.transcript, stretch=1)

        input_row = QtWidgets.QHBoxLayout()
        input_row.setSpacing(12)
        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText("Type to chat while voice standby stays active...")
        self.input.returnPressed.connect(self.on_send)
        input_row.addWidget(self.input, stretch=1)

        self.send_button = QtWidgets.QPushButton("Send")
        self.send_button.setObjectName("PrimaryButton")
        self.send_button.clicked.connect(self.on_send)
        input_row.addWidget(self.send_button)
        layout.addLayout(input_row)

        self.footer = QtWidgets.QLabel("Voice standby online. Say Iris at any time.")
        self.footer.setStyleSheet("color: rgba(247, 243, 234, 0.72); font-size: 12px;")
        self.footer.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.footer)

        root.addWidget(panel)

        self.append_message(
            "SYSTEM",
            "Voice standby online. Say Iris any time.",
            "system",
        )
        self._set_mode_banner("SAY IRIS ANY TIME")

    def append_message(self, label: str, text: str, kind: str):
        if not text:
            return

        palettes = {
            "user": ("rgba(247, 243, 234, 0.14)", "#F7F3EA", "#D7E5E2"),
            "assistant": ("rgba(35, 68, 82, 0.72)", "#F7F3EA", "#F4B066"),
            "system": ("rgba(217, 162, 95, 0.16)", "#10202A", "#D9A25F"),
        }
        bg, fg, accent = palettes.get(kind, palettes["assistant"])

        message_html = f"""
        <div style="margin: 0 0 14px 0; padding: 16px 18px; border-radius: 18px; background:{bg};">
            <div style="font-family: Bahnschrift SemiBold; letter-spacing: 1px; color:{accent}; font-size:11px; margin-bottom:6px;">
                {label.upper()}
            </div>
            <div style="color:{fg}; line-height:1.6; font-size:14px; white-space:pre-wrap;">
                {html.escape(text)}
            </div>
        </div>
        """
        self.transcript.append(message_html)
        self.transcript.verticalScrollBar().setValue(self.transcript.verticalScrollBar().maximum())

    def on_voice_state(self, state: str):
        self.orb.set_state(state)
        self.floating_window.set_state(state)
        state_pill_map = {
            "standby": "VOICE STANDBY",
            "idle": "IDLE",
            "listening": "LISTENING",
            "thinking": "THINKING",
            "speaking": "SPEAKING",
            "error": "ERROR",
        }
        self.state_pill.setText(state_pill_map.get(state, state.upper()))
        footer_map = {
            "standby": "Voice standby online. Say Iris at any time.",
            "idle": "Standing by.",
            "listening": "Listening for 'Iris' or your command.",
            "speaking": "Iris is speaking.",
            "thinking": "Thinking through the request...",
        }
        if state == "listening" or not self._sticky_footer:
            self.footer.setText(footer_map.get(state, self.footer.text()))
        self._apply_engine_visuals()
        if self.tray:
            self.tray.setToolTip(f"{Config.PUBLIC_NAME} // {state.upper()}")

    def set_busy(self, busy: bool, footer: str = ""):
        self.busy = busy
        self.send_button.setEnabled(not busy)
        self.input.setEnabled(not busy)
        if footer:
            self.footer.setText(footer)

    def on_send(self):
        if self.busy:
            return
        text = self.input.text().strip()
        if not text:
            return
        self._sticky_footer = False
        self.input.clear()
        self.append_message("You", text, "user")
        self.orb.set_state("thinking")
        self.state_pill.setText("THINKING")
        self._apply_engine_visuals()
        self.start_worker(mode="process", text=text, footer="Thinking through the request...")

    def on_listen(self):
        if self.busy:
            return
        self._sticky_footer = False
        self.orb.set_state("listening")
        self.state_pill.setText("LISTENING")
        self.footer.setText("Voice standby is already active. Say Iris to speak.")
        self._apply_engine_visuals()

    def start_worker(self, mode: str, text: str = "", footer: str = ""):
        self.set_busy(True, footer)
        self.worker = EngineWorker(self.engine, mode=mode, text=text)
        self.worker.completed.connect(self.on_worker_completed)
        self.worker.failed.connect(self.on_worker_failed)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_worker_completed(self, payload):
        captured = payload.get("captured", "")
        result = payload.get("result")
        mode = payload.get("mode", "process")

        if mode == "listen" and captured:
            self.append_message("You", captured, "user")

        if result and result.response:
            self._display_result(result, speak=True)
            if result.should_exit:
                return

        if mode == "listen" and not captured:
            feedback = payload.get("listen_feedback") or "I didn't catch anything that time."
            spoken_feedback = payload.get("listen_feedback_short") or "I didn't catch that."
            self._sticky_footer = True
            self.append_message("System", feedback, "system")
            self.footer.setText(feedback)
            if self.tray and not self.isVisible():
                self.tray.showMessage(Config.PUBLIC_NAME, feedback, self.app_icon, 5000)
            if getattr(self.engine.voice, "audio_ready", False):
                self.engine.voice.speak_background(spoken_feedback)

    def on_standby_event(self, payload):
        event_type = payload.get("type")

        if event_type == "ack":
            self._sticky_footer = False
            text = payload.get("text", getattr(Config, "WAKE_ACKNOWLEDGEMENT", "I'm here."))
            self.append_message(Config.PUBLIC_NAME, text, "assistant")
            self._set_mode_banner("VOICE STANDBY")
            self.footer.setText("Listening for your command...")
            return

        if event_type == "heard":
            text = payload.get("text", "")
            if text:
                self.append_message("You", text, "user")
                self._set_mode_banner("VOICE MODE")
            return

        if event_type == "result":
            result = payload.get("result")
            if result and result.response:
                self._display_result(result, speak=False)
            return

        if event_type == "feedback":
            feedback = payload.get("text", "I didn't catch that.")
            self._sticky_footer = True
            self.append_message("System", feedback, "system")
            self.footer.setText(feedback)
            if self.tray and not self.isVisible():
                self.tray.showMessage(Config.PUBLIC_NAME, feedback, self.app_icon, 5000)
            return

        if event_type == "shutdown":
            delay_ms = 50 if payload.get("immediate") else 200
            QtCore.QTimer.singleShot(delay_ms, self.quit_app)

    def _display_result(self, result, speak: bool):
        self._sticky_footer = False
        kind = "assistant" if "Diagnostics" not in result.label else "system"
        self.append_message(result.label, result.response, kind)
        self._set_mode_banner(f"{result.mode.upper()} MODE")
        self.refresh_status()
        if speak and not getattr(result, "exit_immediately", False):
            self.engine.voice.speak_background(result.response)
        if self.tray and not self.isVisible():
            snippet = result.response if len(result.response) < 180 else result.response[:177] + "..."
            self.tray.showMessage(result.label, snippet, self.app_icon, 7000)
        if result.should_exit:
            delay_ms = 50 if getattr(result, "exit_immediately", False) else 1500
            QtCore.QTimer.singleShot(delay_ms, self.quit_app)

    def on_worker_failed(self, message: str):
        self._sticky_footer = True
        self.orb.set_state("error")
        self.floating_window.set_state("error")
        self.state_pill.setText("ERROR")
        self._apply_engine_visuals()
        self.append_message("System", f"Something broke: {message}", "system")
        self.footer.setText("The last operation failed.")
        if self.tray:
            self.tray.showMessage("Iris Error", message, self.app_icon, 7000)

    def on_worker_finished(self):
        self.set_busy(False)
        if self.engine.voice.current_state in {"idle", "standby"}:
            target_state = "standby" if self.wake_worker and self.wake_worker.isRunning() else "idle"
            self.orb.set_state(target_state)
            self.floating_window.set_state(target_state)
            self.state_pill.setText("VOICE STANDBY" if target_state == "standby" else "IDLE")
            if not self._sticky_footer:
                self.footer.setText(
                    "Voice standby online. Say Iris at any time."
                    if target_state == "standby"
                    else "Standing by."
                )
        self._apply_engine_visuals()

    def refresh_status(self):
        if self.floating_window.isVisible():
            self._set_mode_banner("FLOATING ORB")
        self._apply_engine_visuals()

    def _refresh_runtime_diagnostics(self):
        snapshot = self.engine.status_snapshot()

        brain = str(snapshot.get("primary_brain") or "unknown").replace("_", " ").upper()
        mic_ready = bool(snapshot.get("mic_ready"))
        mic_name = str(snapshot.get("selected_mic_name") or "").strip()
        if not mic_ready:
            mic_display = "UNAVAILABLE"
        elif not mic_name or mic_name == "Default":
            mic_display = "DEFAULT"
        else:
            mic_display = mic_name
        if len(mic_display) > 34:
            mic_display = mic_display[:31] + "..."

        stt_backend = str(snapshot.get("last_transcript_backend") or "--").upper()
        confidence = float(snapshot.get("last_transcript_confidence") or 0.0)
        attempts = str(snapshot.get("last_transcript_attempts") or "").replace("_", " ").upper()
        capture_ms = int(snapshot.get("last_capture_duration_ms") or 0)
        transcribe_ms = int(snapshot.get("last_transcription_duration_ms") or 0)
        total_ms = int(snapshot.get("last_total_listen_duration_ms") or 0)
        if stt_backend != "--" and confidence > 0:
            stt_display = f"{stt_backend} {confidence:.2f}"
        else:
            stt_display = stt_backend

        tts_display = str(snapshot.get("last_tts_backend") or "--").upper()
        audio_display = "READY" if snapshot.get("audio_ready") else "OFF"

        self.diagnostics_label.setText(
            f"BRAIN {brain}  //  MIC {mic_display}\n"
            f"STT {stt_display}  //  TTS {tts_display}  //  AUDIO {audio_display}\n"
            f"LISTEN {capture_ms}ms + {transcribe_ms}ms = {total_ms}ms  //  PATH {attempts or '--'}"
        )

    def _set_mode_banner(self, text: str):
        self._mode_banner_base = text
        if self.engine.overdrive_active:
            self.mode_label.setText(f"{text} // OVERDRIVE")
        else:
            self.mode_label.setText(text)

    def _apply_engine_visuals(self):
        overdrive = self.engine.overdrive_active
        self.orb.set_overdrive(overdrive)
        self.floating_window.set_overdrive(overdrive)
        self._set_mode_banner(getattr(self, "_mode_banner_base", "SAY IRIS ANY TIME"))
        if hasattr(self, "diagnostics_label"):
            self._refresh_runtime_diagnostics()
        if hasattr(self, "overdrive_button"):
            self.overdrive_button.setText("Disable Overdrive" if overdrive else "Enable Overdrive")
        if overdrive:
            self.state_pill.setStyleSheet(
                "border-radius: 14px; padding: 8px 16px; background: rgba(142, 229, 255, 0.18); "
                "color: #E8FBFF; font-family: 'Bahnschrift SemiBold'; font-size: 11px; letter-spacing: 2px;"
            )
        else:
            self.state_pill.setStyleSheet("")
        if self.tray and hasattr(self, "overdrive_action"):
            self.overdrive_action.blockSignals(True)
            self.overdrive_action.setChecked(overdrive)
            self.overdrive_action.setText("Disable Overdrive" if overdrive else "Enable Overdrive")
            self.overdrive_action.blockSignals(False)

    def toggle_overdrive(self):
        target_state = not self.engine.overdrive_active
        if target_state:
            self.engine.activate_overdrive()
            self.engine.executor._audit(
                "OVERDRIVE_ACTIVATED",
                {
                    "action_type": "overdrive_mode",
                    "description": "activate overdrive via GUI",
                    "command": "gui_toggle_on",
                },
                source="gui",
            )
            message = "Overdrive is active. IRIS will reason more deeply without widening permissions."
        else:
            self.engine.deactivate_overdrive()
            self.engine.executor._audit(
                "OVERDRIVE_DEACTIVATED",
                {
                    "action_type": "overdrive_mode",
                    "description": "deactivate overdrive via GUI",
                    "command": "gui_toggle_off",
                },
                source="gui",
            )
            message = "Overdrive is off. IRIS is back to the normal execution profile."

        self.append_message("System", message, "system")
        self.footer.setText(message)
        self._apply_engine_visuals()

    def _restore_floating_orb_position(self):
        x = self.settings.value("floating_orb_x", None, type=int)
        y = self.settings.value("floating_orb_y", None, type=int)
        if x is not None and y is not None:
            self.floating_window.move(x, y)
            return

        screen = QtGui.QGuiApplication.primaryScreen()
        if not screen:
            return
        geometry = screen.availableGeometry()
        margin = 30
        target = QtCore.QPoint(
            geometry.right() - self.floating_window.width() - margin,
            geometry.bottom() - self.floating_window.height() - margin,
        )
        self.floating_window.move(target)

    def _save_floating_orb_position(self, x: int, y: int):
        self.settings.setValue("floating_orb_x", x)
        self.settings.setValue("floating_orb_y", y)

    def _legacy_startup_script_path(self) -> Path:
        appdata = Path(os.getenv("APPDATA", str(Path.home() / "AppData/Roaming")))
        return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "IrisAletheia.cmd"

    def _has_startup_shortcut(self) -> bool:
        return self._startup_script_path().exists() or self._legacy_startup_script_path().exists()

    def _startup_script_path(self) -> Path:
        appdata = Path(os.getenv("APPDATA", str(Path.home() / "AppData/Roaming")))
        return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "IRIS.cmd"

    def _startup_script_contents(self) -> str:
        if getattr(sys, "frozen", False):
            exe_path = Path(sys.executable).resolve()
            return (
                "@echo off\n"
                f'cd /d "{exe_path.parent}"\n'
                f'start "" "{exe_path}"\n'
            )

        script_path = Path(__file__).resolve()
        pythonw = Path(sys.executable)
        candidate = pythonw.with_name("pythonw.exe")
        if candidate.exists():
            pythonw = candidate
        return (
            "@echo off\n"
            f'cd /d "{script_path.parent}"\n'
            f'start "" "{pythonw}" "{script_path}"\n'
        )

    def set_launch_at_login(self, enabled: bool):
        path = self._startup_script_path()
        legacy_path = self._legacy_startup_script_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if enabled:
            path.write_text(self._startup_script_contents(), encoding="utf-8")
            if legacy_path.exists():
                try:
                    legacy_path.unlink()
                except Exception:
                    pass
            self._startup_enabled = True
            self.footer.setText("Iris will launch at sign-in.")
        else:
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass
            try:
                if legacy_path.exists():
                    legacy_path.unlink()
            except Exception:
                pass
            self._startup_enabled = False
            self.footer.setText("Launch at sign-in disabled.")

        if self.tray and hasattr(self, "startup_action"):
            self.startup_action.blockSignals(True)
            self.startup_action.setChecked(self._startup_enabled)
            self.startup_action.blockSignals(False)
        if hasattr(self, "startup_checkbox"):
            self.startup_checkbox.blockSignals(True)
            self.startup_checkbox.setChecked(self._startup_enabled)
            self.startup_checkbox.blockSignals(False)
        self.refresh_status()

    def hide_to_tray(self):
        self.hide()
        if self.tray and not self._first_tray_hint_shown:
            self.tray.showMessage(
                f"{Config.PUBLIC_NAME} is still here",
                "I moved into the system tray. Double-click the tray icon to bring me back.",
                self.app_icon,
                7000,
            )
            self._first_tray_hint_shown = True
            self.settings.setValue("tray_hint_shown", True)

    def show_dashboard(self, announce: bool = True):
        self.settings.setValue("floating_mode", False)
        self.floating_window.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if announce:
            self.footer.setText("Dashboard mode restored.")
        if self.tray and hasattr(self, "floating_action"):
            self.floating_action.blockSignals(True)
            self.floating_action.setChecked(False)
            self.floating_action.blockSignals(False)
        self.refresh_status()

    def set_floating_mode(self, enabled: bool, announce: bool = True):
        if enabled:
            self.settings.setValue("floating_mode", True)
            if not self.floating_window.isVisible():
                self.floating_window.show()
            self.floating_window.raise_()
            self.floating_window.activateWindow()
            self.hide()
            if announce:
                self.footer.setText("Floating orb mode enabled.")
        else:
            self.show_dashboard(announce=announce)
            return

        if self.tray and hasattr(self, "floating_action"):
            self.floating_action.blockSignals(True)
            self.floating_action.setChecked(enabled)
            self.floating_action.blockSignals(False)
        self.refresh_status()

    def toggle_floating_orb(self):
        self.set_floating_mode(not self.floating_window.isVisible())

    def open_floating_orb(self):
        self.set_floating_mode(True)

    def _on_tray_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.DoubleClick:
            if self.isVisible():
                self.hide_to_tray()
            else:
                self.show_dashboard()

    def quit_app(self):
        self._quitting = True
        self._stop_voice_standby()
        if self.tray:
            self.tray.hide()
        self.floating_window.hide()
        self.close()

    def closeEvent(self, event):
        if not self._quitting and self.tray:
            self.hide_to_tray()
            event.ignore()
            return
        try:
            self._stop_voice_standby()
            self.engine.shutdown()
        finally:
            event.accept()
            super().closeEvent(event)


def main():
    apply_windows_app_user_model_id()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(Config.PUBLIC_NAME.upper())
    app.setOrganizationName("Aletheia")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(create_app_icon())
    app.setStyle("Fusion")

    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#12202A"))
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#12202A"))
    palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#F7F3EA"))
    palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#F7F3EA"))
    palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#F7F3EA"))
    app.setPalette(palette)

    window = IrisWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
