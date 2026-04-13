"""
IRIS Weather Tool — OpenWeatherMap integration (v1.1)
=======================================================
Provides real-time weather data via OpenWeatherMap's free APIs.
Used by handle_user_input() in main.py when weather keywords are detected.

Requires OPENWEATHER_API_KEY in .env
"""
from __future__ import annotations

import re
import requests
from config import Config
from core import logger as _logger_mod

logger = _logger_mod.get_logger("Weather")

# Keyword patterns that should trigger the weather tool
WEATHER_KEYWORDS = (
    "weather", "forecast", "temperature", "degrees",
    "rain", "sunny", "cloudy", "snow", "wind", "humidity",
    "hot outside", "cold outside", "how hot", "how cold",
    "what's it like outside", "what is it like outside",
)

_GEOCODE_URL = "http://api.openweathermap.org/geo/1.0/direct"
_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

# Indian state names → representative city (appended with ",IN" so OWM geocodes to
# the right country).  Without this, "Kerala" might resolve to an obscure village in
# another country returning the wrong temperature.
_INDIA_STATE_TO_CITY: dict[str, str] = {
    "andhra pradesh": "Visakhapatnam,IN",
    "arunachal pradesh": "Itanagar,IN",
    "assam": "Guwahati,IN",
    "bihar": "Patna,IN",
    "chhattisgarh": "Raipur,IN",
    "goa": "Panaji,IN",
    "gujarat": "Ahmedabad,IN",
    "haryana": "Chandigarh,IN",
    "himachal pradesh": "Shimla,IN",
    "jharkhand": "Ranchi,IN",
    "karnataka": "Bengaluru,IN",
    "kerala": "Thiruvananthapuram,IN",
    "madhya pradesh": "Bhopal,IN",
    "maharashtra": "Mumbai,IN",
    "manipur": "Imphal,IN",
    "meghalaya": "Shillong,IN",
    "mizoram": "Aizawl,IN",
    "nagaland": "Kohima,IN",
    "odisha": "Bhubaneswar,IN",
    "punjab": "Chandigarh,IN",
    "rajasthan": "Jaipur,IN",
    "sikkim": "Gangtok,IN",
    "tamil nadu": "Chennai,IN",
    "telangana": "Hyderabad,IN",
    "tripura": "Agartala,IN",
    "uttar pradesh": "Lucknow,IN",
    "uttarakhand": "Dehradun,IN",
    "west bengal": "Kolkata,IN",
    # Union territories & common aliases
    "delhi": "New Delhi,IN",
    "mumbai": "Mumbai,IN",
    "bangalore": "Bengaluru,IN",
    "bengaluru": "Bengaluru,IN",
    "bombay": "Mumbai,IN",
    "calcutta": "Kolkata,IN",
    "madras": "Chennai,IN",
    "trivandrum": "Thiruvananthapuram,IN",
    "kochi": "Kochi,IN",
    "cochin": "Kochi,IN",
    "hyderabad": "Hyderabad,IN",
    "chennai": "Chennai,IN",
    "kolkata": "Kolkata,IN",
}

# Pattern to extract city names from user queries
_CITY_RE = re.compile(
    r"(?:weather|forecast|temperature|degrees|climate)"
    r".*?(?:in|for|at|of)\s+([A-Za-z][a-zA-Z\s\-]{2,30}?)(?:\?|$|[,.]|\s+(?:now|today|tonight|tomorrow))",
    re.IGNORECASE,
)
_CITY_RE2 = re.compile(
    r"(?:in|for|at)\s+([A-Za-z][a-zA-Z\s\-]{2,30})(?:\?|$|[,.]|\s+(?:weather|forecast|temperature|now|today))",
    re.IGNORECASE,
)


def is_weather_query(text: str) -> bool:
    """Return True if the query is about weather."""
    t = text.lower()
    return any(kw in t for kw in WEATHER_KEYWORDS)


