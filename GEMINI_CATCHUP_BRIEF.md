# IRIS Architectural Catch-Up Brief
**For:** Principal Architect (Gemini)
**From:** Claude (Cowork session, verified against live `D:\IRIS-live` codebase)
**Date:** 2026-04-06
**Codebase version:** `config.py → 5.2.5-STABLE` / `main.py banner → v5.1.2` *(version string mismatch — noted below)*

---

## 1. Phase 1 Status: Config Gate

**COMPLETE.** The Phase 1 config patch is fully in place.

All critical runtime variables are now `os.getenv()` reads in `config.py`:

| Variable | Key | Default |
|---|---|---|
| Wake energy gate | `WAKE_RMS_THRESHOLD` | 400 |
| Command energy gate | `COMMAND_RMS_THRESHOLD` | 300 |
| TTS output sample rate | `TTS_OUTPUT_SAMPLE_RATE` | 48000 |
| TTS engine | `TTS_ENGINE` | `auto` |
| Voice name/rate | `VOICE_NAME`, `VOICE_RATE` | `en-GB-SoniaNeural`, `+8%` |
| Whisper model/device/compute | `LOCAL_WHISPER_MODEL`, `LOCAL_WHISPER_DEVICE`, `LOCAL_WHISPER_COMPUTE_TYPE` | `small.en`, `cuda`, `float16` |
| Local GGUF model path | `LOCAL_MODEL_PATH` | — |
| Piper exe/model paths | `PIPER_EXE_PATH`, `PIPER_MODEL_PATH` | — |
| STT routing | `WAKE_STT_PRIORITY` | `local_first` |

`.env.example` is populated and committed. Live `.env` is active with all keys filled.

**One discrepancy to flag:** `config.py` declares `VERSION = "5.2.5-STABLE"` but `main.py` still has the banner string `IRIS Main Entry Point v5.1.2 (Ironclad Edition)`. The runtime behaviour reflects 5.2.5 — the `main.py` header is stale copy, not a functional regression.

**OpenClaw / OpenRouter status:** No trace of OpenClaw or OpenRouter integration exists anywhere in `config.py`, `core/brain.py`, or `main.py`. Either this was planned and not yet applied to the active worktree, or it was scoped to a different branch. `brain.py` routes to: Groq (primary), Gemini, Claude, Perplexity, Ollama (fast/smart), and llama_cpp (local GGUF). There is no OpenRouter gateway layer present.

---

## 2. The Response-Duplication Bug

**RESOLVED.** The `"What's the task? Yes. What's the task?"` loop was a compound failure across three layers — here is exactly what was patched and where:

### Root cause
The LLM was occasionally emitting boilerplate openers (`"What's the task?"`, `"Execution confirmed"`, `"Protocol initiation confirmed"`) as full responses. The TTS pipeline was also receiving these as valid speech chunks and speaking them before `_postprocess` could filter them. In the follow-up loop, fragment transcripts (`"you…"`, `"ok"`) were being passed to the brain, which then regenerated another stub reply, creating the loop.

### Fixes applied

**`core/brain.py` — `_postprocess()`**
Regex scrubber added post-generation. Strips:
- `"As an AI"`, `"Certainly,"`, `"Sure,"`, `"Of course,"`, `"Absolutely,"`, `"Great!"` openers
- Entries in `_GENERIC_ASSISTANT_BOILERPLATE` tuple (`"Hello! How can I assist you today?"`, `"Please let me know your task..."`)
- Full pattern matches for `"Protocol initiation confirmed"` → replaced with one specific clarification ask
- Full pattern matches for `"Execution confirmed"` → same
- Trailing `"What's the task?"` / `"What do you want to do?"` sentences stripped by regex

**`core/brain.py` — voice_rules in `_generation_settings()`**
Explicit instruction injected into every voice-mode system prompt:
> *"Do not roleplay system-status replies like 'protocol initiated', 'execution confirmed', or similar command acknowledgements unless a real system action actually happened."*

