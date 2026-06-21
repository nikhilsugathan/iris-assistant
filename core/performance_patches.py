"""Performance patches for IRIS startup and response latency.

These patches are intentionally isolated from main.py. They keep local LLM support
available, but stop it from delaying startup or becoming a slow fallback unless
the user explicitly enables it.
"""

from __future__ import annotations

import os
import random
import re
from collections import deque


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class _LazyLocalLLMPlaceholder:
    _iris_lazy_placeholder = True

    def __bool__(self) -> bool:
        return True


_RECENT_FAST_REPLIES: deque[str] = deque(maxlen=12)

_STYLE_OPENERS = {
    "english": ["Hey", "Hello", "There you are", "Look who summoned me"],
    "spanish": ["Hola, mi amor", "Claro, mi amor", "Aquí estoy", "Dime"],
    "german": ["Hallo", "Guten Morgen", "Alles klar", "Ich bin da"],
    "french": ["Bonjour", "Salut", "Bien sûr", "Je suis là"],
    "italian": ["Ciao", "Buongiorno", "Eccomi", "Dimmi"],
    "indic": ["Namaste", "Namaskar", "Pranam", "Arre wah"],
    "malayalam": ["Namaskaram", "Sukham alle", "Parayu", "Njan ivide undu"],
}

_STYLE_TASK_LINES = {
    "english": [
        "what are we solving first?",
        "give me the mission.",
        "what needs my dangerously competent attention?",
        "tell me what we are fixing.",
    ],
    "spanish": [
        "¿qué resolvemos primero?",
        "dime qué necesitas y lo hacemos bien.",
        "¿cuál es la misión de hoy?",
        "te escucho; dame el objetivo.",
    ],
    "german": [
        "was lösen wir zuerst?",
        "sag mir das Ziel, dann legen wir los.",
        "was steht heute an?",
        "ich höre; gib mir die Aufgabe.",
    ],
    "french": [
        "qu'est-ce qu'on règle d'abord?",
        "donne-moi la mission, je m'en occupe.",
        "on commence par quoi?",
        "je t'écoute; quel est l'objectif?",
    ],
    "italian": [
        "cosa sistemiamo per prima cosa?",
        "dimmi la missione e partiamo.",
        "da dove cominciamo?",
        "ti ascolto; qual è l'obiettivo?",
    ],
    "indic": [
        "aaj kis cheez ko smart banana hai?",
        "batao, pehle kya solve karna hai?",
        "kaunsa mission shuru karein?",
        "bolo, aaj kisko brilliant banate hain?",
    ],
    "malayalam": [
        "inn entha plan?",
        "parayu, aadyam enthu solve cheyyanam?",
        "innu nammal entha set aakkunne?",
        "task parayu, njan ready aanu.",
    ],
}

_STYLE_THANKS = {
    "english": ["Anytime", "You're welcome", "Naturally", "Tiny miracle delivered"],
    "spanish": ["De nada, mi amor", "Con gusto", "Para eso estoy", "Naturalmente"],
    "german": ["Bitte", "Gern geschehen", "Natürlich", "Dafür bin ich da"],
    "french": ["Avec plaisir", "De rien", "Naturellement", "Je t'en prie"],
    "italian": ["Prego", "Con piacere", "Naturalmente", "Sono qui per questo"],
    "indic": ["Koi baat nahi", "Hamesha", "Bas, itna sa kaam", "Khushi se"],
    "malayalam": ["Parayanda", "Eppozhum", "Santhosham", "Ithokke simple alle"],
}

_STYLE_ACKS = {
    "english": ["Good. Continue.", "Got it. Next.", "Understood. Keep going."],
    "spanish": ["Vale. Sigue.", "Entendido. Continúa.", "Perfecto. Dime más."],
    "german": ["Alles klar. Weiter.", "Verstanden. Mach weiter.", "Gut. Nächster Schritt."],
    "french": ["Très bien. Continue.", "Compris. On continue.", "Parfait. Dis-moi la suite."],
    "italian": ["Va bene. Continua.", "Capito. Avanti.", "Perfetto. Dimmi il resto."],
    "indic": ["Theek hai. Aage bolo.", "Samajh gaya. Continue karo.", "Haan, bolo."],
    "malayalam": ["Sheri. Thudaru.", "Manassilayi. Parayu.", "Athu okay. Next?"],
}

