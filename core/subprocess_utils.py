from __future__ import annotations

import os
import subprocess


def hidden_process_kwargs() -> dict:
    """Hide helper console windows on Windows subprocess calls."""
    if os.name != "nt":
        return {}

    kwargs: dict = {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags

    startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
    startf_use_show_window = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    if startupinfo_factory is not None and startf_use_show_window:
        startupinfo = startupinfo_factory()
        startupinfo.dwFlags |= startf_use_show_window
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo

    return kwargs
