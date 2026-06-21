# IRIS Master Handover Report
## Phase 7 → Phase 8 (Docker / Kubernetes) Transition
**Version:** v5.2.5-STABLE | **Date:** 2026-04-18 | **Auditor:** Principal Systems Architect

---

## EXECUTIVE SUMMARY

IRIS is a resilient, hybrid AI hypervisor running on a bare-metal Windows 11 host with an RTX 5050 (8GB VRAM). The Phase 7 architecture is functionally complete and stable. However, **seventeen concrete blockers** must be resolved before the system can be containerized. The most severe are: a hardcoded Windows absolute path deep in config, a WASAPI-only audio pipeline, Windows-specific executor shell commands, and three undefined `logger` references that silently corrupt error handling in core modules.

---

## SECTION 1: THE "AS-IS" ARCHITECTURE MAP

### 1.1 Voice Input Pipeline

```
[Physical Mic] ──WASAPI──► [PyAudio persistent stream @ 16kHz/512 frames]
                                          │
                    ┌─────────────────────┴──────────────────────────┐
                    │ Dual-consumer WASAPI shared mode                 │
                    ▼                                                   ▼
        [sr.Recognizer: SpeechRecognition]                [RMS Monitor Stream]
        energy_threshold = WAKE_RMS_THRESHOLD (400)        frames_per_buffer = 512
        pause_threshold  = 0.45 s (96ms silence gate)     Used by: start_barge_in_monitor()
        phrase_threshold = 0.2                             BARGE_IN_RMS_THRESHOLD = 750
        dynamic_energy   = OFF (HF-2 fix; anchored)
                    │
                    ▼
        [listen_for_wake()  │  listen_for_command()  │  listen_for_interrupt()]
                    │
                    ▼ (raw WAV bytes, 16kHz PCM)
        [Groq Whisper API: whisper-large-v3-turbo]
        HTTP POST multipart/form-data → api.groq.com
        timeout: ~7s; no retry logic
                    │
                    ▼ (transcript string)
        [should_ignore_transcript()] ── echo guard ──► _recent_spoken deque (maxlen=10)
        + 500ms dead-zone on speaking→silent transition
                    │
                    ▼
        [_strip_wake_aliases()] → removes "iris"/"aletheia" prefixes + 14 Whisper misheards
                    │
                    ▼
        [_is_substantive_voice_input()] → drops single-word noise, trailing prepositions
                    │
                    ▼
        [handle_user_input()]
```

### 1.2 Brain Routing Pipeline

```
[handle_user_input()]
    │
    ├── fast-path: _rewrite_generic_response() → time/date → instant return
    ├── vision intercept: _is_vision_query() → _try_vision() → Groq Vision (Llama 4 Scout)
    │                      screen captured via mss → base64 JPEG → Groq API
    │
    ├── dialog_manager.analyze() → classifies: action | search | copilot | diagnostics | general
    │
    └── _smart_route() [priority: groq → gemini → claude → llama_cpp → ollama]
               │
               ├── _SlidingWindowRateLimiter (deque-based, thread-safe RLock)
               │   groq: 15 calls/60s window  (25% below free-tier 20 RPM)
               │   gemini: 10 calls/60s window (25% below free-tier 15 RPM)
               │
               ├── Groq path: HTTP SSE stream → chunk_stream() generator → voice.speak() per sentence
               │
               └── llama_cpp path: Llama(model=Qwen3-8B-Q4_K_M.gguf)
                   n_gpu_layers=-1 (all layers to VRAM)
                   n_ctx=16384 (doubled; freed VRAM from Groq STT migration)
                   chat_format="chatml"
                   flash_attn=True
                   type_k=8, type_v=8 (KV cache q8_0; 0.56GB vs 1.1GB at N_CTX=8192)
                   GBNF JSON grammar via response_format={"type":"json_object"}
                   (only on require_json=True paths: autonomist, executor _ai_plan)
```

### 1.3 TTS Pipeline

