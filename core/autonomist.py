import json
import os
from datetime import datetime
from config import Config

class Autonomist:
    def __init__(self, brain):
        self.brain = brain
        self.kb_path = "knowledge_base.json"

    def learn_from_session(self, history_file: str):
        """Analyzes session logs to extract new facts and preferences."""
        if not os.path.exists(history_file):
            return

        with open(history_file, 'r', encoding='utf-8') as f:
            content = f.read()

        learning_prompt = f"""
        Analyze the following conversation history:
        ---
        {content[-4000:]} 
        ---
        Extract new facts about the user (Nikhil), the IRIS project, or coding preferences.
        Respond ONLY with a JSON object of key-value pairs. 
        Example: {{"user_preference": "prefers rich panels", "project_goal": "RTX 5050 optimization"}}
        """

        response = self.brain._call_api(Config.OLLAMA_MODEL_DEEP, learning_prompt)
        
        try:
            # Clean and parse JSON
            import re
            json_str = re.search(r"\{.*\}", response, re.DOTALL).group()
            new_knowledge = json.loads(json_str)
            self._update_kb(new_knowledge)
        except:
            pass

    def _update_kb(self, data: dict):
        kb = {}
        if os.path.exists(self.kb_path):
            with open(self.kb_path, 'r') as f: kb = json.load(f)
        
        kb.update(data)
        with open(self.kb_path, 'w') as f:
            json.dump(kb, f, indent=4)
```

---

### **3. Updating `main.py` (The Integration)**
We need to update `main.py` to initialize these new modules and add the routing for web searches and autonomous shutdown learning.

#### **Step A: Update Imports (Top of file)**
```python
from core.logic_engine import LogicalEngine
from tools.researcher import Researcher
from core.autonomist import Autonomist
```

#### **Step B: Initialize in `main()`**
Locate your module initialization block (around line 125) and add these:
```python
    # 2. Module Initialization
    # ... existing init ...
    logic_engine = LogicalEngine(brain)
    researcher = Researcher(brain)
    autonomist = Autonomist(brain)
```

#### **Step C: Update `handle_user_input` Routing**
Add the `search` mode and `analytical` triggers (around line 85):
```python
    # --- ROUTING LOGIC ---
    if decision.mode == "diagnostics":
        response = diagnostics.run(user_input, brain, voice, executor, copilot, brain.memory, self_model)
    elif decision.mode == "action":
        response = executor.plan_action(user_input)
    elif decision.mode == "search": # <--- NEW: RESEARCHER TRIGGER
        response = researcher.search(user_input)
    elif decision.mode == "action_pending":
        # ... existing handshake ...
        pass
    elif decision.analytical or decision.depth == "deep": # <--- NEW: LOGIC ENGINE TRIGGER
        response = logic_engine.reason(user_input, context=str(brain.memory.get_context(2)))
    else:
        # ... standard brain logic ...
```

#### **Step D: Trigger Learning on Shutdown**
Update the finalization block at the bottom of `main()`:
```python
    # 4. Shutdown & Finalization
    console.print("\n[bold cyan]IRIS:[/bold cyan] Running autonomous learning cycle...")
    try:
        # Pass the current session log to the autonomist
        autonomist.learn_from_session(logger.current_file) 
    except Exception: pass
    
    console.print("[bold cyan]IRIS:[/bold cyan] Terminating. Sanitizing memory...")
    logger.finalize()
    # ...