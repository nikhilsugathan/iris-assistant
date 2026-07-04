"""Command and filesystem result verification plus action-plan hardening."""

from __future__ import annotations

import os

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

        try:
            if action_type in {"manage_package", "run_command"}:
                result = self._run_command(plan)
                success = str(result or "").strip().lower().startswith("done.")
                return result, success

            if action_type == "create_file":
                result = self._create_file(plan)
                # Asking the user to disambiguate an extension is a valid deferred
                # executor state, not a failed file creation. Returning success here
                # prevents the improv engine from overwriting the clarification flow.
                if self.waiting_for_clarification():
                    return result, True
                current_path = getattr(self, "last_action_path", None)
                success = (
                    isinstance(result, str)
                    and " created." in result
                    and bool(current_path)
                    and os.path.isfile(current_path)
                )
                return result, success

            if action_type == "create_folder":
                result = self._create_folder(plan)
                current_path = getattr(self, "last_action_path", None)
                success = (
                    str(result or "").strip() == "Done."
                    and bool(current_path)
                    and os.path.isdir(current_path)
                )
                return result, success

            return original_execute_with_verify(self, plan)
        except Exception as exc:
            self._log(f"EXCEPTION: {action_type} - {exc}")
            return f"That didn't work: {str(exc)[:100]}", False

    executor_cls._execute_with_verify = _execute_with_verify_hardened
    executor_cls._iris_executor_verification_hardening_applied = True
    executor_cls._iris_filesystem_verification_hardening_applied = True
