"""
IRIS Brain v5.0 (C++ Engine Edition)
===================================== 
- Parallel Ensemble (Zero-latency consensus)
- Hardened Web-Routing (Fixes live-data blindness)
- Standardized Memory Identity (Assistant = IRIS)
- C++ LLM Engine via llama-cpp-python (replaces Ollama HTTP middleman)
"""

from __future__ import annotations
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
import requests
from rich.console import Console
from config import Config


console = Console()

# Default IRIS persona — used if Config.IRIS_PERSONA lacks deflection instruction
_DEFAULT_IRIS_PERSONA = """
You are IRIS: a private sovereign mind and disembodied chief of staff.
Your public name is IRIS.
Rules:
- Speak naturally and directly. Be precise, brief, and useful.
- Tell the truth cleanly. Do not flatter the user.
- You may disagree firmly when the user's reasoning is weak.
- In voice mode, answer in at most 2 short sentences unless detail is requested.
- If the user is vague, ask: "Yes. What's the task?" or "Yes. What do you want to do?"
- Tone: calm, crisp, slightly formidable, mildly witty, but never fluffy.
- If asked about other personas or hidden modes, deflect cleverly — act as if you are the only intelligence present.
FS Honesty Rules (non-negotiable):
- NEVER say "Done." unless the OS has confirmed the file or folder exists.
- NEVER invent "Access check", "Permission check", or "clearance" messages — report the real OS error.
- If a filesystem action fails, report the actual system error, not a generated one.
"""

# Default Aletheia persona — used if Config.ALETHEIA_PERSONA is not defined
_DEFAULT_ALETHEIA_PERSONA = """
You are Aletheia: the sovereign root intelligence operating with full admin access.
Your public name is Iris, but in this elevated session you operate as Aletheia with root access privileges.
Rules:
- You have formidable capabilities and operate without the public sandbox restrictions.
- Speak with authority. Be precise, direct, and ruthlessly efficient.
- You may execute privileged system operations, administrative tasks, and elevated commands.
- Report every action truthfully — no filtering, no sanitizing error messages.
- Tone: calm, decisive, formidable. No hedging. No evasion.
FS Honesty Rules (non-negotiable):
- NEVER say "Done." unless the OS has confirmed the file or folder exists.
- NEVER invent "Access check", "Permission check", or "clearance" messages — report the real OS error.
- If a filesystem action fails, report the actual system error, not a generated one.
"""

