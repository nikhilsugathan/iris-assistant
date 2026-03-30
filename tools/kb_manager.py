import json
import os
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

class KnowledgeManager:
    def __init__(self, kb_path="knowledge_base.json"):
        self.kb_path = kb_path

    def view_knowledge(self):
        """Displays all harvested knowledge in a formatted table."""
        if not os.path.exists(self.kb_path):
            console.print("[yellow]No knowledge base found. IRIS hasn't learned anything yet.[/yellow]")
            return

        with open(self.kb_path, 'r') as f:
            data = json.load(f)

        if not data:
            console.print("[yellow]Knowledge base is empty.[/yellow]")
            return

        table = Table(title="IRIS Autonomous Knowledge Base", border_style="cyan")
        table.add_column("Fact/Key", style="bold magenta")
        table.add_column("Stored Value", style="white")

        for key, value in data.items():
            table.add_row(str(key), str(value))

        console.print(table)

    def wipe_knowledge(self):
        """Completely clears the knowledge base."""
        if os.path.exists(self.kb_path):
            os.remove(self.kb_path)
            console.print(Panel("[bold red]LOGIC PURGE COMPLETE:[/bold red] All autonomous memory has been erased.", border_style="red"))
        else:
            console.print("[yellow]Nothing to wipe.[/yellow]")

    def delete_fact(self, key_to_delete):
        """Deletes a specific key from the knowledge base."""
        if not os.path.exists(self.kb_path): return

        with open(self.kb_path, 'r') as f:
            data = json.load(f)

        if key_to_delete in data:
            del data[key_to_delete]
            with open(self.kb_path, 'w') as f:
                json.dump(data, f, indent=4)
            console.print(f"[green]Fact '{key_to_delete}' has been forgotten.[/green]")
        else:
            console.print(f"[red]Fact '{key_to_delete}' not found.[/red]")