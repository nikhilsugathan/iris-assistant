"""Bridge detected user language into response-style and optional TTS routing.

User input owns the persistent language style. By default this state changes how
IRIS replies, not which persona voice speaks. Per-language TTS voices are an
explicit opt-in and must never override the configured Iris/Aletheia voice lock.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Optional


class _LanguageVoiceState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._style_key: Optional[str] = None
        self._voice_name: Optional[str] = None
        self._source: str = "default"
        self._revision: int = 0

    def set_detected(self, detected, source: str) -> bool:
        if not detected:
            return False
        key, _label, voice_name = detected
        if key == "malayalam" and not _env_bool("IRIS_MALAYALAM_NATIVE_TTS", False):
            voice_name = None
        with self._lock:
            changed = key != self._style_key or voice_name != self._voice_name
            self._style_key = key
            self._voice_name = voice_name
            self._source = source
            if changed:
                self._revision += 1
            return changed

    def clear(self, source: str = "english") -> bool:
        with self._lock:
            changed = self._style_key is not None or self._voice_name is not None
            self._style_key = None
            self._voice_name = None
            self._source = source
            if changed:
                self._revision += 1
            return changed

    def snapshot(self) -> tuple[Optional[str], Optional[str], str, int]:
        with self._lock:
            return self._style_key, self._voice_name, self._source, self._revision


_STATE = _LanguageVoiceState()

_ENGLISH_SWITCH_RE = re.compile(
    r"(?:^|\b)(?:english|switch\s+(?:back\s+)?to\s+english|"
    r"speak\s+(?:in\s+)?english|reply\s+(?:in\s+)?english|"
    r"respond\s+(?:in\s+)?english|continue\s+(?:in\s+)?english|"
    r"back\s+to\s+english)(?:\b|$)",
    re.IGNORECASE,
)


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _language_voice_switch_enabled() -> bool:
    if _env_bool("IRIS_LOCK_TTS_VOICE", True):
        return False
    if not _env_bool("IRIS_MULTILINGUAL_TTS", False):
        return False
    return _env_bool("IRIS_STICKY_LANGUAGE_TTS", False)


def _requests_english(text: str) -> bool:
    return bool(_ENGLISH_SWITCH_RE.search(text or ""))


def _delete_cached_files(cache: dict) -> None:
    for path in list(cache.values()):
        if not isinstance(path, str):
            continue
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
    cache.clear()


def _prepare_voice_instance(
    self,
    active_key: Optional[str],
    routed_voice: Optional[str],
    revision: int,
) -> None:
    previous_revision = getattr(self, "_iris_language_voice_revision", -1)
    self._iris_language_voice_revision = revision
    self._iris_forced_input_language_key = active_key
    self._iris_language_voice_key = active_key

    if routed_voice:
        # Text-only caches cannot distinguish voices. Flush them only when a real
        # persona-to-language voice route is active; locked persona mode can reuse
        # all normal Iris/Aletheia cache entries safely.
        with self._static_audio_cache_lock:
            _delete_cached_files(self._static_audio_cache)
        if previous_revision != revision:
            with self._tts_prefetch_lock:
                _delete_cached_files(self._tts_prefetch_cache)

        self._iris_forced_input_voice_name = routed_voice
        self._iris_language_voice_name = routed_voice
        self._iris_disable_tts_prefetch = True
        return

    # Locked persona voice: preserve normal cache/prefetch behavior. A language
    # revision is style metadata only and must not invalidate current-voice audio.
    self._iris_forced_input_voice_name = None
    self._iris_language_voice_name = None
    self._iris_disable_tts_prefetch = False


def get_active_language_voice() -> Optional[str]:
    return _STATE.snapshot()[1]


def get_active_language_style() -> Optional[str]:
    return _STATE.snapshot()[0]


def reset_active_language() -> None:
    _STATE.clear(source="reset")


def apply_language_voice_bridge(brain_module, voice_module, multilingual_module) -> None:
    brain_cls = getattr(brain_module, "Brain", None)
    voice_cls = getattr(voice_module, "Voice", None)

    if brain_cls is not None and not getattr(brain_cls, "_iris_language_voice_bridge_applied", False):
        original_generation_settings = brain_cls._generation_settings
        original_rewrite_generic_response = brain_cls._rewrite_generic_response

        def _capture_user_language(self, user_input: str, source: str) -> None:
            detected = multilingual_module.detect_language_style(user_input)
            if detected:
                _STATE.set_detected(detected, source=source)
                self._iris_active_language_key = detected[0]
            elif _requests_english(user_input):
                _STATE.clear(source="explicit_english")
                self._iris_active_language_key = None

        def _rewrite_generic_response_language_bridge(self, text: str):
            _capture_user_language(self, text, source="user_input_fast_path")
            return original_rewrite_generic_response(self, text)

        def _generation_settings_language_bridge(
            self,
            query_type: str,
            council_packet=None,
            voice_mode: bool = False,
            user_input: str = "",
        ):
            _capture_user_language(self, user_input, source="user_input_generation")
            return original_generation_settings(
                self,
                query_type,
                council_packet=council_packet,
                voice_mode=voice_mode,
                user_input=user_input,
            )

        brain_cls._rewrite_generic_response = _rewrite_generic_response_language_bridge
        brain_cls._generation_settings = _generation_settings_language_bridge
        brain_cls._iris_language_voice_bridge_applied = True

    if voice_cls is not None and not getattr(voice_cls, "_iris_language_voice_bridge_applied", False):
        original_init = voice_cls.__init__
        original_speak = voice_cls.speak
        original_start_prefetch = voice_cls.start_prefetch
        original_try_prefetch_next = voice_cls._try_prefetch_next
        original_run_edge = voice_cls._run_edge_tts_async
        original_tts_status = voice_cls.tts_status

        def _init_language_bridge(self, *args, **kwargs):
            _STATE.clear(source="voice_init")
            original_init(self, *args, **kwargs)
            self._iris_language_voice_revision = _STATE.snapshot()[3]
            self._iris_forced_input_language_key = None
            self._iris_forced_input_voice_name = None
            self._iris_disable_tts_prefetch = False

        def _speak_language_bridge(self, text, interrupt=True, on_play_start=None):
            active_key, candidate_voice, _source, revision = _STATE.snapshot()
            routed_voice = candidate_voice if _language_voice_switch_enabled() else None
            _prepare_voice_instance(self, active_key, routed_voice, revision)
            return original_speak(self, text, interrupt=interrupt, on_play_start=on_play_start)

        def _start_prefetch_language_bridge(self, text: str) -> None:
            if getattr(self, "_iris_disable_tts_prefetch", False):
                return
            return original_start_prefetch(self, text)

        def _try_prefetch_next_language_bridge(self, current_stop_event) -> None:
            if getattr(self, "_iris_disable_tts_prefetch", False):
                return
            return original_try_prefetch_next(self, current_stop_event)

        def _run_edge_tts_language_bridge(self, text, voice, rate, out_file, *args, **kwargs):
            active_key, candidate_voice, _source, revision = _STATE.snapshot()
            routed_voice = candidate_voice if _language_voice_switch_enabled() else None
            _prepare_voice_instance(self, active_key, routed_voice, revision)
            if routed_voice:
                voice = routed_voice
                rate = os.getenv("IRIS_MULTILINGUAL_TTS_RATE", "+0%")
                try:
                    self._debug_trace(
                        "tts_language_voice",
                        mode="input_authoritative_switch",
                        language=active_key or "",
                        voice=voice,
                        text=text,
                    )
                except Exception:
                    pass
            else:
                try:
                    self._debug_trace(
                        "tts_language_voice",
                        mode="persona_voice_locked",
                        language=active_key or "",
                        voice=voice,
                        text=text,
                    )
                except Exception:
                    pass
            return original_run_edge(self, text, voice, rate, out_file, *args, **kwargs)

        def _tts_status_language_bridge(self) -> str:
            base = original_tts_status(self)
            active_key, candidate_voice, source, _revision = _STATE.snapshot()
            language = active_key or "english/default"
            route = candidate_voice if _language_voice_switch_enabled() and candidate_voice else "current persona voice"
            return f"{base} / active_language={language} / tts_route={route} / source={source}"

        voice_cls.__init__ = _init_language_bridge
        voice_cls.speak = _speak_language_bridge
        voice_cls.start_prefetch = _start_prefetch_language_bridge
        voice_cls._try_prefetch_next = _try_prefetch_next_language_bridge
        voice_cls._run_edge_tts_async = _run_edge_tts_language_bridge
        voice_cls.tts_status = _tts_status_language_bridge
        voice_cls._iris_multilingual_input_owner_applied = True
        voice_cls._iris_language_voice_bridge_applied = True