```
[voice.speak(text)]
    │
    ├── Check _static_audio_cache (pre-generated wake acks, farewells, thinking cues) → instant
    ├── Check _tts_prefetch_cache (lookahead: sentence N+1 generated while N plays)
    │
    ▼ (cache miss)
    [_run_edge_tts_async(text, voice_name, rate, output_path)]
    │   edge_tts.Communicate → _EdgeTTSEventLoop (ProactorEventLoop, persistent thread)
    │   Microsoft Azure Neural TTS (en-GB-LibbyNeural / en-US-AriaNeural)
    │   timeout = TTS_NETWORK_TIMEOUT_SEC (8s)
    │   output: temp .mp3 file
    │
    ▼
    [_utterance_queue → _run_speech_worker() daemon thread]
    │   pygame.mixer.Sound(mp3_path).play()
    │   stop_event polling for barge-in cancellation
    │
    ▼
    [record_spoken(text)] → _recent_spoken deque (echo guard feed)
```

### 1.4 Rate Limiters and Debounce Interaction

| Mechanism | Type | Location | Value |
|---|---|---|---|
| Wake RMS gate | Hardware filter | Voice._clamp_threshold() | 400 RMS (floor 240, ceiling 540) |
| Acoustic debounce | Silence timer | sr.Recognizer.pause_threshold | 0.45 s |
| Echo dead zone | Sleep | _run_voice_followup_window() | 500ms on speaking→silent |
| Speaker bleed guard | deque similarity | should_ignore_transcript() | last 10 utterances |
| Barge-in gate | RMS sustained | start_barge_in_monitor() | 750 RMS × 3 consecutive frames |
| Barge-in warmup | Suppression timer | start_barge_in_monitor() | 1.5s (covers longest thinking cue) |
| Rate limiter (Groq) | Sliding window | _SlidingWindowRateLimiter | 15 calls / 60s |
| Rate limiter (Gemini) | Sliding window | _SlidingWindowRateLimiter | 10 calls / 60s |

---

## SECTION 2: COMPREHENSIVE DEPENDENCY ANALYSIS

### 2.1 Python Package Inventory

| Package | Pinned Version | Status | Notes |
|---|---|---|---|
| `groq` | `==0.12.0` | ⚠️ Stale | Latest ~0.18.x; API changes possible. Used for STT + vision + LLM. |
| `anthropic` | `==0.40.0` | ⚠️ Stale | Latest ~0.49+; `claude-sonnet-4-6` needs newer SDK features. |
| `google-generativeai` | `==0.8.3` | ⚠️ Stale | Latest 0.8.x; Gemini 2.5 Flash requires ≥0.8.0 — currently OK but should test. |
| `requests` | `==2.32.3` | ✅ OK | Stable. Used for raw HTTP on all API paths not using SDK. |
| `python-dotenv` | `==1.0.1` | ✅ OK | Stable. |
| `rich` | `==13.9.4` | ✅ OK | Stable. |
| `edge-tts` | `==6.1.12` | ⚠️ Check | Tied to Microsoft Azure TTS API endpoints; pin breaking changes are common. |
| `pygame` | `==2.6.1` | 🚫 **Docker Blocker** | Uses WASAPI on Windows. No PulseAudio/ALSA support by default on Linux. |
| `SpeechRecognition` | `==3.11.0` | 🚫 **Docker Blocker** | Wraps PyAudio. Requires PortAudio at OS level. |
| `PyAudio` | `==0.2.14` | 🚫 **Docker Blocker** | Windows-conditional in requirements but used unconditionally in voice.py. Requires libportaudio2 on Linux. |
| `faster-whisper` | `>=1.0.3` | ⚠️ **Dead Code** | Imported in voice.py stub paths but Groq cloud STT replaced local Whisper entirely. Adds ~200MB to image for no benefit. |
| `ctranslate2` | `>=4.4.0` | ⚠️ **Dead Code** | Dependency of faster-whisper. Same removal target. |
| `numpy` | `==1.26.4` | ⚠️ Version Lock | Hard-pinned. Conflicts possible with latest scipy/torch in same environment. |
| `nvidia-ml-py` | `==12.535.133` | 🔶 Conditional | Requires libnvidia-ml.so at runtime. Works only with NVIDIA Container Toolkit. |
| `llama-cpp-python` | `>=0.2.0` | 🚫 **Docker Blocker** | Extremely broad pin. CUDA 12.1 GPU build must be specified explicitly. Different wheels for CPU, CUDA 11.x, CUDA 12.x. |
| `duckduckgo-search` | `>=5.0.0` | ✅ OK | Pure Python, network-only dep. |
| `psutil` | `>=5.9.8` | ✅ OK | Works on Linux. |
| `playwright` | `>=1.42.0` | 🔶 Heavy | Requires `playwright install --with-deps chromium` post-install. Adds ~150MB. Needs display. |
| `sounddevice` | `>=0.4.6` | 🔶 Unclear | In requirements but not visibly used in production paths. Check if dead code. |
| `send2trash` | unpinned | ⚠️ No pin | No version constraint. Used in executor._delete_item(). Behavior differs on Linux (uses `gio trash`). |
| `mss` | **MISSING** | 🚫 **Critical** | Imported in `core/vision.py` for screen capture but absent from requirements.txt. Silent crash on fresh install. |
| `Pillow` | **MISSING** | 🚫 **Critical** | Same — imported dynamically for JPEG encoding in vision path. Absent from requirements.txt. |
| `pytest` | `>=9.0.0` | ✅ OK | Test-only dep. Should be in `[dev]` extras, not base requirements. |

