# IRIS

IRIS is the public-facing identity.

This build is now local-first, voice-capable, and includes a desktop GUI shell with a futuristic live visualization.

## Current Shape
- Local-first brain routing through Ollama: `phi3.5`, `llama3.1:8b`, `deepseek-r1:8b`
- Cognitive routing layer: self-model, dialog manager, council, diagnostics
- Autonomous action handling with security gating
- Voice output with state-aware playback improvements
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

## Notes
- If Ollama is running, IRIS can function even without cloud API keys.
- If you want cloud fallback, keep your `.env` file available.
- `Aletheia` remains an internal codename in the architecture, but the application presents itself simply as `IRIS`.
