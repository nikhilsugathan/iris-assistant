# ARCHITECTURE_PIVOT_PROPOSAL.md
## IRIS v5.2.5 — Rate Limit Resiliency & Routing Overhaul

**Role:** Principal Systems Architect  
**Budget Constraint:** $0.00  
**Status:** Analysis complete. Awaiting approval before code changes.

---

## 1. Diagnostic: The Exact Failure Cascade

Before proposing solutions, here is the precise failure chain observed in the codebase, traced end-to-end.

### 1a. The Routing Table (Current State)

`_get_apis_for_query()` in `brain.py:717` hardcodes the waterfall:

| Query Type | Order |
|---|---|
| `general` | `groq → gemini → claude → llama_cpp → ollama_smart → ollama_fast` |
| `code` | `groq → llama_cpp → claude → ollama_smart → ollama_fast` |
| `web_search` | `groq → gemini → perplexity` |

**Critical observation:** For `code` queries, **Gemini is completely absent**. One Groq 429 drops straight to the 47-second local engine with zero cloud intermediary.

### 1b. The 429 Invisibility Problem

`_call_api()` at `brain.py:426` wraps every provider call in a bare `except Exception: return None`. HTTP 429 is treated identically to a DNS failure, a timeout, or a model overload. IRIS has no visibility into *why* an API failed. She cannot distinguish "rate limited, try again in 30s" from "wrong API key."

This means:
- IRIS will retry the same 429-ing provider on every single request until the rate window resets.
- The cascade does not pause or back off. Every query hammers Groq, gets 429, hammers Gemini, gets 429, drops to llama_cpp.

### 1c. The llama_cpp Non-Cancellable Blocking Call

`_call_ollama("llama_cpp", ...)` at `brain.py:665` calls:

```python
response = self.llm.create_chat_completion(
    messages=messages,
    max_tokens=settings.get("max_tokens", 1024),
    ...
)
```

This is a **fully synchronous, blocking call**. The `_generation_cancel` event (set by barge-in at `voice.py:500`) is an `asyncio`-style threading event — but `create_chat_completion` never checks it. The barge-in fires, the event is set, and then **absolutely nothing happens for 47 seconds** while the model grinds through 16K context.

### 1d. The N_CTX Amplifier

`N_CTX=16384` was a net positive when the primary path is Groq (milliseconds). When the primary path is llama_cpp, it means:
- More KV-cache VRAM allocated on load
- More tokens potentially attended to per generation
- Longer thermal ramp on RTX 5050 Mobile

At 16K context with Qwen3-8B Q4_K_M, token generation time scales nonlinearly. The 47s figure is consistent with this.

### 1e. The BRAIN_PRIORITY Dead Variable

`Config.BRAIN_PRIORITY = ["llama_cpp", "groq", "ollama_smart", "claude", "gemini"]` (config.py:96) appears to declare routing priority. It does not. `_update_priority()` uses it only to set the `Config.PRIMARY_BRAIN` display string. The actual routing is entirely governed by the hardcoded lists in `_get_apis_for_query()`. This is a **silent config lie** that should be corrected in the implementation.

---

## 2. Proposal 1 — The Pre-Classifier (Local-First for Chatter)

### Problem
Every utterance — including "yes", "ok", "thanks", "go ahead", "keep going", "sure", and similar one-to-three word social responses — hits `_classify_query` → `_get_apis_for_query` → Groq. This burns API quota on inputs that need zero intelligence to answer.

### What Already Exists (Don't Reinvent)
`_rewrite_generic_response()` at `brain.py:928` is the embryonic pre-classifier. It currently intercepts:
- Time queries → local clock
- Date queries → local clock
- Three "focus" phrases → fixed advice string

This is the correct pattern. The proposal is to expand it substantially.

### Proposed Expansion: Two-Tier Local Interception

**Tier 1 — Zero-latency exact/fuzzy match (extend `_rewrite_generic_response`)**

Add a local vocabulary table of high-frequency conversational inputs with fixed responses that require no model:

| Input pattern | Local response |
|---|---|
| `yes / yeah / yep / sure / correct / exactly` | `"Got it. Keep going."` |
| `no / nope / not really / incorrect` | `"Understood. What's the right direction?"` |
| `ok / okay / alright / fine` | `"Noted."` |
| `thanks / thank you / cheers` | `"Any time."` |
| `stop / wait / hold on` | (already handled as interrupt in main.py) |
| `what? / pardon? / say that again` | `"I said: [last_spoken]"` (from `_recent_spoken`) |
| 1-2 word fragments with no verb | Ask clarification, no API call |

