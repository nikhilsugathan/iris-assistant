"""
IRIS personality-style smoke test.

Confirms the configured greeting and short-response variants are reachable
through the local brain helpers.
"""

from __future__ import annotations

from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from config import Config
from core.brain import Brain


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class DummyMemory:
    def get_context(self, max_turns: int = 3):
        return []

    def add(self, role: str, content: str, source: str | None = None):
        return None


def main() -> None:
    brain = Brain(DummyMemory())

    startup = brain.startup_greeting()
    assert_true(startup in Config.STARTUP_GREETINGS, "Startup greeting was not chosen from the configured pool.")

    greeting = brain._rewrite_generic_response("hi iris")
    assert_true(greeting in Config.GREETING_RESPONSES, "Greeting response did not come from the configured pool.")

    help_text = brain._rewrite_generic_response("help me")
    assert_true(help_text in Config.HELP_RESPONSES, "Help response did not come from the configured pool.")

    thanks = brain._rewrite_generic_response("thanks iris")
    assert_true(thanks in Config.THANKS_RESPONSES, "Thanks response did not come from the configured pool.")

    ack = brain.quick_ack("search for the berlin weather")
    assert_true(ack in Config.SEARCH_ACKS, "Search acknowledgement did not come from the configured pool.")

    print("PASS: IRIS personality style smoke test completed.")


if __name__ == "__main__":
    main()
