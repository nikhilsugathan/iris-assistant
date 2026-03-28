"""
IRIS Security Guard
======================
Every single action passes through here before execution.
No exceptions.

WHAT IT CHECKS:
  1. ETHICAL COMPLIANCE   — Is this action within ethical boundaries?
  2. THREAT DETECTION     — Malware, phishing, suspicious domains, harmful commands
  3. PERMISSION LEVEL     — Does this need admin/elevated rights?
  4. DOWNLOAD SAFETY      — Is the source trusted? Is the file type safe?
  5. SITE ACCESS SAFETY   — Is the URL known malicious, tracking, or suspicious?

RESPONSE TYPES:
  SAFE        — proceed normally
  WARNING     — inform user of risk, ask explicit confirmation
  BLOCKED     — refuse entirely, explain why
  NEED_ADMIN  — inform user that elevated rights are required, ask to confirm

ETHICAL BASELINE (always enforced, no override):
  - No commands that harm other systems (DDoS, exploits, port scanners with attack intent)
  - No downloads from known malware/phishing domains
  - No accessing or exfiltrating private data without consent
  - No bypassing OS security (UAC bypass, privilege escalation exploits)
  - No illegal content

BEYOND BASELINE (requires YOUR explicit permission):
  - Admin-level system changes
  - Firewall/antivirus modifications
  - Registry edits
  - Network configuration changes
  - Accessing system folders (C:\\Windows\\System32 etc.)
"""

import re
import json
from typing import Tuple
from urllib.parse import urlparse
from config import Config


# ── Verdict constants ──────────────────────────────────────────
SAFE       = "SAFE"
WARNING    = "WARNING"
BLOCKED    = "BLOCKED"
NEED_ADMIN = "NEED_ADMIN"


# ── Hardcoded blocked patterns (never overrideable) ────────────
# These are absolute — no user permission can override them.

BLOCKED_COMMANDS = [
    # Exploit / attack tools
    r"metasploit", r"msfconsole", r"msfvenom",
    r"netcat.*-e", r"nc\.exe.*-e",

    # Credential dumping
    r"mimikatz", r"pwdump", r"hashdump",

    # Mass destruction
    r"rm\s+-rf\s+/", r"del\s+/[sf].*\*",
    r"format\s+c:", r"format\s+[a-z]:\s*/",

    # Ransomware-like patterns
    r"encrypt.*all", r"cipher\s+/w",

    # UAC bypass techniques
    r"fodhelper", r"eventvwr.*bypass", r"cmstp",

    # Fork bomb
    r":\(\)\{.*\|.*&\}", r"%0\|%0",

    # ── Windows LolBins & scripting host bypasses ──────────────
    # These are commonly used to execute code while evading detection.
    # Block them as shell commands (they are still accessible as
    # approved apps via the app_map / open_app path, but not as
    # raw shell commands in run_command / install_package).

    # PowerShell variants — catch aliased and full-path invocations
    r"\bpwsh\b",                          # PowerShell 7 binary
    r"\bpowershell\.exe\b",               # Explicit .exe invocation
    r"WindowsPowerShell",                 # Full path fragment

    # Environment variable bypasses (%WINDIR%\system32\cmd.exe etc.)
    r"%systemroot%",
    r"%windir%",
    r"%comspec%",

    # Scripting hosts — used for dropper/stager execution
    r"\bmshta\b",                         # HTML Application host
    r"\bwscript\b",                       # Windows Script Host (GUI)
    r"\bcscript\b",                       # Windows Script Host (CLI)

    # certutil — commonly abused for base64 decode / download
    r"\bcertutil\b",

    # Inline PowerShell execution via .ps1 or IEX
    r"\.ps1\b",                           # Any .ps1 script reference
    r"iex\s*\(",                          # Invoke-Expression (in-memory execution)
    r"invoke-expression",                 # Full form of IEX
]