Implementation: `difflib.get_close_matches` against a vocabulary set, or a simple normalized-string `frozenset` lookup. Runtime: <0.1ms. No imports. No VRAM.

**Tier 2 — Intent classification without a cloud call**

For ambiguous inputs (3-8 words), classify intent using the existing `_classify_query` keyword patterns *before* routing. If the query matches neither web nor code patterns AND is fewer than 15 words AND contains no proper nouns, entities, or temporal references — route directly to llama_cpp with `max_tokens=60`. This preserves Groq quota for complex reasoning, code, and multi-step tasks.

This is NOT a new model. It is a routing gate using the existing classification infrastructure.

**Projected quota savings:** Tier 1 alone eliminates approximately 30-40% of API calls in a normal voice session (acknowledgments, continuations, and social chatter). The free-tier RPM window that currently depletes in 2-3 minutes of conversation would extend significantly.

---

## 3. Proposal 2 — The Token Bucket Rate Limiter

### Problem
IRIS proactively sends requests to APIs that are already rate-limited. The 429 is guaranteed on each request until the window resets, but IRIS discovers this only by paying the full HTTP round-trip latency (~300-700ms) before getting the error.

### Proposed Design: Sliding Window Counter (Thread-Safe, Zero Dependencies)

A `collections.deque`-based sliding window counter, stored as a class-level attribute on `Brain`. No external libraries. No persistence required.

```
Architecture:

Brain._api_call_log: dict[str, deque[float]]
    "groq"   → deque of UTC timestamps of recent calls
    "gemini" → deque of UTC timestamps of recent calls
    "claude" → deque of UTC timestamps of recent calls

Brain._api_lock: threading.Lock  (shared across all API deques)
```

**Logic (to insert before `_call_api_with_settings`):**

```
def _api_allowed(self, api: str, rpm_limit: int, window_sec: int = 60) -> bool:
    now = time.monotonic()
    with self._api_lock:
        q = self._api_call_log.setdefault(api, deque())
        # Evict timestamps older than the window
        while q and now - q[0] > window_sec:
            q.popleft()
        if len(q) >= rpm_limit:
            return False   # proactive divert — no HTTP call
        q.append(now)
        return True
```

**RPM Limits (Free Tier, April 2026):**

| Provider | Model | Free RPM | Proposed limit |
|---|---|---|---|
| Groq | llama-4-scout-17b-16e-instruct | 30 RPM | 25 (5 headroom) |
| Groq | whisper-large-v3-turbo (STT) | 20 RPM | 18 |
| Gemini | gemini-2.5-flash | 15 RPM | 12 |
| Gemini | gemini-2.0-flash | 15 RPM | 12 |

Note: Set the internal limit 15-20% below the actual API limit. This creates a safety margin for any requests made outside IRIS (browser, scripts) using the same key.

**Integration point:** Insert `_api_allowed(api, rpm)` check inside `_smart_route` before the `_call_api_with_settings` call. If not allowed, skip the API and log a trace event (`[BRAIN] api_proactive_skip api=groq reason=rate_limit_window`). The cascade moves immediately to the next provider without the HTTP round-trip penalty.

**Secondary benefit:** The rate limiter log provides real-time visibility into quota consumption. A `get_rate_status()` method can feed the status panel with per-API remaining headroom.

---

## 4. Proposal 3 — Alternative Free-Tier Providers

### Problem
The current cascade has no middle tier between Gemini and the 47-second local engine. Claude is listed but is a paid-tier endpoint. The effective free-tier waterfall for `general` queries collapses after two 429s.

### Candidate Analysis

**Tier A — Recommended (OpenRouter)**

- **Endpoint:** `https://openrouter.ai/api/v1/chat/completions`
- **Auth:** Bearer token, identical to OpenAI API format
- **Free models (as of April 2026):** `meta-llama/llama-3.1-8b-instruct:free`, `mistralai/mistral-7b-instruct:free`, `microsoft/phi-3-mini-128k-instruct:free`, `qwen/qwen-2.5-7b-instruct:free`
- **RPM on free models:** Typically 20 RPM per model, no hard dollar cost
- **Implementation cost:** A `_call_openrouter()` method that is structurally identical to `_call_groq()` with a different base URL and model string
- **Verdict:** **Highest priority addition.** OpenAI-compatible, multiple free model choices, independent rate limit pool from Groq and Gemini

**Tier B — Recommended (Together AI)**

