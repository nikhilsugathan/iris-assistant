import json
import time
from rich.console import Console
from rich.table import Table
from main import handle_user_input 

console = Console()

def run_qa_analysis(components):
    """
    Simulates a high-speed batch of user inputs.
    Components: (voice, autocorrect, executor, copilot, brain, etc.)
    """
    with open('tests/stress_suite.json', 'r') as f:
        suite = json.load(f)

    report = Table(title="IRIS v5.0 Performance Analysis", border_style="magenta")
    report.add_column("Module Test", style="bold cyan")
    report.add_column("Latency", style="yellow")
    report.add_column("Result", style="green")

    for test in suite:
        console.print(f"[bold yellow]Testing:[/bold yellow] {test['name']}")
        start = time.time()
        try:
            # Feeds input directly into the main routing logic
            response, _ = handle_user_input(test['input'], *components)
            elapsed = time.time() - start
            report.add_row(test['name'], f"{elapsed:.2f}s", "PASS")
        except Exception as e:
            report.add_row(test['name'], "ERROR", str(e)[:30])

    console.print(report)