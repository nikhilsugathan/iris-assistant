"""
IRIS Tool Registry
==================
Central definition of executable and planned tools.

Only tools in IMPLEMENTED_TOOL_NAMES are exposed to the action planner. Registry
entries outside that set are capability definitions for future implementations and
must not be advertised as executable until ActionExecutor has a dispatcher path.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    required_fields: tuple[str, ...] = field(default_factory=tuple)
    optional_fields: tuple[str, ...] = field(default_factory=tuple)
    risk: str = "normal"  # normal|warning|destructive|admin


TOOLS: dict[str, ToolSpec] = {
    "manage_package": ToolSpec(
        name="manage_package",
        description="Install, uninstall, or upgrade software with an exact package command.",
        required_fields=("command",),
        optional_fields=("package_operation", "package_name"),
        risk="admin",
    ),
    "run_command": ToolSpec(
        name="run_command",
        description="Run an exact shell command.",
        required_fields=("command",),
        optional_fields=(),
        risk="warning",
    ),
    "create_file": ToolSpec(
        name="create_file",
        description="Create a new file with content.",
        required_fields=("filename", "content"),
        optional_fields=(),
        risk="warning",
    ),
    "create_folder": ToolSpec(
        name="create_folder",
        description="Create a new folder.",
        required_fields=("filename",),
        optional_fields=(),
        risk="warning",
    ),
    "write_to_file": ToolSpec(
        name="write_to_file",
        description="Append or write text to an existing file.",
        required_fields=("filename", "content"),
        optional_fields=(),
        risk="warning",
    ),
    "open_app": ToolSpec(
        name="open_app",
        description="Open an app, optionally with a web URL.",
        required_fields=("app_name",),
        optional_fields=("url",),
        risk="normal",
    ),
    "search_web": ToolSpec(
        name="search_web",
        description="Search the web in the default browser.",
        required_fields=("search_query",),
        optional_fields=(),
        risk="normal",
    ),
    "type_text": ToolSpec(
        name="type_text",
        description="Type into the currently focused app.",
        required_fields=("text_to_type",),
        optional_fields=(),
        risk="warning",
    ),
    "type_in_window": ToolSpec(
        name="type_in_window",
        description="Focus a named window and type into it.",
        required_fields=("window_title", "text_to_type"),
        optional_fields=(),
        risk="warning",
    ),
    "press_hotkey": ToolSpec(
        name="press_hotkey",
        description="Send a hotkey or keystroke to the focused app.",
        required_fields=("keys",),
        optional_fields=(),
        risk="warning",
    ),
    "press_hotkey_in_window": ToolSpec(
        name="press_hotkey_in_window",
        description="Focus a named window and send a hotkey or keystroke.",
        required_fields=("window_title", "keys"),
        optional_fields=(),
        risk="warning",
    ),
    "click_at": ToolSpec(
        name="click_at",
        description="Click at screen coordinates.",
        required_fields=("x", "y"),
        optional_fields=("button", "clicks"),
        risk="warning",
    ),
    "click_window": ToolSpec(
        name="click_window",
        description="Click inside a named window.",
        required_fields=("window_title",),
        optional_fields=("x", "y", "button", "clicks"),
        risk="warning",
    ),
    "focus_window": ToolSpec(
        name="focus_window",
        description="Bring a named window to the front.",
        required_fields=("window_title",),
        optional_fields=(),
        risk="normal",
    ),
    "window_state": ToolSpec(
        name="window_state",
        description="Minimize, maximize, restore, or close a named window.",
        required_fields=("window_title", "window_state"),
        optional_fields=(),
        risk="warning",
    ),
    "active_window": ToolSpec(
        name="active_window",
        description="Describe the currently active window.",
        required_fields=(),
        optional_fields=(),
        risk="normal",
    ),
    "list_windows": ToolSpec(
        name="list_windows",
        description="List visible titled windows.",
        required_fields=(),
        optional_fields=(),
        risk="normal",
    ),
    "background_status": ToolSpec(
        name="background_status",
        description="Report whether a heavy background task is running.",
        required_fields=(),
        optional_fields=(),
        risk="normal",
    ),
    "background_cancel": ToolSpec(
        name="background_cancel",
        description="Stop a heavy background task.",
        required_fields=(),
        optional_fields=(),
        risk="warning",
    ),
    "focus_mode_start": ToolSpec(
        name="focus_mode_start",
        description="Start focus mode for a duration.",
        required_fields=(),
        optional_fields=("duration_minutes", "duration_seconds"),
        risk="normal",
    ),
    "focus_mode_status": ToolSpec(
        name="focus_mode_status",
        description="Report focus mode status.",
        required_fields=(),
        optional_fields=(),
        risk="normal",
    ),
    "focus_mode_stop": ToolSpec(
        name="focus_mode_stop",
        description="Stop focus mode.",
        required_fields=(),
        optional_fields=(),
        risk="normal",
    ),
    "unsupported": ToolSpec(
        name="unsupported",
        description="Use only if a safe supported action cannot be determined.",
        required_fields=(),
        optional_fields=(),
        risk="normal",
    ),
    "delete_item": ToolSpec(
        name="delete_item",
        description="Move a file or folder to the Recycle Bin.",
        required_fields=("filename",),
        optional_fields=(),
        risk="warning",
    ),
    "play_music": ToolSpec(
        name="play_music",
        description="Play music via YouTube or Spotify.",
        required_fields=("search_query",),
        optional_fields=("platform",),
        risk="normal",
    ),
}


# These are the only action types with a real ActionExecutor dispatch path today.
# Future capability definitions remain in TOOLS but are not planner-visible.
IMPLEMENTED_TOOL_NAMES: frozenset[str] = frozenset({
    "manage_package",
    "run_command",
    "create_file",
    "create_folder",
    "write_to_file",
    "open_app",
    "search_web",
    "delete_item",
    "play_music",
    "unsupported",
})

ACTIVE_TOOL_NAMES: frozenset[str] = frozenset({
    "open_app",
    "search_web",
    "play_music",
    "delete_item",
    "unsupported",
})

ADMIN_TOOL_NAMES: frozenset[str] = IMPLEMENTED_TOOL_NAMES


def tool_names() -> list[str]:
    return sorted(TOOLS.keys())


def tool_union_string() -> str:
    return " | ".join(tool_names())


def tool_union_for(names: frozenset[str]) -> str:
    """Pipe-separated action_type union string for a specific allowlist."""
    return " | ".join(sorted(names))


def tool_schema_lines() -> str:
    lines: list[str] = []
    for name in tool_names():
        spec = TOOLS[name]
        req = ", ".join(spec.required_fields) if spec.required_fields else "(none)"
        opt = ", ".join(spec.optional_fields) if spec.optional_fields else "(none)"
        implementation = "implemented" if name in IMPLEMENTED_TOOL_NAMES else "planned"
        lines.append(
            f"- {name}: {spec.description} Required: {req}. Optional: {opt}. "
            f"Risk: {spec.risk}. Status: {implementation}."
        )
    return "\n".join(lines)


def tool_schema_for(names: frozenset[str]) -> str:
    """Schema lines restricted to an explicit executable allowlist."""
    lines: list[str] = []
    for name in sorted(names):
        if name not in IMPLEMENTED_TOOL_NAMES:
            continue
        spec = TOOLS[name]
        req = ", ".join(spec.required_fields) if spec.required_fields else "(none)"
        opt = ", ".join(spec.optional_fields) if spec.optional_fields else "(none)"
        lines.append(
            f"- {name}: {spec.description} Required: {req}. Optional: {opt}. Risk: {spec.risk}."
        )
    return "\n".join(lines)
