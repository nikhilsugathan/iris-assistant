# 📂 SYSTEM HANDOFF BRIEF: PROJECT IRIS / ALETHEIA
### For: Openclaw (incoming Lead Developer)
### Prepared from: live codebase audit + session trace analysis — April 2026

---

## ⚠️ CORRECTIONS TO PREVIOUS DRAFT

The Gemini-generated draft contained several factual errors. Every item below has been verified directly against the source code. Do not trust the previous document for operational decisions.

| Gemini Draft Claimed | Actual (Verified) |
|---|---|
| Version `v5.2.5-STABLE` | `v5.1.2 (Ironclad Edition)` — per `main.py` header and status display |
| Admin passphrase: `"iris initiate"` | **Does not work.** See §6 for the real unlock mechanism |
| Follow-up window: up to **6 turns** | Hard-coded default `max_turns = 8` in `_run_voice_followup_window` |
| VRAM usage: **~7.2 GB** | Live status shows **46.4% used (~3.8 GB)** of 8 GB total |
| Security layer: **"incomplete"** | **Fully implemented** — 5-layer pipeline in `core/security.py` |
| Task 2 (Schema Firewall): **TODO** | **Already done** — `ACTIVE_TOOL_NAMES` and `ADMIN_TOOL_NAMES` are live `frozenset`s in `core/tools_registry.py` (lines 207–217) |
| Cloud fallback: Local → Groq → Gemini | Local → Groq → Gemini → **Claude Sonnet 4.6** (all four in rotation) |

---

## 1. System Overview

**Project IRIS / Aletheia** is a voice-first, low-latency, local/cloud hybrid AI desktop assistant running on Windows. It has a dual-persona Role-Based Access Control (RBAC) architecture and is designed to operate with near-zero perceived latency through pipelined STT → LLM → TTS streaming.

| Persona | Mode | Capabilities |
|---|---|---|
| **IRIS** | Public | Conversational, web search, basic app launch, play music. All file-system and shell actions are security-gated. Dry humor, warm tone. |
| **Aletheia** | Admin (Root) | Full OS authority: file create/delete/rename, package management, shell commands, window automation, GUI control. Authoritative, precise tone. |

**Active workspace:** `D:\IRIS-live`
**Entry point:** `py main.py` (optionally `--text` for keyboard mode)
**Hardware target:** NVIDIA RTX 5050 Mobile, 8 GB VRAM

---

## 2. Hardware & Engine Configuration

### Local LLM (llama.cpp)
- **Model:** Qwen3-8B-Q4_K_M via llama.cpp C++ engine
- **Context window:** `N_CTX = 8192` (model was trained at 40 960 tokens; the gap is expected and logged at boot as a non-fatal notice)
- **KV Cache:** `q8_0` quantization — **critical**. This prevents CUDA OOM crashes on the 8 GB VRAM budget. Do not change this without a VRAM audit.
- **Prompt format:** ChatML (`<|im_start|>` / `<|im_end|>`)
- **Boot gate:** `main.py` waits up to 30 s for the C++ engine before falling back to cloud APIs

### STT — Local (Primary)
- **Engine:** Faster-Whisper on CUDA, **`float16` only**
- **Why float16:** The RTX 5050 has a known CTranslate2 kernel hang with `int8` quantization on this GPU. Do not switch to `int8`.
- **VAD:** `vad_filter` setting matters — see §8 (Known Live Bugs)

### TTS
- **Engine:** Edge-TTS with a persistent async event loop
- **Cache:** Static audio cache pre-warmed at boot for all wake-ack, greeting, and farewell phrases so first audio is instant
- **Prefetch:** Every sentence is Edge-TTS-prefetched the moment it is assembled from the LLM stream, before it hits the speech queue

### Cloud Fallback APIs (in priority order for general queries)
1. **Groq** — Llama 4 Scout 17B (primary; wins for speed on general turns)
2. **Gemini** — Gemini 2.5 Flash
3. **Claude** — Sonnet 4.6
4. Local llama.cpp is also available for offline operation

Routing is handled by `core/brain.py`. Query type (general / tool / code) and available API health determine which backend wins each turn.

---

## 3. Full Architectural Blueprint

### Core files

