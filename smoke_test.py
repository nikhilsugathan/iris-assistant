"""
IRIS Pre-Flight Smoke Test
==========================
Dry-boot all core components without starting the microphone,
the TTS engine, or the main event loop.
"""

from __future__ import annotations
import os
import sys
import traceback

# ── Force text mode + disable all voice I/O so no mic/driver is touched ──
os.environ["IRIS_DISABLE_VOICE_IO"] = "1"
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from rich.console import Console

console = Console()
PASS = "[bold green]  PASS  [/bold green]"
FAIL = "[bold red]  FAIL  [/bold red]"

def check(label: str, fn) -> bool:
    """Run fn(), report PASS/FAIL, return True on success."""
    try:
        result = fn()
        console.print(f"{PASS} {label}")
        return True
    except Exception as exc:
        console.print(f"{FAIL} {label}")
        console.print(f"       [red]{type(exc).__name__}: {exc}[/red]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return False

def run_smoke_test() -> int:
    console.rule("[bold cyan]IRIS Pre-Flight Smoke Test[/bold cyan]")
    console.print()
    results: list[bool] = []

    # 1. Config
    def boot_config():
        from config import Config
        assert hasattr(Config, "MEMORY_FILE"), "MEMORY_FILE missing"
        return Config
    results.append(check("Config: attributes and structure", boot_config))

    # 2. Memory
    def boot_memory():
        from config import Config
        from core.memory import Memory
        m = Memory(Config.MEMORY_FILE)
        assert callable(m.add), "Memory.add() missing"
        return m
    results.append(check("Memory: __init__, summary(), get_context()", boot_memory))

    # 3. Brain
    def boot_brain():
        from config import Config
        from core.memory import Memory
        from core.brain import Brain
        m = Memory(Config.MEMORY_FILE)
        b = Brain(m)
        assert callable(b.think), "Brain.think() missing"
        return b
    results.append(check("Brain: __init__, think(), quick_ack()", boot_brain))

    # 4. SecurityGuard
    def boot_security():
        from config import Config
        from core.memory import Memory
        from core.brain import Brain
        from core.security import SecurityGuard
        m = Memory(Config.MEMORY_FILE)
        b = Brain(m)
        sg = SecurityGuard(b)
        assert callable(sg.assess), "SecurityGuard.assess() missing"
        return sg
    results.append(check("SecurityGuard: __init__, assess() dry-run", boot_security))

    # 5. ActionExecutor
    def boot_executor():
        from config import Config
        from core.memory import Memory
        from core.brain import Brain
        from core.executor import ActionExecutor
        m = Memory(Config.MEMORY_FILE)
        b = Brain(m)
        
        class VoiceStub:
            text_mode = True
            mic_ready = False
            audio_ready = False
            def speak(self, text): pass
            def stop_speaking(self): pass
            def listen_text(self): return ""
            
        e = ActionExecutor(VoiceStub(), b)
        assert callable(e.plan_action), "ActionExecutor.plan_action() missing"
        return e
    results.append(check("ActionExecutor: __init__, plan_action() dry-run", boot_executor))

    # 6. Voice (text_mode=True)
    def boot_voice():
        from core.voice import Voice
        v = Voice(text_mode=True)
        assert callable(v.speak), "Voice.speak() missing"
        return v
    results.append(check("Voice: __init__(text_mode=True), speak(), stop_speaking()", boot_voice))

    # 7. Council
    def boot_council():
        from core.council import Council
        from core.self_model import SelfModel
        
        class FakeDecision:
            mode = "general"
            tone = "direct"
            depth = "normal"
            reason = "smoke test"
            reflective = False
            creative = False
            high_stakes = False
            emotionally_weighted = False
            
        c = Council()
        sm = SelfModel()
        packet = c.deliberate("test input", FakeDecision(), sm)
        assert hasattr(packet, "roles"), "CouncilPacket.roles missing"
        return c
    results.append(check("Council: deliberate() returns valid CouncilPacket", boot_council))

    console.print()
    console.rule()
    passed = sum(results)
    total  = len(results)
    failed = total - passed

    if failed == 0:
        console.print(f"\n[bold green]✓ All {total} components passed. Dry boot is clean.[/bold green]\n")
        return 0
    else:
        console.print(f"\n[bold red]✗ {failed}/{total} component(s) failed.[/bold red]\n")
        return 1

if __name__ == "__main__":
    sys.exit(run_smoke_test())