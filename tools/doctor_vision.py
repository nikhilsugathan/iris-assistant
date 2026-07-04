"""IRIS vision doctor.

Run from project root:
    python tools\doctor_vision.py

Checks whether screen capture works, saves a preview JPEG, and optionally sends
the capture to Groq/Gemini vision for a short readback test.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _write_preview(image_b64: str) -> Path:
    exports = PROJECT_ROOT / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    preview_path = exports / "vision_doctor_capture.jpg"
    preview_path.write_bytes(base64.b64decode(image_b64))
    return preview_path


def _call_gemini(image_b64: str, prompt: str) -> str:
    import requests
    from config import Config

    api_key = getattr(Config, "GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY missing")
    model = os.getenv("GEMINI_VISION_MODEL", getattr(Config, "GEMINI_MODEL", "gemini-3.5-flash"))
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 300},
    }
    resp = requests.post(url, json=payload, timeout=20)
    if not resp.ok:
        raise RuntimeError(f"Gemini Vision API {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _call_groq(image_b64: str, prompt: str) -> str:
    from groq import Groq
    from config import Config

    api_key = getattr(Config, "GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY missing")
    model = os.getenv("GROQ_VISION_MODEL", getattr(Config, "GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"))
    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }
        ],
        max_tokens=300,
        temperature=0.2,
    )
    return completion.choices[0].message.content.strip()


def main() -> int:
    from core.vision import capture_screen_base64

    monitor = int(os.getenv("VISION_MONITOR", "1"))
    max_width = int(os.getenv("VISION_MAX_WIDTH", "1600"))
    provider = os.getenv("VISION_PROVIDER", "auto").strip().lower()

    print("IRIS Vision Doctor")
    print("=" * 60)
    print(f"monitor:       {monitor}")
    print(f"max_width:     {max_width}")
    print(f"provider:      {provider}")

    started = time.monotonic()
    try:
        image_b64 = capture_screen_base64(monitor=monitor, max_width=max_width)
    except Exception as exc:
        print(f"capture:       failed - {exc}")
        return 1

    preview_path = _write_preview(image_b64)
    print(f"capture:       ok ({len(image_b64)} base64 chars, {(time.monotonic() - started) * 1000:.1f} ms)")
    print(f"preview:       {preview_path}")

    prompt = (
        "Read this screenshot. In one short paragraph, describe the visible app/window, "
        "any readable text, and any obvious error or next action."
    )

    providers = [provider] if provider in {"groq", "gemini"} else ["gemini", "groq"]
    last_error = None
    for item in providers:
        try:
            started = time.monotonic()
            if item == "gemini":
                response = _call_gemini(image_b64, prompt)
            else:
                response = _call_groq(image_b64, prompt)
            print(f"{item}:        ok ({(time.monotonic() - started) * 1000:.1f} ms)")
            print("response:")
            print(response[:1200])
            print("Doctor result: vision capture and provider readback are working.")
            return 0
        except Exception as exc:
            last_error = exc
            print(f"{item}:        failed - {exc}")

    print(f"Doctor result: capture worked, but provider readback failed. Last error: {last_error}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
