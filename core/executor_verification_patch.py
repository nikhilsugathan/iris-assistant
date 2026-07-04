"""Command result verification and AI action-plan hardening."""

from __future__ import annotations

from . import improv as _improv_module
from .action_plan_hardening import apply_action_plan_hardening


def apply_executor_verification_patch(executor_module) -> None:
    apply_action_plan_hardening(executor_module, _improv_module)

    executor_cls = getattr(executor_module, "ActionExecutor", None)
    if executor_cls is None or getattr(executor_cls, "_iris_executor_verification_hardening_applied", False):
        return

    original_execute_with_verify = executor_cls._execute_with_verify

    def _execute_with_verify_hardened(self, plan: dict) -> tuple:
        action_type = plan.get("action_type")
        if action_type not in {"manage_package", "run_command"}:
            return original_execute_with_verify(self, plan)

        try:
            result = self._run_command(plan)
            success = str(result or "").strip().lower().startswith("done.")
            return result, success
        except Exception as exc:
            self._log(f"EXCEPTION: {action_type} - {exc}")
            return f"That didn't work: {str(exc)[:100]}", False

    executor_cls._execute_with_verify = _execute_with_verify_hardened
    executor_cls._iris_executor_verification_hardening_applied = True