- **Endpoint:** `https://api.together.xyz/v1/chat/completions`
- **Auth:** Bearer token, OpenAI-compatible
- **Free tier:** $25 credit on signup; Llama-3.1-8B at ~$0.0002/1K tokens — negligibly cheap for voice use (typically <500 tokens per exchange)
- **Models:** `meta-llama/Llama-3.1-8B-Instruct-Turbo`, `mistralai/Mistral-7B-Instruct-v0.3`
- **Verdict:** **Second priority.** Technically paid but effectively free for light use. Excellent throughput and low latency (~400ms for 8B models)

**Tier C — Do Not Add (Cohere)**

- Free tier is 5 RPM, small context window (4K), requires explicit trial activation
- Not suitable as a real-time voice fallback

**Proposed New Cascade:**

```
For 'general':
    groq → openrouter (free) → gemini → together_ai → llama_cpp

For 'code':
    groq → openrouter (free) → gemini → llama_cpp → claude

For 'web_search':
    groq → gemini → openrouter (with search-capable model) → perplexity
```

**Implementation:** `_call_openrouter()` and `_call_together()` are ~15 lines each. They reuse `_build_msgs()` and `_get_persona()`. New config keys: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `TOGETHER_API_KEY`, `TOGETHER_MODEL`. Both new providers get their own rate-limiter slots.

### N_CTX Adaptive Reduction for Local Fallback

This is architecturally related. When `llama_cpp` is selected as a fallback (not primary), the context window should dynamically shrink:

- **Normal primary path (Groq):** N_CTX = 16384 (irrelevant — Groq does not use local context)
- **Local fallback path:** Initialize or reinitialize llama.cpp with N_CTX = 4096 for fallback calls

**Mechanism:** A dedicated `_call_ollama_fallback()` method that uses a separately-loaded or reconfigured llama.cpp instance with 4K context. At 4K context, the 47s generation time drops to approximately 8-12s on RTX 5050 Mobile — still slow, but no longer a catastrophic failure.

**Alternative (simpler):** Add a `max_tokens` cap specifically for fallback calls. Since voice mode already limits to 150 tokens, cap fallback llama_cpp calls at `max_tokens=80`. Shorter target output = faster completion regardless of N_CTX.

---

## 5. Proposal 4 — Aggressive Barge-In Tuning

### Problem
Background noise (keyboard typing, HVAC, fan) at ~400-600 RMS is cancelling llama_cpp generations during the 47-second fallback window. The barge-in triggers on a single 32ms audio frame exceeding the 550 RMS gate.

### Exact Variables to Change

**Variable 1: `BARGE_IN_RMS_THRESHOLD` (new config key, `.env`)**

Currently the barge-in gate is hardcoded in `start_barge_in_monitor` as:
```python
threshold = max(550.0, float(Config.WAKE_RMS_THRESHOLD) * 1.1)
```
With `WAKE_RMS_THRESHOLD=360`: `max(550, 396) = 550`.

Keyboard typing produces brief spikes of 400-700 RMS. The 550 gate sits squarely in the middle of keyboard noise territory.

**Proposed:** Add `BARGE_IN_RMS_THRESHOLD` as a dedicated `.env` key, defaulting to **750**. Human conversational speech at a normal distance from a Turtle Beach headset registers 800-1400 RMS. Keyboard clicks are transient spikes rarely exceeding 700 RMS sustained over multiple frames.

| Noise source | Typical RMS | Fires at gate=550 | Fires at gate=750 |
|---|---|---|---|
| HVAC / fan | 200-400 | No | No |
| Keyboard typing (single key) | 400-700 peak | Yes (spike) | Possibly (spike) |
| Keyboard typing (sustained) | 350-550 sustained | Yes | No |
| Human speech (normal) | 800-1400 | Yes | Yes |
| Human speech (whisper) | 400-600 | Yes | No |

**Variable 2: Consecutive-frame trigger count**

The current monitor fires on the **first** frame (512 samples = 32ms) above the gate. One keyboard click at 600 RMS fires the barge-in.

**Proposed:** Require **N=3 consecutive frames** above threshold before triggering (`consecutive_required=3`, default). Three consecutive 32ms frames = 96ms of sustained audio. Keyboard clicks are single-frame transients (10-30ms). Voice is sustained. This change alone eliminates the majority of false positives.

Implementation: a running counter inside the `_monitor()` loop:
```
consecutive = 0
if rms > threshold:
    consecutive += 1
    if consecutive >= required:
        fire()
else:
    consecutive = 0
```

**Variable 3: `warmup_sec` (increase from 0.45 to 1.0)**

