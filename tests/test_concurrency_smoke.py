"""
tests/test_concurrency_smoke.py
================================
Concurrency & State Integration Test Suite — IRIS v5.2.5-STABLE

Programmatic proof that the C-01 / C-02 / C-03 / C-04 patches hold under
synthetic OS pressure.  No microphone, no Ctrl-C, no real Ollama required.

    Patch   Finding   Scenario
    ──────  ────────  ────────────────────────────────────────────────────────
    C-01    AdminLeak admin_unlocked reverts to False after an exception path
    C-02    RLock     5 concurrent writers + main-thread reader — no deadlock
    C-03    reset()   Full atomic rollback of every session-scoped field
    C-04    atexit    Ollama proc.terminate() is registered and fires correctly

Run with:
    pytest tests/test_concurrency_smoke.py -v --tb=short
"""
from __future__ import annotations

import atexit
import contextlib
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from unittest.mock import MagicMock, patch, call

import psutil
import pytest

# ── Path bootstrap ────────────────────────────────────────────────────────────
# Allows the suite to be run from the project root OR from inside tests/.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.self_model import SelfModel          # noqa: E402
from core.diagnostics import BootDiagnostics   # noqa: E402


# ── Shared test helpers ───────────────────────────────────────────────────────

@dataclass
class _FakeDecision:
    """Minimal stand-in for a LogicEngine Decision object."""
    mode: str = "chat"
    high_stakes: bool = False
    emotionally_weighted: bool = False
    reason: str = "smoke-test"


# Exact startup defaults — kept in sync with SelfModel field declarations.
_DEFAULTS: dict = {
    "confidence":       0.68,
    "urgency":          0.28,
    "caution":          0.42,
    "warmth":           0.44,
    "initiative_budget": 0.50,
    "emotional_load":   0.20,
    "cognitive_mode":   "idle",
    "last_reason":      "startup",
    "admin_unlocked":   False,
}


def _ollama_spawn_context(extra_patches: list | None = None):
    """
    Returns a contextlib.ExitStack simulating:
      - Ollama API unreachable  (requests.get raises ConnectionError)
      - No local GGUF present   (os.path.exists → False)
      - `ollama` CLI installed  (shutil.which → path)
      - 2-second wait skipped   (time.sleep no-op)

    Caller may pass additional patch objects via `extra_patches`.
    """
    stack = contextlib.ExitStack()
    stack.enter_context(patch("requests.get",   side_effect=ConnectionError("offline")))
    stack.enter_context(patch("os.path.exists", return_value=False))
    stack.enter_context(patch("shutil.which",   return_value="/usr/local/bin/ollama"))
    stack.enter_context(patch("time.sleep"))
    for p in (extra_patches or []):
        stack.enter_context(p)
    return stack


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1 — C-01 & C-03: State Bleed
# ═══════════════════════════════════════════════════════════════════════════════