### 2.2 System-Level Dependencies

These are OS/kernel-level requirements that Python packages rely upon. **None are documented anywhere in the project.** Each is a Docker blocker.

| System Dependency | Required By | Linux Package | Docker Status |
|---|---|---|---|
| **PortAudio** (libportaudio2) | PyAudio, SpeechRecognition | `libportaudio2`, `portaudio19-dev` | Must install in Dockerfile |
| **ALSA / PulseAudio** | pygame.mixer, PyAudio | `libasound2`, `pulseaudio` | Required for audio I/O; needs `/dev/snd` passthrough |
| **NVIDIA CUDA 12.1+** | llama-cpp-python (GPU build) | nvidia-container-toolkit | Requires `--gpus all` Docker flag + NVIDIA runtime |
| **NVIDIA Driver ≥ 525.x** | CUDA 12.1 | Host driver | Host-level; not installable in container |
| **libnvidia-ml.so** | nvidia-ml-py (VRAM monitor) | Ships with driver | Accessible only via NVIDIA Container Toolkit |
| **C++ Build Tools (CMake, gcc)** | llama-cpp-python (if building from source) | `build-essential`, `cmake` | Required if not using pre-built wheel |
| **X11 / Xvfb** | mss (screen capture), playwright | `xvfb`, `xauth` | Vision feature requires virtual framebuffer in headless container |
| **Chromium browser** | playwright | `playwright install chromium` | Separate install step beyond pip |
| **libffi, libbz2, libssl** | Python standard library deps | `libffi-dev`, `libbz2-dev`, `libssl-dev` | Often missing in slim base images |
| **xdg-utils** | `webbrowser.open()` via executor | `xdg-utils` | Not available in minimal containers; open_app/search_web will fail |

### 2.3 Version Conflicts

| Conflict | Detail |
|---|---|
| `numpy==1.26.4` vs `llama-cpp-python` | llama-cpp-python's CUDA wheel may pull numpy ≥2.0 as a dep. Hard pin will conflict. |
| `faster-whisper>=1.0.3` vs `ctranslate2>=4.4.0` | Both are dead dependencies. They declare transitive CUDA deps that conflict with llama-cpp-python's CUDA build. Remove both. |
| `PyAudio==0.2.14` (Windows-conditional) | The `platform_system == "Windows"` marker in requirements means PyAudio is never installed on Linux CI, yet `voice.py` always attempts to open a PyAudio RMS stream. This is a silent Linux breakage. |

---

## SECTION 3: VULNERABILITY & TECHNICAL DEBT HUNT

### 3.1 Critical Bugs (Will Crash at Runtime)

#### BUG-01: Undefined `logger` in `core/autonomist.py`
**File:** [core/autonomist.py:50](core/autonomist.py)
```python
except Exception as _learn_err:
    logger.warning("[Autonomist] learn_from_session parse/update failed: %s", _learn_err)
```
`logger` is never imported or defined in this module. Any parse failure in `learn_from_session()` (which runs on every session shutdown) will raise `NameError: name 'logger' is not defined`, crashing the shutdown learning thread and silently swallowing the original error. The daemon thread catches this but leaves no trace.

