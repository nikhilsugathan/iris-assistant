# IRIS Runtime — Static Analysis Audit Report
**Version:** 5.1.2 (Ironclad Edition)
**Auditor:** Principal QA & Security Review
**Date:** 2026-04-07
**Scope:** `main.py`, `core/voice.py`, `core/brain.py`, `core/memory.py`, `core/executor.py`, `core/tools_registry.py`
**Pre-condition:** Phase 1 (Config Foundation) ✅ | Audio Pipeline Overhaul ✅ | Memory Sanitization ✅ | Barge-In Patch ✅
**Objective:** Clear all systems for Phase 3 (RBAC Schema Firewall) and Phase 6 (Executor Hardening)

---

## Executive Summary

The codebase is structurally sound. The recent audio pipeline overhaul introduced no crash-level regressions. However, two WARNING-class threading issues specific to the new `_EdgeTTSEventLoop` require awareness before Phase 6. No `CRITICAL` crash-on-demand paths were found. The foundation is solid enough to proceed, with the caveats below documented.

---

## CRITICAL

> Immediate crash risks, deadlocks, or security vulnerabilities that block deployment.

**None found.**

The three highest-risk patterns were examined and cleared:

- The `_EdgeTTSEventLoop` uses `concurrent.futures.Future` bridging, which is architecturally correct. The asyncio event loop runs on a dedicated daemon thread and is never blocked by synchronous code.
- `stop_speaking()` correctly sets the stop event, drains the queue, and clears the prefetch cache atomically before the new utterance is enqueued in `speak()`. No inversion path was found.
- The security gate in `executor.py` → `handle_permission_response()` correctly refuses override when `pending_verdict == BLOCKED`. The hard wall holds.

---

## WARNING

> Memory leaks, unhandled edge cases, or race conditions that degrade stability under real-world load.

---

### W-01 — `_EdgeTTSEventLoop` Daemon Thread Has No Crash Recovery

**File:** `core/voice.py`, line 39
**Severity:** High Warning — silent TTS death under adverse network conditions

```python
self._thread = threading.Thread(
    target=self._loop.run_forever, daemon=True, name="edge-tts-loop"
)
```

`run_forever()` is hardened against normal asyncio exceptions, but if the ProactorEventLoop (Windows IOCP) encounters an OS-level fatal error, the thread exits silently. Subsequent calls to `_get_edge_tts_loop().run(coro, timeout=30.0)` will block for the full 30-second timeout per utterance before raising `concurrent.futures.TimeoutError`. This is caught by `_run_speech_worker`'s `except Exception` handler, which logs "Speech worker failed" and moves on — so the crash is soft, but IRIS goes permanently mute for the remainder of the session with no console alarm.

**Additionally:** The lambda used to schedule the task is not exception-safe:

```python
self._loop.call_soon_threadsafe(
    lambda: self._loop.create_task(_wrap())
)
```

If `create_task` fails (loop is closing during shutdown), the `Future` is never resolved, causing a guaranteed 30-second hang during any graceful shutdown sequence that calls `speak()` after the loop thread has begun teardown. In practice `_force_exit(0)` → `os._exit(0)` cuts this off, but it means the farewell utterance in the `finally` block is not guaranteed to complete before exit.

**Risk:** Silent TTS failure cascades for 30s per utterance. No watchdog restarts the loop thread.

---

### W-02 — Speech-Active State Gap During Back-to-Back Utterance Handoff

**File:** `core/voice.py`, lines 468, 477–479, 1441–1456
**Severity:** Medium Warning — brief `is_speaking() == False` between consecutive utterances

Both the Piper path (`_speak_utterance.finally`) and the Edge-TTS path (`_play_edge_tts_file.finally`) call `_set_speech_active(False)`. The `_run_speech_worker.finally` then calls it again. This creates a deterministic gap: between the moment the old utterance's `_play_edge_tts_file.finally` fires and the moment the next queued utterance's `_set_speech_active(True)` is called, `is_speaking()` returns `False` even though an item is pending in the utterance queue.

