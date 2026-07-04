"""Canonical Windows path handling for SecurityGuard protected-path checks."""

from __future__ import annotations

import ntpath
import os
import re


_WINDOWS_ENV_RE = re.compile(r"%([^%]+)%")
_PROTECTED_ROOT_TEXT = (
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData",
    r"%APPDATA%",
    r"%LOCALAPPDATA%",
)


def _expand_windows_env(value: str) -> str:
    expanded = os.path.expandvars(value)

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        return os.environ.get(name, match.group(0))

    return _WINDOWS_ENV_RE.sub(_replace, expanded)


def normalize_guard_path(path: str) -> str:
    expanded = _expand_windows_env(str(path or "").strip())
    expanded = os.path.expanduser(expanded)
    if not expanded:
        return ""

    if re.match(r"^[A-Za-z]:[\\/]", expanded) or expanded.startswith("\\\\"):
        normalized = ntpath.normpath(expanded.replace("/", "\\"))
        return ntpath.normcase(normalized).rstrip("\\").lower()

    normalized = os.path.abspath(os.path.normpath(expanded))
    return os.path.normcase(normalized).rstrip("\\/").lower()


def apply_security_path_hardening(security_module) -> None:
    guard_cls = getattr(security_module, "SecurityGuard", None)
    if guard_cls is None or getattr(guard_cls, "_iris_path_hardening_applied", False):
        return

    protected_roots = tuple(
        root
        for root in (normalize_guard_path(value) for value in _PROTECTED_ROOT_TEXT)
        if root and "%" not in root
    )

    # The base assess implementation uses startswith(). Supplying roots with a
    # trailing separator makes that comparison boundary-aware for descendants.
    security_module._normalize_guard_path = normalize_guard_path
    security_module._PROTECTED_PATH_PREFIXES = tuple(root + "\\" for root in protected_roots)

    original_assess = guard_cls.assess

    def _assess_path_hardened(self, plan: dict, admin_unlocked: bool = False):
        action = plan.get("action_type", "")
        if not admin_unlocked and action in security_module._PATH_GATED_ACTIONS:
            target = plan.get("filename", "") or plan.get("command", "")
            target_norm = normalize_guard_path(target)
            if target_norm and target_norm in protected_roots:
                return security_module.BLOCKED, (
                    f"'{action}' targeting a protected system path is restricted "
                    "in public IRIS mode. Activate Aletheia admin mode to "
                    "operate on system directories."
                )
        return original_assess(self, plan, admin_unlocked=admin_unlocked)

    guard_cls.assess = _assess_path_hardened
    guard_cls._iris_path_hardening_applied = True
