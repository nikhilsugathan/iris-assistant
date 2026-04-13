import os
from rich.console import Console

console = Console()

# ─────────────────────────────────────────────────────────────
# DATABASE OF GOLD MASTER CODE
# ─────────────────────────────────────────────────────────────

FILES = {
    "main.py": """# (Insert finalized main.py v4.6 code here)""",
    "core/brain.py": """# (Insert finalized brain.py v4.6 code here)""",
    "core/voice.py": """# (Insert finalized voice.py v4.3 code here)""",
    "core/memory.py": """# (Insert finalized memory.py v4.6 code here)""",
    "tools/cleaner.py": """# (Insert finalized cleaner.py code here)"""
}

def deploy():
    console.print("[bold cyan]IRIS Deployment Engine v4.6 Starting...[/bold cyan]")
    
    # Ensure directories exist
    for folder in ["core", "tools"]:
        if not os.path.exists(folder):
            os.makedirs(folder)
            console.print(f"[dim]  + Created directory: {folder}[/dim]")

    # Write files
    for path, content in FILES.items():
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content.strip())
            console.print(f"[bold green]✓ Deployed:[/bold green] {path}")
        except Exception as e:
            console.print(f"[bold red]FAILED:[/bold red] {path} - {e}")

    console.print("\n[bold magenta]IRIS is now fully updated and synchronized.[/bold magenta]")
    console.print("Run 'python main.py' to begin.")

if __name__ == "__main__":
    deploy()