# IRIS External Review Pack

Updated: 2026-03-25
Repo branch: `codex/iris-v2-cognitive-core`
Platform: Windows desktop, Python 3.11, local-first assistant with GUI + voice + desktop actions

## 1. What IRIS Is Supposed To Become

IRIS is intended to be a local-first autonomous desktop AI assistant with a strong technical core, low bandwidth requirements, system-level usefulness, and a distinctive identity.

The user expectation is not a generic chatbot. The target is closer to a private Jarvis-style chief-of-staff and operator layer, but without weaponization:

- public identity: `IRIS`
- internal architecture codename: `Aletheia`
- local-first by default, online only when necessary
- lightweight enough to run well on a normal laptop
- system-resource aware so it does not thrash the machine
- able to think, plan, act, inspect the desktop, click, type, open apps, and manage packages
- able to speak naturally, respond with some wit/humor/sarcasm, and feel more alive than a flat assistant
- visually distinctive: sky-blue/futuristic orb, transparent feel, rotating/globe-like motion, natural communication cues
- stronger cognition for technical reasoning, analytical decision support, and “chief of staff” style assistance
- `Overdrive` remains available for critical tasks, but is not meant to bypass hard safety constraints

The user has explicitly pushed the project toward:

- local system resources first for time, location, machine facts, speech, and general responsiveness
- reduced online dependency wherever practical
- accurate live data only where local data is not enough
- faster voice response, better speech pickup, and more human personality
- robust safety controls, including immediate terminate/shutdown behavior
- an assistant that feels exceptional rather than generic

## 2. Current High-Level Architecture

Key entry points and modules:

- `main.py`: terminal/text entry point
- `iris_gui.py`: PySide desktop shell, floating orb, tray integration, startup greeting, voice standby loop
- `core/engine.py`: runtime orchestrator and shared session engine
- `core/brain.py`: cognitive routing, local-vs-cloud choice, short-response shaping, personality helpers
- `core/voice.py`: microphone selection, wake listening, command transcription, TTS playback, voice state handling
- `core/environment.py`: time/location/weather routing with local-first context and weather cache
- `core/system_intel.py`: local machine facts like battery, hostname, OS, memory, storage, network
- `core/resource_guard.py`: prevents aggressive local features when memory or battery conditions are poor
- `core/executor.py`, `core/security.py`, `core/desktop_control.py`: action planning, safety gating, clicks/typing/window interactions/package management
- `core/council.py`, `core/dialog_manager.py`, `core/self_model.py`, `core/diagnostics.py`, `core/copilot.py`: higher-order reasoning/orchestration scaffolding
- `core/visual_identity.py`: orb/icon identity

Local model routing:

- Ollama local models are the primary brain path
- current expected models: `phi3.5`, `llama3.1:8b`, `deepseek-r1:8b`
- cloud APIs remain available as fallback: Groq, Gemini, Claude, Perplexity

Voice stack:

- wake-word listening and command listening are separated
- command STT currently prefers Groq for accuracy, with local and Google fallback paths still present
- TTS currently prefers Edge for normal speech, but uses a fast local route for wake acknowledgements
- mic/device selection tries to avoid bad Bluetooth hands-free profiles and choose a cleaner microphone path

Environment/data strategy:

- system time and machine facts are local-first
- current location uses Windows/system location when possible
- weather uses live data, but caches last-known results locally instead of hallucinating

## 3. What Has Already Been Implemented

Core product shape:

- working desktop GUI shell with tray presence and floating orb mode
- terminal mode and reusable engine
- local-first routing and local model use through Ollama
- desktop actions including clicks, typing, active-window inspection, window targeting, and package-management actions
- safety contract scaffolding, audit logging, blocked action handling, and approval-style flows
- `Overdrive` runtime mode scaffold

Voice and UX work already attempted:

- adaptive mic recalibration
- better mic-device selection for the Turtle Beach headset/mic family
- startup greeting support
- more varied/wittier short responses
- terminate command for immediate exit
- wake-word normalization for common STT mishears like `it`, `eris`, `airis`
- dedicated standby state so the orb does not flap between `idle` and `listening` every wake timeout
- faster local wake acknowledgement path to reduce post-wake delay

Local-first data/system work:

- local machine-state answers for battery, memory, storage, hostname, OS, network
- local-first time and location routing
- weather caching with explicit “last synced” fallback
- resource guardrails so local-heavy behavior can back off under low-memory/low-battery conditions

External collaboration work:

- Perplexity bridge implemented as the preferred external review path
- Claude bridge retained as a fallback path

Visual work:

- new futuristic app icon created and wired into runtime + packaging
- orb visuals already improved from baseline

Verification work:

- smoke tests exist for single-session flow, GUI shell, voice standby, live-data cache path, local-first routing, STT selection, mic selection, personality style, and wake alias normalization

## 4. What Is Still Not Good Enough

This is the most important section.

The project is functional, but the user still does not trust the voice experience yet. The biggest pain points now are:

- wake-word recognition is still unstable in real use
- some wake mishears still normalize poorly or trigger too loosely
- command transcription often does not match what the user actually said
- response timing still feels off in live use
- spoken acknowledgements and greeting timing have needed repeated tuning
- the user reports some spoken output is either delayed or not clearly heard

There is also a product-level gap between “many features exist” and “IRIS feels coherent and elite”:

- personality exists, but still needs stronger consistency and better taste
- orb direction is better, but not yet fully at the “exceptional” bar the user wants
- autonomy and approval boundaries still need a cleaner operating model
- more end-to-end voice verification is needed against real user speech, not just smoke tests
- project cleanup and repo hygiene still lag behind implementation velocity

## 5. Current Product Direction / Non-Negotiables

These are the core direction constraints that should shape all future advice:

- keep IRIS local-first where possible
- reduce online dependency instead of increasing it casually
- prefer system resources and local infrastructure when they can do the job well
- cloud is acceptable as fallback or where local capability is genuinely insufficient
- do not build something bloated, bandwidth-heavy, or laptop-hostile
- do not lose the futuristic/original identity in exchange for generic “assistant app” patterns
- preserve strong technical/operator capabilities
- preserve safety controls even while improving autonomy
- treat voice as first-class; voice quality is not a side issue

## 6. Relevant Current Files For Review

If you are reviewing architecture or implementation, start here:

- `brief.md` equivalent context lives in `ai-collab/brief.md`
- `README.md`
- `SAFETY_CONTRACT.md`
- `config.py`
- `iris_gui.py`
- `main.py`
- `core/engine.py`
- `core/brain.py`
- `core/voice.py`
- `core/environment.py`
- `core/system_intel.py`
- `core/resource_guard.py`
- `core/executor.py`
- `core/security.py`
- `core/desktop_control.py`
- `core/visual_identity.py`
- `tools/smoke_single_session.py`
- `tools/smoke_gui_shell.py`
- `tools/smoke_voice_session.py`
- `tools/smoke_live_data.py`
- `tools/smoke_local_first.py`
- `tools/smoke_stt_selection.py`
- `tools/smoke_mic_selection.py`
- `tools/smoke_personality_style.py`
- `tools/smoke_wake_alias.py`
- `tools/perplexity_bridge.py`

## 7. What Feedback Is Needed Most

Please do not give shallow praise. The most useful response is a high-signal critique with priorities.

Wanted feedback:

1. What should the actual product architecture be from here?
2. What should be simplified, removed, or postponed?
3. What is the cleanest path to a truly reliable voice UX on Windows?
4. What local-first strategy should remain, and what should deliberately move back to cloud fallback?
5. Where are the hidden complexity traps in the current design?
6. How should autonomy, Overdrive, approvals, and safety be framed so the product is powerful but still sane?
7. What should the next 3 implementation milestones be?
8. What should the minimum serious verification suite look like?
9. What would make IRIS feel exceptional rather than like a pile of features?