#### BUG-02: Undefined `logger` in `core/memory.py`
**File:** [core/memory.py:52](core/memory.py)
```python
except Exception as _load_err:
    logger.error("[Memory] Conversation load failed (resetting to empty): %s", _load_err)
```
Same pattern. If `iris_memory.json` is corrupted (e.g., interrupted write), the `except` block raises `NameError` before it can log anything, and `self.conversation = []` is never reached. IRIS launches with stale memory instead of a clean slate.

#### BUG-03: Undefined `logger` in `core/executor.py`
**File:** [core/executor.py:735, 927](core/executor.py)
```python
logger.warning("[Executor] JSON parse failed: %s | snippet: %s", ...)
```
`logger` not imported. AI JSON planning failures are silently swallowed.

#### BUG-04: `mss` and `Pillow` missing from requirements.txt
`core/vision.py` dynamically imports both. Any fresh `pip install -r requirements.txt` will produce a working install that crashes when the user says "what do you see" or "look at my screen". The `_try_vision()` graceful except in `brain.py` saves the user from a hard crash but the feature is silently dead.

### 3.2 Thread Safety Issues

#### TS-01: `Memory.conversation` list has no lock
**File:** [core/memory.py](core/memory.py)
`self.conversation` is a plain Python `list`. It is accessed by:
- Main thread (every `brain.think()` call via `memory.add()`)
- Shutdown learning thread (`autonomist.learn_from_session()` during `_finalize_session()`)
- Session logger (indirectly)

Python's GIL prevents data corruption on simple list operations, but `_self_clean()` iterates and rebuilds the list in O(n) with a `list(reversed(cleaned))` copy. If `add()` fires mid-clean from a concurrent thread, you get a race on the reference swap. Low probability, but non-zero in a 24/7 deployment.

#### TS-02: `Autonomist._update_kb()` has no file lock
**File:** [core/autonomist.py:52](core/autonomist.py)
Reads `knowledge_base.json`, merges, writes back. No `threading.Lock()`. If two learning threads fire concurrently (unlikely but possible at session overlap), the second write can overwrite the first.

### 3.3 Memory Leak Risk (24/7 Operation)

#### ML-01: `_self_clean()` called on every `memory.add()` — O(n²) behavior
**File:** [core/memory.py:170](core/memory.py)
```python
self._self_clean()   # called inside add() for every turn
```
`_self_clean()` iterates the full `conversation` list (up to `MAX_MEMORY_TURNS=200`) to deduplicate. Called N times per session, this is O(N²) list work. At 200 turns: 200 × 200 = 40,000 iterations. Not a leak, but a consistent CPU spike. Replace with a `seen_content` set maintained on `add()` calls.

#### ML-02: `_tts_prefetch_cache` and `_static_audio_cache` grow unbounded
**File:** [core/voice.py](core/voice.py)
Temp `.mp3` files written to `tempfile.NamedTemporaryFile`. The static cache entries (pre-generated phrases) are kept "never deleted mid-session." In a 24/7 container, these temp file descriptors persist indefinitely. On a long-running deployment, `/tmp` fills up.

### 3.4 Fragile Code Patterns

#### FP-01: Hardcoded absolute Windows path in `config.py`
**File:** [config.py:62](config.py)
```python
LOCAL_MODEL_PATH = os.getenv("LOCAL_MODEL_PATH", "D:/IRIS-live/models/Qwen3-8B-Q4_K_M.gguf")
```
The default value is a Windows drive-letter absolute path. On any Linux system (Docker container, CI, deployment), this default is silently invalid. If the env var is not set in the container, `os.path.exists()` returns False, `llama_cpp` is excluded from `available_apis`, and IRIS runs Groq-only without warning.

#### FP-02: Executor is Windows-only
**File:** [core/executor.py](core/executor.py)
- `subprocess.CREATE_NO_WINDOW` flag used unconditionally (raises `AttributeError` on Linux)
- `'start "" "{target}"'` shell command (Windows `start` builtin)
- `'rd /s /q "{path}"'` delete command (Windows only)
- `'ren "{path}" "{name}"'` rename command (Windows only)
- `os.startfile(path)` (Windows only, no Linux equivalent)
- `winget install` hardcoded in AI action plans
- Desktop path resolves via `C:\Users\...\OneDrive\Desktop`

