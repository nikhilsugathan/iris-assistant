# IRIS Ultra Low Latency

This build prioritizes faster voice turn-taking over long answers.

## What changed
- Faster default brain: `llama-3.1-8b-instant` on Groq
- Shorter voice replies by default
- Less memory context in live conversation
- Faster mic end-of-speech settings
- TTS caches generated audio files for repeated phrases
- Text mode is silent by default to avoid fake voice latency during terminal testing

## Setup
1. Copy `.env.example` to `.env`
2. Add at least `GROQ_API_KEY`
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

To force speech even in `--text` mode, set:
```bash
set SPEAK_IN_TEXT_MODE=true
```

## Honest note
This is still not a true realtime voice agent. For genuinely human interruptible conversation, you need a streaming STT/TTS stack or a realtime voice API.
