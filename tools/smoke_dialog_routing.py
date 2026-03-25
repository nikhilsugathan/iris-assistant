"""
IRIS dialog-routing smoke test.

Checks that action-style questions and advisory questions route differently,
so IRIS doesn't jump into execution mode when the user is only asking for
guidance.
"""

from __future__ import annotations

from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from core.engine import IRISEngine


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    engine = IRISEngine(text_mode=True)
    try:
        action_decision = engine.dialog_manager.analyze(
            "can you install git for me",
            engine.executor,
            engine.copilot,
            engine.diagnostics,
            engine.self_model,
        )
        assert_true(action_decision.mode == "action", "Direct install request should route to action mode.")

        advisory_decision = engine.dialog_manager.analyze(
            "should i install git",
            engine.executor,
            engine.copilot,
            engine.diagnostics,
            engine.self_model,
        )
        assert_true(advisory_decision.mode != "action", "Advice-seeking install question should not route to action mode.")

        howto_decision = engine.dialog_manager.analyze(
            "how do i uninstall node",
            engine.executor,
            engine.copilot,
            engine.diagnostics,
            engine.self_model,
        )
        assert_true(howto_decision.mode != "action", "How-to uninstall question should not route to action mode.")

        info_decision = engine.dialog_manager.analyze(
            "what apps are installed",
            engine.executor,
            engine.copilot,
            engine.diagnostics,
            engine.self_model,
        )
        assert_true(info_decision.mode == "action", "Installed-app inventory should stay on the action/system path.")

        print("PASS: IRIS dialog-routing smoke test completed.")
    finally:
        engine.shutdown()


if __name__ == "__main__":
    main()