#### FP-03: `webbrowser.open()` requires display + browser
The executor calls `webbrowser.open()` for web search, Spotify, YouTube, and other media. In a headless container, this silently fails or raises `DISPLAY not set`.

#### FP-04: `evolution.py` hot-reloads AI-generated code
**File:** [core/evolution.py:63](core/evolution.py)
```python
importlib.reload(core.custom_tools)
```
The security scan (`_contains_dangerous_pattern`) checks only 6 regex patterns. This is a code execution attack surface. The feature gates on `admin_unlocked=True` which is a mitigation, but in a container this could write malicious code to `core/custom_tools.py` and hot-reload it into the running process.

#### FP-05: Groq STT has no retry logic
**File:** [core/voice.py](core/voice.py)
Audio is uploaded via `requests` (or the `groq` SDK) with a single attempt. Network blips in a container will drop utterances silently. There is no retry with backoff.

#### FP-06: `_run_with_live_progress()` can block indefinitely
**File:** [core/executor.py:931](core/executor.py)
```python
process = subprocess.Popen(command, shell=True, ...)
for line in process.stdout:  # blocks until stdout EOF
    ...
process.wait()              # then waits again
```
If a subprocess hangs (e.g., `winget install` waiting for UAC), the rich Progress context and the calling thread block forever. The 120-second timeout only applies to `subprocess.run()`, not to `Popen`.

---

## SECTION 4: THE DOCKERIZATION BLOCKERS

### 4.1 Blocker Matrix

| ID | Severity | Component | Description |
|---|---|---|---|
| D-01 | 🔴 FATAL | `config.py` | `LOCAL_MODEL_PATH` default is `D:/IRIS-live/...` — Linux path invalid |
| D-02 | 🔴 FATAL | `core/voice.py` | PyAudio WASAPI RMS stream: `CREATE_NO_WINDOW` → `AttributeError` on Linux |
| D-03 | 🔴 FATAL | `core/voice.py` | `sr.Microphone` requires PortAudio → `libportaudio2` not in base images |
| D-04 | 🔴 FATAL | `core/executor.py` | `subprocess.CREATE_NO_WINDOW` raises `AttributeError` on Linux |
| D-05 | 🔴 FATAL | `core/executor.py` | `os.startfile()` raises `AttributeError` on Linux |
| D-06 | 🔴 FATAL | `core/executor.py` | `'start "" ...'`, `rd /s /q`, `ren` — Windows shell builtins unavailable |
| D-07 | 🔴 FATAL | `llama-cpp-python` | `>=0.2.0` is a source build without CUDA; needs explicit CUDA 12.1 wheel |
| D-08 | 🔴 FATAL | `core/voice.py` | `pygame.mixer` has no Linux ALSA/PulseAudio init; `mixer.init()` will fail |
| D-09 | 🔴 FATAL | `core/brain.py` | `mss` screen capture requires X11 display; will raise `mss.exception.ScreenShotError` |
| D-10 | 🟠 HIGH | Host | `/dev/snd` device passthrough requires `--device /dev/snd` + PulseAudio socket |
| D-11 | 🟠 HIGH | Host | GPU passthrough requires `nvidia-container-toolkit` + `--gpus all` runtime flag |
| D-12 | 🟠 HIGH | `core/executor.py` | `webbrowser.open()` requires `DISPLAY` + `xdg-utils` + browser binary |
| D-13 | 🟠 HIGH | `requirements.txt` | `faster-whisper` + `ctranslate2` pull conflicting CUDA transitive deps |
| D-14 | 🟡 MEDIUM | `core/memory.py` | State files (`iris_memory.json`, archives) in project root → lost on container restart |
| D-15 | 🟡 MEDIUM | `nvidia-ml-py` | NVML library (`libnvidia-ml.so`) requires NVIDIA Container Toolkit even for monitoring |
| D-16 | 🟡 MEDIUM | `playwright` | Requires `playwright install --with-deps chromium` + display |
| D-17 | 🟡 MEDIUM | `core/voice.py` | Edge-TTS requires outbound HTTPS to `*.tts.speech.microsoft.com` from container |

### 4.2 GPU Passthrough Deep-Dive

