"""Performance patches for IRIS startup and response latency.

These patches are intentionally isolated from main.py. They keep local LLM support
available, but stop it from delaying startup or becoming a slow fallback unless
the user explicitly enables it.
"""

from __future__ import annotations

import os


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class _LazyLocalLLMPlaceholder:
    _iris_lazy_placeholder = True

    def __bool__(self) -> bool:
        return True


def apply_performance_patches(brain_module) -> None:
    brain_cls = getattr(brain_module, "Brain", None)
    if brain_cls is None or getattr(brain_cls, "_iris_performance_patch_applied", False):
        return

    trace_logger = getattr(brain_module, "trace_logger", None)
    original_init = brain_cls.__init__
    original_call_ollama = brain_cls._call_ollama
    original_get_apis_for_query = brain_cls._get_apis_for_query

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
        # Keep fast cloud providers before local/ollama routes.
        preferred = ["groq", "gemini", "claude", "perplexity", "llama_cpp", "ollama_smart", "ollama_fast"]
        ordered = [api for api in preferred if api in order]
        ordered.extend(api for api in order if api not in ordered)
        return ordered

    brain_cls.__init__ = _init_fast
    brain_cls._call_ollama = _call_ollama_fast
    brain_cls._get_apis_for_query = _get_apis_for_query_fast
    brain_cls._iris_performance_patch_applied = True
