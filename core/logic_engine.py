"""
Aletheia Logical Engine
=======================
Handles high-complexity reasoning tasks by forcing a multi-step 
Chain-of-Thought (CoT) process.
"""

from rich.panel import Panel
from rich.console import Console
from config import Config

console = Console()

class LogicalEngine:
    def __init__(self, brain):
        self.brain = brain

    def reason(self, problem: str, context: str = "") -> str:
        """Runs a multi-step logical deliberation using the Deep Brain."""
        
        logic_prompt = f"""
        [LOGIC GATE: ACTIVE]
        TASK: Analyze this problem with 100% precision.
        
        PROBLEM: "{problem}"
        CONTEXT: {context}
        
        REQUIRED:
        1. DECONSTRUCTION: Break the problem into variables.
        2. VERIFICATION: Check for fallacies or edge cases.
        3. SYNTHESIS: Formulate the most efficient solution.
        
        THINKING PROCESS: Show monologue inside <think> tags.
        """

        # FIX: Removed nested console.status — main.py already wraps this call
        # with its own spinner, so nesting two Rich spinners caused visual corruption.
        # FIX: Use API key "ollama_smart" instead of the raw model name string
        # (e.g. "deepseek-r1:8b"), which caused _call_api to return None.
        response = self.brain._call_api(Config.PRIMARY_BRAIN, logic_prompt)

        # FIX: Guard against a None / empty response from the engine.
        if not response:
            return "The reasoning engine returned no response. Check Ollama connectivity."

        if "<think>" in response:
            parts = response.split("</think>")
            thinking_trace = parts[0].replace("<think>", "").strip()
            final_answer = parts[1].strip() if len(parts) > 1 else ""
            
            console.print(Panel(
                f"[dim]{thinking_trace}[/dim]", 
                title="[bold magenta]Aletheia Internal Monologue[/bold magenta]", 
                border_style="magenta"
            ))
            # FIX: Fall back to the thinking trace when the model produces no
            # post-</think> text, instead of silently returning an empty string.
            return final_answer if final_answer else thinking_trace
        
        return response
