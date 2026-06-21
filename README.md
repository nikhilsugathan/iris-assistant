# IRIS Ultra Low Latency

IRIS is a private desktop assistant focused on fast voice turn-taking, concise answers, and local-first operation where possible.

## Current runtime notes

- Default cloud brain/STT path is Groq when configured.
- Local llama-cpp remains available when a compatible GGUF model path is configured.
- Edge-TTS is the default low-friction voice path; Piper remains available as a local TTS option.
- Text mode is silent by default so terminal testing does not queue audio.
- Runtime memory, session archives, logs, local models, and local assistant settings are ignored by Git.

## Setup

1. Create a local `.env` file in the repo root.
2. Add the provider keys and runtime settings you use.
3. Install packages:

```bash
pip install -r requirements.txt
```

## Run

```bash
py main.py
```

For silent keyboard testing:

```bash
py main.py --text
```

To force speech even in `--text` mode:

```bash
set SPEAK_IN_TEXT_MODE=true
```

## Voice stability note

Short replies now use a runtime voice-stability patch that creates a fresh speech stop-event after idle turns and registers Edge-TTS prefetch before the speech worker consumes the queue. This reduces missing or broken audio after light interactions.

## Honest note

This is still not a true realtime voice agent. For genuinely human interruptible conversation, use a streaming STT/TTS stack or a realtime voice API.
