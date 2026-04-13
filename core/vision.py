"""
core/vision.py
==============
Phase 7 Vision Capture Engine — IRIS v5.2.5-STABLE

Captures the primary monitor using mss, converts the raw BGRA frame to RGB,
optionally downscales to reduce API payload, then returns a Base64-encoded
JPEG string for direct submission to the Gemini Vision API.

Design constraints:
  - Zero local VRAM cost: all inference runs server-side on Gemini.
  - mss and Pillow are imported inside the function body so their absence
    causes a clear RuntimeError rather than a silent import failure when
    core/brain.py is loaded on machines without a display.
  - quality=75 JPEG is the latency/fidelity sweet spot for UI recognition
    and on-screen text reading over a network API.
"""
from __future__ import annotations

import base64
import io


def capture_screen_base64(monitor: int = 1, max_width: int = 1280) -> str:
    """Capture the specified monitor and return a Base64-encoded JPEG string.

    Args:
        monitor:   mss monitor index (1 = primary display; 0 = all combined).
                   Falls back to 1 if the index is out of range.
        max_width: Maximum pixel width after capture.  If the frame is wider it
                   is downscaled proportionally (LANCZOS) before encoding.
                   Keeps the Gemini API payload under ~200 KB for 1280 px width
                   at quality=75, which is well within the 20 MB inline_data cap.

    Returns:
        Base64-encoded UTF-8 string of the JPEG image, ready for the Gemini
        ``inline_data`` field: ``{"mime_type": "image/jpeg", "data": <return>}``.

    Raises:
        RuntimeError: if mss or Pillow are not installed, or if the screen
                      capture itself fails (e.g. headless environment).
    """
    try:
        import mss                          # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "[Vision] mss is required for screen capture. "
            "Run: pip install mss"
        ) from exc

    try:
        from PIL import Image               # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "[Vision] Pillow is required for image processing. "
            "Run: pip install Pillow"
        ) from exc

    # ── Capture ───────────────────────────────────────────────────────────────
    with mss.mss() as sct:
        monitors = sct.monitors
        # monitors[0] is the virtual "all screens" bounding box on mss;
        # monitors[1] is the first physical display (primary).
        if monitor < 0 or monitor >= len(monitors):
            monitor = 1
        raw = sct.grab(monitors[monitor])

    # mss returns raw bytes in BGRA order — PIL needs "RGBA" mode with "BGRA"
    # decoder to swap channels correctly before converting to RGB for JPEG.
    img = Image.frombytes("RGBA", raw.size, bytes(raw.raw), "raw", "BGRA")
    img = img.convert("RGB")

    # ── Downscale ─────────────────────────────────────────────────────────────
    if img.width > max_width:
        ratio    = max_width / img.width
        new_size = (max_width, max(1, int(img.height * ratio)))
        img      = img.resize(new_size, Image.LANCZOS)

    # ── Encode ────────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75, optimize=True)
    buf.seek(0)

    return base64.b64encode(buf.read()).decode("utf-8")