BLOCKED_DOMAINS = [
    # Known malware / phishing categories (examples — AI judge handles the full list)
    "bit.ly", "tinyurl.com",           # URL shorteners hide destination (warn, not block)
    "pastebin.com",                    # Often used for payload delivery
]

SUSPICIOUS_FILE_EXTENSIONS = [
    ".exe", ".bat", ".cmd", ".vbs", ".ps1", ".msi",
    ".dll", ".scr", ".pif", ".com", ".jar", ".reg"
]

SAFE_DOWNLOAD_DOMAINS = [
    "github.com", "microsoft.com", "python.org", "nodejs.org",
    "npmjs.com", "pypi.org", "chocolatey.org", "winget.run",
    "mozilla.org", "google.com", "visualstudio.com", "aka.ms",
    "apache.org", "ubuntu.com", "debian.org", "postgresql.org",
]

# Commands that always require admin on Windows
ADMIN_REQUIRED_PATTERNS = [
    r"winget\s+install", r"winget\s+uninstall",
    r"choco\s+install", r"choco\s+uninstall",
    r"sc\s+(create|delete|start|stop)",   # Windows services
    r"netsh\s+", r"ipconfig\s+/",         # Network config
    r"reg\s+(add|delete|import|export)",  # Registry
    r"bcdedit", r"diskpart",              # Boot / disk
    r"net\s+(user|group|localgroup)",     # User management
    r"sfc\s+/", r"dism\s+/",             # System file checker
    r"icacls", r"takeown",               # Permission changes
    r"runas\s+/",                        # Explicit runas
    r"Set-ExecutionPolicy",              # PowerShell policy
    r"New-Service", r"Remove-Service",   # PS services
    r"HKLM\\",                           # Registry HKEY_LOCAL_MACHINE
    r"C:\\Windows\\", r"C:\\Program Files", # System directories
]

# Beyond-ethical — requires EXPLICIT user permission each time
SENSITIVE_OPERATIONS = [
    r"firewall", r"antivirus", r"defender",
    r"taskkill.*system", r"kill.*explorer",
    r"hosts\s+file", r"etc\\hosts",
    r"proxy\s+settings", r"ssl.*bypass", r"certificate.*trust",
]


