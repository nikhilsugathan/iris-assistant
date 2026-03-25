"""
IRIS Perplexity bridge smoke test.

This verifies the API bridge wiring without needing a live Perplexity key.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from tools import perplexity_bridge


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": "Best next milestone: strengthen approval policy and end-to-end verification."
                    }
                }
            ],
            "search_results": [
                {
                    "title": "IRIS README",
                    "url": "https://example.com/iris-readme",
                    "date": "2026-03-25",
                }
            ],
        }


def main() -> None:
    smoke_dir = WORKSPACE / "build" / "smoke" / "perplexity_bridge"
    smoke_dir.mkdir(parents=True, exist_ok=True)

    request_path = smoke_dir / "request.md"
    response_path = smoke_dir / "response.md"
    transcript_path = smoke_dir / "transcript.md"
    status_path = smoke_dir / "status.md"

    request_path.write_text(
        "# Request\n\nReview the current IRIS state and recommend the next milestone.\n",
        encoding="utf-8",
    )
    transcript_path.write_text("[07:50] Cody (actual): Smoke test context.\n", encoding="utf-8")

    args = SimpleNamespace(
        workflow="once",
        mode="api",
        prompt="",
        include=[],
        transcript_tail_lines=8,
        no_default_context=True,
        max_tokens=400,
        model="sonar-pro",
        web_profile=str(smoke_dir / "profile"),
        browser_channel="auto",
        web_timeout_seconds=30,
        watch_poll_seconds=1,
    )

    original_post = perplexity_bridge.requests.post
    original_key = perplexity_bridge.Config.PERPLEXITY_API_KEY

    try:
        perplexity_bridge.Config.PERPLEXITY_API_KEY = "smoke-test-key"
        perplexity_bridge.requests.post = lambda *args, **kwargs: FakeResponse()

        exit_code = perplexity_bridge.process_once(
            args=args,
            request_path=request_path,
            response_path=response_path,
            transcript_path=transcript_path,
            status_path=status_path,
        )

        assert_true(exit_code == 0, "Perplexity bridge smoke test failed.")
        response_text = response_path.read_text(encoding="utf-8")
        status_text = status_path.read_text(encoding="utf-8")
        transcript_text = transcript_path.read_text(encoding="utf-8")

        assert_true(
            "Best next milestone" in response_text,
            "Perplexity bridge did not write the response content.",
        )
        assert_true(
            "## Sources" in response_text and "https://example.com/iris-readme" in response_text,
            "Perplexity bridge did not append source links.",
        )
        assert_true(
            "State: ready" in status_text,
            "Perplexity bridge did not report a ready status.",
        )
        assert_true(
            "Perplexity (relay): Responded via Perplexity API bridge (sonar-pro)" in transcript_text,
            "Perplexity bridge did not append the transcript relay entry.",
        )

        print("PASS: IRIS Perplexity bridge smoke test completed.")
        print(f"Response: {response_path}")
    finally:
        perplexity_bridge.requests.post = original_post
        perplexity_bridge.Config.PERPLEXITY_API_KEY = original_key


if __name__ == "__main__":
    main()
