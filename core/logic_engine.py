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

        with console.status("[bold magenta]Engaging Logical Engine...[/bold magenta]"):
            # Route specifically to the smart/deep model
            model = getattr(Config, "OLLAMA_MODEL_DEEP", "deepseek-r1:8b")
            response = self.brain._call_api(model, logic_prompt)

        if "<think>" in response:
            parts = response.split("</think>")
            thinking_trace = parts[0].replace("<think>", "").strip()
            final_answer = parts[1].strip() if len(parts) > 1 else ""
            
            console.print(Panel(
                f"[dim]{thinking_trace}[/dim]", 
                title="[bold magenta]Aletheia Internal Monologue[/bold magenta]", 
                border_style="magenta"
            ))
            return final_answer
        
        return response