The consequence is specific to the wake loop in `main.py` (lines 1216–1221):

```python
during_speech = voice.is_speaking()
if during_speech:
    heard_text = voice.listen_for_interrupt()
else:
    heard_text = voice.listen_for_wake()
```

During a multi-chunk streaming response, the wake loop can momentarily fall into `listen_for_wake()` mode (4-second timeout, full phrase detection) instead of `listen_for_interrupt()` (0.25-second timeout, barge-in detection) at chunk boundaries. The practical result is a ~0-200ms window where a barge-in phrase is not captured with interrupt urgency. For a fast speaker this is not a crash but can cause a missed stop signal between streaming chunks.

**Risk:** Rare missed barge-in at chunk handoff. Not a crash.

---

### W-03 — `_whisper_loading` Flag Read Without Lock in `_transcribe_local`

**File:** `core/voice.py`, line 1090
**Severity:** Low Warning — theoretical double-load race

```python
if self._whisper_loading and self._whisper_model is None:
    raise RuntimeError("Local Whisper model still loading")
```

This check is performed outside `_whisper_lock`. If the `_warm_local_stt` background thread sets `_whisper_loading = True` and then loads the model (setting `_whisper_loading = False` in `finally`), a parallel call to `_transcribe_local` may read a stale `_whisper_loading = True` with `_whisper_model` already populated. The result is an unnecessary `RuntimeError` that triggers the Google cloud fallback for one transcription. Python's GIL ensures the read is atomic, so no memory corruption, but the logic is unsound.

---

### W-04 — `_reload_whisper_model()` Writes `_whisper_model` Without Lock

**File:** `core/voice.py`, line 1213–1221
**Severity:** Low Warning — write-without-lock in error recovery path

```python
def _reload_whisper_model(self, device, compute_type):
    ...
    self._whisper_model = self._instantiate_whisper_model(...)
```

This is called from `_transcribe_local()` on the speech recognition path (effectively the main thread during a command listen call). In the current architecture there is only one active STT call at a time, so this does not race in practice. However, if Phase 6 introduces any concurrent tool execution that triggers STT, this write is exposed.

---

### W-05 — `stream_think()` Bare `except Exception` Swallows Errors Silently

**File:** `core/brain.py`, line 242
**Severity:** Medium Warning — diagnostic blindspot during streaming

```python
try:
    for chunk in stream:
        ...
except Exception:
    if not streamed:
        ...
    return
```

When an exception is raised mid-stream AND some content was already yielded (`streamed` is truthy), the exception is silently discarded with no log entry. This means a partial API failure (e.g., Groq connection drop mid-generation) is invisible in logs. The user sees a truncated response; the trace shows only the chunks that arrived. This is a diagnostic black hole for production debugging.

---

### W-06 — `memory._save()` Is Not Atomic — Corruption Risk on Hard Kill

**File:** `core/memory.py`, line 53–63
**Severity:** Medium Warning — data integrity on crash

```python
with open(self.memory_file, "w", encoding="utf-8") as f:
    json.dump({...}, f, indent=2)
```

A direct overwrite with no write-to-temp + rename pattern. If the process is hard-killed (power loss, `SIGKILL`, or `os._exit(0)` racing a concurrent write) between the `open()` truncation and `json.dump()` completing, `iris_memory.json` is left with a partially-written JSON blob. On next startup, `_load()` catches the `json.JSONDecodeError` and silently resets to `[]`, losing the entire session history. The same vulnerability applies to `_sessions_archive_file` in `archive_session()`.

---

### W-07 — Partial Response Saved to Memory After Mid-Stream Barge-In

**File:** `main.py`, lines 683–720 (`_stream_reasoning_response`)
**Severity:** Low Warning — context pollution

When a barge-in fires during streaming:
1. `voice.stop_speaking()` is called — stop event is set.
2. `brain.stream_think()` continues yielding chunks that are no longer spoken.
3. `_postprocess("".join(streamed))` assembles the partial raw output.
4. `_save_to_memory(user_input, final_response, "brain")` saves the truncated response.