**llama.cpp GPU passthrough** requires:
1. NVIDIA driver ≥ 525.x installed on the **host** (not in container)
2. `nvidia-container-toolkit` installed on the host
3. Docker daemon configured with `"default-runtime": "nvidia"` in `/etc/docker/daemon.json`
4. Container run with `--gpus all` or `--gpus '"device=0"'`
5. Base image: `nvidia/cuda:12.1-cudnn8-runtime-ubuntu22.04` or equivalent
6. `llama-cpp-python` installed from the CUDA 12.1 pre-built wheel:
   ```
   pip install llama-cpp-python \
     --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
   ```
7. The model file (`Qwen3-8B-Q4_K_M.gguf`, ~5.1GB) must be mounted as a Docker volume — it cannot be baked into the image.

**Microphone passthrough** requires:
1. `--device /dev/snd` flag to expose ALSA devices
2. A PulseAudio server socket mounted: `-v /run/user/1000/pulse:/run/user/1000/pulse`
3. `PULSE_SERVER=unix:/run/user/1000/pulse` environment variable in container
4. User in the `audio` group in the container
5. The `voice.py` `_init_mic()` WASAPI code path must be replaced with ALSA-compatible initialization

---

## SECTION 5: STRATEGIC REMEDIATION PLAN

The following items are ordered by: **must-fix before `docker build`** → **must-fix before `docker run` passes all tests** → **must-fix before production deployment**.

### TIER 0 — Prerequisites (Fix Before Writing Dockerfile)

**T0-1: Fix undefined `logger` in three modules** *(BUG-01, BUG-02, BUG-03)*
```
core/autonomist.py: add `from core import logger as _log; logger = _log.get_logger("Autonomist")`
core/memory.py:     add `from core import logger as _log; logger = _log.get_logger("Memory")`
core/executor.py:   add `from core import logger as _log; logger = _log.get_logger("Executor")`
```
These are correctness bugs, not style issues. Fix first.

**T0-2: Externalize model path — remove hardcoded Windows path** *(D-01)*
`config.py:62` — Change default to a relative path or a Linux-compatible env-var-only pattern:
```python
LOCAL_MODEL_PATH = os.getenv("LOCAL_MODEL_PATH", "")
```
Document that `LOCAL_MODEL_PATH` must be set in the container's environment. Mount model at `/models/Qwen3-8B-Q4_K_M.gguf`.

**T0-3: Add `mss` and `Pillow` to `requirements.txt`** *(BUG-04)*
```
mss>=9.0.1
Pillow>=10.0.0
```
These are silent runtime crashes; must be explicit dependencies.

**T0-4: Remove dead code dependencies** *(version conflict risk)*
Remove from `requirements.txt`:
```
faster-whisper>=1.0.3    # replaced by Groq cloud STT
ctranslate2>=4.4.0       # dependency of faster-whisper
```
These consume ~300MB of image space and introduce CUDA transitive dependency conflicts with `llama-cpp-python`.

**T0-5: Fix `subprocess.CREATE_NO_WINDOW` for Linux** *(D-02, D-04)*
`core/executor.py` uses this Windows-only constant in `_run_command()` and `_run_with_live_progress()`.
Wrap with:
```python
_POPEN_FLAGS = {"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {}
subprocess.Popen(command, shell=True, **_POPEN_FLAGS)
```

---

### TIER 1 — Audio Architecture (Enable Docker Audio Passthrough)

**T1-1: Replace WASAPI-only PyAudio init with cross-platform initialization**
In `voice.py._open_rms_stream()`, the RMS monitor stream opens with no backend specification. On Linux, PyAudio defaults to ALSA. The WASAPI code path is implicit via Windows default. Replace with explicit backend detection:
```python
# Detect backend: ALSA on Linux, WASAPI on Windows
_pa_backend = "WASAPI" if sys.platform == "win32" else "ALSA"
```
Add fallback that disables the RMS stream gracefully when `/dev/snd` is not mounted.

**T1-2: Add `IRIS_DISABLE_VOICE_IO=true` container mode**
`voice.py` already has `_force_io_disabled = os.getenv("IRIS_DISABLE_VOICE_IO", "false")`. Document and enforce this as the container default for non-voice deployments. For Kubernetes, the voice pipeline should default to off unless explicitly enabled with `/dev/snd` passthrough.

