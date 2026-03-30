from duckduckgo_search import DDGS
from rich.console import Console
from config import Config

console = Console()

class Researcher:
    def __init__(self, brain):
        self.brain = brain

    def search(self, query: str) -> str:
        """Fetches live web data and synthesizes it via the Primary Brain."""
        with console.status(f"[bold green]Searching for '{query}'...[/bold green]"):
            try:
                with DDGS() as ddgs:
                    results = [r for r in ddgs.text(query, max_results=3)]
                
                if not results:
                    return "I searched the web but couldn't find any relevant information."

                # Format the context for the brain
                web_context = "\n".join([f"Source: {r['title']}\nSnippet: {r['body']}" for r in results])
                
                summary_prompt = f"""
                USER QUERY: {query}
                WEB SEARCH DATA:
                {web_context}

                TASK: Synthesize the web data into a crisp, formidable answer. 
                If the data is conflicting, prioritize newer information.
                """
                
                return self.brain._call_api(Config.PRIMARY_BRAIN, summary_prompt)
            except Exception as e:
                return f"Research failed: {str(e)}"