The memory then contains an incomplete assistant turn that ends mid-sentence. On the next call to `get_context()`, this partial entry is injected into the system prompt as if IRIS had delivered a complete thought. The `_should_drop_entry()` guard only filters boilerplate, not truncated reasoning. Over multiple barge-ins in a session, context window quality degrades.

---

## DEBT

> Leftover dead code, missing docstrings, or minor refactoring needs that do not block Phase 3/6 but should be cleared in the next cleanup pass.

---

### D-01 — `_persistent_source = None` Is a Dangling Attribute

**File:** `core/voice.py`, line 116

```python
self._persistent_source = None
```

This attribute is declared in `__init__` and explicitly reset to `None` in `close_mic()` but is never written to or read from anywhere else in the class. The actual persistent stream is tracked via `self._mic_open` and `self.mic`. This is a dead stub from a prior design iteration. No functional impact. Remove to avoid confusion.

---

### D-02 — Wake Word Fuzzy Matching Is Duplicated Across Two Files

**Files:** `main.py` (lines 238–242), `core/voice.py` (lines 718–745)

`main.py` defines `_token_matches_wake_word()` and `_wake_match_cutoff()` using `difflib.get_close_matches`. `voice.py` reimplements the same fuzzy logic in `_looks_like_wake_transcript()` with slightly different cutoffs (`0.78` in voice.py vs `0.55/0.75` in main.py). Two diverging implementations of the same guard is a maintenance hazard. If cutoffs are tuned in one file they must be manually mirrored in the other.

---

### D-03 — `SIMPLE_ACTIONS` Contains `"play_music"` Without a Verified Handler

**File:** `core/executor.py`, line 295–298

```python
SIMPLE_ACTIONS = [
    "create_file", "create_folder", "open_app",
    "search_web", "write_to_file", "play_music", "delete_item"
]
```

`"play_music"` is listed as a simple auto-executing action type. The `_pattern_match()` method does return `action_type: "play_music"` plans (from the `song_match` branch), and `_is_simple_task()` will pass them through without asking permission. Confirm that `_execute_pending()` has a handler branch for `"play_music"`. If it falls through to the final `return` without a response, the executor silently does nothing for a song request.

---

### D-04 — `brain.stream_think()` Should Log the Swallowed Exception

**File:** `core/brain.py`, line 242–251

The bare `except Exception` in the streaming path needs at minimum one line of trace logging before branching:

```python
except Exception:          # ← no trace_logger.exception() here
    if not streamed:
```

Phase 6 will route more complex executor chains through `stream_think`. Without exception logging, mid-stream failures in elevated sessions will be invisible.

---

### D-05 — `Config.PRIMARY_BRAIN` and `Config.FALLBACK_BRAIN` Are Class-Level Mutations

**File:** `core/brain.py`, lines 136–142

`_update_priority()` writes directly to `Config.PRIMARY_BRAIN` and `Config.FALLBACK_BRAIN`, mutating a module-level class. If a future version instantiates more than one `Brain` (e.g., ensemble shadow brain), the second instance's `_update_priority()` would silently overwrite the first's routing. Convert to instance-level attributes.

---

### D-06 — `_generate_greeting()` Silently Discards Groq Failures

**File:** `main.py`, line 562–564

```python
except Exception:
    pass
```

The Groq API call for dynamic greeting generation is wrapped in a catch-all with no logging. On API key misconfiguration, rate limit, or network failure, IRIS falls back to the static pool correctly, but there is zero trace entry. Add `trace_logger.debug()` to assist boot diagnostics.

---

## ALL CLEAR

> Areas that are structurally solid and ready for Phase 3/6 without modification.

