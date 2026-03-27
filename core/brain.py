"""
IRIS Brain — hardened version
- Structured logging
- Safe API-response parsing helpers
- Configurable timeouts via Config
- Deterministic fallbacks and no bare except-pass
- Thread-safe priority selection
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

import requests
from rich.console import Console

from config import Config

console = Console()
logger = logging.getLogger("IRIS.Brain")

# Avoid silently dropped messages if logging isn't configured at app startup
if not logger.handlers:
    logger.addHandler(logging.NullHandler())


class Brain:
    def __init__(self, memory):
        self.memory = memory
        self.available_apis: List[str] = []
        self._lock = threading.Lock()
        # detect available backends at init
        self._detect_apis()
        # compute primary/fallback (kept on instance; sync to Config once under lock)
        self.primary_brain, self.fallback_brain = self._compute_priority()
        with self._lock:
            try:
                Config.PRIMARY_BRAIN = self.primary_brain
                Config.FALLBACK_BRAIN = self.fallback_brain
            except Exception:
                logger.debug("Could not write primary/fallback to Config; using Brain instance values")

        # Warm local models in background if present
        if "ollama_fast" in self.available_apis or "ollama_smart" in self.available_apis:
            threading.Thread(target=self._warmup_ollama, daemon=True).start()

    # -------------------------
    # API detection and priority
    # -------------------------
    def _detect_apis(self) -> None:
        """Populate self.available_apis without crashing on network errors."""
        self.available_apis = []

        # Ollama (local)
        ollama_base = getattr(Config, "OLLAMA_BASE_URL", "http://localhost:11434")
        detect_timeout = getattr(Config, "OLLAMA_DETECT_TIMEOUT", 2)
        try:
            r = requests.get(f"{ollama_base}/api/tags", timeout=detect_timeout)
            if r.status_code == 200:
                # best-effort parse
                try:
                    models = [m.get("name") for m in r.json().get("models", []) if isinstance(m, dict)]
                except Exception:
                    models = []
                    logger.exception("Error parsing Ollama /api/tags response")
                    console.print_exception()
                # check configured models
                fast = getattr(Config, "OLLAMA_MODEL_FAST", "phi3.5")
                smart = getattr(Config, "OLLAMA_MODEL_SMART", "llama3.1:8b")
                deep = getattr(Config, "OLLAMA_MODEL_DEEP", "deepseek-r1:8b")
                for model, key in [(fast, "ollama_fast"), (smart, "ollama_smart"), (deep, "ollama_deep")]:
                    try:
                        if any((model.split(":")[0] in str(m)) for m in models):
                            self.available_apis.append(key)
                            logger.info("Detected local model %s -> %s", model, key)
                    except Exception:
                        logger.exception("Error checking Ollama model presence: %s", model)
                if not any(k in self.available_apis for k in ("ollama_fast", "ollama_smart", "ollama_deep")):
                    logger.warning("Ollama reachable but no configured models found. Expected at least %s", fast)
        except requests.RequestException as e:
            logger.info("Ollama not reachable; continuing with cloud providers (%s)", e)
        except Exception:
            logger.exception("Unexpected error while detecting Ollama")
            console.print_exception()

        # Cloud providers — use Config variables present in this repo
        if getattr(Config, "GROQ_API_KEY", None):
            self.available_apis.append("groq")
            logger.info("Groq key detected")
        if getattr(Config, "CLAUDE_API_KEY", None):
            self.available_apis.append("claude")
            logger.info("Claude/Anthropic key detected")
        if getattr(Config, "PERPLEXITY_API_KEY", None):
            self.available_apis.append("perplexity")
            logger.info("Perplexity key detected")
        if getattr(Config, "GEMINI_API_KEY", None):
            self.available_apis.append("gemini")
            logger.info("Gemini key detected")

        if not self.available_apis:
            logger.warning("No intelligence backends detected (local or cloud)")

    def _compute_priority(self) -> Tuple[str, str]:
        """Compute primary and fallback from Config.BRAIN_PRIORITY and detected apis."""
        priority = list(getattr(Config, "BRAIN_PRIORITY", ["groq", "gemini", "claude"]))
        primary = getattr(Config, "PRIMARY_BRAIN", "")
        fallback = primary

        for api in priority:
            if api in self.available_apis:
                primary = api
                break

        fallback = primary
        for api in priority:
            if api in self.available_apis and api != primary:
                fallback = api
                break

        logger.info("Priority computed primary=%s fallback=%s", primary, fallback)
        return primary, fallback

    def _update_priority(self) -> None:
        with self._lock:
            self.primary_brain, self.fallback_brain = self._compute_priority()
            try:
                Config.PRIMARY_BRAIN = self.primary_brain
                Config.FALLBACK_BRAIN = self.fallback_brain
            except Exception:
                logger.debug("Config writeback for priority skipped")

    # -------------------------
    # Utilities
    # -------------------------
    def _safe_extract(self, data: Any, path: List[str]) -> Optional[str]:
        """
        Safely traverse nested dict/list using path tokens.
        Numeric tokens are interpreted as list indices. Returns stripped string or None.
        """
        current = data
        try:
            for tok in path:
                if isinstance(current, list):
                    # tok should be index
                    idx = int(tok)
                    current = current[idx]
                elif isinstance(current, dict):
                    current = current.get(tok)
                else:
                    return None
                if current is None:
                    return None
            if isinstance(current, (str, int, float)):
                return str(current).strip()
            return None
        except (ValueError, IndexError, KeyError, TypeError) as e:
            logger.debug("safe_extract path error %s for path %s; data head: %s", e, path, repr(str(data)[:200]))
            return None
        except Exception:
            logger.exception("Unexpected error in safe_extract")
            console.print_exception()
            return None

    # -------------------------
    # High-level entrypoints
    # -------------------------
    def quick_ack(self, user_input: str) -> str:
        text = (user_input or "").lower().strip()
        if not text:
            return ""
        if any(x in text for x in ["wait", "hold on", "stop"]):
            return "All right."
        if any(x in text for x in ["hey", "hello", "hi", "you there", "are you there"]):
            return "I'm here."
        if len(text) > 70:
            return "One second."
        if any(x in text for x in ["check", "look up", "find", "search", "explain", "tell me"]):
            return "Checking."
        return ""

    def think(self, user_input: str, council_packet=None) -> str:
        """
        Main routing: local fast rewrites, ensemble or single-api routing, postprocessing.
        Behavior preserved for success paths; error paths return helpful fallback messages.
        """
        user_input = (user_input or "").strip()
        if not user_input:
            return "Try that again."

        # local quick rewrites
        direct = self._rewrite_generic_response(user_input)
        if direct:
            try:
                self.memory.add("user", user_input)
                self.memory.add("assistant", direct, source="local")
            except Exception:
                logger.exception("Memory update failed for local rewrite")
            return direct

        try:
            self.memory.add("user", user_input)
        except Exception:
            logger.exception("Memory.add failed")

        query_type = self._classify_query(user_input)
        extra_system = getattr(council_packet, "extra_system", "") if council_packet else ""
        allow_long = bool(getattr(council_packet, "allow_long_response", False))

        # Ensemble mode
        if getattr(Config, "USE_ENSEMBLE", False):
            final = self._ensemble_think(user_input, query_type)
            final = self._postprocess_response(final, user_input, allow_long_response=allow_long)
            try:
                self.memory.add("assistant", final, source="ensemble")
            except Exception:
                logger.exception("Memory.add failed for ensemble")
            return final

        # Web searches first when appropriate
        if query_type == "web_search" and "perplexity" in self.available_apis:
            resp = self._call_api("perplexity", user_input, use_persona=False, use_memory=False)
            if resp:
                final = self._postprocess_response(resp, user_input, allow_long_response=allow_long)
                try:
                    self.memory.add("assistant", final, source="perplexity")
                except Exception:
                    logger.exception("Memory.add failed for perplexity")
                return final

        # Build order and try each API
        word_count = len(user_input.split())
        lowered = user_input.lower()
        is_complex = any(w in lowered for w in ["explain", "analyse", "compare", "why", "how does", "summarise", "detail"])
        needs_reasoning = any(w in lowered for w in ["reason", "logic", "proof", "solve", "calculate", "plan", "strategy"])

        order = self._build_api_order(word_count, is_complex, needs_reasoning, council_packet)

        for api in order:
            if api not in self.available_apis:
                continue
            try:
                resp = self._call_api(api, user_input, use_persona=True, use_memory=True, allow_failover=False, extra_system=extra_system)
            except Exception:
                logger.exception("Unexpected error calling %s", api)
                resp = None
            if resp:
                final = self._postprocess_response(resp, user_input, allow_long_response=allow_long)
                try:
                    self.memory.add("assistant", final, source=api)
                except Exception:
                    logger.exception("Memory.add failed for %s", api)
                return final

        return self._fallback_response(user_input)

    # -------------------------
    # Routing helpers
    # -------------------------
    def _build_api_order(self, word_count: int, is_complex: bool, needs_reasoning: bool, council_packet=None) -> List[str]:
        if needs_reasoning and "ollama_deep" in self.available_apis:
            default_order = ["ollama_deep", "ollama_smart", "ollama_fast", "groq", "gemini", "claude"]
        elif is_complex or word_count > 15:
            default_order = ["ollama_smart", "ollama_fast", "groq", "gemini", "claude"]
        else:
            default_order = ["ollama_fast", "ollama_smart", "groq", "gemini", "claude"]

        if not council_packet:
            return default_order

        preferred = list(getattr(council_packet, "preferred_apis", []) or [])
        ordered: List[str] = []
        for api in preferred + default_order:
            if api not in ordered:
                ordered.append(api)
        return ordered

    # -------------------------
    # Local quick rewrites
    # -------------------------
    def _rewrite_generic_response(self, user_input: str) -> str:
        text = user_input.lower().strip()
        if any(phrase in text for phrase in ["how are you", "how're you", "how do you feel"]):
            return "Operational. What do you need?"
        if text in {"hello", "hi", "hey", "hey iris", "hi iris", "iris"}:
            return "I'm here."
        if text in {"can you help", "help", "i need help", "can you help me", "help me"}:
            return "Yes. What's the task?"
        if text in {"can you assist", "assist me", "i need assistance"}:
            return "Yes. What are you trying to do?"
        if ("codename" in text) or ("aletheia" in text and any(word in text for word in ["who", "what", "why"])):
            return f"My public name is {Config.PUBLIC_NAME}. Internally, the deeper core is {Config.INNER_CODENAME}."
        if text in {"who are you", "who are you really"}:
            return f"{Config.PUBLIC_NAME} on the surface. {Config.INNER_CODENAME} underneath."
        return ""

    # -------------------------
    # Query classification
    # -------------------------
    def _classify_query(self, text: str) -> str:
        text_lower = text.lower()
        web_keywords = getattr(Config, "WEB_KEYWORDS", ["latest", "today", "news", "current", "price", "weather", "stock", "score", "recent", "update"])
        code_keywords = getattr(Config, "CODE_KEYWORDS", ["python", "code", "script", "debug", "bug", "function", "class", "api", "json", "regex"])
        if any(word in text_lower for word in web_keywords):
            return "web_search"
        if any(word in text_lower for word in code_keywords):
            return "code"
        return "general"

    def _get_apis_for_query(self, query_type: str) -> List[str]:
        primary = getattr(Config, "PRIMARY_BRAIN", self.primary_brain or "groq")
        if query_type == "code":
            ordered = [primary, "groq", "gemini", "claude"]
        elif query_type == "web_search":
            ordered = ["perplexity", primary, "gemini", "groq", "claude"]
        else:
            ordered = [primary, getattr(Config, "FALLBACK_BRAIN", self.fallback_brain or primary), "gemini", "groq", "claude"]
        result: List[str] = []
        for api in ordered:
            if api in self.available_apis and api not in result:
                result.append(api)
        return result

    # -------------------------
    # Ensemble support
    # -------------------------
    def _ensemble_think(self, user_input: str, query_type: str) -> str:
        apis = self._get_apis_for_query(query_type)
        responses: Dict[str, str] = {}
        for api in apis[:3]:
            try:
                resp = self._call_api(api, user_input, use_persona=True, use_memory=True, allow_failover=False)
            except Exception:
                logger.exception("Error gathering ensemble response from %s", api)
                resp = None
            if resp:
                responses[api] = resp
        if not responses:
            return self._fallback_response(user_input)
        if len(responses) == 1:
            return next(iter(responses.values()))
        judge_prompt = self._build_judge_prompt(user_input, responses)
        judge_result = self._call_api(getattr(Config, "PRIMARY_BRAIN", self.primary_brain or "groq"), judge_prompt, use_persona=False, use_memory=False, allow_failover=False)
        if not judge_result:
            return next(iter(responses.values()))
        judge_result = judge_result.strip()
        if judge_result == "GENERATE_FRESH":
            fresh = self._call_api(getattr(Config, "PRIMARY_BRAIN", self.primary_brain or "groq"), user_input, use_persona=True, use_memory=True, allow_failover=False)
            return fresh or next(iter(responses.values()))
        if judge_result.startswith("NEEDS_POLISH:"):
            candidate = judge_result[len("NEEDS_POLISH:"):].strip()
            return self._polish(user_input, candidate)
        if judge_result.startswith("WINNER:"):
            return judge_result[len("WINNER:"):].strip()
        return next(iter(responses.values()))

    def _build_judge_prompt(self, question: str, responses: Dict[str, str]) -> str:
        min_score = 6
        polish_threshold = 8
        blocks = []
        for api, resp in responses.items():
            blocks.append(f"[Response from {api.upper()}]\n{resp}")
        responses_text = "\n\n".join(blocks)
        return f"""A user asked:
"{question}"

Here are candidate responses from different models:

{responses_text}

Choose the strongest answer.

Rules:
- Prefer accuracy first, then clarity, then natural tone.
- Penalize generic AI disclaimers.
- Penalize robotic filler and unnecessary verbosity.
- Prefer concrete answers over vague conversational padding.
- If none are good enough, choose GENERATE_FRESH.

Respond with exactly one of these formats:
WINNER: <best response>
NEEDS_POLISH: <response needing cleanup>
GENERATE_FRESH

Thresholds:
- Below {min_score}/10 -> GENERATE_FRESH
- {min_score} to {polish_threshold}/10 -> NEEDS_POLISH
- Above {polish_threshold}/10 -> WINNER"""

    def _polish(self, question: str, response: str) -> str:
        polish_prompt = f"""A user asked:
"{question}"

This draft answer is usable but needs cleanup:
"{response}"

Rewrite it to sound natural, sharp, concise, and specific.
Remove filler.
Prefer concrete wording.
Return only the improved response."""
        polished = self._call_api(getattr(Config, "PRIMARY_BRAIN", self.primary_brain or "groq"), polish_prompt, use_persona=False, use_memory=False)
        return polished or response

    # -------------------------
    # Ollama local calls
    # -------------------------
    def _warmup_ollama(self) -> None:
        models_to_warm: List[str] = []
        if "ollama_fast" in self.available_apis:
            models_to_warm.append(getattr(Config, "OLLAMA_MODEL_FAST", "phi3.5"))
        if "ollama_smart" in self.available_apis:
            models_to_warm.append(getattr(Config, "OLLAMA_MODEL_SMART", "llama3.1:8b"))
        for model in models_to_warm:
            try:
                requests.post(
                    f"{getattr(Config, 'OLLAMA_BASE_URL', 'http://localhost:11434')}/api/generate",
                    json={"model": model, "prompt": "hi", "stream": False, "options": {"num_predict": 1}},
                    timeout=getattr(Config, "OLLAMA_WARMUP_TIMEOUT", 30),
                )
                logger.info("Warmed up Ollama model %s", model)
            except Exception:
                logger.exception("Failed to warm up Ollama model %s", model)

    def _call_ollama(self, model: str, prompt: str, use_persona: bool, use_memory: bool, extra_system: str = "") -> Optional[str]:
        base_url = getattr(Config, "OLLAMA_BASE_URL", "http://localhost:11434")
        full_prompt = ""
        if use_persona:
            full_prompt += f"{self._persona_text(extra_system)}\n\n"
        if use_memory:
            try:
                ctx = self._memory_context(3)
                for item in ctx:
                    role = "User" if item["role"] == "user" else "Iris"
                    full_prompt += f"{role}: {item['content']}\n"
            except Exception:
                logger.exception("Memory context building failed for Ollama")
        full_prompt += f"User: {prompt}\nIris:"
        try:
            resp = requests.post(
                f"{base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {"temperature": 0.4, "num_predict": getattr(Config, "OLLAMA_NUM_PREDICT", 150), "stop": ["\nUser:", "\nHuman:", "\n\n"]},
                },
                timeout=getattr(Config, "OLLAMA_INFER_TIMEOUT", 15),
            )
            resp.raise_for_status()
            payload = resp.json()
            # Ollama may return top-level "response" or other shapes
            if isinstance(payload, dict) and "response" in payload:
                text = payload.get("response", "")
            else:
                text = self._safe_extract(payload, ["choices", "0", "message", "content"])
            if text:
                text = re.sub(r"^(Iris:|Assistant:)\s*", "", str(text)).strip()
                return text or None
        except Exception:
            logger.exception("Ollama call failed for %s", model)
        return None

    # -------------------------
    # Generic API router + safe calls
    # -------------------------
    def _call_api(self, api: str, prompt: str, use_persona: bool = True, use_memory: bool = False, allow_failover: bool = True, extra_system: str = "") -> Optional[str]:
        try:
            if api == "ollama_fast":
                return self._call_ollama(getattr(Config, "OLLAMA_MODEL_FAST", "phi3.5"), prompt, use_persona, use_memory, extra_system=extra_system)
            if api == "ollama_smart":
                return self._call_ollama(getattr(Config, "OLLAMA_MODEL_SMART", "llama3.1:8b"), prompt, use_persona, use_memory, extra_system=extra_system)
            if api == "ollama_deep":
                return self._call_ollama(getattr(Config, "OLLAMA_MODEL_DEEP", "deepseek-r1:8b"), prompt, use_persona, use_memory, extra_system=extra_system)
            if api == "groq":
                return self._call_groq(prompt, use_persona, use_memory, extra_system=extra_system)
            if api == "gemini":
                return self._call_gemini(prompt, use_persona, use_memory, extra_system=extra_system)
            if api == "claude":
                return self._call_claude(prompt, use_persona, use_memory, extra_system=extra_system)
            if api == "perplexity":
                return self._call_perplexity(prompt)
        except Exception:
            logger.exception("Error during API call to %s", api)
            # failover to fallback brain if configured
            try:
                if allow_failover and api == getattr(Config, "PRIMARY_BRAIN", self.primary_brain or ""):
                    fallback = getattr(Config, "FALLBACK_BRAIN", self.fallback_brain or "")
                    if fallback and fallback != api:
                        logger.info("Attempting failover from %s to %s", api, fallback)
                        return self._call_api(fallback, prompt, use_persona=use_persona, use_memory=use_memory, allow_failover=False, extra_system=extra_system)
            except Exception:
                logger.exception("Failover attempt failed")
        return None

    def _call_groq(self, prompt: str, use_persona: bool, use_memory: bool, extra_system: str = "") -> Optional[str]:
        headers = {"Authorization": f"Bearer {Config.GROQ_API_KEY}", "Content-Type": "application/json"}
        messages = []
        if use_persona:
            messages.append({"role": "system", "content": self._persona_text(extra_system)})
        if use_memory:
            messages.extend(self._memory_context(getattr(Config, "MAX_MEMORY_TURNS", 8)))
        messages.append({"role": "user", "content": self._build_user_prompt(prompt)})
        payload = {"model": Config.GROQ_MODEL, "messages": messages, "temperature": 0.4, "max_tokens": getattr(Config, "GROQ_MAX_TOKENS", 150)}
        try:
            response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=getattr(Config, "GROQ_TIMEOUT", 12))
            response.raise_for_status()
            data = response.json()
            content = self._safe_extract(data, ["choices", "0", "message", "content"])
            if content is None:
                logger.error("Groq returned unexpected schema: %s", data)
            return content
        except Exception:
            logger.exception("Groq call failed")
            return None

    def _call_gemini(self, prompt: str, use_persona: bool, use_memory: bool, extra_system: str = "") -> Optional[str]:
        try:
            from google import genai
            from google.genai import types
        except Exception:
            logger.exception("Gemini client import failed")
            return None
        try:
            client = genai.Client(api_key=Config.GEMINI_API_KEY)
            messages = []
            if use_memory:
                for item in self._memory_context(getattr(Config, "MAX_MEMORY_TURNS", 8)):
                    role = "user" if item.get("role") == "user" else "model"
                    messages.append({"role": role, "parts": [{"text": item.get("content", "")}]} )
            messages.append({"role": "user", "parts": [{"text": prompt}]})
            response = client.models.generate_content(model=Config.GEMINI_MODEL, contents=messages, config=types.GenerateContentConfig(system_instruction=self._persona_text(extra_system) if use_persona else None, max_output_tokens=getattr(Config, "GEMINI_MAX_TOKENS", 500), temperature=0.4))
            return getattr(response, "text", None)
        except Exception:
            logger.exception("Gemini call failed")
            return None

    def _call_claude(self, prompt: str, use_persona: bool, use_memory: bool, extra_system: str = "") -> Optional[str]:
        headers = {"x-api-key": Config.CLAUDE_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        system_text = self._persona_text(extra_system) if use_persona else ""
        memory_text = ""
        if use_memory:
            chunks = []
            for item in self._memory_context(getattr(Config, "MAX_MEMORY_TURNS", 8)):
                role = item.get("role", "user").upper()
                chunks.append(f"{role}: {item.get('content', '')}")
            memory_text = "\n".join(chunks)
        final_prompt = prompt if not memory_text else f"{memory_text}\n\nUser: {prompt}"
        payload = {"model": Config.CLAUDE_MODEL, "max_tokens": getattr(Config, "CLAUDE_MAX_TOKENS", 700), "temperature": 0.4, "system": system_text, "messages": [{"role": "user", "content": final_prompt}]}
        try:
            response = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=getattr(Config, "CLAUDE_TIMEOUT", 45))
            response.raise_for_status()
            data = response.json()
            text = self._safe_extract(data, ["content", "0", "text"])
            if text is None:
                logger.error("Claude returned unexpected schema: %s", data)
            return text
        except Exception:
            logger.exception("Claude call failed")
            return None

    def _call_perplexity(self, prompt: str) -> Optional[str]:
        headers = {"Authorization": f"Bearer {Config.PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": Config.PERPLEXITY_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}
        try:
            response = requests.post("https://api.perplexity.ai/chat/completions", headers=headers, json=payload, timeout=getattr(Config, "PERPLEXITY_TIMEOUT", 60))
            response.raise_for_status()
            data = response.json()
            content = self._safe_extract(data, ["choices", "0", "message", "content"])
            if content is None:
                logger.error("Perplexity returned unexpected schema: %s", data)
            return content
        except Exception:
            logger.exception("Perplexity call failed")
            return None

    # -------------------------
    # Prompt/memory helpers & postprocessing
    # -------------------------
    def _persona_text(self, extra_system: str = "") -> str:
        persona = getattr(Config, "IRIS_PERSONA", "")
        voice_style = getattr(Config, "VOICE_RESPONSE_STYLE", "")
        parts = [p.strip() for p in (persona, voice_style, extra_system) if p and p.strip()]
        if not parts:
            return "Your name is Iris. Speak naturally, directly, clearly, and specifically. Never use AI disclaimers."
        return "\n\n".join(parts)

    def _memory_context(self, max_turns: int = 3) -> List[Dict[str, str]]:
        try:
            raw_context = self.memory.get_context(max_turns)
        except Exception:
            logger.exception("Failed to read memory context")
            raw_context = []
        filtered: List[Dict[str, str]] = []
        generic_patterns = [r"\bi(?: am|'m) (?:just )?(?:a )?(?:large )?language model\b", r"\bas an ai\b", r"\bi do not have feelings\b", r"\bi don't have feelings\b", r"\bi do not have emotions\b", r"\bi don't have emotions\b"]
        for item in raw_context:
            role = item.get("role", "")
            content = (item.get("content") or "").strip()
            if not content:
                continue
            if role == "assistant":
                if any(re.search(pat, content, flags=re.IGNORECASE) for pat in generic_patterns):
                    continue
            filtered.append({"role": role, "content": content})
        return filtered[-max_turns * 2:]

    def _build_user_prompt(self, user_input: str) -> str:
        return user_input.strip()

    def _postprocess_response(self, text: str, user_input: str, allow_long_response: bool = False) -> str:
        if not text:
            return self._fallback_response(user_input)
        clean = text.strip()
        clean = re.sub(r"^\s*(Sure|Absolutely|Certainly|Of course)[.!]?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\bAs an AI[^.]*\.\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\bI am an AI[^.]*\.\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\bI(?:'m| am) happy to help[.!]?\s*", "", clean, flags=re.IGNORECASE)
        short_mode = bool(getattr(Config, "SHORT_VOICE_RESPONSES", False)) and not allow_long_response
        if short_mode:
            clean = self._shorten_response(clean)
        return clean.strip()

    def _shorten_response(self, text: str) -> str:
        max_sentences = int(getattr(Config, "VOICE_MAX_SENTENCES", 2))
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return text.strip()
        return " ".join(sentences[:max_sentences]).strip()

    def _fallback_response(self, query: str) -> str:
        lowered = (query or "").lower()
        if any(word in lowered for word in ["hello", "hi", "hey", "you there"]):
            return "Still here."
        return "Something upstream failed. Check the API keys, packages, and network, then try again."