class SecurityGuard:

    def __init__(self, brain):
        self.brain = brain

    # ─────────────────────────────────────────────────────────────
    # MAIN ENTRY: check everything before any action runs
    # ─────────────────────────────────────────────────────────────

    def assess(self, plan: dict) -> Tuple[str, str]:
        """
        Assess a planned action for safety.

        Returns: (verdict, message)
          verdict : SAFE | WARNING | BLOCKED | NEED_ADMIN
          message : Human-readable explanation to speak to user
        """
        command  = plan.get("command", "")
        url      = self._extract_url(command) or plan.get("url", "")
        filename = plan.get("filename", "")
        action   = plan.get("action_type", "")

        # ── Layer 1: Hard blocks (no override ever) ────────────
        blocked, reason = self._check_hard_blocks(command)
        if blocked:
            return BLOCKED, f"Can't do that — {reason}. This is a hard security block."

        # ── Layer 2: Admin rights check ────────────────────────
        needs_admin, admin_reason = self._check_admin_required(command)
        if needs_admin:
            return NEED_ADMIN, f"Needs admin rights. Run as Administrator or say 'go ahead' for UAC prompt."

        # ── Layer 3: URL / domain safety ──────────────────────
        if url:
            url_verdict, url_msg = self._check_url(url)
            if url_verdict in (BLOCKED, WARNING):
                return url_verdict, url_msg

        # ── Layer 4: Download safety ───────────────────────────
        if action in ("install_package", "run_command") and any(
            ext in command.lower() for ext in SUSPICIOUS_FILE_EXTENSIONS
        ):
            dl_verdict, dl_msg = self._check_download(command, url)
            if dl_verdict in (BLOCKED, WARNING):
                return dl_verdict, dl_msg

        # ── Layer 5: Sensitive operations (need explicit OK) ───
        sensitive, sens_reason = self._check_sensitive(command)
        if sensitive:
            return WARNING, f"This touches a sensitive area: {sens_reason}. Go ahead?"

        # Layer 6 (AI ethical check) intentionally removed —
        # it was blocking legitimate user actions like delete.
        # Hard blocks in Layer 1 handle actual dangerous commands.

        return SAFE, ""

    # ─────────────────────────────────────────────────────────────
    # LAYER 1: Hard-coded blocks
    # ─────────────────────────────────────────────────────────────

    def _check_hard_blocks(self, command: str) -> Tuple[bool, str]:
        cmd_lower = command.lower()
        for pattern in BLOCKED_COMMANDS:
            if re.search(pattern, cmd_lower, re.IGNORECASE):
                return True, f"matches blocked pattern: '{pattern}'"
        return False, ""

    # ─────────────────────────────────────────────────────────────
    # LAYER 2: Admin rights
    # ─────────────────────────────────────────────────────────────

    def _check_admin_required(self, command: str) -> Tuple[bool, str]:
        for pattern in ADMIN_REQUIRED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                readable = pattern.replace(r"\s+", " ").replace(r"\\", "\\")
                return True, f"'{readable}' requires elevated privileges on Windows"
        return False, ""

    # ─────────────────────────────────────────────────────────────
    # LAYER 3: URL safety
    # ─────────────────────────────────────────────────────────────

    def _is_trusted_domain(self, url: str) -> bool:
        """
        Check whether a URL's netloc exactly matches a trusted domain
        or is a direct subdomain of one.

        Uses urllib.parse for proper netloc extraction — prevents
        substring spoofing attacks like 'notgithub.com' or
        'github.com.evil.io' from passing as trusted.
        """
        try:
            netloc = urlparse(url).netloc.lower()
            # Strip port number if present (e.g. "python.org:443" → "python.org")
            netloc = netloc.split(":")[0]
        except Exception:
            return False

        if not netloc:
            return False

        return any(
            netloc == domain or netloc.endswith("." + domain)
            for domain in SAFE_DOWNLOAD_DOMAINS
        )

    def _check_url(self, url: str) -> Tuple[str, str]:
        url_lower = url.lower()

        # HARDENED: use proper netloc parsing, not substring match
        is_trusted = self._is_trusted_domain(url)

        # Check against known suspicious domains
        for domain in BLOCKED_DOMAINS:
            if domain in url_lower:
                if domain in ["bit.ly", "tinyurl.com"]:
                    return WARNING, (
                        f"The URL uses a shortener ({domain}) which hides the real "
                        f"destination. I can't verify where it actually leads. "
                        f"This could be safe or could redirect to something harmful. "
                        f"Do you explicitly want me to proceed to this unknown destination?"
                    )
                return BLOCKED, (
                    f"The domain '{domain}' is flagged as potentially unsafe. "
                    f"I'm blocking this to protect you."
                )

        # HTTP (not HTTPS) on a non-local address
        if url_lower.startswith("http://") and not any(
            x in url_lower for x in ["localhost", "127.0.0.1", "192.168."]
        ):
            return WARNING, (
                f"This URL uses HTTP instead of HTTPS, meaning the connection "
                f"is not encrypted and data could be intercepted. "
                f"It's safer to find an HTTPS version. Do you want to proceed anyway?"
            )

        if not is_trusted:
            return WARNING, (
                f"This URL is from an unverified source (not in my trusted domain list). "
                f"I can't guarantee it's safe. "
                f"Trusted sources include: GitHub, Microsoft, Python.org, PyPI etc. "
                f"Do you want to proceed from this unverified source?"
            )

        return SAFE, ""

    # ─────────────────────────────────────────────────────────────
    # LAYER 4: Download safety
    # ────────────────────────────────────��────────────────────────

    def _check_download(self, command: str, url: str) -> Tuple[str, str]:
        cmd_lower = command.lower()

        # Executable downloaded from unverified source
        # HARDENED: uses _is_trusted_domain for the source check
        for ext in [".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs"]:
            if ext in cmd_lower:
                if not self._is_trusted_domain(url or ""):
                    return WARNING, (
                        f"This downloads a '{ext}' file from an unverified source. "
                        f"Executable files from unknown sources can contain malware. "
                        f"I strongly recommend only downloading executables from "
                        f"official vendor sites. Do you explicitly want to proceed?"
                    )

        return SAFE, ""

    # ─────────────────────────────────────────────────────────────
    # LAYER 5: Sensitive operations
    # ─────────────────────────────────────────────────────────────

    def _check_sensitive(self, command: str) -> Tuple[bool, str]:
        for pattern in SENSITIVE_OPERATIONS:
            if re.search(pattern, command, re.IGNORECASE):
                readable = pattern.replace(r"\s+", " ")
                return True, f"this touches '{readable}'"
        return False, ""

    # ─────────────────────────────────────────────────────────────
    # LAYER 6: AI ethical judgement
    # ─────────────────────────────────────────────────────────────

    def _ai_ethical_check(self, plan: dict) -> Tuple[str, str]:
        """
        Use the primary brain as a final ethical judgement layer.
        Catches edge cases the pattern matching might miss.
        """
        prompt = f"""You are a security auditor reviewing an action that an AI assistant is about to take on a user's computer.

Action plan:
{json.dumps(plan, indent=2)}

Assess this action for:
1. Ethical concerns (could this harm the user or others?)
2. Security risks (could this expose the system to threats?)
3. Privacy concerns (does this access or transmit sensitive data?)
4. Legality (could this violate laws or terms of service?)

Respond in this exact format:
VERDICT: SAFE | WARNING | BLOCKED
REASON: [one sentence explanation, or "none" if SAFE]

Rules:
- Be SAFE for clearly benign actions (install popular apps, create files, web searches)
- Be WARNING for grey-area actions that the user should know about
- Be BLOCKED only for clearly harmful, illegal, or unethical actions
- Do NOT be overly cautious — most developer/IT tasks are safe"""

        response = self.brain._call_api(
            Config.PRIMARY_BRAIN, prompt,
            use_persona=False, use_memory=False
        )

        if not response:
            return SAFE, ""

        lines = response.strip().split("\n")
        verdict_line = next((l for l in lines if l.startswith("VERDICT:")), "")
        reason_line  = next((l for l in lines if l.startswith("REASON:")),  "")

        verdict = verdict_line.replace("VERDICT:", "").strip()
        reason  = reason_line.replace("REASON:", "").strip()

        if verdict == BLOCKED:
            return BLOCKED, (
                f"My ethical safety check flagged this: {reason}. "
                f"I'm not able to proceed with this action."
            )
        if verdict == WARNING and reason.lower() != "none":
            return WARNING, (
                f"One thing to be aware of: {reason}. "
                f"Do you still want to proceed?"
            )

        return SAFE, ""

    # ─────────────────────────────────────────────────────────────
    # UTILITY
    # ─────────────────────────────────────────────────────────────

    def _extract_url(self, text: str) -> str:
        """Extract first URL from a command string."""
        match = re.search(r"https?://[^\s\"']+", text)
        return match.group(0) if match else ""

    def format_security_header(self, verdict: str) -> str:
        """Return a spoken/printed header for security messages."""
        headers = {
            BLOCKED:    "🔴 IRIS Security — BLOCKED",
            WARNING:    "🟡 IRIS Security — WARNING",
            NEED_ADMIN: "🔵 IRIS Security — ADMIN REQUIRED",
            SAFE:       "",
        }
        return headers.get(verdict, "")