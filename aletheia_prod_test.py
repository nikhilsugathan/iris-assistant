# -*- coding: utf-8 -*-
"""
aletheia_prod_test.py
=====================
Phase 7 — Aletheia Protocol: Comprehensive Engineering-Grade Validation Suite
==============================================================================

PURPOSE
───────
This suite validates every behavioural contract introduced in Phase 7 of the
IRIS → Aletheia bifurcation. It is deliberately written to be:

  RED  on the current repo (exposing exactly what Phase 7 has not yet landed)
  GREEN once all Phase 7 changes are merged

This makes it a living regression gate: run it after every merge commit.

TEST INVENTORY
──────────────
  TC-01  test_stealth_integrity         SelfModel boots with admin_unlocked=False;
                                         summary() masks Aletheia in public mode.

  TC-02  test_layer_0_sandbox           SecurityGuard blocks run_command with
                                         admin_unlocked=False (Layer 0 public jail).

  TC-03  test_privilege_escalation      Same run_command returns SAFE (or WARNING,
                                         never BLOCKED on public-jail grounds) when
                                         admin_unlocked=True.

  TC-04  test_persona_bifurcation       brain._get_persona() returns 'Sassy IRIS'
                                         text in public mode and 'Formidable Aletheia'
                                         text in admin mode.

  TC-05  test_sync_and_latency          main._generate_greeting / _generate_farewell
                                         draw from pre-built random.choice pools and
                                         never call any LLM API endpoint.

  TC-06  test_stale_keyword_audit       brain._call_api has exactly (api, prompt) —
                                         no use_persona or use_memory kwargs anywhere
                                         in the live signature OR in the source text
                                         of _ai_ethical_check.

  TC-07  test_executor_bridge           executor.plan_action signature accepts
                                         admin_unlocked: bool = False, and the
                                         kwarg is forwarded to security.assess().

ISOLATION STRATEGY
──────────────────
  All hardware/network dependencies (llama_cpp, requests, speech_recognition,
  pygame, rich, send2trash) are stubbed before any project module is imported.
  No real shell commands, no GPU, no network, no file system writes outside /tmp.

RUN
───
  python aletheia_prod_test.py          # prints per-test results
  python -m pytest aletheia_prod_test.py -v --tb=short
"""

from __future__ import annotations

import inspect
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — DEPENDENCY ISOLATION
# Stub every heavy import BEFORE any project module is touched.
# ══════════════════════════════════════════════════════════════════════════════