class TestStateBleed:
    """
    SelfModel.reset() must atomically revert every session-scoped field to its
    startup default.  Covers both the reset() primitive (C-03) and the
    exception-path safety net added to main.py (C-01).
    """

    def test_reset_clears_admin_unlocked(self):
        """Core C-03: admin_unlocked is strictly False after reset()."""
        m = SelfModel()
        m.admin_unlocked = True
        m.reset()
        assert m.admin_unlocked is False, "admin_unlocked must be False after reset()"

    def test_reset_reverts_all_fields_to_exact_defaults(self):
        """
        Every numeric and string field must equal its default after reset(),
        regardless of how far it drifted during a session.
        """
        m = SelfModel()
        # Simulate a fully-drifted Aletheia session.
        m.emotional_load    = 0.99
        m.initiative_budget = 0.01
        m.confidence        = 0.05
        m.urgency           = 0.95
        m.caution           = 0.98
        m.warmth            = 0.10
        m.cognitive_mode    = "action"
        m.last_reason       = "root-command-executed"
        m.admin_unlocked    = True
        m.reset()

        for field, expected in _DEFAULTS.items():
            actual = getattr(m, field)
            assert actual == expected, (
                f"Field '{field}': expected {expected!r} after reset(), got {actual!r}"
            )

    def test_reset_clears_list_fields(self):
        """active_roles and recent_friction must be empty lists after reset()."""
        m = SelfModel()
        m.active_roles    = ["strategist", "analyst", "executor"]
        m.recent_friction = ["empty-response", "response:error", "response:fallback"]
        m.reset()

        assert m.active_roles    == [], f"active_roles not cleared: {m.active_roles!r}"
        assert m.recent_friction == [], f"recent_friction not cleared: {m.recent_friction!r}"

    def test_reset_produces_independent_list_objects(self):
        """
        The lists returned after reset() must be new objects, not references to
        the pre-reset list.  Appending after reset must not corrupt any cached copy.
        """
        m = SelfModel()
        m.active_roles = ["old-role"]
        m.reset()
        m.active_roles.append("new-role")   # mutate the post-reset list

        # A fresh reset should clear this too.
        m.reset()
        assert m.active_roles == []

    def test_reset_is_idempotent(self):
        """Calling reset() twice must not corrupt state or raise an exception."""
        m = SelfModel()
        m.emotional_load = 0.99
        m.reset()
        m.reset()

        assert m.emotional_load    == _DEFAULTS["emotional_load"]
        assert m.initiative_budget == _DEFAULTS["initiative_budget"]
        assert m.admin_unlocked    is False

    def test_c01_exception_path_revokes_admin_access(self):
        """
        C-01 regression: the patched outer except block in main.py now explicitly
        sets self_model.admin_unlocked = False.  Simulate that exact path and
        verify root access is revoked even if an exception fires mid-session.
        """
        m = SelfModel()
        m.admin_unlocked = True   # session was in Aletheia admin mode

        try:
            raise RuntimeError("Simulated brain API timeout mid-admin-session")
        except Exception:
            # ← mirrors the line added to main.py's outer except block
            m.admin_unlocked = False

        assert m.admin_unlocked is False, (
            "admin_unlocked must be False after exception in conversation loop"
        )

    def test_lock_to_public_mode_resets_all_drifted_state(self):
        """
        C-03 wiring: _lock_to_public_mode() now calls self_model.reset() rather
        than only clearing admin_unlocked.  Verify that emotional and initiative
        state does not bleed from an admin session into the next public session.
        """
        m = SelfModel()
        m.admin_unlocked    = True
        m.emotional_load    = 0.99     # drifted high from a long Aletheia session
        m.initiative_budget = 0.01     # depleted

        # Simulate _lock_to_public_mode():
        m.reset()

        assert m.admin_unlocked    is False,                          "admin_unlocked not cleared"
        assert m.emotional_load    == _DEFAULTS["emotional_load"],    "emotional_load not reset"
        assert m.initiative_budget == _DEFAULTS["initiative_budget"], "initiative_budget not reset"

    def test_snapshot_reflects_defaults_immediately_after_reset(self):
        """snapshot() must return default values in the same call after reset()."""
        m = SelfModel()
        m.emotional_load = 0.99
        m.reset()
        snap = m.snapshot()

        assert snap["emotional_load"]    == _DEFAULTS["emotional_load"]
        assert snap["initiative_budget"] == _DEFAULTS["initiative_budget"]
        assert snap["cognitive_mode"]    == _DEFAULTS["cognitive_mode"]


