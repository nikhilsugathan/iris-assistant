from __future__ import annotations

import html
import math
import sys

from PySide6 import QtCore, QtGui, QtWidgets

from config import Config
from core.engine import IRISEngine


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
    COLORS = {
        "idle": ("#2C6E77", "#D9A25F"),
        "listening": ("#1F9DB7", "#8DE8F4"),
        "thinking": ("#9A5C1D", "#F2C572"),
        "speaking": ("#257A67", "#F4B066"),
        "error": ("#8D2E2E", "#FF7A7A"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self._state = "idle"
        self._base_radius = 88
        self.setMinimumSize(340, 340)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    def set_state(self, state: str):
        self._state = state if state in self.COLORS else "idle"
        self.update()

    def _tick(self):
        speed = {
            "idle": 0.02,
            "listening": 0.05,
            "thinking": 0.09,
            "speaking": 0.07,
            "error": 0.12,
        }.get(self._state, 0.02)
        self._phase += speed
        self.update()

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

        halo = QtGui.QRadialGradient(center, radius * 1.85)
        halo.setColorAt(0.0, QtGui.QColor(accent.red(), accent.green(), accent.blue(), 130))
        halo.setColorAt(0.38, QtGui.QColor(primary.red(), primary.green(), primary.blue(), 90))
        halo.setColorAt(1.0, QtGui.QColor(primary.red(), primary.green(), primary.blue(), 0))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(halo))
        painter.drawEllipse(center, radius * 1.85, radius * 1.85)

        orbit_pen = QtGui.QPen(QtGui.QColor(accent.red(), accent.green(), accent.blue(), 110), 2.2)
        orbit_pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.setPen(orbit_pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        for idx, orbit_scale in enumerate((1.45, 1.80, 2.20)):
            orbit_rect = QtCore.QRectF(
                center.x() - radius * orbit_scale,
                center.y() - radius * orbit_scale,
                radius * orbit_scale * 2,
                radius * orbit_scale * 2,
            )
            start = int((self._phase * 120 + idx * 100) * 16)
            span = int((120 + pulse * 120) * 16)
            painter.drawArc(orbit_rect, start, span)

        core = QtGui.QRadialGradient(center, radius)
        core.setColorAt(0.0, QtGui.QColor("#FFF9F0"))
        core.setColorAt(0.34, QtGui.QColor(accent.red(), accent.green(), accent.blue(), 230))
        core.setColorAt(1.0, QtGui.QColor(primary.red(), primary.green(), primary.blue(), 235))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(core))
        painter.drawEllipse(center, radius, radius)

        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 95), 1.4))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(center, radius * 0.74, radius * 0.74)

        label_font = QtGui.QFont("Bahnschrift SemiBold", 12)
        painter.setFont(label_font)
        painter.setPen(QtGui.QColor("#F6F2E8"))
        painter.drawText(
            QtCore.QRectF(center.x() - 85, center.y() - 18, 170, 36),
            QtCore.Qt.AlignCenter,
            Config.INNER_CODENAME.upper(),
        )

        state_font = QtGui.QFont("Segoe UI Semibold", 10)
        painter.setFont(state_font)
        painter.setPen(QtGui.QColor(240, 240, 240, 190))
        painter.drawText(
            QtCore.QRectF(0, h - 42, w, 24),
            QtCore.Qt.AlignCenter,
            self._state.upper(),
        )


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
                    self.completed.emit({"captured": "", "result": None, "mode": "listen"})
                    return
                result = self.engine.process_user_input(captured)
                self.completed.emit({"captured": captured, "result": result, "mode": "listen"})
                return

            result = self.engine.process_user_input(self.text)
            self.completed.emit({"captured": self.text, "result": result, "mode": "process"})
        except Exception as exc:
            self.failed.emit(str(exc))


class IrisWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.engine = IRISEngine(text_mode=False)
        self.signals = AppSignals()
        self.engine.voice.set_state_callback(self.signals.voice_state.emit)
        self.signals.voice_state.connect(self.on_voice_state)
        self.worker = None
        self.busy = False

        self.setWindowTitle(f"{Config.SYSTEM_NAME} // {Config.INNER_CODENAME}")
        self.resize(1380, 860)
        self.setMinimumSize(1220, 760)

        self._build_ui()
        self.refresh_status()

    def _build_ui(self):
        self.setStyleSheet(
            """
            QWidget {
                color: #F7F3EA;
                font-family: 'Segoe UI';
            }
            QLabel#Title {
                font-family: 'Bahnschrift SemiBold';
                font-size: 34px;
                color: #10202A;
            }
            QLabel#SubTitle {
                font-size: 13px;
                color: rgba(16, 32, 42, 0.82);
                letter-spacing: 1px;
            }
            QFrame#GlassPanel {
                background: rgba(9, 19, 28, 0.62);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 28px;
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
                background: rgba(255, 255, 255, 0.10);
                color: #F7F3EA;
                border: 1px solid rgba(255, 255, 255, 0.12);
            }
            QPushButton#SecondaryButton:hover {
                background: rgba(255, 255, 255, 0.16);
            }
            QLabel#Chip {
                border-radius: 12px;
                padding: 6px 10px;
                background: rgba(255, 255, 255, 0.12);
                color: #F7F3EA;
                font-size: 11px;
            }
            QLabel#StatePill {
                border-radius: 12px;
                padding: 8px 14px;
                background: rgba(217, 162, 95, 0.22);
                color: #F6E2C2;
                font-family: 'Bahnschrift SemiBold';
                font-size: 11px;
                letter-spacing: 1px;
            }
            """
        )

        backdrop = BackdropWidget()
        self.setCentralWidget(backdrop)

        root = QtWidgets.QHBoxLayout(backdrop)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(22)

        left_panel = QtWidgets.QFrame()
        left_panel.setObjectName("GlassPanel")
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(30, 30, 30, 30)
        left_layout.setSpacing(18)

        title = QtWidgets.QLabel(f"{Config.PUBLIC_NAME} // {Config.INNER_CODENAME}")
        title.setObjectName("Title")
        left_layout.addWidget(title)

        subtitle = QtWidgets.QLabel(Config.SYSTEM_MOTTO.upper())
        subtitle.setObjectName("SubTitle")
        left_layout.addWidget(subtitle)

        self.state_pill = QtWidgets.QLabel("IDLE")
        self.state_pill.setObjectName("StatePill")
        self.state_pill.setAlignment(QtCore.Qt.AlignCenter)
        left_layout.addWidget(self.state_pill, alignment=QtCore.Qt.AlignLeft)

        self.orb = OrbWidget()
        left_layout.addWidget(self.orb, alignment=QtCore.Qt.AlignCenter, stretch=1)

        self.status_stack = QtWidgets.QVBoxLayout()
        self.status_stack.setSpacing(10)
        self.brain_chip = QtWidgets.QLabel()
        self.brain_chip.setObjectName("Chip")
        self.core_chip = QtWidgets.QLabel()
        self.core_chip.setObjectName("Chip")
        self.self_model_chip = QtWidgets.QLabel()
        self.self_model_chip.setObjectName("Chip")
        self.memory_chip = QtWidgets.QLabel()
        self.memory_chip.setObjectName("Chip")
        for chip in (self.brain_chip, self.core_chip, self.self_model_chip, self.memory_chip):
            chip.setWordWrap(True)
            self.status_stack.addWidget(chip)
        left_layout.addLayout(self.status_stack)
        left_layout.addStretch(1)

        right_panel = QtWidgets.QFrame()
        right_panel.setObjectName("GlassPanel")
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(30, 30, 30, 30)
        right_layout.setSpacing(18)

        header_row = QtWidgets.QHBoxLayout()
        header_row.setSpacing(12)
        conversation_title = QtWidgets.QLabel("Conversation")
        conversation_title.setStyleSheet("font-family: 'Bahnschrift SemiBold'; font-size: 28px; color: #F7F3EA;")
        header_row.addWidget(conversation_title)
        header_row.addStretch(1)

        self.mode_label = QtWidgets.QLabel("ALETHEIA ACTIVE")
        self.mode_label.setObjectName("Chip")
        header_row.addWidget(self.mode_label)
        right_layout.addLayout(header_row)

        self.transcript = QtWidgets.QTextBrowser()
        self.transcript.setOpenExternalLinks(False)
        self.transcript.document().setDocumentMargin(18)
        right_layout.addWidget(self.transcript, stretch=1)

        input_row = QtWidgets.QHBoxLayout()
        input_row.setSpacing(12)
        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText("Speak your mind, or type it here...")
        self.input.returnPressed.connect(self.on_send)
        input_row.addWidget(self.input, stretch=1)

        self.listen_button = QtWidgets.QPushButton("Listen")
        self.listen_button.setObjectName("SecondaryButton")
        self.listen_button.clicked.connect(self.on_listen)
        input_row.addWidget(self.listen_button)

        self.send_button = QtWidgets.QPushButton("Send")
        self.send_button.setObjectName("PrimaryButton")
        self.send_button.clicked.connect(self.on_send)
        input_row.addWidget(self.send_button)
        right_layout.addLayout(input_row)

        self.footer = QtWidgets.QLabel("Desktop shell online.")
        self.footer.setStyleSheet("color: rgba(247, 243, 234, 0.72); font-size: 12px;")
        right_layout.addWidget(self.footer)

        root.addWidget(left_panel, 4)
        root.addWidget(right_panel, 6)

        self.append_message(
            "SYSTEM",
            f"{Config.PUBLIC_NAME} is online. {Config.INNER_CODENAME} is active underneath.",
            "system",
        )

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
        self.state_pill.setText(state.upper())
        footer_map = {
            "idle": "Standing by.",
            "listening": "Listening for your voice.",
            "speaking": "Iris is speaking.",
        }
        self.footer.setText(footer_map.get(state, self.footer.text()))

    def set_busy(self, busy: bool, footer: str = ""):
        self.busy = busy
        self.send_button.setEnabled(not busy)
        self.listen_button.setEnabled(not busy)
        self.input.setEnabled(not busy)
        if footer:
            self.footer.setText(footer)

    def on_send(self):
        if self.busy:
            return
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.append_message("You", text, "user")
        self.orb.set_state("thinking")
        self.state_pill.setText("THINKING")
        self.start_worker(mode="process", text=text, footer="Thinking through the request...")

    def on_listen(self):
        if self.busy:
            return
        self.orb.set_state("listening")
        self.state_pill.setText("LISTENING")
        self.start_worker(mode="listen", footer="Listening for a command...")

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
            kind = "assistant" if "Diagnostics" not in result.label else "system"
            self.append_message(result.label, result.response, kind)
            self.mode_label.setText(f"{result.mode.upper()} MODE")
            self.refresh_status()
            if result.should_exit:
                QtCore.QTimer.singleShot(250, self.close)
                return

        if mode == "listen" and not captured:
            self.footer.setText("I didn't catch anything that time.")

    def on_worker_failed(self, message: str):
        self.orb.set_state("error")
        self.state_pill.setText("ERROR")
        self.append_message("System", f"Something broke: {message}", "system")
        self.footer.setText("The last operation failed.")

    def on_worker_finished(self):
        self.set_busy(False)
        if self.engine.voice.current_state == "idle":
            self.orb.set_state("idle")
            self.state_pill.setText("IDLE")
            self.footer.setText("Standing by.")

    def refresh_status(self):
        status = self.engine.status_snapshot()
        self.brain_chip.setText(f"Brains: {status['primary_brain']} -> {status['fallback_brain']}")
        self.core_chip.setText(f"Core: {status['public_name']} outside, {status['inner_codename']} inside")
        self.self_model_chip.setText(f"Self model: {status['self_model']}")
        self.memory_chip.setText(f"Memory: {status['memory']}")

    def closeEvent(self, event):
        try:
            self.engine.shutdown()
        finally:
            super().closeEvent(event)


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(f"{Config.SYSTEM_NAME} Desktop")
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
