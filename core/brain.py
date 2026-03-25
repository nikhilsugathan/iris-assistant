"""
IRIS Brain v4
=============
Primary reasoning + API routing + cleanup.
Local LLM first (Ollama), cloud APIs as fallback.
"""

from __future__ import annotations

import json
import random
import re
import threading
from typing import Dict, List, Optional

import requests
from rich.console import Console

from config import Config
from core.context_intel import ClipboardIntel, DesktopIntel
from core.environment import EnvironmentIntel
from core.system_intel import SystemIntel

console = Console()


class Brain:
    def __init__(self, memory):
        self.memory = memory
        self.system_intel = SystemIntel()
        self.environment = EnvironmentIntel()
        self.desktop_intel = DesktopIntel()
        self.clipboard_intel = ClipboardIntel()
        self._last_variant_by_bucket: Dict[str, str] = {}
        self.available_apis = self._detect_apis()
        self._update_priority()
        # Pre-warm local models in background so first call is instant
        if "ollama_fast" in self.available_apis or "ollama_smart" in self.available_apis:
            threading.Thread(target=self._warmup_ollama, daemon=True).start()

    # ─────────────────────────────────────────────────────────────
    # API DETECTION / PRIORITY
    # ─────────────────────────────────────────────────────────────

    def _detect_apis(self) -> List[str]:
        available = []

        # ── Local LLM (Ollama) — check first, highest priority ──
        ollama_base = getattr(Config, "OLLAMA_BASE_URL", "http://localhost:11434")
        try:
            resp = requests.get(f"{ollama_base}/api/tags", timeout=2)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                fast_model  = getattr(Config, "OLLAMA_MODEL_FAST", "phi3.5")
                smart_model = getattr(Config, "OLLAMA_MODEL_SMART", "llama3.1:8b")
                deep_model  = getattr(Config, "OLLAMA_MODEL_DEEP", "deepseek-r1:8b")

                # Check which models are actually downloaded
                for model, key in [(fast_model, "ollama_fast"), (smart_model, "ollama_smart"), (deep_model, "ollama_deep")]:
                    if any(self._ollama_model_matches(model, available_name) for available_name in models):
                        available.append(key)
                        print(f"  [✓] Ollama {key} ({model}) detected")

                if not any(k in available for k in ["ollama_fast", "ollama_smart", "ollama_deep"]):
                    print(f"  [!] Ollama running but no models found. Run: ollama pull phi3.5")
        except Exception:
            print("  [!] Ollama not running — using cloud APIs only")

        if getattr(Config, "GEMINI_API_KEY", ""):
            print("  [✓] Gemini API detected")
            available.append("gemini")

        if getattr(Config, "GROQ_API_KEY", ""):
            print("  [✓] Groq API detected")
            available.append("groq")

        if getattr(Config, "CLAUDE_API_KEY", ""):
            print("  [✓] Claude API detected")
            available.append("claude")

        if getattr(Config, "PERPLEXITY_API_KEY", ""):
            print("  [✓] Perplexity API detected")
            available.append("perplexity")

        if not available:
            print("  [!] No APIs found")

        return available

    def _ollama_model_matches(self, configured_model: str, available_name: str) -> bool:
        configured = str(configured_model or "").strip().lower()
        available = str(available_name or "").strip().lower()
        if not configured or not available:
            return False
        if available == configured:
            return True
        if ":" not in configured:
            return available.split(":", 1)[0] == configured
        return available.startswith(f"{configured}:")

    def _update_priority(self) -> None:
        priority = list(getattr(Config, "BRAIN_PRIORITY", ["groq", "gemini", "claude"]))

        for api in priority:
            if api in self.available_apis:
                Config.PRIMARY_BRAIN = api
                break

        Config.FALLBACK_BRAIN = Config.PRIMARY_BRAIN
        for api in priority:
            if api in self.available_apis and api != Config.PRIMARY_BRAIN:
                Config.FALLBACK_BRAIN = api
                break

    # ─────────────────────────────────────────────────────────────
    # MAIN ENTRY
    # ─────────────────────────────────────────────────────────────

    def startup_greeting(self) -> str:
        return self._pick_variant(
            "startup_greeting",
            getattr(Config, "STARTUP_GREETINGS", []),
            default="Systems online. Ready when you are.",
        )

    def plan_action_json(self, prompt: str) -> Optional[str]:
        return self._call_local_first_planner(
            prompt,
            max_tokens=getattr(Config, "ACTION_PLAN_MAX_TOKENS", 480),
        )

    def diagnose_command_failure(self, prompt: str) -> Optional[str]:
        return self._call_local_first_planner(
            prompt,
            max_tokens=getattr(Config, "COMMAND_FIX_MAX_TOKENS", 160),
        )

    def _call_local_first_planner(self, prompt: str, max_tokens: int) -> Optional[str]:
        planner_model = getattr(
            Config,
            "OLLAMA_MODEL_PLANNER",
            getattr(Config, "OLLAMA_MODEL_SMART", "llama3.1:8b"),
        )

        if any(api in self.available_apis for api in ("ollama_fast", "ollama_smart", "ollama_deep")):
            response = self._call_ollama(
                planner_model,
                prompt,
                use_persona=False,
                use_memory=False,
                max_tokens=max_tokens,
            )
            if response:
                return response

        primary = getattr(Config, "PRIMARY_BRAIN", "groq")
        response = self._call_api(
            primary,
            prompt,
            use_persona=False,
            use_memory=False,
            max_tokens=max_tokens,
        )
        if response:
            return response

        fallback = getattr(Config, "FALLBACK_BRAIN", primary)
        if fallback and fallback != primary:
            return self._call_api(
                fallback,
                prompt,
                use_persona=False,
                use_memory=False,
                allow_failover=False,
                max_tokens=max_tokens,
            )

        return None

    def quick_ack(self, user_input: str) -> str:
        text = (user_input or "").lower().strip()

        if not text:
            return ""

        if any(x in text for x in ["wait", "hold on", "stop"]):
            return self._pick_variant(
                "hold_ack",
                getattr(Config, "HOLD_ACKS", []),
                default="All right.",
            )

        if any(
            x in text
            for x in ["hey", "hello", "hi", "iris you there", "you there", "are you there"]
        ):
            return self._pick_variant(
                "hello_ack",
                getattr(Config, "GREETING_RESPONSES", []),
                default="I'm here.",
            )

        if len(text) > 70:
            return self._pick_variant(
                "thinking_ack",
                getattr(Config, "THINKING_ACKS", []),
                default="One second.",
            )

        if any(
            x in text
            for x in ["check", "look up", "find", "search", "explain", "tell me", "what is", "how does"]
        ):
            return self._pick_variant(
                "search_ack",
                getattr(Config, "SEARCH_ACKS", []),
                default="Checking.",
            )

        return ""

    def think(self, user_input: str, council_packet=None) -> str:
        return self.think_with_stream(user_input, council_packet=council_packet, stream_callback=None)

    def think_with_stream(self, user_input: str, council_packet=None, stream_callback=None) -> str:
        """
        Smart routing:
        - Simple/short → ollama_fast (phi3.5, instant)
        - Complex/long → ollama_smart (llama3.1:8b, fast)
        - Reasoning    → ollama_deep (deepseek-r1, thorough)
        - Web data     → perplexity
        - Fallback     → groq → claude
        """
        user_input = (user_input or "").strip()
        if not user_input:
            return "Try that again."

        # Instant local rewrites — no API needed
        direct = self._rewrite_generic_response(user_input)
        if direct:
            self.memory.add("user", user_input)
            self.memory.add("assistant", direct, source="local")
            return direct

        desktop_data = self.desktop_intel.answer_query(user_input)
        if desktop_data:
            self.memory.add("user", user_input)
            self.memory.add("assistant", desktop_data, source="desktop-local")
            return desktop_data

        clipboard_data = self.clipboard_intel.answer_query(user_input)
        if clipboard_data:
            self.memory.add("user", user_input)
            self.memory.add("assistant", clipboard_data, source="clipboard-local")
            return clipboard_data

        system_data = self.system_intel.answer_query(user_input)
        if system_data:
            self.memory.add("user", user_input)
            self.memory.add("assistant", system_data, source="system-local")
            return system_data

        live_data = self.environment.answer_query(user_input)
        if live_data:
            self.memory.add("user", user_input)
            self.memory.add("assistant", live_data, source="live-data")
            return live_data

        self.memory.add("user", user_input)
        effective_input, clipboard_error = self.clipboard_intel.build_prompt(user_input)
        if clipboard_error:
            self.memory.add("assistant", clipboard_error, source="clipboard-local")
            return clipboard_error
        effective_input = effective_input or user_input
        query_type = self._classify_query(effective_input)
        extra_system = getattr(council_packet, "extra_system", "") if council_packet else ""
        allow_long_response = bool(getattr(council_packet, "allow_long_response", False))

        if getattr(Config, "USE_ENSEMBLE", False):
            final = self._ensemble_think(effective_input, query_type)
            final = self._postprocess_response(final, user_input, allow_long_response=allow_long_response)
            self.memory.add("assistant", final, source="ensemble")
            return final

        # Web search → Perplexity
        if query_type == "web_search" and "perplexity" in self.available_apis:
            resp = self._call_api("perplexity", effective_input, use_persona=False, use_memory=False)
            if resp:
                final = self._postprocess_response(resp, user_input, allow_long_response=allow_long_response)
                self.memory.add("assistant", final, source="perplexity")
                return final

        # Smart routing based on query complexity
        lowered_effective = effective_input.lower()
        word_count = len(effective_input.split())
        is_complex = any(w in lowered_effective for w in [
            "explain", "analyse", "compare", "why", "how does", "what is the difference",
            "reason", "think", "evaluate", "summarise", "detail"
        ])
        needs_reasoning = any(w in lowered_effective for w in [
            "reason", "logic", "proof", "solve", "calculate", "plan", "strategy"
        ])

        order = self._build_api_order(
            word_count=word_count,
            is_complex=is_complex,
            needs_reasoning=needs_reasoning,
            council_packet=council_packet,
        )

        for api in order:
            if api not in self.available_apis:
                continue
            resp = self._call_api(
                api,
                effective_input,
                use_persona=True,
                use_memory=True,
                allow_failover=False,
                extra_system=extra_system,
                stream_callback=stream_callback,
            )
            if resp:
                final = self._postprocess_response(resp, user_input, allow_long_response=allow_long_response)
                self.memory.add("assistant", final, source=api)
                return final

        return self._fallback_response(user_input)

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

    # ─────────────────────────────────────────────────────────────
    # FAST LOCAL REWRITES FOR GENERIC VOICE INPUT
    # ─────────────────────────────────────────────────────────────

    def _rewrite_generic_response(self, user_input: str) -> str:
        text = user_input.lower().strip()

        if any(phrase in text for phrase in ["how are you", "how're you", "how do you feel"]):
            return self._pick_variant(
                "status_response",
                getattr(Config, "STATUS_RESPONSES", []),
                default="Operational. What do you need?",
            )

        if text in {"hello", "hi", "hey", "hey iris", "hi iris", "iris", "yo iris", "good morning iris", "good evening iris"}:
            return self._pick_variant(
                "greeting_response",
                getattr(Config, "GREETING_RESPONSES", []),
                default="I'm here.",
            )

        if text in {
            "can you help",
            "help",
            "i need help",
            "can you help me",
            "help me",
        }:
            return self._pick_variant(
                "help_response",
                getattr(Config, "HELP_RESPONSES", []),
                default="Yes. What's the task?",
            )

        if text in {"can you assist", "assist me", "i need assistance"}:
            return self._pick_variant(
                "assist_response",
                getattr(Config, "HELP_RESPONSES", []),
                default="Yes. What are you trying to do?",
            )

        if text in {"thanks", "thank you", "thanks iris", "thank you iris"}:
            return self._pick_variant(
                "thanks_response",
                getattr(Config, "THANKS_RESPONSES", []),
                default="You're welcome.",
            )

        if (
            "codename" in text
            or ("aletheia" in text and any(word in text for word in ["who", "what", "why"]))
        ):
            return f"My public name is {Config.PUBLIC_NAME}. I keep internal implementation details private."

        if text in {"who are you", "who are you really"}:
            return f"I'm {Config.PUBLIC_NAME}."

        return ""

    def _pick_variant(self, bucket: str, options: List[str], default: str = "") -> str:
        items = [str(item).strip() for item in (options or []) if str(item).strip()]
        if not items:
            return default

        last = self._last_variant_by_bucket.get(bucket)
        choices = [item for item in items if item != last]
        selected = random.choice(choices or items)
        self._last_variant_by_bucket[bucket] = selected
        return selected

    # ─────────────────────────────────────────────────────────────
    # QUERY ROUTING
    # ─────────────────────────────────────────────────────────────

    def _classify_query(self, text: str) -> str:
        text_lower = text.lower()

        web_keywords = list(
            getattr(
                Config,
                "WEB_KEYWORDS",
                [
                    "latest", "today", "news", "current", "price",
                    "weather", "stock", "score", "recent", "update",
                ],
            )
        )
        code_keywords = getattr(
            Config,
            "CODE_KEYWORDS",
            [
                "python", "code", "script", "debug", "bug",
                "function", "class", "api", "json", "regex",
            ],
        )

        if self._requires_live_web_search(text_lower, web_keywords):
            return "web_search"
        if any(word in text_lower for word in code_keywords):
            return "code"
        return "general"

    def _requires_live_web_search(self, text_lower: str, web_keywords: list[str]) -> bool:
        explicit_online_phrases = [
            "search the web",
            "search online",
            "search the internet",
            "look it up online",
            "check online",
            "browse online",
        ]
        if any(phrase in text_lower for phrase in explicit_online_phrases):
            return True

        live_subjects = [
            "weather",
            "forecast",
            "price",
            "stock",
            "score",
            "news",
            "exchange rate",
            "flight",
            "hotel",
            "restaurant near me",
            "bitcoin",
            "crypto",
        ]
        if any(subject in text_lower for subject in live_subjects):
            return True

        recency_markers = ["latest", "today", "current", "now", "recent", "recently", "update"]
        public_office_terms = ["president", "prime minister", "ceo", "governor", "mayor"]
        if any(marker in text_lower for marker in recency_markers) and any(
            term in text_lower for term in public_office_terms
        ):
            return True

        if not getattr(Config, "PREFER_LOCAL_RESOURCES", True):
            return any(word in text_lower for word in web_keywords)

        return False

    def _get_apis_for_query(self, query_type: str) -> List[str]:
        primary = getattr(Config, "PRIMARY_BRAIN", "groq")

        if query_type == "code":
            ordered = [primary, "groq", "gemini", "claude"]
        elif query_type == "web_search":
            ordered = ["perplexity", primary, "gemini", "groq", "claude"]
        else:
            ordered = [primary, getattr(Config, "FALLBACK_BRAIN", primary), "gemini", "groq", "claude"]

        result: List[str] = []
        for api in ordered:
            if api in self.available_apis and api not in result:
                result.append(api)
        return result

    # ─────────────────────────────────────────────────────────────
    # ENSEMBLE
    # ─────────────────────────────────────────────────────────────

    def _ensemble_think(self, user_input: str, query_type: str) -> str:
        apis = self._get_apis_for_query(query_type)
        responses: Dict[str, str] = {}

        for api in apis[:3]:
            resp = self._call_api(api, user_input, use_persona=True, use_memory=True, allow_failover=False)
            if resp:
                responses[api] = resp

        if not responses:
            return self._fallback_response(user_input)

        if len(responses) == 1:
            return next(iter(responses.values()))

        judge_prompt = self._build_judge_prompt(user_input, responses)
        judge_result = self._call_api(
            getattr(Config, "PRIMARY_BRAIN", "groq"),
            judge_prompt,
            use_persona=False,
            use_memory=False,
            allow_failover=False,
        )

        if not judge_result:
            return next(iter(responses.values()))

        judge_result = judge_result.strip()

        if judge_result == "GENERATE_FRESH":
            fresh = self._call_api(
                getattr(Config, "PRIMARY_BRAIN", "groq"),
                user_input,
                use_persona=True,
                use_memory=True,
                allow_failover=False,
            )
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

        polished = self._call_api(
            getattr(Config, "PRIMARY_BRAIN", "groq"),
            polish_prompt,
            use_persona=False,
            use_memory=False,
        )
        return polished or response

    # ─────────────────────────────────────────────────────────────
    # SINGLE MODE
    # ─────────────────────────────────────────────────────────────

    def _single_think(self, user_input: str, api: str) -> str:
        response = self._call_api(api, user_input, use_persona=True, use_memory=True)
        if response:
            return response
        return self._fallback_response(user_input)

    # ─────────────────────────────────────────────────────────────
    # PROMPT + MEMORY
    # ─────────────────────────────────────────────────────────────

    def _persona_text(self, extra_system: str = "") -> str:
        persona = getattr(Config, "IRIS_PERSONA", "")
        voice_style = getattr(Config, "VOICE_RESPONSE_STYLE", "")

        parts = [persona.strip()] if persona else []
        if voice_style:
            parts.append(str(voice_style).strip())
        if extra_system:
            parts.append(str(extra_system).strip())

        if not parts:
            return (
                "Your name is Iris. Speak naturally, directly, clearly, and specifically. "
                "Never use AI disclaimers."
            )

        return "\n\n".join(part for part in parts if part)

    def _memory_context(self, max_turns: int = 3) -> List[Dict[str, str]]:
        raw_context = self.memory.get_context(max_turns)
        filtered: List[Dict[str, str]] = []

        generic_patterns = [
            r"\bi(?: am|'m) (?:just )?(?:a )?(?:large )?language model\b",
            r"\bas an ai\b",
            r"\bi do not have feelings\b",
            r"\bi don't have feelings\b",
            r"\bi do not have emotions\b",
            r"\bi don't have emotions\b",
        ]

        for item in raw_context:
            role = item.get("role", "")
            content = (item.get("content") or "").strip()
            if not content:
                continue

            if role == "assistant":
                if any(re.search(pattern, content, flags=re.IGNORECASE) for pattern in generic_patterns):
                    continue

            filtered.append({"role": role, "content": content})

        return filtered[-max_turns * 2:]

    def _build_user_prompt(self, user_input: str) -> str:
        return user_input.strip()

    # ─────────────────────────────────────────────────────────────
    # POST-PROCESSING
    # ─────────────────────────────────────────────────────────────

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

    # ─────────────────────────────────────────────────────────────
    # OLLAMA — Local LLM
    # ─────────────────────────────────────────────────────────────

    def _warmup_ollama(self):
        """Pre-warm both local models so first real call is instant."""
        models_to_warm = []
        if "ollama_fast" in self.available_apis:
            models_to_warm.append(getattr(Config, "OLLAMA_MODEL_FAST", "phi3.5"))
        if "ollama_smart" in self.available_apis:
            models_to_warm.append(getattr(Config, "OLLAMA_MODEL_SMART", "llama3.1:8b"))

        for model in models_to_warm:
            try:
                requests.post(
                    f"{getattr(Config, 'OLLAMA_BASE_URL', 'http://localhost:11434')}/api/generate",
                    json={"model": model, "prompt": "hi", "stream": False, "options": {"num_predict": 1}},
                    timeout=30,
                )
                console.print(f"[dim]✓ Warmed up {model}[/dim]")
            except Exception:
                pass

    def _call_ollama(
        self,
        model: str,
        prompt: str,
        use_persona: bool,
        use_memory: bool,
        extra_system: str = "",
        max_tokens: int | None = None,
        stream_callback=None,
    ) -> Optional[str]:
        """Call a local Ollama model."""
        base_url = getattr(Config, "OLLAMA_BASE_URL", "http://localhost:11434")
        token_limit = max(32, int(max_tokens if max_tokens is not None else 150))

        # Build full prompt with persona and memory
        full_prompt = ""
        if use_persona:
            full_prompt += f"{self._persona_text(extra_system)}\n\n"
        if use_memory:
            ctx = self._memory_context(3)
            for item in ctx:
                role = "User" if item["role"] == "user" else "Iris"
                full_prompt += f"{role}: {item['content']}\n"
        full_prompt += f"User: {prompt}\nIris:"

        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": 0.4,
                "num_predict": token_limit,
                "stop": ["\nUser:", "\nHuman:", "\n\n"],
            }
        }

        if stream_callback:
            try:
                return self._call_ollama_streaming(base_url, payload, stream_callback=stream_callback)
            except Exception:
                pass

        try:
            return self._call_ollama_blocking(base_url, payload)
        except Exception:
            return None

    def _call_ollama_blocking(self, base_url: str, payload: dict) -> Optional[str]:
        resp = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
        text = re.sub(r"^(Iris:|Assistant:)\s*", "", text).strip()
        return text if text else None

    def _call_ollama_streaming(self, base_url: str, payload: dict, stream_callback) -> Optional[str]:
        payload = dict(payload)
        payload["stream"] = True
        resp = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            stream=True,
            timeout=30,
        )
        resp.raise_for_status()

        pieces: list[str] = []
        sentence_buffer = ""

        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            chunk = json.loads(line)
            token = str(chunk.get("response", "") or "")
            if token:
                pieces.append(token)
                sentence_buffer += token
                sentence_buffer = self._emit_stream_ready_sentences(sentence_buffer, stream_callback)
            if chunk.get("done"):
                break

        trailing = self._clean_streaming_chunk(sentence_buffer)
        if trailing:
            try:
                stream_callback(trailing)
            except Exception:
                pass

        text = "".join(pieces).strip()
        text = re.sub(r"^(Iris:|Assistant:)\s*", "", text).strip()
        return text if text else None

    def _emit_stream_ready_sentences(self, buffer: str, stream_callback) -> str:
        text = buffer or ""
        while True:
            match = re.search(r"(.+?[.!?])(?:\s+|$)", text, flags=re.DOTALL)
            if not match:
                return text
            sentence = self._clean_streaming_chunk(match.group(1))
            if sentence:
                try:
                    stream_callback(sentence)
                except Exception:
                    pass
            text = text[match.end():]

    def _clean_streaming_chunk(self, text: str) -> str:
        clean = (text or "").strip()
        if not clean:
            return ""
        clean = re.sub(r"^(Iris:|Assistant:)\s*", "", clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r"^\s*(Sure|Absolutely|Certainly|Of course)[,!]?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\bAs an AI[^.?!]*[.?!]?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\bI am an AI[^.?!]*[.?!]?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\bI(?:'m| am) happy to help[.!]?\s*", "", clean, flags=re.IGNORECASE)
        return clean.strip()

    # ─────────────────────────────────────────────────────────────
    # API ROUTER
    # ─────────────────────────────────────────────────────────────

    def _call_api(
        self,
        api: str,
        prompt: str,
        use_persona: bool = True,
        use_memory: bool = False,
        allow_failover: bool = True,
        extra_system: str = "",
        max_tokens: int | None = None,
        stream_callback=None,
    ) -> Optional[str]:
        try:
            if api == "ollama_fast":
                return self._call_ollama(
                    getattr(Config, "OLLAMA_MODEL_FAST", "phi3.5"),
                    prompt,
                    use_persona,
                    use_memory,
                    extra_system=extra_system,
                    max_tokens=max_tokens,
                    stream_callback=stream_callback,
                )
            if api == "ollama_smart":
                return self._call_ollama(
                    getattr(Config, "OLLAMA_MODEL_SMART", "llama3.1:8b"),
                    prompt,
                    use_persona,
                    use_memory,
                    extra_system=extra_system,
                    max_tokens=max_tokens,
                    stream_callback=stream_callback,
                )
            if api == "ollama_deep":
                return self._call_ollama(
                    getattr(Config, "OLLAMA_MODEL_DEEP", "deepseek-r1:8b"),
                    prompt,
                    use_persona,
                    use_memory,
                    extra_system=extra_system,
                    max_tokens=max_tokens,
                    stream_callback=stream_callback,
                )
            if api == "claude":
                return self._call_claude(prompt, use_persona, use_memory, extra_system=extra_system, max_tokens=max_tokens)
            if api == "gemini":
                return self._call_gemini(prompt, use_persona, use_memory, extra_system=extra_system, max_tokens=max_tokens)
            if api == "groq":
                return self._call_groq(prompt, use_persona, use_memory, extra_system=extra_system, max_tokens=max_tokens)
            if api == "perplexity":
                return self._call_perplexity(prompt)
        except Exception:
            if allow_failover and api == getattr(Config, "PRIMARY_BRAIN", ""):
                fallback = getattr(Config, "FALLBACK_BRAIN", "")
                if fallback and fallback != api:
                    return self._call_api(
                        fallback,
                        prompt,
                        use_persona=use_persona,
                        use_memory=use_memory,
                        allow_failover=False,
                        extra_system=extra_system,
                        max_tokens=max_tokens,
                        stream_callback=None,
                    )
        return None

    def _call_groq(
        self,
        prompt: str,
        use_persona: bool,
        use_memory: bool,
        extra_system: str = "",
        max_tokens: int | None = None,
    ) -> Optional[str]:
        headers = {
            "Authorization": f"Bearer {Config.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }

        messages = []
        if use_persona:
            messages.append({"role": "system", "content": self._persona_text(extra_system)})
        if use_memory:
            messages.extend(self._memory_context(getattr(Config, "MAX_MEMORY_TURNS", 8)))
        messages.append({"role": "user", "content": self._build_user_prompt(prompt)})

        payload = {
            "model": Config.GROQ_MODEL,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": max(32, int(max_tokens if max_tokens is not None else 150)),
        }

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=12,   # Fail fast if Groq is slow
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    def _call_gemini(
        self,
        prompt: str,
        use_persona: bool,
        use_memory: bool,
        extra_system: str = "",
        max_tokens: int | None = None,
    ) -> Optional[str]:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=Config.GEMINI_API_KEY)

        messages = []
        if use_memory:
            for item in self._memory_context(getattr(Config, "MAX_MEMORY_TURNS", 8)):
                role = "user" if item.get("role") == "user" else "model"
                messages.append({"role": role, "parts": [{"text": item.get("content", "")}]})
        messages.append({"role": "user", "parts": [{"text": prompt}]})

        response = client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=messages,
            config=types.GenerateContentConfig(
                system_instruction=self._persona_text(extra_system) if use_persona else None,
                max_output_tokens=max(64, int(max_tokens if max_tokens is not None else 500)),
                temperature=0.4,
            ),
        )
        return getattr(response, "text", None)

    def _call_claude(
        self,
        prompt: str,
        use_persona: bool,
        use_memory: bool,
        extra_system: str = "",
        max_tokens: int | None = None,
    ) -> Optional[str]:
        headers = {
            "x-api-key": Config.CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        system_text = self._persona_text(extra_system) if use_persona else ""
        memory_text = ""
        if use_memory:
            chunks = []
            for item in self._memory_context(getattr(Config, "MAX_MEMORY_TURNS", 8)):
                role = item.get("role", "user").upper()
                chunks.append(f"{role}: {item.get('content', '')}")
            memory_text = "\n".join(chunks)

        final_prompt = prompt if not memory_text else f"{memory_text}\n\nUser: {prompt}"

        payload = {
            "model": Config.CLAUDE_MODEL,
            "max_tokens": max(64, int(max_tokens if max_tokens is not None else 700)),
            "temperature": 0.4,
            "system": system_text,
            "messages": [{"role": "user", "content": final_prompt}],
        }

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"].strip()

    def _call_perplexity(self, prompt: str) -> Optional[str]:
        headers = {
            "Authorization": f"Bearer {Config.PERPLEXITY_API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": Config.PERPLEXITY_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }

        response = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    # ─────────────────────────────────────────────────────────────
    # FALLBACK
    # ─────────────────────────────────────────────────────────────

    def _fallback_response(self, query: str) -> str:
        lowered = (query or "").lower()

        if any(word in lowered for word in ["hello", "hi", "hey", "you there"]):
            return "Still here."

        return "Something upstream failed. Check the API keys, packages, and network, then try again."
