"""
IRIS Improvisation Engine
==========================
When a direct action fails or has multiple valid approaches,
Iris doesn't just error — she improvises.

PLAN STRUCTURE:
  Plan A — Safest, most standard approach (just does it)
  Plan B — Alternative method, slightly more involved (just does it)
  Plan C — Powerful/extraordinary/elevated approach (requires explicit yes)

EXAMPLES:

  User: "play me some music"
  Plan A: Open YouTube Music in browser         ← just does it
  Plan B: Open Spotify in browser               ← just does it
  Plan C: Install Spotify desktop app via winget ← asks permission

  User: "I can't access this website"
  Plan A: Open it in Edge instead of Chrome     ← just does it
  Plan B: Clear DNS cache and retry             ← just does it
  Plan C: Flush DNS + reset network adapter     ← asks permission (system change)

  User: "delete this folder" (fails - permission denied)
  Plan A: Try with current permissions          ← tried, failed
  Plan B: Take ownership first then delete      ← just does it
  Plan C: Force delete via admin PowerShell     ← asks permission (destructive)
"""

from __future__ import annotations

import json
from typing import Optional
from config import Config


class ImprovEngine:

    def __init__(self, brain):
        self.brain = brain

    # ─────────────────────────────────────────────────────────────
    # MAIN: Generate plans for any request or failure
    # ─────────────────────────────────────────────────────────────

    def generate_plans(
        self,
        user_request: str,
        failed_plan: dict = None,
        error_msg: str = None,
    ) -> dict:
        """
        Generate Plan A, B, C for a request.

        Returns:
        {
            "plan_a": { action plan dict },
            "plan_b": { action plan dict },
            "plan_c": { action plan dict, "requires_permission": True },
            "summary": "One line spoken summary of the three options"
        }
        """
        context = ""
        if failed_plan:
            context = f"""
Previous attempt failed:
  Action: {failed_plan.get('description', '?')}
  Command: {failed_plan.get('command', '?')}
  Error: {error_msg or 'unknown'}
"""

        prompt = f"""You are Iris's improvisation engine. Generate three plans to handle this request.

User request: "{user_request}"
{context}

Generate three distinct approaches:
- Plan A: Safest, most standard method. Should work reliably.
- Plan B: Alternative method using a different tool or approach.
- Plan C: Powerful or extraordinary method. May require admin rights, 
          system changes, or have side effects. Mark as requires_permission=true.

Respond ONLY with this JSON structure:
{{
  "plan_a": {{
    "action_type": "run_command | create_file | create_folder | open_app | search_web | install_package | write_to_file",
    "description": "one sentence plain English",
    "command": "exact Windows command if needed",
    "filename": "full path if file/folder operation",
    "content": "",
    "app_name": "",
    "url": "direct URL if opening browser",
    "search_query": "",
    "is_dangerous": false,
    "requires_permission": false
  }},
  "plan_b": {{
    "action_type": "...",
    "description": "one sentence plain English",
    "command": "",
    "filename": "",
    "content": "",
    "app_name": "",
    "url": "",
    "search_query": "",
    "is_dangerous": false,
    "requires_permission": false
  }},
  "plan_c": {{
    "action_type": "...",
    "description": "one sentence plain English — more powerful approach",
    "command": "",
    "filename": "",
    "content": "",
    "app_name": "",
    "url": "",
    "search_query": "",
    "is_dangerous": true,
    "requires_permission": true
  }},
  "summary": "One spoken sentence describing the three options briefly"
}}

Rules:
- Plan A and B should be safe and auto-executable
- Plan C should be the nuclear option — admin commands, force operations, 
  system-level changes, or something that has real side effects
- Use Windows-specific commands (winget, PowerShell, cmd)
- All paths must use backslashes
- summary should sound natural when spoken aloud, e.g.:
  "I can try YouTube Music, Spotify, or install the Spotify app — which works for you?"
  "Standard delete, take ownership first, or force-delete as admin — pick one."

Respond with ONLY the JSON. No explanation."""

        response = self.brain._call_api(
            Config.PRIMARY_BRAIN, prompt
        )

        if not response:
            return None

        try:
            clean = response.strip().replace("```json", "").replace("```", "").strip()
            plans = json.loads(clean)
            return plans
        except Exception:
            return None

    def format_spoken_options(self, plans: dict) -> str:
        """
        Format plans as a natural spoken response.
        Returns what Iris says out loud.
        """
        if not plans:
            return "I couldn't think of a way to do that."

        summary = plans.get("summary", "")
        if summary:
            return summary

        # Fallback: build from plan descriptions
        a = plans.get("plan_a", {}).get("description", "")
        b = plans.get("plan_b", {}).get("description", "")
        c = plans.get("plan_c", {}).get("description", "")

        parts = []
        if a: parts.append(f"Plan A: {a}")
        if b: parts.append(f"Plan B: {b}")
        if c: parts.append(f"or {c} — that one needs your go-ahead")

        return ". ".join(parts) + "." if parts else "I have a few options — want me to list them?"

    def select_plan(self, plans: dict, user_choice: str) -> Optional[dict]:
        """
        Parse user's choice from voice input.
        Returns the selected plan dict or None.
        """
        text = (user_choice or "").lower().strip()

        # Explicit plan selection
        if any(x in text for x in ["plan a", "option a", "first", "first one", "a"]):
            return plans.get("plan_a")
        if any(x in text for x in ["plan b", "option b", "second", "second one", "b"]):
            return plans.get("plan_b")
        if any(x in text for x in ["plan c", "option c", "third", "third one", "c",
                                     "nuclear", "powerful", "extraordinary", "go for it"]):
            return plans.get("plan_c")

        # Natural language hints
        plan_a = plans.get("plan_a", {})
        plan_b = plans.get("plan_b", {})
        plan_c = plans.get("plan_c", {})

        for plan in [plan_a, plan_b, plan_c]:
            desc = plan.get("description", "").lower()
            app  = plan.get("app_name", "").lower()
            url  = plan.get("url", "").lower()
            # If user mentions something from the plan description
            key_words = [w for w in desc.split() if len(w) > 4]
            if any(kw in text for kw in key_words):
                return plan
            if app and app in text:
                return plan
            if url and any(part in text for part in url.split(".")):
                return plan

        # Default to plan A if they say yes/ok/sure
        if any(x in text for x in ["yes", "ok", "okay", "sure", "go ahead", "do it", "yeah"]):
            return plans.get("plan_a")

        return None
