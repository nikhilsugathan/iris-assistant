"""Validation and security reassessment for AI-generated action plans."""

from __future__ import annotations

import re

from .security import BLOCKED, NEED_ADMIN, SAFE, WARNING
from .tools_registry import ACTIVE_TOOL_NAMES, ADMIN_TOOL_NAMES, TOOLS


_EXACT_PLAN_CHOICES = {
    "a": "plan_a",
    "plan a": "plan_a",
    "option a": "plan_a",
    "first": "plan_a",
    "first one": "plan_a",
    "the first": "plan_a",
    "the first one": "plan_a",
    "b": "plan_b",
    "plan b": "plan_b",
    "option b": "plan_b",
    "second": "plan_b",
    "second one": "plan_b",
    "the second": "plan_b",
    "the second one": "plan_b",
    "c": "plan_c",
    "plan c": "plan_c",
    "option c": "plan_c",
    "third": "plan_c",
    "third one": "plan_c",
    "the third": "plan_c",
    "the third one": "plan_c",
    "nuclear": "plan_c",
    "powerful": "plan_c",
    "extraordinary": "plan_c",
}

_AFFIRMATIVE_PLAN_A = {
    "yes",
    "yeah",
    "yep",
    "ok",
    "okay",
    "sure",
    "go ahead",
    "do it",
}

_CANCEL_CHOICES = {
    "cancel",
    "never mind",
    "nevermind",
    "forget it",
    "no",
    "nope",
    "stop",
}

_EMPTY_REQUIRED_ALLOWED = {"content"}


def _normalize(text: str) -> str:
    value = str(text or "").lower().replace("’", "'")
    value = re.sub(r"[^a-z0-9']+", " ", value)
    value = value.replace("'", " ")
    return re.sub(r"\s+", " ", value).strip()


def _allowed_tools(admin_unlocked: bool):
    return ADMIN_TOOL_NAMES if admin_unlocked else ACTIVE_TOOL_NAMES


def validate_action_plan(plan, *, admin_unlocked: bool) -> tuple[bool, str]:
    if not isinstance(plan, dict):
        return False, "plan is not an object"

    action_type = str(plan.get("action_type") or "").strip()
    allowed = _allowed_tools(admin_unlocked)
    if action_type not in allowed:
        return False, f"action type '{action_type or 'missing'}' is not allowed in this mode"

    spec = TOOLS.get(action_type)
    if spec is None:
        return False, f"action type '{action_type}' is not registered"

    for field in spec.required_fields:
        if field not in plan:
            return False, f"required field '{field}' is missing"
        if field not in _EMPTY_REQUIRED_ALLOWED:
            value = plan.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                return False, f"required field '{field}' is empty"

    if action_type == "open_app" and plan.get("command") and not plan.get("app_name"):
        return False, "open_app cannot substitute a shell command for app_name"

    return True, ""


def apply_action_plan_hardening(executor_module, improv_module) -> None:
    executor_cls = getattr(executor_module, "ActionExecutor", None)
    improv_cls = getattr(improv_module, "ImprovEngine", None)

    if improv_cls is not None and not getattr(improv_cls, "_iris_plan_selection_hardening_applied", False):
        def _select_plan_hardened(self, plans: dict, user_choice: str):
            if not isinstance(plans, dict):
                return None

            text = _normalize(user_choice)
            exact = _EXACT_PLAN_CHOICES.get(text)
            if exact:
                return plans.get(exact)
            if text in _AFFIRMATIVE_PLAN_A:
                return plans.get("plan_a")

            for plan_key in ("plan_a", "plan_b", "plan_c"):
                plan = plans.get(plan_key, {})
                if not isinstance(plan, dict):
                    continue
                description = _normalize(plan.get("description", ""))
                app = _normalize(plan.get("app_name", ""))
                search_query = _normalize(plan.get("search_query", ""))

                distinctive = {
                    word
                    for word in description.split()
                    if len(word) >= 6
                }
                if distinctive and any(
                    f" {word} " in f" {text} "
                    for word in distinctive
                ):
                    return plan
                if app and app in text:
                    return plan
                if search_query and search_query in text:
                    return plan
            return None

        improv_cls.select_plan = _select_plan_hardened
        improv_cls._iris_plan_selection_hardening_applied = True

    if executor_cls is None or getattr(executor_cls, "_iris_action_plan_hardening_applied", False):
        return

    original_ai_plan = executor_cls._ai_plan
    original_plan_action = executor_cls.plan_action

    def _ai_plan_validated(self, user_input: str, admin_unlocked: bool = False):
        plan = original_ai_plan(self, user_input, admin_unlocked=admin_unlocked)
        if plan is None:
            return None
        valid, reason = validate_action_plan(plan, admin_unlocked=admin_unlocked)
        if not valid:
            self._log(f"AI PLAN REJECTED: {reason}")
            return None
        return plan

    def _plan_action_track_mode(self, user_input: str, admin_unlocked: bool = False):
        self._iris_plan_admin_unlocked = bool(admin_unlocked)
        return original_plan_action(self, user_input, admin_unlocked=admin_unlocked)

    def _handle_plan_choice_hardened(self, user_input: str):
        plans = self.pending_plans
        if not plans:
            return None

        normalized = _normalize(user_input)
        if normalized in _CANCEL_CHOICES:
            self.pending_plans = None
            return "Cancelled."

        selected = self.improv.select_plan(plans, user_input)
        if not selected:
            plan_a = plans.get("plan_a", {}).get("description", "?")
            plan_b = plans.get("plan_b", {}).get("description", "?")
            plan_c = plans.get("plan_c", {}).get("description", "?")
            return f"Which one - A: {plan_a}, B: {plan_b}, or C: {plan_c}?"

        admin_unlocked = bool(getattr(self, "_iris_plan_admin_unlocked", False))
        valid, reason = validate_action_plan(selected, admin_unlocked=admin_unlocked)
        if not valid:
            self._log(f"IMPROV PLAN REJECTED: {reason}")
            self.pending_plans = None
            return "I rejected that recovery plan because it did not match the allowed action schema."

        verdict, security_msg = self.security.assess(
            selected,
            admin_unlocked=admin_unlocked,
        )
        if verdict == BLOCKED:
            self._log(f"IMPROV PLAN BLOCKED: {security_msg}")
            self.pending_plans = None
            self.pending_action = None
            self.pending_verdict = None
            return f"Security refusal.\n{security_msg}"

        self.pending_plans = None
        self.pending_action = selected
        if selected.get("requires_permission") and verdict == SAFE:
            verdict = WARNING
        self.pending_verdict = verdict

        if self._is_simple_task(selected, verdict):
            return self._execute_pending()

        permission_msg = self._build_permission_request(selected)
        if verdict in {WARNING, NEED_ADMIN} and security_msg:
            return f"{self._build_security_header(verdict)}\n{security_msg}\n\n{permission_msg}"
        return permission_msg

    executor_cls._ai_plan = _ai_plan_validated
    executor_cls.plan_action = _plan_action_track_mode
    executor_cls.handle_plan_choice = _handle_plan_choice_hardened
    executor_cls._iris_action_plan_hardening_applied = True