**`main.py` — `_is_substantive_voice_input()`**
Fragment filter added at line 372. Before any transcript reaches the brain, it is screened against:
- `_NON_SUBSTANTIVE_SINGLE_WORDS` set (`"you"`, `"ok"`, `"um"`, `"yeah"`, etc.)
- `_NON_SUBSTANTIVE_PHRASES` set
- Trailing weak-word patterns
Fragments that fail return `False` → the follow-up loop logs `followup_fragment_ignored` and continues listening without dispatching to the LLM. This breaks the loop.

**`main.py` — wake loop `wake_duplicate_ignored` guard**
Added a secondary guard in the wake loop to catch duplicate wake detections during the same active speech window.

**`main.py` — barge-in sequencing**
`voice.stop_speaking()` now fires **before** the substantive-input filter in the follow-up loop (line 786 before line 788). Prior to this fix, IRIS would not stop speaking until after the fragment had been validated as substantive — meaning she kept talking through the user's opening words.

---

## 3. Architectural Fixes Applied

### Audio Pipeline — COMPLETE

| Subsystem | Status | Detail |
|---|---|---|
| Persistent Edge-TTS event loop | ✅ Done | `_EdgeTTSEventLoop` — single `ProactorEventLoop` (Windows IOCP) eliminates ~300ms per-call TLS handshake overhead |
| Static audio cache | ✅ Done | Pre-generated MP3 files for all 30+ known short phrases (wake acks, farewells, greetings). Zero network latency on replay |
| Concurrent priming | ✅ Done | `asyncio.gather` + `Semaphore(5)` primes all static phrases in ~3-5s at boot instead of ~21s sequential |
| Lookahead TTS prefetch | ✅ Done | While chunk N plays, chunk N+1 generates in background |
| First-flush threshold | ✅ Done | First TTS chunk fires on first complete sentence or 95 chars (was 200 chars / 3 sentences) |
| Subsequent-flush threshold | ✅ Done | 2 sentences or 220 chars for Edge-TTS |
| Persistent mic stream | ✅ Done | `_get_mic_source()` keeps PyAudio stream open permanently — prevents Windows taskbar mic indicator flash and IRIS going deaf between `listen()` calls |
| Interrupt capture speed | ✅ Done (session) | `phrase_type="interrupt"` path: greedy Whisper `beam_size=1`, no VAD, 0.45s capture window → ~150ms transcription vs ~400ms |

### Memory Sanitization — COMPLETE

| Change | Status |
|---|---|
| Session fresh-start on boot | ✅ Done — `memory.archive_session()` then `memory.conversation.clear()` + `_save()` at main() startup |
| Long-term session archive | ✅ Done — `archive_session()` writes to `iris_memory_sessions_archive.json` (last 20 sessions, 30 turns each) |
| Recall injection | ✅ Done — `_is_recall_query()` + `_build_recall_context()` in `main.py` inject session archive into council packet's `extra_system` when user uses recall keywords |
| Archive file | Live — 2 sessions already logged in `iris_memory_sessions_archive.json` |

### STT Accuracy — COMPLETE (session)

The `initial_prompt` for Whisper in command mode was set to:
```
"iris aletheia alithia initiate protocol authorize protocol terminate exit quit goodbye stop"
```
This was actively pulling everyday conversational phrases toward wake/admin vocabulary. Removed for `command` and `interrupt` types. Now:
- **Wake**: `beam_size=3`, `best_of=3`, `vad_filter=False`, prompt = minimal wake keywords
- **Interrupt**: `beam_size=1`, `best_of=1`, `vad_filter=False`, `prompt=""` — greedy, unbiased, fastest
- **Command**: `beam_size=5`, `best_of=1`, `vad_filter=False`, `prompt=""` — accurate, no keyword bias, no double-VAD

`vad_filter=False` for all types: the SpeechRecognition energy-based VAD already confirmed speech is present before Whisper sees the audio. Running Silero VAD as a second pass was clipping real speech on short clips.

### Persona Overhaul — COMPLETE