| File | Role |
|---|---|
| `main.py` | **Orchestrator.** Wake-word loop, follow-up conversation window (8-turn default), barge-in detection, STT fragment filtering, mode switching, exit handling. All high-level conversation flow lives here. |
| `config.py` | **Source of Truth.** All thresholds, API keys (via env vars), voice names, VRAM caps. Always read config from here — never hardcode values in other files. Key constants: `WAKE_RMS_THRESHOLD=400`, `COMMAND_RMS_THRESHOLD=300`. |
| `core/voice.py` | **Audio Physics Engine.** Persistent PyAudio stream, Faster-Whisper dispatch, VAD, interrupt/barge-in polling, Edge-TTS playback queue, static audio cache. |
| `core/brain.py` | **Cognitive Router.** Priority fallback chain (Local→Groq→Gemini→Claude), ChatML prompt formatting, streaming (`stream_think`), and `_postprocess()` which strips boilerplate before TTS receives text. |
| `core/executor.py` | **OS Bridge.** Pattern-match → AI-plan → security-assess → execute pipeline. Handles file/folder creation, shell commands, app launch, music, window automation. Maintains `pending_action` state for permission gating. |
| `core/security.py` | **5-Layer Security Guard.** Every action passes through this before execution. See §7 for full layer breakdown. |
| `core/tools_registry.py` | **Tool Schema Registry.** Defines all executable tools as `ToolSpec` dataclasses. Exports `ACTIVE_TOOL_NAMES` (public allowlist) and `ADMIN_TOOL_NAMES` (all tools) as `frozenset`s. LLM only receives schemas for the active persona's allowlist. |
| `core/dialog_manager.py` | **Turn Router.** Classifies each user turn into a mode: `action_pending`, `action`, `diagnostics`, `search`, `copilot`, `reflection`, `analysis`, `creative`, `chat`. This is what decides whether a turn goes to the executor, the LLM, or the web researcher. |
| `core/memory.py` | **Session Archivist.** Clears short-term memory on boot, archives previous sessions to JSON. Injects archived session context into LLM prompts when the user asks IRIS to recall a past conversation. |
| `core/self_model.py` | **Internal State Machine.** Tracks `confidence`, `urgency`, `caution`, `warmth`, `initiative_budget`, `emotional_load`, `cognitive_mode`, and the critical `admin_unlocked` flag. Updated every turn by observing user input and LLM response. |
| `core/council.py` | **Multi-Agent Deliberation.** For complex or emotionally weighted turns, activates specialist cognitive roles before the LLM responds. |
| `core/autocorrect.py` | **Voice Input Corrector.** Fixes Whisper mishears (e.g. "py thon" → "Python") and corrects file extensions before the executor acts on them. |
| `core/improv.py` | **Plan A/B/C Generator.** When an executor action fails, generates up to 3 alternative approaches and presents them to the user for selection. |
| `core/dialog_manager.py` | **Routing classifier.** See above. |
| `core/copilot.py` | **Step-by-Step Guidance.** Activated for multi-step tutorial-style tasks. |
| `core/autonomist.py` | **Session Learner.** Post-session, learns patterns from the session log on a daemon thread. Bounded to 1.5 s at shutdown to prevent exit stalls. |
| `tools/researcher.py` | **Web Search.** Called when dialog_manager routes to `mode="search"`. |
| `core/evolution.py` | **Unknown Intent Triage.** Called when the executor returns "couldn't figure out how to do that" — attempts to derive an alternative plan. |
| `core/session_logger.py` | **Session Logger.** Writes full turn transcripts for later learning and user review. |
| `core/browser.py` | **Browser Automation.** Selenium-based; used by executor for web interactions. |
| `core/weather.py` | **Weather Tool.** OpenWeatherMap integration, invoked pre-LLM when a weather query is detected. |

---

## 4. The Conversation Flow (End-to-End)

Understanding this flow is essential before touching anything.

```
Microphone audio
    │
    ▼
voice.py — VAD → Whisper STT
    │  transcript
    ▼
main.py — wake-word detection / _strip_wake_aliases()
    │  cleaned text
    ▼
handle_user_input()
    ├── exit / lock / unlock checks  (short-circuits if matched)
    ├── mute / stop / status checks  (short-circuits if matched)
    ├── autocorrect.correct_input()
    ├── dialog_manager.analyze()     → determines MODE
    │
    ├── mode="action_pending"  → executor.handle_permission/clarification/followup/plan_choice()
    ├── mode="action"          → executor.plan_action()
    │       └── _pattern_match() → fast path
    │           └── _ai_plan()   → LLM JSON fallback
    │           └── security.assess() → SAFE/WARNING/BLOCKED/NEED_ADMIN
    │           └── _execute_pending() → actual OS call
    ├── mode="diagnostics"     → diagnostics.run()
    ├── mode="search"          → researcher.search()
    ├── mode="copilot"         → copilot.start()
    └── mode="chat/analysis/…" → brain.stream_think() → Edge-TTS stream
```

