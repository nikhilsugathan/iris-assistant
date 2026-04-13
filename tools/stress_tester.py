import json
import time
from rich.console import Console
from rich.table import Table
from main import handle_user_input # Import the core router

console = Console()

class IRIS_QA:
    def __init__(self, iris_components):
        self.components = iris_components # voice, brain, executor, etc.
        self.results = []

    def run_suite(self, suite_path):
        with open(suite_path, 'r') as f:
            tests = json.load(f)

        for test in tests:
            console.print(f"\n[bold yellow]RUNNING TEST:[/bold yellow] {test['name']}")
            start_time = time.time()
            
            try:
                # We call handle_user_input directly, bypassing voice/UI
                # This feeds the 'input' into the routing logic
                response, _ = handle_user_input(
                    test['input'], 
                    *self.components
                )
                duration = time.time() - start_time
                self.results.append({
                    "name": test['name'],
                    "status": "PASS" if response else "FAIL",
                    "time": f"{duration:.2f}s",
                    "output": str(response)[:50] + "..."
                })
            except Exception as e:
                self.results.append({"name": test['name'], "status": "CRASH", "error": str(e)})

    def display_report(self):
        table = Table(title="IRIS v5.0 Stress Test Report")
        table.add_column("Mission", style="cyan")
        table.add_column("Status", style="bold green")
        table.add_column("Time", style="magenta")
        table.add_column("Output Preview", style="white")

        for r in self.results:
            table.add_row(r['name'], r['status'], r.get('time', 'N/A'), r.get('output', 'N/A'))
        
        console.print(table)