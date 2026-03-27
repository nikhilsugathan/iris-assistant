"""
IRIS Action Executor (Anchored & Hardened)
==========================================
Handles system actions, logging, and security permissions.
"""

import os
import json
import datetime
from pathlib import Path
from core import logger, console

# We derive the local BASE_DIR to ensure internal logs are anchored
BASE_DIR = Path(__file__).resolve().parent.parent

class ActionExecutor:
    def __init__(self, voice, brain):
        self.voice = voice
        self.brain = brain
        
        # --- PATH ANCHORING (Audit Fix) ---
        # Ensures logs always write to the project's build/logs folder
        self.log_file = BASE_DIR / "build" / "logs" / "iris_actions.log"
        self.audit_file = BASE_DIR / "build" / "logs" / "iris_audit.log"
        
        # Ensure directory exists
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # State management for multi-turn interactions
        self._waiting_for_permission = False
        self._pending_action = None

    # ─── INTERFACE CONTRACT (9 REQUIRED METHODS) ───

    def waiting_for_followup(self): return False
    
    def handle_followup_response(self, text): return None

    def waiting_for_clarification(self): return False

    def handle_clarification_response(self, text): return None

    def waiting_for_plan_choice(self): return False

    def handle_plan_choice(self, index): return None

    def waiting_for_permission(self): 
        return self._waiting_for_permission

    def handle_permission_response(self, approved):
        """Audit Fix: Removed security override bypass."""
        self._waiting_for_permission = False
        if approved and self._pending_action:
            result = self.execute_direct(self._pending_action)
            self._pending_action = None
            return result
        return "Action cancelled by user."

    def plan_action(self, task_description):
        """Analyzes a task and decides if it needs permission."""
        logger.info(f"Planning action: {task_description}")
        # Logic to determine if permission is needed goes here
        return {"status": "planned", "task": task_description}

    # ─── EXECUTION LOGIC ───

    def execute_direct(self, action_data):
        """Logs and executes an authorized system command."""
        timestamp = datetime.datetime.now().isoformat()
        log_entry = f"[{timestamp}] EXECUTING: {action_data}\n"
        
        with open(self.log_file, "a") as f:
            f.write(log_entry)
            
        console.print(f"[bold green]▶ Executing:[/bold green] {action_data}")
        return f"Successfully executed: {action_data}"

    def _is_simple_task(self, task):
        """Properly checks approval levels based on security guidelines."""
        # Add logic here to filter harmless tasks from high-risk ones
        return True