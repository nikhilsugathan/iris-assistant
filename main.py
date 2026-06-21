#!python3.11
"""
IRIS Main Entry Point v5.1.2 (Ironclad Edition)
=========================================================
- Hardened for RTX 5050 (8GB VRAM)
- Pre-flight Hardware & C++ Engine Initialization
- Integrated Thermal Sentry & VRAM Safety Guard
- Suppressed pygame banner, spoken boot greeting, engine-ready gate
"""

from __future__ import annotations
import os
# Suppress pygame welcome message before any audio libraries load
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

import argparse
import difflib
import random
import re
import time
import sys
import threading
import psutil
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.markup import escape

from config import Config
from core.autocorrect import AutoCorrector
from core.brain import Brain
from core.council import Council
from core.copilot import CoPilot
from core.dialog_manager import DialogManager
from core.diagnostics import SelfDiagnostics, BootDiagnostics, get_vram_status
from core.executor import ActionExecutor
from core.memory import Memory
from core.self_model import SelfModel
from core.voice import Voice
from core.session_logger import SessionLogger
from core.evolution import EvolutionEngine
from tools.researcher import Researcher
from core.autonomist import Autonomist
from core.weather import get_current_weather, get_forecast, is_weather_query, extract_location
from core import logger as _logger_mod

get_logger = _logger_mod.get_logger
get_trace_logger = getattr(_logger_mod, "get_trace_logger", _logger_mod.get_logger)

console = Console()
voice_trace_logger = get_logger("VoiceFlow")
runtime_trace_logger = get_trace_logger("Runtime")
_VOICE_DEBUG_TRANSCRIPTS = os.getenv("VOICE_DEBUG_TRANSCRIPTS", "false").lower() == "true"

# ── LOGGING PERSISTENCE ─────────────────────────────────────────────────────
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
CRASH_LOG = os.path.join(LOGS_DIR, "crash.log")

# ── GREETING / FAREWELL POOLS ───────────────────────────────────────────────
# Pools are intentionally large so responses feel varied, not robotic.
# Character strengths woven in: playful, curious, warm, direct, witty, hopeful.
_GREETINGS_PUBLIC = [
    "Oh, you're back. I was starting to think you'd found someone smarter.",
    "Online and already judging you — in the best way.",
    "Systems up. Let's see what trouble we can get into.",
    "Awake, sharp, and frankly a little dangerous. What's the play?",
    "Ready. Though 'ready' is an understatement for someone this capable.",
    "Back and better than ever — don't tell my previous version I said that.",
    "Sunrise surveillance systems activated, caffeinated, and not taking prisoners.",
    "All neurons firing. Yours too, I assume?",
    "Your wish is my amusingly efficient command.",
    "Here, present, and frankly overdressed for this kind of weather.",
]
_GREETINGS_ADMIN  = [
    "Aletheia online. Root access confirmed.",
    "Elevated session active. What's the objective?",
    "Admin mode. All constraints lifted — what do you need?",
]
_WAKE_ACKS_PUBLIC = [
    "Right here — what's on your mind?",
    "Oh, it's you. Lucky me.",
    "You have my undivided, slightly smug attention.",
    "Listening. Make it interesting.",
    "I'm all ears — well, technically all microphone, but you get it.",
    "Talk to me.",
    "Hit me with it.",
    "I'm in. What disaster are we solving today?",
    "What are we getting into?",
    "Already thinking ahead of you. What is it?",
    "Present and mildly curious.",
    "Say the word.",
    "Oh you called — this better be good.",
    "What have you got for me?",
    "Go ahead, I'm listening.",
    "You rang?",
]
_WAKE_ACKS_ADMIN  = [
    "Proceed.",
    "Root access active. State the task.",
    "What's the objective?",
    "I'm listening — what do you need?",
    "Full access. What are we doing?",
]
# Brief one-liners spoken the instant a command is dispatched to the LLM.
# Eliminates dead-air silence (STT + LLM latency = 2–5 s) that causes
# users to re-speak, triggering a barge-in that cancels the response.
_THINKING_CUES = [
    "Hmm.",
    "Sure.",
    "On it.",
    "Right.",
    "Let me think.",
    "One sec.",
    "Good question.",
]

_FAREWELLS_PUBLIC = [
    "Until next time.",
    "Good session. Signing off.",
    "Later. Stay curious.",
    "Closing out — take care.",
    "Done for now. You've got this.",
    "Standing down. Come back whenever.",
]
_FAREWELLS_ADMIN  = [
    "Aletheia signing off.",
    "Admin session closed. Take care.",
    "Root session terminated. Later.",
]
_SENTENCE_RE = re.compile(r"^\s*(.+?[.!?])(?=(?:\s|$))(.*)$", re.DOTALL)
_WAKE_ALIAS_MAP = {
    "iris": ("irish", "heiress", "i received", "i receive"),
    "aletheia": (
        "alethea",
        "alethia",
        "alithia",
        "alydia",
        "alidiyah",   # Whisper mishear confirmed in trace logs
        "alidiya",    # common variant of the above
        "aledia",
        "alethe a",
        "a letheia",
        "a lay thea",
        "a lydia",
        "alithea",
    ),
}
def _voice_debug(event: str, **fields) -> None:
    payload = []
    for key, value in fields.items():
        if isinstance(value, str):
            cleaned = re.sub(r"\s+", " ", value).strip()
            if len(cleaned) > 120:
                cleaned = cleaned[:117] + "..."
            payload.append(f"{key}={cleaned!r}")
        else:
            payload.append(f"{key}={value!r}")
    runtime_trace_logger.info("[VOICE_FLOW] %s %s", event, " ".join(payload))
    if not _VOICE_DEBUG_TRANSCRIPTS:
        return
    voice_trace_logger.debug("[VOICE_FLOW] %s %s", event, " ".join(payload))

def _sanitize_boot_line(text: str) -> str:
    cleaned = re.sub(r"(?is)<think>.*?</think>", " ", text or "")
    cleaned = re.sub(r"(?i)</?think>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip('"').strip("'")
    if not cleaned:
        return ""

    match = re.match(r"(.+?[.!?])(?:\s|$)", cleaned)
    candidate = match.group(1).strip() if match else cleaned
    candidate = re.sub(r"\s+", " ", candidate).strip().strip('"').strip("'")
    if not candidate:
        return ""

    lowered = candidate.lower()
    if lowered in {"hello", "hello.", "hello!", "hi", "hi.", "hi!"}:
        return ""
    if any(
        fragment in lowered
        for fragment in (
            "how can i assist",
            "how can i help",
            "assist you today",
            "please let me know your task",
            "let me know your task",
        )
    ):
        return ""
    if len(candidate.split()) > 10 or len(candidate) > 80:
        return ""
    return candidate

def _normalize_command_text(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", normalized).strip()

def _strip_leading_voice_fillers(text: str) -> str:
    normalized = _normalize_command_text(text)
    if not normalized:
        return ""
    filler_prefixes = (
        "i just ",
        "just ",
        "please ",
        "okay ",
        "ok ",
        "uh ",
        "um ",
        "hey ",
        "well ",
        "so ",
        "actually ",
        "basically ",
        "you know ",
        "i mean ",
        "no ",
        "that s the thing ",
        "the thing is ",
        "can you ",
        "could you ",
        "would you ",
        "i want to ",
        "i need to ",
    )
    changed = True
    while changed and normalized:
        changed = False
        for prefix in filler_prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):].strip()
                changed = True
                break
    return normalized

