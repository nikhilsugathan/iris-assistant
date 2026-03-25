"""
IRIS wake-alias smoke test.

Ensures common wake-word misrecognitions normalize back to Iris without
introducing false positives for ordinary phrases like "what time is it".
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
        assert_true(engine.contains_wake_word("it open notepad"), "Leading alias should count as the wake word.")
        assert_true(engine.contains_wake_word("eris check the weather"), "Phonetic wake alias should count as the wake word.")
        assert_true(engine.contains_wake_word("hey iris"), "Prefixed wake phrase should count as the wake word.")
        assert_true(engine.contains_wake_word("okay, eris open browser"), "Prefixed wake alias should count as the wake word.")
        assert_true(not engine.contains_wake_word("what time is it"), "Ordinary use of 'it' should not trigger the wake word.")

        normalized = engine.normalize_wake_transcript("it open notepad")
        assert_true(normalized == "Iris open notepad", "Wake alias should normalize back to Iris for display.")
        assert_true(
            engine.normalize_wake_transcript("hey iris") == "Iris",
            "Prefixed wake phrase should normalize back to Iris.",
        )
        assert_true(
            engine.normalize_wake_transcript("okay, eris open browser") == "Iris open browser",
            "Prefixed wake alias should normalize back to Iris for display.",
        )
        assert_true(
            engine.strip_wake_word("it open notepad") == "open notepad",
            "Wake alias should be stripped cleanly from the front of the transcript.",
        )
        assert_true(
            engine.strip_wake_word("hey iris") == "",
            "Pure prefixed wake phrase should strip down to an empty command.",
        )
        assert_true(
            engine.strip_wake_word("okay, eris open browser") == "open browser",
            "Prefixed wake alias should strip down to just the command text.",
        )

        print("PASS: IRIS wake alias smoke test completed.")
    finally:
        engine.shutdown()


if __name__ == "__main__":
    main()