Both `config.py` (`IRIS_PERSONA`) and `core/brain.py` (`_DEFAULT_IRIS_PERSONA`) aligned to the structured trait model:
- **Primary**: curiosity, judgment, prudence, honesty, kindness, perspective
- **Personality colour**: dry humor, controlled playfulness, creativity, zest
- **Stability**: self-regulation, temperance, humility, perseverance
- **Ethical baseline**: fairness, justice, appreciation, forgiveness

`_get_persona()` uses the config version when `"deflect"` is present in the string (guard check at line 322), otherwise falls back to the `_DEFAULT_IRIS_PERSONA` which is identical in structure.

### NOT YET APPLIED

| Phase | Status | Notes |
|---|---|---|
| RBAC Schema Firewall | ❌ Not started | `phase6_executor_hardening_test.py` exists as a test scaffold but no firewall logic is present in `core/executor.py` |
| Executor Hardening | ❌ Not started | `ActionExecutor.plan_action()` exists but no risk-level gating, no schema validation layer |
| Proactivity Engine | ❌ Not started | `IRIS_COGNITIVE_ROADMAP.md` defines Phase 4 but no implementation |
| Goal/Preference Memory split | ❌ Not started | Only conversation + session archive memory exists; no `user_preferences.json` or `active_goals.json` |
| Reasoning Summary Layer | ❌ Not started | Defined in roadmap Phase 5 |

---

## 4. Branch Status

**Cannot fully determine from this session.** The `.git` file (not directory) confirms this is a git worktree reference, not a detached clone. However `git log` returns nothing accessible from this mount.

What can be confirmed from the filesystem:
- Active path: `D:\IRIS-live` (the previously identified active worktree — `codex/voice-startup-hardening` branch)
- The `D:\IRIS` stale path is not accessible or present in this mount — it has not caused any interference in this session
- `OLD_FILES/` directory exists in root — suggests previous manual cleanup was done
- No evidence of a `main` branch merge PR beyond `reviews/PR_18_ready_for_review.md`, which contains only a placeholder (`"The pull request is now ready for review. Please provide your feedback."`) — no actual merge confirmation

**Assumption:** The active worktree has not been merged to `main`. `D:\IRIS` stale path has been abandoned but likely not formally deleted.

---

## 5. Current State & New Blockers

### Confirmed working
- Boot sequence: static TTS cache primed, greeting pre-generated in parallel with STT warmup, greeting TTS audio lands in static cache before playback
- Wake detection: `local_first` → Whisper `small.en` on CUDA/float16
- Follow-up conversation loop: 6 context turns, TOPIC CONTINUITY rule active
- Barge-in: stop fires before fragment filter, any non-echo speech stops IRIS
- Session memory: fresh on boot, recallable on keyword
- Persistent mic: Windows taskbar indicator stable across session

### Active version mismatch
`config.py VERSION = "5.2.5-STABLE"` vs `main.py` banner `v5.1.2`. Not functional, but should be corrected.

### Next blockers to address (priority order)

1. **Executor Hardening / Phase 6** — `phase6_executor_hardening_test.py` test scaffold exists but the actual `ActionExecutor` has no risk-level validation, RBAC schema firewall, or safe-action gate. Any voice command routed to `decision.mode == "action"` goes straight to `executor.plan_action()` with no intermediate safety check. This is the highest-risk gap in the current runtime.

2. **OpenClaw / OpenRouter integration** — If this was planned during your previous Gemini session, it has not been applied to the active worktree. Need to either apply the integration or confirm it was scoped to a different branch that needs merging.

3. **Command STT latency regression check** — Setting `vad_filter=False` for command type improves accuracy on short clips but may increase false positives on very noisy environments. Recommend a live trace session with `VOICE_DEBUG_TRANSCRIPTS=true` to confirm transcription quality after the bias-removal patch.

4. **Formal `main` merge + `D:\IRIS` cleanup** — The split-reality risk still technically exists until the `codex/voice-startup-hardening` branch is merged and the stale `D:\IRIS` directory is deleted. All current work is in the active worktree but an accidental `cd D:\IRIS` + run would launch the old stale runtime.

5. **Version string sync** — Update `main.py` header banner to `v5.2.5` to match `config.py`.