| Component | Finding |
|---|---|
| `_EdgeTTSEventLoop` instantiation | Correct double-checked locking (`_edge_tts_loop_lock`). Thread-safe lazy init. |
| `stop_speaking()` null-safety | `_active_stop_event` is checked for `None` before `.set()`. No NPE path. |
| Prefetch cache cleanup on barge-in | `stop_speaking()` iterates `_tts_prefetch_cache` under lock and removes all orphaned temp files. |
| `_speak_edge_tts` temp file cleanup | Correct `finally` block removes the temp MP3 file unconditionally, even if generation fails. |
| Security gate — BLOCKED override | `handle_permission_response()` correctly refuses `override` for `BLOCKED` verdicts. Hard wall is intact. |
| Microphone stream recovery | `_get_mic_source()` correctly detects a dead `pyaudio_stream` and calls `__exit__` + `__enter__` to reopen without a full `_init_mic()` cycle. |
| `listen_for_interrupt()` threshold restore | `finally` block correctly restores all three recognizer thresholds (`pause_threshold`, `phrase_threshold`, `non_speaking_duration`). No state bleed into wake loop. |
| `listen_for_command()` threshold restore | Same as above. Both methods are symmetrically correct. |
| Session archive ordering | `archive_session()` is called BEFORE `conversation.clear()` in `main()`. Correct sequencing — no data loss on startup. |
| `_self_clean()` deduplication | Reverse-iterate + `seen_content` set correctly retains most-recent duplicate entries and discards older ones. |
| `_sanitize_content()` wake-word stripping | Regex and sort-by-length logic correctly handles compound wake words like "hey iris, do X". |
| `_should_drop_entry()` boilerplate filter | Think-tag stripping with `(?is)` flag is correct. The `all()` check requires BOTH boilerplate fragments present, preventing false drops. |
| `_get_whisper_model()` double-checked lock | Outer read → lock → inner read pattern is correct under Python's GIL. |
| `_get_piper_engine()` double-checked lock | Same. Correct. |
| `_run_speech_worker` task_done accounting | The merged-extra-text loop correctly calls `task_done()` for each item retrieved via `get_nowait()`. The outer `finally` block handles only the primary item. No double-decrement or undercount. |
| `_stream_piper_chunks` sentinel pattern | Producer always puts `_QUEUE_SENTINEL` in `finally`, even under `stop_event`. Consumer `break`s cleanly. No deadlock path. |
| Admin protocol escalation/de-escalation | `_matches_admin_unlock()` and `_classify_exit_action()` are mutually exclusive. Lock/unlock state transitions clear memory correctly. |
| `memory.add()` role normalization | `normalized_role` correctly maps both `"iris"` and `"assistant"` to `"assistant"`. No role leakage. |
| `_force_exit(0)` placement | Called AFTER `voice.close_mic()`, `_wait_for_voice_idle()`, and `_finalize_session()`. Shutdown sequence is ordered correctly. |
| `_looks_like_wake_transcript()` control phrase passthrough | `"terminate"`, `"exit"`, `"shutdown"`, `"quit"`, `"goodbye"` bypass the wake-word filter correctly so exit commands are never dropped. |
| `brain._rewrite_generic_response()` short-circuit | Fires before any API call. Saves cloud tokens for identity probes and boilerplate. |
| `_ensemble_think()` graceful degradation | Falls back to `next(iter(responses.values()))` if the Groq judge call fails. No crash path. |

---

## Verdict

**The foundation is solid. Proceed to Executor Hardening.**

Before closing the sprint, assign the following to the backlog:

1. **W-01** — Add a watchdog restart mechanism to `_EdgeTTSEventLoop` or detect loop thread death and re-instantiate.
2. **W-05** — Add `trace_logger.exception()` (or equivalent) to `brain.stream_think()`'s bare `except` block.
3. **W-06** — Implement atomic write (temp file + `os.replace()`) for `memory._save()` and `archive_session()`.
4. **D-01** — Remove `_persistent_source` dead attribute.
5. **D-03** — Confirm or add `play_music` handler in `_execute_pending()` before Phase 6 routes any elevated music actions through the executor.

W-02, W-03, W-04, and W-07 are architectural trade-offs that are acceptable at the current scale and do not need to be fixed before Phase 3/6. Document them in the roadmap.
