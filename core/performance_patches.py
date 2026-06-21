"""Performance patches for IRIS startup and response latency.

These patches are intentionally isolated from main.py. They keep local LLM support
available, but stop it from delaying startup or becoming a slow fallback unless
the user explicitly enables it.
"""

from __future__ import annotations

import os
import re


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class _LazyLocalLLMPlaceholder:
    _iris_lazy_placeholder = True

    def __bool__(self) -> bool:
        return True


_FAST_REPLIES = {
    "hi": "Hey. What are we doing?",
    "hello": "Hey. What are we doing?",
    "hey": "Hey. What are we doing?",
    "yo": "I'm here. What's the move?",
    "good morning": "Morning. What's first?",
    "good evening": "Evening. What's the plan?",
    "good night": "Good night. I'll be here when you need me.",
    "thanks": "Anytime.",
    "thank you": "Anytime.",
    "ok": "Good.",
    "okay": "Good.",
    "yes": "Go on.",
    "no": "Alright. Correct me.",
}


def _normalized_short(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9'\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def apply_performance_patches(brain_module) -> None:
    brain_cls = getattr(brain_module, "Brain", None)
    if brain_cls is None or getattr(brain_cls, "_iris_performance_patch_applied", False):
        return

    trace_logger = getattr(brain_module, "trace_logger", None)
    original_init = brain_cls.__init__
    original_call_ollama = brain_cls._call_ollama
    original_get_apis_for_query = brain_cls._get_apis_for_query
    original_rewrite_generic_response = brain_cls._rewrite_generic_response
    original_generation_settings = brain_cls._generation_settings

    def _local_enabled() -> bool:
        return _env_bool("IRIS_ENABLE_LOCAL_LLM", False) or _env_bool("IRIS_PRELOAD_LOCAL_LLM", False)

    def _log(message: str, *args) -> None:
        try:
            if trace_logger is not None:
                trace_logger.info(message, *args)
        except Exception:
            pass

    def _init_fast(self, memory):
        original_init(self, memory)
        if _env_bool("IRIS_FAST_BOOT", True) and not _env_bool("IRIS_PRELOAD_LOCAL_LLM", False):
            if getattr(self, "llm", None) is None:
                self.llm = _LazyLocalLLMPlaceholder()
                self._iris_local_llm_placeholder = True
                _log("[PERF] fast_boot_placeholder_set local_llm_wait_skipped=true")
        if not _local_enabled():
            try:
                self.available_apis = [api for api in self.available_apis if api != "llama_cpp"]
                self._update_priority()
                _log("[PERF] local_llm_removed_from_default_routing available=%s", ",".join(self.available_apis))
            except Exception:
                pass

    def _call_ollama_fast(self, api_key, prompt, settings=None, admin_unlocked=False):
        if api_key == "llama_cpp" and getattr(getattr(self, "llm", None), "_iris_lazy_placeholder", False):
            self.llm = None
            self._iris_local_llm_placeholder = False
            _log("[PERF] local_llm_lazy_load_on_explicit_use=true")
            self._load_llm()
        return original_call_ollama(self, api_key, prompt, settings=settings, admin_unlocked=admin_unlocked)

    def _get_apis_for_query_fast(self, q_type: str):
        order = list(original_get_apis_for_query(self, q_type))
        if not _local_enabled():
            order = [api for api in order if api != "llama_cpp"]
        preferred = ["groq", "gemini", "claude", "perplexity", "llama_cpp", "ollama_smart", "ollama_fast"]
        ordered = [api for api in preferred if api in order]
        ordered.extend(api for api in order if api not in ordered)
        return ordered

    def _rewrite_generic_response_fast(self, text: str) -> str:
        normalized = _normalized_short(text)
        if normalized in _FAST_REPLIES:
            _log("[PERF] instant_reply text=%s", normalized)
            return _FAST_REPLIES[normalized]
        if normalized in {"are you there", "you there", "iris are you there"}:
            return "I'm here."
        return original_rewrite_generic_response(self, text)

    def _generation_settings_fast(self, query_type: str, council_packet=None, voice_mode: bool = False, user_input: str = ""):
        settings = original_generation_settings(
            self,
            query_type,
            council_packet=council_packet,
            voice_mode=voice_mode,
            user_input=user_input,
        )
        normalized = _normalized_short(user_input)
        short_general = query_type == "general" and len(normalized.split()) <= 10
        if short_general and not re.search(r"\b(explain|detail|detailed|step by step|compare|analyze|write|draft|plan)\b", normalized):
            settings["max_tokens"] = min(int(settings.get("max_tokens", 160)), 120)
            settings["context_turns"] = min(int(settings.get("context_turns", 3)), 2)
            settings["temperature"] = min(float(settings.get("temperature", 0.5)), 0.45)
            _log("[PERF] short_general_settings max_tokens=%s context_turns=%s", settings["max_tokens"], settings["context_turns"])
        if voice_mode:
            settings["max_tokens"] = min(int(settings.get("max_tokens", 150)), int(os.getenv("IRIS_VOICE_MAX_TOKENS", "110")))
            settings["context_turns"] = min(int(settings.get("context_turns", 3)), int(os.getenv("IRIS_VOICE_CONTEXT_TURNS", "2")))
        return settings

    brain_cls.__init__ = _init_fast
    brain_cls._call_ollama = _call_ollama_fast
    brain_cls._get_apis_for_query = _get_apis_for_query_fast
    brain_cls._rewrite_generic_response = _rewrite_generic_response_fast
    brain_cls._generation_settings = _generation_settings_fast
    brain_cls._iris_performance_patch_applied = True