## 8. Zero-Context Primer For External Reviewers

Assume the reviewer knows nothing about IRIS before reading the prompt.

Important factual context:

- This is not a web app. It is a Windows desktop assistant.
- The core stack is still Python-first.
- The assistant is intended to be private, operator-grade, and local-first rather than a SaaS companion.
- The system is already beyond toy-chatbot stage: it has a GUI shell, local reasoning path, desktop action path, safety layer, and multiple voice/data subsystems.
- The current bottleneck is not “can it do anything?” but “can it become coherent, reliable, premium, and trustworthy?”
- The user values originality, strong technical capability, low bandwidth, reduced cloud dependence, and a futuristic identity.
- The user does not want generic assistant behavior or generic UI.
- The user is specifically sensitive to voice quality, wake behavior, latency, personality/tone, and local-system usefulness.

Recent implementation direction:

- local-first routing increased
- system-resource answers added
- weather/time/location path hardened
- voice device selection improved
- wake handling, standby state, and startup greeting were adjusted
- icon/orb identity was refreshed
- Perplexity became the preferred external review path because the Claude web bridge was flaky

Current reality check:

- The product ambition is strong.
- The architecture is increasingly interesting.
- The voice experience is still not stable enough.
- This project now needs sharper architectural judgment, not just more feature accumulation.

## 9. Copy-Paste Prompt For Claude

```text
I need a high-signal architecture and product critique for a Windows desktop AI assistant project called IRIS.

Please read this carefully and respond like a strong technical/product reviewer, not a cheerleader.

PROJECT GOAL
IRIS is supposed to become a local-first autonomous desktop AI assistant with a Jarvis-like chief-of-staff feel, but without weaponization. It should be technically strong, low-bandwidth, system-aware, voice-capable, visually distinctive, and useful for real desktop work. The public name is IRIS. Aletheia is only the internal codename for the deeper architecture.

NON-NEGOTIABLE PRODUCT DIRECTION
- local-first where possible
- reduced online dependency
- use system resources and local infra first when practical
- cloud only when needed or as fallback
- should not thrash the laptop
- should be strong at technical reasoning and operator-style assistance
- should support desktop actions like clicks, typing, app control, and package management
- should have a futuristic sky-blue orb identity and feel more alive than a generic assistant
- Overdrive should remain for critical tasks, but not bypass hard safety constraints

CURRENT IMPLEMENTATION SHAPE
- Python 3.11 on Windows
- terminal mode plus PySide GUI shell
- local brain routing through Ollama with phi3.5, llama3.1:8b, deepseek-r1:8b
- runtime engine, voice module, cognitive routing, action execution, safety layer, diagnostics, council/self-model layers
- local machine facts, system-first time/location handling, live weather with explicit cache fallback
- desktop shell with tray, floating orb, startup greeting, voice standby
- desktop control, window targeting, click/type actions, package-management actions
- Perplexity bridge as preferred external reviewer path, Claude bridge still available as fallback
- smoke tests exist for GUI, voice standby, STT selection, mic selection, local-first routing, live-data cache path, and more

MAIN CURRENT PROBLEM
The voice experience is still not trustworthy enough in real use.

Observed issues:
- wake word recognition still mishears or overfires
- command transcription often does not match what the user actually said
- wake acknowledgement and command-listen timing have needed repeated tuning
- some spoken output feels delayed or not clearly audible
- the product has many features, but still risks feeling like a collection of systems rather than one elite coherent assistant

CURRENT DESIGN AREAS
- main.py
- iris_gui.py
- core/engine.py
- core/brain.py
- core/voice.py
- core/environment.py
- core/system_intel.py
- core/resource_guard.py
- core/executor.py
- core/security.py
- core/desktop_control.py
- core/visual_identity.py

WHAT I WANT FROM YOU
1. Give me a blunt high-level assessment of the architecture and product direction.
2. Tell me what should be simplified, removed, or postponed.
3. Propose the best next 3 milestones.
4. Give me a serious plan for making the Windows voice experience reliable.
5. Call out hidden complexity traps, especially around local-first, voice, autonomy, and safety.
6. Tell me what makes this feel exceptional vs generic, and what is still missing.
7. Recommend a clean product boundary for Overdrive, approvals, and autonomous actions.

Please structure your answer as:
- Executive assessment
- Top risks
- What to cut or defer
- Recommended next 3 milestones
- Voice strategy
- Product/UX direction
- Verification strategy

Do not be vague. Prioritize practical decisions over inspirational language.
```

