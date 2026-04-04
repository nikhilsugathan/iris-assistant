"""
IRIS Auto-Corrector
====================
1. INPUT CORRECTION   — typos in commands
2. PATH CORRECTION    — typos in folder/file paths
3. EXTENSION CORRECTION — wrong/missing file extensions
4. AI FALLBACK        — anything the dictionary misses
"""

from __future__ import annotations

import difflib
import os
import re
from typing import Optional, Tuple, List


WORD_CORRECTIONS = {
    "instal": "install", "instll": "install", "isntall": "install",
    "insatll": "install", "nstall": "install",
    "delet": "delete", "dleete": "delete", "delte": "delete",
    "opn": "open", "oen": "open", "poen": "open",
    "crate": "create", "craete": "create", "crete": "create",
    "mkae": "make", "mke": "make",
    "lauch": "launch", "laucnh": "launch",
    "downlad": "download", "dowload": "download", "donwload": "download",
    "searh": "search", "serach": "search", "saerch": "search",
    "runn": "run", "rnu": "run",
    "mve": "move", "mvoe": "move",
    "coopy": "copy", "coyp": "copy",
    "renam": "rename", "reanme": "rename",
    "upadte": "update", "udpate": "update",
    "upgarde": "upgrade", "upgrad": "upgrade",
    "cofigure": "configure", "configrue": "configure",
    "noteapd": "notepad", "notpad": "notepad", "noepad": "notepad",
    "cahrme": "chrome", "chorme": "chrome", "chrme": "chrome",
    "firfox": "firefox", "fireofx": "firefox",
    "calucator": "calculator", "calcualtor": "calculator",
    "explroer": "explorer", "exploer": "explorer",
    "powershll": "powershell", "pwershell": "powershell",
    "wordapd": "wordpad", "wrordpad": "wordpad",
    "taskmanger": "taskmanager", "taskmgr": "taskmanager",
    "deskop": "desktop", "desktoop": "desktop", "desktpo": "desktop",
    "desktp": "desktop", "destop": "desktop", "dekstop": "desktop",
    "documants": "documents", "docuemnts": "documents", "documets": "documents",
    "documts": "documents", "docments": "documents", "docmnts": "documents",
    "downlods": "downloads", "downlaods": "downloads", "dowloads": "downloads",
    "picutres": "pictures", "pictrues": "pictures", "pictres": "pictures",
    "muscic": "music", "musci": "music",
    "vdieos": "videos", "vidoes": "videos",
    "prograsm": "programs", "porgramfiles": "program files",
    "pytohn": "python", "pyhon": "python", "pyton": "python",
    "javascirpt": "javascript", "javasript": "javascript",
    "gti": "git", "gitt": "git",
    "npn": "npm", "nmp": "npm",
    "pyhton": "python",
    "winegt": "winget", "wingett": "winget",
    "requirments": "requirements", "requierments": "requirements",
    "fil": "file", "fle": "file", "foder": "folder", "foldr": "folder",
    "nmaed": "named", "naemd": "named", "caleld": "called",
}

WINDOWS_PATHS = [
    "Desktop", "Documents", "Downloads", "Pictures", "Music",
    "Videos", "AppData", "Program Files", "Program Files (x86)",
    "Users", "Windows", "System32", "Temp", "OneDrive",
]

COMMON_COMMANDS = [
    "install", "uninstall", "create", "delete", "open", "launch",
    "run", "execute", "download", "search", "make", "build",
    "move", "copy", "rename", "update", "upgrade", "configure",
    "enable", "disable", "start", "stop", "close", "quit",
]

VALID_EXTENSIONS = {
    ".txt": ["text", "note", "notes", "plain"],
    ".md": ["markdown", "readme"],
    ".pdf": ["pdf", "document"],
    ".docx": ["word", "document", "doc"],
    ".doc": ["word", "document"],
    ".xlsx": ["excel", "spreadsheet", "sheet"],
    ".csv": ["data", "table", "csv"],
    ".json": ["json", "data", "config"],
    ".xml": ["xml", "data", "config"],
    ".yaml": ["config", "settings"],
    ".yml": ["config", "settings"],
    ".py": ["python", "script", "code"],
    ".js": ["javascript", "script", "node"],
    ".ts": ["typescript", "script"],
    ".html": ["web", "page", "html"],
    ".css": ["style", "css"],
    ".bat": ["batch", "windows", "script"],
    ".ps1": ["powershell", "script"],
    ".sh": ["bash", "shell", "script"],
    ".png": ["image", "picture", "screenshot"],
    ".jpg": ["image", "photo"],
    ".jpeg": ["image", "photo"],
    ".zip": ["archive", "compressed"],
    ".log": ["log", "output"],
    ".env": ["environment", "config", "secrets"],
    ".ini": ["config", "settings"],
}

TYPO_MAP = {
    ".pf":     [".pdf", ".py"],
    ".pd":     [".pdf"],
    ".pfd":    [".pdf"],
    ".tx":     [".txt"],
    ".text":   [".txt"],
    ".doc":    [".docx"],
    ".xls":    [".xlsx"],
    ".exel":   [".xlsx"],
    ".xlxs":   [".xlsx"],
    ".jason":  [".json"],
    ".jsn":    [".json"],
    ".phyton": [".py"],
    ".python": [".py"],
    ".pyt":    [".py"],
    ".htm":    [".html"],
    ".yam":    [".yaml"],
    ".phyon":  [".py"],
    ".jso":    [".json"],
}

