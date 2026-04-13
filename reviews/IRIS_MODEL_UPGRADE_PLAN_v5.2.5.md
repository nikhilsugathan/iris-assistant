# IRIS Model Upgrade Plan — v5.2.5
**Date:** 2026-04-07
**Hardware:** RTX 5050 Mobile — 8 GB VRAM (~6.7 GB free at idle)
**Status:** READY TO APPLY

---

## Executive Summary

Every active model in the IRIS stack is either outdated, dangerously underpowered for available hardware, or scheduled for deprecation. The local LLM is running at roughly 25% of available VRAM. The Gemini model shuts down June 1, 2026. The Claude and Groq models have been superseded by significantly more capable successors. The Whisper model undershoots accuracy on noisy microphone input. This plan closes all seven gaps with no increase in operating cost.

---

## Upgrade Table

| Component | Current | Recommended Upgrade | Priority |
|-----------|---------|---------------------|----------|
| Local LLM | Llama 3.2 3B Q4_K_M (~2 GB VRAM) | **Qwen3 8B Q4_K_M** (~5.1 GB VRAM) | HIGH |
| N_GPU_LAYERS | 32 | **99** | HIGH |
| N_CTX | 4096 | **8192** | MEDIUM |
| Groq model | llama-3.3-70b-versatile | **meta-llama/llama-4-scout-17b-16e-instruct** | MEDIUM |
| Gemini model | gemini-2.0-flash ⚠️ DEPRECATED Jun 1 | **gemini-2.5-flash** | CRITICAL |
| Claude model | claude-3-5-sonnet-20241022 | **claude-sonnet-4-6** | MEDIUM |
| Whisper STT | small.en (~485 MB) | **medium.en** (~1.5 GB VRAM) | MEDIUM |

---

## VRAM Budget (Post-Upgrade)

```
Qwen3 8B Q4_K_M    ≈ 5.1 GB
Whisper medium.en  ≈ 1.5 GB
OS + drivers       ≈ 0.8 GB
──────────────────────────────
Total              ≈ 7.4 GB  (within 8 GB limit, ~0.6 GB headroom)
```

This is safe. The previous stack (3B + small.en) left ~5.5 GB idle — a complete waste.

---

## Per-Component Analysis

### 1. Local LLM — Llama 3.2 3B → Qwen3 8B Q4_K_M

**Why this matters for IRIS:**
The 3B model has 3.2 billion parameters and limited instruction-following capacity. This is the root cause of persona drift — the model frequently ignores voice_rules constraints, invents answers when it should ask, and mishandles ambiguous queries. Qwen3 8B has 8 billion parameters with state-of-the-art 2025/2026 training data and dramatically stronger instruction adherence.

**VRAM fit:** 5.03 GB at Q4_K_M — sits comfortably in 8 GB alongside Whisper medium.en.

**Download (run in PowerShell, save to D:\IRIS-live\models\):**
```
huggingface-cli download Qwen/Qwen3-8B-GGUF --include "Qwen3-8B-Q4_K_M.gguf" --local-dir D:/IRIS-live/models/
```
Or download manually from: https://huggingface.co/Qwen/Qwen3-8B-GGUF

**Expected improvement:** Better persona adherence, fewer assumption errors, more natural conversation flow.

---

### 2. N_GPU_LAYERS: 32 → 99

**Why this matters:**
The value `32` was correct for the 3B model (which has 28 transformer layers, so 32 effectively means "all"). Qwen3 8B has 36 layers. With N_GPU_LAYERS=32, 4 layers run on CPU — adding ~80–150ms of latency per inference call and partially defeating the GPU upgrade. Setting it to `99` is the standard "offload everything" sentinel regardless of model layer count.

**No download required.** Config change only.

---

### 3. N_CTX: 4096 → 8192

**Why this matters:**
The models are capable of 128K context but IRIS caps them at 4096 tokens — roughly 10–15 turns of conversation before memory starts getting truncated. Doubling to 8192 gives 20–30 turns with minimal VRAM cost (~250 MB extra). This directly improves multi-step task memory and follow-up question coherence.

**No download required.** Config change only.

---

### 4. Groq: llama-3.3-70b-versatile → meta-llama/llama-4-scout-17b-16e-instruct

**Why this matters:**
Llama 4 Scout is the current-generation Meta model on Groq. Key improvements:
- **460 tokens/second** inference (versus ~200 for 70B) — faster cloud fallback responses
- **128K context window** (versus 32K for 3.3 70B)
- **12-language support** and stronger multimodal reasoning
- Mixture-of-Experts architecture: 17B active parameters, 109B total