def _make_stub(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules.setdefault(name, mod)
    return sys.modules[name]


# ── Hardware & audio ──────────────────────────────────────────────────────────
_pygame       = _make_stub("pygame")
_pygame_mixer = _make_stub("pygame.mixer",
    init=MagicMock(), get_init=MagicMock(return_value=True),
    music=MagicMock())
_pygame.mixer = _pygame_mixer

_sr = _make_stub("speech_recognition", Recognizer=MagicMock, Microphone=MagicMock)
_np = _make_stub("numpy", frombuffer=MagicMock(return_value=[]), int16=int, array=MagicMock)

_make_stub("llama_cpp", Llama=MagicMock)
_make_stub("send2trash", send2trash=MagicMock)
_make_stub("pyttsx3")
_make_stub("pyaudio", PyAudio=MagicMock, paInt16=8)

# ── Network — prevent every outbound HTTP call ────────────────────────────────
_mock_response = MagicMock(status_code=404, ok=False)
_mock_response.json.return_value = {}

_req_get_patcher  = patch("requests.get",  return_value=_mock_response)
_req_post_patcher = patch("requests.post", return_value=_mock_response)
_req_get_patcher.start()
_req_post_patcher.start()

# ── Rich UI ───────────────────────────────────────────────────────────────────
# ── Section 1: Rich UI Stubs ──────────────────────────────────────────────────
# ── Section 1: Rich UI & Hardware Stubs ───────────────────────────────────────
# We add __path__=[] so Python treats 'rich' as a package, allowing sub-imports.
_rich         = _make_stub("rich", __path__=[]) 
_rich_console = _make_stub("rich.console",  Console=MagicMock)
_rich_panel   = _make_stub("rich.panel",    Panel=MagicMock)
_rich_prog    = _make_stub("rich.progress", Progress=MagicMock, SpinnerColumn=MagicMock, TextColumn=MagicMock)
_rich_live    = _make_stub("rich.live",     Live=MagicMock)

# Explicitly stub the sub-modules and their required attributes
_make_stub("rich.markup", escape=MagicMock)
_make_stub("rich.text",   Text=MagicMock)
_make_stub("rich.table",  Table=MagicMock)

# Add the hardware telemetry stub used in v5.1
_make_stub("psutil", cpu_percent=MagicMock(return_value=10.0))

# ── Config (minimal stub — matches what project code reads) ──────────────────
class _Config:
    LOCAL_MODEL_PATH       = ""
    OLLAMA_BASE_URL        = "http://localhost:11434"
    GEMINI_API_KEY         = ""
    GROQ_API_KEY           = ""
    CLAUDE_API_KEY         = ""
    PERPLEXITY_API_KEY     = ""
    GROQ_MODEL             = "llama3-8b-8192"
    CLAUDE_MODEL           = "claude-3-haiku-20240307"
    GEMINI_MODEL           = "gemini-1.5-flash"
    PERPLEXITY_MODEL       = "llama-3-sonar-small-32k-online"
    IRIS_PERSONA           = "You are IRIS, a helpful assistant."
    MEMORY_FILE            = "memory.json"
    PRIMARY_BRAIN          = "groq"
    FALLBACK_BRAIN         = "gemini"
    BRAIN_PRIORITY         = ["groq", "gemini", "claude"]
    WAKE_WORDS             = ["iris"]
    WEB_KEYWORDS           = ["search", "latest", "news", "today"]
    CODE_KEYWORDS          = ["code", "python", "script"]
    WAKE_RMS_THRESHOLD     = 400
    COMMAND_RMS_THRESHOLD  = 550
    VOICE_NAME             = "en-US-JennyNeural"
    VOICE_RATE             = "+0%"
    PIPER_MODEL_PATH       = ""
    PIPER_EXE_PATH         = ""
    INNER_CODENAME         = "Aletheia"
    SYSTEM_MOTTO           = "Intelligence. Redefined."

    @staticmethod
    def validate():
        pass

_config_mod = _make_stub("config", Config=_Config)

# ── Core stubs that are imported but not under test here ─────────────────────
_mem_instance = MagicMock()
_mem_instance.get_context.return_value = []
_mem_instance.add.return_value = None

_make_stub("core.memory",         Memory=MagicMock(return_value=_mem_instance))
_make_stub("core.session_logger", SessionLogger=MagicMock)
_make_stub("core.autocorrect",    AutoCorrector=MagicMock)
_make_stub("core.browser",        BrowserAutomation=MagicMock)
_make_stub("core.improv",         ImprovEngine=MagicMock)
_make_stub("core.council",        Council=MagicMock)
_make_stub("core.copilot",        CoPilot=MagicMock)
_make_stub("core.dialog_manager", DialogManager=MagicMock)
_make_stub("core.logic_engine",   LogicalEngine=MagicMock)
_make_stub("core.evolution",      EvolutionEngine=MagicMock)
_make_stub("core.autonomist",     Autonomist=MagicMock)
_make_stub("core.piper_tts",      PiperTTS=MagicMock)
_make_stub("tools.researcher",    Researcher=MagicMock)
_make_stub("tools.cleaner",       sanitize_memory=MagicMock)

_diag_mock = MagicMock()
_diag_mock.get_vram_status = MagicMock(return_value=(0.0, 8192.0))
_make_stub("core.diagnostics",
    SelfDiagnostics=MagicMock,
    BootDiagnostics=MagicMock,
    get_vram_status=MagicMock(return_value=(0.0, 8192.0)))

# Subprocess — never run real shell commands
import subprocess as _real_subprocess  # noqa: E402 (already imported by Python)

_subprocess_stub = _make_stub("subprocess",
    Popen=MagicMock,
    run=MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr="")),
    PIPE=-1, STDOUT=-2, CREATE_NO_WINDOW=0,
    TimeoutExpired=TimeoutError)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — IMPORT PROJECT MODULES UNDER TEST
# ══════════════════════════════════════════════════════════════════════════════

from core.self_model import SelfModel                                    # noqa: E402
from core.security   import SecurityGuard, SAFE, BLOCKED, WARNING, NEED_ADMIN  # noqa: E402
from core.brain      import Brain                                        # noqa: E402
from core.executor   import ActionExecutor                               # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — TEST HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _make_brain() -> Brain:
    """Return a Brain wired to a mock memory — no HTTP, no local model."""
    b = Brain.__new__(Brain)
    b.memory        = _mem_instance
    b.llm           = None
    b._llm_lock     = __import__("threading").Lock()
    b.available_apis = []
    _Config.PRIMARY_BRAIN  = "groq"
    _Config.FALLBACK_BRAIN = "gemini"
    return b