**T1-3: Replace `pygame.mixer` Linux audio backend**
`pygame` on Linux requires either ALSA or PulseAudio. Add to Dockerfile:
```dockerfile
RUN apt-get install -y libsdl2-dev libsdl2-mixer-2.0-0 pulseaudio
```
And in container entrypoint: `pulseaudio --start --exit-idle-time=-1`

---

### TIER 2 — Executor OS Abstraction

**T2-1: Abstract OS-specific executor commands**
Create an `OsAdapter` class or split `executor.py` into:
- `executor_core.py` — OS-agnostic logic (permission gates, security check, improv engine)
- `executor_windows.py` — `CREATE_NO_WINDOW`, `os.startfile`, `winget`, `ren`, `rd /s /q`
- `executor_linux.py` — `xdg-open`, `apt`/`snap`, `mv`, `rm -rf`, `xdg-mime`

Short-term Docker fix: add an `is_linux` guard and return "This action requires Windows." for Windows-only commands, rather than crashing.

**T2-2: Fix `_open_app()` and `webbrowser.open()` for headless**
Add `DISPLAY` environment check before `webbrowser.open()`:
```python
if not os.environ.get("DISPLAY") and sys.platform != "win32":
    return "Browser operations require a display environment."
```

---

### TIER 3 — 24/7 Stability Fixes

**T3-1: Add `threading.RLock` to `Memory.conversation`**
Wrap the `conversation` list with a re-entrant lock. Specifically protect `add()`, `_self_clean()`, `get_context()`, and `archive_session()`.

**T3-2: Fix O(n²) `_self_clean()` in `memory.py`**
Move deduplication tracking to a `set` maintained persistently on the `Memory` object, updated on each `add()`. Eliminates the full-list scan on every turn.

**T3-3: Add retry logic to Groq STT**
In `voice.py`, wrap the Groq transcription call with exponential backoff (2 retries, 0.5s/1.0s delays). Transient 429s and network blips in Kubernetes should not drop utterances.

**T3-4: Add file lock to `Autonomist._update_kb()`**
Add a module-level `threading.Lock` for `knowledge_base.json` read-write cycles.

**T3-5: Cap TTS temp file accumulation**
Add a cleanup pass in `_run_speech_worker()` that deletes temp `.mp3` files after playback. Static cache files (in `_static_audio_cache`) should be written to a dedicated `/tmp/iris-static/` directory, cleared on startup.

---

### TIER 4 — Containerization Prerequisites

**T4-1: Externalize all state paths as environment variables**

| Current Hardcoded Path | Env Var | Docker Volume Mount |
|---|---|---|
| `iris_memory.json` (project root) | `IRIS_MEMORY_PATH` | `/data/memory/iris_memory.json` |
| `iris_memory_sessions_archive.json` | Derived from `IRIS_MEMORY_PATH` | Same volume |
| `knowledge_base.json` | `IRIS_KB_PATH` | `/data/memory/knowledge_base.json` |
| `logs/` | `IRIS_LOG_DIR` | `/data/logs/` |
| `iris_actions.log` | `IRIS_ACTION_LOG` | `/data/logs/iris_actions.log` |
| Model file | `LOCAL_MODEL_PATH` | `/models/Qwen3-8B-Q4_K_M.gguf` |

**T4-2: Pin `llama-cpp-python` to a specific CUDA wheel**
```
# requirements.txt
# CPU-only fallback (default):
llama-cpp-python==0.3.9

# GPU build (separate requirements-cuda.txt or Dockerfile ARG):
# pip install llama-cpp-python==0.3.9 \
#   --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

**T4-3: Add Xvfb service for vision feature**
For the screen-capture (mss) and playwright features in headless mode:
```dockerfile
RUN apt-get install -y xvfb
# Entrypoint: Xvfb :99 -screen 0 1920x1080x24 &
ENV DISPLAY=:99
```
Alternatively, provide `IRIS_DISABLE_VISION=true` env var to skip `_try_vision()`.

**T4-4: Add a health check endpoint**
IRIS has no HTTP server or health endpoint. For Kubernetes liveness/readiness probes, add a minimal FastAPI/Flask health endpoint:
```python
# At minimum: GET /health → {"status": "ok", "llm_ready": brain.llm is not None}
```

**T4-5: Update stale SDK versions**
```
groq==0.12.0       → groq>=0.18.0
anthropic==0.40.0  → anthropic>=0.49.0
```
Test against current model IDs (`claude-sonnet-4-6`, `whisper-large-v3-turbo`, `meta-llama/llama-4-scout-17b-16e-instruct`) after upgrading.

---

## SECTION 6: RECOMMENDED DOCKER IMAGE ARCHITECTURE

```
Base: nvidia/cuda:12.1-cudnn8-runtime-ubuntu22.04
         │
         ├── System packages:
         │   libportaudio2, portaudio19-dev (PyAudio)
         │   libasound2, pulseaudio (audio I/O)
         │   libsdl2-dev, libsdl2-mixer-2.0-0 (pygame)
         │   xvfb, xauth (headless display for mss/playwright)
         │   xdg-utils (webbrowser fallback)
         │   build-essential, cmake (llama-cpp-python if building from source)
         │
         ├── Python 3.11 (match host Python version)
         │
         ├── pip install -r requirements.txt
         │   (with faster-whisper/ctranslate2 removed)
         │
         ├── pip install llama-cpp-python \
         │     --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
         │
         └── playwright install --with-deps chromium

