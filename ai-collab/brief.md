# IRIS Research Brief

## Project

IRIS is a Windows-focused local-first assistant with:

- shared runtime in `core/engine.py`
- terminal entry in `main.py`
- desktop GUI shell in `iris_gui.py`
- local/cloud brain routing in `core/brain.py`
- action execution in `core/executor.py`
- voice stack in `core/voice.py`
- persistent transcript memory in `core/memory.py`

## Current Request

The user wants a thorough feasibility review before implementation work begins on a more proactive, more logically grounded, more "Cody-like" IRIS.

The user specifically wants:

- stronger reasoning style
- clearer communication
- more proactive behavior
- more cognitive discipline
- a realistic design that uses local system resources well

## Important Constraint

The goal is not to claim IRIS can become a copy of Cody's hidden internals.

The real target is to reproduce practical behaviors:

- calmer, clearer communication
- short reasoning summaries
- verification after actions
- stronger memory of preferences/goals
- bounded proactivity
- local-first orchestration with optional escalation

## Existing Roadmap

See `IRIS_COGNITIVE_ROADMAP.md` for the proposed phased plan.

## What Reviewers Should Assess

1. Is the roadmap feasible on top of the current IRIS architecture?
2. What is missing technically?
3. What parts are too ambitious for the current local-first stack?
4. What should be implemented first for the biggest practical gain?
5. What risks or regressions are most likely?