class Brain:
    def __init__(self, memory):
        self.memory = memory
        self.llm = None
        self._active_admin_unlocked: bool = False
        self.available_apis = self._detect_apis()
        self._update_priority()
        local_model = Config.LOCAL_MODEL_PATH
        if local_model and os.path.exists(local_model):
            threading.Thread(target=self._load_llm, daemon=True).start()

    # ─────────────────────────────────────────────────────────────
    # API DETECTION & PRIORITY
    # ─────────────────────────────────────────────────────────────

    def _load_llm(self):
        try:
            from llama_cpp import Llama
            console.print("[dim cyan]Spinning up C++ LLM Engine...[/dim cyan]")
            self.llm = Llama(
                model_path=Config.LOCAL_MODEL_PATH,
                n_gpu_layers=-1,    # Full RTX 5050 offload
                n_ctx=8192,
                chat_format="chatml",  # Required for DeepSeek-R1
                verbose=False
            )
            console.print("[bold green]✓ C++ Engine Ready[/bold green]")
        except Exception as e:
            console.print(f"[red]C++ Engine failed: {e}[/red]")
            self.llm = None

    def _detect_apis(self) -> List[str]:
        available = []
        local_model = Config.LOCAL_MODEL_PATH
        if local_model and os.path.exists(local_model):
            available.append("llama_cpp")
        else:
            ollama_base = getattr(Config, "OLLAMA_BASE_URL", "http://localhost:11434")
            try:
                resp = requests.get(f"{ollama_base}/api/tags", timeout=2)
                if resp.status_code == 200:
                    models = [m["name"] for m in resp.json().get("models", [])]
                    for key, cfg_key in [("ollama_fast", "OLLAMA_MODEL_FAST"), ("ollama_smart", "OLLAMA_MODEL_SMART")]:
                        model_val = getattr(Config, cfg_key, "phi3.5")
                        if any(model_val.split(':')[0] in m for m in models):
                            available.append(key)
            except Exception: pass

        for api in ["gemini", "groq", "claude", "perplexity"]:
            if getattr(Config, f"{api.upper()}_API_KEY", ""):
                available.append(api)
        return available

    def _update_priority(self) -> None:
        priority = ["llama_cpp"] + list(getattr(Config, "BRAIN_PRIORITY", ["groq", "gemini", "claude"]))
        for api in priority:
            if api in self.available_apis:
                Config.PRIMARY_BRAIN = api
                break
        Config.FALLBACK_BRAIN = "gemini" if "gemini" in self.available_apis else "groq"

    # ─────────────────────────────────────────────────────────────
    # MAIN REASONING ENGINE
    # ─────────────────────────────────────────────────────────────

    def think(self, user_input: str, council_packet=None, admin_unlocked: bool = False) -> str:
        user_input = (user_input or "").strip()
        if not user_input: return "Try that again."

        # 1. Instant Local Rewrites
        direct = self._rewrite_generic_response(user_input)
        if direct:
            self._save_to_memory(user_input, direct, "local")
            return direct

        # 2. Classification (Web Search Trigger)
        query_type = self._classify_query(user_input)
        
        # 3. Ensemble Reasoning
        if getattr(Config, "USE_ENSEMBLE", False):
            response = self._ensemble_think(user_input, query_type, admin_unlocked=admin_unlocked)
        else:
            response = self._smart_route(user_input, query_type, admin_unlocked=admin_unlocked)

        if response:
            clean_response = self._postprocess(response)
            self._save_to_memory(user_input, clean_response, "brain")
            return clean_response

        return "I encountered a connection error. Please try again."

    def _ensemble_think(self, user_input: str, query_type: str, admin_unlocked: bool = False) -> str:
        """Calls APIs in parallel and selects the best answer."""
        self._active_admin_unlocked = admin_unlocked
        apis = self._get_apis_for_query(query_type)[:3]
        responses: Dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=len(apis)) as executor:
            futures = {executor.submit(self._call_api, api, user_input): api for api in apis}
            for future in futures:
                api = futures[future]
                try:
                    res = future.result()
                    if res: responses[api] = res
                except Exception: continue

        if not responses: return "Cognitive failure."
        judge_prompt = f"Question: {user_input}\nAnswers: {responses}\nPick the best response. WINNER: "
        judge_res = self._call_api("groq", judge_prompt)
        if judge_res and "WINNER:" in judge_res:
            return judge_res.split("WINNER:")[-1].strip()
        return next(iter(responses.values()))

    def _smart_route(self, user_input, query_type, admin_unlocked: bool = False):
        self._active_admin_unlocked = admin_unlocked
        order = self._get_apis_for_query(query_type)
        for api in order:
            if api not in self.available_apis: continue
            resp = self._call_api(api, user_input)
            if resp: return resp
        return None

    # ─────────────────────────────────────────────────────────────
    # PERSONA SELECTION
    # ─────────────────────────────────────────────────────────────

    def _get_persona(self, admin_unlocked: bool = False) -> str:
        if admin_unlocked:
            return getattr(Config, "ALETHEIA_PERSONA", _DEFAULT_ALETHEIA_PERSONA)
        persona = getattr(Config, "IRIS_PERSONA", _DEFAULT_IRIS_PERSONA)
        # Ensure the persona has deflection instruction; if not, use the full default
        if "deflect" not in persona.lower():
            return _DEFAULT_IRIS_PERSONA
        return persona

    # ─────────────────────────────────────────────────────────────
    # API HANDLERS
    # ─────────────────────────────────────────────────────────────

    def _call_api(self, api, prompt) -> Optional[str]:
        try:
            if api == "groq": return self._call_groq(prompt)
            if api == "claude": return self._call_claude(prompt)
            if api == "gemini": return self._call_gemini(prompt)
            if api == "perplexity": return self._call_perplexity(prompt)
            if api == "llama_cpp": return self._call_ollama("llama_cpp", prompt)
            if "ollama" in api: return self._call_ollama(api, prompt)
        except Exception: pass
        return None

    def _call_groq(self, prompt) -> str:
        payload = {"model": Config.GROQ_MODEL, "messages": self._build_msgs(prompt, self._active_admin_unlocked), "temperature": 0.4}
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {Config.GROQ_API_KEY}"}, json=payload, timeout=7)
        return resp.json()["choices"][0]["message"]["content"].strip()

    def _call_claude(self, prompt) -> str:
        headers = {"x-api-key": Config.CLAUDE_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        payload = {"model": Config.CLAUDE_MODEL, "max_tokens": 1024, "messages": [{"role": "user", "content": prompt}]}
        resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=12)
        return resp.json()["content"][0]["text"].strip()

    def _call_gemini(self, prompt) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{Config.GEMINI_MODEL}:generateContent?key={Config.GEMINI_API_KEY}"
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=10)
        return resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()

    def _call_perplexity(self, prompt) -> str:
        payload = {"model": Config.PERPLEXITY_MODEL, "messages": [{"role": "user", "content": prompt}]}
        resp = requests.post("https://api.perplexity.ai/chat/completions", headers={"Authorization": f"Bearer {Config.PERPLEXITY_API_KEY}"}, json=payload, timeout=15)
        return resp.json()["choices"][0]["message"]["content"].strip()

    def _call_ollama(self, api_key, prompt) -> str:
        if api_key == "llama_cpp":
            if self.llm is None:
                raise RuntimeError("C++ engine not loaded yet")
            messages = self._build_msgs(prompt, self._active_admin_unlocked)
            response = self.llm.create_chat_completion(
                messages=messages,
                max_tokens=1024,
                temperature=0.6,
            )
            return response["choices"][0]["message"]["content"].strip()
        model = getattr(Config, "OLLAMA_MODEL_FAST" if api_key == "ollama_fast" else "OLLAMA_MODEL_SMART", "phi3.5")
        payload = {"model": model, "prompt": f"User: {prompt}\nIris:", "stream": False}
        resp = requests.post(f"{Config.OLLAMA_BASE_URL}/api/generate", json=payload, timeout=10)
        return resp.json().get("response", "").strip()

    # ─────────────────────────────────────────────────────────────
    # MEMORY & ROUTING UTILS
    # ─────────────────────────────────────────────────────────────

    def _save_to_memory(self, user, assistant, source):
        self.memory.add("user", user)
        self.memory.add("assistant", assistant, source=source)

    def _classify_query(self, text: str) -> str:
        t = text.lower()
        if any(w in t for w in Config.WEB_KEYWORDS): return "web_search"
        if any(w in t for w in Config.CODE_KEYWORDS): return "code"
        return "general"

    def _get_apis_for_query(self, q_type: str) -> List[str]:
        if q_type == "web_search": return ["perplexity", "gemini", "groq"]
        return ["groq", "claude", "gemini"]

    def _build_msgs(self, prompt, admin_unlocked: bool = False):
        msgs = [{"role": "system", "content": self._get_persona(admin_unlocked)}]
        msgs.extend(self.memory.get_context(3))
        msgs.append({"role": "user", "content": prompt})
        return msgs

    def _postprocess(self, text: str) -> str:
        return re.sub(r"^(As an AI|I'm happy to help|Certainly),?\s*", "", text, flags=re.IGNORECASE).strip()

    def _rewrite_generic_response(self, text: str) -> str:
        t = text.lower()
        if "how are you" in t: return "Operational. Ready."
        if t in ["hi", "hello", "iris"]: return "I'm here."
        return ""