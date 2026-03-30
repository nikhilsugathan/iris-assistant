from duckduckgo_search import DDGS
from config import Config

class Researcher:
    def __init__(self, brain):
        self.brain = brain

    def search(self, query: str) -> str:
        """Fetches live web data and synthesizes it via the Primary Brain.
        NOTE: The caller (main.py) is responsible for wrapping this in a
        console.status spinner. Do NOT add one here — nested Rich live
        contexts corrupt the terminal display.
        """
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=3))

            if not results:
                return "I searched the web but couldn't find any relevant information."

            web_context = "\n".join(
                [f"Source: {r['title']}\nSnippet: {r['body']}" for r in results]
            )

            summary_prompt = f"""
            USER QUERY: {query}
            WEB SEARCH DATA:
            {web_context}

            TASK: Synthesize the web data into a crisp, formidable answer.
            If the data is conflicting, prioritize newer information.
            """

            # FIX: Normalize to lowercase — Config.PRIMARY_BRAIN defaults to
            # "GROQ" (uppercase) at startup. brain._call_api() checks lowercase
            # "groq", so the uppercase version hits no branch and returns None.
            api_provider = Config.PRIMARY_BRAIN.lower() if Config.PRIMARY_BRAIN else "groq"
            result = self.brain._call_api(api_provider, summary_prompt)
            return result or "I found results but couldn't synthesize them right now."
        except Exception as e:
            return f"Research failed: {str(e)}"