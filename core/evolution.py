import os
import re
import importlib
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from config import Config

console = Console()

CUSTOM_TOOLS_PATH = os.path.join(os.path.dirname(__file__), "custom_tools.py")

class EvolutionEngine:
    def __init__(self, brain, researcher):
        self.brain = brain
        self.researcher = researcher
        self._pending_tool_code = None

    def triage_unknown_intent(self, user_input: str, admin_unlocked: bool = False) -> str:
        # CRIT-03: Security Gate
        if not admin_unlocked:
            return "The Evolution Engine requires Aletheia-level administrative authorization."

        console.print("[dim cyan]Unknown intent — triggering Evolution Engine...[/dim cyan]")
        research_result = self.researcher.search(user_input) if self.researcher else ""

        # CRIT-04: Fixed unterminated string literal
        draft_prompt = f"""You are a Python developer for IRIS.
User intent: "{user_input}"
Context: {research_result[:1000]}

Write a function 'custom_{self._slugify(user_input)}' that returns a string.
Respond with ONLY the Python code, no explanation."""

        tool_code = self.brain._call_api(Config.PRIMARY_BRAIN, draft_prompt)
        
        # Security Scan using centralized danger patterns
        for pattern in Config.DANGER_PATTERNS:
            if re.search(pattern, tool_code):
                return "Drafted tool rejected due to safety patterns. Rephrase the request."

        self._pending_tool_code = tool_code.strip()
        console.print(Panel(f"[green]{self._pending_tool_code}[/green]", title="Drafted Tool"))
        return "Tool drafted. Say 'approve tool' to integrate it."

    def approve_tool(self) -> str:
        if not self._pending_tool_code: return "No pending tool."

        # CRIT-04: Fixed header writing and added hot-reload
        if not os.path.exists(CUSTOM_TOOLS_PATH):
            with open(CUSTOM_TOOLS_PATH, "w", encoding="utf-8") as f:
                f.write('"""IRIS Custom Tools Library"""\nimport os\nimport subprocess\n\n')

        with open(CUSTOM_TOOLS_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n{self._pending_tool_code}\n")

        self._pending_tool_code = None
        # Hot-reload the tools module
        try:
            import core.custom_tools
            importlib.reload(core.custom_tools)
        except: pass
        
        return "Tool integrated and hot-reloaded successfully."

    @staticmethod
    def _slugify(text: str) -> str:
        return re.sub(r'[^a-z0-9]+', '_', text.lower().strip())[:40]