_BOOT_ACTIONS = {
    "english": ["what are we bending into shape today?", "give me something worthy.", "let's make the machine behave."],
    "spanish": ["¿qué caos domesticamos hoy?", "dame una misión digna.", "vamos a poner orden."],
    "german": ["was bringen wir heute in Ordnung?", "gib mir eine würdige Aufgabe.", "wir machen das sauber."],
    "french": ["quel petit chaos on apprivoise?", "donne-moi une mission digne.", "on va faire ça proprement."],
    "indic": ["aaj kis chaos ko tame karna hai?", "mission do, drama main sambhaal lungi.", "chalo, kuch smart karte hain."],
    "malayalam": ["inn entha chaos set aakkam?", "mission parayu, njan nokkam.", "innu nammal smart aayi cheyyam."],
}

_MALAYALAM_NATIVE_OPENERS = ["നമസ്കാരം", "പറയൂ", "ഞാൻ ഇവിടെ ഉണ്ട്", "സുഖമാണോ"]
_MALAYALAM_NATIVE_TASK_LINES = [
    "ഇന്ന് എന്താണ് പ്ലാൻ?",
    "ആദ്യം എന്ത് ചെയ്യണം?",
    "എന്താണ് സഹായിക്കേണ്ടത്?",
    "പറയൂ, നമുക്ക് ശരിയാക്കാം.",
]
_MALAYALAM_NATIVE_THANKS = ["സന്തോഷം", "എപ്പോഴും", "അതു പ്രശ്നമില്ല"]
_MALAYALAM_NATIVE_ACKS = ["ശരി. തുടരൂ.", "മനസ്സിലായി. പറയൂ.", "ശരി. അടുത്തത്?"]
_MALAYALAM_NATIVE_BOOT = ["ഇന്ന് എന്താണ് പ്ലാൻ?", "എന്ത് കാര്യമാണ് ശരിയാക്കേണ്ടത്?", "പറയൂ, നമുക്ക് തുടങ്ങാം."]


def _malayalam_native_enabled() -> bool:
    return _env_bool("IRIS_MALAYALAM_NATIVE_TTS", True)