Volumes:
  /models      ← model files (read-only in container)
  /data/memory ← iris_memory.json, archives, knowledge_base.json
  /data/logs   ← session logs, action logs

Runtime flags:
  --gpus all                          ← NVIDIA GPU passthrough
  --device /dev/snd                   ← Microphone passthrough
  -v /run/user/1000/pulse:/run/user/1000/pulse   ← PulseAudio socket
  -e PULSE_SERVER=unix:/run/user/1000/pulse
  -e LOCAL_MODEL_PATH=/models/Qwen3-8B-Q4_K_M.gguf
  -e IRIS_MEMORY_PATH=/data/memory/iris_memory.json
  -e DISPLAY=:99
```

---

## APPENDIX: ISSUE REGISTRY

| ID | File | Line | Severity | Category |
|---|---|---|---|---|
| BUG-01 | autonomist.py | 50 | 🔴 Critical | Undefined `logger` |
| BUG-02 | memory.py | 52 | 🔴 Critical | Undefined `logger` |
| BUG-03 | executor.py | 735, 927 | 🔴 Critical | Undefined `logger` |
| BUG-04 | requirements.txt | — | 🔴 Critical | `mss`, `Pillow` missing |
| D-01 | config.py | 62 | 🔴 Fatal | Hardcoded Windows path |
| D-04 | executor.py | 940 | 🔴 Fatal | `CREATE_NO_WINDOW` |
| D-05 | executor.py | 207 | 🔴 Fatal | `os.startfile()` |
| D-06 | executor.py | 410,583 | 🔴 Fatal | Windows shell commands |
| D-07 | requirements.txt | 33 | 🔴 Fatal | Unpinned CUDA wheel |
| D-08 | voice.py | 143 | 🔴 Fatal | pygame WASAPI |
| D-09 | brain.py | 734 | 🔴 Fatal | mss requires X11 |
| TS-01 | memory.py | 31 | 🟠 High | No lock on conversation list |
| TS-02 | autonomist.py | 52 | 🟠 High | No file lock on KB |
| FP-01 | config.py | 62 | 🟠 High | Windows default path |
| FP-04 | evolution.py | 63 | 🟠 High | Hot-reload of AI code |
| FP-05 | voice.py | — | 🟠 High | No retry on STT upload |
| FP-06 | executor.py | 931 | 🟠 High | Indefinite Popen block |
| ML-01 | memory.py | 170 | 🟡 Medium | O(n²) _self_clean |
| ML-02 | voice.py | 109 | 🟡 Medium | TTS temp file accumulation |
| DEP-01 | requirements.txt | 19 | 🟡 Medium | Dead: faster-whisper |
| DEP-02 | requirements.txt | 20 | 🟡 Medium | Dead: ctranslate2 |
| DEP-03 | requirements.txt | 6 | 🟡 Medium | Stale: groq==0.12.0 |
| DEP-04 | requirements.txt | 4 | 🟡 Medium | Stale: anthropic==0.40.0 |

---

*End of IRIS Master Handover Report — Phase 7 to Phase 8*
*Total blockers identified: 17 (4 fatal bugs, 10 Docker blockers, 3 stability issues)*
*Estimated remediation effort before first `docker build`: ~12 engineering hours*
