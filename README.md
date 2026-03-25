# IRIS

IRIS is the public-facing identity.

This build is now local-first, voice-capable, and includes a desktop GUI shell with a futuristic live visualization.

## Canonical Runtime
- This `v2` runtime is the actively hardened architecture for IRIS.
- The shared runtime in `core/engine.py`, `iris_gui.py`, and `main.py` is the path being stabilized and extended.
- Older branch history and legacy flows should be treated as superseded once this runtime is merged forward.

## Current Shape
- Local-first brain routing through Ollama: `phi3.5`, `llama3.1:8b`, `deepseek-r1:8b`
- Local system-intel routing for machine facts like time, location, battery, storage, memory, and network state
- Hybrid voice stack: Piper local neural voice rollout, Windows system voices, and local/cloud STT fallbacks
- Local resource guardrails so offline features back off when memory is tight or battery is low
- Weather caching with last-synced fallback so offline weather answers stay explicit instead of guessed
- Cognitive routing layer: self-model, dialog manager, council, diagnostics
- Autonomous action handling with security gating
- Voice output with state-aware playback improvements
- Focus/work-session workflow with live status and timed completion reminders
- Desktop shell in `iris_gui.py`
- Floating orb mode, tray presence, and launch-at-sign-in support
- Automated Windows build workflow on git push

## Install
```bash
py -3 -m pip install -r requirements.txt
```

Optional build tooling for local packaging:
```bash
py -3 -m pip install pyinstaller
```

## Run
Terminal mode:
```bash
py -3 main.py --text
```

Desktop shell:
```bash
py -3 iris_gui.py
```

Optional local Piper voice download:
```powershell
powershell -ExecutionPolicy Bypass -File tools/install_piper_voice.ps1
```

## Windows Build
The repo now includes a GitHub Actions workflow at `.github/workflows/build-windows.yml`.

On every push to `main` or `codex/*`, GitHub will build a Windows desktop artifact and upload it.

For a local build:
```bash
py -3 tools/generate_app_icon.py
py -3 -m PyInstaller --noconfirm --clean --windowed --onefile --name IRIS --icon assets/iris_aletheia.ico --collect-all PySide6 --hidden-import edge_tts --hidden-import pygame --hidden-import speech_recognition iris_gui.py
```

The easiest local packaged app is generated in:
```bash
dist\IRIS.exe
```

## Stability Soak
To run the stabilized `v2` smoke/soak matrix in one shot:
```bash
py -3 tools/soak_v2_stability.py
```

## Notes
- If Ollama is running, IRIS can function even without cloud API keys.
- System resources are used first where possible; cloud APIs remain available as fallbacks instead of the default.
- Local-first is safety-bounded: if the laptop is low on free memory or low on battery, IRIS can fall back instead of pushing harder.
- If you want cloud fallback, keep your `.env` file available.
- `Aletheia` remains an internal codename in the architecture, but the application presents itself simply as `IRIS`.