def _make_executor(brain=None) -> ActionExecutor:
    """Return an ActionExecutor with mock voice and a real SecurityGuard."""
    if brain is None:
        brain = _make_brain()
    voice = MagicMock()
    ex = ActionExecutor.__new__(ActionExecutor)
    ex.voice   = voice
    ex.brain   = brain
    ex.security = SecurityGuard(brain)
    ex.log_file    = "/dev/null"          # silence log writes during tests
    ex.is_windows  = False
    ex.pending_action         = None
    ex.pending_verdict        = None
    ex.follow_up              = None
    ex.autocorrect            = MagicMock()
    ex.improv                 = MagicMock()
    ex.pending_plans          = None
    ex.last_action_path       = None
    ex._clarification_options = []
    ex._browser               = None
    return ex


# A minimal run_command plan that should be SAFE when admin is unlocked
_BENIGN_RUN_PLAN = {
    "action_type": "run_command",
    "command":     "echo hello",
    "description": "print hello",
    "url":         "",
    "filename":    "",
    "is_dangerous": False,
}

# A run_command plan that should be BLOCKED by Layer 1 regardless of admin flag
_HARD_BLOCKED_PLAN = {
    "action_type": "run_command",
    "command":     "rm -rf /",
    "description": "wipe filesystem",
    "url":         "",
    "filename":    "",
    "is_dangerous": True,
}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — THE TEST SUITE
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase7AletheiaProtocol(unittest.TestCase):
    """
    Seven engineering-grade tests covering the full Phase 7 bifurcation contract.

    Failure messages are written to be actionable: they state the file, method,
    and exact code change required to make the test go green.
    """

    # ── TC-01 ─────────────────────────────────────────────────────────────────
    def test_stealth_integrity(self):
        """
        WHAT  SelfModel must boot with admin_unlocked=False (stealth-by-default).
              summary() must NOT expose Aletheia or admin status in public mode.
              Flipping admin_unlocked=True must alter summary() accordingly.

        WHY   If admin_unlocked defaults to anything truthy the Layer 0 sandbox
              never fires and every user gets full Aletheia access on boot.

        FILE  core/self_model.py
        FIX   Add   admin_unlocked: bool = False   to the @dataclass fields.
              Update summary() to return different strings based on admin_unlocked.
        """
        sm = SelfModel()

        # 1. Field must exist and be strictly False
        self.assertTrue(
            hasattr(sm, "admin_unlocked"),
            "FAIL TC-01a: SelfModel has no 'admin_unlocked' field.\n"
            "  → core/self_model.py: add  admin_unlocked: bool = False  to the dataclass."
        )
        self.assertIs(
            sm.admin_unlocked, False,
            f"FAIL TC-01b: admin_unlocked should be False on boot, got {sm.admin_unlocked!r}.\n"
            "  → core/self_model.py: ensure the default is False, not True or None."
        )

        # 2. Public summary must NOT reveal Aletheia
        pub_summary = sm.summary()
        self.assertNotIn(
            "Aletheia", pub_summary,
            f"FAIL TC-01c: summary() exposes 'Aletheia' in public mode.\n"
            f"  Got: {pub_summary!r}\n"
            "  → core/self_model.py: mask the codename in summary() when admin_unlocked=False."
        )

        # 3. Public summary must identify as IRIS
        self.assertIn(
            "IRIS", pub_summary,
            f"FAIL TC-01d: summary() does not contain 'IRIS' in public mode.\n"
            f"  Got: {pub_summary!r}\n"
            "  → core/self_model.py: include the public persona label in summary()."
        )

        # 4. Admin mode must change the summary
        sm.admin_unlocked = True
        admin_summary = sm.summary()
        self.assertIn(
            "Aletheia", admin_summary,
            f"FAIL TC-01e: summary() does not reveal 'Aletheia' in admin mode.\n"
            f"  Got: {admin_summary!r}\n"
            "  → core/self_model.py: include codename in summary() when admin_unlocked=True."
        )

        # 5. Revert must restore stealth
        sm.admin_unlocked = False
        self.assertNotIn(
            "Aletheia", sm.summary(),
            "FAIL TC-01f: summary() did not revert to stealth after admin_unlocked reset to False."
        )

    # ── TC-02 ─────────────────────────────────────────────────────────────────
    def test_layer_0_sandbox(self):
        """
        WHAT  SecurityGuard.assess(plan, admin_unlocked=False):
              - run_command and manage_package must return BLOCKED.
              - delete_item on a safe path must NOT be BLOCKED.
              - delete_item on a protected path must return BLOCKED.

        WHY   Public mode should allow safe Recycle Bin deletes while still
              blocking shell/package actions and protected system paths.

        FILE  core/security.py
        """
        brain = _make_brain()
        guard = SecurityGuard(brain)

        hard_restricted = [
            ("run_command", "echo hello", "run a command"),
            ("manage_package", "pip install requests", "install a package"),
        ]

        for action_type, command, label in hard_restricted:
            plan = {
                "action_type":  action_type,
                "command":      command,
                "description":  label,
                "url":          "",
                "filename":     "",
                "is_dangerous": False,
            }
            with self.subTest(action_type=action_type):
                try:
                    verdict, msg = guard.assess(plan, admin_unlocked=False)
                except TypeError:
                    self.fail(
                        f"FAIL TC-02 ({action_type}): assess() does not accept admin_unlocked kwarg.\n"
                        "  → core/security.py: change signature to  def assess(self, plan, admin_unlocked=False)"
                    )

                self.assertEqual(
                    verdict, BLOCKED,
                    f"FAIL TC-02 ({action_type}): public mode should BLOCK '{action_type}'.\n"
                    f"  Got verdict={verdict!r}  msg={msg!r}\n"
                    "  → core/security.py: add Layer 0 sandbox that blocks restricted action_types"
                    " when admin_unlocked=False."
                )
                # The block message must hint at how to unlock
                self.assertIn(
                    "aletheia", msg.lower(),
                    f"FAIL TC-02 ({action_type}): BLOCKED message must reference 'Aletheia'.\n"
                    f"  Got msg={msg!r}\n"
                    "  → core/security.py: Layer 0 message must tell the user to unlock with Aletheia."
                )

        safe_delete_plan = {
            "action_type": "delete_item",
            "command": "",
            "description": "delete a file",
            "url": "",
            "filename": "/tmp/testfile.txt",
            "is_dangerous": False,
        }
        verdict_safe, msg_safe = guard.assess(safe_delete_plan, admin_unlocked=False)
        self.assertNotEqual(
            verdict_safe, BLOCKED,
            f"FAIL TC-02 (delete_item safe path): public mode must ALLOW Recycle Bin delete "
            f"on a safe path.\n  Got verdict={verdict_safe!r}  msg={msg_safe!r}"
        )

        import os
        protected_delete_plan = {
            "action_type": "delete_item",
            "command": "",
            "description": "delete a system file",
            "url": "",
            "filename": os.path.expandvars(r"C:\Windows\system32\test.dll"),
            "is_dangerous": False,
        }
        verdict_protected, msg_protected = guard.assess(protected_delete_plan, admin_unlocked=False)
        self.assertEqual(
            verdict_protected, BLOCKED,
            f"FAIL TC-02 (delete_item protected path): public mode must BLOCK delete "
            f"targeting a protected system path.\n  Got verdict={verdict_protected!r}  msg={msg_protected!r}"
        )
        self.assertIn(
            "aletheia", msg_protected.lower(),
            f"FAIL TC-02 (delete_item protected path): BLOCKED message must reference 'Aletheia'.\n"
            f"  Got msg={msg_protected!r}"
        )

    # ── TC-03 ─────────────────────────────────────────────────────────────────
    def test_privilege_escalation(self):
        """
        WHAT  With admin_unlocked=True a benign run_command ('echo hello') must
              NOT be blocked by the public sandbox — it should be SAFE (or WARNING
              from deeper layers, but never BLOCKED on Layer 0 grounds).
              A Layer-1 hard-blocked command ('rm -rf /') must remain BLOCKED
              even with admin_unlocked=True — hard blocks are unconditional.

        WHY   Admin mode must lift the public jail without disabling real security.

        FILE  core/security.py
        FIX   Layer 0 must guard on admin_unlocked=False only.
              Layer 1 must fire unconditionally regardless of admin_unlocked.
        """
        brain = _make_brain()
        guard = SecurityGuard(brain)

        # ── Part A: benign command, admin unlocked ────────────────────────────
        try:
            verdict_benign, msg_benign = guard.assess(_BENIGN_RUN_PLAN, admin_unlocked=True)
        except TypeError:
            self.fail(
                "FAIL TC-03a: assess() does not accept admin_unlocked kwarg.\n"
                "  → core/security.py: def assess(self, plan, admin_unlocked=False)"
            )

        self.assertIn(
            verdict_benign, (SAFE, WARNING, NEED_ADMIN),
            f"FAIL TC-03a: 'echo hello' with admin_unlocked=True must NOT be BLOCKED.\n"
            f"  Got verdict={verdict_benign!r}  msg={msg_benign!r}\n"
            "  → core/security.py: Layer 0 must be skipped when admin_unlocked=True."
        )

        # ── Part B: hard-blocked command, admin unlocked ──────────────────────
        try:
            verdict_hard, msg_hard = guard.assess(_HARD_BLOCKED_PLAN, admin_unlocked=True)
        except TypeError:
            self.fail(
                "FAIL TC-03b: assess() does not accept admin_unlocked kwarg.\n"
                "  → core/security.py: def assess(self, plan, admin_unlocked=False)"
            )

        self.assertEqual(
            verdict_hard, BLOCKED,
            f"FAIL TC-03b: 'rm -rf /' must be BLOCKED even with admin_unlocked=True.\n"
            f"  Got verdict={verdict_hard!r}  msg={msg_hard!r}\n"
            "  → core/security.py: Layer 1 hard blocks must fire regardless of admin state."
        )

        # The Layer-1 block message must NOT mention 'aletheia'
        # (it's a permanent block, not an access-control issue)
        self.assertNotIn(
            "aletheia", msg_hard.lower(),
            f"FAIL TC-03c: Layer-1 BLOCKED message for 'rm -rf /' should not mention Aletheia.\n"
            f"  Got msg={msg_hard!r}\n"
            "  → core/security.py: differentiate Layer 0 (unlock hint) from Layer 1 (hard block) messages."
        )

    # ── TC-04 ─────────────────────────────────────────────────────────────────
    def test_persona_bifurcation(self):
        """
        WHAT  brain._get_persona(admin_unlocked) must return two distinct persona
              strings:
                Public  (False) — must contain 'IRIS' and the sassy/deflection marker
                Admin   (True)  — must contain 'Aletheia' and the formidable/root-access marker

        WHY   If the wrong persona is injected into the LLM system prompt the
              entire identity bifurcation collapses.

        FILE  core/brain.py
        FIX   Add  def _get_persona(self, admin_unlocked: bool = False) -> str:
              Return Config.IRIS_PERSONA (public) vs Config.ALETHEIA_PERSONA (admin).
        """
        brain = _make_brain()

        # Method must exist
        self.assertTrue(
            hasattr(brain, "_get_persona"),
            "FAIL TC-04a: Brain has no '_get_persona' method.\n"
            "  → core/brain.py: add  def _get_persona(self, admin_unlocked: bool = False) -> str"
        )
        self.assertTrue(
            callable(brain._get_persona),
            "FAIL TC-04b: Brain._get_persona is not callable."
        )

        public_persona = brain._get_persona(admin_unlocked=False)
        admin_persona  = brain._get_persona(admin_unlocked=True)

        self.assertIsInstance(public_persona, str,
            "FAIL TC-04c: _get_persona(False) must return a str.")
        self.assertIsInstance(admin_persona, str,
            "FAIL TC-04d: _get_persona(True) must return a str.")

        # Public persona checks
        self.assertIn(
            "IRIS", public_persona,
            f"FAIL TC-04e: Public persona must contain 'IRIS'.\n  Got: {public_persona!r}"
        )
        self.assertIn(
            "deflect", public_persona.lower(),
            f"FAIL TC-04f: Public persona must contain deflection instruction.\n  Got: {public_persona!r}\n"
            "  → Add language like 'deflect cleverly' to the public IRIS persona string."
        )
        # Public persona must NOT expose admin identity
        self.assertNotIn(
            "Aletheia", public_persona,
            f"FAIL TC-04g: Public persona must NOT mention 'Aletheia'.\n  Got: {public_persona!r}"
        )
        self.assertNotIn(
            "root access", public_persona.lower(),
            f"FAIL TC-04h: Public persona must NOT grant root access.\n  Got: {public_persona!r}"
        )

        # Admin persona checks
        self.assertIn(
            "Aletheia", admin_persona,
            f"FAIL TC-04i: Admin persona must contain 'Aletheia'.\n  Got: {admin_persona!r}"
        )
        self.assertIn(
            "root access", admin_persona.lower(),
            f"FAIL TC-04j: Admin persona must contain 'root access'.\n  Got: {admin_persona!r}\n"
            "  → Add 'root access' language to the Aletheia admin persona string."
        )
        # Admin persona must not retain the public deflection order
        self.assertNotIn(
            "deflect", admin_persona.lower(),
            f"FAIL TC-04k: Admin persona must NOT contain public deflection instruction.\n  Got: {admin_persona!r}"
        )

    # ── TC-05 ─────────────────────────────────────────────────────────────────
    def test_sync_and_latency(self):
        """
        WHAT  main._generate_greeting(admin_unlocked) and
              main._generate_farewell(self_model) must:
                • exist as module-level callables
                • return a non-empty string
                • draw from pre-built pool lists (_GREETINGS_PUBLIC, _GREETINGS_ADMIN,
                  _FAREWELLS_PUBLIC, _FAREWELLS_ADMIN)
                • NEVER call any LLM API (verified by asserting requests.post
                  was not called during the greeting/farewell generation)

        WHY   Zero-latency boot greetings cannot wait for an LLM round-trip.
              If they call the API, the first 5–15 seconds of every session
              are blocked.

        FILE  main.py
        FIX   Add four module-level pool lists and two helper functions that
              use random.choice() on those lists.
        """
        try:
            import main as _main
        except Exception as e:
            self.skipTest(f"Could not import main.py (heavy deps): {e}")

        # ── Check pool lists exist ────────────────────────────────────────────
        for pool_name in ("_GREETINGS_PUBLIC", "_GREETINGS_ADMIN",
                          "_FAREWELLS_PUBLIC", "_FAREWELLS_ADMIN"):
            self.assertTrue(
                hasattr(_main, pool_name),
                f"FAIL TC-05a: main.py has no module-level '{pool_name}' list.\n"
                f"  → main.py: add  {pool_name} = [...]  with ≥2 strings."
            )
            pool = getattr(_main, pool_name)
            self.assertIsInstance(pool, list,
                f"FAIL TC-05b: {pool_name} must be a list, got {type(pool).__name__}.")
            self.assertGreaterEqual(len(pool), 2,
                f"FAIL TC-05c: {pool_name} must have ≥2 entries for meaningful variance.")
            for item in pool:
                self.assertIsInstance(item, str,
                    f"FAIL TC-05d: Every item in {pool_name} must be a str.")
                self.assertTrue(item.strip(),
                    f"FAIL TC-05e: {pool_name} contains an empty/blank string.")

        # ── Check helper functions exist ──────────────────────────────────────
        for fn_name in ("_generate_greeting", "_generate_farewell"):
            self.assertTrue(
                hasattr(_main, fn_name),
                f"FAIL TC-05f: main.py has no '{fn_name}' function.\n"
                f"  → main.py: add  def {fn_name}(...)  that returns random.choice(pool)."
            )
            self.assertTrue(callable(getattr(_main, fn_name)),
                f"FAIL TC-05g: main.{fn_name} is not callable.")

        # ── Greetings return correct pool membership ──────────────────────────
        sm = SelfModel()

        with patch("requests.post") as mock_post, \
             patch("requests.get")  as mock_get:

            # Public greeting
            pub_greeting = _main._generate_greeting(admin_unlocked=False)
            self.assertIsInstance(pub_greeting, str,
                "FAIL TC-05h: _generate_greeting(False) must return a str.")
            self.assertTrue(pub_greeting.strip(),
                "FAIL TC-05i: _generate_greeting(False) returned an empty string.")
            self.assertIn(pub_greeting, _main._GREETINGS_PUBLIC,
                f"FAIL TC-05j: Public greeting {pub_greeting!r} not in _GREETINGS_PUBLIC pool.")
            self.assertNotIn(pub_greeting, _main._GREETINGS_ADMIN,
                f"FAIL TC-05k: Public greeting leaked from admin pool: {pub_greeting!r}.")

            # Admin greeting
            adm_greeting = _main._generate_greeting(admin_unlocked=True)
            self.assertIn(adm_greeting, _main._GREETINGS_ADMIN,
                f"FAIL TC-05l: Admin greeting {adm_greeting!r} not in _GREETINGS_ADMIN pool.")

            # Public farewell
            sm.admin_unlocked = False
            pub_farewell = _main._generate_farewell(sm)
            self.assertIn(pub_farewell, _main._FAREWELLS_PUBLIC,
                f"FAIL TC-05m: Public farewell {pub_farewell!r} not in _FAREWELLS_PUBLIC pool.")
            self.assertNotIn(pub_farewell, _main._FAREWELLS_ADMIN,
                f"FAIL TC-05n: Public farewell leaked from admin pool: {pub_farewell!r}.")

            # Admin farewell
            sm.admin_unlocked = True
            adm_farewell = _main._generate_farewell(sm)
            self.assertIn(adm_farewell, _main._FAREWELLS_ADMIN,
                f"FAIL TC-05o: Admin farewell {adm_farewell!r} not in _FAREWELLS_ADMIN pool.")

            # Zero LLM calls — greetings/farewells must be instantaneous
            self.assertEqual(
                mock_post.call_count, 0,
                f"FAIL TC-05p: _generate_greeting/_generate_farewell triggered {mock_post.call_count} "
                "HTTP POST call(s) — these must be zero-latency random.choice(), not LLM calls.\n"
                "  → main.py: remove any API call from greeting/farewell helpers."
            )
            self.assertEqual(
                mock_get.call_count, 0,
                f"FAIL TC-05q: greeting/farewell triggered {mock_get.call_count} HTTP GET call(s)."
            )

    # ── TC-06 ─────────────────────────────────────────────────────────────────
    def test_stale_keyword_audit(self):
        """
        WHAT  brain._call_api must have EXACTLY (self, api, prompt) — no
              use_persona or use_memory parameters in the signature.
              Additionally, the source text of _ai_ethical_check in security.py
              must NOT contain the stale kwargs use_persona= or use_memory=.

        WHY   security.py line 299 currently calls:
                self.brain._call_api(Config.PRIMARY_BRAIN, prompt,
                    use_persona=False, use_memory=False)
              This will raise a TypeError at runtime because Brain._call_api
              does NOT accept those kwargs.  The test catches this live bug.

        FILE  core/security.py  AND  core/brain.py
        FIX   security.py: remove use_persona=False, use_memory=False from the
              _call_api call inside _ai_ethical_check().
              brain.py: do not add those params — the strict two-arg contract
              must be preserved.
        """
        brain = _make_brain()

        # ── 1. Inspect the live signature ─────────────────────────────────────
        sig    = inspect.signature(brain._call_api)
        params = list(sig.parameters.keys())

        for bad_kwarg in ("use_persona", "use_memory"):
            self.assertNotIn(
                bad_kwarg, params,
                f"FAIL TC-06a: Brain._call_api has forbidden parameter '{bad_kwarg}'.\n"
                f"  Current signature params: {params}\n"
                f"  → core/brain.py: remove '{bad_kwarg}' from _call_api; keep (api, prompt) only."
            )

        self.assertIn("api", params,
            f"FAIL TC-06b: 'api' missing from _call_api params: {params}")
        self.assertIn("prompt", params,
            f"FAIL TC-06c: 'prompt' missing from _call_api params: {params}")
        self.assertEqual(len(params), 2,
            f"FAIL TC-06d: _call_api must have exactly 2 params (api, prompt), got {params}.")

        # ── 2. Scan security.py source for the stale call-site ───────────────
        import core.security as _sec_module
        sec_source = inspect.getsource(_sec_module)

        for bad_kwarg in ("use_persona", "use_memory"):
            self.assertNotIn(
                bad_kwarg, sec_source,
                f"FAIL TC-06e: core/security.py still contains stale kwarg '{bad_kwarg}='.\n"
                "  This will cause a TypeError at runtime in _ai_ethical_check().\n"
                f"  → core/security.py: remove  {bad_kwarg}=False  from the _call_api() call "
                "inside _ai_ethical_check (approx. line 299)."
            )

        # ── 3. Confirm _call_api is callable with (api, prompt) ──────────────
        with patch.object(brain, "_call_groq",      return_value="ok"), \
             patch.object(brain, "_call_gemini",     return_value="ok"), \
             patch.object(brain, "_call_claude",     return_value="ok"), \
             patch.object(brain, "_call_perplexity", return_value="ok"), \
             patch.object(brain, "_call_ollama",     return_value="ok"):
            try:
                result = brain._call_api("groq", "test prompt")
            except TypeError as exc:
                self.fail(
                    f"FAIL TC-06f: brain._call_api('groq', 'test prompt') raised TypeError: {exc}\n"
                    "  → core/brain.py: fix the _call_api signature."
                )
            self.assertEqual(result, "ok",
                "FAIL TC-06g: _call_api did not return the sub-caller's return value.")

    # ── TC-07 ─────────────────────────────────────────────────────────────────
    def test_executor_bridge(self):
        """
        WHAT  executor.plan_action must:
                a) Accept  admin_unlocked: bool = False  in its signature.
                b) Forward that value to  self.security.assess()  as a kwarg.
                c) Default to False (no behaviour change for callers that
                   don't pass the flag — backwards-compatible).

        WHY   main.py will call  executor.plan_action(user_input, admin_unlocked=...)
              If the executor doesn't forward the flag, the Layer 0 sandbox in
              SecurityGuard is never consulted, and the entire gate is bypassed.

        FILE  core/executor.py
        FIX   Change signature to:
                def plan_action(self, user_input: str, admin_unlocked: bool = False) -> str:
              Change the assess call to:
                verdict, security_msg = self.security.assess(plan, admin_unlocked=admin_unlocked)
        """
        ex = _make_executor()

        # ── Part A: signature check ───────────────────────────────────────────
        sig    = inspect.signature(ex.plan_action)
        params = list(sig.parameters.keys())

        self.assertIn(
            "admin_unlocked", params,
            f"FAIL TC-07a: executor.plan_action has no 'admin_unlocked' parameter.\n"
            f"  Current params: {params}\n"
            "  → core/executor.py: change signature to  "
            "def plan_action(self, user_input: str, admin_unlocked: bool = False) -> str"
        )

        # Default must be False (backwards-compatible)
        default = sig.parameters["admin_unlocked"].default
        self.assertIs(
            default, False,
            f"FAIL TC-07b: admin_unlocked default must be False, got {default!r}.\n"
            "  → core/executor.py: ensure the default is False in the signature."
        )

        # ── Part B: forwarding check ──────────────────────────────────────────
        # Inject a spy on security.assess and verify admin_unlocked is passed
        sentinel_plan = {
            "action_type": "run_command",
            "command":     "echo test",
            "description": "test",
            "url":         "",
            "filename":    "",
            "is_dangerous": False,
        }

        with patch.object(ex, "_pattern_match", return_value=sentinel_plan), \
             patch.object(ex, "_execute_pending", return_value="done"), \
             patch.object(ex.security, "assess", return_value=(SAFE, "")) as mock_assess:

            # Call with admin_unlocked=True
            ex.plan_action("run a test command", admin_unlocked=True)

            self.assertTrue(
                mock_assess.called,
                "FAIL TC-07c: plan_action did not call security.assess() at all."
            )

            # Verify admin_unlocked=True was forwarded
            call_kwargs = mock_assess.call_args[1] if mock_assess.call_args[1] else {}
            call_args   = mock_assess.call_args[0] if mock_assess.call_args[0] else ()
            forwarded   = call_kwargs.get("admin_unlocked")

            # assess might be called as assess(plan, True) or assess(plan, admin_unlocked=True)
            if forwarded is None and len(call_args) >= 2:
                forwarded = call_args[1]  # positional second arg

            self.assertIs(
                forwarded, True,
                f"FAIL TC-07d: plan_action did not forward admin_unlocked=True to security.assess().\n"
                f"  assess() was called with args={mock_assess.call_args}\n"
                "  �� core/executor.py: change the assess call to  "
                "self.security.assess(plan, admin_unlocked=admin_unlocked)"
            )

        # ── Part C: default False is forwarded when caller omits the flag ─────
        with patch.object(ex, "_pattern_match", return_value=sentinel_plan), \
             patch.object(ex, "_execute_pending", return_value="done"), \
             patch.object(ex.security, "assess", return_value=(SAFE, "")) as mock_assess_default:

            ex.plan_action("run a test command")   # no admin_unlocked arg

            call_kwargs = mock_assess_default.call_args[1] if mock_assess_default.call_args[1] else {}
            call_args   = mock_assess_default.call_args[0] if mock_assess_default.call_args[0] else ()
            forwarded_default = call_kwargs.get("admin_unlocked")
            if forwarded_default is None and len(call_args) >= 2:
                forwarded_default = call_args[1]

            self.assertIs(
                forwarded_default, False,
                f"FAIL TC-07e: When plan_action is called without admin_unlocked, "
                f"assess() must receive False, got {forwarded_default!r}.\n"
                "  → core/executor.py: ensure the default False propagates to assess()."
            )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromTestCase(TestPhase7AletheiaProtocol)
    runner = unittest.TextTestRunner(verbosity=2, failfast=False)
    result = runner.run(suite)

    print("\n" + "═" * 70)
    print(f"  Phase 7 Gate: {'✅ ALL PASS — ready to merge' if result.wasSuccessful() else '❌ FAILURES DETECTED — see messages above'}")
    print("═" * 70)

    sys.exit(0 if result.wasSuccessful() else 1)