**Critical**: When the executor has a pending action (waiting for "yes/go ahead"), the dialog_manager returns `mode="action_pending"`. The response MUST be routed to the executor handlers — not to the LLM. This was a live bug that has now been patched (see §9).

---

## 5. The Follow-Up Window

After any user interaction, IRIS enters a follow-up loop (`_run_voice_followup_window`) instead of returning to the cold wake-word loop. This gives the conversation its natural back-and-forth feel.

- **Default max turns:** 8 (not 6 as previously stated)
- **Missed-listen patience:** 3 timeouts before "Still here" is spoken and the counter resets (sessions are intentionally persistent — only an explicit "terminate" or goodbye exits)
- **Double patience:** If IRIS's last response ended with "?", the missed-limit doubles (user might be thinking)
- **Barge-in:** During TTS playback, a 0.3-second interrupt window polls the mic. If real speech is detected, TTS stops and a full 9-second command window opens

---

## 6. Admin Unlock — The Real Mechanism

**The Gemini draft's passphrase `"iris initiate"` does NOT work.** The unlock is handled by `_matches_admin_unlock()` which uses pattern matching, not a single fixed phrase.

**Phrases that unlock Aletheia (any of these work):**
- `"initiate protocol"`
- `"initiate protocol aletheia"`
- `"authorize protocol"`
- `"activate protocol aletheia"`
- `"unlock aletheia"`
- `"open aletheia"`

The function also fuzzy-matches combinations of action words (`authorize/initiate/activate/unlock`) with the admin name (`aletheia` and its aliases). A token-level difflib check with cutoff 0.62 handles Whisper mishears of "aletheia".

**To revert to public IRIS mode:** say `"lock protocol"` or `"revert to iris"`.

**What changes on unlock:**
- `self_model.admin_unlocked = True`
- Voice switches to Aletheia's voice profile (`Config.ALETHEIA_VOICE_NAME`)
- Conversation memory is cleared (fresh slate for admin session)
- All `_PUBLIC_RESTRICTED_ACTIONS` in the security guard are now permitted

---

## 7. Security Architecture (Already Complete)

The security layer is **fully operational** — the Gemini brief's description of it as "incomplete" is wrong. Every executor action passes through `SecurityGuard.assess()` in `core/security.py` before any OS call is made.

### 5-Layer Pipeline

| Layer | Trigger | Action |
|---|---|---|
| **0 — Public Sandbox** | `admin_unlocked=False` AND action in `_PUBLIC_RESTRICTED_ACTIONS` | BLOCKED. Tells user to activate Aletheia. |
| **0b — Path Protection** | `admin_unlocked=False` AND target path inside `C:\Windows`, `C:\Program Files`, `%APPDATA%` etc. | BLOCKED. |
| **1 — Hard Blocks** | Command matches `BLOCKED_COMMANDS` (mimikatz, rm -rf /, format c:, fork bombs, etc.) | BLOCKED unconditionally. No override. |
| **2 — Admin Rights** | Command matches `ADMIN_REQUIRED_PATTERNS` (winget, netsh, reg add, etc.) | NEED_ADMIN — user must explicitly confirm. |
| **3 — URL Safety** | URL from shortened domain (bit.ly, tinyurl) or plain HTTP | WARNING or BLOCKED depending on severity. |
| **4 — Download Safety** | Executable extension (`.exe`, `.ps1`, etc.) from unverified source | WARNING. |
| **5 — Sensitive Ops** | firewall, antivirus, hosts file, proxy, SSL bypass patterns | WARNING — requires explicit confirmation. |

### Tool Allowlists (Already Implemented)

In `core/tools_registry.py`:

