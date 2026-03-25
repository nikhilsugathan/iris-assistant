"""
Offscreen GUI smoke test for the IRIS desktop shell.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from PySide6 import QtGui, QtTest, QtWidgets

from config import Config
from core.engine import IRISEngine
from core.runtime_log import get_runtime_log_path
from core.visual_identity import create_app_icon
from iris_gui import IrisWindow


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeRunningWorker:
    def isRunning(self) -> bool:
        return True


def configure_app(app: QtWidgets.QApplication) -> None:
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


def main() -> None:
    smoke_dir = WORKSPACE / "build" / "smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    dashboard_preview = smoke_dir / "iris_gui_dashboard.png"
    floating_preview = smoke_dir / "iris_gui_floating_orb.png"
    audit_log = smoke_dir / "iris_gui_audit.log"
    original_runtime_log = Config.RUNTIME_LOG_FILE
    Config.RUNTIME_LOG_FILE = str(smoke_dir / "iris_gui_runtime.log")
    runtime_log = get_runtime_log_path()

    for artifact in (dashboard_preview, floating_preview, audit_log, runtime_log):
        if artifact.exists():
            try:
                artifact.unlink()
            except PermissionError:
                pass

    app = QtWidgets.QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QtWidgets.QApplication([])
    configure_app(app)

    engine = IRISEngine(text_mode=True)
    engine.executor.audit_file = str(audit_log)
    window = IrisWindow(engine=engine, start_voice_standby=False, enable_tray=False)

    try:
        window.show_dashboard(announce=False)
        window.show()
        app.processEvents()
        QtTest.QTest.qWait(max(80, int(getattr(Config, "STARTUP_GREETING_DELAY_MS", 0)) + 80))
        app.processEvents()

        assert_true(window.mode_label.text() == "SAY IRIS ANY TIME", "Dashboard mode banner did not initialize correctly.")
        assert_true(
            "BRAIN " in window.diagnostics_label.text() and "MIC " in window.diagnostics_label.text(),
            "Runtime diagnostics did not render in the dashboard.",
        )
        assert_true(
            "LISTEN " in window.diagnostics_label.text() and "PATH " in window.diagnostics_label.text(),
            "Runtime diagnostics did not render the voice timing path.",
        )
        assert_true(
            "STATE " in window.diagnostics_label.text() and "WAKE " in window.diagnostics_label.text(),
            "Runtime diagnostics did not render the live wake-state summary.",
        )
        engine.voice.last_transcript_uncertain = True
        engine.voice.last_transcript_backend = "faster_whisper"
        engine.voice.last_transcript_confidence = 0.61
        engine.voice.last_listen_status = "wake_not_understood"
        engine.voice.last_listen_detail = "Wake audio was captured, but no wake phrase was recognized."
        engine.voice.last_rejected_wake_text = "hey artists"
        engine.voice.last_rejected_wake_backend = "system"
        engine.voice.last_rejected_wake_confidence = 0.44
        engine.voice.last_rejected_wake_score = 0.82
        window.refresh_status()
        app.processEvents()
        assert_true(
            "UNCERTAIN" in window.diagnostics_label.text(),
            "Runtime diagnostics did not surface uncertain transcript state.",
        )
        assert_true(
            "HEY ARTISTS" in window.diagnostics_label.text().upper(),
            "Runtime diagnostics did not surface the strongest rejected wake phrase.",
        )
        engine.voice.last_transcript_uncertain = False
        transcript_text = window.transcript.toPlainText()
        if getattr(Config, "STARTUP_GREETING_ENABLED", True):
            assert_true(
                any(greeting in transcript_text for greeting in getattr(Config, "STARTUP_GREETINGS", [])),
                "Startup greeting did not appear in the dashboard transcript.",
            )

        window.on_voice_state("standby")
        app.processEvents()
        assert_true(window.state_pill.text() == "VOICE STANDBY", "Standby state did not render the expected pill label.")
        assert_true(
            window.footer.text() == "Voice standby online. Say Iris at any time.",
            "Standby state did not keep the stable voice standby footer.",
        )

        original_wake_worker = window.wake_worker
        window.wake_worker = FakeRunningWorker()
        window.on_voice_state("idle")
        app.processEvents()
        assert_true(
            window.state_pill.text() == "VOICE STANDBY",
            "Idle voice state should render as voice standby while the wake worker is still running.",
        )
        window.wake_worker = original_wake_worker

        window.on_voice_state("thinking")
        app.processEvents()
        assert_true(window.state_pill.text() == "THINKING", "Voice-state updates did not reach the dashboard.")

        window.toggle_overdrive()
        app.processEvents()
        assert_true(window.engine.overdrive_active, "GUI overdrive toggle did not activate Overdrive.")
        assert_true(window.overdrive_button.text() == "Disable Overdrive", "Overdrive button label did not update.")
        assert_true("OVERDRIVE" in window.mode_label.text(), "Mode banner did not reflect Overdrive.")

        assert_true(window.grab().save(str(dashboard_preview)), "Dashboard preview could not be written.")

        window.set_floating_mode(True, announce=False)
        app.processEvents()
        assert_true(window.floating_window.isVisible(), "Floating orb window did not become visible.")
        assert_true("OVERDRIVE" in window.floating_window.state_label.text(), "Floating orb did not reflect Overdrive.")
        assert_true(window.floating_window.grab().save(str(floating_preview)), "Floating orb preview could not be written.")

        window.show_dashboard(announce=False)
        app.processEvents()
        assert_true(window.isVisible(), "Dashboard did not restore after floating orb mode.")
        assert_true(not window.floating_window.isVisible(), "Floating orb did not hide when restoring dashboard.")
        assert_true(audit_log.exists(), "GUI overdrive smoke did not produce an audit log.")
        assert_true(runtime_log.exists(), "GUI startup did not produce the runtime diagnostics log.")

        print("PASS: IRIS GUI shell smoke test completed.")
        print(f"Dashboard preview: {dashboard_preview}")
        print(f"Floating orb preview: {floating_preview}")
    finally:
        Config.RUNTIME_LOG_FILE = original_runtime_log
        window._quitting = True
        window.close()
        app.processEvents()
        if owns_app:
            app.quit()


if __name__ == "__main__":
    main()