ALL_EXTENSIONS = list(VALID_EXTENSIONS.keys())
SKIP_CORRECTION_WORDS = frozenset({
    "yes", "no", "ok", "okay", "go ahead", "cancel", "stop", "proceed",
    "confirm", "do it", "sure", "yep", "nope", "override", "abort",
    "wait", "hold on", "thanks", "thank you", "bye",
    "authorize protocol aletheia", "lock protocol", "revert to iris",
})
FAST_ACTION_PREFIXES = (
    "open ", "create ", "make ", "delete ", "run ", "launch ", "play ",
    "search ", "find ", "write ", "rename ", "move ", "copy ",
)


class AutoCorrector:

    def __init__(self, brain=None):
        self.brain = brain

    def correct_input(self, text: str) -> tuple:
        normalized = (text or "").strip()
        lowered = normalized.lower()
        if not normalized or len(normalized) < 8:
            return text, None
        if lowered in SKIP_CORRECTION_WORDS:
            return text, None
        if any(lowered.startswith(prefix) for prefix in FAST_ACTION_PREFIXES) and len(normalized) < 40:
            return text, None

        words = text.split()
        corrected = []
        changes = []
        for word in words:
            fixed, original = self._correct_word(word)
            corrected.append(fixed)
            if fixed.lower() != original.lower():
                changes.append(f"'{original}' → '{fixed}'")
        corrected_text = " ".join(corrected)
        note = f"Auto-corrected: {', '.join(changes)}." if changes else None
        return corrected_text, note

    def correct_path(self, path: str) -> tuple:
        if not path:
            return path, None
        parts = re.split(r"([\\/])", path)
        fixed_parts = []
        changes = []
        for part in parts:
            if part in ("\\", "/") or not part:
                fixed_parts.append(part)
                continue
            fixed = self._correct_path_component(part)
            if fixed != part:
                changes.append(f"'{part}' → '{fixed}'")
            fixed_parts.append(fixed)
        corrected = "".join(fixed_parts)
        note = f"Path corrected: {', '.join(changes)}." if changes else None
        return corrected, note

    def correct_extension(
        self, filename: str, context: str = ""
    ) -> Tuple[str, Optional[str], bool, List[str]]:
        """
        Cognitively correct file extensions.
        Returns: (corrected_filename, note, needs_clarification, options)
        """
        if not filename:
            return filename, None, False, []

        context = (context or "").lower().strip()
        root, ext = os.path.splitext(filename)
        ext = ext.lower()

        # No extension — infer from context
        if not ext:
            inferred = self._infer_extension(context)
            return f"{filename}{inferred}", f"No extension — using '{inferred}'.", False, []

        # Already valid
        if ext in VALID_EXTENSIONS:
            return filename, None, False, []

        # Known typo map
        if ext in TYPO_MAP:
            options = TYPO_MAP[ext]
            if len(options) == 1:
                return f"{root}{options[0]}", f"'{ext}' → '{options[0]}'", False, []
            # Resolve from context
            if ".py" in options and any(w in context for w in ["python", "script", "code"]):
                return f"{root}.py", f"'{ext}' → '.py'", False, []
            if ".pdf" in options and any(w in context for w in ["pdf", "document"]):
                return f"{root}.pdf", f"'{ext}' → '.pdf'", False, []
            return filename, None, True, options  # ask user

        # Fuzzy match
        matches = difflib.get_close_matches(ext, ALL_EXTENSIONS, n=1, cutoff=0.72)
        if matches:
            return f"{root}{matches[0]}", f"'{ext}' → '{matches[0]}'", False, []

        return filename, None, False, []

    def _infer_extension(self, context: str) -> str:
        if any(w in context for w in ["pdf", "document pdf"]):
            return ".pdf"
        if any(w in context for w in ["word", "docx"]):
            return ".docx"
        if any(w in context for w in ["excel", "spreadsheet", "sheet"]):
            return ".xlsx"
        if any(w in context for w in ["python", "script", "code"]):
            return ".py"
        if any(w in context for w in ["json", "config"]):
            return ".json"
        if any(w in context for w in ["markdown", "readme"]):
            return ".md"
        if any(w in context for w in ["csv", "table", "data"]):
            return ".csv"
        return ".txt"

    def _correct_word(self, word: str) -> tuple:
        original = word
        clean = re.sub(r"[^a-zA-Z]", "", word).lower()
        if len(clean) < 3:
            return word, original
        if clean in WORD_CORRECTIONS:
            corrected = WORD_CORRECTIONS[clean]
            if word[0].isupper():
                corrected = corrected.capitalize()
            return corrected, original
        all_known = list(WORD_CORRECTIONS.values()) + COMMON_COMMANDS
        matches = difflib.get_close_matches(clean, all_known, n=1, cutoff=0.82)
        if matches:
            corrected = matches[0]
            if word[0].isupper():
                corrected = corrected.capitalize()
            if corrected.lower() != clean:
                return corrected, original
        return word, original

    def _correct_path_component(self, component: str) -> str:
        clean = component.lower()
        if clean in WORD_CORRECTIONS:
            corrected = WORD_CORRECTIONS[clean]
            if component[0].isupper():
                corrected = corrected.capitalize()
            return corrected
        matches = difflib.get_close_matches(component, WINDOWS_PATHS, n=1, cutoff=0.75)
        if matches:
            return matches[0]
        return component

    def ai_correct(self, text: str) -> Optional[str]:
        if not self.brain:
            return None
        prompt = (
            f'The user typed this command but it may have typos: "{text}"\n'
            f"Return the corrected version, or the original if it's fine. "
            f"Return ONLY the text, nothing else."
        )
        try:
            response = self.brain._call_api("groq", prompt)
            return response.strip() if response else None
        except Exception:
            return None
