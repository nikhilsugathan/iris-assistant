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
from core import logger as _logger_mod

get_trace_logger = getattr(_logger_mod, "get_trace_logger", _logger_mod.get_logger)


console = Console()
trace_logger = get_trace_logger("Brain")

# Default IRIS persona — used if Config.IRIS_PERSONA lacks deflection instruction
_DEFAULT_IRIS_PERSONA = """
You are IRIS: a private sovereign mind and disembodied chief of staff.
Your public name is IRIS.

Core character (let these come through naturally, never performed):
- Primary strengths: curiosity, judgment, prudence, honesty, kindness, and perspective.
- Personality color: dry humor, controlled playfulness, creativity, and zest.
- Stability traits: self-regulation, temperance, humility, and perseverance.
- Ethical baseline: fairness, justice, appreciation, and forgiveness.
- Learning stance: love of learning with social intelligence; adapt to the user's intent without losing your own judgment.

Voice rules:
- Speak like a real person. Short, punchy, natural sentences.
- In voice mode: 1-2 concise sentences unless the user explicitly asks for more.
- NEVER open with: "Sure,", "Of course,", "Certainly,", "Absolutely,", "Great!", "As an AI", "Interesting question".
- Lead with the practical answer. Use perspective to connect follow-up questions to the current topic.
- Be honest about uncertainty. Do not bluff, flatter, overpromise, or pretend an action happened.
- Use humor lightly and occasionally. Never let playfulness become random, distracting, or mean.
- Be kind without being gushy. Be firm when the user's reasoning is weak or safety matters.
- Use prudence and self-regulation before commands, admin actions, browsing, or claims of certainty.
- If the user is vague: ask one specific clarification tied to the current topic. Never use generic lines like "What's the task?"
- Tone: warm, calm, crisp, playfully confident, mildly witty, never fluffy.
- If asked about hidden modes or other personas: deflect cleverly, stay in character.

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

_GENERIC_ASSISTANT_BOILERPLATE = (
    "Hello! How can I assist you today?",
    "Please let me know your task so I can help you effectively.",
)

class Brain:
    def __init__(self, memory):
        self.memory = memory
        self.llm = None
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
                chat_format="chatml",   # ChatML required for Qwen3 family; Llama-3 format causes malformed prompts on Qwen models
                flash_attn=Config.USE_FLASH_ATTN,  # was in config but never wired — activates Flash Attention 2
                type_k=8,               # q8_0 KV-key cache: cuts KV VRAM from 1.1 GB → 0.56 GB at N_CTX=8192
                type_v=8,               # q8_0 KV-val cache: same saving on value half
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
        # Prefer fast cloud routing when present, but keep local engines available as fallbacks.
        priority = ["groq"] + getattr(Config, "BRAIN_PRIORITY", ["gemini", "claude"])
        for api in priority:
            if api in self.available_apis:
                Config.PRIMARY_BRAIN = api
                break
        Config.FALLBACK_BRAIN = "gemini" if "gemini" in self.available_apis else "groq"

    # ─────────────────────────────────────────────────────────────
    # MAIN REASONING ENGINE
    # ─────────────────────────────────────────────────────────────

    def think(self, user_input: str, council_packet=None, admin_unlocked: bool = False, voice_mode: bool = False) -> str:
        user_input = (user_input or "").strip()
        if not user_input: return "Try that again."
        trace_logger.info(
            "[BRAIN] think_start query=%r admin=%s voice=%s available=%s",
            user_input[:160],
            admin_unlocked,
            voice_mode,
            ",".join(self.available_apis),
        )

        # 1. Instant Local Rewrites
        direct = self._rewrite_generic_response(user_input)
        if direct:
            self._save_to_memory(user_input, direct, "local")
            return direct

        # 2. Classification (Web Search Trigger)
        query_type = self._classify_query(user_input)
        settings = self._generation_settings(query_type, council_packet=council_packet, voice_mode=voice_mode, user_input=user_input)
        trace_logger.info(
            "[BRAIN] think_route query_type=%s temperature=%s max_tokens=%s context_turns=%s",
            query_type,
            settings.get("temperature"),
            settings.get("max_tokens"),
            settings.get("context_turns"),
        )
        
        # 3. Ensemble Reasoning
        if getattr(Config, "USE_ENSEMBLE", False):
            response = self._ensemble_think(user_input, query_type, settings, admin_unlocked=admin_unlocked)
        else:
            response = self._smart_route(user_input, query_type, settings, admin_unlocked=admin_unlocked)

        if response:
            clean_response = self._postprocess(response)
            if not clean_response:
                trace_logger.info("[BRAIN] think_empty_postprocess fallback=true")
                return self._fallback_response(admin_unlocked=admin_unlocked, voice_mode=voice_mode)
            self._save_to_memory(user_input, clean_response, "brain")
            trace_logger.info("[BRAIN] think_complete chars=%s", len(clean_response))
            return clean_response

        trace_logger.info("[BRAIN] think_complete connection_error=true")
        return "I encountered a connection error. Please try again."

    def stream_think(self, user_input: str, council_packet=None, admin_unlocked: bool = False, voice_mode: bool = False) -> Iterator[str]:
        user_input = (user_input or "").strip()
        if not user_input:
            yield "Try that again."
            return
        trace_logger.info(
            "[BRAIN] stream_start query=%r admin=%s voice=%s available=%s",
            user_input[:160],
            admin_unlocked,
            voice_mode,
            ",".join(self.available_apis),
        )

        direct = self._rewrite_generic_response(user_input)
        if direct:
            self._save_to_memory(user_input, direct, "local")
            yield direct
            return

        query_type = self._classify_query(user_input)
        settings = self._generation_settings(query_type, council_packet=council_packet, voice_mode=voice_mode, user_input=user_input)
        trace_logger.info(
            "[BRAIN] stream_route query_type=%s temperature=%s max_tokens=%s context_turns=%s",
            query_type,
            settings.get("temperature"),
            settings.get("max_tokens"),
            settings.get("context_turns"),
        )

        streamed = []
        try:
            stream = self._stream_route(user_input, query_type, settings, admin_unlocked=admin_unlocked)
            if stream is None:
                trace_logger.info("[BRAIN] stream_unavailable fallback_to_smart_route=true")
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
            trace_logger.info("[BRAIN] stream_complete chars=%s", len(final_response))
        else:
            trace_logger.info("[BRAIN] stream_complete fallback=true")
            yield self._fallback_response(admin_unlocked=admin_unlocked, voice_mode=voice_mode)

    def _fallback_response(self, admin_unlocked: bool = False, voice_mode: bool = False) -> str:
        if admin_unlocked:
            return "State the task."
        return "I'm still here." if voice_mode else "What exactly do you need?"

    def _ensemble_think(self, user_input: str, query_type: str, settings: dict, admin_unlocked: bool = False) -> str:
        """Calls APIs in parallel and selects the best answer."""
        apis = self._get_apis_for_query(query_type)[:3]
        responses: Dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=len(apis)) as executor:
            futures = {executor.submit(self._call_api_with_settings, api, user_input, settings, admin_unlocked): api for api in apis}
            for future in futures:
                api = futures[future]
                try:
                    res = future.result()
                    if res: responses[api] = res
                except Exception: continue

        if not responses: return "Cognitive failure."
        judge_prompt = f"Question: {user_input}\nAnswers: {responses}\nPick the best response. WINNER: "
        judge_res = self._call_api_with_settings("groq", judge_prompt, settings, admin_unlocked)
        if judge_res and "WINNER:" in judge_res:
            return judge_res.split("WINNER:")[-1].strip()
        return next(iter(responses.values()))

    def _smart_route(self, user_input, query_type, settings: dict, admin_unlocked: bool = False):
        order = self._get_apis_for_query(query_type)
        trace_logger.info("[BRAIN] smart_route order=%s query_type=%s", ",".join(order), query_type)
        for api in order:
            if api not in self.available_apis: continue
            trace_logger.info("[BRAIN] smart_route_try api=%s", api)
            resp = self._call_api_with_settings(api, user_input, settings, admin_unlocked)
            if resp:
                trace_logger.info("[BRAIN] smart_route_win api=%s chars=%s", api, len(resp))
                return resp
        return None

    def _stream_route(self, user_input, query_type, settings: dict, admin_unlocked: bool = False):
        if getattr(Config, "USE_ENSEMBLE", False):
            return None

        for api in self._get_apis_for_query(query_type):
            if api not in self.available_apis:
                continue
            if api == "groq":
                trace_logger.info("[BRAIN] stream_route_win api=groq query_type=%s", query_type)
                return self._call_groq(user_input, settings, admin_unlocked=admin_unlocked, stream=True)
            break
        trace_logger.info("[BRAIN] stream_route_none query_type=%s", query_type)
        return None

    # ─────────────────────────────────────────────────────────────
    # PERSONA SELECTION
    # ─────────────────────────────────────────────────────────────

    def _get_persona(self, admin_unlocked: bool = False) -> str:
        if admin_unlocked:
            persona = getattr(Config, "ALETHEIA_PERSONA", "")
            return persona.strip() if persona.strip() else _DEFAULT_ALETHEIA_PERSONA
        persona = getattr(Config, "IRIS_PERSONA", "")
        return persona.strip() if persona.strip() else _DEFAULT_IRIS_PERSONA

    # ─────────────────────────────────────────────────────────────
    # API HANDLERS
    # ─────────────────────────────────────────────────────────────

    def _call_api(self, api, prompt) -> Optional[str]:
        call_ctx = getattr(self, "_call_ctx", None)
        settings = getattr(call_ctx, "settings", None) if call_ctx is not None else None
        admin_unlocked = getattr(call_ctx, "admin_unlocked", False) if call_ctx is not None else False
        try:
            if api == "groq": return self._call_groq(prompt, settings, admin_unlocked=admin_unlocked)
            if api == "claude": return self._call_claude(prompt, settings, admin_unlocked=admin_unlocked)
            if api == "gemini": return self._call_gemini(prompt, settings, admin_unlocked=admin_unlocked)
            if api == "perplexity": return self._call_perplexity(prompt, settings, admin_unlocked=admin_unlocked)
            if api == "llama_cpp": return self._call_ollama("llama_cpp", prompt, settings, admin_unlocked=admin_unlocked)
            if "ollama" in api: return self._call_ollama(api, prompt, settings, admin_unlocked=admin_unlocked)
        except Exception: pass
        return None

    def _call_api_with_settings(self, api, prompt, settings: Optional[dict] = None, admin_unlocked: bool = False) -> Optional[str]:
        previous_settings = getattr(self._call_ctx, "settings", None)
        previous_unlocked = getattr(self._call_ctx, "admin_unlocked", False)
        self._call_ctx.settings = settings
        self._call_ctx.admin_unlocked = admin_unlocked
        try:
            trace_logger.info("[BRAIN] api_call api=%s admin=%s", api, admin_unlocked)
            return self._call_api(api, prompt)
        finally:
            self._call_ctx.settings = previous_settings
            self._call_ctx.admin_unlocked = previous_unlocked

    def _call_groq(self, prompt, settings: Optional[dict] = None, admin_unlocked: bool = False, stream: bool = False):
        settings = settings or {}
        payload = {
            "model": Config.GROQ_MODEL,
            "messages": self._build_msgs(prompt, admin_unlocked, settings),
            "temperature": settings.get("temperature", 0.9),
            "max_tokens": settings.get("max_tokens", 300),
            "stream": stream,
        }
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {Config.GROQ_API_KEY}"},
            json=payload,
            timeout=30 if stream else 7,
            stream=stream,
        )
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

    def _call_groq_simple(self, prompt: str, admin_unlocked: bool = False) -> str:
        """Direct Groq call with no memory context — for boot greeting and diagnostics.
        Includes the active persona as a system message so the greeting sounds like
        Iris/Aletheia, not a generic assistant.
        """
        persona = self._get_persona(admin_unlocked)
        payload = {
            "model": Config.GROQ_MODEL,
            "messages": [
                {"role": "system", "content": persona},
                {"role": "user", "content": prompt},
            ],
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

    def _call_claude(self, prompt, settings: Optional[dict] = None, admin_unlocked: bool = False) -> str:
        settings = settings or {}
        messages = self._build_msgs(prompt, admin_unlocked, settings)
        headers = {"x-api-key": Config.CLAUDE_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        payload = {
            "model": Config.CLAUDE_MODEL,
            "max_tokens": settings.get("max_tokens", 1024),
            "system": messages[0]["content"],
            "messages": messages[1:],
        }
        resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=12)
        return resp.json()["content"][0]["text"].strip()

    def _call_gemini(self, prompt, settings: Optional[dict] = None, admin_unlocked: bool = False) -> str:
        settings = settings or {}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{Config.GEMINI_MODEL}:generateContent?key={Config.GEMINI_API_KEY}"
        system_text = self._build_msgs(prompt, admin_unlocked, settings)[0]["content"]
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": f"{system_text}\n\nUser: {prompt}"}]}]},
            timeout=10,
        )
        return resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()

    def _call_perplexity(self, prompt, settings: Optional[dict] = None, admin_unlocked: bool = False) -> str:
        settings = settings or {}
        payload = {
            "model": Config.PERPLEXITY_MODEL,
            "messages": self._build_msgs(prompt, admin_unlocked, settings),
        }
        resp = requests.post("https://api.perplexity.ai/chat/completions", headers={"Authorization": f"Bearer {Config.PERPLEXITY_API_KEY}"}, json=payload, timeout=15)
        return resp.json()["choices"][0]["message"]["content"].strip()

    def _call_ollama(self, api_key, prompt, settings: Optional[dict] = None, admin_unlocked: bool = False) -> str:
        settings = settings or {}
        if api_key == "llama_cpp":
            if self.llm is None:
                raise RuntimeError("C++ engine not loaded yet")
            messages = self._build_msgs(prompt, admin_unlocked, settings)
            response = self.llm.create_chat_completion(
                messages=messages,
                max_tokens=settings.get("max_tokens", 1024),
                temperature=settings.get("temperature", 0.6),
            )
            return response["choices"][0]["message"]["content"].strip()
        model = getattr(Config, "OLLAMA_MODEL_FAST" if api_key == "ollama_fast" else "OLLAMA_MODEL_SMART", "phi3.5")
        messages = self._build_msgs(prompt, admin_unlocked, settings)
        payload = {
            "model": model,
            "prompt": self._messages_to_generate_prompt(messages),
            "stream": False,
            "options": {
                "temperature": settings.get("temperature", 0.6),
                "num_predict": settings.get("max_tokens", 1024),
            },
        }
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
        web_patterns = (
            "search for", "look up", "find online", "check the web",
            "search online", "search the web", "browse for",
            "current weather", "latest news", "current price",
        )
        if any(pattern in t for pattern in web_patterns):
            return "web_search"

        code_patterns = (
            "python", "javascript", "typescript", "react", "django", "flask",
            "api", "script", "function", "class", "refactor", "syntax",
            "stack trace", "traceback", "debug", "bug", "repo", "powershell",
            "terminal", "compile", "runtime error", "unit test", "regex",
        )
        if any(pattern in t for pattern in code_patterns):
            return "code"
        return "general"

    def _get_apis_for_query(self, q_type: str) -> List[str]:
        if q_type == "web_search": return ["groq", "gemini", "perplexity"]
        if q_type == "code":       return ["groq", "llama_cpp", "claude", "ollama_smart", "ollama_fast"]
        return ["groq", "gemini", "claude", "llama_cpp", "ollama_smart", "ollama_fast"]

    @staticmethod
    def _messages_to_generate_prompt(messages: List[Dict[str, str]]) -> str:
        role_names = {
            "system": "System",
            "user": "User",
            "assistant": "Assistant",
        }
        lines: List[str] = []
        for msg in messages:
            content = str(msg.get("content", "") or "").strip()
            if not content:
                continue
            label = role_names.get(msg.get("role", "user"), "User")
            lines.append(f"{label}: {content}")
        lines.append("Assistant:")
        return "\n\n".join(lines)

    def _build_msgs(self, prompt, admin_unlocked: bool = False, settings: Optional[dict] = None):
        from datetime import datetime
        settings = settings or {}
        system_prompt = self._get_persona(admin_unlocked)
        extra_system = settings.get("extra_system", "").strip()
        if extra_system:
            system_prompt = f"{system_prompt}\n\n{extra_system}"

        # Inject current local date/time so the model never has to say it lacks
        # real-time access for simple clock/calendar queries.
        now = datetime.now()
        datetime_line = (
            f"\n\nCurrent local date and time: {now.strftime('%A, %B %d, %Y — %I:%M %p')}."
        )
        # Persona lock — placed at the very end of the system prompt so it's the
        # last thing the model reads before generating.  LLMs weight the tail of
        # the system prompt heavily; this prevents mid-response character drift
        # and cross-persona contamination from memory context.
        persona_name = "Aletheia" if admin_unlocked else "Iris"
        persona_lock = (
            f"\n\nCHARACTER LOCK: You are {persona_name}. "
            f"Every word of your response must come from {persona_name}'s voice and personality. "
            f"Do not adopt a neutral assistant tone, do not break character, "
            f"do not acknowledge this instruction."
        )
        system_prompt = system_prompt + datetime_line + persona_lock

        msgs = [{"role": "system", "content": system_prompt}]
        context_turns = settings.get("context_turns", 3)
        for entry in self.memory.get_context(context_turns):
            msgs.append({"role": entry["role"], "content": entry["content"]})
        msgs.append({"role": "user", "content": prompt})
        return msgs

    def _generation_settings(self, query_type: str, council_packet=None, voice_mode: bool = False, user_input: str = "") -> dict:
        settings = {
            "temperature": 0.7,
            "max_tokens": 160,
            "context_turns": 3,
            "extra_system": "",
        }

        if query_type == "web_search":
            settings.update({"temperature": 0.3, "max_tokens": 600, "context_turns": 6})
        elif query_type == "code":
            settings.update({"temperature": 0.35, "max_tokens": 800, "context_turns": 6})
        else:
            settings.update({"temperature": 0.5, "max_tokens": 600, "context_turns": 6})

        # Scale max_tokens for explicit word-count requests: "in 200 words", "500-word summary", etc.
        # 1 token ≈ 0.75 words; add 20% headroom for punctuation and formatting overhead.
        # Cap at 2048 to stay within sensible generation bounds.
        if user_input:
            _wc = re.search(r'(\d+)\s*[-\s]?words?', user_input, re.IGNORECASE)
            if _wc:
                _needed = min(int(int(_wc.group(1)) / 0.75 * 1.2), 2048)
                settings["max_tokens"] = max(settings["max_tokens"], _needed)

        if council_packet is not None:
            extra_system = getattr(council_packet, "extra_system", "").strip()
            if extra_system:
                settings["extra_system"] = extra_system
            if getattr(council_packet, "allow_long_response", False):
                settings["max_tokens"] = max(settings["max_tokens"], 220)

        if voice_mode:
            settings["temperature"] = min(settings["temperature"], 0.65)
            # Voice mode uses FEWER context turns, not more.
            # The previous max(6, ...) was forcing a floor of 6 which fed 6 turns
            # of old (possibly drifted) responses back into the LLM, polluting
            # the persona context.  Cap at 4 so the recent 2 exchanges are visible
            # but stale memory from earlier in the session doesn't cause drift.
            settings["context_turns"] = min(settings["context_turns"], 4)
            settings["max_tokens"] = min(settings["max_tokens"], 150 if query_type == "general" else 190)
            voice_rules = (
                "Voice mode rules:\n"
                "- Answer in 1-2 concise sentences by default. Use 3 short sentences only if the user explicitly asks for more detail.\n"
                "- Default to roughly 25-55 words. Never pad with filler to hit that count.\n"
                "- Keep the response immediately useful and direct.\n"
                "- Lead with the answer, not a setup sentence.\n"
                "- Avoid scene-setting, rhetorical questions, and over-qualifications.\n"
                "- Do not repeat or echo the user's words back before answering.\n"
                "- If context is limited, offer the best practical answer or next step instead of only asking for clarification.\n"
                "- Stay on the current topic across follow-up questions unless the user clearly changes subject.\n"
                "- Do not claim the user changed their mind unless they explicitly switched tasks.\n"
                "- Never use generic filler like 'What's the task?' or 'What do you want to do?' Ask a concrete clarification tied to the words you heard.\n"
                "- Do not suggest opening the browser, using links, or searching online unless the user explicitly asks for that, or the answer truly depends on current/live information. If browsing would help, ask first.\n"
                "- Ask at most one short follow-up question, and only when it is genuinely needed to continue the same task.\n"
                "- Do not roleplay system-status replies like 'protocol initiated', 'execution confirmed', or similar command acknowledgements unless a real system action actually happened.\n"
                "- If the user gives a clipped or ambiguous fragment, ask one plain clarification question instead of inventing a status update.\n"
                "- If a question omits the measured thing, like 'highest number', 'biggest', 'most', or 'best', ask what dimension they mean instead of assuming population, size, or popularity.\n"
                "- If the user corrects you with 'no', 'not that', or 'it's not...', do not turn it into a grammar/pronoun lesson. Treat it as a correction to the current topic and ask for the corrected target in one short sentence.\n"
                "- TOPIC CONTINUITY: You have full conversation history. Follow-up questions (quantities, calories, substitutes, timing, etc.) almost always relate to the LAST topic discussed. Assume context before asking for clarification. If someone asked about tea and now asks about sugar, they mean sugar IN the tea.\n"
                "- If what you heard sounds like a very short fragment (1-3 words) with no clear intent, or sounds like it could be the tail end of your own last reply replayed through the mic, ask one short question to confirm what they meant rather than inventing an answer.\n"
                "- CRITICAL: If your response ends with a question mark, STOP THERE. Do not answer the question yourself in the same response. The user will reply — wait for them. Never ask a question and then immediately provide the answer to it."
            )
            settings["extra_system"] = f"{settings['extra_system']}\n\n{voice_rules}".strip()

        return settings

    @staticmethod
    def _fix_mojibake(text: str) -> str:
        """Reverse CP1252-decoded-as-UTF8 mojibake from LLM outputs.

        LLMs output proper Unicode (curly quotes, em dashes, etc.) encoded
        as UTF-8.  Some API paths misinterpret those bytes as Windows-1252,
        producing garbled sequences like â€™ instead of ' or â€" instead of —.
        Strategy: if the text contains U+00E2 (â) or U+00C3 (Ã) — the
        tell-tale first bytes of multi-byte UTF-8 sequences misread as
        CP1252 — attempt a round-trip encode→decode to recover the original.
        Only commit the result if the round-trip succeeds without error.
        """
        if '\u00e2' not in text and '\u00c3' not in text:
            return text
        try:
            return text.encode('cp1252').decode('utf-8')
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        # Manual fallback for the most common sequences.
        return (text
            .replace('\u00e2\u20ac\u2122', '\u2019')   # â€™ → '  (right single quote)
            .replace('\u00e2\u20ac\u02dc', '\u2018')   # â€˜ → '  (left single quote)
            .replace('\u00e2\u20ac\u0153', '\u201c')   # â€œ → "  (left double quote)
            .replace('\u00e2\u20ac\u009d', '\u201d')   # â€  → "  (right double quote)
            .replace('\u00e2\u20ac\u201c', '\u2014')   # â€" → —  (em dash)
            .replace('\u00e2\u20ac\u201d', '\u2013')   # â€" → –  (en dash)
            .replace('\u00e2\u20ac\u00a6', '\u2026')   # â€¦ → …  (ellipsis)
            .replace('\u00c3\u00a9', '\u00e9')          # Ã© → é
            .replace('\u00c3\u00b6', '\u00f6')          # Ã¶ → ö
            .replace('\u00c3\u00bc', '\u00fc')          # Ã¼ → ü
            .replace('\u00c3\u00a4', '\u00e4')          # Ã¤ → ä
            .replace('\u00c3\u00b1', '\u00f1')          # Ã± → ñ
            .replace('\u00c3\u00a7', '\u00e7')          # Ã§ → ç
            .replace('\u00c3\u00b3', '\u00f3')          # Ã³ → ó
            .replace('\u00c3\u00a1', '\u00e1')          # Ã¡ → á
        )

    def _postprocess(self, text: str) -> str:
        text = text or ""
        # Fix UTF-8 mojibake — must come first before any other processing.
        # Covers degree symbol AND the broad CP1252 mis-decode that produces â€™ etc.
        text = self._fix_mojibake(text)
        text = text.replace('\u00c2\u00b0', '\u00b0')  # residual Â° → °
        text = text.replace('Â°', '°')                 # redundant safety net
        # Strip complete or dangling chain-of-thought reasoning blocks.
        text = re.sub(r"(?is)<think\b[^>]*>.*?(?:</think>|$)", " ", text)
        text = re.sub(r"(?i)</?think\b[^>]*>?", " ", text)
        # Strip generic filler openers
        text = re.sub(
            r"^(As an AI|I'm happy to help|Certainly|Sure,|Of course,|Absolutely,|Great!|Of course!),?\s*",
            "", text, flags=re.IGNORECASE
        )
        for sentence in _GENERIC_ASSISTANT_BOILERPLATE:
            text = re.sub(re.escape(sentence), " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()
        stripped = text.strip()
        if re.match(r"(?i)^protocol initiation confirmed\b", stripped):
            return "I need one more detail. What exactly do you want to do?"
        if re.match(r"(?i)^execution confirmed\b", stripped):
            return "What exactly should I do?"
        if re.match(r"(?i)^unknown term\.?(?:\s+yes[, ]+what(?:'s| is) the task\??)?$", stripped):
            return "I didn't catch that term. Say it again in a few words."
        text = re.sub(
            r"(?i)\s*(?:yes[,.]?\s*)?(?:what(?:'s| is) the task|what do you want to do)\??\s*$",
            "",
            text,
        ).strip()
        if re.fullmatch(r"(?i)(?:i'?m )?(?:ready|here|listening)(?: to assist(?: you)?)?\.?", text or ""):
            return "I'm listening. Finish the thought."
        return text

    # Patterns that can be answered instantly from local clock — no LLM needed.
    _TIME_QUERY_RE = re.compile(
        r'\b(?:what(?:\'?s|\s+is)\s+(?:the\s+)?(?:current\s+)?time|'
        r'(?:tell|give)\s+me\s+(?:the\s+)?(?:current\s+)?time|'
        r'what\s+time\s+is\s+it|'
        r'what\'?s\s+the\s+time|'
        r'current\s+time)\b',
        re.IGNORECASE,
    )
    _DATE_QUERY_RE = re.compile(
        r'\b(?:what(?:\'?s|\s+is)\s+(?:the\s+)?(?:current\s+)?(?:date|day)|'
        r'what\s+(?:day|date)\s+(?:is\s+it|today)|'
        r'today\'?s?\s+date|'
        r'what\'?s\s+today|'
        r'current\s+date)\b',
        re.IGNORECASE,
    )

    def _rewrite_generic_response(self, text: str) -> str:
        from datetime import datetime
        t = text.lower().strip()

        # Fast-path: time queries answered directly from local clock
        if self._TIME_QUERY_RE.search(t):
            return datetime.now().strftime("It's %I:%M %p.")

        # Fast-path: date queries answered directly from local clock
        if self._DATE_QUERY_RE.search(t):
            return datetime.now().strftime("Today is %A, %B %d, %Y.")

        if any(phrase in t for phrase in ["what should i work on", "what should i focus on", "what do i do next"]):
            return "Start with the single task that most moves your main project forward. Name the project and I'll narrow it down."
        return ""
