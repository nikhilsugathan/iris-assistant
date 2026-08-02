# IRIS

A personal, multi-provider AI automation assistant built around a safety-first architecture. Every privileged action passes through explicit approval gates, gets written to a rotating audit log, and respects hard security boundaries that hold even in an elevated execution mode.

## Architecture

- **Approval gates** — sensitive actions require explicit confirmation before execution, not silent auto-run.
- **Audit logging** — actions, blocked attempts, and confirmations are written to a rotating log so nothing executes without a trace.
- **Scoped, time-bound permission elevation** — elevated access is granted per task and expires automatically rather than persisting indefinitely.
- **Hard security blocks** — a defined set of blocked commands and sensitive paths cannot be executed regardless of elevation state. No override, no exception.
- **Multi-provider routing** — local inference via llama-cpp-python, with routing to Google Gen AI, Groq, and Anthropic depending on the task.

## Testing

The `tests/` directory covers state machine behavior, executor hardening, and post-remediation audit checks, validating that the security boundaries above actually hold rather than just being described.

## Setup

1. Copy `.env.example` to `.env`
2. Add at least `GROQ_API_KEY`
3. Install dependencies: `pip install -r requirements.txt`

## Run
```
py main.py
```

Text-only mode for local testing:
```
py main.py --text
```

## Status

Active personal project. Voice turn-taking is currently tuned for speed over full realtime interruption support, that's still on the roadmap rather than done.

## Stack

Python, Docker, llama-cpp-python, Groq, Google Gen AI, Anthropic