```python
# Public IRIS — safe tools only
ACTIVE_TOOL_NAMES: frozenset[str] = frozenset({
    "open_app", "search_web", "play_music", "delete_item",
    "active_window", "list_windows", "focus_window", "window_state",
    "focus_mode_start", "focus_mode_status", "focus_mode_stop",
    "background_status", "unsupported",
})

# Aletheia — all tools
ADMIN_TOOL_NAMES: frozenset[str] = frozenset(TOOLS.keys())
```

The LLM's action-planning prompt only receives schemas for the active persona's allowlist via `tool_schema_for(tool_set)`. **Task 2 from the previous brief is done.**

---

## 8. Known Live Bugs (Still Open)

These two audio-layer bugs were identified but not patched in the last session. They are the immediate priority for Openclaw.

### Bug A — The Deaf Command Window (`core/voice.py`)
`SpeechRecognition`'s `dynamic_energy_threshold` is autonomously spiking the command gate to ~375 during follow-up listening, well above the configured `COMMAND_RMS_THRESHOLD=300`. This causes the system to silently discard normal-volume speech as "too quiet."

**Fix approach:** Clamp or disable dynamic threshold scaling so the recognizer strictly honours `COMMAND_RMS_THRESHOLD` during the follow-up window. The wake loop can retain dynamic adjustment; the command window must not.

### Bug B — The Whisper Hallucination Problem (`core/voice.py`)
The 0.25-second interrupt window is dispatched to Faster-Whisper with `vad_filter=False`. On ambient silence, Whisper generates garbage transcripts (historically: "urn.com", random single words). These pass through `should_ignore_transcript()` imperfectly and occasionally trigger unintended commands.

**Fix approach:** Set `vad_filter=True` for the `wake` and `interrupt` STT dispatch paths. Keep `vad_filter=False` only for the main command window where speech is guaranteed. Keep `beam_size=1` for speed.

---

## 9. Recently Patched Bugs (This Session — April 2026)

These three bugs were diagnosed from live trace logs and patched in `main.py`. Do not re-open or revert these changes.

### Patch 1 — Wake Alias Stripping: Last Word of Commands Eaten (`_strip_wake_aliases`)
**Root cause:** The fallback difflib scan iterated over *every* token in the transcript. The word `"alpha"` scores ~0.61 against `"aletheia"` at the 0.55 cutoff, so `"rename folder X to alpha"` was silently becoming `"rename folder X to"`. The executor's rename regex could not match a command with no target name and fell back to the LLM.

**Fix:** The fallback now only checks the **first token**. Wake words appear at the start of utterances, never mid-sentence.

