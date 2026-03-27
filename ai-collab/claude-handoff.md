# Claude Handoff

## Your Role

Review the IRIS codebase as an architecture and product reviewer.

You are not being asked to invent a new greenfield assistant. You are being asked to evaluate whether the current IRIS runtime can be evolved toward a more proactive, more logically grounded, more Cody-like assistant.

## Focus

Please evaluate:

1. Feasibility of the roadmap in `IRIS_COGNITIVE_ROADMAP.md`
2. What the current architecture already supports
3. What is still missing
4. Which parts should be implemented first
5. What design risks or regressions are likely

## Important Context

The target is to reproduce useful outward behaviors, not private OpenAI internals.

The most important desired upgrades are:

- clearer reasoning summaries
- better communication policy
- goal/preference memory
- verification/reflection after actions
- bounded proactivity

## Files To Inspect First

- `IRIS_COGNITIVE_ROADMAP.md`
- `README.md`
- `core/engine.py`
- `core/brain.py`
- `core/dialog_manager.py`
- `core/self_model.py`
- `core/council.py`
- `core/executor.py`
- `core/memory.py`
- `core/environment.py`
- `core/resource_guard.py`
- `core/voice.py`
- `iris_gui.py`

## Desired Output

Please answer in this order:

1. Feasibility verdict
2. What is already present in the architecture
3. What is missing or weak
4. Biggest risks
5. Recommended phased implementation order
6. What you would cut, simplify, or delay

## Tone

Be direct and practical. Prefer findings and recommendations over recap.