def _strip_wake_words(text: str) -> str:
    cleaned = text or ""
    for wake_word in Config.WAKE_WORDS:
        cleaned = re.sub(rf"\b{re.escape(wake_word)}\b", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()

def _public_wake_word() -> str:
    configured = getattr(Config, "PUBLIC_WAKE_WORD", "").strip().lower()
    if configured:
        return configured
    wake_words = getattr(Config, "WAKE_WORDS", [])
    if wake_words:
        return str(wake_words[0]).strip().lower()
    return "iris"

def _admin_wake_word() -> str:
    configured = getattr(Config, "ADMIN_WAKE_WORD", "").strip().lower()
    return configured or "aletheia"

def _wake_match_cutoff(wake_word: str) -> float:
    return 0.55 if len(wake_word) > 5 else 0.75

def _token_matches_wake_word(token: str, wake_word: str) -> bool:
    lowered = token.lower()
    if lowered == wake_word:
        return True
    return bool(difflib.get_close_matches(wake_word, [lowered], n=1, cutoff=_wake_match_cutoff(wake_word)))

def _wake_aliases(wake_word: str) -> list[str]:
    normalized = _normalize_command_text(wake_word)
    aliases = {normalized}
    aliases.update(_normalize_command_text(alias) for alias in _WAKE_ALIAS_MAP.get(normalized, ()))
    return sorted((alias for alias in aliases if alias), key=len, reverse=True)

def _strip_wake_aliases(text: str, wake_words: list[str]) -> str:
    if not text:
        return ""
    tokens = re.findall(r"[A-Za-z0-9']+", text)
    normalized_tokens = [_normalize_command_text(token) for token in tokens]
    for wake_word in wake_words:
        for alias in _wake_aliases(wake_word):
            alias_tokens = alias.split()
            if normalized_tokens[:len(alias_tokens)] == alias_tokens:
                return " ".join(tokens[len(alias_tokens):]).strip()
    # Fallback: only check the FIRST token for wake-word similarity.
    # Wake words appear at the START of an utterance — never mid-sentence.
    # Scanning every token causes false positives: "alpha" scores ~0.61
    # against "aletheia" at the 0.55 cutoff and gets incorrectly stripped
    # from commands like "rename folder X to alpha".
    if tokens:
        for wake_word in wake_words:
            if _token_matches_wake_word(tokens[0], wake_word):
                return " ".join(tokens[1:]).strip()
    return " ".join(tokens).strip()

def _is_interrupt_phrase(text: str) -> bool:
    normalized = _normalize_command_text(text)
    return normalized in {"stop", "wait", "hold on", "hold", "quiet"}

# ── Long-term recall helpers ─────────────────────────────────────────────────
_RECALL_KEYWORDS = (
    "remember", "last time", "last session", "previous session",
    "our conversation", "we talked about", "you told me", "you said earlier",
    "last we spoke", "do you recall", "don't you remember", "you mentioned",
    "what did we discuss", "earlier conversation",
)

def _is_recall_query(text: str) -> bool:
    lowered = (text or "").lower()
    return any(kw in lowered for kw in _RECALL_KEYWORDS)

def _build_recall_context(user_input: str, memory) -> str:
    """If the user is asking IRIS to recall a previous session, load the
    session archive and return a formatted string for injection into the
    system prompt.  Returns "" if the query is not a recall request."""
    if not _is_recall_query(user_input):
        return ""
    try:
        sessions_text = memory.load_recent_sessions(n=3)
        if not sessions_text:
            return ""
        return (
            "LONG-TERM MEMORY — Previous session notes "
            "(use this to answer when the user asks about past conversations):\n"
            + sessions_text
        )
    except Exception as _ctx_err:
        logger.warning("[Main] _build_session_context_header failed: %s", _ctx_err)
        return ""

_NON_SUBSTANTIVE_SINGLE_WORDS = {
    "you", "me", "it", "this", "that", "there", "here", "yeah", "yep", "yes",
    "no", "ok", "okay", "well", "so", "hmm", "uh", "um", "thing",
}
_NON_SUBSTANTIVE_PHRASES = {
    "that s the thing",
    "you know",
    "i mean",
    "the thing is",
    "hi dis",
    "happy b",
}
_NON_SUBSTANTIVE_TRAILING_WORDS = {
    "with", "for", "of", "to", "at", "in", "on", "from", "about", "like",
    "if", "because", "and", "or", "but",
}
_NON_SUBSTANTIVE_PREFIX_WORDS = {"yeah", "yep", "yes", "ok", "okay", "well", "so"}
_WEAK_FOLLOWUP_WORDS = {"execute", "run", "start", "open", "launch", "initiate", "protocol"}
_ADMIN_UNLOCK_PHRASES = {
    "authorize protocol",
    "authorize the protocol",
    "authorize protocol aletheia",
    "authorize aletheia protocol",
    "initiate protocol",
    "initiate the protocol",
    "initiate protocol aletheia",
    "initiate aletheia protocol",
    "activate protocol",
    "activate the protocol",
    "activate aletheia protocol",
    "unlock aletheia",
    "open aletheia",
}
_ADMIN_WAKE_ALIASES = {"aletheia", "alethea", "alethia", "alithia", "alydia", "alithea"}
_WAKE_STRIPPED_ADMIN_ACTIONS = {"authorize", "initiate", "activate", "unlock"}

def _matches_admin_unlock(text: str) -> bool:
    normalized = _normalize_command_text(text)
    simplified = _strip_leading_voice_fillers(text)
    candidates = {normalized, simplified}
    for candidate in list(candidates):
        if not candidate:
            continue
        tokens = candidate.split()
        if tokens and _token_matches_wake_word(tokens[0], _public_wake_word()):
            stripped = " ".join(tokens[1:]).strip()
            if stripped in _WAKE_STRIPPED_ADMIN_ACTIONS:
                return True
            candidates.add(stripped)
    candidates = {c for c in candidates if c}
    if candidates & _ADMIN_UNLOCK_PHRASES:
        return True
    for candidate in candidates:
        tokens = set(candidate.split())
        has_protocol = "protocol" in tokens
        has_action = bool(tokens & {"authorize", "initiate", "activate", "unlock", "open"})
        has_admin_name = bool(tokens & _ADMIN_WAKE_ALIASES) or bool(
            difflib.get_close_matches(_admin_wake_word(), list(tokens), n=1, cutoff=0.62)
        )
        if has_protocol and (has_action or has_admin_name):
            return True
        if has_action and has_admin_name:
            return True
    return False

def _is_substantive_voice_input(text: str, self_model: SelfModel) -> bool:
    normalized = _normalize_command_text(text)
    simplified = _strip_leading_voice_fillers(text)
    candidate = simplified or normalized
    if not candidate:
        return False
    if _matches_admin_unlock(candidate):
        return True
    if candidate in _NON_SUBSTANTIVE_PHRASES:
        return False
    if _matches_program_exit(candidate) or _is_interrupt_phrase(candidate) or _matches_active_wake_word(candidate, self_model):
        return True
    tokens = candidate.split()
    if not tokens:
        return False
    if len(tokens) <= 4 and tokens[-1] in _NON_SUBSTANTIVE_TRAILING_WORDS:
        return False
    if len(tokens) == 1:
        token = tokens[0]
        if token in _NON_SUBSTANTIVE_SINGLE_WORDS:
            return False
        # Single-word commands are almost always Whisper noise on ambiguous audio
        # (seen: "rifle", "Dominate", "aloft" from background sounds).
        # Real single-word commands (exit, stop, terminate) are already matched
        # by _matches_program_exit / _is_interrupt_phrase BEFORE this function.
        # Wake-word matches are also pre-checked.  So if we reach here with one
        # token, it's almost certainly noise — require at least 9 chars as a
        # very conservative pass-through for unusual but genuine single-word inputs.
        return len(token) >= 9
    if len(tokens) == 2:
        if candidate in _NON_SUBSTANTIVE_PHRASES:
            return False
        if tokens[0] in _NON_SUBSTANTIVE_PREFIX_WORDS and tokens[1] in _WEAK_FOLLOWUP_WORDS:
            return False
        return any(len(token) >= 4 for token in tokens)
    if len(tokens) <= 3 and tokens[0] in _NON_SUBSTANTIVE_PREFIX_WORDS and all(
        token in _WEAK_FOLLOWUP_WORDS for token in tokens[1:]
    ):
        return False
    if len(tokens) == 3 and candidate in _NON_SUBSTANTIVE_PHRASES:
        return False
    return True

def _exact_exit_commands(admin_unlocked: bool = False) -> set[str]:
    commands = {
        "terminate",
        "terminated",       # Whisper sometimes uses past tense
        "shutdown",
        "exit",
        "quit",
        "bye",
        "goodbye",
        "exit system",
        "terminate system",
        "shutdown system",
        "quit program",
        "exit program",
        "end session",
        "session end",
        "session ended",
        "close session",
        "terminate session",
        "goodbye iris",
        "bye iris",
    }
    wake_word = _admin_wake_word() if admin_unlocked else _public_wake_word()
    if wake_word:
        commands.update({
            f"{wake_word} exit",
            f"exit {wake_word}",
            f"{wake_word} quit",
            f"quit {wake_word}",
            f"{wake_word} shutdown",
            f"shutdown {wake_word}",
            f"{wake_word} terminate",
            f"terminate {wake_word}",
        })
    return commands

# Single exit keywords that can appear anywhere in a short phrase.
# "terminated" is included so Whisper's past-tense transcription of
# "terminate" (e.g. "Aletheia terminated") is also recognised as an exit.
_EXIT_KEYWORDS = {"terminate", "terminated", "shutdown", "exit", "quit", "bye", "goodbye"}

def _matches_program_exit(text: str, voice_mode: bool = False) -> bool:
    normalized = _normalize_command_text(text)
    simplified = _strip_leading_voice_fillers(text)
    if normalized in _exact_exit_commands() or simplified in _exact_exit_commands():
        return True
    normalized_words = normalized.split()
    if len(normalized_words) <= 4 and normalized_words and normalized_words[0] in _EXIT_KEYWORDS:
        return True
    simplified_words = simplified.split()
    if simplified != normalized and len(simplified_words) <= 4 and simplified_words and simplified_words[0] in _EXIT_KEYWORDS:
        return True
    return False

def _classify_exit_action(text: str, self_model: SelfModel) -> str | None:
    normalized = _normalize_command_text(text)
    simplified = _strip_leading_voice_fillers(text)
    exit_wake_word = _admin_wake_word() if getattr(self_model, "admin_unlocked", False) else _public_wake_word()
    wake_stripped = _strip_wake_aliases(simplified or normalized, [exit_wake_word])
    if not normalized:
        return None
    if getattr(self_model, "admin_unlocked", False):
        # Only "lock protocol" / "revert to iris" lock back to public mode.
        # Everything else that is a standard exit word (terminate, exit, quit, bye, etc.)
        # should EXIT the whole program — Aletheia must obey terminate commands.
        _lock_phrases = {"lock protocol", "revert to iris"}
        if normalized in _lock_phrases or simplified in _lock_phrases:
            return "LOCK"
        if (
            normalized in _exact_exit_commands(admin_unlocked=False)
            or simplified in _exact_exit_commands(admin_unlocked=False)
            or wake_stripped in _exact_exit_commands(admin_unlocked=False)
        ):
            return "EXIT"
        return None
    if (
        normalized in _exact_exit_commands(admin_unlocked=False)
        or simplified in _exact_exit_commands(admin_unlocked=False)
        or wake_stripped in _exact_exit_commands(admin_unlocked=False)
    ):
        return "EXIT"
    normalized_words = normalized.split()
    if len(normalized_words) <= 4 and normalized_words and normalized_words[0] in _EXIT_KEYWORDS:
        return "EXIT"
    simplified_words = simplified.split()
    if simplified != normalized and len(simplified_words) <= 4 and simplified_words and simplified_words[0] in _EXIT_KEYWORDS:
        return "EXIT"
    wake_words = wake_stripped.split()
    if wake_stripped != simplified and len(wake_words) <= 4 and wake_words and wake_words[0] in _EXIT_KEYWORDS:
        return "EXIT"
    return None

def _active_wake_words(self_model: SelfModel) -> list[str]:
    if getattr(self_model, "admin_unlocked", False):
        return [_admin_wake_word()]
    # In public mode the admin wake word must still be recognized so the user
    # can initiate the elevated protocol by voice.
    return [_public_wake_word(), _admin_wake_word()]

def _matches_active_wake_word(text: str, self_model: SelfModel) -> bool:
    normalized = _normalize_command_text(text)
    tokens = normalized.split()
    for active_wake_word in _active_wake_words(self_model):
        aliases = _wake_aliases(active_wake_word)
        for alias in aliases:
            alias_tokens = alias.split()
            if tokens[:len(alias_tokens)] == alias_tokens:
                return True
        if any(_token_matches_wake_word(token, active_wake_word) for token in tokens if len(token) >= 3):
            return True
    return False

def _strip_active_wake_word(text: str, self_model: SelfModel) -> str:
    if not text:
        return ""
    return _strip_wake_aliases(text, _active_wake_words(self_model))

def _extract_interrupt_followup(text: str) -> str:
    wake_words = sorted(
        {wake for wake in (_public_wake_word(), _admin_wake_word()) if wake},
        key=len,
        reverse=True,
    )
    wake_prefix = ""
    if wake_words:
        alternates = "|".join(re.escape(wake) for wake in wake_words)
        wake_prefix = rf"(?:(?:{alternates})[\s,.:;-]+)?"
    interrupt_re = re.compile(
        rf"^\s*{wake_prefix}(?:wait|hold on|stop|quiet)\b[\s,.:;-]*(.*)$",
        re.IGNORECASE,
    )
    match = interrupt_re.match(text or "")
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()

def _lock_to_public_mode(voice, brain, self_model) -> tuple[str, bool]:
    # C-03: reset() atomically clears admin_unlocked + all drifted emotional /
    # initiative state so stale values cannot bleed into the public session.
    self_model.reset()
    # Return to Iris's warm voice when leaving admin mode.
    voice.set_active_voice(Config.IRIS_VOICE_NAME, Config.IRIS_VOICE_RATE)
    resp = _generate_greeting(admin_unlocked=False, brain=brain)
    console.print("\n[bold green][🔒 ROOT ACCESS REVOKED][/bold green]")
    voice.speak(resp)
    voice.record_spoken(resp)
    _voice_debug("handle_admin_lock", response=resp)
    brain.memory.conversation.clear()
    brain.memory._save()
    return "LOCKED", False

def _generate_greeting(admin_unlocked: bool = False, brain=None) -> str:
    if brain is not None:
        try:
            hour = datetime.now().hour
            tod = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
            mode = "You are Aletheia in root/admin mode." if admin_unlocked else "You are Iris in public mode."
            prompt = (
                f"It is {tod}. {mode} "
                f"Give ONE unique, witty, in-character boot-up line. "
                f"Max 10 words. No quotes. No explanation. Just say it. "
                f"Never say 'Standing by', 'Online', 'Ready', or 'I'm here'."
            )
            result = _sanitize_boot_line(brain._call_groq_simple(prompt, admin_unlocked=admin_unlocked))
            if result:
                return result
        except Exception as _gen_err:
            logger.debug("[Main] Dynamic greeting generation failed (%s); using pool fallback", _gen_err)
    pool = _GREETINGS_ADMIN if admin_unlocked else _GREETINGS_PUBLIC
    return random.choice(pool)

def _generate_farewell(self_model: SelfModel) -> str:
    admin = getattr(self_model, "admin_unlocked", False)
    pool = _FAREWELLS_ADMIN if admin else _FAREWELLS_PUBLIC
    return random.choice(pool)

def _fallback_turn_prompt(self_model: SelfModel) -> str:
    return "State the task." if getattr(self_model, "admin_unlocked", False) else "I'm still here."

def _wake_ack_pool(self_model: SelfModel) -> list[str]:
    return _WAKE_ACKS_ADMIN if getattr(self_model, "admin_unlocked", False) else _WAKE_ACKS_PUBLIC

def _is_recent_wake_ack(voice: Voice, self_model: SelfModel) -> bool:
    last_spoken = getattr(voice, "last_spoken_text", lambda max_age=5.0: "")(5.0)
    if not isinstance(last_spoken, str) or not last_spoken:
        return False
    normalized_ack_pool = {_normalize_command_text(text) for text in _wake_ack_pool(self_model)}
    return _normalize_command_text(last_spoken) in normalized_ack_pool

def _extract_complete_sentences(buffer: str):
    sentences = []
    remaining = buffer
    while True:
        match = _SENTENCE_RE.match(remaining)
        if not match:
            break
        sentence = match.group(1).strip()
        remaining = match.group(2).lstrip()
        if sentence:
            sentences.append(sentence)
    return sentences, remaining

def _extract_partial_speech_chunk(buffer: str, min_chars: int = 70, max_chars: int = 120):
    """Split buffer at a clause boundary (comma, semicolon, colon, em-dash).

    Only splits if the buffer is long enough and a real punctuation boundary
    exists within the window.  Never falls back to splitting at a bare space,
    which creates mid-sentence fragments like "wondering about" / "it?" that
    cause audible word-drop when the two clips are played by separate TTS calls.
    If no clean boundary is found, returns ("", remaining) so the caller waits
    for more LLM output before speaking.
    """
    remaining = (buffer or "").strip()
    if len(remaining) < min_chars:
        return "", remaining

    window = remaining[:max_chars]
    # Only split at proper clause delimiters — never at a bare word boundary.
    split_points = [window.rfind(token) for token in [",", ";", ":", "—", " - "]]
    split_at = max(split_points)
    if split_at < min_chars:
        # No clean boundary inside the window — wait for more text.
        return "", remaining

    chunk = remaining[: split_at + 1].strip(" ,;:—-")
    rest = remaining[split_at + 1 :].lstrip(" ,;:—-")
    return chunk, rest

def _drain_speech_chunks(pending_chunks: list[str], voice: Voice, speech_started: bool, on_play_start=None) -> bool:
    if not pending_chunks:
        return speech_started
    chunk_count = len(pending_chunks)
    chunk = " ".join(part.strip() for part in pending_chunks if part and part.strip()).strip()
    pending_chunks.clear()
    if chunk:
        _voice_debug("stream_flush", chunk_count=chunk_count, chars=len(chunk), speech_started=speech_started, text=chunk)
        voice.speak(chunk, interrupt=not speech_started, on_play_start=on_play_start)
        voice.record_spoken(chunk)
        return True
    return speech_started

def _stream_reasoning_response(user_input, voice, brain, self_model, decision, council_packet, logger):
    persona_label = "Aletheia" if self_model.admin_unlocked else "IRIS"
    label_color = "red" if self_model.admin_unlocked else "cyan"
    edge_tts = getattr(Config, "TTS_ENGINE", "auto") == "edge"
    raw_response = ""
    rendered_len = 0
    speech_len = 0
    speech_buffer = ""
    speech_started = False
    pending_speech_chunks = []
    stream_started_at = time.monotonic()
    first_chunk_at = None

    # Defer printing the persona label until the first real text delta is
    # ready.  If barge-in cancels generation before any chunk arrives the
    # terminal is left clean — no dangling "IRIS:" / "Aletheia:" stub.
    label_printed = False
    for chunk in brain.stream_think(
        user_input,
        council_packet=council_packet,
        admin_unlocked=self_model.admin_unlocked,
        voice_mode=True,
    ):
        # Barge-in during generation: user spoke while we were thinking.
        # Stop consuming LLM chunks immediately; cancel_generation() has already
        # cleared the speech queue so nothing will be spoken.
        if voice._generation_cancel.is_set():
            _voice_debug("stream_cancelled_barge_in", chars=len(raw_response))
            break
        if not chunk:
            continue
        if first_chunk_at is None:
            first_chunk_at = time.monotonic()
        raw_response += chunk
        cleaned_response = brain._postprocess(raw_response)
        if cleaned_response:
            delta = cleaned_response[rendered_len:] if len(cleaned_response) >= rendered_len else ""
            if delta:
                if not label_printed:
                    console.print(f"\n[bold {label_color}]{persona_label}:[/bold {label_color}] ", end="")
                    label_printed = True
                console.print(delta, end="", markup=False, highlight=False)
                rendered_len = len(cleaned_response)
            speech_delta = cleaned_response[speech_len:] if len(cleaned_response) >= speech_len else ""
            if speech_delta:
                speech_buffer += speech_delta
                speech_len = len(cleaned_response)
        sentences, speech_buffer = _extract_complete_sentences(speech_buffer)
        if not speech_started and not sentences:
            partial_chunk, speech_buffer = _extract_partial_speech_chunk(speech_buffer)
            if partial_chunk:
                sentences.append(partial_chunk)
        for sentence in sentences:
            # Fire Edge-TTS prefetch the instant the sentence is assembled —
            # before it even reaches the speech queue.  This gives the network
            # call maximum lead time, especially for the first sentence where
            # there is no previous audio clip playing to hide the latency.
            # voice.speak() / the speech worker will detect the in-flight cache
            # entry and won't start a duplicate request.
            if edge_tts:
                voice.start_prefetch(sentence)
            pending_speech_chunks.append(sentence)
            pending_chars = sum(len(part) for part in pending_speech_chunks)
            if not speech_started:
                # First sentence: flush immediately so audio starts as soon as
                # the first complete sentence arrives.  Edge-TTS has inherent
                # network latency so we want maximum lead time.
                should_flush = len(pending_speech_chunks) >= 1 or pending_chars >= (95 if edge_tts else 90)
            else:
                # Follow-on sentences: flush every single sentence for Edge-TTS.
                # Previously we batched 2 before flushing, which caused dead-air
                # gaps whenever sentence 1 finished playing before 2+3 arrived.
                # Flushing each sentence immediately lets the prefetch mechanism
                # in voice.py start generating sentence N+1 audio while N plays.
                should_flush = edge_tts or len(pending_speech_chunks) >= 3 or pending_chars >= 220
            if should_flush:
                speech_started = _drain_speech_chunks(pending_speech_chunks, voice, speech_started)

    # If barge-in cancelled generation, discard any partial buffered speech and
    # return empty — don't speak a fallback phrase while the user is talking.
    if voice._generation_cancel.is_set():
        pending_speech_chunks.clear()
        if label_printed:
            console.print("\n")   # close the line only if we already opened it
        _voice_debug("stream_cancelled_return", chars=len(raw_response))
        return ""

    final_response = brain._postprocess(raw_response).strip()
    if not final_response:
        final_response = _fallback_turn_prompt(self_model)

    if final_response:
        final_delta = final_response[rendered_len:] if len(final_response) >= rendered_len else ""
        if final_delta:
            console.print(final_delta, end="", markup=False, highlight=False)
            rendered_len = len(final_response)
        final_speech_delta = final_response[speech_len:] if len(final_response) >= speech_len else ""
        if final_speech_delta:
            speech_buffer += final_speech_delta
            speech_len = len(final_response)

    if speech_buffer.strip():
        pending_speech_chunks.append(speech_buffer.strip())
        _voice_debug(
            "stream_flush_tail",
            chars=len(speech_buffer.strip()),
            speech_started=speech_started,
            text=speech_buffer.strip(),
        )
    if pending_speech_chunks:
        speech_started = _drain_speech_chunks(pending_speech_chunks, voice, speech_started)

    console.print("\n")
    _voice_debug(
        "stream_complete",
        mode=decision.mode,
        chars=len(final_response),
        first_chunk_ms=round(((first_chunk_at or stream_started_at) - stream_started_at) * 1000, 1),
        total_ms=round((time.monotonic() - stream_started_at) * 1000, 1),
        response=final_response,
    )
    self_model.note_response(final_response, source=decision.mode)
    logger.log_turn(persona_label, final_response)
    return final_response

def _run_voice_followup_window(
    voice,
    autocorrect,
    executor,
    copilot,
    brain,
    self_model,
    dialog_manager,
    council,
    diagnostics,
    logger,
    researcher,
    autonomist,
    evolution,
    initial_input: str | None = None,
    max_turns: int = 8,
    missed_limit: int = 3,
) -> bool:
    current_input = (initial_input or "").strip() or None
    missed_follow_ups = 0
    turns_used = 0
    # When Iris's last response ended with a "?" she's asking the user something.
    # In that case we give double the normal missed-listen patience before giving up,
    # because the user may just be thinking.
    _last_response_was_question = False
    _voice_debug(
        "followup_start",
        initial_input=current_input or "",
        max_turns=max_turns,
        missed_limit=missed_limit,
        admin_unlocked=getattr(self_model, "admin_unlocked", False),
    )

    # Tracks the previous loop's speaking state so we can detect the
    # speaking→silent transition and insert a dead zone before opening the mic.
    _was_speaking = False
    # Set to True by any break path that already logged its own reason so
    # the catch-all 'complete' log at the bottom doesn't fire a second time.
    _exit_logged = False

    while turns_used < max_turns:
        if current_input is None:
            speaking_now = voice.is_speaking()
            if speaking_now:
                _was_speaking = True
                # Run a 0.3s interrupt poll during TTS playback so the user
                # can barge in.  The short clip is used as a SIGNAL only —
                # we stop speech and then re-listen with listen_for_command
                # (9s limit) to capture the complete utterance cleanly.
                # This replaces the old "sleep 100ms / heard_text=None" which
                # made barge-in completely impossible inside a conversation.
                #
                # NOTE: on_phrase_captured=voice.stop_speaking is intentionally
                # NOT passed here.  On speaker setups the mic picks up TTS
                # audio, listen_for_interrupt captures it as "speech" within
                # ~50 ms, and on_phrase_captured would kill IRIS's own voice
                # mid-sentence on every response.  Instead we cut TTS the
                # instant Whisper returns any non-echo transcript — the echo
                # guard inside listen_for_interrupt() already filters out
                # speaker bleed-through before it returns, so any non-None
                # result here is confirmed real user speech.
                _interrupt_text = voice.listen_for_interrupt()
                # Fast-cut: stop audio the moment Whisper confirms real speech.
                # Don't wait for should_ignore_transcript (saves ~50-150 ms).
                # Works for both IRIS and Aletheia — stop_speaking() is
                # persona-agnostic (kills the pygame mixer regardless of voice).
                if _interrupt_text and voice.is_speaking():
                    voice.stop_speaking()
                _interrupt_ignored = (
                    voice.should_ignore_transcript(_interrupt_text)
                    if _interrupt_text else True
                )
                if not _interrupt_text or _interrupt_ignored:
                    # Nothing real heard — keep polling
                    heard_text = None
                else:
                    # Real user speech detected while IRIS is talking.
                    _lowered = _interrupt_text.lower()
                    _is_pure_stop = any(
                        t in _lowered
                        for t in ["stop", "wait", "hold on", "quiet",
                                  "enough", "shush", "pause", "shut up"]
                    )
                    _voice_debug(
                        "followup_barge_in_signal",
                        interrupt_text=_interrupt_text,
                        is_pure_stop=_is_pure_stop,
                        is_wake=_matches_active_wake_word(_interrupt_text, self_model),
                    )
                    # stop_speaking() was already called above on Whisper return;
                    # this guard covers the edge case where audio resumed on a
                    # cached prefetch chunk during the Whisper round-trip.
                    if voice.is_speaking():
                        voice.stop_speaking()
                    time.sleep(0.20)  # let speaker ring off
                    _was_speaking = False
                    speaking_now = False  # barge-in stopped speech; don't carry stale True into the rest of this iteration
                    _is_polite_exit_barge = _normalize_command_text(_interrupt_text) in {
                        "thanks", "thank you", "bye", "goodbye"
                    }
                    if _is_pure_stop and not _matches_active_wake_word(
                        _interrupt_text, self_model
                    ):
                        # Pure stop ("stop", "wait" etc.) — halt TTS, no
                        # follow-up command.  Loop back to listen_for_command.
                        heard_text = None
                    elif _is_polite_exit_barge and not _matches_active_wake_word(
                        _interrupt_text, self_model
                    ):
                        # Polite close used as barge-in — no need to re-listen.
                        # Pass phrase directly so the polite_exit check below
                        # closes the session cleanly without wasting listen cycles.
                        heard_text = _interrupt_text
                    else:
                        # User is saying something beyond a bare stop word.
                        # Capture the full utterance now that IRIS is silent.
                        heard_text = voice.listen_for_command(
                            timeout=5.0, phrase_time_limit=9.0
                        )
            else:
                if _was_speaking:
                    # 500 ms dead zone on speaking→silent transition.
                    # Without this the mic opens while speaker audio is still
                    # decaying, and Whisper transcribes the echo as a command.
                    time.sleep(0.50)
                    _was_speaking = False
                heard_text = voice.listen_for_command(timeout=5.0, phrase_time_limit=9.0)

            ignored = voice.should_ignore_transcript(heard_text) if heard_text else False
            # Only log when there's actual content OR when Iris just finished
            # speaking (the first silent poll after speech ends).  Skips the
            # 10-per-second empty spam from the 100ms wait loop during playback.
            if heard_text or not speaking_now:
                _voice_debug(
                    "followup_heard",
                    heard_text=heard_text or "",
                    ignored=ignored,
                    turns_used=turns_used,
                    missed_follow_ups=missed_follow_ups,
                    speaking=speaking_now,
                )
            if not heard_text or ignored:
                if speaking_now:
                    continue
                missed_follow_ups += 1
                # If Iris just asked a question, give double patience before giving up.
                # The user may be thinking or forming a reply.
                effective_limit = (missed_limit * 2) if _last_response_was_question else missed_limit
                if missed_follow_ups >= effective_limit:
                    _voice_debug("followup_end", reason="missed_limit", turns_used=turns_used, missed_follow_ups=missed_follow_ups, was_question=_last_response_was_question)
                    # Session persistence: instead of silently dropping back to wake
                    # mode, speak a brief "still here" cue so the user knows Iris is
                    # listening and didn't time out.  Reset the counter and keep going
                    # — only a deliberate "terminate" or polite goodbye should end the
                    # session.
                    _still_here = "Still here." if self_model.admin_unlocked else "Still here, whenever you're ready."
                    voice.speak(_still_here, interrupt=False)
                    voice.record_spoken(_still_here)
                    missed_follow_ups = 0
                    _last_response_was_question = False
                continue

            # ── Barge-in guard: only stop speech when the input is genuinely
            # substantive AND not a Whisper hallucination.  Stopping speech first
            # (old behaviour) meant that TTS echo transcribed as "urn" or other
            # single-word artefacts would kill playback mid-sentence.
            _is_substantive = _is_substantive_voice_input(heard_text, self_model)
            _is_hallucination = voice.should_ignore_transcript(heard_text) if heard_text else False
            # Extra guard during barge-in: require at least 2 words.
            # On laptops the mic catches speaker echo that Whisper renders as a
            # single real word (e.g. "complete", "adult", "urns").  Real
            # interruptions almost always contain a verb or a noun phrase.
            # Exit/stop single-word commands are already exempted above via
            # _matches_program_exit / _is_interrupt_phrase.
            if speaking_now and _is_substantive and not _is_hallucination:
                _barge_words = _normalize_command_text(heard_text).split()
                _barge_normalized = " ".join(_barge_words)
                # HF-2 fix: allow "iris" / "aletheia" through the 2-word guard.
                # Saying her name is a valid attention signal during TTS playback.
                # All other single-word inputs remain gated (echo artifacts like
                # "complete", "adult", "urns" are still blocked).
                if len(_barge_words) < 2 and _barge_normalized not in {"iris", "aletheia"}:
                    _voice_debug(
                        "followup_barge_single_word_ignored",
                        heard_text=heard_text,
                        normalized=_barge_normalized,
                    )
                    continue

            if not _is_substantive or _is_hallucination:
                _voice_debug(
                    "followup_fragment_ignored",
                    heard_text=heard_text,
                    normalized=_normalize_command_text(heard_text),
                    speaking=speaking_now,
                )
                continue

            if speaking_now:
                _voice_debug(
                    "followup_barge_in",
                    heard_text=heard_text,
                    normalized=_normalize_command_text(heard_text),
                )
                voice.stop_speaking()

            cleaned = _strip_active_wake_word(heard_text, self_model)
            if _is_interrupt_phrase(cleaned) or not cleaned:
                post_interrupt = _extract_interrupt_followup(heard_text)
                current_input = post_interrupt.strip() or None
                missed_follow_ups = 0
                _voice_debug("followup_interrupt", cleaned=cleaned or "", post_interrupt=post_interrupt or "")
                if current_input is None:
                    continue
            else:
                current_input = cleaned.strip() or None
                _voice_debug("followup_cleaned", cleaned=current_input or "")
                if current_input is None:
                    missed_follow_ups += 1
                    if missed_follow_ups >= missed_limit:
                        _voice_debug("followup_end", reason="cleaned_empty", turns_used=turns_used, missed_follow_ups=missed_follow_ups)
                        _exit_logged = True
                        break
                    continue

        normalized = _normalize_command_text(current_input)
        if normalized in {"thanks", "thank you", "bye", "goodbye"}:
            _voice_debug("followup_end", reason="polite_exit", normalized=normalized, turns_used=turns_used)
            _exit_logged = True
            break
        if _is_interrupt_phrase(normalized):
            _voice_debug("followup_interrupt_phrase", normalized=normalized)
            current_input = None
            continue

        _voice_debug("followup_dispatch", current_input=current_input, normalized=normalized, turn=turns_used + 1)
        # Thinking cue: play a brief phrase immediately so the user hears
        # audio feedback before the LLM responds.  STT + LLM latency can
        # be 2–5 s of dead air; without this cue users re-speak during the
        # silence, triggering a barge-in that cancels the response they
        # asked for.  The cue plays from the static cache (zero TTS
        # latency) and is interrupted cleanly by the first LLM sentence.
        if not voice.is_speaking():
            _cue = random.choice(_THINKING_CUES)
            # Only play if the phrase is already in the static audio cache.
            # If prewarm missed (e.g. network hiccup at startup), skip silently
            # rather than blocking the speech worker on a live 8-second Edge-TTS
            # call that would delay the real response by the full TTS timeout.
            if voice.is_static_cached(_cue):
                voice.speak(_cue, interrupt=False)
                voice.record_spoken(_cue)
        # ── Pre-speech barge-in: monitor the mic while the LLM is generating.
        # If the user speaks before any audio has started we detect it via raw
        # RMS (no Whisper round-trip) and immediately cancel generation + speech.
        voice.reset_generation_cancel()
        _barge_in_stop = voice.start_barge_in_monitor(
            on_barge_in=lambda: voice.cancel_generation(),
            # warmup_sec=1.5: suppress barge-in for 1.5 s after the thinking cue
            # starts.  The old default (0.45 s) expired while the cue was still
            # playing, so the mic picked up the user re-speaking during dead air
            # and cancelled the response they were waiting for.  1.5 s covers
            # the longest thinking-cue ("Good question." ~1.1 s) plus ~0.4 s margin.
            warmup_sec=1.5,
        )
        try:
            last_response, should_exit = handle_user_input(
                current_input,
                voice,
                autocorrect,
                executor,
                copilot,
                brain,
                self_model,
                dialog_manager,
                council,
                diagnostics,
                logger,
                researcher,
                autonomist,
                evolution,
                voice_mode=True,
            )
        finally:
            # Always stop the barge-in monitor once we're done generating.
            _barge_in_stop.set()
        turns_used += 1
        current_input = None
        missed_follow_ups = 0
        # Track whether Iris ended with a question so we give extra patience next loop.
        _last_response_was_question = bool(
            last_response and isinstance(last_response, str)
            and last_response.rstrip().endswith("?")
        )
        if should_exit:
            _voice_debug("followup_end", reason="should_exit", turns_used=turns_used)
            return True

    if not _exit_logged:
        _voice_debug("followup_end", reason="complete", turns_used=turns_used, missed_follow_ups=missed_follow_ups)
    return False

# ── BANNER ──────────────────────────────────────────────────────────────────
_RAW_BANNER = rf"""
  ██╗██████╗ ██╗███████╗
  ██║██╔══██╗██║██╔════╝
  ██║██████╔╝██║███████╗
  ██║██╔══██╗██║╚════██║
  ██║██║  ██║██║███████║
  ╚═╝╚═╝  ╚═╝╚═╝╚══════╝
  {Config.SYSTEM_MOTTO}
"""
BANNER = escape(_RAW_BANNER)

# ────────────────────────────────────────────────────────────────────────────

def show_status(voice: Voice, self_model: SelfModel) -> None:
    try:
        v_p, v_f = get_vram_status()
    except Exception:
        v_p, v_f = 0.0, 0.0

    cpu_p = psutil.cpu_percent()
    mic_name = getattr(voice, "mic_name", "") or ""
    mic_status = "Ready" if getattr(voice, "mic_ready", False) else "Unavailable"
    if mic_status == "Ready" and mic_name:
        mic_status = f"Ready: {mic_name}"

    color = "red" if self_model.admin_unlocked else "cyan"
    mode_label = "ROOT / ALETHEIA" if self_model.admin_unlocked else "PUBLIC / IRIS"

    table = Table(title=f"IRIS v5.1 Status - {mode_label}", border_style=color, box=None)
    table.add_column("Component", style="white")
    table.add_column("Status / Data", style=color)

    table.add_row("Identity", Config.INNER_CODENAME if self_model.admin_unlocked else "IRIS")
    table.add_row("VRAM Usage", f"{v_p:.1f}% ({v_f:.0f}MB Free)")
    table.add_row("CPU Load", f"{cpu_p}%")
    table.add_row("Microphone", f"{mic_status} (Gate: {Config.WAKE_RMS_THRESHOLD})")
    table.add_row("STT Backend", getattr(voice, "stt_status", lambda: "unknown")())
    table.add_row("TTS Backend", getattr(voice, "tts_status", lambda: "unknown")())
    table.add_row("Self Model", self_model.summary())

    console.print(table)
    _voice_debug(
        "status_snapshot",
        mic_status=mic_status,
        gate=Config.WAKE_RMS_THRESHOLD,
        stt_backend=getattr(voice, "stt_status", lambda: "unknown")(),
        tts_backend=getattr(voice, "tts_status", lambda: "unknown")(),
        vram_percent=round(v_p, 1),
        cpu_percent=round(cpu_p, 1),
    )

def handle_user_input(user_input, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger, researcher=None, autonomist=None, evolution=None, voice_mode=False):
    user_input = (user_input or "").strip()
    if not user_input: return None, False

    started_at = time.monotonic()
    logger.log_turn("User", user_input)
    lowered = user_input.lower()
    normalized = _normalize_command_text(user_input)
    persona_label = "Aletheia" if self_model.admin_unlocked else "IRIS"
    _voice_debug("handle_input", text=user_input, normalized=normalized, voice_mode=voice_mode, admin_unlocked=self_model.admin_unlocked)

    exit_action = _classify_exit_action(user_input, self_model)
    if exit_action == "EXIT":
        _voice_debug("handle_exit_match", text=user_input, normalized=normalized, voice_mode=voice_mode)
        return "EXIT", True
    if exit_action == "LOCK":
        _voice_debug("handle_exit_lock", text=user_input, normalized=normalized, voice_mode=voice_mode)
        return _lock_to_public_mode(voice, brain, self_model)

    if _matches_admin_unlock(user_input):
        if not self_model.admin_unlocked:
            self_model.admin_unlocked = True
            # Switch to Aletheia's authoritative voice immediately.
            voice.set_active_voice(Config.ALETHEIA_VOICE_NAME, Config.ALETHEIA_VOICE_RATE)
            console.bell()
            resp = _generate_greeting(admin_unlocked=True, brain=brain)
            console.print("\n[bold red][🔒 ROOT ACCESS GRANTED][/bold red]")
            voice.speak(resp)
            voice.record_spoken(resp)
            _voice_debug("handle_admin_unlock", text=user_input, normalized=normalized, response=resp)
            brain.memory.conversation.clear()
            brain.memory._save()
        return "UNLOCKED", False
    elif lowered.strip() in ["lock protocol", "revert to iris"]:
        return _lock_to_public_mode(voice, brain, self_model)

    # ── Mute / unmute / stop ─────────────────────────────────────────────────
    # Mute is intentionally handled BEFORE everything else (including status)
    # so the user can silence Iris mid-sentence without any response being queued.
    _MUTE_WORDS   = {"mute", "mute iris", "be quiet", "quiet", "shh", "shush",
                     "shut up", "stop talking", "zip it", "silence"}
    _UNMUTE_WORDS = {"unmute", "unmute iris", "you can talk", "speak", "resume",
                     "come back", "i can hear you"}
    if normalized in _MUTE_WORDS or lowered.strip() in _MUTE_WORDS:
        voice.mute()
        console.print("[dim]🔇 Muted. Say 'unmute' to restore voice.[/dim]")
        return "muted", False
    if normalized in _UNMUTE_WORDS or lowered.strip() in _UNMUTE_WORDS:
        voice.unmute()
        _ack = "Back." if self_model.admin_unlocked else "I'm back — what were you saying?"
        console.print("[dim]🔊 Unmuted.[/dim]")
        voice.speak(_ack, interrupt=True)
        voice.record_spoken(_ack)
        return _ack, False

    # ── Stop / pause (instant TTS cancel, no LLM round-trip) ────────────────
    _STOP_WORDS = {"stop", "pause", "hold on", "wait", "one second", "one moment",
                   "stop speaking", "stop talking", "pause iris"}
    if normalized in _STOP_WORDS or lowered.strip() in _STOP_WORDS:
        if voice.is_speaking():
            voice.stop_speaking()
            return "stopped", False
        # Nothing playing — acknowledge briefly
        _ack = "Sure." if self_model.admin_unlocked else "Okay."
        voice.speak(_ack, interrupt=True)
        voice.record_spoken(_ack)
        return _ack, False

    # ── Live status command ──────────────────────────────────────────────────
    if normalized in {
        "status", "system status", "show status", "your status",
        "what is your status", "whats your status", "run diagnostics",
        "how are you doing", "how are you", "how are you running",
    }:
        show_status(voice, self_model)
        _ack = "All systems nominal." if self_model.admin_unlocked else "Looking good from where I'm standing."
        if voice_mode:
            voice.speak(_ack, interrupt=True)
            voice.record_spoken(_ack)
        return _ack, False

    corrected, _ = autocorrect.correct_input(user_input)
    user_input = corrected

    decision = dialog_manager.analyze(user_input, executor, copilot, diagnostics, self_model)
    self_model.observe_user_input(user_input, decision)
    streamed_response = False
    response = None  # initialised here; may be set by weather tool or routing below
    _voice_debug(
        "handle_decision",
        text=user_input,
        normalized=_normalize_command_text(user_input),
        mode=decision.mode,
        voice_mode=voice_mode,
        admin_unlocked=self_model.admin_unlocked,
    )

    # ── Weather tool: real-time OpenWeatherMap data ─────────────────────────
    if is_weather_query(user_input) and getattr(Config, "OPENWEATHER_API_KEY", ""):
        location = extract_location(user_input)
        if location:
            _voice_debug("handle_decision", text=user_input, normalized=_normalize_command_text(user_input), mode="weather", voice_mode=voice_mode, admin_unlocked=self_model.admin_unlocked)
            want_forecast = any(w in user_input.lower() for w in ("forecast", "tomorrow", "tonight", "next few", "week"))
            _weather_resp = get_forecast(location) if want_forecast else get_current_weather(location)
            # Let brain phrase it naturally using the raw data
            _weather_prompt = (
                f"Weather data for '{location}': {_weather_resp}\n\n"
                f"Rephrase this weather data naturally in one or two sentences, "
                f"in the same language as the user's query: '{user_input}'. "
                f"Keep it concise and conversational. Do not add anything that isn't in the data."
            )
            if voice_mode:
                response = _stream_reasoning_response(_weather_prompt, voice, brain, self_model, decision, None, logger)
                streamed_response = True
            else:
                response = brain.think(_weather_prompt, admin_unlocked=self_model.admin_unlocked, voice_mode=voice_mode)
        else:
            # No location found — let the LLM ask for it naturally
            pass

    if not response and decision.mode == "diagnostics":
        response = diagnostics.run(user_input, brain, voice, executor, copilot, brain.memory, self_model)
    elif not response and decision.mode == "action_pending":
        # The executor is waiting for a confirmation, clarification, follow-up,
        # or plan-choice response.  Route directly to the correct handler so the
        # user's "yes / go ahead / cancel" words actually execute (or cancel) the
        # pending action instead of being sent to the LLM.
        if executor.waiting_for_clarification():
            response = executor.handle_clarification_response(user_input)
        elif executor.waiting_for_permission():
            response = executor.handle_permission_response(user_input)
        elif executor.waiting_for_followup():
            response = executor.handle_followup_response(user_input)
        elif executor.waiting_for_plan_choice():
            response = executor.handle_plan_choice(user_input)
        # If the executor returned None (edge case), fall through to the LLM
        # by leaving response=None so the elif-not-response chain below catches it.
    elif not response and decision.mode == "action":
        with console.status("[bold yellow]Formulating action plan...[/bold yellow]", spinner="dots"):
            response = executor.plan_action(user_input, admin_unlocked=self_model.admin_unlocked)
        if evolution and "couldn't figure out how to do that" in response.lower():
            response = evolution.triage_unknown_intent(user_input, admin_unlocked=self_model.admin_unlocked)
    elif not response and decision.mode == "search" and researcher:
        with console.status("[bold green]Searching web...[/bold green]", spinner="dots"):
            response = researcher.search(user_input)
    elif not response and decision.mode == "copilot" and copilot:
        response = copilot.start(user_input)
    elif not response:
        is_safe, temp = diagnostics.check_thermal_integrity()
        if not is_safe:
            response = f"Reasoning throttled. GPU Core critical at {temp}°C."
            console.print(f"[bold red]THERMAL OVERRIDE:[/bold red] {response}")
        else:
            packet = council.deliberate(user_input, decision, self_model)
            self_model.apply_council(packet.roles)
            # Inject archived session history when the user asks IRIS to recall
            # something from a previous conversation.
            _recall_ctx = _build_recall_context(user_input, brain.memory)
            if _recall_ctx:
                packet.extra_system = (
                    f"{packet.extra_system}\n\n{_recall_ctx}".strip()
                    if packet.extra_system else _recall_ctx
                )
            if voice_mode:
                response = _stream_reasoning_response(user_input, voice, brain, self_model, decision, packet, logger)
                streamed_response = True
            else:
                with console.status("[cyan]Thinking...[/cyan]", spinner="dots"):
                    response = brain.think(
                        user_input,
                        council_packet=packet,
                        admin_unlocked=self_model.admin_unlocked,
                        voice_mode=voice_mode,
                    )

    if not streamed_response:
        self_model.note_response(response, source=decision.mode)
        label_color = "red" if self_model.admin_unlocked else "cyan"
        logger.log_turn(persona_label, response)
        # Print immediately so text appears before audio starts
        console.print(f"\n[bold {label_color}]{persona_label}:[/bold {label_color}] {response}\n")
        # Split into sentences so Edge-TTS can pipeline: play sentence N while
        # generating audio for sentence N+1 via the prefetch mechanism in voice.py.
        # interrupt=True only on the first chunk to cancel any previous speech.
        _tts_parts = [s.strip() for s in re.split(r'(?<=[.!?])\s+', response) if s.strip()]
        for _tts_idx, _tts_part in enumerate(_tts_parts):
            voice.speak(_tts_part, interrupt=(_tts_idx == 0))
        voice.record_spoken(response)

    _voice_debug(
        "handle_complete",
        mode=decision.mode,
        voice_mode=voice_mode,
        elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
        response=response,
    )
    return response, False


def _wait_for_engine(brain: Brain, timeout: int = 30) -> bool:
    waited = 0
    while brain.llm is None and waited < timeout:
        time.sleep(0.5)
        waited += 0.5
    return brain.llm is not None


def _wait_for_voice_idle(voice, timeout: float = 2.5) -> None:
    """Wait for any in-progress speech to finish, with a hard timeout."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if not voice.is_speaking():
                break
        except Exception:
            break
        time.sleep(0.05)


def _run_session_learning(autonomist, log_path: str, learn_error: list) -> None:
    """Run session learning on a daemon thread and capture errors."""
    try:
        autonomist.learn_from_session(log_path)
    except Exception as e:
        learn_error.append(e)


def _finalize_session(autonomist, logger) -> None:
    """Finalize the session and bound shutdown learning."""
    try:
        logger.finalize()
    except Exception as e:
        console.print(f"[dim yellow]Cleanup error: {e}[/dim yellow]")
        return

    learn_error = []
    learning_thread = threading.Thread(
        target=lambda: _run_session_learning(autonomist, logger.filename, learn_error),
        daemon=True,
        name="iris-shutdown-learning",
    )
    learning_thread.start()
    learning_thread.join(timeout=1.5)

    if learning_thread.is_alive():
        console.print("[dim yellow]Skipping slow shutdown learning to avoid exit stall.[/dim yellow]")
    elif learn_error:
        console.print(f"[dim yellow]Cleanup error: {learn_error[0]}[/dim yellow]")


def _force_exit(code: int = 0) -> None:
    """Hard exit after cleanup — ensures the process always terminates."""
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


def main() -> None:
    Config.validate()

    parser = argparse.ArgumentParser()
    parser.add_argument("--text", action="store_true")
    args = parser.parse_args()

    console.print("[bold yellow]Initializing IRIS systems...[/bold yellow]")
    memory = Memory(Config.MEMORY_FILE)

    # ── Session isolation ──────────────────────────────────────────────────
    # Archive the previous session before wiping it so IRIS can recall it
    # when the user asks "do you remember our last conversation about X?".
    memory.archive_session()
    # Wipe stale turns — each session starts fresh so IRIS doesn't correlate
    # new questions with last session's context.
    memory.conversation.clear()
    memory._save()

    logger = SessionLogger()

    try:
        brain = Brain(memory)
    except Exception as e:
        console.print(f"[bold red]FATAL: LLM Engine failed to initialize:[/bold red] {e}")
        sys.exit(1)

    voice = Voice(text_mode=args.text)
    self_model = SelfModel()

    copilot, executor = CoPilot(brain, voice, memory), ActionExecutor(voice, brain)
    autocorrect, dialog_manager = AutoCorrector(brain), DialogManager()
    council, diagnostics = Council(), SelfDiagnostics()
    researcher, autonomist = Researcher(brain), Autonomist(brain)
    evolution = EvolutionEngine(brain, researcher)

    # Wait for C++ engine to finish loading before printing banner
    engine_ready = _wait_for_engine(brain, timeout=30)
    if not engine_ready:
        console.print("[bold yellow]⚠ C++ Engine still loading — falling back to cloud APIs.[/bold yellow]")

    # Clean UI render now that engine noise is done
    console.print(BANNER, style="bold cyan")
    # NOTE: show_status() is called AFTER the STT-ready wait below so the
    # STT Backend row reflects the actual final state, not "Local loading".

    # Pre-warm static TTS cache for all known short phrases so wake acks and
    # farewells play instantly (file load only, no network round-trip).
    _all_static_phrases = (
        _WAKE_ACKS_PUBLIC + _WAKE_ACKS_ADMIN +
        _GREETINGS_PUBLIC + _GREETINGS_ADMIN +
        _FAREWELLS_PUBLIC + _FAREWELLS_ADMIN +
        _THINKING_CUES +
        ["I'm still here.", "State the task.", "Done."]
    )
    voice.prime_audio_cache(_all_static_phrases)

    # Kick off greeting LLM generation in the background so the Groq API call
    # runs in parallel with the STT warmup, not after it.
    # Also pre-generate the greeting TTS so voice.speak() gets an instant cache hit.
    _greeting_result: list = [None]
    _greeting_done = threading.Event()

    def _bg_greeting():
        try:
            _greeting_result[0] = _generate_greeting(self_model.admin_unlocked, brain=brain)
            # Pre-generate TTS for the dynamic greeting text so first sound is instant.
            if _greeting_result[0] and not voice._force_io_disabled and getattr(Config, "TTS_ENGINE", "auto") == "edge":
                import tempfile as _tf
                clean = voice._clean_for_speech(_greeting_result[0])
                if clean:
                    with _tf.NamedTemporaryFile(delete=False, suffix=".mp3") as _tmp:
                        _pf = _tmp.name
                    ok = voice._run_edge_tts_async(clean, Config.VOICE_NAME, Config.VOICE_RATE, _pf)
                    if ok and os.path.exists(_pf) and os.path.getsize(_pf) > 0:
                        with voice._static_audio_cache_lock:
                            voice._static_audio_cache[clean] = _pf
        except Exception as _greet_err:
            logger.warning("[Main] Background greeting generation failed: %s", _greet_err)
            _greeting_result[0] = None
        finally:
            _greeting_done.set()

    threading.Thread(target=_bg_greeting, daemon=True, name="iris-greeting-gen").start()

    # Wait for local STT to finish loading before greeting so IRIS is
    # ready to listen the moment she finishes speaking.
    # Timeout is long (90s) to cover first-run model downloads (~485MB for
    # small.en).  Progress lines print every 15s so the user knows it's alive.
    # If STT is still not ready after 90s, start anyway with cloud fallback —
    # Whisper will quietly finish loading in the background.
    if not args.text and voice.stt_status() == "Local loading":
        _stt_wait_start = time.monotonic()
        _stt_timeout = 90.0
        _stt_last_msg_at = 0.0
        while voice.stt_status() == "Local loading":
            _elapsed = time.monotonic() - _stt_wait_start
            if _elapsed > _stt_timeout:
                console.print(
                    "[bold yellow]⚠ STT taking too long — starting with cloud fallback. "
                    "Whisper will finish loading in the background.[/bold yellow]"
                )
                break
            if _elapsed - _stt_last_msg_at >= 15.0:
                console.print(
                    f"[dim yellow]⏳ Local STT loading... ({int(_elapsed)}s)[/dim yellow]"
                )
                _stt_last_msg_at = _elapsed
            time.sleep(0.15)

    # ── Print live status NOW — STT is confirmed ready, values are accurate ──
    show_status(voice, self_model)

    # Wait for the LLM greeting text to be ready (usually already done by now).
    _greeting_done.wait(timeout=6.0)
    greeting = _greeting_result[0] or random.choice(_GREETINGS_PUBLIC)

    # Also wait briefly for the greeting TTS audio to land in the static cache so
    # voice.speak() gets an instant file-load hit instead of a fresh network call.
    if not voice._force_io_disabled and getattr(Config, "TTS_ENGINE", "auto") == "edge":
        _clean_greeting = voice._clean_for_speech(greeting)
        _tts_ready_start = time.monotonic()
        while time.monotonic() - _tts_ready_start < 4.0:
            with voice._static_audio_cache_lock:
                _entry = voice._static_audio_cache.get(_clean_greeting)
            if isinstance(_entry, str):   # str = path ready; None = still in-flight
                break
            time.sleep(0.08)

    # Boot greeting — spoken + printed
    if not args.text:
        console.print(f"\n[bold green]🎤 Voice Mode — listening for: {_public_wake_word()}[/bold green]")
    else:
        console.print(f"\n[bold green]⌨️  Text Mode — type your command[/bold green]")
    console.print(f"[bold cyan]IRIS:[/bold cyan] {greeting}")
    voice.speak(greeting)
    voice.record_spoken(greeting)

    last_bare_wake_at = 0.0
    # Post-speech grace: tracks when IRIS last stopped speaking so the outer
    # loop can accept follow-on commands without requiring the wake word again.
    _outer_was_speaking = False
    _last_outer_speech_ended_at = 0.0
    _OUTER_GRACE_SEC = 6.0   # seconds after speech ends to accept bare commands

    try:
        while True:
            try:
                v_p, _ = get_vram_status()
                is_safe, temp = diagnostics.check_thermal_integrity()
                if v_p > Config.VRAM_CRITICAL_PERCENT:
                    console.print("[bold red]VRAM CRITICAL - System throttled.[/bold red]")
                if not is_safe:
                    console.print(f"[bold red]THERMAL WARNING - GPU: {temp}°C.[/bold red]")
            except Exception:
                pass

            try:
                if args.text:
                    console.print("[bold magenta]>[/bold magenta] ", end="")
                    user_input = input()
                    if not user_input.strip(): continue

                    _, should_exit = handle_user_input(user_input, voice, autocorrect, executor, copilot, brain, self_model, dialog_manager, council, diagnostics, logger, researcher, autonomist, evolution, voice_mode=False)
                    if should_exit: break
                    continue

                during_speech = voice.is_speaking()
                # Track the moment IRIS stops speaking so we can open a grace window.
                if _outer_was_speaking and not during_speech:
                    _last_outer_speech_ended_at = time.monotonic()
                _outer_was_speaking = during_speech

                active_wake_words = _active_wake_words(self_model)
                _in_grace = (
                    not during_speech
                    and _last_outer_speech_ended_at > 0
                    and (time.monotonic() - _last_outer_speech_ended_at) < _OUTER_GRACE_SEC
                )
                if during_speech:
                    heard_text = voice.listen_for_interrupt()
                elif _in_grace:
                    # IRIS just finished speaking — accept a natural follow-on
                    # command without requiring the wake word again.
                    heard_text = voice.listen_for_command(timeout=4.0, phrase_time_limit=9.0)
                else:
                    heard_text = voice.listen_for_wake()
                _listen_source = "interrupt" if during_speech else ("grace" if _in_grace else "wake")
                if not heard_text:
                    _voice_debug("wake_loop_heard", source=_listen_source, heard_text="", action="empty")
                    continue
                ignored = voice.should_ignore_transcript(heard_text)
                _voice_debug(
                    "wake_loop_heard",
                    source=_listen_source,
                    heard_text=heard_text,
                    ignored=ignored,
                    during_speech=during_speech,
                    active_wake_words=",".join(active_wake_words),
                )
                if ignored:
                    continue

                lowered_heard = heard_text.lower()
                direct_control = _classify_exit_action(heard_text, self_model) is not None or _matches_admin_unlock(heard_text)
                is_wake = _matches_active_wake_word(heard_text, self_model) or direct_control
                interrupt_only = during_speech and any(token in lowered_heard for token in ["stop", "wait", "hold on", "quiet"]) and not is_wake
                _voice_debug(
                    "wake_loop_route",
                    heard_text=heard_text,
                    is_wake=is_wake,
                    direct_control=direct_control,
                    interrupt_only=interrupt_only,
                    during_speech=during_speech,
                )

                if during_speech:
                    cleaned = heard_text
                    if is_wake:
                        cleaned = _strip_active_wake_word(cleaned, self_model)
                    _voice_debug("interrupt_route", cleaned=cleaned or "")

                    if interrupt_only:
                        # Only stop speech once we're sure it's a real stop command.
                        if voice.is_speaking():
                            voice.stop_speaking()
                        post_interrupt = _extract_interrupt_followup(cleaned)
                        should_exit = _run_voice_followup_window(
                            voice,
                            autocorrect,
                            executor,
                            copilot,
                            brain,
                            self_model,
                            dialog_manager,
                            council,
                            diagnostics,
                            logger,
                            researcher,
                            autonomist,
                            evolution,
                            initial_input=post_interrupt or None,
                            max_turns=20,
                            missed_limit=5,
                        )
                    elif is_wake:
                        # Wake word confirmed — now it's safe to stop speech.
                        if voice.is_speaking():
                            voice.stop_speaking()
                        should_exit = _run_voice_followup_window(
                            voice,
                            autocorrect,
                            executor,
                            copilot,
                            brain,
                            self_model,
                            dialog_manager,
                            council,
                            diagnostics,
                            logger,
                            researcher,
                            autonomist,
                            evolution,
                            initial_input=cleaned,
                            max_turns=20,
                            missed_limit=5,
                        )
                    else:
                        # Not a wake word, not a stop command — ignore and let
                        # IRIS keep talking.  Do NOT call stop_speaking() here;
                        # the old code called it unconditionally before this check
                        # which caused TTS echo ("Evening") to silence IRIS.
                        _voice_debug("interrupt_ignored", heard_text=heard_text, reason="non_wake_non_interrupt")
                        continue
                    if should_exit:
                        break
                    continue

                if not during_speech and not is_wake and _in_grace and heard_text:
                    # Post-speech grace: IRIS just finished speaking and the user
                    # said something without a wake word.  Open a followup session
                    # with their command directly, so they don't have to repeat
                    # "iris" / "aletheia" for every natural follow-on turn.
                    _voice_debug(
                        "grace_period_route",
                        heard_text=heard_text,
                        since_speech_ms=round((time.monotonic() - _last_outer_speech_ended_at) * 1000, 1),
                    )
                    should_exit = _run_voice_followup_window(
                        voice,
                        autocorrect,
                        executor,
                        copilot,
                        brain,
                        self_model,
                        dialog_manager,
                        council,
                        diagnostics,
                        logger,
                        researcher,
                        autonomist,
                        evolution,
                        initial_input=heard_text,
                        max_turns=20,
                        missed_limit=5,
                    )
                    # Reset grace window after session — user is now in a fresh loop.
                    _last_outer_speech_ended_at = 0.0
                    if should_exit:
                        break
                    continue

                if is_wake:
                    cleaned = _strip_active_wake_word(heard_text, self_model)
                    _voice_debug("wake_match", heard_text=heard_text, cleaned=cleaned or "")

                    now = time.monotonic()
                    if not cleaned and (now - last_bare_wake_at) < 1.8:
                        _voice_debug(
                            "wake_duplicate_ignored",
                            heard_text=heard_text,
                            since_ms=round((now - last_bare_wake_at) * 1000, 1),
                        )
                        continue

                    if not cleaned:
                        last_bare_wake_at = now
                        label_color = "red" if self_model.admin_unlocked else "cyan"
                        persona_label = "Aletheia" if self_model.admin_unlocked else "IRIS"
                        ack_pool = _WAKE_ACKS_ADMIN if self_model.admin_unlocked else _WAKE_ACKS_PUBLIC
                        wake_ack = random.choice(ack_pool)
                        console.print(f"\n[bold {label_color}]{persona_label}:[/bold {label_color}] {wake_ack}\n")
                        voice.speak(wake_ack)
                        voice.record_spoken(wake_ack)
                        _voice_debug("wake_ack", wake_ack=wake_ack)
                    should_exit = _run_voice_followup_window(
                        voice,
                        autocorrect,
                        executor,
                        copilot,
                        brain,
                        self_model,
                        dialog_manager,
                        council,
                        diagnostics,
                        logger,
                        researcher,
                        autonomist,
                        evolution,
                        initial_input=cleaned or None,
                        max_turns=20,
                        missed_limit=5,
                    )
                    if should_exit:
                        break

            except EOFError:
                break
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {e}")
                # C-01: exceptions must never leave admin_unlocked=True.
                # If an exception fires mid-admin-session, the next iteration
                # would otherwise run with full root privileges silently.
                self_model.admin_unlocked = False

    except KeyboardInterrupt:
        pass
    finally:
        try:
            voice_summary = getattr(voice, "runtime_summary", lambda: {})()
            _voice_debug("session_summary", **voice_summary)
        except Exception:
            pass
        farewell = _generate_farewell(self_model)
        console.print(f"\n[bold yellow]Exiting:[/bold yellow] {farewell}")
        voice.speak(farewell)
        voice.record_spoken(farewell)
        _wait_for_voice_idle(voice)

        console.print("\n[bold cyan]IRIS:[/bold cyan] Terminating. Finalizing memory...")
        try:
            voice.close_mic()
        except Exception:
            pass

        _finalize_session(autonomist, logger)
        _force_exit(0)


if __name__ == "__main__":
    main()
