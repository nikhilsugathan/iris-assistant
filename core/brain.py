import ollama
import requests
import re
from core import logger, console

class Brain:
    def __init__(self, memory=None, model="phi3.5"):
        self.memory = memory if memory else []
        self.model = model if isinstance(model, str) else "phi3.5"
        self.available_apis = ["weather", "system_control", "diagnostics"]
        self.weather_api_key = "YOUR_OPENWEATHERMAP_API_KEY_HERE"

    def _detect_mood(self, user_input):
        ui = user_input.lower()
        if any(w in ui for w in ["urgent", "quick", "fast", "emergency"]): return "urgent"
        if any(w in ui for w in ["weather", "relax", "night", "slow"]): return "calm"
        return "normal"

    def get_weather(self, user_input):
        if not self.weather_api_key or "YOUR_" in self.weather_api_key:
            return "Weather tool active. Please provide an API key in brain.py."
        
        match = re.search(r"(?:in|for|at)\s+([a-zA-Z\s]+)", user_input, re.I)
        city = match.group(1).strip() if match else "New York"
        
        try:
            url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={self.weather_api_key}&units=imperial"
            res = requests.get(url, timeout=5).json()
            if res.get("cod") != 200: return f"I couldn't locate weather data for {city}."
            temp, desc = int(res['main']['temp']), res['weather'][0]['description']
            return f"The current weather in {city} is {temp} degrees with {desc}."
        except: return "Weather sensors are currently offline."

    def think(self, user_input, voice_engine=None, council_packet=None):
        mood = self._detect_mood(user_input)
        
        if "weather" in user_input.lower():
            report = self.get_weather(user_input)
            if voice_engine: voice_engine.speak(report, mood="calm")
            return report

        # Council Synthesis
        prompt_prefix = ""
        if council_packet and "responses" in council_packet:
            prompt_prefix = "The expert council suggests:\n"
            for m, r in council_packet["responses"].items():
                prompt_prefix += f"- {m}: {r}\n"
            prompt_prefix += "\nPlease synthesize a final response: "

        full_response = ""
        sentence_buffer = ""
        try:
            stream = ollama.chat(
                model=str(self.model),
                messages=[{'role': 'user', 'content': f"{prompt_prefix}{user_input}"}],
                stream=True,
            )

            console.print("[bold cyan]IRIS:[/bold cyan] ", end="")
            for chunk in stream:
                content = chunk['message']['content']
                print(content, end="", flush=True)
                full_response += content
                sentence_buffer += content

                if any(p in content for p in [".", "!", "?", "\n"]):
                    if voice_engine and sentence_buffer.strip():
                        voice_engine.speak(sentence_buffer.strip(), mood=mood)
                        sentence_buffer = "" 
            print()
            return full_response
        except Exception as e:
            logger.error(f"Brain Error: {e}")
            return "I encountered a cognitive processing error."