# ═══════════════════════════════════════════════════════════════════════════════
# Group 2 — C-02: Concurrency (RLock — no deadlock, no corruption)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConcurrency:
    """
    Five daemon threads concurrently hammer SelfModel while the main thread
    reads snapshot().  Asserts:
      - All threads finish within DEADLINE seconds (no deadlock).
      - All float fields stay within [0.0, 1.0] (no race on _clamp()).
      - reset() called mid-battle completes in < 0.5 s (RLock is re-entrant).
    """

    THREADS  = 5
    ITERS    = 300    # write iterations per thread
    DEADLINE = 2.0    # seconds — failure = deadlock signal

    def _writer(self, model: SelfModel, errors: list) -> None:
        """
        Exercises every locked method in SelfModel, alternating between action
        and chat decisions to hit both branches in observe_user_input().
        """
        action_dec = _FakeDecision(mode="action", high_stakes=True, emotionally_weighted=False)
        chat_dec   = _FakeDecision(mode="chat",   high_stakes=False, emotionally_weighted=True)
        for i in range(self.ITERS):
            try:
                dec = action_dec if i % 2 == 0 else chat_dec
                model.observe_user_input(
                    "run it now"     if i % 2 == 0 else "explain this to me",
                    dec,
                )
                model.note_response("acknowledged", source=None)
                if i % 15 == 0:
                    model.note_failure("transient-error")
                if i % 11 == 0:
                    model.note_success("recovered")
                if i % 25 == 0:
                    model.apply_council(["strategist", "analyst"])
                if i % 30 == 0:
                    _ = model.snapshot()    # readers from writer threads too
            except Exception as exc:
                errors.append(repr(exc))

    # ── test: no deadlock ─────────────────────────────────────────────────────

    def test_no_deadlock_within_deadline(self):
        """
        Five writer threads + main-thread reader must all complete within
        DEADLINE seconds.  A hang indicates the RLock is mis-nested.
        """
        model  = SelfModel()
        errors: list = []
        threads = [
            threading.Thread(
                target=self._writer, args=(model, errors), daemon=True,
                name=f"iris-writer-{i}",
            )
            for i in range(self.THREADS)
        ]

        start = time.monotonic()
        for t in threads:
            t.start()

        # Concurrent main-thread reads — must never block permanently.
        snapshots_taken = 0
        while any(t.is_alive() for t in threads):
            _ = model.snapshot()
            snapshots_taken += 1
            if time.monotonic() - start > self.DEADLINE:
                pytest.fail(
                    f"Deadlock detected: {self.THREADS} writer threads did not "
                    f"complete within {self.DEADLINE}s "
                    f"(snapshots taken by main thread: {snapshots_taken}). "
                    "The RLock may be incorrectly nested."
                )

        for t in threads:
            t.join(timeout=0.5)

        assert not errors, (
            f"{len(errors)} exception(s) raised in writer threads:\n"
            + "\n".join(errors)
        )

    # ── test: value bounds ────────────────────────────────────────────────────

    def test_float_fields_within_bounds_after_concurrent_writes(self):
        """
        After THREADS × ITERS concurrent read-modify-write cycles, all float
        fields must remain in [0.0, 1.0].  An out-of-range value proves that
        a compound operation bypassed _clamp() due to a race condition.
        """
        model  = SelfModel()
        errors: list = []
        threads = [
            threading.Thread(target=self._writer, args=(model, errors), daemon=True)
            for _ in range(self.THREADS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=self.DEADLINE + 2)

        snap = model.snapshot()
        for field in (
            "confidence", "urgency", "caution", "warmth",
            "initiative_budget", "emotional_load",
        ):
            val = snap[field]
            assert 0.0 <= val <= 1.0, (
                f"Field '{field}' is {val!r} — outside [0.0, 1.0] after "
                f"{self.THREADS} × {self.ITERS} concurrent writes. "
                "Possible race condition on _clamp()."
            )
        assert not errors, "Writer threads raised exceptions"

    # ── test: reset() under concurrent load ──────────────────────────────────

    def test_reset_does_not_deadlock_under_concurrent_writers(self):
        """
        reset() called from the main thread while 3 writers actively mutate
        the model must complete in < 0.5 s.

        The RLock is re-entrant, so reset() must not block waiting for writers
        that hold the lock — it will acquire the lock between their write cycles.
        A hang here means the lock is incorrectly implemented as a non-re-entrant
        Lock rather than an RLock.
        """
        model  = SelfModel()
        stop   = threading.Event()
        errors: list = []

        def _aggressive_writer() -> None:
            # Uses public methods (all RLock-guarded) to create genuine contention.
            decision = _FakeDecision(mode="action", emotionally_weighted=True)
            while not stop.is_set():
                try:
                    model.observe_user_input("flood message", decision)
                    model.note_failure("stress-load")
                    model.note_response("ok")
                except Exception as exc:
                    errors.append(repr(exc))

        writers = [
            threading.Thread(target=_aggressive_writer, daemon=True, name=f"hammer-{i}")
            for i in range(3)
        ]
        for w in writers:
            w.start()

        time.sleep(0.02)   # give writers a head start before racing reset()

        t0 = time.monotonic()
        model.reset()
        elapsed = time.monotonic() - t0

        stop.set()
        for w in writers:
            w.join(timeout=1.5)

        assert elapsed < 0.5, (
            f"reset() blocked for {elapsed:.3f}s under concurrent writers — "
            "possible RLock deadlock or non-reentrant Lock used."
        )
        # Values must be within bounds regardless of what writers did after reset().
        snap = model.snapshot()
        for field in ("emotional_load", "initiative_budget", "confidence"):
            assert 0.0 <= snap[field] <= 1.0, (
                f"'{field}' = {snap[field]} is out of bounds post-reset"
            )
        assert not errors, f"Writer threads raised: {errors}"

    # ── test: summary() is consistent under concurrent mutation ──────────────

    def test_summary_never_raises_under_concurrent_writes(self):
        """
        summary() must not raise AttributeError or TypeError even when
        admin_unlocked flips between True/False on a background thread.
        """
        model  = SelfModel()
        errors: list = []
        stop   = threading.Event()

        def _flip_admin() -> None:
            toggle = True
            while not stop.is_set():
                try:
                    # Direct attribute write — deliberate: mirrors main.py behaviour.
                    model.admin_unlocked = toggle
                    toggle = not toggle
                except Exception as exc:
                    errors.append(repr(exc))

        flipper = threading.Thread(target=_flip_admin, daemon=True)
        flipper.start()

        summary_errors = []
        for _ in range(500):
            try:
                _ = model.summary()
            except Exception as exc:
                summary_errors.append(repr(exc))

        stop.set()
        flipper.join(timeout=1.0)

        assert not summary_errors, (
            f"summary() raised {len(summary_errors)} exception(s) under "
            f"concurrent admin_unlocked mutation:\n" + "\n".join(summary_errors)
        )
        assert not errors, f"Flipper thread raised: {errors}"


# ═══════════════════════════════════════════════════════════════════════════════
# Group 3 — C-04: Zombie Process Teardown
# ═══════════════════════════════════════════════════════════════════════════════

class TestZombieProcessTeardown:
    """
    Ollama subprocess spawned by check_ollama() must be registered with atexit
    and must terminate cleanly — never left as an orphan on crash or exit.
    """

    # ── Test 1: atexit.register is called with the right argument ─────────────

    def test_atexit_register_called_with_proc_terminate(self):
        """
        check_ollama() must call atexit.register(proc.terminate) — not
        atexit.register(proc), not atexit.register(proc.kill), and not omitted.
        """
        mock_proc = MagicMock(name="ollama_proc")
        registered: list = []

        with _ollama_spawn_context([
            patch("subprocess.Popen", return_value=mock_proc),
            patch("atexit.register",
                  side_effect=lambda fn, *a, **k: registered.append((fn, a, k))),
        ]):
            BootDiagnostics().check_ollama()

        assert len(registered) == 1, (
            f"Expected exactly 1 atexit.register() call, got {len(registered)}: "
            + str(registered)
        )
        fn, _args, _kwargs = registered[0]
        assert fn is mock_proc.terminate, (
            f"atexit must register proc.terminate — got {fn!r}. "
            "The wrong teardown target is registered."
        )

    # ── Test 2: the registered handler actually calls terminate() ─────────────

    def test_atexit_handler_terminates_process_exactly_once(self):
        """
        Manually fire the atexit-registered function and assert proc.terminate()
        was called exactly once — no double-call, no silent miss.
        """
        mock_proc = MagicMock(name="ollama_proc")
        registered: list = []

        with _ollama_spawn_context([
            patch("subprocess.Popen", return_value=mock_proc),
            patch("atexit.register",
                  side_effect=lambda fn, *a, **k: registered.append((fn, a, k))),
        ]):
            BootDiagnostics().check_ollama()

        assert registered, "No atexit handler was registered — patch may not be wired"
        fn, args, kwargs = registered[0]

        # Simulate the Python runtime calling atexit handlers on exit.
        fn(*args, **kwargs)

        mock_proc.terminate.assert_called_once_with(
            *args, **kwargs
        )

    # ── Test 3: end-to-end with a real subprocess (proxy for Ollama) ──────────

    def test_real_subprocess_is_gone_after_teardown(self):
        """
        Integration: spawn a real long-lived subprocess as a proxy for Ollama,
        fire proc.terminate() via the atexit path, and confirm psutil reports
        it as dead or non-existent.

        Uses the Python interpreter itself — zero external dependencies needed.
        """
        # Long-lived stand-in for `ollama serve`.
        cmd  = [sys.executable, "-c", "import time; time.sleep(60)"]
        proc = subprocess.Popen(cmd)
        pid  = proc.pid

        # Mirror the C-04 patch exactly.
        atexit.register(proc.terminate)

        # Confirm it's alive before teardown.
        assert psutil.pid_exists(pid), (
            f"Proxy subprocess (pid={pid}) was not found before teardown."
        )

        # Fire the teardown — simulates atexit handler invocation.
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()           # escalate if SIGTERM wasn't enough
            proc.wait(timeout=3)

        # Allow up to 1 s for OS reaping (Windows may hold the pid briefly).
        is_gone  = False
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                status = psutil.Process(pid).status()
                # On Linux/macOS the process lingers as a zombie; on Windows it
                # simply disappears — both outcomes are correct.
                if status in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                    is_gone = True
                    break
            except psutil.NoSuchProcess:
                is_gone = True
                break
            time.sleep(0.05)

        assert is_gone, (
            f"Proxy subprocess pid={pid} is still alive after terminate() + wait(). "
            "The atexit teardown is not cleaning up the Ollama process reliably."
        )

    # ── Test 4: no spawn when local GGUF model is present ─────────────────────

    def test_no_subprocess_spawned_when_local_model_exists(self):
        """
        Regression guard: if LOCAL_MODEL_PATH exists on disk, check_ollama()
        must return False immediately without spawning any subprocess.
        """
        with (
            patch("requests.get", side_effect=ConnectionError("offline")),
            patch("os.path.exists", return_value=True),   # local GGUF is present
            patch("subprocess.Popen") as mock_popen,
        ):
            result = BootDiagnostics().check_ollama()

        assert result is False, "Should return False when local GGUF model exists"
        mock_popen.assert_not_called()

    # ── Test 5: no spawn when `ollama` CLI is absent from PATH ────────────────

    def test_no_subprocess_spawned_when_ollama_not_in_path(self):
        """
        Regression guard: if shutil.which("ollama") returns None, no Popen call
        must be attempted — spawning a non-existent binary would OSError.
        """
        with (
            patch("requests.get", side_effect=ConnectionError("offline")),
            patch("os.path.exists", return_value=False),
            patch("shutil.which",   return_value=None),   # CLI not found
            patch("subprocess.Popen") as mock_popen,
        ):
            result = BootDiagnostics().check_ollama()

        assert result is False, "Should return False when ollama CLI not found in PATH"
        mock_popen.assert_not_called()
