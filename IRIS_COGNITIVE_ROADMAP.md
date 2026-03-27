# IRIS Cognitive Roadmap

## Goal

Make IRIS feel more proactive, more logically grounded, and more supportive in the way she communicates, while staying realistic about local hardware and the current `v2` architecture.

The target is not "clone Cody exactly."

The realistic target is:

- Cody-like communication style
- stronger planning and verification loops
- better memory of goals, preferences, and unfinished work
- more initiative, but only when helpful and safe
- local-first behavior with optional cloud escalation

## What Can Be Copied vs What Cannot

### What We Can Realistically Recreate

- calm, structured, supportive communication
- explicit short reasoning summaries
- uncertainty handling
- self-checking before actions
- multi-step planning and follow-through
- proactive suggestions based on context
- memory-backed continuity
- tool-using behavior with safety gates

### What We Cannot Directly Copy

- Cody's internal model weights
- hidden internal reasoning implementation
- OpenAI-hosted orchestration infrastructure
- large-scale training and safety systems behind the model

So the right strategy is to reproduce the visible behaviors and decision patterns, not the private internals.

## Current IRIS Architecture

IRIS already has strong building blocks:

- runtime/orchestration: `core/engine.py`
- dialogue routing: `core/dialog_manager.py`
- self-state tracking: `core/self_model.py`
- multi-perspective packet shaping: `core/council.py`
- persistent memory: `core/memory.py`
- action execution: `core/executor.py`
- environment and system sensing: `core/environment.py`, `core/system_intel.py`
- resource-aware local/cloud fallback: `core/resource_guard.py`
- guided assistance mode: `core/copilot.py`

This means IRIS is already closer to an agent runtime than a simple chatbot.

## Gap Between Current IRIS and Target IRIS

### Current Strengths

- local-first routing works
- voice stack is solid
- desktop actions and focus workflows exist
- safety and approval gates exist
- memory persists between sessions
- the runtime already separates chat, action, diagnostics, and copilot modes

### Main Missing Pieces

- durable goals and task graph
- proactive trigger engine
- explicit reflection loop after actions
- preference memory separate from chat history
- reasoning-summary renderer
- stronger "why I think this" communication policy
- initiative budget so IRIS does not become noisy

## Target Architecture

### 1. Social Layer

Purpose: make IRIS communicate like a thoughtful, steady collaborator.

Behaviors:

- warm but not overly theatrical
- concise by default
- explains decisions clearly
- states uncertainty directly
- escalates gently when risk is high

Implementation shape:

- add a response-style policy object
- add response transforms for tone, pacing, and structure
- keep "reasoning summary" separate from raw internal processing

### 2. Cognitive Control Loop

Purpose: make IRIS behave less like "input -> answer" and more like "observe -> reason -> act -> verify -> reflect."

Loop:

1. interpret request
2. classify intent and stakes
3. choose plan depth
4. act or answer
5. verify result
6. reflect on outcome
7. store durable memory if useful

Implementation shape:

- expand `engine + dialog_manager + executor`
- introduce post-action verification policy
- introduce failure recovery policy

### 3. Working Memory and Long-Term Memory

Purpose: help IRIS carry context the way a good collaborator does.

Split memory into:

- conversation memory: what was said
- preference memory: how the user likes things done
- goal memory: active tasks and commitments
- episodic memory: important completed events
- environment memory: recurring device/location/system patterns

Implementation shape:

- keep `core/memory.py` for transcript history
- add separate stores for preferences/goals
- store confidence and freshness, not just raw text

### 4. Proactivity Engine

Purpose: let IRIS speak first only when it adds value.

Trigger examples:

- a focus session ended
- a background task failed
- a repeated problem pattern appears
- the user usually performs step B after step A
- the system is low on resources and local mode should adapt

Rules:

- prefer silent preparation over unsolicited speaking
- only interrupt for high-value cases
- support quiet, normal, and proactive initiative modes

### 5. Reasoning Summary Layer