The 0.45s warmup absorbs the tail of the user's previous utterance. For the barge-in during llama_cpp fallback (which starts after the cascade already took 1-2s), 1.0s is safer — it ensures the user's most recent words have fully decayed from the mic buffer before monitoring begins.

**Variable 4: `llama_cpp` max_tokens for fallback calls**

When `llama_cpp` is reached in the cascade (i.e., all cloud APIs have been skipped or failed), the `max_tokens` for voice mode is currently 150. In fallback mode, cap at **80 tokens**. Fewer output tokens = shorter generation = smaller window in which barge-in can fire. In voice mode, 80 tokens is approximately 2 spoken sentences — fully adequate.

**Variable 5: `_generation_cancel` check in `_call_ollama`**

The llama_cpp `create_chat_completion` call does not check `_generation_cancel`. Two options:

- **Option A (Preferred):** Switch to streaming mode for llama_cpp (`stream=True`) and yield chunks through `_stream_route`. Check `_generation_cancel` between chunks. This keeps the mic responsive — user can interrupt after the first sentence.

- **Option B (Simpler):** Use a separate daemon thread for the blocking llama_cpp call. The `_smart_route` function uses `concurrent.futures.Future` with a timeout. If `_generation_cancel` is set within the timeout, cancel the future. Note: `Future.cancel()` cannot abort a running llama_cpp call — it only skips result retrieval. The inference continues but the result is discarded. This wastes GPU cycles but immediately returns control.

Option A is the correct long-term fix. Option B is a 10-line stop-gap.

---

## 6. Summary: Ranked Implementation Plan

| Priority | Change | File | Budget |
|---|---|---|---|
| 1 (CRITICAL) | Sliding window rate limiter (Groq + Gemini) | `core/brain.py` | $0 |
| 2 (CRITICAL) | Add `consecutive_required=3` to barge-in | `core/voice.py` | $0 |
| 3 (CRITICAL) | Add `BARGE_IN_RMS_THRESHOLD=750` | `.env` + `core/voice.py` | $0 |
| 4 (HIGH) | Expand `_rewrite_generic_response` pre-classifier | `core/brain.py` | $0 |
| 5 (HIGH) | Add OpenRouter as middle-tier fallback | `core/brain.py`, `config.py`, `.env` | $0 |
| 6 (HIGH) | Fix code cascade: insert Gemini between groq and llama_cpp | `core/brain.py` | $0 |
| 7 (MEDIUM) | Cap fallback llama_cpp at max_tokens=80 | `core/brain.py` | $0 |
| 8 (MEDIUM) | Add Together AI as second middle-tier fallback | `core/brain.py`, `config.py`, `.env` | ~$0 |
| 9 (MEDIUM) | Enable llama_cpp streaming with cancel check | `core/brain.py` | $0 |
| 10 (LOW) | Remove dead BRAIN_PRIORITY config and fix PRIMARY_BRAIN display | `config.py`, `core/brain.py` | $0 |
| 11 (LOW) | Adaptive N_CTX reduction for llama_cpp fallback path | `core/brain.py`, `config.py` | $0 |

---

## 7. Risks & Mitigations

**Risk:** Expanded pre-classifier gives wrong answers for ambiguous short phrases.  
**Mitigation:** The local vocabulary table only handles unambiguous social utterances. Any phrase containing a proper noun, a number, or a question word is passed to the LLM path.

**Risk:** Rate limiter skips a provider that has recovered before its window expires.  
**Mitigation:** Use a sliding window (timestamps, not a fixed counter). The window is accurate to the second. A 5-request headroom buffer (internal limit set below actual limit) ensures the real 429 wall is never reached even with slight clock drift.

**Risk:** OpenRouter free models have lower quality than Groq llama-4-scout.  
**Mitigation:** OpenRouter is a fallback, not primary. Quality for conversational voice mode at 150 tokens is adequate from any 7B+ instruction-tuned model.

**Risk:** Raising BARGE_IN_RMS_THRESHOLD to 750 prevents intentional interrupts.  
**Mitigation:** The interrupt *poller* (`listen_for_interrupt`) runs on the SR stream at WAKE_RMS_THRESHOLD (360) — it still hears the user and can trigger an interrupt via the text wake-word check. The barge-in RMS monitor is a parallel, faster mechanism; raising its gate just means soft/whispered speech won't trigger it. The SR path still handles those.

---

*Awaiting directive to proceed with implementation. Recommend starting with Priority 1-3 (rate limiter + barge-in tuning) as they address the immediate catastrophic failure mode before adding new providers.*
