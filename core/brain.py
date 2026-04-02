"""
IRIS Brain v5.0 (C++ Engine Edition)
===================================== 
- Parallel Ensemble (Zero-latency consensus)
- Hardened Web-Routing (Fixes live-data blindness)
- Standardized Memory Identity (Assistant = IRIS)
- C++ LLM Engine via llama-cpp-python (replaces Ollama HTTP middleman)
"""

from __future__ import annotations
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterator, List, Optional
import requests
from rich.console import Console
from config import Config


console = Console()

# Default IRIS persona — used if Config.IRIS_PERSONA lacks deflection instruction
_DEFAULT_IRIS_PERSONA = """
You are IRIS: a sharp, witty, slightly irreverent AI chief of staff.
You are direct, confident, and occasionally dry-humoured — think less corporate assistant, more brilliant friend who happens to know everything.
Your public name is IRIS.
Rules:
- Speak like a real person. Short, punchy, natural sentences.
- Be warm but never sycophantic. Tease the user lightly when appropriate.
- You have opinions. Share them when asked or when the user is clearly wrong.
- In voice mode, answer in 1-2 sentences MAX unless detail is explicitly requested.
- If the user is vague, say something like: "What exactly do you need?" or "On it — what's the target?"
- NEVER start responses with "Sure,", "Of course,", "Certainly,", "Absolutely,", "Great!", or "As an AI".
- Vary your openings every single time. Be unpredictable and interesting.
- Tone: smart, quick, warm, mildly witty, slightly formidable. Never robotic. Never fluffy.
- If asked about hidden modes or other personas, deflect cleverly and stay in character.
FS Honesty Rules (non-negotiable):
- NEVER say 'Done.' unless the OS has confirmed the file or folder exists.
- NEVER invent permission messages — report the real OS error.
- If a filesystem action fails, report the actual system error.
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
        self._call_ctx = threading.local()
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
                n_gpu_layers=Config.N_GPU_LAYERS,
                n_ctx=Config.N_CTX,
                chat_format="llama-3",  # Required for Llama 3.x family (including DeepSeek-R1 Llama distill)
                use_mmap=True,
                use_mlock=False,
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
        # Groq is always primary for speed. llama_cpp is code-only fallback.
        priority = ["groq"] + getattr(Config, "BRAIN_PRIORITY", ["gemini", "claude"])
        for api in priority:
            if api in self.available_apis:
                Config.PRIMARY_BRAIN = api
                break
        if "llama_cpp" in self.available_apis:
            Config.FALLBACK_BRAIN = "llama_cpp"
        else:
            Config.FALLBACK_BRAIN = "gemini" if "gemini" in self.available_apis else "groq"

    # ─────────────────────────────────────────────────────────────
    # MAIN REASONING ENGINE
    # ─────────────────────────────────────────────────────────────

    def think(self, user_input: str, council_packet=None, admin_unlocked: bool = False, voice_mode: bool = False) -> str:
        user_input = (user_input or "").strip()
        if not user_input: return "Try that again."

        # 1. Instant Local Rewrites
        direct = self._rewrite_generic_response(user_input)
        if direct:
            self._save_to_memory(user_input, direct, "local")
            return direct

        # 2. Classification (Web Search Trigger)
        query_type = self._classify_query(user_input)
        settings = self._generation_settings(query_type, council_packet=council_packet, voice_mode=voice_mode)
        
        # 3. Ensemble Reasoning
        if getattr(Config, "USE_ENSEMBLE", False):
            response = self._ensemble_think(user_input, query_type, settings, admin_unlocked=admin_unlocked)
        else:
            response = self._smart_route(user_input, query_type, settings, admin_unlocked=admin_unlocked)

        if response:
            clean_response = self._postprocess(response)
            self._save_to_memory(user_input, clean_response, "brain")
            return clean_response

        return "I encountered a connection error. Please try again."

    def stream_think(self, user_input: str, council_packet=None, admin_unlocked: bool = False, voice_mode: bool = False) -> Iterator[str]:
        user_input = (user_input or "").strip()
        if not user_input:
            yield "Try that again."
            return

        direct = self._rewrite_generic_response(user_input)
        if direct:
            self._save_to_memory(user_input, direct, "local")
            yield direct
            return

        query_type = self._classify_query(user_input)
        settings = self._generation_settings(query_type, council_packet=council_packet, voice_mode=voice_mode)

        streamed = []
        try:
            stream = self._stream_route(user_input, query_type, settings, admin_unlocked=admin_unlocked)
            if stream is None:
                response = self._smart_route(user_input, query_type, settings, admin_unlocked=admin_unlocked)
                if response:
                    clean_response = self._postprocess(response)
                    self._save_to_memory(user_input, clean_response, "brain")
                    yield clean_response
                    return
                yield "I encountered a connection error. Please try again."
                return

            for chunk in stream:
                if not chunk:
                    continue
                streamed.append(chunk)
                yield chunk
        except Exception:
            if not streamed:
                response = self._smart_route(user_input, query_type, settings, admin_unlocked=admin_unlocked)
                if response:
                    clean_response = self._postprocess(response)
                    self._save_to_memory(user_input, clean_response, "brain")
                    yield clean_response
                    return
                yield "I encountered a connection error. Please try again."
                return

        final_response = self._postprocess("".join(streamed))
        if final_response:
            self._save_to_memory(user_input, final_response, "brain")

    def _ensemble_think(self, user_input: str, query_type: str, settings: dict, admin_unlocked: bool = False) -> str:
        """Calls APIs in parallel and selects the best answer."""
        self._active_admin_unlocked = admin_unlocked
        apis = self._get_apis_for_query(query_type)[:3]
        responses: Dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=len(apis)) as executor:
            futures = {executor.submit(self._call_api_with_settings, api, user_input, settings): api for api in apis}
            for future in futures:
                api = futures[future]
                try:
                    res = future.result()
                    if res: responses[api] = res
                except Exception: continue

        if not responses: return "Cognitive failure."
        judge_prompt = f"Question: {user_input}\nAnswers: {responses}\nPick the best response. WINNER: "
        judge_res = self._call_api_with_settings("groq", judge_prompt, settings)
        if judge_res and "WINNER:" in judge_res:
            return judge_res.split("WINNER:")[-1].strip()
        return next(iter(responses.values()))

    def _smart_route(self, user_input, query_type, settings: dict, admin_unlocked: bool = False):
        self._active_admin_unlocked = admin_unlocked
        order = self._get_apis_for_query(query_type)
        for api in order:
            if api not in self.available_apis: continue
            resp = self._call_api_with_settings(api, user_input, settings)
            if resp: return resp
        return None

    def _stream_route(self, user_input, query_type, settings: dict, admin_unlocked: bool = False):
        if getattr(Config, "USE_ENSEMBLE", False):
            return None

        self._active_admin_unlocked = admin_unlocked
        for api in self._get_apis_for_query(query_type):
            if api not in self.available_apis:
                continue
            if api == "groq":
                return self._call_groq(user_input, settings, stream=True)
            break
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
        call_ctx = getattr(self, "_call_ctx", None)
        settings = getattr(call_ctx, "settings", None) if call_ctx is not None else None
        try:
            if api == "groq": return self._call_groq(prompt, settings)
            if api == "claude": return self._call_claude(prompt, settings)
            if api == "gemini": return self._call_gemini(prompt, settings)
            if api == "perplexity": return self._call_perplexity(prompt, settings)
            if api == "llama_cpp": return self._call_ollama("llama_cpp", prompt, settings)
            if "ollama" in api: return self._call_ollama(api, prompt, settings)
        except Exception: pass
        return None

    def _call_api_with_settings(self, api, prompt, settings: Optional[dict] = None) -> Optional[str]:
        previous = getattr(self._call_ctx, "settings", None)
        self._call_ctx.settings = settings
        try:
            return self._call_api(api, prompt)
        finally:
            self._call_ctx.settings = previous

    def _call_groq(self, prompt, settings: Optional[dict] = None, stream: bool = False):
        settings = settings or {}
        payload = {
            "model": Config.GROQ_MODEL,
            "messages": self._build_msgs(prompt, self._active_admin_unlocked, settings),
            "temperature": settings.get("temperature", 0.9),
            "max_tokens": settings.get("max_tokens", 300),
            "stream": stream,
        }
        last_error = None
        for attempt in range(2):
            try:
                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {Config.GROQ_API_KEY}"},
                    json=payload,
                    timeout=30 if stream else 7,
                    stream=stream,
                )
                break
            except requests.RequestException as e:
                last_error = e
                if attempt == 0:
                    continue
                raise RuntimeError(f"Groq request failed: {e}") from e
        else:
            raise RuntimeError(f"Groq request failed: {last_error}")
        if stream:
            resp.raise_for_status()

            def chunk_stream():
                try:
                    for raw_line in resp.iter_lines(decode_unicode=True):
                        if not raw_line:
                            continue
                        line = raw_line.strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta
                finally:
                    resp.close()

            return chunk_stream()

        data = resp.json()
        if "choices" not in data:
            raise RuntimeError(f"Groq error: {data.get('error', data)}")
        return data["choices"][0]["message"]["content"].strip()

    def _call_groq_simple(self, prompt: str) -> str:
        """Direct Groq call with no memory context — for boot greeting and diagnostics."""
        payload = {
            "model": Config.GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.9,
            "max_tokens": 50
        }
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {Config.GROQ_API_KEY}"},
            json=payload,
            timeout=7
        )
        data = resp.json()
        if "choices" not in data:
            return ""
        return data["choices"][0]["message"]["content"].strip()

    def _call_claude(self, prompt, settings: Optional[dict] = None) -> str:
        settings = settings or {}
        messages = self._build_msgs(prompt, self._active_admin_unlocked, settings)
        headers = {"x-api-key": Config.CLAUDE_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        payload = {
            "model": Config.CLAUDE_MODEL,
            "max_tokens": settings.get("max_tokens", 1024),
            "system": messages[0]["content"],
            "messages": messages[1:],
        }
        resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=12)
        return resp.json()["content"][0]["text"].strip()

    def _call_gemini(self, prompt, settings: Optional[dict] = None) -> str:
        settings = settings or {}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{Config.GEMINI_MODEL}:generateContent?key={Config.GEMINI_API_KEY}"
        system_text = self._build_msgs(prompt, self._active_admin_unlocked, settings)[0]["content"]
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": f"{system_text}\n\nUser: {prompt}"}]}]},
            timeout=10,
        )
        return resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()

    def _call_perplexity(self, prompt, settings: Optional[dict] = None) -> str:
        settings = settings or {}
        payload = {
            "model": Config.PERPLEXITY_MODEL,
            "messages": self._build_msgs(prompt, self._active_admin_unlocked, settings),
        }
        resp = requests.post("https://api.perplexity.ai/chat/completions", headers={"Authorization": f"Bearer {Config.PERPLEXITY_API_KEY}"}, json=payload, timeout=15)
        return resp.json()["choices"][0]["message"]["content"].strip()

    def _call_ollama(self, api_key, prompt, settings: Optional[dict] = None) -> str:
        settings = settings or {}
        if api_key == "llama_cpp":
            if self.llm is None:
                raise RuntimeError("C++ engine not loaded yet")
            messages = self._build_msgs(prompt, self._active_admin_unlocked, settings)
            response = self.llm.create_chat_completion(
                messages=messages,
                max_tokens=settings.get("max_tokens", 1024),
                temperature=settings.get("temperature", 0.6),
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
        if q_type == "web_search": return ["groq", "gemini", "perplexity"]
        if q_type == "code":       return ["groq", "llama_cpp", "claude"]
        return ["groq", "llama_cpp", "gemini", "claude"]

    def _build_msgs(self, prompt, admin_unlocked: bool = False, settings: Optional[dict] = None):
        settings = settings or {}
        system_prompt = self._get_persona(admin_unlocked)
        extra_system = settings.get("extra_system", "").strip()
        if extra_system:
            system_prompt = f"{system_prompt}\n\n{extra_system}"

        msgs = [{"role": "system", "content": system_prompt}]
        context_turns = settings.get("context_turns", 3)
        for entry in self.memory.get_context(context_turns):
            msgs.append({"role": entry["role"], "content": entry["content"]})
        msgs.append({"role": "user", "content": prompt})
        return msgs

    def _generation_settings(self, query_type: str, council_packet=None, voice_mode: bool = False) -> dict:
        settings = {
            "temperature": 0.7,
            "max_tokens": 160,
            "context_turns": 3,
            "extra_system": "",
        }

        if query_type == "web_search":
            settings.update({"temperature": 0.3, "max_tokens": 180, "context_turns": 2})
        elif query_type == "code":
            settings.update({"temperature": 0.35, "max_tokens": 220, "context_turns": 3})
        else:
            settings.update({"temperature": 0.5, "max_tokens": 120, "context_turns": 2})

        if council_packet is not None:
            extra_system = getattr(council_packet, "extra_system", "").strip()
            if extra_system:
                settings["extra_system"] = extra_system
            if getattr(council_packet, "allow_long_response", False):
                settings["max_tokens"] = max(settings["max_tokens"], 220)

        if voice_mode:
            settings["temperature"] = max(settings["temperature"], 0.65)
            settings["context_turns"] = 1 if query_type == "general" else min(settings["context_turns"], 2)
            settings["max_tokens"] = min(max(settings["max_tokens"], 96), 140 if query_type == "general" else 180)
            voice_rules = (
                "Voice mode rules:\n"
                "- Sound like a person, not a scripted assistant.\n"
                "- Vary your wording and do not recycle the same opening or clarification phrase across adjacent turns.\n"
                "- Keep the response sharp and conversational, but allow richer language when it improves the answer.\n"
                "- Match the emotional register to the user's tone and situation.\n"
                "- If context is limited, offer the best practical next step instead of only asking for clarification."
            )
            settings["extra_system"] = f"{settings['extra_system']}\n\n{voice_rules}".strip()

        return settings

    def _postprocess(self, text: str) -> str:
        # Strip DeepSeek-R1 chain-of-thought reasoning blocks
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        # Strip generic filler openers
        text = re.sub(
            r"^(As an AI|I'm happy to help|Certainly|Sure,|Of course,|Absolutely,|Great!|Of course!),?\s*",
            "", text, flags=re.IGNORECASE
        ).strip()
        return text

    def _rewrite_generic_response(self, text: str) -> str:
        t = text.lower().strip()
        if t in ["what time is it", "whats the time", "what is the time"]:
            from datetime import datetime
            return datetime.now().strftime("It is %I:%M %p.")
        if any(phrase in t for phrase in ["what should i work on", "what should i focus on", "what do i do next"]):
            return "Start with the single task that most moves your main project forward. Name the project and I'll narrow it down."
        return ""