def extract_location(text: str) -> str | None:
    """Best-effort extraction of a city/region name from a weather query."""
    for pattern in (_CITY_RE, _CITY_RE2):
        m = pattern.search(text)
        if m:
            loc = m.group(1).strip().rstrip("?.,")
            if len(loc) >= 3:
                return loc
    # Fallback: look for "X weather" pattern
    m = re.search(r"([A-Za-z][a-zA-Z\s]{2,25}?)\s+weather", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _resolve_location(city: str) -> str:
    """
    Normalise a raw location string.
    Converts Indian state names to their representative city + country code so
    OWM geocoding doesn't match a random village with the same name abroad.
    """
    key = city.strip().lower()
    resolved = _INDIA_STATE_TO_CITY.get(key)
    if resolved:
        logger.debug(f"[Weather] Resolved '{city}' → '{resolved}'")
        return resolved
    return city


def _geocode(city: str) -> tuple[float, float, str, str] | None:
    """
    Return (lat, lon, display_name, country) for a city string.
    Fetches up to 5 candidates and prefers results whose country code matches
    a ",CC" suffix in the query (e.g. "Thiruvananthapuram,IN" → prefer IN).
    Returns None on failure.
    """
    api_key = getattr(Config, "OPENWEATHER_API_KEY", "")
    if not api_key:
        return None

    city = _resolve_location(city)

    # Extract explicit country code from "City,CC" format
    target_country: str | None = None
    query_city = city
    if "," in city:
        parts = city.split(",")
        cc = parts[-1].strip().upper()
        if len(cc) == 2 and cc.isalpha():
            target_country = cc
            query_city = parts[0].strip()

    try:
        resp = requests.get(
            _GEOCODE_URL,
            params={"q": city, "limit": 5, "appid": api_key},
            timeout=6,
        )
        data = resp.json()
        if not (data and isinstance(data, list)):
            return None

        candidates = data
        if target_country:
            preferred = [r for r in candidates if r.get("country", "").upper() == target_country]
            if preferred:
                candidates = preferred

        result = candidates[0]
        display = result.get("local_names", {}).get("en") or result["name"]
        return result["lat"], result["lon"], display, result.get("country", "")

    except Exception as exc:
        logger.debug(f"[Weather] Geocode error for {city!r}: {exc}")
        return None


def get_current_weather(location: str, units: str = "metric") -> str:
    """
    Fetch current weather for a location and return a concise spoken summary.
    Falls back gracefully on errors.
    """
    api_key = getattr(Config, "OPENWEATHER_API_KEY", "")
    if not api_key:
        return "I'd love to check the weather, but I don't have an API key set up."

    geo = _geocode(location)
    if not geo:
        return f"Couldn't find a place called '{location}' — double-check the spelling?"

    lat, lon, city_name, country = geo

    try:
        resp = requests.get(
            _WEATHER_URL,
            params={"lat": lat, "lon": lon, "appid": api_key, "units": units},
            timeout=8,
        )
        data = resp.json()
    except Exception as exc:
        logger.warning(f"[Weather] API error: {exc}")
        return "Weather lookup hit a snag — try again in a moment."

    if data.get("cod") != 200:
        return f"Weather data unavailable: {data.get('message', 'unknown error')}."

    unit_sym  = "°C" if units == "metric" else "°F"
    speed_unit = "m/s" if units == "metric" else "mph"
    desc      = data["weather"][0]["description"].capitalize() if data.get("weather") else "Unknown"
    temp      = round(data["main"]["temp"])
    feels     = round(data["main"]["feels_like"])
    humidity  = data["main"]["humidity"]
    wind      = round(data["wind"].get("speed", 0))
    location_str = f"{city_name}, {country}" if country else city_name

    return (
        f"{location_str}: {desc}. "
        f"{temp}{unit_sym}, feels like {feels}{unit_sym}. "
        f"Humidity {humidity}%, wind {wind} {speed_unit}."
    )


def get_forecast(location: str, units: str = "metric") -> str:
    """
    Return a brief 4-period forecast (every 3 hours from now).
    """
    api_key = getattr(Config, "OPENWEATHER_API_KEY", "")
    if not api_key:
        return "I'd love to give you a forecast, but I don't have an API key set up."

    geo = _geocode(location)
    if not geo:
        return f"Couldn't find a place called '{location}'."

    lat, lon, city_name, country = geo

    try:
        resp = requests.get(
            _FORECAST_URL,
            params={"lat": lat, "lon": lon, "appid": api_key, "units": units, "cnt": 8},
            timeout=8,
        )
        data = resp.json()
    except Exception as exc:
        logger.warning(f"[Weather] Forecast error: {exc}")
        return "Forecast lookup hit a snag."

    if data.get("cod") != "200":
        return f"Forecast unavailable: {data.get('message', 'unknown error')}."

    unit_sym = "°C" if units == "metric" else "°F"
    location_str = f"{city_name}, {country}" if country else city_name
    periods = data.get("list", [])[:4]
    if not periods:
        return f"No forecast data available for {location_str}."

    import datetime
    parts = []
    for p in periods:
        dt    = datetime.datetime.fromtimestamp(p["dt"])
        label = dt.strftime("%a %H:%M")
        t     = round(p["main"]["temp"])
        desc  = p["weather"][0]["description"] if p.get("weather") else "?"
        parts.append(f"{label}: {desc}, {t}{unit_sym}")

    return f"{location_str} forecast — " + " | ".join(parts) + "."
