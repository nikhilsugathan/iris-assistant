from __future__ import annotations


def test_parent_segments_cannot_bypass_protected_windows_path_gate():
    import core  # noqa: F401
    from core.security import BLOCKED, SecurityGuard

    guard = SecurityGuard(brain=None)
    verdict, _message = guard.assess(
        {
            "action_type": "delete_item",
            "filename": r"C:\Users\Nikhil\Desktop\..\..\..\Windows\System32",
        },
        admin_unlocked=False,
    )

    assert verdict == BLOCKED


def test_similar_sibling_name_is_not_treated_as_windows_directory_child():
    import core  # noqa: F401
    from core.security import SAFE, SecurityGuard

    guard = SecurityGuard(brain=None)
    verdict, _message = guard.assess(
        {
            "action_type": "delete_item",
            "filename": r"C:\WindowsOld\example.txt",
        },
        admin_unlocked=False,
    )

    assert verdict == SAFE


def test_security_path_hardening_is_loaded():
    import core  # noqa: F401
    from core.security import SecurityGuard

    assert getattr(SecurityGuard, "_iris_path_hardening_applied", False)
