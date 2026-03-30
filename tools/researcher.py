"""
IRIS Researcher
===============
Live web search via DuckDuckGo — synthesizes results using the Primary Brain.
"""

from duckduckgo_search import DDGS
from rich.console import Console
from config import Config

console = Console()

class Researcher:
    def __init__(self, brain):
        self.brain = brain
        self._ddgs = DDGS()  # persistent instance — avoids context-manager bug

    def search(self, query: str) -> str:
        """Fetches live web data and synthesizes it via the Primary Brain."""
        try:
            results = list(self._ddgs.text(query, max_results=3))  # list() forces evaluation

            if not results:
                return "I searched the web but couldn't find any relevant information."

            web_context = "\n".join([
                f"Source: {r.get('href', '')}\nTitle: {r.get('title', '')}\nSnippet: {r.get('body', '')}"
                for r in results
            ])

            summary_prompt = f"""USER QUERY: {query}
WEB SEARCH DATA:
{web_context}

TASK: Synthesize the web data into a crisp, accurate answer.
If the data is conflicting, prioritize newer information."""

            return self.brain._call_api(Config.PRIMARY_BRAIN, summary_prompt)
        except Exception as e:
            return f"Research failed: {str(e)}"