Purpose: make IRIS feel logically grounded without pretending to expose hidden chain-of-thought.

Output pattern:

- answer
- short rationale: "I’m suggesting this because..."
- uncertainty if relevant
- next step or confirmation ask

This is the safest way to make IRIS sound more like Cody.

### 6. Skill and Capability Layer

Purpose: give IRIS bounded specialist behaviors instead of one giant monolithic reasoning path.

Candidate skills:

- desktop operator
- file/workspace helper
- system diagnostics
- planning coach
- focus coach
- environment intel
- note summarizer

## Recommended Local-First Resource Profile

Do not try to reproduce a frontier hosted agent with one oversized local model.

Use a layered system instead.

### Suggested Runtime Mix

- fast chat / style / lightweight planning: `phi3.5`
- general assistant default: `llama3.1:8b`
- deeper local reasoning / verifier role: `deepseek-r1:8b`
- local STT: faster-whisper with dynamic profile
- local TTS: Piper primary, system/Edge fallback

### Why This Is Better

- lower latency
- less VRAM and RAM pressure
- clearer role separation
- easier fallback behavior
- better real-world responsiveness on a normal workstation

## Phased Build Plan

## Phase 1: Cody-Like Communication

Goal: match the outward style first.

Deliverables:

- response style policy
- short reasoning-summary formatter
- confidence and uncertainty phrases
- gentle escalation phrases for risky actions
- user-preference hooks for verbosity and tone

Expected outcome:

IRIS sounds more like a thoughtful collaborator even before deeper cognition is added.

## Phase 2: Goal and Preference Memory

Goal: move beyond transcript memory.

Deliverables:

- `user_preferences.json`
- `active_goals.json`
- memory write rules: only store durable information
- retrieval rules: fetch relevant preferences before reply generation

Expected outcome:

IRIS remembers how you like to work and what is still in progress.

## Phase 3: Reflection and Verification

Goal: make actions more trustworthy.

Deliverables:

- post-action verifier
- failure diagnosis pass
- explicit "worked / uncertain / failed" result labels
- retry policies for safe actions

Expected outcome:

IRIS feels more careful and more competent after taking actions.

## Phase 4: Proactive Initiative

Goal: let IRIS help before being asked, without becoming annoying.

Deliverables:

- trigger registry
- initiative policy with rate limits
- quiet mode / normal mode / proactive mode
- contextual nudges for focus, background work, and repeated routines

Expected outcome:

IRIS starts behaving like a real assistant rather than a passive responder.

## Phase 5: Multi-Role Internal Cognition

Goal: improve reasoning quality without massive model size.

Deliverables:

- planner role
- verifier role
- communicator role
- optional conflict-resolution pass when confidence is low

Expected outcome:

IRIS gets a lightweight internal "team" model using your current local stack.

## Best Match to Cody

If the target is "feel like Cody," the highest-value features are:

1. concise supportive style
2. reasoning summaries
3. explicit uncertainty
4. verification after actions
5. memory of preferences and ongoing goals
6. proactive but polite suggestions

Those will produce the biggest perceived jump, even more than adding a larger local model.

## Recommended Next Implementation Order

1. Add a response-policy layer for tone, structure, and reasoning summaries.
2. Add durable preference and goal memory separate from conversation history.
3. Add post-action verification and reflection.
4. Add a bounded proactivity engine with user-controlled initiative levels.

## Important Design Rule

Do not make IRIS "proactive" by simply having her talk more.

Make her proactive by:

- noticing useful patterns
- preparing good suggestions
- surfacing them at the right time
- staying concise and context-aware

That is much closer to how a strong assistant actually feels in use.

## Final Recommendation

Yes, IRIS can become substantially more proactive and more cognitively disciplined using the architecture already in this repo.

The best path is:

- imitate Cody's outward behavior
- strengthen orchestration, memory, and verification
- keep local models specialized and resource-aware
- add initiative gradually under strict policy controls

That will get IRIS much closer to "Cody-like" in practice without trying to recreate infrastructure that only exists in hosted frontier systems.