## 10. Copy-Paste Prompt For Perplexity

```text
Assume you know nothing about this project before reading this prompt.

I need a research-backed critique and recommendation set for a Windows desktop AI assistant project called IRIS.

Please use web research where helpful, especially for:
- Windows voice/STT/TTS best practices
- local-first assistant architecture patterns
- desktop automation safety patterns
- useful open-source components or design references

PROJECT GOAL
IRIS is meant to become a local-first autonomous desktop AI assistant with a Jarvis-like chief-of-staff feel, minus weaponization. It should be low-bandwidth, technically strong, voice-first, system-aware, capable of desktop actions, and visually distinctive.

NON-NEGOTIABLE DIRECTION
- local-first where possible
- reduced online dependency
- system resources first where practical
- cloud only when needed or as fallback
- should not overload the laptop
- should support desktop actions, package management, and operator-style tasks
- should feel exceptional, not generic
- Overdrive remains for critical tasks but should not bypass hard safety constraints

CURRENT IMPLEMENTATION SHAPE
- Windows + Python 3.11
- terminal mode and PySide desktop GUI
- Ollama local models as primary brain path
- cognitive engine, memory, diagnostics, action execution, safety layer, voice module
- local machine facts and local-first environment routing
- weather uses live data with cached fallback
- GUI shell includes floating orb, tray, voice standby, and startup greeting
- package management and desktop control actions already exist
- Perplexity bridge and Claude fallback bridge also exist
- key modules include:
  - main.py
  - iris_gui.py
  - core/engine.py
  - core/brain.py
  - core/voice.py
  - core/environment.py
  - core/system_intel.py
  - core/resource_guard.py
  - core/executor.py
  - core/security.py
  - core/desktop_control.py
  - core/visual_identity.py

MAIN CURRENT PROBLEM
Voice UX is still unstable in real-world use:
- wake word recognition is not consistently reliable
- command transcription quality is still poor for the actual user
- TTS/listen timing still needs tuning
- some spoken output is unclear or delayed
- the user also wants the assistant to feel more alive, witty, and premium, without becoming cheesy or unreliable

WHAT I WANT FROM YOU
1. Research and recommend the best architecture direction for a local-first Windows assistant like this.
2. Identify what should stay local and what should intentionally use cloud fallback.
3. Recommend a strong voice stack strategy for wake word, command STT, and TTS on Windows.
4. Suggest specific open-source tools/libraries/projects worth studying or integrating.
5. Give a realistic roadmap for making this feel premium and reliable.
6. Flag safety, autonomy, and desktop automation risks.
7. Suggest a verification strategy that goes beyond smoke tests.
8. Tell me what should be cut, simplified, or postponed so the project does not turn into a fragile pile of subsystems.
9. Recommend whether some currently local features should deliberately remain cloud-assisted for quality reasons.

Please return:
- A concise executive summary
- A prioritized recommendations list
- Specific architecture changes
- Specific voice-stack recommendations
- Open-source/project references
- Risks and tradeoffs
- A recommended next-milestone plan

Use citations/links where relevant, and bias toward practical recommendations instead of generic AI-assistant commentary.
```
