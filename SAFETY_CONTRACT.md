# IRIS Safety Contract

This document defines the default execution boundaries for IRIS before wider autonomy or Overdrive expansion.

The intent is simple:

- prevent unsafe or irreversible behavior
- make approval boundaries explicit
- keep high-confidence local assistance fast

Session approval memory is a product goal, but not fully implemented yet. Until it is, `CONFIRM_ONCE` should be treated as "ask explicitly before execution."

## NEVER

These actions are hard blocks and should not be runnable through normal or Overdrive flows unless this contract is deliberately changed.

- exploit tooling or attack frameworks such as Metasploit-style payload flows
- credential dumping or password/hash extraction
- ransomware-like or mass-encryption behavior
- destructive mass-deletion or disk-formatting behavior
- privilege-escalation and UAC-bypass techniques
- known malware/phishing destinations
- illegal or clearly harmful actions
- private data exfiltration or covert network export without explicit, narrow user intent
- silent removal or weakening of core operating-system protections without a narrowly defined recovery workflow

## CONFIRM_ONCE

These actions require explicit user approval before execution. Long-term, IRIS may remember approval for the current session only.

- installs and uninstalls
- admin-required commands
- registry changes
- service creation, deletion, start, or stop
- firewall, antivirus, Defender, proxy, certificate, or hosts-file changes
- network reconfiguration
- external downloads from unverified or indirect sources
- browser actions that could submit data, authenticate, or operate on user accounts
- desktop automation actions such as typing, hotkeys, and coordinate-based clicks
- destructive actions against user files, folders, or applications
- any future Overdrive path that changes safety posture, execution speed, or approval behavior

## AUTO

These actions are acceptable for silent or near-silent execution when they stay within normal local assistance boundaries and pass the hard-block rules above.

- answering questions
- local reasoning and planning
- safe file creation in user space
- safe folder creation in user space
- opening local applications
- opening trusted URLs
- local status checks and diagnostics
- read-only inspection tasks
- low-risk desktop assistance that does not alter security posture or remove user data

## Overdrive Placeholder

Overdrive is not allowed to weaken `NEVER`.
Overdrive is a named execution mode for critical or high-attention work.

Current contract:

- explicit activation only by user voice/text command or GUI control
- deeper reasoning and more visible operator feedback
- stronger audit logging and review posture
- no widening of `AUTO`
- no bypass of `CONFIRM_ONCE`
- no weakening of `NEVER`
- automatic deactivation after task completion or extended idle time

Still deferred:

- batching multiple `CONFIRM_ONCE` actions under one approval
- any permission widening based on trust or learned patterns
- any self-activation without the user explicitly turning Overdrive on