def _normalized_short(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9'\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _detect_style(normalized: str) -> str:
    words = set(normalized.split())
    if words & {"hola", "amor", "gracias", "buenos", "buenas", "dime", "si", "vale"} or "mi amor" in normalized:
        return "spanish"
    if words & {"hallo", "guten", "morgen", "abend", "danke", "bitte", "ja", "nein", "weiter"}:
        return "german"
    if words & {"bonjour", "salut", "merci", "oui", "non", "bonsoir"}:
        return "french"
    if words & {"ciao", "buongiorno", "grazie", "prego"}:
        return "italian"
    if words & {"namaste", "namaskar", "pranam", "salaam", "shukriya", "dhanyavad"}:
        return "indic"
    if words & {"namaskaram", "sukham", "alle", "parayu", "nanni", "entha", "innu"}:
        return "malayalam"
    return "english"


def _intent_for(normalized: str) -> str:
    if normalized in {"thanks", "thank you", "gracias", "merci", "danke", "grazie", "nanni", "shukriya", "dhanyavad"}:
        return "thanks"
    if normalized in {"ok", "okay", "yes", "no", "ja", "nein", "si", "vale", "oui", "non"}:
        return "ack"
    if normalized in {"are you there", "you there", "iris are you there"}:
        return "presence"
    return "greeting"


def _compose(style: str, intent: str) -> str:
    if style == "malayalam" and _malayalam_native_enabled():
        if intent == "thanks":
            return _avoid_recent(random.choice(_MALAYALAM_NATIVE_THANKS))
        if intent == "ack":
            return _avoid_recent(random.choice(_MALAYALAM_NATIVE_ACKS))
        opener = random.choice(_MALAYALAM_NATIVE_OPENERS)
        line = random.choice(_MALAYALAM_NATIVE_TASK_LINES)
        return _avoid_recent(f"{opener}. {line}")
    if intent == "thanks":
        return _avoid_recent(random.choice(_STYLE_THANKS.get(style, _STYLE_THANKS["english"])))
    if intent == "ack":
        return _avoid_recent(random.choice(_STYLE_ACKS.get(style, _STYLE_ACKS["english"])))
    if intent == "presence":
        opener = random.choice(_STYLE_OPENERS.get(style, _STYLE_OPENERS["english"]))
        line = random.choice(_STYLE_TASK_LINES.get(style, _STYLE_TASK_LINES["english"]))
        return _avoid_recent(f"{opener}. {line}")
    opener = random.choice(_STYLE_OPENERS.get(style, _STYLE_OPENERS["english"]))
    line = random.choice(_STYLE_TASK_LINES.get(style, _STYLE_TASK_LINES["english"]))
    return _avoid_recent(f"{opener}. {line}")


def _compose_boot(admin_unlocked: bool = False) -> str:
    if admin_unlocked:
        options = [
            "Aletheia online. State the objective.",
            "Root session active. Define the target.",
            "Admin layer awake. Proceed.",
            "Sovereign mode active. Speak clearly.",
        ]
        return _avoid_recent(random.choice(options))
    style = random.choice(["english", "spanish", "german", "french", "indic", "malayalam"])
    if style == "malayalam" and _malayalam_native_enabled():
        opener = random.choice(_MALAYALAM_NATIVE_OPENERS)
        action = random.choice(_MALAYALAM_NATIVE_BOOT)
        return _avoid_recent(f"{opener}. {action}")
    opener = random.choice(_STYLE_OPENERS[style])
    action = random.choice(_BOOT_ACTIONS.get(style, _BOOT_ACTIONS["english"]))
    return _avoid_recent(f"{opener}. {action}")


def _avoid_recent(candidate: str) -> str:
    for _ in range(8):
        if candidate not in _RECENT_FAST_REPLIES:
            _RECENT_FAST_REPLIES.append(candidate)
            return candidate
        candidate = candidate.rstrip(".!?") + random.choice([". Naturally.", ". Obviously.", ". Let's move."])
    _RECENT_FAST_REPLIES.append(candidate)
    return candidate


def _is_fast_smalltalk(normalized: str) -> bool:
    if not normalized or len(normalized.split()) > 4:
        return False
    known = {
        "hi", "hello", "hey", "yo", "good morning", "good evening", "good night",
        "thanks", "thank you", "ok", "okay", "yes", "no", "are you there", "you there",
        "namaste", "namaskar", "pranam", "namaskaram", "hola", "mi amor", "buenos dias",
        "buenas noches", "bonjour", "salut", "hallo", "guten morgen", "guten abend",
        "ciao", "buongiorno", "gracias", "danke", "merci", "grazie", "nanni",
    }
    if normalized in known:
        return True
    style = _detect_style(normalized)
    return style != "english" and len(normalized.split()) <= 3


def _is_boot_prompt(prompt: str) -> bool:
    p = (prompt or "").lower()
    return "boot-up line" in p or "boot up line" in p or "boot line" in p


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
    original_call_groq_simple = brain_cls._call_groq_simple

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

    def _call_groq_simple_fast(self, prompt: str, admin_unlocked: bool = False) -> str:
        if _env_bool("IRIS_FAST_BOOT_GREETINGS", True) and _is_boot_prompt(prompt):
            reply = _compose_boot(admin_unlocked=admin_unlocked)
            _log("[PERF] instant_boot_greeting admin=%s reply=%s", admin_unlocked, reply)
            return reply
        return original_call_groq_simple(self, prompt, admin_unlocked=admin_unlocked)

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
        if _is_fast_smalltalk(normalized):
            style = _detect_style(normalized)
            intent = _intent_for(normalized)
            reply = _compose(style, intent)
            _log("[PERF] instant_smalltalk text=%s style=%s intent=%s reply=%s", normalized, style, intent, reply)
            return reply
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
    brain_cls._call_groq_simple = _call_groq_simple_fast
    brain_cls._get_apis_for_query = _get_apis_for_query_fast
    brain_cls._rewrite_generic_response = _rewrite_generic_response_fast
    brain_cls._generation_settings = _generation_settings_fast
    brain_cls._iris_performance_patch_applied = True