The 70B model remains available but Scout is objectively faster for voice-assistant use cases where response speed matters more than raw model size.

**No download required.** Model string change only.

---

### 5. Gemini: gemini-2.0-flash → gemini-2.5-flash ⚠️ URGENT

**Why this is critical:**
Google has officially announced that `gemini-2.0-flash` and `gemini-2.0-flash-lite` will be **shut down on June 1, 2026**. Any IRIS instance still using this model string after that date will hard-fail with HTTP 404 or 410 on every Gemini call. With ~55 days remaining, this is the most time-sensitive change in this plan.

Gemini 2.5 Flash is Google's current workhorse model — advanced reasoning, coding, math, and faster than 2.0 Flash on most benchmarks with improved accuracy.

**No download required.** Model string change only.

---

### 6. Claude: claude-3-5-sonnet-20241022 → claude-sonnet-4-6

**Why this matters:**
The current model string is 18 months old. Claude Sonnet 4.6 (released February 17, 2026) offers:
- **1 million token context window** (versus 200K)
- **Extended thinking** support
- **64K max output tokens** (versus 8K)
- Improved instruction following and reasoning at the same price tier ($3/$15 per 1M tokens)

**No download required.** Model string change only.

---

### 7. Whisper STT: small.en → medium.en

**Why this matters for IRIS voice problems:**
`small.en` transcription accuracy degrades significantly in real-world conditions — ambient noise, fast speech, or words spoken near a microphone boundary. The medium model (769M parameters, ~7% WER on noisy speech versus ~11% for small) will reduce the number of garbled transcriptions that trigger the "IRIS assumes instead of asks" behavior and the mishearing issues reported. It also handles low-energy phrases better, reducing false-negative captures.

**VRAM fit:** ~1.5 GB — comfortable alongside Qwen3 8B (5.1 GB). Total: ~7.4 GB of 8 GB.

**No separate download needed** — faster-whisper downloads medium.en automatically on first run from the existing `LOCAL_WHISPER_CACHE_DIR=D:/IRIS/models/.cache`. Download size: ~1.5 GB. Expect a 60–90 second download on first boot after the change.

---

## Changes Required

### `.env` changes (3 lines)
```
LOCAL_MODEL_PATH=D:/IRIS-live/models/Qwen3-8B-Q4_K_M.gguf
LOCAL_WHISPER_MODEL=medium.en
N_GPU_LAYERS=99
N_CTX=8192
```

### `config.py` changes (5 values)
```python
GROQ_MODEL   = "meta-llama/llama-4-scout-17b-16e-instruct"
GEMINI_MODEL = "gemini-2.5-flash"
CLAUDE_MODEL = "claude-sonnet-4-6"
N_GPU_LAYERS = int(os.getenv("N_GPU_LAYERS", "99"))
N_CTX        = int(os.getenv("N_CTX", "8192"))
```

---

## Action Required by User

Before starting IRIS after this upgrade, download the new local model:

```powershell
# Option A — via huggingface-cli (recommended):
pip install huggingface_hub
huggingface-cli download Qwen/Qwen3-8B-GGUF --include "Qwen3-8B-Q4_K_M.gguf" --local-dir "D:/IRIS-live/models/"

# Option B — direct browser download:
# https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf
# Save to: D:\IRIS-live\models\Qwen3-8B-Q4_K_M.gguf
# File size: ~5.0 GB
```

IRIS will automatically download `medium.en` on first boot after the Whisper model change. No manual action needed for that.

---

## Impact on Known Voice Problems

| Problem Reported | Primary Cause | How Upgrade Helps |
|-----------------|--------------|-------------------|
| IRIS assumes instead of asking | 3B model weak instruction adherence | Qwen3 8B follows persona rules much more reliably |
| Mishearing / wrong words | small.en accuracy degradation on noisy input | medium.en ~35% fewer errors on noisy speech |
| Persona drift after long sessions | N_CTX=4096 truncating conversation context | N_CTX=8192 keeps 2x more history in context |
| Cloud fallback slow | 70B Groq model latency | Llama 4 Scout: 2.3x faster at 460 tok/s |
| Gemini fallback (June) | Deprecated model | Fixed before shutdown |

---

*Report generated: 2026-04-07 | IRIS v5.2.5-STABLE*