### Patch 2 — Whisper Mishear `"Alidiyah"` Not Stripped as Wake Word
**Root cause:** `"alidiyah"` (Whisper's confirmed mishear of `"Aletheia"`) scored only ~0.50 in difflib — just below the 0.55 cutoff — so it was never stripped. The full phrase `"Alidiyah terminated"` was sent verbatim to the LLM, which hallucinated `"The process 'Alidiyah' has been terminated."` Additionally, the residual `"terminated"` (past tense) was not in `_EXIT_KEYWORDS`, so the session failed to exit even when the user intended `"Aletheia, terminate"`.

**Fix:** `"alidiyah"` and `"alidiya"` added to `_WAKE_ALIAS_MAP["aletheia"]`. `"terminated"` added to `_EXIT_KEYWORDS` and `_exact_exit_commands()`.

### Patch 3 — `action_pending` Mode Routed to LLM Instead of Executor
**Root cause — the most critical bug.** When the executor had a pending action waiting for a yes/no confirmation, `dialog_manager.analyze()` correctly returned `mode="action_pending"`. But `handle_user_input()` had `elif` branches for `"diagnostics"`, `"action"`, `"search"`, `"copilot"` — and **nothing for `"action_pending"`**. Every confirmation word ("go", "yes", "do it") fell through to the LLM council path. The LLM invented responses instead of executing the waiting action. This is why "Go" caused Aletheia to monologue about lithium instead of completing the rename.

**Fix:** New `elif not response and decision.mode == "action_pending":` branch added before the `"action"` branch in `handle_user_input()`. It routes to `executor.handle_clarification_response()`, `handle_permission_response()`, `handle_followup_response()`, or `handle_plan_choice()` in priority order.

---

## 10. Task List for Openclaw

Tasks are ordered by impact. Do not jump ahead — the audio bugs (A and B) are the foundation for everything else.

### ✅ Already Complete (Do Not Redo)
- Schema Firewall (`ACTIVE_TOOL_NAMES` / `ADMIN_TOOL_NAMES` frozensets) — live in `tools_registry.py`
- Executor `OSError` wrapping — `_create_file` and `_create_folder` both have `except OSError` blocks
- The three main.py patches from §9

### 🔴 Priority 1 — Audio Physics Hotfix (`core/voice.py`)
Fix Bugs A and B from §8. This is the most user-facing breakage: the system is occasionally deaf and occasionally talking to itself.

Checklist:
- [ ] Clamp `dynamic_energy_threshold` in the command listen path to `Config.COMMAND_RMS_THRESHOLD`
- [ ] Set `vad_filter=True` for wake and interrupt STT calls; keep `False` for command window
- [ ] Verify `should_ignore_transcript()` rejection patterns after the VAD change

### 🟡 Priority 2 — Executor Hardening Audit (`core/executor.py`)
`_create_file` and `_create_folder` already have `OSError` guards. The following methods need an audit for bare exception paths:
- [ ] `_write_to_file` — verify it has `OSError` handling, not just bare `Exception`
- [ ] `_delete_item` — verify Recycle Bin failure is caught and reported gracefully
- [ ] `_run_command` — already has `subprocess.TimeoutExpired` and `Exception` but consider adding a check for commands that exit non-zero due to path issues

### 🟢 Priority 3 — Observation Only
- Monitor `self_model.py` — the `admin_unlocked` flag must be passed correctly to all downstream callers. A regression here would re-expose the security sandbox to Aletheia-level actions without authentication.
- The `brain.py` `_postprocess()` strip list may need updating if new LLM boilerplate patterns appear in production.

---

## 11. File Map for Quick Navigation

```
D:\IRIS-live\
├── main.py                  ← START HERE for any conversation-flow work
├── config.py                ← ALL thresholds and keys — edit nothing else for config
├── HANDOVER_OPENCLAW.md     ← this document
├── logs\
│   ├── iris_trace.log       ← full runtime trace (grep [VOICE_FLOW] and [BRAIN])
│   └── iris_actions.log     ← every executor action with verdict
├── core\
│   ├── voice.py             ← audio layer — Bug A and B live here
│   ├── brain.py             ← LLM routing and streaming
│   ├── executor.py          ← OS actions — the "hands"
│   ├── security.py          ← 5-layer gate — do not bypass
│   ├── tools_registry.py    ← tool schemas and persona allowlists
│   ├── dialog_manager.py    ← turn routing classifier
│   ├── self_model.py        ← internal state, admin_unlocked flag
│   ├── memory.py            ← session archiving and recall
│   ├── council.py           ← multi-agent deliberation
│   ├── autocorrect.py       ← Whisper mishear correction
│   ├── improv.py            ← Plan A/B/C on action failure
│   ├── copilot.py           ← step-by-step guided mode
│   ├── autonomist.py        ← post-session learning
│   ├── evolution.py         ← unknown-intent triage
│   ├── session_logger.py    ← turn-by-turn log writer
│   ├── browser.py           ← Selenium browser automation
│   └── weather.py           ← OpenWeatherMap integration
└── tools\
    └── researcher.py        ← web search (called in mode="search")
```

---

## 12. Operational Notes

- **Never hardcode thresholds** outside `config.py`. Every audio gate, VRAM cap, and API key reads from there.
- **The security layer cannot be bypassed in code.** `security.assess()` is called inside `plan_action()` before any `_execute_*` method is reached. If you need a new action type, add it to `tools_registry.py` and give it the correct `risk` level.
- **The LLM does not execute actions.** The LLM in `_ai_plan()` returns a JSON plan dict. The executor validates it, security-gates it, and then physically runs it. The LLM never calls OS APIs directly.
- **Logs are your best friend.** Filter `iris_trace.log` for `[VOICE_FLOW]` to trace conversation routing, `[BRAIN]` for LLM decisions, and `iris_actions.log` for every executed or blocked action.
- **VRAM budget:** Current usage is ~46% (~3.8 GB). The KV cache `q8_0` quantization is what keeps it there. Any model change must be validated against a VRAM headroom of at least 500 MB.

---

*Document compiled from live codebase audit, session trace logs (2026-04-11 23:28–23:29), and direct source reading. All factual claims are verified against the actual source files.*
