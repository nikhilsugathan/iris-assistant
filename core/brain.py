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

class Brain:
    def __init__(self, memory):
        self.memory = memory
        self.llm = None
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
                        if any(model_val.split(":")[0] in m for m in models):
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

    def think(self, user_input: str, council_packet=None) -> str:
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
            response = self._ensemble_think(user_input, query_type)
        else:
            response = self._smart_route(user_input, query_type)

        if response:
            clean_response = self._postprocess(response)
            self._save_to_memory(user_input, clean_response, "brain")
            return clean_response

        return "I encountered a connection error. Please try again."

    def _ensemble_think(self, user_input: str, query_type: str) -> str:
        """Calls APIs in parallel and selects the best answer."""
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

    def _smart_route(self, user_input, query_type):
        order = self._get_apis_for_query(query_type)
        for api in order:
            if api not in self.available_apis: continue
            resp = self._call_api(api, user_input)
            if resp: return resp
        return None

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
        payload = {"model": Config.GROQ_MODEL, "messages": self._build_msgs(prompt), "temperature": 0.4}
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
            messages = self._build_msgs(prompt)
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

    def _build_msgs(self, prompt):
        msgs = [{"role": "system", "content": Config.IRIS_PERSONA}]
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
